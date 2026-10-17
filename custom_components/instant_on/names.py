"""Give clients useful names when Instant On only knows their MAC address.

Sources, best first: the Instant On name, a name another integration gave the device in Home Assistant,
mDNS (via Home Assistant's zeroconf cache), the DHCP hostname, reverse DNS, NetBIOS, and finally the MAC's
vendor from an offline copy of Wireshark's manufacturer database. MAC addresses are never sent anywhere:
the vendor database is downloaded whole and looked up locally.
"""
from __future__ import annotations

import asyncio
from dataclasses import asdict, dataclass, field
import gzip
import ipaddress
import logging
import os
import random
import re
import socket
import struct
import time
from typing import Any

import aiohttp
from homeassistant.core import HomeAssistant
from homeassistant.helpers import device_registry as dr
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.storage import Store

from .const import DOMAIN, client_mac

_LOGGER = logging.getLogger(__name__)

OUI_URL = "https://www.wireshark.org/download/automated/data/manuf.gz"
OUI_MAX_AGE = 30 * 86400
LOOKUP_EVERY = 6 * 3600  # per client
LOOKUP_CONCURRENCY = 8
LOOKUP_TIMEOUT = 2.0
SWEEP_EVERY = 3600
STORE_VERSION = 1

MAC_LIKE = re.compile(r"^([0-9a-f]{2}[:-]?){5}[0-9a-f]{2}$", re.IGNORECASE)

# Vendor keyword -> device kind, used for icons and the fallback name. First match wins.
KINDS = (
    ("speaker", ("sonos", "bose", "denon", "yamaha", "harman", "bang & olufsen", "devialet")),
    ("camera", ("reolink", "hikvision", "dahua", "axis comm", "amcrest", "wyze", "ring", "arlo", "ubiquiti")),
    ("printer", ("epson", "brother", "canon", "lexmark", "xerox", "kyocera", "ricoh", "hewlett packard", "hp inc")),
    ("tv", ("roku", "lg electronics", "vizio", "tcl", "hisense", "sony", "samsung")),
    ("console", ("nintendo", "sony interactive", "microsoft xbox", "valve")),
    ("apple", ("apple",)),
    ("phone", ("google", "oneplus", "xiaomi", "huawei", "motorola", "oppo")),
    ("computer", ("super micro", "supermicro", "asrock", "asustek", "gigabyte", "intel", "dell", "lenovo", "micro-star", "raspberry",
                  "10gtek", "mellanox", "aquantia", "synology", "qnap")),
    ("iot", ("espressif", "tuya", "shelly", "allterco", "sonoff", "itead", "withings", "ecobee", "nest", "philips lighting",
             "signify", "lutron", "wiz", "tp-link", "amazon", "fn-link", "quectel", "azurewave", "murata", "realtek", "silicon lab")),
)
MDNS_KIND = (
    ("_sonos._tcp", "speaker"), ("_airplay._tcp", "apple"), ("_ipp._tcp", "printer"), ("_ipps._tcp", "printer"),
    ("_printer._tcp", "printer"), ("_googlecast._tcp", "tv"), ("_hap._tcp", "iot"), ("_esphomelib._tcp", "iot"),
    ("_smb._tcp", "computer"), ("_ssh._tcp", "computer"), ("_rdlink._tcp", "apple"),
)


def is_mac_like(name: str | None) -> bool:
    return bool(name) and bool(MAC_LIKE.match(name.strip()))


def is_random_mac(mac: str) -> bool:
    """Locally administered (e.g. phones' private Wi-Fi addresses): no vendor to look up."""
    return bool(int(mac[:2], 16) & 0x02)


def kind_for(vendor: str | None, services: list[str] | None = None) -> str | None:
    # MDNS_KIND is in priority order: a Sonos also advertises AirPlay, but it's a speaker.
    for key, kind in MDNS_KIND:
        if any(svc.startswith(key) for svc in services or []):
            return kind
    v = (vendor or "").lower()
    for kind, words in KINDS:
        if any(w in v for w in words):
            return kind
    return None


def short_vendor(vendor: str | None) -> str | None:
    """'Sonos, Inc.' -> 'Sonos', 'Seiko Epson Corporation' -> 'Seiko Epson'."""
    if not vendor:
        return None
    v = re.split(r",|\(", vendor)[0]
    v = re.sub(r"\b(inc|ltd|llc|co|corp|corporation|company|limited|gmbh|technology|technologies|incorporation|innovation|"
               r"wireless solutions|solutions|transceivers|electronics|computer|shenzhen|international)\b\.?", "", v, flags=re.I)
    return re.sub(r"\s+", " ", v).strip(" .") or vendor


# --------------------------------------------------------------------------- OUI database
def parse_manuf(text: str) -> dict[str, str]:
    """Wireshark 'manuf': prefix<TAB>short<TAB>long. Prefixes are 24 bits, or /28 and /36 with a mask."""
    db: dict[str, str] = {}
    for line in text.splitlines():
        if not line.strip() or line.startswith("#"):
            continue
        parts = [p.strip() for p in line.split("\t")]
        if len(parts) < 2:
            continue
        prefix, bits = parts[0], 24
        if "/" in prefix:
            prefix, b = prefix.split("/", 1)
            bits = int(b)
        hexs = prefix.replace(":", "").replace("-", "").lower()[: bits // 4]
        db[hexs] = parts[2] if len(parts) > 2 and parts[2] else parts[1]
    return db


def vendor_for(db: dict[str, str], mac: str) -> str | None:
    h = mac.replace(":", "").lower()
    return db.get(h[:9]) or db.get(h[:7]) or db.get(h[:6])


# --------------------------------------------------------------------------- network lookups (blocking)
def arp_table() -> dict[str, str]:
    """MAC -> IP from the host's neighbour table."""
    out: dict[str, str] = {}
    try:
        with open("/proc/net/arp", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if len(p) >= 4 and p[2] != "0x0" and p[3] != "00:00:00:00:00:00":
                    out[p[3].lower()] = p[0]
    except OSError:
        pass
    return out


def reverse_dns(ip: str) -> str | None:
    try:
        name = socket.gethostbyaddr(ip)[0]
    except (OSError, UnicodeError):
        return None
    return None if name == ip else name


def netbios_name(ip: str) -> str | None:
    """NetBIOS node status query (UDP 137): the machine's workstation name, if it answers."""
    tid = random.randint(0, 65535)
    query = struct.pack(">HHHHHH", tid, 0, 1, 0, 0, 0) + b"\x20" + b"CK" + b"AA" * 15 + b"\x00" + struct.pack(">HH", 0x21, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(1.0)
    try:
        sock.sendto(query, (ip, 137))
        data = sock.recv(2048)
    except OSError:
        return None
    finally:
        sock.close()
    try:
        # Header (12) + echoed name (34) + type/class/ttl/rdlength (10) + count (1), then 18-byte entries.
        count = data[56]
        for i in range(count):
            entry = data[57 + 18 * i : 57 + 18 * (i + 1)]
            name, suffix, flags = entry[:15].decode("ascii", "replace").strip(), entry[15], entry[16]
            if suffix == 0x00 and not flags & 0x80:  # unique workstation name, not a group
                return name or None
    except IndexError:
        return None
    return None


def local_subnets() -> list[ipaddress.IPv4Network]:
    """IPv4 networks of the host's default-route interface (/proc/net/route), capped at /24."""
    nets = []
    try:
        with open("/proc/net/route", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if p[1] != "00000000" and int(p[3], 16) & 1 and p[2] == "00000000":
                    net = socket.inet_ntoa(struct.pack("<L", int(p[1], 16)))
                    mask = socket.inet_ntoa(struct.pack("<L", int(p[7], 16)))
                    n = ipaddress.ip_network(f"{net}/{mask}", strict=False)
                    if n.prefixlen >= 24 and not n.is_loopback and not str(n).startswith(("172.17.", "172.30.", "172.31.")):
                        nets.append(n)
    except (OSError, ValueError):
        pass
    return nets


def sweep(nets: list[ipaddress.IPv4Network]) -> int:
    """Send one tiny UDP packet to every address so the kernel ARPs them and fills the neighbour table."""
    sent = 0
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        for net in nets:
            for host in net.hosts():
                try:
                    sock.sendto(b"", (str(host), 9))  # discard port
                    sent += 1
                except OSError:
                    pass
    finally:
        sock.close()
    return sent


# --------------------------------------------------------------------------- resolver
@dataclass
class ClientInfo:
    vendor: str | None = None
    kind: str | None = None
    random_mac: bool = False
    ip: str | None = None
    ha_name: str | None = None
    mdns: str | None = None
    mdns_services: list[str] = field(default_factory=list)
    dhcp: str | None = None
    rdns: str | None = None
    netbios: str | None = None
    checked: float = 0.0


class ClientNamer:
    """Resolves and caches names per MAC. Lookups run in the background and never block a poll."""

    def __init__(self, hass: HomeAssistant, active_sweep: bool = False, on_update=None) -> None:
        self.hass = hass
        self._on_update = on_update
        self.active_sweep = active_sweep
        self.info: dict[str, ClientInfo] = {}
        self._oui: dict[str, str] = {}
        self._store: Store = Store(hass, STORE_VERSION, f"{DOMAIN}.client_names")
        self._oui_path = hass.config.path(".storage", f"{DOMAIN}.manuf.gz")
        self._task: asyncio.Task | None = None
        self._last_sweep = 0.0

    async def async_load(self) -> None:
        if data := await self._store.async_load():
            for mac, raw in data.get("clients", {}).items():
                try:
                    self.info[mac] = ClientInfo(**raw)
                except TypeError:
                    continue
        await self._load_oui()

    async def _load_oui(self) -> None:
        def read() -> tuple[str | None, float]:
            try:
                with gzip.open(self._oui_path, "rt", encoding="utf-8", errors="replace") as f:
                    return f.read(), os.path.getmtime(self._oui_path)
            except OSError:
                return None, 0.0

        text, mtime = await self.hass.async_add_executor_job(read)
        if text is None or time.time() - mtime > OUI_MAX_AGE:
            try:
                session = async_get_clientsession(self.hass)
                async with session.get(OUI_URL, timeout=aiohttp.ClientTimeout(total=60)) as resp:
                    resp.raise_for_status()
                    raw = await resp.read()

                def write() -> str:
                    with open(self._oui_path, "wb") as f:
                        f.write(raw)
                    return gzip.decompress(raw).decode("utf-8", "replace")

                text = await self.hass.async_add_executor_job(write)
            except (aiohttp.ClientError, TimeoutError, OSError) as err:
                _LOGGER.info("Couldn't download the MAC vendor database (%s); using the cached copy if any", err)
        if text:
            self._oui = await self.hass.async_add_executor_job(parse_manuf, text)

    # ------------------------------------------------------------------ public API
    def schedule(self, clients: list[dict[str, Any]]) -> None:
        """Start a background refresh unless one is still running."""
        if self._task and not self._task.done():
            return
        self._task = self.hass.async_create_background_task(self._refresh(clients), f"{DOMAIN} client names")

    def label(self, client: dict[str, Any]) -> dict[str, Any]:
        """Best display name plus everything known about this client."""
        mac = client_mac(client) or ""
        info = self.info.get(mac) or ClientInfo(vendor=vendor_for(self._oui, mac) if mac else None)
        candidates = (
            ("instant_on", client.get("name")),
            ("home_assistant", info.ha_name),
            ("mdns", info.mdns),
            ("dhcp", client.get("hostName") or info.dhcp),
            ("dns", info.rdns),
            ("netbios", info.netbios),
        )
        name, source = None, None
        for src, val in candidates:
            if val and not is_mac_like(val):
                name, source = val, src
                break
        if not name:
            tail = mac[-8:] if mac else ""
            if info.random_mac:
                name, source = f"Private address · {tail}", "random_mac"
            elif info.vendor:
                name, source = f"{short_vendor(info.vendor)} · {tail}", "vendor"
            else:
                name, source = mac or "Unknown", "mac"
        return {
            "name": name,
            "source": source,
            "vendor": short_vendor(info.vendor),
            "kind": info.kind or kind_for(info.vendor, info.mdns_services),
            "random_mac": info.random_mac,
            "ip": client.get("ipAddress") or info.ip,
            "hostnames": {k: v for k, v in (("mdns", info.mdns), ("dhcp", client.get("hostName") or info.dhcp),
                                            ("dns", info.rdns), ("netbios", info.netbios)) if v and not is_mac_like(v)},
        }

    def as_dict(self) -> dict[str, Any]:
        return {mac: asdict(i) for mac, i in self.info.items()}

    # ------------------------------------------------------------------ refresh
    async def _refresh(self, clients: list[dict[str, Any]]) -> None:
        now = time.time()
        if self.active_sweep and now - self._last_sweep > SWEEP_EVERY:
            nets = await self.hass.async_add_executor_job(local_subnets)
            if nets:
                sent = await self.hass.async_add_executor_job(sweep, nets)
                _LOGGER.debug("Subnet sweep: %s packets to %s", sent, nets)
                await asyncio.sleep(3)  # let ARP replies land
            self._last_sweep = now
        arp, dhcp, mdns, ha_names = await asyncio.gather(
            self.hass.async_add_executor_job(arp_table), self._dhcp_data(), self._mdns_data(), self._ha_device_names()
        )
        sem = asyncio.Semaphore(LOOKUP_CONCURRENCY)

        async def one(client: dict[str, Any]) -> None:
            mac = client_mac(client)
            if not mac:
                return
            info = self.info.setdefault(mac, ClientInfo())
            info.random_mac = is_random_mac(mac)
            info.vendor = None if info.random_mac else vendor_for(self._oui, mac)
            info.ha_name = ha_names.get(mac)
            d = dhcp.get(mac.replace(":", "")) or dhcp.get(mac) or {}
            info.dhcp = d.get("hostname") or info.dhcp
            info.ip = client.get("ipAddress") or d.get("ip") or arp.get(mac) or info.ip
            # mDNS: by IP, or by the MAC embedded in the hostname (Sonos-48A6B8xxxxxx, shelly1-AABBCC…).
            flat = mac.replace(":", "")
            tail_hits = [c for c in clients if (client_mac(c) or "").replace(":", "")[-6:] == flat[-6:]]
            m = (
                (mdns["by_ip"].get(info.ip) if info.ip else None)
                or mdns["by_mac"].get(flat)
                # last-6 match only when no other client shares those digits
                or (mdns["by_tail"].get(flat[-6:]) if len(tail_hits) == 1 else None)
            )
            if m:
                info.mdns, info.mdns_services = m["name"], m["services"]
                info.ip = info.ip or m.get("ip")
            info.kind = kind_for(info.vendor, info.mdns_services)
            if info.ip and now - info.checked > LOOKUP_EVERY:
                async with sem:
                    info.rdns, info.netbios = await asyncio.gather(
                        self._timed(reverse_dns, info.ip), self._timed(netbios_name, info.ip)
                    )
                info.checked = now

        await asyncio.gather(*(one(c) for c in clients))
        await self._store.async_save({"clients": self.as_dict()})
        if self._on_update:
            self._on_update()

    async def _timed(self, fn, *args):
        try:
            return await asyncio.wait_for(self.hass.async_add_executor_job(fn, *args), LOOKUP_TIMEOUT)
        except (TimeoutError, OSError):
            return None

    async def _dhcp_data(self) -> dict[str, dict[str, str]]:
        """MAC -> {ip, hostname} that Home Assistant's DHCP watcher has seen (internal API; optional)."""
        try:
            from homeassistant.components import dhcp

            data = dhcp.async_get_address_data_internal(self.hass)
        except (ImportError, AttributeError, KeyError):
            return {}
        out = {}
        for mac, entry in (data or {}).items():
            get = entry.get if isinstance(entry, dict) else lambda k, e=entry: getattr(e, k, None)
            out[str(mac).lower()] = {"ip": get("ip"), "hostname": get("hostname")}
        return out

    async def _mdns_data(self) -> dict[str, dict[str, Any]]:
        """Names from Home Assistant's zeroconf cache: by IP, and by MAC found inside the hostname."""
        by_ip: dict[str, dict[str, Any]] = {}
        by_mac: dict[str, dict[str, Any]] = {}
        by_tail: dict[str, list[dict[str, Any]]] = {}
        try:
            from homeassistant.components import zeroconf
            from zeroconf import DNSAddress, DNSService

            aiozc = await zeroconf.async_get_async_instance(self.hass)
            records = [r for entries in list(aiozc.zeroconf.cache.cache.values()) for r in list(entries)]
        except Exception as err:  # optional source, and zeroconf's internals vary between versions
            _LOGGER.debug("mDNS cache unavailable: %s", err)
            return {"by_ip": by_ip, "by_mac": by_mac, "by_tail": {}}
        host_ip: dict[str, str] = {}
        host_services: dict[str, list[tuple[str, str]]] = {}
        for r in records:
            if isinstance(r, DNSAddress) and len(r.address) == 4:
                host_ip[r.name.lower()] = socket.inet_ntoa(r.address)
            elif isinstance(r, DNSService):
                instance, _, svc = r.name.partition("._")
                host_services.setdefault(r.server.lower(), []).append((instance, "_" + svc))
        for host, ip in host_ip.items():
            svcs = host_services.get(host, [])
            # Friendlier instance names first (e.g. "Kitchen" for Sonos is "RINCON_xxx@Kitchen").
            names = [i.split("@")[-1] for i, _ in svcs if i]
            name = (names[0] if names else host.removesuffix(".local.").removesuffix(".local"))
            entry = {"name": name, "services": sorted({s for _, s in svcs}), "ip": ip}
            by_ip[ip] = entry
            flat = host.replace("-", "")
            for m in re.findall(r"[0-9a-f]{12}", flat):
                by_mac[m] = entry
            # Many devices use only the MAC's last 6 hex digits (e.g. HP64500D.local).
            for m in set(re.findall(r"(?=([0-9a-f]{6}))", flat.split(".")[0])):
                by_tail.setdefault(m, []).append(entry)
        return {"by_ip": by_ip, "by_mac": by_mac, "by_tail": {k: v[0] for k, v in by_tail.items() if len(v) == 1}}

    async def _ha_device_names(self) -> dict[str, str]:
        """Names other integrations gave devices with a MAC connection (ignores bare-MAC names and our own)."""
        out = {}
        for dev in dr.async_get(self.hass).devices:  # iterating yields entries
            if isinstance(dev, str):  # older Home Assistant: iterating gives ids
                dev = dr.async_get(self.hass).async_get(dev)
            if dev is None:
                continue
            if any(domain == DOMAIN for domain, _ in dev.identifiers):
                continue
            name = dev.name_by_user or dev.name
            if not name or is_mac_like(name):
                continue
            for kind, val in dev.connections:
                if kind == dr.CONNECTION_NETWORK_MAC:
                    out[dr.format_mac(val)] = name
        return out
