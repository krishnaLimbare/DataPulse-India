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

# The row identity for one day's snapshot. Offset paging over a dataset that is
# still being written to can return the same row twice, so this is what we
# de-duplicate on.
PRIMARY_KEY = ["state", "district", "market", "commodity", "variety", "arrival_date"]


def _envelope_total(payload: dict[str, Any]) -> int | None:
    """Read the upstream row count, tolerating the key being absent or junk."""
    for key in ("total", "count"):
        try:
            value = int(payload[key])
        except (KeyError, TypeError, ValueError):
            continue
        if value > 0:
            return value
    return None


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
        primary_key=["collected_date", *PRIMARY_KEY],
    )

    def fetch(self, ctx: RunContext) -> list[dict[str, Any]]:
        """Page until the API says we have everything.

        The portal reports the full row count in the envelope's `total`, so we
        page to that rather than to a guessed page count. `max_pages` stays on
        as a circuit breaker only: hitting it means we truncated, and that is
        recorded as a warning so the run never reports a clean `ok` over
        incomplete data.
        """
        api_key = ctx.secret("data_gov_in")
        page_size = int(ctx.option("page_size", 1000))
        max_pages = int(ctx.option("max_pages", 50))

        records: list[dict[str, Any]] = []
        total: int | None = None

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
            payload = resp.json()
            batch = payload.get("records", [])
            records.extend(batch)

            if total is None:
                total = _envelope_total(payload)
                if total is not None:
                    self.log.info("upstream reports %d total records", total)

            if len(batch) < page_size:
                break  # short page: we reached the end
            if total is not None and len(records) >= total:
                break
        else:
            # Loop ran to the cap without a natural end -- we are truncating.
            self.warn(
                f"stopped at the {max_pages}-page cap with {len(records)} rows"
                + (f" of {total} reported" if total else "")
                + "; raise max_pages in config/settings.yaml"
            )

        if total is not None and len(records) < total:
            self.warn(f"collected {len(records)} of {total} reported rows")
        self.log.info("fetched %d mandi records", len(records))
        return records

    def parse(self, raw: list[dict[str, Any]], ctx: RunContext) -> pd.DataFrame:
        if not raw:
            return pd.DataFrame(columns=self.schema.names)

        # The portal has shipped both `min_price` and `Min_Price` across API
        # versions, so normalise keys instead of trusting one casing.
        df = pd.DataFrame(raw)
        df.columns = [str(c).strip().lower().replace(" ", "_") for c in df.columns]

        for col in self.schema.names:
            if col not in df.columns:
                df[col] = pd.NA
        for col in ("min_price", "max_price", "modal_price"):
            df[col] = pd.to_numeric(df[col], errors="coerce")

        # Offset paging over a dataset the portal is still writing to can hand
        # back the same row on two pages. Drop those before the schema's
        # primary-key check turns them into a hard failure.
        before = len(df)
        df = df.drop_duplicates(subset=PRIMARY_KEY, keep="last").reset_index(drop=True)
        if dropped := before - len(df):
            self.warn(f"dropped {dropped} duplicate rows across page boundaries")
        return df
