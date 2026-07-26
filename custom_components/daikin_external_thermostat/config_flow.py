"""Config and options flows for Daikin External Thermostat."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping
from typing import Any

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODES,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import ConfigFlowResult
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_SUPPORTED_FEATURES,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import callback
from homeassistant.data_entry_flow import section
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.selector import (
    BooleanSelector,
    BooleanSelectorConfig,
    EntitySelector,
    EntitySelectorConfig,
    NumberSelector,
    NumberSelectorConfig,
    NumberSelectorMode,
    TextSelector,
    TextSelectorConfig,
)

from .const import (
    CONF_BOOST_ENABLED,
    CONF_BOOST_ENTER_DELTA,
    CONF_BOOST_EXIT_DELTA,
    CONF_BOOST_OFFSET,
    CONF_CLIMATE_ENTITY_ID,
    CONF_COAST_ENTER_DELTA,
    CONF_COASTING_OFFSET,
    CONF_COOL_ENTER_DELTA,
    CONF_COOLING_OFFSET,
    CONF_ENTRY_NAME,
    CONF_FALLBACK_BOOST_OFFSET,
    CONF_FALLBACK_COASTING_OFFSET,
    CONF_FALLBACK_COOLING_OFFSET,
    CONF_MAX_AUTOMATIC_COMMANDS_24H,
    CONF_MINIMUM_AUTOMATIC_COMMAND_INTERVAL,
    CONF_RESUME_AFTER_SENSOR_RECOVERY,
    CONF_SAFETY_OFF_DELTA,
    CONF_SAFETY_RESUME_DELTA,
    CONF_SENSOR_ENTITY_ID,
    CONF_SENSOR_STALE_TIMEOUT,
    CONF_STARTUP_SETTLE_DELAY,
    CONF_TARGET_CHANGE_DEBOUNCE,
    CONF_TARGET_TEMPERATURE_MAX,
    CONF_TARGET_TEMPERATURE_MIN,
    CONF_TARGET_TEMPERATURE_STEP,
    CONF_TEMPERATURE_DEBOUNCE,
    CONF_WATCHDOG_INTERVAL,
    DOMAIN,
    SECTION_BUDGET,
    SECTION_OFFSETS,
    SECTION_SAFETY,
    SECTION_TARGET,
    SECTION_THRESHOLDS,
    SECTION_TIMING,
    default_options,
)
from .models import validate_options


def _number(
    *,
    minimum: float = 0,
    maximum: float = 86400,
    step_value: float = 0.1,
    unit: str | None = None,
) -> NumberSelector:
    config = NumberSelectorConfig(
        min=minimum,
        max=maximum,
        step=step_value,
        mode=NumberSelectorMode.BOX,
    )
    if unit is not None:
        config["unit_of_measurement"] = unit
    return NumberSelector(config)


def _required(key: str, values: Mapping[str, Any], selector: Any) -> tuple[Any, Any]:
    return vol.Required(key, default=values[key]), selector


def _options_schema(unit: str, values: Mapping[str, Any]) -> vol.Schema:
    temperature = lambda: _number(maximum=20, unit=unit)  # noqa: E731
    seconds = lambda maximum=172800: _number(  # noqa: E731
        maximum=maximum, step_value=1, unit="s"
    )
    return vol.Schema(
        {
            vol.Required(SECTION_THRESHOLDS): section(
                vol.Schema(
                    dict(
                        (
                            _required(
                                CONF_BOOST_ENABLED,
                                values,
                                BooleanSelector(BooleanSelectorConfig()),
                            ),
                            _required(CONF_BOOST_ENTER_DELTA, values, temperature()),
                            _required(CONF_BOOST_EXIT_DELTA, values, temperature()),
                            _required(CONF_COOL_ENTER_DELTA, values, temperature()),
                            _required(CONF_COAST_ENTER_DELTA, values, temperature()),
                            _required(CONF_SAFETY_OFF_DELTA, values, temperature()),
                            _required(CONF_SAFETY_RESUME_DELTA, values, temperature()),
                        )
                    )
                ),
                {"collapsed": False},
            ),
            vol.Required(SECTION_OFFSETS): section(
                vol.Schema(
                    dict(
                        (
                            _required(CONF_BOOST_OFFSET, values, temperature()),
                            _required(CONF_COOLING_OFFSET, values, temperature()),
                            _required(CONF_COASTING_OFFSET, values, temperature()),
                            _required(
                                CONF_FALLBACK_BOOST_OFFSET, values, temperature()
                            ),
                            _required(
                                CONF_FALLBACK_COOLING_OFFSET, values, temperature()
                            ),
                            _required(
                                CONF_FALLBACK_COASTING_OFFSET, values, temperature()
                            ),
                        )
                    )
                ),
                {"collapsed": True},
            ),
            vol.Required(SECTION_TIMING): section(
                vol.Schema(
                    dict(
                        (
                            _required(CONF_TEMPERATURE_DEBOUNCE, values, seconds(3600)),
                            _required(
                                CONF_TARGET_CHANGE_DEBOUNCE, values, seconds(300)
                            ),
                            _required(
                                CONF_MINIMUM_AUTOMATIC_COMMAND_INTERVAL,
                                values,
                                seconds(),
                            ),
                            _required(CONF_WATCHDOG_INTERVAL, values, seconds(604800)),
                            _required(CONF_STARTUP_SETTLE_DELAY, values, seconds(3600)),
                        )
                    )
                ),
                {"collapsed": True},
            ),
            vol.Required(SECTION_SAFETY): section(
                vol.Schema(
                    dict(
                        (
                            _required(
                                CONF_SENSOR_STALE_TIMEOUT, values, seconds(604800)
                            ),
                            _required(
                                CONF_RESUME_AFTER_SENSOR_RECOVERY,
                                values,
                                BooleanSelector(BooleanSelectorConfig()),
                            ),
                        )
                    )
                ),
                {"collapsed": True},
            ),
            vol.Required(SECTION_BUDGET): section(
                vol.Schema(
                    dict(
                        (
                            _required(
                                CONF_MAX_AUTOMATIC_COMMANDS_24H,
                                values,
                                _number(maximum=1000, step_value=1),
                            ),
                        )
                    )
                ),
                {"collapsed": True},
            ),
            vol.Required(SECTION_TARGET): section(
                vol.Schema(
                    dict(
                        (
                            _required(
                                CONF_TARGET_TEMPERATURE_MIN,
                                values,
                                _number(
                                    minimum=-50,
                                    maximum=140,
                                    step_value=0.1,
                                    unit=unit,
                                ),
                            ),
                            _required(
                                CONF_TARGET_TEMPERATURE_MAX,
                                values,
                                _number(
                                    minimum=-50,
                                    maximum=140,
                                    step_value=0.1,
                                    unit=unit,
                                ),
                            ),
                            _required(
                                CONF_TARGET_TEMPERATURE_STEP,
                                values,
                                _number(
                                    minimum=0.1,
                                    maximum=10,
                                    step_value=0.1,
                                    unit=unit,
                                ),
                            ),
                        )
                    )
                ),
                {"collapsed": True},
            ),
        }
    )


def _flatten_options(user_input: Mapping[str, Any]) -> dict[str, Any]:
    flattened: dict[str, Any] = {}
    for section_key in (
        SECTION_THRESHOLDS,
        SECTION_OFFSETS,
        SECTION_TIMING,
        SECTION_SAFETY,
        SECTION_BUDGET,
        SECTION_TARGET,
    ):
        flattened.update(user_input.get(section_key, {}))
    return flattened


class DaikinExternalThermostatConfigFlow(config_entries.ConfigFlow, domain=DOMAIN):
    """Handle initial controller configuration."""

    VERSION = 1
    MINOR_VERSION = 1

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Configure one sensor/climate pair."""
        errors: dict[str, str] = {}
        warning = ""
        if user_input is not None:
            sensor_id = user_input[CONF_SENSOR_ENTITY_ID]
            climate_id = user_input[CONF_CLIMATE_ENTITY_ID]
            error, warning = self._validate_entities(sensor_id, climate_id)
            if error is not None:
                errors["base"] = error
            elif any(
                entry.data.get(CONF_CLIMATE_ENTITY_ID) == climate_id
                for entry in self._async_current_entries()
            ):
                errors["base"] = "underlying_already_managed"
            else:
                await self.async_set_unique_id(
                    self._pair_unique_id(sensor_id, climate_id)
                )
                self._abort_if_unique_id_configured()
                return self.async_create_entry(
                    title=user_input[CONF_ENTRY_NAME],
                    data=user_input,
                    options=default_options(self.hass.config.units.temperature_unit),
                )

        schema = vol.Schema(
            {
                vol.Required(CONF_ENTRY_NAME): TextSelector(
                    TextSelectorConfig(autocomplete="name")
                ),
                vol.Required(CONF_SENSOR_ENTITY_ID): EntitySelector(
                    EntitySelectorConfig(
                        domain="sensor", device_class=SensorDeviceClass.TEMPERATURE
                    )
                ),
                vol.Required(CONF_CLIMATE_ENTITY_ID): EntitySelector(
                    EntitySelectorConfig(domain="climate")
                ),
            }
        )
        return self.async_show_form(
            step_id="user",
            data_schema=schema,
            errors=errors,
            description_placeholders={"warning": warning},
        )

    @staticmethod
    @callback
    def async_get_options_flow(
        config_entry: config_entries.ConfigEntry,
    ) -> config_entries.OptionsFlow:
        """Return the options flow."""
        return DaikinExternalThermostatOptionsFlow()

    def _validate_entities(
        self, sensor_id: str, climate_id: str
    ) -> tuple[str | None, str]:
        registry = er.async_get(self.hass)
        sensor = self.hass.states.get(sensor_id)
        sensor_registry = registry.async_get(sensor_id)
        sensor_device_class = (
            sensor.attributes.get(ATTR_DEVICE_CLASS) if sensor is not None else None
        ) or (
            getattr(sensor_registry, "device_class", None)
            or getattr(sensor_registry, "original_device_class", None)
            if sensor_registry is not None
            else None
        )
        if sensor_device_class != SensorDeviceClass.TEMPERATURE:
            return "sensor_not_temperature", ""

        climate = self.hass.states.get(climate_id)
        climate_registry = registry.async_get(climate_id)
        if climate is None and climate_registry is None:
            return "climate_not_found", ""
        if climate is not None and climate.state not in (
            STATE_UNAVAILABLE,
            STATE_UNKNOWN,
        ):
            modes = climate.attributes.get(ATTR_HVAC_MODES, [])
            features = int(climate.attributes.get(ATTR_SUPPORTED_FEATURES, 0))
            if HVACMode.COOL not in modes:
                return "climate_no_cool", ""
            if not features & ClimateEntityFeature.TARGET_TEMPERATURE:
                return "climate_no_target_temperature", ""
        elif climate_registry is None:
            return "climate_not_found", ""
        else:
            return (
                None,
                "The selected climate is unavailable; setup will validate it again "
                "after recovery.",
            )
        return None, ""

    def _pair_unique_id(self, sensor_id: str, climate_id: str) -> str:
        registry = er.async_get(self.hass)

        def identity(entity_id: str) -> str:
            if (entry := registry.async_get(entity_id)) is not None and entry.unique_id:
                return f"{entry.platform}:{entry.unique_id}"
            return entity_id

        material = f"{identity(climate_id)}|{identity(sensor_id)}"
        return hashlib.sha256(material.encode()).hexdigest()


class DaikinExternalThermostatOptionsFlow(config_entries.OptionsFlow):
    """Edit all controller tuning in grouped sections."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Show and validate options."""
        unit = self.hass.config.units.temperature_unit
        values = default_options(unit)
        values.update(self.config_entry.options)
        errors: dict[str, str] = {}
        if user_input is not None:
            flattened = _flatten_options(user_input)
            if (error := validate_options(flattened)) is None:
                return self.async_create_entry(title="", data=flattened)
            errors["base"] = error
            values.update(flattened)
        return self.async_show_form(
            step_id="init",
            data_schema=_options_schema(unit, values),
            errors=errors,
        )
