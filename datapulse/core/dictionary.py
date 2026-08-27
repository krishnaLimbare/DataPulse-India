"""Generates the data dictionary from the schemas themselves.

A dictionary maintained by hand in a separate file goes stale the first time a
column changes and nobody remembers to update it. These are built from the
`Schema` objects at publish time, so the documentation cannot disagree with the
data it describes.

Two outputs:
  docs/DATA_DICTIONARY.md      for people
  dashboard/data/schema.json   for tools, published beside the data
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .config import Settings
from .logging import get_logger
from .source import registry

log = get_logger(__name__)

# Written once here rather than repeated per source: these hold for every
# dataset this project publishes.
USAGE_NOTES = [
    "One row is a single observation, not a summary. Stacking the daily files "
    "gives you one long table, which is the shape most tools expect.",
    "A missing day means the source did not report that day. It does not mean "
    "zero, and it does not mean the value was unchanged.",
    "Do not fill those gaps by carrying values forward or averaging neighbours. "
    "That invents numbers nobody published, and once written they cannot be told "
    "apart from real ones.",
    "If you need a continuous series, aggregate upwards instead. Grouping by "
    "state, or nationally, has far fewer gaps than a single market does.",
    "Use series_id to follow one thing across days. It is derived from the "
    "identifying columns, so it is the same code in every run.",
    "Rows that failed a quality check are kept, not deleted, with the reason in "
    "quality_flag. Filter to an empty quality_flag for clean rows only.",
]


def _source_entry(cls: Any) -> dict[str, Any]:
    return {
        "source": cls.name,
        "domain": cls.domain,
        "grain": (
            "one row per "
            + " + ".join(cls.identity_columns)
            + f" per {cls.partition_column or 'collection date'}"
            if cls.identity_columns
            else "one row per observation"
        ),
        "series_columns": list(cls.series_columns),
        "partition_column": cls.partition_column,
        "primary_key": list(cls.schema.primary_key),
        "columns": [
            {
                "name": c.name,
                "type": c.dtype,
                "nullable": c.nullable,
                "unit": c.unit or None,
                "description": c.description or None,
                "empty_means": c.empty_means or None,
            }
            for c in cls.schema.columns
        ],
    }


def build_dictionary(settings: Settings) -> dict[str, Any]:
    sources = [
        _source_entry(cls)
        for name, cls in sorted(registry().items())
        if name in settings.sources
    ]
    return {
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "usage_notes": USAGE_NOTES,
        "datasets": sources,
    }


def _markdown(doc: dict[str, Any]) -> str:
    lines = [
        "# Data dictionary",
        "",
        "Generated from the schemas in `datapulse/sources/`. Do not edit by hand —",
        "run `datapulse dictionary` instead.",
        "",
        "## How to use this data",
        "",
    ]
    lines += [f"- {note}" for note in doc["usage_notes"]]

    for ds in doc["datasets"]:
        lines += [
            "",
            f"## `{ds['source']}`",
            "",
            f"- **Domain:** {ds['domain']}",
            f"- **Grain:** {ds['grain']}",
            f"- **One series is:** {' + '.join(ds['series_columns']) or 'n/a'}",
            f"- **Files are named after:** `{ds['partition_column'] or 'the collection date'}`",
            "",
            "| Column | Type | Unit | Empty means | Description |",
            "|---|---|---|---|---|",
        ]
        for c in ds["columns"]:
            lines.append(
                f"| `{c['name']}` | {c['type']} | {c['unit'] or '—'} | "
                f"{c['empty_means'] or ('not reported' if c['nullable'] else 'never empty')} | "
                f"{c['description'] or '—'} |"
            )
    return "\n".join(lines) + "\n"


def write_dictionary(settings: Settings, md_path: Path, json_path: Path) -> None:
    doc = build_dictionary(settings)
    md_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.parent.mkdir(parents=True, exist_ok=True)
    md_path.write_text(_markdown(doc), encoding="utf-8")
    json_path.write_text(json.dumps(doc, indent=2), encoding="utf-8")
    log.info("dictionary written to %s and %s", md_path, json_path)
