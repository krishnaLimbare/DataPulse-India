"""Pipeline orchestration.

One source failing must never take the run down: each is isolated, and the
run report records outcomes so CI can decide what counts as a failure.
"""

from __future__ import annotations

import json
import time
from datetime import UTC, date, datetime
from pathlib import Path

import pandas as pd
from pydantic import BaseModel

from .config import Settings
from .http import HttpClient
from .logging import get_logger, scrub
from .source import BaseSource, RunContext, registry
from .storage import build_storage

log = get_logger(__name__)


class SourceResult(BaseModel):
    name: str
    domain: str
    status: str  # ok | partial | skipped | failed
    rows: int = 0
    warnings: list[str] = []
    days_written: list[str] = []
    path: str | None = None
    duration_seconds: float = 0.0
    error: str | None = None


class RunReport(BaseModel):
    run_date: date
    started_at: datetime
    finished_at: datetime
    dry_run: bool
    results: list[SourceResult]

    @property
    def failed(self) -> list[SourceResult]:
        return [r for r in self.results if r.status == "failed"]

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(self.model_dump_json(indent=2), encoding="utf-8")


def _relative(path: str) -> str:
    """Report repo-relative paths: absolute ones leak the local username."""
    try:
        return Path(path).relative_to(Path(__file__).resolve().parents[2]).as_posix()
    except ValueError:
        return Path(path).name


def _write_dataset(source: BaseSource, storage, df, run_date: date) -> tuple[list[str], list[str]]:
    """Write the frame, keyed on the day the data describes.

    Without `partition_column` this behaves as before: one file named for the
    run date. With it, rows are filed under their own event date, so a run
    delayed past UTC midnight -- GitHub schedules drift by hours -- still lands
    in the right day instead of creating a mislabelled file and a gap.

    An existing day is merged, not replaced: a later run that carries a few
    late-reported rows for an earlier day must not shrink that day to just
    those rows.
    """
    column = source.partition_column
    if not column or column not in df.columns:
        return [_relative(storage.write(source.domain, source.name, df, run_date))], [
            run_date.isoformat()
        ]

    days = pd.to_datetime(df[column], errors="coerce")
    undated = int(days.isna().sum())
    if undated:
        source.warn(f"{undated} rows have no {column}; filed under the run date")
        days = days.fillna(pd.Timestamp(run_date))

    paths, written = [], []
    for day, part in df.groupby(days.dt.date, sort=True):
        existing = storage.read_day(source.domain, source.name, day)
        if not existing.empty and source.identity_columns:
            before = len(existing)
            part = pd.concat([existing, part], ignore_index=True).drop_duplicates(
                subset=list(source.identity_columns), keep="last"
            )
            log.info("merged %d new rows into %d existing for %s", len(part) - before, before, day)
        paths.append(_relative(storage.write(source.domain, source.name, part, day)))
        written.append(day.isoformat())
    return paths, written


def _run_one(source: BaseSource, settings: Settings, run_date: date, storage) -> SourceResult:
    started = time.monotonic()
    cfg = source.config
    try:
        with HttpClient(
            settings.user_agent,
            rate_limit_per_sec=cfg.rate_limit_per_sec,
            timeout=cfg.timeout_seconds,
            max_retries=cfg.max_retries,
            respect_robots=settings.respect_robots_txt,
        ) as http:
            ctx = RunContext(
                run_date,
                cfg,
                http,
                dry_run=settings.dry_run,
                secrets={k: v.get_secret_value() for k, v in settings.api_keys.items()},
            )
            df = source.collect(ctx)

        path, days = None, []
        if settings.dry_run:
            log.info("[dry-run] %s produced %d rows; not written", source.name, len(df))
        else:
            paths, days = _write_dataset(source, storage, df, run_date)
            path = paths[-1] if paths else None
        return SourceResult(
            name=source.name,
            domain=source.domain,
            status="partial" if source.warnings else "ok",
            warnings=[scrub(w) for w in source.warnings],
            rows=len(df),
            days_written=days,
            path=path,
            duration_seconds=round(time.monotonic() - started, 2),
        )
    except Exception as exc:  # isolate: one bad source must not kill the run
        log.exception("source %s failed", source.name)
        return SourceResult(
            name=source.name,
            domain=source.domain,
            status="failed",
            duration_seconds=round(time.monotonic() - started, 2),
            # Never let a credential-bearing URL reach the committed run report.
            error=scrub(f"{type(exc).__name__}: {exc}")[:500],
        )


def run(
    settings: Settings,
    *,
    run_date: date | None = None,
    only: list[str] | None = None,
    domains: list[str] | None = None,
) -> RunReport:
    run_date = run_date or datetime.now(UTC).date()
    started_at = datetime.now(UTC)
    storage = build_storage(settings.storage)
    results: list[SourceResult] = []

    for name, cls in sorted(registry().items()):
        cfg = settings.sources.get(name)
        if cfg is None:
            log.warning("source %r has no config block; skipping", name)
            continue
        selected = (only is None or name in only) and (domains is None or cls.domain in domains)
        if not selected:
            continue
        if not cfg.enabled:
            results.append(SourceResult(name=name, domain=cls.domain, status="skipped"))
            continue
        results.append(_run_one(cls(cfg), settings, run_date, storage))

    report = RunReport(
        run_date=run_date,
        started_at=started_at,
        finished_at=datetime.now(UTC),
        dry_run=settings.dry_run,
        results=results,
    )
    log.info("run summary: %s", json.dumps({r.name: r.status for r in results}))
    return report
