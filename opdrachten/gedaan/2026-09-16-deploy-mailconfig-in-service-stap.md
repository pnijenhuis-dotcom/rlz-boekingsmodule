> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-deploy-envset.md

# OPDRACHT 16-09 — Deploy: mailconfig (en overige envs) van de service in ÉÉN stap, geen venster zonder SMTP (melding Peter 16-09)

**Aanleiding:** Peter stuurde 16-09 ~09:00 een herstel-link naar een klant-accordeur en kreeg: "Herstel-link aangemaakt …,
maar het mailen mislukte: Mailkanaal niet geconfigureerd (BERICHTEN_SMTP_HOST/-GEBRUIKER/-WACHTWOORD ontbreekt)." De fallback
(link tonen) werkte; de mail niet.

**Oorzaak in `.github/workflows/deploy.yml`:** stap `gcloud run deploy rlz-backend` (regel ~162) gebruikt `--set-env-vars`
en VERVANGT daarmee de hele envset van de service; BERICHTEN_SMTP_*/APP_BASIS_URL/VAPID/APNS/INTAKE_POSTVAK_ADRES/STORE_LINK_IOS
worden pas in latere `gcloud run services update`-stappen (regels ~194, ~406, ~419) teruggezet. Gevolg: (a) élke deploy heeft
een venster van minuten waarin de service niet kan mailen; (b) een deploy die ná de service-stap rood gaat (les 10-09: dat is
al twee keer gebeurd) laat de service blijvend zonder mailconfig achter. Dezelfde constructie bij de jobs (`--set-env-vars` in de
lus + latere `--update-env-vars`) heeft hetzelfde risico.

## Te doen
1. Service: alle envs in de ENE `gcloud run deploy`-stap (één `--set-env-vars` mét een scheidingsteken dat in geen enkele
   waarde voorkomt — les 10-09; `^|^` bevat nu al e-mailadressen mét `@`, controleer dat `|` nergens in een waarde staat) én
   `--set-secrets` in dezelfde stap. De latere `services update`-stappen voor envs/secrets vervallen (alleen stappen die
   iets anders doen blijven). Volgorde-onafhankelijk: een nieuwe revisie is pas live mét complete config.
2. Jobs: idem — per job één `jobs deploy`/`update` mét de volledige envset en secrets; geen `--set-env-vars` in een lus
   gevolgd door losse `--update-env-vars`. Eén bron voor de gedeelde mail-envset (YAML-anchor of shell-variabele
   `MAIL_ENVS`), zodat service en jobs niet uit elkaar lopen.
3. Guard `tests/unit/test_deploy_yml_envset_compleet.py`: (a) de service-deploy-stap bevat alle env-sleutels die elders in
   het bestand voor `rlz-backend` genoemd worden (fail-closed: een nieuwe `services update --update-env-vars` op rlz-backend
   is rood); (b) geen scheidingsteken in een waarde; (c) BERICHTEN_SMTP_HOST/GEBRUIKER + secret BERICHTEN_SMTP_WACHTWOORD staan
   in de service-stap. Bestaande guards (`test_deploy_yml_envvar_delimiters`, `test_deploy_yml_image_uniform`) blijven.
4. Smoketest ná deploy: bestaande post-deploy-smoketest krijgt een lees-only check "mailkanaal geconfigureerd" via een
   bestaande status-route (bewaking kent al `reconciliatie_mail`/`niet_geconfigureerd`) — rood = deploy rood + mail via
   `deploy-mislukt`.
5. Nazorg productie: als de deploy van 16-09 (`a23042e`) halverwege gestrand is, staat de service nu zonder mailconfig —
   de eerstvolgende groene deploy van deze commit herstelt dat vanzelf (geen handmatige job-update; regel Peter 08-09).
   Meetrecept: ná deploy `gcloud run services describe rlz-backend --format='value(spec.template.spec.containers[0].env)'`
   (lees-only, in de nameting-allowlist) bevat BERICHTEN_SMTP_HOST; daarna één herstel-link → mail komt aan.

## Af
- BESLISSINGEN nieuwe sectie "DEPLOY — VOLLEDIGE ENVSET IN ÉÉN STAP (Peter 16-09)" + aanvulling op de deploy-les 10-09 in
  CLAUDE.md (één verwijsregel), GCP_UITROL bijwerken, rapport `docs/rapporten/2026-09-16-deploy-envset.md` + INDEX mét
  "werkt in productie: ja/nee" ná de eerste groene run (CI-job-bewijs = groene run, niet lokaal). Geen migratie.
