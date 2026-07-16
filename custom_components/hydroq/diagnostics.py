"""Diagnostics for HydroQ."""

from __future__ import annotations

from typing import Any

from homeassistant.components.diagnostics import async_redact_data
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import DOMAIN
from .coordinator import HydroQCoordinator

TO_REDACT = {"api_key", "password", "token"}


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: ConfigEntry
) -> dict[str, Any]:
    coordinator: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    return {
        "public": coordinator.data,
        "controller": coordinator.controller.diagnostics_blob(),
        "entry": async_redact_data(dict(entry.data), TO_REDACT),
        "options": dict(entry.options),
    }
