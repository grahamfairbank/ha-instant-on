"""Websocket command feeding the instant-on-card."""
from __future__ import annotations

from typing import Any

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
import voluptuous as vol

from .const import DOMAIN
from .overview import build_site


@callback
def async_register(hass: HomeAssistant) -> None:
    websocket_api.async_register_command(hass, ws_overview)


@websocket_api.websocket_command({vol.Required("type"): "instant_on/overview"})
@callback
def ws_overview(hass: HomeAssistant, connection: websocket_api.ActiveConnection, msg: dict[str, Any]) -> None:
    ent_reg = er.async_get(hass)
    sites = []
    for entry in hass.config_entries.async_entries(DOMAIN):
        if entry.state is not ConfigEntryState.LOADED:
            continue
        coordinator = entry.runtime_data
        for site_id, sd in (coordinator.data or {}).items():
            site = build_site(sd.site, sd.clients, sd.inventory, coordinator.namer.label if coordinator.namer else None)
            # Entity ids the card can pull history for.
            site["entities"] = {
                key: ent_reg.async_get_entity_id("sensor", DOMAIN, f"{site_id}_{key}")
                for key in ("clients", "throughput_down", "throughput_up", "health_score")
            }
            last = coordinator.last_update_success_time
            site["updated"] = last.isoformat() if last else None
            sites.append(site)
    connection.send_result(msg["id"], {"sites": sites, "internet": _internet(hass, ent_reg)})


def _internet(hass: HomeAssistant, ent_reg: er.EntityRegistry) -> dict[str, Any] | None:
    for entry in hass.config_entries.async_loaded_entries(DOMAIN):
        net = entry.runtime_data.internet
        if not net or not net.data:
            continue
        ids = {
            key: ent_reg.async_get_entity_id(platform, DOMAIN, f"internet_{entry.entry_id}_{key}")
            for platform, key in (("sensor", "latency"), ("sensor", "status"), ("sensor", "download"),
                                  ("sensor", "upload"), ("sensor", "packet_loss"), ("button", "speedtest"))
        }
        speed = net.speed
        if speed is None and ids["download"]:
            # After a restart, fall back to the restored sensor values until the next test.
            down, up = hass.states.get(ids["download"]), hass.states.get(ids["upload"] or "")
            try:
                speed = {"down": float(down.state) * 1e6, "up": float(up.state) * 1e6, "ms": None,
                         "at": down.attributes.get("tested_at"), "capped": down.attributes.get("limited_by_host_link"),
                         "link_mbps": down.attributes.get("host_link_mbps")}
            except (AttributeError, TypeError, ValueError):
                speed = None
        last = net.last_update_success_time
        return {
            **net.data,
            "link": net.link,
            "speed": speed,
            "speed_running": net.speed_running,
            "entities": ids,
            "updated": last.isoformat() if last else None,
        }
    return None
