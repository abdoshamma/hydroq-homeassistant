"""Irrigation manager — owns IrrigationFSM; uses HAL only."""

from __future__ import annotations

import asyncio
import logging

from ..controller.events import DomainEvent
from ..hardware.hal import HardwareHAL
from ..models.capability import ChannelRole
from ..models.runtime import ScheduleSlot
from ..process.irrigation_fsm import IrrigationFSM, IrrigationState

_LOGGER = logging.getLogger(__name__)


class IrrigationManager:
    def __init__(self, hal: HardwareHAL) -> None:
        self.hal = hal
        self.fsm = IrrigationFSM()
        self.auto_enabled = False
        self.schedule: list[ScheduleSlot] = [
            ScheduleSlot(True, 8, 0, 5),
            ScheduleSlot(True, 12, 0, 5),
            ScheduleSlot(True, 16, 0, 5),
            ScheduleSlot(True, 20, 0, 5),
            ScheduleSlot(True, 22, 0, 5),
        ]
        self._last_fired: str | None = None
        self._task: asyncio.Task | None = None

    def snapshot(self) -> dict:
        return {
            "state": self.fsm.state.value,
            "auto": self.auto_enabled,
            "busy": self.fsm.busy,
            "fault": self.fsm.ctx.fault_reason,
            "schedule": [s.as_dict() for s in self.schedule],
        }

    def set_slot(
        self,
        index: int,
        *,
        enabled: bool | None = None,
        hour: int | None = None,
        minute: int | None = None,
        duration_min: int | None = None,
    ) -> bool:
        """Update one 1-based schedule slot. Clears fire latch so new time can run today."""
        if index < 1 or index > len(self.schedule):
            return False
        slot = self.schedule[index - 1]
        if enabled is not None:
            slot.enabled = bool(enabled)
        if hour is not None:
            slot.hour = max(0, min(23, int(hour)))
        if minute is not None:
            slot.minute = max(0, min(59, int(minute)))
        if duration_min is not None:
            slot.duration_min = max(1, min(120, int(duration_min)))
        self._last_fired = None
        return True


    async def start(
        self, duration_min: float, event_number: int | None, safety_ok: bool, reason: str | None
    ) -> list[DomainEvent]:
        events: list[DomainEvent] = []
        if self.fsm.busy:
            return [DomainEvent("irrigation.rejected", "Already running", "warning")]
        if not self.hal.has(ChannelRole.IRRIGATION.value):
            return [DomainEvent("irrigation.rejected", "No irrigation channel", "error")]

        if not self.fsm.start(duration_min * 60.0, event_number):
            return [DomainEvent("irrigation.rejected", "Invalid state", "warning")]

        events.append(
            DomainEvent(
                "irrigation.started",
                f"Irrigation starting ({duration_min} min)",
                process="irrigation",
                data={"event_number": event_number, "duration_min": duration_min},
            )
        )
        if not safety_ok:
            self.fsm.precheck_fail(reason or "safety")
            events.append(
                DomainEvent(
                    "irrigation.fault",
                    f"Precheck failed: {reason}",
                    "error",
                    process="irrigation",
                )
            )
            return events

        self.fsm.precheck_pass()
        self._cancel()
        self._task = asyncio.create_task(self._run())
        return events

    async def stop(self, reason: str = "stop") -> list[DomainEvent]:
        self._cancel()
        await self.hal.set_output(ChannelRole.IRRIGATION.value, 0)
        if self.fsm.busy:
            self.fsm.abort(reason)
        else:
            self.fsm.reset_to_idle()
        return [
            DomainEvent(
                "irrigation.aborted" if reason != "complete" else "irrigation.completed",
                f"Irrigation {reason}",
                process="irrigation",
            )
        ]

    async def ack_fault(self) -> None:
        self.fsm.reset_to_idle()

    async def _run(self) -> None:
        try:
            await self.hal.set_output(ChannelRole.IRRIGATION.value, 100)
            while self.fsm.state == IrrigationState.RUNNING:
                if self.fsm.tick_running():
                    break
                await asyncio.sleep(1)
            await self.hal.set_output(ChannelRole.IRRIGATION.value, 0)
            if self.fsm.state == IrrigationState.RUNNING:
                self.fsm.complete()
        except asyncio.CancelledError:
            await self.hal.set_output(ChannelRole.IRRIGATION.value, 0)
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Irrigation fault")
            await self.hal.set_output(ChannelRole.IRRIGATION.value, 0)
            self.fsm.fault(str(err))

    def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    def schedule_due(self, now) -> tuple[int, ScheduleSlot] | None:
        """Return (index, slot) if a daily event should start now. Does not latch."""
        if self.fsm.busy:
            return None
        day = now.strftime("%Y-%m-%d")
        now_m = int(now.hour) * 60 + int(now.minute)
        for idx, slot in enumerate(self.schedule, start=1):
            if not slot.enabled:
                continue
            key = f"{day}:{idx}:{slot.hour:02d}:{slot.minute:02d}"
            if self._last_fired == key:
                continue
            slot_m = slot.hour * 60 + slot.minute
            # Exact minute, or up to 2 min late (missed tick / HA lag)
            delta = now_m - slot_m
            if 0 <= delta <= 2:
                return idx, slot
        return None

    def mark_schedule_fired(self, now, index: int, slot: ScheduleSlot) -> None:
        day = now.strftime("%Y-%m-%d")
        self._last_fired = f"{day}:{index}:{slot.hour:02d}:{slot.minute:02d}"
