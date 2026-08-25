# Architecture

## Why it is shaped this way

The goal is that **adding the 5th, 10th, or 20th dataset costs one file** — and
that no scraper can quietly corrupt the archive.

```
             config/settings.yaml            .env / GH secrets
                      |                             |
                      v                             v
   CLI  ->  Settings  ->  Runner  ->  [ Source ]  ->  Storage  ->  datasets/
                             |         fetch()        (Protocol)
                             |         parse()
                             |         schema.validate()
                             +-- RunReport -> datasets/_runs/*.json
```

## The layers

| Layer | Module | Rule it enforces |
|---|---|---|
| Config | `core/config.py` | Non-secret settings in YAML, secrets only from env. |
| Contract | `core/source.py` | Every dataset is `fetch` + `parse`; nothing else. |
| Validation | `core/schema.py` | Nothing is written before it type-checks. |
| Transport | `core/http.py` | Rate limits, retries, timeouts, robots.txt — in one place. |
| Persistence | `core/storage.py` | A `Protocol`; local parquet today, S3/DuckDB tomorrow. |
| Orchestration | `core/runner.py` | One source failing never kills the run. |

## Design decisions that buy future flexibility

- **`fetch` / `parse` split.** Network I/O is isolated from transformation, so
  parsing is a pure function you can unit test on a saved fixture. When a site
  changes its HTML, only `parse` moves.
- **Registry by decorator + package auto-import.** No central list of sources to
  keep in sync — dropping a module into `datapulse/sources/` is the whole wiring.
- **`Storage` as a Protocol.** Swapping backends is a config value plus one class;
  sources never learn where bytes land.
- **Additive schemas.** Adding a nullable column keeps old parquet readable.
  Renaming or narrowing a column is a breaking change: add the new column, backfill,
  then drop the old one in a later release.
- **Date-partitioned, idempotent writes.** `year=/month=/name_YYYY-MM-DD.parquet`.
  Re-running a day overwrites exactly that day, so retries and backfills are safe.
- **Run reports.** Every run writes JSON to `datasets/_runs/`, which is what the
  dashboard's health panel and any future alerting read.

## Adding a dataset

1. `datapulse/sources/city_rents.py` — subclass `BaseSource`, `@register`, declare `schema`.
2. Add a block under `sources:` in `config/settings.yaml`.
3. `datapulse run --source city_rents --dry-run` until the schema passes.
4. Flip `enabled: true`.

Contract tests in `tests/test_source_contract.py` apply to the new source automatically.

## Deliberately deferred

Kept out of v1 so it can be added without rework:
incremental/CDC loads, a DuckDB serving layer, backfill orchestration beyond
`--date`, alerting on failed runs, and dbt-style derived tables under `datasets/derived/`.
