"""Plant × stage recipes — EC is canonical; TDS derived via zone TDS factor."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any

from ..const import GROWTH_STAGES
from ..models.runtime import ScheduleSlot, normalize_schedule

DEFAULT_TDS_FACTOR = 500
TDS_FACTOR_CHOICES = (500, 700)
BUILTIN_PLANT_IDS = frozenset(
    {"generic", "lettuce", "basil", "spinach", "kale", "strawberry", "tomato"}
)


def ec_to_tds(ec: float, factor: int = DEFAULT_TDS_FACTOR) -> float:
    return float(ec) * float(factor)


def tds_to_ec(tds: float, factor: int = DEFAULT_TDS_FACTOR) -> float:
    f = float(factor) or float(DEFAULT_TDS_FACTOR)
    return float(tds) / f


def _slots(*runs: tuple[int, int, int]) -> tuple[ScheduleSlot, ...]:
    """(hour, minute, duration_min) enabled runs; pad to 5."""
    out = [ScheduleSlot(True, h, m, d) for h, m, d in runs]
    while len(out) < 5:
        out.append(ScheduleSlot(False, 0, 0, 5))
    return tuple(out[:5])


def _slug(name: str) -> str:
    s = re.sub(r"[^a-z0-9]+", "_", name.strip().lower()).strip("_")
    return s or "custom"


@dataclass(frozen=True)
class Recipe:
    stage: str
    light_on: tuple[int, int]
    light_off: tuple[int, int]
    desired_ph: float
    desired_ec: float  # mS/cm — SSOT
    ph_tolerance: float
    ec_tolerance: float  # mS/cm
    schedule: tuple[ScheduleSlot, ...]
    duration_days: int = 0  # 0 = final / no auto advance

    def desired_tds(self, factor: int = DEFAULT_TDS_FACTOR) -> float:
        return ec_to_tds(self.desired_ec, factor)

    def tds_tolerance(self, factor: int = DEFAULT_TDS_FACTOR) -> float:
        return ec_to_tds(self.ec_tolerance, factor)

    def as_dict(self) -> dict[str, Any]:
        return {
            "stage": self.stage,
            "light_on": list(self.light_on),
            "light_off": list(self.light_off),
            "desired_ph": self.desired_ph,
            "desired_ec": self.desired_ec,
            "ph_tolerance": self.ph_tolerance,
            "ec_tolerance": self.ec_tolerance,
            "duration_days": self.duration_days,
            "schedule": [s.as_dict() for s in self.schedule],
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, stage: str | None = None) -> Recipe:
        st = str(stage or data.get("stage") or "Vegetative")
        lon = data.get("light_on") or [6, 0]
        loff = data.get("light_off") or [22, 0]
        if isinstance(lon, (list, tuple)) and len(lon) >= 2:
            light_on = (int(lon[0]), int(lon[1]))
        else:
            light_on = (6, 0)
        if isinstance(loff, (list, tuple)) and len(loff) >= 2:
            light_off = (int(loff[0]), int(loff[1]))
        else:
            light_off = (22, 0)
        # Accept legacy desired_tds if EC missing (assume 500-scale).
        if "desired_ec" in data and data["desired_ec"] is not None:
            desired_ec = float(data["desired_ec"])
        elif "desired_tds" in data:
            desired_ec = tds_to_ec(float(data["desired_tds"]), DEFAULT_TDS_FACTOR)
        else:
            desired_ec = 1.2
        if "ec_tolerance" in data and data.get("ec_tolerance") is not None:
            # Heuristic: values > 5 are legacy ppm tolerances.
            raw_tol = float(data["ec_tolerance"])
            ec_tol = tds_to_ec(raw_tol, DEFAULT_TDS_FACTOR) if raw_tol > 5 else raw_tol
        elif "tds_tolerance" in data:
            ec_tol = tds_to_ec(float(data["tds_tolerance"]), DEFAULT_TDS_FACTOR)
        else:
            ec_tol = 0.1
        sched = normalize_schedule(data.get("schedule"))
        return cls(
            stage=st,
            light_on=light_on,
            light_off=light_off,
            desired_ph=float(data.get("desired_ph", 6.0)),
            desired_ec=desired_ec,
            ph_tolerance=float(data.get("ph_tolerance", 0.3)),
            ec_tolerance=ec_tol,
            schedule=tuple(sched),
            duration_days=max(0, int(data.get("duration_days", 0))),
        )


@dataclass
class PlantDef:
    plant_id: str
    label: str
    stages: tuple[str, ...]
    recipes: dict[str, Recipe] = field(default_factory=dict)
    builtin: bool = True

    def as_dict(self) -> dict[str, Any]:
        return {
            "plant_id": self.plant_id,
            "label": self.label,
            "stages": list(self.stages),
            "builtin": self.builtin,
            "recipes": {k: v.as_dict() for k, v in self.recipes.items()},
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any], *, builtin: bool = False) -> PlantDef:
        plant_id = str(data.get("plant_id") or _slug(str(data.get("label", "custom"))))
        label = str(data.get("label") or plant_id.replace("_", " ").title())
        stages_raw = data.get("stages") or list(GROWTH_STAGES)
        stages = tuple(str(s) for s in stages_raw if str(s) in GROWTH_STAGES)
        if not stages:
            stages = ("Seedling", "Vegetative", "Harvest")
        recipes_in = data.get("recipes") or {}
        recipes: dict[str, Recipe] = {}
        for st in stages:
            raw = recipes_in.get(st) if isinstance(recipes_in, dict) else None
            if isinstance(raw, dict):
                recipes[st] = Recipe.from_dict(raw, stage=st)
            else:
                recipes[st] = Recipe.from_dict({"stage": st}, stage=st)
        return cls(
            plant_id=plant_id,
            label=label,
            stages=stages,
            recipes=recipes,
            builtin=builtin,
        )


def _r(
    stage: str,
    *,
    ph: float,
    ec: float,
    ph_tol: float,
    ec_tol: float,
    on: tuple[int, int],
    off: tuple[int, int],
    days: int,
    slots: tuple[ScheduleSlot, ...],
) -> Recipe:
    return Recipe(
        stage=stage,
        light_on=on,
        light_off=off,
        desired_ph=ph,
        desired_ec=ec,
        ph_tolerance=ph_tol,
        ec_tolerance=ec_tol,
        schedule=slots,
        duration_days=days,
    )


def _plant(
    plant_id: str,
    label: str,
    stages: tuple[str, ...],
    recipes: dict[str, Recipe],
) -> PlantDef:
    return PlantDef(plant_id=plant_id, label=label, stages=stages, recipes=recipes, builtin=True)


# Researched defaults — EC = TDS/500 from plan tables.
BUILTIN_PLANTS: dict[str, PlantDef] = {
    "generic": _plant(
        "generic",
        "Generic",
        GROWTH_STAGES,
        {
            "Seedling": _r(
                "Seedling",
                ph=5.8,
                ec=0.7,
                ph_tol=0.2,
                ec_tol=0.1,
                on=(6, 0),
                off=(22, 0),
                days=14,
                slots=_slots((8, 0, 5), (20, 0, 5)),
            ),
            "Vegetative": _r(
                "Vegetative",
                ph=6.0,
                ec=1.2,
                ph_tol=0.3,
                ec_tol=0.1,
                on=(6, 0),
                off=(22, 0),
                days=28,
                slots=_slots((8, 0, 10), (12, 0, 10), (16, 0, 10), (20, 0, 10)),
            ),
            "Flowering": _r(
                "Flowering",
                ph=6.0,
                ec=1.8,
                ph_tol=0.3,
                ec_tol=0.15,
                on=(6, 0),
                off=(18, 0),
                days=28,
                slots=_slots((8, 0, 8), (11, 0, 8), (14, 0, 8), (17, 0, 8), (20, 0, 8)),
            ),
            "Harvest": _r(
                "Harvest",
                ph=5.8,
                ec=0.8,
                ph_tol=0.3,
                ec_tol=0.1,
                on=(6, 0),
                off=(18, 0),
                days=0,
                slots=_slots((8, 0, 5), (16, 0, 5)),
            ),
        },
    ),
    "lettuce": _plant(
        "lettuce",
        "Lettuce",
        ("Seedling", "Vegetative", "Harvest"),
        {
            "Seedling": _r(
                "Seedling",
                ph=5.8,
                ec=0.6,
                ph_tol=0.2,
                ec_tol=0.1,
                on=(6, 0),
                off=(22, 0),
                days=10,
                slots=_slots((8, 0, 5), (20, 0, 5)),
            ),
            "Vegetative": _r(
                "Vegetative",
                ph=5.8,
                ec=0.9,
                ph_tol=0.2,
                ec_tol=0.1,
                on=(6, 0),
                off=(22, 0),
                days=25,
                slots=_slots((8, 0, 8), (12, 0, 8), (16, 0, 8), (20, 0, 8)),
            ),
            "Harvest": _r(
                "Harvest",
                ph=5.8,
                ec=1.1,
                ph_tol=0.2,
                ec_tol=0.1,
                on=(6, 0),
                off=(20, 0),
                days=0,
                slots=_slots((8, 0, 5), (16, 0, 5)),
            ),
        },
    ),
    "basil": _plant(
        "basil",
        "Basil",
        ("Seedling", "Vegetative", "Harvest"),
        {
            "Seedling": _r(
                "Seedling",
                ph=5.9,
                ec=0.8,
                ph_tol=0.3,
                ec_tol=0.15,
                on=(6, 0),
                off=(22, 0),
                days=10,
                slots=_slots((8, 0, 5), (20, 0, 5)),
            ),
            "Vegetative": _r(
                "Vegetative",
                ph=5.9,
                ec=1.4,
                ph_tol=0.3,
                ec_tol=0.2,
                on=(6, 0),
                off=(22, 0),
                days=21,
                slots=_slots((8, 0, 8), (12, 0, 8), (16, 0, 8), (20, 0, 8)),
            ),
            "Harvest": _r(
                "Harvest",
                ph=5.9,
                ec=1.6,
                ph_tol=0.3,
                ec_tol=0.2,
                on=(6, 0),
                off=(20, 0),
                days=0,
                slots=_slots((8, 0, 8), (14, 0, 8), (20, 0, 8)),
            ),
        },
    ),
    "spinach": _plant(
        "spinach",
        "Spinach",
        ("Seedling", "Vegetative", "Harvest"),
        {
            "Seedling": _r(
                "Seedling",
                ph=6.0,
                ec=1.0,
                ph_tol=0.3,
                ec_tol=0.15,
                on=(6, 0),
                off=(22, 0),
                days=12,
                slots=_slots((8, 0, 5), (20, 0, 5)),
            ),
            "Vegetative": _r(
                "Vegetative",
                ph=6.0,
                ec=1.8,
                ph_tol=0.3,
                ec_tol=0.2,
                on=(6, 0),
                off=(22, 0),
                days=28,
                slots=_slots((8, 0, 10), (12, 0, 10), (16, 0, 10), (20, 0, 10)),
            ),
            "Harvest": _r(
                "Harvest",
                ph=6.0,
                ec=2.0,
                ph_tol=0.3,
                ec_tol=0.2,
                on=(6, 0),
                off=(20, 0),
                days=0,
                slots=_slots((8, 0, 8), (14, 0, 8), (20, 0, 8)),
            ),
        },
    ),
    "kale": _plant(
        "kale",
        "Kale",
        ("Seedling", "Vegetative", "Harvest"),
        {
            "Seedling": _r(
                "Seedling",
                ph=6.0,
                ec=1.0,
                ph_tol=0.3,
                ec_tol=0.15,
                on=(6, 0),
                off=(22, 0),
                days=14,
                slots=_slots((8, 0, 5), (20, 0, 5)),
            ),
            "Vegetative": _r(
                "Vegetative",
                ph=6.0,
                ec=2.0,
                ph_tol=0.3,
                ec_tol=0.25,
                on=(6, 0),
                off=(22, 0),
                days=35,
                slots=_slots((8, 0, 10), (12, 0, 10), (16, 0, 10), (20, 0, 10)),
            ),
            "Harvest": _r(
                "Harvest",
                ph=6.0,
                ec=2.2,
                ph_tol=0.3,
                ec_tol=0.25,
                on=(6, 0),
                off=(20, 0),
                days=0,
                slots=_slots((8, 0, 8), (14, 0, 8), (20, 0, 8)),
            ),
        },
    ),
    "strawberry": _plant(
        "strawberry",
        "Strawberry",
        GROWTH_STAGES,
        {
            "Seedling": _r(
                "Seedling",
                ph=5.8,
                ec=0.9,
                ph_tol=0.2,
                ec_tol=0.15,
                on=(6, 0),
                off=(22, 0),
                days=14,
                slots=_slots((8, 0, 5), (14, 0, 5), (20, 0, 5)),
            ),
            "Vegetative": _r(
                "Vegetative",
                ph=5.8,
                ec=1.4,
                ph_tol=0.2,
                ec_tol=0.2,
                on=(6, 0),
                off=(22, 0),
                days=21,
                slots=_slots((8, 0, 8), (12, 0, 8), (16, 0, 8), (20, 0, 8)),
            ),
            "Flowering": _r(
                "Flowering",
                ph=5.8,
                ec=1.7,
                ph_tol=0.2,
                ec_tol=0.2,
                on=(6, 0),
                off=(18, 0),
                days=21,
                slots=_slots((8, 0, 8), (11, 0, 8), (14, 0, 8), (17, 0, 8), (20, 0, 8)),
            ),
            "Harvest": _r(
                "Harvest",
                ph=5.8,
                ec=1.9,
                ph_tol=0.2,
                ec_tol=0.2,
                on=(6, 0),
                off=(18, 0),
                days=0,
                slots=_slots((8, 0, 8), (12, 0, 8), (16, 0, 8), (20, 0, 8)),
            ),
        },
    ),
    "tomato": _plant(
        "tomato",
        "Tomato",
        GROWTH_STAGES,
        {
            "Seedling": _r(
                "Seedling",
                ph=5.8,
                ec=1.0,
                ph_tol=0.3,
                ec_tol=0.15,
                on=(6, 0),
                off=(22, 0),
                days=21,
                slots=_slots((8, 0, 5), (14, 0, 5), (20, 0, 5)),
            ),
            "Vegetative": _r(
                "Vegetative",
                ph=5.8,
                ec=2.4,
                ph_tol=0.3,
                ec_tol=0.3,
                on=(6, 0),
                off=(22, 0),
                days=35,
                slots=_slots((8, 0, 10), (11, 0, 10), (14, 0, 10), (17, 0, 10), (20, 0, 10)),
            ),
            "Flowering": _r(
                "Flowering",
                ph=6.0,
                ec=2.8,
                ph_tol=0.3,
                ec_tol=0.3,
                on=(6, 0),
                off=(20, 0),
                days=35,
                slots=_slots((7, 0, 12), (10, 0, 12), (13, 0, 12), (16, 0, 12), (19, 0, 12)),
            ),
            "Harvest": _r(
                "Harvest",
                ph=6.0,
                ec=2.6,
                ph_tol=0.3,
                ec_tol=0.3,
                on=(6, 0),
                off=(20, 0),
                days=0,
                slots=_slots((8, 0, 10), (12, 0, 10), (16, 0, 10), (20, 0, 10)),
            ),
        },
    ),
}


# Back-compat alias used by older callers / tests
RECIPES: dict[str, Recipe] = dict(BUILTIN_PLANTS["generic"].recipes)


def validate_custom_plant(data: dict[str, Any]) -> tuple[PlantDef | None, str | None]:
    """Return (plant, error)."""
    try:
        plant = PlantDef.from_dict(data, builtin=False)
    except Exception as err:  # noqa: BLE001
        return None, str(err)
    if not plant.label.strip():
        return None, "Plant name required"
    if plant.plant_id in BUILTIN_PLANT_IDS:
        return None, "Cannot overwrite a built-in plant id"
    if not plant.stages:
        return None, "At least one stage required"
    for st in plant.stages:
        if st not in plant.recipes:
            return None, f"Missing recipe for {st}"
        r = plant.recipes[st]
        if not (4.0 <= r.desired_ph <= 9.0):
            return None, f"{st}: pH out of range"
        if not (0.1 <= r.desired_ec <= 5.0):
            return None, f"{st}: EC out of range"
    return plant, None


def serialize_custom_recipes(plants: dict[str, PlantDef]) -> dict[str, Any]:
    customs = {pid: p.as_dict() for pid, p in plants.items() if not p.builtin}
    return {"schema": 1, "plants": customs}


def load_custom_recipes(raw: dict[str, Any] | None) -> dict[str, PlantDef]:
    if not raw or not isinstance(raw, dict):
        return {}
    plants_in = raw.get("plants") if raw.get("schema") == 1 else raw
    if not isinstance(plants_in, dict):
        return {}
    out: dict[str, PlantDef] = {}
    for pid, pdata in plants_in.items():
        if not isinstance(pdata, dict):
            continue
        if str(pid) in BUILTIN_PLANT_IDS or pdata.get("plant_id") in BUILTIN_PLANT_IDS:
            continue
        data = dict(pdata)
        data.setdefault("plant_id", pid)
        plant, err = validate_custom_plant(data)
        if plant and not err:
            out[plant.plant_id] = plant
    return out


class RecipeManager:
    def __init__(self) -> None:
        self._custom: dict[str, PlantDef] = {}

    def set_custom(self, raw: dict[str, Any] | None) -> None:
        self._custom = load_custom_recipes(raw)

    def upsert_custom(self, plant: PlantDef) -> str | None:
        if plant.plant_id in BUILTIN_PLANT_IDS:
            return "Cannot overwrite built-in plant"
        plant.builtin = False
        self._custom[plant.plant_id] = plant
        return None

    def delete_custom(self, plant_id: str) -> bool:
        if plant_id in BUILTIN_PLANT_IDS:
            return False
        return self._custom.pop(plant_id, None) is not None

    def custom_blob(self) -> dict[str, Any]:
        return serialize_custom_recipes(self._custom)

    def plants(self) -> dict[str, PlantDef]:
        out = {k: v for k, v in BUILTIN_PLANTS.items()}
        out.update(self._custom)
        return out

    def plant_options(self) -> list[str]:
        """Labels for select — use plant_id as value via mapping in entity."""
        return sorted(self.plants().keys(), key=lambda p: (p not in BUILTIN_PLANT_IDS, p))

    def plant_labels(self) -> dict[str, str]:
        return {pid: p.label for pid, p in self.plants().items()}

    def get_plant(self, plant_id: str | None) -> PlantDef:
        plants = self.plants()
        return plants.get(plant_id or "generic") or plants["generic"]

    def stages_for(self, plant_id: str | None) -> tuple[str, ...]:
        return self.get_plant(plant_id).stages

    def get(self, stage: str, plant_id: str | None = None) -> Recipe:
        """Resolve recipe for plant × stage; fall back to generic stage then Vegetative."""
        plant = self.get_plant(plant_id)
        if stage in plant.recipes:
            return plant.recipes[stage]
        generic = BUILTIN_PLANTS["generic"].recipes
        if stage in generic:
            return generic[stage]
        return generic["Vegetative"]

    def expected_stage(self, plant_id: str | None, days_after_sow: int) -> str:
        plant = self.get_plant(plant_id)
        remaining = max(0, int(days_after_sow))
        stages = plant.stages
        for i, st in enumerate(stages):
            recipe = plant.recipes.get(st) or self.get(st, plant_id)
            is_last = i == len(stages) - 1
            days = int(recipe.duration_days or 0)
            if is_last or days <= 0:
                return st
            if remaining < days:
                return st
            remaining -= days
        return stages[-1]

    def snapshot(self) -> dict[str, Any]:
        return {
            "plants": list(self.plants().keys()),
            "custom": list(self._custom.keys()),
            "stages": list(GROWTH_STAGES),
        }
