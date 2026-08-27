"""The one interface every dataset implements.

Adding a dataset = one file in `datapulse/sources/` + one YAML block.
Nothing in core needs to change.

    @register
    class MySource(BaseSource):
        name = "my_source"
        domain = "cars"
        schema = Schema([...])

        def fetch(self, ctx): ...     # -> raw payloads (network only)
        def parse(self, raw, ctx): ...# -> pd.DataFrame (pure, unit-testable)
"""

from __future__ import annotations

import hashlib
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import date
from typing import Any, ClassVar

import pandas as pd

from .config import SourceConfig
from .http import HttpClient
from .logging import get_logger
from .quality import CLEAN, Rule, apply_rules
from .schema import Schema


class MissingSecret(RuntimeError):
    """A source asked for a credential that is not configured."""


@dataclass
class RunContext:
    """Everything a source is allowed to touch. Sources never read globals."""

    run_date: date
    config: SourceConfig
    http: HttpClient
    dry_run: bool = False
    secrets: dict[str, str] = field(default_factory=dict)

    def option(self, key: str, default: Any = None) -> Any:
        """Non-secret, per-source tuning from config/settings.yaml."""
        return self.config.options.get(key, default)

    def secret(self, name: str) -> str:
        """Credential from the environment. Raises with an actionable message."""
        value = self.secrets.get(name.lower())
        if not value:
            raise MissingSecret(
                f"secret {name!r} is not set; export "
                f"DATAPULSE_API_KEYS__{name.upper()} (see .env.example)"
            )
        return value


class BaseSource(ABC):
    name: ClassVar[str]
    domain: ClassVar[str]
    schema: ClassVar[Schema]
    # Checks applied after validation. Rows are flagged, never dropped.
    quality_rules: ClassVar[tuple[Rule, ...]] = ()

    # The column holding the date the data *describes*, as opposed to when we
    # happened to fetch it. Naming files from the clock means a delayed run --
    # GitHub schedules drift by hours -- files the wrong day and leaves a gap.
    # Set this and the archive becomes independent of when the job wakes up.
    partition_column: ClassVar[str] = ""
    # Natural key within one partition, used to merge a re-run into an existing
    # day instead of overwriting it. Must exclude collected_date.
    identity_columns: ClassVar[tuple[str, ...]] = ()
    # The columns that identify one thing followed across days -- the identity
    # minus anything date-shaped. Filled into `series_id` so joining a series
    # over time is one column instead of six.
    series_columns: ClassVar[tuple[str, ...]] = ()
    # Set False for sources whose data is legally/ToS restricted from redistribution.
    publishable: ClassVar[bool] = True

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.log = get_logger(f"source.{self.name}")
        # Non-fatal problems worth surfacing: incomplete data, dropped rows.
        # The runner turns these into a `partial` status on the run report so
        # degraded collection can never look like a clean success.
        self.warnings: list[str] = []

    def warn(self, message: str) -> None:
        self.log.warning(message)
        self.warnings.append(message)

    @abstractmethod
    def fetch(self, ctx: RunContext) -> Any:
        """Do the network I/O. Keep parsing out of here so it can be mocked."""

    @abstractmethod
    def parse(self, raw: Any, ctx: RunContext) -> pd.DataFrame:
        """Pure transform from raw payload to a dataframe matching `schema`."""

    def collect(self, ctx: RunContext) -> pd.DataFrame:
        """Template method: fetch -> parse -> stamp -> validate."""
        raw = self.fetch(ctx)
        df = self.parse(raw, ctx)
        self._stamp(df, "collected_date", pd.to_datetime(ctx.run_date))
        self._stamp(df, "source", self.name)
        df = self._add_series_id(df)
        df = self._flag_quality(df)
        return self.schema.validate(df)

    def _add_series_id(self, df: pd.DataFrame) -> pd.DataFrame:
        """A short stable code for one market+product followed over time.

        Derived purely from columns already present, so it invents nothing --
        the same combination always produces the same id, in any run, on any
        machine.
        """
        if "series_id" not in self.schema.names or not self.series_columns or df.empty:
            return df
        missing = [c for c in self.series_columns if c not in df.columns]
        if missing:
            self.warn(f"cannot build series_id, missing {missing}")
            return df

        df = df.copy()
        joined = df[list(self.series_columns)].astype("string").fillna("").agg("|".join, axis=1)
        df["series_id"] = joined.map(
            lambda key: hashlib.sha1(key.encode("utf-8")).hexdigest()[:12]  # noqa: S324
        )
        return df

    def _flag_quality(self, df: pd.DataFrame) -> pd.DataFrame:
        """Attach `quality_flag` without removing anything.

        Suspect rows stay in the archive with their original values; the flag
        lets consumers exclude them from averages while keeping the evidence.
        """
        if "quality_flag" not in self.schema.names:
            return df
        df = df.copy()
        df["quality_flag"] = apply_rules(df, self.quality_rules)
        flagged = int((df["quality_flag"] != CLEAN).sum())
        if flagged:
            counts = (
                df.loc[df["quality_flag"] != CLEAN, "quality_flag"].value_counts().to_dict()
            )
            self.log.info("flagged %d of %d rows: %s", flagged, len(df), counts)
        return df

    def _stamp(self, df: pd.DataFrame, column: str, value: Any) -> None:
        """Fill a provenance column the source did not populate.

        Absent *or* all-null counts as unpopulated: `parse` implementations
        commonly back-fill every declared column with NA before returning.
        """
        if column not in self.schema.names:
            return
        if column not in df.columns or df[column].isna().all():
            df[column] = value


_REGISTRY: dict[str, type[BaseSource]] = {}


def register(cls: type[BaseSource]) -> type[BaseSource]:
    """Class decorator that makes a source discoverable by name."""
    for attr in ("name", "domain", "schema"):
        if not getattr(cls, attr, None):
            raise TypeError(f"{cls.__name__} must define a class-level `{attr}`")
    if cls.name in _REGISTRY:
        raise ValueError(f"duplicate source name {cls.name!r}")
    _REGISTRY[cls.name] = cls
    return cls


def registry() -> dict[str, type[BaseSource]]:
    from datapulse import sources  # noqa: F401  -- import side effect populates registry

    return dict(_REGISTRY)
