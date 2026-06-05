# Entry points for the ATS repo (web app + pipeline worker).
# Thin wrappers over the per-package commands — no new tooling required.

.DEFAULT_GOAL := help
WEB    := apps/web
WORKER := apps/worker

.PHONY: help install dev build lint test test-web test-worker up down db-push

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
	cd $(WORKER) && python -m pytest

db-push: ## Sync the Prisma schema into the SQLite db
	cd $(WEB) && npx prisma db push

up: ## Build + start the full stack (web + worker) via Docker Compose
	UID=$$(id -u) GID=$$(id -g) docker compose up --build -d

down: ## Stop the Docker Compose stack
	docker compose down
