.PHONY: help install sync dev run voice test integration-tests lint format

help:
	@echo 'Targets:'
	@echo '  install             Sync runtime dependencies with uv'
	@echo '  sync                Sync project + dev dependencies with uv'
	@echo '  dev                 Sync deps and start LangGraph + FastAPI with overmind'
	@echo '  run                 Start the local LangGraph dev server'
	@echo '  voice               Start the Twilio voice webhook server'
	@echo '  test                Run unit tests'
	@echo '  integration-tests   Run integration tests'
	@echo '  lint                Run Ruff checks'
	@echo '  format              Format with Ruff'

install:
	uv sync --no-dev

sync:
	uv sync

dev: sync
	@command -v overmind >/dev/null 2>&1 || { echo "overmind is required for make dev"; exit 1; }
	@if [ -S ./.overmind.sock ] && ! overmind status >/dev/null 2>&1; then \
		echo "Removing stale Overmind socket ./.overmind.sock"; \
		rm -f ./.overmind.sock; \
	fi
	overmind start -f Procfile.dev

run:
	uv run langgraph dev --no-browser

voice:
	uv run uvicorn voice.app:app --host 0.0.0.0 --port 8000 --reload

test:
	uv run python -m pytest tests/unit_tests -q

integration-tests:
	uv run python -m pytest tests/integration_tests -q

lint:
	uv run python -m ruff check src tests

format:
	uv run python -m ruff format src tests
