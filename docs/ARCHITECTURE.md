# DataPulse-India: Architecture & Data Flow Specification

This document provides a comprehensive breakdown of the system architecture, process flows, data pipelines, and component relationships using Mermaid diagrams and detailed technical specifications. It is designed so that any engineer, reviewer, or third party can immediately understand how DataPulse-India operates.

---

## 1. System Context & Component Architecture

DataPulse-India is designed as an **Automated, Multi-Dataset Open-Data Platform**. The platform isolates core engine logic from domain-specific scrapers so that adding new datasets requires zero modifications to the core engine.

```mermaid
flowchart TB
    subgraph Triggers["1. Execution Triggers"]
        GHA["🤖 GitHub Actions\n(Nightly Cron @ 00:00 UTC)"]
        CLI["💻 Local CLI\n(datapulse run)"]
    end

    subgraph Configuration["2. Configuration & Secrets"]
        YAML["⚙️ config/settings.yaml\n(Non-secret settings)"]
        ENV["🔑 .env / GH Secrets\n(API Keys & Tokens)"]
    end

    subgraph CoreEngine["3. Core Engine (datapulse/core)"]
        Runner["⚡ Runner\n(Orchestrates execution & handles errors)"]
        HTTP["🌐 PoliteHTTPClient\n(Rate limiting, retries, robots.txt)"]
        SchemaVal["🛡️ SchemaValidator\n(Pre-write type & contract check)"]
        StorageEngine["💾 ParquetStorage\n(Idempotent date-partitioning)"]
        ReportGen["📝 ReportGenerator\n(Execution logs & telemetry)"]
    end

    subgraph Sources["4. Dataset Sources (datapulse/sources)"]
        direction LR
        S1["🌾 Mandi Prices\n(data.gov.in API)"]
        S2["🏎️ Used Cars\n(Price Index Scraper)"]
        S3["💼 Tech Jobs\n(Skill Demand Scraper)"]
        S4["🏠 City Rents\n(Housing Rent Index)"]
    end

    subgraph StorageLayer["5. Persistence Layer (datasets/)"]
        PQ["📂 Date-Partitioned Parquet\nyear=YYYY/month=MM/filename.parquet"]
        Runs["📋 Run Reports\ndatasets/_runs/run_ID.json"]
    end

    subgraph Presentation["6. Web Dashboard (GitHub Pages)"]
        Manifest["📄 dashboard/datasets.json"]
        UI["🌐 Live Web App\n(Interactive graphs & tables)"]
    end

    %% Trigger connections
    GHA --> Runner
    CLI --> Runner

    %% Config connections
    YAML --> Runner
    ENV --> Runner

    %% Core Engine & Sources flow
    Runner --> Sources
    Sources --> HTTP
    HTTP -->|Fetches raw data| RawData["External APIs & Websites"]
    RawData -->|Raw JSON / HTML| Sources
    Sources -->|Parsed Records| SchemaVal
    SchemaVal -->|Validated Data| StorageEngine
    StorageEngine -->|Writes Parquet| PQ
    Runner -->|Writes Log| ReportGen
    ReportGen -->|Save Report| Runs

    %% Presentation connections
    PQ --> Manifest
    Runs --> Manifest
    Manifest --> UI
```

---

## 2. End-to-End Data Pipeline Flow

The following sequence diagram details the step-by-step lifecycle of a data collection job—from trigger initiation to dashboard updates.

```mermaid
sequenceDiagram
    autonumber
    actor Trigger as Execution Trigger (GHA / CLI)
    participant Runner as Core Runner (runner.py)
    participant Config as Config System (config.py)
    participant Source as Dataset Source (BaseSource)
    participant HTTP as HTTP Client (http.py)
    participant Web as External Web / API
    participant Schema as Schema Validator (schema.py)
    participant Storage as Parquet Storage (storage.py)
    participant Report as Run Report (runner.py)

    Trigger->>Runner: Initiate run (e.g. datapulse run --source mandi_prices)
    Runner->>Config: Load settings & env secrets
    Config-->>Runner: Return active configuration
    Runner->>Source: Instantiate registered source module
    
    Runner->>Source: Call fetch()
    Source->>HTTP: Send GET request with polite rate limiting
    HTTP->>Web: Request endpoint (with custom User-Agent)
    Web-->>HTTP: 200 OK (Raw HTML / JSON response)
    HTTP-->>Source: Return response payload
    
    Runner->>Source: Call parse(raw_payload)
    Source-->>Runner: Return list of standardized Python dictionaries

    Runner->>Schema: Validate raw dictionaries against declared schema
    alt Validation Fails
        Schema-->>Runner: Raise ValidationError
        Runner->>Report: Record failed status & exception details
    else Validation Passes
        Schema-->>Runner: Return validated record batch
        Runner->>Storage: Call save(validated_batch, source_metadata)
        Storage->>Storage: Compute date partition (year=YYYY/month=MM/)
        Storage->>Storage: Write/Overwrite parquet file atomically
        Storage-->>Runner: Confirm file write success
        Runner->>Report: Record success metrics (row_count, duration, path)
    end

    Report->>Report: Save run metadata to datasets/_runs/<timestamp>.json
    Runner-->>Trigger: Return exit code 0 (Success) or 1 (Partial Failure)
```

---

## 3. Detailed Process Flowchart

This flowchart outlines the decision logic, error handling, and guardrails enforced during data collection:

```mermaid
flowchart TD
    Start([🚀 Run Triggered]) --> LoadConfig[Load settings.yaml & Environment Variables]
    LoadConfig --> DiscoverSources[Auto-discover & register sources in datapulse/sources/]
    DiscoverSources --> LoopSources{For each requested source...}

    LoopSources --> CheckEnabled{Is source enabled?}
    CheckEnabled -- No --> Skip[Skip & log disabled state] --> NextSource
    CheckEnabled -- Yes --> FetchData[Call source.fetch via PoliteHTTPClient]

    FetchData --> FetchSuccess{HTTP 200 & Valid Payload?}
    FetchSuccess -- No (5xx/Timeout) --> Retry[Retry with Exponential Backoff]
    Retry --> RetryCheck{Max retries reached?}
    RetryCheck -- Yes --> LogError[Mark source as FAILED in RunReport] --> NextSource
    RetryCheck -- No --> FetchData

    FetchSuccess -- Yes --> ParseData[Call source.parse to extract raw records]
    ParseData --> ValidateSchema[Validate each record against declared Schema]

    ValidateSchema --> SchemaPass{All records pass schema check?}
    SchemaPass -- No --> FailSchema[Abort write for this source & Log Schema Error] --> NextSource
    SchemaPass -- Yes --> PartitionPath[Compute target path: datasets/domain/source/year=Y/month=M/]
    
    PartitionPath --> WriteParquet[Atomic Write: source_YYYY-MM-DD.parquet]
    WriteParquet --> LogSuccess[Record status SUCCESS + row count + file size] --> NextSource

    NextSource --> MoreSources{More sources to process?}
    MoreSources -- Yes --> LoopSources
    MoreSources -- No --> GenerateReport[Generate summary JSON in datasets/_runs/]

    GenerateReport --> UpdateManifest[Update dashboard/datasets.json manifest]
    UpdateManifest --> Finish([🏁 Run Completed cleanly])
```

---

## 4. Class & Data Contract Model

The object model is built around strict interfaces and data contracts:

```mermaid
classDiagram
    class BaseSource {
        +str name
        +str domain
        +str schedule
        +Schema schema
        +fetch(http_client) RawData
        +parse(raw_data) List[Dict]
    }

    class Schema {
        +List[Column] columns
        +validate(record: Dict) Dict
    }

    class Column {
        +str name
        +Type data_type
        +bool required
        +bool nullable
    }

    class PoliteHTTPClient {
        +float rate_limit_delay
        +int max_retries
        +get(url, headers, params) Response
    }

    class ParquetStorage {
        +str base_dir
        +save(source_name, domain, date, records) Path
    }

    class RunReport {
        +str run_id
        +datetime timestamp
        +int duration_ms
        +List[SourceResult] results
        +to_json() str
    }

    BaseSource "1" -- "1" Schema : defines
    Schema "1" *-- "many" Column : contains
    BaseSource ..> PoliteHTTPClient : uses for I/O
    ParquetStorage ..> BaseSource : consumes data from
    RunReport *-- "many" BaseSource : logs outcome of
```

---

## 5. Architectural Guarantees & Principles

| Layer | Module | Enforced Rule / Contract |
|---|---|---|
| **Configuration** | `datapulse/core/config.py` | Non-secrets in YAML, secrets **only** via environment variables/GitHub Secrets. |
| **Data Contract** | `datapulse/core/source.py` | Every dataset is strictly `fetch()` (network) + `parse()` (transformation). |
| **Schema Guard** | `datapulse/core/schema.py` | Zero writes permitted unless incoming records pass declared data type checks. |
| **Network Discipline** | `datapulse/core/http.py` | Built-in rate limiter, exponential backoff retries, user-agent headers, and robots.txt compliance. |
| **Storage Engine** | `datapulse/core/storage.py` | Idempotent date-partitioned Parquet storage (`year=YYYY/month=MM/`). Re-runs overwrite cleanly without duplication. |
| **Fault Isolation** | `datapulse/core/runner.py` | A single source failure (e.g. site structure change) never halts other sources. Run results are logged to JSON. |

---

## 6. How a 3rd Party Developer / Recruiter Understands This Project

When explaining this project to a colleague, tech lead, or recruiter:
1. **It's a Data Engine, not just scrapers**: The core engine manages retries, schemas, and parquet storage automatically.
2. **Adding a dataset takes 5 minutes**: Create `datapulse/sources/my_dataset.py`, inherit `BaseSource`, define columns, and add 4 lines to `config/settings.yaml`.
3. **Zero Maintenance Infra**: Runs nightly on GitHub Actions without needing an EC2 instance, database server, or monthly cloud bill.
4. **Clean Web UI**: The static HTML/JS dashboard reads parquet metadata via `datasets.json` to showcase interactive charts.
