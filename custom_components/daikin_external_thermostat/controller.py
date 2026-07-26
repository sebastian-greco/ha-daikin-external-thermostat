"""Event-driven controller for Daikin External Thermostat."""

from __future__ import annotations

import asyncio
import logging
from collections import deque
from collections.abc import Callable
from dataclasses import asdict
from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.climate.const import (
    ATTR_CURRENT_TEMPERATURE,
    ATTR_HVAC_ACTION,
    ATTR_MAX_TEMP,
    ATTR_MIN_TEMP,
    ATTR_TARGET_TEMP_STEP,
    SERVICE_SET_TEMPERATURE,
    HVACAction,
    HVACMode,
)
from homeassistant.components.climate.const import (
    DOMAIN as CLIMATE_DOMAIN,
)
from homeassistant.const import (
    ATTR_ENTITY_ID,
    ATTR_TEMPERATURE,
    ATTR_UNIT_OF_MEASUREMENT,
    SERVICE_TURN_OFF,
    STATE_UNAVAILABLE,
    STATE_UNKNOWN,
)
from homeassistant.core import (
    Event,
    EventStateChangedData,
    HomeAssistant,
    State,
    callback,
)
from homeassistant.helpers.event import (
    async_call_later,
    async_track_state_change_event,
    async_track_time_interval,
)
from homeassistant.helpers.start import async_at_start
from homeassistant.util import dt as dt_util
from homeassistant.util.unit_conversion import TemperatureConverter

from .const import (
    BUDGET_WINDOW,
    COMMAND_HISTORY_LIMIT,
    CONF_CLIMATE_ENTITY_ID,
    CONF_SENSOR_ENTITY_ID,
    SELF_COMMAND_SUPPRESSION,
    TRANSITION_HISTORY_LIMIT,
)
from .models import (
    ControllerOptions,
    ControllerState,
    DesiredCommand,
    commands_equivalent,
    desired_setpoint,
    finite_float,
    initial_cooling_state,
    next_controller_state,
)

_LOGGER = logging.getLogger(__name__)


class DaikinExternalThermostatController:
    """Coordinate one external sensor and one underlying climate entity."""

    def __init__(
        self,
        hass: HomeAssistant,
        entry_id: str,
        entry_data: dict[str, Any],
        options: ControllerOptions,
        initial_target: float,
    ) -> None:
        """Initialize in-memory state without performing I/O."""
        self.hass = hass
        self.entry_id = entry_id
        self.sensor_entity_id = str(entry_data[CONF_SENSOR_ENTITY_ID])
        self.climate_entity_id = str(entry_data[CONF_CLIMATE_ENTITY_ID])
        self.options = options

        self.requested_hvac_mode = HVACMode.OFF
        self.target_temperature = initial_target
        self.controller_state = ControllerState.MANUAL_OFF
        self.current_temperature: float | None = None
        self.underlying_temperature: float | None = None
        self.underlying_target: float | None = None
        self.underlying_mode: str | None = None
        self.underlying_action: str | None = None
        self.underlying_minimum: float | None = None
        self.underlying_maximum: float | None = None
        self.underlying_step: float | None = None
        self.underlying_available = False

        self.desired_command: DesiredCommand | None = None
        self.pending_command: DesiredCommand | None = None
        self.pending_command_at: datetime | None = None
        self.last_command_at: datetime | None = None
        self.last_command_reason: str | None = None
        self.fault_reason: str | None = None
        self.last_error_at: datetime | None = None
        self.external_control = False
        self.external_target_drift = False

        self._started = False
        self._startup_settled = False
        self._sensor_valid = False
        self._sensor_invalid_since: datetime | None = None
        self._sensor_fault_active = False
        self._sensor_fault_warned = False
        self._underlying_fault_warned = False
        self._quota_warned = False
        self._expected_command: DesiredCommand | None = None
        self._suppression_until: datetime | None = None
        self._error_count = 0
        self._backoff_until: datetime | None = None
        self._automatic_command_timestamps: deque[datetime] = deque()
        self._command_history: deque[dict[str, Any]] = deque(
            maxlen=COMMAND_HISTORY_LIMIT
        )
        self._transition_history: deque[dict[str, Any]] = deque(
            maxlen=TRANSITION_HISTORY_LIMIT
        )
        self._listeners: list[Callable[[], None]] = []
        self._state_callbacks: list[Callable[[], None]] = []
        self._watchdog_unsub: Callable[[], None] | None = None
        self._threshold_unsub: Callable[[], None] | None = None
        self._target_unsub: Callable[[], None] | None = None
        self._stale_unsub: Callable[[], None] | None = None
        self._pending_unsub: Callable[[], None] | None = None
        self._settle_unsub: Callable[[], None] | None = None
        self._threshold_candidate: ControllerState | None = None
        self._lock = asyncio.Lock()
        self._dirty = False
        self._dirty_reason = "event"

    @property
    def available(self) -> bool:
        """Return virtual entity availability."""
        return self.underlying_available

    @property
    def automatic_command_count_24h(self) -> int:
        """Return rolling controller-generated automatic call count."""
        self._purge_budget(dt_util.utcnow())
        return len(self._automatic_command_timestamps)

    @property
    def hvac_action(self) -> HVACAction:
        """Map internal and underlying state to the standard climate action."""
        if self.requested_hvac_mode is HVACMode.OFF:
            return HVACAction.OFF
        if (
            self.controller_state in (ControllerState.BOOSTING, ControllerState.COOLING)
            and self.underlying_action == HVACAction.COOLING
        ):
            return HVACAction.COOLING
        return HVACAction.IDLE

    @property
    def diagnostic_attributes(self) -> dict[str, Any]:
        """Return small, read-only attributes for the climate entity."""
        return {
            "controller_state": self.controller_state,
            "desired_underlying_mode": (
                self.desired_command.hvac_mode if self.desired_command else None
            ),
            "desired_underlying_temperature": (
                self.desired_command.temperature if self.desired_command else None
            ),
            "last_command_at": self._iso(self.last_command_at),
            "last_command_reason": self.last_command_reason,
            "automatic_command_count_24h": self.automatic_command_count_24h,
            "automatic_command_timestamps": [
                self._iso(item) for item in self._automatic_command_timestamps
            ],
            "pending_command_at": self._iso(self.pending_command_at),
            "fault_reason": self.fault_reason,
            "last_valid_external_temperature": self.current_temperature,
            "last_valid_underlying_temperature": self.underlying_temperature,
            "external_control": self.external_control,
            "external_target_drift": self.external_target_drift,
        }

    def diagnostics(self) -> dict[str, Any]:
        """Return runtime diagnostics without entity identifiers or entry names."""
        return {
            "requested_hvac_mode": self.requested_hvac_mode,
            "target_temperature": self.target_temperature,
            "available": self.available,
            **self.diagnostic_attributes,
            "options": asdict(self.options),
            "pending_command": self._command_dict(self.pending_command),
            "recent_commands": list(self._command_history),
            "recent_transitions": list(self._transition_history),
            "last_error_at": self._iso(self.last_error_at),
        }

    @callback
    def add_state_listener(self, listener: Callable[[], None]) -> Callable[[], None]:
        """Register an entity-state listener."""
        self._state_callbacks.append(listener)

        @callback
        def remove() -> None:
            if listener in self._state_callbacks:
                self._state_callbacks.remove(listener)

        return remove

    def restore(
        self,
        mode: str | None,
        target: Any,
        automatic_timestamps: Any,
    ) -> None:
        """Restore user intent and quota history before startup reconciliation."""
        if mode in (HVACMode.OFF, HVACMode.COOL):
            self.requested_hvac_mode = HVACMode(mode)
        restored_target = finite_float(target)
        if restored_target is not None:
            self.target_temperature = self._normalize_target(restored_target)
        if isinstance(automatic_timestamps, list):
            for raw in automatic_timestamps:
                if not isinstance(raw, str):
                    continue
                parsed = dt_util.parse_datetime(raw)
                if parsed is not None:
                    self._automatic_command_timestamps.append(parsed)
        self._purge_budget(dt_util.utcnow())

    async def async_start(self) -> None:
        """Register all event sources and wait for startup settling."""
        if self._started:
            return
        self._started = True
        self._read_sensor_state(self.hass.states.get(self.sensor_entity_id))
        self._read_underlying_state(self.hass.states.get(self.climate_entity_id))
        self._listeners.extend(
            (
                async_track_state_change_event(
                    self.hass, self.sensor_entity_id, self._async_sensor_changed
                ),
                async_track_state_change_event(
                    self.hass,
                    self.climate_entity_id,
                    self._async_underlying_changed,
                ),
                async_at_start(self.hass, self._async_home_assistant_start),
            )
        )
        self._schedule_watchdog()
        if not self._sensor_valid:
            self._start_stale_timer()
        self._notify_state()

    async def async_stop(self) -> None:
        """Cancel every listener and timer owned by this entry."""
        self._started = False
        for remove in self._listeners:
            remove()
        self._listeners.clear()
        if self._watchdog_unsub is not None:
            self._watchdog_unsub()
            self._watchdog_unsub = None
        for name in (
            "_threshold_unsub",
            "_target_unsub",
            "_stale_unsub",
            "_pending_unsub",
            "_settle_unsub",
        ):
            remove = getattr(self, name)
            if remove is not None:
                remove()
                setattr(self, name, None)
        self.pending_command = None
        self.pending_command_at = None

    async def async_options_updated(self, options: ControllerOptions) -> None:
        """Apply options without reloading the config entry."""
        self.options = options
        self.target_temperature = self._normalize_target(self.target_temperature)
        self._cancel_threshold_timer()
        self._cancel_pending_timer()
        self._schedule_watchdog()
        if not self._sensor_valid:
            self._start_stale_timer()
        await self._consider_transition("options_update", debounce=False)
        await self.async_reconcile("options_update")

    async def async_set_hvac_mode(self, mode: HVACMode) -> None:
        """Apply user HVAC intent."""
        if mode not in (HVACMode.OFF, HVACMode.COOL):
            raise ValueError(f"Unsupported HVAC mode: {mode}")
        self.requested_hvac_mode = mode
        self._cancel_threshold_timer()
        if mode is HVACMode.OFF:
            self._set_controller_state(ControllerState.MANUAL_OFF, "manual_off")
            self._sensor_fault_active = False
            self.external_control = self.underlying_mode not in (
                None,
                HVACMode.OFF,
                STATE_UNAVAILABLE,
                STATE_UNKNOWN,
            )
            self._notify_state()
            await self.async_reconcile("manual_off")
            return

        self.external_control = False
        if self._sensor_valid and self.current_temperature is not None:
            self._set_controller_state(
                initial_cooling_state(
                    self.current_temperature, self.target_temperature, self.options
                ),
                "manual_turn_on",
            )
        else:
            self._set_controller_state(ControllerState.COOLING, "manual_turn_on")
        self._notify_state()
        await self.async_reconcile("manual_turn_on")

    async def async_set_target_temperature(self, temperature: float) -> None:
        """Store and debounce a new user room target."""
        parsed = finite_float(temperature)
        if parsed is None:
            raise ValueError("Target temperature must be a finite number")
        self.target_temperature = self._normalize_target(parsed)
        self._notify_state()
        if self.requested_hvac_mode is HVACMode.OFF:
            return
        if self._target_unsub is not None:
            self._target_unsub()

        async def target_ready(_now: datetime) -> None:
            self._target_unsub = None
            await self._consider_transition("target_change", debounce=True)
            await self.async_reconcile("target_change")

        self._target_unsub = async_call_later(
            self.hass, self.options.target_change_debounce, target_ready
        )

    async def async_reconcile(self, reason: str) -> None:
        """Serialize reconciliation and ensure a final pass after concurrent events."""
        if not self._started:
            return
        if not self._startup_settled and reason not in (
            "manual_off",
            "safety_off",
            "sensor_stale",
        ):
            return
        if self._lock.locked():
            self._dirty = True
            self._dirty_reason = reason
            return
        async with self._lock:
            current_reason = reason
            while True:
                self._dirty = False
                await self._async_reconcile_once(current_reason)
                if not self._dirty:
                    break
                current_reason = self._dirty_reason

    async def _async_reconcile_once(self, reason: str) -> None:
        """Calculate one desired command and apply quota controls."""
        if not self.underlying_available:
            self._set_controller_state(
                ControllerState.UNDERLYING_FAULT, "underlying_unavailable"
            )
            self.desired_command = None
            self._notify_state()
            return

        if self.requested_hvac_mode is HVACMode.OFF or self._sensor_fault_active:
            desired = DesiredCommand(HVACMode.OFF)
        elif not self._sensor_valid:
            _LOGGER.debug(
                "Suppressing %s: external sensor is temporarily invalid", reason
            )
            return
        elif self.controller_state in (
            ControllerState.SAFETY_OFF,
            ControllerState.SENSOR_FAULT,
        ):
            desired = DesiredCommand(HVACMode.OFF)
        else:
            setpoint = desired_setpoint(
                self.controller_state,
                target_temperature=self.target_temperature,
                underlying_temperature=self.underlying_temperature,
                configured_minimum=self.options.target_temperature_min,
                configured_maximum=self.options.target_temperature_max,
                underlying_minimum=self.underlying_minimum,
                underlying_maximum=self.underlying_maximum,
                underlying_step=self.underlying_step,
                options=self.options,
            )
            if setpoint is None:
                self.fault_reason = "no_common_temperature_range"
                return
            desired = DesiredCommand(HVACMode.COOL, setpoint)

        self.desired_command = desired
        now = dt_util.utcnow()
        if (
            self._expected_command == desired
            and self._suppression_until is not None
            and now <= self._suppression_until
        ):
            _LOGGER.debug("Deduplicated %s while awaiting command confirmation", reason)
            return
        step = self.underlying_step or self.options.target_temperature_step
        if commands_equivalent(
            desired,
            actual_mode=self.underlying_mode,
            actual_temperature=self.underlying_target,
            step=step,
        ):
            _LOGGER.debug("Deduplicated %s command: %s", reason, desired)
            self._clear_pending()
            self._notify_state()
            return

        bypass_all = reason in ("manual_off", "safety_off", "sensor_stale")
        bypass_interval = bypass_all or reason in ("manual_turn_on", "target_change")
        automatic = desired.hvac_mode == HVACMode.COOL
        if self._backoff_until is not None and now < self._backoff_until:
            self.pending_command = desired
            self.pending_command_at = self._backoff_until
            self._notify_state()
            return

        if automatic and not bypass_interval and self.last_command_at is not None:
            eligible_at = self.last_command_at + timedelta(
                seconds=self.options.minimum_automatic_command_interval
            )
            if now < eligible_at:
                self._schedule_pending(desired, eligible_at, reason)
                return

        if automatic and not bypass_all:
            self._purge_budget(now)
            if (
                len(self._automatic_command_timestamps)
                >= self.options.max_automatic_commands_24h
            ):
                eligible_at = self._automatic_command_timestamps[0] + BUDGET_WINDOW
                self.fault_reason = "automatic_command_budget_exhausted"
                if not self._quota_warned:
                    _LOGGER.warning(
                        "Controller automatic-command budget exhausted; safety and "
                        "manual off remain available"
                    )
                    self._quota_warned = True
                self._schedule_pending(desired, eligible_at, reason)
                self._notify_state()
                return

        await self._async_send_command(desired, reason, automatic)

    async def _async_send_command(
        self, desired: DesiredCommand, reason: str, automatic: bool
    ) -> None:
        """Send the minimum single Home Assistant climate service call."""
        now = dt_util.utcnow()
        self._expected_command = desired
        self._suppression_until = now + SELF_COMMAND_SUPPRESSION
        try:
            if desired.hvac_mode == HVACMode.OFF:
                await self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_TURN_OFF,
                    {ATTR_ENTITY_ID: self.climate_entity_id},
                    blocking=True,
                )
            else:
                await self.hass.services.async_call(
                    CLIMATE_DOMAIN,
                    SERVICE_SET_TEMPERATURE,
                    {
                        ATTR_ENTITY_ID: self.climate_entity_id,
                        ATTR_TEMPERATURE: desired.temperature,
                        "hvac_mode": HVACMode.COOL,
                    },
                    blocking=True,
                )
        except Exception as err:
            self._error_count += 1
            delay = min(
                60 * (2 ** (self._error_count - 1)), self.options.watchdog_interval
            )
            self._backoff_until = now + timedelta(seconds=delay)
            self.last_error_at = now
            self.fault_reason = type(err).__name__
            self._command_history.append(
                {
                    "at": self._iso(now),
                    "reason": reason,
                    "command": self._command_dict(desired),
                    "result": "error",
                    "error_category": type(err).__name__,
                }
            )
            _LOGGER.warning(
                "Underlying climate command failed (%s); next retry is "
                "event-driven and backoff-protected",
                type(err).__name__,
            )
            self._notify_state()
            return

        self._error_count = 0
        self._backoff_until = None
        self.fault_reason = None
        self.last_command_at = now
        self.last_command_reason = reason
        if automatic:
            self._automatic_command_timestamps.append(now)
        self._command_history.append(
            {
                "at": self._iso(now),
                "reason": reason,
                "command": self._command_dict(desired),
                "result": "sent",
            }
        )
        self._clear_pending()
        _LOGGER.info("Sent underlying climate command for %s: %s", reason, desired)
        self._notify_state()

    async def _async_sensor_changed(self, event: Event[EventStateChangedData]) -> None:
        """Process external sensor events."""
        was_valid = self._sensor_valid
        self._read_sensor_state(event.data["new_state"])
        if not self._sensor_valid:
            self._cancel_threshold_timer()
            self._start_stale_timer()
            self._notify_state()
            return

        self._cancel_stale_timer()
        if not was_valid and self._sensor_fault_active:
            self._sensor_fault_active = False
            self._sensor_fault_warned = False
            if not self.options.resume_after_sensor_recovery:
                self.requested_hvac_mode = HVACMode.OFF
                self._set_controller_state(
                    ControllerState.MANUAL_OFF, "sensor_recovery_requires_manual_on"
                )
                self._notify_state()
                return
            await self._consider_transition("sensor_recovery", debounce=False)
            await self.async_reconcile("sensor_recovery")
            return

        await self._consider_transition("sensor_event", debounce=True)
        self._notify_state()

    async def _async_underlying_changed(
        self, event: Event[EventStateChangedData]
    ) -> None:
        """Process underlying mode, action, and target events."""
        previous_available = self.underlying_available
        old_state = event.data["old_state"]
        new_state = event.data["new_state"]
        old_target = (
            finite_float(old_state.attributes.get(ATTR_TEMPERATURE))
            if old_state is not None
            else None
        )
        self._read_underlying_state(new_state)

        if not self.underlying_available:
            self._set_controller_state(
                ControllerState.UNDERLYING_FAULT, "underlying_unavailable"
            )
            self.fault_reason = "underlying_unavailable"
            if not self._underlying_fault_warned:
                _LOGGER.warning("Underlying climate entity is unavailable")
                self._underlying_fault_warned = True
            self._notify_state()
            return

        if not previous_available:
            self._underlying_fault_warned = False
            self._schedule_startup_settle("underlying_recovery")
            self._notify_state()
            return

        self_generated = self._matches_expected_command()
        if self_generated:
            self._expected_command = None
            self._suppression_until = None
        if (
            self.requested_hvac_mode is HVACMode.COOL
            and self.underlying_mode == HVACMode.OFF
            and not self_generated
        ):
            self.requested_hvac_mode = HVACMode.OFF
            self._set_controller_state(
                ControllerState.MANUAL_OFF, "external_manual_off"
            )
            self._cancel_threshold_timer()
            _LOGGER.info("Adopted external underlying off as virtual manual off")
        elif self.requested_hvac_mode is HVACMode.OFF:
            self.external_control = self.underlying_mode not in (
                HVACMode.OFF,
                None,
                STATE_UNKNOWN,
                STATE_UNAVAILABLE,
            )

        if (
            self.requested_hvac_mode is HVACMode.COOL
            and old_target != self.underlying_target
            and not self_generated
        ):
            self.external_target_drift = True
        self._notify_state()

    async def _consider_transition(self, reason: str, *, debounce: bool) -> None:
        """Apply or schedule a stable threshold transition."""
        candidate = next_controller_state(
            self.controller_state,
            requested_cool=self.requested_hvac_mode is HVACMode.COOL,
            room_temperature=self.current_temperature if self._sensor_valid else None,
            target_temperature=self.target_temperature,
            options=self.options,
            sensor_fault=self._sensor_fault_active,
            underlying_available=self.underlying_available,
        )
        if candidate is self.controller_state:
            self._cancel_threshold_timer()
            return
        if not debounce or self.options.temperature_debounce == 0:
            self._cancel_threshold_timer()
            self._set_controller_state(candidate, reason)
            return
        if candidate is self._threshold_candidate and self._threshold_unsub is not None:
            return
        self._cancel_threshold_timer()
        self._threshold_candidate = candidate

        async def transition_ready(_now: datetime) -> None:
            self._threshold_unsub = None
            expected = self._threshold_candidate
            self._threshold_candidate = None
            actual = next_controller_state(
                self.controller_state,
                requested_cool=self.requested_hvac_mode is HVACMode.COOL,
                room_temperature=(
                    self.current_temperature if self._sensor_valid else None
                ),
                target_temperature=self.target_temperature,
                options=self.options,
                sensor_fault=self._sensor_fault_active,
                underlying_available=self.underlying_available,
            )
            if expected is not None and actual is expected:
                self._set_controller_state(actual, reason)
                await self.async_reconcile(
                    "safety_off" if actual is ControllerState.SAFETY_OFF else reason
                )
            self._notify_state()

        self._threshold_unsub = async_call_later(
            self.hass, self.options.temperature_debounce, transition_ready
        )

    @callback
    def _set_controller_state(self, state: ControllerState, reason: str) -> None:
        if state is self.controller_state:
            return
        previous = self.controller_state
        self.controller_state = state
        self._transition_history.append(
            {
                "at": self._iso(dt_util.utcnow()),
                "from": previous,
                "to": state,
                "reason": reason,
            }
        )
        _LOGGER.debug("Controller transition %s -> %s (%s)", previous, state, reason)

    async def _async_home_assistant_start(self, _hass: HomeAssistant) -> None:
        self._schedule_startup_settle("startup")

    @callback
    def _schedule_startup_settle(self, reason: str) -> None:
        self._startup_settled = False
        if self._settle_unsub is not None:
            self._settle_unsub()

        async def settled(_now: datetime) -> None:
            self._settle_unsub = None
            self._read_sensor_state(self.hass.states.get(self.sensor_entity_id))
            self._read_underlying_state(self.hass.states.get(self.climate_entity_id))
            self._startup_settled = True
            await self._consider_transition(reason, debounce=False)
            await self.async_reconcile(reason)
            self._notify_state()

        self._settle_unsub = async_call_later(
            self.hass, self.options.startup_settle_delay, settled
        )

    @callback
    def _schedule_watchdog(self) -> None:
        if self._watchdog_unsub is not None:
            self._watchdog_unsub()
        self._watchdog_unsub = async_track_time_interval(
            self.hass,
            self._async_watchdog,
            timedelta(seconds=self.options.watchdog_interval),
        )

    async def _async_watchdog(self, _now: datetime) -> None:
        await self._consider_transition("watchdog", debounce=True)
        await self.async_reconcile("watchdog")

    @callback
    def _start_stale_timer(self) -> None:
        if self._sensor_invalid_since is None:
            self._sensor_invalid_since = dt_util.utcnow()
        self._cancel_stale_timer()
        elapsed = (dt_util.utcnow() - self._sensor_invalid_since).total_seconds()
        delay = max(0, self.options.sensor_stale_timeout - elapsed)

        async def stale(_now: datetime) -> None:
            self._stale_unsub = None
            if self._sensor_valid or self.requested_hvac_mode is HVACMode.OFF:
                return
            self._sensor_fault_active = True
            self._set_controller_state(ControllerState.SENSOR_FAULT, "sensor_stale")
            self.fault_reason = "external_sensor_stale"
            if not self._sensor_fault_warned:
                _LOGGER.warning("External temperature sensor remained invalid too long")
                self._sensor_fault_warned = True
            self._notify_state()
            await self.async_reconcile("sensor_stale")

        self._stale_unsub = async_call_later(self.hass, delay, stale)

    @callback
    def _read_sensor_state(self, state: State | None) -> None:
        value = None
        if state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE):
            value = finite_float(state.state)
            unit = state.attributes.get(ATTR_UNIT_OF_MEASUREMENT)
            configured_unit = self.hass.config.units.temperature_unit
            if value is not None and unit and unit != configured_unit:
                try:
                    value = TemperatureConverter.convert(value, unit, configured_unit)
                except ValueError:
                    value = None
        self._sensor_valid = value is not None
        if value is not None:
            self.current_temperature = value
            self._sensor_invalid_since = None
        elif self._sensor_invalid_since is None:
            self._sensor_invalid_since = dt_util.utcnow()

    @callback
    def _read_underlying_state(self, state: State | None) -> None:
        self.underlying_available = bool(
            state is not None and state.state not in (STATE_UNKNOWN, STATE_UNAVAILABLE)
        )
        if state is None:
            self.underlying_mode = None
            return
        self.underlying_mode = state.state
        self.underlying_action = state.attributes.get(ATTR_HVAC_ACTION)
        current = finite_float(state.attributes.get(ATTR_CURRENT_TEMPERATURE))
        if current is not None:
            self.underlying_temperature = current
        self.underlying_target = finite_float(state.attributes.get(ATTR_TEMPERATURE))
        self.underlying_minimum = finite_float(state.attributes.get(ATTR_MIN_TEMP))
        self.underlying_maximum = finite_float(state.attributes.get(ATTR_MAX_TEMP))
        self.underlying_step = finite_float(state.attributes.get(ATTR_TARGET_TEMP_STEP))

    @callback
    def _matches_expected_command(self) -> bool:
        if (
            self._expected_command is None
            or self._suppression_until is None
            or dt_util.utcnow() > self._suppression_until
        ):
            return False
        return commands_equivalent(
            self._expected_command,
            actual_mode=self.underlying_mode,
            actual_temperature=self.underlying_target,
            step=self.underlying_step or self.options.target_temperature_step,
        )

    @callback
    def _schedule_pending(
        self, command: DesiredCommand, when: datetime, reason: str
    ) -> None:
        self.pending_command = command
        self.pending_command_at = when
        if self._pending_unsub is not None:
            self._pending_unsub()
        delay = max(0, (when - dt_util.utcnow()).total_seconds())

        async def pending_ready(_now: datetime) -> None:
            self._pending_unsub = None
            await self.async_reconcile(f"pending_{reason}")

        self._pending_unsub = async_call_later(self.hass, delay, pending_ready)
        self._notify_state()

    @callback
    def _clear_pending(self) -> None:
        self._cancel_pending_timer()
        self.pending_command = None
        self.pending_command_at = None

    @callback
    def _cancel_pending_timer(self) -> None:
        if self._pending_unsub is not None:
            self._pending_unsub()
            self._pending_unsub = None

    @callback
    def _cancel_threshold_timer(self) -> None:
        if self._threshold_unsub is not None:
            self._threshold_unsub()
            self._threshold_unsub = None
        self._threshold_candidate = None

    @callback
    def _cancel_stale_timer(self) -> None:
        if self._stale_unsub is not None:
            self._stale_unsub()
            self._stale_unsub = None

    @callback
    def _purge_budget(self, now: datetime) -> None:
        cutoff = now - BUDGET_WINDOW
        while (
            self._automatic_command_timestamps
            and self._automatic_command_timestamps[0] <= cutoff
        ):
            self._automatic_command_timestamps.popleft()
        if (
            len(self._automatic_command_timestamps)
            < self.options.max_automatic_commands_24h
        ):
            self._quota_warned = False

    @callback
    def _normalize_target(self, value: float) -> float:
        minimum = self.options.target_temperature_min
        maximum = self.options.target_temperature_max
        step = self.options.target_temperature_step
        bounded = min(max(value, minimum), maximum)
        steps = round((bounded - minimum) / step)
        return min(maximum, max(minimum, minimum + steps * step))

    @callback
    def _notify_state(self) -> None:
        for listener in tuple(self._state_callbacks):
            listener()

    @staticmethod
    def _iso(value: datetime | None) -> str | None:
        return value.isoformat() if value is not None else None

    @staticmethod
    def _command_dict(command: DesiredCommand | None) -> dict[str, Any] | None:
        if command is None:
            return None
        return {"hvac_mode": command.hvac_mode, "temperature": command.temperature}
