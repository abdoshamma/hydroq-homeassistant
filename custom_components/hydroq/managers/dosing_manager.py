"""Dosing manager — owns DosingFSM; HAL only.

Nutrient dosing matches legacy scripts2.yaml zone1_dose_nutrients:
  Phase A → Solution A only until mid-TDS
  Phase B → Solution B only until desired TDS
  Pump speed proportional to remaining error (10–100%)
  5s on / 5s off pulses, max 300s
Neutralize (high TDS) uses Solution C only (legacy zone1_neutralize_tds).
"""

from __future__ import annotations

import asyncio
import logging
import time

from ..const import (
    DEFAULT_MAX_DOSE_ML_DAY,
    DOSING_LIMIT_COOLDOWN_S,
    DOSING_PULSE_OFF_S,
    DOSING_PULSE_ON_S,
    MAX_DOSING_SECONDS,
)
from ..controller.events import DomainEvent
from ..hardware.hal import HardwareHAL
from ..models.capability import ChannelRole, SensorRole
from ..process.dosing_fsm import DosingFSM, DosingProcess, DosingState
from ..util import valid_float

_LOGGER = logging.getLogger(__name__)

NUTRIENT_MAX_S = 300.0
PUMP_MIN_PCT = 10.0
PUMP_MAX_PCT = 100.0


class DosingManager:
    def __init__(self, hal: HardwareHAL) -> None:
        self.hal = hal
        self.fsm = DosingFSM()
        self.auto_ph = False
        self.auto_ec = False
        self.desired_ph = 6.2
        self.ph_tolerance = 0.3
        self.desired_tds = 400.0
        self.ec_tolerance = 50.0
        self.max_ml_day = DEFAULT_MAX_DOSE_ML_DAY
        self.ml_today = 0.0
        self._ml_day = ""
        self._limit_cooldown_until = 0.0
        self._task: asyncio.Task | None = None
        self._active_ph_channels: list[str] = []

    def snapshot(self) -> dict:
        return {
            "state": self.fsm.state.value,
            "process": self.fsm.ctx.process.value
            if self.fsm.busy or self.fsm.state != DosingState.IDLE
            else None,
            "auto_ph": self.auto_ph,
            "auto_ec": self.auto_ec,
            "busy": self.fsm.busy,
            "fault": self.fsm.ctx.fault_reason,
            "ml_today": self.ml_today,
            "max_ml_day": self.max_ml_day,
        }

    def _roll_day(self) -> None:
        day = time.strftime("%Y-%m-%d")
        if day != self._ml_day:
            self._ml_day = day
            self.ml_today = 0.0

    def _ml_per_min(self, channel: str) -> float:
        ch = self.hal.capabilities.actuators.get(channel)
        if ch is None:
            return 50.0
        return max(0.0, float(ch.ml_per_min))

    def _account_pulse(self, channel: str, pct: float, on_s: float) -> bool:
        """Add ml for this pulse. False if daily budget would be exceeded."""
        self._roll_day()
        ml = self._ml_per_min(channel) * (max(0.0, pct) / 100.0) * (on_s / 60.0)
        if self.ml_today + ml > self.max_ml_day:
            return False
        self.ml_today += ml
        return True

    def _channels_for(self, process: DosingProcess) -> list[str]:
        if process == DosingProcess.PH:
            out: list[str] = []
            if self.hal.has(ChannelRole.PH_UP.value):
                out.append(ChannelRole.PH_UP.value)
            if self.hal.has(ChannelRole.PH_DOWN.value):
                out.append(ChannelRole.PH_DOWN.value)
            return out
        if process == DosingProcess.NUTRIENTS:
            out = []
            if self.hal.has(ChannelRole.NUTRIENT_A.value):
                out.append(ChannelRole.NUTRIENT_A.value)
            if self.hal.has(ChannelRole.NUTRIENT_B.value):
                out.append(ChannelRole.NUTRIENT_B.value)
            return out
        if process == DosingProcess.NEUTRALIZE:
            if self.hal.has(ChannelRole.NEUTRALIZATION.value):
                return [ChannelRole.NEUTRALIZATION.value]
            if self.hal.has(ChannelRole.NUTRIENT_C.value):
                return [ChannelRole.NUTRIENT_C.value]
        return []

    async def _ph_channels_for_reading(self, ph: float | None) -> list[str]:
        if ph is None:
            return self._channels_for(DosingProcess.PH)[:1]
        if ph < self.desired_ph and self.hal.has(ChannelRole.PH_UP.value):
            return [ChannelRole.PH_UP.value]
        if ph > self.desired_ph and self.hal.has(ChannelRole.PH_DOWN.value):
            return [ChannelRole.PH_DOWN.value]
        return self._channels_for(DosingProcess.PH)[:1]

    async def start(
        self, process: DosingProcess, safety_ok: bool, reason: str | None
    ) -> list[DomainEvent]:
        if self.fsm.busy:
            return [DomainEvent("dosing.rejected", "Dosing already active", "warning")]
        if time.monotonic() < self._limit_cooldown_until:
            return [
                DomainEvent(
                    "dosing.rejected",
                    "Cooldown budget / limit cooldown active",
                    "warning",
                    process="dosing",
                )
            ]
        self._roll_day()
        if self.ml_today >= self.max_ml_day:
            return [
                DomainEvent(
                    "dosing.rejected",
                    f"Daily dose budget reached ({self.max_ml_day:.0f} ml)",
                    "warning",
                    process="dosing",
                )
            ]

        channels = self._channels_for(process)
        if process == DosingProcess.PH:
            ph = valid_float(await self.hal.read_sensor(SensorRole.PH.value))
            channels = await self._ph_channels_for_reading(ph)
        if not channels:
            return [
                DomainEvent(
                    "dosing.rejected", f"No channels for {process.value}", "error"
                )
            ]
        max_s = NUTRIENT_MAX_S if process == DosingProcess.NUTRIENTS else MAX_DOSING_SECONDS
        if not self.fsm.start(process, max_s):
            return [DomainEvent("dosing.rejected", "Invalid state", "warning")]

        events = [
            DomainEvent(
                f"dosing.{process.value}.started",
                f"Dosing {process.value} started",
                process="dosing",
            )
        ]
        if not safety_ok:
            self.fsm.precheck_fail(reason or "safety")
            events.append(
                DomainEvent(
                    "dosing.fault",
                    f"Precheck failed: {reason}",
                    "error",
                    process="dosing",
                )
            )
            return events

        self.fsm.precheck_pass()
        self._cancel()
        self._active_ph_channels = list(channels) if process == DosingProcess.PH else []
        if process == DosingProcess.NUTRIENTS:
            self._task = asyncio.create_task(self._run_nutrients())
        else:
            self._task = asyncio.create_task(self._run_pulse(channels))
        return events

    async def stop(self, reason: str = "stop") -> list[DomainEvent]:
        self._cancel()
        await self._all_off()
        if self.fsm.busy:
            self.fsm.abort(reason)
        else:
            self.fsm.reset_to_idle()
        return [DomainEvent("dosing.stopped", f"Dosing {reason}", process="dosing")]

    async def ack_fault(self) -> None:
        self.fsm.reset_to_idle()

    async def _read_tds(self) -> float | None:
        return valid_float(await self.hal.read_sensor(SensorRole.TDS.value))

    @staticmethod
    def _clamp_pct(raw: float) -> float:
        return max(PUMP_MIN_PCT, min(PUMP_MAX_PCT, raw))

    def _mark_limit_cooldown(self) -> None:
        self._limit_cooldown_until = time.monotonic() + DOSING_LIMIT_COOLDOWN_S

    async def _run_nutrients(self) -> None:
        try:
            tds0 = await self._read_tds()
            if tds0 is None:
                await self._all_off()
                self.fsm.fault("tds_unavailable")
                return

            desired = float(self.desired_tds)
            if tds0 >= desired:
                self.fsm.complete()
                return

            half = (desired - tds0) / 2.0 + tds0

            if self.hal.has(ChannelRole.NUTRIENT_A.value) and tds0 < half:
                ok = await self._pulse_until(
                    ChannelRole.NUTRIENT_A.value,
                    target_fn=lambda t: t >= half,
                    speed_fn=lambda t: self._clamp_pct(
                        ((half - t) / half * 100.0) if half > 0 else 50.0
                    ),
                )
                if not ok:
                    return

            if self.hal.has(ChannelRole.NUTRIENT_B.value):
                span = max(desired - half, 1.0)
                ok = await self._pulse_until(
                    ChannelRole.NUTRIENT_B.value,
                    target_fn=lambda t: t >= desired,
                    speed_fn=lambda t: self._clamp_pct((desired - t) / span * 100.0),
                )
                if not ok:
                    return
            elif self.hal.has(ChannelRole.NUTRIENT_A.value):
                ok = await self._pulse_until(
                    ChannelRole.NUTRIENT_A.value,
                    target_fn=lambda t: t >= desired,
                    speed_fn=lambda t: self._clamp_pct(
                        ((desired - t) / desired * 100.0) if desired > 0 else 50.0
                    ),
                )
                if not ok:
                    return

            if self.fsm.state not in (DosingState.LIMIT, DosingState.FAULT, DosingState.ABORTED):
                self.fsm.complete()
        except asyncio.CancelledError:
            await self._all_off()
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Nutrient dosing fault")
            await self._all_off()
            self.fsm.fault(str(err))

    async def _pulse_until(
        self,
        channel: str,
        *,
        target_fn,
        speed_fn,
    ) -> bool:
        while self.fsm.state in (
            DosingState.PULSE_ON,
            DosingState.PULSE_OFF,
            DosingState.EVALUATE,
        ):
            if self.fsm.overtime() or self.fsm.over_pulses():
                await self._all_off()
                self.fsm.hit_limit()
                self._mark_limit_cooldown()
                return False

            if self.fsm.state == DosingState.PULSE_ON:
                tds = await self._read_tds()
                if tds is None:
                    await self._all_off()
                    self.fsm.fault("tds_unavailable")
                    return False
                if target_fn(tds):
                    await self._all_off()
                    return True
                pct = float(speed_fn(tds))
                if not self._account_pulse(channel, pct, DOSING_PULSE_ON_S):
                    await self._all_off()
                    self.fsm.hit_limit()
                    self._mark_limit_cooldown()
                    return False
                self.fsm.ctx.pump_percent = pct
                await self.hal.set_output(channel, pct)
                await asyncio.sleep(DOSING_PULSE_ON_S)
                await self._all_off()
                self.fsm.pulse_on_done()
            elif self.fsm.state == DosingState.PULSE_OFF:
                await asyncio.sleep(DOSING_PULSE_OFF_S)
                self.fsm.pulse_off_done()
            elif self.fsm.state == DosingState.EVALUATE:
                tds = await self._read_tds()
                if tds is None:
                    await self._all_off()
                    self.fsm.fault("tds_unavailable")
                    return False
                if target_fn(tds):
                    return True
                self.fsm.continue_pulsing()
        return self.fsm.state not in (DosingState.FAULT, DosingState.LIMIT, DosingState.ABORTED)

    async def _run_pulse(self, channels: list[str]) -> None:
        process = self.fsm.ctx.process
        try:
            while self.fsm.state in (
                DosingState.PULSE_ON,
                DosingState.PULSE_OFF,
                DosingState.EVALUATE,
            ):
                if self.fsm.overtime() or self.fsm.over_pulses():
                    await self._all_off()
                    self.fsm.hit_limit()
                    self._mark_limit_cooldown()
                    return

                if self.fsm.state == DosingState.PULSE_ON:
                    pct = await self._dynamic_pump_percent(process)
                    if pct is None:
                        await self._all_off()
                        self.fsm.fault(
                            "ph_unavailable"
                            if process == DosingProcess.PH
                            else "tds_unavailable"
                        )
                        return
                    for ch in channels:
                        if not self._account_pulse(ch, pct, DOSING_PULSE_ON_S):
                            await self._all_off()
                            self.fsm.hit_limit()
                            self._mark_limit_cooldown()
                            return
                        await self.hal.set_output(ch, pct)
                    self.fsm.ctx.pump_percent = pct
                    await asyncio.sleep(DOSING_PULSE_ON_S)
                    await self._all_off()
                    self.fsm.pulse_on_done()
                elif self.fsm.state == DosingState.PULSE_OFF:
                    await asyncio.sleep(DOSING_PULSE_OFF_S)
                    self.fsm.pulse_off_done()
                elif self.fsm.state == DosingState.EVALUATE:
                    reached = await self._target_reached(process)
                    if self.fsm.state == DosingState.FAULT:
                        await self._all_off()
                        return
                    if reached:
                        self.fsm.complete()
                        return
                    self.fsm.continue_pulsing()
        except asyncio.CancelledError:
            await self._all_off()
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Dosing fault")
            await self._all_off()
            self.fsm.fault(str(err))

    async def _dynamic_pump_percent(self, process: DosingProcess) -> float | None:
        """Proportional speeds; None = sensor invalid → caller must FAULT."""
        if process == DosingProcess.PH:
            ph = valid_float(await self.hal.read_sensor(SensorRole.PH.value))
            if ph is None:
                return None
            return max(5.0, min(100.0, abs(self.desired_ph - ph) * 50.0))
        if process == DosingProcess.NEUTRALIZE:
            tds = await self._read_tds()
            if tds is None:
                return None
            denom = max(self.desired_tds + self.ec_tolerance, 1.0)
            raw = abs(float(tds) - self.desired_tds) / denom * 100.0
            return max(5.0, min(100.0, raw))
        return 50.0

    async def _target_reached(self, process: DosingProcess) -> bool:
        if process == DosingProcess.PH:
            ph = valid_float(await self.hal.read_sensor(SensorRole.PH.value))
            if ph is None:
                self.fsm.fault("ph_unavailable")
                return True
            using_down = ChannelRole.PH_DOWN.value in getattr(
                self, "_active_ph_channels", []
            )
            if using_down:
                return ph <= self.desired_ph
            return ph >= self.desired_ph
        tds = await self._read_tds()
        if tds is None:
            self.fsm.fault("tds_unavailable")
            return True
        if process == DosingProcess.NUTRIENTS:
            return tds >= self.desired_tds
        return tds <= self.desired_tds + self.ec_tolerance

    async def _all_off(self) -> None:
        for role in (
            ChannelRole.NUTRIENT_A.value,
            ChannelRole.NUTRIENT_B.value,
            ChannelRole.NUTRIENT_C.value,
            ChannelRole.PH_UP.value,
            ChannelRole.PH_DOWN.value,
            ChannelRole.NEUTRALIZATION.value,
        ):
            if self.hal.has(role):
                await self.hal.set_output(role, 0)

    def _cancel(self) -> None:
        if self._task and not self._task.done():
            self._task.cancel()
        self._task = None

    async def suggest_auto(self, ph: float | None, tds: float | None) -> DosingProcess | None:
        if self.fsm.busy:
            return None
        if time.monotonic() < self._limit_cooldown_until:
            return None
        self._roll_day()
        if self.ml_today >= self.max_ml_day:
            return None
        ph_v = valid_float(ph)
        tds_v = valid_float(tds)
        if self.auto_ph and ph_v is not None:
            if ph_v < self.desired_ph - self.ph_tolerance:
                if self.hal.has(ChannelRole.PH_UP.value):
                    return DosingProcess.PH
            elif ph_v > self.desired_ph + self.ph_tolerance:
                if self.hal.has(ChannelRole.PH_DOWN.value):
                    return DosingProcess.PH
        if self.auto_ec and tds_v is not None:
            if tds_v < self.desired_tds - self.ec_tolerance:
                if self._channels_for(DosingProcess.NUTRIENTS):
                    return DosingProcess.NUTRIENTS
            if tds_v > self.desired_tds + self.ec_tolerance:
                if self._channels_for(DosingProcess.NEUTRALIZE):
                    return DosingProcess.NEUTRALIZE
        return None
