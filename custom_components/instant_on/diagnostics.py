"""Diagnostics: dumps raw payloads so the undocumented schema can be inspected, with personal data removed.

Users attach this file to public GitHub issues, so redaction is broad: any field whose name suggests a name, address,
location or alert text, and any string that looks like a MAC or IP address wherever it appears (device ids are MACs).
"""
from __future__ import annotations

from dataclasses import asdict
import re
from typing import Any

from homeassistant.const import CONF_PASSWORD, CONF_USERNAME
from homeassistant.core import HomeAssistant

from . import InstantOnConfigEntry

REDACTED = "**REDACTED**"
_KEY = re.compile(
    r"(?i)(mac|ip(v4|v6)?(address|subnet|route)?s?$|address|name|serial|latitude|longitude|ssid|host|"
    r"latestactivealert|latestalert|connectedtoports|email|user(?!role)|phone|key$|password|secret|token|psk|passphrase)"
)
_MAC = re.compile(r"(?i)\b([0-9a-f]{2}[:-]){5}[0-9a-f]{2}\b")
_IP = re.compile(r"\b\d{1,3}(\.\d{1,3}){3}\b")


def redact(value: Any, key: str = "") -> Any:
    if isinstance(value, dict):
        return {k: redact(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, key) for v in value]
    if isinstance(value, bool) or value is None or isinstance(value, int | float):
        return value  # flags and counters (macAuthenticationEnabled, activeAlertsCount) are harmless
    if key and _KEY.search(key):
        return REDACTED
    if isinstance(value, str) and (_MAC.search(value) or _IP.search(value)):
        return REDACTED
    return value


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: InstantOnConfigEntry
) -> dict[str, Any]:
    coordinator = entry.runtime_data
    sites = {}
    for n, sd in enumerate((coordinator.data or {}).values(), 1):
        raw = asdict(sd)
        raw["clients"] = list(raw["clients"].values())  # the dict is keyed by MAC
        sites[f"site_{n}"] = redact(raw)
    return {
        "entry": {k: (REDACTED if k in (CONF_PASSWORD, CONF_USERNAME) else v) for k, v in entry.data.items()},
        "options": dict(entry.options),
        "client_names": _names_summary(coordinator),
        "sites": sites,
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
