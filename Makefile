.PHONY: db-up db-down db-reset seed test

db-up:
	docker compose up -d db

db-down:
	docker compose down

db-reset:
	uv run python -c "from tpa.db import connect, reset_schema; reset_schema(connect())"

seed:
	uv run python scripts/seed.py --seed 1337 --months 24 --load-terms

test:
	uv run pytest -q
