"""Public binary sensors."""

from __future__ import annotations

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .coordinator import HydroQCoordinator
from .entity import HydroQEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [
            HydroQFlag(c, "water_ok", "Water OK", BinarySensorDeviceClass.MOISTURE),
            HydroQFlag(c, "active_alarm", "Alarm Active", BinarySensorDeviceClass.PROBLEM),
            HydroQFlag(c, "refill_requested", "Refill Requested", None),
            HydroQFlag(c, "simulation", "Simulation", None),
            HydroQProcessActive(c, "irrigation_active", "Irrigation Active", "irrigation_state"),
            HydroQProcessActive(c, "dosing_active", "Dosing Active", "dosing_state"),
        ]
    )


class HydroQFlag(HydroQEntity, BinarySensorEntity):
    def __init__(
        self,
        coordinator: HydroQCoordinator,
        key: str,
        name: str,
        device_class: BinarySensorDeviceClass | None,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        if device_class:
            self._attr_device_class = device_class

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(self._key))


class HydroQProcessActive(HydroQEntity, BinarySensorEntity):
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(
        self, coordinator: HydroQCoordinator, key: str, name: str, state_key: str
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._state_key = state_key

    @property
    def is_on(self) -> bool:
        state = self.coordinator.data.get(self._state_key, "IDLE")
        return state not in ("IDLE", "COMPLETE", "ABORTED", "FAULT", "LIMIT")
