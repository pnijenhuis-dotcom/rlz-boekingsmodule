# Dev-runbook — lokaal opstarten

Voor Peter: exacte stappen om de RLZ Boekingsmodule lokaal te starten en te gebruiken.

## 0. Eenmalig per machine (al gedaan als `make install` ooit is gelukt)

- PostgreSQL 16 via Homebrew (`brew install postgresql@16`) — **niet** een nieuwere PG-versie, de
  `check-versions`-target in de Makefile faalt hard als dat niet klopt (prod = Cloud SQL 16).
- Python 3.12 via Homebrew (`brew install python@3.12`) — ook hier faalt `check-versions` hard bij
  een andere versie (Cloud Run-container = 3.12).
- `cd backend && make install` — maakt `.venv` en installeert de package.
- `cd frontend && npm install`.

## 1. Dagelijkse start: `make dev`

Vanaf de repo-root, één commando:

```bash
make dev
```

Dit doet, in volgorde: Postgres 16 starten (genegeerd als hij al draait — dagelijks gebruik, geen
foutmelding bij een tweede keer opstarten), de database bijwerken naar de laatste migratie
(`make migrate`; sinds de migratie-guard in `app/main.py` weigert de backend anders sowieso te
starten met een duidelijke melding), en dan backend + frontend **parallel**. Laat dit
terminalvenster open; **ctrl-C stopt beide** in één keer (geen twee terminals meer nodig om ze
allebei netjes af te sluiten).

Backend draait op `http://localhost:8000`, frontend normaal op `http://localhost:5173` (Vite kiest
automatisch een hogere poort als die bezet is — kijk in de terminal-output naar de regel `Local:
http://localhost:....` voor het echte adres).

**De losse targets blijven bestaan** voor wie liever apart start, alleen één van de twee wil
draaien, of iets wil troubleshooten:

```bash
cd backend && make pg16-start   # alleen Postgres (make pg16-stop om te stoppen)
cd backend && make migrate      # alleen de database bijwerken
cd backend && make run          # alleen de backend, --reload
cd frontend && npm run dev      # alleen de frontend
```

## 2. Eerste Beheerder aanmaken (eenmalig — al gedaan voor Peter)

```bash
cd backend
make bootstrap-beheerder NAAM="Peter Nijenhuis" EMAIL=p.nijenhuis@kempengroep.nl
```

Dit commando weigert als er al een Beheerder bestaat ("er bestaat al een Beheerder") — dat is
correct gedrag, geen bug.

Activeren doe je via het scherm op `/activeren?token=<jouw-token>` in de frontend (zie stap 4) —
daar stel je je eigen wachtwoord in en koppel je een authenticator-app (TOTP, verplicht).

## 3. RLZ-credentials importeren (eenmalig — al gedaan)

```bash
cd backend
make import-env-credentials BEHEERDER_ID=<jouw-gebruiker-id>
```

Leest `verkenning/.env` (nooit `backend/.env`, nooit in git) en zet de bekende
RLZ-webservice-logins (RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_-prefixen) in de
credential-store. Hoeft niet opnieuw als de administraties al gekoppeld zijn.

## 4. Inloggen / activeren in de browser

- **Eerste keer (activatie)**: ga naar `http://localhost:<poort>/activeren?token=<jouw-token>`.
  Stap 1: wachtwoord instellen (minimaal 12 tekens). Stap 2: een geheime sleutel verschijnt —
  voeg die toe aan een authenticator-app (Google Authenticator, 1Password, etc.), typ de 6-cijferige
  code die de app toont, en klik "Bevestigen en inloggen". Je komt daarna direct in de werkvoorraad.
- **Elke volgende keer**: `http://localhost:<poort>/login` — e-mailadres, wachtwoord, en de actuele
  6-cijferige TOTP-code uit je authenticator-app.

## 5. Werkvoorraad gebruiken

- Kies een administratie in de dropdown rechtsboven (alleen administraties waar je scope voor
  hebt — als Beheerder zie je ze allemaal).
- Sleep een PDF of UBL-XML in het uploadvak, of klik erop om een bestand te kiezen. Bij een
  vermoedelijk duplicaat (zelfde sha256) verschijnt een melding en een badge in de lijst — het
  document wordt niet stil overgeslagen.
- Klik op een rij in de documentenlijst voor het detailscherm: status, tijdlijn
  (binnenkomst → extractie → …), het boekvoorstel (grootboek/btw/project per regel, met
  geheugen-voorstellen en afwijkingen gemarkeerd), de checks, en de bijlage zelf (PDF inline, of
  downloadlink). Zijn de checks groen, dan boekt de boekknop echt door naar RLZ (actie 17) —
  dit is geen placeholder meer.
- Documenten kunnen (soft-)verwijderd en hersteld worden via het prullenbak-icoon in de lijst;
  geboekte/ter-accordering-documenten kunnen dat bewust niet (bewaarplicht/lopende accordering).

## Bekende beperkingen van deze slice

- Afwijzen (met verplichte reden) en de vragenworkflow staan nog niet in de UI.
- Klant-autorisatie (accordering) en het e-mail-intake-scherm zijn nog niet gebouwd.
- Geen automatische tests op de React-UI in een echte browser vanuit een geautomatiseerde sessie
  (geen browser-automatiseringstool beschikbaar) — wel volledig geverifieerd via `tsc`, `oxlint`,
  `vitest` en een productie-build; een eigen doorloop in de browser blijft de eerste echte
  klik-voor-klik-test na elke sessie.
