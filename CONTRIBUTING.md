# Contributing

Thanks for helping improve Daikin External Thermostat.

1. Open an issue describing the behavior or proposed change.
2. Create a focused branch and keep the event-driven, sparse-command contract.
3. Add or update tests, especially exact threshold boundaries and safety paths.
4. Run `uv run ruff check .`, `uv run ruff format --check .`, and
   `uv run pytest` before opening a pull request.

Never test changes against a live air conditioner from the automated test
suite. Use mocked Home Assistant states and service calls.
