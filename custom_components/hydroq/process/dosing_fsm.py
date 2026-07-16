"""Dosing process state machine (pH / nutrients / neutralize)."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
import time


class DosingState(StrEnum):
    IDLE = "IDLE"
    PRECHECK = "PRECHECK"
    PULSE_ON = "PULSE_ON"
    PULSE_OFF = "PULSE_OFF"
    EVALUATE = "EVALUATE"
    COMPLETE = "COMPLETE"
    LIMIT = "LIMIT"
    FAULT = "FAULT"
    ABORTED = "ABORTED"


class DosingProcess(StrEnum):
    PH = "ph"
    NUTRIENTS = "nutrients"
    NEUTRALIZE = "neutralize"


@dataclass
class DosingContext:
    process: DosingProcess = DosingProcess.PH
    started_monotonic: float = 0.0
    pulse_count: int = 0
    max_seconds: float = 600.0
    max_pulses: int = 60
    fault_reason: str | None = None
    pump_percent: float = 0.0


class DosingFSM:
    def __init__(self) -> None:
        self.state = DosingState.IDLE
        self.ctx = DosingContext()

    @property
    def busy(self) -> bool:
        return self.state not in (
            DosingState.IDLE,
            DosingState.COMPLETE,
            DosingState.FAULT,
            DosingState.ABORTED,
            DosingState.LIMIT,
        )

    def start(self, process: DosingProcess, max_seconds: float = 600.0) -> bool:
        if self.busy:
            return False
        self.ctx = DosingContext(
            process=process,
            started_monotonic=time.monotonic(),
            max_seconds=max_seconds,
        )
        self.state = DosingState.PRECHECK
        return True

    def precheck_pass(self) -> None:
        if self.state == DosingState.PRECHECK:
            self.state = DosingState.PULSE_ON

    def precheck_fail(self, reason: str) -> None:
        self.ctx.fault_reason = reason
        self.state = DosingState.FAULT

    def pulse_on_done(self) -> None:
        if self.state == DosingState.PULSE_ON:
            self.ctx.pulse_count += 1
            self.state = DosingState.PULSE_OFF

    def pulse_off_done(self) -> None:
        if self.state == DosingState.PULSE_OFF:
            self.state = DosingState.EVALUATE

    def continue_pulsing(self) -> None:
        if self.state == DosingState.EVALUATE:
            self.state = DosingState.PULSE_ON

    def complete(self) -> None:
        self.state = DosingState.COMPLETE

    def hit_limit(self, reason: str = "max_runtime") -> None:
        self.ctx.fault_reason = reason
        self.state = DosingState.LIMIT

    def abort(self, reason: str = "aborted") -> None:
        self.ctx.fault_reason = reason
        self.state = DosingState.ABORTED

    def fault(self, reason: str) -> None:
        self.ctx.fault_reason = reason
        self.state = DosingState.FAULT

    def reset_to_idle(self) -> None:
        self.state = DosingState.IDLE
        self.ctx = DosingContext()

    def overtime(self) -> bool:
        return (time.monotonic() - self.ctx.started_monotonic) >= self.ctx.max_seconds

    def over_pulses(self) -> bool:
        return self.ctx.pulse_count >= self.ctx.max_pulses
