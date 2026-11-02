# SCORM_DISPATCH_SRC: checkout of the server (default ../scorm-dispatch), needed by `integration`.
PYTHONS ?= 3.11 3.12 3.13 3.14
.PHONY: lint typecheck unit contract matrix integration check
lint:
	uv run ruff format --check . && uv run ruff check .

typecheck:
	uv run mypy

unit:
	uv run pytest tests/test_unit.py -q --cov --cov-branch --cov-report=term-missing --cov-fail-under=100

contract:
	uv run pytest tests/test_contract.py -q

# unit (100% coverage) + contract on every supported minor, each in its own venv
matrix:
	@for v in $(PYTHONS); do echo "== Python $$v"; \
	  UV_PROJECT_ENVIRONMENT=.venv-$$v uv run --python $$v pytest tests/test_unit.py tests/test_contract.py -q \
	    --cov --cov-branch --cov-fail-under=100 --cov-report=term:skip-covered || exit 1; done

# Builds the Go server, starts Postgres + PgBouncer + MinIO in Docker. Fails (not skips) without the source.
integration:
	uv run pytest tests/test_integration.py -q -m integration

check: lint typecheck matrix integration
