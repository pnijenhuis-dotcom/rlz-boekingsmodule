# Intake — facturen@kempengroep.nl als tweede postvak DIRECT gelezen, verwerkt-administratie op Message-ID (INBOX + Spam, gelezen én ongelezen), postvak-bewaking "ontvangen vs verwerkt", lees-only dubbele mailbox-audit (Peter 22-09)

**Datum:** 23-09-2026 (nachtrun, inbox-opdracht) · **Opdracht:** `opdrachten/gedaan/2026-09-22-intake-tweede-postvak-facturen-kempengroep-direct-plus-postvakbewaking-en-message-id.md` · **BESLISSINGEN:** "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)" · **Migratie:** 0171
**Werkt in productie: niet gemeten** — deze commit is nog niet gedeployd; de eerste échte run is de deploy + `rlz-intake-imap-kempengroep` (*/10) + `rlz-reconciliatie` 06:30. De dubbele mailbox-audit (opdracht D) kon in deze run NIET tegen productie draaien: alleen de job-image mét beide IMAP-credentials kan de postvakken lezen, `nameting@` heeft geen secrets en die image bestaat pas ná deploy. Het antwoord voor Peter komt als bot-bestand via het nieuwe dispatch-onderdeel `intake-postvak-audit` (vervolg-opdracht `opdrachten/inbox/2026-09-23-nameting-intake-postvak-audit-herstelrun-en-forward-uit.md`, niet vóór 23-09 09:00); het meetrecept + invulskelet staat in `docs/rapporten/2026-09-23-intake-postvak-audit.md`.

## Poging 2 (23-09 nacht, cc-inbox rij (j3))

Poging 1 (23-09 00:43–01:37) bouwde alles hieronder maar eindigde vóór de volledige suite klaar was; het ongecommitte werk stond als WIP-commit `fb69f83` op branch `wip/2026-09-22-intake-tweede-postvak-facturen-kempengroep-direct-plus-postvakbewaking-en-message-id` (blijft ter controle staan). Poging 2 begon met `git merge --squash` van die branch en vond twee restpunten: (1) `tests/intake/test_mailbody.py::test_controlescherm_dto_draagt_herkomst_mail` vergeleek het volledige `herkomst_mail`-dict en kende de drie nieuwe velden `kanaal`/`postvak_adres`/`uit_spam` nog niet — verwachting bijgewerkt (de velden zijn additief); (2) 19 × E501 in eigen nieuwe regels (`bewaking.py`, `postvak_audit.py`, `nu_verwerken.py`, `verwerkt.py`) — handmatig gewikkeld, geen gedragswijziging. Daarna de volledige poort (zie § Poort).

## Aanleiding en feiten

Peter 22-09: "er zijn facturen gemaild die niet in onze module staan". De intake las alléén `UNSEEN` in de INBOX van facturen@ak-nijenhuis.nl en gebruikte de IMAP-gelezen-vlag als verwerkt-administratie. Een groot deel van de facturen komt binnen op facturen@kempengroep.nl (Workspace-account "facturen algemeen") en werd vandaar automatisch doorgestuurd. Drie verliespaden die de module nooit zag:

- Gmail stuurt eigen spam-/duplicaatclassificaties niet door.
- Doorsturen breekt SPF; strikte-DMARC-afzenders landen bij ak-nijenhuis in Spam, en Spam werd nooit gelezen.
- Een mens die de mailbox open heeft zet berichten op gelezen vóór de intake ze ziet.

Stand 22-09 14:2x (Cowork + Peter): IMAP org-breed aan, app-wachtwoord "RLZ intake" gemaakt, secret `INTAKE_KEMPENGROEP_IMAP_WACHTWOORD` (versie 1, user-managed europe-west4 — de org-policy `gcp.resourceLocations` weigert automatic/global) mét `secretAccessor` voor run-jobs@ door Peter gezet. Het declaraties@-kanaal (blok 3 bundel 08-09) blijkt nooit een job in deploy.yml gekregen te hebben (bijvangst; de bewaking meldt dat als OVERGESLAGEN, geen FOUT).

## Wat er gebouwd is

### A — kanaal `facturen_kempengroep` + job `rlz-intake-imap-kempengroep`

- `app/documenten/betaalstatus.py`: `KANAAL_FACTUREN_KEMPENGROEP`, `KANALEN`, `POSTVAK_ADRES_PER_KANAAL`; CHECK-constraint op `intake_bericht.kanaal` verruimd (0171).
- Settings `intake_kempengroep_imap_host/poort/gebruiker/wachtwoord`; `ImapInstellingen.voor_kanaal("facturen_kempengroep")` mét env-prefix `INTAKE_KEMPENGROEP_IMAP`.
- CLI-alias `intake-postvak-kempengroep-verwerken` (identiek aan `intake-postvak-verwerken --kanaal facturen_kempengroep`); deploy.yml F3-entry `rlz-intake-imap-kempengroep|intake-postvak-kempengroep-verwerken|900` mét `--command python`, gedeelde `INTAKE_ENVS`/`INTAKE_SECRETS` (beide postvakken) in het workflow-`env:`-blok op beide intake-jobs én op `rlz-reconciliatie`; service-envs `INTAKE_IMAP_JOB_RESOURCE` + `INTAKE_KEMPENGROEP_IMAP_JOB_RESOURCE`.
- `scripts/gcp/f3_jobs.sh`: JOBS-entry */10 Europe/Amsterdam ACTIEF (de pauze-regel geldt alleen de verse aanmaak van `rlz-intake-imap`), secret-slot idempotent + accessor, `roles/run.invoker` voor run-backend@ op beide intake-jobs ("Nu verwerken").
- Kanaal zichtbaar: `HerkomstMailDto.kanaal/postvak_adres/uit_spam` → blok "Uit de e-mail" en de binnenkomst-regel van de tijdlijn ("via facturen@kempengroep.nl"), chip "via facturen@kempengroep.nl" op het controlescherm (`BoekvoorstelPanel`, `intake_kanaal`).
- Overgangsperiode (forward nog aan): zelfde Message-ID = op de kop `al_bekend` (body wordt niet opgehaald, geen tweede document); handmatige "Fwd:" mét zelfde bijlage = `mogelijk_duplicaat_van` + duplicaat-afvoer én teller "dubbel via forward" (`intake_bericht.detail.bijlage_hashes`, `verwerkt.dubbel_via_forward`). Beide paden expliciet getest (`test_postvak_kempengroep.py::TestTweeKanalenZelfdeBijlage`).

### B — verwerkt-administratie op Message-ID (migratie 0171)

- Tabel `boekhouding.intake_bericht_verwerkt` (kanaal, message_id, uid, postvak_map, verwerkt_op, uitkomst verwerkt/al_bekend/niet_verwerkbaar, intake_bericht_id, detail; uniek op kanaal × message_id; RLS USING(true) + FORCE als `intake_bericht`, GRANT zonder DELETE).
- `app/intake/postvak.py` herschreven: `PostvakVerbinding` (verbind/mappen/koppen/bericht/markeer_gelezen, allemaal BODY.PEEK), `ImapPostvakBron.nieuwe_berichten()` leest per map (INBOX + `intake_imap_spam_map` = `[Gmail]/Spam`; een map die niet SELECT'baar is = `PostvakFout`, nooit stil) `UID SEARCH SINCE <vandaag − intake_postvak_venster_dagen (14)>` — dus óók gelezen berichten — haalt eerst de kop (Message-ID, FLAGS, From, Subject, Date, References/In-Reply-To), slaat over wat `verwerkt.bekend_toets` kent (eigen kanaal-tabel ∪ élke `intake_bericht.message_id`, ook .eml-uploads), en zet `\Seen` pas ná verwerking, als bijproduct. Sleutel zonder Message-ID = `uid:<map>:<uid>`.
- `verwerk_eml(..., postvak_map=…)` zet `detail.postvak_map` en `detail.bijlage_hashes` op het intake-bericht; de CLI registreert élk opgehaald bericht (`verwerkt.registreer`, idempotent), ook niet-parsebare (`niet_verwerkbaar`, geen eeuwige retry-lus, exit 1 blijft), en schrijft één audit `intake_postvak_run` per kanaal per run (gezien/gezien_spam/verwerkt/al_bekend/niet_verwerkbaar/uit_spam/dubbel_via_forward/overgeslagen_bekend/venster_vanaf).
- `--sinds JJJJ-MM-DD` = herstelrun over een langer venster (job-image), rapport per bericht VERWERKT / AL-VERWERKT / NIET-VERWERKBAAR / DUBBEL-VIA-FORWARD mét `[SPAM]`-markering.

### C — postvak-bewaking: reconciliatieblok `intake`

- `app/intake/bewaking.py::cli_blok` (in `run.BLOKKEN` en `cli._reconciliatie_alles` ná `activa`; `--alleen intake --lees-only` werkt): per kanaal mét instellingen telt het aan de bron (INBOX + Spam sinds gisteren 00:00 NL, gelezen én ongelezen) en legt dat naast de verwerkt-administratie en de uitkomsten per bijlage (documenten/verzamelbak/niet verwerkbaar uit `intake_bericht.detail`, géén Document-query over RLS heen).
- Verschil > 0 = afwijking `intake_postvak_verschil` (platformbreed; vingerafdruk per kanaal × set Message-ID's; `detail.berichten` ≤ 50 mét message_id/afzender/onderwerp/map/gelezen/datum) — **direct in `actie`** (`SoortDefinitie.direct_actie_reden`, tweede uitzondering; besluit Peter in de opdracht). Knop "Nu verwerken" (`NuVerwerkenActie.tsx`, élke kantoorrol) → `POST /reconciliatie/intake/{kanaal}/nu-verwerken` → `app/intake/nu_verwerken.py` start de intake-job (Cloud Run v2 `:run` op `INTAKE_*_JOB_RESOURCE`; dev = thread), audit `intake_postvak_nu_verwerken`, 202 / 404 onbekend kanaal / 502 start mislukt mét reden.
- Verbinding mislukt = FOUT `intake_postvak_verbinding`; kanaal mét job zonder instellingen op de reconciliatie-job = FOUT `intake_postvak_niet_geconfigureerd`; declaraties (geen job) = zichtbaar OVERGESLAGEN. Uit Spam verwerkt (7 dagen) = LET-OP `intake_uit_spam` per (kanaal, afzender) mét domein en de handeling (Workspace toestaan / DKIM-DMARC). Leesbare teksten (`teksten._intake`, LET-OP, FOUT) zonder GUID's; `BLOK_LABEL.intake` = "Postvak".
- Dagtellers in de reconciliatiemail: teller `INTAKE_POSTVAK` ("Intake-postvakken …", `automatiseringen.py`) uit audit `intake_postvak_run`: gedaan = verwerkt, zachte redenen `postvak_al_bekend` / `postvak_niet_verwerkbaar` / `postvak_uit_spam` / `postvak_dubbel_via_forward` (overgangsperiode), `detail.per_kanaal`.

### D — dubbele mailbox-audit (lees-only CLI, meting volgt ná deploy)

- `intake-postvak-audit --sinds 2026-07-01 [--detail] [--kanaal-bron facturen_kempengroep] [--kanaal-doel facturen]` (`app/intake/postvak_audit.py`): bron = élk bericht mét factuurbijlage (PDF/UBL/afbeelding) in INBOX + Spam + "[Gmail]/All Mail" (ontdubbeld), per bericht Message-ID/datum/afzender/onderwerp/bestandsnamen/sha256; doorgifte = dezelfde set in ak-nijenhuis, koppeling Message-ID → References/In-Reply-To → bijlage-sha256 → bestandsnaam (gelabeld); module = `intake_bericht.message_id`, `detail.bijlage_hashes`, `document.sha256_hash` per administratie-scope (status/administratie/boekstuk). Tabel per bronbericht + uitval (a) nooit doorgestuurd, (b) in Spam overgeslagen, (c) in INBOX niet verwerkt (gelezen vóór de intake / anders) + omgekeerde controle (rechtstreeks in ak-nijenhuis zonder module-spoor) + `Oordeel:`-regel. BODY.PEEK, geen writes; geen PII buiten afzender/onderwerp/bestandsnaam.
- Allowlist `nameting.sh` + `via_gh_onderdeel` + dispatch-onderdeel `intake-postvak-audit` in `nameting.yml` (options, if-tak, VGG-uitsluiting, OORDEEL_BRON) — draait op `rlz-reconciliatie` dat sinds deze commit de INTAKE-envset draagt.
- Waarom niet in deze run: geen lokaal proces tegen productie (regel 08-09), nameting@ zonder secrets, job-image mét beide credentials pas ná deploy. Zie `docs/rapporten/2026-09-23-intake-postvak-audit.md` voor het meetrecept, de invulplekken en de herstelrun-stappen.

### E — tests, guards, docs

- pytest nieuw: `tests/intake/test_postvak_imap.py` (17 — nieuwe FakeImap mét mappen/vlaggen/kop-fetch: gelezen én Spam gelezen, bekend op de kop overgeslagen zonder body-fetch, sleutel zonder Message-ID, crash laat vlag weg, spam-map ontbreekt = fout, CLI registreert/slaat over/niet_verwerkbaar/`--sinds`), `test_postvak_kempengroep.py` (11), `test_postvak_audit.py` (10), `tests/reconciliatie/test_intake_bewaking.py` (14: pure toets, cli_blok mét nep-lezer, FOUT-paden, spam-LET-OP, dagteller, route 202/502/404/401), gouden-set-casus al `tests/keten/test_al_postvak_kempengroep_kanaal.py` (2). Guards bijgewerkt: `test_soort_stand` (pin direct-actie-lijst), `test_cli_smoketest` (alias), `test_deploy_yml_envset_compleet` (service-envs), `test_nameting_workflow` (options), `test_postvak_declaraties` ((map, uid)).
- vitest: `NuVerwerkenActie.test.tsx` (4) + ReconciliatieScreen/changelog/BoekvoorstelPanel.betaalstatus/DocumentDetailScreen groen; `tsc -b` schoon.
- Docs: regels-alinea's `intake-extractie.md`, `reconciliatie.md`, `werkloop-productie.md`; BESLISSINGEN-sectie; CLAUDE.md intake rij 6 + reconciliatie rij 5; `docs/GCP_UITROL.md` §F3.4b; `frontend/src/changelog/WAT_IS_NIEUW.md`; les `Platform/registers/verbeteringen.md` (23-09): "een gelezen-vlag is geen verwerkt-administratie; wat de module niet ontvangt telt ze niet — dus tel aan de bron".
- Migratie-routine: `make migrate` dev-DB (0170 → 0171), `alembic check` schoon, `scripts/dump_schema.sh` ververst, live op een eigen uvicorn (poort 8011): `/reconciliatie/stand` 200, `POST /reconciliatie/intake/facturen_kempengroep/nu-verwerken` 202 (`voertuig: thread`), `declaraties` 404, zonder token 401.

## Keuzes zonder Peter

1. `intake_postvak_verschil` start DIRECT in `actie` — de opdracht zegt letterlijk "actie-bevinding mét de Message-ID's en knop Nu verwerken"; het bewijs is deterministisch (de Message-ID staat in de mailbox) en de handeling is één knop.
2. De bewaking herstelt niet zelf (patroon 19-09 "vaststaande actie = het systeem doet het"): de intake-job toetst elke 10 minuten al ALLES in het venster tegen de verwerkt-administratie; een verschil om 06:30 betekent dat de job het bericht niet kón verwerken. "Nu verwerken" is een zichtbare herkansing, geen tweede schrijver in de reconciliatie-run.
3. CLI-alias per job i.p.v. `--kanaal`-argument in de F3-lus (deploy.yml splitst `--args` op komma's en de smoketest op `^|^`).
4. "via <postvak>" alleen voor niet-default kanalen — facturen@ak-nijenhuis.nl blijft "(postvak)" zodat de gouden-set-pixelbaseline van bestaande casussen niet verschuift.
5. `bijlage_hashes` op het intake-bericht i.p.v. een Document-query over administraties heen (RLS: `document` per scope, `intake_bericht` platformbreed); tegelijk de basis van de audit-koppeling.
6. Audit + herstelrun als vervolg-opdracht mét `niet vóór:` (regel 21-09 "niet gemeten = schuld mét vervaldatum"); de audit als dispatch-onderdeel op `rlz-reconciliatie`.
7. `INTAKE_ENVS`/`INTAKE_SECRETS` in het workflow-`env:`-blok (de delimiter-guard expandeert alleen constanten dáár).
8. Gemiste optie bewust niet gebouwd: automatisch whitelisten in Workspace — dat is Peters console, de LET-OP noemt afzender + domein.

## Handelingen voor Peter (letterlijk)

1. Ná de deploy: `scripts/gcp/f3_jobs.sh` één keer draaien (owner-sessie) — maakt de scheduler `rlz-intake-imap-kempengroep` (*/10, ACTIEF) en zet `roles/run.invoker` voor run-backend@ op beide intake-jobs; de job zelf komt uit deploy.yml.
2. Controleer de eerste groene run: Cloud Logging op job `rlz-intake-imap-kempengroep` → regel `Postvak verwerkt (facturen_kempengroep): N nieuw, …` zonder `NIET-GECONFIGUREERD`/`FOUT`. Daarna in Gmail (facturen@kempengroep.nl › Instellingen › Doorsturen) de automatische forward naar facturen@ak-nijenhuis.nl UITZETTEN — tot die tijd vangt de dedup het dubbel.
3. De audit en de herstelrun lopen via de vervolg-opdracht; de herstelrun zelf is schrijvend en is jouw commando in de owner-sessie ná het lezen van het audit-rapport:
   `gcloud run jobs execute rlz-intake-imap-kempengroep --region europe-west4 --args="^|^-m|app.cli|intake-postvak-kempengroep-verwerken|--sinds|2026-07-25" --wait` en `gcloud run jobs execute rlz-intake-imap --region europe-west4 --args="^|^-m|app.cli|intake-postvak-verwerken|--sinds|2026-07-25" --wait`; het log toont per bericht VERWERKT / AL-VERWERKT / NIET-VERWERKBAAR / DUBBEL-VIA-FORWARD.
4. Bijvangst (niet in deze run): alle vier de Workspace-domeinen "Status van e-mailconfiguratie: Actie vereist" (DKIM/DMARC) — verklaart mede de spam-classificatie; kevin@kempenrecreatie.nl sinds 18-05-2024 als "wachtwoordlek" open terwijl de medewerker weg is.

## Meetrecept (werkt in productie)

- Dispatch-onderdeel `intake-postvak-audit` → `verkenning/nameting-intake-postvak-audit-<dd-mm>.txt` mét `Oordeel: GROEN|ROOD — N bronberichten, K zonder module-spoor (a/b/c), R rechtstreeks zonder spoor`.
- Scheduler-run rlz-reconciliatie 06:30 (of `reconciliatie-alles --alleen intake --lees-only` via nameting): per kanaal een `INTAKE postvak … VERSCHIL v`-regel, géén FOUT `intake_postvak_niet_geconfigureerd`; blok `intake` `gecontroleerd` 2.
- Cloud Logging job `rlz-intake-imap-kempengroep`: `Postvak verwerkt (facturen_kempengroep): …`; leesreplica `SELECT kanaal, uitkomst, count(*) FROM boekhouding.intake_bericht_verwerkt GROUP BY 1,2` groeit per run; audit `intake_postvak_run` per kanaal.
- Reconciliatiemail/Instellingen › Boeken: teller "Intake-postvakken" mét gedaan/overgeslagen per reden.

## Poort

- **pytest volledige suite (poging 2, 23-09 01:5x–02:5x, 55:42): 7243 passed, 5 failed, 1 skipped.** De vijf rode tests waren allemaal gevolgen van dit blok of een middernacht-flake, geen productie-gedrag: (1) `tests/activa/test_reconciliatie.py::test_blok_staat_in_run_blokken` eiste `activa` als laatste blok — sinds dit blok is `intake` het laatste (verwachting: `activa`, `intake`); (2) `tests/reconciliatie/test_rlz_dubbel.py::test_zonder_opties_ongewijzigd_alle_blokken_via_voer_uit` — blokkenlijst mét `intake`; (3) `tests/reconciliatie/test_run.py::test_cli_uitvoer_identiek_plus_run_slotregel` telde 5 i.p.v. 3 bevindingen: het intake-blok draaide écht mee en meldde per kanaal-mét-job een FOUT `intake_postvak_niet_geconfigureerd` (test-omgeving zonder IMAP-instellingen — precies het "nooit stil"-gedrag) → in die test leeg gestubd zoals `rlz_dubbel`, eigen dekking in `test_intake_bewaking.py`; (4) `tests/unit/test_kalenderdag_guard.py` — `postvak.py::venster_vanaf` gebruikte `datetime.now(UTC).date()` → `app.tijd.vandaag_nl()` (een UTC-datum verschuift ná 22:00 NL naar gisteren, dus het leesvenster zou een dag te kort zijn); (5) `tests/uren/test_stempels.py::TestIntake::test_eigen_stempels_en_endpoints` — middernacht-flake buiten dit domein: `nu − 3 u` viel om 02:45 NL op de vorige kalenderdag, de test vroeg de stempels van die dag op en miste de "uit"-stempel; de test gebruikt nu een vast middaguur van gisteren (verleden, < `MAX_LEEFTIJD`, één kalenderdag). Herdraai ná de fixes: `tests/intake` + `tests/reconciliatie/{test_run,test_rlz_dubbel,test_intake_bewaking,test_soort_stand}.py` + `tests/activa/test_reconciliatie.py` + `tests/uren/test_stempels.py` + kalenderdag-guard + gouden-set-casus al + nameting-guard: **243 passed + 34 passed**, 0 failed. Poging 1 (vóór de squash) had al één extra correctie nodig: `test_mailbody.py` kende de drie additieve herkomst-velden niet (zie § Poging 2).
- **Gouden set:** casus al (2) groen in de suite; exports `frontend/src/dev/keten/{a_universal_nederland,c_spot_services,h_bdo}.json` dragen additief `herkomst_mail.kanaal/postvak_adres/uit_spam` (gegenereerd door de suite, zelfde stand als de DTO); `frontend/scripts/keten_sweep.sh` **groen: 11 metingen, 0 nieuwe baselines** (de default-postvak-tekst is bewust ongewijzigd — keuze 4).
- **vitest volledig: 255 bestanden, 1934 passed** (incl. `NuVerwerkenActie.test.tsx` 4); **`tsc -b` schoon**; ruff op de eigen nieuwe regels schoon (19 × E501 handmatig gewikkeld, geen gedragswijziging); `alembic check` "No new upgrade operations detected" (dev-DB op 0171).
- Procesles poging 1: een tweede pytest-aanroep (alleen doc-guards) tijdens de lopende suite zette via de autouse-sessiefixture (`downgrade base` + `upgrade head`) de gedeelde test-DB opnieuw op → E/F-reeks in de suite; suite gestopt en schoon herstart, memory `geen-parallelle-pytest-runs` aangescherpt. Poging 1 eindigde daarna vóór de suite klaar was (rij (j3)) → WIP-branch; poging 2 wachtte de suite in een voorgrond-lus af.

## Gelezen regels

- `docs/regels/intake-extractie.md` (322 regels)
- `docs/regels/reconciliatie.md` (282 regels)
- `docs/regels/werkloop-productie.md` (306 regels)
