"""Growth-stage recipes — pure data; controller applies to other managers.

Aligned with legacy scripts2.yaml zone1_set_seedling / vegetative schedules.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models.runtime import ScheduleSlot


@dataclass(frozen=True)
class Recipe:
    stage: str
    light_on: tuple[int, int]
    light_off: tuple[int, int]
    desired_ph: float
    desired_tds: float
    ph_tolerance: float
    ec_tolerance: float
    schedule: tuple[ScheduleSlot, ...]


RECIPES: dict[str, Recipe] = {
    # Legacy: 18h light (06:00–00:00), pH 6.0 ±0.2, TDS 400 ±50, fert 2×5min
    "Seedling": Recipe(
        "Seedling",
        (6, 0),
        (0, 0),
        6.0,
        400,
        0.2,
        50,
        (
            ScheduleSlot(True, 8, 0, 5),
            ScheduleSlot(True, 20, 0, 5),
            ScheduleSlot(False, 0, 0, 5),
            ScheduleSlot(False, 0, 0, 5),
            ScheduleSlot(False, 0, 0, 5),
        ),
    ),
    # Legacy: 16h light (06–22), pH 6.2 ±0.3, TDS 800 ±100, fert 4×10min
    "Vegetative": Recipe(
        "Vegetative",
        (6, 0),
        (22, 0),
        6.2,
        800,
        0.3,
        100,
        (
            ScheduleSlot(True, 8, 0, 10),
            ScheduleSlot(True, 12, 0, 10),
            ScheduleSlot(True, 16, 0, 10),
            ScheduleSlot(True, 20, 0, 10),
            ScheduleSlot(False, 0, 0, 5),
        ),
    ),
    # Legacy flowering: 12h light (06–18), denser fertigation 6×8min
    "Flowering": Recipe(
        "Flowering",
        (6, 0),
        (18, 0),
        6.0,
        600,
        0.3,
        75,
        (
            ScheduleSlot(True, 8, 0, 8),
            ScheduleSlot(True, 11, 0, 8),
            ScheduleSlot(True, 14, 0, 8),
            ScheduleSlot(True, 17, 0, 8),
            ScheduleSlot(True, 20, 0, 8),
        ),
    ),
    "Harvest": Recipe(
        "Harvest",
        (6, 0),
        (18, 0),
        6.0,
        200,
        0.3,
        50,
        (
            ScheduleSlot(True, 8, 0, 5),
            ScheduleSlot(True, 16, 0, 5),
            ScheduleSlot(False, 0, 0, 5),
            ScheduleSlot(False, 0, 0, 5),
            ScheduleSlot(False, 0, 0, 5),
        ),
    ),
}


class RecipeManager:
    def get(self, stage: str) -> Recipe:
        return RECIPES.get(stage, RECIPES["Vegetative"])

    def snapshot(self) -> dict:
        return {"stages": list(RECIPES.keys())}
