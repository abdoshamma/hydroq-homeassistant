"""Alarm evaluation — no actuator control."""

from __future__ import annotations

from datetime import datetime, timedelta

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
        self.active = False
        self.refill_requested = False

    def snapshot(self) -> dict:
        return {
            "active": self.active,
            "warnings": list(self.warnings),
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
        if safety.estop_active:
            warnings.append("emergency_stop")
            if self._cool("estop"):
                events.append(
                    DomainEvent("alarm.estop", "Emergency stop active", "error", process="safety")
                )
        if not safety.water_ok:
            warnings.append("tank_empty")
            self.refill_requested = True
            if self._cool("water"):
                events.append(
                    DomainEvent("alarm.water", "Water level low", "warning", process="safety")
                )
        if safety.ph is not None and abs(safety.ph - self.desired_ph) > self.ph_tolerance:
            warnings.append("ph_out_of_range")
            if self._cool("ph"):
                events.append(
                    DomainEvent(
                        "alarm.ph_range",
                        f"pH {safety.ph:.2f} out of range",
                        "warning",
                        process="dosing",
                    )
                )
        if safety.tds is not None and abs(safety.tds - self.desired_tds) > self.ec_tolerance:
            warnings.append("ec_out_of_range")
            if self._cool("ec"):
                events.append(
                    DomainEvent(
                        "alarm.ec_range",
                        f"TDS {safety.tds:.0f} out of range",
                        "warning",
                        process="dosing",
                    )
                )
        self.warnings = warnings
        self.active = bool(warnings)
        return events

    def request_refill(self) -> list[DomainEvent]:
        self.refill_requested = True
        return [DomainEvent("alarm.refill_requested", "Reservoir refill requested", "info")]
