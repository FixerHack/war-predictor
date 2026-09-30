# Notes for Claude Code

- Python 3.12, dependencies via uv only (`uv add`, `uv sync`); never pip.
- Before finishing a task: `make check` (ruff check + format check, pytest, plan render) must pass.
- After finishing a task, update `roadmap/roadmap.yaml`: task `status` (done / in_progress / todo / blocked),
  optional `note_uk`/`note_en`, bump `project.version` (+0.0.1 per task, +0.1.0 per finished stage),
  set `project.updated`, add a `changelog` entry on top; new decisions -> `decisions`, risks -> `risks`.
  Tasks only a person can do get `owner: human`. Then `make plan` and commit PLAN.md / PLAN.en.md.
  Never edit PLAN*.md by hand. Keep `pyproject.toml` / `__init__.py` version equal to `project.version`.
- Never create branches with auto-generated names (e.g. `claude/...`); merge finished work into `main`.
- Branches: `main` is default and protected. New work goes to `dev-<area>` (e.g. `dev-tg-bot`), fixes to
  `fix-<what>`, docs to `docs-<what>`. Use the branch listed for the stage in roadmap.yaml.
- Tests must not hit the network: mock HTTP with `httpx.MockTransport`.
- The user writes in Ukrainian; don't address them by name. Bot texts live in `i18n.py` (uk + en, both
  required); code, comments and commits in English.
- Scale numbers live in `config/weights.yaml`, not in code; the war status list `config/conflicts.yaml`
  is changed only after human review.
- Keep README.md (uk) and README.en.md (en) in sync when either changes.
- The index is a signal-state indicator, never a probability or forecast; keep that wording everywhere.
