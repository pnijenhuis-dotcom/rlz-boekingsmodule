PYTHON := python3.12
PG16_BIN := /opt/homebrew/opt/postgresql@16/bin

.PHONY: check-versions venv install migrate test test-write-integration test-read-integration bootstrap-beheerder sync-alles import-env-credentials run pg16-start pg16-stop

# Harde versie-pariteitscheck met productie (Cloud SQL 16, Cloud Run-container op 3.12).
# Lokaal ouder-of-gelijk aan prod is aanvaardbaar om te signaleren; lokaal NIEUWER dan prod
# (bv. de PG18/Python 3.14 die hier standaard stonden) is de gevaarlijke richting: wat hier
# werkt kan in productie stuklopen. Faalt hard met een duidelijke melding bij afwijking.
check-versions:
	@command -v $(PYTHON) >/dev/null 2>&1 || { \
		echo "FOUT: '$(PYTHON)' niet gevonden. Vereist (pint de Cloud Run-container, geen 3.14)."; \
		echo "  Installeer met: brew install python@3.12"; exit 1; }
	@$(PYTHON) -c "import sys; raise SystemExit(0 if sys.version_info[:2] == (3, 12) else 1)" || { \
		echo "FOUT: $(PYTHON) is niet Python 3.12 ($$($(PYTHON) --version))."; exit 1; }
	@test -x "$(PG16_BIN)/pg_ctl" || { \
		echo "FOUT: PostgreSQL 16 niet gevonden op $(PG16_BIN)."; \
		echo "  Installeer met: brew install postgresql@16"; exit 1; }
	@"$(PG16_BIN)/pg_ctl" --version | grep -q ' 16\.' || { \
		echo "FOUT: $(PG16_BIN)/pg_ctl is geen PostgreSQL 16 ($$($(PG16_BIN)/pg_ctl --version))."; exit 1; }
	@echo "Versies OK: $$($(PYTHON) --version) · $$($(PG16_BIN)/pg_ctl --version)"

# PG16 draait via pg_ctl (géén brew services / auto-start bij reboot) — zie README.md.
pg16-start:
	@"$(PG16_BIN)/pg_ctl" -D /opt/homebrew/var/postgresql@16 -l /opt/homebrew/var/log/postgresql@16.log start

pg16-stop:
	@"$(PG16_BIN)/pg_ctl" -D /opt/homebrew/var/postgresql@16 stop

venv: check-versions
	$(PYTHON) -m venv .venv

install: venv
	.venv/bin/pip install -e ".[dev]"

migrate: check-versions
	.venv/bin/alembic upgrade head

test: check-versions
	.venv/bin/pytest

# write_integration is opt-in (pyproject.toml addopts sluit hem standaard uit) — raakt de LIVE
# RLZ-test-administratie. --override-ini negeert addopts zodat -m write_integration niet met
# "not write_integration" botst.
test-write-integration: check-versions
	.venv/bin/pytest -m write_integration --override-ini='addopts=' -s

# read_integration is óók opt-in (net als write_integration): leest live tegen de RLZ-test-
# administratie. Read-only, maar bewust nog steeds niet in de kale run — zie pyproject.toml.
test-read-integration: check-versions
	.venv/bin/pytest -m read_integration --override-ini='addopts=' -s

# Eenmalig, kip-ei-oplossing: uitnodigen is zelf Beheerder-only (zie app/auth/service.py).
# Voorbeeld: make bootstrap-beheerder NAAM="Peter Nijenhuis" EMAIL=peter@nijenhuis.nl
bootstrap-beheerder: check-versions
	.venv/bin/python -m app.cli bootstrap-beheerder --naam "$(NAAM)" --e-mail "$(EMAIL)"

# Nachtelijke sync (fase-vervolg: Cloud Scheduler -> Cloud Run job roept dit aan). Lokaal
# handmatig, of via cron: raakt alleen administraties met werkende .env-credentials.
sync-alles: check-versions
	.venv/bin/python -m app.cli sync-alles

# Eenmalig: de bestaande .env-logins de credential-store in. Voorbeeld:
# make import-env-credentials BEHEERDER_ID=<uuid>
import-env-credentials: check-versions
	.venv/bin/python -m app.cli import-env-credentials --beheerder-id "$(BEHEERDER_ID)"

# Lokale dev-server (tegen boekhouding, niet boekhouding_test — zie app/config.py). --reload
# herlaadt bij codewijzigingen; poort 8000 moet matchen met frontend/vite.config.ts's proxy.
run: check-versions
	.venv/bin/uvicorn app.main:app --reload --port 8000
