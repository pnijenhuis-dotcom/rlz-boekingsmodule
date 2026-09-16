# Rapport 16-09 — Deploy: volledige envset (mail, push, inbox-adres, store-links) in ÉÉN stap voor service en jobs

**Opdracht:** `opdrachten/gedaan/2026-09-16-deploy-mailconfig-in-service-stap.md` (melding Peter 16-09 ~09:00: herstel-link →
"Mailkanaal niet geconfigureerd"). **Werkt in productie: niet gemeten** — het bewijs is de eerstvolgende groene deploy-run van deze
commit (CI-job-bewijs, niet lokaal); meetrecept hieronder.

## Wat er mis was
- `gcloud run deploy rlz-backend --set-env-vars …` verving de hele envset met alleen de basis-set. INTAKE_POSTVAK_ADRES, STORE_LINK_IOS,
  BERICHTEN_*/APP_BASIS_URL, het VAPID-paar, APNs en FCM kwamen pas terug in drie latere `gcloud run services update`-stappen.
- Gevolg: élke deploy een venster van minuten zonder mail; een run die ná de service-stap rood ging (10-09 tweemaal, 16-09 `a23042e`)
  liet de service blijvend zonder mailconfig achter. Dezelfde constructie bij de jobs (lus met `--set-env-vars` + losse `jobs update`).
- Bijvangst: `rlz-kantoor-digest` (weekdigest, mailt via `app/berichten/digest.py`) had in deploy.yml nooit mailconfig gekregen.

## Gedaan
1. **Service in één stap** — alle 26 envs + 12 secrets in de ene `gcloud run deploy`-stap, scheider `^|^`, geen `||`-fallback meer
   (ontbrekend secret-slot = zichtbaar rode deploy + mail via `deploy-mislukt`). De stappen "Registersync inbox_adres + store-links" en
   "Notificatie-config service (mail + VAPID-paar)" zijn weg.
2. **Jobs in één stap per job** — F3-lus bouwt `BASIS_ENVS`/`BASIS_SECRETS` + `case`-extra's op (intake-imap, extractie-wachtrij,
   herinneringen/nieuwe-facturen mét push, kantoor-digest/reconciliatie mét mail, bewaking, webhook-afleveraar) en doet per job precies één
   `gcloud run jobs deploy`; alle losse `jobs update`-stappen zijn weg; `rlz-webhook-afleveraar` zit in de lus.
3. **Eén bron** — workflow-`env:` `MAIL_ENVS`, `MAIL_SECRETS`, `PUSH_ENVS`, `PUSH_SECRETS`, geëxpandeerd in service-stap, lus en
   smoketest-job.
4. **Guard** `backend/tests/unit/test_deploy_yml_envset_compleet.py` (7 tests): geen `services update`/`jobs update`/`--update-*` (fail-closed),
   volledige sleutel-set in de service-stap incl. mailkanaal, scheider in geen waarde, mailconfig alleen via `${MAIL_ENVS}`, mailende jobs
   dragen de set, élke `jobs deploy` heeft envs + secrets. Bestaande guards aangepast: delimiter-guard expandeert de constanten en toetst
   óók `ENVS="…"`-toewijzingen; image-guard telt 4 beeld-vlaggen.
5. **Smoketest ná deploy** — `deploy-smoketest` leest lees-only de servicetemplate (Cloud Run Admin API, zelfde token als de drift-toets) en
   eist BERICHTEN_SMTP_HOST + BERICHTEN_SMTP_GEBRUIKER (env) + BERICHTEN_SMTP_WACHTWOORD (secret-mount). `app/bewaking/deploy_drift.py::
   lees_service_config`/`mailkanaal_ontbrekend`, `app/cli.py::_smoketest_service_mailkanaal`; 5 nieuwe tests in `tests/bewaking/test_deploy_drift.py`.
6. Docs: BESLISSINGEN "DEPLOY — VOLLEDIGE ENVSET IN ÉÉN STAP (Peter 16-09)", CLAUDE.md-aanvulling op de deploy-les 10-09, GCP_UITROL §F3.9,
   WAT_IS_NIEUW-blok.

## Tests
- `tests/unit/test_deploy_yml_*` (3 bestanden) + `tests/bewaking/test_deploy_drift.py`: 34 groen. `test_claude_md_beslissingen_verwijzingen` groen,
  frontend `changelog.test.ts` groen. YAML geparsed + `bash -n` op alle run-blokken groen.

## Meetrecept ná deploy (lees-only)
```
gcloud run services describe rlz-backend --region europe-west4 --project rlz-boekhouding \
  --format='value(spec.template.spec.containers[0].env)'      # bevat BERICHTEN_SMTP_HOST, INTAKE_POSTVAK_ADRES, STORE_LINK_IOS
gcloud run jobs describe rlz-kantoor-digest --region europe-west4 --project rlz-boekhouding \
  --format='value(spec.template.spec.template.spec.containers[0].env)'   # bevat BERICHTEN_SMTP_HOST
```
Smoketest-log: "service-template draagt de mailkanaal-config (N envs, M secrets)". Daarna één herstel-link → mail komt aan. Geen handmatige
`services update` als tussenoplossing (regel Peter 08-09).

## Beslispunten (default gekozen)
- `||`-fallbacks op ontbrekende secret-slots zijn weg: een deploy zonder een van de slots is nu rood i.p.v. "draait zonder config". Alle
  slots bestaan sinds 08-2026; wil Peter de zachte val terug, dan alleen voor de APNs-slots.
- `rlz-kantoor-digest` krijgt de mail-envset (was: nooit gehad — een stille no-op sinds de job bestaat).
