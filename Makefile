# ═══════════════════════════════════════════════════════════════════
# Setup Engine Quality Gates
#
# Quality gates ordered by diagnostic severity — if Gate 1 fails,
# later gates are less meaningful.
#
#   make help          Show all targets
#   make gates         Run all 5 gates
#   make all           Full CI (gate-check + identity + backend + frontend)
# ═══════════════════════════════════════════════════════════════════

.PHONY: help gate-identity gate-1 gate-2 gate-3 gate-4 gate-5 gate-6-load gate-7-chaos \
        gate-market-parity gates gate-check frontend-lint frontend-test frontend \
        phase2-type-gate phase2-reliability golden-update load-baseline-update all

# ── Tooling ─────────────────────────────────────────────────────────

# Use venv python if available (local dev), fall back to system python (CI)
PYTHON = $(shell [ -x backend/venv/bin/python ] && echo ./venv/bin/python || echo python)
PYTEST = cd backend && $(PYTHON) -m pytest
NVM_ACTIVATE = export NVM_DIR="$$HOME/.nvm" && [ -s "$$NVM_DIR/nvm.sh" ] && . "$$NVM_DIR/nvm.sh" || true

# ── Gate 1: Detector Correctness ────────────────────────────────────
# Detectors produce correct outputs, contracts are honored, schemas validate.

GATE_1 = \
  tests/unit/test_detector_interface_contract.py \
  tests/unit/test_detector_subtasks_c3a_c4a_c6a.py \
  tests/unit/test_detector_fixtures_se_g1.py \
  tests/unit/test_setup_engine_contract.py \
  tests/unit/test_setup_engine_report_schema.py \
  tests/unit/test_setup_engine_screener.py \
  tests/unit/test_setup_engine_parameters.py \
  tests/unit/test_aggregator_execution_pipeline.py

# ── Identity Invariants (Fail Fast) ──────────────────────────────────
# Canonical-key uniqueness, alias-key integrity, and identity contracts.

GATE_IDENTITY = \
  tests/unit/test_theme_identity_invariants_ci.py

# ── Gate 2: Temporal Integrity ──────────────────────────────────────
# No future-data leakage, data policies enforce sufficiency.

GATE_2 = \
  tests/unit/test_temporal_integrity_no_lookahead.py \
  tests/unit/test_setup_engine_data_policy.py \
  tests/unit/test_setup_engine_score_trace.py \
  tests/unit/test_setup_engine_readiness.py

# ── Gate 3: Integration Coverage ────────────────────────────────────
# Round-trip persistence, feature flags, query pipeline, path parity.

GATE_3 = \
  tests/unit/test_setup_engine_persistence.py \
  tests/unit/test_setup_engine_feature_flag.py \
  tests/integration/test_setup_engine_query_integration.py \
  tests/unit/test_backfill_setup_engine.py \
  tests/parity/test_scan_parity.py \
  tests/unit/test_scan_path_parity.py

# ── Gate 4: Performance Baselines ───────────────────────────────────
# Runtime budget regression (blocking in CI).

GATE_4 = \
  tests/performance/test_setup_engine_performance.py \
  tests/performance/test_theme_pipeline_performance.py

# ── Gate 5: Golden Regression ───────────────────────────────────────
# Snapshot-pinned detector, aggregator, and scanner outputs.

GATE_5 = \
  tests/unit/golden/test_golden_detectors.py \
  tests/unit/golden/test_golden_aggregator.py \
  tests/unit/golden/test_golden_scanner.py \
  tests/unit/golden/test_golden_rrg.py

# ── Market-Parity Gate (E6) ─────────────────────────────────────────
# US parity and non-US correctness for the market-normalization epic.
# Runs independently of SE gates; gate-check sweeps it in via the
# *parity* glob.

GATE_MARKET_PARITY = \
  tests/parity/test_market_parity_e6.py

# All gate files (used by gate-check)
ALL_GATE_FILES = $(GATE_1) $(GATE_2) $(GATE_3) $(GATE_4) $(GATE_5) $(GATE_MARKET_PARITY)


# ═══════════════════════════════════════════════════════════════════
# Targets
# ═══════════════════════════════════════════════════════════════════

help: ## Show available targets
	@echo "Setup Engine Quality Gates"
	@echo "══════════════════════════════════════════════════════════"
	@grep -E '^[a-zA-Z0-9_-]+:.*?## .*$$' $(MAKEFILE_LIST) | \
	  awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-18s\033[0m %s\n", $$1, $$2}'

# ── Backend Gates ───────────────────────────────────────────────────

gate-1: ## Detector correctness
	$(PYTEST) $(GATE_1) -v --tb=short

gate-identity: ## Theme identity invariants
	$(PYTEST) $(GATE_IDENTITY) -v --tb=short

gate-2: ## Temporal integrity
	$(PYTEST) $(GATE_2) -v --tb=short

gate-3: ## Integration coverage
	$(PYTEST) $(GATE_3) -v --tb=short

gate-4: ## Performance baselines
	$(PYTEST) $(GATE_4) -v --tb=short

gate-5: ## Golden regression
	$(PYTEST) $(GATE_5) -v --tb=short

gate-6-load: ## Per-market load/soak harness (E9.3) — requires Redis; not gated per-PR
	$(PYTEST) tests/load/test_per_market_load.py -v --tb=short -m load

gate-7-chaos: ## Per-market fault-isolation chaos tests (E9.4) — requires Redis; not gated per-PR
	$(PYTEST) tests/load/test_failure_isolation.py -v --tb=short -m load

load-baseline-update: ## Regenerate the committed load baseline (use sparingly, intentionally)
	LOAD_TEST_UPDATE_BASELINE=1 $(PYTEST) tests/load/test_per_market_load.py -v --tb=short -m load

gate-market-parity: ## E6 US parity and non-US correctness (T6.5)
	$(PYTEST) $(GATE_MARKET_PARITY) -v --tb=short

gates: ## Run all gates sequentially (SE + market-parity)
	$(MAKE) gate-1
	$(MAKE) gate-2
	$(MAKE) gate-3
	$(MAKE) gate-4
	$(MAKE) gate-5
	$(MAKE) gate-market-parity

gate-check: ## Verify all SE test files are assigned to a gate
	@echo "Checking that all SE test files are assigned to a gate..."
	@FAIL=0; \
	for f in $$(find backend/tests -type f -name '*.py' \( \
	  -name 'test_*setup_engine*.py' -o \
	  -name 'test_*detector*.py' -o \
	  -name 'test_*backfill_setup*.py' -o \
	  -name 'test_golden_*.py' -o \
	  -name 'test_*temporal*.py' -o \
	  -name 'test_*parity*.py' -o \
	  -name 'test_*aggregator*.py' \
	\) | sed 's|^backend/||' | sort); do \
	  FOUND=0; \
	  for g in $(ALL_GATE_FILES); do \
	    if [ "$$f" = "$$g" ]; then FOUND=1; break; fi; \
	  done; \
	  if [ $$FOUND -eq 0 ]; then \
	    if [ $$FAIL -eq 0 ]; then echo "ERROR: Unassigned SE test files:"; FAIL=1; fi; \
	    echo "  $$f"; \
	  fi; \
	done; \
	if [ $$FAIL -eq 1 ]; then exit 1; fi; \
	echo "All SE test files are assigned to a gate."

# ── Frontend ────────────────────────────────────────────────────────

frontend-lint: ## Lint frontend code
	@$(NVM_ACTIVATE) && cd frontend && npm run lint

frontend-test: ## Run frontend tests
	@$(NVM_ACTIVATE) && cd frontend && npm run test:run

frontend: frontend-lint frontend-test ## Frontend lint + test

# ── Phase 2 Reliability ─────────────────────────────────────────────

phase2-type-gate: ## Focused Phase 2 type-contract checks (touched modules)
	cd backend && $(PYTHON) scripts/check_phase2_type_contracts.py

phase2-reliability: phase2-type-gate ## Alias for Phase 2 reliability gate bundle

# ── Utilities ───────────────────────────────────────────────────────

golden-update: ## Regenerate golden snapshots for review
	$(PYTEST) tests/unit/golden/ -v --tb=short --golden-update

all: gate-check gate-identity gates phase2-reliability frontend ## Full CI (gate-check + identity + backend gates + phase2 reliability + frontend)

# ── Docker Deployment ───────────────────────────────────────────────
# One-liners for rebuilding + migrating the Docker stack so you don't have
# to remember the full compose invocation.
#
#   make docker-deploy                 # build + up + migrate (homelab combo)
#   make docker-deploy HTTPS=1         # include Caddy HTTPS overlay (VPS)
#   make docker-verify                 # sanity-check deps, fonts, migration, chart URL
#
# Overridable variables:
#   COMPOSE   full compose command prefix   (default: sudo docker compose)
#   ENV_FILE  env file                      (default: .env.docker)
#   HTTPS     set to 1 to add the HTTPS overlay
#   PUBLIC_URL public origin for endpoint check (default from .env.docker)
#   SYMBOL    stock code used by docker-verify (default: 2330)

.PHONY: docker-build docker-up docker-migrate docker-deploy docker-verify \
        docker-logs docker-restart docker-down

COMPOSE      ?= sudo docker compose
ENV_FILE     ?= .env.docker
COMPOSE_BASE  = -f docker-compose.yml -f docker-compose.prod.yml
COMPOSE_HTTPS = $(if $(filter 1 true yes,$(HTTPS)),-f docker-compose.https.yml,)
DC            = $(COMPOSE) $(COMPOSE_BASE) $(COMPOSE_HTTPS) --env-file $(ENV_FILE)
PUBLIC_URL   ?= $(shell grep -E '^PUBLIC_BASE_URL=' $(ENV_FILE) 2>/dev/null | cut -d= -f2- | sed 's:/*$$::')
SYMBOL       ?= 2330

docker-build: ## Rebuild backend + frontend images (matplotlib + CJK fonts + JS)
	$(DC) build --no-cache backend frontend

docker-up: ## Recreate all services (applies new .env.docker vars)
	$(DC) up -d

docker-migrate: ## Apply DB migrations inside the backend container
	$(DC) exec backend alembic upgrade head

docker-deploy: ## Full redeploy: build + up + migrate
	$(MAKE) docker-build
	$(MAKE) docker-up
	$(MAKE) docker-migrate
	@echo "✅ Deploy complete. Run 'make docker-verify' to sanity-check."

docker-verify: ## Sanity-check chip charts deployment (deps, fonts, migration, endpoint)
	@echo "── alembic current ─────────────────────────────"
	@$(DC) exec backend alembic current || true
	@echo "── matplotlib ──────────────────────────────────"
	@$(DC) exec backend python -c "import matplotlib; print('matplotlib', matplotlib.__version__)" || true
	@echo "── CJK fonts ───────────────────────────────────"
	@$(DC) exec backend sh -c "fc-list | grep -i 'noto.*cjk' | head -3" || echo "  (fc-list unavailable)"
	@echo "── public chart endpoint ($(SYMBOL)) ───────────"
	@if [ -n "$(PUBLIC_URL)" ]; then \
	  curl -sI "$(PUBLIC_URL)/api/v1/chip/chart/$(SYMBOL).png?kind=daily" | head -5; \
	else \
	  echo "  PUBLIC_BASE_URL not set in $(ENV_FILE); skipping endpoint check"; \
	fi

docker-restart: ## Restart backend + celery beat/general workers without rebuilding
	$(DC) restart backend celery-beat celery-general celery-datafetch

docker-logs: ## Tail backend logs (Ctrl-C to stop)
	$(DC) logs -f --tail=100 backend

docker-down: ## Stop the stack (keeps volumes/data)
	$(DC) down

