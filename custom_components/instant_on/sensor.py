"""Per-site summary sensors."""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from homeassistant.components.sensor import (
    RestoreSensor,
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, EntityCategory, UnitOfDataRate, UnitOfPower, UnitOfTime
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import InstantOnConfigEntry
from .const import is_online, is_wireless
from .coordinator import SiteData
from .entity import InstantOnEntity, InternetEntity, inventory_device_info, inventory_id, site_device_info
from .internet import STATES
from .overview import site_throughput


def _online(d: SiteData) -> list:
    return [c for c in d.clients.values() if is_online(c)]


@dataclass(frozen=True, kw_only=True)
class SiteSensorDescription(SensorEntityDescription):
    value_fn: Callable[[SiteData], int | None]


SENSORS = (
    SiteSensorDescription(
        key="clients", translation_key="clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: len(_online(d)),
    ),
    SiteSensorDescription(
        key="wireless_clients", translation_key="wireless_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(is_wireless(c) for c in _online(d)),
    ),
    SiteSensorDescription(
        key="wired_clients", translation_key="wired_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: sum(not is_wireless(c) for c in _online(d)),
    ),
    SiteSensorDescription(
        key="devices", translation_key="devices",
        value_fn=lambda d: len(d.inventory),
    ),
    SiteSensorDescription(
        key="active_alerts", translation_key="active_alerts",
        value_fn=lambda d: d.site.get("activeAlertsCount"),
    ),
    SiteSensorDescription(
        key="throughput_down", translation_key="throughput_down",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda d: round(site_throughput(d.clients)[0] / 1e6, 2),
    ),
    SiteSensorDescription(
        key="throughput_up", translation_key="throughput_up",
        device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND,
        state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=1,
        value_fn=lambda d: round(site_throughput(d.clients)[1] / 1e6, 2),
    ),
    SiteSensorDescription(
        key="health_score", translation_key="health_score",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda d: (d.site.get("currentHealthScore") or {}).get("score"),
    ),
)


async def async_setup_entry(
    hass: HomeAssistant, entry: InstantOnConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    coordinator = entry.runtime_data
    entities: list[SensorEntity] = [
        SiteSensor(coordinator, site_id, desc)
        for site_id in coordinator.data
        for desc in SENSORS
    ]
    for site_id, sd in coordinator.data.items():
        for dev in sd.inventory:
            if not (dev_id := inventory_id(dev)):
                continue
            for desc in DEVICE_SENSORS:
                if desc.exists_fn(dev):
                    entities.append(DeviceSensor(coordinator, site_id, dev_id, dev, desc))
    if coordinator.internet:
        entities += [InternetSensor(coordinator.internet, desc) for desc in INTERNET_SENSORS]
    async_add_entities(entities)


class SiteSensor(InstantOnEntity, SensorEntity):
    entity_description: SiteSensorDescription

    def __init__(self, coordinator, site_id: str, desc: SiteSensorDescription) -> None:
        super().__init__(coordinator, site_id)
        self.entity_description = desc
        self._attr_unique_id = f"{site_id}_{desc.key}"
        self._attr_device_info = site_device_info(coordinator.data[site_id])

    @property
    def native_value(self) -> int | None:
        return self.entity_description.value_fn(self.site_data) if self.site_data else None

    @property
    def extra_state_attributes(self):
        if not self.site_data:
            return None
        site = self.site_data.site
        if self.entity_description.key == "active_alerts":
            return {"latest_alert": site.get("latestActiveAlert"), **(site.get("activeAlertsCounters") or {})}
        if self.entity_description.key == "health_score":
            return {"health": site.get("health"), "reason": site.get("healthReason")}
        return None


@dataclass(frozen=True, kw_only=True)
class DeviceSensorDescription(SensorEntityDescription):
    value_fn: Callable[[dict[str, Any], SiteData], Any]
    exists_fn: Callable[[dict[str, Any]], bool] = lambda dev: True


DEVICE_SENSORS = (
    DeviceSensorDescription(
        key="clients", translation_key="device_clients",
        state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda dev, sd: sum(
            1 for c in sd.clients.values() if c.get("deviceId") == dev.get("id") and c.get("status") == "up"
        ),
    ),
    DeviceSensorDescription(
        key="channel_utilization", translation_key="channel_utilization",
        native_unit_of_measurement=PERCENTAGE, state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda dev: bool(dev.get("radios")),
        value_fn=lambda dev, sd: max((r.get("utilizationPercent") or 0 for r in dev.get("radios") or []), default=None),
    ),
    DeviceSensorDescription(
        key="poe_power", translation_key="poe_power",
        device_class=SensorDeviceClass.POWER, native_unit_of_measurement=UnitOfPower.WATT,
        state_class=SensorStateClass.MEASUREMENT,
        exists_fn=lambda dev: bool(dev.get("poePseNominalPowerInWatts")),
        value_fn=lambda dev, sd: dev.get("poePseConsumedPowerInWatts"),
    ),
)


class DeviceSensor(InstantOnEntity, SensorEntity):
    entity_description: DeviceSensorDescription

    def __init__(self, coordinator, site_id: str, dev_id: str, dev: dict, desc: DeviceSensorDescription) -> None:
        super().__init__(coordinator, site_id)
        self.entity_description = desc
        self._dev_id = dev_id
        self._attr_unique_id = f"dev_{dev_id}_{desc.key}"
        self._attr_device_info = inventory_device_info(coordinator, site_id, dev)

    @property
    def _dev(self) -> dict[str, Any] | None:
        if self.site_data:
            return next((d for d in self.site_data.inventory if inventory_id(d) == self._dev_id), None)
        return None

    @property
    def available(self) -> bool:
        return super().available and self._dev is not None

    @property
    def native_value(self):
        return self.entity_description.value_fn(self._dev, self.site_data) if self._dev else None

    @property
    def extra_state_attributes(self):
        dev = self._dev
        if self.entity_description.key == "channel_utilization" and dev:
            return {
                r.get("band"): {"channel": r.get("channel"), "width": r.get("channelWidth"),
                                "utilization": r.get("utilizationPercent"), "clients": r.get("wirelessClientsCount")}
                for r in dev.get("radios") or []
            }
        if self.entity_description.key == "poe_power" and dev:
            return {"budget_w": dev.get("poePseNominalPowerInWatts")}
        return None


@dataclass(frozen=True, kw_only=True)
class InternetSensorDescription(SensorEntityDescription):
    value_fn: Callable[[Any], Any]
    attrs_fn: Callable[[Any], dict | None] = lambda c: None


def _ms(**kw) -> dict:
    return dict(device_class=SensorDeviceClass.DURATION, native_unit_of_measurement=UnitOfTime.MILLISECONDS,
                state_class=SensorStateClass.MEASUREMENT, suggested_display_precision=0, **kw)


def _rate(c, key):
    return round(c.speed[key] / 1e6, 1) if c.speed else None


INTERNET_SENSORS = (
    InternetSensorDescription(
        key="status", translation_key="internet_status", device_class=SensorDeviceClass.ENUM, options=list(STATES),
        value_fn=lambda c: c.data["state"],
        attrs_fn=lambda c: {"outage_since": c.data.get("outage_since"), "public_ip": c.data.get("ip"),
                            "cloudflare_location": c.data.get("colo")},
    ),
    InternetSensorDescription(key="latency", translation_key="internet_latency", **_ms(),
                              value_fn=lambda c: c.data["latency"],
                              attrs_fn=lambda c: {"cloudflare_ms": c.data["cloudflare"]["ms"], "google_ms": c.data["google"]["ms"]}),
    InternetSensorDescription(key="jitter", translation_key="internet_jitter", **_ms(), value_fn=lambda c: c.data["jitter"]),
    InternetSensorDescription(key="packet_loss", translation_key="internet_packet_loss", native_unit_of_measurement=PERCENTAGE,
                              state_class=SensorStateClass.MEASUREMENT, value_fn=lambda c: c.data["loss"]),
    InternetSensorDescription(key="dns", translation_key="internet_dns", **_ms(), value_fn=lambda c: c.data["dns"],
                              attrs_fn=lambda c: {"resolver": c.data.get("dns_resolver"), "cloudflare_ms": c.data.get("dns_cloudflare")}),
    InternetSensorDescription(key="https", translation_key="internet_https", **_ms(), value_fn=lambda c: c.data["https"]),
    InternetSensorDescription(
        key="download", translation_key="internet_download", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _rate(c, "down"),
        attrs_fn=lambda c: c.speed and {"tested_at": c.speed["at"], "latency_ms": c.speed["ms"],
                                        "limited_by_host_link": c.speed["capped"], "host_link_mbps": c.speed["link_mbps"]},
    ),
    InternetSensorDescription(
        key="upload", translation_key="internet_upload", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, state_class=SensorStateClass.MEASUREMENT,
        value_fn=lambda c: _rate(c, "up"),
        attrs_fn=lambda c: c.speed and {"tested_at": c.speed["at"], "limited_by_host_link": c.speed["capped"]},
    ),
    InternetSensorDescription(
        key="host_link", translation_key="internet_host_link", device_class=SensorDeviceClass.DATA_RATE,
        native_unit_of_measurement=UnitOfDataRate.MEGABITS_PER_SECOND, entity_category=EntityCategory.DIAGNOSTIC,
        value_fn=lambda c: (c.link or {}).get("speed"),
        attrs_fn=lambda c: {"interface": (c.link or {}).get("iface"), "type": (c.link or {}).get("kind")},
    ),
)


class InternetSensor(InternetEntity, RestoreSensor):
    """Internet health sensor. Speed results are restored after a restart until the next test."""

    entity_description: InternetSensorDescription

    def __init__(self, coordinator, desc: InternetSensorDescription) -> None:
        super().__init__(coordinator, desc.key)
        self.entity_description = desc
        self._restored = None

    async def async_added_to_hass(self) -> None:
        await super().async_added_to_hass()
        if self.entity_description.key in ("download", "upload") and (last := await self.async_get_last_sensor_data()):
            self._restored = last.native_value

    @property
    def native_value(self):
        value = self.entity_description.value_fn(self.coordinator)
        return self._restored if value is None and self._restored is not None else value

    @property
    def extra_state_attributes(self):
        return self.entity_description.attrs_fn(self.coordinator) or None
