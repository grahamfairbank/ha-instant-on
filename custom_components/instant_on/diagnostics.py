"""Diagnostics: dumps raw payloads so the undocumented schema can be inspected."""
from __future__ import annotations

from dataclasses import asdict
from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import InstantOnConfigEntry

TO_REDACT = {CONF_PASSWORD, CONF_USERNAME, "macAddress", "mac", "ipAddress", "serialNumber", "hostName", "name"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: InstantOnConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    return {
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
        "client_names": _names_summary(coordinator),
        "sites": async_redact_data(
            {sid: asdict(sd) for sid, sd in (coordinator.data or {}).items()}, TO_REDACT
        ),
    }


def _names_summary(coordinator) -> dict[str, Any] | None:
    """How clients got their names (counts only; no names or MACs)."""
    if not coordinator.namer:
        return None
    sources: dict[str, int] = {}
    for sd in (coordinator.data or {}).values():
        for c in sd.clients.values():
            src = coordinator.namer.label(c)["source"]
            sources[src] = sources.get(src, 0) + 1
    return {"sources": sources, "vendor_db_entries": len(coordinator.namer._oui)}
