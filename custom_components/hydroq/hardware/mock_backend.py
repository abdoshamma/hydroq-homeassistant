"""Simulation HAL for development and CI."""

from __future__ import annotations

import logging
from typing import Any

from ..models.capability import CapabilityMap, ChannelRole, SensorRole
from .hal import HardwareHAL

_LOGGER = logging.getLogger(__name__)


class MockHAL(HardwareHAL):
    def __init__(self, capabilities: CapabilityMap | None = None) -> None:
        caps = capabilities or CapabilityMap(simulation=True)
        caps.simulation = True
        # Ensure minimal sensors exist for sim
        for role in (
            SensorRole.PH,
            SensorRole.TDS,
            SensorRole.WATER_TEMP,
            SensorRole.WATER_LEVEL,
            SensorRole.ESTOP,
        ):
            if role.value not in caps.sensors:
                from ..models.capability import SensorChannel

                # No HA entity — MockHAL serves values by role. Fake "sim.*" IDs break Lovelace.
                caps.sensors[role.value] = SensorChannel(role=role.value, entity_id=None)
        for role in (
            ChannelRole.NUTRIENT_A,
            ChannelRole.PH_UP,
            ChannelRole.IRRIGATION,
            ChannelRole.LIGHTING,
        ):
            if role.value not in caps.actuators:
                from ..models.capability import ActuatorChannel

                caps.actuators[role.value] = ActuatorChannel(
                    role=role.value,
                    entity_id=None,
                    kind="relay" if role == ChannelRole.IRRIGATION else "peristaltic",
                )
        # Detach real ESPHome entity IDs so sim never claims them, and has_* uses simulation flag.
        self._park_entity_ids: list[str] = []
        for ch in caps.sensors.values():
            if ch.entity_id and not ch.entity_id.startswith("sim."):
                # sensors read-only — leave mapping but ignore for I/O
                pass
            if ch.entity_id and ch.entity_id.startswith("sim."):
                ch.entity_id = None
        for ch in caps.actuators.values():
            if ch.entity_id and not str(ch.entity_id).startswith("sim."):
                self._park_entity_ids.append(ch.entity_id)
            if ch.entity_ids:
                self._park_entity_ids.extend(
                    e for e in ch.entity_ids if e and not str(e).startswith("sim.")
                )
            ch.entity_id = None
            ch.entity_ids = []
        super().__init__(caps)
        self._values: dict[str, float | str] = {
            SensorRole.PH.value: 5.8,
            SensorRole.TDS.value: 350.0,
            SensorRole.WATER_TEMP.value: 22.0,
            SensorRole.WATER_LEVEL.value: "on",
            SensorRole.ESTOP.value: "off",
        }
        self._outputs: dict[str, float] = {}
        self._lights_on = False

    async def read_sensor(self, role: str) -> float | str | None:
        return self._values.get(role)

    async def set_output(self, role: str, value: float) -> None:
        self._outputs[role] = value
        # First-order drift: dosing toward targets
        if value > 0:
            if role in (ChannelRole.PH_UP.value, ChannelRole.PH_DOWN.value):
                ph = float(self._values.get(SensorRole.PH.value, 6.0))
                delta = 0.05 if role == ChannelRole.PH_UP.value else -0.05
                self._values[SensorRole.PH.value] = max(0.0, min(14.0, ph + delta))
            if role in (
                ChannelRole.NUTRIENT_A.value,
                ChannelRole.NUTRIENT_B.value,
                ChannelRole.NUTRIENT_C.value,
            ):
                tds = float(self._values.get(SensorRole.TDS.value, 0))
                self._values[SensorRole.TDS.value] = tds + value * 0.5
            if role == ChannelRole.NEUTRALIZATION.value:
                tds = float(self._values.get(SensorRole.TDS.value, 0))
                self._values[SensorRole.TDS.value] = max(0.0, tds - value * 0.5)
        _LOGGER.debug("MockHAL %s -> %s", role, value)

    async def set_group(self, role: str, on: bool, *, stagger_s: float = 0.0) -> None:
        if role == ChannelRole.LIGHTING.value:
            self._lights_on = on

    async def press_button(self, cal_role: str) -> bool:
        _LOGGER.info("MockHAL calibrate %s", cal_role)
        self._values["cal_result"] = f"{cal_role}:ok#mock"
        return True

    async def read_cal_result(self) -> str | None:
        val = self._values.get("cal_result")
        return None if val is None else str(val)

    async def wait_cal_result(
        self, kind: str, *, before: str | None, timeout_s: float = 2.5
    ) -> str | None:
        return "ok"

    def set_sim(self, role: str, value: float | str) -> None:
        self._values[role] = value

    def diagnostics(self) -> dict[str, Any]:
        return {
            "backend": "mock",
            "values": dict(self._values),
            "outputs": dict(self._outputs),
            "lights_on": self._lights_on,
        }
