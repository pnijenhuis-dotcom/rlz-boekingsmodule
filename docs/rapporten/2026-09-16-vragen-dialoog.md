# Rapport 16-09 — Vragen-dialoog open tot "Afgehandeld" (meerdere berichten achter elkaar, van beide kanten)

**Wortel in twee zinnen:** de beurt-regel zat alleen in de accordeur-app-UI — `GoedkeurenFlow.tsx` toonde het antwoordveld uitsluitend als
`ik_ben_aan_de_beurt` waar was, dus ná Sophia's antwoord (beurt → kantoor) verdween haar veld tot Barbara reageerde. De backend weigerde nooit
een tweede bericht en het kantoor-paneel toonde het veld altijd; de fix is nu in alle drie de lagen consistent (status afgeleid, geen gate).

**Opdracht:** `opdrachten/gedaan/2026-09-16-vragen-dialoog-open-houden.md`. Geen migratie.
**Werkt in productie: niet gemeten** — meetrecept hieronder (accordeur-app-deel = PWA direct; native app volgt de bestaande build-flow).

## Gedaan
1. **Thread open voor beide kanten** (blok 1): accordeur-app toont de antwoordbalk altijd zolang de vraag open is; kantoor-paneel
   ongewijzigd open. Enter = nieuwe regel, Cmd/Ctrl-Enter = versturen (textarea in beide apps); concept lokaal bewaard bij een fout.
2. **Status afgeleid** (blok 2): `laatste_bericht_door/_op` in de DTO's, badge "laatste bericht van ‹naam› · ‹tijd›" (kantoor) en chip
   "Laatste bericht van u · wacht op kantoor" (app); `aan_de_beurt` blijft afgeleid uit de laatste schrijver. Legacy `beantwoord` = historie
   (beslispunt: geen datastap, wél heropenbaar). Werkvoorraad: `vraag_open` telt in lijst + groep-tellers op de afgeleide kant (klant aan zet =
   "Wachten op anderen", kantoor/niemand aan zet = standaardlijst), NULL-veilig.
3. **Meldingen gebundeld** (blok 3): ongemelde inhoud i.p.v. per-beurt-idempotentie; directe aanroep slaat over binnen 10 min in dezelfde beurt,
   de 10-min-job stuurt "N nieuwe berichten"; nooit naar de schrijver zelf.
4. **UI** (blok 4): eigen berichten rechts, "Afgehandeld namens vraagsteller…" voor kantoor (expliciete vlag, audit `vraag_afgehandeld_namens`),
   "Heropenen" ná afhandelen (`POST …/vragen/{id}/heropenen`, kantoor, alleen vanuit een herstelbare herkomst, één open vraag per document).
5. **Boeken blijft geblokkeerd** zolang de vraag open is (harde check ongewijzigd); geheugen-voeding via de boek-leerlus ongewijzigd.

## Tests
- Backend: `test_vragen.py::TestDialoogOpenTotAfgehandeld` 3, `test_vragen_accordeur.py::TestDialoogOpenVoorDeAccordeur` 2 (+ bestaande 5),
  `test_afgehandeld_lijst.py` + `tests/vragen` + `tests/werkvoorraad` groen (55), gouden set `test_lijst_standaard_en_wachten.py`
  aangepast (open vraag zonder accordeur = kantoor, aan accordeur = wachten), rol-endpoint-sweep — zie slotrapport voor de laatste run.
- Frontend: `VraagThread.test.tsx` 3 (nieuw), `GoedkeurenFlow.test.tsx` (veld blijft ná antwoord), `VragenScreen.test.tsx`,
  `OpenVragenKantoorbreed.test.tsx`, `accordeurCss.test.ts` groen (51); `tsc -b` groen.

## Beslispunten (default gekozen, zie `2026-09-16-beslispunten-peter.md` opdracht 10)
Legacy `beantwoord` niet omgezet (geen datastap; heropenbaar) · "namens" = kantoorrol in scope mét expliciete vlag, ook niet-Beheerder ·
heropenen alleen vanuit een herstelbare herkomst · bundelvenster 10 min per beurt, eerste bericht van een nieuwe beurt direct ·
werkvoorraad-groep op de afgeleide kant.

## Meetrecept ná deploy
1. Barbara stelt in kantoor-web een vraag aan Sophia (klant-accordeur); Sophia antwoordt in de app → het antwoordveld blijft staan en Sophia
   plaatst direct een tweede bericht (201); chip "Laatste bericht van u · wacht op kantoor".
2. Kantoor-web: het paneel toont "laatste bericht van Sophia · ‹tijd›", beide berichten van Sophia, Barbara typt twee reacties achter elkaar
   (Cmd/Ctrl-Enter). Sophia krijgt binnen 10 min ÉÉN melding ("2 nieuwe berichten") — audit `vraag_accordeur_gemeld` mét `aantal_berichten`.
3. Een collega (niet Barbara) ziet "Afgehandeld namens vraagsteller…"; afhandelen → audit `vraag_afgehandeld_namens`; daarna "Heropenen" →
   document weer `vraag_open`, audit `vraag_heropend`.
4. Documentenlijst: met de beurt bij Sophia staat het document onder "Wachten op anderen"; ná haar antwoord (beurt bij kantoor) in de
   standaardlijst — tellers volgen.
