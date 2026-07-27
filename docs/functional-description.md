# Event-driven external-sensor climate controller

Status: implementation specification for a new Home Assistant custom integration.

Published integration name: **Daikin External Thermostat**
Published domain: `daikin_external_thermostat`

The behavior in this document is the implementation contract.

## 1. Objective

Build a standalone Home Assistant integration that exposes a normal
`ClimateEntity` and controls an existing inverter air conditioner using an
external room-temperature sensor.

The virtual climate entity must be the everyday user interface:

- turn cooling on and off from any standard climate card;
- select any HVAC mode and standard control advertised by the underlying entity;
- change the requested room temperature directly on that card;
- display the external sensor as its current temperature;
- retain the last target temperature;
- regulate the underlying AC with very few service calls;
- stop excessive cooling safely;
- avoid continuously polling or continually rewriting the Daikin setpoint.

This is not a generic on/off thermostat and is not a Versatile Thermostat fork.
It is a small controller for an already-integrated modulating AC. Regulated
cooling can use an optional automatic boost stage when the room is far above
target; all other advertised modes use direct passthrough.

## 2. Initial installation

The first production entry will control only Camera matrimoniale:

| Role | Entity |
| --- | --- |
| External room sensor | `sensor.temperatura_camera_matrimoniale_temperature` |
| Underlying Daikin climate | `climate.camera_matrimoniale_room_temperature` |
| New virtual climate | Entity ID chosen by Home Assistant from the entry name |

The integration supports multiple independent config entries. Each
entry controls exactly one underlying climate entity with exactly one external
temperature sensor. The config flow must reject an underlying climate entity
already managed by another entry.

## 3. Non-goals

- No PID loop and no periodic setpoint adjustment.
- No direct Daikin API client. All commands go through Home Assistant's existing
  underlying `climate` entity.
- No dependence on Sleep mode, presence, schedules, or automations.
- No helper required for the target temperature.
- No attempt to estimate compressor power or inverter frequency.
- No synthetic Daikin-specific modes or presets. Only standard capabilities
  advertised by the underlying Home Assistant climate entity are forwarded.
- No separate Boost HVAC mode. Automatic boost is an internal cooling stage
  described in sections 6–8; native Powerful/Boost remains a distinct forwarded
  preset when the underlying entity advertises it.
- No attachment to or merging with the Daikin integration's device-registry
  device.

## 4. User-facing climate entity

Implement `DaikinExternalThermostatClimate(ClimateEntity)` with
`should_poll = False`.

### 4.1 Standard capabilities

Always expose:

- `hvac_modes`: every valid standard mode advertised by the underlying climate;
- `hvac_mode`: the user's requested mode, not merely the latest underlying mode;
- `current_temperature`: latest valid value from the external sensor;
- `target_temperature`: the user's requested room target in `off`/`cool`, or the
  cached underlying target in a passthrough mode;
- `hvac_action`:
  - `off` when the requested mode is off;
  - `cooling` when the controller is demanding cooling and the underlying entity
    reports cooling;
  - `idle` while coasting, safety-held, waiting for a command lockout, or when
    cooling is requested but the underlying entity is not actively cooling;
  - the cached underlying action in a passthrough HVAC mode;
- configurable minimum, maximum, and target step;
- supported features for target temperature, turn on, and turn off.

Capability-based passthrough must additionally expose the underlying entity's:

- fan modes and current fan mode;
- vertical/combined and horizontal swing modes;
- native presets, including Powerful/Boost, Quiet, Comfort, or Econo whenever
  those exact values are advertised;
- target-temperature range and current low/high targets;
- current/target humidity and humidity bounds/step.

Never invent a feature or option absent from the underlying entity's cached
state. Arbitrary preset and mode strings supplied by the underlying integration
must be retained, while HVAC modes must be valid Home Assistant `HVACMode`
values.

All entity properties must return values already held in memory. They must never
perform I/O or service calls.

### 4.2 Standard service behavior

`climate.set_hvac_mode`:

- `off`: immediately request an underlying off command, bypassing normal command
  spacing and budget restrictions;
- `cool`: retain the current target, enter automatic control, and reconcile once;
- any other advertised mode: immediately forward that mode and enter
  `passthrough`; external-sensor transitions, safety-off, and the cooling
  watchdog must not operate until `cool` is selected again.

`climate.turn_off` is equivalent to setting HVAC mode to off.

`climate.turn_on` restores `cool`, using the retained target temperature.

`climate.set_temperature`:

- in `off`/`cool`, validates and stores the new room target;
- while off, sends no underlying command;
- while cool, schedules one immediate reconciliation;
- multiple rapid cooling target changes are debounced and coalesced into one
  command;
- in another advertised mode, forwards the normalized underlying target or
  target-temperature range immediately without applying cooling offsets;
- does not directly copy the room target to the underlying AC setpoint in
  regulated cooling.

Fan, swing, horizontal-swing, preset, and humidity service requests validate the
requested value against cached underlying capabilities and are then forwarded
immediately. These manual passthrough calls are serialized and logged, but do not
consume the automatic cooling command budget and are never automatically
replayed after failure.

The retained cooling target and requested HVAC mode must be restored across Home
Assistant restarts. A restored `cool` request does not command the AC until
startup settling and entity validation have completed. A restored passthrough
mode reflects cached underlying state and does not create a startup write.

### 4.3 Availability

The virtual climate entity is unavailable when the underlying climate entity is
unavailable. A temporarily unavailable external sensor does not immediately
make the virtual entity unavailable; it invokes the sensor-fault policy in
section 10.

### 4.4 Device and unique identity

Create either no device or a dedicated controller/service device belonging only
to this config entry. Do not add this entity to the Daikin device.

Derive a stable config-entry unique ID from the underlying entity-registry
identity plus the external sensor identity when both are available. Fall back to
the two configured entity IDs. Never use the user-visible entry name as the
unique ID.

## 5. Temperature model

Use these terms throughout the code:

- `R`: valid external room temperature;
- `T`: user-selected room target;
- `U`: current temperature reported by the underlying AC;
- `error = R - T`: positive means the room is warmer than requested;
- `S`: desired underlying AC setpoint after clamping and quantization.

Temperatures must be converted to Home Assistant's configured temperature unit
before comparison. Validate sensor states as finite numbers. Reject `unknown`,
`unavailable`, NaN, and infinity.

## 6. Controller states

The controller has one user-requested mode and a separate internal state.

Internal states:

| State | Meaning |
| --- | --- |
| `manual_off` | User requested off; the integration will not restart the AC. |
| `passthrough` | A non-cooling HVAC mode is active; mirror and forward controls without external-sensor regulation. |
| `boosting` | Room is far above target; request a more aggressive AC setpoint. |
| `cooling` | Cooling is required and an active cooling setpoint is desired. |
| `coasting` | Near the target; request little/no cooling without cycling power. |
| `safety_off` | Room is materially too cold; force the underlying AC off. |
| `sensor_fault` | External sensor has been invalid too long; force off once. |
| `underlying_fault` | The underlying climate cannot currently be controlled. |

Boost is not another mode the user has to select. The climate entity continues
to show HVAC mode `cool` and HVAC action `cooling`; `boosting` is visible only as
controller diagnostic state. Its purpose is to cool more aggressively while the
room is far from target, then step down to ordinary cooling before coasting.

Boost must remain optional. When `boost_enabled` is false, conditions that would
enter `boosting` remain in `cooling` instead.

## 7. Transition rules

Defaults are initial tuning values, not hard-coded constants. Every value in
this section must be exposed in the options flow.

| Option | Default | Meaning |
| --- | ---: | --- |
| `boost_enabled` | true | Permit the automatic aggressive-cooling stage. |
| `boost_enter_delta` | 1.5 °C | Enter boost when `R >= T + delta`. |
| `boost_exit_delta` | 0.8 °C | Step down to normal cooling when `R <= T + delta`. |
| `cool_enter_delta` | 0.5 °C | Start/resume cooling when `R >= T + delta`. |
| `coast_enter_delta` | 0.2 °C | Begin coasting early when `R <= T + delta`. |
| `safety_off_delta` | 1.0 °C | Force off when `R <= T - delta`. |
| `safety_resume_delta` | 0.5 °C | Leave safety-off only when `R >= T + delta`. |
| `temperature_debounce` | 30 s | Require a threshold crossing to remain valid. |

The controller applies these rules in priority order:

1. A user request for off always enters `manual_off`.
2. Any advertised active mode other than `cool` enters `passthrough` and skips
   the remaining cooling transition rules.
3. An invalid/stale external sensor can enter `sensor_fault` while `cool` is
   requested.
4. `R <= T - safety_off_delta` enters `safety_off` from any requested-cool
   state.
5. `safety_off` remains latched until `R >= T + safety_resume_delta`; on release,
   select `boosting` if its entry condition is true, otherwise `cooling`.
6. With boost enabled, `cooling` enters `boosting` when
   `R >= T + boost_enter_delta`.
7. `boosting` returns to `cooling` when `R <= T + boost_exit_delta`.
8. `cooling` enters `coasting` when `R <= T + coast_enter_delta`.
9. `coasting` enters `cooling` when `R >= T + cool_enter_delta`, or directly
   enters `boosting` if the boost entry condition is already true.

All automatic threshold transitions require the condition to remain true for
`temperature_debounce`. Manual off is never debounced. A target change is
evaluated against the latest temperature immediately but still produces at most
one reconciled command.

The transition comparisons are inclusive to avoid edge ambiguity. Hysteresis
prevents chatter between cooling and coasting.

### 7.1 Validation of options

Reject invalid option combinations in the options flow:

- all deltas and offsets must be non-negative;
- `coast_enter_delta < cool_enter_delta`;
- `cool_enter_delta <= boost_exit_delta < boost_enter_delta`;
- `safety_resume_delta >= cool_enter_delta`;
- target minimum must be lower than target maximum;
- target step must be supported by the underlying entity or be safely
  quantizable to it;
- minimum command interval and watchdog interval must be positive;
- stale timeout must exceed the ordinary expected sensor reporting interval.

Display the inequalities in validation errors so the user can correct them.

## 8. Mapping room demand to the AC setpoint

The controller manipulates the underlying target relative to the underlying
unit's own thermometer. Offsets are configured as positive magnitudes.

| Option | Default | Formula |
| --- | ---: | --- |
| `boost_offset` | 1.5 °C | In `boosting`, `S = U - boost_offset`. |
| `cooling_offset` | 0.5 °C | In `cooling`, `S = U - cooling_offset`. |
| `coasting_offset` | 1.0 °C | In `coasting`, `S = U + coasting_offset`. |
| `fallback_boost_offset` | 2.0 °C | If `U` is invalid, `S = T - offset`. |
| `fallback_cooling_offset` | 1.0 °C | If `U` is invalid, `S = T - offset`. |
| `fallback_coasting_offset` | 1.5 °C | If `U` is invalid, `S = T + offset`. |

Require `boost_offset > cooling_offset` and
`fallback_boost_offset > fallback_cooling_offset`. Otherwise boost would have no
meaningful effect. Boost changes only the requested AC target; it never changes
fan mode, swing mode, or any Daikin-specific feature.

Entering and leaving boost are ordinary state transitions. Each can produce at
most one deduplicated command and remains subject to automatic command spacing
and budget protection. Boost must never introduce periodic writes.

### 8.1 Boost example

With the defaults, assume:

- the user target is `T = 26.5 °C`;
- the external room sensor reports `R = 28.2 °C`;
- the underlying AC sensor reports `U = 25.0 °C`.

The room error is `1.7 °C`, which is above `boost_enter_delta = 1.5 °C`.
The controller enters `boosting` and calculates
`S = 25.0 - 1.5 = 23.5 °C`, subject to the underlying entity's limits and step.

When the room reaches `T + boost_exit_delta = 27.3 °C`, it moves to ordinary
`cooling` and uses the smaller cooling offset. When the room reaches
`T + coast_enter_delta = 26.7 °C`, it moves to `coasting` to reduce overshoot.

This is why boost can help without being a separate dashboard control: it is
simply the high-error part of the automatic cooling curve. Disabling boost makes
the first stage ordinary `cooling` instead.

After calculating `S`:

1. clamp it to the intersection of the configured and underlying min/max target;
2. quantize it to the underlying entity's supported temperature step;
3. compare it with the underlying target using half a step as tolerance;
4. do not send a setpoint command if it is already equivalent.

Changing `U` alone must not cause continuous setpoint updates. Recalculate and
possibly send `S` only on:

- an internal-state transition;
- a virtual target or HVAC-mode change;
- recovery from a fault;
- a detected external override that policy says to reconcile;
- the low-frequency watchdog finding a material mismatch.

For an underlying entity that supports setting HVAC mode and temperature in a
single service call, prefer one `climate.set_temperature` call containing
`hvac_mode: cool` and `temperature: S`. Otherwise serialize the minimum number
of calls and count each service call separately.

## 9. Event-driven operation

The integration must not use `DataUpdateCoordinator`, an update loop, or polling.
Register state listeners with `async_track_state_change_event` for:

- the external temperature sensor;
- the underlying climate entity.

Also reconcile on:

- virtual climate service calls;
- options changes;
- Home Assistant startup after a configurable settle delay;
- one low-frequency watchdog timer.

Local state-change events do not themselves consume Daikin cloud quota. Only
service actions sent to the underlying climate can result in API calls.

Use `async_at_start` for startup handling. Store every unsubscribe callback and
remove it during config-entry unload.

All event sources call one serialized `async_reconcile(reason)` method guarded
by an `asyncio.Lock`. A generation counter or dirty flag must cause one final
reconciliation if a relevant event arrives during an active reconciliation.
Never allow overlapping command sequences.

### 9.1 Watchdog

The watchdog is recovery, not the primary control mechanism.

| Option | Default |
| --- | ---: |
| `watchdog_interval` | 60 min |
| `startup_settle_delay` | 30 s |

At each watchdog event, read only Home Assistant's in-memory states. Send a
command only if the desired stage/mode/setpoint materially differs from the
underlying entity and all rate controls permit it.

## 10. Sensor and underlying failures

### 10.1 External sensor

Options:

| Option | Default |
| --- | ---: |
| `sensor_stale_timeout` | 60 min |
| `resume_after_sensor_recovery` | true |

A brief invalid state starts a stale timer and suppresses new automatic cooling
commands. It does not immediately turn off the AC, because short sensor gaps can
occur during reloads.

If invalidity lasts for `sensor_stale_timeout` while cooling is requested:

- send underlying off once, bypassing the normal interval and budget;
- enter `sensor_fault`;
- retain the user's requested HVAC mode as `cool` and retain the target;
- expose the fault in diagnostics and log one warning, not one per event.

On sensor recovery:

- if `resume_after_sensor_recovery` is true, evaluate normal thresholds and
  resume only when the hysteresis rules demand cooling;
- if false, change the requested virtual HVAC mode to off and require manual
  re-enabling.

### 10.2 Underlying climate

When the underlying entity is unavailable:

- enter `underlying_fault`;
- mark the virtual climate unavailable;
- retain target and requested mode;
- issue no command and start no retry loop.

On recovery, wait for the startup settle delay, then perform one reconciliation.

### 10.3 Command errors

On a failed service call:

- record the error category and timestamp;
- do not retry immediately;
- retry only after a meaningful state/target event or a watchdog event, subject
  to an exponential backoff capped at the watchdog interval;
- clear the fault after a confirmed successful reconciliation.

## 11. Command rate and quota protection

The controller must deduplicate desired commands before applying rate limits.

Options:

| Option | Default | Meaning |
| --- | ---: | --- |
| `minimum_automatic_command_interval` | 20 min | Minimum spacing between ordinary automatic writes. |
| `target_change_debounce` | 5 s | Coalesce rapid UI changes. |
| `max_automatic_commands_24h` | 40 | Controller-side rolling write budget. |

Rules:

- Never send an identical effective mode/setpoint command.
- When ordinary control changes during the interval, retain exactly one pending
  desired command. The newest desired command replaces the older pending one.
- Schedule one callback for interval expiry; cancel obsolete callbacks.
- Manual off, `safety_off`, and stale-sensor off bypass both the interval and the
  automatic-command budget.
- Manual turn-on and target changes may bypass the interval once, but remain
  deduplicated and count toward the budget.
- Explicit user passthrough controls are serialized and logged but bypass the
  automatic interval and budget. They are not automatic cooling commands.
- After the automatic budget is exhausted, suppress ordinary commands until the
  rolling count permits them again. Keep safety and manual off operational.
- Persist timestamped logical service-call records needed for the rolling count
  across restarts.
- This budget counts only calls caused by this integration. It cannot know every
  API request made by Daikin polling, the mobile app, or other integrations; the
  option must be described as a controller cap, not as the Daikin quota.

Default 40 leaves substantial room beneath Daikin's rolling daily limit for the
underlying integration's reads and for occasional manual use.

## 12. Manual changes to the underlying AC

The virtual climate is the intended control surface, but physical remotes and the
Daikin app remain possible.

Policy:

- If the underlying AC is manually turned off while virtual mode is `cool`,
  adopt that safety-significant choice: change the virtual requested mode to
  `off` and do not restart automatically.
- If the underlying AC is turned on while virtual mode is `off`, leave it
  unmanaged. Do not immediately turn it off or adopt it as virtual `cool`.
- If its target is externally changed while virtual mode is `cool`, record drift
  but do not immediately fight the change. Reconcile at the next controller
  transition or watchdog.
- While the virtual mode is active, adopt an externally selected advertised HVAC
  mode so the virtual entity remains an accurate control surface. Non-cooling
  modes enter `passthrough`; selecting `cool` resumes external-sensor regulation
  without an immediate target fight. Preserve virtual `off` as unmanaged intent.
- Mirror external fan, swing, preset, range, and humidity changes from the
  underlying state event without sending a response command.
- Distinguish self-generated changes using a short suppression window, expected
  desired state, and command generation ID. Do not rely solely on Home
  Assistant context, which may not survive a cloud round trip.

Expose an `external_control` diagnostic state when the underlying AC is running
while the virtual climate is off. A future option may add stricter authoritative
  behavior, but it is deliberately excluded.

## 13. Configuration and options flows

### 13.1 Config flow: stable identity

Required data:

- entry name;
- one temperature-sensor entity selector;
- one climate-entity selector.

Validate that the selected sensor currently has, or declares, temperature as its
device class and that the climate entity supports cool and a target temperature.
Allow setup while an entity is temporarily unavailable if registry metadata is
sufficient, but show a warning.

### 13.2 Options flow: tuning

All behavior values belong in options, grouped as:

1. room thresholds;
2. underlying setpoint offsets;
3. timing and debounce;
4. safety and recovery;
5. command budget;
6. displayed target min/max/step.

The complete v1 option set is:

```text
boost_enabled
boost_enter_delta
boost_exit_delta
cool_enter_delta
coast_enter_delta
safety_off_delta
safety_resume_delta
boost_offset
cooling_offset
coasting_offset
fallback_boost_offset
fallback_cooling_offset
fallback_coasting_offset
temperature_debounce
target_change_debounce
minimum_automatic_command_interval
watchdog_interval
startup_settle_delay
sensor_stale_timeout
resume_after_sensor_recovery
max_automatic_commands_24h
target_temperature_min
target_temperature_max
target_temperature_step
```

An options update must cancel/reschedule affected timers and perform one
reconciliation. It must not require deleting and recreating the entry.

## 14. Proposed code structure

```text
custom_components/daikin_external_thermostat/
  __init__.py          # config-entry setup/unload and runtime_data
  manifest.json
  const.py             # domain, defaults, option keys
  config_flow.py       # config and options flows
  climate.py           # thin ClimateEntity adapter
  controller.py        # listeners, state machine, reconciliation, commands
  models.py            # dataclasses/enums and pure transition calculations
  diagnostics.py       # redacted config-entry diagnostics
  translations/
    en.json            # required for a custom integration
    it.json            # recommended for the household UI
tests/
    test_config_flow.py
    test_climate.py
    test_controller.py
    test_diagnostics.py
```

Use a typed config-entry `runtime_data` dataclass holding the controller and
entity-facing runtime values. Keep transition and setpoint calculations pure so
they can be exhaustively unit tested without Home Assistant.

The entity forwards user intent to the controller; it must not duplicate the
state machine. The controller is the only component allowed to call underlying
climate services.

## 15. Diagnostics and logging

Keep normal entity attributes small. Recommended read-only diagnostic attributes
are:

- `controller_state`;
- `desired_underlying_mode`;
- `desired_underlying_temperature`;
- `last_command_at` and `last_command_reason`;
- `automatic_command_count_24h`;
- `pending_command_at`;
- `fault_reason`;
- last valid external and underlying temperatures.

If these prove noisy, expose disabled-by-default diagnostic sensor entities
instead. Never create controls that bypass the options flow.

Provide config-entry diagnostics containing redacted options, current controller
state, transitions, pending command, and a bounded recent command history. Redact
entity IDs and user-assigned names from exported diagnostics.

Logging policy:

- debug: state transition evaluation and deduplication decision;
- info: commands actually sent and explicit manual-mode changes;
- warning: first entry into a sensor/underlying/quota fault;
- no repeated warning on every sensor event;
- never log credentials, endpoints, device IDs, or tokens.

## 16. Test contract

### 16.1 Unit tests

Cover at least:

- every state transition and exact boundary equality;
- boost disabled, boost entry, boost exit, and direct coasting-to-boost entry;
- boost threshold hysteresis and proof that it sends no periodic commands;
- hysteresis with noisy temperatures;
- a threshold that becomes false before debounce completion;
- user target changes while on and off;
- target clamping and underlying-step rounding;
- invalid `R` and invalid `U` independently;
- stale-sensor off and recovery settings;
- underlying unavailability and recovery;
- duplicate command suppression;
- rapid target updates coalesced to one desired command;
- minimum-interval pending command replacement;
- rolling 24-hour budget expiry;
- safety/manual off bypassing interval and budget;
- service-call failure and backoff;
- restart state restoration and delayed reconciliation;
- manual underlying off adoption;
- external underlying target drift;
- dynamic discovery of every advertised standard HVAC and feature capability;
- fan, vertical/horizontal swing, preset, temperature-range, and humidity
  passthrough, including validation failures;
- proof that passthrough modes ignore external-sensor safety transitions and do
  not consume the automatic command budget;
- config-entry unload cancelling every listener and timer;
- two entries remaining fully isolated.

Use mocked Home Assistant states and service calls. Unit tests must never contact
a real AC or the Daikin API.

### 16.2 Live rollout

Before enabling the new entry for Camera matrimoniale:

1. Disable the current Versatile Thermostat entry or ensure it cannot control the
   underlying AC.
2. Disable `automation.ac_matrimoniale_on` and
   `automation.ac_matrimoniale_off`.
3. Confirm no other automation writes to the same underlying climate entity.
4. Add the Daikin External Thermostat entry and select the two entities in
   section 2.
5. Begin with the defaults in this document and only one AC.
6. Turn the new virtual climate on manually and set the room target on its normal
   climate card.
7. Review climate history, controller diagnostics, automation traces, and Daikin
   rate-limit errors after each night.

Only one controller may have authority over the underlying entity at a time.
The observed case where VTherm was off while the Daikin entity was cooling is
exactly the conflict this rule prevents.

### 16.3 Initial acceptance criteria

- Standard climate cards can turn the controller on/off and set its target.
- Standard cards expose every underlying HVAC, fan, swing, preset, range, and
  humidity control the selected entity advertises.
- The displayed current temperature is the external bedroom sensor.
- No command is emitted merely because ten minutes passed.
- No duplicate effective mode/setpoint command is emitted.
- Boost produces at most one command on entry and one on exit, subject to
  deduplication and command spacing.
- Manual off results in one immediate underlying off request.
- Safety-off remains functional after the ordinary command budget is exhausted.
- Controller-generated writes remain at or below 20 in a representative
  24-hour bedroom run; 40 is the hard default cap, not the desired count.
- No Daikin rate-limit error occurs during the trial.
- The room normally remains within 0.5 °C of target after tuning, with no cold
  excursion beyond the configured safety delta.
- Restarting Home Assistant does not create a command burst.

Collect at least three nights before changing more than one option at a time.

## 17. Installation and rollback

For local testing, copy the completed `daikin_external_thermostat` directory
under Home Assistant's `custom_components/`, restart Home Assistant so the new
integration is discovered, and add it through **Settings > Devices & services**.
Do not edit `.storage` directly.

The public repository is packaged for HACS; manual copying remains available for
local development and rollback.

Rollback is intentionally simple:

1. turn the virtual climate off;
2. disable or remove its config entry;
3. re-enable the previous automation pair if temporary control is needed;
4. keep the integration directory until diagnostics and logs have been reviewed.

Do not delete the previous automations until the new controller has passed the
multi-night trial.

## 18. Dashboard recommendation

Use Home Assistant's standard Thermostat card or Tile card with climate features.
No custom dashboard card and no target-temperature helper are required. This is
the principal reason the controller must be a real `ClimateEntity` rather than
an automation plus `input_number`.

## 19. Implementation completion checklist

- Integration loads through a UI config flow and unloads cleanly.
- A real climate entity exposes all underlying standard modes and features while
  regulating only `cool` from the external sensor.
- All listed thresholds, offsets, timers, and budgets are editable options.
- Optional automatic boost has configurable enter/exit thresholds and setpoint
  offsets, but is not exposed as another HVAC mode and remains distinct from a
  native Powerful/Boost preset.
- Regulation is event-driven, with only a recovery watchdog.
- The controller sends the minimum necessary underlying service calls.
- Manual and safety off paths cannot be blocked by quota protection.
- Faults, pending commands, and rolling command count are diagnosable.
- English custom-component translations are included; Italian is included for
  the household UI.
- Tests cover the state machine, rate protection, recovery, and unload behavior.
- Only one live controller owns Camera matrimoniale during testing.

## 20. Compatibility and implementation references

The initial implementation target is Home Assistant Core 2026.7.4, the version
recorded in this configuration repository when this specification was written.
Use current APIs rather than copying older custom-component examples.

Authoritative references:

- [Climate entity developer contract](https://developers.home-assistant.io/docs/core/entity/climate/)
- [Listening for state changes](https://developers.home-assistant.io/docs/integration_listen_events/)
- [Config and options flows](https://developers.home-assistant.io/docs/core/integration/config_flow/)
- [Entity registry and unique IDs](https://developers.home-assistant.io/docs/entity_registry_index/)
- [Device registry](https://developers.home-assistant.io/docs/device_registry_index/)
- [Single-config-entry device-registry change](https://developers.home-assistant.io/blog/2026/07/21/device-registry-single-config-entry/)
- [Custom-integration translations](https://developers.home-assistant.io/docs/internationalization/custom_integration/)
- [Integration diagnostics](https://developers.home-assistant.io/docs/core/integration/diagnostics/)
- [Daikin Developer Portal and rolling call quota](https://www.daikin.eu/en_us/product-group/control-systems/daikin-developer-portal.html)
