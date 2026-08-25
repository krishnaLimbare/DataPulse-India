"""Storage backends.

`Storage` is a Protocol so the local-parquet default can be swapped for S3,
DuckDB, or a database later without touching a single source.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path
from typing import Protocol, runtime_checkable

import pandas as pd

from .config import StorageConfig
from .logging import get_logger

log = get_logger(__name__)


@runtime_checkable
class Storage(Protocol):
    def write(self, domain: str, name: str, df: pd.DataFrame, run_date: date) -> str: ...
    def read_all(self, domain: str, name: str) -> pd.DataFrame: ...


class ParquetLocalStorage:
    """Date-partitioned parquet under `datasets/<domain>/<name>/year=/month=/`.

    Writes are idempotent: re-running a day overwrites that day's file only, so
    a failed run can be safely retried and back-fills never duplicate rows.
    """

    def __init__(self, cfg: StorageConfig) -> None:
        self.cfg = cfg

    def _path(self, domain: str, name: str, run_date: date) -> Path:
        return (
            self.cfg.root
            / domain
            / name
            / f"year={run_date:%Y}"
            / f"month={run_date:%m}"
            / f"{name}_{run_date:%Y-%m-%d}.parquet"
        )

    def write(self, domain: str, name: str, df: pd.DataFrame, run_date: date) -> str:
        path = self._path(domain, name, run_date)
        path.parent.mkdir(parents=True, exist_ok=True)
        df.to_parquet(path, engine="pyarrow", compression=self.cfg.compression, index=False)
        log.info("wrote %d rows -> %s", len(df), path)
        return str(path)

    def read_all(self, domain: str, name: str) -> pd.DataFrame:
        root = self.cfg.root / domain / name
        files = sorted(root.rglob("*.parquet"))
        if not files:
            return pd.DataFrame()
        return pd.concat([pd.read_parquet(f) for f in files], ignore_index=True)


_BACKENDS = {"parquet_local": ParquetLocalStorage}


def build_storage(cfg: StorageConfig) -> Storage:
    try:
        return _BACKENDS[cfg.backend](cfg)
    except KeyError:
        raise ValueError(
            f"unknown storage backend {cfg.backend!r}; known: {sorted(_BACKENDS)}"
        ) from None
