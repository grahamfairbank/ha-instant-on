"""Internet health: latency, jitter, loss, DNS, HTTPS, speed tests and the HA host's own link speed.

Runs on the Home Assistant host, independent of Instant On. ICMP ping usually isn't available to Home
Assistant (no raw sockets), so latency is measured as TCP connect time to well-known anycast resolvers.
"""
from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from itertools import pairwise
import logging
import os
import random
import socket
import struct
import time
from typing import Any

import aiohttp
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.event import async_call_later, async_track_time_interval
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator

from .const import CONF_SPEEDTEST_HOURS, DEFAULT_SPEEDTEST_HOURS, DOMAIN

_LOGGER = logging.getLogger(__name__)

INTERVAL = timedelta(seconds=30)
TARGETS = {"cloudflare": ("1.1.1.1", 443), "google": ("8.8.8.8", 443)}
SAMPLES = 5
CONNECT_TIMEOUT = 2.0
TRACE_EVERY = 600
SPEEDTEST_COOLDOWN = 300
SPEED_DOWN_BYTES = 25_000_000
SPEED_UP_BYTES = 8_000_000
SPEED_STREAMS = 4
# A sample is degraded above this latency or loss, and down when every target fails.
DEGRADED_MS = 80.0
DEGRADED_LOSS = 10.0
# Results this close to the host's own link speed are probably limited by the host, not the internet.
LINK_CAP_RATIO = 0.85

STATES = ("down", "degraded", "healthy")
VIRTUAL_DRIVERS = {"virtio_net", "vmxnet3", "hv_netvsc", "xen-netfront", "veth", "vif"}


async def _tcp_ping(host: str, port: int) -> dict[str, Any]:
    """Average TCP connect time, jitter and loss over a few samples."""
    times: list[float] = []
    for _ in range(SAMPLES):
        start = time.perf_counter()
        try:
            _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), CONNECT_TIMEOUT)
            times.append((time.perf_counter() - start) * 1000)
            writer.close()
        except (TimeoutError, OSError):
            pass
        await asyncio.sleep(0.1)
    loss = round(100 * (SAMPLES - len(times)) / SAMPLES, 1)
    if not times:
        return {"ms": None, "jitter": None, "loss": 100.0}
    jitter = sum(abs(a - b) for a, b in pairwise(times)) / max(1, len(times) - 1)
    return {"ms": round(sum(times) / len(times), 1), "jitter": round(jitter, 1), "loss": loss}


def _dns_query(server: str, name: str = "www.google.com") -> float | None:
    """One raw UDP A query; round-trip ms, or None on failure. Blocking: run in the executor."""
    tid = random.randint(0, 65535)
    query = struct.pack(">HHHHHH", tid, 0x0100, 1, 0, 0, 0)
    query += b"".join(bytes([len(p)]) + p.encode() for p in name.split(".")) + b"\0" + struct.pack(">HH", 1, 1)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.settimeout(2)
    try:
        start = time.perf_counter()
        sock.sendto(query, (server, 53))
        while True:
            data = sock.recv(1500)
            if data[:2] == query[:2]:
                return round((time.perf_counter() - start) * 1000, 1) if data[3] & 0x0F == 0 else None
    except OSError:
        return None
    finally:
        sock.close()


def _system_resolver() -> str | None:
    try:
        with open("/etc/resolv.conf", encoding="utf-8") as f:
            for line in f:
                parts = line.split()
                if len(parts) >= 2 and parts[0] == "nameserver" and "." in parts[1]:
                    return parts[1]
    except OSError:
        pass
    return None


def host_link() -> dict[str, Any]:
    """The HA host's default-route interface and its negotiated speed. Blocking: run in the executor.

    Reads /proc/net/route and /sys/class/net. On Home Assistant OS the core container shares the host's
    network namespace, so this is the real NIC. Wi-Fi and some virtual NICs don't report a speed.
    """
    iface = None
    try:
        with open("/proc/net/route", encoding="utf-8") as f:
            for line in f.readlines()[1:]:
                p = line.split()
                if p[1] == "00000000" and int(p[3], 16) & 2:
                    iface = p[0]
                    break
    except OSError:
        return {"iface": None, "speed": None, "kind": None}
    if not iface:
        return {"iface": None, "speed": None, "kind": None}
    base = f"/sys/class/net/{iface}"
    kind = "wifi" if os.path.isdir(f"{base}/wireless") or os.path.isdir(f"{base}/phy80211") else "ethernet"
    speed = None
    try:
        with open(f"{base}/speed", encoding="utf-8") as f:
            val = int(f.read().strip())
            speed = val if val > 0 else None
    except (OSError, ValueError):
        pass
    if kind == "ethernet":
        # A VM's NIC reports a nominal speed (often 10 Gb/s); the physical host's port is the real limit.
        driver = os.path.basename(os.path.realpath(f"{base}/device/driver")) if os.path.exists(f"{base}/device/driver") else None
        if driver is None or driver in VIRTUAL_DRIVERS:
            kind = "virtual"
    return {"iface": iface, "speed": speed, "kind": kind}


class InternetCoordinator(TimestampDataUpdateCoordinator[dict[str, Any]]):
    """Probes internet health every 30 s and runs speed tests on a schedule."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(hass, _LOGGER, config_entry=entry, name=f"{DOMAIN}_internet", update_interval=INTERVAL)
        # Own session: speed tests open several parallel connections and shouldn't share a pool.
        self.session = async_create_clientsession(hass)
        self.trace: dict[str, str] = {}
        self._trace_at = 0.0
        self.link: dict[str, Any] = {}
        self.speed: dict[str, Any] | None = None  # last result: down/up bit/s, ms, at (iso), capped
        self.speed_running = False
        self._speed_lock = asyncio.Lock()
        self._last_speed = 0.0
        self.outage_since: str | None = None

    @callback
    def async_start_schedule(self) -> None:
        hours = self.config_entry.options.get(CONF_SPEEDTEST_HOURS, DEFAULT_SPEEDTEST_HOURS)
        if hours:
            self.config_entry.async_on_unload(
                async_track_time_interval(self.hass, self._scheduled_speedtest, timedelta(hours=hours))
            )
            # First result shortly after start-up rather than hours later.
            self.config_entry.async_on_unload(async_call_later(self.hass, 120, self._scheduled_speedtest))

    async def _scheduled_speedtest(self, _now: datetime) -> None:
        await self.async_run_speedtest()

    async def _trace(self) -> None:
        try:
            async with self.session.get("https://1.1.1.1/cdn-cgi/trace", timeout=aiohttp.ClientTimeout(total=5)) as resp:
                text = await resp.text()
            self.trace = dict(line.split("=", 1) for line in text.splitlines() if "=" in line)
            self._trace_at = time.monotonic()
        except (TimeoutError, aiohttp.ClientError):
            pass

    async def _https(self) -> float | None:
        start = time.perf_counter()
        try:
            # "Connection: close" means the next check opens a fresh connection, so the figure includes
            # TCP and TLS setup like a real page load.
            async with self.session.get(
                "https://www.google.com/generate_204", headers={"Connection": "close"}, timeout=aiohttp.ClientTimeout(total=5)
            ) as resp:
                if resp.status >= 400:
                    return None
            return round((time.perf_counter() - start) * 1000, 1)
        except (TimeoutError, aiohttp.ClientError):
            return None

    async def _async_update_data(self) -> dict[str, Any]:
        resolver = await self.hass.async_add_executor_job(_system_resolver)
        cf, google, https, dns_cf, dns_sys, link = await asyncio.gather(
            _tcp_ping(*TARGETS["cloudflare"]),
            _tcp_ping(*TARGETS["google"]),
            self._https(),
            self.hass.async_add_executor_job(_dns_query, "1.1.1.1"),
            self.hass.async_add_executor_job(_dns_query, resolver) if resolver else asyncio.sleep(0, None),
            self.hass.async_add_executor_job(host_link),
        )
        self.link = link
        if cf["ms"] is None and google["ms"] is None and https is None:
            state = 0
        elif max(cf["loss"], google["loss"]) >= DEGRADED_LOSS or (cf["ms"] or 0) > DEGRADED_MS or https is None:
            state = 1
        else:
            state = 2
        now = datetime.now(UTC).isoformat()
        if state == 0 and self.outage_since is None:
            self.outage_since = now
        elif state > 0:
            self.outage_since = None
        if state > 0 and time.monotonic() - self._trace_at > TRACE_EVERY:
            await self._trace()
        best = min((t for t in (cf, google) if t["ms"] is not None), key=lambda t: t["ms"], default=cf)
        return {
            "state": STATES[state],
            "latency": best["ms"],
            "jitter": best["jitter"],
            "loss": max(cf["loss"], google["loss"]),
            "cloudflare": cf,
            "google": google,
            "dns": dns_sys if dns_sys is not None else dns_cf,
            "dns_cloudflare": dns_cf,
            "dns_resolver": resolver,
            "https": https,
            "outage_since": self.outage_since,
            "ip": self.trace.get("ip"),
            "colo": self.trace.get("colo"),
            "loc": self.trace.get("loc"),
        }

    # ------------------------------------------------------------------ speed test
    async def async_run_speedtest(self, force: bool = False) -> bool:
        """Run a speed test unless one is running or ran in the last few minutes. Returns True if started."""
        if self._speed_lock.locked() or (not force and time.monotonic() - self._last_speed < SPEEDTEST_COOLDOWN):
            return False
        async with self._speed_lock:
            self.speed_running = True
            self.async_update_listeners()
            try:
                self.speed = await self._speedtest()
                _LOGGER.debug("Speed test: %s", self.speed)
            except (TimeoutError, aiohttp.ClientError) as err:
                _LOGGER.warning("Speed test failed: %s", err)
            finally:
                self._last_speed = time.monotonic()
                self.speed_running = False
                self.async_update_listeners()
        return True

    async def _speedtest(self) -> dict[str, Any]:
        """Cloudflare speed test: idle latency, then parallel downloads, then parallel uploads."""
        timeout = aiohttp.ClientTimeout(total=60)
        base = "https://speed.cloudflare.com"
        start = time.perf_counter()
        async with self.session.get(f"{base}/__down?bytes=0", timeout=timeout) as resp:
            await resp.read()
        latency = round((time.perf_counter() - start) * 1000, 1)

        async def down() -> int:
            total = 0
            async with self.session.get(f"{base}/__down?bytes={SPEED_DOWN_BYTES // SPEED_STREAMS}", timeout=timeout) as resp:
                async for chunk in resp.content.iter_chunked(65536):
                    total += len(chunk)
            return total

        async def up() -> int:
            data = os.urandom(SPEED_UP_BYTES // SPEED_STREAMS)
            async with self.session.post(f"{base}/__up", data=data, timeout=timeout) as resp:
                await resp.read()
            return len(data)

        start = time.perf_counter()
        received = sum(await asyncio.gather(*(down() for _ in range(SPEED_STREAMS))))
        down_bps = received * 8 / (time.perf_counter() - start)
        start = time.perf_counter()
        sent = sum(await asyncio.gather(*(up() for _ in range(SPEED_STREAMS))))
        up_bps = sent * 8 / (time.perf_counter() - start)

        link_mbps = (self.link or {}).get("speed")
        capped = bool(link_mbps and max(down_bps, up_bps) >= LINK_CAP_RATIO * link_mbps * 1e6)
        return {
            "down": round(down_bps),
            "up": round(up_bps),
            "ms": latency,
            "at": datetime.now(UTC).isoformat(),
            "capped": capped,
            "link_mbps": link_mbps,
        }
