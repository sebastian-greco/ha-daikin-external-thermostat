# Daikin External Thermostat

An event-driven Home Assistant custom integration that exposes a normal climate
entity while controlling an existing inverter air conditioner from a better
external room-temperature sensor.

It is designed to be quiet on the API: state changes drive control, identical
commands are deduplicated, normal writes are spaced and budgeted, and the only
timer that runs indefinitely is a low-frequency recovery watchdog. Despite the
name, the controller talks only to Home Assistant's standard `climate` service,
so it does not connect directly to Daikin or store Daikin credentials.

## Highlights

- All standard HVAC modes advertised by the selected underlying climate
- Capability-based forwarding for fan speed, native presets (including
  Powerful/Boost when available), vertical and horizontal swing, target ranges,
  and humidity controls
- External sensor shown as current temperature
- Retained target temperature and requested mode across restarts
- Cooling, coasting, optional automatic boost, and latched cold-safety stages
- Sensor-stale and underlying-unavailable fault handling
- Command deduplication, 20-minute default spacing, and rolling 24-hour budget
- Manual and safety off always remain available, even after budget exhaustion
- Detection of external remote/app changes without immediately fighting them
- Multiple isolated entries, with one controller allowed per underlying climate
- Fully configurable thresholds, offsets, timing, recovery, and target range
- English and Italian UI translations and privacy-safe diagnostics

The complete behavioral contract is in
[the functional description](docs/functional-description.md).

## Install with HACS

1. In HACS, open **Integrations**.
2. Open the three-dot menu and choose **Custom repositories**.
3. Add `https://github.com/sebastian-greco/ha-daikin-external-thermostat` as an
   **Integration** repository.
4. Find **Daikin External Thermostat**, download the latest release, and restart
   Home Assistant.
5. Go to **Settings > Devices & services > Add integration**, search for
   **Daikin External Thermostat**, then select the room sensor and underlying AC.

[Open the HACS repository dialog](https://my.home-assistant.io/redirect/hacs_repository/?owner=sebastian-greco&repository=ha-daikin-external-thermostat&category=integration)

## Manual installation

Copy
`custom_components/daikin_external_thermostat` into your Home Assistant
`/config/custom_components/` directory, restart Home Assistant, and add the
integration from **Settings > Devices & services**. Do not edit `.storage`.

## First bedroom rollout

For the setup described in this repository, choose:

| Role | Entity |
| --- | --- |
| External room sensor | `sensor.temperatura_camera_matrimoniale_temperature` |
| Underlying climate | `climate.camera_matrimoniale_room_temperature` |

Before turning the new virtual climate on:

1. Disable the Versatile Thermostat entry that controls this AC.
2. Disable `automation.ac_matrimoniale_on` and
   `automation.ac_matrimoniale_off`.
3. Confirm that no other automation writes to the same climate entity.
4. Start with defaults and change only one tuning option at a time after
   reviewing several nights of history and diagnostics.

Only one controller should have authority over the underlying AC. A physical
remote or Daikin app can still turn it off; the integration adopts that off as
the new virtual user intent instead of restarting it.

## How control works

The virtual room target is not copied to the Daikin setpoint. Instead, the
controller compares external room temperature (`R`) with the room target (`T`),
selects an internal stage, and moves the underlying target relative to the
underlying AC thermometer (`U`):

| Internal stage | Default setpoint mapping |
| --- | --- |
| Boosting | `U - 1.5 °C` |
| Cooling | `U - 0.5 °C` |
| Coasting | `U + 1.0 °C` |
| Safety off | Underlying climate off |

Boost is optional and internal; it is never exposed as an HVAC mode. Threshold
crossings must remain stable for 30 seconds by default. The resulting setpoint
is clamped and quantized to the underlying entity's supported range and step.

`cool` is the externally regulated mode described above. Every other HVAC mode
advertised by the underlying entity—such as heat, dry, auto, heat/cool, or
fan-only—is exposed as direct passthrough. In passthrough modes, temperature,
temperature range, humidity, fan, swing, and preset requests are sent unchanged
through Home Assistant after validation and normalization. These manual controls
are immediate and do not consume the automatic cooling command budget.

Native Daikin Powerful/Boost is exposed only when the underlying climate lists it
as a preset. It remains separate from the controller's automatic `boosting`
stage, which changes only the calculated cooling setpoint.

## Diagnostics

Download diagnostics from the config entry menu in **Settings > Devices &
services**. Diagnostics include controller state, recent bounded transitions and
commands, pending work, quota count, and fault category. Entity IDs and the
user-assigned entry name are intentionally omitted.

## Development

Home Assistant Core 2026.7.4 is the initial compatibility target.

```bash
uv sync --dev
uv run ruff check .
uv run ruff format --check .
uv run mypy custom_components/daikin_external_thermostat
uv run pytest
```

See [CONTRIBUTING.md](CONTRIBUTING.md) and [AGENTS.md](AGENTS.md) before making
controller changes.

## License

[MIT](LICENSE)
