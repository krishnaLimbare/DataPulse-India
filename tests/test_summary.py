from datetime import date

import pandas as pd

from datapulse.core.config import Settings, SourceConfig, StorageConfig
from datapulse.core.storage import ParquetLocalStorage
from datapulse.core.summary import build_summary


def _settings(tmp_path):
    return Settings(
        storage=StorageConfig(root=tmp_path),
        sources={
            "mandi_prices": SourceConfig(
                domain="food_mandi",
                options={
                    "summary": {
                        "label": "Food & Mandi Prices",
                        "dimension": "commodity",
                        "metric": "modal_price",
                        "distinct_counts": ["state", "market"],
                        "top_by_count": "commodity",
                        "preview_columns": ["state", "commodity", "modal_price"],
                    }
                },
            )
        },
    )


def test_summary_reports_zero_rows_when_nothing_collected(tmp_path):
    out = build_summary(_settings(tmp_path))
    entry = out["datasets"][0]
    assert entry["rows"] == 0
    assert entry["preview"] == []
    assert entry["chart"] == {"labels": [], "values": []}


def test_summary_aggregates_real_values(tmp_path):
    df = pd.DataFrame(
        {
            "collected_date": [pd.Timestamp("2026-08-25")] * 3,
            "state": ["MH", "MH", "TN"],
            "market": ["Pune", "Nashik", "Karur"],
            "commodity": ["Tomato", "Tomato", "Mango"],
            "modal_price": [100.0, 200.0, 5000.0],
        }
    )
    settings = _settings(tmp_path)
    ParquetLocalStorage(settings.storage).write(
        "food_mandi", "mandi_prices", df, date(2026, 8, 25)
    )

    entry = build_summary(settings)["datasets"][0]
    assert entry["rows"] == 3
    assert entry["days"] == 1
    assert entry["last_collected"] == "2026-08-25"
    # Mango averages higher than Tomato, so it sorts first.
    assert entry["chart"]["labels"] == ["Mango", "Tomato"]
    assert entry["chart"]["values"] == [5000.0, 150.0]
    assert entry["stats"]["distinct"] == {"state": 2, "market": 3}
    assert entry["stats"]["top_by_count"] == {"value": "Tomato", "reports": 2}
    assert len(entry["preview"]) == 3


def test_csv_export_includes_flagged_rows_with_their_flag(tmp_path):
    """Export everything and let people filter -- hiding rows hides the evidence."""
    df = pd.DataFrame(
        {
            "collected_date": [pd.Timestamp("2026-08-25")] * 2,
            "state": ["MH", "PB"],
            "market": ["Pune", "Patti"],
            "commodity": ["Potato", "Potato"],
            "modal_price": [2000.0, 0.20],
            "quality_flag": ["", "unit_or_outlier"],
        }
    )
    settings = _settings(tmp_path)
    ParquetLocalStorage(settings.storage).write(
        "food_mandi", "mandi_prices", df, date(2026, 8, 25)
    )

    export = tmp_path / "out"
    entry = build_summary(settings, export_dir=export)["datasets"][0]

    assert entry["download"] == "mandi_prices_latest.csv"
    assert entry["download_rows"] == 2
    exported = pd.read_csv(export / entry["download"])
    assert len(exported) == 2, "flagged rows belong in the export"
    assert "quality_flag" in exported.columns

    # ...but the averages shown on the page use clean rows only.
    assert entry["chart"]["values"] == [2000.0]
    assert entry["flagged_rows"] == 1


def test_provenance_is_passed_through_from_config(tmp_path):
    settings = _settings(tmp_path)
    settings.sources["mandi_prices"].options["provenance"] = {
        "source_name": "data.gov.in",
        "license": "GODL",
    }
    entry = build_summary(settings)["datasets"][0]
    assert entry["provenance"]["source_name"] == "data.gov.in"


def test_no_export_dir_means_no_download_offered(tmp_path):
    entry = build_summary(_settings(tmp_path))["datasets"][0]
    assert entry["download"] is None
