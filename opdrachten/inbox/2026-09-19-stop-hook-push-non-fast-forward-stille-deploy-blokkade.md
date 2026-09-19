Domeinen: werkloop-productie

# OPDRACHT 19-09 — Procesfix: Stop-hook-push non-fast-forward = stille deploy-blokkade (bevinding poging 1 nameting kassarapport-autotype,
# docs/rapporten/2026-09-19-nameting-kassarapport-autotype-poging-1-deploy-geblokkeerd.md)

**Wat er misging (19-09):** de nameting-bot committe om 12:18 op origin/main terwijl een inbox-run liep; de Stop-hook-push van die run en
van vijf volgende runs faalde non-fast-forward (alleen stderr + exit 1, onzichtbaar in `claude -p`), de inbox-tick sloeg de gedivergeerde
branch bewust over → drie uur geen deploy terwijl vier na-deploy-nametingen wachtten. Hersteld door een handmatige merge (`6dafb0f`).

## Te bouwen (voorstel — toets eerst of het past bij WERKWIJZE en de deny-lijst; nooit rebase, nooit force, `git push` alleen in de hook)
1. Stop-hook (`.claude/settings.local.json`): bij een geweigerde push eerst `git fetch origin`; raken de binnenkomende commits UITSLUITEND
   `verkenning/nameting-*` / `verkenning/lezen-*` (bot-only, toets op `git diff --name-only main...origin/main`), dan `git merge --no-ff
   origin/main -m "merge(origin/main — nameting-bot …)"` en opnieuw pushen; anders luide fout: macOS-melding + regel in
   `opdrachten/log/` ("PUSH GEBLOKKEERD — origin gedivergeerd (N lokaal / M remote)"). Zelfde logica voor de Platform-repo-hook.
2. `scripts/cc_inbox.sh`: bij "pull overgeslagen — ff-only mislukt" óók een macOS-melding (hoogstens elk uur) en de regel in het
   opdrachtenlog; `rlz inbox status` toont "origin gedivergeerd (N lokaal / M remote) — deploy staat stil" zolang `main..origin/main` > 0.
3. Nameting-workflow (`.github/workflows/nameting.yml`): overweeg de bot-commit te laten wachten/overslaan als er binnen het laatste uur
   een deploy-run liep, óf de bot-bestanden op een eigen branch te zetten — alleen als (1)+(2) niet volstaan; beslissing vastleggen.
4. Guards: `tests/unit/test_cc_inbox_*.py` uitbreiden (divergentie-melding, status-regel), Stop-hook-shellregel getoetst in een unit-test op de
   settings-JSON (bot-only-filter, geen rebase/force-woord). Regeltekst: `docs/regels/werkloop-productie.md` alinea "Stop-hook-push
   non-fast-forward = stille deploy-blokkade (19-09)" aanvullen mét de gebouwde vorm + BESLISSINGEN-rij + hooguit één regel CLAUDE.md.
Geen productie-rakende stappen; werkt in productie: n.v.t. (lokale werkloop) — wél een bewijs: reproduceer de blokkade in een tijdelijke
kloon (bare origin + bot-commit) vóór en ná de fix en zet beide uitkomsten in het rapport.
