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
