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

from abc import ABC, abstractmethod
from dataclasses import dataclass
from datetime import date
from typing import Any, ClassVar

import pandas as pd

from .config import SourceConfig
from .http import HttpClient
from .logging import get_logger
from .schema import Schema


@dataclass
class RunContext:
    """Everything a source is allowed to touch. Sources never read globals."""

    run_date: date
    config: SourceConfig
    http: HttpClient
    dry_run: bool = False

    def option(self, key: str, default: Any = None) -> Any:
        return self.config.options.get(key, default)


class BaseSource(ABC):
    name: ClassVar[str]
    domain: ClassVar[str]
    schema: ClassVar[Schema]
    # Set False for sources whose data is legally/ToS restricted from redistribution.
    publishable: ClassVar[bool] = True

    def __init__(self, config: SourceConfig) -> None:
        self.config = config
        self.log = get_logger(f"source.{self.name}")

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
        if "collected_date" in self.schema.names and "collected_date" not in df.columns:
            df["collected_date"] = pd.to_datetime(ctx.run_date)
        if "source" in self.schema.names and "source" not in df.columns:
            df["source"] = self.name
        return self.schema.validate(df)


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
