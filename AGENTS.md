# Agent starter guide

## Project contract

- Display name: `Daikin External Thermostat`
- Integration domain: `daikin_external_thermostat`
- Runtime target: Home Assistant Core 2026.7.4 or newer
- Canonical behavior: `docs/functional-description.md`

The integration is event-driven. Do not add polling, a `DataUpdateCoordinator`,
periodic setpoint rewrites, or direct Daikin API access. Mirror the standard HVAC
modes, fan modes, swing modes, presets, temperature ranges, and humidity controls
advertised by the selected underlying climate. The controller is the only code
allowed to call the underlying climate. Entity properties must remain I/O-free.

## Architecture

- `climate.py` is a thin user-intent and state adapter.
- `controller.py` owns listeners, timers, serialization, quota protection, and
  service calls.
- `models.py` contains pure transition and setpoint calculations.
- Each config entry owns exactly one external sensor and one underlying climate.
- `cool` uses external-sensor regulation; every other supported active HVAC mode
  is direct, event-driven passthrough.
- Native presets such as Powerful/Boost are distinct from the controller's
  automatic internal `boosting` stage.
- Immediate user passthrough writes are logged and serialized but do not consume
  the automatic cooling command budget.
- Manual off, safety off, and stale-sensor off must bypass automatic throttles.

## Development

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/daikin_external_thermostat
uv run pytest
```

Before releasing, update the version in both `pyproject.toml` and
`custom_components/daikin_external_thermostat/manifest.json`, run all checks,
tag `vX.Y.Z`, and publish a GitHub release with user-facing notes.
