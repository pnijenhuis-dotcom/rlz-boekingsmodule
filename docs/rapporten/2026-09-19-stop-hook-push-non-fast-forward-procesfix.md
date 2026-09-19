# Stop-hook-push non-fast-forward = stille deploy-blokkade — procesfix getoetst, beslissing punt 3 (19-09 avond)

**Opdracht:** `opdrachten/gedaan/2026-09-19-stop-hook-push-non-fast-forward-stille-deploy-blokkade.md` (bevinding poging 1 nameting
kassarapport-autotype, `docs/rapporten/2026-09-19-nameting-kassarapport-autotype-poging-1-deploy-geblokkeerd.md`).
**Werkt in productie: n.v.t.** — lokale werkloop (Stop-hook, inbox-tick, `rlz inbox status`); geen productie-rakende stap, geen migratie,
geen RLZ-write. Wél een bewijs vóór/ná in een tijdelijke kloon (onder).

## Uitkomst in één alinea

Punten 1, 2 en 4 van de opdracht waren al gebouwd in de run "cc-inbox-lock-per-opdracht-en-wachten-op-suite" (rapport
`2026-09-19-cc-inbox-lock-per-opdracht-en-poort.md`, rij (j4)); deze run heeft dat getoetst tegen de opdrachttekst en compleet bevonden,
mét twee bewuste afwijkingen (geen bot-only-filter, merge i.p.v. rebase). Punt 3 (nameting-workflow) is als beslissing vastgelegd:
**`nameting.yml` blijft ongewijzigd** — de bot-commit gaat niet naar een eigen branch en wacht niet op een deploy-run. Toegevoegd zijn
twee guards (reproductie vóór/ná als test, settings-JSON-hookregels zonder git-woord, bot blijft op main) en de regeltekst.

## Toets: wat stond er al, wat ontbrak

| Punt | Opdrachttekst | Stand vóór deze run | Oordeel |
|---|---|---|---|
| 1 | Stop-hook: fetch, bot-only-toets, merge --no-ff, retry; anders luide fout (melding + logregel); ook Platform-repo | `scripts/git-hooks/stop-push.sh` (tracked) voor beide repo's: fetch → merge --no-ff → retry; blokkade = stderr mét commando's + macOS-melding + `opdrachten/log/push.log` + `opdrachten/.push-geblokkeerd` | Compleet; **zonder bot-only-filter** (bewust, zie keuzes) |
| 2 | Inbox-tick: melding (hoogstens elk uur) + logregel bij ff-only-mislukt; `rlz inbox status` toont "origin gedivergeerd (N lokaal / M remote) — deploy staat stil" | `cc_inbox.sh` `meld_hoogstens_per_uur divergentie` + tellers in de logregel; `rlz.zsh` `_rlz_push_stand` toont de regel zolang `main..origin/main` > 0 | Compleet |
| 3 | Nameting-workflow: bot wachten/overslaan bij een deploy binnen het uur, óf eigen branch — alleen als (1)+(2) niet volstaan; beslissing vastleggen | Niet gebouwd (kopregel-notitie in de opdracht) | **Beslissing: niet bouwen** (onder) |
| 4 | Guards inbox (divergentie-melding, status-regel) + Stop-hook-shellregel op de settings-JSON (bot-only-filter, geen rebase/force); regeltekst + BESLISSINGEN + CLAUDE.md | `test_stop_hook_push.py` (7), `test_cc_inbox_pull.py::test_pull_overgeslagen_bij_gedivergeerde_stand_nooit_merge`, `test_cc_inbox_claim_en_poort.py` (statusregel "origin gedivergeerd"); regels-alinea zei nog "(3) procesfix … niet gebouwd" | Guards aangevuld (2), regeltekst/BESLISSINGEN/CLAUDE.md bijgewerkt |

## Beslissing punt 3 — nameting-workflow ongewijzigd

Sinds (1)+(2) is de prijs van een bot-commit tijdens een run precies één merge-commit door de Stop-hook plus één extra deploy op die
merge; de meting zelf verliest niets. Beide alternatieven uit de opdracht kosten meer dan ze opleveren:

- **Bot laten wachten op "geen deploy in het laatste uur"** voegt een bewegend deel toe (gh-API-call, eigen wachtlus) en vertraagt juist
  de metingen die een inbox-run zelf aanvraagt — de bot pusht in de praktijk *tijdens* de run die 'm dispatchte (17-09, 19-09 drie keer).
  De divergentie is dan geen storing maar het normale pad; die lost de Stop-hook nu automatisch op.
- **Bot-bestanden op een eigen branch** breekt de definitie van een meting ("een meting telt pas als het bot-bestand op main staat óf het
  run-log is gelezen", CLAUDE.md werkloop regel 1) en elk `git show origin/main:verkenning/nameting-…`-recept in de memory/regels.

De `git pull --rebase` in de bot-stap blijft: die rebaset uitsluitend de ene verse bot-commit op origin/main; geen rapport citeert die
hash. Guard: `test_nameting_workflow.py::test_bot_commit_blijft_op_main_en_wacht_niet_op_een_deploy` (push naar `HEAD:main`, geen eigen
branch, geen `workflow_run`/`gh run list`-wachtconstructie, precies één `--rebase`).

## Keuzes zonder Peter (vastgelegd)

1. **Geen bot-only-filter** (afwijking van punt 1): de opdracht wil alleen mergen als de binnenkomende commits uitsluitend
   `verkenning/nameting-*`/`lezen-*` raken. Een mens-commit op origin (Peter vanaf een andere Mac, Cowork) is even legitiem; het gevaar
   is een conflict, en dát blokkeert al luid (`merge --abort`, werkboom als vóór, status "PUSH GEBLOKKEERD"). Een filter zou juist de
   mens-commit-situatie weer stil laten worden.
2. **Merge, geen rebase** — bevestigd uit de vorige run: lokale hashes staan in het zojuist geschreven rapport/BESLISSINGEN.
3. **Punt 3 niet bouwen** — zie boven.
4. **Geen macOS-melding bij een geslaagde merge+push**: dat pad is de gewenste automatische afloop; `push.log` en de stderr-regel volstaan.
   Alleen een blokkade meldt.

## Bewijs vóór/ná (tijdelijke kloon: bare origin + mac-kloon + bot-kloon; `.scratch/reproductie-stop-hook.sh`, 19-09 18:48)

Opzet: bot commit `nameting-alles-19-09.txt` op origin/main; de mac heeft lokaal `docs(rapport run)` — exact de stand van 19-09 12:18.

**VÓÓR — oude hook-regel `git push origin main`:**
```
 ! [rejected]        main -> main (fetch first)
error: failed to push some refs to '…/origin.git'
exitcode oude hook: 1
origin/main ná: b9c26b8 nameting 19-09 alles — Oordeel: groen  | lokaal vooruit: 1 / remote vooruit: 1
```
Stderr + exit 1 is alles; in `claude -p` ziet niemand dat, de deploy blijft uit.

**NÁ — `scripts/git-hooks/stop-push.sh`:**
```
push reproductie geweigerd:  ! [rejected]        main -> main (fetch first)
merge origin/main (1 remote commit(s): b9c26b8 test: nameting 19-09 alles — Oordeel: groen) — retry push
push reproductie ok ná merge (1 + 1 commit(s))
Stop-hook reproductie: origin was gedivergeerd (1 lokaal / 1 remote) → merge --no-ff + push geslaagd
exitcode stop-push.sh: 0
*   c3916a6 merge(origin/main — automatisch door de Stop-hook ná een non-fast-forward-push, …; nooit rebase)
|\
| * b9c26b8 nameting 19-09 alles — Oordeel: groen
* | 351fcf9 docs(rapport run)
blokkade-bestand: afwezig (goed) · rebase-sporen (reflog): 0
```
Dezelfde reproductie staat nu als test `test_stop_hook_push.py::test_reproductie_bot_commit_tijdens_run_voor_en_na` (vóór: exit 1 +
"fetch first" + origin alleen de bot-commit; ná: merge-commit mét beide ouders, geen blokkade-bestand, geen rebase in de reflog).

## Gebouwd in deze run

- `backend/tests/unit/test_stop_hook_push.py`: reproductie-test vóór/ná; de settings-JSON-hookregels dragen zelf geen rebase-/force-/push-/
  stash-woord (alle logica in het tracked script).
- `backend/tests/unit/test_nameting_workflow.py`: `test_bot_commit_blijft_op_main_en_wacht_niet_op_een_deploy` (beslissing punt 3).
- `docs/regels/werkloop-productie.md` alinea "Stop-hook-push non-fast-forward = stille deploy-blokkade (19-09)": "(3) … niet gebouwd" →
  gebouwde vorm + beslissingen (a)/(b) + bewijs; BESLISSINGEN "CC-INBOX — LOCK PER OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)" slotalinea;
  CLAUDE.md werkloop regel 6 (één regel).
- Geen wijziging aan `stop-push.sh`, `cc_inbox.sh`, `rlz.zsh`, `nameting.yml`, `.claude/settings.local.json`.

## Tests

- `test_stop_hook_push.py` (8) + `test_nameting_workflow.py` (16) + `test_cc_inbox_pull.py`: 35 passed.
- Docs-guards (`test_claude_md_beslissingen_verwijzingen`, `test_regels_index`, `test_rapporten_index`, `test_rapporten_gelezen_regels`,
  `test_rapporten_klikpunten`): zie commitbericht.

## Meetrecept eerste echte gelegenheid

De volgende keer dat de nameting-bot tijdens een inbox-run op origin/main commit: `opdrachten/log/push.log` toont "geweigerd → merge
origin/main (…) — retry push → ok ná merge", `git log --merges -1` op main is de Stop-hook-merge en de deploy-run start op die merge-commit
binnen ~2 min. Blijft er een `opdrachten/.push-geblokkeerd` staan, dan is `rlz inbox status` de plek.

## Gelezen regels

- `docs/regels/werkloop-productie.md` (162 regels) — volledig gelezen vóór de start (LEESPLICHT uit de Domeinen-kopregel).
