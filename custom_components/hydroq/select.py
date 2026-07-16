"""Public selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, GROWTH_STAGES, SYSTEM_MODES
from .controller.commands import CommandType
from .coordinator import HydroQCoordinator
from .entity import HydroQEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities([HydroQGrowthSelect(c), HydroQModeSelect(c)])


class HydroQGrowthSelect(HydroQEntity, SelectEntity):
    _attr_name = "Growth Stage"
    _attr_options = list(GROWTH_STAGES)
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "growth_stage")

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("growth_stage")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_handle(CommandType.APPLY_GROWTH_STAGE, {"stage": option})


class HydroQModeSelect(HydroQEntity, SelectEntity):
    _attr_name = "System Mode"
    _attr_options = list(SYSTEM_MODES)
    _attr_icon = "mdi:cog"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "system_mode")

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("system_mode")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_handle(CommandType.SET_SYSTEM_MODE, {"mode": option})
