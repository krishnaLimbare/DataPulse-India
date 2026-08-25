"""Parse tests for the reference source — fixtures only, never the live API."""

from datetime import date

import pandas as pd

from datapulse.core.config import SourceConfig
from datapulse.core.source import RunContext
from datapulse.sources.mandi_prices import MandiPrices

CFG = SourceConfig(domain="food_mandi")
CTX = RunContext(date(2026, 8, 25), CFG, http=None)

LOWER = [
    {
        "state": "Maharashtra",
        "district": "Pune",
        "market": "Pune",
        "commodity": "Tomato",
        "variety": "Local",
        "arrival_date": "25/08/2026",
        "min_price": "1200",
        "max_price": "1800",
        "modal_price": "1500",
    }
]
TITLE = [{k.title(): v for k, v in LOWER[0].items()}]


def _collect(payload):
    """Drive the real collect() path with fetch stubbed out — no network."""
    source = MandiPrices(CFG)
    source.fetch = lambda ctx: payload  # type: ignore[method-assign]
    return source.collect(CTX)


def test_parses_lowercase_keys():
    out = _collect(LOWER)
    assert out.loc[0, "collected_date"] == pd.Timestamp("2026-08-25")
    assert out.loc[0, "source"] == "mandi_prices"
    assert out.loc[0, "commodity"] == "Tomato"
    assert out.loc[0, "modal_price"] == 1500.0


def test_parses_title_case_keys_identically():
    pd.testing.assert_frame_equal(_collect(LOWER), _collect(TITLE))


def test_non_numeric_prices_become_null_not_errors():
    payload = [{**LOWER[0], "min_price": "NA", "max_price": ""}]
    out = _collect(payload)
    assert pd.isna(out.loc[0, "min_price"]) and pd.isna(out.loc[0, "max_price"])


def test_empty_response_yields_empty_frame_with_schema():
    out = _collect([])
    assert out.empty and list(out.columns) == MandiPrices.schema.names
