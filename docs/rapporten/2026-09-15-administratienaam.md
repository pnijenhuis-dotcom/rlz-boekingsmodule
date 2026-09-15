# Administratienaam — bewerkbaar in de module + volgt de bron — 15-09-2026

Opdracht: `opdrachten/gedaan/2026-09-15-odoo-companynaam-volgen.md` (Peter/Cowork 15-09; casus Camping "Nieuwenhoven" → in
Odoo hernoemd naar "Strandpark Zilverduynen" ná het koppelen). Migratie 0144. Canoniek: BESLISSINGEN "ADMINISTRATIENAAM —
BEWERKBAAR + VOLGT DE BRON (Peter 15-09)".
**Werkt in productie: niet gemeten** — eerste meting = ná de deploy van deze commit: data-stap + sync (§ 4).

## 1. Wat er stond

- De administratienaam was in de module nergens te wijzigen (geen veld, geen route) en volgde de bron niet: de wizard kopieert
  de RLZ-/Odoo-naam één keer bij het koppelen; een hernoeming in Odoo (`res.company.name`) of RLZ (`Administrations.Name`)
  bereikte de module nooit. Nieuwenhoven toont daardoor nog "Camping Nieuwenhoven".
- Er is geen gedenormaliseerde naam-kolom (grep `administratie_naam` over `app/*/models.py` = 0): klantenlijst, tellers-cache-DTO,
  combobox en reconciliatie lezen `administratie.naam` live. Geen cache-invalidatie nodig.

## 2. Gebouwd

| Blok | Wat | Waar |
|---|---|---|
| A Naam bewerkbaar | Rij "Naam" bovenaan Instellingen › Administraties › ‹administratie› › Algemeen: naam + herkomst-chip ("volgt Odoo/Reeleezee" of "handmatig"), linkbtn Bewerken → inline invoer + Opslaan/annuleren (Enter/Escape). `PUT /administraties/{id}/naam` (Beheerder-only): whitespace-normalisatie, leeg/> 200 = 422, hoofdletter-ongevoelig bezet bij élke andere administratie (ook gearchiveerd) = 409 mét leesbare reden, zet `naam_bron='mens'`, audit `administratie_naam_gewijzigd` oud→nieuw (`via: handmatig`); zelfde naam = geen audit. Ná opslaan herlaadt de lijst (kop, breadcrumb, chips, klantenlijst). | `app/beheer/administratienaam.py::wijzig_naam`, `router.py`, `frontend/src/instellingen/NaamRij.tsx` |
| B Naam volgt de bron | Migratie 0144: `naam_bron` ('odoo'/'rlz'/'mens', CHECK, DB-default 'mens' = fail-closed), `bron_naam`, `bron_naam_gezien_op`, `naam_gevolgd_op`. Eén leesbron per backend: Odoo `probe.lees_company_naam` (de rechten-probe leest nu via dezelfde functie), RLZ `RlzClient.list_administrations()` via het nieuwe `RlzClient.root()` (zonder administratie-prefix, óók op de gescoped sync-login). Hooks: RLZ `sync_alles_voor_administratie` (ná de vier caches, zelfde client) en Odoo `sync_alles_voor_odoo_administratie` (zelfde leesronde + zelfde lokale transactie als de caches; `odoo_koppeling.company_naam` volgt mee). `verwerk_bronnaam`: bron_naam + gezien_op altijd; `naam_bron` ≠ mens én afwijkend → naam volgt, `naam_gevolgd_op`, audit `administratie_naam_gevolgd` oud→nieuw mét bron; mens → niet overschrijven; bronnaam bezet bij een ander → niet gevolgd (`bezet`, logregel); onleesbaar → `onbekend`, sync blijft groen. `SyncResultaat.naam` + `sync-alles` print `naam=<uitkomst>`. Chip "in Odoo/Reeleezee heet deze administratie nu ‹naam›" + linkbtn "Naam overnemen" (`POST …/naam-overnemen`, houdt 'mens', `via: bron_overgenomen`). | `migrations/versions/0144_…`, `app/db/models.py`, `app/odoo/{probe,sync}.py`, `app/rlz/client.py`, `app/sync/service.py`, `app/cli.py`, `NaamRij.tsx` |
| C Data-stap | CLI `administratie-naam-bron-backfill [--schrijf] [--administratie <uuid>]` — dry-run default. Per actieve administratie de LIVE bronnaam (Odoo read-only client / RLZ root-client): naam == bron (case-/witruimte-ongevoelig) → `naam_bron` = bron + audit `administratie_naam_bron_backfill`; afwijkend → blijft 'mens', bronnaam vastgelegd (chip); al ≠ mens → al_gezet; bron onleesbaar → OVERGESLAGEN (blijft 'mens', zichtbaar). Idempotent. Dry-run in de nameting-allowlist, `--schrijf` door `nameting.sh` geweigerd. | `app/beheer/administratienaam_cli.py`, `scripts/gcp/nameting.sh` |
| D Af | Tests, rol-matrix, gouden set, tsc, docs — § 3. | — |

## 3. Bewijs (lokaal)

| Toets | Uitkomst |
|---|---|
| `tests/beheer/test_administratienaam.py` (service A/B/C, RLZ-root-vorm, RLZ-sync-hook, Odoo-sync-hook incl. `company_naam`, één leesbron, overnemen, backfill + CLI dry-run, router 403/422/409/200, DTO) | 20 groen |
| `tests/security/test_rol_endpoint_gates.py` (rijen `PUT …/naam`, `POST …/naam-overnemen` + Beheerder-only-uitsluiting), `tests/beheer`, `tests/odoo/test_probe.py`, `tests/odoo/test_router.py`, `tests/sync`, `test_migratie_metadata_guard`, `test_nameting_workflow`, `test_dependencies_gedeclareerd` | 705 groen; 9 setup-errors in `test_odoo/test_router.py` bleken mijn eigen fout (een tweede pytest-proces — de CLAUDE.md-guard — draaide parallel en deed de conftest-downgrade "schema platform does not exist"); apart herdraaid: 30 groen |
| `tests/unit` + `tests/keten` (gouden set) | 320 groen, 1 skipped; 16 setup-errors in `test_rlz_client_tempo`/`test_static_frontend` (deadlock + "schema platform does not exist") — oorzaak: de inbox-run `2026-09-15-inbox-pull-untracked` (launchd `claude -p`, klaar 09:11) draaide parallel pytest op dezelfde `boekhouding_test` in dezelfde werkboom; de 16 apart herdraaid ná afloop: 24 groen. Gouden set (tests/keten) volledig groen; `test_keten_guard` niet geraakt (geen wijziging onder app/intake, app/extractie, app/documenten, frontend/src/document) |
| Migratie-afsluitroutine | `make migrate` dev-DB 0143 → 0144 ("Running upgrade 0143 -> 0144"), `alembic check` "No new upgrade operations detected", live op 8011: `GET /instellingen/administraties` 200 mét `naam_bron`, `PUT /administraties/{id}/naam` 200 (zelfde naam, no-op), `scripts/dump_schema.sh` head 0144 (+4 kolommen + CHECK) |
| Frontend | `tsc -b` groen; vitest `NaamRij.test.tsx` 6 groen, `AdministratiesV2`/`InstellingenScreen`/`instellingenApi`/`api` 206 groen; changelog-guard 5 groen |
| Docs-guards | `test_claude_md_beslissingen_verwijzingen` 3 groen; CLAUDE.md 111k tekens |
| Keten-sweep (pixel) | niet gedraaid — geen wijziging in controlescherm/documentenlijst (alleen Instellingen › Administraties) |

## 4. Meetrecept productie (ná deploy; regel Peter 08-09: alleen via de gedeployde job-image)

1. Dry-run lezen: `scripts/gcp/nameting.sh administratie-naam-bron-backfill` → per administratie BRON/MENS/OVERGESLAGEN.
   Verwachting: RLZ-administraties met de wizard-naam = "BRON rlz"; Camping Nieuwenhoven = **"MENS — bron: Strandpark
   Zilverduynen"** (de live Odoo-naam is al anders dan de module-naam — zie beslispunt 1 in BESLISSINGEN).
2. Schrijven: `gcloud run jobs execute rlz-sync --region europe-west4 --args="-m,app.cli,administratie-naam-bron-backfill,--schrijf"`.
3. Zilverduynen: Instellingen › Administraties › Camping Nieuwenhoven › Algemeen toont de oranje chip "in Odoo heet deze
   administratie nu “Strandpark Zilverduynen”" → Peter klikt "Naam overnemen" (één klik; audit `administratie_naam_gewijzigd`
   `via: bron_overgenomen`). Daarna: administratielijst en klantenlijst tonen "Strandpark Zilverduynen".
   Alternatief zonder klik bestaat bewust niet (geen SQL-update op `naam_bron` in code — beslispunt 1).
4. Volgen bewezen: eerstvolgende `sync-alles` (07:00) logt per administratie `naam=gelijk` (of `gevolgd` bij een hernoeming in de
   bron); een latere hernoeming in Odoo van een 'odoo'-administratie geeft `naam=gevolgd` + audit `administratie_naam_gevolgd`.

## 5. Beslispunten voor Peter

1. Nieuwenhoven volgt ná de backfill NIET automatisch (live bronnaam ≠ module-naam → 'mens' + chip). Akkoord met de klik
   "Naam overnemen", of wil je dat de backfill vergelijkt met de bij koppeling vastgelegde `odoo_koppeling.company_naam` (dan
   wordt hij 'odoo' en hernoemt de sync 'm zelf; voor RLZ bestaat zo'n koppelnaam niet)?
2. Nieuwe administraties via de wizard krijgen nu nog 'mens' (DB-default). Vervolg (klein, geen migratie): wizard zet `naam_bron`
   direct op de bron. Nu bouwen of eerst de backfill afwachten?
3. "Naam overnemen" houdt 'mens' — een aparte schakelaar "weer automatisch volgen" is niet gebouwd; nodig?

## 6. Niet gedaan / grenzen

- **Les (herhaald, memory "geen parallelle pytest-runs"):** de launchd-inbox-tick startte tijdens deze interactieve run een tweede
  `claude -p` in dezelfde werkboom (de `.lock` was bij de start gezet maar die run verwijderde 'm bij haar einde); beide sessies
  deelden `boekhouding_test` → deadlock/schema-fouten in twee testronden. Lock opnieuw gezet voor het slot van deze run; structurele
  keuze (één werkboom per sessie / lock-eigenaar toetsen) = beslispunt uit het nazorg-rapport van 15-09.

- Geen DB-unique-index op `administratie.naam` (productie kan historische dubbelen dragen; de service weigert nieuwe botsingen).
- Geen apart tijdlijn-scherm voor de administratie: de audit-regels (`administratie_naam_gewijzigd`/`_gevolgd`/`_bron_backfill`)
  staan in het audit_event mét administratie_id; de detailpagina toont de herkomst-chip + datum-tooltip.
