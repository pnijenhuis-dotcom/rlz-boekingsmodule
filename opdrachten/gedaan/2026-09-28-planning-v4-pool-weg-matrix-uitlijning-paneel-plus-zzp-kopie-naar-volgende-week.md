> uitgevoerd 2026-09-28, rapport: docs/rapporten/2026-09-28-planning-v4.md (vijf blokken, handmatige CC-sessie; werkt in productie: niet gemeten — vervolg 2026-09-29-nameting-planning-v4-na-deploy.md)

# Planning v4 (steigerbouw) — pool weg, project×dag-uitlijning, ploeg-paneel als dé werkwijze, "+ ZZP'er" in het paneel, kopie naar volgende week

Bron: feedback Peter 28-09 (letterlijk + waarnemingen schermopname) in `docs/feedback/2026-09-28-planning-steigerbouw-feedback-peter.md`.
Besluit Peter 28-09: "Ik hoef hier geen mockup van, maak dit maar gewoon zoals besproken" (UX-review gedaan in het gesprek; mockup
`planning-steigerbouw.html` wordt ná de bouw bijgewerkt naar de gebouwde vorm — ontwerpnotities v4 erin). Dit herziet drie v3-keuzes
(18-09): de ZZP-pool + slepen van personen, de vrije kaartvolgorde per dag, en de reserveringskaart mét infopaneel.
Handmatige CC-sessie, Peter start hem zelf. Frontend-zwaar; backend alleen voor de kopie-route en quick-add.

LEESPLICHT (volledig): CLAUDE.md, docs/regels/uren-planning-veldwerkers.md (Planning v3 DAG-EERST 18-09, conflictenpaneel 21-09,
veldwerkerbeheer, achteraf-audit), docs/regels/kantoor-frontend.md, docs/regels/auth-toegang.md (recht veldwerkerbeheer), werkloop-
productie.md; docs/gesprekken/2026-09-28.md; mockup `planning-steigerbouw.html` + `planning-werkopdracht-transport.html`.

## Blok 1 — ZZP-pool rechts weg; ploeg-paneel is dé werkwijze
- De rechterkolom "ZZP'ers & uitvoerders · sleep naar een kaart" verdwijnt uit de Personeel-tab (ook uit Transport als hij daar staat).
  Slepen van personen naar kaarten vervalt (drop-targets voor personen weg; project → dag slepen én "klik project, dan dag" blijven).
- Kaart klikken = ploeg-paneel (bestaand: zoeken, beschikbaarheid per dag, "al op …", conflict oranje kiesbaar, afwezig niet kiesbaar,
  "Zelfde ploeg als ‹vorige dag›", "Toepassen op hele week", Opslaan (N)). Het paneel scrolt zelf; het hoofdscherm scrolt niet mee.
- BUG (schermopname): een GERESERVEERDE kaart (reservering zonder ploeg) opent nu een doodlopend infopaneel "sleep personen uit de pool".
  Klik op zo'n kaart opent direct het ploeg-paneel; opslaan mét ≥ 1 persoon maakt de reservering tot planning (bestaande bulkroute).
- Weekoverzicht "wie is nog vrij" blijft beschikbaar als compacte regel in de kop van het paneel ("N vrij op ‹dag› · M vrij hele week")
  en in de bestaande "Per project"-tab; geen aparte lijst.

## Blok 2 — "+ ZZP'er" in het ploeg-paneel (quick-add)
- Knop "+ Veldwerker toevoegen…" onderaan de lijst in het paneel (recht `veldwerkerbeheer` of Beheerder; anders niet zichtbaar).
- Quick-add = naam + rol (zzp'er/uitvoerder/detacheerder) + administratie(scope) = huidige; maakt de veldwerker via de bestaande
  route uit Beheer › Veldwerkers, direct aanvinkbaar in het paneel. Dossier (KvK/IBAN/e-mail) blijft verplicht vóór goedkeuring van de
  eerste weekstaat: chip "dossier onvolledig" op de persoon (paneel, lijst, Beheer) + bestaande bevinding; dubbelencheck alleen op harde
  sleutels (21-09: nooit op naam — broers). Audit `veldwerker_aangemaakt` bron `planning_paneel`.

## Blok 3 — project × dag-uitlijning (dezelfde rij over de week)
- De vijf dagkolommen worden een matrix: rijen = projecten met planning of reservering deze week; kolommen = dagen. Rijvolgorde:
  eerste geplande dag, dan aantal geplande dagen (aflopend), dan projectnummer. Een cel zonder planning = lege drop-/klikcel
  "sleep hierheen / + plannen" voor dát project op dié dag (opent het paneel met de ploeg van de dichtstbijzijnde eerdere dag als
  voorstel, niet automatisch opgeslagen).
- Kaartinhoud ongewijzigd (initialen, uren-status, conflict, achteraf, handvat). Handvat "trek over de week" blijft en vult cellen op
  dezelfde rij. Projectbalk bovenaan blijft (project → dag = nieuwe rij of cel).
- Breedte/hoogte: geen horizontale overflow (regel kantoor-frontend 4), sticky dagkop (18-09) blijft; bij > 12 rijen interne scroll mét
  sticky dagkop; "alleen zonder uren"/"alleen ongekeurd" filteren rijen, niet cellen.

## Blok 4 — "Kopiëren naar volgende week" (besluit Peter 28-09: alleen dezelfde weekdag)
- In het ploeg-paneel van een kaart: knop "Kopiëren naar ‹weekdag› volgende week" = dezelfde kaart (project + ploeg + werkopdracht-
  koppeling indien aanwezig, géén uren) op dezelfde weekdag in week+1, via de bestaande bulkroute (bron `kopie_volgende_week`):
  conflict = gepland + oranje, nooit blokkerend; afwezig volgende week = persoon overgeslagen mét melding in de uitkomst; bestaat de
  kaart al = ploeg samengevoegd, niets dubbel. Daarna kan de planner in week+1 "Toepassen op hele week" gebruiken (bestaand).
  Uitkomst-toast mét link "Naar week ‹n+1›" en "Ongedaan" (zelfde set terug, bestaand patroon).
- Geen "hele projectweek → volgende week"-knop (bewust niet, besluit Peter: week-voor-week plannen).
- Achteraf-regel (verstreken/lopende week) geldt niet voor week+1; audit per persoon × dag zoals de bulkroute.

## Blok 5 — mockup en documentatie ná de bouw
- `mockup/planning-steigerbouw.html` bijwerken naar de gebouwde v4-vorm (pool weg, matrix, paneelknoppen) mét ontwerpnotities v4
  (de vijf feedbackpunten + besluit "alleen dezelfde weekdag"); `docs/regels/uren-planning-veldwerkers.md` regel "Planning v4";
  BESLISSINGEN-rij; WAT_IS_NIEUW klantleesbaar (Haci leest mee).

## Tests / guards
Vitest: paneel opent op reserveringskaart; quick-add zichtbaar alleen mét recht; matrix-rijvolgorde; lege cel opent paneel mét
voorstel-ploeg zonder opslaan; geen persoon-drop-targets meer. Pytest: kopie-route (conflict oranje, afwezig overgeslagen, bestaande
kaart samengevoegd, idempotent, ongedaan = zelfde set), quick-add audit + dossier-onvolledig-chip, dubbelencheck harde sleutels.
Pixel-sweep planning (beide modi), overflow-sweep, contrast-test.

## Niet doen
- Geen wijziging aan de veld-app-planningweergave (leest dezelfde data). Geen automatische ploegtoewijzing. Geen "hele week →
  volgende week". Geen verwijderen van veldwerkers vanuit het paneel.

## Definitie van af
Gouden set groen; deploy; nameting: Peter/Haci plant week 40 via paneel + kopie (klikpunt, uitkomst in het rapport), dispatch-onderdeel
`planning-v4` (kopie-route audit + quick-add + reserveringskaart-klik); rapport `docs/rapporten/2026-09-28-planning-v4.md` + INDEX +
"Gelezen regels" + "werkt in productie: ja/nee/niet gemeten"; gespreksverslag 28-09; opdracht naar gedaan/.
