"""Sensors for D.A.R.S.: active drone count, nearest-drone id, nearest RSSI,
and receiver battery (boards that report one: Waveshare ESP32-C5 kit, ToughC5)."""

from __future__ import annotations

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import (
    PERCENTAGE,
    SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
    EntityCategory,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import DarsCoordinator
from .entity import DarsEntity


async def async_setup_entry(
    hass: HomeAssistant,
    entry: ConfigEntry,
    async_add_entities: AddEntitiesCallback,
) -> None:
    coordinator: DarsCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            DarsDroneCount(coordinator, entry),
            DarsNearestId(coordinator, entry),
            DarsNearestRssi(coordinator, entry),
        ]
    )
    # Battery only exists on some boards; add it when the receiver reports one.
    coordinator.async_add_battery_listener(
        lambda: async_add_entities([DarsBattery(coordinator, entry)])
    )


class DarsDroneCount(DarsEntity, SensorEntity):
    """Number of drones currently detected; the full list rides in attributes."""

    _attr_translation_key = "drone_count"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_native_unit_of_measurement = "drones"
    _attr_icon = "mdi:quadcopter"

    def __init__(self, coordinator: DarsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.unique_id}_drone_count"

    @property
    def native_value(self) -> int:
        return len(self.coordinator.drones)

    @property
    def extra_state_attributes(self) -> dict:
        return {"drones": self.coordinator.drone_payload()}


class DarsNearestId(DarsEntity, SensorEntity):
    """Identifier of the strongest-signal drone (blank when none)."""

    _attr_translation_key = "nearest_id"
    _attr_icon = "mdi:identifier"

    def __init__(self, coordinator: DarsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.unique_id}_nearest_id"

    @property
    def native_value(self) -> str | None:
        drone = self.coordinator.nearest()
        if drone is None:
            return None
        return drone.uas_id or drone.mac

    @property
    def extra_state_attributes(self) -> dict:
        drone = self.coordinator.nearest()
        return self.coordinator._faa_merge(drone, drone.as_dict()) if drone else {}


class DarsNearestRssi(DarsEntity, SensorEntity):
    """Signal strength of the strongest currently-detected drone."""

    _attr_translation_key = "nearest_rssi"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DarsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.unique_id}_nearest_rssi"

    @property
    def native_value(self) -> int | None:
        rssis = [d.rssi for d in self.coordinator.drones.values() if d.rssi is not None]
        return max(rssis) if rssis else None


class DarsBattery(DarsEntity, SensorEntity):
    """Receiver battery level. Unknown while on external power: the charger then
    holds the cell full, so the reading says nothing about its charge."""

    _attr_translation_key = "battery"
    _attr_device_class = SensorDeviceClass.BATTERY
    _attr_native_unit_of_measurement = PERCENTAGE
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: DarsCoordinator, entry: ConfigEntry) -> None:
        super().__init__(coordinator, entry)
        self._attr_unique_id = f"{entry.unique_id}_battery"

    @property
    def native_value(self) -> int | None:
        st = self.coordinator.status
        if st is None or not st.has_battery or st.external_power:
            return None
        return st.battery_pct

    @property
    def extra_state_attributes(self) -> dict:
        st = self.coordinator.status
        if st is None or not st.has_battery:
            return {}
        return {"voltage": round(st.battery_mv / 1000, 2)}
