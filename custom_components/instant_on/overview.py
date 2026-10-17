"""Compact per-site snapshot for the instant-on-card (no Home Assistant imports)."""
from __future__ import annotations

from typing import Any

from .const import client_mac, client_name, is_online, is_wireless

TOP_CLIENTS = 8


def _bps(item: dict, key: str) -> int:
    val = item.get(key)
    if val is None:
        val = (item.get("dataTraffic") or item.get("portDataTraffic") or {}).get(key)
    return int(val or 0)


def _device(dev: dict[str, Any], clients_by_dev: dict[str, int]) -> dict[str, Any]:
    out: dict[str, Any] = {
        "id": dev.get("id"),
        "name": dev.get("name") or dev.get("defaultName"),
        "type": dev.get("deviceType"),
        "model": dev.get("model"),
        "online": is_online(dev),
        "health": dev.get("health"),
        "uptime": dev.get("uptimeInSeconds"),
        "uplink": dev.get("uplinkDeviceDeviceId"),
        "uplink_name": dev.get("uplinkDeviceName"),
        "firmware": dev.get("currentFirmwareVersion") or dev.get("deviceSoftwareVersion"),
        "up_to_date": dev.get("isUpToDate"),
        "clients": clients_by_dev.get(dev.get("id"), 0),
    }
    if radios := dev.get("radios"):
        out["radios"] = [
            {
                "band": r.get("band"),
                "channel": r.get("channel"),
                "width": r.get("channelWidth"),
                "util": r.get("utilizationPercent"),
                "clients": r.get("wirelessClientsCount"),
                "power": r.get("txPowerEirpInDbm"),
            }
            for r in radios
        ]
    if ports := dev.get("ethernetPorts"):
        out["ports"] = [
            {
                "n": p.get("faceplatePortNumber") or p.get("portNumber"),
                "up": bool(p.get("isLinkUp")),
                "speed": p.get("speed"),
                "uplink": bool(p.get("isUplink")),
                "sfp": bool(p.get("isSfp")),
                "poe_mw": p.get("powerProvidedInMilliwatts") or 0,
                "peer": p.get("directlyConnectedDeviceName"),
                "down": _bps(p, "downstreamThroughputInBitsPerSecond"),
                "up_bps": _bps(p, "upstreamThroughputInBitsPerSecond"),
            }
            for p in ports
        ]
    if dev.get("poePseNominalPowerInWatts"):
        out["poe"] = {
            "used": dev.get("poePseConsumedPowerInWatts") or 0,
            "budget": dev.get("poePseNominalPowerInWatts"),
        }
    return out


def _name(c: dict, label) -> str:
    return label(c)["name"] if label else (client_name(c) or client_mac(c))


def talkers(clients: dict[str, dict], label=None) -> list[dict[str, Any]]:
    """One entry per wireless client, and one per switch port for wired clients.

    Wired clients report the throughput of the switch port they sit behind, so clients
    sharing a port (e.g. behind an unmanaged switch) would otherwise be counted repeatedly.
    """
    out: dict[Any, dict[str, Any]] = {}
    for c in clients.values():
        if not is_online(c):
            continue
        port = (c.get("connectedToPorts") or [{}])[0]
        wireless = is_wireless(c)
        key = client_mac(c) if wireless or not port.get("deviceId") else (port.get("deviceId"), port.get("portNumber"))
        if key in out:
            out[key]["names"].append(_name(c, label))
            continue
        out[key] = {
            "names": [_name(c, label)],
            "vendor": (label(c) if label else {}).get("vendor"),
            "kind": (label(c) if label else {}).get("kind"),
            "type": "wireless" if wireless else "wired",
            "via": c.get("deviceName"),
            "port": None if wireless else port.get("portNumber"),
            "band": c.get("wirelessBand"),
            "down": _bps(c, "downstreamThroughputInBitsPerSecond"),
            "up": _bps(c, "upstreamThroughputInBitsPerSecond"),
        }
    return list(out.values())


def _client_row(c: dict, label) -> dict[str, Any]:
    lab = label(c) if label else {"name": client_name(c) or client_mac(c), "source": "instant_on"}
    port = (c.get("connectedToPorts") or [{}])[0]
    return {
        "name": lab["name"],
        "source": lab.get("source"),
        "vendor": lab.get("vendor"),
        "kind": lab.get("kind"),
        "mac": client_mac(c),
        "ip": lab.get("ip") or c.get("ipAddress") or None,
        "hostnames": lab.get("hostnames") or {},
        "online": is_online(c),
        "type": "wireless" if is_wireless(c) else "wired",
        "via": c.get("deviceName"),
        "port": port.get("portNumber"),
        "band": c.get("wirelessBand"),
        "signal": c.get("signalQuality"),
        "down": _bps(c, "downstreamThroughputInBitsPerSecond") if is_wireless(c) else None,
    }


def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Several devices can share a name (e.g. Sonos speakers in one room): add the MAC's last 3 bytes."""
    counts: dict[str, int] = {}
    for r in rows:
        counts[r["name"]] = counts.get(r["name"], 0) + 1
    for r in rows:
        if counts[r["name"]] > 1 and r.get("mac") and r["mac"][-8:] not in r["name"]:
            r["name"] = f'{r["name"]} · {r["mac"][-8:]}'
    return rows


def site_throughput(clients: dict[str, dict]) -> tuple[int, int]:
    t = talkers(clients)
    return sum(x["down"] for x in t), sum(x["up"] for x in t)


def build_site(site: dict, clients: dict[str, dict], inventory: list[dict], label=None) -> dict[str, Any]:
    online = [c for c in clients.values() if is_online(c)]
    by_dev: dict[str, int] = {}
    for c in online:
        if dev := c.get("deviceId"):
            by_dev[dev] = by_dev.get(dev, 0) + 1
    flows = talkers(clients, label)
    down, up = sum(x["down"] for x in flows), sum(x["up"] for x in flows)
    top = sorted(flows, key=lambda x: x["down"] + x["up"], reverse=True)[:TOP_CLIENTS]
    score = site.get("currentHealthScore") or {}
    alerts = site.get("activeAlertsCounters") or {}
    # The gateway is whatever the root switch reports as its uplink (e.g. a non-Instant On router).
    ids = {d.get("id") for d in inventory}
    gateway = next(
        (d.get("uplinkDeviceName") for d in inventory if d.get("uplinkDeviceDeviceId") not in ids and d.get("uplinkDeviceName")),
        None,
    )
    return {
        "id": str(site.get("id")),
        "name": site.get("name"),
        "health": site.get("health"),
        "health_reason": site.get("healthReason"),
        "score": score.get("score"),
        "alerts": {
            "total": site.get("activeAlertsCount") or 0,
            "major": alerts.get("activeMajorAlertsCount") or 0,
            "minor": alerts.get("activeMinorAlertsCount") or 0,
            "info": alerts.get("activeInfoAlertsCount") or 0,
            "latest": (site.get("latestActiveAlert") or {}).get("type") if isinstance(site.get("latestActiveAlert"), dict) else site.get("latestActiveAlert"),
        },
        "gateway": gateway,
        "clients": {
            "total": len(online),
            "wireless": sum(is_wireless(c) for c in online),
            "wired": sum(not is_wireless(c) for c in online),
            "bands": {
                b: sum(1 for c in online if c.get("wirelessBand") == b)
                for b in ("2.4ghz", "5ghz", "6ghz")
            },
        },
        "throughput": {"down": down, "up": up},
        "devices": [_device(d, by_dev) for d in inventory],
        "client_list": _dedupe([_client_row(c, label) for c in sorted(clients.values(), key=lambda c: (not is_online(c), _name(c, label).lower()))]),
        "top_clients": [
            {
                "name": t["names"][0],
                "others": len(t["names"]) - 1,
                "type": t["type"],
                "via": t["via"],
                "port": t["port"],
                "vendor": t.get("vendor"),
                "kind": t.get("kind"),
                "band": t["band"],
                "down": t["down"],
                "up": t["up"],
            }
            for t in top
        ],
    }
