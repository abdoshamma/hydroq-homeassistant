"""Device / safety sensing via HAL — no other managers."""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..hardware.hal import HardwareHAL
from ..models.capability import ChannelRole, SensorRole
from ..util import valid_float

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant


def _binary_on(value: Any) -> bool:
    if isinstance(value, str):
        return value.lower() in ("on", "true", "1")
    if isinstance(value, (int, float)):
        return bool(value)
    return value is True


@dataclass
class SafetyReading:
    water_ok: bool
    estop_active: bool
    ph: float | None
    tds: float | None
    water_temp: float | None
    reason: str | None = None
    leak_active: bool = False
    flow_ok: bool | None = None  # None = sensor not mapped

    @property
    def actuators_allowed(self) -> bool:
        return (
            self.water_ok
            and not self.estop_active
            and not self.leak_active
            and self.reason is None
        )


class DeviceManager:
    def __init__(self, hal: HardwareHAL, hass: HomeAssistant | None = None) -> None:
        self.hal = hal
        self.hass = hass

    async def read_safety(self) -> SafetyReading:
        level = await self.hal.read_sensor(SensorRole.WATER_LEVEL.value)
        level2 = await self.hal.read_sensor(SensorRole.WATER_LEVEL_SECONDARY.value)
        estop = await self.hal.read_sensor(SensorRole.ESTOP.value)
        leak = await self.hal.read_sensor(SensorRole.LEAK.value)
        flow = await self.hal.read_sensor(SensorRole.FLOW_OK.value)
        ph = await self.hal.read_sensor(SensorRole.PH.value)
        tds = await self.hal.read_sensor(SensorRole.TDS.value)
        temp = await self.hal.read_sensor(SensorRole.WATER_TEMP.value)

        has_level = self.hal.capabilities.has_sensor(SensorRole.WATER_LEVEL.value)
        has_level2 = self.hal.capabilities.has_sensor(
            SensorRole.WATER_LEVEL_SECONDARY.value
        )
        has_estop = self.hal.capabilities.has_sensor(SensorRole.ESTOP.value)
        has_leak = self.hal.capabilities.has_sensor(SensorRole.LEAK.value)
        has_flow = self.hal.capabilities.has_sensor(SensorRole.FLOW_OK.value)

        estop_active = False
        if has_estop:
            estop_active = _binary_on(estop)

        leak_active = False
        if has_leak:
            if leak is None:
                leak_active = True  # fail-safe: missing leak entity while mapped
            else:
                leak_active = _binary_on(leak)

        flow_ok: bool | None = None
        if has_flow:
            flow_ok = False if flow is None else _binary_on(flow)

        reason = None

        if not has_level:
            water_ok = True
        elif level is None:
            water_ok = False
            reason = "water_level_unavailable"
        elif _binary_on(level):
            water_ok = True
        else:
            water_ok = False
            reason = "tank_empty"

        # Dual level: secondary mapped → both must read OK
        if water_ok and has_level2:
            if level2 is None:
                water_ok = False
                reason = "water_level_secondary_unavailable"
            elif not _binary_on(level2):
                water_ok = False
                reason = "tank_empty_secondary"

        if has_estop and estop is None and reason is None:
            reason = "estop_unavailable"
        if estop_active:
            reason = "emergency_stop"
        if leak_active:
            reason = "leak_detected"

        return SafetyReading(
            water_ok=water_ok,
            estop_active=estop_active,
            ph=valid_float(ph),
            tds=valid_float(tds),
            water_temp=valid_float(temp),
            reason=reason,
            leak_active=leak_active,
            flow_ok=flow_ok,
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
        from homeassistant.helpers import entity_registry as er

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

    def snapshot(self) -> dict[str, Any]:
        return {"simulation": self.hal.capabilities.simulation}
