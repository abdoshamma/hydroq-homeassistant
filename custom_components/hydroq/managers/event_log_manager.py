"""Ring-buffer event journal (internal). Persists via optional HA Store."""

from __future__ import annotations

from collections import deque
from typing import Any

from ..controller.events import DomainEvent

_MAX = 500


class EventLogManager:
    def __init__(self, maxlen: int = _MAX, store: Any | None = None) -> None:
        self._events: deque[dict[str, Any]] = deque(maxlen=maxlen)
        self._store = store
        self._dirty = False

    async def async_load(self) -> None:
        if self._store is None:
            return
        data = await self._store.async_load()
        if not data:
            return
        for item in data.get("events") or []:
            if isinstance(item, dict):
                self._events.append(item)

    async def async_flush(self) -> None:
        if self._store is None or not self._dirty:
            return
        await self._store.async_save({"events": list(self._events)})
        self._dirty = False

    def append(self, event: DomainEvent) -> None:
        self._events.append(event.as_dict())
        self._dirty = True

    def recent(self, limit: int = 50) -> list[dict[str, Any]]:
        items = list(self._events)
        return items[-limit:]

    @property
    def last_message(self) -> str | None:
        if not self._events:
            return None
        e = self._events[-1]
        return f"{e['code']}: {e['message']}"

    def diagnostics(self) -> dict[str, Any]:
        return {"count": len(self._events), "events": self.recent(100)}
