Domeinen: werkloop-productie, reconciliatie, werkvoorraad-controlescherm

niet vóór: 2026-09-22 09:00

# Nameting ná deploy — F3-jobs `command: python`, job-smoketest, scheduler-vangnetten, wordt_geboekt-LET-OP (vervolg BUG 21-09)

Bouwrapport: `docs/rapporten/2026-09-21-f3-jobs-command-python-job-smoketest-wordt-geboekt-let-op.md` ("werkt in productie: niet gemeten" is een schuld mét
vervaldatum — regel 21-09). BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)".

## Stap 0 — deploy-check (service ÉN jobs)
- `git fetch origin main` + `git rev-list --count main..origin/main` (> 0 → `git merge --no-ff origin/main`, nooit rebase).
- `gh run list --workflow deploy --limit 5` → de run van de commit "fix(f3-jobs: --command python …)" (21-09) is groen; let op de nieuwe stap
  "F3-jobs bijwerken … + job-smoketest": lees de log — élke `job-smoketest <job>: start ok` (15 regels). Rood? Dan is dát de uitkomst: rapport.
- `gcloud run jobs describe rlz-boek-wachtrij --region europe-west4 --format="value(spec.template.spec.template.spec.containers[0].image, spec.template.spec.template.spec.containers[0].command)"` = HEAD-image + `python`.

## Stap 1 — meetlat `jobs-start` (lees-only, bot-bestand op main)
- `gh workflow run nameting -f onderdeel=jobs-start` (of `scripts/gcp/nameting.sh` via gh); wacht op de bot-commit `verkenning/nameting-jobs-start-<dd-mm>.txt`.
- Verwacht: oordeelregel "alle jobs dragen command python (rlz-migratie: alembic)"; laatste executies rlz-boek-wachtrij `succeededCount 1`;
  scheduler-stand vangnetten ENABLED (of "niet leesbaar" — dan via Peter/owner-sessie `gcloud scheduler jobs describe rlz-boek-wachtrij --location europe-west4 --format=value(state)`);
  `db-lezen boek-wachtrij`: 0 rijen `wordt_geboekt_nu`.

## Stap 2 — trigger-pad (klik → job binnen 2 min, niet via het vangnet)
- Lees in het bot-bestand (sectie db-lezen) élke `ingediend` ná de deploy-tijd: hoort een `trigger` `geslaagd` binnen 1 s en een `afgerond`
  `geboekt`/`mislukt` mét verwerker `job` binnen 2 min bij. Ja → "trigger-pad werkt in productie: JA" mét de drie tijdstippen.
- Geen indiening ná de deploy? Dan is het trigger-pad NIET meetbaar zonder mens: rapporteer letterlijk "trigger-pad: niet gemeten — vraagt één
  klik 'Boeken in RLZ' van Peter op de RLZ-testadministratie (8dbfb856-d75b-4ec3-9124-c8b739fe3bc5, TEST-referentie); daarna
  `gh workflow run nameting -f onderdeel=jobs-start` opnieuw". Nooit zelf een boeking indienen op een klantadministratie.

## Stap 3 — bewaking + reconciliatie
- Cloud Logging job `rlz-bewaking` ná deploy: probe `boek_wachtrij_gestrand` = `ok` (`gcloud logging read 'resource.type="cloud_run_job" AND resource.labels.job_name="rlz-bewaking" AND textPayload:"boek_wachtrij_gestrand"' --limit 5`).
- Reconciliatie-run 22-09 06:30 (`db-lezen reconciliatie-bevindingen --param soort=let_op` of het bot-bestand): 0 × `boek_wachtrij_gestrand`; de
  oude `wordt_geboekt_verouderd`-afwijkingen (in meting) zijn ná deze run `reconciliatie_auto_gesloten` (delta `verdwenen_afwijkingen`).

## Afronding
Rapport `docs/rapporten/2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md` + INDEX-regel + "## Gelezen regels"; BESLISSINGEN-sectie
hierboven: status → "werkt in productie: ja/nee" per onderdeel (command, smoketest, scheduler, trigger-pad, probe); regels-alinea's
`werkloop-productie.md`/`reconciliatie.md`/`werkvoorraad-controlescherm.md` van 21-09 bijwerken met de meetuitkomst. Te vroeg (deploy niet
live)? Zet `niet vóór:` een uur verder en leg de opdracht terug in inbox/.
---
LEESPLICHT (Domeinen-kopregel): lees EERST volledig docs/regels/werkloop-productie.md, docs/regels/reconciliatie.md,
docs/regels/werkvoorraad-controlescherm.md — niet gelezen = niet beginnen. Werkloop automatisch: rapport + INDEX + gedaan/-kopregel + commit.
