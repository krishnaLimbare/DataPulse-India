# DataPulse-India

An automated, multi-dataset data hub for India. One pipeline collects daily
time-series across several domains — mandi (food) prices, used cars, city rents,
tech-job demand — validates every row against a declared schema, and commits
date-partitioned parquet to this repo. Runs nightly on GitHub Actions for ₹0.

> Status: **foundation**. Core platform, CI, and one reference source are in
> place; additional sources are being added one file at a time.

## Quick start

```bash
pip install -e ".[dev]"
cp .env.example .env

datapulse list
datapulse run --source mandi_prices --dry-run
```

## System Architecture & Data Flow

```mermaid
flowchart TB
    subgraph Triggers["Execution"]
        GHA["🤖 GitHub Actions (Nightly)"]
        CLI["💻 Local CLI (datapulse run)"]
    end

    subgraph Engine["Core Engine (datapulse/core)"]
        Runner["⚡ Runner"]
        HTTP["🌐 PoliteHTTPClient"]
        SchemaVal["🛡️ SchemaValidator"]
        StorageEngine["💾 ParquetStorage"]
    end

    subgraph Sources["Modular Sources (datapulse/sources)"]
        S1["🌾 Mandi Prices"]
        S2["🏎️ Used Cars"]
        S3["💼 Tech Jobs"]
        S4["🏠 City Rents"]
    end

    subgraph Persistence["Storage Layer"]
        PQ["📂 Parquet Datasets (datasets/)"]
        Runs["📋 JSON Run Reports"]
    end

    GHA --> Runner
    CLI --> Runner
    Runner --> Sources
    Sources --> HTTP
    HTTP -->|Fetch| Web["External APIs & Sites"]
    Web -->|Raw Data| Sources
    Sources --> SchemaVal --> StorageEngine --> PQ
    Runner --> Runs
```

See [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) for full sequence diagrams, process flowcharts, class models, and data contract specifications.

## Layout

```
datapulse/
  core/          config, http, schema, storage, runner, logging  <- stable platform
  sources/       one file per dataset                            <- where growth happens
  cli.py
config/settings.yaml   non-secret config (enable/disable, tuning)
datasets/              date-partitioned parquet, committed daily
  <domain>/<source>/year=YYYY/month=MM/<source>_YYYY-MM-DD.parquet
  _runs/               JSON run reports
dashboard/             static GitHub Pages site
docs/                  architecture, adding a source, data ethics
```

## Adding a dataset

One module in `datapulse/sources/`, one block in `config/settings.yaml`. Nothing
in `core/` changes. See [docs/ADDING_A_SOURCE.md](docs/ADDING_A_SOURCE.md).

## Design notes

- **Schema-validated writes** — a broken scraper fails the run instead of
  poisoning the archive.
- **Idempotent, date-partitioned storage** — retries and backfills never duplicate rows.
- **Isolated sources** — one failure doesn't take the nightly run down; the run
  report records what happened.
- **Swappable storage** — `Storage` is a Protocol; local parquet today, S3 or
  DuckDB later without touching a source.
- **Polite by default** — shared rate limiter, backoff, identifying User-Agent,
  robots.txt honoured. See [docs/DATA_ETHICS.md](docs/DATA_ETHICS.md).
- **Secrets never in git** — env-only, gitleaks in pre-commit and CI. See [SECURITY.md](SECURITY.md).

Full rationale: [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).

## Using the data

Each day lands as one Parquet file under
`datasets/<domain>/<source>/year=YYYY/month=MM/`. To read the whole archive:

```python
import pandas as pd, glob

df = pd.concat(map(pd.read_parquet, glob.glob("datasets/**/*.parquet", recursive=True)))
df.to_csv("all_prices.csv", index=False)   # only if you need CSV
```

**Before you analyse it**, read [docs/DATA_DICTIONARY.md](docs/DATA_DICTIONARY.md) — it is
generated from the schemas, so it cannot drift from the data. The short version:

- One row is one price at one market on one day. `series_id` follows the same
  market and crop across days.
- A missing day means the market did not report. Not zero, not "unchanged".
  Do not fill those gaps; roughly half of single-market series have holes
  between any two days. Aggregate upwards if you need an unbroken line.

Rows that failed a quality check are kept, not dropped, and carry a reason in
`quality_flag`. Filter `df[df.quality_flag == ""]` for clean rows only — a
handful of markets report in rupees per kilogram rather than per quintal, and
averaging those in will skew a commodity badly.

The dashboard publishes only the latest day as CSV, deliberately: the full
archive as CSV would be roughly 126 MB at 90 days and is rebuilt on every
deploy. Parquet is about 15x smaller and every tool that matters reads it.

## Data licensing

Each dataset carries the licence of its upstream source, documented in that
source's module docstring and shown on the dashboard.
