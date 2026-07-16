"""Installer hardware presets (expand to CapabilityMap — not runtime branches)."""

from __future__ import annotations

from dataclasses import dataclass

from ..const import PRESET_GEN1_NEUTRAL, PRESET_GEN1_PH_UP


@dataclass(frozen=True)
class PresetSpec:
    key: str
    label: str


PROFILES: dict[str, PresetSpec] = {
    PRESET_GEN1_PH_UP: PresetSpec(
        PRESET_GEN1_PH_UP,
        "Preset: Nutrient A/B/C + pH Up",
    ),
    PRESET_GEN1_NEUTRAL: PresetSpec(
        PRESET_GEN1_NEUTRAL,
        "Preset: Nutrient A/B + Neutralization + pH",
    ),
    # legacy keys still accepted in config flow
    "profile_a": PresetSpec(PRESET_GEN1_PH_UP, "Preset: Nutrient A/B/C + pH Up"),
    "profile_b": PresetSpec(PRESET_GEN1_NEUTRAL, "Preset: Nutrient A/B + Neutralization + pH"),
}


def get_profile(key: str) -> PresetSpec:
    return PROFILES.get(key, PROFILES[PRESET_GEN1_PH_UP])
