from datetime import date

import pandas as pd

from datapulse.core.config import StorageConfig
from datapulse.core.storage import ParquetLocalStorage


def test_write_is_partitioned_and_idempotent(tmp_path):
    storage = ParquetLocalStorage(StorageConfig(root=tmp_path))
    day = date(2026, 8, 25)
    df = pd.DataFrame({"a": [1, 2]})

    path = storage.write("cars", "used_cars", df, day)
    assert "year=2026" in path and "month=08" in path

    storage.write("cars", "used_cars", df, day)  # rerun same day
    assert len(storage.read_all("cars", "used_cars")) == 2


def _source(tmp_path, pcol="market_date"):
    """A minimal source so the runner's write path can be exercised directly."""
    from datapulse.core.config import SourceConfig
    from datapulse.core.schema import Column, Schema
    from datapulse.core.source import BaseSource

    class _S(BaseSource):
        name = "t"
        domain = "d"
        schema = Schema([Column("market", "string")])
        partition_column = pcol  # class body cannot see a same-named parameter
        identity_columns = ("market",)

        def fetch(self, ctx):
            return []

        def parse(self, raw, ctx):
            return pd.DataFrame()

    return _S(SourceConfig(domain="d"))


def test_rows_are_filed_under_their_own_date_not_the_run_date(tmp_path):
    """A run delayed past UTC midnight must still file data under its real day."""
    from datapulse.core.runner import _write_dataset

    storage = ParquetLocalStorage(StorageConfig(root=tmp_path))
    df = pd.DataFrame(
        {
            "market": ["a", "b"],
            "market_date": pd.to_datetime(["2026-08-27", "2026-08-27"]),
        }
    )
    # The clock says the 28th; the data says the 27th. The data wins.
    paths, days = _write_dataset(_source(tmp_path), storage, df, date(2026, 8, 28))

    assert days == ["2026-08-27"]
    assert "2026-08-27" in paths[0]
    assert len(storage.read_day("d", "t", date(2026, 8, 27))) == 2
    assert storage.read_day("d", "t", date(2026, 8, 28)).empty


def test_a_mixed_response_is_split_across_days(tmp_path):
    from datapulse.core.runner import _write_dataset

    storage = ParquetLocalStorage(StorageConfig(root=tmp_path))
    df = pd.DataFrame(
        {
            "market": ["a", "b"],
            "market_date": pd.to_datetime(["2026-08-26", "2026-08-27"]),
        }
    )
    _, days = _write_dataset(_source(tmp_path), storage, df, date(2026, 8, 27))
    assert days == ["2026-08-26", "2026-08-27"]


def test_a_later_run_merges_into_a_day_instead_of_shrinking_it(tmp_path):
    """Late-reported rows must not replace the day they belong to."""
    from datapulse.core.runner import _write_dataset

    storage = ParquetLocalStorage(StorageConfig(root=tmp_path))
    day = pd.to_datetime("2026-08-27")

    full = pd.DataFrame({"market": list("abcde"), "market_date": [day] * 5})
    _write_dataset(_source(tmp_path), storage, full, date(2026, 8, 27))

    late = pd.DataFrame({"market": ["f"], "market_date": [day]})
    _write_dataset(_source(tmp_path), storage, late, date(2026, 8, 28))

    kept = storage.read_day("d", "t", date(2026, 8, 27))
    assert sorted(kept.market) == list("abcdef"), "the earlier rows must survive"


def test_without_a_partition_column_it_still_uses_the_run_date(tmp_path):
    from datapulse.core.runner import _write_dataset

    storage = ParquetLocalStorage(StorageConfig(root=tmp_path))
    df = pd.DataFrame({"market": ["a"]})
    _, days = _write_dataset(_source(tmp_path, pcol=""), storage, df, date(2026, 8, 28))
    assert days == ["2026-08-28"]
