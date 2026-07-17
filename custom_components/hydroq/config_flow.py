"""Config flow for HydroQ."""

from __future__ import annotations

from typing import Any

import voluptuous as vol

from homeassistant import config_entries
from homeassistant.core import HomeAssistant, callback
from homeassistant.data_entry_flow import FlowResult
from homeassistant.helpers import device_registry as dr, selector

from .const import (
    CONF_CAPABILITIES,
    CONF_CONTROLLER_DEVICE_ID,
    CONF_CUSTOM_RECIPES,
    CONF_ENTITY_MAP,
    CONF_HARDWARE_PROFILE,
    CONF_LEVEL_SENSOR_TYPE,
    CONF_LIGHT_STAND_COUNT,
    CONF_MAX_DOSE_ML_DAY,
    CONF_PUMP_ML_PER_MIN,
    CONF_RESERVOIR_VOLUME_L,
    CONF_SIMULATION,
    CONF_TDS_FACTOR,
    CONF_ZONE_NAME,
    CONTROLLER_LIGHT_STANDS,
    DEFAULT_MAX_DOSE_ML_DAY,
    DEFAULT_TDS_FACTOR,
    DOMAIN,
    GROWTH_STAGES,
    LEVEL_BINARY,
    LIGHT_STAND_CHOICES,
    PROFILE_A,
    TDS_FACTOR_CHOICES,
)
from .hardware.esphome_mapping import order_light_entities, suggest_entity_map
from .hardware.profiles import PROFILES
from .managers.recipe_manager import (
    BUILTIN_PLANTS,
    PlantDef,
    Recipe,
    RecipeManager,
    _coerce_stages,
    _slug,
    load_custom_recipes,
    serialize_custom_recipes,
    validate_custom_plant,
)
from .models.capability import legacy_entity_map_to_capabilities
from .models.runtime import ScheduleSlot, normalize_schedule


def _hm_to_time(hour: int, minute: int) -> str:
    """HA TimeSelector value (HH:MM:SS)."""
    return f"{int(hour):02d}:{int(minute):02d}:00"


def _time_to_hm(value: Any) -> tuple[int, int]:
    """Parse TimeSelector / HH:MM[:SS] into (hour, minute)."""
    if hasattr(value, "hour") and hasattr(value, "minute"):
        return int(value.hour), int(value.minute)
    parts = str(value or "0:0").strip().split(":")
    hour = int(parts[0]) if parts and parts[0] != "" else 0
    minute = int(parts[1]) if len(parts) > 1 and parts[1] != "" else 0
    return max(0, min(23, hour)), max(0, min(59, minute))


def _trim_lights(
    hass: HomeAssistant | None,
    lights: list[str] | None,
    count: int,
    controller_device_id: str | None = None,
) -> list[str]:
    if count <= 0 or not lights:
        return []
    if isinstance(lights, str):
        lights = [x.strip() for x in lights.split(",") if x.strip()]
    ordered = (
        order_light_entities(hass, list(lights), controller_device_id)
        if hass is not None
        else list(lights)
    )
    return ordered[:count]


def _rebuild_capabilities(data: dict[str, Any]) -> dict[str, Any]:
    ml = float(data.get(CONF_PUMP_ML_PER_MIN, 50))
    emap = dict(data.get(CONF_ENTITY_MAP, {}) or {})
    count = int(data.get(CONF_LIGHT_STAND_COUNT, CONTROLLER_LIGHT_STANDS) or 0)
    if "lights" in emap:
        emap["lights"] = _trim_lights(
            None,
            emap.get("lights"),
            count,
            data.get(CONF_CONTROLLER_DEVICE_ID),
        )
    caps = legacy_entity_map_to_capabilities(
        emap,
        preset_id=data.get(CONF_HARDWARE_PROFILE),
        ml_per_min=ml,
        simulation=bool(data.get(CONF_SIMULATION, False)),
    )
    return caps.as_dict()


class HydroQConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Install a HydroQ zone."""

    VERSION = 2

    def __init__(self) -> None:
        self._data: dict[str, Any] = {}

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        return await self.async_step_controller()

    async def async_step_controller(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            self._data[CONF_ZONE_NAME] = user_input[CONF_ZONE_NAME]
            self._data[CONF_CONTROLLER_DEVICE_ID] = user_input[CONF_CONTROLLER_DEVICE_ID]
            self._data[CONF_HARDWARE_PROFILE] = user_input[CONF_HARDWARE_PROFILE]
            await self.async_set_unique_id(user_input[CONF_CONTROLLER_DEVICE_ID])
            self._abort_if_unique_id_configured()
            return await self.async_step_lighting()

        devices = {
            d.id: f"{d.name_by_user or d.name}"
            for d in dr.async_get(self.hass).devices.values()
            if d.name
        }
        if not devices:
            return self.async_abort(reason="no_devices")

        schema = vol.Schema(
            {
                vol.Required(CONF_ZONE_NAME, default="Grow Zone"): str,
                vol.Required(CONF_CONTROLLER_DEVICE_ID): vol.In(devices),
                vol.Required(CONF_HARDWARE_PROFILE, default=PROFILE_A): vol.In(
                    {k: v.label for k, v in PROFILES.items()}
                ),
            }
        )
        return self.async_show_form(step_id="controller", data_schema=schema, errors=errors)

    async def async_step_lighting(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Choose lighting kit size (0 / 4 / 8 / 16)."""
        if user_input is not None:
            self._data[CONF_LIGHT_STAND_COUNT] = int(user_input[CONF_LIGHT_STAND_COUNT])
            return await self.async_step_mapping()

        schema = vol.Schema(
            {
                vol.Required(CONF_LIGHT_STAND_COUNT, default=CONTROLLER_LIGHT_STANDS): vol.In(
                    LIGHT_STAND_CHOICES
                ),
            }
        )
        return self.async_show_form(step_id="lighting", data_schema=schema)

    async def async_step_mapping(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        light_count = int(self._data.get(CONF_LIGHT_STAND_COUNT, CONTROLLER_LIGHT_STANDS))
        suggested = suggest_entity_map(
            self.hass,
            self._data.get(CONF_CONTROLLER_DEVICE_ID),
            self._data.get(CONF_HARDWARE_PROFILE, PROFILE_A),
            max_lights=light_count,
        )
        if user_input is not None:
            lights = _trim_lights(
                self.hass,
                user_input.get("lights"),
                light_count,
                self._data.get(CONF_CONTROLLER_DEVICE_ID),
            )
            emap = {
                "ph": user_input.get("ph"),
                "tds": user_input.get("tds"),
                "ec": user_input.get("ec"),
                "do": user_input.get("do"),
                "do_raw": user_input.get("do_raw"),
                "water_temp": user_input.get("water_temp"),
                "water_level": user_input.get("water_level"),
                "emergency_stop": user_input.get("emergency_stop"),
                "co2": user_input.get("co2"),
                "iaq": user_input.get("iaq"),
                "air_pressure": user_input.get("air_pressure"),
                "air_humidity": user_input.get("air_humidity"),
                "air_temp": user_input.get("air_temp"),
                "eco2": user_input.get("eco2"),
                "bvoc": user_input.get("bvoc"),
                "irrigation_pump": user_input.get("irrigation_pump"),
                "solution_a": user_input.get("solution_a"),
                "solution_b": user_input.get("solution_b"),
                "solution_c": user_input.get("solution_c"),
                "ph_pump": user_input.get("ph_pump"),
                "neutralization": user_input.get("neutralization"),
                "cal_ph_neutral": user_input.get("cal_ph_neutral"),
                "cal_ph_acid": user_input.get("cal_ph_acid"),
                "cal_tds": user_input.get("cal_tds"),
                "cal_do": user_input.get("cal_do"),
            }
            if lights:
                emap["lights"] = lights
            self._data[CONF_ENTITY_MAP] = {k: v for k, v in emap.items() if v}
            return await self.async_step_reservoir()

        def _field(key: str, sel: Any) -> tuple[Any, Any]:
            val = suggested.get(key)
            marker = vol.Optional(key) if val is None else vol.Optional(key, default=val)
            return marker, sel

        entity_sel = selector.EntitySelector(
            selector.EntitySelectorConfig(multiple=False)
        )
        button_sel = selector.EntitySelector(
            selector.EntitySelectorConfig(domain="button", multiple=False)
        )
        schema_dict: dict[Any, Any] = {}
        for key, sel in (
            ("ph", entity_sel),
            ("tds", entity_sel),
            ("ec", entity_sel),
            ("do", entity_sel),
            ("do_raw", entity_sel),
            ("water_temp", entity_sel),
            ("water_level", entity_sel),
            ("emergency_stop", entity_sel),
            ("co2", entity_sel),
            ("iaq", entity_sel),
            ("air_pressure", entity_sel),
            ("air_humidity", entity_sel),
            ("air_temp", entity_sel),
            ("eco2", entity_sel),
            ("bvoc", entity_sel),
            ("irrigation_pump", entity_sel),
            ("solution_a", entity_sel),
            ("solution_b", entity_sel),
            ("ph_pump", entity_sel),
            ("cal_ph_neutral", button_sel),
            ("cal_ph_acid", button_sel),
            ("cal_tds", button_sel),
            ("cal_do", button_sel),
        ):
            marker, field_sel = _field(key, sel)
            schema_dict[marker] = field_sel

        if light_count > 0:
            lights_sel = selector.EntitySelector(
                selector.EntitySelectorConfig(domain="switch", multiple=True)
            )
            suggested_lights = suggested.get("lights") or []
            if isinstance(suggested_lights, list) and suggested_lights:
                schema_dict[vol.Optional("lights", default=suggested_lights)] = lights_sel
            else:
                schema_dict[vol.Optional("lights")] = lights_sel

        pump_key = (
            "solution_c"
            if self._data.get(CONF_HARDWARE_PROFILE) == PROFILE_A
            else "neutralization"
        )
        marker, field_sel = _field(pump_key, entity_sel)
        schema_dict[marker] = field_sel

        return self.async_show_form(step_id="mapping", data_schema=vol.Schema(schema_dict))

    async def async_step_reservoir(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            self._data[CONF_RESERVOIR_VOLUME_L] = user_input[CONF_RESERVOIR_VOLUME_L]
            self._data[CONF_LEVEL_SENSOR_TYPE] = user_input[CONF_LEVEL_SENSOR_TYPE]
            self._data[CONF_PUMP_ML_PER_MIN] = user_input[CONF_PUMP_ML_PER_MIN]
            self._data[CONF_SIMULATION] = bool(user_input.get(CONF_SIMULATION, False))
            return await self.async_step_frontend()

        schema = vol.Schema(
            {
                vol.Required(CONF_RESERVOIR_VOLUME_L, default=100): vol.Coerce(float),
                vol.Required(CONF_LEVEL_SENSOR_TYPE, default=LEVEL_BINARY): vol.In(
                    {LEVEL_BINARY: "Binary float switch", "ultrasonic": "Ultrasonic"}
                ),
                vol.Required(CONF_PUMP_ML_PER_MIN, default=50): vol.Coerce(float),
                vol.Optional(CONF_SIMULATION, default=False): bool,
            }
        )
        return self.async_show_form(step_id="reservoir", data_schema=schema)

    async def async_step_frontend(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            if not user_input.get("cards_installed"):
                errors["cards_installed"] = "cards_required"
            else:
                self._data[CONF_CAPABILITIES] = _rebuild_capabilities(self._data)
                self._data.setdefault(CONF_LIGHT_STAND_COUNT, CONTROLLER_LIGHT_STANDS)
                return self.async_create_entry(
                    title=self._data[CONF_ZONE_NAME],
                    data=self._data,
                    options={
                        "desired_ph": 6.2,
                        "ph_tolerance": 0.3,
                        "desired_tds": 400,
                        "tds_tolerance": 50,
                    },
                )

        schema = vol.Schema(
            {
                vol.Required("cards_installed", default=False): bool,
            }
        )
        return self.async_show_form(
            step_id="frontend", data_schema=schema, errors=errors
        )

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: config_entries.ConfigEntry):
        return HydroQOptionsFlow()


class HydroQOptionsFlow(config_entries.OptionsFlow):
    """Setpoints, lighting remap, TDS scale, and custom recipes."""

    def __init__(self) -> None:
        self._recipe_draft: dict[str, Any] = {}
        self._stage_index = 0

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            nxt = user_input.get("next")
            if nxt == "lighting":
                return await self.async_step_lighting()
            if nxt == "recipes":
                return await self.async_step_recipes()
            if nxt == "tds_scale":
                return await self.async_step_tds_scale()
            return self.async_create_entry(
                title="",
                data={
                    **{
                        k: v
                        for k, v in self.config_entry.options.items()
                        if k
                        not in (
                            "desired_ph",
                            "ph_tolerance",
                            "desired_tds",
                            "tds_tolerance",
                            CONF_MAX_DOSE_ML_DAY,
                        )
                    },
                    "desired_ph": user_input["desired_ph"],
                    "ph_tolerance": user_input["ph_tolerance"],
                    "desired_tds": user_input["desired_tds"],
                    "tds_tolerance": user_input["tds_tolerance"],
                    CONF_MAX_DOSE_ML_DAY: user_input[CONF_MAX_DOSE_ML_DAY],
                },
            )

        opts = self.config_entry.options
        schema = vol.Schema(
            {
                vol.Required("desired_ph", default=opts.get("desired_ph", 6.2)): vol.Coerce(
                    float
                ),
                vol.Required(
                    "ph_tolerance", default=opts.get("ph_tolerance", 0.3)
                ): vol.Coerce(float),
                vol.Required("desired_tds", default=opts.get("desired_tds", 400)): vol.Coerce(
                    float
                ),
                vol.Required(
                    "tds_tolerance", default=opts.get("tds_tolerance", 50)
                ): vol.Coerce(float),
                vol.Required(
                    CONF_MAX_DOSE_ML_DAY,
                    default=opts.get(CONF_MAX_DOSE_ML_DAY, DEFAULT_MAX_DOSE_ML_DAY),
                ): vol.Coerce(float),
                vol.Optional("next", default="setpoints"): vol.In(
                    {
                        "setpoints": "Save setpoints",
                        "lighting": "Change lighting kit / remap stands…",
                        "tds_scale": "TDS meter scale (500 / 700)…",
                        "recipes": "Manage plant recipes…",
                    }
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

    async def async_step_tds_scale(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        opts = dict(self.config_entry.options)
        if user_input is not None:
            opts[CONF_TDS_FACTOR] = int(user_input[CONF_TDS_FACTOR])
            return self.async_create_entry(title="", data=opts)
        current = int(opts.get(CONF_TDS_FACTOR, DEFAULT_TDS_FACTOR) or DEFAULT_TDS_FACTOR)
        schema = vol.Schema(
            {
                vol.Required(CONF_TDS_FACTOR, default=current): vol.In(TDS_FACTOR_CHOICES),
            }
        )
        return self.async_show_form(step_id="tds_scale", data_schema=schema)

    async def async_step_recipes(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        customs = load_custom_recipes(self.config_entry.options.get(CONF_CUSTOM_RECIPES))
        custom_ids = sorted(customs.keys())
        builtin_ids = [p for p in ("lettuce", "basil", "spinach", "kale", "strawberry", "tomato", "generic")]

        if user_input is not None:
            action = user_input["action"]
            if action == "from_template":
                return await self.async_step_recipe_from_template()
            if action == "blank":
                # Prefill leafy-style stages from generic so stage screens have values.
                src = BUILTIN_PLANTS["generic"]
                self._recipe_draft = {
                    "mode": "add",
                    "label": "My Crop",
                    "stages": ["Seedling", "Vegetative", "Harvest"],
                    "recipes": {
                        k: v.as_dict()
                        for k, v in src.recipes.items()
                        if k in ("Seedling", "Vegetative", "Harvest")
                    },
                }
                return await self.async_step_recipe_plant()
            if action == "edit":
                if not custom_ids:
                    return self.async_show_form(
                        step_id="recipes",
                        data_schema=self._recipes_schema(customs, builtin_ids),
                        errors={"base": "no_custom"},
                    )
                return await self.async_step_recipe_pick_edit()
            if action == "delete":
                if not custom_ids:
                    return self.async_show_form(
                        step_id="recipes",
                        data_schema=self._recipes_schema(customs, builtin_ids),
                        errors={"base": "no_custom"},
                    )
                return await self.async_step_recipe_pick_delete()
            return await self.async_step_init()

        return self.async_show_form(
            step_id="recipes",
            data_schema=self._recipes_schema(customs, builtin_ids),
        )

    def _recipes_schema(self, customs: dict, builtin_ids: list[str]) -> vol.Schema:
        return vol.Schema(
            {
                vol.Required("action", default="from_template"): vol.In(
                    {
                        "from_template": "Create from template (recommended)",
                        "blank": "Create blank plant",
                        "edit": "Edit my custom plant",
                        "delete": "Delete my custom plant",
                        "back": "Back",
                    }
                ),
            }
        )

    async def async_step_recipe_from_template(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        """One-screen create: pick template + name → save."""
        errors: dict[str, str] = {}
        builtin_ids = [
            p for p in ("lettuce", "basil", "spinach", "kale", "strawberry", "tomato", "generic")
        ]
        if user_input is not None:
            label = str(user_input["label"]).strip()
            src_id = str(user_input["template"])
            if not label:
                errors["base"] = "name_required"
            elif src_id not in BUILTIN_PLANTS:
                errors["base"] = "stages_required"
            else:
                src = BUILTIN_PLANTS[src_id]
                plant_id = f"custom_{_slug(label)}"
                # Avoid clobbering an existing custom id
                customs = load_custom_recipes(
                    self.config_entry.options.get(CONF_CUSTOM_RECIPES)
                )
                if plant_id in customs:
                    plant_id = f"custom_{_slug(label)}_{len(customs)+1}"
                plant_data = {
                    "plant_id": plant_id,
                    "label": label,
                    "stages": list(src.stages),
                    "recipes": {k: v.as_dict() for k, v in src.recipes.items()},
                }
                plant, err = validate_custom_plant(plant_data)
                if err or plant is None:
                    errors["base"] = "recipe_invalid"
                    self._recipe_draft["last_error"] = err or "Validation failed"
                else:
                    customs[plant.plant_id] = plant
                    opts = dict(self.config_entry.options)
                    opts[CONF_CUSTOM_RECIPES] = serialize_custom_recipes(customs)
                    return self.async_create_entry(title="", data=opts)

        hint = (
            self._recipe_draft.get("last_error")
            if errors
            else "Copies all stage targets (pH, EC, lights, irrigation). You can edit later."
        )
        schema = vol.Schema(
            {
                vol.Required("template", default="lettuce"): vol.In(
                    {pid: BUILTIN_PLANTS[pid].label for pid in builtin_ids}
                ),
                vol.Required("label", default="My Lettuce"): str,
            }
        )
        return self.async_show_form(
            step_id="recipe_from_template",
            data_schema=schema,
            errors=errors,
            description_placeholders={"hint": hint or ""},
        )

    async def async_step_recipe_pick_edit(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        customs = load_custom_recipes(self.config_entry.options.get(CONF_CUSTOM_RECIPES))
        if user_input is not None:
            pid = user_input["custom_plant"]
            plant = customs[pid]
            self._recipe_draft = {
                "mode": "edit",
                "plant_id": plant.plant_id,
                "label": plant.label,
                "stages": list(plant.stages),
                "recipes": {k: v.as_dict() for k, v in plant.recipes.items()},
            }
            self._stage_index = 0
            return await self.async_step_recipe_stage()
        schema = vol.Schema(
            {
                vol.Required("custom_plant"): vol.In(
                    {pid: p.label for pid, p in customs.items()}
                ),
            }
        )
        return self.async_show_form(step_id="recipe_pick_edit", data_schema=schema)

    async def async_step_recipe_pick_delete(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        customs = load_custom_recipes(self.config_entry.options.get(CONF_CUSTOM_RECIPES))
        if user_input is not None:
            pid = user_input["custom_plant"]
            customs.pop(pid, None)
            opts = dict(self.config_entry.options)
            opts[CONF_CUSTOM_RECIPES] = serialize_custom_recipes(customs)
            if opts.get("plant_id") == pid:
                opts["plant_id"] = "generic"
                opts["auto_stage"] = False
                opts["sow_date"] = None
            return self.async_create_entry(title="", data=opts)
        schema = vol.Schema(
            {
                vol.Required("custom_plant"): vol.In(
                    {pid: p.label for pid, p in customs.items()}
                ),
            }
        )
        return self.async_show_form(step_id="recipe_pick_delete", data_schema=schema)

    async def async_step_recipe_plant(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        errors: dict[str, str] = {}
        if user_input is not None:
            label = str(user_input["label"]).strip()
            stages = _coerce_stages(user_input.get("stages"))
            if not label:
                errors["base"] = "name_required"
            elif not stages:
                errors["base"] = "stages_required"
            else:
                plant_id = self._recipe_draft.get("plant_id") or f"custom_{_slug(label)}"
                if not str(plant_id).startswith("custom_"):
                    plant_id = f"custom_{_slug(label)}"
                self._recipe_draft["label"] = label
                self._recipe_draft["plant_id"] = plant_id
                self._recipe_draft["stages"] = list(stages)
                # Prefer existing stage data; fill missing from generic.
                generic = BUILTIN_PLANTS["generic"].recipes
                kept: dict[str, Any] = {}
                for st in stages:
                    existing = self._recipe_draft.get("recipes", {}).get(st)
                    if isinstance(existing, dict) and existing:
                        kept[st] = existing
                    elif st in generic:
                        kept[st] = generic[st].as_dict()
                    else:
                        kept[st] = {"stage": st}
                self._recipe_draft["recipes"] = kept
                self._stage_index = 0
                return await self.async_step_recipe_stage()

        defaults = self._recipe_draft
        schema = vol.Schema(
            {
                vol.Required("label", default=defaults.get("label", "My Crop")): str,
                vol.Required(
                    "stages",
                    default=defaults.get("stages")
                    or ["Seedling", "Vegetative", "Harvest"],
                ): selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(GROWTH_STAGES),
                        multiple=True,
                        mode=selector.SelectSelectorMode.LIST,
                    )
                ),
            }
        )
        return self.async_show_form(
            step_id="recipe_plant", data_schema=schema, errors=errors
        )

    async def async_step_recipe_stage(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        stages = list(self._recipe_draft.get("stages") or [])
        if not stages:
            return await self.async_step_recipe_plant()
        idx = min(self._stage_index, len(stages) - 1)
        stage = stages[idx]
        existing = self._recipe_draft.get("recipes", {}).get(stage) or {}

        if user_input is not None:
            lon = _time_to_hm(user_input["lights_on"])
            loff = _time_to_hm(user_input["lights_off"])
            irr1 = _time_to_hm(user_input["irr1_time"])
            irr2 = _time_to_hm(user_input["irr2_time"])
            recipe = Recipe(
                stage=stage,
                light_on=lon,
                light_off=loff,
                desired_ph=float(user_input["desired_ph"]),
                desired_ec=float(user_input["desired_ec"]),
                ph_tolerance=float(user_input["ph_tolerance"]),
                ec_tolerance=float(user_input["ec_tolerance"]),
                duration_days=int(user_input["duration_days"]),
                schedule=tuple(
                    normalize_schedule(
                        [
                            ScheduleSlot(
                                True,
                                irr1[0],
                                irr1[1],
                                int(user_input["irr1_duration"]),
                            ).as_dict(),
                            ScheduleSlot(
                                bool(user_input.get("irr2_enabled")),
                                irr2[0],
                                irr2[1],
                                int(user_input["irr2_duration"]),
                            ).as_dict(),
                            ScheduleSlot(False, 0, 0, 5).as_dict(),
                            ScheduleSlot(False, 0, 0, 5).as_dict(),
                            ScheduleSlot(False, 0, 0, 5).as_dict(),
                        ]
                    )
                ),
            )
            self._recipe_draft.setdefault("recipes", {})[stage] = recipe.as_dict()
            self._recipe_draft.pop("last_error", None)
            if idx + 1 < len(stages):
                self._stage_index = idx + 1
                return await self.async_step_recipe_stage()
            return await self.async_step_recipe_save()

        lon = existing.get("light_on") or [6, 0]
        loff = existing.get("light_off") or [22, 0]
        sched = normalize_schedule(existing.get("schedule"))
        time_sel = selector.TimeSelector()
        mins_sel = selector.NumberSelector(
            selector.NumberSelectorConfig(
                min=1,
                max=120,
                step=1,
                mode=selector.NumberSelectorMode.BOX,
                unit_of_measurement="min",
            )
        )
        schema = vol.Schema(
            {
                vol.Required(
                    "desired_ph", default=float(existing.get("desired_ph", 6.0))
                ): vol.Coerce(float),
                vol.Required(
                    "ph_tolerance", default=float(existing.get("ph_tolerance", 0.3))
                ): vol.Coerce(float),
                vol.Required(
                    "desired_ec", default=float(existing.get("desired_ec", 1.2))
                ): vol.Coerce(float),
                vol.Required(
                    "ec_tolerance", default=float(existing.get("ec_tolerance", 0.1))
                ): vol.Coerce(float),
                vol.Required(
                    "duration_days",
                    default=int(existing.get("duration_days", 14 if idx < len(stages) - 1 else 0)),
                ): vol.All(vol.Coerce(int), vol.Range(min=0, max=365)),
                vol.Required(
                    "lights_on", default=_hm_to_time(int(lon[0]), int(lon[1]))
                ): time_sel,
                vol.Required(
                    "lights_off", default=_hm_to_time(int(loff[0]), int(loff[1]))
                ): time_sel,
                vol.Required(
                    "irr1_time",
                    default=_hm_to_time(sched[0].hour, sched[0].minute),
                ): time_sel,
                vol.Required(
                    "irr1_duration", default=int(sched[0].duration_min)
                ): mins_sel,
                vol.Required("irr2_enabled", default=bool(sched[1].enabled)): bool,
                vol.Required(
                    "irr2_time",
                    default=_hm_to_time(sched[1].hour or 20, sched[1].minute),
                ): time_sel,
                vol.Required(
                    "irr2_duration", default=int(sched[1].duration_min or 5)
                ): mins_sel,
            }
        )
        return self.async_show_form(
            step_id="recipe_stage",
            data_schema=schema,
            errors={"base": "recipe_invalid"} if self._recipe_draft.get("last_error") else None,
            description_placeholders={
                "plant": self._recipe_draft.get("label", ""),
                "stage": stage,
                "index": str(idx + 1),
                "total": str(len(stages)),
            },
        )

    async def async_step_recipe_save(
        self, user_input: dict[str, Any] | None = None
    ) -> FlowResult:
        plant_data = {
            "plant_id": self._recipe_draft.get("plant_id")
            or f"custom_{_slug(str(self._recipe_draft.get('label', 'crop')))}",
            "label": self._recipe_draft.get("label", "My Crop"),
            "stages": list(self._recipe_draft.get("stages") or []),
            "recipes": self._recipe_draft.get("recipes", {}),
        }
        plant, err = validate_custom_plant(plant_data)
        if err or plant is None:
            self._recipe_draft["last_error"] = err or "Validation failed"
            # Send user back to the first stage so values can be fixed.
            self._stage_index = 0
            return await self.async_step_recipe_stage()

        if user_input is not None:
            customs = load_custom_recipes(
                self.config_entry.options.get(CONF_CUSTOM_RECIPES)
            )
            customs[plant.plant_id] = plant
            opts = dict(self.config_entry.options)
            opts[CONF_CUSTOM_RECIPES] = serialize_custom_recipes(customs)
            return self.async_create_entry(title="", data=opts)

        summary = f"Save {plant.label} — stages: {', '.join(plant.stages)}?"
        return self.async_show_form(
            step_id="recipe_save",
            data_schema=vol.Schema({}),
            description_placeholders={"summary": summary},
        )

    async def async_step_lighting(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        """Add/change lights later (e.g. after flashing the relay kit)."""
        entry = self.config_entry
        data = dict(entry.data)
        current_count = int(data.get(CONF_LIGHT_STAND_COUNT, CONTROLLER_LIGHT_STANDS))
        emap = dict(data.get(CONF_ENTITY_MAP) or {})
        current_lights = list(emap.get("lights") or [])

        if user_input is not None:
            count = int(user_input[CONF_LIGHT_STAND_COUNT])
            lights = _trim_lights(
                self.hass,
                user_input.get("lights"),
                count,
                data.get(CONF_CONTROLLER_DEVICE_ID),
            )
            data[CONF_LIGHT_STAND_COUNT] = count
            if lights:
                emap["lights"] = lights
            else:
                emap.pop("lights", None)
            data[CONF_ENTITY_MAP] = emap
            data[CONF_CAPABILITIES] = _rebuild_capabilities(data)
            self.hass.config_entries.async_update_entry(entry, data=data)
            self.hass.async_create_task(self._async_reload_and_dashboard())
            return self.async_create_entry(title="", data=dict(entry.options))

        suggested = suggest_entity_map(
            self.hass,
            data.get(CONF_CONTROLLER_DEVICE_ID),
            data.get(CONF_HARDWARE_PROFILE, PROFILE_A),
            max_lights=20,
        )
        suggested_lights = suggested.get("lights") or []
        if isinstance(suggested_lights, list) and len(suggested_lights) >= current_count:
            default_lights = list(suggested_lights)[: max(current_count, 12)]
        elif current_lights:
            default_lights = order_light_entities(
                self.hass,
                current_lights,
                data.get(CONF_CONTROLLER_DEVICE_ID),
            )
        else:
            default_lights = list(suggested_lights) if isinstance(suggested_lights, list) else []

        schema = vol.Schema(
            {
                vol.Required(CONF_LIGHT_STAND_COUNT, default=current_count): vol.In(
                    LIGHT_STAND_CHOICES
                ),
                vol.Optional("lights", default=default_lights): selector.EntitySelector(
                    selector.EntitySelectorConfig(domain="switch", multiple=True)
                ),
            }
        )
        return self.async_show_form(step_id="lighting", data_schema=schema)

    async def _async_reload_and_dashboard(self) -> None:
        await self.hass.config_entries.async_reload(self.config_entry.entry_id)
        from .dashboard import async_setup_lovelace

        await async_setup_lovelace(self.hass, force=True)
