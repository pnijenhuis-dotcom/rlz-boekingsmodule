> uitgevoerd 2026-09-16 (nacht), rapport: docs/rapporten/2026-09-16-cc-inbox-parallel.md

# OPDRACHT 16-09 (nacht) — cc-inbox: twee CC-runs draaiden tegelijk in dezelfde werkboom (16-09 avond) — oorzaak + guard

**Incident (slotrapport `2026-09-16-inbox-afgewerkt-3.md`, "Wat er gebeurde bij de start"):** een handmatige CC-run en een cc-inbox-run
werkten gelijktijdig in dezelfde werkboom; de een committe het werk van de ander (57ca852 om 20:43, c1df300 om 21:36). Het ging goed,
maar dit is precies de klasse "stille brokken" die de guard van 15-09 (rij (f): `claude`-proces mét cwd in deze repo = "wacht —
handmatige CC actief") had moeten voorkomen.

Pre-feature-ritueel: BESLISSINGEN "WERKLOOP AUTOMATISCH — NAMETING-WORKFLOW, RAPPORTEN- EN OPDRACHTENMAP, CC-INBOX" (herstel-tabel),
`scripts/cc_inbox.sh`, `tests/unit/test_cc_inbox_herstel.py`, `opdrachten/log/`.

## Blok A — Oorzaak (lees-only, uit de logs)
- Reconstrueer uit `opdrachten/log/*.log` + `git log --format='%h %ci %s' --since='2026-09-16 19:00'` + de lock-bestanden: welke run
  startte wanneer, welke detectie (pgrep + lsof) faalde en waarom (cwd van de handmatige `claude` niet leesbaar? proces heette anders?
  handmatige run gestart ná de tick-check? lock verlopen?). Eén tijdlijn in het rapport.

## Blok B — Guard sluiten
- Detectie verbreden: niet alleen `pgrep claude` + lsof-cwd, maar óók `.git/index.lock` en een werkboom mét ongecommitte
  wijzigingen van een ándere run (lock-eigenaar-PID in het lockbestand; onbekende PID = wacht). Handmatige CC: `scripts/zsh/rlz.zsh`
  krijgt een `rlz cc`-wrapper die zelf de inbox-lock zet (met PID + "handmatig") zodat de agent het altijd ziet; docs in CLAUDE.md
  Werkwijze-regel + BESLISSINGEN herstel-tabel rij (g).
- Omgekeerd: start een mens `claude` terwijl een inbox-run loopt, dan toont de wrapper "inbox-run actief sinds …, wacht of `rlz
  inbox stop`" — nooit twee schrijvers.
- Guard-test: `tests/unit/test_cc_inbox_parallel.py` (gesimuleerde lock met vreemde PID → geen start; handmatige wrapper zet lock).

## Afronding
Rapport `docs/rapporten/2026-09-1x-cc-inbox-parallel.md` + INDEX ("werkt in productie: n.v.t. — lokale werkloop"), WAT_IS_NIEUW niet
(intern).
