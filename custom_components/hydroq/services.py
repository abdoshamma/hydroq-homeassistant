"""HydroQ services → controller commands."""

from __future__ import annotations

import logging

import voluptuous as vol
from homeassistant.core import HomeAssistant, ServiceCall
from homeassistant.helpers import config_validation as cv

from .const import (
    ATTR_DURATION_MIN,
    ATTR_ENTRY_ID,
    ATTR_EVENT_NUMBER,
    ATTR_STAGE,
    DOMAIN,
)
from .controller.commands import CommandType
from .coordinator import HydroQCoordinator

_LOGGER = logging.getLogger(__name__)

SERVICE_SCHEMA = vol.Schema({vol.Required(ATTR_ENTRY_ID): cv.string})


def _coord(hass: HomeAssistant, call: ServiceCall) -> HydroQCoordinator:
    return hass.data[DOMAIN][call.data[ATTR_ENTRY_ID]]


async def async_setup_services(hass: HomeAssistant) -> None:
    async def _run(call: ServiceCall, ctype: CommandType, payload: dict | None = None) -> None:
        await _coord(hass, call).async_handle(ctype, payload)

    handlers = {
        "start_irrigation": (
            CommandType.START_IRRIGATION,
            SERVICE_SCHEMA.extend(
                {
                    vol.Optional(ATTR_DURATION_MIN): vol.Coerce(float),
                    vol.Optional(ATTR_EVENT_NUMBER): vol.Coerce(int),
                }
            ),
            lambda c: {
                "duration_min": c.data.get(ATTR_DURATION_MIN, 5),
                "event_number": c.data.get(ATTR_EVENT_NUMBER),
            },
        ),
        "stop_irrigation": (CommandType.STOP_IRRIGATION, SERVICE_SCHEMA, lambda c: None),
        "start_dosing_ph": (CommandType.START_DOSING_PH, SERVICE_SCHEMA, lambda c: None),
        "start_dosing_nutrients": (
            CommandType.START_DOSING_NUTRIENTS,
            SERVICE_SCHEMA,
            lambda c: None,
        ),
        "start_dosing_neutralize": (
            CommandType.START_DOSING_NEUTRALIZE,
            SERVICE_SCHEMA,
            lambda c: None,
        ),
        "start_balance": (CommandType.START_BALANCE, SERVICE_SCHEMA, lambda c: None),
        "stop_dosing": (CommandType.STOP_DOSING, SERVICE_SCHEMA, lambda c: None),
        "calibrate_ph": (
            CommandType.CALIBRATE,
            SERVICE_SCHEMA.extend({vol.Optional("point", default="neutral"): cv.string}),
            lambda c: {"kind": "ph", "point": c.data.get("point", "neutral")},
        ),
        "calibrate_ec": (
            CommandType.CALIBRATE,
            SERVICE_SCHEMA,
            lambda c: {"kind": "tds", "point": "std"},
        ),
        "calibrate_do": (
            CommandType.CALIBRATE,
            SERVICE_SCHEMA,
            lambda c: {"kind": "do", "point": "air"},
        ),
        "emergency_stop": (CommandType.EMERGENCY_STOP, SERVICE_SCHEMA, lambda c: None),
        "reset_emergency_stop": (CommandType.RESET_ESTOP, SERVICE_SCHEMA, lambda c: None),
        "change_growth_stage": (
            CommandType.APPLY_GROWTH_STAGE,
            SERVICE_SCHEMA.extend({vol.Required(ATTR_STAGE): cv.string}),
            lambda c: {"stage": c.data[ATTR_STAGE]},
        ),
        "apply_recipe": (
            CommandType.APPLY_GROWTH_STAGE,
            SERVICE_SCHEMA.extend({vol.Required(ATTR_STAGE): cv.string}),
            lambda c: {"stage": c.data[ATTR_STAGE]},
        ),
        "request_refill": (CommandType.REQUEST_REFILL, SERVICE_SCHEMA, lambda c: None),
        "refill_reservoir": (CommandType.REQUEST_REFILL, SERVICE_SCHEMA, lambda c: None),
        "set_maintenance_mode": (
            CommandType.SET_SYSTEM_MODE,
            SERVICE_SCHEMA,
            lambda c: {"mode": "Maintenance"},
        ),
        "start_cleaning": (
            CommandType.SET_SYSTEM_MODE,
            SERVICE_SCHEMA,
            lambda c: {"mode": "Maintenance"},
        ),
        "stop_all_pumps": (CommandType.EMERGENCY_STOP, SERVICE_SCHEMA, lambda c: None),
    }

    for name, (ctype, schema, payload_fn) in handlers.items():

        async def _handler(call: ServiceCall, ct=ctype, pfn=payload_fn) -> None:
            await _run(call, ct, pfn(call))

        hass.services.async_register(DOMAIN, name, _handler, schema=schema)

    async def _create_dashboard(_call: ServiceCall) -> None:
        from .dashboard import async_setup_lovelace

        await async_setup_lovelace(hass, force=True)

    hass.services.async_register(
        DOMAIN,
        "create_dashboard",
        _create_dashboard,
        schema=vol.Schema({}),
    )

    async def _export_support_bundle(_call: ServiceCall) -> None:
        import json
        from pathlib import Path

        from homeassistant.components.diagnostics import async_redact_data
        from homeassistant.components.persistent_notification import (
            async_create as async_create_notification,
        )

        from .const import VERSION
        from .fleet import build_support_bundle, slim_public

        to_redact = {"api_key", "password", "token", "encryption_key"}
        zones: list[dict] = []
        for entry_id, coord in list(hass.data.get(DOMAIN, {}).items()):
            if not isinstance(entry_id, str) or entry_id.startswith("_"):
                continue
            if not hasattr(coord, "controller"):
                continue
            zones.append(
                {
                    "entry_id": entry_id,
                    "zone_name": getattr(coord, "zone_name", entry_id),
                    "public": slim_public(getattr(coord, "data", None) or {}),
                    "controller": async_redact_data(
                        coord.controller.diagnostics_blob(), to_redact
                    ),
                    "entry": async_redact_data(
                        dict(coord.entry.data), to_redact
                    ),
                    "options": dict(coord.entry.options),
                }
            )

        try:
            from homeassistant.const import __version__ as ha_ver
        except Exception:  # noqa: BLE001
            ha_ver = None

        bundle = build_support_bundle(zones=zones, ha_version=ha_ver)
        out = Path(hass.config.path("hydroq_support_bundle.json"))
        out.write_text(json.dumps(bundle, indent=2, default=str), encoding="utf-8")
        async_create_notification(
            hass,
            (
                f"HydroQ support bundle written ({len(zones)} zone(s), v{VERSION}).\n\n"
                f"File: `{out}`\n\n"
                "Attach this file when contacting support. Secrets are redacted."
            ),
            title="HydroQ support bundle",
            notification_id="hydroq_support_bundle",
        )
        _LOGGER.info("HydroQ support bundle → %s (%s zones)", out, len(zones))

    hass.services.async_register(
        DOMAIN,
        "export_support_bundle",
        _export_support_bundle,
        schema=vol.Schema({}),
    )

    _LOGGER.info("HydroQ services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    for service in list(hass.services.async_services().get(DOMAIN, {})):
        hass.services.async_remove(DOMAIN, service)
