.PHONY: verify test lint build browsers install-skill

verify:
	uv run --extra dev --extra mcp python scripts/verify.py

test:
	uv run --extra dev --extra mcp pytest -q

lint:
	uv run --extra dev ruff check .
	uv run --extra dev ruff format --check .

build:
	uv build

browsers:
	uv run playwright install chromium firefox webkit

install-skill:
	uv run python scripts/install_skill.py
