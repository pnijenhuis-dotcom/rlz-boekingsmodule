# F3-jobs: `--command python` in deploy.yml + job-smoketest + wordt_geboekt-LET-OP — BUG rlz-boek-wachtrij startte 18→21-09 niet (21-09)

Opdracht `opdrachten/gedaan/2026-09-21-BUG-rlz-boek-wachtrij-job-zonder-command-python-exec-failed-deploy-yml.md` (Peter + Cowork 21-09:
Shine Employes € 480,13 en Reeleezee € 2.711,61 bij Administratiekantoor Nijenhuis C.V. ingediend 12:46, om 13:02 nog "Wordt geboekt…";
`gcloud run jobs execute rlz-boek-wachtrij --wait` → exit 1, "Application exec likely failed", `command` leeg). Gebouwd + getest; geen
migratie, geen AI. **Werkt in productie: niet gemeten** — de fix deployt ná deze run; de nameting staat als vervolg-opdracht in de inbox
(`2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md`, `niet vóór: 2026-09-22 09:00`) mét het meetrecept als dispatch-onderdeel
`jobs-start` in `nameting.yml`. Peter keek niet mee; keuzes staan onder "Keuzes". BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)".

**Één regel voor Peter:** de achtergrond-schrijver van "Boeken in RLZ" kon van 18 tot 21 september niet starten omdat de deploy de job zonder
startcommando aanmaakte; de deploy zet dat commando nu zelf, start ná elke uitrol élke job één keer als test, het bootstrap-script hervat
gepauzeerde vangnetten en zegt luid wat er nog ontbreekt, en een boeking die langer dan tien minuten hangt is vanaf nu een systeemfout-melding
mét de knop "Opnieuw indienen" — in de lijst zie je ná vijf minuten "Wordt geboekt… (loopt vast — N min)".

## Feiten uit productie (deze run, lees-only)

- **Cloud Logging job `rlz-boek-wachtrij`:** 2.237 executies mét "Application exec likely failed" — 18-09: 190, 19-09: 732, 20-09: 722,
  21-09: 593; laatste om 15:30:10 UTC. Eerste geslaagde verwerking 15:31:40 UTC: "boek-wachtrij-verwerken: 5 boeking(en) afgerond", daarna
  elke 2 min "0 boeking(en)" (het vangnet draait). De executies op 18-09 17:40–17:52 kwamen élke 2 min: de scheduler draaide toen; later
  onregelmatig — het vangnet bestond, maar een job zonder commando kan niets.
- **Leesreplica (`db_lezen.sh`, per administratie — `audit_event`/`document` hebben geen Beheerder-clausule zonder scope):** vijf boekingen
  hingen: Administratiekantoor Nijenhuis C.V. `75b35516` ingediend 19-09 06:55 UTC (2,4 dag) en `6b828010` 21-09 10:46; Belastingbutler
  `15a9bc7e` 21-09 07:20; Old Dutch `de629f95` + `1ad6e15f` 21-09 07:53. Alle vijf `boek_wachtrij_afgerond` `geboekt` door verwerker `job`
  tussen 15:31:28 en 15:31:40 UTC, ná Peters `gcloud run jobs update rlz-boek-wachtrij --command python`.
- **Audit `boek_wachtrij_trigger` sinds 18-09: 140 rijen, allemaal `geslaagd`, 0 `mislukt`** (27–41 per document: het startup-vangnet
  `herstel_achtergebleven_boekingen` triggert bij élke service-start opnieuw; 38+30+35 op 21-09 10–12 u = de deploys van die ochtend).
  De opdrachttekst "de trigger vanuit de service faalde sinds 18-09 (invoker)" klopt dus niet: `run.jobs.run` slaagde, de EXECUTIE startte niet.
  De letterlijke fouttekst die de opdracht vroeg bestaat niet in het audit; de fout stond alleen in de job-log ("Application exec likely
  failed") — precies de klasse die de nieuwe LET-OP benoemt als "trigger geslaagd maar de job rondde de boeking niet af".
- **Waarom drie dagen stil:** `wordt_geboekt_verouderd` stond in `meten` (facet, nooit mail), de systeemmail is `uitgeschakeld`, de
  `vangnet_scheduler`-LET-OP telt alleen mislukte triggers, de rij toonde een eeuwige grijze stip, de tijdlijn zei "de boeking loopt op de
  achtergrond" en daarna niets.

## Gebouwd

1. **`.github/workflows/deploy.yml`** — F3-lus als bash-array `F3_JOBS`, `--command python` op élke job-deploy; ná de lus de **job-smoketest**:
   per job `gcloud run jobs execute … --args="^|^-m|app.cli|--smoketest|<cli>" --wait` (parallel, dan gewacht), één niet-startende job =
   stap rood (`::error::`) → `if: failure()` mailt het beheer. Guard `tests/unit/test_deploy_yml_jobs_command.py`.
2. **`app/cli.py --smoketest`** (root-vlag vóór het subcommando; `_job_smoketest`): argparse heeft het commando herkend, imports + settings +
   `SELECT 1`, print "job-smoketest ok: commando=… database=bereikbaar — geen werk uitgevoerd", nooit een dispatcher. Guard
   `tests/unit/test_cli_smoketest.py` roept élke CLI-vorm uit de F3-lus letterlijk aan (14 commando's) + DB-onbereikbaar = exit 1.
3. **`scripts/gcp/f3_jobs.sh`** — stap 4 "bestaat al" leest `containers[0].command` en zet `--command python` bij als het leeg is; stap 6
   `VANGNET_SCHEDULERS` (boek-wachtrij, extractie-wachtrij, bank-sync, bewaking, webhook-afleveraar) → `resume` alleen bij PAUSED; nieuwe
   stap 12 "Slotcontrole" eindigt luid: "GEPAUZEERD: …" + resume-commando's, "ZONDER STARTCOMMANDO: …" + update-commando's. Guard
   `tests/unit/test_f3_jobs_sh.py` (`bash -n` + inhoud).
4. **Niets stil (kernprincipe 4):**
   - `automatiseringen.boek_wachtrij_gestrand_bevindingen` (in `registreer`): per document > `BOEK_WACHTRIJ_HERSTEL_MINUTEN` (10) op
     wordt_geboekt één LET-OP op blok automatisering, categorie `boek_wachtrij_gestrand` ∈ `REGRESSIE_CATEGORIEEN` → systeemmail + audit
     `automatisering_regressie` + bewakingsprobe (alert naar `bewaking_alert_ontvanger`, óók bij uitgeschakelde systeemmail); tekst mét
     trigger-reden; detail `afwijking_soort`, `document_id`, `minuten`, `trigger_*`, `doel_pad`; vingerafdruk per document × indienmoment.
     Het documenten-blok produceert de `afwijking` niet meer; registry-entry `wordt_geboekt_verouderd` blijft (`gepromoveerd_op` 21-09).
   - **Kwartier-probe `boek_wachtrij_gestrand`** (`app/bewaking/service.py`): ≥ 1 hangende boeking = `fout` → alert ná 2 metingen (~30 min),
     herstelmelding zodra leeg.
   - **Tijdlijn:** `CloudRunJobBoekWachtrij.enqueue` schrijft bij een MISLUKTE trigger één systeemregel ("achtergrond-schrijver starten
     mislukt (job …): <fout> — het scheduler-vangnet … 'Opnieuw indienen'"); geslaagd = alleen audit.
   - **Route `POST …/documenten/{id}/boek-wachtrij/opnieuw-indienen`** (`boek_wachtrij.dien_opnieuw_in`): zelfde sleutel/claim, geen
     statuswissel, tijdlijnregel + audit `boek_wachtrij_opnieuw_ingediend`, `trigger_uitkomst` geslaagd | mislukt (+fout) | lokaal terug;
     niet op wordt_geboekt = 409.
   - **Frontend:** `status.ts::wordtGeboektLabel` (ná 5 min "Wordt geboekt… (loopt vast — N min)"), `StatusChip` leest `laatst_gewijzigd_op`
     en kleurt oranje; `WordtGeboektBalk` op het controlescherm (minuten, ná 5 min knop "Opnieuw indienen" + toast mét trigger-uitkomst);
     `OpnieuwIndienenActie` op Inzicht › Reconciliatie (rij mét `reden == boek_wachtrij_gestrand`), deeplink "Naar het document →".
   - **Bijvangst (echte bug in de bouw):** `_wachtrij_detail` en het indienmoment (`_wordt_geboekt_documenten`) lazen "de jongste
     gebeurtenis naar wordt_geboekt" — de nieuwe tijdlijnregels (van = naar = wordt_geboekt) zouden de actor/bevestigingsvlaggen van de
     indiening verbergen en "sinds" verschuiven; beide lezen nu alleen de échte overgang (van ≠ wordt_geboekt). Gevonden door
     `test_gestrande_boeking_…` (LET-OP verdween ná een trigger-regel).
   - Teller `boek_wachtrij` in de reconciliatiemail telt `opnieuw_ingediend_24u`.
5. **Meetlat:** querybibliotheek `app/lezen/queries/boek-wachtrij.sql` (scope administratie: `wordt_geboekt_nu` + audits 7 dagen);
   nameting-onderdeel `jobs-start` (`nameting.yml` if-tak + `options:` + `via_gh_onderdeel`, guard `test_nameting_workflow.py` bijgewerkt).
6. **Gouden set:** casus **ai** `tests/keten/test_ai_wordt_geboekt_loopt_vast.py` (BDO via de 202-route, verwerker start niet, veroudering →
   lijst-DTO + LET-OP mét reden + deeplink → "Opnieuw indienen" via API → verwerker rondt precies één boeking af → 409 daarna).

## Keuzes (Peter keek niet mee)

- **Geen `ENTRYPOINT ["python"]` in de Dockerfile (opdracht punt 1 "overwegen"):** NEE — de service-CMD is `sh -c exec uvicorn …`; met een
  python-ENTRYPOINT wordt dat `python sh -c …` en start de service niet; rlz-migratie heeft bovendien `alembic` nodig. Het startcommando hoort
  in de deploy (canoniek, versiebeheerd), de guard eist het daar. De Dockerfile-guard maakt een latere ENTRYPOINT rood.
- **Job-smoketest parallel** (15 executies tegelijk, ~30–60 s) i.p.v. serieel (~10 min binnen de 30-min-timeout).
- **LET-OP als REGRESSIE-categorie, niet via `meten` en niet als `afwijking`-promotie:** een boeking die > 10 min hangt terwijl trigger én
  vangnet bestaan is een infra-/codefout, geen domeinoordeel (lijn `groep_saldo_fout` 21-09). Regressie is óók de enige klasse die Peter
  bereikt zolang de systeemmail uit staat (bewakingsalert). Per document één LET-OP (volume klein; geen bundeling).
- **Kwartier-probe erbij:** de reconciliatie draait 06:30 — een boeking van 12:46 zou pas de volgende ochtend gemeld zijn; de probe meldt
  binnen ~30 min. Twee kanalen, zelfde bron (`gestrande_boekingen`).
- **"Opnieuw indienen" = verwerker herstarten, geen nieuwe boeking:** dezelfde idempotency-key; de RLZ-adapter hervat idempotent. Een 409 als
  het document intussen geboekt/mislukt is — nooit stil.
- **Vangnet-schedulers hervatten in f3_jobs.sh (niet alleen melden):** een vangnet dat gepauzeerd staat vangt niets; notificatie-cadansen
  houden hun bewuste pauze-regels (les 16-08). `rlz-bank-sync` heeft in de JOBS-lijst geen scheduler → "geen scheduler — overgeslagen".
- **Trigger-pad-nameting vraagt een mens:** het trigger-pad (service → job) is alleen meetbaar mét een echte indiening via de service; een
  proef-CLI op de job-image zou de job-envset (zonder `BOEK_WACHTRIJ_JOB_RESOURCE`) meten, niet het pad. De vervolg-opdracht leest de audits
  ná deploy en zegt anders letterlijk "niet gemeten — vraagt één klik van Peter op de RLZ-testadministratie". Nooit een boeking op een
  klantadministratie.
- **Opdracht-aanname gecorrigeerd:** "de trigger faalde sinds 18-09" — het audit toont 140 × `geslaagd`, 0 × `mislukt`. De invoker-binding van
  stap 8b was niet de oorzaak van het hangen; de LET-OP benoemt beide klassen apart.

## Poort

- pytest gericht: `test_deploy_yml_*` (4 bestanden), `test_f3_jobs_sh`, `test_cli_smoketest`, `test_nameting_workflow`, `test_regels_index`,
  `test_boek_wachtrij` (incl. `TestNietsStil21_09` 3), `test_router_boeken` (+1), `test_bewaking`, `test_soort_stand`, `test_automatiseringen`,
  `test_lezen`, gouden set `test_ai_…` + `test_keten_guard` + `test_export_deterministisch`: groen (zie sectie "Volledige suite" hieronder).
- vitest volledig: 248 bestanden / 1909 tests groen; `tsc -b` schoon.
- Keten-sweep frontend: zie hieronder.
- `alembic check`: geen migratie in deze run.

## Volledige suite

- pytest volledig (één run, ná alle wijzigingen): **7105 passed, 1 skipped, 21 deselected in 54:04** — EXIT 0.
- vitest volledig: 248 bestanden / 1909 tests groen; `tsc -b` schoon.
- Keten-sweep frontend (`frontend/scripts/keten_sweep.sh`): **11/11 groen, 0 nieuwe baselines** (de "loopt vast"-weergave raakt alleen
  rijen op wordt_geboekt; geen gouden-set-casus staat in die stand ten tijde van de screenshot).
- ruff: nieuwe bestanden schoon; in bestaande bestanden alleen de eigen regels getoetst (de backend is niet ruff-schoon, bewust
  buiten scope). **Procesles:** een generieke wrap-/merge-heuristiek over hele bestanden brak tijdens deze run een def-signature en
  voegde 45 vreemde regels samen; hersteld via HEAD-vergelijking (difflib) en de volledige suite is daarná opnieuw gestart —
  vastgelegd als geheugenregel, niet als projectregel (eigen fout, geen domeinles).

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT, kopregel "Domeinen"): `docs/regels/werkloop-productie.md` (195 regels bij het lezen; 220 ná
deze run), `docs/regels/werkvoorraad-controlescherm.md` (347 regels; 368 ná), `docs/regels/reconciliatie.md` (191 regels; 216 ná).
