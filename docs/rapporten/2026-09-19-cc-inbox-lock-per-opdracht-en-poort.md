# CC-inbox — lock per opdracht, poort vóór einde, push-retry (19-09)

**Opdracht:** `opdrachten/gedaan/2026-09-19-cc-inbox-lock-per-opdracht-en-wachten-op-suite.md` (procesles inbox-run 19-09 12:46).
**Werkt in productie: n.v.t.** — lokale werkloop op de Mac (launchd-agent, `rlz cc`, Stop-hook); geen productie-rakende stap, geen
migratie, geen RLZ-write. Meetrecept voor de eerste echte run ná deze commit staat onderaan.

## Uitkomst in één alinea

De vijf regels zijn gebouwd en getest tegen het échte script, de échte zsh-functie en echte git (bare origin + bot-kloon). Oppakken van
een opdracht is nu een atomische `mv inbox/X lopend/X` mét claim-bestand (pid/starttijd); de runner-lock `opdrachten/.lock` wordt
atomisch genomen en een tweede starter stopt zichtbaar; een run die ongecommit werk achterlaat krijgt géén "af" meer — het werk gaat
als WIP-commit op `wip/<slug>`, de opdracht blijft in `lopend/` en de volgende poging begint met die branch; exit 0 zonder rapport of
commit is "geen resultaat" en wordt herstart; ongecommit werk bij de start is melding + stop. De Stop-hook roept nu het tracked script
`scripts/git-hooks/stop-push.sh` aan: bij een geweigerde push fetch + `merge --no-ff` + één retry, een echt conflict is een luide
blokkade die `rlz inbox status` toont. Vier keuzes zijn zonder Peter gemaakt en hieronder vastgelegd; de belangrijkste: **merge in
plaats van het gevraagde rebase**.

## Bijvangst tijdens deze run (incident 16:12)

Vlak vóór deze run eindigde de inbox-run `2026-09-19-nameting-projecten-afsluiten-tab-na-deploy` met code 0 op de zin "ik wacht op de
melding" (een achtergrondtaak liep nog) en het script zette 'm mét kopregel "rapport: geen" in `gedaan/` — een vals "af", precies feit
(2) van de opdracht in een nieuwe gedaante. Dat is de aanleiding voor de extra "geen resultaat"-toets (j3). De opdracht is in deze run
teruggezet in `opdrachten/inbox/` (kopregel weg) zodat hij opnieuw loopt.

## Wat er is gebouwd

| # | Regel uit de opdracht | Gebouwd | Waar |
|---|---|---|---|
| 1 | Lock per opdracht, atomisch | `claim_opdracht()`: `mv inbox/X lopend/X` (rename(2), één winnaar), verliezer logt "claim verloren" en neemt de volgende kandidaat; `opdrachten/log/<slug>.claim` = pid/starttijd; dode claim < 30 min "onzeker", ≥ 30 min "gestrand" → herstelpad (e) mét melding; zonder claim = run sloot zelf af → herstel direct; `rlz inbox status` toont per lopend-bestand pid + starttijd; seam `CC_INBOX_CLAIM_ALLEEN=1` voor de race-test | `scripts/cc_inbox.sh`, `scripts/zsh/rlz.zsh` |
| 2 | Eén inbox-runner per repo | `neem_runner_lock()`: `opdrachten/.lock` via O_EXCL (noclobber), dode lock atomisch weggedraaid met `mv`; tweede tick logt "runner-lock net gepakt door pid N" of "wacht — inbox-run actief (pid, sinds, N min)" (was stil); `rlz cc` neemt de lock op dezelfde manier en weigert mét melding | idem |
| 3 | Run eindigt pas ná zijn poort | `wip_wegzetten()`: ongecommit werk (tracked + untracked buiten `opdrachten/`, `.scratch/`, `.claude/`) → WIP-commit op `wip/<slug>` via plumbing mét eigen index (`read-tree`/`add`/`write-tree`/`commit-tree`/`update-ref`; main onaangeraakt, geen `.git/index.lock` nodig, nooit stash), werkboom schoon, marker `.wip`, exitcode 4, opdracht blijft in `lopend/`; volgende poging krijgt "begin met `git merge --squash wip/<slug>` … eindig NOOIT terwijl een suite nog loopt" in de prompt; gedaan-zonder-commit → terug naar `lopend/`; exit 0 zonder rapport/commit/afmelding = GEEN RESULTAAT; ongecommit werk bij de START = melding + stop (hoogstens elk uur) | `scripts/cc_inbox.sh` |
| 4 | Push-conflict nooit alleen "push handmatig" | `scripts/git-hooks/stop-push.sh <repo> <label>` (nieuw, tracked; beide hook-entries in `.claude/settings.local.json` roepen 'm aan): fetch → `merge --no-ff --no-edit origin/main` → retry; conflict = `merge --abort` + stderr mét de exacte commando's + macOS-melding + `opdrachten/log/push.log` + `opdrachten/.push-geblokkeerd`; `rlz inbox status` toont "PUSH GEBLOKKEERD (…)" + "herstel: …", "origin gedivergeerd (N lokaal / M remote) — deploy staat stil" en de wip/-branches; inbox-tick meldt divergentie hoogstens elk uur | `scripts/git-hooks/stop-push.sh`, `scripts/zsh/rlz.zsh`, `scripts/cc_inbox.sh` |
| 5 | Guards + docs | `tests/unit/test_cc_inbox_claim_en_poort.py` (16), `tests/unit/test_stop_hook_push.py` (7); bestaande inbox-guards aangepast; regels-alinea, BESLISSINGEN-sectie, CLAUDE.md regel 7 | zie onder |

## Keuzes zonder Peter (vastgelegd)

1. **Merge, geen rebase (regel 4).** De opdracht vraagt `git pull --rebase` "alleen fast-forward-achtig zonder conflicten". De regel van
   19-09 ochtend in `werkloop-productie.md` ("Stop-hook-push non-fast-forward") zegt nadrukkelijk nooit rebase: de lokale hashes staan
   in het rapport en de BESLISSINGEN-rij die de run zojuist schreef, en een rebase herschrijft precies die commits. Een `merge --no-ff`
   haalt hetzelfde doel (automatische retry, nooit stil) zonder hashes te breken. Wil Peter tóch rebase, dan is dat één regel in
   `stop-push.sh` — maar dan moeten rapporten ophouden hashes te citeren.
2. **Lock-naam `.lock` gehouden**, niet `.runner.lock`/flock: macOS heeft geen `flock`, en `opdrachten/.lock` is al de ene gedeelde lock
   van launchd én `rlz cc` (tests, docs, `rlz inbox status|stop|vrijgeven` kennen 'm). "Geen tweede mechanisme" = bestaande lock
   atomisch maken.
3. **De wip/-branch blijft staan** ná een geslaagde volgende poging (status toont 'm, log noemt `git branch -D`). Het script kan niet
   bewijzen dat de run de squash-merge echt deed; verwijderen doet een mens.
4. **"Geen resultaat"-toets** toegevoegd hoewel niet letterlijk gevraagd: exit 0 zonder nieuw rapport, zonder nieuwe commit en zonder
   zelf naar `gedaan/` te verplaatsen = herstart. Dit is de oorzaak van het incident van 16:12; zonder deze toets zou regel 3 een run die
   "wacht" toch als af boeken.
5. **Overlap met de inbox-opdracht "stop-hook-push-non-fast-forward-stille-deploy-blokkade":** punten 1, 2 en 4 daarvan zijn hier
   gebouwd, bewust zonder bot-only-filter (élke conflictvrije divergentie merget — een mens-commit op origin is even legitiem als een
   bot-commit; een conflict blokkeert luid). Punt 3 (bot-commit uitstellen in `nameting.yml`) blijft een beslissing voor die opdracht;
   het inbox-bestand draagt een kopregel-notitie.
6. **Untracked bestanden** onder `opdrachten/`, `.scratch/` en `.claude/` tellen niet als "vuil" (Cowork schrijft opdrachten untracked;
   scratch en lokale runtime-artefacten horen niet in een WIP); tracked wijzigingen onder `opdrachten/` (bv. een verplaatste, ooit
   gecommitte inbox-opdracht) tellen wél en gaan mee in de WIP.

## Bewijs (tests, allemaal tegen echte scripts/git)

- Claim-race: twee `cc_inbox.sh`-processen mét `CC_INBOX_CLAIM_ALLEEN=1` op één opdracht → precies één `CLAIM`, één `GEEN CLAIM`, het bestand
  staat één keer in `lopend/` (`test_claim_twee_processen_een_wint`).
- Twee ticks tegelijk mét twee opdrachten → precies één "start", de ander logt de wachtregel of "runner-lock net gepakt"; ná afloop 1 in
  gedaan/, 1 nog in inbox/ (`test_twee_ticks_tegelijk_een_run_de_ander_stopt_zichtbaar`).
- Nameting rij 5: twee `rlz cc`-starts tegelijk mét een slapende claude-stub → één loopt ("stub-wakker"), één stopt mét rc 1 en de melding
  wie de lock heeft (`test_twee_rlz_cc_starts_tegelijk_een_loopt_een_stopt_met_melding`).
- WIP: stub laat `backend_nieuw.py` + een README-wijziging ongecommit → rc 4, HEAD gelijk, werkboom schoon, `wip/<slug>` bevat beide
  bestanden mét HEAD als ouder, marker + logregel + melding, opdracht in `lopend/`; volgende tick: "terug naar inbox/, poging 2/3", de
  prompt bevat "git merge --squash wip/<slug>" (`test_ongecommit_werk_…`, `test_volgende_poging_…`).
- Stop-hook (echte bare origin): bot pusht `verkenning/nameting-alles-19-09.txt`, Mac heeft een lokale commit → vóór 19-09 "push handmatig"
  (dat was de shellregel in settings.local.json); nu: merge-commit mét beide ouders op origin, lokale hash bestaat nog, `push.log` "ok ná
  merge (1 + 1 commit(s))", geen melding (`test_geweigerde_push_door_bot_commit_…`). Conflict op README → rc 1, `merge --abort`, werkboom
  als vóór, `.push-geblokkeerd`, melding, `rlz inbox status` "PUSH GEBLOKKEERD" + "origin gedivergeerd (1 lokaal / 1 remote)"; ná een
  handmatige merge ruimt de volgende geslaagde push de blokkade op (`test_conflict_is_luide_blokkade_…`).
- Woordguard: `stop-push.sh` en `cc_inbox.sh` bevatten geen rebase-, force- of stash-commando.

Resultaat: `test_cc_inbox_claim_en_poort.py` + `test_stop_hook_push.py` + `test_cc_inbox_parallel.py` + `test_cc_inbox_herstel.py` +
`test_cc_inbox_pull.py` = **64 passed**. Volledige `backend/tests/unit`-map (alle inbox- en docs-guards): **300 passed, 1 skipped**
(140 s). Vitest/tsc/gouden set niet gedraaid: deze run raakt geen app-, frontend- of intake-code (alleen `scripts/`, `backend/tests/unit/`
en docs), de pre-commit-hook toetst dat; de docs-guards (`test_claude_md_beslissingen_verwijzingen`, `test_rapporten_index`,
`test_rapporten_gelezen_regels`, `test_regels_index`, `test_rapporten_klikpunten`) draaiden ná het schrijven opnieuw: 15 passed.

## Aangepaste bestaande guards (waarom)

- `test_cc_inbox_parallel.py`: "levende inbox-lock blijft stil" → "wacht zichtbaar"; "vuile werkboom = LET-OP maar start" → "melding +
  stop"; `index.lock`-scenario: de stub kan niet committen → poort niet gehaald → WIP via eigen index + LET-OP "werkboom niet
  schoongemaakt", opdracht blijft in lopend/.
- `test_cc_inbox_herstel.py`: fixture committeert nu een schone baseline (was: `git init` zonder commit → alles untracked → stop);
  stubs schrijven een rapport en committen (een afgeronde run doet dat ook); levende lock zonder soort → zichtbare wachtregel.
- `test_cc_inbox_pull.py`: vuile werkboom stopt nu vóór de pull (zelfde effect: geen pull, geen stash); de woordtoets staat `reset -q
  --hard HEAD` precies één keer toe (alleen ná de WIP-commit) en verbiedt een `merge`-commando in het inbox-script.

## Meetrecept (eerste echte run ná deze commit)

1. `rlz inbox status` → toont voor de lopende opdracht "loopt (claim pid N, sinds T)" en, zolang de nameting-bot vóór is, "origin
   gedivergeerd (N lokaal / M remote)".
2. Ná de run: `opdrachten/log/push.log` bevat "push rlz-boekingsmodule ok" óf "ok ná merge (…)"; bij een blokkade staat
   `opdrachten/.push-geblokkeerd` en toont `rlz inbox status` "PUSH GEBLOKKEERD".
3. Twee `rlz cc`-starts in twee terminals: de tweede krijgt "er loopt al een handmatige CC via rlz cc (pid …)" of "runner-lock net gepakt".

## Bestanden

`scripts/cc_inbox.sh`, `scripts/zsh/rlz.zsh`, `scripts/git-hooks/stop-push.sh` (nieuw), `.claude/settings.local.json` (lokaal, niet in
git), `backend/tests/unit/test_cc_inbox_claim_en_poort.py` (nieuw), `backend/tests/unit/test_stop_hook_push.py` (nieuw),
`backend/tests/unit/test_cc_inbox_parallel.py`, `…_herstel.py`, `…_pull.py`, `docs/regels/werkloop-productie.md` (alinea "CC-inbox rij
(j)"), `docs/BESLISSINGEN.md` (sectie "CC-INBOX — LOCK PER OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)"), `CLAUDE.md` (werkloop regel
7), `opdrachten/inbox/2026-09-19-stop-hook-push-non-fast-forward-stille-deploy-blokkade.md` (notitie),
`opdrachten/inbox/2026-09-19-nameting-projecten-afsluiten-tab-na-deploy.md` (teruggezet uit gedaan/).

## Gelezen regels

- `docs/regels/werkloop-productie.md` (87 regels) — volledig gelezen vóór de start (LEESPLICHT uit de Domeinen-kopregel).
