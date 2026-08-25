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
from .source import registry
from .storage import build_storage

log = get_logger(__name__)

TOP_N = 12
PREVIEW_ROWS = 50


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


def build_summary(settings: Settings) -> dict[str, Any]:
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
            "preview": [],
            "preview_note": "",
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
            if (dim := spec.get("dimension")) and (met := spec.get("metric")):
                entry["chart"] = _series(latest, dim, met)
            entry["stats"] = _stats(latest, spec)
            entry["preview"] = _preview(latest, spec)
            if entry["preview"]:
                entry["preview_note"] = (
                    f"Showing {len(entry['preview'])} of {len(latest):,} rows "
                    f"collected on {entry['last_collected']}."
                )

        datasets.append(entry)

    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "datasets": datasets,
    }


def write_summary(settings: Settings, path: Path) -> Path:
    import json

    summary = build_summary(settings)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(summary, indent=2), encoding="utf-8")
    live = [d["id"] for d in summary["datasets"] if d["rows"]]
    log.info("summary written to %s (%d datasets with data: %s)", path, len(live), live or "none")
    return path
