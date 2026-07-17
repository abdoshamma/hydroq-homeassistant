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
        HydroQTextSensor(c, "alarm_message", "Alarm Message"),
        HydroQTextSensor(c, "last_cal_ph", "Last pH Calibration"),
        HydroQTextSensor(c, "last_cal_tds", "Last TDS Calibration"),
        HydroQTextSensor(c, "last_cal_do", "Last DO Calibration"),
        HydroQTextSensor(c, "plant_label", "Plant"),
        HydroQDaysSensor(c),
        HydroQEcSensor(c, "live_ec", "EC", live=True),
        HydroQTdsSensor(c, "live_tds", "TDS", live=True),
        HydroQEcSensor(c, "target_ec", "Target EC", live=False),
        HydroQTdsSensor(c, "target_tds", "Target TDS", live=False),
        HydroQTdsFactorSensor(c),
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
        val = self.coordinator.data.get(self._key)
        return None if val is None else str(val)


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


class HydroQDaysSensor(HydroQEntity, SensorEntity):
    _attr_name = "Days After Sow"
    _attr_native_unit_of_measurement = "d"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "days_after_sow")

    @property
    def native_value(self) -> int | None:
        val = self.coordinator.data.get("days_after_sow")
        return None if val is None else int(val)


class HydroQEcSensor(HydroQEntity, SensorEntity):
    _attr_native_unit_of_measurement = "mS/cm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:flash"
    _attr_suggested_display_precision = 2

    def __init__(
        self, coordinator: HydroQCoordinator, key: str, name: str, *, live: bool
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._live = live

    @property
    def native_value(self) -> float | None:
        val = self.coordinator.data.get(self._key)
        if val is None and not self._live:
            val = self.coordinator.data.get("desired_ec")
        return None if val is None else round(float(val), 3)

    @property
    def extra_state_attributes(self) -> dict:
        attrs: dict = {"tds_factor": self.coordinator.data.get("tds_factor", 500)}
        if self._live:
            attrs["derived"] = bool(self.coordinator.data.get("ec_derived"))
        return attrs


class HydroQTdsSensor(HydroQEntity, SensorEntity):
    _attr_native_unit_of_measurement = "ppm"
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_icon = "mdi:water-opacity"

    def __init__(
        self, coordinator: HydroQCoordinator, key: str, name: str, *, live: bool
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._live = live

    @property
    def native_value(self) -> float | None:
        val = self.coordinator.data.get(self._key)
        if val is None and not self._live:
            val = self.coordinator.data.get("desired_ec_tds")
        return None if val is None else round(float(val), 1)

    @property
    def extra_state_attributes(self) -> dict:
        factor = self.coordinator.data.get("tds_factor", 500)
        return {"scale": f"ppm {factor}", "tds_factor": factor}


class HydroQTdsFactorSensor(HydroQEntity, SensorEntity):
    _attr_name = "TDS Scale"
    _attr_icon = "mdi:scale-balance"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "tds_factor")

    @property
    def native_value(self) -> str:
        factor = int(self.coordinator.data.get("tds_factor", 500) or 500)
        return f"ppm {factor}"
