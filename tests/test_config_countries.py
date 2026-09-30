import pytest

from tension_index.config import Settings
from tension_index.countries import COUNTRIES, get_country


def test_admin_ids_parsed_from_csv(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "123, 456")
    assert Settings(_env_file=None).telegram_admin_ids == [123, 456]


def test_admin_ids_empty(monkeypatch):
    monkeypatch.setenv("TELEGRAM_ADMIN_IDS", "")
    assert Settings(_env_file=None).telegram_admin_ids == []


def test_country_set():
    assert len(COUNTRIES) == 38
    assert "UA" not in COUNTRIES
    assert get_country("pl").name == "Poland"
    with pytest.raises(KeyError):
        get_country("UA")
