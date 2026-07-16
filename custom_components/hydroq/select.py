"""Public selects."""

from __future__ import annotations

from homeassistant.components.select import SelectEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN, SYSTEM_MODES
from .controller.commands import CommandType
from .coordinator import HydroQCoordinator
from .entity import HydroQEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    async_add_entities(
        [HydroQPlantSelect(c), HydroQGrowthSelect(c), HydroQModeSelect(c)]
    )


class HydroQPlantSelect(HydroQEntity, SelectEntity):
    _attr_name = "Plant"
    _attr_icon = "mdi:leaf"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "plant_id")

    @property
    def options(self) -> list[str]:
        labels = self.coordinator.data.get("plant_labels") or {}
        ids = self.coordinator.data.get("plant_options") or list(labels.keys())
        # Show human labels as options; map back via labels dict.
        return [labels.get(pid, pid) for pid in ids]

    @property
    def current_option(self) -> str | None:
        labels = self.coordinator.data.get("plant_labels") or {}
        pid = self.coordinator.data.get("plant_id")
        if pid is None:
            return None
        return labels.get(pid, pid)

    async def async_select_option(self, option: str) -> None:
        labels = self.coordinator.data.get("plant_labels") or {}
        plant_id = option
        for pid, label in labels.items():
            if label == option or pid == option:
                plant_id = pid
                break
        await self.coordinator.async_handle(CommandType.SET_PLANT, {"plant_id": plant_id})


class HydroQGrowthSelect(HydroQEntity, SelectEntity):
    _attr_name = "Growth Stage"
    _attr_icon = "mdi:sprout"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "growth_stage")

    @property
    def options(self) -> list[str]:
        opts = self.coordinator.data.get("stage_options")
        if opts:
            return list(opts)
        return list(self.coordinator.controller.recipes.stages_for(
            self.coordinator.controller.plant_id
        ))

    @property
    def current_option(self) -> str | None:
        return self.coordinator.data.get("growth_stage")

    async def async_select_option(self, option: str) -> None:
        await self.coordinator.async_handle(
            CommandType.APPLY_GROWTH_STAGE, {"stage": option}
        )


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
