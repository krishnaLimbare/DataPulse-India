import pandas as pd
import pytest

from datapulse.core.schema import Column, Schema, SchemaError

SCHEMA = Schema(
    columns=[
        Column("id", "Int64", nullable=False, unique=True),
        Column("city", "string"),
        Column("price", "float64"),
    ],
    primary_key=["id"],
)


def test_validate_coerces_and_orders_columns():
    df = pd.DataFrame({"price": ["1.5", "2"], "id": [1, 2], "city": ["Pune", None], "junk": [0, 0]})
    out = SCHEMA.validate(df)
    assert list(out.columns) == ["id", "city", "price"]
    assert out["price"].tolist() == [1.5, 2.0]


def test_missing_column_is_rejected():
    with pytest.raises(SchemaError, match="missing columns"):
        SCHEMA.validate(pd.DataFrame({"id": [1]}))


def test_non_nullable_and_uniqueness_enforced():
    with pytest.raises(SchemaError, match="non-nullable"):
        SCHEMA.validate(pd.DataFrame({"id": [None], "city": ["x"], "price": [1.0]}))
    with pytest.raises(SchemaError, match="unique"):
        SCHEMA.validate(pd.DataFrame({"id": [1, 1], "city": ["x", "y"], "price": [1.0, 2.0]}))


def test_scrub_masks_credentials_in_urls():
    from datapulse.core.logging import scrub

    msg = "HTTPStatusError for url 'https://api.data.gov.in/r/x?api-key=SUPERSECRET&format=json'"
    out = scrub(msg)
    assert "SUPERSECRET" not in out
    assert "api-key=***redacted***" in out
    assert "format=json" in out  # non-secret params survive


def test_plain_text_logs_are_scrubbed_too(caplog, capsys):
    import logging

    from datapulse.core.logging import setup_logging

    setup_logging("INFO", json_logs=False)
    logging.getLogger("t").info("GET https://x.in/r?api-key=LEAKME&format=json")
    assert "LEAKME" not in capsys.readouterr().out


def test_httpx_request_logging_is_silenced():
    import logging

    from datapulse.core.logging import setup_logging

    setup_logging("INFO")
    assert logging.getLogger("httpx").level == logging.WARNING
