"""Register HydroQ Lovelace dashboard from product dashboard_views.yaml template."""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

import yaml

from homeassistant.components.http import StaticPathConfig
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.storage import Store

from .const import CONF_CAPABILITIES, CONF_CONTROLLER_DEVICE_ID, CONF_ENTITY_MAP, CONF_LIGHT_STAND_COUNT, CONF_SIMULATION, DOMAIN
from .hardware.esphome_mapping import order_light_entities
from .models.capability import CapabilityMap, ChannelRole

_LOGGER = logging.getLogger(__name__)

URL_PATH = "hydroq"
LOGO_URL = f"/{DOMAIN}/logo.png"
_DASHBOARD_FLAG = "_hydroq_dashboard_ready"
_STATIC_REGISTERED = "_hydroq_static_registered"
_PLACEHOLDER_RE = re.compile(r"__(HQ|HAL)\.([a-z0-9_]+)__")

HQ_KEYS = (
    "status",
    "health",
    "irrigation_state",
    "dosing_state",
    "last_event",
    "last_error",
    "last_cal_ph",
    "last_cal_tds",
    "last_cal_do",
    "water_ok",
    "active_alarm",
    "refill_requested",
    "simulation",
    "irrigation_active",
    "dosing_active",
    "auto_irrigation",
    "auto_lighting",
    "auto_ph",
    "auto_ec",
    "grow_lights",
    "desired_ph",
    "ph_tolerance",
    "desired_ec_tds",
    "ec_tolerance",
    "growth_stage",
    "system_mode",
    "start_irrigation",
    "stop_irrigation",
    "start_ph",
    "start_nutrients",
    "start_neutralize",
    "start_balance",
    "test_pump_a",
    "test_pump_b",
    "test_pump_c",
    "test_ph_pump",
    "test_irrigation",
    "stop_dosing",
    "emergency_stop",
    "cal_ph_neutral",
    "cal_ph_acid",
    "cal_ec",
    "cal_do",
    "request_refill",
    "sched_1_enabled",
    "sched_1_time",
    "sched_1_duration",
    "sched_1_label",
    "sched_2_enabled",
    "sched_2_time",
    "sched_2_duration",
    "sched_2_label",
    "sched_3_enabled",
    "sched_3_time",
    "sched_3_duration",
    "sched_3_label",
    "sched_4_enabled",
    "sched_4_time",
    "sched_4_duration",
    "sched_4_label",
    "sched_5_enabled",
    "sched_5_time",
    "sched_5_duration",
    "sched_5_label",
)

HAL_SENSOR_ROLES = (
    "ph",
    "tds",
    "ec",
    "do",
    "water_temp",
    "water_level",
    "emergency_stop",
    "co2",
)
HAL_ACTUATOR_ROLES = (
    ChannelRole.NUTRIENT_A.value,
    ChannelRole.NUTRIENT_B.value,
    ChannelRole.NUTRIENT_C.value,
    ChannelRole.PH_UP.value,
    ChannelRole.PH_DOWN.value,
    ChannelRole.NEUTRALIZATION.value,
    ChannelRole.IRRIGATION.value,
)

_LEGACY_ACTUATOR = {
    ChannelRole.NUTRIENT_A.value: "solution_a",
    ChannelRole.NUTRIENT_B.value: "solution_b",
    ChannelRole.NUTRIENT_C.value: "solution_c",
    ChannelRole.PH_UP.value: "ph_pump",
    ChannelRole.NEUTRALIZATION.value: "neutralization",
    ChannelRole.IRRIGATION.value: "irrigation_pump",
}


async def async_setup_lovelace(hass: HomeAssistant, *, force: bool = False) -> None:
    """Create/update the HydroQ sidebar dashboard from the YAML template."""
    await _async_register_static(hass)
    if force:
        hass.data.setdefault(DOMAIN, {}).pop(_DASHBOARD_FLAG, None)

    async def _run(*, delayed: bool = False) -> None:
        if delayed:
            import asyncio

            await asyncio.sleep(5)
            hass.data.setdefault(DOMAIN, {}).pop(_DASHBOARD_FLAG, None)
        await _async_ensure_dashboard(hass)

    if hass.is_running:
        await _run()
        # Second pass after entity registry settles (first install race)
        if not force:
            hass.async_create_task(_run(delayed=True))
    else:
        hass.bus.async_listen_once(
            "homeassistant_started",
            lambda _e: hass.async_create_task(_run()),
        )


async def _async_register_static(hass: HomeAssistant) -> None:
    """Serve www/ (logo.png, optional strategy JS) at /hydroq/."""
    if hass.data.get(DOMAIN, {}).get(_STATIC_REGISTERED):
        return
    www = Path(__file__).parent / "www"
    await hass.http.async_register_static_paths(
        [StaticPathConfig(f"/{DOMAIN}", str(www), False)]
    )
    hass.data.setdefault(DOMAIN, {})[_STATIC_REGISTERED] = True
    _LOGGER.debug("HydroQ static assets at /%s (logo: %s)", DOMAIN, LOGO_URL)


async def _async_ensure_dashboard(hass: HomeAssistant) -> None:
    if hass.data.get(DOMAIN, {}).get(_DASHBOARD_FLAG):
        return

    created = await _try_create_via_collection(hass)
    if not created:
        created = await _try_create_via_store(hass)

    if created:
        hass.data.setdefault(DOMAIN, {})[_DASHBOARD_FLAG] = True
        _LOGGER.info("HydroQ dashboard ready at /%s", URL_PATH)
    else:
        _LOGGER.warning(
            "Could not auto-create HydroQ dashboard. "
            "Install required HACS cards (Mushroom, Bubble, Mini Graph, "
            "Vertical Stack In Card), then call hydroq.create_dashboard."
        )


async def _try_create_via_collection(hass: HomeAssistant) -> bool:
    try:
        lovelace = hass.data.get("lovelace")
        if lovelace is None:
            return False
        collection = getattr(lovelace, "dashboards", None)
        if collection is None:
            return False

        if hasattr(collection, "async_create_item"):
            existing = [
                item
                for item in getattr(collection, "data", {}).values()
                if isinstance(item, dict) and item.get("url_path") == URL_PATH
            ]
            if not existing and hasattr(collection, "async_items"):
                existing = [
                    i for i in collection.async_items() if i.get("url_path") == URL_PATH
                ]
            if not existing:
                await collection.async_create_item(
                    {
                        "title": "HydroQ",
                        "icon": "mdi:sprout",
                        "url_path": URL_PATH,
                        "require_admin": False,
                        "show_in_sidebar": True,
                    }
                )
            await _async_write_views_config(hass)
            return True

        if isinstance(collection, dict) and URL_PATH in collection:
            await _async_write_views_config(hass)
            return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Lovelace collection create failed: %s", err)
    return False


async def _try_create_via_store(hass: HomeAssistant) -> bool:
    try:
        dash_store: Store[dict[str, Any]] = Store(hass, 1, "lovelace_dashboards")
        data = await dash_store.async_load()
        if data is None:
            data = {"items": []}
        items: list[dict[str, Any]] = list(data.get("items") or [])
        if not any(i.get("url_path") == URL_PATH for i in items):
            items.append(
                {
                    "id": "hydroq",
                    "show_in_sidebar": True,
                    "icon": "mdi:sprout",
                    "title": "HydroQ",
                    "require_admin": False,
                    "mode": "storage",
                    "url_path": URL_PATH,
                }
            )
            await dash_store.async_save({"items": items})
            _LOGGER.info(
                "Wrote HydroQ entry to lovelace_dashboards — restart HA if missing from sidebar"
            )
        await _async_write_views_config(hass)
        return True
    except Exception as err:  # noqa: BLE001
        _LOGGER.debug("Lovelace store create failed: %s", err)
        return False


async def _async_write_views_config(hass: HomeAssistant) -> None:
    """Resolve template placeholders and write lovelace.hydroq config."""
    replacements = _collect_replacements(hass)
    config = await hass.async_add_executor_job(_load_and_resolve_template, replacements)
    if not config:
        _LOGGER.warning("HydroQ dashboard template resolved empty; skipping write")
        return

    overview = _build_zones_overview(hass)
    if overview and isinstance(config.get("views"), list):
        config["views"] = [overview] + list(config["views"])

    store: Store[dict[str, Any]] = Store(hass, 1, f"lovelace.{URL_PATH}")
    existing = await store.async_load()
    if existing and isinstance(existing, dict):
        cfg = existing.get("config") or existing
        if (
            isinstance(cfg, dict)
            and cfg.get("views")
            and not cfg.get("_hydroq_managed")
            and "strategy" not in cfg
        ):
            _LOGGER.debug("HydroQ dashboard has custom unmanaged views; leaving unchanged")
            return

    config["_hydroq_managed"] = True
    await store.async_save({"config": config})


def _build_zones_overview(hass: HomeAssistant) -> dict[str, Any] | None:
    """First-tab overview when 2+ HydroQ zones are installed."""
    cards: list[dict[str, Any]] = []
    registry = er.async_get(hass)
    zones = 0
    for entry_id, coordinator in list(hass.data.get(DOMAIN, {}).items()):
        if not isinstance(entry_id, str) or entry_id.startswith("_"):
            continue
        if not hasattr(coordinator, "entry"):
            continue
        zones += 1
        entry = coordinator.entry
        name = getattr(coordinator, "zone_name", None) or entry.title or "Zone"
        prefix = f"{entry.entry_id}_"
        found: dict[str, str] = {}
        for ent in registry.entities.values():
            if ent.platform != DOMAIN or not (ent.unique_id or "").startswith(prefix):
                continue
            key = (ent.unique_id or "")[len(prefix) :]
            if key in ("status", "health", "water_ok", "active_alarm", "growth_stage", "irrigation_active"):
                found[key] = ent.entity_id
        stack: list[Any] = [
            {"type": "markdown", "content": f"### {name}"},
        ]
        for key, label in (
            ("status", "Status"),
            ("health", "Health"),
            ("water_ok", "Water OK"),
            ("active_alarm", "Alarm"),
            ("growth_stage", "Stage"),
            ("irrigation_active", "Irrigation"),
        ):
            eid = found.get(key)
            if not eid:
                continue
            stack.append(
                {
                    "type": "custom:mushroom-entity-card",
                    "entity": eid,
                    "name": label,
                    "layout": "horizontal",
                }
            )
        cards.append({"type": "custom:vertical-stack-in-card", "cards": stack})

    if zones < 2:
        return None
    return {
        "type": "sections",
        "title": "Zones",
        "path": "zones",
        "icon": "mdi:view-dashboard-variant",
        "max_columns": 4,
        "sections": [
            {
                "type": "grid",
                "column_span": 4,
                "cards": [
                    {
                        "type": "heading",
                        "heading": "All zones",
                        "heading_style": "title",
                        "icon": "mdi:sprout",
                    },
                    {
                        "type": "markdown",
                        "content": "Each card is one HydroQ zone. Open **Overview** for the primary operator view.",
                    },
                    {
                        "type": "grid",
                        "columns": 2,
                        "square": False,
                        "cards": cards,
                    },
                ],
            }
        ],
    }


def _load_and_resolve_template(replacements: dict[str, str]) -> dict[str, Any] | None:
    template_path = Path(__file__).parent / "dashboard_views.yaml"
    if not template_path.is_file():
        _LOGGER.error("Missing dashboard template: %s", template_path)
        return None

    text = template_path.read_text(encoding="utf-8")
    for key, entity_id in replacements.items():
        text = text.replace(key, entity_id)
    text = _PLACEHOLDER_RE.sub("", text)

    try:
        data = yaml.safe_load(text)
    except yaml.YAMLError as err:
        _LOGGER.error("HydroQ dashboard YAML parse failed: %s", err)
        return None

    if not isinstance(data, dict) or "views" not in data:
        return None

    return {"title": "HydroQ", "views": _prune_empty_entities(data["views"])}


def _collect_replacements(hass: HomeAssistant) -> dict[str, str]:
    """Map __HQ.key__ / __HAL.role__ placeholders to live entity_ids."""
    out: dict[str, str] = {}
    registry = er.async_get(hass)
    known = {e.entity_id for e in registry.entities.values() if not e.disabled_by}

    def _ok(eid: str | None) -> bool:
        if not eid or not isinstance(eid, str):
            return False
        if eid.startswith("sim.") or eid.startswith("__"):
            return False
        return eid in known or hass.states.get(eid) is not None

    for entry_id, coordinator in list(hass.data.get(DOMAIN, {}).items()):
        if not isinstance(entry_id, str) or entry_id.startswith("_"):
            continue
        if not hasattr(coordinator, "entry"):
            continue
        entry = coordinator.entry
        for ent in registry.entities.values():
            if ent.platform != DOMAIN or ent.disabled_by or ent.hidden_by:
                continue
            uid = ent.unique_id or ""
            prefix = f"{entry.entry_id}_"
            if not uid.startswith(prefix):
                continue
            key = uid[len(prefix) :]
            if key in HQ_KEYS and _ok(ent.entity_id):
                out[f"__HQ.{key}__"] = ent.entity_id

        # Simulation: skip HAL wiring — no real ESPHome entities to show
        if entry.data.get(CONF_SIMULATION):
            continue

        caps_raw = entry.data.get(CONF_CAPABILITIES)
        emap = entry.data.get(CONF_ENTITY_MAP) or {}
        caps = CapabilityMap.from_dict(caps_raw) if caps_raw else CapabilityMap()
        if caps.simulation:
            continue

        for role in HAL_SENSOR_ROLES:
            eid = None
            if caps.has_sensor(role):
                eid = caps.sensors[role].entity_id
            elif emap.get(role):
                eid = emap.get(role)
            if _ok(eid):
                out[f"__HAL.{role}__"] = eid  # type: ignore[arg-type]

        for role in HAL_ACTUATOR_ROLES:
            eid = None
            ch = caps.actuators.get(role)
            if ch and ch.entity_id:
                eid = ch.entity_id
            else:
                legacy = _LEGACY_ACTUATOR.get(role)
                if legacy and emap.get(legacy):
                    eid = emap[legacy]
            if _ok(eid):
                out[f"__HAL.{role}__"] = eid  # type: ignore[arg-type]

        light_ids: list[str] = []
        light_ch = caps.actuators.get(ChannelRole.LIGHTING.value)
        if light_ch:
            light_ids = list(light_ch.entity_ids or [])
            if light_ch.entity_id:
                light_ids.insert(0, light_ch.entity_id)
        elif isinstance(emap.get("lights"), list):
            light_ids = list(emap["lights"])
        light_ids = order_light_entities(
            hass,
            light_ids,
            entry.data.get(CONF_CONTROLLER_DEVICE_ID),
        )
        max_stands = int(entry.data.get(CONF_LIGHT_STAND_COUNT, 4) or 4)
        light_ids = light_ids[: min(max_stands, 20)]
        for i, eid in enumerate(light_ids):
            if _ok(eid):
                out[f"__HAL.light_{i}__"] = eid

    _LOGGER.info(
        "HydroQ dashboard placeholders resolved: %s HQ, %s HAL",
        sum(1 for k in out if k.startswith("__HQ.")),
        sum(1 for k in out if k.startswith("__HAL.")),
    )
    return out


def _prune_empty_entities(obj: Any) -> Any:
    """Remove cards / badges that reference an empty entity after unresolved strip."""
    if isinstance(obj, list):
        pruned = [_prune_empty_entities(x) for x in obj]
        return [x for x in pruned if not _is_empty_card(x)]
    if isinstance(obj, dict):
        result = {k: _prune_empty_entities(v) for k, v in obj.items()}
        # Drop broken sub_buttons (Bubble Card)
        if "sub_button" in result and isinstance(result["sub_button"], list):
            result["sub_button"] = [
                s
                for s in result["sub_button"]
                if not (
                    isinstance(s, dict)
                    and "entity" in s
                    and _is_empty_ref(s.get("entity"))
                )
            ]
        for key in ("cards", "badges", "chips"):
            if key in result and isinstance(result[key], list):
                result[key] = [x for x in result[key] if not _is_empty_card(x)]
        if "entities" in result and isinstance(result["entities"], list):
            cleaned: list[Any] = []
            for x in result["entities"]:
                if isinstance(x, dict):
                    ent = x.get("entity")
                    if not ent or str(ent).startswith("__"):
                        continue
                elif isinstance(x, str) and (not x or x.startswith("__")):
                    continue
                cleaned.append(x)
            result["entities"] = cleaned
        return result
    return obj


def _is_empty_ref(val: Any) -> bool:
    return (
        val is None
        or val == ""
        or (isinstance(val, str) and (val.startswith("__") or val.startswith("sim.")))
    )


def _is_empty_card(card: Any) -> bool:
    if not isinstance(card, dict):
        return False
    if "entity" in card and _is_empty_ref(card.get("entity")):
        return True
    # Nested entity refs in sub_buttons without a top-level entity
    subs = card.get("sub_button")
    if isinstance(subs, list) and card.get("type", "").startswith("custom:bubble"):
        if not card.get("entity") and (
            not subs
            or all(isinstance(s, dict) and _is_empty_ref(s.get("entity")) for s in subs)
        ):
            # keep separators that only have a name
            if card.get("card_type") != "separator":
                pass
    ents = card.get("entities")
    if isinstance(ents, list) and card.get("type") == "custom:mini-graph-card":
        if not ents or all(
            isinstance(e, dict) and _is_empty_ref(e.get("entity")) for e in ents
        ):
            return True
    ctype = card.get("type")
    if ctype in (
        "horizontal-stack",
        "vertical-stack",
        "grid",
        "custom:vertical-stack-in-card",
    ):
        kids = card.get("cards")
        if isinstance(kids, list) and len(kids) == 0:
            return True
    if ctype == "markdown":
        content = card.get("content")
        if content is None or (isinstance(content, str) and not content.strip()):
            return True
    for action_key in ("tap_action", "hold_action", "double_tap_action"):
        action = card.get(action_key)
        if not isinstance(action, dict):
            continue
        target = action.get("target")
        if isinstance(target, dict) and _is_empty_ref(target.get("entity_id")):
            return True
    return False


@callback
def async_get_dashboard_url() -> str:
    return f"/{URL_PATH}"
