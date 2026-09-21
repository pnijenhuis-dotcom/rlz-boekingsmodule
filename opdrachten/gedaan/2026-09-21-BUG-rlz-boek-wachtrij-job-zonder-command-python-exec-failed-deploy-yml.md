uitgevoerd 2026-09-21, rapport: docs/rapporten/2026-09-21-f3-jobs-command-python-job-smoketest-wordt-geboekt-let-op.md

Domeinen: werkloop-productie, werkvoorraad-controlescherm, reconciliatie

# BUG 21-09 — job `rlz-boek-wachtrij` faalde in productie zonder één regel uitvoer: geen `--command python` (deploy.yml maakt jobs
# aan zónder commando; Dockerfile heeft geen ENTRYPOINT) → "Boeken in RLZ" bleef sinds 18-09 op "Wordt geboekt…" hangen

**Feiten (Peter + Cowork 21-09, Terminal):**
- Administratiekantoor Nijenhuis C.V.: Shine Employes € 480,13 en Reeleezee € 2.711,61 ingediend 12:46 NL, om 13:02 nog `wordt_geboekt`;
  tijdlijn "Boeken in RLZ ingediend — de boeking loopt op de achtergrond", daarna niets.
- `f3_jobs.sh` (13:0x): stap 8b zette pas NU `roles/run.invoker` voor run-backend@ op de job (de trigger vanuit de service faalde
  dus sinds 18-09); scheduler `rlz-boek-wachtrij` "bestaat al — overgeslagen" maar stond GEPAUZEERD ("verse cadansen starten
  gepauzeerd") → Peter: `gcloud scheduler jobs resume`.
- `gcloud run jobs execute rlz-boek-wachtrij --wait` → exit 1, log alleen "Application exec likely failed / Application failed to
  start", géén Python-uitvoer. `describe`: image = HEAD 7881cfd, args `-m;app.cli;boek-wachtrij-verwerken`, **command leeg**.
- Oorzaak: `backend/Dockerfile` heeft geen `ENTRYPOINT` (alleen `CMD` uvicorn); `f3_jobs.sh` stap 4 geeft `--command python` bij de
  eerste aanmaak; `deploy.yml` "F3-jobs bijwerken" geeft alleen `--args` en laat een bestaand commando staan. `rlz-boek-wachtrij` is
  de eerste job die door deploy.yml zélf is aangemaakt (18-09, f3_jobs zag hem daarna als "bestaat al") → nooit een commando gekregen.
  Herstel door Peter: `gcloud run jobs update rlz-boek-wachtrij --region=europe-west4 --command python` (+ execute).

## Opdracht
1. **deploy.yml:** `--command python` in élke `gcloud run jobs deploy` (de hele for-lus) — de deploy is de canonieke config
   (staat er letterlijk), dus hij mag niet afhankelijk zijn van wat f3_jobs ooit zette. Guard: een test die deploy.yml parseert en
   voor élke `jobs deploy` het `--command` afdwingt (`tests/test_deploy_yml.py`-patroon), plus `ENTRYPOINT ["python"]` in de Dockerfile
   overwegen — NEE als dat de service-CMD raakt; motiveer in het rapport.
2. **Post-deploy-smoketest jobs:** ná elke deploy élke job één keer `execute --wait` mét een no-op-vlag (bv. `--smoketest` op de CLI:
   imports + settings + DB-ping, geen werk) — een job die niet start maakt de deploy rood (les 10-09 "service en jobs kunnen uit de pas
   lopen" gaat nu ook over start-baarheid). Bewijs in CI (les 21-08).
3. **f3_jobs.sh:** stap 6 maakt nieuwe schedulers gepauzeerd en niemand hervat ze ("verse cadansen starten gepauzeerd") → voor
   vangnet-schedulers (`rlz-boek-wachtrij`, `rlz-extractie-wachtrij`, `rlz-bank-sync`) direct actief, of het script eindigt met een
   luide lijst "GEPAUZEERD: …" + het resume-commando. Stap 4 "bestaat al — overgeslagen" moet óók het commando toetsen en bijzetten.
4. **Niets stil (Kernprincipe 4):** bevinding `wordt_geboekt_verouderd` bestaat maar staat in `meten` → promoveer tot LET-OP (systeemmail)
   bij > 10 min op `wordt_geboekt`, mét actie "Opnieuw indienen" op de rij én de reden uit het audit `boek_wachtrij_trigger`
   ("trigger mislukt: <fout>") zichtbaar in de tijdlijn (nu alleen audit). De rij in de documentenlijst toont ná 5 min "Wordt geboekt…
   (loopt vast — N min)" i.p.v. een eeuwige stip. Lees de audit-rijen `boek_wachtrij_trigger` sinds 18-09 (leesreplica) en zet de
   werkelijke foutteksten in het rapport.
5. Nameting ná deploy (`niet vóór:` de deploy): één boeking indienen op de RLZ-testadministratie → binnen 2 min geboekt via de trigger
   (niet via het vangnet); `gcloud run jobs describe` van álle jobs toont `command: python`; scheduler-status van alle vangnetten =
   ENABLED. Rapport + INDEX + Gelezen regels; BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT
   LET-OP (21-09)"; les `Platform/registers/verbeteringen.md`: "een job die door de deploy wordt aangemaakt erft niets van het
   bootstrap-script — élke eigenschap die de start bepaalt staat in de deploy zelf"; CLAUDE.md één verwijsregel onder werkloop.
