"""Button to run an internet speed test on demand."""
from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InstantOnConfigEntry
from .entity import InternetEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: InstantOnConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    if internet := entry.runtime_data.internet:
        async_add_entities([SpeedTestButton(internet)])


class SpeedTestButton(InternetEntity, ButtonEntity):
    _attr_translation_key = "speedtest"
    _attr_icon = "mdi:speedometer"

    def __init__(self, coordinator) -> None:
        super().__init__(coordinator, "speedtest")

    async def async_press(self) -> None:
        # Runs in the background; the sensors update when it finishes (about 10-30 s).
        self.hass.async_create_background_task(self.coordinator.async_run_speedtest(force=True), "instant_on speed test")
