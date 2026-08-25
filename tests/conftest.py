import pytest

from datapulse.core.config import SourceConfig


@pytest.fixture
def source_config():
    return SourceConfig(domain="test", rate_limit_per_sec=0)
