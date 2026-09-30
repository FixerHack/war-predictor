# Notes for Claude Code

- Python 3.12, dependencies via uv only (`uv add`, `uv sync`); never pip.
- Before finishing a task: `make check` (ruff check + format check, pytest, plan render) must pass.
- After finishing a task, update its `status` in `roadmap/roadmap.yaml` (done / in_progress / todo / blocked),
  add new tasks there if scope grew, then run `make plan` and commit PLAN.md / PLAN.en.md with the change.
  Never edit PLAN*.md by hand.
- Branches: `main` is default and protected. New work goes to `dev-<area>` (e.g. `dev-tg-bot`), fixes to
  `fix-<what>`, docs to `docs-<what>`. Use the branch listed for the stage in roadmap.yaml.
- Tests must not hit the network: mock HTTP with `httpx.MockTransport`.
- The user writes in Ukrainian; user-facing bot text is Ukrainian; code, comments and commits in English.
- Keep README.md (uk) and README.en.md (en) in sync when either changes.
- The index is a signal-state indicator, never a probability or forecast; keep that wording everywhere.
