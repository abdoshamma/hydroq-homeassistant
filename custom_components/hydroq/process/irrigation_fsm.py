"""Irrigation process state machine."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import time


class IrrigationState(StrEnum):
    IDLE = "IDLE"
    PRECHECK = "PRECHECK"
    RUNNING = "RUNNING"
    COMPLETE = "COMPLETE"
    FAULT = "FAULT"
    ABORTED = "ABORTED"


@dataclass
class IrrigationContext:
    duration_s: float = 0.0
    event_number: int | None = None
    started_monotonic: float = 0.0
    fault_reason: str | None = None


class IrrigationFSM:
    def __init__(self) -> None:
        self.state = IrrigationState.IDLE
        self.ctx = IrrigationContext()

    @property
    def busy(self) -> bool:
        return self.state in (IrrigationState.PRECHECK, IrrigationState.RUNNING)

    def start(self, duration_s: float, event_number: int | None = None) -> bool:
        if self.state not in (IrrigationState.IDLE, IrrigationState.COMPLETE, IrrigationState.ABORTED):
            if self.state != IrrigationState.FAULT:
                return False
        self.ctx = IrrigationContext(
            duration_s=duration_s,
            event_number=event_number,
            started_monotonic=time.monotonic(),
        )
        self.state = IrrigationState.PRECHECK
        return True

    def precheck_pass(self) -> None:
        if self.state == IrrigationState.PRECHECK:
            self.state = IrrigationState.RUNNING
            self.ctx.started_monotonic = time.monotonic()

    def precheck_fail(self, reason: str) -> None:
        if self.state == IrrigationState.PRECHECK:
            self.ctx.fault_reason = reason
            self.state = IrrigationState.FAULT

    def tick_running(self) -> bool:
        """Return True when duration elapsed."""
        if self.state != IrrigationState.RUNNING:
            return False
        elapsed = time.monotonic() - self.ctx.started_monotonic
        return elapsed >= self.ctx.duration_s

    def complete(self) -> None:
        self.state = IrrigationState.COMPLETE

    def abort(self, reason: str = "aborted") -> None:
        self.ctx.fault_reason = reason
        self.state = IrrigationState.ABORTED

    def fault(self, reason: str) -> None:
        self.ctx.fault_reason = reason
        self.state = IrrigationState.FAULT

    def reset_to_idle(self) -> None:
        self.state = IrrigationState.IDLE
        self.ctx = IrrigationContext()
