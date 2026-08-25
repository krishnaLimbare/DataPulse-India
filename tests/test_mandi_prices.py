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


def test_duplicate_rows_across_pages_are_dropped_and_warned():
    source = MandiPrices(CFG)
    source.fetch = lambda ctx: LOWER + LOWER  # same row on two pages
    out = source.collect(CTX)
    assert len(out) == 1
    assert any("duplicate" in w for w in source.warnings)


def test_clean_payload_produces_no_warnings():
    source = MandiPrices(CFG)
    source.fetch = lambda ctx: LOWER
    source.collect(CTX)
    assert source.warnings == []


class _FakeHttp:
    """Serves paged responses so fetch() can be exercised without a network."""

    def __init__(self, rows, total=None, page_size=2):
        self.rows, self.total, self.page_size = rows, total, page_size
        self.calls = 0

    def get(self, url, params=None, **kw):
        self.calls += 1
        offset = params["offset"]
        body = {"records": self.rows[offset : offset + params["limit"]]}
        if self.total is not None:
            body["total"] = self.total
        return _FakeResponse(body)


class _FakeResponse:
    def __init__(self, body):
        self._body = body

    def json(self):
        return self._body

    def raise_for_status(self):
        return None


def _ctx_with(http):
    cfg = SourceConfig(domain="food_mandi", options={"page_size": 2, "max_pages": 10})
    return RunContext(date(2026, 8, 25), cfg, http, secrets={"data_gov_in": "k"})


def _rows(n):
    return [{**LOWER[0], "market": f"m{i}"} for i in range(n)]


def test_pages_until_total_is_reached():
    http = _FakeHttp(_rows(5), total=5)
    ctx = _ctx_with(http)
    assert len(MandiPrices(ctx.config).fetch(ctx)) == 5
    assert http.calls == 3  # 2 + 2 + 1, stopping on the short page


def test_hitting_the_page_cap_warns_instead_of_passing_silently():
    cfg = SourceConfig(domain="food_mandi", options={"page_size": 2, "max_pages": 2})
    ctx = RunContext(
        date(2026, 8, 25), cfg, _FakeHttp(_rows(100), total=100), secrets={"data_gov_in": "k"}
    )
    source = MandiPrices(cfg)
    source.fetch(ctx)
    assert any("cap" in w for w in source.warnings)
    assert any("4 of 100" in w for w in source.warnings)


def test_missing_total_falls_back_to_short_page_rule():
    http = _FakeHttp(_rows(3), total=None)
    ctx = _ctx_with(http)
    source = MandiPrices(ctx.config)
    assert len(source.fetch(ctx)) == 3
    assert source.warnings == []
