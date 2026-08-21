.PHONY: help db up down migrate seed api test check bench artwork

BE := backend

help: ## list targets
	@grep -E '^[a-z-]+:.*?##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'

db: ## start Postgres and create the database the integration tests use
	docker compose up -d db
	@until docker compose exec -T db pg_isready -U peblo -d peblo_tv >/dev/null 2>&1; do sleep 1; done
	@docker compose exec -T db psql -U peblo -d postgres -tAc \
		"SELECT 1 FROM pg_database WHERE datname='peblo_tv_test'" | grep -q 1 \
		|| docker compose exec -T db psql -U peblo -d postgres -c "CREATE DATABASE peblo_tv_test"

up: ## build and start the whole stack
	docker compose up -d --build

down: ## stop the stack (keeps volumes)
	docker compose down

migrate: ## apply migrations
	cd $(BE) && .venv/bin/alembic upgrade head

artwork: ## fetch one Unsplash photograph per show into data/artwork/ (run once)
	cd $(BE) && .venv/bin/python -m tools.fetch_artwork

seed: ## load the challenge seed data and print the validation report
	cd $(BE) && .venv/bin/python -m scripts.seed --reset

api: ## run the API with reload
	cd $(BE) && .venv/bin/uvicorn app.main:create_app --factory --reload --port 8000

test: ## backend tests only (DB tests skip without Postgres)
	cd $(BE) && .venv/bin/python -m pytest -q

check: ## everything CI will run — lint, types, tests
	./scripts/check.sh

bench: ## measure the real search query plans (see docs/ROADMAP.md)
	@docker compose exec -T db psql -U peblo -d postgres -c "DROP DATABASE IF EXISTS peblo_bench" >/dev/null
	@docker compose exec -T db psql -U peblo -d postgres -c "CREATE DATABASE peblo_bench" >/dev/null
	@cd $(BE) && BENCH_DATABASE_URL=postgresql+psycopg://peblo:peblo@localhost:5432/peblo_bench \
		.venv/bin/python -m tools.benchmark_search; status=$$?; \
		cd .. && docker compose exec -T db psql -U peblo -d postgres \
			-c "DROP DATABASE IF EXISTS peblo_bench" >/dev/null; \
		echo "(peblo_bench dropped)"; exit $$status
