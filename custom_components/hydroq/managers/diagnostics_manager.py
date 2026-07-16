"""Aggregates diagnostics payload for HA."""

from __future__ import annotations

from typing import Any

from ..hardware.hal import HardwareHAL
from ..managers.event_log_manager import EventLogManager


class DiagnosticsManager:
    def __init__(self, hal: HardwareHAL, event_log: EventLogManager) -> None:
        self.hal = hal
        self.event_log = event_log

    def build(self, controller_snapshot: dict[str, Any]) -> dict[str, Any]:
        return {
            "controller": controller_snapshot,
            "hal": self.hal.diagnostics(),
            "capabilities": self.hal.capabilities.as_dict(),
            "event_log": self.event_log.diagnostics(),
        }
