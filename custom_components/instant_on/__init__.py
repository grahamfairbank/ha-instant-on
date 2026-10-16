"""HPE Aruba Networking Instant On integration (unofficial cloud API)."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .api import InstantOnClient
from .const import DOMAIN
from .coordinator import InstantOnCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_URL = "/instant_on/instant-on-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "instant-on-card.js"

PLATFORMS = [Platform.BINARY_SENSOR, Platform.DEVICE_TRACKER, Platform.SENSOR]

type InstantOnConfigEntry = ConfigEntry[InstantOnCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card and its data feed (once, for all entries)."""
    websocket.async_register(hass)
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(CARD_PATH), True)])
    # Version query busts browser caches after an update.
    version = await hass.async_add_executor_job(lambda: int(CARD_PATH.stat().st_mtime))
    add_extra_js_url(hass, f"{CARD_URL}?v={version}")
    return True


async def async_setup_entry(hass: HomeAssistant, entry: InstantOnConfigEntry) -> bool:
    # Own session (own cookie jar) so SSO cookies don't leak into HA's shared session.
    session = async_create_clientsession(hass)
    client = InstantOnClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = InstantOnCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InstantOnConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)


async def _async_reload(hass: HomeAssistant, entry: InstantOnConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
