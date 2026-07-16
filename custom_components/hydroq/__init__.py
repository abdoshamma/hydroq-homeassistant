"""HydroQ — commercial hydroponic zone control for Home Assistant."""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from .const import DOMAIN, PLATFORMS

if TYPE_CHECKING:
    from homeassistant.config_entries import ConfigEntry
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)


async def async_setup_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Set up one HydroQ zone (one config entry)."""
    from .coordinator import HydroQCoordinator
    from .dashboard import async_setup_lovelace
    from .services import async_setup_services

    hass.data.setdefault(DOMAIN, {})

    coordinator = HydroQCoordinator(hass, entry)
    await coordinator.async_config_entry_first_refresh()

    hass.data[DOMAIN][entry.entry_id] = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_update_listener))

    if sum(1 for v in hass.data[DOMAIN].values() if isinstance(v, HydroQCoordinator)) == 1:
        await async_setup_services(hass)
        await async_setup_lovelace(hass)
    return True


async def async_unload_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    from .services import async_unload_services

    unload_ok = await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
    if unload_ok:
        coordinator = hass.data[DOMAIN].pop(entry.entry_id)
        await coordinator.async_shutdown()
        if not hass.data[DOMAIN]:
            await async_unload_services(hass)
            hass.data.pop(DOMAIN, None)
    return unload_ok


async def _async_update_listener(hass: "HomeAssistant", entry: "ConfigEntry") -> None:
    """Soft-apply option changes (schedule / setpoints) without full reload."""
    from .coordinator import HydroQCoordinator

    coord = hass.data.get(DOMAIN, {}).get(entry.entry_id)
    if isinstance(coord, HydroQCoordinator):
        coord.apply_options(entry.options)
        await coord.async_request_refresh()
        return
    await hass.config_entries.async_reload(entry.entry_id)


async def async_migrate_entry(hass: "HomeAssistant", entry: "ConfigEntry") -> bool:
    """Migrate config entry schema to capability map (v2)."""
    from .const import (
        CONF_CAPABILITIES,
        CONF_ENTITY_MAP,
        CONF_HARDWARE_PROFILE,
        CONF_PUMP_ML_PER_MIN,
        CONF_SIMULATION,
    )
    from .models.capability import legacy_entity_map_to_capabilities

    _LOGGER.info("Migrating HydroQ entry from v%s", entry.version)
    if entry.version < 2:
        data = dict(entry.data)
        if CONF_CAPABILITIES not in data:
            caps = legacy_entity_map_to_capabilities(
                data.get(CONF_ENTITY_MAP, {}),
                preset_id=data.get(CONF_HARDWARE_PROFILE),
                ml_per_min=float(data.get(CONF_PUMP_ML_PER_MIN, 50)),
                simulation=bool(data.get(CONF_SIMULATION, False)),
            )
            data[CONF_CAPABILITIES] = caps.as_dict()
        hass.config_entries.async_update_entry(entry, data=data, version=2)
    return True
