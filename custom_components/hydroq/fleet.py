"""Stage 5 — multi-zone fleet helpers (support bundle, no HA-only deps in pure builders)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .const import VERSION


def slim_public(data: dict[str, Any] | None) -> dict[str, Any]:
    """Operator-facing snapshot fields for fleet / support bundle."""
    if not data:
        return {}
    keys = (
        "status",
        "health_score",
        "system_mode",
        "plant_id",
        "growth_stage",
        "water_ok",
        "active_alarm",
        "alarm_message",
        "irrigation_state",
        "dosing_state",
        "offline_mode",
        "offline_hours_left",
        "probe_health",
        "live_tds",
        "live_ec",
        "desired_ph",
        "desired_ec_tds",
        "last_error",
        "last_event",
        "warnings",
    )
    return {k: data.get(k) for k in keys if k in data}


def build_support_bundle(
    *,
    zones: list[dict[str, Any]],
    ha_version: str | None = None,
) -> dict[str, Any]:
    """Assemble redacted fleet diagnostics for support."""
    return {
        "schema": 1,
        "product": "HydroQ",
        "integration_version": VERSION,
        "ha_version": ha_version,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "zone_count": len(zones),
        "zones": zones,
    }
