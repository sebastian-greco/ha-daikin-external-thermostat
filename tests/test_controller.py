from dataclasses import replace
from datetime import timedelta

from homeassistant.components.climate.const import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_TARGET_TEMP_STEP,
    HVACAction,
    HVACMode,
)
from homeassistant.const import (
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    UnitOfTemperature,
)
from homeassistant.core import HomeAssistant, ServiceCall, State
from homeassistant.exceptions import HomeAssistantError
from homeassistant.util import dt as dt_util
from pytest_homeassistant_custom_component.common import async_fire_time_changed

from custom_components.daikin_external_thermostat.const import (
    CONF_CLIMATE_ENTITY_ID,
    CONF_SENSOR_ENTITY_ID,
    default_options,
)
from custom_components.daikin_external_thermostat.controller import (
    DaikinExternalThermostatController,
)
from custom_components.daikin_external_thermostat.models import (
    ControllerOptions,
    ControllerState,
)


def make_controller(hass: HomeAssistant, suffix: str = "one"):
    values = default_options(UnitOfTemperature.CELSIUS)
    options = replace(
        ControllerOptions.from_mapping(values),
        startup_settle_delay=0,
        target_change_debounce=0,
        temperature_debounce=0,
    )
    sensor_id = f"sensor.room_{suffix}"
    climate_id = f"climate.ac_{suffix}"
    hass.states.async_set(
        sensor_id,
        "27",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    hass.states.async_set(
        climate_id,
        HVACMode.COOL,
        {
            ATTR_CURRENT_TEMPERATURE: 25,
            ATTR_TEMPERATURE: 23.5,
            ATTR_MIN_TEMP: 16,
            ATTR_MAX_TEMP: 32,
            ATTR_TARGET_TEMP_STEP: 0.5,
            ATTR_HVAC_ACTION: HVACAction.COOLING,
        },
    )
    controller = DaikinExternalThermostatController(
        hass,
        suffix,
        {
            CONF_SENSOR_ENTITY_ID: sensor_id,
            CONF_CLIMATE_ENTITY_ID: climate_id,
        },
        options,
        24,
    )
    controller._read_sensor_state(hass.states.get(sensor_id))
    controller._read_underlying_state(hass.states.get(climate_id))
    controller._started = True
    controller._startup_settled = True
    return controller


async def test_duplicate_effective_command_is_suppressed(hass: HomeAssistant) -> None:
    controller = make_controller(hass)
    calls: list[ServiceCall] = []

    async def capture(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("climate", "set_temperature", capture)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.BOOSTING
    await controller.async_reconcile("sensor_event")
    assert calls == []


async def test_manual_off_bypasses_exhausted_budget(hass: HomeAssistant) -> None:
    controller = make_controller(hass)
    calls: list[ServiceCall] = []

    async def capture(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("climate", "turn_off", capture)
    controller.requested_hvac_mode = HVACMode.COOL
    now = dt_util.utcnow()
    for index in range(controller.options.max_automatic_commands_24h):
        controller._automatic_command_timestamps.append(now - timedelta(minutes=index))
    await controller.async_set_hvac_mode(HVACMode.OFF)
    assert len(calls) == 1
    assert controller.requested_hvac_mode is HVACMode.OFF
    assert controller.controller_state is ControllerState.MANUAL_OFF


async def test_manual_off_bypasses_startup_settling(hass: HomeAssistant) -> None:
    controller = make_controller(hass)
    controller._startup_settled = False
    calls: list[ServiceCall] = []

    async def capture(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("climate", "turn_off", capture)
    await controller.async_set_hvac_mode(HVACMode.OFF)
    assert len(calls) == 1


async def test_target_change_while_off_sends_nothing(hass: HomeAssistant) -> None:
    controller = make_controller(hass)
    calls: list[ServiceCall] = []

    async def capture(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("climate", "set_temperature", capture)
    await controller.async_set_target_temperature(26)
    await hass.async_block_till_done()
    assert controller.target_temperature == 26
    assert calls == []


async def test_two_entries_are_isolated(hass: HomeAssistant) -> None:
    first = make_controller(hass, "first")
    second = make_controller(hass, "second")
    await first.async_set_target_temperature(25)
    assert first.target_temperature == 25
    assert second.target_temperature == 24


async def test_sensor_fault_recovery_can_require_manual_enable(
    hass: HomeAssistant,
) -> None:
    controller = make_controller(hass)
    controller.options = replace(controller.options, resume_after_sensor_recovery=False)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.SENSOR_FAULT
    controller._sensor_fault_active = True
    controller._sensor_valid = False
    controller.hass.states.async_set(
        controller.sensor_entity_id,
        "25",
        {ATTR_UNIT_OF_MEASUREMENT: UnitOfTemperature.CELSIUS},
    )
    event = type(
        "Event",
        (),
        {
            "data": {
                "new_state": controller.hass.states.get(controller.sensor_entity_id)
            }
        },
    )()
    await controller._async_sensor_changed(event)
    assert controller.requested_hvac_mode is HVACMode.OFF
    assert controller.controller_state is ControllerState.MANUAL_OFF


async def test_threshold_that_clears_before_debounce_does_not_transition(
    hass: HomeAssistant,
) -> None:
    controller = make_controller(hass)
    controller.options = replace(controller.options, temperature_debounce=30)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    controller.current_temperature = 24.2
    await controller._consider_transition("sensor_event", debounce=True)
    assert controller._threshold_unsub is not None
    controller.current_temperature = 24.3
    await controller._consider_transition("sensor_event", debounce=True)
    assert controller._threshold_unsub is None
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=31))
    await hass.async_block_till_done()
    assert controller.controller_state is ControllerState.COOLING


async def test_rapid_targets_coalesce_into_one_command(hass: HomeAssistant) -> None:
    controller = make_controller(hass)
    controller.options = replace(controller.options, target_change_debounce=5)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    controller.underlying_target = 20
    calls: list[ServiceCall] = []

    async def capture(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("climate", "set_temperature", capture)
    await controller.async_set_target_temperature(25)
    await controller.async_set_target_temperature(26)
    assert calls == []
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert controller.target_temperature == 26


async def test_minimum_interval_keeps_only_newest_pending_command(
    hass: HomeAssistant,
) -> None:
    controller = make_controller(hass)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    controller.underlying_target = 20
    controller.last_command_at = dt_util.utcnow()
    await controller.async_reconcile("sensor_event")
    assert controller.pending_command is not None
    assert controller.pending_command.temperature == 24.5
    controller.underlying_temperature = 26
    await controller.async_reconcile("sensor_event")
    assert controller.pending_command is not None
    assert controller.pending_command.temperature == 25.5
    await controller.async_stop()


async def test_budget_exhaustion_schedules_next_rolling_expiry(
    hass: HomeAssistant,
) -> None:
    controller = make_controller(hass)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    controller.underlying_target = 20
    now = dt_util.utcnow()
    for index in range(controller.options.max_automatic_commands_24h):
        controller._automatic_command_timestamps.append(
            now
            - timedelta(minutes=controller.options.max_automatic_commands_24h - index)
        )
    await controller.async_reconcile("watchdog")
    assert controller.fault_reason == "automatic_command_budget_exhausted"
    assert controller.pending_command_at is not None
    expected = controller._automatic_command_timestamps[0] + timedelta(hours=24)
    assert abs((controller.pending_command_at - expected).total_seconds()) < 1
    await controller.async_stop()


async def test_stale_sensor_forces_one_off_call(hass: HomeAssistant) -> None:
    controller = make_controller(hass)
    controller.options = replace(controller.options, sensor_stale_timeout=5)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    calls: list[ServiceCall] = []

    async def capture(call: ServiceCall) -> None:
        calls.append(call)

    hass.services.async_register("climate", "turn_off", capture)
    controller._read_sensor_state(State(controller.sensor_entity_id, "unavailable"))
    controller._start_stale_timer()
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=6))
    await hass.async_block_till_done()
    assert len(calls) == 1
    assert controller.controller_state is ControllerState.SENSOR_FAULT
    assert controller.requested_hvac_mode is HVACMode.COOL
    await controller.async_reconcile("sensor_stale")
    assert len(calls) == 1


async def test_failed_service_call_uses_backoff_without_immediate_retry(
    hass: HomeAssistant,
) -> None:
    controller = make_controller(hass)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    controller.underlying_target = 20
    calls = 0

    async def fail(_call: ServiceCall) -> None:
        nonlocal calls
        calls += 1
        raise HomeAssistantError("mock failure")

    hass.services.async_register("climate", "set_temperature", fail)
    await controller.async_reconcile("sensor_event")
    await controller.async_reconcile("sensor_event")
    assert calls == 1
    assert controller.fault_reason == "HomeAssistantError"
    assert controller._backoff_until is not None
    await controller.async_stop()


async def test_external_manual_off_is_adopted(hass: HomeAssistant) -> None:
    controller = make_controller(hass)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    old_state = hass.states.get(controller.climate_entity_id)
    new_state = State(
        controller.climate_entity_id,
        HVACMode.OFF,
        old_state.attributes if old_state is not None else {},
    )
    event = type(
        "Event",
        (),
        {"data": {"old_state": old_state, "new_state": new_state}},
    )()
    await controller._async_underlying_changed(event)
    assert controller.requested_hvac_mode is HVACMode.OFF
    assert controller.controller_state is ControllerState.MANUAL_OFF


async def test_external_target_drift_is_recorded_but_not_fought(
    hass: HomeAssistant,
) -> None:
    controller = make_controller(hass)
    controller.requested_hvac_mode = HVACMode.COOL
    controller.controller_state = ControllerState.COOLING
    old_state = hass.states.get(controller.climate_entity_id)
    attributes = dict(old_state.attributes if old_state is not None else {})
    attributes[ATTR_TEMPERATURE] = 27
    new_state = State(controller.climate_entity_id, HVACMode.COOL, attributes)
    event = type(
        "Event",
        (),
        {"data": {"old_state": old_state, "new_state": new_state}},
    )()
    await controller._async_underlying_changed(event)
    assert controller.external_target_drift
    assert controller.pending_command is None


def test_restart_restores_intent_target_and_rolling_budget(
    hass: HomeAssistant,
) -> None:
    controller = make_controller(hass)
    timestamp = (dt_util.utcnow() - timedelta(hours=1)).isoformat()
    controller.restore(HVACMode.COOL, 25.5, [timestamp])
    assert controller.requested_hvac_mode is HVACMode.COOL
    assert controller.target_temperature == 25.5
    assert controller.automatic_command_count_24h == 1
