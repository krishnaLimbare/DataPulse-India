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
        "grade": "FAQ",
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


def test_overlapping_partitions_dedupe_without_flagging_the_run():
    """Partition overlap is by design, so it must not degrade the run status."""
    rows = _multi_state_rows()
    ctx = _partitioned_ctx(_PartitionedHttp(rows), values=["Gujarat", "Gujarat", "Kerala"])
    source = MandiPrices(ctx.config)
    source.collect(ctx)
    assert source.warnings == []


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


class _PartitionedHttp:
    """Fake portal with an offset ceiling, like the real one."""

    OFFSET_CEILING = 6  # stands in for the real 10000

    def __init__(self, rows, field="state"):
        self.rows, self.field, self.calls = rows, field, 0

    def get(self, url, params=None, **kw):
        self.calls += 1
        wanted = params.get(f"filters[{self.field}]")
        pool = [r for r in self.rows if wanted is None or r[self.field] == wanted]
        offset, limit = params["offset"], params["limit"]
        page = [] if offset >= self.OFFSET_CEILING else pool[offset : offset + limit]
        return _FakeResponse({"records": page, "total": len(pool)})


def _partitioned_ctx(http, **partition):
    cfg = SourceConfig(
        domain="food_mandi",
        options={"page_size": 2, "max_pages": 10, "partition": {"field": "state", **partition}},
    )
    return RunContext(date(2026, 8, 25), cfg, http, secrets={"data_gov_in": "k"})


def _multi_state_rows():
    rows = []
    for state, n in (("Gujarat", 5), ("Kerala", 4), ("Assam", 3)):
        rows += [{**LOWER[0], "state": state, "market": f"{state}-{i}"} for i in range(n)]
    return rows


def test_partitioning_reaches_rows_beyond_the_offset_ceiling():
    rows = _multi_state_rows()  # 12 rows; a flat scan can only see 6
    http = _PartitionedHttp(rows)
    ctx = _partitioned_ctx(http, values=["Gujarat", "Kerala", "Assam"])
    source = MandiPrices(ctx.config)
    fetched = source.fetch(ctx)
    assert len(fetched) == len(rows)  # complete, despite the ceiling
    assert source.warnings == []


def test_flat_scan_is_truncated_by_the_ceiling():
    """Control: without partitioning the same portal yields a partial result."""
    rows = _multi_state_rows()
    cfg = SourceConfig(domain="food_mandi", options={"page_size": 2, "max_pages": 10})
    ctx = RunContext(date(2026, 8, 25), cfg, _PartitionedHttp(rows), secrets={"data_gov_in": "k"})
    source = MandiPrices(cfg)
    assert len(source.fetch(ctx)) < len(rows)
    assert any("of 12 reported" in w for w in source.warnings)


def test_partition_values_are_discovered_from_live_data():
    """No hand-maintained state list: the names come from the feed itself."""
    rows = [{**LOWER[0], "state": s, "market": f"{s}-{i}"}
            for s, n in (("Gujarat", 3), ("Kerala", 2)) for i in range(n)]
    http = _PartitionedHttp(rows)
    ctx = _partitioned_ctx(http, discovery_pages=3)
    source = MandiPrices(ctx.config)
    fetched = source.fetch(ctx)
    assert {r["state"] for r in fetched} == {"Gujarat", "Kerala"}
    assert source.warnings == []


def test_pinned_values_recover_what_discovery_cannot_see():
    """Discovery samples a capped window, so a value whose rows all sit past
    the ceiling is invisible to it. The portal's loose filter matching makes
    the reported totals too unreliable to detect that gap, so pinning the
    values in config is the actual guarantee -- that path has to work.
    """
    rows = _multi_state_rows()  # Assam sits past the fake ceiling

    ctx = _partitioned_ctx(_PartitionedHttp(rows), discovery_pages=3)
    discovered = MandiPrices(ctx.config).fetch(ctx)
    assert "Assam" not in {r["state"] for r in discovered}

    pinned_ctx = _partitioned_ctx(_PartitionedHttp(rows), values=["Gujarat", "Kerala", "Assam"])
    pinned = MandiPrices(pinned_ctx.config).fetch(pinned_ctx)
    assert {r["state"] for r in pinned} == {"Gujarat", "Kerala", "Assam"}


class _FlakyPartitionedHttp(_PartitionedHttp):
    """Fails one partition outright, however many times it is retried."""

    def __init__(self, rows, broken):
        super().__init__(rows)
        self.broken = broken

    def get(self, url, params=None, **kw):
        if params.get("filters[state]") == self.broken:
            raise RuntimeError("429 after retries")
        return super().get(url, params=params, **kw)


def test_one_failed_partition_does_not_lose_the_whole_day():
    rows = _multi_state_rows()
    ctx = _partitioned_ctx(
        _FlakyPartitionedHttp(rows, broken="Kerala"), values=["Gujarat", "Kerala", "Assam"]
    )
    source = MandiPrices(ctx.config)
    fetched = source.fetch(ctx)

    assert {r["state"] for r in fetched} == {"Gujarat", "Assam"}  # Kerala lost, rest kept
    assert any("Kerala failed after retries" in w for w in source.warnings)
    assert any("1 of 3 partitions failed" in w for w in source.warnings)


def test_total_collection_failure_still_raises():
    """Losing every partition is a failed run, not a quietly empty one."""
    import pytest

    rows = _multi_state_rows()

    class _AllBroken(_PartitionedHttp):
        def get(self, url, params=None, **kw):
            if params.get("filters[state]"):
                raise RuntimeError("429")
            return super().get(url, params=params, **kw)

    ctx = _partitioned_ctx(_AllBroken(rows), values=["Gujarat", "Kerala"])
    with pytest.raises(RuntimeError, match="collected nothing"):
        MandiPrices(ctx.config).fetch(ctx)


def test_quality_flag_is_attached_without_dropping_rows():
    """End-to-end: a unit error survives into the archive, clearly marked."""
    peers = [
        {**LOWER[0], "market": f"m{i}", "min_price": "1800", "modal_price": "2000",
         "max_price": "2200"}
        for i in range(6)
    ]
    # Same market, same crop, priced per kilogram instead of per quintal.
    broken = {**LOWER[0], "market": "patti", "min_price": "0.20", "modal_price": "0.20",
              "max_price": "0.20"}
    source = MandiPrices(CFG)
    source.fetch = lambda ctx: [*peers, broken]
    out = source.collect(CTX)

    assert len(out) == 7, "flagged rows must be kept, not deleted"
    flagged = out[out.quality_flag != ""]
    assert len(flagged) == 1
    assert flagged.iloc[0]["market"] == "patti"
    assert flagged.iloc[0]["modal_price"] == 0.20, "the raw value is preserved"


def test_stray_whitespace_cannot_fork_a_series():
    """The portal ships "Sweet Corn " and a commodity ending in a newline. Left
    alone those are different strings, so the same market+crop would carry two
    different series_ids and its history would split in half."""
    tidy = {**LOWER[0], "commodity": "Sweet Corn", "market": "Pune APMC"}
    messy = {**LOWER[0], "commodity": "Sweet Corn\n", "market": "Pune  APMC",
             "arrival_date": "26/08/2026"}
    out = _collect([tidy, messy])

    assert out["commodity"].tolist() == ["Sweet Corn", "Sweet Corn"]
    assert out["market"].tolist() == ["Pune APMC", "Pune APMC"]
    assert out["series_id"].nunique() == 1, "one market and crop is one series"


def test_normalisation_leaves_case_alone():
    """Case is part of the primary key. Folding it would merge rows the portal
    reports separately, and nothing could tell them apart afterwards."""
    out = _collect([{**LOWER[0], "commodity": "TOMATO"}])
    assert out.loc[0, "commodity"] == "TOMATO"


def test_implausible_prices_are_flagged_not_dropped():
    source = MandiPrices(CFG)
    source.fetch = lambda ctx: [{**LOWER[0], "min_price": "0", "modal_price": "0",
                                 "max_price": "0"}]
    out = source.collect(CTX)
    assert len(out) == 1
    assert "price_implausible" in out.loc[0, "quality_flag"]


def test_real_prices_do_not_trip_the_bounds():
    """Cardamom really does trade near 272,500 per quintal."""
    source = MandiPrices(CFG)
    source.fetch = lambda ctx: [{**LOWER[0], "commodity": "Cardamom", "min_price": "268000",
                                 "modal_price": "272500", "max_price": "275000"}]
    assert source.collect(CTX).loc[0, "quality_flag"] == ""
