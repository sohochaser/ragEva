.PHONY: setup dev check backend-check frontend-check contract-check e2e-check

UV_CACHE_DIR ?= .local/uv-cache
export UV_CACHE_DIR

setup:
	uv sync --python 3.11 --frozen
	npm ci --prefix frontend

dev:
	uv run --frozen python scripts/dev.py

backend-check:
	uv run --frozen ruff check backend scripts
	uv run --frozen ruff format --check backend scripts
	uv run --frozen mypy
	uv run --frozen pytest

contract-check:
	uv run --frozen python scripts/export_openapi.py --check
	cd frontend && npm run generate:api:check

frontend-check:
	npm --prefix frontend run lint
	npm --prefix frontend run typecheck
	npm --prefix frontend run test
	npm --prefix frontend run build

e2e-check:
	npm --prefix frontend run test:e2e

check: backend-check contract-check frontend-check e2e-check
