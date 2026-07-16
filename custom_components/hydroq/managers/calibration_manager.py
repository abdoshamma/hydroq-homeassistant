"""Calibration manager — owns CalibrationFSM."""

from __future__ import annotations

from datetime import datetime, timezone

from ..controller.events import DomainEvent
from ..hardware.hal import HardwareHAL
from ..process.calibration_fsm import CalibrationFSM, CalibrationState


class CalibrationManager:
    def __init__(self, hal: HardwareHAL) -> None:
        self.hal = hal
        self.fsm = CalibrationFSM()
        self.last_ph: datetime | None = None
        self.last_tds: datetime | None = None
        self.last_do: datetime | None = None

    def snapshot(self) -> dict:
        return {
            "state": self.fsm.state.value,
            "point": self.fsm.ctx.current_point,
            "last_ph": None if self.last_ph is None else self.last_ph.isoformat(),
            "last_tds": None if self.last_tds is None else self.last_tds.isoformat(),
            "last_do": None if self.last_do is None else self.last_do.isoformat(),
        }

    async def calibrate_point(self, kind: str, point: str) -> list[DomainEvent]:
        """Single-shot calibration press driven through CalibrationFSM."""
        cal_role = {
            ("ph", "neutral"): "ph_neutral",
            ("ph", "acid"): "ph_acid",
            ("ph", "6.86"): "ph_neutral",
            ("ph", "4.0"): "ph_acid",
            ("tds", "std"): "tds",
            ("do", "air"): "do",
        }.get((kind, point))
        if not cal_role:
            return [DomainEvent("calibration.rejected", f"Unknown point {kind}/{point}", "error")]

        if self.fsm.busy:
            self.fsm.reset_to_idle()

        if not self.fsm.start(kind, [point]):
            return [DomainEvent("calibration.rejected", "Invalid calibration state", "warning")]

        self.fsm.begin_sample()
        ok = await self.hal.press_button(cal_role)
        if not ok:
            self.fsm.fault("button_unavailable")
            self.fsm.reset_to_idle()
            return [DomainEvent("calibration.fault", "Button unavailable", "error")]

        self.fsm.store_ok()
        now = datetime.now(timezone.utc)
        if kind == "ph":
            self.last_ph = now
        elif kind == "tds":
            self.last_tds = now
        else:
            self.last_do = now

        if self.fsm.state == CalibrationState.COMPLETE:
            self.fsm.reset_to_idle()

        return [
            DomainEvent(
                "calibration.done",
                f"Calibrated {kind} {point}",
                process="calibration",
                data={"kind": kind, "point": point},
            )
        ]
