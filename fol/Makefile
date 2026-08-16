.PHONY: install test lint format clean dev typecheck

install:
	uv sync --all-groups --all-extras

test:
	pytest -v --timeout=30

test-unit:
	pytest tests/unit -v

test-integration:
	pytest tests/integration -v

lint:
	ruff check .
	mypy core/ modules/

format:
	ruff format .
	ruff check --fix .

typecheck:
	mypy core/ modules/ --strict

clean:
	rm -rf .pytest_cache .ruff_cache .mypy_cache htmlcov
	rm -rf data/logs/*.log

dev:
	uv run python -m core.app start --debug
