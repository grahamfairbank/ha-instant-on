"""Data coordinator: one cloud poll per interval for all selected sites."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import timedelta
import logging
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import TimestampDataUpdateCoordinator, UpdateFailed

from .api import InstantOnAuthError, InstantOnClient, InstantOnError
from .const import CONF_SCAN_INTERVAL, CONF_SITES, DEFAULT_SCAN_INTERVAL, DOMAIN, client_mac
from .inventory import complete_inventory

_LOGGER = logging.getLogger(__name__)


@dataclass
class SiteData:
    site: dict[str, Any]
    clients: dict[str, dict[str, Any]] = field(default_factory=dict)  # keyed by MAC
    inventory: list[dict[str, Any]] = field(default_factory=list)


class InstantOnCoordinator(TimestampDataUpdateCoordinator[dict[str, SiteData]]):
    """Polls sites (incl. alert counts + health), clients and inventory."""

    config_entry: ConfigEntry

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: InstantOnClient) -> None:
        interval = entry.options.get(CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL)
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=DOMAIN,
            update_interval=timedelta(seconds=interval),
        )
        self.client = client
        self.site_device_ids: dict[str, str] = {}  # site id -> device registry id
        self.internet = None  # InternetCoordinator when internet health is on
        self.namer = None  # ClientNamer when client name lookup is on
        self._warned_missing: set[str] = set()

    async def _async_update_data(self) -> dict[str, SiteData]:
        wanted = set(self.config_entry.options.get(CONF_SITES) or self.config_entry.data.get(CONF_SITES, []))
        try:
            sites = await self.client.get_sites()
            result: dict[str, SiteData] = {}
            for site in sites:
                site_id = str(site.get("id"))
                if wanted and site_id not in wanted:
                    continue
                clients, (inventory, meta) = await asyncio.gather(
                    self.client.get_clients(site_id),
                    self.client.get_inventory(site_id),
                )
                inventory, added = complete_inventory(inventory, meta, clients)
                for dev in added:
                    if dev["id"] not in self._warned_missing:
                        self._warned_missing.add(dev["id"])
                        _LOGGER.warning(
                            "Instant On's inventory omits %s (%s); added it from the site's device list with limited details",
                            dev.get("name"), dev.get("model"),
                        )
                result[site_id] = SiteData(
                    site=site,
                    clients={m: c for c in clients if (m := client_mac(c))},
                    inventory=inventory,
                )
            if self.namer:
                self.namer.schedule([c for sd in result.values() for c in sd.clients.values()])
            return result
        except InstantOnAuthError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except (InstantOnError, TimeoutError, OSError) as err:
            raise UpdateFailed(f"Instant On API error: {err}") from err
