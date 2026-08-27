"""Lightweight dataframe contracts.

Every source declares a `Schema`. The runner validates before anything is
written, so a broken scraper fails loudly instead of poisoning the dataset.
Schemas are additive by design: adding a nullable column is backwards
compatible, so historic parquet files stay readable.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import pandas as pd


class SchemaError(ValueError):
    """Raised when a source produces data that violates its declared contract."""


@dataclass(frozen=True)
class Column:
    name: str
    dtype: str  # pandas dtype string: "string", "float64", "Int64", "datetime64[ns, UTC]", "bool"
    nullable: bool = True
    unique: bool = False
    # Documentation lives next to the definition so the two cannot drift apart.
    # A dictionary maintained in a separate file goes stale the first time a
    # column changes and nobody remembers to update it.
    description: str = ""
    unit: str = ""
    empty_means: str = ""


@dataclass(frozen=True)
class Schema:
    columns: list[Column]
    primary_key: list[str] = field(default_factory=list)

    @property
    def names(self) -> list[str]:
        return [c.name for c in self.columns]

    def validate(self, df: pd.DataFrame) -> pd.DataFrame:
        """Coerce to the declared types and enforce constraints. Returns a new frame."""
        missing = [c.name for c in self.columns if c.name not in df.columns]
        if missing:
            raise SchemaError(f"missing columns: {missing}")

        out = df.loc[:, self.names].copy()
        for col in self.columns:
            try:
                out[col.name] = out[col.name].astype(col.dtype)
            except (TypeError, ValueError) as exc:
                raise SchemaError(
                    f"column {col.name!r} not coercible to {col.dtype}: {exc}"
                ) from exc
            if not col.nullable and out[col.name].isna().any():
                raise SchemaError(f"column {col.name!r} declared non-nullable but has nulls")
            if col.unique and out[col.name].duplicated().any():
                raise SchemaError(f"column {col.name!r} declared unique but has duplicates")

        if self.primary_key and out.duplicated(subset=self.primary_key).any():
            raise SchemaError(f"duplicate rows for primary key {self.primary_key}")
        return out
