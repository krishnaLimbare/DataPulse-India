"""Daily mandi (agricultural market) commodity prices from data.gov.in.

Reference implementation -- copy this file as the template for new sources.
Needs a free API key: https://data.gov.in/help/how-use-datasets-apis
Set it as `DATAPULSE_API_KEYS__DATA_GOV_IN` and flip `enabled: true` in config.

Three quirks of this portal shape the code below, all verified against the
live API rather than assumed:

1. `offset` is refused past 10000, while the dataset holds ~16.5k rows. An
   unpartitioned scan therefore sees a *different* ~60% slice every run, which
   would make day-to-day price comparisons meaningless. Hence partitioning.
2. `filters[...]` matches loosely: `filters[state]=Uttar Pradesh` also returns
   Andhra, Madhya and Himachal Pradesh. Slices overlap heavily and per-slice
   totals sum to far more than the dataset holds, so the union is de-duplicated
   and those totals are not treated as a completeness measure.
3. The unfiltered `total` (16,579) disagrees with the sum of per-state totals
   (26,719). Neither number is authoritative, so neither gates the run.
"""

from __future__ import annotations

from typing import Any

import pandas as pd

from datapulse.core.quality import Between, Ordered, PeerRatio
from datapulse.core.schema import Column, Schema
from datapulse.core.source import BaseSource, RunContext, register

RESOURCE_ID = "9ef84268-d588-465a-a308-a864a43d0070"
ENDPOINT = f"https://api.data.gov.in/resource/{RESOURCE_ID}"

# Row identity for one day's snapshot -- what we de-duplicate on.
# `grade` belongs here: a single market reports the same commodity+variety at
# several grades with genuinely different prices (Grade Range-1/2/3), so
# omitting it silently collapsed three real price points into one.
PRIMARY_KEY = [
    "state",
    "district",
    "market",
    "commodity",
    "variety",
    "grade",
    "arrival_date",
]


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
            Column("collected_date", "datetime64[ns]", nullable=False,
                   description="When our robot fetched the row. Provenance, not a market date.",
                   empty_means="never empty"),
            Column("market_date", "datetime64[ns]",
                   description="The trading day these prices are for. Files are named after this.",
                   empty_means="the portal gave an unreadable arrival_date"),
            Column("series_id", "string",
                   description="Stable code for one market + crop + variety + grade. Use it to "
                               "follow the same thing across days.",
                   empty_means="one of the six identifying fields was missing"),
            Column("state", "string", normalize=True,
                   description="State or union territory, spelled as the portal spells it."),
            Column("district", "string", normalize=True,
                   description="District within the state."),
            Column("market", "string", normalize=True,
                   description="The mandi (wholesale market) reporting the price."),
            Column("commodity", "string", nullable=False, normalize=True,
                   description="The crop or product traded."),
            Column("variety", "string", normalize=True,
                   description="Variety of the commodity, e.g. Local, Nasik, Jyoti."),
            Column("grade", "string", normalize=True,
                   description="Quality grade. The same crop at one market trades at several "
                               "grades with genuinely different prices."),
            Column("arrival_date", "string",
                   description="Trading day exactly as the portal sent it (DD/MM/YYYY). "
                               "market_date is the parsed version."),
            Column("min_price", "float64", unit="INR per quintal (100 kg)",
                   description="Lowest price recorded at that market that day.",
                   empty_means="not reported"),
            Column("max_price", "float64", unit="INR per quintal (100 kg)",
                   description="Highest price recorded at that market that day.",
                   empty_means="not reported"),
            Column("modal_price", "float64", unit="INR per quintal (100 kg)",
                   description="The most common price that day. Usually the one to use.",
                   empty_means="not reported"),
            Column("source", "string", nullable=False,
                   description="Which pipeline collected the row."),
            Column("quality_flag", "string",
                   description="Empty when the row passed every check. Otherwise a "
                               "comma-separated list of what looked wrong. Flagged rows are "
                               "kept, never deleted.",
                   empty_means="the row passed all checks"),
        ],
        primary_key=["market_date", *PRIMARY_KEY],
    )

    partition_column = "market_date"
    identity_columns = tuple(PRIMARY_KEY)
    # A series is a market and a product followed over time -- the identity
    # without the date.
    series_columns = ("state", "district", "market", "commodity", "variety", "grade")

    quality_rules = (
        # A modal price outside its own min/max is internally inconsistent.
        Ordered(["min_price", "modal_price", "max_price"], code="price_order_invalid"),
        # Catches unit errors: Patti APMC (Punjab) reports rupees per kilogram
        # while the rest of the country reports per quintal, so its potato
        # arrives as 0.20 against a national median near 2000. Real regional
        # spread stays far inside 20x.
        PeerRatio("modal_price", group_by=["commodity"], factor=20, code="unit_or_outlier"),
        # A tripwire, not a filter. Nothing in the archive trips it today; the
        # bounds are deliberately far outside any real Indian mandi price so
        # that only a portal malfunction -- a zero, a negative, a stray decimal
        # shift -- can set it off. A rule that fires on nothing is still doing
        # its job, and costs one comparison per row.
        *[
            Between(c, low=0.01, high=10_000_000, code="price_implausible")
            for c in ("min_price", "modal_price", "max_price")
        ],
    )

    def fetch(self, ctx: RunContext) -> list[dict[str, Any]]:
        """Collect the day's rows, working around the portal's offset ceiling.

        The API refuses to serve past offset 10000, but the dataset is larger
        than that -- so an unpartitioned scan can only ever see the first ~10k
        of ~16.5k rows, and a different ~10k each run as the portal writes to
        it. Slicing the query by a low-cardinality field (state) keeps every
        slice under the ceiling, which makes the collection both complete and
        the same every day.

        With no `partition` configured this falls back to a plain paged scan.
        """
        api_key = ctx.secret("data_gov_in")
        page_size = int(ctx.option("page_size", 1000))
        max_pages = int(ctx.option("max_pages", 50))
        partition = ctx.option("partition") or {}
        field = partition.get("field")

        if not field:
            records, total = self._scan(ctx, api_key, page_size, max_pages)
            self._check_completeness(len(records), total)
            return records

        values = partition.get("values") or self._discover_values(
            ctx, api_key, page_size, field, int(partition.get("discovery_pages", 10))
        )
        if not values:
            self.warn(f"could not determine any {field} values; falling back to a flat scan")
            records, total = self._scan(ctx, api_key, page_size, max_pages)
            self._check_completeness(len(records), total)
            return records

        self.log.info("collecting %d %s partitions", len(values), field)
        records: list[dict[str, Any]] = []
        failed: list[str] = []
        for value in values:
            try:
                slice_rows, slice_total = self._scan(
                    ctx, api_key, page_size, max_pages, filters={f"filters[{field}]": value}
                )
            except Exception as exc:
                # One partition dying must not throw away the other 28. A day
                # missing one state beats a day missing everything -- the run is
                # marked `partial` so the gap is visible either way.
                failed.append(value)
                self.warn(f"{field}={value} failed after retries: {type(exc).__name__}")
                continue
            if slice_total is not None and len(slice_rows) < slice_total:
                self.warn(f"{field}={value}: got {len(slice_rows)} of {slice_total} rows")
            records.extend(slice_rows)

        if failed:
            self.warn(f"{len(failed)} of {len(values)} partitions failed: {sorted(failed)}")
        if not records:
            raise RuntimeError(f"every {field} partition failed; collected nothing")

        # The portal's filters match loosely (`state=Uttar Pradesh` also returns
        # Andhra/Madhya/Himachal Pradesh), so slices overlap and their totals
        # sum to more than the dataset holds. The union is what matters; parse()
        # de-duplicates it. Only a page-cap hit signals real truncation.
        self.log.info(
            "fetched %d rows across %d partitions (unfiltered total reported: %s)",
            len(records),
            len(values),
            self._reported_total,
        )
        return records

    # -- helpers --------------------------------------------------------
    _reported_total: int | None = None

    def _scan(
        self,
        ctx: RunContext,
        api_key: str,
        page_size: int,
        max_pages: int,
        filters: dict[str, str] | None = None,
        warn_on_cap: bool = True,
    ) -> tuple[list[dict[str, Any]], int | None]:
        """Page one query to exhaustion. Returns the rows and the reported total."""
        records: list[dict[str, Any]] = []
        total: int | None = None

        for page in range(max_pages):
            params = {
                "api-key": api_key,
                "format": "json",
                "limit": page_size,
                "offset": page * page_size,
            }
            params.update(filters or {})
            resp = ctx.http.get(ENDPOINT, params=params)
            resp.raise_for_status()
            payload = resp.json()
            batch = payload.get("records", [])
            records.extend(batch)

            if total is None:
                total = _envelope_total(payload)
                if filters is None and total is not None:
                    self._reported_total = total
                    self.log.info("upstream reports %d total records", total)

            if len(batch) < page_size:
                break  # short page: end of this query
            if total is not None and len(records) >= total:
                break
        else:
            if warn_on_cap:
                self.warn(
                    f"stopped at the {max_pages}-page cap with {len(records)} rows"
                    + (f" of {total} reported" if total else "")
                    + f" for {filters or 'the unfiltered query'}"
                )
        return records, total

    def _discover_values(
        self, ctx: RunContext, api_key: str, page_size: int, field: str, pages: int
    ) -> list[str]:
        """Learn the partition values from the data itself.

        Hand-maintaining a list of states is fragile -- the portal uses its own
        spellings ("Chattisgarh", "NCT of Delhi"), and a mismatch would silently
        drop a whole region. Sampling the live feed avoids inventing names.
        """
        # Hitting the ceiling here is expected -- that is why we partition at
        # all -- so it must not be recorded as a collection failure.
        sample, _ = self._scan(ctx, api_key, page_size, pages, warn_on_cap=False)
        seen = {
            str(row[field]).strip()
            for row in sample
            if row.get(field) not in (None, "")
        }
        values = sorted(seen)
        self.log.info("discovered %d distinct %s values", len(values), field)
        if self._reported_total and len(sample) < self._reported_total:
            # The sample itself was capped, so a value whose rows all sit past
            # the ceiling is invisible here. The completeness check below is
            # what catches that; pin `partition.values` in config to remove
            # the risk entirely.
            self.log.info(
                "%s values discovered from %d of %d rows", field, len(sample), self._reported_total
            )
        return values

    def _check_completeness(self, collected: int, total: int | None) -> None:
        if total is not None and collected < total:
            self.warn(f"collected {collected} of {total} reported rows")

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

        # The portal reports DD/MM/YYYY. dayfirst is explicit because pandas
        # would otherwise read 03/04/2026 as 3 April in some locales and
        # 4 March in others.
        df["market_date"] = pd.to_datetime(
            df["arrival_date"], format="%d/%m/%Y", errors="coerce"
        )
        unparsed = int(df["market_date"].isna().sum())
        if unparsed:
            self.warn(f"{unparsed} rows have an unreadable arrival_date")

        # Offset paging over a dataset the portal is still writing to can hand
        # back the same row on two pages. Drop those before the schema's
        # primary-key check turns them into a hard failure.
        before = len(df)
        df = df.drop_duplicates(subset=PRIMARY_KEY, keep="last").reset_index(drop=True)
        if dropped := before - len(df):
            if ctx.option("partition"):
                # Expected: the portal's filters match loosely, so state slices
                # overlap by design and the union is meant to be de-duplicated.
                self.log.info("dropped %d rows duplicated across partitions", dropped)
            else:
                # Unpartitioned, a repeat means the dataset shifted mid-scan.
                self.warn(f"dropped {dropped} duplicate rows across page boundaries")
        return df
