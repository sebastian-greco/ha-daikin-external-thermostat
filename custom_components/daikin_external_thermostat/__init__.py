"""Daikin External Thermostat integration."""

from __future__ import annotations

from dataclasses import dataclass

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant

from .const import PLATFORMS, default_options, default_target
from .controller import DaikinExternalThermostatController
from .models import ControllerOptions


@dataclass(slots=True)
class RuntimeData:
    """Runtime data owned by one config entry."""

    controller: DaikinExternalThermostatController


type DaikinExternalThermostatConfigEntry = ConfigEntry[RuntimeData]


def _entry_options(
    hass: HomeAssistant, entry: DaikinExternalThermostatConfigEntry
) -> ControllerOptions:
    values = default_options(hass.config.units.temperature_unit)
    values.update(entry.options)
    return ControllerOptions.from_mapping(values)


async def async_setup_entry(
    hass: HomeAssistant, entry: DaikinExternalThermostatConfigEntry
) -> bool:
    """Set up Daikin External Thermostat from a config entry."""
    controller = DaikinExternalThermostatController(
        hass,
        entry.entry_id,
        dict(entry.data),
        _entry_options(hass, entry),
        default_target(hass.config.units.temperature_unit),
    )
    entry.runtime_data = RuntimeData(controller)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    return True


async def async_unload_entry(
    hass: HomeAssistant, entry: DaikinExternalThermostatConfigEntry
) -> bool:
    """Unload a config entry and every controller callback."""
    if not await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        return False
    await entry.runtime_data.controller.async_stop()
    return True


async def _async_options_updated(
    hass: HomeAssistant, entry: DaikinExternalThermostatConfigEntry
) -> None:
    """Apply changed options in place without recreating the entry."""
    await entry.runtime_data.controller.async_options_updated(
        _entry_options(hass, entry)
    )
