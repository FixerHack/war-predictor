# Shortcuts for local development (macOS / Linux). Everything goes through uv.
.PHONY: setup lint fmt test gateway-test check plan site pages bot collect health

setup:        ## install deps, create .env and DB, run tests
	./scripts/bootstrap.sh

lint:
	uv run ruff check .
	uv run ruff format --check .

fmt:
	uv run ruff check --fix .
	uv run ruff format .

test:
	uv run pytest -q

check: lint test gateway-test plan

gateway-test: ## tests of the separate claude-gateway tool (gateway/)
	cd gateway && uv run --frozen pytest -q

plan:         ## regenerate PLAN.md / PLAN.en.md and the site from roadmap/roadmap.yaml
	uv run tension-index roadmap --out _site

site: plan    ## preview the progress page at http://localhost:8000
	cd _site && uv run python -m http.server 8000

pages:        ## publish the progress page to the gh-pages branch (no GitHub Actions needed)
	./scripts/publish_pages.sh

bot:
	uv run tension-index bot

collect:
	uv run tension-index collect

health:
	./scripts/healthcheck.sh
