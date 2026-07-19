"""Push irrigation schedule to MCU offline brain (ESPHome NVS)."""

from __future__ import annotations

import logging
import re
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

_LOGGER = logging.getLogger(__name__)

_SLOT_SERVICE = "hydroq_set_offline_slot"
_POLICY_SERVICE = "hydroq_set_offline_policy"
_DEFAULT_MAX_HOURS = 12


def _device_name_from_entity(hass: HomeAssistant, entity_id: str | None) -> str | None:
    if not entity_id:
        return None
    from homeassistant.helpers import device_registry as dr
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    ent = registry.async_get(entity_id)
    if ent is None or not ent.device_id:
        return None
    device = dr.async_get(hass).async_get(ent.device_id)
    if device is None:
        return None
    for domain, ident in device.identifiers:
        if domain == "esphome" and ident:
            return str(ident)
    if device.name:
        return re.sub(r"[^a-z0-9]", "_", device.name.lower()).strip("_")
    return None


def _resolve_service(hass: HomeAssistant, suffix: str, entity_id: str | None) -> str | None:
    """Return esphome service name like hydroq_ctrl_01_hydroq_set_offline_slot."""
    services = hass.services.async_services().get("esphome", {})
    if not services:
        return None
    base = _device_name_from_entity(hass, entity_id)
    if base:
        candidate = f"{base}_{suffix}"
        if candidate in services:
            return candidate
        alt = base.replace("-", "_")
        candidate = f"{alt}_{suffix}"
        if candidate in services:
            return candidate
    matches = [name for name in services if name.endswith(suffix)]
    if len(matches) == 1:
        return matches[0]
    if matches:
        _LOGGER.debug("Multiple ESPHome %s services: %s", suffix, matches)
    return None


async def async_sync_offline_schedule(
    hass: HomeAssistant,
    *,
    irrigation_entity_id: str | None,
    slots: list[Any],
    enabled: bool = True,
    max_hours: int = _DEFAULT_MAX_HOURS,
) -> bool:
    """Push up to 5 slots + policy to the controller. Returns True if any call succeeded."""
    slot_svc = _resolve_service(hass, _SLOT_SERVICE, irrigation_entity_id)
    policy_svc = _resolve_service(hass, _POLICY_SERVICE, irrigation_entity_id)
    if not slot_svc and not policy_svc:
        _LOGGER.debug("Offline brain services not found; skip MCU sync")
        return False

    ok = False
    if policy_svc:
        try:
            await hass.services.async_call(
                "esphome",
                policy_svc,
                {
                    "enabled": bool(enabled),
                    "max_hours": max(1, min(48, int(max_hours))),
                },
                blocking=False,
            )
            ok = True
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Offline policy sync failed", exc_info=True)

    if not slot_svc:
        return ok

    for i in range(5):
        if i < len(slots):
            slot = slots[i]
            payload = {
                "slot": i + 1,
                "enabled": bool(getattr(slot, "enabled", False)),
                "hour": int(getattr(slot, "hour", 0)),
                "minute": int(getattr(slot, "minute", 0)),
                "duration_min": int(getattr(slot, "duration_min", 5)),
            }
        else:
            payload = {
                "slot": i + 1,
                "enabled": False,
                "hour": 0,
                "minute": 0,
                "duration_min": 5,
            }
        try:
            await hass.services.async_call(
                "esphome", slot_svc, payload, blocking=False
            )
            ok = True
        except Exception:  # noqa: BLE001
            _LOGGER.debug("Offline slot %s sync failed", i + 1, exc_info=True)
    return ok


def read_offline_status(hass: HomeAssistant, irrigation_entity_id: str | None) -> dict[str, Any]:
    """Best-effort read of Offline Mode Active / Hours Left on same ESPHome device."""
    out: dict[str, Any] = {
        "offline_mode": "unknown",
        "offline_hours_left": None,
    }
    if not irrigation_entity_id:
        return out
    from homeassistant.helpers import entity_registry as er

    registry = er.async_get(hass)
    primary = registry.async_get(irrigation_entity_id)
    if primary is None or not primary.device_id:
        return out
    active_eid = None
    hours_eid = None
    for ent in registry.entities.values():
        if ent.device_id != primary.device_id or ent.disabled:
            continue
        hay = f"{ent.entity_id} {ent.original_name or ''}".lower()
        if "offline_mode_active" in hay or "offline mode active" in hay:
            active_eid = ent.entity_id
        if "offline_hours_left" in hay or "offline hours left" in hay:
            hours_eid = ent.entity_id
    if active_eid:
        st = hass.states.get(active_eid)
        if st is not None:
            out["offline_mode"] = "active" if st.state == "on" else "idle"
    if hours_eid:
        st = hass.states.get(hours_eid)
        if st is not None and st.state not in ("unknown", "unavailable"):
            try:
                out["offline_hours_left"] = float(st.state)
            except (TypeError, ValueError):
                pass
    return out
