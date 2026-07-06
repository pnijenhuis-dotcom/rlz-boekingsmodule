# RLZ Boekingsmodule — backend

FastAPI + SQLAlchemy + Alembic + PostgreSQL. Zie `../CLAUDE.md` en `../docs/BOUWPLAN.md` voor
context en fasering.

## Vereiste versies (hard, niet onderhandelbaar)

- **Python 3.12** — pint de Cloud Run-container. Niet 3.14 (macOS-systeem-Python): een nieuwere
  taalversie lokaal dan in productie is de gevaarlijke richting, want wat hier werkt kan in
  Cloud Run alsnog stuklopen.
- **PostgreSQL 16** — pint Cloud SQL for PostgreSQL (productie). Zelfde argument: lokaal moet
  gelijk zijn aan prod, nooit nieuwer.

`make check-versions` (of gewoon `make venv`/`make test`, die roepen het aan) faalt hard met een
duidelijke foutmelding als een van beide afwijkt. `tests/conftest.py` herhaalt dezelfde check bij
elke `pytest`-run (ook los van `make`), zodat een verkeerde venv of databaseverbinding nooit
stilzwijgend meedraait.

### Installatie van de vereiste versies (Homebrew)

```bash
brew install postgresql@16 python@3.12
```

### PostgreSQL 16 lokaal draaien

**PostgreSQL 16 via `docker-compose.yml`** (repo-root, koppelcontract v1.2) is de weg voor devs/CI
met Docker: `docker compose up -d postgres` maakt zowel `boekhouding` als `boekhouding_test` aan op
poort 5433, credentials identiek aan `.env.example`. Op deze ontwikkelmachine is Docker niet
geïnstalleerd; in plaats daarvan draait een losse Homebrew-PostgreSQL-16-cluster **op poort 5433**
(5432 kan in gebruik zijn door een andere lokale Postgres-installatie, bv. Postgres.app —
expliciet niet gebruikt voor dit project omdat die op een nieuwere major-versie dan prod zit). Kies
één van de twee paden; ze delen dezelfde poort en zijn dus niet gelijktijdig te draaien.

```bash
make pg16-start   # start via pg_ctl — zie let op hieronder
make pg16-stop
```

> **Let op — geen auto-start.** `pg_ctl` start de cluster alleen voor de huidige sessie; er is
> geen `brew services`- of launchd-registratie, dus **na een reboot draait PostgreSQL 16 niet
> vanzelf**. Permanente optie (macOS-launchd-service, start automatisch bij login/boot):
>
> ```bash
> brew services start postgresql@16
> ```
>
> Let dan wel op de poort: de Homebrew-formule luistert standaard op 5432. Zet `port = 5433` in
> `/opt/homebrew/var/postgresql@16/postgresql.conf` vóórdat je naar `brew services` overstapt, om
> een conflict met een eventuele andere lokale Postgres op 5432 te vermijden (dat is ook hoe de
> huidige `pg_ctl`-instantie is geconfigureerd).

Databases: `boekhouding` (dev) en `boekhouding_test` (pytest, wordt bij elke testrun gereset).

```bash
createdb -p 5433 boekhouding
createdb -p 5433 boekhouding_test
```

## Setup

```bash
make install          # venv met python3.12 + alle dependencies (faalt hard bij verkeerde versies)
cp .env.example .env  # DATABASE_URL/APP_DATABASE_URL/TEST_*_URL naar wens aanpassen
make migrate           # alembic upgrade head tegen boekhouding
make test              # pytest — reset + migreert boekhouding_test, draait dan de tests
```

Schrijf-integratietests (marker `write_integration`) draaien alleen als
`TESTADMIN_USERNAME`/`TESTADMIN_PASSWORD` gevuld zijn in `../verkenning/.env` — zie
`tests/integration/test_write_integration.py`.
