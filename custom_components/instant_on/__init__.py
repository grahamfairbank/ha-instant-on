"""HPE Aruba Networking Instant On integration (unofficial cloud API)."""
from __future__ import annotations

from pathlib import Path

from homeassistant.components import frontend, panel_custom
from homeassistant.components.frontend import add_extra_js_url
from homeassistant.components.http import StaticPathConfig
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_PASSWORD, CONF_USERNAME, Platform
from homeassistant.core import HomeAssistant
from homeassistant.helpers import config_validation as cv, device_registry as dr
from homeassistant.helpers.aiohttp_client import async_create_clientsession
from homeassistant.helpers.typing import ConfigType

from . import websocket
from .api import InstantOnClient
from .const import CONF_INTERNET, CONF_SHOW_PANEL, DOMAIN, PANEL_ICON, PANEL_TITLE, PANEL_URL_PATH
from .coordinator import InstantOnCoordinator
from .entity import site_device_info
from .internet import InternetCoordinator

CONFIG_SCHEMA = cv.config_entry_only_config_schema(DOMAIN)
CARD_URL = "/instant_on/instant-on-card.js"
CARD_PATH = Path(__file__).parent / "frontend" / "instant-on-card.js"

PLATFORMS = [Platform.BINARY_SENSOR, Platform.BUTTON, Platform.DEVICE_TRACKER, Platform.SENSOR]

type InstantOnConfigEntry = ConfigEntry[InstantOnCoordinator]


async def async_setup(hass: HomeAssistant, config: ConfigType) -> bool:
    """Serve the dashboard card and its data feed (once, for all entries)."""
    websocket.async_register(hass)
    await hass.http.async_register_static_paths([StaticPathConfig(CARD_URL, str(CARD_PATH), True)])
    # Version query busts browser caches after an update.
    version = await hass.async_add_executor_job(lambda: int(CARD_PATH.stat().st_mtime))
    hass.data[DOMAIN] = {"module_url": f"{CARD_URL}?v={version}"}
    add_extra_js_url(hass, hass.data[DOMAIN]["module_url"])
    return True


def _panel_wanted(hass: HomeAssistant) -> bool:
    return any(
        e.options.get(CONF_SHOW_PANEL, True)
        for e in hass.config_entries.async_entries(DOMAIN)
        if not e.disabled_by
    )


async def _async_update_panel(hass: HomeAssistant, keep: bool = True) -> None:
    """Show the built-in Network panel while any entry wants it, remove it otherwise."""
    registered = PANEL_URL_PATH in hass.data.get(frontend.DATA_PANELS, {})
    if keep and _panel_wanted(hass):
        if not registered:
            await panel_custom.async_register_panel(
                hass,
                frontend_url_path=PANEL_URL_PATH,
                webcomponent_name="instant-on-panel",
                module_url=hass.data[DOMAIN]["module_url"],
                sidebar_title=PANEL_TITLE,
                sidebar_icon=PANEL_ICON,
                require_admin=False,
                config={},
            )
    elif registered:
        frontend.async_remove_panel(hass, PANEL_URL_PATH)


async def async_setup_entry(hass: HomeAssistant, entry: InstantOnConfigEntry) -> bool:
    # Own session (own cookie jar) so SSO cookies don't leak into HA's shared session.
    session = async_create_clientsession(hass)
    client = InstantOnClient(session, entry.data[CONF_USERNAME], entry.data[CONF_PASSWORD])
    coordinator = InstantOnCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    # Register site devices first so APs and switches can link to them by id.
    dev_reg = dr.async_get(hass)
    for site_id, site_data in coordinator.data.items():
        device = dev_reg.async_get_or_create(config_entry_id=entry.entry_id, **site_device_info(site_data))
        coordinator.site_device_ids[site_id] = device.id
    if entry.options.get(CONF_INTERNET, True):
        internet = InternetCoordinator(hass, entry)
        await internet.async_config_entry_first_refresh()
        internet.async_start_schedule()
        coordinator.internet = internet
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    await _async_update_panel(hass)
    entry.async_on_unload(entry.add_update_listener(_async_reload))
    return True


async def async_unload_entry(hass: HomeAssistant, entry: InstantOnConfigEntry) -> bool:
    unloaded = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unloaded:
        # Keep the panel only if another loaded entry still wants it.
        others = [
            e for e in hass.config_entries.async_loaded_entries(DOMAIN)
            if e.entry_id != entry.entry_id and e.options.get(CONF_SHOW_PANEL, True)
        ]
        await _async_update_panel(hass, keep=bool(others))
    return unloaded


async def _async_reload(hass: HomeAssistant, entry: InstantOnConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)
