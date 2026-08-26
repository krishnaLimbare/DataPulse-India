# Adding a source

Copy [`datapulse/sources/mandi_prices.py`](../datapulse/sources/mandi_prices.py) — it is the
reference implementation.

```python
from datapulse.core.schema import Column, Schema
from datapulse.core.source import BaseSource, RunContext, register


@register
class CityRents(BaseSource):
    name = "city_rents"          # unique; also the folder name
    domain = "real_estate"       # dataset family; groups folders and --domain filters
    schema = Schema(
        columns=[
            Column("collected_date", "datetime64[ns]", nullable=False),
            Column("city", "string", nullable=False),
            Column("bhk", "Int64"),
            Column("rent_inr", "float64"),
            Column("source", "string", nullable=False),
        ],
        primary_key=["collected_date", "city", "bhk"],
    )

    def fetch(self, ctx: RunContext):
        # Only network I/O. Use ctx.http (rate limited, retried, robots-aware)
        # and ctx.option("key", default) for anything configurable.
        return ctx.http.get(ctx.option("url")).json()

    def parse(self, raw, ctx: RunContext):
        # Pure. No network. Unit test this against a saved fixture.
        return pd.DataFrame(raw)
```

Declare quality rules next to the schema when the upstream data can be wrong
rather than merely missing:

```python
from datapulse.core.quality import Ordered, PeerRatio

    quality_rules = (
        Ordered(["min_price", "modal_price", "max_price"]),
        # 20x off its own commodity's median means a unit error, not a bargain.
        PeerRatio("modal_price", group_by=["commodity"], factor=20),
    )
```

Add a nullable `quality_flag` column to the schema to switch it on. Flagged rows
are kept with their original values -- never drop a row you cannot recover.

Rules of thumb:

- `collected_date` and `source` are auto-stamped if declared — don't set them in `parse`.
- Return an **empty dataframe with the right columns** rather than raising when a
  source legitimately has no data today.
- Put anything you might tune (URLs, page sizes, city lists) in `options` in YAML,
  not in the module.
- Never read `os.environ` directly. Non-secret tuning is `ctx.option("key", default)`;
  credentials are `ctx.secret("data_gov_in")`, which reads
  `DATAPULSE_API_KEYS__DATA_GOV_IN` and raises `MissingSecret` with the variable name.
- If a site's terms forbid redistribution, set `publishable = False` and keep the
  output out of the committed `datasets/` tree.
