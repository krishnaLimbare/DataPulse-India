"""Contract tests that every source must pass â€” no network involved."""

import pandas as pdimport pytestfrom datapulse.core.config import load_settingsfrom datapulse.core.schema import Column, Schemafrom datapulse.core.source import BaseSource, RunContext, registrydef test_registry_is_populated():
    assert registry(), "no sources registered"


@pytest.mark.parametrize("name", sorted(registry()))
def test_source_declares_a_usable_schema(name):
    cls = registry()[name]
    assert cls.schema.columns, f"{name} declares an empty schema"
    assert cls.domain and cls.domain.isidentifier()


def test_every_registered_source_has_config():
    settings = load_settings()
    assert set(registry()) <= set(settings.sources), "source missing a config/settings.yaml block"


def test_collect_stamps_and_validates(source_config):
    # deliberately not @register -- keeps the global registry clean for other tests
    class _Dummy(BaseSource):
        name = "_dummy_test_source"
        domain = "test"
        schema = Schema([Column("collected_date", "datetime64[ns]"), Column("source", "string")])

        def fetch(self, ctx):
            return [{}]

        def parse(self, raw, ctx):
            return pd.DataFrame(raw, index=[0])

    from datetime import date

    df = _Dummy(source_config).collect(RunContext(date(2026, 8, 25), source_config, http=None))
    assert df.loc[0, "source"] == "_dummy_test_source"


def test_secret_lookup_is_actionable(source_config):
    from datetime import date

    from datapulse.core.source import MissingSecret

    ctx = RunContext(date(2026, 8, 25), source_config, http=None, secrets={"present": "x"})
    assert ctx.secret("PRESENT") == "x"
    with pytest.raises(MissingSecret, match="DATAPULSE_API_KEYS__ABSENT"):
        ctx.secret("absent")


def test_series_id_is_stable_across_days_and_runs():
    """The point of series_id: the same market and crop keeps the same code."""
    from datetime import date

    from datapulse.core.config import SourceConfig
    from datapulse.sources.mandi_prices import MandiPrices

    cfg = SourceConfig(domain="food_mandi")
    row = {
        "state": "MH", "district": "Pune", "market": "Pune", "commodity": "Tomato",
        "variety": "Local", "grade": "FAQ", "arrival_date": "26/08/2026",
        "min_price": "1800", "max_price": "2200", "modal_price": "2000",
    }

    def collect(payload, day):
        source = MandiPrices(cfg)
        source.fetch = lambda ctx: payload
        return source.collect(RunContext(day, cfg, http=None))

    today = collect([row], date(2026, 8, 26))
    tomorrow = collect(
        [{**row, "arrival_date": "27/08/2026", "modal_price": "2100"}], date(2026, 8, 27)
    )
    assert today.series_id.iloc[0] == tomorrow.series_id.iloc[0]

    # A different grade is a different series -- those prices are not comparable.
    other = collect([{**row, "grade": "Medium"}], date(2026, 8, 26))
    assert other.series_id.iloc[0] != today.series_id.iloc[0]


def test_every_column_of_every_source_is_documented():
    """A dictionary is only useful if nothing is missing from it."""
    for name, cls in registry().items():
        undocumented = [c.name for c in cls.schema.columns if not c.description]
        assert not undocumented, f"{name} has undocumented columns: {undocumented}"
