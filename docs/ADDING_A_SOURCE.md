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

Rules of thumb:

- `collected_date` and `source` are auto-stamped if declared — don't set them in `parse`.
- Return an **empty dataframe with the right columns** rather than raising when a
  source legitimately has no data today.
- Put anything you might tune (URLs, page sizes, city lists) in `options` in YAML,
  not in the module.
- Never read `os.environ` for non-secrets; use `ctx.option`. Secrets go through env
  with a clear error message when missing.
- If a site's terms forbid redistribution, set `publishable = False` and keep the
  output out of the committed `datasets/` tree.
