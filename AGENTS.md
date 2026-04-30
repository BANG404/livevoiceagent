# Repository Guidelines

## Project Structure & Module Organization

This is a Python 3.13 `uv` project for a live voice visitor-registration agent. Runtime code lives under `src/`: `src/agent` contains the LangGraph workflow, domain model, configuration, registration tools, and guard notification logic; `src/voice` contains the FastAPI/Twilio transport layer, audio handling, speech adapters, and app entrypoint. Tests are split into `tests/unit_tests` and `tests/integration_tests`, with shared fixtures in `tests/conftest.py`. Project notes and vendor references live in `DOCS/` and `TODO/`.

## Build, Test, and Development Commands

Use the Makefile targets as the stable interface:

- `make sync` syncs runtime and development dependencies with `uv`.
- `make dev` syncs dependencies and starts LangGraph + FastAPI via `overmind`.
- `make run` starts the local LangGraph dev server.
- `make voice` runs the Twilio/FastAPI webhook server on port `8000`.
- `make test` runs unit tests in `tests/unit_tests`.
- `make integration-tests` runs integration tests in `tests/integration_tests`.
- `make lint` and `make format` run Ruff checks and formatting.

For local TTS/VAD experiments, run `uv sync --dev --extra voice-local`.

## Coding Style & Naming Conventions

Follow the existing Python style: 4-space indentation, type annotations for public functions, and small modules organized by responsibility. Use `snake_case` for functions, variables, test names, and modules; use `PascalCase` for Pydantic models and classes. Prefer structured configuration through `src/agent/config.py` and environment variables instead of hard-coded secrets or URLs. Run `make format` before submitting changes.

## Testing Guidelines

Use `pytest`. Place fast, isolated tests in `tests/unit_tests/test_*.py`; place graph, service-bound, or cross-module tests in `tests/integration_tests/test_*.py`. Add or update tests when changing registration behavior, Twilio webhook handling, audio framing, speech adapters, or configuration loading. Keep tests deterministic and avoid real network calls unless they are explicitly integration behavior.

## Commit & Pull Request Guidelines

Recent history uses Conventional Commit prefixes such as `feat:`, `test:`, `docs:`, and `chore:`. Keep commit messages imperative and scoped to one logical change. Pull requests should include a short summary, commands run (`make test`, `make lint`, etc.), linked issues or task notes, and webhook examples when changing user-visible voice/Twilio behavior.

## Security & Configuration Tips

Copy `.env.example` to `.env` for local development and never commit real API keys, Twilio credentials, WeCom webhook URLs, or generated visitor data. Validate any new environment variable in configuration code and document it in `.env.example` and `README.md`.

## Agent-Specific Instructions

When operating through Codex in this repository, follow `~/.codex/RTK.md`: prefix shell commands with `rtk`, for example `rtk make test` or `rtk git status`.
