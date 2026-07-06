PYTHON := python3.12
PG16_BIN := /opt/homebrew/opt/postgresql@16/bin

.PHONY: check-versions venv install migrate test test-write-integration pg16-start pg16-stop

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
