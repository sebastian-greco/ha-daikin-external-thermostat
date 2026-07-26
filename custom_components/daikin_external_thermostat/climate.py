"""Climate entity for Daikin External Thermostat."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from homeassistant.components.climate import ClimateEntity
from homeassistant.components.climate.const import (
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
    _attr_supported_features = (
        ClimateEntityFeature.TARGET_TEMPERATURE
        | ClimateEntityFeature.TURN_ON
        | ClimateEntityFeature.TURN_OFF
    )

    def __init__(self, entry: DaikinExternalThermostatConfigEntry) -> None:
        """Initialize from config-entry runtime data."""
        self._entry = entry
        self._attr_hvac_modes = [HVACMode.OFF, HVACMode.COOL]
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
    def target_temperature(self) -> float:
        """Return the retained user room target."""
        return self._controller.target_temperature

    @property
    def target_temperature_step(self) -> float:
        """Return the configured room-target step."""
        return self._controller.options.target_temperature_step

    @property
    def min_temp(self) -> float:
        """Return the configured minimum room target."""
        return self._controller.options.target_temperature_min

    @property
    def max_temp(self) -> float:
        """Return the configured maximum room target."""
        return self._controller.options.target_temperature_max

    @property
    def hvac_mode(self) -> HVACMode:
        """Return user intent, independently of underlying mode."""
        return self._controller.requested_hvac_mode

    @property
    def hvac_action(self) -> HVACAction:
        """Return the standard action mapped from controller state."""
        return self._controller.hvac_action

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
                last_state.attributes.get(ATTR_TEMPERATURE),
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
        """Set the virtual room target without directly copying it downstream."""
        if ATTR_TEMPERATURE not in kwargs:
            return
        await self._controller.async_set_target_temperature(kwargs[ATTR_TEMPERATURE])

    @callback
    def _async_controller_updated(self) -> None:
        if self.hass is not None and self.entity_id is not None:
            self.async_write_ha_state()
