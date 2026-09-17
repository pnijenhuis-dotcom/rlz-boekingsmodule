# Rapport 17-09 — cc-inbox: zeven uur geen inbox-start terwijl zes opdrachten klaarlagen — oorzaak uit de logregels, fix "wachten is nooit stil" (rij h)

Blok "als laatste" uit de run-opdracht van Peter 17-09. Geen migratie; lokale werkloop. **Werkt in productie: n.v.t. (lokale launchd-werkloop); guards groen.**

## Oorzaak — letterlijk uit de logs (niet geraden)
- `~/Library/Logs/cc-inbox.log`: laatste inbox-start `>> cc_inbox: start 2026-09-17-native-ota-nameting (2026-09-17T08:12:35, poging 1/3)` → `>> cc_inbox: claude eindigde met code 0 (2026-09-17T08:19:41, 7 min)`. Daarna élke tick, van `10:15:12` tot `15:23:48`, dezelfde regel:
  **`>> cc_inbox: wacht — handmatige CC actief (pid 82714, /Users/mr.x/Claude/Projects/Rlz boekings module) — geen herstel, geen pull, geen start; volgende tick opnieuw`**
- `ps -p 82714 -o lstart,command` = `claude`, gestart **do 17 sep. 08:19:00**; `lsof -a -p 82714 -d cwd` = de repo-root; ouder = een zsh van 16-09 20:22:23. Dus: een interactieve Claude Code-sessie in de repo (deze sessie, vóór `/clear`), gestart terwijl de inbox-run `native-ota-nameting` nog liep (08:19:00 < 08:19:41) — niet via `rlz cc` (die had geweigerd).
- `opdrachten/log/`: laatste logs `2026-09-17-doorbelasting-aansluiting-nameting.log` (08:07) en `2026-09-17-native-ota-nameting.log` (08:19); niets erna.
- Conclusie: regel (f) van 15-09 ("handmatige CC actief = wachten") werkte precies zoals ontworpen; het gat was dat het wachten onzichtbaar was — geen duur, geen aantal klare opdrachten, geen melding, geen uitweg behalve de sessie sluiten.

## Fix (`scripts/cc_inbox.sh`, `scripts/zsh/rlz.zsh`) — rij (h)
- (h1) wachtregel mét "sinds HH:MM:SS (N min), M opdracht(en) klaar in inbox/".
- (h2) ná `CC_INBOX_WACHT_MELDING_S` (default 1800 s) één macOS-melding "CC-inbox wacht al N min op handmatige CC (pid …) — M opdracht(en) klaar; sluit die sessie af of `rlz inbox vrijgeven`", herhaald op z'n vroegst ná `CC_INBOX_WACHT_HERHAAL_S` (3600 s); stand in `opdrachten/log/.wacht-<pid>`, opgeruimd zodra er niet meer gewacht wordt.
- (h3) **bewuste vrijgave** `rlz inbox vrijgeven [pid]` → `opdrachten/.vrijgave` (pid, tijd): die pid houdt de inbox niet meer tegen, logregel "vrijgegeven door Peter … twee schrijvers in één werkboom, risico bewust aanvaard"; vervalt zodra de pid niet meer leeft; `rlz inbox status` toont 'm. De 16-09-guard blijft de default — parallel is een mensenkeuze.
- Guards: `test_cc_inbox_herstel.py` (+3: wachtregel + melding + herhaaldrempel; vrijgave; documentatie) en `test_cc_inbox_parallel.py` (+1: `rlz inbox vrijgeven`/status/dode pid) — 36 groen. Kop van het script beschrijft rij (h) mét de logregel van 17-09.

## Wat Peter nu doet
Niets extra: zodra deze sessie sluit, start de inbox de drie vervolg-opdrachten (`leesreplica-nameting`, `herstellink-nameting`, `vgg-schrijf-c-na-deploy`) vanzelf; wil hij dat de inbox naast een open sessie doorgaat: `rlz inbox vrijgeven`.

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/werkloop-productie.md` (55 regels)
