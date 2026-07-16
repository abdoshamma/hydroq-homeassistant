"""Sow date entity."""

from __future__ import annotations

from datetime import date, datetime

from homeassistant.components.date import DateEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller.commands import CommandType
from .coordinator import HydroQCoordinator
from .entity import HydroQEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HydroQSowDate(c)])


class HydroQSowDate(HydroQEntity, DateEntity):
    _attr_name = "Sow Date"
    _attr_icon = "mdi:calendar-start"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "sow_date")

    @property
    def native_value(self) -> date | None:
        raw = self.coordinator.data.get("sow_date")
        if not raw:
            return None
        try:
            return datetime.strptime(str(raw)[:10], "%Y-%m-%d").date()
        except ValueError:
            return None

    async def async_set_value(self, value: date) -> None:
        await self.coordinator.async_handle(
            CommandType.SET_SOW_DATE, {"sow_date": value.isoformat()}
        )
