from homeassistant.components.climate.const import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_HVAC_MODES,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_TARGET_TEMP_STEP,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_DEVICE_CLASS,
    ATTR_SUPPORTED_FEATURES,
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    STATE_UNAVAILABLE,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.daikin_external_thermostat.const import (
    CONF_CLIMATE_ENTITY_ID,
    CONF_ENTRY_NAME,
    CONF_SENSOR_ENTITY_ID,
    CONF_STARTUP_SETTLE_DELAY,
    DOMAIN,
    default_options,
)


async def test_entry_setup_entity_state_diagnostics_and_unload(
    hass: HomeAssistant,
) -> None:
    sensor_id = "sensor.bedroom_temperature"
    climate_id = "climate.bedroom_ac"
    hass.states.async_set(
        sensor_id,
        "26.5",
        {
            ATTR_DEVICE_CLASS: "temperature",
            ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS,
        },
    )
    hass.states.async_set(
        climate_id,
        HVACMode.OFF,
        {
            ATTR_HVAC_MODES: [HVACMode.OFF, HVACMode.COOL],
            ATTR_SUPPORTED_FEATURES: (
                ClimateEntityFeature.TARGET_TEMPERATURE
                | ClimateEntityFeature.TURN_ON
                | ClimateEntityFeature.TURN_OFF
            ),
            ATTR_CURRENT_TEMPERATURE: 25,
            ATTR_TEMPERATURE: 24,
            ATTR_MIN_TEMP: 16,
            ATTR_MAX_TEMP: 32,
            ATTR_TARGET_TEMP_STEP: 0.5,
            ATTR_HVAC_ACTION: HVACAction.OFF,
        },
    )
    options = default_options(UnitOfTemperature.CELSIUS)
    options[CONF_STARTUP_SETTLE_DELAY] = 0
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="Bedroom",
        data={
            CONF_ENTRY_NAME: "Bedroom",
            CONF_SENSOR_ENTITY_ID: sensor_id,
            CONF_CLIMATE_ENTITY_ID: climate_id,
        },
        options=options,
        unique_id="stable-pair-id",
    )
    entry.add_to_hass(hass)

    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()

    registry = er.async_get(hass)
    entities = [
        entity
        for entity in registry.entities.values()
        if entity.config_entry_id == entry.entry_id and entity.platform == DOMAIN
    ]
    assert len(entities) == 1
    entity_id = entities[0].entity_id
    state = hass.states.get(entity_id)
    assert state is not None
    assert state.state == HVACMode.OFF
    assert state.attributes[ATTR_CURRENT_TEMPERATURE] == 26.5
    assert state.attributes["controller_state"] == "manual_off"

    from custom_components.daikin_external_thermostat.diagnostics import (
        async_get_config_entry_diagnostics,
    )

    diagnostics = await async_get_config_entry_diagnostics(hass, entry)
    rendered = str(diagnostics)
    assert sensor_id not in rendered
    assert climate_id not in rendered
    assert "Bedroom" not in rendered

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    unloaded_state = hass.states.get(entity_id)
    assert unloaded_state is None or unloaded_state.state == STATE_UNAVAILABLE
