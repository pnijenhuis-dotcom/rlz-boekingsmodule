Domeinen: werkloop-productie, werkvoorraad-controlescherm

niet vóór: 2026-09-23 09:00

# Nameting trigger-pad "Boeken in RLZ" → job `rlz-boek-wachtrij` binnen 2 min — POGING 2 (van hoogstens 3)

Poging 1 (`docs/rapporten/2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md`): command/smoketest/schedulers/job/probe/auto-sluiting
werken in productie; het TRIGGER-PAD is niet gemeten omdat er ná de deploy van 21-09 17:38 UTC geen enkele indiening was. Regel 22-09: een
vervolg-opdracht die op een klik/gebruik wacht legt zichzelf terug mét `niet vóór:` +1 dag, hoogstens drie keer, daarna `mislukt/` mét klikpunt.
BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)" alinea "Gemeten 22-09".

## Stap 0 — deploy-check (kort)
- `git fetch origin main` + `git rev-list --count main..origin/main` (> 0 → `git merge --no-ff origin/main`, nooit rebase).
- `gcloud run jobs describe rlz-boek-wachtrij --region europe-west4 --format="value(spec.template.spec.template.spec.containers[0].image, spec.template.spec.template.spec.containers[0].command)"` = HEAD-image + `python`.

## Stap 1 — meetlat (lees-only, bot-bestand op main)
- `gh workflow run nameting -f onderdeel=jobs-start` → wacht op de bot-commit `verkenning/nameting-jobs-start-<dd-mm>.txt` (het commitbericht draagt
  sinds 22-09 de eigen oordeelregel — staat er tóch een replay-regel, dan is dát een bevinding).
- Lees élke `ingediend` ná 2026-09-21 17:38 UTC in de sectie db-lezen: hoort een `trigger` `geslaagd` binnen 1 s en een `afgerond`
  `geboekt`/`mislukt` mét verwerker `job` binnen 2 min bij → "trigger-pad werkt in productie: JA" mét de drie tijdstippen per document.
  Terugval: request-log `rlz-backend` POST `/boeken` 202 + Cloud Logging job-kant "N boeking(en) afgerond" mét N > 0 en de executienaam.
- Nog steeds geen indiening? Poging 3 mét `niet vóór:` +1 dag. Ná poging 3 → `opdrachten/mislukt/` mét dit klikpunt letterlijk:
  "één klik 'Boeken in RLZ' van Peter op de RLZ-testadministratie (RLZ-adminId 8dbfb856-d75b-4ec3-9124-c8b739fe3bc5 = platform faae29c5,
  gearchiveerd 30-08 zonder credential → éérst dearchiveren mét de TESTADMIN-login, Boeken AAN; TEST-referentie); daarna
  `gh workflow run nameting -f onderdeel=jobs-start`". Nooit zelf een boeking indienen op een klantadministratie.

## Afronding
Rapport `docs/rapporten/<datum>-nameting-boek-wachtrij-trigger-pad-poging-2.md` + INDEX-regel + "## Gelezen regels"; BESLISSINGEN-alinea
"Gemeten 22-09" aanvullen mét "trigger-pad: werkt in productie ja/nee"; regels-alinea's `werkloop-productie.md` en `werkvoorraad-controlescherm.md`
van 22-09 bijwerken. Te vroeg (geen indiening) → deze opdracht terug in inbox/ mét `niet vóór:` +1 dag en "POGING 3" in de kop.
