"""Base entity for HydroQ."""

from __future__ import annotations

from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN, MANUFACTURER, VERSION
from .coordinator import HydroQCoordinator
from .hardware.profiles import get_profile


class HydroQEntity(CoordinatorEntity[HydroQCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: HydroQCoordinator, key: str) -> None:
        super().__init__(coordinator)
        self._key = key
        self._attr_unique_id = f"{coordinator.entry.entry_id}_{key}"
        preset = coordinator.controller.hal.capabilities.preset_id or "capability"
        model = get_profile(preset).label if preset else "Capability map"
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, coordinator.entry.entry_id)},
            name=f"HydroQ {coordinator.zone_name}",
            manufacturer=MANUFACTURER,
            model=model,
            sw_version=VERSION,
        )
