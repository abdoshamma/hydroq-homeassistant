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

    _LOGGER.info("HydroQ services registered")


async def async_unload_services(hass: HomeAssistant) -> None:
    for service in list(hass.services.async_services().get(DOMAIN, {})):
        hass.services.async_remove(DOMAIN, service)
