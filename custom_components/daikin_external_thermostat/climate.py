"""Climate entity for Daikin External Thermostat."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
    ATTR_HVAC_MODE,
    ATTR_TARGET_TEMP_HIGH,
    ATTR_TARGET_TEMP_LOW,
    ClimateEntityFeature,
    HVACAction,
    HVACMode,
)
from homeassistant.const import ATTR_TEMPERATURE
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.device_registry import DeviceEntryType, DeviceInfo
from homeassistant.helpers.entity_platform import AddConfigEntryEntitiesCallback
from homeassistant.helpers.restore_state import RestoreEntity

from . import DaikinExternalThermostatConfigEntry
from .const import DOMAIN
from .controller import DaikinExternalThermostatController


async def async_setup_entry(
    hass: HomeAssistant,
    entry: DaikinExternalThermostatConfigEntry,
    async_add_entities: AddConfigEntryEntitiesCallback,
) -> None:
    """Set up the virtual climate entity."""
    async_add_entities([DaikinExternalThermostatClimate(entry)])


class DaikinExternalThermostatClimate(ClimateEntity, RestoreEntity):
    """User-facing climate adapter; all control lives in the controller."""

    _attr_should_poll = False
    _attr_has_entity_name = True
    _attr_name = None

    def __init__(self, entry: DaikinExternalThermostatConfigEntry) -> None:
        """Initialize from config-entry runtime data."""
        self._entry = entry
        self._controller: DaikinExternalThermostatController = (
            entry.runtime_data.controller
        )
        self._attr_unique_id = entry.unique_id or entry.entry_id
        self._attr_device_info = DeviceInfo(
            identifiers={(DOMAIN, entry.entry_id)},
            name=entry.title,
            manufacturer="Home Assistant Community",
            model="External thermostat controller",
            entry_type=DeviceEntryType.SERVICE,
        )
        self._remove_controller_listener: Callable[[], None] | None = None

    @property
    def available(self) -> bool:
        """Return whether the underlying climate is available."""
        return self._controller.available

    @property
    def temperature_unit(self) -> str:
        """Return Home Assistant's configured temperature unit."""
        return self.hass.config.units.temperature_unit

    @property
    def current_temperature(self) -> float | None:
        """Return the latest valid external sensor temperature."""
        return self._controller.current_temperature

    @property
    def supported_features(self) -> ClimateEntityFeature:
        """Expose standard features genuinely supported by the underlying AC."""
        features = (
            ClimateEntityFeature.TARGET_TEMPERATURE
            | ClimateEntityFeature.TURN_ON
            | ClimateEntityFeature.TURN_OFF
        )
        forwarded = self._controller.underlying_supported_features
        for feature, modes in (
            (ClimateEntityFeature.FAN_MODE, self.fan_modes),
            (ClimateEntityFeature.PRESET_MODE, self.preset_modes),
            (ClimateEntityFeature.SWING_MODE, self.swing_modes),
            (
                ClimateEntityFeature.SWING_HORIZONTAL_MODE,
                self.swing_horizontal_modes,
            ),
        ):
            if forwarded & feature and modes:
                features |= feature
        if forwarded & ClimateEntityFeature.TARGET_TEMPERATURE_RANGE:
            features |= ClimateEntityFeature.TARGET_TEMPERATURE_RANGE
        if forwarded & ClimateEntityFeature.TARGET_HUMIDITY:
            features |= ClimateEntityFeature.TARGET_HUMIDITY
        return features

    @property
    def hvac_modes(self) -> list[HVACMode]:
        """Return the HVAC modes advertised by the underlying AC."""
        return self._controller.underlying_hvac_modes

    @property
    def target_temperature(self) -> float | None:
        """Return the regulated cool target or raw passthrough target."""
        return self._controller.exposed_target_temperature

    @property
    def target_temperature_step(self) -> float:
        """Return the regulated or underlying target step."""
        if (
            self.hvac_mode not in (HVACMode.OFF, HVACMode.COOL)
            and self._controller.underlying_step is not None
        ):
            return self._controller.underlying_step
        return self._controller.options.target_temperature_step

    @property
    def min_temp(self) -> float:
        """Return the regulated or underlying minimum target."""
        if (
            self.hvac_mode not in (HVACMode.OFF, HVACMode.COOL)
            and self._controller.underlying_minimum is not None
        ):
            return self._controller.underlying_minimum
        return self._controller.options.target_temperature_min

    @property
    def max_temp(self) -> float:
        """Return the regulated or underlying maximum target."""
        if (
            self.hvac_mode not in (HVACMode.OFF, HVACMode.COOL)
            and self._controller.underlying_maximum is not None
        ):
            return self._controller.underlying_maximum
        return self._controller.options.target_temperature_max

    @property
    def target_temperature_low(self) -> float | None:
        """Return the cached lower target for heat/cool range modes."""
        return self._controller.underlying_target_low

    @property
    def target_temperature_high(self) -> float | None:
        """Return the cached upper target for heat/cool range modes."""
        return self._controller.underlying_target_high

    @property
    def current_humidity(self) -> int | None:
        """Return cached underlying humidity when available."""
        return self._controller.underlying_current_humidity

    @property
    def target_humidity(self) -> int | None:
        """Return the cached underlying humidity target."""
        return self._controller.underlying_target_humidity

    @property
    def min_humidity(self) -> int:
        """Return the underlying minimum humidity target."""
        return (
            self._controller.underlying_minimum_humidity
            if self._controller.underlying_minimum_humidity is not None
            else 30
        )

    @property
    def max_humidity(self) -> int:
        """Return the underlying maximum humidity target."""
        return (
            self._controller.underlying_maximum_humidity
            if self._controller.underlying_maximum_humidity is not None
            else 99
        )

    @property
    def target_humidity_step(self) -> int:
        """Return the underlying target-humidity step."""
        return (
            self._controller.underlying_humidity_step
            if self._controller.underlying_humidity_step is not None
            else 1
        )

    @property
    def hvac_mode(self) -> HVACMode:
        """Return user intent, independently of underlying mode."""
        return self._controller.requested_hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Return the standard action mapped from controller state."""
        return self._controller.hvac_action

    @property
    def fan_mode(self) -> str | None:
        """Return the cached underlying fan mode."""
        return self._controller.underlying_fan_mode

    @property
    def fan_modes(self) -> list[str] | None:
        """Return the cached underlying fan modes."""
        return self._controller.underlying_fan_modes

    @property
    def swing_mode(self) -> str | None:
        """Return the cached underlying vertical/combined swing mode."""
        return self._controller.underlying_swing_mode

    @property
    def swing_modes(self) -> list[str] | None:
        """Return cached underlying vertical/combined swing modes."""
        return self._controller.underlying_swing_modes

    @property
    def swing_horizontal_mode(self) -> str | None:
        """Return the cached underlying horizontal swing mode."""
        return self._controller.underlying_swing_horizontal_mode

    @property
    def swing_horizontal_modes(self) -> list[str] | None:
        """Return cached underlying horizontal swing modes."""
        return self._controller.underlying_swing_horizontal_modes

    @property
    def preset_mode(self) -> str | None:
        """Return the cached native preset mode."""
        return self._controller.underlying_preset_mode

    @property
    def preset_modes(self) -> list[str] | None:
        """Return cached native preset modes."""
        return self._controller.underlying_preset_modes

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        """Return bounded controller diagnostics and restore data."""
        return self._controller.diagnostic_attributes

    async def async_added_to_hass(self) -> None:
        """Restore intent before event processing and delayed reconciliation."""
        await super().async_added_to_hass()
        if (last_state := await self.async_get_last_state()) is not None:
            self._controller.restore(
                last_state.state,
                last_state.attributes.get(
                    "cooling_target_temperature",
                    last_state.attributes.get(ATTR_TEMPERATURE),
                ),
                last_state.attributes.get("automatic_command_timestamps"),
            )
        self._remove_controller_listener = self._controller.add_state_listener(
            self._async_controller_updated
        )
        await self._controller.async_start()

    async def async_will_remove_from_hass(self) -> None:
        """Detach the entity and cancel all owned callbacks."""
        if self._remove_controller_listener is not None:
            self._remove_controller_listener()
            self._remove_controller_listener = None
        await self._controller.async_stop()
        await super().async_will_remove_from_hass()

    async def async_set_hvac_mode(self, hvac_mode: HVACMode) -> None:
        """Set requested virtual mode."""
        await self._controller.async_set_hvac_mode(hvac_mode)

    async def async_turn_on(self) -> None:
        """Restore cooling using the retained room target."""
        await self._controller.async_set_hvac_mode(HVACMode.COOL)

    async def async_turn_off(self) -> None:
        """Immediately turn off virtual and underlying climates."""
        await self._controller.async_set_hvac_mode(HVACMode.OFF)

    async def async_set_temperature(self, **kwargs: Any) -> None:
        """Set a regulated cooling target or a raw passthrough target."""
        requested_mode_raw = kwargs.get(ATTR_HVAC_MODE)
        requested_mode = (
            HVACMode(requested_mode_raw) if requested_mode_raw is not None else None
        )
        if ATTR_TEMPERATURE not in kwargs:
            if ATTR_TARGET_TEMP_LOW in kwargs or ATTR_TARGET_TEMP_HIGH in kwargs:
                effective_mode = requested_mode or self._controller.requested_hvac_mode
                await self._controller.async_set_passthrough_temperature(
                    mode=effective_mode,
                    target_low=kwargs.get(ATTR_TARGET_TEMP_LOW),
                    target_high=kwargs.get(ATTR_TARGET_TEMP_HIGH),
                )
                return
            if requested_mode is not None:
                await self._controller.async_set_hvac_mode(requested_mode)
            return
        temperature = kwargs[ATTR_TEMPERATURE]
        effective_mode = requested_mode or self._controller.requested_hvac_mode
        if effective_mode not in (HVACMode.OFF, HVACMode.COOL):
            await self._controller.async_set_passthrough_temperature(
                temperature, requested_mode
            )
            return
        await self._controller.async_set_target_temperature(temperature)
        if requested_mode is not None and (
            self._controller.requested_hvac_mode is not requested_mode
        ):
            await self._controller.async_set_hvac_mode(requested_mode)

    async def async_set_fan_mode(self, fan_mode: str) -> None:
        """Set the underlying fan mode."""
        await self._controller.async_set_fan_mode(fan_mode)

    async def async_set_swing_mode(self, swing_mode: str) -> None:
        """Set the underlying vertical/combined swing mode."""
        await self._controller.async_set_swing_mode(swing_mode)

    async def async_set_swing_horizontal_mode(self, swing_horizontal_mode: str) -> None:
        """Set the underlying horizontal swing mode."""
        await self._controller.async_set_swing_horizontal_mode(swing_horizontal_mode)

    async def async_set_preset_mode(self, preset_mode: str) -> None:
        """Set a native underlying preset such as Powerful or Econo."""
        await self._controller.async_set_preset_mode(preset_mode)

    async def async_set_humidity(self, humidity: int) -> None:
        """Set the underlying target humidity."""
        await self._controller.async_set_humidity(humidity)

    @callback
    def _async_controller_updated(self) -> None:
        if self.hass is not None and self.entity_id is not None:
            self.async_write_ha_state()
