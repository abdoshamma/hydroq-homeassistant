"""ESPHome / HA entity-backed HAL."""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er

from ..models.capability import CapabilityMap
from .hal import HardwareHAL

_LOGGER = logging.getLogger(__name__)


class EsphomeHAL(HardwareHAL):
    def __init__(self, hass: HomeAssistant, capabilities: CapabilityMap) -> None:
        super().__init__(capabilities)
        self.hass = hass

    async def read_sensor(self, role: str) -> float | str | None:
        ch = self.capabilities.sensors.get(role)
        if not ch or not ch.entity_id:
            return None
        st = self.hass.states.get(ch.entity_id)
        if st is None:
            return None
        if role in ("water_level", "emergency_stop"):
            return st.state
        from ..util import valid_float

        return valid_float(st.state)

    async def set_output(self, role: str, value: float) -> None:
        ch = self.capabilities.actuators.get(role)
        if not ch or not ch.entity_id:
            _LOGGER.debug("HAL set_output skipped; no channel %s", role)
            return
        pct = max(0, min(100, float(value)))
        # ESPHome often exposes the same PWM as fan.* AND number.*_control — drive both.
        for entity_id in self._actuator_targets(ch.entity_id):
            await self._write_percent(entity_id, pct)

    async def set_group(self, role: str, on: bool, *, stagger_s: float = 0.0) -> None:
        ch = self.capabilities.actuators.get(role)
        if not ch:
            return
        ids = list(ch.entity_ids or [])
        if ch.entity_id:
            ids.insert(0, ch.entity_id)
        ordered: list[str] = []
        seen: set[str] = set()
        for entity_id in ids:
            for target in self._actuator_targets(entity_id):
                if target in seen:
                    continue
                seen.add(target)
                ordered.append(target)
        pct = 100.0 if on else 0.0
        delay = max(0.0, float(stagger_s))
        for i, target in enumerate(ordered):
            if i > 0 and delay > 0:
                await asyncio.sleep(delay)
            await self._write_percent(target, pct)

    async def press_button(self, cal_role: str) -> bool:
        entity_id = self.capabilities.cal_buttons.get(cal_role)
        if not entity_id:
            return False
        await self.hass.services.async_call(
            "button", "press", {"entity_id": entity_id}, blocking=True
        )
        return True

    def _cal_result_entity(self) -> str | None:
        ch = self.capabilities.sensors.get("cal_result")
        if ch and ch.entity_id:
            return ch.entity_id
        # Fallback: same ESPHome device as any mapped cal button
        for eid in self.capabilities.cal_buttons.values():
            twin = self._find_named_on_device(eid, "cal_result")
            if twin:
                return twin
        return None

    def _find_named_on_device(self, entity_id: str, needle: str) -> str | None:
        registry = er.async_get(self.hass)
        primary = registry.async_get(entity_id)
        if primary is None or not primary.device_id:
            return None
        for ent in registry.entities.values():
            if ent.device_id != primary.device_id or ent.disabled:
                continue
            hay = f"{ent.entity_id} {ent.original_name or ''}".lower()
            if needle in hay.replace(" ", "_"):
                return ent.entity_id
        return None

    async def read_cal_result(self) -> str | None:
        eid = self._cal_result_entity()
        if not eid:
            return None
        st = self.hass.states.get(eid)
        return None if st is None else str(st.state)

    async def wait_cal_result(
        self, kind: str, *, before: str | None, timeout_s: float = 2.5
    ) -> str | None:
        eid = self._cal_result_entity()
        if not eid:
            return None
        prefix = f"{kind}:"
        deadline = asyncio.get_running_loop().time() + max(0.5, timeout_s)
        while asyncio.get_running_loop().time() < deadline:
            st = self.hass.states.get(eid)
            cur = None if st is None else str(st.state)
            if cur and cur != before and cur.startswith(prefix):
                body = cur.split("#", 1)[0]  # strip millis uniqueness
                # body = "tds:ok" or "tds:fail:unstable"
                rest = body[len(prefix) :]
                if rest.startswith("ok"):
                    return "ok"
                if rest.startswith("fail"):
                    return rest  # fail:unstable
            await asyncio.sleep(0.15)
        return None

    def diagnostics(self) -> dict[str, Any]:
        avail: dict[str, Any] = {}
        for role, s in self.capabilities.sensors.items():
            st = self.hass.states.get(s.entity_id) if s.entity_id else None
            avail[f"sensor.{role}"] = {
                "entity_id": s.entity_id,
                "available": st is not None,
                "state": None if st is None else st.state,
            }
        for role, a in self.capabilities.actuators.items():
            eid = a.entity_id or (a.entity_ids[0] if a.entity_ids else None)
            targets = self._actuator_targets(eid) if eid else []
            avail[f"actuator.{role}"] = {
                "entity_id": eid,
                "targets": targets,
                "states": {
                    t: (None if (st := self.hass.states.get(t)) is None else st.state)
                    for t in targets
                },
            }
        return {"backend": "esphome", "availability": avail}

    def _actuator_targets(self, entity_id: str) -> list[str]:
        """Primary entity + fan/number twin for the same ESPHome PWM pump."""
        if not entity_id:
            return []
        targets = [entity_id]
        twin = self._find_pump_twin(entity_id)
        if twin and twin not in targets:
            targets.append(twin)
        return targets

    def _find_pump_twin(self, entity_id: str) -> str | None:
        domain, object_id = entity_id.split(".", 1)
        candidates: list[str] = []
        if domain == "fan":
            candidates = [
                f"number.{object_id}_control",
                f"number.{object_id}",
            ]
        elif domain == "number":
            base = object_id.removesuffix("_control")
            candidates = [f"fan.{base}"]
            if not base.endswith("_pump"):
                candidates.append(f"fan.{base}_pump")
        else:
            return None

        for cand in candidates:
            if cand != entity_id and self.hass.states.get(cand) is not None:
                return cand

        registry = er.async_get(self.hass)
        primary = registry.async_get(entity_id)
        if primary is None or not primary.device_id:
            return None
        needle = object_id.replace("_control", "").replace("_pump", "")
        prefer = "number" if domain == "fan" else "fan"
        for ent in registry.entities.values():
            if ent.device_id != primary.device_id or ent.domain != prefer:
                continue
            oid = ent.entity_id.split(".", 1)[1]
            compact = oid.replace("_control", "").replace("_pump", "")
            if needle and needle in compact:
                return ent.entity_id
        return None

    async def _write_percent(self, entity_id: str, pct: float) -> None:
        domain = entity_id.split(".", 1)[0]
        pct_i = int(round(pct))
        st = self.hass.states.get(entity_id)
        try:
            if domain == "switch":
                desired = "on" if pct_i > 0 else "off"
                if st is not None and st.state == desired:
                    return
                await self.hass.services.async_call(
                    "switch",
                    "turn_on" if desired == "on" else "turn_off",
                    {"entity_id": entity_id},
                    blocking=True,
                )
            elif domain == "fan":
                if pct_i <= 0:
                    if st is not None and st.state == "off":
                        return
                    await self.hass.services.async_call(
                        "fan", "turn_off", {"entity_id": entity_id}, blocking=True
                    )
                else:
                    await self.hass.services.async_call(
                        "fan",
                        "turn_on",
                        {"entity_id": entity_id, "percentage": pct_i},
                        blocking=True,
                    )
            elif domain == "number":
                # Skip no-op set_value (empty-tank park was spamming ESPHome every tick)
                if st is not None:
                    try:
                        if abs(float(st.state) - float(pct_i)) < 0.5:
                            return
                    except (TypeError, ValueError):
                        pass
                await self.hass.services.async_call(
                    "number",
                    "set_value",
                    {"entity_id": entity_id, "value": float(pct_i)},
                    blocking=True,
                )
            elif domain == "light":
                service = "turn_on" if pct_i > 0 else "turn_off"
                data: dict[str, Any] = {"entity_id": entity_id}
                if pct_i > 0:
                    data["brightness_pct"] = pct_i
                await self.hass.services.async_call("light", service, data, blocking=True)
            else:
                _LOGGER.warning(
                    "HydroQ cannot drive actuator domain '%s' (%s)", domain, entity_id
                )
        except Exception:  # noqa: BLE001
            _LOGGER.exception("HAL write failed for %s -> %s%%", entity_id, pct_i)
