# Makefile for openagentd

.PHONY: all up down run dev test coverage migrate revision build-web build dist clean help

# Default target
all: test

up: ## Start Docker services
	docker compose up -d

down: ## Stop Docker services
	docker compose down

run: ## Start the API server only (no reload, no frontend; :8000)
	uv run uvicorn app.server:app

dev: ## Start backend (:8000 + reload) and frontend (Vite :5173) together
	@command -v bun >/dev/null 2>&1 || { echo "error: 'bun' not found — install from https://bun.sh"; exit 1; }
	@trap 'kill 0' INT TERM EXIT; \
	(uv run uvicorn app.server:app --reload --reload-dir app 2>&1 | sed 's/^/[api] /') & \
	(cd web && bun dev 2>&1 | sed 's/^/[web] /') & \
	wait

test: ## Run tests
	uv run pytest -q

coverage: ## Run tests with coverage report
	uv run pytest --cov=app --cov-report=term-missing tests/

migrate: ## Run Alembic migrations (dev only — production auto-migrates on startup)
	uv run alembic -c app/alembic.ini upgrade head

revision: ## Create a new Alembic revision (usage: make revision MSG="message")
	uv run alembic -c app/alembic.ini revision --autogenerate -m "$(MSG)"

build-web: ## Build web UI and copy into app/_web_dist/
	cd web && bun install && bun run build
	rm -rf app/_web_dist
	cp -r web/dist app/_web_dist

build: build-web ## Build Python wheel (includes bundled web UI)
	uv build

dist: build ## Alias for build

clean: ## Remove build and cache artifacts
	rm -rf .pytest_cache .ruff_cache .coverage .ty_cache htmlcov
	rm -rf app/_web_dist dist
	find . -type d -name "__pycache__" -exec rm -rf {} +

help: ## Show this help message
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "\033[36m%-15s\033[0m %s\n", $$1, $$2}'
