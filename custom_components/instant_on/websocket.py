"""Websocket command feeding the instant-on-card."""
from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant.components import websocket_api
from homeassistant.config_entries import ConfigEntryState
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er

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
            site = build_site(sd.site, sd.clients, sd.inventory)
            # Entity ids the card can pull history for.
            site["entities"] = {
                key: ent_reg.async_get_entity_id("sensor", DOMAIN, f"{site_id}_{key}")
                for key in ("clients", "throughput_down", "throughput_up", "health_score")
            }
            last = coordinator.last_update_success_time
            site["updated"] = last.isoformat() if last else None
            sites.append(site)
    connection.send_result(msg["id"], {"sites": sites})
