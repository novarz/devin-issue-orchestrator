.PHONY: install test lint run up

install:
	pip install -r requirements-dev.txt

test:
	python -m pytest -v

lint:
	ruff check devin_orchestrator && ruff format --check devin_orchestrator

run:
	uvicorn devin_orchestrator.app:app --reload --port 8000

up:
	docker compose up --build
