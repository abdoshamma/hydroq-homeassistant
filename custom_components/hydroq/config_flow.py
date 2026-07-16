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
    CONF_ENTITY_MAP,
    CONF_HARDWARE_PROFILE,
    CONF_LEVEL_SENSOR_TYPE,
    CONF_LIGHT_STAND_COUNT,
    CONF_MAX_DOSE_ML_DAY,
    CONF_PUMP_ML_PER_MIN,
    CONF_RESERVOIR_VOLUME_L,
    CONF_SIMULATION,
    CONF_ZONE_NAME,
    CONTROLLER_LIGHT_STANDS,
    DEFAULT_MAX_DOSE_ML_DAY,
    DOMAIN,
    LEVEL_BINARY,
    LIGHT_STAND_CHOICES,
    PROFILE_A,
)
from .hardware.esphome_mapping import order_light_entities, suggest_entity_map
from .hardware.profiles import PROFILES
from .models.capability import legacy_entity_map_to_capabilities


def _trim_lights(
    hass: HomeAssistant,
    lights: list[str] | None,
    count: int,
    controller_device_id: str | None = None,
) -> list[str]:
    if count <= 0 or not lights:
        return []
    ordered = order_light_entities(hass, list(lights), controller_device_id)
    return ordered[:count]


def _rebuild_capabilities(data: dict[str, Any]) -> dict[str, Any]:
    ml = float(data.get(CONF_PUMP_ML_PER_MIN, 50))
    caps = legacy_entity_map_to_capabilities(
        data.get(CONF_ENTITY_MAP, {}),
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
                "water_temp": user_input.get("water_temp"),
                "water_level": user_input.get("water_level"),
                "emergency_stop": user_input.get("emergency_stop"),
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
            ("water_temp", entity_sel),
            ("water_level", entity_sel),
            ("emergency_stop", entity_sel),
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
    """Setpoints + later lighting kit / remap."""

    async def async_step_init(self, user_input: dict[str, Any] | None = None) -> FlowResult:
        if user_input is not None:
            if user_input.get("next") == "lighting":
                return await self.async_step_lighting()
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
                    }
                ),
            }
        )
        return self.async_show_form(step_id="init", data_schema=schema)

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
