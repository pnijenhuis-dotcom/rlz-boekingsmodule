Domeinen: intake-extractie, reconciliatie, werkloop-productie
niet vóór: 2026-09-23 09:00

# NAMETING 23-09 — intake-postvak-audit (dubbele mailbox-controle) + eerste groene run rlz-intake-imap-kempengroep + blok `intake` in de 06:30-run; herstelrun en forward-uit als handelingen Peter

**Context:** bouwrapport `docs/rapporten/2026-09-23-intake-tweede-postvak-kempengroep-message-id-postvakbewaking.md` (werkt in productie: niet gemeten); audit-skelet `docs/rapporten/2026-09-23-intake-postvak-audit.md`; BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)". De deploy van de bouwcommit
moet live zijn (stap 0: `git rev-list --count main..origin/main` → merge --no-ff bij divergentie; deploy-check toetst service ÉN jobs incl. de
nieuwe job `rlz-intake-imap-kempengroep` op hetzelfde beeld; `spec.template.spec.template.spec.containers[0].image`).

## Opdracht
1. **Audit (lees-only, D):** `gh workflow run nameting -f onderdeel=intake-postvak-audit` (of `scripts/gcp/nameting.sh intake-postvak-audit --sinds 2026-07-01 --detail`
   mét `NAMETING_VIA_GH=0` in een geldige gcloud-sessie). Wacht op het bot-bestand `verkenning/nameting-intake-postvak-audit-<dd-mm>.txt` op
   origin/main (`git show origin/main:…`). Vul de rapporttabel in `docs/rapporten/2026-09-23-intake-postvak-audit.md` in (tellers + de UITVAL-regels + RECHTSTREEKS-regels letterlijk, geen PII
   buiten afzender/onderwerp/bestandsnaam), benoem per uitvalcategorie de oorzaak, en zet de status op GEMETEN. Meldt het bot-bestand
   `NIET-GECONFIGUREERD` → de INTAKE-envset staat niet op rlz-reconciliatie (deploy-check) → systeemfout van de bouw, fix in dezelfde run.
   Kan de workflow niet gestart worden (auth) → terugvalroute regel 19-09 (lokaal `NAMETING_VIA_GH=0`), ruwe uitvoer in het rapport.
2. **Eerste groene run kempengroep:** Cloud Logging job `rlz-intake-imap-kempengroep` (laatste executies): regel `Postvak verwerkt (facturen_kempengroep): …`
   zonder `NIET-GECONFIGUREERD`/`FOUT`; leesreplica `db_lezen.sh` → `SELECT kanaal, uitkomst, postvak_map, count(*) FROM boekhouding.intake_bericht_verwerkt
   GROUP BY 1,2,3` en `SELECT nieuwe_waarde FROM platform.audit_event WHERE actie='intake_postvak_run' ORDER BY tijdstip DESC LIMIT 6`. Bestaat de
   scheduler nog niet (f3_jobs.sh niet gedraaid) → handeling Peter, letterlijk in het rapport; geen eigen gcloud-schrijfactie.
3. **Blok `intake` in de 06:30-run** (van 24-09 als de deploy ná 06:30 op 23-09 live kwam): leesreplica `reconciliatie_bevinding` blok `intake`
   (soorten afwijking/let_op/fout, `detail.reden`), `reconciliatie_run.samenvatting->'intake'` → verwacht `gecontroleerd` 2 en géén
   `intake_postvak_niet_geconfigureerd`; plus `reconciliatie-alles --alleen intake --lees-only` via nameting als directe meetlat.
4. **Handelingen Peter in het rapport (letterlijk, mét datum/bron):** (a) `scripts/gcp/f3_jobs.sh` draaien (scheduler + run.invoker nieuwe job);
   (b) ná de eerste groene run de Gmail-forward facturen@kempengroep.nl → facturen@ak-nijenhuis.nl UITZETTEN; (c) herstelrun ná het lezen van de audit:
   `gcloud run jobs execute rlz-intake-imap-kempengroep --region europe-west4 --args="^|^-m|app.cli|intake-postvak-kempengroep-verwerken|--sinds|2026-07-25" --wait`
   en idem `rlz-intake-imap … intake-postvak-verwerken|--sinds|2026-07-25`; het log per bericht is het bewijs. Deze run doet zelf géén schrijvende job-executie.
5. Rapport `docs/rapporten/2026-09-2x-nameting-intake-postvak-audit-en-eerste-run.md` + INDEX + Gelezen regels; BESLISSINGEN-alinea "Gemeten <datum>" onder de
   sectie; regels-alinea's bijwerken mét de meetuitkomst ("werkt in productie: ja/nee"). Kan iets pas ná een klik van Peter (scheduler/forward),
   dan terug in de inbox mét `niet vóór:` +1 dag (max 3 pogingen, rij (k)).
---
LEESPLICHT (Domeinen-kopregel): lees EERST volledig docs/regels/intake-extractie.md, docs/regels/reconciliatie.md, docs/regels/werkloop-productie.md.
Werkloop automatisch: opdracht → lopend/ → gedaan/ mét kopregel; committen zoals gebruikelijk (nooit pushen — de Stop-hook doet dat).
