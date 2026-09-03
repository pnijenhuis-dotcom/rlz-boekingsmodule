PYTHON := python3.12
PG16_BIN := /opt/homebrew/opt/postgresql@16/bin

.PHONY: intake-herlezen verzamelbak-nabundelen voorraad-hernormaliseer voorraad-rlz-sync odoo-leesbron projecten-cijfers-sync check-versions venv install migrate dump-proxy-prefixes test seed-boekingsgeheugen test-write-integration test-read-integration test-ai-integration bootstrap-beheerder sync-alles reconciliatie bank-sync bank-reconciliatie omzet-reconciliatie doorbelasting-reconciliatie doorbelasting-facturen-herstel accordering-herstel-boeken doorbelasting-seed-kempen materiaal-seed-universal reconciliatie-alles reconciliatie-accepteer reconciliatie-intrekken reconciliatie-acceptaties reconciliatie-uitsluiten reconciliatie-insluiten bank-autoboeken-aan bank-autoboeken-uit verkoop-autoboeken-aan verkoop-autoboeken-uit omzet-autoboeken-aan omzet-autoboeken-uit autoboek-kandidaten-herbereken kantoor-digest uren-meerwerk-aan uren-meerwerk-uit afgeletterd-event-aan afgeletterd-event-uit is-vastgoed-aan is-vastgoed-uit boeken-aan boeken-uit boeken-status ai-extractie-aan ai-extractie-uit webhook-afleveren webhook-aflevering-aan webhook-aflevering-uit webhook-redrive import-env-credentials run pg16-start pg16-stop intake-ai-aan intake-ai-uit

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

# Ververst frontend/proxy-prefixes.json uit de backend-router (proxy-bugklasse-fix 2026-08-07).
# Drift wordt bewaakt door tests/unit/test_proxy_prefixes_dump.py — resultaat mee-committen.
dump-proxy-prefixes:
	.venv/bin/python -m app.proxy_prefixes

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

# ai_integration: echte Claude-API-aanroepen (kost geld, vereist ANTHROPIC_API_KEY in
# backend/.env) — opt-in, nooit in de kale run. Zie tests/integration/test_ai_extractie_integration.py.
test-ai-integration: check-versions
	.venv/bin/pytest -m ai_integration --override-ini='addopts=' -s

# Eenmalig, kip-ei-oplossing: uitnodigen is zelf Beheerder-only (zie app/auth/service.py).
# Voorbeeld: make bootstrap-beheerder NAAM="Peter Nijenhuis" EMAIL=peter@nijenhuis.nl
bootstrap-beheerder: check-versions
	.venv/bin/python -m app.cli bootstrap-beheerder --naam "$(NAAM)" --e-mail "$(EMAIL)"

# Nachtelijke sync (fase-vervolg: Cloud Scheduler -> Cloud Run job roept dit aan). Lokaal
# handmatig, of via cron: raakt alleen administraties met werkende .env-credentials.
sync-alles: check-versions
	.venv/bin/python -m app.cli sync-alles

# Boekingsgeheugen-seed (RLZ PurchaseInvoices+Lines, idempotent/hervatbaar). Voorbeeld:
# make seed-boekingsgeheugen ADMIN_ID=<uuid> [MAANDEN=36]
seed-boekingsgeheugen: check-versions
	.venv/bin/python -m app.cli seed-boekingsgeheugen --administratie-id "$(ADMIN_ID)" $(if $(MAANDEN),--maanden $(MAANDEN),)

# Boeken-failsafe (b): vergelijk geboekte documenten met de werkelijke RLZ-staat, los draaien of
# via cron naast sync-alles. Exit-code 1 bij fouten of afwijkingen (CI/cron-vriendelijk).
reconciliatie: check-versions
	.venv/bin/python -m app.cli reconciliatie

# Bank-sync (rekeningen/mutaties/open posten + afletter-verificatie + Vastly-detectie + opt-in
# autoboeken). Alle administraties, of één: make bank-sync ADMIN_ID=<uuid>
bank-sync: check-versions
	.venv/bin/python -m app.cli bank-sync $(if $(ADMIN_ID),--administratie-id "$(ADMIN_ID)",)

# Bank-failsafe: directe boekingen + geverifieerde afletteringen vergelijken met de werkelijke
# RLZ-staat (OpenAmount/documentstatus — nooit IsComplete). Exit-code 1 bij afwijkingen.
bank-reconciliatie: check-versions
	.venv/bin/python -m app.cli bank-reconciliatie

omzet-reconciliatie: check-versions
	.venv/bin/python -m app.cli omzet-reconciliatie

doorbelasting-reconciliatie: check-versions
	.venv/bin/python -m app.cli doorbelasting-reconciliatie

# Nazorg blok A 26-08: factuur-PDF alsnog op bestaande GEBOEKTE doorbelastingen (beide kanten),
# géén herboeking. Eerst `make doorbelasting-facturen-herstel DRY_RUN=1` (telt alleen), dan zonder.
# Optioneel BEHEERDER_ID=<uuid> als audit-actor (default systeem-actor).
doorbelasting-facturen-herstel: check-versions
	.venv/bin/python -m app.cli doorbelasting-facturen-herstel $(if $(DRY_RUN),--dry-run,) $(if $(BEHEERDER_ID),--beheerder-id "$(BEHEERDER_ID)",)

# Bugfix-run 28-08 (auto-boeken ná laatste klant-akkoord vuurde niet): documenten mét afgeronde
# accordering die niet geboekt staan alsnog boeken via het gefixte pad — NOOIT automatisch.
# Eerst `make accordering-herstel-boeken DRY_RUN=1` (lijst + diagnose per document, niets gewijzigd),
# dan zonder DRY_RUN — optioneel ADMINISTRATIE_ID=<uuid> en MAX=<n> (bv. MAX=1 als proef).
# Volumerem 20/dag/administratie geldt onverkort (run stopt zichtbaar; rest morgen of
# MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE=<n> vóór déze aanroep).
accordering-herstel-boeken: check-versions
	.venv/bin/python -m app.cli accordering-herstel-boeken $(if $(DRY_RUN),--dry-run,) $(if $(ADMINISTRATIE_ID),--administratie-id "$(ADMINISTRATIE_ID)",) $(if $(MAX),--max $(MAX),)

# Losse expliciete seed-stap (migraties zijn schema-only): ADMINISTRATIE_ID=<uuid> BEHEERDER_ID=<uuid>
doorbelasting-seed-kempen: check-versions
	.venv/bin/python -m app.cli doorbelasting-seed-kempen --administratie-id "$(ADMINISTRATIE_ID)" --beheerder-id "$(BEHEERDER_ID)"

materiaal-seed-universal: check-versions
	.venv/bin/python -m app.cli materiaal-seed-universal --administratie-id "$(ADMINISTRATIE_ID)" --beheerder-id "$(BEHEERDER_ID)"

# DE dagelijkse vangrail: alle drie in één run. Bewust géén `make a && make b && make c` —
# die keten sloeg de rest over zodra de eerste afwijkingen vond, precies op de dag dat je de
# andere twee het hardst nodig had. Exit 1 zodra één blok afwijkingen of fouten meldt.
reconciliatie-alles: check-versions
	.venv/bin/python -m app.cli reconciliatie-alles

# Beoordeelde afwijking bewust laten staan (blijft zichtbaar, telt niet meer mee in de exit-code).
# Voorbeeld: make reconciliatie-accepteer BRON=documenten ADMIN_ID=<uuid> VAF=<vingerafdruk> \
#   REDEN="kliktest-documenten na storno in de RLZ-UI opgeruimd" BEHEERDER_ID=<uuid>
reconciliatie-accepteer: check-versions
	.venv/bin/python -m app.cli reconciliatie-accepteer --bron "$(BRON)" --administratie-id "$(ADMIN_ID)" \
		--vingerafdruk "$(VAF)" --reden "$(REDEN)" --beheerder-id "$(BEHEERDER_ID)"

reconciliatie-intrekken: check-versions
	.venv/bin/python -m app.cli reconciliatie-intrekken --bron "$(BRON)" --administratie-id "$(ADMIN_ID)" \
		--vingerafdruk "$(VAF)" --reden "$(REDEN)" --beheerder-id "$(BEHEERDER_ID)"

reconciliatie-acceptaties: check-versions
	.venv/bin/python -m app.cli reconciliatie-acceptaties --administratie-id "$(ADMIN_ID)"

# Administratie niet laten meetellen in de exit-code (bevindingen blijven zichtbaar als
# UITGESLOTEN) — bedoeld voor de test-administratie. Voorbeeld:
# make reconciliatie-uitsluiten ADMIN_ID=<uuid> REDEN="test-administratie" BEHEERDER_ID=<uuid>
reconciliatie-uitsluiten: check-versions
	.venv/bin/python -m app.cli reconciliatie-uitsluiten --administratie-id "$(ADMIN_ID)" \
		--reden "$(REDEN)" --beheerder-id "$(BEHEERDER_ID)"

reconciliatie-insluiten: check-versions
	.venv/bin/python -m app.cli reconciliatie-insluiten --administratie-id "$(ADMIN_ID)" \
		--beheerder-id "$(BEHEERDER_ID)"

# Opt-in-toggle volautomatische bankstappen (vaste regels automatisch boeken), default UIT.
# Voorbeeld: make bank-autoboeken-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
bank-autoboeken-aan: check-versions
	.venv/bin/python -m app.cli bank-autoboeken-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

bank-autoboeken-uit: check-versions
	.venv/bin/python -m app.cli bank-autoboeken-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Opt-in-toggle verkoop-autoboeken (VASTLY-VERKOOP automatisch boeken), default UIT;
# aanzetten kan alleen voor is_vastgoed-administraties.
# Voorbeeld: make uren-meerwerk-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
uren-meerwerk-aan: check-versions
	.venv/bin/python -m app.cli uren-meerwerk-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

uren-meerwerk-uit: check-versions
	.venv/bin/python -m app.cli uren-meerwerk-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Opt-in "Voorraad bijhouden" (voorraad-aansluiting mi-schema, blok D 28-08), default UIT.
# Voorbeeld: make voorraad-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
voorraad-aan: check-versions
	.venv/bin/python -m app.cli voorraad-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

voorraad-uit: check-versions
	.venv/bin/python -m app.cli voorraad-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Voorraad-uitstroom uit RLZ-verkoopfacturen (leesroute, blok A 29-08) — loopt dagelijks mee in
# sync-alles; los voor een eerste/volledige run. Voorbeeld: make voorraad-rlz-sync ADMIN_ID=<uuid> VOLLEDIG=1
voorraad-rlz-sync: check-versions
	.venv/bin/python -m app.cli voorraad-rlz-sync $(if $(ADMIN_ID),--administratie-id "$(ADMIN_ID)") $(if $(VOLLEDIG),--volledig)

# Odoo als leesbron voor een RLZ-administratie (Odoo-adapter blok D 03-09): koppelen mét leesprobe
# (API-key uit $ODOO_API_KEY) of alleen de voorraad-knip zetten. Bv.
#   ODOO_API_KEY=… make odoo-leesbron ADMIN_ID=<uuid> ODOO_URL=https://x.odoo.com COMPANY_ID=3 KNIP=2026-08-01
#   make odoo-leesbron ADMIN_ID=<uuid> KNIP=2026-09-01
odoo-leesbron: check-versions
	.venv/bin/python -m app.cli odoo-leesbron --administratie-id "$(ADMIN_ID)" $(if $(ODOO_URL),--odoo-url "$(ODOO_URL)") $(if $(COMPANY_ID),--company-id $(COMPANY_ID)) $(if $(KNIP),--knip "$(KNIP)") $(if $(API_GEBRUIKER),--api-gebruiker "$(API_GEBRUIKER)")

# Voorraad-hernormalisatie (v2 30-08): alle feitenregels opnieuw door de motor (soort-label artikel/dienst/
# transport, artikelcodes; bekende teksten deterministisch, onbekende via de AI-gates) — géén RLZ-calls;
# rapport per administratie + AI-maandmeter. Voorbeeld: make voorraad-hernormaliseer ADMIN_ID=<uuid> ZONDER_AI=1
voorraad-hernormaliseer: check-versions
	.venv/bin/python -m app.cli voorraad-hernormaliseer $(if $(ADMIN_ID),--administratie-id "$(ADMIN_ID)") $(if $(ZONDER_AI),--zonder-ai)

# Voorbeeld: make verkoop-autoboeken-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
verkoop-autoboeken-aan: check-versions
	.venv/bin/python -m app.cli verkoop-autoboeken-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

verkoop-autoboeken-uit: check-versions
	.venv/bin/python -m app.cli verkoop-autoboeken-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Opt-in omzet-autoboeken (kassarapporten automatisch boeken; GO Peter 01-09, migratie 0096), default UIT.
# Voorbeeld: make omzet-autoboeken-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
omzet-autoboeken-aan: check-versions
	.venv/bin/python -m app.cli omzet-autoboeken-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

omzet-autoboeken-uit: check-versions
	.venv/bin/python -m app.cli omzet-autoboeken-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Nazorg intake-splitsingsbug (02-09): verzamelbak-PDF's sinds SINDS opnieuw lezen met de gefixte keten.
# DRY_RUN=1 telt alleen. Tegen de cloud: scripts/cloud_cli.py intake-herlezen --sinds 2026-08-25 (zie docstring).
intake-herlezen: check-versions
	.venv/bin/python -m app.cli intake-herlezen --sinds $(or $(SINDS),2026-08-25) $(if $(DRY_RUN),--dry-run,)

# Nabundel-nazorg (03-09): verzamelbak-UBL's koppelen aan hun al toegewezen PDF-tegenhanger (UBL = data,
# PDF = beeld, her-extractie; alleen te_controleren/handmatig_afmaken). DRY_RUN=1 eerst. OOK_TOEGEWEZEN=1 neemt de
# dubbelparen mee (03-09: al toegewezen UBL-document naast zijn PDF-document in dezelfde administratie); ADMINISTRATIE=<uuid>
# begrenst de run tot één administratie. Tegen de cloud:
# scripts/cloud_cli.py verzamelbak-nabundelen --dry-run [--ook-toegewezen] (mét DOCUMENT_GCS_BUCKET — leest en schrijft bestanden).
verzamelbak-nabundelen: check-versions
	.venv/bin/python -m app.cli verzamelbak-nabundelen $(if $(DRY_RUN),--dry-run,) $(if $(OOK_TOEGEWEZEN),--ook-toegewezen,) $(if $(ADMINISTRATIE),--administratie $(ADMINISTRATIE),)

# Maandagochtend-digest kantoor los draaien (job rlz-kantoor-digest, ma 07:30; idempotent per week).
kantoor-digest: check-versions
	.venv/bin/python -m app.cli kantoor-digest

# Autoboek-kandidaten-motor los draaien (loopt óók dagelijks mee in sync-alles; blok B 01-09).
autoboek-kandidaten-herbereken: check-versions
	.venv/bin/python -m app.cli autoboek-kandidaten-herbereken

# Tier-vlag factuur_afgeletterd-event (koppelcontract §3 v1.11; activatie wacht op vastgoed)
afgeletterd-event-aan: check-versions
	.venv/bin/python -m app.cli afgeletterd-event-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

afgeletterd-event-uit: check-versions
	.venv/bin/python -m app.cli afgeletterd-event-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Vastgoed-koppeling per administratie (S2-draaiboek R1; UI-toggle op Instellingen › Administraties
# is de hoofdroute, dit is de begeleide terugval). UIT neemt verkoop-autoboeken zichtbaar mee uit.
# Voorbeeld: make is-vastgoed-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
is-vastgoed-aan: check-versions
	.venv/bin/python -m app.cli is-vastgoed-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

is-vastgoed-uit: check-versions
	.venv/bin/python -m app.cli is-vastgoed-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Eenmalig: de bestaande .env-logins de credential-store in. Voorbeeld:
# make import-env-credentials BEHEERDER_ID=<uuid>
import-env-credentials: check-versions
	.venv/bin/python -m app.cli import-env-credentials --beheerder-id "$(BEHEERDER_ID)"

# Boeken-failsafe (a), per-administratie toggle — hetzelfde patroon als bootstrap-beheerder qua
# BEHEERDER_ID-parameter (audit_event-actor). Voorbeeld:
# make boeken-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
boeken-aan: check-versions
	.venv/bin/python -m app.cli boeken-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

boeken-uit: check-versions
	.venv/bin/python -m app.cli boeken-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Overzicht: globale kill switch + per-administratie boeken-toggle (+ effectieve status).
boeken-status: check-versions
	.venv/bin/python -m app.cli boeken-status

# AVG-gate AI-extractie (migratie 0014), zelfde parameterpatroon als boeken-aan/uit. Default
# UIT; alleen de test-administratie/eigen facturen aanzetten tot de AVG-volgorde rond is
# (docs/BOUWPLAN.md). Voorbeeld: make ai-extractie-aan ADMIN_ID=<uuid> BEHEERDER_ID=<uuid>
ai-extractie-aan: check-versions
	.venv/bin/python -m app.cli ai-extractie-aan --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

ai-extractie-uit: check-versions
	.venv/bin/python -m app.cli ai-extractie-uit --administratie-id "$(ADMIN_ID)" --beheerder-id "$(BEHEERDER_ID)"

# Webhook-afleveraar (koppelcontract §3): één verwerk-run — Cloud Scheduler/Cloud Run
# job-entrypoint (zelfde patroon als sync-alles). De toggle is default UIT en zonder
# webhook_doel_url/WEBHOOK_HMAC_SECRET blijven rijen openstaand (failsafe, geen fout).
webhook-afleveren: check-versions
	.venv/bin/python -m app.cli webhook-afleveren

webhook-aflevering-aan: check-versions
	.venv/bin/python -m app.cli webhook-aflevering-aan --beheerder-id "$(BEHEERDER_ID)"

webhook-aflevering-uit: check-versions
	.venv/bin/python -m app.cli webhook-aflevering-uit --beheerder-id "$(BEHEERDER_ID)"

# Intake-AI-toggle (migratie 0029): de platform-brede AVG-gate voor AI op nog-niet-toegewezen
# intake-documenten (tenaamstelling + splitsingsdetectie). Default UIT; env is alleen fallback.
intake-ai-aan: check-versions
	.venv/bin/python -m app.cli intake-ai-aan --beheerder-id "$(BEHEERDER_ID)"

intake-ai-uit: check-versions
	.venv/bin/python -m app.cli intake-ai-uit --beheerder-id "$(BEHEERDER_ID)"

# Re-drive: dead-letter-rijen terug naar openstaand (herstel na bv. langdurige downtime van de
# vastgoed-ontvanger). Optioneel één rij: make webhook-redrive BEHEERDER_ID=<uuid> OUTBOX_ID=<uuid>
webhook-redrive: check-versions
	.venv/bin/python -m app.cli webhook-redrive --beheerder-id "$(BEHEERDER_ID)" $(if $(OUTBOX_ID),--outbox-id "$(OUTBOX_ID)")

# Lokale dev-server (tegen boekhouding, niet boekhouding_test — zie app/config.py). --reload
# herlaadt bij codewijzigingen; poort 8000 moet matchen met frontend/vite.config.ts's proxy.
run: check-versions
	.venv/bin/uvicorn app.main:app --reload --port 8000

# Projectcijfers-sync (projectenmodule 22-08): ververst project_regel_cache uit RLZ voor alle
# administraties mét de uren-&-meerwerk-opt-in — leescache, RLZ blijft de bron van waarheid.
projecten-cijfers-sync: check-versions
	.venv/bin/python -m app.cli projecten-cijfers-sync
