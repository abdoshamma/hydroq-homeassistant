"""Public setpoint + irrigation duration numbers."""

from __future__ import annotations

from homeassistant.components.number import NumberEntity, NumberMode
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SCHEDULE_SLOT_COUNT
from .controller.commands import CommandType
from .coordinator import HydroQCoordinator
from .entity import HydroQEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    entities: list = [
        HydroQSetpoint(c, "desired_ph", "Desired pH", 5.0, 8.0, 0.1, "desired_ph"),
        HydroQSetpoint(c, "ph_tolerance", "pH Tolerance", 0.1, 1.0, 0.1, "ph_tolerance"),
        HydroQSetpoint(c, "desired_ec_tds", "Desired EC/TDS", 0, 2000, 10, "desired_ec_tds"),
        HydroQSetpoint(c, "ec_tolerance", "EC Tolerance", 10, 200, 5, "ec_tolerance"),
    ]
    for i in range(1, SCHEDULE_SLOT_COUNT + 1):
        entities.append(
            HydroQScheduleDuration(c, i),
        )
    async_add_entities(entities)


class HydroQSetpoint(HydroQEntity, NumberEntity):
    _attr_mode = NumberMode.BOX

    def __init__(
        self,
        coordinator: HydroQCoordinator,
        key: str,
        name: str,
        min_v: float,
        max_v: float,
        step: float,
        field: str,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_native_min_value = min_v
        self._attr_native_max_value = max_v
        self._attr_native_step = step
        self._field = field

    @property
    def native_value(self) -> float | None:
        val = self.coordinator.data.get(self._field)
        return None if val is None else float(val)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_handle(CommandType.SET_SETPOINT, {self._field: value})


class HydroQScheduleDuration(HydroQEntity, NumberEntity):
    _attr_mode = NumberMode.BOX
    _attr_native_unit_of_measurement = "min"
    _attr_icon = "mdi:timer-outline"
    _attr_native_min_value = 1
    _attr_native_max_value = 120
    _attr_native_step = 1

    def __init__(self, coordinator: HydroQCoordinator, index: int) -> None:
        super().__init__(coordinator, f"sched_{index}_duration")
        self._index = index
        self._attr_name = f"Event {index} — run for"

    @property
    def native_value(self) -> float | None:
        val = self.coordinator.data.get(f"sched_{self._index}_duration")
        return None if val is None else float(val)

    async def async_set_native_value(self, value: float) -> None:
        await self.coordinator.async_handle(
            CommandType.SET_SCHEDULE_SLOT,
            {"index": self._index, "duration_min": int(value)},
        )
