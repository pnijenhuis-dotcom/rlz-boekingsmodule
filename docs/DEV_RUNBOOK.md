# Dev-runbook — lokaal opstarten

Voor Peter: exacte stappen om de RLZ Boekingsmodule lokaal te starten en te gebruiken. Dit runbook
is in deze sessie vers uitgevoerd (niet alleen opgeschreven) — elke stap hieronder is echt gedraaid.

## 0. Eenmalig per machine (al gedaan als `make install` ooit is gelukt)

- PostgreSQL 16 via Homebrew (`brew install postgresql@16`) — **niet** een nieuwere PG-versie, de
  `check-versions`-target in de Makefile faalt hard als dat niet klopt (prod = Cloud SQL 16).
- Python 3.12 via Homebrew (`brew install python@3.12`) — ook hier faalt `check-versions` hard bij
  een andere versie (Cloud Run-container = 3.12).
- `cd backend && make install` — maakt `.venv` en installeert de package.
- `cd frontend && npm install`.

## 1. Postgres 16 starten

**Postgres start niet automatisch na een reboot** (draait via `pg_ctl`, geen `brew services`,
bewust zo gekozen — zie de Makefile-comments). Elke sessie/dag opnieuw:

```bash
cd backend
make pg16-start
```

Stoppen kan met `make pg16-stop` (hoeft niet voor dagelijks gebruik).

## 2. Database op de laatste migratie brengen

```bash
cd backend
make migrate
```

Dit voert alle Alembic-migraties uit tegen de `boekhouding`-database (niet `boekhouding_test`,
die gebruiken alleen de tests). **Gevonden en gefixt deze sessie**: de dev-database stond nog op
migratie 0001 omdat latere migraties alleen ooit tegen de testdatabase waren gedraaid — `make
migrate` haalt hem bij.

## 3. Eerste Beheerder aanmaken (eenmalig — al gedaan voor Peter)

```bash
make bootstrap-beheerder NAAM="Peter Nijenhuis" EMAIL=p.nijenhuis@kempengroep.nl
```

**Dit is in deze sessie al uitgevoerd voor jouw account.** Het commando weigert nu als je het
opnieuw draait ("er bestaat al een Beheerder") — dat is correct gedrag, geen bug. Je
uitnodigingslink staat in het eindrapport van deze sessie (los bericht, niet in dit bestand — een
eenmalig activatietoken hoort niet in een document dat in git terechtkomt).

Activeren doe je via het scherm op `/activeren?token=<jouw-token>` in de frontend (zie stap 5) —
daar stel je je eigen wachtwoord in en koppel je een authenticator-app (TOTP, verplicht).

## 4. RLZ-credentials importeren (eenmalig — al gedaan)

```bash
make import-env-credentials BEHEERDER_ID=<jouw-gebruiker-id>
```

Leest `verkenning/.env` (nooit `backend/.env`, nooit in git) en zet de bekende
RLZ-webservice-logins (RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_-prefixen) in de
credential-store. **Gevonden en gefixt deze sessie**: dit commando gaf altijd "env-vars niet
gevuld" omdat niets `verkenning/.env` laadde buiten de testsuite — `app/cli.py` laadt het bestand
nu zelf.

Dit hoeft niet opnieuw als de administraties al gekoppeld zijn (deze sessie: UNIVERSAL, TESTADMIN,
RUBICON zijn al geïmporteerd).

## 5. Backend starten

```bash
cd backend
make run
```

Draait op `http://localhost:8000` met `--reload` (herlaadt bij codewijzigingen). Laat dit terminal-
venster open staan.

Check: `curl http://localhost:8000/health` → `{"status":"ok"}`.

## 6. Frontend starten

In een tweede terminal:

```bash
cd frontend
npm run dev
```

Draait normaal op `http://localhost:5173`. **Let op**: als die poort al bezet is (bv. door een
vergeten vorige `npm run dev`), kiest Vite automatisch 5174 (of hoger) — kijk in de terminal-output
naar de regel `Local: http://localhost:....` voor het echte adres.

De frontend proxyt `/auth`, `/administraties` en `/health` naar de backend op poort 8000 (config in
`frontend/vite.config.ts`) — dus geen aparte CORS-instellingen nodig voor lokaal gebruik.

## 7. Inloggen / activeren in de browser

- **Eerste keer (activatie)**: ga naar `http://localhost:<poort>/activeren?token=<jouw-token>`.
  Stap 1: wachtwoord instellen (minimaal 12 tekens). Stap 2: een geheime sleutel verschijnt —
  voeg die toe aan een authenticator-app (Google Authenticator, 1Password, etc.), typ de 6-cijferige
  code die de app toont, en klik "Bevestigen en inloggen". Je komt daarna direct in de werkvoorraad.
- **Elke volgende keer**: `http://localhost:<poort>/login` — e-mailadres, wachtwoord, en de actuele
  6-cijferige TOTP-code uit je authenticator-app.

## 8. Werkvoorraad gebruiken

- Kies een administratie in de dropdown rechtsboven (alleen administraties waar je scope voor
  hebt — als Beheerder zie je ze allemaal).
- Sleep een PDF of UBL-XML in het uploadvak, of klik erop om een bestand te kiezen. Bij een
  vermoedelijk duplicaat (zelfde sha256) verschijnt een melding en een badge in de lijst — het
  document wordt niet stil overgeslagen.
- Klik op een rij in de documentenlijst voor het detailscherm: status, tijdlijn
  (binnenkomst → extractie → …), veldvoorstellen uit UBL (indien aanwezig), en de bijlage zelf
  (PDF inline, of downloadlink). De boekknop staat er al maar is bewust uitgeschakeld — de
  boekflow volgt in een volgende sessie.

## Bekende beperkingen van deze slice

- Alleen lezen + uploaden; afwijzen, vragen en boeken zijn nog niet gebouwd.
- Geen automatische tests op de React-UI zelf in een echte browser zijn gedraaid door mij (geen
  browser-automatiseringstool beschikbaar in deze sessie) — wel volledig geverifieerd: het
  volledige backend-contract via curl (login, uploaden, lijst, detail, bijlage-download,
  sessie-vernieuwing), en de frontend via `tsc`, `oxlint`, `vitest` en een productie-build. Jouw
  eigen doorloop vanavond in de browser is de eerste echte klik-voor-klik-test.
