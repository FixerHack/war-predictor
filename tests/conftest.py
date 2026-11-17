import pytest

from tension_index.config import Settings


@pytest.fixture
def settings(tmp_path) -> Settings:
    return Settings(
        _env_file=None,
        database_path=tmp_path / "test.sqlite3",
        health_min_free_disk_mb=1,
    )


@pytest.fixture(autouse=True)
def no_national_feeds(monkeypatch):
    """Tests never hit the network: the cycle's national-media collector is a no-op here
    (tests of stability.py call its functions with MockTransport)."""
    from tension_index import runner
    from tension_index.collector import RunResult

    async def quiet(db, client, settings, countries=None):
        return RunResult(source="national", fetched=1)

    monkeypatch.setattr(runner, "collect_stability", quiet)
