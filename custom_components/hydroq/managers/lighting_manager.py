"""Lighting manager — HAL only."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime

from ..controller.events import DomainEvent
from ..hardware.hal import HardwareHAL
from ..models.capability import ChannelRole

_LOGGER = logging.getLogger(__name__)

STAGGER_S = 1.0


class LightingManager:
    def __init__(self, hal: HardwareHAL) -> None:
        self.hal = hal
        self.auto_enabled = False
        self.on_hour = 6
        self.on_minute = 0
        self.off_hour = 22
        self.off_minute = 0
        self._last_on: bool | None = None
        self._task: asyncio.Task | None = None

    def snapshot(self) -> dict:
        return {
            "auto": self.auto_enabled,
            "on": f"{self.on_hour:02d}:{self.on_minute:02d}",
            "off": f"{self.off_hour:02d}:{self.off_minute:02d}",
            "lights_on": self._last_on,
        }

    def should_be_on(self, now: datetime) -> bool:
        now_m = now.hour * 60 + now.minute
        on_m = self.on_hour * 60 + self.on_minute
        off_m = self.off_hour * 60 + self.off_minute
        if on_m == off_m:
            return False
        if on_m < off_m:
            return on_m <= now_m < off_m
        return now_m >= on_m or now_m < off_m

    def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def set_all(
        self,
        on: bool,
        *,
        estop: bool = False,
        stagger_s: float = STAGGER_S,
    ) -> list[DomainEvent]:
        if on and estop:
            return [DomainEvent("lighting.blocked", "E-stop active", "warning")]
        if not self.hal.has(ChannelRole.LIGHTING.value):
            return []

        delay = 0.0 if estop else max(0.0, float(stagger_s))
        # Optimistic so All Lights toggle flips immediately
        self._last_on = on
        self._cancel()

        if delay <= 0:
            await self.hal.set_group(ChannelRole.LIGHTING.value, on, stagger_s=0.0)
        else:
            self._task = asyncio.create_task(
                self._run_stagger(on, delay),
                name="hydroq_lights_stagger",
            )

        return [
            DomainEvent(
                "lighting.on" if on else "lighting.off",
                "Lights "
                + ("on" if on else "off")
                + (" (1s/stand)" if delay > 0 else ""),
                process="lighting",
            )
        ]

    async def _run_stagger(self, on: bool, stagger_s: float) -> None:
        try:
            await self.hal.set_group(
                ChannelRole.LIGHTING.value, on, stagger_s=stagger_s
            )
        except asyncio.CancelledError:
            _LOGGER.debug("Lighting stagger cancelled (target=%s)", on)
            raise
        except Exception:  # noqa: BLE001
            _LOGGER.exception("Lighting stagger failed")

    async def tick_auto(self, now: datetime, estop: bool) -> list[DomainEvent]:
        if not self.auto_enabled:
            return []
        if estop:
            return await self.set_all(False, stagger_s=0.0)
        desired = self.should_be_on(now)
        if self._last_on is not None and self._last_on == desired:
            return []
        return await self.set_all(desired, estop=False, stagger_s=STAGGER_S)
