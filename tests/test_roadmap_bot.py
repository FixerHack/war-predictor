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
    assert "# Tension Index — План робіт" in (tmp_path / "PLAN.md").read_text()
    assert "# Tension Index — Project plan" in (tmp_path / "PLAN.en.md").read_text()


def test_branch_names_follow_convention():
    for stage in load(ROOT / "roadmap" / "roadmap.yaml")["stages"]:
        assert stage["branch"] == "—" or stage["branch"].startswith("dev-"), stage["id"]


def test_dispatcher_builds(settings):
    dp = build_dispatcher(settings)
    assert dp.sub_routers


def test_cli_parses():
    args = build_parser().parse_args(["collect", "--countries", "PL,EE", "--notify"])
    assert args.countries == ["PL", "EE"] and args.notify
