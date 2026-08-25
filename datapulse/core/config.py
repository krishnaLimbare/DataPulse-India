"""Configuration.

Three layers, lowest to highest precedence:
  1. defaults in code
  2. `config/settings.yaml`  (checked in, non-secret)
  3. environment / `.env`    (secrets only, never committed)

Adding a new dataset means adding a YAML block, not editing this file.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CONFIG = REPO_ROOT / "config" / "settings.yaml"


class SourceConfig(BaseModel):
    """Per-source knobs. Unknown keys land in `options` for the source to interpret."""

    enabled: bool = True
    domain: str = Field(description="Logical dataset family, e.g. 'cars'; becomes a folder.")
    schedule: str = "daily"
    rate_limit_per_sec: float = 0.5
    timeout_seconds: float = 30.0
    max_retries: int = 3
    options: dict[str, Any] = Field(default_factory=dict)


class StorageConfig(BaseModel):
    backend: str = "parquet_local"
    root: Path = Path("datasets")
    compression: str = "zstd"
    # Partitioning keeps daily files small and makes back-fills idempotent.
    partition_by: list[str] = Field(default_factory=lambda: ["year", "month"])


class Settings(BaseSettings):
    """Runtime settings. Secrets come from env only (`DATAPULSE_*`)."""

    model_config = SettingsConfigDict(
        env_prefix="DATAPULSE_",
        env_nested_delimiter="__",  # DATAPULSE_API_KEYS__DATA_GOV_IN -> api_keys["data_gov_in"]
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    environment: str = "local"
    log_level: str = "INFO"
    user_agent: str = (
        "DataPulse-India/0.1 (+https://github.com/KrishnaLimbare/DataPulse-India) "
        "research bot; contact via GitHub issues"
    )
    respect_robots_txt: bool = True
    dry_run: bool = False
    storage: StorageConfig = Field(default_factory=StorageConfig)
    sources: dict[str, SourceConfig] = Field(default_factory=dict)

    # Credentials for sources that need them, populated from env only.
    api_keys: dict[str, SecretStr] = Field(default_factory=dict)

    def secret(self, name: str) -> str | None:
        """Look up a credential by lowercase name, e.g. "data_gov_in"."""
        value = self.api_keys.get(name.lower())
        return value.get_secret_value() if value else None


def load_settings(config_path: Path | None = None) -> Settings:
    path = config_path or DEFAULT_CONFIG
    data: dict[str, Any] = {}
    if path.exists():
        data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    settings = Settings(**data)
    if not settings.storage.root.is_absolute():
        settings.storage.root = REPO_ROOT / settings.storage.root
    return settings
