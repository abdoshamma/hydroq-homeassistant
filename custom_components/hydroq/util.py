"""Shared numeric safety helpers."""

from __future__ import annotations

import math
from typing import Any


def valid_float(value: Any) -> float | None:
    """Return finite float or None (rejects None/str/NaN/inf)."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        f = float(value)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    if math.isnan(f) or math.isinf(f):
        return None
    return f
