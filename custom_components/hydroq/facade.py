"""Stage 4 public-entity façade (no Home Assistant import)."""

from __future__ import annotations

# Operator-facing keys stay uncategorized (primary).
CONFIG_KEYS = frozenset(
    {
        "cal_ph_neutral",
        "cal_ph_acid",
        "cal_ph_auto",
        "cal_ec",
        "cal_do",
    }
)
DIAGNOSTIC_KEYS = frozenset(
    {
        "last_event",
        "last_error",
        "last_cal_ph",
        "last_cal_tds",
        "last_cal_do",
        "last_cal_result",
        "probe_health",
        "offline_mode",
        "offline_hours_left",
        "dose_ml_today",
        "dose_ml_budget",
        "stock_ml",
        "stock_days_left",
        "tds_factor",
        "plant_label",
        "irrigation_active",
        "dosing_active",
        "simulation",
        "live_ec",
        "target_ec",
        "desired_ec",
        "ec_tolerance_ms",
        "start_neutralize",
        "test_pump_a",
        "test_pump_b",
        "test_pump_c",
        "test_ph_pump",
        "test_ph_down",
        "test_irrigation",
    }
)


def facade_category(key: str) -> str | None:
    """Return 'config', 'diagnostic', or None (primary / operator)."""
    if key in CONFIG_KEYS or key.startswith("cal_"):
        return "config"
    if key in DIAGNOSTIC_KEYS:
        return "diagnostic"
    if key.startswith("test_"):
        return "diagnostic"
    if key.startswith("sched_") and key.endswith("_label"):
        return "diagnostic"
    return None
