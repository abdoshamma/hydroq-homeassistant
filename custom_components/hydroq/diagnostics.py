"""Diagnostics for HydroQ (per-entry + fleet fields)."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN, VERSION
from .coordinator import HydroQCoordinator
from .fleet import slim_public

TO_REDACT = {"api_key", "password", "token", "encryption_key"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    fleet_zones = 0
    for eid, coord in list(hass.data.get(DOMAIN, {}).items()):
        if isinstance(eid, str) and not eid.startswith("_") and hasattr(coord, "entry"):
            fleet_zones += 1
    return {
        "integration_version": VERSION,
        "fleet_zone_count": fleet_zones,
        "public": slim_public(coordinator.data or {}),
        "public_full": coordinator.data,
        "controller": coordinator.controller.diagnostics_blob(),
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
    }
