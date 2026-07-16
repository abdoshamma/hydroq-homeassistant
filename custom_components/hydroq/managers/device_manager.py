"""Device / safety sensing via HAL — no other managers."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..hardware.hal import HardwareHAL
from ..models.capability import ChannelRole, SensorRole
from ..util import valid_float


@dataclass
class SafetyReading:
    water_ok: bool
    estop_active: bool
    ph: float | None
    tds: float | None
    water_temp: float | None
    reason: str | None = None

    @property
    def actuators_allowed(self) -> bool:
        return self.water_ok and not self.estop_active and self.reason is None


class DeviceManager:
    def __init__(self, hal: HardwareHAL, hass: HomeAssistant | None = None) -> None:
        self.hal = hal
        self.hass = hass

    async def read_safety(self) -> SafetyReading:
        level = await self.hal.read_sensor(SensorRole.WATER_LEVEL.value)
        estop = await self.hal.read_sensor(SensorRole.ESTOP.value)
        ph = await self.hal.read_sensor(SensorRole.PH.value)
        tds = await self.hal.read_sensor(SensorRole.TDS.value)
        temp = await self.hal.read_sensor(SensorRole.WATER_TEMP.value)

        has_level = self.hal.capabilities.has_sensor(SensorRole.WATER_LEVEL.value)
        has_estop = self.hal.capabilities.has_sensor(SensorRole.ESTOP.value)

        estop_active = False
        if has_estop:
            if isinstance(estop, str):
                estop_active = estop.lower() in ("on", "true", "1")
            elif isinstance(estop, (int, float)):
                estop_active = bool(estop)

        reason = None

        if not has_level:
            water_ok = True
        elif level is None:
            water_ok = False
            reason = "water_level_unavailable"
        elif isinstance(level, str) and level.lower() in ("on", "true", "1"):
            water_ok = True
        elif level is True:
            water_ok = True
        else:
            water_ok = False
            reason = "tank_empty"

        if has_estop and estop is None and reason is None:
            reason = "estop_unavailable"
        if estop_active:
            reason = "emergency_stop"

        return SafetyReading(
            water_ok=water_ok,
            estop_active=estop_active,
            ph=valid_float(ph),
            tds=valid_float(tds),
            water_temp=valid_float(temp),
            reason=reason,
        )

    async def stop_all_actuators(self, *, include_lights: bool = True) -> None:
        """Park pumps/irrigation. Lights only when include_lights (e-stop / cold start)."""
        for role in list(self.hal.capabilities.actuators.keys()):
            if role == ChannelRole.LIGHTING.value:
                if include_lights:
                    await self.hal.set_group(role, False, stagger_s=0.0)
            else:
                await self.hal.set_output(role, 0)

    async def press_reset_estop(self) -> bool:
        """Press firmware Reset Emergency Stop on the same device as the e-stop sensor."""
        if self.hass is None:
            return False
        estop = self.hal.capabilities.sensors.get(SensorRole.ESTOP.value)
        if not estop or not estop.entity_id:
            return False
        registry = er.async_get(self.hass)
        primary = registry.async_get(estop.entity_id)
        if primary is None or not primary.device_id:
            return False
        for ent in registry.entities.values():
            if ent.device_id != primary.device_id or ent.domain != "button":
                continue
            hay = f"{ent.entity_id} {ent.original_name or ''}".lower()
            if "reset" in hay and "emergency" in hay:
                await self.hass.services.async_call(
                    "button", "press", {"entity_id": ent.entity_id}, blocking=True
                )
                return True
        return False

    def snapshot(self) -> dict:
        return {"simulation": self.hal.capabilities.simulation}
