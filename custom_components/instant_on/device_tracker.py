"""Presence tracking for clients seen in clientSummary."""
from __future__ import annotations

from typing import Any

from homeassistant.components.device_tracker import ScannerEntity
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InstantOnConfigEntry
from .const import CONF_TRACK_CLIENTS, client_name, is_online, is_wireless
from .entity import InstantOnEntity

_ATTRS = (
    "deviceName", "health", "signalQuality", "snrInDb", "wirelessBand",
    "wirelessNetworkName", "wiredNetworkName", "stateDurationInSeconds",
)


async def async_setup_entry(
    hass: HomeAssistant, entry: InstantOnConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if not entry.options.get(CONF_TRACK_CLIENTS, True):
        return
    coordinator = entry.runtime_data
    known: set[str] = set()

    @callback
    def _add_new() -> None:
        new = [
            ClientTracker(coordinator, site_id, mac)
            for site_id, sd in coordinator.data.items()
            for mac in sd.clients
            if mac not in known
        ]
        known.update(t.mac_address for t in new)
        if new:
            async_add_entities(new)

    _add_new()
    entry.async_on_unload(coordinator.async_add_listener(_add_new))


class ClientTracker(InstantOnEntity, ScannerEntity):
    # Clients can number in the hundreds: create disabled, user enables the ones they care about.
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator, site_id: str, mac: str) -> None:
        super().__init__(coordinator, site_id)
        self._mac = mac
        self._attr_unique_id = f"client_{mac}"
        self._last: dict[str, Any] = self._client or {}

    @property
    def _client(self) -> dict[str, Any] | None:
        return self.site_data.clients.get(self._mac) if self.site_data else None

    @property
    def available(self) -> bool:
        # Stay available when the client simply disappears (that means "away").
        return self.coordinator.last_update_success

    @property
    def mac_address(self) -> str:
        return self._mac

    @property
    def name(self) -> str:
        return client_name(self._client or self._last) or self._mac

    @property
    def is_connected(self) -> bool:
        return self._client is not None and is_online(self._client)

    @property
    def ip_address(self) -> str | None:
        return (self._client or {}).get("ipAddress") or None  # most wired clients report ""

    @property
    def hostname(self) -> str | None:
        return (self._client or self._last).get("hostName")

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        c = self._client or self._last
        attrs = {"connection": "wireless" if is_wireless(c) else "wired"}
        attrs.update({k: c[k] for k in _ATTRS if c.get(k) is not None})
        if ports := c.get("connectedToPorts"):
            attrs["switch_port"] = f"{ports[0].get('deviceName')} port {ports[0].get('portName')}"
        return attrs

    @callback
    def _handle_coordinator_update(self) -> None:
        if self._client:
            self._last = self._client
        super()._handle_coordinator_update()
