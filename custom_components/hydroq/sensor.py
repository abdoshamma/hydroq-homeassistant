"""Public sensors."""

from __future__ import annotations

from homeassistant.components.sensor import SensorEntity, SensorStateClass
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCHEDULE_SLOT_COUNT
from .coordinator import HydroQCoordinator
from .entity import HydroQEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = [
        HydroQTextSensor(c, "status", "Status"),
        HydroQHealthSensor(c),
        HydroQTextSensor(c, "irrigation_state", "Irrigation State"),
        HydroQTextSensor(c, "dosing_state", "Dosing State"),
        HydroQTextSensor(c, "last_event", "Last Event"),
        HydroQTextSensor(c, "last_error", "Last Error"),
        HydroQTextSensor(c, "last_cal_ph", "Last pH Calibration"),
        HydroQTextSensor(c, "last_cal_tds", "Last TDS Calibration"),
        HydroQTextSensor(c, "last_cal_do", "Last DO Calibration"),
    ]
    for i in range(1, SCHEDULE_SLOT_COUNT + 1):
        entities.append(
            HydroQTextSensor(c, f"sched_{i}_label", f"Event {i} — plan")
        )
    async_add_entities(entities)


class HydroQTextSensor(HydroQEntity, SensorEntity):
    def __init__(self, coordinator: HydroQCoordinator, key: str, name: str) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name

    @property
    def native_value(self) -> str | None:
        return self.coordinator.data.get(self._key)


class HydroQHealthSensor(HydroQEntity, SensorEntity):
    _attr_name = "Health"
    _attr_native_unit_of_measurement = "%"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:heart-pulse"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "health")

    @property
    def native_value(self) -> int:
        return int(self.coordinator.data.get("health_score", 0))
