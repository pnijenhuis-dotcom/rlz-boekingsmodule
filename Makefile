SHELL := /bin/bash
PG16_BIN := /opt/homebrew/opt/postgresql@16/bin

.PHONY: dev

# Eén commando voor de dagelijkse start (zie docs/DEV_RUNBOOK.md): Postgres (tolerant als hij al
# draait), de database bijwerken, en dan backend + frontend parallel — ctrl-C stopt allebei. De
# losse targets (backend/Makefile: pg16-start, migrate, run; frontend: npm run dev) blijven
# gewoon bestaan voor wie liever apart start of alleen één van de twee wil.
dev:
	@echo "→ Postgres 16 (genegeerd als al actief)…"
	-@$(MAKE) -C backend pg16-start
	@"$(PG16_BIN)/pg_isready" -h localhost -p 5433 >/dev/null 2>&1 || { \
		echo "FOUT: Postgres 16 niet bereikbaar op localhost:5433, ook niet na pg16-start."; \
		echo "  Log: /opt/homebrew/var/log/postgresql@16.log"; exit 1; }
	@echo "→ make migrate…"
	@$(MAKE) -C backend migrate
	@echo "→ backend (poort 8000) + frontend (poort 5173) — ctrl-C stopt beide…"
	@trap 'kill 0' EXIT INT TERM; \
	( cd backend && make run ) & \
	( cd frontend && npm run dev ) & \
	wait
