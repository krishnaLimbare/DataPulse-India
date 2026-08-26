"""Data-quality rules.

Upstream data is not clean. One Punjab market reports in rupees per kilogram
while every other market reports per quintal, so its potato price arrives as
0.20 against a national median near 2000. Averaged in, it drags the mean down;
compared across states, it invents a 14,000x arbitrage opportunity.

The rule here is **flag, never delete**. Dropping rows would quietly rewrite the
archive and we could never recover the original. Instead every row keeps its raw
values and gains a `quality_flag` column: empty when clean, otherwise a
comma-separated list of rule codes. Consumers decide what to do -- the dashboard
excludes flagged rows from averages, while the parquet keeps everything.

Rules are declared per source next to its schema, because which values are
implausible is a fact about the data, not about the platform:

    quality_rules = (
        Ordered(["min_price", "modal_price", "max_price"]),
        PeerRatio("modal_price", group_by=["commodity"], factor=20),
    )
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass

import pandas as pd

CLEAN = ""


class Rule(ABC):
    """A named check. `flags` returns True for every row that fails it."""

    code: str

    @abstractmethod
    def flags(self, df: pd.DataFrame) -> pd.Series: ...

    def _missing(self, df: pd.DataFrame, columns: list[str]) -> bool:
        return any(c not in df.columns for c in columns)


@dataclass(frozen=True)
class Between(Rule):
    """Value must sit inside an absolute range. Nulls pass -- absent is not wrong."""

    column: str
    low: float | None = None
    high: float | None = None
    code: str = "out_of_range"

    def flags(self, df: pd.DataFrame) -> pd.Series:
        if self._missing(df, [self.column]):
            return pd.Series(False, index=df.index)
        values = pd.to_numeric(df[self.column], errors="coerce")
        bad = pd.Series(False, index=df.index)
        if self.low is not None:
            bad |= values < self.low
        if self.high is not None:
            bad |= values > self.high
        return bad.fillna(False)


@dataclass(frozen=True)
class Ordered(Rule):
    """Columns must be non-decreasing left to right, e.g. min <= modal <= max."""

    columns: tuple[str, ...]
    code: str = "order_invalid"

    def __init__(self, columns: list[str] | tuple[str, ...], code: str = "order_invalid") -> None:
        object.__setattr__(self, "columns", tuple(columns))
        object.__setattr__(self, "code", code)

    def flags(self, df: pd.DataFrame) -> pd.Series:
        if self._missing(df, list(self.columns)):
            return pd.Series(False, index=df.index)
        bad = pd.Series(False, index=df.index)
        for left, right in zip(self.columns, self.columns[1:], strict=False):
            pair = df[[left, right]].apply(pd.to_numeric, errors="coerce")
            bad |= (pair[left] > pair[right]).fillna(False)
        return bad


@dataclass(frozen=True)
class PeerRatio(Rule):
    """Value must be within `factor` of its peer group's median.

    This is what catches unit errors: a per-kilogram price sitting in a
    per-quintal column is ~100x out, while genuine regional variation is well
    under 20x. Groups smaller than `min_group` are skipped -- a median over two
    rows is not a baseline worth trusting.
    """

    column: str
    group_by: tuple[str, ...]
    factor: float = 20.0
    min_group: int = 5
    code: str = "peer_outlier"

    def __init__(
        self,
        column: str,
        group_by: list[str] | tuple[str, ...],
        factor: float = 20.0,
        min_group: int = 5,
        code: str = "peer_outlier",
    ) -> None:
        object.__setattr__(self, "column", column)
        object.__setattr__(self, "group_by", tuple(group_by))
        object.__setattr__(self, "factor", factor)
        object.__setattr__(self, "min_group", min_group)
        object.__setattr__(self, "code", code)

    def flags(self, df: pd.DataFrame) -> pd.Series:
        if self._missing(df, [self.column, *self.group_by]):
            return pd.Series(False, index=df.index)

        values = pd.to_numeric(df[self.column], errors="coerce")
        grouped = values.groupby([df[c] for c in self.group_by])
        median = grouped.transform("median")
        size = grouped.transform("size")

        comparable = (size >= self.min_group) & median.gt(0) & values.notna()
        ratio = values / median
        bad = comparable & ((ratio > self.factor) | (ratio < 1 / self.factor))
        return bad.fillna(False)


def apply_rules(df: pd.DataFrame, rules: tuple[Rule, ...]) -> pd.Series:
    """Return one flag string per row: empty when clean, else joined rule codes."""
    if df.empty or not rules:
        return pd.Series(CLEAN, index=df.index, dtype="string")

    hits: list[pd.Series] = []
    for rule in rules:
        failed = rule.flags(df).astype(bool)
        hits.append(failed.map({True: rule.code, False: CLEAN}))

    combined = pd.concat(hits, axis=1) if hits else pd.DataFrame(index=df.index)
    return (
        combined.apply(lambda row: ",".join(c for c in row if c), axis=1)
        .astype("string")
        .fillna(CLEAN)
    )
