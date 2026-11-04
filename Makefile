.PHONY: dev deps up down test lint fmt migrate seed eval web-dev api-dev

API=apps/api
WEB=apps/web

deps:
	cd $(API) && uv sync
	cd $(WEB) && npm install

up:
	docker compose up -d postgres redis redis-http

down:
	docker compose down

dev: up
	$(MAKE) -j2 api-dev web-dev

api-dev:
	cd $(API) && uv run uvicorn app.main:app --reload --port 8000

web-dev:
	cd $(WEB) && npm run dev

migrate:
	cd $(API) && uv run alembic upgrade head

test:
	cd $(API) && uv run pytest -q
	cd $(WEB) && npm test --if-present

lint:
	cd $(API) && uv run ruff check . && uv run ruff format --check . && uv run mypy app
	cd $(WEB) && npm run lint && npm run typecheck

fmt:
	cd $(API) && uv run ruff check --fix . && uv run ruff format .

seed:
	cd $(API) && uv run python -m app.scripts.seed

eval:
	cd $(API) && uv run aura-eval --help
