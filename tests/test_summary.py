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
