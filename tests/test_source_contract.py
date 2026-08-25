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
