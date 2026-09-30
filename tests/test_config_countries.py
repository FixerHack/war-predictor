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
    # Ukraine is not monitored, but exists for replaying the 2022 episode.
    assert get_country("UA").region == "backtest"
    with pytest.raises(KeyError):
        get_country("XX")


def test_model_id_in_provider_is_understood(monkeypatch, capsys):
    monkeypatch.setenv("CLASSIFIER_PROVIDER", "anthropic/claude-haiku-4.5")
    s = Settings(_env_file=None)
    assert (
        s.classifier_provider == "openrouter" and s.classifier_model == "anthropic/claude-haiku-4.5"
    )
    assert "looks like a model id" in capsys.readouterr().err


def test_provider_is_case_insensitive(monkeypatch):
    monkeypatch.setenv("CLASSIFIER_PROVIDER", "OpenRouter")
    assert Settings(_env_file=None).classifier_provider == "openrouter"


def test_bad_setting_gives_a_readable_error(monkeypatch, capsys):
    from tension_index import cli, config

    monkeypatch.setenv("CLASSIFIER_PROVIDER", "gpt")
    config.get_settings.cache_clear()
    try:
        with pytest.raises(SystemExit) as exit_info:
            cli.main(["health"])
    finally:
        config.get_settings.cache_clear()
    assert exit_info.value.code == 2
    err = capsys.readouterr().err
    assert "CLASSIFIER_PROVIDER = 'gpt'" in err and "Traceback" not in err
