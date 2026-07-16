"""Calibration process state machine."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum


class CalibrationState(StrEnum):
    IDLE = "IDLE"
    PROMPT_POINT = "PROMPT_POINT"
    SAMPLE = "SAMPLE"
    STORE = "STORE"
    COMPLETE = "COMPLETE"
    FAULT = "FAULT"


@dataclass
class CalibrationContext:
    points: list[str] = field(default_factory=list)
    index: int = 0
    kind: str = "ph"  # ph | tds | do
    fault_reason: str | None = None

    @property
    def current_point(self) -> str | None:
        if 0 <= self.index < len(self.points):
            return self.points[self.index]
        return None


class CalibrationFSM:
    def __init__(self) -> None:
        self.state = CalibrationState.IDLE
        self.ctx = CalibrationContext()

    @property
    def busy(self) -> bool:
        return self.state in (
            CalibrationState.PROMPT_POINT,
            CalibrationState.SAMPLE,
            CalibrationState.STORE,
        )

    def start(self, kind: str, points: list[str]) -> bool:
        if self.busy:
            return False
        self.ctx = CalibrationContext(points=list(points), kind=kind)
        self.state = CalibrationState.PROMPT_POINT
        return True

    def begin_sample(self) -> None:
        if self.state == CalibrationState.PROMPT_POINT:
            self.state = CalibrationState.SAMPLE

    def store_ok(self) -> None:
        if self.state != CalibrationState.SAMPLE:
            return
        self.state = CalibrationState.STORE
        self.ctx.index += 1
        if self.ctx.index >= len(self.ctx.points):
            self.state = CalibrationState.COMPLETE
        else:
            self.state = CalibrationState.PROMPT_POINT

    def fault(self, reason: str) -> None:
        self.ctx.fault_reason = reason
        self.state = CalibrationState.FAULT

    def reset_to_idle(self) -> None:
        self.state = CalibrationState.IDLE
        self.ctx = CalibrationContext()
