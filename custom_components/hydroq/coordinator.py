"""HA DataUpdateCoordinator — thin adapter over HydroQController."""

from __future__ import annotations

import logging
from datetime import timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.storage import Store
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator

from .const import (
    CONF_AUTO_STAGE,
    CONF_CAPABILITIES,
    CONF_CUSTOM_RECIPES,
    CONF_ENTITY_MAP,
    CONF_GROWTH_STAGE,
    CONF_HARDWARE_PROFILE,
    CONF_IRRIGATION_SCHEDULE,
    CONF_LAST_CALIBRATION,
    CONF_LIGHT_STAND_COUNT,
    CONF_MAX_DOSE_ML_DAY,
    CONF_PLANT_ID,
    CONF_PUMP_ML_PER_MIN,
    CONF_SIMULATION,
    CONF_SOW_DATE,
    CONF_TDS_FACTOR,
    CONF_ZONE_NAME,
    CONTROLLER_LIGHT_STANDS,
    DEFAULT_MAX_DOSE_ML_DAY,
    DEFAULT_PLANT_ID,
    DEFAULT_TDS_FACTOR,
    DOMAIN,
    UPDATE_INTERVAL_S,
)
from .controller.commands import Command, CommandType
from .controller.hydroq_controller import HydroQController
from .hardware.esphome_backend import EsphomeHAL
from .hardware.mock_backend import MockHAL
from .models.capability import CapabilityMap, ChannelRole, legacy_entity_map_to_capabilities
from .models.runtime import normalize_schedule

_LOGGER = logging.getLogger(__name__)


def build_capabilities(entry: ConfigEntry) -> CapabilityMap:
    data = entry.data
    if CONF_CAPABILITIES in data:
        caps = CapabilityMap.from_dict(data[CONF_CAPABILITIES])
    else:
        caps = legacy_entity_map_to_capabilities(
            data.get(CONF_ENTITY_MAP, {}),
            preset_id=data.get(CONF_HARDWARE_PROFILE),
            ml_per_min=float(data.get(CONF_PUMP_ML_PER_MIN, 50)),
            simulation=bool(data.get(CONF_SIMULATION, False)),
        )
    # Enforce kit size from setup (capabilities may still list extras).
    count = int(data.get(CONF_LIGHT_STAND_COUNT, CONTROLLER_LIGHT_STANDS) or 0)
    light = caps.actuators.get(ChannelRole.LIGHTING.value)
    if light is not None:
        ids = list(light.entity_ids or [])
        if light.entity_id:
            ids.insert(0, light.entity_id)
            light.entity_id = None
        light.entity_ids = ids[:count] if count > 0 else []
        if not light.entity_ids:
            caps.actuators.pop(ChannelRole.LIGHTING.value, None)
    return caps


class HydroQCoordinator(DataUpdateCoordinator[dict[str, Any]]):
    """Publishes PublicSnapshot to HA entities; services call controller.handle."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=f"{DOMAIN}_{entry.entry_id}",
            update_interval=timedelta(seconds=UPDATE_INTERVAL_S),
        )
        self.entry = entry
        self.zone_name = entry.data.get(CONF_ZONE_NAME, "Zone")
        caps = build_capabilities(entry)
        # Config entry flag is source of truth (caps.simulation can be stale)
        use_sim = bool(entry.data.get(CONF_SIMULATION, False))
        caps.simulation = use_sim
        if use_sim:
            hal = MockHAL(caps)
            self.hass.async_create_task(self._async_park_real_actuators(hal))
        else:
            for ch in caps.actuators.values():
                if ch.role == ChannelRole.IRRIGATION.value:
                    ch.kind = "relay"
                elif ch.entity_id and ch.entity_id.startswith(("fan.", "number.")):
                    ch.kind = "peristaltic"
            hal = EsphomeHAL(hass, caps)

        self.controller = HydroQController(
            hass,
            hal,
            zone_name=self.zone_name,
            entry_id=entry.entry_id,
            event_store=Store(hass, 1, f"{DOMAIN}.{entry.entry_id}.events"),
            on_update=lambda: self.async_set_updated_data(self.data or {}),
        )
        self.controller.set_persist_schedule(self._persist_schedule)
        self.controller.set_persist_calibration(self._persist_calibration)
        self.controller.set_persist_crop(self._persist_crop)
        self.controller.load_calibration(entry.options.get(CONF_LAST_CALIBRATION))
        self.controller.load_custom_recipes(entry.options.get(CONF_CUSTOM_RECIPES))
        self.apply_options(entry.options)
        self.hass.async_create_task(self.controller.events.async_load())
        if not use_sim:
            self.hass.async_create_task(self._async_boot_safe())

    async def _async_boot_safe(self) -> None:
        from .controller.events import DomainEvent

        await self.controller.device.stop_all_actuators()
        self.controller.events.append(
            DomainEvent(
                "process_interrupted",
                "Cold start — actuators parked",
                "warning",
            )
        )
        # Catch up auto-stage once after boot.
        from homeassistant.util import dt as dt_util

        for ev in self.controller._tick_auto_stage(dt_util.now()):
            self.controller.events.append(ev)
        await self.controller.events.async_flush()

    async def _async_park_real_actuators(self, hal: MockHAL) -> None:
        """Turn off any ESPHome actuators that were mapped before simulation took over."""
        for entity_id in getattr(hal, "_park_entity_ids", []) or []:
            domain = entity_id.split(".", 1)[0]
            try:
                if domain == "switch":
                    await self.hass.services.async_call(
                        "switch", "turn_off", {"entity_id": entity_id}, blocking=False
                    )
                elif domain == "fan":
                    await self.hass.services.async_call(
                        "fan", "turn_off", {"entity_id": entity_id}, blocking=False
                    )
                elif domain == "number":
                    await self.hass.services.async_call(
                        "number",
                        "set_value",
                        {"entity_id": entity_id, "value": 0},
                        blocking=False,
                    )
                elif domain == "light":
                    await self.hass.services.async_call(
                        "light", "turn_off", {"entity_id": entity_id}, blocking=False
                    )
            except Exception:  # noqa: BLE001
                _LOGGER.debug("Sim park failed for %s", entity_id)

    def apply_options(self, options: dict[str, Any]) -> None:
        """Apply setpoints + irrigation schedule without reloading the entry."""
        self.controller.load_custom_recipes(options.get(CONF_CUSTOM_RECIPES))
        factor = int(options.get(CONF_TDS_FACTOR, DEFAULT_TDS_FACTOR) or DEFAULT_TDS_FACTOR)
        factor = 700 if factor == 700 else 500
        if factor != self.controller.tds_factor:
            self.hass.async_create_task(
                self.controller.handle(
                    Command(CommandType.SET_TDS_FACTOR, {"tds_factor": factor})
                )
            )
        else:
            self.controller.tds_factor = factor

        plant_id = options.get(CONF_PLANT_ID) or DEFAULT_PLANT_ID
        if plant_id in self.controller.recipes.plants():
            self.controller.plant_id = str(plant_id)
        stage = options.get(CONF_GROWTH_STAGE)
        if stage:
            self.controller.growth_stage = str(stage)
        self.controller.sow_date = options.get(CONF_SOW_DATE) or None
        self.controller.auto_stage = bool(options.get(CONF_AUTO_STAGE, False))

        payload = {
            "desired_ph": options.get("desired_ph"),
            "ph_tolerance": options.get("ph_tolerance"),
            "desired_tds": options.get("desired_tds"),
            "tds_tolerance": options.get("tds_tolerance"),
        }
        payload = {k: v for k, v in payload.items() if v is not None}
        if payload:
            self.hass.async_create_task(
                self.controller.handle(Command(CommandType.SET_SETPOINT, payload))
            )

        raw = options.get(CONF_IRRIGATION_SCHEDULE)
        if raw is not None:
            self.controller.irrigation.schedule = normalize_schedule(raw)
            self.controller.irrigation._last_fired = None

        max_ml = options.get(CONF_MAX_DOSE_ML_DAY)
        self.controller.dosing.max_ml_day = float(
            max_ml if max_ml is not None else DEFAULT_MAX_DOSE_ML_DAY
        )

    def _persist_schedule(self) -> None:
        """Write current slots into config entry options (survives restart)."""
        slots = [s.as_dict() for s in self.controller.irrigation.schedule]
        opts = dict(self.entry.options)
        if opts.get(CONF_IRRIGATION_SCHEDULE) == slots:
            return
        opts[CONF_IRRIGATION_SCHEDULE] = slots
        self.hass.config_entries.async_update_entry(self.entry, options=opts)

    def _persist_calibration(self) -> None:
        snap = self.controller.calibration.snapshot()
        cal = {
            "ph": snap.get("last_ph"),
            "tds": snap.get("last_tds"),
            "do": snap.get("last_do"),
        }
        opts = dict(self.entry.options)
        if opts.get(CONF_LAST_CALIBRATION) == cal:
            return
        opts[CONF_LAST_CALIBRATION] = cal
        self.hass.config_entries.async_update_entry(self.entry, options=opts)

    def _persist_crop(self) -> None:
        opts = dict(self.entry.options)
        desired = {
            CONF_PLANT_ID: self.controller.plant_id,
            CONF_GROWTH_STAGE: self.controller.growth_stage,
            CONF_SOW_DATE: self.controller.sow_date,
            CONF_AUTO_STAGE: self.controller.auto_stage,
            CONF_TDS_FACTOR: self.controller.tds_factor,
            CONF_CUSTOM_RECIPES: self.controller.recipes.custom_blob(),
            "desired_ph": self.controller.dosing.desired_ph,
            "ph_tolerance": self.controller.dosing.ph_tolerance,
            "desired_tds": self.controller.dosing.desired_tds,
            "tds_tolerance": self.controller.dosing.ec_tolerance,
        }
        changed = False
        for k, v in desired.items():
            if opts.get(k) != v:
                opts[k] = v
                changed = True
        if changed:
            self.hass.config_entries.async_update_entry(self.entry, options=opts)

    async def _async_update_data(self) -> dict[str, Any]:
        snap = await self.controller.public_snapshot()
        data = snap.as_dict()
        data["lights_on"] = self._read_lights_on()
        live_ec, live_tds, ec_derived = await self.controller._live_ec_tds()
        data["live_ec"] = live_ec
        data["live_tds"] = live_tds
        data["ec_derived"] = ec_derived
        data["target_ec"] = data.get("desired_ec")
        data["target_tds"] = data.get("desired_ec_tds")
        data["plant_options"] = self.controller.recipes.plant_options()
        data["plant_labels"] = self.controller.recipes.plant_labels()
        data["stage_options"] = list(
            self.controller.recipes.stages_for(self.controller.plant_id)
        )
        cal = self.controller.calibration.snapshot()
        data["last_cal_ph"] = self._fmt_cal(cal.get("last_ph"))
        data["last_cal_tds"] = self._fmt_cal(cal.get("last_tds"))
        data["last_cal_do"] = self._fmt_cal(cal.get("last_do"))
        for i, slot in enumerate(self.controller.irrigation.schedule, start=1):
            data[f"sched_{i}_enabled"] = slot.enabled
            data[f"sched_{i}_hour"] = slot.hour
            data[f"sched_{i}_minute"] = slot.minute
            data[f"sched_{i}_duration"] = slot.duration_min
            if slot.enabled:
                data[f"sched_{i}_label"] = (
                    f"Irrigate at {slot.hour:02d}:{slot.minute:02d} for {slot.duration_min} min"
                )
            else:
                data[f"sched_{i}_label"] = "Skipped (off)"
        await self.controller.events.async_flush()
        return data

    @staticmethod
    def _fmt_cal(iso: str | None) -> str:
        if not iso:
            return "Never"
        try:
            return str(iso)[:10]
        except Exception:  # noqa: BLE001
            return "Never"

    def _read_lights_on(self) -> bool:
        last = self.controller.lighting._last_on
        if last is not None:
            return bool(last)
        ch = self.controller.hal.capabilities.actuators.get("lighting")
        if not ch:
            return False
        ids = list(ch.entity_ids or [])
        if ch.entity_id:
            ids.insert(0, ch.entity_id)
        for eid in ids:
            st = self.hass.states.get(eid)
            if st is not None and st.state == "on":
                return True
        return False

    async def async_shutdown(self) -> None:
        await self.controller.async_shutdown()

    async def async_handle(self, command_type: CommandType, payload: dict | None = None) -> None:
        await self.controller.handle(Command(command_type, payload))
        self.async_set_updated_data(await self._async_update_data())
