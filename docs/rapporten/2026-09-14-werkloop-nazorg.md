# Werkloop nazorg — lokale pull + commitbericht per onderdeel — 14-09-2026

Opdracht: `opdrachten/gedaan/2026-09-14-werkloop-nazorg-pull-en-commitbericht.md` (Cowork, 14-09). Geen migratie, geen
productie-writes, geen klantfeature (WAT_IS_NIEUW bewust leeg).

**Werkloop automatisch: werkt in productie: ja.** Workflow-run 34845170512 (`workflow_dispatch`, onderdeel `reconciliatie`,
gestart 14-09 12:45 UTC op `353ee68`) eindigde `success`; nameting-bot committe `f4c702c` (`verkenning/nameting-reconciliatie-14-09.txt`,
738 regels) op origin/main. Daarmee is het meetrecept uit BESLISSINGEN "WERKLOOP AUTOMATISCH" stap (1)–(3) doorlopen: WIF als
`nameting@` werkt, de commit landt, er startte geen deploy achter de bot-push. Stap (4) — de eerste cron-run 07:30 NL met
`alles` — volgt op 15-09.
**Deze nazorg zelf: werkt in productie: niet gemeten** — de nieuwe oordeelregel-keuze draait pas bij de volgende workflow-run; de
lokale pull is op deze Mac getest via het échte script tegen wegwerp-repo's (zie Tests), niet via een launchd-tick.

## Wat is gedaan

| # | Punt | Uitkomst | Waar |
|---|---|---|---|
| 1 | Lokale pull in het inbox-script | `pull_ff_only()` draait ná de lock-check en vóór het zoeken van een opdracht — dus vóór het oppakken én bij elke launchd-tick zonder werk (StartInterval 300). Voorwaarden: geen levende lock (die tak eindigt al eerder), werkboom schoon. `git pull --ff-only origin main`; mislukt ff-only (gedivergeerd/geen netwerk) = overslaan mét logregel, lokale stand onaangeraakt. Nooit rebase/merge/stash. Alleen loggen als er iets binnenkwam of overgeslagen is (geen "Already up to date" om de vijf minuten in `~/Library/Logs/cc-inbox.log`). `CC_INBOX_GEEN_PULL=1` slaat de pull over (handmatige start/test). | `scripts/cc_inbox.sh` |
| 2 | Oordeelregel per gedraaid onderdeel | `OORDEEL_BRON` = `nameting-reconciliatie-<dd-mm>.txt` bij `reconciliatie`, anders `nameting-vgg-replay-<dd-mm>.txt`; `grep -m1 'Oordeel: …'` daaruit; niets gevonden of bestand afwezig → `geen oordeelregel (N rapport(en) van <dd-mm>)`. Run f4c702c had met deze regel "nameting 14-09 reconciliatie — geen oordeelregel (2 rapport(en) van 14-09)" gedragen in plaats van de replay-regel "GROEN ZONDER DOEL". | `.github/workflows/nameting.yml` |
| 3a | Guard punt 2 | `test_nameting_workflow.py` +6 tests: het oordeel-fragment wordt LETTERLIJK uit de workflow geknipt en met bash gedraaid tegen fixture-rapporten (reconciliatie mét replay aanwezig → niet de replay-regel; reconciliatie mét eigen `Oordeel:` → die; alles/c/a → replay; geen rapport → "geen oordeelregel"; commitbericht-vorm). | `backend/tests/unit/test_nameting_workflow.py` |
| 3b | Test punt 1 | Nieuw `test_cc_inbox_pull.py` (7 tests, Python-wrapper om het échte script): bare origin + "mac"-kloon + "bot"-kloon. Bot pusht → tick zonder werk haalt 'm ff-only binnen (0 merges); geen nieuws → geen logregel; vuile werkboom → overgeslagen mét logregel, wijziging blijft staan (geen stash); untracked opdracht in inbox/ houdt de pull niet tegen én wordt daarna gewoon opgepakt (claude-stub); gedivergeerd → overgeslagen, HEAD ongewijzigd, 0 merges; levende lock → niets, ook geen pull; statische check: `--ff-only` aanwezig, geen stash/merge/rebase/reset in de code. | `backend/tests/unit/test_cc_inbox_pull.py` |
| 4 | Vastlegging | Deze rapportregel + INDEX; BESLISSINGEN "WERKLOOP AUTOMATISCH" rij "Nazorg 14-09" + productie-uitkomst; CLAUDE.md § Werkwijze regel (1)/(3) aangevuld (één zin per punt). | `docs/`, `CLAUDE.md` |

## Tests

- `tests/unit/test_nameting_workflow.py` + `tests/unit/test_cc_inbox_pull.py`: 21 passed (~20 s, de git-repo's per test).
- `bash -n scripts/cc_inbox.sh` schoon; executable-bit staat (755). Ruff check + format schoon op de twee testbestanden.
- Guards `test_rapporten_index`, `test_claude_md_beslissingen_verwijzingen`: groen (zie commit).

## Keuzes zonder Peter (vastgelegd)

1. **"Werkboom schoon" = geen gewijzigde TRACKED bestanden** (`git status --porcelain --untracked-files=no`), niet letterlijk
   `git status --porcelain` leeg. Reden: een nieuwe opdracht in `opdrachten/inbox/` is untracked; met de letterlijke lezing zou de
   pull precies dan overgeslagen worden wanneer er werk staat — en Cowork's bot-rapporten zouden nooit binnenkomen zolang er
   opdrachten liggen. Git weigert een ff-pull die een untracked bestand zou overschrijven toch zelf (dan valt het onder "ff-only
   mislukt" → overslaan mét logregel). Getest.
2. **Gedivergeerde stand = overslaan, niet oplossen.** Bij de start van deze run stond de Mac `ahead 3, behind 1` (drie lokale
   commits van de nazorg-7d-run waren nog niet gepusht toen de bot pushte). Ik heb dat als CC-run éénmalig opgelost met
   `git pull --rebase origin main` (alleen een nieuw txt-bestand van de bot, geen conflict) zodat de Stop-hook weer kan pushen —
   het script zelf doet dat bewust NIET. Structureel: de Stop-hook pusht met een kale `git push origin main`; als de bot tussen
   commit en push pusht, faalt die push zichtbaar en meldt "push handmatig". Dat blijft zo (geen automatische rebase in een hook);
   met de dagelijkse cron om 07:30 NL en Cowork-runs overdag is de kans klein, en de pull bij elke tick maakt het venster kleiner.
3. **"Anders replay" letterlijk gevolgd** voor a/b/d/e: de opdracht zegt reconciliatie → reconciliatie-rapport, anders replay. Voor
   een losse `a`/`b`/`d`/`e`-run bestaat er die dag meestal geen replay-rapport → "geen oordeelregel (N rapport(en) …)", wat klopt:
   die onderdelen dragen geen Oordeel-regel. Staat er wél een replay van eerder die dag, dan wordt die genomen (zelfde dag, zelfde
   beeld) — aanvaard; een per-onderdeel-bron is één regel extra als dat ooit stoort.
4. De oude telling "N rapport(en) van <dd-mm>" blijft als achtervoegsel in de fallback staan — het commitbericht zegt dan nog steeds
   hoeveel bestanden de run raakte.

## Volgende stap

- 15-09 07:30 NL: eerste cron-run `alles` → verwacht commit `nameting 15-09 alles — Oordeel: …` (replay-regel, terecht) én daarna
  binnen 5 min op deze Mac via de tick-pull (logregel `pull ff-only 1 commit(s) binnen` in `~/Library/Logs/cc-inbox.log`). Dat is de
  productienameting van dit blok.
- Het launchd-agent leest het script bij elke start opnieuw; herinstallatie is niet nodig.
