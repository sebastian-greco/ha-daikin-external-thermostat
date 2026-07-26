"""Constants for Daikin External Thermostat."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

from homeassistant.const import UnitOfTemperature
from homeassistant.util.unit_conversion import TemperatureConverter

DOMAIN: Final = "daikin_external_thermostat"
NAME: Final = "Daikin External Thermostat"
PLATFORMS: Final = ["climate"]

CONF_ENTRY_NAME: Final = "entry_name"
CONF_SENSOR_ENTITY_ID: Final = "sensor_entity_id"
CONF_CLIMATE_ENTITY_ID: Final = "climate_entity_id"

CONF_BOOST_ENABLED: Final = "boost_enabled"
CONF_BOOST_ENTER_DELTA: Final = "boost_enter_delta"
CONF_BOOST_EXIT_DELTA: Final = "boost_exit_delta"
CONF_COOL_ENTER_DELTA: Final = "cool_enter_delta"
CONF_COAST_ENTER_DELTA: Final = "coast_enter_delta"
CONF_SAFETY_OFF_DELTA: Final = "safety_off_delta"
CONF_SAFETY_RESUME_DELTA: Final = "safety_resume_delta"
CONF_BOOST_OFFSET: Final = "boost_offset"
CONF_COOLING_OFFSET: Final = "cooling_offset"
CONF_COASTING_OFFSET: Final = "coasting_offset"
CONF_FALLBACK_BOOST_OFFSET: Final = "fallback_boost_offset"
CONF_FALLBACK_COOLING_OFFSET: Final = "fallback_cooling_offset"
CONF_FALLBACK_COASTING_OFFSET: Final = "fallback_coasting_offset"
CONF_TEMPERATURE_DEBOUNCE: Final = "temperature_debounce"
CONF_TARGET_CHANGE_DEBOUNCE: Final = "target_change_debounce"
CONF_MINIMUM_AUTOMATIC_COMMAND_INTERVAL: Final = "minimum_automatic_command_interval"
CONF_WATCHDOG_INTERVAL: Final = "watchdog_interval"
CONF_STARTUP_SETTLE_DELAY: Final = "startup_settle_delay"
CONF_SENSOR_STALE_TIMEOUT: Final = "sensor_stale_timeout"
CONF_RESUME_AFTER_SENSOR_RECOVERY: Final = "resume_after_sensor_recovery"
CONF_MAX_AUTOMATIC_COMMANDS_24H: Final = "max_automatic_commands_24h"
CONF_TARGET_TEMPERATURE_MIN: Final = "target_temperature_min"
CONF_TARGET_TEMPERATURE_MAX: Final = "target_temperature_max"
CONF_TARGET_TEMPERATURE_STEP: Final = "target_temperature_step"

SECTION_THRESHOLDS: Final = "room_thresholds"
SECTION_OFFSETS: Final = "setpoint_offsets"
SECTION_TIMING: Final = "timing"
SECTION_SAFETY: Final = "safety_recovery"
SECTION_BUDGET: Final = "command_budget"
SECTION_TARGET: Final = "displayed_target"

DEFAULTS_CELSIUS: Final = {
    CONF_BOOST_ENABLED: True,
    CONF_BOOST_ENTER_DELTA: 1.5,
    CONF_BOOST_EXIT_DELTA: 0.8,
    CONF_COOL_ENTER_DELTA: 0.5,
    CONF_COAST_ENTER_DELTA: 0.2,
    CONF_SAFETY_OFF_DELTA: 1.0,
    CONF_SAFETY_RESUME_DELTA: 0.5,
    CONF_BOOST_OFFSET: 1.5,
    CONF_COOLING_OFFSET: 0.5,
    CONF_COASTING_OFFSET: 1.0,
    CONF_FALLBACK_BOOST_OFFSET: 2.0,
    CONF_FALLBACK_COOLING_OFFSET: 1.0,
    CONF_FALLBACK_COASTING_OFFSET: 1.5,
    CONF_TEMPERATURE_DEBOUNCE: 30,
    CONF_TARGET_CHANGE_DEBOUNCE: 5,
    CONF_MINIMUM_AUTOMATIC_COMMAND_INTERVAL: 20 * 60,
    CONF_WATCHDOG_INTERVAL: 60 * 60,
    CONF_STARTUP_SETTLE_DELAY: 30,
    CONF_SENSOR_STALE_TIMEOUT: 60 * 60,
    CONF_RESUME_AFTER_SENSOR_RECOVERY: True,
    CONF_MAX_AUTOMATIC_COMMANDS_24H: 40,
    CONF_TARGET_TEMPERATURE_MIN: 16.0,
    CONF_TARGET_TEMPERATURE_MAX: 32.0,
    CONF_TARGET_TEMPERATURE_STEP: 0.5,
}

TEMPERATURE_OPTION_KEYS: Final = {
    CONF_BOOST_ENTER_DELTA,
    CONF_BOOST_EXIT_DELTA,
    CONF_COOL_ENTER_DELTA,
    CONF_COAST_ENTER_DELTA,
    CONF_SAFETY_OFF_DELTA,
    CONF_SAFETY_RESUME_DELTA,
    CONF_BOOST_OFFSET,
    CONF_COOLING_OFFSET,
    CONF_COASTING_OFFSET,
    CONF_FALLBACK_BOOST_OFFSET,
    CONF_FALLBACK_COOLING_OFFSET,
    CONF_FALLBACK_COASTING_OFFSET,
    CONF_TARGET_TEMPERATURE_MIN,
    CONF_TARGET_TEMPERATURE_MAX,
    CONF_TARGET_TEMPERATURE_STEP,
}

DELTA_OPTION_KEYS: Final = TEMPERATURE_OPTION_KEYS - {
    CONF_TARGET_TEMPERATURE_MIN,
    CONF_TARGET_TEMPERATURE_MAX,
}

DEFAULT_TARGET_CELSIUS: Final = 24.0
COMMAND_HISTORY_LIMIT: Final = 50
TRANSITION_HISTORY_LIMIT: Final = 30
SELF_COMMAND_SUPPRESSION: Final = timedelta(minutes=2)
BUDGET_WINDOW: Final = timedelta(hours=24)


def _convert_celsius(value: float, unit: str, *, delta: bool) -> float:
    """Convert a Celsius absolute value or difference into the HA unit."""
    if unit == UnitOfTemperature.CELSIUS:
        return value
    if delta:
        converted_zero = TemperatureConverter.convert(
            0, UnitOfTemperature.CELSIUS, unit
        )
        converted_value = TemperatureConverter.convert(
            value, UnitOfTemperature.CELSIUS, unit
        )
        return round(converted_value - converted_zero, 3)
    return round(
        TemperatureConverter.convert(value, UnitOfTemperature.CELSIUS, unit), 3
    )


def default_options(unit: str) -> dict[str, bool | float | int]:
    """Return defaults expressed in Home Assistant's configured unit."""
    defaults = dict(DEFAULTS_CELSIUS)
    for key in TEMPERATURE_OPTION_KEYS:
        defaults[key] = _convert_celsius(
            float(defaults[key]), unit, delta=key in DELTA_OPTION_KEYS
        )
    return defaults


def default_target(unit: str) -> float:
    """Return the initial target in Home Assistant's configured unit."""
    return _convert_celsius(DEFAULT_TARGET_CELSIUS, unit, delta=False)
