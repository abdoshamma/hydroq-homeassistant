"""Hardware abstraction interface."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any

from ..models.capability import CapabilityMap


class HardwareHAL(ABC):
    """All actuator/sensor I/O goes through this interface."""

    def __init__(self, capabilities: CapabilityMap) -> None:
        self.capabilities = capabilities

    def has(self, role: str) -> bool:
        return self.capabilities.has_actuator(role) or self.capabilities.has_sensor(role)

    @abstractmethod
    async def read_sensor(self, role: str) -> float | str | None:
        """Return float for numeric sensors, 'on'/'off' for binary, None if unavailable."""

    @abstractmethod
    async def set_output(self, role: str, value: float) -> None:
        """0–100 for pumps; 0/100 for relays. Lighting uses 0 or 100."""

    @abstractmethod
    async def set_group(self, role: str, on: bool, *, stagger_s: float = 0.0) -> None:
        """Relay groups (lighting). Optional stagger_s between each stand."""

    @abstractmethod
    async def press_button(self, cal_role: str) -> bool:
        """Press calibration button by cal role key."""

    @abstractmethod
    def diagnostics(self) -> dict[str, Any]:
        """Backend-specific diagnostic blob."""
