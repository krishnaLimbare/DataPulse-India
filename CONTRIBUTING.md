# Contributing

```bash
python -m venv .venv && . .venv/Scripts/activate   # Windows; use bin/activate on Unix
pip install -e ".[dev]"
pre-commit install
cp .env.example .env
```

Common commands:

```bash
datapulse list                                # what's registered and enabled
datapulse run --source mandi_prices --dry-run # collect + validate, write nothing
datapulse run --domain cars --date 2026-08-01 # backfill one day
datapulse validate                            # config <-> registry consistency
pytest && ruff check .
```

Before opening a PR: tests pass, `ruff check .` is clean, no secrets added, and a
new source has a `parse` unit test against a saved fixture (not the live site).

See [docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md) and
[docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
