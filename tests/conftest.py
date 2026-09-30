import pytest

from tension_index.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "test.sqlite3",
        health_min_free_disk_mb=1,
    )
