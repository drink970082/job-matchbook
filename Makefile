# Entry points for the Job Matchbook repo (web app + pipeline worker).
# Thin wrappers over the per-package commands — no new tooling required.

.DEFAULT_GOAL := help
WEB    := apps/web
WORKER := apps/worker
PY     := python3   # the host ships python3, not a bare `python`
DB     := file:$(CURDIR)/db/applications.db  # local shared SQLite (override: make seed-dev DB=...)
COUNT  := 40                                 # rows for seed-dev

.PHONY: help install setup doctor dev build lint test test-web test-worker \
        test-integration test-e2e test-coverage check-schema check-privacy up down health db-push seed-dev \
        eval-score eval-screen eval-seniority

help: ## Show this help
	@grep -E '^[a-zA-Z_-]+:.*?## .*$$' $(MAKEFILE_LIST) \
		| awk 'BEGIN{FS=":.*?## "}{printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

install: ## Install web dependencies
	cd $(WEB) && npm install

setup: install ## Full local setup: web + worker deps, DB, and non-clobbering template copies
	$(PY) -m pip install -r $(WORKER)/requirements.txt -r $(WORKER)/requirements-dev.txt
	$(MAKE) db-push
	@# Only the two inert config templates. resume.txt / personal_profile.txt are
	@# deliberately NOT copied: every resume/*.txt is loaded as a resume version, so a
	@# forgotten placeholder would silently score against "TEMPLATE - REPLACE ME",
	@# while an absent file fails loudly and points at resume/README.md.
	@for f in .env config.yaml; do \
		src=$(WORKER)/$$f.example; dst=$(WORKER)/$$f; \
		if [ -e "$$dst" ]; then echo "kept existing $$dst"; \
		elif [ -f "$$src" ]; then cp "$$src" "$$dst"; echo "created $$dst (fill it in)"; fi; \
	done
	@echo "setup done — run 'make doctor', then edit $(WORKER)/.env and config.yaml"
	@echo "then add your resume: $(WORKER)/resume/resume.txt (see resume/README.md)"

doctor: ## Preflight: report worker prerequisites (exits non-zero only if a core one is missing)
	cd $(WORKER) && $(PY) -m ats_worker.doctor

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
	cd $(WORKER) && $(PY) tools/score_eval.py

eval-screen: ## Hard-requirement accuracy eval vs the screen golden set (249 local Ollama calls: free, ~10min). Gate = zero false disqualification
	cd $(WORKER) && PYTHONPATH=. $(PY) tools/screen_eval.py

eval-seniority: ## Seniority pre-ordering accuracy vs the strong scorer's own verdicts (446 local Ollama calls: free, ~12min). Gate = zero false demotions on a domain=match or notified row
	cd $(WORKER) && PYTHONPATH=. $(PY) tools/seniority_eval.py

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
	$(MAKE) health

health: ## Wait for ats-web + ats-autoheal to report healthy (polls; treats a missing healthcheck as failure)
	@# A fixed `sleep N && docker inspect` reads `starting` and calls it success — the same
	@# defect as asserting `status=running` at t=0. ats-web has a 40s start_period, so poll:
	@# 60 tries x 2s = ~120s per container, comfortably past it.
	@# `NO-HEALTHCHECK` must FAIL, not pass: a container with no healthcheck reports an
	@# empty .State.Health, and treating that as "fine" would silently un-gate this target
	@# the moment someone drops a healthcheck block.
	@# RestartCount is checked too, and it is not belt-and-braces: a crash-looping container
	@# reads `healthy` with `.State.Status` == `running` for most of each cycle, so polling
	@# health alone passes it — the residual of the very defect this target exists to close.
	@# The check is a DELTA against the count at entry, because the cumulative number says
	@# nothing about now (a container that restarted last week is fine).
	@# RESIDUAL, stated rather than papered over: this catches a container that flaps
	@# BEFORE it ever reads healthy. One that comes up healthy and only then starts
	@# crash-looping is passed, because the poll exits on the first `healthy` — dwelling
	@# long enough to see it would slow every `make up` for a case the container's own
	@# restart policy already surfaces in `docker ps`.
	@# `docker compose up --wait` covers most of this and was considered; it does not treat
	@# a MISSING healthcheck as failure, which is the case that silently un-gates us.
	@# The MISSING arm needs `[ -n "$$s" ]`, NOT `|| echo MISSING`: a failing
	@# `docker inspect` still writes an empty line to STDOUT, so the substitution yields
	@# the empty string and `|| echo` never fires — which left an absent container spinning
	@# the whole timeout before failing with a blank status.
	@for c in ats-web ats-autoheal; do \
		printf 'waiting for %s ' "$$c"; ok=0; \
		rc0=$$(docker inspect -f '{{.RestartCount}}' "$$c" 2>/dev/null || echo 0); \
		for i in $$(seq 1 60); do \
			s=$$(docker inspect -f '{{if .State.Health}}{{.State.Health.Status}}{{else}}NO-HEALTHCHECK{{end}}' "$$c" 2>/dev/null); \
			[ -n "$$s" ] || s=MISSING; \
			rc=$$(docker inspect -f '{{.RestartCount}}' "$$c" 2>/dev/null || echo 0); \
			if [ "$$rc" != "$$rc0" ]; then s="crash-looping (RestartCount $$rc0 -> $$rc)"; break; fi; \
			case "$$s" in \
				healthy) ok=1; break ;; \
				unhealthy|NO-HEALTHCHECK|MISSING) break ;; \
			esac; \
			printf '.'; sleep 2; \
		done; \
		if [ "$$ok" = 1 ]; then echo " healthy"; else \
			echo " FAILED ($$s)"; \
			echo "--- docker logs --tail 20 $$c ---"; \
			docker logs --tail 20 "$$c" 2>&1 || true; \
			exit 1; fi; \
	done
	@echo "stack healthy"

down: ## Stop the Docker Compose stack
	docker compose down
