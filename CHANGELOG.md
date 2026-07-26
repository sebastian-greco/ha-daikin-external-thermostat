# Changelog

All notable changes follow semantic versioning.

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
