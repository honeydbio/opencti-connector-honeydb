# Repo-local developer targets (not part of the upstream OpenCTI connector copy).
PYTHON ?= python3

.PHONY: venv lint format test metadata docker check

venv:
	uv venv --python 3.12 .venv
	uv pip install --python .venv/bin/python -r tests/test-requirements.txt -r tools/requirements.txt

lint:
	ruff format --check .
	ruff check .

format:
	ruff format .
	ruff check --fix .

test:
	$(PYTHON) -m pytest -q

metadata:
	$(PYTHON) tools/generate_metadata.py

docker:
	docker build -t opencti-connector-honeydb:dev .

check: lint test metadata
	git diff --exit-code __metadata__/
