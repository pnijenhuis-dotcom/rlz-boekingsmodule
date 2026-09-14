# Rapport 14-09-2026 — Werkloop automatisch: nameting-workflow, rapporten-/opdrachtenmap, CC-inbox

Opdracht Peter 14-09: "alles wat automatisch kan gaat automatisch; Peter test en meldt, geen plakwerk meer." Canoniek:
BESLISSINGEN "WERKLOOP AUTOMATISCH — NAMETING-WORKFLOW, RAPPORTEN- EN OPDRACHTENMAP, CC-INBOX (besluit Peter 14-09)".
Geen migratie, geen klantfeature (WAT_IS_NIEUW leeg).

## Wat er staat

**A. Nameting als GitHub Actions-workflow** — `.github/workflows/nameting.yml`
- Dagelijks 05:30 UTC (07:30 NL) én `workflow_dispatch` met input `onderdeel` (alles|a|b|c|d|e|reconciliatie).
- Auth via WIF met dezelfde provider als deploy.yml, als `nameting@rlz-boekhouding` (nooit deploy@, geen keys).
- Stappen: `scripts/gcp/vgg_blok7_nameting.sh <onderdeel>` + `scripts/gcp/nameting.sh reconciliatie-alles --lees-only`
  naar `verkenning/nameting-reconciliatie-<dd-mm>.txt`. `nameting_env.sh` herkent `GITHUB_ACTIONS=true` en zet dan geen
  impersonatie-vlag; lokaal gedrag ongewijzigd.
- Commit als `nameting-bot <nameting@rlz-boekhouding.iam.gserviceaccount.com>`, alleen `verkenning/nameting-*.txt`,
  bericht `nameting <dd-mm> <onderdeel> — <Oordeel-regel replay-rapport>`, push met GITHUB_TOKEN. Geen wijzigingen = geen
  commit. Rood rapport = exit 0; alleen deploy-drift (exit 3) en auth-/executiefouten maken de run rood. Een push met
  GITHUB_TOKEN start geen nieuwe workflow — de deploy-workflow blijft stil op een nameting-commit.
- IAM-script `scripts/gcp/nameting_wif_iam.sh` (dry-run default, `--apply` schrijft, idempotent).
- Guard `backend/tests/unit/test_nameting_workflow.py` (7 tests, groen).

**B. Rapporten en opdrachten via bestanden**
- `docs/rapporten/<jjjj-mm-dd>-<blok-slug>.md` + `INDEX.md` (nieuwste bovenaan); guard `test_rapporten_index.py` (4, groen).
- `opdrachten/inbox/` → `lopend/` → `gedaan/` (kopregel "uitgevoerd <datum>, rapport: …"); mappen gecommit, log + lock in .gitignore.
- `scripts/cc_inbox.sh` (oudste bestand, lock mét pid, `claude -p … --permission-mode acceptEdits`, log, macOS-melding).
- launchd-agent `nl.aknijenhuis.cc-inbox` (WatchPaths + 300 s), `scripts/cc_inbox_install.sh [--uninstall]`.
- `scripts/zsh/rlz.zsh`: `rlz plan | meting [onderdeel] | status | inbox`.

**C. Documentatie** — CLAUDE.md § Werkwijze blok "Werkloop automatisch (14-09)" (één verwijsregel, guard groen, 105k tekens);
BESLISSINGEN-sectie met reden (plakwerk weg; beslispunt SA-key 10-09 vervalt door WIF) en de aan/uit-knoppen.

## Uitkomst dry-run IAM (14-09, als info@vastly.software, lees-only)

```
(a) roles/iam.workloadIdentityUser op nameting@ voor principalSet://…/workloadIdentityPools/github/attribute.repository/pnijenhuis-dotcom/rlz-boekingsmodule
    ✗ ONTBREEKT
(b) provider github/github-oidc: state ACTIVE, conditie assertion.repository == 'pnijenhuis-dotcom/rlz-boekingsmodule'  ✓ (geldt ook voor deploy@)
(c) nameting@: projectbreed roles/logging.viewer + roles/run.viewer; job rlz-reconciliatie: projects/rlz-boekhouding/roles/nametingUitvoerder  ✓ exact, geen extra
```

**Wat Peter nog doet (één commando, als owner):**

```
scripts/gcp/nameting_wif_iam.sh --apply
```

Daarna `rlz meting reconciliatie` (of GitHub → Actions → nameting → Run workflow) = de eerste échte meting.

## Test cc_inbox op deze Mac (14-09)

- `scripts/cc_inbox_install.sh`: toolcheck ✓ claude `~/.local/bin/claude`, git `/usr/bin/git`, gcloud `/opt/homebrew/bin/gcloud`,
  osascript; agent geladen (`launchctl print gui/501/nl.aknijenhuis.cc-inbox`).
- Dummy `opdrachten/inbox/2026-09-14-dummy-test.md` neergezet 14:12:50 → launchd startte cc_inbox.sh 14:12:51 (WatchPaths, geen
  wacht op het 300 s-interval), `claude -p` 13 s, exit 0, slotregel "test — dummy geslaagd", bestand naar `gedaan/` mét kopregel
  "uitgevoerd 2026-09-14, rapport: geen". Melding via `osascript display notification` verstuurd (exit 0); of hij op het scherm
  verscheen kan ik niet zien — Peter bevestigt.

## Aandachtspunten

1. `acceptEdits` in `claude -p` weigert Bash buiten de allow-lijst zonder mens → een echte bouwopdracht kan dan niet zelf
   `git commit`/`mv`. Het script vangt de verplaatsing naar gedaan/ op; de commit blijft dan liggen. Advies:
   `CC_INBOX_PERMISSION_MODE=auto` (deny-lijst blijft gelden) — default volgt de opdracht.
2. De workflow draait `vgg_blok7_nameting.sh alles` dagelijks mee (a–e, ~17 job-executies); na afronding run 2 VGG de schedule
   op `reconciliatie` zetten.
3. Nameting-commits door nameting-bot triggeren bewust geen deploy (GITHUB_TOKEN-regel).

## Tests

- `tests/unit/test_nameting_workflow.py` 7 groen, `tests/unit/test_rapporten_index.py` 4 groen,
  `tests/unit/test_claude_md_beslissingen_verwijzingen.py` groen, gouden set `tests/keten` groen, `tsc -b` groen (zie commit).

**Werkt in productie:** workflow **niet gemeten, wacht op IAM** (`--apply` door Peter; eerste `workflow_dispatch` groen = ja).
CC-inbox + launchd: **ja** (dummy 14-09 op deze Mac). IAM dry-run: **ja** (lees-only uitgevoerd).
