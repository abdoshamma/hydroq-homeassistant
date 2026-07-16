"""Typed commands accepted by HydroQController."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Any


class CommandType(StrEnum):
    START_IRRIGATION = "start_irrigation"
    STOP_IRRIGATION = "stop_irrigation"
    START_DOSING_PH = "start_dosing_ph"
    START_DOSING_NUTRIENTS = "start_dosing_nutrients"
    START_DOSING_NEUTRALIZE = "start_dosing_neutralize"
    STOP_DOSING = "stop_dosing"
    START_BALANCE = "start_balance"
    SET_LIGHTS = "set_lights"
    EMERGENCY_STOP = "emergency_stop"
    RESET_ESTOP = "reset_estop"
    APPLY_GROWTH_STAGE = "apply_growth_stage"
    SET_SYSTEM_MODE = "set_system_mode"
    SET_AUTO = "set_auto"
    SET_SETPOINT = "set_setpoint"
    SET_SCHEDULE_SLOT = "set_schedule_slot"
    TEST_PUMP = "test_pump"
    CALIBRATE = "calibrate"
    REQUEST_REFILL = "request_refill"
    ACK_FAULT = "ack_fault"
    TICK = "tick"


@dataclass(frozen=True)
class Command:
    type: CommandType
    payload: dict[str, Any] | None = None
