# Nazorg inbox — "pull overgeslagen door untracked bestanden" — 15-09-2026

Opdracht: `opdrachten/gedaan/2026-09-15-inbox-pull-untracked.md` (Cowork, 15-09, klein). Geen migratie, geen productie-writes.
**Werkt in productie: ja, met één kanttekening** — zie § 3: de nameting-bot-commit van 15-09 (`2cea369`) is ná een handmatig
gestarte workflow-run met exact het pull-commando van het script (`git pull --ff-only origin main`) binnengekomen terwijl er
elf untracked paden in de werkboom stonden. De launchd-tick zelf kon ik niet laten pullen: er draaide intussen een tweede,
interactieve Claude-sessie in dezelfde werkboom mét niet-gecommitte TRACKED wijzigingen (en een levende lock) — dat is de
échte overslag-reden van het script, en die is correct.

## 0. Diagnose — de premisse klopt niet

Cowork zag om 08:30 "werkboom vuil door `?? .claude/` en `?? opdrachten/gedaan/…dummy…`" en concludeerde dat de pull daarom
is overgeslagen. Dat is niet wat er gebeurde:

| Feit | Bron |
|---|---|
| Het script kijkt sinds `75008d8` (14-09 15:04) al met `git status --porcelain --untracked-files=no`; untracked bestanden tellen niet als vuil. | `scripts/cc_inbox.sh` regel 116, kopcommentaar regel 36–44 |
| Het inbox-log van 15-09 08:30 bevat géén regel "pull overgeslagen"; het script logt zo'n overslag altijd. De laatste twee overslagen (8 en 33 gewijzigde bestanden) zijn van 14-09, tijdens lopende CC-runs mét tracked wijzigingen. | `~/Library/Logs/cc-inbox.log` regels 54, 57, 119 |
| `origin/main` = lokaal `HEAD` = `a82390d`. Er wás niets te pullen. | `git fetch` + `git log HEAD..origin/main` (leeg) |
| De nameting-workflow heeft op 15-09 **niet** gedraaid: 0 runs met `event=schedule` ooit; de enige run is de handmatige dispatch van 14-09 12:45 UTC (`34845170512`). De workflow staat op `active`, cron `30 5 * * *`. | `gh api …/workflows/357800950/runs?event=schedule` → `total_count: 0` |
| `.claude/` in de repo-root is niet nieuw (24-08) en bevat alleen `settings.local.json` (globaal genegeerd via `~/.config/git/ignore`) en `scheduled_tasks.lock` (genegeerd via `.git/info/exclude`). Voor git op deze Mac is de map `!!` (ignored), niet `??`. Cowork ziet 'm als untracked omdat Cowork's git-omgeving die twee LOKALE ignore-bronnen niet heeft. | `git status --ignored -- .claude`, `git check-ignore -v` |

Wortel: **de eerste geplande run van een nieuw toegevoegd `schedule`-workflow-bestand (gecommit 14-09 14:17 CEST) is door GitHub
niet afgevuurd.** Bekend GitHub-gedrag: scheduled runs kunnen bij drukte vertragen of uitvallen, en een cron die voor het eerst
op de default-branch staat wordt niet altijd op de eerste gelegenheid ingepland. Of het structureel is weet ik ná 16-09 05:30 UTC.

## 1. Punt 1 — "schoon" = alleen tracked bestanden

Al gebouwd op 14-09; geen scriptwijziging nodig. Guard-test uitgebreid (`backend/tests/unit/test_cc_inbox_pull.py`, 7 → 9):
- `test_untracked_buiten_inbox_houdt_pull_niet_tegen`: untracked `opdrachten/gedaan/…dummy.md` + untracked `.claude/scheduled_tasks.lock`
  in de 'Mac'-kloon, bot pusht → HEAD = bot-commit, logregel "pull ff-only 1 commit(s) binnen", géén "overgeslagen", beide untracked
  bestanden staan er nog (nooit stash/clean).
- `test_gestaged_tracked_bestand_telt_als_vuil`: een gestagede wijziging aan een tracked bestand is wél vuil → overgeslagen mét
  logregel, index onaangeraakt.
- Statische toets: de string `status --porcelain --untracked-files=no` moet in het script staan.
Resultaat: 9 groen; `test_cc_inbox_herstel.py` + `test_nameting_workflow.py` + `test_rapporten_index.py` 27 groen.

## 2. Punt 2 — gedaan-bestand en `.claude/`

- `opdrachten/gedaan/2026-09-14-dummy-inbox-herstel.md` gecommit (hoorde bij de herstel-run 14-09 avond; CC-run van 20:00 had 'm
  bewust niet aangeraakt).
- `.claude/`: **niets verwijderd**. De map is niet nieuw en niet leeg; de inhoud is Claude Code-runtime. Toegevoegd aan `.gitignore`:
  `.claude/settings.local.json`, `.claude/*.lock`, `.claude/scheduled_tasks.json` — zodat élke kloon en élke agent-omgeving (ook
  Cowork zonder de Mac-lokale ignore-bronnen) dezelfde schone stand ziet. Bewust géén `.claude/` als geheel: een gedeelde
  `.claude/settings.json` of skills-map moet later gewoon committable blijven.

## 3. Punt 3 — pull en de 15-09-nametingrapporten

Omdat de cron niet liep, was er om 08:30 niets te pullen. Ik heb de dagelijkse nameting handmatig gestart
(`gh workflow run nameting.yml -f onderdeel=alles`, run `34937392494`, 06:32 UTC) — lees-only, dezelfde job die om 05:30 had
moeten lopen, onder `nameting@` via WIF.

Uitkomst:

| Wat | Waarde |
|---|---|
| Run | `34937392494`, `completed/success`, 06:32 → 07:07 UTC (35 min; `alles` is zwaarder dan de 7 min van de reconciliatie-run 14-09) |
| Bot-commit | `2cea369` "nameting 15-09 alles — Oordeel: ROOD", 8 bestanden `verkenning/nameting-*-15-09.txt` |
| Pull | `git pull --ff-only origin main` → Fast-forward (reflog), 11 untracked paden aanwezig, geen merge-commit, niets gestasht |
| Oordeelregel | uit `nameting-vgg-replay-15-09.txt`: "ROOD — 1 verschil(len), 1096 niet vertaalbaar (waarvan 1096 alleen door de ontbrekende doelkoppeling), 0 leesfouten, 0 documenten zonder regels, 0 regelsom ≠ totaal". De zeven andere rapporten dragen geen `Oordeel:`-regel (het commitbericht koos daarom terecht de replay-regel). Inhoudelijke duiding van dat ene verschil valt buiten deze opdracht — Cowork kan het rapport nu lokaal lezen. |

Kanttekening op de meting: mijn twee commits (`45a124c`, `270f040`) stonden al op origin vóórdat de bot committe (de bot bouwde
er bovenop, `2cea369` → `270f040`). Ik push zelf nooit; de push kwam van de Stop-hook van de tweede Claude-sessie die
tegelijk in deze werkboom werkte (opdracht `2026-09-15-odoo-companynaam-volgen`, zie § 4). Daardoor was de pull een zuivere
fast-forward in plaats van "gedivergeerd". Zonder die toevallige push had het script óók niet kunnen pullen — een lokale
CC-run die over 05:30 UTC heen loopt maakt de branch altijd gedivergeerd tot de Stop-hook pusht. Dat is aanvaard gedrag
(nooit rebase in het script); de eerstvolgende lege tick ná de push haalt de bot-commit dan wél binnen.

## 4. Keuzes zonder Peter

- De nameting handmatig starten: dit is precies het dagelijkse lees-only recept, alleen 62 minuten later; het levert de rapporten
  die Cowork wilde lezen. Geen writes op productie.
- Geen automatische "cron gemist"-bewaking gebouwd (buiten de opdracht). Beslispunt hieronder.
- `.gitignore`-regels smal gehouden (drie patronen), niet `.claude/` als map.
- **Parallelle sessie in dezelfde werkboom.** Tijdens deze run bleek een tweede, interactieve `claude`-sessie (pid uit
  `opdrachten/.lock`, gestart ±08:47 CEST vanuit een terminal) aan de opdracht `odoo-companynaam-volgen` te werken: ~19
  gewijzigde tracked bestanden + migratie 0144 ongecommit in de werkboom. Ik heb géén van die bestanden aangeraakt, niet
  gerebased/gestasht, en alleen mijn eigen paden gecommit. Mijn eigen lock-poging aan het begin (`echo $$`) schreef de pid
  van een wegwerp-bash-subshell en was dus direct "dood" — de tweede sessie heeft de lock daarna overschreven. Les voor CC-runs:
  de lock moet de pid van het `claude`-proces dragen (grootouder van het Bash-commando), niet `$$`.

## 5. Beslispunten voor Peter / Cowork

1. **Gemiste cron zichtbaar maken.** Als de cron op 16-09 05:30 UTC wél loopt, was dit een eenmalige GitHub-eigenaardigheid. Loopt hij
   opnieuw niet, dan is een vangnet nodig: óf een tweede cron-regel (bv. `45 5 * * *`, de concurrency-group voorkomt dubbel werk), óf
   een bewakingsprobe "geen nameting-commit vandaag ná 07:00 UTC" in `rlz-bewaking` (LET-OP in de reconciliatiemail). Mijn advies:
   de tweede cron-regel — nul code, en de workflow is toch idempotent per dag.
2. **Twee Claude-sessies in één werkboom is een risico** (verwevenheid van commits, hooks die elkaars werk pushen). Als Cowork én
   een terminal-sessie parallel moeten kunnen werken: een tweede kloon of `git worktree` voor de interactieve sessie.
3. Cowork leest de werkboom met een git zonder de Mac-lokale ignore-bronnen; ná deze commit ziet Cowork `.claude/` ook als genegeerd.
   Meldt Cowork opnieuw `??`-paden, dan eerst `git status --porcelain --untracked-files=no` lezen: alleen dát is de maat van het script.
