"""HA Repairs hooks for HydroQ."""

from __future__ import annotations

from homeassistant.core import HomeAssistant
from homeassistant.helpers import issue_registry as ir

from .const import DOMAIN


def async_create_issue_uncalibrated(hass: HomeAssistant, entry_id: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"uncalibrated_{entry_id}",
        is_fixable=True,
        severity=ir.IssueSeverity.WARNING,
        translation_key="uncalibrated",
    )


def async_create_issue_sensor_unavailable(hass: HomeAssistant, entry_id: str, sensor: str) -> None:
    ir.async_create_issue(
        hass,
        DOMAIN,
        f"unavailable_{entry_id}_{sensor}",
        is_fixable=True,
        severity=ir.IssueSeverity.ERROR,
        translation_key="sensor_unavailable",
        translation_placeholders={"sensor": sensor},
    )
