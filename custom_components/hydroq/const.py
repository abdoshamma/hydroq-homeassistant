"""Constants for HydroQ."""

from __future__ import annotations

DOMAIN = "hydroq"
MANUFACTURER = "HydroQ"
VERSION = "1.9.14"
CONFIG_VERSION = 2

# Platform names as strings — avoids importing homeassistant at module load (unit tests).
PLATFORMS: list[str] = [
    "sensor",
    "binary_sensor",
    "switch",
    "number",
    "select",
    "button",
    "time",
    "date",
]

CONF_ZONE_NAME = "zone_name"
CONF_HARDWARE_PROFILE = "hardware_profile"  # installer preset id only
CONF_CONTROLLER_DEVICE_ID = "controller_device_id"
CONF_RESERVOIR_VOLUME_L = "reservoir_volume_l"
CONF_LEVEL_SENSOR_TYPE = "level_sensor_type"
CONF_PUMP_ML_PER_MIN = "pump_ml_per_min"
CONF_ENTITY_MAP = "entity_map"  # legacy v1
CONF_CAPABILITIES = "capabilities"
CONF_SIMULATION = "simulation"
CONF_IRRIGATION_SCHEDULE = "irrigation_schedule"
CONF_LAST_CALIBRATION = "last_calibration"
CONF_NOTIFY = "notify_enabled"
CONF_LIGHT_STAND_COUNT = "light_stand_count"
# Main controller GPIO always exposes 4 light stands; kits add more.
CONTROLLER_LIGHT_STANDS = 4
LIGHT_STAND_CHOICES: dict[int, str] = {
    4: "Controller only (4 stands — always on main board)",
    8: "Controller + additional 4-stand kit (8 total)",
    12: "Controller + additional 8-stand kit (12 total)",
    20: "Controller + additional 16-stand kit (20 total)",
}
SCHEDULE_SLOT_COUNT = 5

# Legacy entity-map keys (config flow mapping UX)
EM_PH = "ph"
EM_TDS = "tds"
EM_EC = "ec"
EM_DO = "do"
EM_DO_RAW = "do_raw"
EM_WATER_TEMP = "water_temp"
EM_WATER_LEVEL = "water_level"
EM_ESTOP = "emergency_stop"
EM_CO2 = "co2"
EM_IAQ = "iaq"
EM_AIR_PRESSURE = "air_pressure"
EM_AIR_HUMIDITY = "air_humidity"
EM_AIR_TEMP = "air_temp"
EM_ECO2 = "eco2"
EM_BVOC = "bvoc"
EM_IRRIGATION = "irrigation_pump"
EM_PUMP_A = "solution_a"
EM_PUMP_B = "solution_b"
EM_PUMP_C = "solution_c"
EM_PUMP_PH = "ph_pump"
EM_PUMP_NEUTRAL = "neutralization"
EM_LIGHTS = "lights"
EM_CAL_PH_NEUTRAL = "cal_ph_neutral"
EM_CAL_PH_ACID = "cal_ph_acid"
EM_CAL_TDS = "cal_tds"
EM_CAL_DO = "cal_do"

PRESET_GEN1_PH_UP = "preset_gen1_ph_up"  # was profile_a
PRESET_GEN1_NEUTRAL = "preset_gen1_neutral"  # was profile_b
PROFILE_A = PRESET_GEN1_PH_UP  # back-compat alias
PROFILE_B = PRESET_GEN1_NEUTRAL

LEVEL_BINARY = "binary"
LEVEL_ULTRASONIC = "ultrasonic"

GROWTH_STAGES = ("Seedling", "Vegetative", "Flowering", "Harvest")
SYSTEM_MODES = ("Manual", "Semi-Auto", "Full-Auto", "Maintenance")

DEFAULT_PH = 6.2
DEFAULT_PH_TOLERANCE = 0.3
DEFAULT_TDS = 400
DEFAULT_TDS_TOLERANCE = 50
MAX_DOSING_SECONDS = 600
DOSING_PULSE_ON_S = 5
DOSING_PULSE_OFF_S = 5
SCHEDULER_TICK_S = 15
UPDATE_INTERVAL_S = 30
DEFAULT_MAX_DOSE_ML_DAY = 500.0
DOSING_LIMIT_COOLDOWN_S = 120
CONF_MAX_DOSE_ML_DAY = "max_dose_ml_day"
CONF_CUSTOM_RECIPES = "custom_recipes"
CONF_TDS_FACTOR = "tds_factor"
CONF_PLANT_ID = "plant_id"
CONF_GROWTH_STAGE = "growth_stage"
CONF_SOW_DATE = "sow_date"
CONF_AUTO_STAGE = "auto_stage"
DEFAULT_TDS_FACTOR = 500
TDS_FACTOR_CHOICES: dict[int, str] = {
    500: "500 scale (ppm ≈ EC × 500)",
    700: "700 scale (ppm ≈ EC × 700)",
}
DEFAULT_PLANT_ID = "generic"

ATTR_ENTRY_ID = "entry_id"
ATTR_EVENT_NUMBER = "event_number"
ATTR_DURATION_MIN = "duration_min"
ATTR_STAGE = "stage"
ATTR_PUMP = "pump"
ATTR_ML = "ml"
