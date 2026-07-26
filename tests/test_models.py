from dataclasses import replace

import pytest
from homeassistant.const import UnitOfTemperature

from custom_components.daikin_external_thermostat.const import (
    CONF_BOOST_ENTER_DELTA,
    CONF_BOOST_OFFSET,
    CONF_COAST_ENTER_DELTA,
    CONF_COOL_ENTER_DELTA,
    CONF_COOLING_OFFSET,
    CONF_FALLBACK_BOOST_OFFSET,
    CONF_SAFETY_RESUME_DELTA,
    CONF_TARGET_TEMPERATURE_MAX,
    CONF_TARGET_TEMPERATURE_MIN,
    default_options,
)
from custom_components.daikin_external_thermostat.models import (
    ControllerOptions,
    ControllerState,
    DesiredCommand,
    commands_equivalent,
    desired_setpoint,
    finite_float,
    initial_cooling_state,
    next_controller_state,
    validate_options,
)


@pytest.fixture
def options() -> ControllerOptions:
    return ControllerOptions.from_mapping(default_options(UnitOfTemperature.CELSIUS))


@pytest.mark.parametrize("value", [None, "unknown", float("nan"), float("inf")])
def test_finite_float_rejects_invalid_values(value) -> None:
    assert finite_float(value) is None


@pytest.mark.parametrize(
    ("room", "expected"),
    [
        (24.0 - 1.0, ControllerState.SAFETY_OFF),
        (24.0 + 0.2, ControllerState.COASTING),
        (24.0 + 0.3, ControllerState.COOLING),
        (24.0 + 1.5, ControllerState.BOOSTING),
    ],
)
def test_initial_state_exact_boundaries(
    options: ControllerOptions, room: float, expected: ControllerState
) -> None:
    assert initial_cooling_state(room, 24.0, options) is expected


def test_boost_disabled_never_enters_boost(options: ControllerOptions) -> None:
    options = replace(options, boost_enabled=False)
    assert (
        next_controller_state(
            ControllerState.COOLING,
            requested_cool=True,
            room_temperature=30,
            target_temperature=24,
            options=options,
        )
        is ControllerState.COOLING
    )


def test_boost_entry_exit_and_hysteresis(options: ControllerOptions) -> None:
    assert (
        next_controller_state(
            ControllerState.COOLING,
            requested_cool=True,
            room_temperature=25.5,
            target_temperature=24,
            options=options,
        )
        is ControllerState.BOOSTING
    )
    assert (
        next_controller_state(
            ControllerState.BOOSTING,
            requested_cool=True,
            room_temperature=24.9,
            target_temperature=24,
            options=options,
        )
        is ControllerState.BOOSTING
    )
    assert (
        next_controller_state(
            ControllerState.BOOSTING,
            requested_cool=True,
            room_temperature=24.8,
            target_temperature=24,
            options=options,
        )
        is ControllerState.COOLING
    )


def test_cooling_coasting_hysteresis_with_noise(options: ControllerOptions) -> None:
    state = ControllerState.COOLING
    for room in (24.4, 24.3, 24.21):
        state = next_controller_state(
            state,
            requested_cool=True,
            room_temperature=room,
            target_temperature=24,
            options=options,
        )
        assert state is ControllerState.COOLING
    state = next_controller_state(
        state,
        requested_cool=True,
        room_temperature=24.2,
        target_temperature=24,
        options=options,
    )
    assert state is ControllerState.COASTING
    for room in (24.21, 24.49):
        state = next_controller_state(
            state,
            requested_cool=True,
            room_temperature=room,
            target_temperature=24,
            options=options,
        )
        assert state is ControllerState.COASTING
    assert (
        next_controller_state(
            state,
            requested_cool=True,
            room_temperature=24.5,
            target_temperature=24,
            options=options,
        )
        is ControllerState.COOLING
    )


def test_coasting_can_enter_boost_directly(options: ControllerOptions) -> None:
    assert (
        next_controller_state(
            ControllerState.COASTING,
            requested_cool=True,
            room_temperature=25.5,
            target_temperature=24,
            options=options,
        )
        is ControllerState.BOOSTING
    )


def test_safety_is_latched_through_exact_resume_boundary(
    options: ControllerOptions,
) -> None:
    assert (
        next_controller_state(
            ControllerState.COOLING,
            requested_cool=True,
            room_temperature=23,
            target_temperature=24,
            options=options,
        )
        is ControllerState.SAFETY_OFF
    )
    assert (
        next_controller_state(
            ControllerState.SAFETY_OFF,
            requested_cool=True,
            room_temperature=24.49,
            target_temperature=24,
            options=options,
        )
        is ControllerState.SAFETY_OFF
    )
    assert (
        next_controller_state(
            ControllerState.SAFETY_OFF,
            requested_cool=True,
            room_temperature=24.5,
            target_temperature=24,
            options=options,
        )
        is ControllerState.COOLING
    )


def test_priority_manual_sensor_and_underlying_faults(
    options: ControllerOptions,
) -> None:
    assert (
        next_controller_state(
            ControllerState.BOOSTING,
            requested_cool=False,
            room_temperature=30,
            target_temperature=24,
            options=options,
            sensor_fault=True,
            underlying_available=False,
        )
        is ControllerState.MANUAL_OFF
    )
    assert (
        next_controller_state(
            ControllerState.COOLING,
            requested_cool=True,
            room_temperature=None,
            target_temperature=24,
            options=options,
            sensor_fault=True,
        )
        is ControllerState.SENSOR_FAULT
    )
    assert (
        next_controller_state(
            ControllerState.COOLING,
            requested_cool=True,
            room_temperature=30,
            target_temperature=24,
            options=options,
            underlying_available=False,
        )
        is ControllerState.UNDERLYING_FAULT
    )


@pytest.mark.parametrize(
    ("state", "underlying", "expected"),
    [
        (ControllerState.BOOSTING, 25.0, 23.5),
        (ControllerState.COOLING, 25.0, 24.5),
        (ControllerState.COASTING, 25.0, 26.0),
        (ControllerState.BOOSTING, None, 22.0),
        (ControllerState.COOLING, None, 23.0),
        (ControllerState.COASTING, None, 25.5),
    ],
)
def test_setpoint_formulas(
    options: ControllerOptions,
    state: ControllerState,
    underlying: float | None,
    expected: float,
) -> None:
    assert (
        desired_setpoint(
            state,
            target_temperature=24,
            underlying_temperature=underlying,
            configured_minimum=16,
            configured_maximum=32,
            underlying_minimum=16,
            underlying_maximum=32,
            underlying_step=0.5,
            options=options,
        )
        == expected
    )


def test_setpoint_clamps_and_rounds_to_underlying_step(
    options: ControllerOptions,
) -> None:
    assert (
        desired_setpoint(
            ControllerState.COOLING,
            target_temperature=24,
            underlying_temperature=16,
            configured_minimum=15,
            configured_maximum=35,
            underlying_minimum=17,
            underlying_maximum=30,
            underlying_step=0.5,
            options=options,
        )
        == 17
    )
    assert (
        desired_setpoint(
            ControllerState.COOLING,
            target_temperature=24,
            underlying_temperature=25.26,
            configured_minimum=16,
            configured_maximum=32,
            underlying_minimum=16,
            underlying_maximum=32,
            underlying_step=0.5,
            options=options,
        )
        == 25.0
    )


def test_command_equivalence_uses_half_step_tolerance() -> None:
    desired = DesiredCommand("cool", 24.0)
    assert commands_equivalent(
        desired, actual_mode="cool", actual_temperature=24.24, step=0.5
    )
    assert not commands_equivalent(
        desired, actual_mode="cool", actual_temperature=24.25, step=0.5
    )
    assert not commands_equivalent(
        desired, actual_mode="off", actual_temperature=24.0, step=0.5
    )


@pytest.mark.parametrize(
    ("updates", "error"),
    [
        ({CONF_COAST_ENTER_DELTA: 0.5}, "threshold_order"),
        ({CONF_COOL_ENTER_DELTA: 0.9}, "threshold_order"),
        ({CONF_BOOST_ENTER_DELTA: 0.8}, "threshold_order"),
        ({CONF_SAFETY_RESUME_DELTA: 0.4}, "safety_resume"),
        ({CONF_BOOST_OFFSET: 0.5}, "boost_offset"),
        ({CONF_FALLBACK_BOOST_OFFSET: 1.0}, "fallback_boost_offset"),
        (
            {CONF_TARGET_TEMPERATURE_MIN: 32, CONF_TARGET_TEMPERATURE_MAX: 32},
            "target_range",
        ),
        ({CONF_COOLING_OFFSET: -1}, "non_negative"),
    ],
)
def test_option_validation(updates: dict[str, float], error: str) -> None:
    values = default_options(UnitOfTemperature.CELSIUS)
    values.update(updates)
    assert validate_options(values) == error


def test_fahrenheit_defaults_convert_deltas_and_absolutes() -> None:
    values = default_options(UnitOfTemperature.FAHRENHEIT)
    assert values[CONF_BOOST_ENTER_DELTA] == 2.7
    assert values[CONF_TARGET_TEMPERATURE_MIN] == 60.8
    assert values[CONF_TARGET_TEMPERATURE_MAX] == 89.6
