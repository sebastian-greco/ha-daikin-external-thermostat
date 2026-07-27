"""Pure controller models and calculations."""

from __future__ import annotations

import math
from collections.abc import Mapping
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Any

from .const import (
    CONF_BOOST_ENABLED,
    CONF_BOOST_ENTER_DELTA,
    CONF_BOOST_EXIT_DELTA,
    CONF_BOOST_OFFSET,
    CONF_COAST_ENTER_DELTA,
    CONF_COASTING_OFFSET,
    CONF_COOL_ENTER_DELTA,
    CONF_COOLING_OFFSET,
    CONF_FALLBACK_BOOST_OFFSET,
    CONF_FALLBACK_COASTING_OFFSET,
    CONF_FALLBACK_COOLING_OFFSET,
    CONF_MAX_AUTOMATIC_COMMANDS_24H,
    CONF_MINIMUM_AUTOMATIC_COMMAND_INTERVAL,
    CONF_RESUME_AFTER_SENSOR_RECOVERY,
    CONF_SAFETY_OFF_DELTA,
    CONF_SAFETY_RESUME_DELTA,
    CONF_SENSOR_STALE_TIMEOUT,
    CONF_STARTUP_SETTLE_DELAY,
    CONF_TARGET_CHANGE_DEBOUNCE,
    CONF_TARGET_TEMPERATURE_MAX,
    CONF_TARGET_TEMPERATURE_MIN,
    CONF_TARGET_TEMPERATURE_STEP,
    CONF_TEMPERATURE_DEBOUNCE,
    CONF_WATCHDOG_INTERVAL,
)


class ControllerState(StrEnum):
    """Internal state of the controller."""

    MANUAL_OFF = "manual_off"
    PASSTHROUGH = "passthrough"
    BOOSTING = "boosting"
    COOLING = "cooling"
    COASTING = "coasting"
    SAFETY_OFF = "safety_off"
    SENSOR_FAULT = "sensor_fault"
    UNDERLYING_FAULT = "underlying_fault"


@dataclass(frozen=True, slots=True)
class ControllerOptions:
    """Validated controller options."""

    boost_enabled: bool
    boost_enter_delta: float
    boost_exit_delta: float
    cool_enter_delta: float
    coast_enter_delta: float
    safety_off_delta: float
    safety_resume_delta: float
    boost_offset: float
    cooling_offset: float
    coasting_offset: float
    fallback_boost_offset: float
    fallback_cooling_offset: float
    fallback_coasting_offset: float
    temperature_debounce: float
    target_change_debounce: float
    minimum_automatic_command_interval: float
    watchdog_interval: float
    startup_settle_delay: float
    sensor_stale_timeout: float
    resume_after_sensor_recovery: bool
    max_automatic_commands_24h: int
    target_temperature_min: float
    target_temperature_max: float
    target_temperature_step: float

    @classmethod
    def from_mapping(cls, values: Mapping[str, Any]) -> ControllerOptions:
        """Build options from a complete mapping."""
        return cls(
            boost_enabled=bool(values[CONF_BOOST_ENABLED]),
            boost_enter_delta=float(values[CONF_BOOST_ENTER_DELTA]),
            boost_exit_delta=float(values[CONF_BOOST_EXIT_DELTA]),
            cool_enter_delta=float(values[CONF_COOL_ENTER_DELTA]),
            coast_enter_delta=float(values[CONF_COAST_ENTER_DELTA]),
            safety_off_delta=float(values[CONF_SAFETY_OFF_DELTA]),
            safety_resume_delta=float(values[CONF_SAFETY_RESUME_DELTA]),
            boost_offset=float(values[CONF_BOOST_OFFSET]),
            cooling_offset=float(values[CONF_COOLING_OFFSET]),
            coasting_offset=float(values[CONF_COASTING_OFFSET]),
            fallback_boost_offset=float(values[CONF_FALLBACK_BOOST_OFFSET]),
            fallback_cooling_offset=float(values[CONF_FALLBACK_COOLING_OFFSET]),
            fallback_coasting_offset=float(values[CONF_FALLBACK_COASTING_OFFSET]),
            temperature_debounce=float(values[CONF_TEMPERATURE_DEBOUNCE]),
            target_change_debounce=float(values[CONF_TARGET_CHANGE_DEBOUNCE]),
            minimum_automatic_command_interval=float(
                values[CONF_MINIMUM_AUTOMATIC_COMMAND_INTERVAL]
            ),
            watchdog_interval=float(values[CONF_WATCHDOG_INTERVAL]),
            startup_settle_delay=float(values[CONF_STARTUP_SETTLE_DELAY]),
            sensor_stale_timeout=float(values[CONF_SENSOR_STALE_TIMEOUT]),
            resume_after_sensor_recovery=bool(
                values[CONF_RESUME_AFTER_SENSOR_RECOVERY]
            ),
            max_automatic_commands_24h=int(values[CONF_MAX_AUTOMATIC_COMMANDS_24H]),
            target_temperature_min=float(values[CONF_TARGET_TEMPERATURE_MIN]),
            target_temperature_max=float(values[CONF_TARGET_TEMPERATURE_MAX]),
            target_temperature_step=float(values[CONF_TARGET_TEMPERATURE_STEP]),
        )


@dataclass(frozen=True, slots=True)
class DesiredCommand:
    """Effective command requested for the underlying climate entity."""

    hvac_mode: str
    temperature: float | None = None


def finite_float(value: Any) -> float | None:
    """Return a finite float, or None for invalid input."""
    try:
        number = float(value)
    except TypeError, ValueError:
        return None
    return number if math.isfinite(number) else None


def initial_cooling_state(
    room_temperature: float,
    target_temperature: float,
    options: ControllerOptions,
) -> ControllerState:
    """Select a safe stage when cooling control starts or recovers."""
    if room_temperature <= target_temperature - options.safety_off_delta:
        return ControllerState.SAFETY_OFF
    if (
        options.boost_enabled
        and room_temperature >= target_temperature + options.boost_enter_delta
    ):
        return ControllerState.BOOSTING
    if room_temperature <= target_temperature + options.coast_enter_delta:
        return ControllerState.COASTING
    return ControllerState.COOLING


def next_controller_state(
    current: ControllerState,
    *,
    requested_cool: bool,
    room_temperature: float | None,
    target_temperature: float,
    options: ControllerOptions,
    sensor_fault: bool = False,
    underlying_available: bool = True,
) -> ControllerState:
    """Evaluate one state transition using the specification's priority order."""
    if not requested_cool:
        return ControllerState.MANUAL_OFF
    if not underlying_available:
        return ControllerState.UNDERLYING_FAULT
    if sensor_fault or room_temperature is None:
        return ControllerState.SENSOR_FAULT if sensor_fault else current

    room = room_temperature
    target = target_temperature

    if current in (
        ControllerState.MANUAL_OFF,
        ControllerState.SENSOR_FAULT,
        ControllerState.UNDERLYING_FAULT,
    ):
        return initial_cooling_state(room, target, options)

    if room <= target - options.safety_off_delta:
        return ControllerState.SAFETY_OFF

    if current is ControllerState.SAFETY_OFF:
        if room < target + options.safety_resume_delta:
            return ControllerState.SAFETY_OFF
        if options.boost_enabled and room >= target + options.boost_enter_delta:
            return ControllerState.BOOSTING
        return ControllerState.COOLING

    if current is ControllerState.BOOSTING:
        if not options.boost_enabled or room <= target + options.boost_exit_delta:
            return ControllerState.COOLING
        return ControllerState.BOOSTING

    if current is ControllerState.COOLING:
        if options.boost_enabled and room >= target + options.boost_enter_delta:
            return ControllerState.BOOSTING
        if room <= target + options.coast_enter_delta:
            return ControllerState.COASTING
        return ControllerState.COOLING

    if current is ControllerState.COASTING:
        if options.boost_enabled and room >= target + options.boost_enter_delta:
            return ControllerState.BOOSTING
        if room >= target + options.cool_enter_delta:
            return ControllerState.COOLING
        return ControllerState.COASTING

    return current


def desired_setpoint(
    state: ControllerState,
    *,
    target_temperature: float,
    underlying_temperature: float | None,
    configured_minimum: float,
    configured_maximum: float,
    underlying_minimum: float | None,
    underlying_maximum: float | None,
    underlying_step: float | None,
    options: ControllerOptions,
) -> float | None:
    """Calculate, clamp, and quantize the desired underlying setpoint."""
    if state not in (
        ControllerState.BOOSTING,
        ControllerState.COOLING,
        ControllerState.COASTING,
    ):
        return None

    if state is ControllerState.BOOSTING:
        value = (
            underlying_temperature - options.boost_offset
            if underlying_temperature is not None
            else target_temperature - options.fallback_boost_offset
        )
    elif state is ControllerState.COOLING:
        value = (
            underlying_temperature - options.cooling_offset
            if underlying_temperature is not None
            else target_temperature - options.fallback_cooling_offset
        )
    else:
        value = (
            underlying_temperature + options.coasting_offset
            if underlying_temperature is not None
            else target_temperature + options.fallback_coasting_offset
        )

    minimum = max(
        configured_minimum,
        underlying_minimum if underlying_minimum is not None else configured_minimum,
    )
    maximum = min(
        configured_maximum,
        underlying_maximum if underlying_maximum is not None else configured_maximum,
    )
    if minimum > maximum:
        return None

    value = min(max(value, minimum), maximum)
    step = underlying_step or options.target_temperature_step
    if step <= 0:
        return value

    decimal_value = Decimal(str(value))
    decimal_minimum = Decimal(str(minimum))
    decimal_step = Decimal(str(step))
    steps = ((decimal_value - decimal_minimum) / decimal_step).quantize(
        Decimal("1"), rounding=ROUND_HALF_UP
    )
    quantized = decimal_minimum + steps * decimal_step
    return float(min(max(quantized, Decimal(str(minimum))), Decimal(str(maximum))))


def commands_equivalent(
    desired: DesiredCommand,
    *,
    actual_mode: str | None,
    actual_temperature: float | None,
    step: float,
) -> bool:
    """Return whether the underlying state already satisfies a command."""
    if desired.hvac_mode != actual_mode:
        return False
    if desired.temperature is None:
        return True
    if actual_temperature is None:
        return False
    return abs(desired.temperature - actual_temperature) < max(step / 2, 0.001)


def validate_options(values: Mapping[str, Any]) -> str | None:
    """Return a translation error key for an invalid option combination."""
    options = ControllerOptions.from_mapping(values)
    non_negative = (
        options.boost_enter_delta,
        options.boost_exit_delta,
        options.cool_enter_delta,
        options.coast_enter_delta,
        options.safety_off_delta,
        options.safety_resume_delta,
        options.boost_offset,
        options.cooling_offset,
        options.coasting_offset,
        options.fallback_boost_offset,
        options.fallback_cooling_offset,
        options.fallback_coasting_offset,
        options.temperature_debounce,
        options.target_change_debounce,
    )
    if any(not math.isfinite(value) or value < 0 for value in non_negative):
        return "non_negative"
    if not (
        options.coast_enter_delta
        < options.cool_enter_delta
        <= options.boost_exit_delta
        < options.boost_enter_delta
    ):
        return "threshold_order"
    if options.safety_resume_delta < options.cool_enter_delta:
        return "safety_resume"
    if options.boost_offset <= options.cooling_offset:
        return "boost_offset"
    if options.fallback_boost_offset <= options.fallback_cooling_offset:
        return "fallback_boost_offset"
    if options.target_temperature_min >= options.target_temperature_max:
        return "target_range"
    if options.target_temperature_step <= 0:
        return "target_step"
    if (
        options.minimum_automatic_command_interval <= 0
        or options.watchdog_interval <= 0
        or options.sensor_stale_timeout <= 0
        or options.startup_settle_delay < 0
    ):
        return "positive_timing"
    if options.sensor_stale_timeout <= options.temperature_debounce:
        return "stale_timeout"
    if options.max_automatic_commands_24h <= 0:
        return "command_budget"
    return None
