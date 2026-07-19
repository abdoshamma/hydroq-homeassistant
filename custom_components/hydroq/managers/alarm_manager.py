"""Alarm evaluation — no actuator control."""

from __future__ import annotations

from datetime import datetime, timedelta

from ..const import CAL_DUE_DAYS
from ..controller.events import DomainEvent
from ..managers.device_manager import SafetyReading


class AlarmManager:
    def __init__(self) -> None:
        self.desired_ph = 6.2
        self.ph_tolerance = 0.3
        self.desired_tds = 400.0
        self.ec_tolerance = 50.0
        self._last: dict[str, datetime] = {}
        self.warnings: list[str] = []
        self.messages: list[str] = []
        self.active = False
        self.refill_requested = False
        self._cal_due: list[str] = []

    def set_cal_due(self, labels: list[str]) -> None:
        self._cal_due = list(labels)

    @property
    def message(self) -> str:
        """Human-readable active problems, or Clear."""
        if not self.messages:
            return "Clear"
        return " · ".join(self.messages)

    def snapshot(self) -> dict:
        return {
            "active": self.active,
            "warnings": list(self.warnings),
            "messages": list(self.messages),
            "message": self.message,
            "refill_requested": self.refill_requested,
        }

    def _cool(self, key: str, minutes: int = 15) -> bool:
        now = datetime.now()
        last = self._last.get(key)
        if last and now - last < timedelta(minutes=minutes):
            return False
        self._last[key] = now
        return True

    def evaluate(self, safety: SafetyReading) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        warnings: list[str] = []
        messages: list[str] = []
        if safety.estop_active:
            warnings.append("emergency_stop")
            messages.append("Emergency stop active")
            if self._cool("estop"):
                events.append(
                    DomainEvent("alarm.estop", "Emergency stop active", "error", process="safety")
                )
        if safety.leak_active:
            warnings.append("leak")
            messages.append("Leak detected — pumps stopped")
            if self._cool("leak", minutes=5):
                events.append(
                    DomainEvent("alarm.leak", "Leak detected", "error", process="safety")
                )
        if not safety.water_ok:
            warnings.append("tank_empty")
            messages.append("Tank empty — refill reservoir")
            self.refill_requested = True
            if self._cool("water"):
                events.append(
                    DomainEvent("alarm.water", "Water level low", "warning", process="safety")
                )
        if safety.ph is not None and abs(safety.ph - self.desired_ph) > self.ph_tolerance:
            warnings.append("ph_out_of_range")
            msg = (
                f"pH {safety.ph:.2f} out of range "
                f"(target {self.desired_ph:.1f} ± {self.ph_tolerance:.1f})"
            )
            messages.append(msg)
            if self._cool("ph"):
                events.append(
                    DomainEvent("alarm.ph_range", msg, "warning", process="dosing")
                )
        if safety.tds is not None and abs(safety.tds - self.desired_tds) > self.ec_tolerance:
            warnings.append("ec_out_of_range")
            msg = (
                f"TDS {safety.tds:.0f} out of range "
                f"(target {self.desired_tds:.0f} ± {self.ec_tolerance:.0f})"
            )
            messages.append(msg)
            if self._cool("ec"):
                events.append(
                    DomainEvent("alarm.ec_range", msg, "warning", process="dosing")
                )
        for label in self._cal_due:
            key = f"cal_{label.lower()}_due"
            warnings.append(key)
            messages.append(f"{label} calibration overdue (≥{CAL_DUE_DAYS}d)")
        self.warnings = warnings
        self.messages = messages
        self.active = bool(warnings)
        return events

    def request_refill(self) -> list[DomainEvent]:
        self.refill_requested = True
        return [DomainEvent("alarm.refill_requested", "Reservoir refill requested", "info")]
