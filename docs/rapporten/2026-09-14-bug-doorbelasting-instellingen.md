# Bugfix 14-09 — Instellingen › Doorbelasting laadt niet (500 op administratie zonder instellingen-rij)

**Voor Peter, in twee zinnen:** het scherm Instellingen › Doorbelasting vroeg de instellingen op van een administratie
waarvoor nog nooit doorbelasting-instellingen waren opgeslagen, en de code gaf dan een "lege" instelling terug zonder het
standaard-provisiepercentage (5 %) — de database vult dat standaardpercentage namelijk pas in op het moment van
opslaan, niet bij het alleen maar lezen. De server weigerde die lege instelling als antwoord en gaf een foutmelding
(500); nu geeft de code voor zo'n administratie expliciet de standaardstand (5 %, verder leeg) terug, zonder iets op te
slaan, en opent het scherm gewoon.

Melding Peter 14-09 ~15:00, centrale 500-handler, correlatie-id `0f7c36ca-49ba-4524-950b-d674b0ff3a19`.
Opdrachtgrenzen: niet gecommit, geen CLAUDE.md/BESLISSINGEN/WAT_IS_NIEUW-bewerkingen (coördinator); BESLISSINGEN-sectie
en Wat-is-nieuw-regel als scratchpad-bestanden aangeleverd.

## Route / exception / regel

- Route: `GET /doorbelasting/{administratie_id}/instelling` → `backend/app/doorbelasting/router.py::instelling_ophalen`
  → `schemas.InstellingResponse(...)`.
- Exception (productie-log 2026-09-14T13:23:47Z, service `rlz-backend`):
  `pydantic_core.ValidationError: 1 validation error for InstellingResponse`. Het veld staat niet in de log;
  `provisie_percentage: Decimal` is het enige niet-Optional veld en is in de test bewezen de boosdoener.
- Wortel: `service.haal_instelling_op` gaf voor een administratie zonder rij in `boekhouding.doorbelasting_instelling`
  een kaal `DoorbelastingInstelling(administratie_id=…)` terug. Een SQLAlchemy kolom-`default=` geldt pas bij INSERT,
  dus op dat transient object is `provisie_percentage` `None` → response-validatie faalt → 500.
- Dataconditie: een administratie die het doorbelastingscherm opent zonder ooit instellingen te hebben opgeslagen.
  Dezelfde `None` zou in `provisie_over(netto, None)` (checks/preview, accordeur-wachtrij-bulk) een `TypeError` geven.

## Fix

Eén bron voor de niet-opgeslagen standaardstand (`backend/app/doorbelasting/models.py`):
`STANDAARD_PROVISIE_PERCENTAGE = Decimal("5.00")` + classmethod `DoorbelastingInstelling.standaard(administratie_id)`
(transient, nooit `session.add` — lezen schrijft niets, de rij ontstaat pas bij de eerste PUT). Gebruikt door:
`haal_instelling_op` (de route), `_check_invoer` (checks + provisie-preview) en `verdeling_per_doelentiteit_bulk`
(accordeur-wachtrij). Regel voor de toekomst: een ORM-object nooit kaal construeren als "default-stand" — kolom-defaults
bestaan pas ná INSERT.

**Fix van de eerdere (afgebroken) agent beoordeeld:** de opzet was goed en is overgenomen. Eén fout hersteld:
`STANDAARD_PROVISIE_PERCENTAGE` werd in `service.py` gebruikt zonder import → `NameError` in
`verdeling_per_doelentiteit_bulk` voor élke administratie zonder rij (dat had de accordeur-wachtrij geraakt). De nieuwe
bulk-test ving dit op de eerste run; import toegevoegd aan het `app.doorbelasting.models`-importblok.

## Sweep — zusterroutes van het scherm (frontend `doorbelastingApi.ts` + `DoorbelastingInstellingen.tsx`)

| Route (bij laden / gebruik) | Toets op dataconditie | Uitkomst |
|---|---|---|
| `GET /administraties/{id}/doorbelasting-instelling` (toggle, bij laden) | onbekende administratie | 404 via `BeheerFout`, geen 500 — ok |
| `GET /doorbelasting/{id}/instelling` (bij laden) | geen rij | **was 500 → gefixt** |
| `GET /doorbelasting/{id}/mappings` (bij laden) | lege tabel, gearchiveerde doelentiteit, ontbrekende doel-koppeling | alleen DB-rijen; elk niet-Optional DTO-veld is NOT NULL in het model; `doel_administratie_id`/ledger-id's Optional — ok |
| `GET /administraties/{doel}/grootboek` (per doel, `useDoelGrootboek`) | lege sync-cache, geen scope op het doel | lege lijst / 403 (frontend vangt `ApiError`) — ok |
| `GET /doorbelasting/{id}/mappings/kandidaat-doelen` (dialoog) | geen mappings, doel-GB niet in cache | lege lijst / `provisie_voorstel=None` — ok |
| `GET /doorbelasting/{id}/mappings/{m}/projecten` (`useDoelProjecten`) | niet-onboarded doel, onbekende mapping, geen scope | `[]` / 404 / 403 — ok |
| `GET /doorbelasting/{id}/opruimlijst` (Scan-knop) | bron-administratie zonder RLZ-credential (Odoo, nog niet gekoppeld, ingetrokken) mét gestorneerde/vervallen runs | **onafgevangen `GeenRlzCredentials` → 500 (de doel-kant ving dat wél af) → gefixt:** zichtbare fout-regel "bron-administratie heeft geen RLZ-credentials (meer) — N verkoop-concept(en) niet controleerbaar"; de doel-kant wordt nog steeds gecontroleerd |

Backend-brede sweep op "kaal geconstrueerd ORM-object als default teruggeven" (script over alle `Base`-subklassen:
`or <Model>(` / `return <Model>(` / toewijzing zonder `.add(` binnen 25 regels): twee treffers —
`documenten/duplicaat_afvoer.py::Groep` is een lokale dataclass (vals alarm); `uren/dossier.py:321`
`VeldwerkerDossier(…)` zet de gelezen defaults (`herinneringen_teller`, `geblokkeerd`) expliciet en de overige gelezen
kolommen zijn nullable → geen bug (niet aangeraakt: ander werkgebied). `doorbelasting/boeken.py:709` heeft zijn
`session.add` verderop — vals alarm.

## Tests

- Nieuw `backend/tests/doorbelasting/test_instelling_api.py` (8): valkuil-unit (kaal object → `None`; `standaard()` →
  5,00 + lege verwijzingen), route zonder rij → 200 + exact `{"provisie_percentage": "5.00", …None}` én de tabel blijft
  leeg, servicelaag, PUT → GET leest de rij, `review_data` zonder rij (provisie € 5,00 over € 100, checks blokkeren op
  ontbrekende btw/omzet-GB), run-route 200 zonder rij, `verdeling_per_doelentiteit_bulk` zonder rij.
- `backend/tests/doorbelasting/test_opruimlijst.py` +1: bron zonder credential = zichtbare fout, doel-kant blijft
  gecontroleerd.
- **Rood-bewijs:** met de oude regel in `haal_instelling_op` tijdelijk teruggezet (geen `git stash`) gaven de
  route-tests `assert 500 == 200` met exact `pydantic_core.ValidationError: 1 validation error for InstellingResponse`
  (2 failed, 1 passed); regel hersteld → 16/16 groen.
- Uitkomsten (eigen test-database `a` via `pytest_blok.sh`):
  - `tests/doorbelasting/test_instelling_api.py tests/doorbelasting/test_opruimlijst.py`: **16 passed**.
  - `tests/doorbelasting` volledig: **158 passed** (140 s).
  - `tests/accordering` (wachtrij raakt de bulk-verdeling: `test_doorbelasting_in_flow.py`,
    `test_wachtrij_querytelling.py`, `test_boeken_na_akkoord.py`, `test_opruimrun_28_08.py`): **29 passed** (31 s; een eerste run met 16 errors was een `DeadlockDetected` door een gelijktijdige tweede pytest op dezelfde test-DB — herhaald alleen: groen).
- Ruff: geen nieuwe meldingen — `service.py` (16) en `models.py` (1) dragen E501's die op HEAD al identiek aanwezig
  waren (gecontroleerd tegen een HEAD-kopie met dezelfde config); `reconciliatie.py` en beide testbestanden schoon.

## Gewijzigde bestanden

- `backend/app/doorbelasting/models.py` — `STANDAARD_PROVISIE_PERCENTAGE` + `DoorbelastingInstelling.standaard()`.
- `backend/app/doorbelasting/service.py` — `haal_instelling_op`, `_check_invoer`, `verdeling_per_doelentiteit_bulk` via de
  ene bron; ontbrekende import toegevoegd.
- `backend/app/doorbelasting/reconciliatie.py` — bron-kant opruimlijst vangt `GeenRlzCredentials` af.
- `backend/tests/doorbelasting/test_instelling_api.py` (nieuw), `backend/tests/doorbelasting/test_opruimlijst.py` (+1).
- `docs/rapporten/2026-09-14-bug-doorbelasting-instellingen.md` + regel in `docs/rapporten/INDEX.md`.

## Werkt in productie

**werkt in productie: niet gemeten** — meetrecept: ná deploy opent Peter Instellingen › Doorbelasting voor dezelfde
administratie; dezelfde gcloud-logquery (op nieuwe correlatie-id's / `textPayload` "Onverwachte fout bij GET
/doorbelasting") moet geen 500 meer tonen.
