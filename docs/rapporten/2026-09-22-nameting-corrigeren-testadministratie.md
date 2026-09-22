# Nameting "Corrigeren…" (storno actie 19 + opnieuw klaarzetten) ná de deploy van 21-09 — RLZ-testadministratie (22-09, poging 2)

Opdracht `opdrachten/gedaan/2026-09-22-nameting-corrigeren-testadministratie.md` (vervolg op `docs/rapporten/2026-09-21-corrigeren-geboekt-document.md`,
BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)"). Poging 1 (inbox-run 22-09 10:42) stierf ná
vijf minuten op de sessielimiet ("You've hit your session limit · resets 12:30pm"); de WIP-branch
`wip/2026-09-22-nameting-corrigeren-testadministratie` (dbce16b) bevatte uitsluitend de verplaatsing inbox → lopend en blijft ter controle
staan. Peter keek niet mee; keuzes staan onder "Keuzes".

**Één regel voor Peter:** de feature staat sinds 21-09 17:59 NL in productie, maar de nameting kon de storno-cyclus NIET draaien: de
RLZ-testadministratie "Administratiekantoor Nijenhuis (test)" is op 30-08 gearchiveerd en archiveren trekt de webservice-login in — er
staat geen credential meer, dus élke corrigeer-actie zou daar 503 geven. Niemand heeft de route sinds de deploy aangeraakt (0 × POST
corrigeren, 0 × 5xx). De schrijvende stappen zijn een klikpunt van jou (dearchiveren mét de TESTADMIN-login, dan de acht stappen onder
"Klikpunt"); de lees-only meetlat staat nu als nameting-onderdeel `corrigeren`, zodat het bewijs ná je klik als bot-bestand op main komt.

## Werkt in productie — per stap

| Stap | Uitkomst | Werkt in productie |
|---|---|---|
| 0 deploy-check | service én álle 17 jobs op `1018bcf` (≥ `c43111e`, deploy-run 21-09 15:53–15:59 UTC); `main..origin/main` = 0 | ja (code live sinds 21-09 17:59 NL) |
| 1 inkoop op de testadministratie (boeken → Corrigeren… → herboeken → terugweg) | niet uitvoerbaar: testadministratie gearchiveerd, `boeken_ingeschakeld` false, 0 credentials → klikpunt Peter | **niet gemeten** |
| 2 idempotentie (409 `al_gecorrigeerd`) + blokkade-route (aangifte) | vereist stap 1; aangifte-blokkade op de testadministratie niet meetbaar zonder ingediende aangifte | **niet gemeten** |
| 3 request-log `POST …/corrigeren` | sinds de deploy 3 requests, alle drie probes van poging 1 zonder token (401/401/404); 0 × 200, 0 × 5xx; audit `document_gecorrigeerd` 0 | **niet gemeten** (geen verkeer; wél 0 fouten) |
| meetlat als dispatch-onderdeel | `nameting.yml` onderdeel `corrigeren` + querybibliotheek `correcties` GEBOUWD (deze commit) | niet gemeten (gaat mét deze deploy live; vervolg-opdracht 23-09) |

## Stap 0 — deploy-check

```
gcloud run services describe rlz-backend --region europe-west4 → …/backend:1018bcf356c7c0ea447d43dd6cc0ed9bc869e1b6
gcloud run jobs list --region europe-west4 --format='value(name,spec.template.spec.template.spec.containers[0].image)'
  → 17 jobs, alle 1018bcf (rlz-reconciliatie inbegrepen; het `template.template.…`-pad uit de opdrachttekst geeft een lege waarde —
    het juiste veld is `spec.template.spec.template.spec.containers[0].image`, zoals de F3-scripts al gebruiken)
git rev-list --count main..origin/main → 0
gh run list --workflow deploy.yml → c43111e completed success 2026-09-21T15:53:50Z → 15:59:40Z (= 17:59 NL)
```
Groen. De corrigeer-routes (`GET …/corrigeer-toets`, `POST …/corrigeren`) staan sinds 21-09 17:59 NL in productie.

## Stap 1 — waarom de storno-cyclus niet gedraaid is (feiten, leesreplica)

`scripts/gcp/db_lezen.sh` (leesreplica `rlz-sql2-lees`, als nameting@, READ ONLY, `--als` Beheerder `2f2262cd…`):

| Feit | Waarde |
|---|---|
| Testadministratie | `faae29c5-d197-4c24-a704-be2eae91fe49` "Administratiekantoor Nijenhuis (test)", `rlz_admin_id` `8dbfb856-d75b-4ec3-9124-c8b739fe3bc5` (= `TESTADMIN_RLZ_ADMIN_ID` in `tests/integration/test_boekflow_write_integration.py`) |
| `gearchiveerd_op` | 2026-08-30 10:05:38 UTC (`actief` false) |
| `boeken_ingeschakeld` | false |
| `platform.rlz_credential` | 0 rijen voor deze administratie (75 in totaal) — `archiveer_administratie` roept `trek_credential_in` aan (`app/beheer/service.py`), dat is bedoeld gedrag |
| Odoo-koppeling | geen rij (de Odoo-generale van 04-09 is ontkoppeld) |
| Documenten | 6 geboekt (RLZ-04-00002006/2010/2014/2023/2024/2033, juli–aug), 3 ter_accordering (DEMO-2026-08xx, 18-08), 1 te_controleren (verkoop, 09-08), 8 verwijderd |
| Audit `document_gecorrigeerd`/`_mislukt` | 0 (scope testadministratie én NULL-scope) |

Gevolg: `corrigeren.toets`/`corrigeer` lopen via de credential-seam → `GeenRlzCredentials` → **503** op de testadministratie; uploaden en
boeken kan er evenmin (boeken uit, administratie uit de werkvoorraad). De opdrachttekst ("upload in de web-app op de RLZ-testadministratie")
veronderstelde een actieve testadministratie mét login — die stand bestaat sinds 30-08 niet meer. Het bouwrapport van 21-09 had dit niet
getoetst (les hieronder). Geen enkele andere administratie komt in aanmerking: de regel "schrijftests uitsluitend op de testadministratie
mét TEST-referentie" (CLAUDE.md "Testdata (v1.3-afspraak)") is hard; ik heb niets gedearchiveerd, geen credential gezet en niets geschreven.

## Stap 2 — idempotentie en blokkade-route

Niet meetbaar zonder stap 1. Aanvulling voor het klikpunt: de zes geboekte augustus-stukken van de testadministratie zijn volgens
`verkenning/odoo-verkenning.md` (r. 671) in RLZ "ná het testen opgeruimd" — de toets (`GET …/corrigeer-toets`, alleen lezen; de dialoog
doet niets vóór "Storneren en opnieuw klaarzetten") hoort daar `beschikbaar` false mét blokkade `verdwenen` + route "Opnieuw boeken" te geven.
Dat is een gratis lees-only meting van de blokkade-route zodra de credential terug is (stap 8 van het klikpunt).

## Stap 3 — request-log en audit (lees-only, gemeten)

Cloud Logging, `httpRequest.requestUrl:"/corrigeren" OR :"/corrigeer-toets"`, sinds 2026-09-21T16:00Z:

```
2026-09-22T08:45:48Z  POST 401  …/administraties/00000000-…/documenten/00000000-…/corrigeren        0,007 s
2026-09-22T08:46:25Z  GET  401  …/administraties/1bda74d3-…/documenten/29c5c5bf-…/corrigeer-toets    0,004 s
2026-09-22T08:46:25Z  GET  404  …/administraties/1bda74d3-…/documenten/29c5c5bf-…/corrigeer-toetsX   0,007 s
```
Drie requests, alle drie tokenloze probes uit poging 1 van deze opdracht (10:45–10:46 NL, run 10:42–10:48); geen mens raakte de route.
**0 × 200, 0 × 409, 0 × 5xx.** Audit `document_gecorrigeerd` / `document_correctie_mislukt`: 0 rijen (testadministratie-scope én NULL-scope).
De BLOW-stukken RLZ-04-00000357/358 uit de aanleiding zijn dus óók nog niet gecorrigeerd (klikwerk Peter, klantadministratie).

## Gebouwd in deze run — de meetlat als dispatch-onderdeel (regel 21-09: "niet gemeten" = vervolg-opdracht + onderdeel)

Het bouwrapport van 21-09 leverde de vervolg-opdracht wél maar géén dispatch-onderdeel — en de opdracht steunde op een klikpunt dat niemand
kon uitvoeren. Gedicht:

1. **`.github/workflows/nameting.yml` onderdeel `corrigeren`** (alleen op verzoek, niet in `alles`; uitgesloten van de VGG-tak; eigen
   `OORDEEL_BRON`): (1) request-log van beide corrigeer-routes sinds de deploy (methode/status/latency/URL); (2)
   `scripts/gcp/nameting.sh rlz-lezen --administratie "Nijenhuis (test)" --pad PurchaseInvoices --filter "startswith(Reference,'TEST-CORRIGEREN')"`
   (exit 1 "geen credential" = uitkomst, geen fout); (3) `scripts/gcp/nameting.sh db-lezen correcties --administratie "Nijenhuis (test)"`.
   Oordeelregel: `Oordeel: POST corrigeren 200 = N, 409 = M, 5xx beide routes = K — werkt in productie: ja | niet gemeten (klikpunt open) | ROOD`.
   `via_gh_onderdeel corrigeren` in `nameting.sh` (patroon jobs-start: geen CLI-commando).
2. **Querybibliotheek `app/lezen/queries/correcties.sql`** (scope administratie, `dagen` optioneel, default 30): audit
   `document_gecorrigeerd`/`document_correctie_mislukt` mét `nieuwe_waarde` (reden, oud boekstuk, oud extern id) náást de huidige stand
   (status, `boek_cyclus`, `rlz_boekstuknummer`). Live-vorm op de replica gedraaid: 0 rijen (verwacht).
3. **Guards:** `test_nameting_workflow.py::test_onderdeel_corrigeren_alleen_op_verzoek_en_lees_only` (if-tak, beide scripts, request-log-
   filter, niet in alles, OORDEEL_BRON, oordeel-extractie via het échte shellfragment) + `::test_nameting_sh_kent_onderdeel_corrigeren`;
   options-regex bijgewerkt; `test_lezen.py` eist `correcties` in de bibliotheek. De request-log-opdracht is in exact de workflow-vorm
   lokaal gedraaid (tabel hierboven; P200 = 0, P5XX = 0).

## Klikpunt Peter — de storno-cyclus op de testadministratie (letterlijk, ná deze deploy)

Alle stappen in de web-app; niets hiervan raakt een klantadministratie. Referentie `TEST-CORRIGEREN-2026-09-22` (of de dag van klikken).

1. Instellingen › Administraties → zoek "Nijenhuis (test)" (gearchiveerde tonen) → **Dearchiveren** → vul de TESTADMIN-webservice-login in
   (dezelfde login als `verkenning/.env` voor de write-integratietests; de rechten-probe moet groen zijn — 422 = login/rechten, niets gewijzigd).
2. Op de detailpagina van de testadministratie de toggle **Boeken** AAN (staat sinds 30-08 uit).
3. Werkvoorraad › Administratiekantoor Nijenhuis (test) → upload een klein test-PDF → controlescherm: bestaande testcrediteur, referentie
   `TEST-CORRIGEREN-2026-09-22`, factuurdatum vandaag, één regel netto € 100,00 + 21 % (€ 21,00) → **Boeken in RLZ** → wacht tot de lijst
   "Geboekt · RLZ-04-…" toont (boekstuknummer A noteren).
4. Open het document (toggle "Toon afgehandelde documenten" of via Archief) → ⋯ → **Corrigeren…** → de dialoog toont vooraf "beschikbaar"
   (geen blokkades; aangifte testadministratie open, niet betaald, geen doorbelasting) → reden `TEST nameting corrigeren 22-09` →
   **Storneren en opnieuw klaarzetten** → toast + gele balk "Gecorrigeerd — reden … · vorige boeking A gestorneerd (actie 19)", status
   klaar om te boeken.
5. Direct nogmaals ⋯ → Corrigeren… → verwacht: de dialoog meldt dat het document al gecorrigeerd is (409 `al_gecorrigeerd`) en herlaadt.
6. Btw-bedrag van de regel op € 20,00 zetten → **Boeken in RLZ** → boekstuknummer B ≠ A op 22-09 (de duplicaatcheck is groen: het oude
   concept van 22-09 is als eigen keten uitgezonderd; bron ná de klik: `db-lezen correcties` toont boek_cyclus 1 + oud boekstuk A).
7. Terugweg testdata: ⋯ → Corrigeren… → reden `TEST nameting terugweg 22-09` → het TEST-stuk (€ 120,00 incl., bron `db-lezen correcties`) staat weer als concept
   in RLZ en lokaal op klaar om te boeken (tweede audit van 22-09) — laat het zo staan (geen geboekt TEST-stuk
   over; nooit verwijderen in RLZ; het concept mag blijven).
8. Bonus (alleen kijken): op het augustus-document met referentie `KLIKTEST-ACC-1` (€ 121,00, geboekt 11-08, `db-lezen document-feiten`
   id `f3f5c5be`) ⋯ → Corrigeren… → verwacht blokkade "verdwenen" mét route "Opnieuw boeken" als het RLZ-stuk is opgeruimd — de
   dialoog **niet** bevestigen (annuleren).
9. Daarna: toggle Boeken weer UIT en, als de testadministratie niet in de kantoorbrede lijsten hoort, opnieuw archiveren (trekt de
   credential weer in — het onderdeel `corrigeren` leest dan de rlz-kant niet meer, request-log en `db-lezen correcties` wél).
10. Meting: `gh workflow run nameting -f onderdeel=corrigeren` (of wacht op de vervolg-opdracht van 23-09 09:00) → bot-bestand
    `verkenning/nameting-corrigeren-<dd-mm>.txt` op main mét de oordeelregel.

## Keuzes (Peter keek niet mee)

1. **Niets geforceerd.** Dearchiveren vereist de TESTADMIN-webservice-login (`dearchiveer_administratie` doet admin-pin + rechten-probe en
   schrijft de credential) — die login staat in `verkenning/.env` (Read-deny, secrets-terrein) en hoort niet door een CC-run in productie
   gezet te worden. Een andere administratie gebruiken is uitgesloten (TEST-referentie-regel). Dus: klikpunt, mét de letterlijke stappen.
2. **De meetlat is een dispatch-onderdeel geworden**, niet alleen een klikpunt in een rapport: zodra Peter klikt, levert `onderdeel=corrigeren`
   het bewijs als bot-bestand op main — het antwoord komt als bestand, niet als belofte (regel 21-09).
3. **Vervolg-opdracht mét herlegging.** `opdrachten/inbox/2026-09-23-nameting-corrigeren-testadministratie-na-klikpunt.md` (`niet vóór:
   2026-09-23 09:00`) draait het onderdeel; is er dan nog geen `POST corrigeren` 200, dan legt de run zichzelf terug in de inbox mét
   `niet vóór:` een dag later (rij (k)-mechanisme, hoogstens drie keer, daarna `mislukt/` mét het klikpunt) — geen lege rapporten stapelen.
4. **Request-log-onderdeel via `gcloud logging read` in de workflow zelf** (zoals `jobs-start` `gcloud run jobs list` doet): nameting@
   heeft `logging.viewer`; de guard `test_productie_aanroepen_alleen_via_de_nameting_scripts` verbiedt alleen execute/deploy/sql/secrets/iam.
5. **Geen WAT_IS_NIEUW-regel:** niets klantzichtbaars veranderd.

## Poort — poging 2

| Poort | Uitkomst |
|---|---|
| gerichte set (`test_nameting_workflow.py` + `tests/lezen/test_lezen.py`) | 47 passed |
| ruff op de eigen regels | schoon (E501 in dit bestand is voorbestaand op andere regels) |
| `bash -n scripts/gcp/nameting.sh` + YAML-parse `nameting.yml` | ok |
| `tsc -b` (volledige werkboom) | schoon (exit 0) |
| vitest volledig | 248 bestanden, 1909 tests groen (21 s) |
| gouden set frontend `scripts/keten_sweep.sh` | eerst 10/11 (a_universal_nederland detail 14,6 % pixelverschil), herdraai `KETEN_ALLEEN=a_universal_nederland` → 2/2 gelijk (0,000 %) = render-flake van de PDF-viewer (memory 20-09), géén baseline-verversing; geen frontend-wijziging in deze run |
| pytest volledig (incl. `tests/keten`) | 7117 passed, 2 skipped, 21 deselected (56:22, `.scratch/corrigeren-p2-pytest.log`) |
| `alembic check` | n.v.t. — geen migratie, geen modelwijziging |

## Documentatie

BESLISSINGEN: alinea "Gemeten 22-09" onder "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)" + registerrij-status;
`docs/regels/werkvoorraad-controlescherm.md` (alinea "Gemeten 22-09"); `docs/regels/werkloop-productie.md` (les: een nameting die schrijft
op de testadministratie toetst éérst de stand van die administratie — gearchiveerd/credential — en het bouwrapport levert het
dispatch-onderdeel zelf); CLAUDE.md werkvoorraad rij 8; dit rapport + INDEX; opdracht → gedaan mét kopregel; vervolg-opdracht in de inbox.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT, kopregel "Domeinen"): `docs/regels/werkvoorraad-controlescherm.md` (379 regels bij het lezen;
391 regels ná deze run), `docs/regels/werkloop-productie.md` (244 regels bij het lezen; 260 regels ná deze run).
