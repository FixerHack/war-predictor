"""Render the roadmap (roadmap/roadmap.yaml) into PLAN.md, PLAN.en.md and the
GitHub Pages progress site."""

from __future__ import annotations

import json
import os
import shutil
from datetime import UTC, datetime
from pathlib import Path

import yaml

STATUSES = ("done", "in_progress", "todo", "blocked")
ICONS = {"done": "✅", "in_progress": "🟡", "todo": "⬜", "blocked": "⛔"}
LABELS = {
    "uk": {"done": "готово", "in_progress": "в роботі", "todo": "заплановано", "blocked": "блок"},
    "en": {"done": "done", "in_progress": "in progress", "todo": "todo", "blocked": "blocked"},
}
TEMPLATE = Path(__file__).resolve().parents[2] / "site" / "index.html"


def _items(value: object) -> list[str]:
    """A changelog side is a list of lines; a single string is one line (not characters)."""
    return [value] if isinstance(value, str) else list(value or [])


def load(path: Path) -> dict:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    seen: set[str] = set()
    for stage in data["stages"]:
        for task in stage["tasks"]:
            if task["status"] not in STATUSES:
                raise ValueError(f"{task['id']}: unknown status {task['status']!r}")
            if task["id"] in seen:
                raise ValueError(f"duplicate task id {task['id']}")
            seen.add(task["id"])
            task.setdefault("owner", "claude")
            if task["owner"] not in ("claude", "human"):
                raise ValueError(f"{task['id']}: owner must be claude or human")
    for entry in data.get("changelog") or []:  # one string = one line, not its characters
        for lang in ("uk", "en"):
            entry[lang] = _items(entry.get(lang))
    return data


def _stats(tasks: list[dict]) -> dict:
    total = sum(t["days"] for t in tasks) or 1
    # In-progress work counts as half done.
    done = sum(t["days"] for t in tasks if t["status"] == "done")
    half = sum(t["days"] for t in tasks if t["status"] == "in_progress") / 2
    counts = {s: sum(1 for t in tasks if t["status"] == s) for s in STATUSES}
    return {
        "percent": round(100 * (done + half) / total),
        "days_total": round(total, 1),
        "days_left": round(total - done - half, 1),
        "counts": counts,
        "days_by_status": {
            st: round(sum(t["days"] for t in tasks if t["status"] == st), 2) for st in STATUSES
        },
        "tasks": len(tasks),
    }


def compute(data: dict) -> dict:
    all_tasks = [t for s in data["stages"] for t in s["tasks"]]
    for stage in data["stages"]:
        stage["stats"] = _stats(stage["tasks"])
    data["stats"] = _stats(all_tasks)
    data["build"] = {
        "built_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "commit": os.environ.get("GITHUB_SHA", "")[:7],
    }
    return data


def render_markdown(data: dict, lang: str) -> str:
    other = "PLAN.en.md" if lang == "uk" else "PLAN.md"
    t = {
        "uk": {
            "title": "План робіт",
            "note": "Файл згенеровано з `roadmap/roadmap.yaml` командою "
            "`uv run tension-index roadmap`. Не редагуйте вручну.",
            "other": "English version",
            "version": "Версія",
            "updated": "оновлено",
            "overall": "Загальний прогрес",
            "left": "лишилось",
            "days": "днів",
            "branch": "Гілка",
            "milestones": "Віхи",
            "decisions": "Зафіксовані рішення",
            "risks": "Ризики",
            "changelog": "Журнал змін",
            "ideas": "Ідеї",
            "owner": "вручну",
        },
        "en": {
            "title": "Project plan",
            "note": "Generated from `roadmap/roadmap.yaml` by `uv run tension-index roadmap`. "
            "Do not edit by hand.",
            "other": "Українська версія",
            "version": "Version",
            "updated": "updated",
            "overall": "Overall progress",
            "left": "left",
            "days": "days",
            "branch": "Branch",
            "milestones": "Milestones",
            "decisions": "Decisions",
            "risks": "Risks",
            "changelog": "Changelog",
            "ideas": "Ideas",
            "owner": "manual",
        },
    }[lang]
    project = data["project"]
    st = data["stats"]
    lines = [
        f"# {project['name_' + lang]} — {t['title']}",
        "",
        f"> {t['note']} [{t['other']}]({other})",
        "",
        f"{t['version']} **{project['version']}**, {t['updated']} {project['updated']}.",
        "",
        f"**{t['overall']}: {st['percent']}%** · {t['left']} ≈ {st['days_left']} {t['days']} "
        f"· " + " · ".join(f"{ICONS[s]} {st['counts'][s]}" for s in STATUSES),
        "",
        f"## {t['milestones']}",
        "",
    ]
    lines += [f"- **{m['id']}** — {m[lang]}" for m in data.get("milestones", [])]
    for stage in data["stages"]:
        s = stage["stats"]
        lines += ["", f"## {stage['id']}. {stage[lang]} — {s['percent']}%", ""]
        if stage.get("goal_" + lang):
            lines += [f"_{stage['goal_' + lang]}_", ""]
        lines += [f"{t['branch']}: `{stage['branch']}`", ""]
        for task in stage["tasks"]:
            owner = f" _({t['owner']})_" if task["owner"] == "human" else ""
            lines.append(f"- {ICONS[task['status']]} **{task['id']}** {task[lang]}{owner}")
            if task.get("note_" + lang):
                lines.append(f"  - {task['note_' + lang]}")
    if data.get("decisions"):
        lines += ["", f"## {t['decisions']}", ""]
        lines += [f"- {d['date']}: {d[lang]}" for d in data["decisions"]]
    if data.get("risks"):
        lines += ["", f"## {t['risks']}", ""]
        lines += [f"- {r[lang]}" for r in data["risks"]]
    if data.get("changelog"):
        lines += ["", f"## {t['changelog']}", ""]
        for entry in data["changelog"]:
            lines.append(f"- **{entry['version']}** ({entry['date']})")
            lines += [f"  - {change}" for change in _items(entry[lang])]
    if data.get("ideas"):
        lines += ["", f"## {t['ideas']}", ""]
        lines += [f"- {idea[lang]}" for idea in data["ideas"]]
    return "\n".join(lines) + "\n"


def build(source: Path, out: Path, plan_dir: Path | None = None) -> dict:
    data = compute(load(source))
    out.mkdir(parents=True, exist_ok=True)
    (out / "roadmap.json").write_text(
        json.dumps(data, ensure_ascii=False, indent=2, default=str), encoding="utf-8"
    )
    shutil.copyfile(TEMPLATE, out / "index.html")
    # Public dashboard page (its data, scores.json, comes from `tension-index export`).
    dashboard = TEMPLATE.parent / "dashboard" / "index.html"
    if dashboard.exists():
        (out / "dashboard").mkdir(exist_ok=True)
        shutil.copyfile(dashboard, out / "dashboard" / "index.html")
    (out / ".nojekyll").write_text("")
    if plan_dir is not None:
        (plan_dir / "PLAN.md").write_text(render_markdown(data, "uk"), encoding="utf-8")
        (plan_dir / "PLAN.en.md").write_text(render_markdown(data, "en"), encoding="utf-8")
    print(f"Roadmap: {data['stats']['percent']}% done, site -> {out}")
    return data
