"""Complete the site inventory with devices the inventory list leaves out (no Home Assistant imports).

On some sites the inventory's `elements` omit a device that is adopted, online and serving clients, while its
`totalCount` agrees with the shortened list. The same response's `metaData.networkScopes[].ipReservationInfo.siteDevices`
still lists every device, so devices found only there are added, with what can be learned elsewhere: the switch
port they're plugged into, and the clients and radios that report them.
"""
from __future__ import annotations

from typing import Any


def site_devices(meta: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Every device listed under the inventory's metaData, de-duplicated by id."""
    seen: dict[str, dict[str, Any]] = {}
    for scope in (meta or {}).get("networkScopes") or []:
        for dev in (scope.get("ipReservationInfo") or {}).get("siteDevices") or []:
            if dev.get("id") and dev["id"] not in seen:
                seen[dev["id"]] = dev
    return list(seen.values())


def _device_type(model: str | None) -> str:
    model = (model or "").upper()
    if model.startswith("AP"):
        return "accessPoint"
    if model.startswith(("JL", "R8", "S0")):  # Instant On 1830/1930/1960 switch SKUs
        return "switch"
    return "unknown"


def complete_inventory(
    elements: list[dict[str, Any]], meta: dict[str, Any] | None, clients: list[dict[str, Any]]
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Return (inventory with missing devices added, the devices that were added)."""
    known = {d.get("id") for d in elements}
    added: list[dict[str, Any]] = []
    for sd in site_devices(meta):
        dev_id = sd["id"]
        if dev_id in known:
            continue
        dev: dict[str, Any] = {
            "id": dev_id,
            "macAddress": sd.get("macAddress") or dev_id,
            "name": sd.get("name"),
            "model": sd.get("model"),
            "deviceType": _device_type(sd.get("model")),
            "status": "up" if sd.get("isOnline") else "down",
            "ipAddress": (sd.get("ipAddress") or "").split("/")[0] or None,
            "partial": True,  # details beyond these aren't available for this device
        }
        # Uplink: the switch port that reports this device as its neighbour.
        for sw in elements:
            for port in sw.get("ethernetPorts") or []:
                if port.get("directlyConnectedDeviceId") == dev_id:
                    dev["uplinkDeviceDeviceId"] = sw.get("id")
                    dev["uplinkDeviceName"] = sw.get("name") or sw.get("defaultName")
                    dev["uplinkPort"] = port.get("faceplatePortNumber") or port.get("portNumber")
                    dev["inputPowerSource"] = "poe" if port.get("powerProvidedInMilliwatts") else None
        # Radios: one per radio id the online wireless clients report, with its band and client count.
        if dev["deviceType"] == "accessPoint":
            radios: dict[str, dict[str, Any]] = {}
            for c in clients:
                if c.get("deviceId") != dev_id or c.get("clientType") != "wireless" or c.get("status") != "up":
                    continue
                rid = c.get("wirelessRadioId") or c.get("wirelessBand") or "radio"
                r = radios.setdefault(rid, {"id": rid, "band": c.get("wirelessBand"), "channel": None,
                                            "channelWidth": None, "utilizationPercent": None, "wirelessClientsCount": 0})
                r["wirelessClientsCount"] += 1
            dev["radios"] = sorted(radios.values(), key=lambda r: r.get("band") or "")
        added.append(dev)
    return elements + added, added
