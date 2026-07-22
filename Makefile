# Entry points for the Job Matchbook repo (web app + pipeline worker).
# Thin wrappers over the per-package commands — no new tooling required.

.DEFAULT_GOAL := help
WEB    := apps/web
WORKER := apps/worker
PY     := python3   # the host ships python3, not a bare `python`
DB     := file:$(CURDIR)/db/applications.db  # local shared SQLite (override: make seed-dev DB=...)
COUNT  := 40                                 # rows for seed-dev

.PHONY: help install dev build lint test test-web test-worker \
        test-integration test-e2e test-coverage check-schema check-privacy up down db-push seed-dev \
        eval-score

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install web dependencies
	cd $(WEB) && npm install

dev: ## Run the Next.js dev server (http://localhost:3000)
	cd $(WEB) && npm run dev

build: ## Production build of the web app
	cd $(WEB) && npm run build

lint: ## Lint the web app
	cd $(WEB) && npm run lint

test: test-web test-worker ## Run both test suites

test-web: ## Run the web (Jest) suite
	cd $(WEB) && npm test

test-worker: ## Run the worker (pytest) suite
	cd $(WORKER) && $(PY) -m pytest

test-integration: ## Run the integration tiers (worker run_once + web server actions)
	cd $(WORKER) && $(PY) -m pytest -m integration
	cd $(WEB) && npm run test:integration

test-e2e: ## Run the Playwright e2e suite (builds web, seeds a throwaway DB)
	cd $(WEB) && npm run test:e2e

test-coverage: ## Run both suites with coverage (gated by thresholds)
	cd $(WORKER) && $(PY) -m pytest --cov --cov-report=term-missing
	cd $(WEB) && npm run test:coverage

eval-score: ## Verdict-accuracy eval vs the frozen golden set (~70 calls on the default codex backend: free, ~50min; SCORE_BACKEND=claude is PAID)
	$(WORKER)/.venv/bin/python $(WORKER)/tools/score_eval.py

check-schema: ## Fail if worker schema.sql drifts from prisma/schema.prisma
	node tools/check_schema_drift.mjs

check-privacy: ## Fail if a private file (.env, resume, db, config.yaml) is tracked by git
	node tools/check_privacy.mjs

db-push: ## Sync the Prisma schema into the SQLite db
	cd $(WEB) && npx prisma db push

seed-dev: ## Append realistic sample applications to the local db (vars: DB, COUNT)
	node apps/web/prisma/seed-dev.mjs "$(DB)" $(COUNT)

up: ## Build + start the web stack (web + autoheal) via Docker Compose — the worker runs natively, see SPEC §6
	UID=$$(id -u) GID=$$(id -g) docker compose up --build -d

down: ## Stop the Docker Compose stack
	docker compose down
