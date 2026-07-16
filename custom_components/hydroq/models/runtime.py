"""Runtime / public snapshot models."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class ScheduleSlot:
    enabled: bool = True
    hour: int = 8
    minute: int = 0
    duration_min: int = 5

    def as_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "hour": int(self.hour),
            "minute": int(self.minute),
            "duration_min": int(self.duration_min),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> ScheduleSlot:
        if not data:
            return cls(False, 0, 0, 5)
        return cls(
            enabled=bool(data.get("enabled", False)),
            hour=max(0, min(23, int(data.get("hour", 0)))),
            minute=max(0, min(59, int(data.get("minute", 0)))),
            duration_min=max(1, min(120, int(data.get("duration_min", 5)))),
        )


def normalize_schedule(raw: list[Any] | None, *, slots: int = 5) -> list[ScheduleSlot]:
    """Pad / trim to fixed slot count for UI + persistence."""
    out: list[ScheduleSlot] = []
    for item in raw or []:
        if isinstance(item, ScheduleSlot):
            out.append(item)
        elif isinstance(item, dict):
            out.append(ScheduleSlot.from_dict(item))
    while len(out) < slots:
        out.append(ScheduleSlot(False, 0, 0, 5))
    return out[:slots]


@dataclass
class PublicSnapshot:
    """Operator-facing state published to HA entities."""

    status: str = "ready"
    health_score: int = 100
    system_mode: str = "Semi-Auto"
    plant_id: str = "generic"
    plant_label: str = "Generic"
    growth_stage: str = "Vegetative"
    irrigation_state: str = "IDLE"
    dosing_state: str = "IDLE"
    calibration_state: str = "IDLE"
    auto_irrigation: bool = False
    auto_lighting: bool = True
    auto_ph: bool = False
    auto_ec: bool = False
    auto_stage: bool = False
    desired_ph: float = 6.2
    ph_tolerance: float = 0.3
    desired_ec_tds: float = 400.0
    desired_ec: float = 0.8
    ec_tolerance: float = 50.0
    ec_tolerance_ms: float = 0.1
    tds_factor: int = 500
    sow_date: str | None = None
    days_after_sow: int | None = None
    water_ok: bool = False
    estop_active: bool = False
    refill_requested: bool = False
    simulation: bool = False
    last_error: str | None = None
    last_event: str | None = None
    warnings: list[str] = field(default_factory=list)
    active_alarm: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "health_score": self.health_score,
            "system_mode": self.system_mode,
            "plant_id": self.plant_id,
            "plant_label": self.plant_label,
            "growth_stage": self.growth_stage,
            "irrigation_state": self.irrigation_state,
            "dosing_state": self.dosing_state,
            "calibration_state": self.calibration_state,
            "auto_irrigation": self.auto_irrigation,
            "auto_lighting": self.auto_lighting,
            "auto_ph": self.auto_ph,
            "auto_ec": self.auto_ec,
            "auto_stage": self.auto_stage,
            "desired_ph": self.desired_ph,
            "ph_tolerance": self.ph_tolerance,
            "desired_ec_tds": self.desired_ec_tds,
            "desired_ec": self.desired_ec,
            "ec_tolerance": self.ec_tolerance,
            "ec_tolerance_ms": self.ec_tolerance_ms,
            "tds_factor": self.tds_factor,
            "sow_date": self.sow_date,
            "days_after_sow": self.days_after_sow,
            "water_ok": self.water_ok,
            "estop_active": self.estop_active,
            "refill_requested": self.refill_requested,
            "simulation": self.simulation,
            "last_error": self.last_error,
            "last_event": self.last_event,
            "warnings": list(self.warnings),
            "active_alarm": self.active_alarm,
        }
