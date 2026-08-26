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
                    }
                },
            )
        },
    )


def test_summary_reports_zero_rows_when_nothing_collected(tmp_path):
    out = build_summary(_settings(tmp_path))
    entry = out["datasets"][0]
    assert entry["rows"] == 0
    assert entry["chart"] == {"labels": [], "values": []}
    assert entry["headline_note"] == ""


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


def _table_settings(tmp_path):
    settings = _settings(tmp_path)
    settings.sources["mandi_prices"].options["summary"]["table"] = {
        "dimension": "commodity",
        "facet": "state",
        "metric": "modal_price",
        "count": "market",
    }
    return settings


def _write(settings, df):
    ParquetLocalStorage(settings.storage).write(
        "food_mandi", "mandi_prices", df, date(2026, 8, 25)
    )


def test_table_gives_an_all_india_row_and_a_row_per_state(tmp_path):
    df = pd.DataFrame(
        {
            "collected_date": [pd.Timestamp("2026-08-25")] * 4,
            "state": ["MH", "MH", "PB", "PB"],
            "market": ["Pune", "Nashik", "Patti", "Ludhiana"],
            "commodity": ["Onion"] * 4,
            "modal_price": [1000.0, 2000.0, 3000.0, 5000.0],
        }
    )
    settings = _table_settings(tmp_path)
    _write(settings, df)
    table = build_summary(settings)["datasets"][0]["table"]

    assert table["facets"] == ["MH", "PB"]

    india = table["overall"][0]
    assert india["low"] == 1000 and india["high"] == 5000
    assert india["typical"] == 2500  # median of all four rows
    assert india["places"] == 4
    assert india["spread"] == 5.0

    mh = next(r for r in table["faceted"] if r["state"] == "MH")
    assert mh["low"] == 1000 and mh["high"] == 2000 and mh["places"] == 2


def test_all_india_typical_is_not_a_median_of_medians(tmp_path):
    """Two rows in one state, one in another: the true median is the middle row."""
    df = pd.DataFrame(
        {
            "collected_date": [pd.Timestamp("2026-08-25")] * 3,
            "state": ["MH", "MH", "PB"],
            "market": ["a", "b", "c"],
            "commodity": ["Onion"] * 3,
            "modal_price": [100.0, 200.0, 900.0],
        }
    )
    settings = _table_settings(tmp_path)
    _write(settings, df)
    india = build_summary(settings)["datasets"][0]["table"]["overall"][0]

    assert india["typical"] == 200  # median of 100/200/900
    # a median of state medians would give (150 + 900) / 2 = 525
    assert india["typical"] != 525


def test_table_is_absent_when_not_configured(tmp_path):
    settings = _settings(tmp_path)
    _write(settings, pd.DataFrame({
        "collected_date": [pd.Timestamp("2026-08-25")],
        "state": ["MH"], "market": ["Pune"], "commodity": ["Onion"], "modal_price": [100.0],
    }))
    table = build_summary(settings)["datasets"][0]["table"]
    assert table["overall"] == [] and table["facets"] == []


def test_headline_count_is_the_latest_day_not_the_whole_archive(tmp_path):
    """Everything on the page describes the latest day, so the headline must too."""
    settings = _table_settings(tmp_path)
    storage = ParquetLocalStorage(settings.storage)
    base = {"state": ["MH"], "market": ["Pune"], "commodity": ["Onion"], "modal_price": [100.0]}

    storage.write(
        "food_mandi",
        "mandi_prices",
        pd.DataFrame({**base, "collected_date": [pd.Timestamp("2026-08-25")]}),
        date(2026, 8, 25),
    )
    storage.write(
        "food_mandi",
        "mandi_prices",
        pd.DataFrame(
            {
                "state": ["MH", "PB"],
                "market": ["Pune", "Patti"],
                "commodity": ["Onion", "Onion"],
                "modal_price": [110.0, 120.0],
                "collected_date": [pd.Timestamp("2026-08-26")] * 2,
            }
        ),
        date(2026, 8, 26),
    )

    export = tmp_path / "out"
    entry = build_summary(settings, export_dir=export)["datasets"][0]

    assert entry["rows"] == 3, "archive total spans both days"
    assert entry["rows_latest"] == 2, "headline is the latest day"
    assert entry["download_rows"] == entry["rows_latest"], "download must match the headline"
    assert entry["first_collected"] == "2026-08-25"
    assert entry["last_collected"] == "2026-08-26"
