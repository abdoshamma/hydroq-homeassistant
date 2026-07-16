"""Public auto-mode switches."""

from __future__ import annotations

from homeassistant.components.switch import SwitchEntity
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
        HydroQAutoSwitch(c, "auto_irrigation", "Auto Irrigation", "irrigation"),
        HydroQAutoSwitch(c, "auto_lighting", "Auto Lighting", "lighting"),
        HydroQAutoSwitch(c, "auto_ph", "Auto pH", "ph"),
        HydroQAutoSwitch(c, "auto_ec", "Auto EC", "ec"),
        HydroQAutoSwitch(c, "auto_stage", "Auto Stage", "stage"),
        HydroQLightsSwitch(c),
    ]
    for i in range(1, SCHEDULE_SLOT_COUNT + 1):
        entities.append(HydroQScheduleEnableSwitch(c, i))
    async_add_entities(entities)


class HydroQAutoSwitch(HydroQEntity, SwitchEntity):
    def __init__(self, coordinator: HydroQCoordinator, key: str, name: str, auto_key: str) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._auto_key = auto_key

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(f"auto_{self._auto_key}"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_handle(
            CommandType.SET_AUTO, {"key": self._auto_key, "value": True}
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_handle(
            CommandType.SET_AUTO, {"key": self._auto_key, "value": False}
        )


class HydroQLightsSwitch(HydroQEntity, SwitchEntity):
    _attr_name = "Grow Lights"
    _attr_icon = "mdi:lightbulb-group"

    def __init__(self, coordinator: HydroQCoordinator) -> None:
        super().__init__(coordinator, "grow_lights")

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get("lights_on"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_handle(CommandType.SET_LIGHTS, {"on": True})

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_handle(CommandType.SET_LIGHTS, {"on": False})


class HydroQScheduleEnableSwitch(HydroQEntity, SwitchEntity):
    _attr_icon = "mdi:calendar-clock"

    def __init__(self, coordinator: HydroQCoordinator, index: int) -> None:
        super().__init__(coordinator, f"sched_{index}_enabled")
        self._index = index
        self._attr_name = f"Event {index} — use today"

    @property
    def is_on(self) -> bool:
        return bool(self.coordinator.data.get(f"sched_{self._index}_enabled"))

    async def async_turn_on(self, **kwargs) -> None:
        await self.coordinator.async_handle(
            CommandType.SET_SCHEDULE_SLOT, {"index": self._index, "enabled": True}
        )

    async def async_turn_off(self, **kwargs) -> None:
        await self.coordinator.async_handle(
            CommandType.SET_SCHEDULE_SLOT, {"index": self._index, "enabled": False}
        )
