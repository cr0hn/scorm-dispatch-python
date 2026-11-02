# SCORM_DISPATCH_SRC: checkout of the server (default ../scorm-dispatch), needed by `integration`.
.PHONY: lint typecheck unit contract integration check
lint:
	uv run ruff format --check . && uv run ruff check .

typecheck:
	uv run mypy

unit:
	uv run pytest tests/test_unit.py -q --cov --cov-branch --cov-report=term-missing --cov-fail-under=100

contract:
	uv run pytest tests/test_contract.py -q

# Builds the Go server, starts Postgres + PgBouncer + MinIO in Docker. Fails (not skips) without the source.
integration:
	uv run pytest tests/test_integration.py -q -m integration

check: lint typecheck unit contract integration
