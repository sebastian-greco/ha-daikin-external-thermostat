from homeassistant.components.climate.const import (
    ATTR_HVAC_MODES,
    ClimateEntityFeature,
    HVACMode,
)
from homeassistant.components.sensor import SensorDeviceClass
from homeassistant.config_entries import SOURCE_USER
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_SUPPORTED_FEATURES,
)
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.daikin_external_thermostat.const import (
    CONF_CLIMATE_ENTITY_ID,
    CONF_COAST_ENTER_DELTA,
    CONF_COOL_ENTER_DELTA,
    CONF_ENTRY_NAME,
    CONF_SENSOR_ENTITY_ID,
    DOMAIN,
    SECTION_BUDGET,
    SECTION_OFFSETS,
    SECTION_SAFETY,
    SECTION_TARGET,
    SECTION_THRESHOLDS,
    SECTION_TIMING,
    default_options,
)


async def test_config_flow_creates_entry(hass: HomeAssistant) -> None:
    hass.states.async_set(
        "sensor.bedroom",
        "25",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE},
    )
    hass.states.async_set(
        "climate.bedroom",
        HVACMode.OFF,
        {
            ATTR_HVAC_MODES: [HVACMode.OFF, HVACMode.COOL],
            ATTR_SUPPORTED_FEATURES: ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ENTRY_NAME: "Bedroom",
            CONF_SENSOR_ENTITY_ID: "sensor.bedroom",
            CONF_CLIMATE_ENTITY_ID: "climate.bedroom",
        },
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["title"] == "Bedroom"
    assert result["result"].unique_id


async def test_rejects_climate_owned_by_another_entry(hass: HomeAssistant) -> None:
    MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ENTRY_NAME: "Existing",
            CONF_SENSOR_ENTITY_ID: "sensor.first",
            CONF_CLIMATE_ENTITY_ID: "climate.shared",
        },
    ).add_to_hass(hass)
    hass.states.async_set(
        "sensor.second",
        "25",
        {ATTR_DEVICE_CLASS: SensorDeviceClass.TEMPERATURE},
    )
    hass.states.async_set(
        "climate.shared",
        HVACMode.OFF,
        {
            ATTR_HVAC_MODES: [HVACMode.OFF, HVACMode.COOL],
            ATTR_SUPPORTED_FEATURES: ClimateEntityFeature.TARGET_TEMPERATURE,
        },
    )
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            CONF_ENTRY_NAME: "Second",
            CONF_SENSOR_ENTITY_ID: "sensor.second",
            CONF_CLIMATE_ENTITY_ID: "climate.shared",
        },
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "underlying_already_managed"}


async def test_options_flow_groups_and_rejects_invalid_threshold_order(
    hass: HomeAssistant,
) -> None:
    values = default_options(hass.config.units.temperature_unit)
    entry = MockConfigEntry(
        domain=DOMAIN,
        data={
            CONF_ENTRY_NAME: "Bedroom",
            CONF_SENSOR_ENTITY_ID: "sensor.bedroom",
            CONF_CLIMATE_ENTITY_ID: "climate.bedroom",
        },
        options=values,
    )
    entry.add_to_hass(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] is FlowResultType.FORM

    threshold_keys = {
        "boost_enabled",
        "boost_enter_delta",
        "boost_exit_delta",
        "cool_enter_delta",
        "coast_enter_delta",
        "safety_off_delta",
        "safety_resume_delta",
    }
    offset_keys = {
        "boost_offset",
        "cooling_offset",
        "coasting_offset",
        "fallback_boost_offset",
        "fallback_cooling_offset",
        "fallback_coasting_offset",
    }
    timing_keys = {
        "temperature_debounce",
        "target_change_debounce",
        "minimum_automatic_command_interval",
        "watchdog_interval",
        "startup_settle_delay",
    }
    safety_keys = {"sensor_stale_timeout", "resume_after_sensor_recovery"}
    budget_keys = {"max_automatic_commands_24h"}
    target_keys = {
        "target_temperature_min",
        "target_temperature_max",
        "target_temperature_step",
    }
    grouped = {
        SECTION_THRESHOLDS: {key: values[key] for key in threshold_keys},
        SECTION_OFFSETS: {key: values[key] for key in offset_keys},
        SECTION_TIMING: {key: values[key] for key in timing_keys},
        SECTION_SAFETY: {key: values[key] for key in safety_keys},
        SECTION_BUDGET: {key: values[key] for key in budget_keys},
        SECTION_TARGET: {key: values[key] for key in target_keys},
    }
    grouped[SECTION_THRESHOLDS][CONF_COAST_ENTER_DELTA] = grouped[SECTION_THRESHOLDS][
        CONF_COOL_ENTER_DELTA
    ]
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], grouped
    )
    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "threshold_order"}
