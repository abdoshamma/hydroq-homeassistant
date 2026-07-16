"""Periodic tick source — notifies controller via callback only."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.event import async_track_time_interval

from ..const import SCHEDULER_TICK_S

TickCb = Callable[[datetime], Awaitable[None]]


class SchedulerManager:
    def __init__(self, hass: HomeAssistant) -> None:
        self.hass = hass
        self._unsub = None
        self._cb: TickCb | None = None

    def set_callback(self, cb: TickCb) -> None:
        self._cb = cb

    def start(self) -> None:
        if self._unsub:
            return

        @callback
        def _handle(now: datetime) -> None:
            if self._cb:
                self.hass.async_create_task(self._cb(now))

        self._unsub = async_track_time_interval(
            self.hass, _handle, timedelta(seconds=SCHEDULER_TICK_S)
        )

    def stop(self) -> None:
        if self._unsub:
            self._unsub()
            self._unsub = None
