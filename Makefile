-include .env
export

.PHONY: db-up db-down db-scratch db-reset seed test step year players says-no api backtest benchmarks mail-demo

# Without the compose plugin, run the same container directly.
db-up:
	docker compose up -d db 2>/dev/null || docker start jade-tpa-db 2>/dev/null || \
	  docker run -d --name jade-tpa-db -e POSTGRES_USER=tpa -e POSTGRES_PASSWORD=tpa -e POSTGRES_DB=tpa \
	    -p 5433:5432 -v jade-tpa-pgdata:/var/lib/postgresql/data postgres:16

# The database tests reset; never the demo one.
db-scratch:
	(docker compose exec -T db createdb -U tpa tpa_scratch 2>/dev/null || \
	  docker exec jade-tpa-db createdb -U tpa tpa_scratch 2>/dev/null) || true

db-down:
	docker compose down

db-reset:
	uv run python -c "from tpa.db import connect, reset_schema; reset_schema(connect())"

seed:
	uv run python scripts/seed.py --seed 1337 --months 24

test:
	DATABASE_URL=$${TEST_DATABASE_URL:?set TEST_DATABASE_URL to a scratch database; tests reset it} uv run pytest -q

step:
	uv run python scripts/step.py --inbox

year:
	uv run python scripts/step.py --reset --through month-12 --autopilot --metrics

players:
	uv run python scripts/step.py --reset --through month-12 --players --metrics

says-no:
	uv run python scripts/step.py --reset --through month-12 --players --controller-says-no --metrics

api:
	uv run uvicorn tpa.api:app --reload --port 8000

backtest: ## the accrual estimate and the close's controls on General Mills' real 10-Ks (no DB)
	uv run python scripts/backtest.py

benchmarks: ## the played year's statistics beside sourced industry and peer figures (run after make players)
	uv run python scripts/benchmarks.py

mail-demo: ## the Walmart side letter by email: SCENARIO=side-letter|late-backup|amendment
	uv run python scripts/demo_mail.py run $(or $(SCENARIO),side-letter)
