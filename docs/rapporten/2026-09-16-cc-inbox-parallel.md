# Rapport 16-09 (nacht) — cc-inbox: twee CC-runs tegelijk in dezelfde werkboom — oorzaak + guard

Opdracht: `opdrachten/gedaan/2026-09-16-cc-inbox-parallelle-runs-guard.md`. **Werkt in productie: n.v.t. — lokale werkloop.**
Geen migratie, geen WAT_IS_NIEUW (intern).

## Blok A — Oorzaak (lees-only uit `~/Library/Logs/cc-inbox.log`, `opdrachten/log/`, `git log`)

| Tijd (16-09) | Wat | Bron |
|---|---|---|
| 16:18–16:51 | Handmatige CC pid 32137 in de repo → 8 ticks "wacht — handmatige CC actief" (rij (f) werkt) | cc-inbox.log |
| 16:52:47 | Inbox-run `verplichting-projectveld-combobox` start (poging 1) | opdrachtenlog |
| 20:19:16 | Die run eindigt code 0 — mét onafgerond werk in de werkboom ("sweeps lopen nog … commit ik" en toch gestopt) | opdrachtenlog |
| 20:24:06 | Inbox-run `omzet-store` start; op dát moment geen claude-proces in de repo → geen wacht, lock `opdrachten/.lock` (pid) gezet | cc-inbox.log |
| 20:24–21:04 | Peter start een handmatige `claude` (pid 36860) in de repo voor rij 3 (capture besluiten, VGG blok 9, accordeur-uitnodiging). Niets aan de mens-kant leest de lock | git log: f3dee5c 21:04 |
| 20:43:06 | Inbox-run commit 57ca852 = het achtergebleven werk van de verplichting-run | git log + omzet-rapport "Vorige run gecommit" |
| 21:08:28 | Handmatig: 94a2887 + ea024aa (VGG blok 9); de gedeelde test-DB wordt gereset midden in de inbox-pytest | omzet-rapport "Parallelle sessie" |
| 21:36:44 | Inbox-run commit c1df300 (omzet); 21:37:23/32 handmatig 12ced32 + b1a88e3 — 39 s uit elkaar, één werkboom | git log |
| 21:39:43 | Inbox-run klaar (75 min) | opdrachtenlog |
| 21:44:44 → 22:41 | Ticks zien pid 36860 wél en wachten (17×) | cc-inbox.log |

**Conclusie.** De detectie van rij (f) (pgrep + lsof-cwd) was niet stuk: elke tick vóór en ná de run zag de handmatige sessie. Het gat is
richting en moment: de check draait alleen bij de START van een inbox-run, en een mens die daarná `claude` start ziet de lock nooit.
Tweede gat, bewezen tijdens deze run: een claude-proces kan een cwd BUITEN de repo hebben terwijl het erin werkt (pid 44249 met cwd
"Vastgoed software" op dezelfde Mac) — cwd-detectie is dan blind. Derde bevinding: `pgrep -x claude` vanuit een kindproces van claude
ziet zijn eigen voorouder niet (36860 ontbrak in de uitvoer binnen deze sessie) — voor launchd irrelevant, voor een wrapper wel:
de wrapper leest daarom de lock, niet de proceslijst.

## Blok B — Guard gesloten

| # | Wat | Waar |
|---|---|---|
| g1 | Lock = drie regels pid / soort (`inbox` \| `handmatig`) / starttijd; levende `handmatig`-lock → logregel "wacht — handmatige CC (rlz cc) actief (pid N, sinds T)" + exit 0; levende `inbox`-lock stil; dode lock mét soort gemeld en opgeruimd; lock zonder soort = `inbox` (oud) | `scripts/cc_inbox.sh` |
| g2 | `.git/index.lock` aanwezig → wachten mét logregel (eigenaar onbekend); ouder dan `CC_INBOX_INDEX_LOCK_MAX_S` (1800 s) → "verweesd, genegeerd (niet verwijderd)" en door | `scripts/cc_inbox.sh` |
| g3 | Werkboom niet schoon bij het oppakken → LET-OP-regel in het opdrachtenlog (N tracked bestanden); geen blokkade — de CC-run beslist (zoals 57ca852). Blokkeren zou de inbox ná élke gestopte run voorgoed stil zetten | `scripts/cc_inbox.sh` |
| wrapper | `rlz cc [claude-args]`: weigert bij een levende `inbox`-lock ("inbox-run actief sinds …, wacht of `rlz inbox stop`"), ruimt een dode lock op, zet de `handmatig`-lock mét de shell-pid, start `claude`, ruimt de lock op in een `always`-blok; `rlz inbox status` toont de lock; `rlz inbox stop` stuurt TERM aan de inbox-run (trap → GESTOPT-regel, opdracht terug via (e)) en weigert een handmatige lock te stoppen; zombies tellen als dood; seam `RLZ_REPO` voor de test | `scripts/zsh/rlz.zsh` |
| guard | 10 tests: handmatige lock mét vreemde levende pid → geen start, zichtbaar; inbox-lock stil; dode lock mét soort → opgeruimd, nieuwe lock draagt soort + tijd; index.lock wacht / verweesd genegeerd niet verwijderd; vuile werkboom LET-OP + start; `rlz cc` zet lock + ruimt op; weigert bij inbox-lock zonder claude te starten; ruimt dode lock op; status/stop incl. TERM-bewijs; documentatiestrings | `backend/tests/unit/test_cc_inbox_parallel.py` |

Bestaande guards `test_cc_inbox_herstel.py` (21) en `test_cc_inbox_pull.py` blijven groen.

## Werkwijze-regel (nieuw)

Handmatige Claude Code in deze repo start via `rlz cc`, niet via kale `claude` — alleen dan ziet de launchd-tick de sessie gegarandeerd
(óók bij een cwd buiten de repo). Kale `claude` blijft door rij (f) meestal gezien, maar zonder garantie. Vastgelegd in CLAUDE.md
§ Werkwijze (werkloop-regel) en BESLISSINGEN herstel-tabel rij (g).

## Niet gedaan (bewust)

- Geen blokkade op een vuile werkboom (g3) — zie boven.
- Geen automatische `git stash`/`reset` van andermans werk — nooit.
- De inbox-run leest de lock van de mens, de mens leest de lock van de inbox; een kale `claude` buiten `rlz cc` blijft afhankelijk van rij (f).
