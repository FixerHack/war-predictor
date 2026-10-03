import json
from pathlib import Path

from tension_index.bot.app import build_dispatcher
from tension_index.cli import build_parser
from tension_index.roadmap import build, load

ROOT = Path(__file__).resolve().parents[1]


def test_roadmap_is_valid_and_renders(tmp_path):
    data = build(ROOT / "roadmap" / "roadmap.yaml", tmp_path / "site", plan_dir=tmp_path)
    assert 0 <= data["stats"]["percent"] <= 100
    assert (tmp_path / "site" / "index.html").exists()
    assert json.loads((tmp_path / "site" / "roadmap.json").read_text())["stages"]
    assert "# Індекс напруги: Європа — План робіт" in (tmp_path / "PLAN.md").read_text()
    assert "# Tension Index: Europe — Project plan" in (tmp_path / "PLAN.en.md").read_text()


def test_branch_names_follow_convention():
    for stage in load(ROOT / "roadmap" / "roadmap.yaml")["stages"]:
        assert stage["branch"] == "—" or stage["branch"].startswith("dev-"), stage["id"]


def test_dispatcher_builds(settings):
    dp = build_dispatcher(settings)
    assert dp.sub_routers


def test_cli_parses():
    args = build_parser().parse_args(["collect", "--countries", "PL,EE", "--notify"])
    assert args.countries == ["PL", "EE"] and args.notify


def test_every_bot_text_has_both_languages():
    from tension_index.i18n import LANGS, TEXTS

    for key, entry in TEXTS.items():
        assert set(entry) == set(LANGS), key


def test_package_version_matches_roadmap():
    from tension_index import __version__

    assert str(load(ROOT / "roadmap" / "roadmap.yaml")["project"]["version"]) == __version__


def test_changelog_lines_are_lists(tmp_path):
    """A changelog side written as one string is one line (PLAN.md once listed its letters)."""
    from pathlib import Path

    import yaml

    raw = yaml.safe_load(Path("roadmap/roadmap.yaml").read_text(encoding="utf-8"))
    assert all(isinstance(e[lang], list) for e in raw["changelog"] for lang in ("uk", "en"))
    data = load(Path("roadmap/roadmap.yaml"))
    data["changelog"][0]["uk"] = "Один рядок"
    src = tmp_path / "roadmap.yaml"
    src.write_text(yaml.safe_dump(data, allow_unicode=True), encoding="utf-8")
    plan = build(src, tmp_path / "site", plan_dir=tmp_path)
    assert plan["changelog"][0]["uk"] == ["Один рядок"]
    assert "  - Один рядок" in (tmp_path / "PLAN.md").read_text(encoding="utf-8")


def test_rebuilds_are_identical_with_source_date_epoch(tmp_path, monkeypatch):
    """publish_pages.sh skips the push when nothing changed: the build must be repeatable."""
    monkeypatch.setenv("SOURCE_DATE_EPOCH", "1790000000")
    first = build(ROOT / "roadmap" / "roadmap.yaml", tmp_path / "a", plan_dir=tmp_path)
    second = build(ROOT / "roadmap" / "roadmap.yaml", tmp_path / "b", plan_dir=tmp_path)
    assert first["build"]["built_at"] == second["build"]["built_at"] == "2026-09-21T14:13:20+00:00"
