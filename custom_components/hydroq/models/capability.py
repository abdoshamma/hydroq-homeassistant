"""Hardware capability map — application logic never branches on board SKU."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class ChannelRole(StrEnum):
    NUTRIENT_A = "nutrient_a"
    NUTRIENT_B = "nutrient_b"
    NUTRIENT_C = "nutrient_c"
    PH_UP = "ph_up"
    PH_DOWN = "ph_down"
    NEUTRALIZATION = "neutralization"
    IRRIGATION = "irrigation"
    MIXING = "mixing"
    CIRCULATION = "circulation"
    AIR = "air"
    FILL_VALVE = "fill_valve"
    DRAIN_VALVE = "drain_valve"
    LIGHTING = "lighting"


class SensorRole(StrEnum):
    PH = "ph"
    TDS = "tds"
    EC = "ec"
    DO = "do"
    DO_RAW = "do_raw"
    WATER_TEMP = "water_temp"
    WATER_LEVEL = "water_level"
    ESTOP = "emergency_stop"
    CO2 = "co2"


@dataclass
class ActuatorChannel:
    role: str
    entity_id: str | None = None
    entity_ids: list[str] = field(default_factory=list)  # lighting groups
    ml_per_min: float = 50.0
    kind: str = "peristaltic"  # peristaltic | relay | relay_group

    def as_dict(self) -> dict[str, Any]:
        return {
            "role": self.role,
            "entity_id": self.entity_id,
            "entity_ids": list(self.entity_ids),
            "ml_per_min": self.ml_per_min,
            "kind": self.kind,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> ActuatorChannel:
        return cls(
            role=data["role"],
            entity_id=data.get("entity_id"),
            entity_ids=list(data.get("entity_ids") or []),
            ml_per_min=float(data.get("ml_per_min", 50)),
            kind=data.get("kind", "peristaltic"),
        )


@dataclass
class SensorChannel:
    role: str
    entity_id: str | None = None

    def as_dict(self) -> dict[str, Any]:
        return {"role": self.role, "entity_id": self.entity_id}

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> SensorChannel:
        return cls(role=data["role"], entity_id=data.get("entity_id"))


@dataclass
class CapabilityMap:
    """Describes what this controller instance can do."""

    actuators: dict[str, ActuatorChannel] = field(default_factory=dict)
    sensors: dict[str, SensorChannel] = field(default_factory=dict)
    cal_buttons: dict[str, str] = field(default_factory=dict)  # role -> entity_id
    preset_id: str | None = None  # installer hint only
    simulation: bool = False

    def has_actuator(self, role: str) -> bool:
        ch = self.actuators.get(role)
        if ch is None:
            return False
        # Simulation declares the channel without a real HA entity_id.
        if self.simulation:
            return True
        return bool(ch.entity_id or ch.entity_ids)

    def has_sensor(self, role: str) -> bool:
        s = self.sensors.get(role)
        if s is None:
            return False
        if self.simulation:
            return True
        return bool(s.entity_id)

    def as_dict(self) -> dict[str, Any]:
        return {
            "actuators": {k: v.as_dict() for k, v in self.actuators.items()},
            "sensors": {k: v.as_dict() for k, v in self.sensors.items()},
            "cal_buttons": dict(self.cal_buttons),
            "preset_id": self.preset_id,
            "simulation": self.simulation,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> CapabilityMap:
        return cls(
            actuators={
                k: ActuatorChannel.from_dict(v)
                for k, v in (data.get("actuators") or {}).items()
            },
            sensors={
                k: SensorChannel.from_dict(v)
                for k, v in (data.get("sensors") or {}).items()
            },
            cal_buttons=dict(data.get("cal_buttons") or {}),
            preset_id=data.get("preset_id"),
            simulation=bool(data.get("simulation", False)),
        )


# Legacy entity-map key → capability role
_LEGACY_ACTUATOR = {
    "solution_a": ChannelRole.NUTRIENT_A,
    "solution_b": ChannelRole.NUTRIENT_B,
    "solution_c": ChannelRole.NUTRIENT_C,
    "ph_pump": ChannelRole.PH_UP,
    "neutralization": ChannelRole.NEUTRALIZATION,
    "irrigation_pump": ChannelRole.IRRIGATION,
}
_LEGACY_SENSOR = {
    "ph": SensorRole.PH,
    "tds": SensorRole.TDS,
    "ec": SensorRole.EC,
    "do": SensorRole.DO,
    "do_raw": SensorRole.DO_RAW,
    "water_temp": SensorRole.WATER_TEMP,
    "water_level": SensorRole.WATER_LEVEL,
    "emergency_stop": SensorRole.ESTOP,
    "co2": SensorRole.CO2,
}


def legacy_entity_map_to_capabilities(
    entity_map: dict[str, Any],
    *,
    preset_id: str | None = None,
    ml_per_min: float = 50.0,
    simulation: bool = False,
) -> CapabilityMap:
    """Migrate v1 entity_map + profile preset into CapabilityMap."""
    caps = CapabilityMap(preset_id=preset_id, simulation=simulation)
    for key, role in _LEGACY_ACTUATOR.items():
        eid = entity_map.get(key)
        if eid:
            kind = "relay" if role == ChannelRole.IRRIGATION else "peristaltic"
            caps.actuators[role.value] = ActuatorChannel(
                role=role.value, entity_id=eid, ml_per_min=ml_per_min, kind=kind
            )
    lights = entity_map.get("lights") or []
    if isinstance(lights, str):
        lights = [x.strip() for x in lights.split(",") if x.strip()]
    if lights:
        caps.actuators[ChannelRole.LIGHTING.value] = ActuatorChannel(
            role=ChannelRole.LIGHTING.value,
            entity_ids=list(lights),
            kind="relay_group",
        )
    for key, role in _LEGACY_SENSOR.items():
        eid = entity_map.get(key)
        if eid:
            caps.sensors[role.value] = SensorChannel(role=role.value, entity_id=eid)
    for key, role in (
        ("cal_ph_neutral", "ph_neutral"),
        ("cal_ph_acid", "ph_acid"),
        ("cal_tds", "tds"),
        ("cal_do", "do"),
    ):
        eid = entity_map.get(key)
        if eid:
            caps.cal_buttons[role] = eid
    return caps


def preset_to_capabilities(preset_id: str, entity_map: dict[str, Any], ml_per_min: float) -> CapabilityMap:
    """Installer presets expand to capabilities (data only, not runtime branches)."""
    return legacy_entity_map_to_capabilities(
        entity_map, preset_id=preset_id, ml_per_min=ml_per_min
    )
