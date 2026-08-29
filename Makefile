COMPOSE := docker compose -f docker/compose.yml
RUN := $(COMPOSE) run --rm --no-deps app
RUN_DB := $(COMPOSE) run --rm app

.PHONY: up down logs build migrate revision seed lint format typecheck test test-unit shell gate

up:
	$(COMPOSE) up -d --build

down:
	$(COMPOSE) down

logs:
	$(COMPOSE) logs -f bot worker

build:
	$(COMPOSE) build

migrate:
	$(RUN_DB) alembic upgrade head

# Team lead only: schema and contracts are owned upstream (tech.md 11.2).
revision:
	$(RUN_DB) alembic revision --autogenerate -m "$(m)"

seed:
	$(RUN_DB) python -m scripts.seed

lint:
	$(RUN) ruff check .
	$(RUN) ruff format --check .

format:
	$(RUN) ruff format .
	$(RUN) ruff check --fix .

typecheck:
	$(RUN) mypy app

test:
	$(RUN_DB) pytest --cov=app/domain --cov=app/services --cov-report=term-missing --cov-fail-under=85

test-unit:
	$(RUN) pytest tests/unit tests/contract

shell:
	$(RUN_DB) bash

# Full gate on an ephemeral stack, same steps as CI.
gate:
	docker compose -f docker/compose.ci.yml up --build --abort-on-container-exit --exit-code-from gate
	docker compose -f docker/compose.ci.yml down -v
