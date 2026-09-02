.PHONY: setup run test discover match migrate

setup:
	python3 -m venv .venv
	.venv/bin/pip install -e ".[dev]"
	@test -f .env || cp .env.example .env
	@echo "Done. Edit .env, then put your resume in data/resume.md"

run:
	.venv/bin/uvicorn app.main:app --reload

test:
	.venv/bin/pytest -q

discover:
	.venv/bin/python -m app.cli discover

match:
	.venv/bin/python -m app.cli match

migrate:
	.venv/bin/alembic upgrade head
