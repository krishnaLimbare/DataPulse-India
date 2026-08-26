"""Builds the small JSON file the dashboard reads.

Browsers cannot read parquet, and shipping the full archive to a static page
would be absurd anyway. So the pipeline pre-aggregates: a few KB of JSON that
the dashboard renders directly.

What gets charted is declared per source in `config/settings.yaml`, so adding a
dataset never means editing this module or the dashboard:

    options:
      summary:
        label: "Food & Mandi Prices"
        dimension: commodity      # x axis: what we group by
        metric: modal_price       # y axis: what we average
        distinct_counts: [state, market]   # KPI tiles
        top_by_count: commodity            # most frequently reported value
        preview_columns: [state, market, commodity, modal_price]
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd

from .config import Settings
from .logging import get_logger
from .quality import CLEAN
from .source import registry
from .storage import build_storage

log = get_logger(__name__)

TOP_N = 12
PREVIEW_ROWS = 50

# Parquet is 15x smaller but unopenable for most visitors -- Excel and Sheets
# cannot read it. The archive stays parquet; the dashboard also publishes the
# latest day as CSV so anyone can actually use it.
CSV_NAME = "{source}_latest.csv"


def _series(df: pd.DataFrame, dimension: str, metric: str) -> dict[str, list]:
    """Average `metric` per `dimension`, biggest first, capped at TOP_N."""
    if dimension not in df.columns or metric not in df.columns:
        return {"labels": [], "values": []}
    grouped = (
        df.groupby(dimension, dropna=True)[metric].mean().dropna().sort_values(ascending=False)
    )
    grouped = grouped.head(TOP_N)
    return {
        "labels": [str(i) for i in grouped.index],
        "values": [round(float(v), 2) for v in grouped.to_numpy()],
    }


def _aggregate(df: pd.DataFrame, keys: list[str], metric: str, count: str) -> list[dict[str, Any]]:
    """Cheapest / typical / priciest per group, with a spread multiple.

    `spread` is what makes the table worth reading: a crop selling at 5x the
    price in one state versus another is a real signal about supply, transport
    or a local glut.
    """
    values = pd.to_numeric(df[metric], errors="coerce")
    frame = df.assign(**{metric: values}).dropna(subset=[metric])
    if frame.empty:
        return []

    agg: dict[str, Any] = {
        "low": (metric, "min"),
        "typical": (metric, "median"),
        "high": (metric, "max"),
    }
    if count in frame.columns:
        agg["places"] = (count, "nunique")

    grouped = frame.groupby(keys, dropna=True).agg(**agg).reset_index()
    grouped["spread"] = (grouped["high"] / grouped["low"].where(grouped["low"] > 0)).round(1)

    records = []
    for row in grouped.to_dict(orient="records"):
        clean = {}
        for k, v in row.items():
            if isinstance(v, (int, float)) and not isinstance(v, bool):
                clean[k] = None if pd.isna(v) else round(float(v), 2)
            else:
                clean[k] = None if pd.isna(v) else str(v)
        records.append(clean)
    return sorted(records, key=lambda r: r.get(keys[0]) or "")


def _build_table(df: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    """Two views of the same data: all-India, and broken down per facet.

    Both are computed here rather than folded together in the browser, because
    a median of medians is not a median -- the all-India typical price has to
    come from the underlying rows.
    """
    table = spec.get("table") or {}
    dimension, metric = table.get("dimension"), table.get("metric")
    if not dimension or not metric or dimension not in df.columns:
        return {"dimension": "", "facet": "", "overall": [], "faceted": [], "facets": []}

    facet = table.get("facet")
    count = table.get("count", "")
    faceted = (
        _aggregate(df, [dimension, facet], metric, count)
        if facet and facet in df.columns
        else []
    )
    return {
        "dimension": dimension,
        "facet": facet or "",
        "overall": _aggregate(df, [dimension], metric, count),
        "faceted": faceted,
        "facets": sorted({r[facet] for r in faceted if r.get(facet)}) if faceted else [],
    }


def _stats(df: pd.DataFrame, spec: dict[str, Any]) -> dict[str, Any]:
    """KPI values, computed from the data — never hardcoded in the page."""
    out: dict[str, Any] = {"distinct": {}}
    for column in spec.get("distinct_counts", []):
        if column in df.columns:
            out["distinct"][column] = int(df[column].nunique(dropna=True))
    if (column := spec.get("top_by_count")) and column in df.columns:
        counts = df[column].value_counts()
        if not counts.empty:
            out["top_by_count"] = {"value": str(counts.index[0]), "reports": int(counts.iloc[0])}
    return out


def _preview(df: pd.DataFrame, spec: dict[str, Any]) -> list[dict[str, Any]]:
    """A small, explicitly-labelled sample so the page can show real rows."""
    columns = [c for c in spec.get("preview_columns", []) if c in df.columns]
    if not columns:
        return []
    sample = df.loc[:, columns].head(PREVIEW_ROWS)
    return [
        {k: (None if pd.isna(v) else (float(v) if isinstance(v, (int, float)) else str(v)))
         for k, v in row.items()}
        for row in sample.to_dict(orient="records")
    ]


def build_summary(settings: Settings, export_dir: Path | None = None) -> dict[str, Any]:
    """Aggregate the archive. With `export_dir`, also write the latest day as CSV."""
    storage = build_storage(settings.storage)
    datasets: list[dict[str, Any]] = []

    for name, cls in sorted(registry().items()):
        cfg = settings.sources.get(name)
        if cfg is None:
            continue
        spec = cfg.options.get("summary", {})
        entry: dict[str, Any] = {
            "id": name,
            "domain": cls.domain,
            "label": spec.get("label", name.replace("_", " ").title()),
            "enabled": cfg.enabled,
            "rows": 0,
            "days": 0,
            "last_collected": None,
            "chart": {"labels": [], "values": []},
            "chart_title": spec.get("chart_title", ""),
            "stats": {"distinct": {}},
            "flagged_rows": 0,
            "preview": [],
            "table": {"dimension": "", "facet": "", "overall": [], "faceted": [], "facets": []},
            "preview_note": "",
            "provenance": cfg.options.get("provenance", {}),
            "download": None,
            "download_rows": 0,
        }

        df = storage.read_all(cls.domain, name)
        if not df.empty:
            entry["rows"] = len(df)
            if "collected_date" in df.columns:
                dates = pd.to_datetime(df["collected_date"], errors="coerce").dropna()
                entry["days"] = int(dates.dt.date.nunique())
                if not dates.empty:
                    entry["last_collected"] = str(dates.max().date())
                    latest = df[dates == dates.max()]
                else:
                    latest = df
            else:
                latest = df
            # Averages and previews use clean rows only -- a single
            # mis-keyed unit is enough to drag a commodity average visibly
            # off. The flagged rows stay in the parquet either way.
            if "quality_flag" in latest.columns:
                flagged = latest["quality_flag"].fillna(CLEAN) != CLEAN
                entry["flagged_rows"] = int(flagged.sum())
                clean = latest[~flagged]
            else:
                clean = latest

            if (dim := spec.get("dimension")) and (met := spec.get("metric")):
                entry["chart"] = _series(clean, dim, met)
            entry["stats"] = _stats(clean, spec)
            entry["table"] = _build_table(clean, spec)
            entry["preview"] = _preview(clean, spec)
            if export_dir is not None:
                # Every row is exported, flagged ones included, so nothing is
                # hidden -- the flag column lets people filter for themselves.
                export_dir.mkdir(parents=True, exist_ok=True)
                csv_path = export_dir / CSV_NAME.format(source=name)
                latest.to_csv(csv_path, index=False)
                entry["download"] = csv_path.name
                entry["download_rows"] = len(latest)
                log.info("wrote %s (%d rows)", csv_path, len(latest))

            if entry["preview"]:
                note = (
                    f"Showing {len(entry['preview'])} of {len(latest):,} prices "
                    f"collected on {entry['last_collected']}."
                )
                if entry["flagged_rows"]:
                    note += (
                        f" {entry['flagged_rows']} row(s) failed a quality check and are "
                        "excluded from the averages below."
                    )
                entry["preview_note"] = note

        datasets.append(entry)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "datasets": datasets,
    }


def write_summary(settings: Settings, path: Path) -> Path:
    import json

    summary = build_summary(settings, export_dir=path.parent)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    live = [d["id"] for d in summary["datasets"] if d["rows"]]
    log.info("summary written to %s (%d datasets with data: %s)", path, len(live), live or "none")
    return path
