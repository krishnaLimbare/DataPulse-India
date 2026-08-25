"""Daily mandi (agricultural market) commodity prices from data.gov.in.

Reference implementation — copy this file as the template for new sources.
Needs a free API key: https://data.gov.in/help/how-use-datasets-apis
Set it as `DATAPULSE_API_KEYS__DATA_GOV_IN` and flip `enabled: true` in config.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from datapulse.core.schema import Column, Schema
from datapulse.core.source import BaseSource, RunContext, register

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
ENDPOINT = f"https://api.data.gov.in/resource/{RESOURCE_ID}"


@register
class MandiPrices(BaseSource):
    name = "mandi_prices"
    domain = "food_mandi"
    schema = Schema(
        columns=[
            Column("collected_date", "datetime64[ns]", nullable=False),
            Column("state", "string"),
            Column("district", "string"),
            Column("market", "string"),
            Column("commodity", "string", nullable=False),
            Column("variety", "string"),
            Column("arrival_date", "string"),
            Column("min_price", "float64"),
            Column("max_price", "float64"),
            Column("modal_price", "float64"),
            Column("source", "string", nullable=False),
        ],
    )

    def fetch(self, ctx: RunContext) -> list[dict[str, Any]]:
        api_key = ctx.secret("data_gov_in")
        page_size = int(ctx.option("page_size", 1000))
        max_pages = int(ctx.option("max_pages", 5))
        records: list[dict[str, Any]] = []
        for page in range(max_pages):
            resp = ctx.http.get(
                ENDPOINT,
                params={
                    "api-key": api_key,
                    "format": "json",
                    "limit": page_size,
                    "offset": page * page_size,
                },
            )
            resp.raise_for_status()
            batch = resp.json().get("records", [])
            records.extend(batch)
            if len(batch) < page_size:
                break
        self.log.info("fetched %d mandi records", len(records))
        return records

    def parse(self, raw: list[dict[str, Any]], ctx: RunContext) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame(columns=self.schema.names)
        df = pd.DataFrame(raw).rename(
            columns={
                "state": "state",
                "district": "district",
                "market": "market",
                "commodity": "commodity",
                "variety": "variety",
                "arrival_date": "arrival_date",
                "min_price": "min_price",
                "max_price": "max_price",
                "modal_price": "modal_price",
            }
        )
        for col in ("min_price", "max_price", "modal_price"):
            df[col] = pd.to_numeric(df.get(col), errors="coerce")
        for col in self.schema.names:
            if col not in df.columns:
                df[col] = pd.NA
        return df
