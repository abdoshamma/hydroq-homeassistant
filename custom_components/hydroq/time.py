"""Irrigation event time pickers (one clock per daily event)."""

from __future__ import annotations

from datetime import time

from homeassistant.components.time import TimeEntity
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
    async_add_entities([HydroQScheduleTime(c, i) for i in range(1, SCHEDULE_SLOT_COUNT + 1)])


class HydroQScheduleTime(HydroQEntity, TimeEntity):
    """User picks a local start time for one daily irrigation event."""

    _attr_icon = "mdi:clock-start"

    def __init__(self, coordinator: HydroQCoordinator, index: int) -> None:
        super().__init__(coordinator, f"sched_{index}_time")
        self._index = index
        self._attr_name = f"Event {index} — start time"

    @property
    def native_value(self) -> time | None:
        slots = self.coordinator.controller.irrigation.schedule
        if self._index < 1 or self._index > len(slots):
            return None
        slot = slots[self._index - 1]
        return time(hour=slot.hour, minute=slot.minute)

    async def async_set_value(self, value: time) -> None:
        await self.coordinator.async_handle(
            CommandType.SET_SCHEDULE_SLOT,
            {"index": self._index, "hour": value.hour, "minute": value.minute},
        )
