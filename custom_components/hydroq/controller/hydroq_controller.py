"""HydroQController — sole orchestrator; managers never call each other."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Callable

from homeassistant.core import HomeAssistant
from homeassistant.util import dt as dt_util

from ..controller.commands import Command, CommandType
from ..controller.events import DomainEvent
from ..hardware.hal import HardwareHAL
from ..managers.alarm_manager import AlarmManager
from ..managers.calibration_manager import CalibrationManager
from ..managers.device_manager import DeviceManager
from ..managers.diagnostics_manager import DiagnosticsManager
from ..managers.dosing_manager import DosingManager
from ..managers.event_log_manager import EventLogManager
from ..managers.irrigation_manager import IrrigationManager
from ..managers.lighting_manager import LightingManager
from ..managers.recipe_manager import DEFAULT_TDS_FACTOR, RecipeManager, tds_to_ec
from ..managers.scheduler_manager import SchedulerManager
from ..models.capability import ChannelRole, SensorRole
from ..models.runtime import PublicSnapshot, normalize_schedule
from ..process.dosing_fsm import DosingProcess

_LOGGER = logging.getLogger(__name__)


class HydroQController:
    """Central controller for one grow zone instance."""

    def __init__(
        self,
        hass: HomeAssistant,
        hal: HardwareHAL,
        *,
        zone_name: str = "Zone",
        entry_id: str | None = None,
        event_store: Any | None = None,
        on_update: Callable[[], None] | None = None,
    ) -> None:
        self.hass = hass
        self.hal = hal
        self.zone_name = zone_name
        self.entry_id = entry_id
        self._on_update = on_update

        self.events = EventLogManager(store=event_store)
        self.device = DeviceManager(hal, hass)
        self.irrigation = IrrigationManager(hal)
        self.dosing = DosingManager(hal)
        self.lighting = LightingManager(hal)
        self.calibration = CalibrationManager(hal)
        self.recipes = RecipeManager()
        self.alarms = AlarmManager()
        self.diagnostics = DiagnosticsManager(hal, self.events)
        self.scheduler = SchedulerManager(hass)

        self.system_mode = "Manual"
        self.plant_id = "generic"
        self.growth_stage = "Vegetative"
        self.auto_stage = False
        self.sow_date: str | None = None  # YYYY-MM-DD local
        self.tds_factor = DEFAULT_TDS_FACTOR
        self.last_error: str | None = None
        self._persist_schedule: Callable[[], None] | None = None
        self._persist_calibration: Callable[[], None] | None = None
        self._persist_crop: Callable[[], None] | None = None
        self._balance_task: asyncio.Task | None = None
        self._cal_warn_day: str | None = None
        self._stage_advance_day: str | None = None

        self.scheduler.set_callback(self._on_tick)
        self.scheduler.start()

    def set_persist_schedule(self, cb: Callable[[], None] | None) -> None:
        self._persist_schedule = cb

    def set_persist_calibration(self, cb: Callable[[], None] | None) -> None:
        self._persist_calibration = cb

    def set_persist_crop(self, cb: Callable[[], None] | None) -> None:
        self._persist_crop = cb

    def _save_schedule(self) -> None:
        if self._persist_schedule:
            self._persist_schedule()

    def _save_calibration(self) -> None:
        if self._persist_calibration:
            self._persist_calibration()

    def _save_crop(self) -> None:
        if self._persist_crop:
            self._persist_crop()

    def load_custom_recipes(self, raw: dict[str, Any] | None) -> None:
        self.recipes.set_custom(raw)

    def days_after_sow(self, now: datetime | None = None) -> int | None:
        if not self.sow_date:
            return None
        try:
            y, m, d = (int(x) for x in self.sow_date.split("-", 2))
            sow = datetime(y, m, d).date()
        except ValueError:
            return None
        today = dt_util.as_local(now or dt_util.now()).date()
        return max(0, (today - sow).days)

    def load_calibration(self, data: dict[str, Any] | None) -> None:
        if not data:
            return
        from datetime import datetime, timezone

        def _parse(key: str):
            raw = data.get(key)
            if not raw:
                return None
            try:
                return datetime.fromisoformat(str(raw))
            except ValueError:
                return None

        self.calibration.last_ph = _parse("ph")
        self.calibration.last_tds = _parse("tds")
        self.calibration.last_do = _parse("do")

    async def async_shutdown(self) -> None:
        if self._balance_task and not self._balance_task.done():
            self._balance_task.cancel()
        self.scheduler.stop()
        await self.handle(Command(CommandType.EMERGENCY_STOP))

    def _emit(self, events: list[DomainEvent]) -> None:
        for ev in events:
            self.events.append(ev)
            if ev.severity in ("error", "warning"):
                _LOGGER.log(
                    logging.ERROR if ev.severity == "error" else logging.WARNING,
                    "%s %s",
                    ev.code,
                    ev.message,
                )
                self.hass.async_create_task(self._notify_customer(ev))
            if ev.severity == "error":
                self.last_error = ev.message

    async def _notify_customer(self, ev: DomainEvent) -> None:
        """HA notification for customer-visible warnings/errors."""
        title = f"HydroQ — {self.zone_name}"
        nid = f"hydroq_{self.zone_name}_{ev.code}".replace(" ", "_")[:64]
        try:
            await self.hass.services.async_call(
                "persistent_notification",
                "create",
                {
                    "title": title,
                    "message": ev.message,
                    "notification_id": nid,
                },
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            _LOGGER.debug("persistent_notification failed", exc_info=True)
        try:
            await self.hass.services.async_call(
                "notify",
                "notify",
                {"title": title, "message": ev.message},
                blocking=False,
            )
        except Exception:  # noqa: BLE001
            pass

    def _notify_ha(self) -> None:
        if self._on_update:
            self._on_update()

    async def handle(self, command: Command) -> list[DomainEvent]:
        """Single entry for all operator / schedule actions."""
        ctype = command.type
        payload = command.payload or {}
        out: list[DomainEvent] = []

        if ctype == CommandType.TICK:
            out = await self._tick_logic(payload.get("now"))
        elif ctype == CommandType.EMERGENCY_STOP:
            out = await self._emergency_stop()
        elif ctype == CommandType.START_IRRIGATION:
            out = await self._start_irrigation(payload)
        elif ctype == CommandType.STOP_IRRIGATION:
            out = await self.irrigation.stop("stop")
        elif ctype == CommandType.START_DOSING_PH:
            out = await self._start_dosing(DosingProcess.PH)
        elif ctype == CommandType.START_DOSING_NUTRIENTS:
            out = await self._start_dosing(DosingProcess.NUTRIENTS)
        elif ctype == CommandType.START_DOSING_NEUTRALIZE:
            out = await self._start_dosing(DosingProcess.NEUTRALIZE)
        elif ctype == CommandType.STOP_DOSING:
            if self._balance_task and not self._balance_task.done():
                self._balance_task.cancel()
            out = await self.dosing.stop("stop")
        elif ctype == CommandType.START_BALANCE:
            out = await self._start_balance()
        elif ctype == CommandType.SET_LIGHTS:
            # Manual master toggle — take over from schedule so Off sticks
            self.lighting.auto_enabled = False
            safety = await self.device.read_safety()
            out = await self.lighting.set_all(bool(payload.get("on")), estop=safety.estop_active)
            out.append(
                DomainEvent(
                    "system.auto",
                    "Auto lighting=False (manual All Lights)",
                )
            )
        elif ctype == CommandType.APPLY_GROWTH_STAGE:
            # Manual stage change disables auto-stage so tick cannot undo it.
            if self.auto_stage:
                self.auto_stage = False
                self._save_crop()
            out = self._apply_stage(str(payload.get("stage", "Vegetative")), manual=True)
        elif ctype == CommandType.SET_PLANT:
            out = self._set_plant(str(payload.get("plant_id", "generic")))
        elif ctype == CommandType.START_CROP:
            out = self._start_crop()
        elif ctype == CommandType.SET_SOW_DATE:
            out = self._set_sow_date(payload.get("sow_date"))
        elif ctype == CommandType.SET_TDS_FACTOR:
            out = self._set_tds_factor(int(payload.get("tds_factor", DEFAULT_TDS_FACTOR)))
        elif ctype == CommandType.SET_SYSTEM_MODE:
            self.system_mode = str(payload.get("mode", self.system_mode))
            if self.system_mode == "Maintenance":
                self.dosing.auto_ph = False
                self.dosing.auto_ec = False
                out += await self.dosing.stop("maintenance")
            out.append(DomainEvent("system.mode", f"Mode {self.system_mode}"))
        elif ctype == CommandType.SET_AUTO:
            key = payload.get("key")
            val = bool(payload.get("value"))
            if key == "irrigation":
                self.irrigation.auto_enabled = val
            elif key == "lighting":
                self.lighting.auto_enabled = val
            elif key == "ph":
                self.dosing.auto_ph = val
            elif key == "ec":
                self.dosing.auto_ec = val
            elif key == "stage":
                self.auto_stage = val
                self._save_crop()
            out.append(DomainEvent("system.auto", f"Auto {key}={val}"))
        elif ctype == CommandType.SET_SETPOINT:
            self._set_setpoint(payload)
            out.append(DomainEvent("system.setpoint", "Setpoint updated", data=payload))
        elif ctype == CommandType.SET_SCHEDULE_SLOT:
            idx = int(payload.get("index", 0))
            ok = self.irrigation.set_slot(
                idx,
                enabled=payload.get("enabled"),
                hour=payload.get("hour"),
                minute=payload.get("minute"),
                duration_min=payload.get("duration_min"),
            )
            if ok:
                # Arm auto when user enables an event — matches "I turned the schedule on"
                if payload.get("enabled") is True:
                    self.irrigation.auto_enabled = True
                self._save_schedule()
                out.append(
                    DomainEvent(
                        "irrigation.schedule",
                        f"Slot {idx} updated",
                        data={"index": idx, **{k: v for k, v in payload.items() if k != "index"}},
                    )
                )
            else:
                out.append(
                    DomainEvent(
                        "irrigation.schedule",
                        f"Invalid slot {idx}",
                        "warning",
                    )
                )
        elif ctype == CommandType.CALIBRATE:
            out = await self.calibration.calibrate_point(
                str(payload.get("kind", "ph")),
                str(payload.get("point", "neutral")),
            )
            if any(e.code == "calibration.done" for e in out):
                self._save_calibration()
        elif ctype == CommandType.TEST_PUMP:
            out = await self._test_pump(
                str(payload.get("role", "")),
                float(payload.get("seconds", 10)),
            )
        elif ctype == CommandType.REQUEST_REFILL:
            out = self.alarms.request_refill()
        elif ctype == CommandType.ACK_FAULT:
            await self.irrigation.ack_fault()
            await self.dosing.ack_fault()
            out.append(DomainEvent("system.ack_fault", "Faults acknowledged"))
        elif ctype == CommandType.RESET_ESTOP:
            ok = await self.device.press_reset_estop()
            if ok:
                out.append(
                    DomainEvent(
                        "system.reset_estop",
                        "Reset Emergency Stop button pressed",
                    )
                )
            else:
                out.append(
                    DomainEvent(
                        "system.reset_estop",
                        "Reset requested — press Reset Emergency Stop on device",
                        "warning",
                    )
                )

        self._emit(out)
        self._notify_ha()
        return out

    async def _on_tick(self, now: datetime) -> None:
        await self.handle(Command(CommandType.TICK, {"now": now}))

    async def _tick_logic(self, now: datetime | None) -> list[DomainEvent]:
        # Schedule slots use local wall clock (same as the Schedule editor).
        if now is None:
            now = dt_util.now()
        else:
            now = dt_util.as_local(now)
        events: list[DomainEvent] = []
        safety = await self.device.read_safety()
        events += self.alarms.evaluate(safety)
        events += self._calibration_age_warn(now)
        events += self._maybe_create_repairs(safety)

        # Mid-process safety: abort busy work when actuators not allowed (e-stop / empty).
        # Empty tank stops pumps only — lights stay under lighting manager (not water-gated).
        if not safety.actuators_allowed:
            reason = safety.reason or "safety"
            if self._balance_task and not self._balance_task.done():
                self._balance_task.cancel()
            if self.irrigation.fsm.busy:
                events += await self.irrigation.stop(reason)
                events.append(
                    DomainEvent(
                        "process_interrupted",
                        f"Irrigation stopped: {reason}",
                        "error",
                        process="irrigation",
                    )
                )
            if self.dosing.fsm.busy:
                events += await self.dosing.stop(reason)
                events.append(
                    DomainEvent(
                        "process_interrupted",
                        f"Dosing stopped: {reason}",
                        "error",
                        process="dosing",
                    )
                )
            await self.device.stop_all_actuators(include_lights=False)
            if safety.estop_active:
                events += await self.lighting.set_all(False, stagger_s=0.0)
            else:
                events += await self.lighting.tick_auto(now, estop=False)
            return events

        if self.system_mode == "Maintenance":
            return events

        # Clear prior COMPLETE/FAULT so schedule can start a new run
        from ..process.irrigation_fsm import IrrigationState
        from ..process.dosing_fsm import DosingState

        if self.irrigation.fsm.state in (
            IrrigationState.COMPLETE,
            IrrigationState.ABORTED,
            IrrigationState.FAULT,
        ):
            self.irrigation.fsm.reset_to_idle()
        if self.dosing.fsm.state in (
            DosingState.COMPLETE,
            DosingState.ABORTED,
            DosingState.LIMIT,
        ):
            self.dosing.fsm.reset_to_idle()

        if self.system_mode in ("Semi-Auto", "Full-Auto"):
            events += await self.lighting.tick_auto(now, safety.estop_active)
        events += self._tick_auto_stage(now)

        due = self.irrigation.schedule_due(now)
        if due:
            idx, slot = due
            if self.system_mode not in ("Semi-Auto", "Full-Auto"):
                events.append(
                    DomainEvent(
                        "irrigation.schedule_skip",
                        f"Event {idx} due but System Mode is {self.system_mode} "
                        "(need Semi-Auto or Full-Auto)",
                        "warning",
                        process="irrigation",
                    )
                )
            elif not self.irrigation.auto_enabled:
                events.append(
                    DomainEvent(
                        "irrigation.schedule_skip",
                        f"Event {idx} due but Auto Irrigation is OFF",
                        "warning",
                        process="irrigation",
                    )
                )
            else:
                started = await self._start_irrigation(
                    {"duration_min": slot.duration_min, "event_number": idx}
                )
                events += started
                if self.irrigation.fsm.state == IrrigationState.RUNNING:
                    self.irrigation.mark_schedule_fired(now, idx, slot)

        if self.system_mode in ("Semi-Auto", "Full-Auto"):
            if not self.dosing.fsm.busy and not self.irrigation.fsm.busy and safety.actuators_allowed:
                suggestion = await self.dosing.suggest_auto(safety.ph, safety.tds)
                if suggestion:
                    events += await self._start_dosing(suggestion)

        return events

    def _maybe_create_repairs(self, safety) -> list[DomainEvent]:
        if not self.entry_id:
            return []
        try:
            from ..repair import (
                async_create_issue_sensor_unavailable,
                async_create_issue_uncalibrated,
            )
            from ..models.capability import SensorRole

            if self.hal.capabilities.has_sensor(SensorRole.PH.value) and safety.ph is None:
                async_create_issue_sensor_unavailable(self.hass, self.entry_id, "ph")
            if self.calibration.last_ph is None and self.hal.capabilities.has_sensor(
                SensorRole.PH.value
            ):
                async_create_issue_uncalibrated(self.hass, self.entry_id)
        except Exception:  # noqa: BLE001
            _LOGGER.debug("repair issue create skipped", exc_info=True)
        return []

    def _calibration_age_warn(self, now: datetime) -> list[DomainEvent]:
        """Remind once per day if any calibration is older than 30 days."""
        day = now.strftime("%Y-%m-%d")
        if self._cal_warn_day == day:
            return []
        events: list[DomainEvent] = []
        for label, last in (
            ("pH", self.calibration.last_ph),
            ("TDS", self.calibration.last_tds),
            ("DO", self.calibration.last_do),
        ):
            if last is None:
                continue
            age = (dt_util.as_utc(now) - dt_util.as_utc(last)).days
            if age >= 30:
                events.append(
                    DomainEvent(
                        "calibration.due",
                        f"{label} calibration is {age} days old — recalibrate recommended",
                        "warning",
                        process="calibration",
                    )
                )
        if events:
            self._cal_warn_day = day
        return events

    async def _test_pump(self, role: str, seconds: float) -> list[DomainEvent]:
        """Short bench test (legacy test_pump_a/b style)."""
        role_map = {
            "nutrient_a": ChannelRole.NUTRIENT_A.value,
            "a": ChannelRole.NUTRIENT_A.value,
            "nutrient_b": ChannelRole.NUTRIENT_B.value,
            "b": ChannelRole.NUTRIENT_B.value,
            "nutrient_c": ChannelRole.NUTRIENT_C.value,
            "c": ChannelRole.NUTRIENT_C.value,
            "ph": ChannelRole.PH_UP.value,
            "ph_up": ChannelRole.PH_UP.value,
            "irrigation": ChannelRole.IRRIGATION.value,
        }
        ch = role_map.get(role.lower().strip())
        if not ch or not self.hal.has(ch):
            return [DomainEvent("test.rejected", f"Unknown or unmapped pump '{role}'", "warning")]
        if self.dosing.fsm.busy or self.irrigation.fsm.busy:
            return [DomainEvent("test.rejected", "System busy — stop dosing/irrigation first", "warning")]
        safety = await self.device.read_safety()
        if safety.estop_active:
            return [DomainEvent("test.rejected", "E-stop active", "error")]
        secs = max(1.0, min(30.0, float(seconds)))
        await self.hal.set_output(ch, 50.0 if ch != ChannelRole.IRRIGATION.value else 100.0)
        await asyncio.sleep(secs)
        await self.hal.set_output(ch, 0)
        return [
            DomainEvent(
                "test.done",
                f"Pump test {role} finished ({secs:.0f}s)",
                process="test",
            )
        ]

    def _health_score(self, safety) -> int:
        score = 100
        if safety.estop_active:
            return 0
        if not safety.water_ok:
            score -= 30
        score -= 10 * min(len(self.alarms.warnings), 5)
        return max(0, score)

    def _health_warn_if_low(self, safety, process: str) -> list[DomainEvent]:
        score = self._health_score(safety)
        if score < 70:
            return [
                DomainEvent(
                    "health.low",
                    f"Health {score} < 70 — {process} continuing (alert only)",
                    "warning",
                    process=process,
                )
            ]
        return []

    async def _start_irrigation(self, payload: dict[str, Any]) -> list[DomainEvent]:
        if self.dosing.fsm.busy:
            return [
                DomainEvent(
                    "irrigation.rejected",
                    "Blocked: dosing active",
                    "warning",
                    process="irrigation",
                )
            ]
        if self.system_mode == "Maintenance":
            return [DomainEvent("irrigation.rejected", "Maintenance mode", "warning")]
        safety = await self.device.read_safety()
        events = self._health_warn_if_low(safety, "irrigation")
        duration = float(payload.get("duration_min", 5))
        event_number = payload.get("event_number")
        events += await self.irrigation.start(
            duration, event_number, safety.actuators_allowed, safety.reason
        )
        return events

    async def _start_dosing(self, process: DosingProcess) -> list[DomainEvent]:
        if self.irrigation.fsm.busy:
            return [
                DomainEvent("dosing.rejected", "Blocked: irrigation active", "warning", process="dosing")
            ]
        if self.system_mode == "Maintenance":
            return [DomainEvent("dosing.rejected", "Maintenance mode", "warning")]
        safety = await self.device.read_safety()
        events = self._health_warn_if_low(safety, "dosing")
        events += await self.dosing.start(process, safety.actuators_allowed, safety.reason)
        return events

    async def _start_balance(self) -> list[DomainEvent]:
        """Legacy zone1_adjust_hydroponic_system: pH → wait 60s → TDS decide."""
        if self.system_mode == "Maintenance":
            return [DomainEvent("balance.rejected", "Maintenance mode", "warning")]
        if self.irrigation.fsm.busy or self.dosing.fsm.busy:
            return [DomainEvent("balance.rejected", "Busy — stop dosing/irrigation first", "warning")]
        if self._balance_task and not self._balance_task.done():
            return [DomainEvent("balance.rejected", "Balance already running", "warning")]

        safety = await self.device.read_safety()
        if not safety.actuators_allowed:
            return [
                DomainEvent(
                    "balance.rejected",
                    f"Safety blocked: {safety.reason}",
                    "error",
                )
            ]

        warn = self._health_warn_if_low(safety, "balance")

        self._balance_task = asyncio.create_task(self._run_balance())
        return warn + [
            DomainEvent(
                "balance.started",
                "Balance started (pH → 60s → TDS)",
                process="dosing",
            )
        ]

    async def _run_balance(self) -> None:
        """Match scripts2.yaml zone1_adjust_hydroponic_system (+ main_tds decide)."""
        try:
            # 1) pH adjust (legacy always called adjust_ph; loop no-ops if already ≥ desired)
            events = await self._start_dosing(DosingProcess.PH)
            self._emit(events)
            self._notify_ha()
            while self.dosing.fsm.busy:
                await asyncio.sleep(1)

            # 2) settle gap
            await asyncio.sleep(60)

            # 3) TDS decide = legacy zone1_main_tds_adjustment
            safety = await self.device.read_safety()
            tds = safety.tds
            if tds is None:
                self._emit(
                    [
                        DomainEvent(
                            "balance.tds_skip",
                            "Balance: TDS unavailable — skipped TDS step",
                            "warning",
                        )
                    ]
                )
                self._notify_ha()
                return

            desired = self.dosing.desired_tds
            tol = self.dosing.ec_tolerance
            if tds < desired - tol:
                ev = await self._start_dosing(DosingProcess.NUTRIENTS)
            elif tds > desired + tol:
                ev = await self._start_dosing(DosingProcess.NEUTRALIZE)
            else:
                self._emit(
                    [
                        DomainEvent(
                            "balance.tds_ok",
                            f"Balance: TDS {tds:.0f} in range — no dose",
                        )
                    ]
                )
                self._notify_ha()
                return

            self._emit(ev)
            self._notify_ha()
            while self.dosing.fsm.busy:
                await asyncio.sleep(1)

            self._emit(
                [DomainEvent("balance.completed", "Balance completed", process="dosing")]
            )
            self._notify_ha()
        except asyncio.CancelledError:
            await self.dosing.stop("balance_cancelled")
            raise
        except Exception as err:  # noqa: BLE001
            _LOGGER.exception("Balance failed")
            self.last_error = str(err)
            self._emit(
                [DomainEvent("balance.fault", f"Balance fault: {err}", "error")]
            )
            self._notify_ha()

    async def _emergency_stop(self) -> list[DomainEvent]:
        if self._balance_task and not self._balance_task.done():
            self._balance_task.cancel()
        self.dosing.auto_ph = False
        self.dosing.auto_ec = False
        self.irrigation.auto_enabled = False
        self.lighting.auto_enabled = False
        events: list[DomainEvent] = []
        events += await self.dosing.stop("emergency_stop")
        events += await self.irrigation.stop("emergency_stop")
        events += await self.lighting.set_all(False, stagger_s=0.0)
        await self.device.stop_all_actuators()
        events.append(
            DomainEvent(
                "safety.emergency_stop",
                "Emergency stop — actuators off, autos cleared",
                "error",
            )
        )
        return events

    def _apply_stage(self, stage: str, *, manual: bool = False) -> list[DomainEvent]:
        plant = self.recipes.get_plant(self.plant_id)
        if stage not in plant.stages:
            stage = plant.stages[0] if plant.stages else "Vegetative"
        recipe = self.recipes.get(stage, self.plant_id)
        self.growth_stage = stage
        self.dosing.desired_ph = recipe.desired_ph
        self.dosing.desired_tds = recipe.desired_tds(self.tds_factor)
        self.dosing.ph_tolerance = recipe.ph_tolerance
        self.dosing.ec_tolerance = recipe.tds_tolerance(self.tds_factor)
        self.alarms.desired_ph = recipe.desired_ph
        self.alarms.desired_tds = self.dosing.desired_tds
        self.alarms.ph_tolerance = recipe.ph_tolerance
        self.alarms.ec_tolerance = self.dosing.ec_tolerance
        self.lighting.on_hour, self.lighting.on_minute = recipe.light_on
        self.lighting.off_hour, self.lighting.off_minute = recipe.light_off
        slots = normalize_schedule(list(recipe.schedule))
        self.irrigation.schedule = slots
        self.irrigation._last_fired = None
        self._save_schedule()
        self._save_crop()
        code = "recipe.applied"
        msg = f"Applied {plant.label} / {stage}"
        if manual:
            msg += " (manual)"
        return [
            DomainEvent(
                code,
                msg,
                data={
                    "plant_id": self.plant_id,
                    "stage": stage,
                    "desired_ec": recipe.desired_ec,
                    "desired_tds": self.dosing.desired_tds,
                    "tds_factor": self.tds_factor,
                },
            )
        ]

    def _set_plant(self, plant_id: str) -> list[DomainEvent]:
        plant = self.recipes.get_plant(plant_id)
        self.plant_id = plant.plant_id
        # Changing plant clears crop cycle — operator must Start Crop again.
        self.sow_date = None
        self.auto_stage = False
        stage = (
            self.growth_stage
            if self.growth_stage in plant.stages
            else plant.stages[0]
        )
        events = self._apply_stage(stage)
        events.insert(
            0,
            DomainEvent(
                "recipe.plant",
                f"Plant set to {plant.label} — Start Crop to begin auto stages",
                data={"plant_id": self.plant_id},
            ),
        )
        return events

    def _start_crop(self) -> list[DomainEvent]:
        today = dt_util.as_local(dt_util.now()).date().isoformat()
        plant = self.recipes.get_plant(self.plant_id)
        first = plant.stages[0] if plant.stages else "Seedling"
        self.sow_date = today
        self.auto_stage = True
        events = self._apply_stage(first)
        events.insert(
            0,
            DomainEvent(
                "recipe.crop_started",
                f"Crop started ({plant.label}) — sow {today}",
                data={"sow_date": today, "plant_id": self.plant_id, "stage": first},
            ),
        )
        self._save_crop()
        return events

    def _set_sow_date(self, raw: Any) -> list[DomainEvent]:
        if raw in (None, "", "unknown", "unavailable"):
            self.sow_date = None
        else:
            text = str(raw)[:10]
            try:
                y, m, d = (int(x) for x in text.split("-", 2))
                self.sow_date = datetime(y, m, d).date().isoformat()
            except ValueError:
                return [
                    DomainEvent(
                        "recipe.sow_date",
                        f"Invalid sow date: {raw}",
                        "warning",
                    )
                ]
        self._save_crop()
        return [
            DomainEvent(
                "recipe.sow_date",
                f"Sow date={self.sow_date or 'cleared'}",
                data={"sow_date": self.sow_date},
            )
        ]

    def _set_tds_factor(self, factor: int) -> list[DomainEvent]:
        factor = 700 if int(factor) == 700 else 500
        # Keep EC stable: recompute TDS targets from current EC.
        current_ec = tds_to_ec(self.dosing.desired_tds, self.tds_factor)
        current_ec_tol = tds_to_ec(self.dosing.ec_tolerance, self.tds_factor)
        self.tds_factor = factor
        self.dosing.desired_tds = current_ec * factor
        self.dosing.ec_tolerance = current_ec_tol * factor
        self.alarms.desired_tds = self.dosing.desired_tds
        self.alarms.ec_tolerance = self.dosing.ec_tolerance
        self._save_crop()
        return [
            DomainEvent(
                "system.tds_factor",
                f"TDS factor={factor} (targets recomputed, no dose)",
                data={"tds_factor": factor, "desired_tds": self.dosing.desired_tds},
            )
        ]

    def _tick_auto_stage(self, now: datetime) -> list[DomainEvent]:
        if not self.auto_stage or not self.sow_date:
            return []
        day = now.strftime("%Y-%m-%d")
        # Idempotent once per local day (also covers restart catch-up).
        if self._stage_advance_day == day:
            return []
        days = self.days_after_sow(now)
        if days is None:
            return []
        expected = self.recipes.expected_stage(self.plant_id, days)
        self._stage_advance_day = day
        if expected == self.growth_stage:
            return []
        events = self._apply_stage(expected)
        events.insert(
            0,
            DomainEvent(
                "recipe.stage_advanced",
                f"Auto stage → {expected} (day {days})",
                data={
                    "stage": expected,
                    "days_after_sow": days,
                    "plant_id": self.plant_id,
                },
            ),
        )
        return events

    def _set_setpoint(self, payload: dict[str, Any]) -> None:
        if "desired_ph" in payload:
            self.dosing.desired_ph = float(payload["desired_ph"])
            self.alarms.desired_ph = self.dosing.desired_ph
        if "ph_tolerance" in payload:
            self.dosing.ph_tolerance = float(payload["ph_tolerance"])
            self.alarms.ph_tolerance = self.dosing.ph_tolerance
        if "desired_ec" in payload:
            ec = float(payload["desired_ec"])
            self.dosing.desired_tds = ec * self.tds_factor
            self.alarms.desired_tds = self.dosing.desired_tds
        if "desired_ec_tds" in payload or "desired_tds" in payload:
            self.dosing.desired_tds = float(
                payload.get("desired_ec_tds", payload.get("desired_tds"))
            )
            self.alarms.desired_tds = self.dosing.desired_tds
        if "ec_tolerance_ms" in payload:
            self.dosing.ec_tolerance = float(payload["ec_tolerance_ms"]) * self.tds_factor
            self.alarms.ec_tolerance = self.dosing.ec_tolerance
        if "ec_tolerance" in payload or "tds_tolerance" in payload:
            self.dosing.ec_tolerance = float(
                payload.get("ec_tolerance", payload.get("tds_tolerance"))
            )
            self.alarms.ec_tolerance = self.dosing.ec_tolerance

    async def _live_ec_tds(self) -> tuple[float | None, float | None, bool]:
        """Return (ec, tds, ec_derived)."""
        from ..util import valid_float

        tds = await self.hal.read_sensor(SensorRole.TDS.value)
        ec = await self.hal.read_sensor(SensorRole.EC.value)
        tds_f = valid_float(tds)
        ec_f = valid_float(ec)
        if ec_f is not None and tds_f is None:
            return ec_f, ec_f * self.tds_factor, False
        if tds_f is not None and ec_f is None:
            return tds_to_ec(tds_f, self.tds_factor), tds_f, True
        if ec_f is not None and tds_f is not None:
            return ec_f, tds_f, False
        return None, None, True

    async def public_snapshot(self) -> PublicSnapshot:
        safety = await self.device.read_safety()
        score = 100
        if safety.estop_active:
            score = 0
        elif not safety.water_ok:
            score -= 30
        score -= 10 * min(len(self.alarms.warnings), 5)

        status = "ready"
        if safety.estop_active:
            status = "emergency_stop"
        elif not safety.water_ok:
            status = "tank_empty"
        elif self.dosing.fsm.busy:
            status = f"dosing_{self.dosing.fsm.ctx.process.value}"
        elif self.irrigation.fsm.busy:
            status = "irrigating"

        plant = self.recipes.get_plant(self.plant_id)
        desired_ec = tds_to_ec(self.dosing.desired_tds, self.tds_factor)
        ec_tol_ms = tds_to_ec(self.dosing.ec_tolerance, self.tds_factor)

        snap = PublicSnapshot(
            status=status,
            health_score=max(0, score),
            system_mode=self.system_mode,
            plant_id=self.plant_id,
            plant_label=plant.label,
            growth_stage=self.growth_stage,
            irrigation_state=self.irrigation.fsm.state.value,
            dosing_state=self.dosing.fsm.state.value,
            calibration_state=self.calibration.fsm.state.value,
            auto_irrigation=self.irrigation.auto_enabled,
            auto_lighting=self.lighting.auto_enabled,
            auto_ph=self.dosing.auto_ph,
            auto_ec=self.dosing.auto_ec,
            auto_stage=self.auto_stage,
            desired_ph=self.dosing.desired_ph,
            ph_tolerance=self.dosing.ph_tolerance,
            desired_ec_tds=self.dosing.desired_tds,
            desired_ec=desired_ec,
            ec_tolerance=self.dosing.ec_tolerance,
            ec_tolerance_ms=ec_tol_ms,
            tds_factor=self.tds_factor,
            sow_date=self.sow_date,
            days_after_sow=self.days_after_sow(),
            water_ok=safety.water_ok,
            estop_active=safety.estop_active,
            refill_requested=self.alarms.refill_requested,
            simulation=self.hal.capabilities.simulation,
            last_error=self.last_error,
            last_event=self.events.last_message,
            warnings=list(self.alarms.warnings),
            active_alarm=self.alarms.active,
        )
        return snap

    def diagnostics_blob(self) -> dict[str, Any]:
        return self.diagnostics.build(
            {
                "zone_name": self.zone_name,
                "system_mode": self.system_mode,
                "plant_id": self.plant_id,
                "growth_stage": self.growth_stage,
                "sow_date": self.sow_date,
                "auto_stage": self.auto_stage,
                "tds_factor": self.tds_factor,
                "irrigation": self.irrigation.snapshot(),
                "dosing": self.dosing.snapshot(),
                "lighting": self.lighting.snapshot(),
                "calibration": self.calibration.snapshot(),
                "alarms": self.alarms.snapshot(),
                "recipes": self.recipes.snapshot(),
            }
        )
