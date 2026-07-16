"""Public action buttons."""

from __future__ import annotations

from homeassistant.components.button import ButtonEntity
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from .const import DOMAIN
from .controller.commands import CommandType
from .coordinator import HydroQCoordinator
from .entity import HydroQEntity


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    c: HydroQCoordinator = hass.data[DOMAIN][entry.entry_id]
    specs = [
        ("start_irrigation", "Start Irrigation", CommandType.START_IRRIGATION, {}),
        ("stop_irrigation", "Stop Irrigation", CommandType.STOP_IRRIGATION, {}),
        ("start_ph", "Start pH Dosing", CommandType.START_DOSING_PH, {}),
        ("start_nutrients", "Start Nutrient Dosing", CommandType.START_DOSING_NUTRIENTS, {}),
        ("start_neutralize", "Start Neutralize", CommandType.START_DOSING_NEUTRALIZE, {}),
        ("start_balance", "Balance System", CommandType.START_BALANCE, {}),
        ("test_pump_a", "Test Pump A (10s)", CommandType.TEST_PUMP, {"role": "a", "seconds": 10}),
        ("test_pump_b", "Test Pump B (10s)", CommandType.TEST_PUMP, {"role": "b", "seconds": 10}),
        ("test_pump_c", "Test Pump C (10s)", CommandType.TEST_PUMP, {"role": "c", "seconds": 10}),
        ("test_ph_pump", "Test pH Pump (10s)", CommandType.TEST_PUMP, {"role": "ph", "seconds": 10}),
        ("test_irrigation", "Test Irrigation (10s)", CommandType.TEST_PUMP, {"role": "irrigation", "seconds": 10}),
        ("stop_dosing", "Stop Dosing", CommandType.STOP_DOSING, {}),
        ("emergency_stop", "Emergency Stop", CommandType.EMERGENCY_STOP, {}),
        ("cal_ph_neutral", "Calibrate pH Neutral", CommandType.CALIBRATE, {"kind": "ph", "point": "neutral"}),
        ("cal_ph_acid", "Calibrate pH Acid", CommandType.CALIBRATE, {"kind": "ph", "point": "acid"}),
        ("cal_ec", "Calibrate EC", CommandType.CALIBRATE, {"kind": "tds", "point": "std"}),
        ("cal_do", "Calibrate DO", CommandType.CALIBRATE, {"kind": "do", "point": "air"}),
        ("request_refill", "Request Refill", CommandType.REQUEST_REFILL, {}),
    ]
    async_add_entities(
        [HydroQActionButton(c, key, name, ctype, payload) for key, name, ctype, payload in specs]
    )


class HydroQActionButton(HydroQEntity, ButtonEntity):
    def __init__(
        self,
        coordinator: HydroQCoordinator,
        key: str,
        name: str,
        ctype: CommandType,
        payload: dict,
    ) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._ctype = ctype
        self._payload = payload

    async def async_press(self) -> None:
        await self.coordinator.async_handle(self._ctype, self._payload or None)
