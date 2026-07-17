"""Suggest ESPHome entity bindings from the HA entity registry."""

from __future__ import annotations

import re

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..const import (
    EM_AIR_HUMIDITY,
    EM_AIR_PRESSURE,
    EM_AIR_TEMP,
    EM_BVOC,
    EM_CAL_DO,
    EM_CAL_PH_ACID,
    EM_CAL_PH_NEUTRAL,
    EM_CAL_TDS,
    EM_CO2,
    EM_DO,
    EM_DO_RAW,
    EM_EC,
    EM_ECO2,
    EM_ESTOP,
    EM_IAQ,
    EM_IRRIGATION,
    EM_LIGHTS,
    EM_PH,
    EM_PUMP_A,
    EM_PUMP_B,
    EM_PUMP_C,
    EM_PUMP_NEUTRAL,
    EM_PUMP_PH,
    EM_TDS,
    EM_WATER_LEVEL,
    EM_WATER_TEMP,
    PROFILE_A,
)


_HINTS: dict[str, tuple[str, ...]] = {
    EM_PH: ("ph_value", "ph value", "_ph"),
    EM_TDS: ("tds_value", "tds value", "_tds"),
    EM_EC: ("ec_value", "ec value", "_ec"),
    EM_DO: ("dissolved_oxygen", "dissolved oxygen", "do_sensor", "do_value"),
    EM_DO_RAW: ("do_raw", "do raw"),
    EM_WATER_TEMP: ("water_temperature", "water_temp"),
    EM_WATER_LEVEL: ("water_level",),
    EM_ESTOP: ("emergency_stop_active", "emergency_stop"),
    EM_CO2: ("_co2", " co2", "co2"),
    EM_IAQ: ("_iaq", " iaq", "iaq"),
    EM_AIR_PRESSURE: ("air_pressure", "air pressure"),
    EM_AIR_HUMIDITY: ("canopy_humidity", "canopy humidity"),
    EM_AIR_TEMP: ("canopy_temperature", "canopy temperature"),
    EM_ECO2: ("eco2", "co2_equivalent", "voc_est", "voc est"),
    EM_BVOC: ("bvoc", "breath_voc", "breath voc"),
    EM_IRRIGATION: ("irrigation_pump",),
    EM_PUMP_A: ("solution_a_pump",),
    EM_PUMP_B: ("solution_b_pump",),
    EM_PUMP_C: ("solution_c_pump",),
    EM_PUMP_PH: ("ph_up_pump", "ph_pump"),
    EM_PUMP_NEUTRAL: ("neutralization_pump",),
    EM_CAL_PH_NEUTRAL: ("calibrate_ph_6", "calibrate_ph_7"),
    EM_CAL_PH_ACID: ("calibrate_ph_4",),
    EM_CAL_TDS: ("calibrate_tds",),
    EM_CAL_DO: ("do_air_calibration", "calibrate_do"),
}

_STAND_RE = re.compile(r"(?:grow[_ ]?)?light[_ ]stand[_ ]?(\d+)", re.I)


def _stand_number(entity_id: str, original_name: str | None = None) -> int:
    hay = f"{entity_id} {original_name or ''}".lower().replace("-", "_")
    match = _STAND_RE.search(hay)
    return int(match.group(1)) if match else 999


def _is_kit_light(entity_id: str, original_name: str | None = None) -> bool:
    hay = f"{entity_id} {original_name or ''}".lower()
    return "grow_light" in hay or "grow light" in hay


def _is_controller_light(entity_id: str, original_name: str | None = None) -> bool:
    """Main-board stands (Light Stand N) — not Grow Light Stand N."""
    if _is_kit_light(entity_id, original_name):
        return False
    hay = f"{entity_id} {original_name or ''}".lower().replace("-", "_")
    return "light_stand" in hay or "light stand" in hay


def order_light_entities(
    hass: HomeAssistant,
    entity_ids: list[str],
    controller_device_id: str | None = None,
) -> list[str]:
    """Order lights: controller stands 1..4 first, then kit (5..12), never interleaved."""
    registry = er.async_get(hass)
    ctrl: list[tuple[int, str]] = []
    kit: list[tuple[int, str]] = []
    other: list[tuple[int, str]] = []
    seen: set[str] = set()

    for eid in entity_ids:
        if not eid or eid in seen:
            continue
        seen.add(eid)
        ent = registry.async_get(eid)
        name = ent.original_name if ent else None
        num = _stand_number(eid, name)
        on_ctrl = bool(ent and controller_device_id and ent.device_id == controller_device_id)
        if on_ctrl or _is_controller_light(eid, name):
            ctrl.append((num, eid))
        elif _is_kit_light(eid, name):
            kit.append((num, eid))
        else:
            other.append((num, eid))

    ctrl.sort()
    kit.sort()
    other.sort()
    return [eid for _, eid in ctrl + kit + other]


def suggest_entity_map(
    hass: HomeAssistant,
    device_id: str | None,
    profile: str = PROFILE_A,
    *,
    max_lights: int = 16,
) -> dict[str, str | list[str]]:
    """Auto-suggest entity IDs for a controller device (+ light accessory boards)."""
    registry = er.async_get(hass)
    candidates: list[er.RegistryEntry] = []
    for entry in registry.entities.values():
        if device_id and entry.device_id != device_id:
            continue
        if entry.disabled:
            continue
        candidates.append(entry)

    result: dict[str, str | list[str]] = {}
    used: set[str] = set()

    def _pick(role: str, domains: tuple[str, ...]) -> str | None:
        hints = _HINTS.get(role, ())
        for domain in domains:
            for ent in candidates:
                if ent.entity_id in used:
                    continue
                if ent.domain != domain:
                    continue
                hay = f"{ent.entity_id} {ent.original_name or ''}".lower()
                if role == EM_DO and "do_raw" in hay:
                    continue
                if role == EM_CO2 and (
                    "eco2" in hay or "equivalent" in hay or "voc" in hay
                ):
                    continue
                if role == EM_IAQ and ("accuracy" in hay or "class" in hay):
                    continue
                if role in (EM_PUMP_A, EM_PUMP_B, EM_PUMP_C, EM_PUMP_PH, EM_PUMP_NEUTRAL):
                    if domain == "number" and "control" in hay:
                        continue
                if any(h in hay for h in hints):
                    used.add(ent.entity_id)
                    return ent.entity_id
            if domain == "number":
                for ent in candidates:
                    if ent.entity_id in used or ent.domain != "number":
                        continue
                    hay = f"{ent.entity_id} {ent.original_name or ''}".lower()
                    if any(h in hay for h in hints):
                        used.add(ent.entity_id)
                        return ent.entity_id
        return None

    for role, domains in (
        (EM_PH, ("sensor",)),
        (EM_TDS, ("sensor",)),
        (EM_EC, ("sensor",)),
        (EM_DO, ("sensor",)),
        (EM_DO_RAW, ("sensor",)),
        (EM_WATER_TEMP, ("sensor",)),
        (EM_WATER_LEVEL, ("binary_sensor",)),
        (EM_ESTOP, ("binary_sensor",)),
        (EM_CO2, ("sensor",)),
        (EM_IAQ, ("sensor",)),
        (EM_AIR_PRESSURE, ("sensor",)),
        (EM_AIR_HUMIDITY, ("sensor",)),
        (EM_AIR_TEMP, ("sensor",)),
        (EM_ECO2, ("sensor",)),
        (EM_BVOC, ("sensor",)),
        (EM_IRRIGATION, ("switch",)),
        (EM_PUMP_A, ("fan", "number")),
        (EM_PUMP_B, ("fan", "number")),
        (EM_PUMP_C, ("fan", "number")),
        (EM_PUMP_PH, ("fan", "number")),
        (EM_PUMP_NEUTRAL, ("fan", "number")),
        (EM_CAL_PH_NEUTRAL, ("button",)),
        (EM_CAL_PH_ACID, ("button",)),
        (EM_CAL_TDS, ("button",)),
        (EM_CAL_DO, ("button",)),
    ):
        ph_up_preset = profile in (PROFILE_A, "profile_a", "preset_gen1_ph_up")
        if ph_up_preset and role == EM_PUMP_NEUTRAL:
            continue
        if not ph_up_preset and role == EM_PUMP_C:
            continue
        picked = _pick(role, domains)
        if picked:
            result[role] = picked

    lights: list[str] = []
    for ent in candidates:
        if ent.entity_id in used or ent.domain != "switch":
            continue
        hay = ent.entity_id.lower() + " " + (ent.original_name or "").lower()
        if "grow_light_stand" in hay or "light_stand" in hay:
            lights.append(ent.entity_id)
            used.add(ent.entity_id)

    for ent in registry.entities.values():
        if ent.entity_id in used or ent.disabled or ent.domain != "switch":
            continue
        hay = ent.entity_id.lower() + " " + (ent.original_name or "").lower()
        if "grow_light_stand" in hay or "light_stand" in hay:
            lights.append(ent.entity_id)
            used.add(ent.entity_id)

    if lights and max_lights > 0:
        ordered = order_light_entities(hass, lights, device_id)
        result[EM_LIGHTS] = ordered[:max_lights]

    return result
