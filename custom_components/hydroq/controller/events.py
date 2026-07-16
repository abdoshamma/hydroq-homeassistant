"""Domain events emitted by managers / controller."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class DomainEvent:
    code: str
    message: str
    severity: str = "info"  # debug | info | warning | error
    data: dict[str, Any] = field(default_factory=dict)
    process: str | None = None
    source: str = "controller"
    ts: datetime = field(default_factory=lambda: datetime.now(timezone.utc))

    def as_dict(self) -> dict[str, Any]:
        return {
            "ts": self.ts.isoformat(),
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "data": self.data,
            "process": self.process,
            "source": self.source,
        }
