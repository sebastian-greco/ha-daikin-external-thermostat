# Changelog

All notable changes follow semantic versioning.

## 1.1.1 - 2026-07-27

- Prevent delayed attribute-only refreshes of an already-off underlying climate
  from being mistaken for a new external manual-off command.
- Keep expected self-generated commands active for the complete suppression
  window so multiple cloud state updates remain correctly classified.

## 1.1.0 - 2026-07-27

- Mirror every standard HVAC mode advertised by the underlying climate while
  keeping external-sensor regulation scoped to cooling.
- Forward fan speed, vertical and horizontal swing, and native presets such as
  Powerful/Boost, Quiet, and Econo when the underlying entity supports them.
- Forward passthrough target temperatures, heat/cool ranges, and humidity
  controls with underlying bounds and step normalization.
- Reflect remote/app changes to passthrough controls immediately from cached
  Home Assistant state without polling or direct Daikin API access.
- Keep native Powerful/Boost presets distinct from the automatic internal
  boosting stage and exclude manual passthrough calls from the automatic budget.

## 1.0.0 - 2026-07-27

- Add an event-driven `off` / `cool` climate entity using an external room
  temperature sensor.
- Add cooling, coasting, optional boost, safety-off, sensor-fault, and
  underlying-fault controller states.
- Add command deduplication, minimum spacing, rolling 24-hour budget,
  exponential error backoff, and a recovery watchdog.
- Add target/mode restoration, external remote/app change handling, and
  privacy-safe diagnostics.
- Add grouped UI configuration, complete tuning options, and English/Italian
  translations.
- Add HACS metadata, automated validation and release workflows, and Home
  Assistant 2026.7.4 integration tests.
