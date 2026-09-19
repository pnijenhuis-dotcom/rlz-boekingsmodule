uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-cc-inbox-lock-per-opdracht-en-poort.md

Domeinen: werkloop-productie

# OPDRACHT 19-09 — CC-inbox: lock per opdracht (nooit twee runs op één opdracht), run eindigt nooit vóór zijn suite, push-conflict
# nooit stil (procesles inbox-run 19-09 12:46)

**Feiten (rapport `2026-09-19-inbox-afgewerkt.md` + Stop-hook-melding 12:46):** (1) twee inbox-runs pakten tegelijk
`2026-09-19-ontwerp-vastly-odoo-toetsen-en-pilotmeting.md` en moesten via berichten afstemmen; (2) twee keer eindigde een run vóór zijn
testsuite klaar was, waardoor gebouwd werk ongecommit in de werkboom bleef en door een latere run "door de poort gehaald" moest worden;
(3) de Stop-hook-push faalde met `! [rejected] main -> main (fetch first)` omdat de parallelle run eerder pushte — melding "push
handmatig", geen retry, en de deploy bleef uit tot Peter zelf pull --rebase + push deed.

## Regels (bindend; volledige tekst naar `docs/regels/werkloop-productie.md`)
1. **Lock per opdracht, atomisch.** Oppakken = `mv inbox/X lopend/X` als atomische claim (rename faalt als een ander hem al heeft); een
   run die de rename verliest slaat de opdracht over en logt dat. Geen tweede mechanisme. `rlz inbox status` toont per lopend-bestand
   pid + starttijd; een lopend-bestand zonder levend pid > 30 min = "gestrand" (bestaande rij (i)-regel), nooit stil herstarten.
2. **Eén inbox-runner tegelijk per repo.** De launchd-agent en `rlz cc` delen één repo-lock (`opdrachten/.runner.lock`, flock); een
   tweede starter wacht zichtbaar of stopt met melding — nooit parallel op dezelfde werkboom. Parallelle agenten BINNEN één run mogen,
   parallelle runs niet.
3. **Een run eindigt pas ná zijn poort.** De suite (pytest + vitest + tsc + gouden set) is onderdeel van de run; time-out/tegoed-uitval
   = werk stashen in een genoemde WIP-commit op een branch `wip/<opdracht>` (nooit in main, nooit ongecommit in de werkboom) mét
   rapportregel "poort niet gehaald — WIP op branch …"; de volgende run begint met die branch. Ongecommit werk in de werkboom bij de
   start van een run = melding + stop (niet stil overnemen).
4. **Push-conflict = rebase + retry, nooit alleen "push handmatig".** De Stop-hook doet bij `rejected` één `git pull --rebase origin main`
   (alleen fast-forward-achtige rebase zonder conflicten) + één retry-push; blijft het falen (echt conflict) → melding mét de exacte
   commando's én een inbox-rij "push geblokkeerd" zodat `rlz inbox status` het toont. Force blijft verboden.
5. **Guards:** tests op de claim (twee processen, één wint), op de runner-lock, op de WIP-branch-afhandeling en op de hook-retry
   (gemockte git). Rapport + INDEX + Gelezen regels; BESLISSINGEN "CC-INBOX — LOCK PER OPDRACHT, POORT VÓÓR EINDE, PUSH-RETRY (19-09)";
   CLAUDE.md één verwijsregel onder werkloop. Nameting: twee `rlz cc`-starts tegelijk → één loopt, één wacht zichtbaar.
