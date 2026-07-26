"""Diagnostics for Daikin External Thermostat."""

from __future__ import annotations

from typing import Any

from homeassistant.core import HomeAssistant

from . import DaikinExternalThermostatConfigEntry


async def async_get_config_entry_diagnostics(
    hass: HomeAssistant, entry: DaikinExternalThermostatConfigEntry
) -> dict[str, Any]:
    """Return diagnostics with names and entity IDs deliberately omitted."""
    return {
        "entry": {
            "version": entry.version,
            "minor_version": entry.minor_version,
        },
        "controller": entry.runtime_data.controller.diagnostics(),
    }
