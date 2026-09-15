# Mockup planning met ploegen — verfijnd en gecommit (Cowork 15-09; ter beoordeling Peter/Haci)

**In gewone taal:** Cowork schreef 15-09 een eerste mockup voor "ploegen" in de planning: rijen blijven projecten, rechts komt een
tab Ploegen waarmee je een hele ploeg in één keer voor de hele week op een project zet. Die mockup is nu in de huisstijl van de
kantoor-console gezet (designpass v2, zelfde raster als de planningsagenda), klikbaar gemaakt (ploeg slepen, blokje weghalen,
"Kopieer week") en gecommit als `mockup/planning-ploegen.html`. Het is een voorstel: geen bouwnorm tot Peter/Haci akkoord geven.

**Werkt in productie:** niet van toepassing (mockup, geen productiecode).

## Wat er is gedaan

- `mockup/planning-ploegen.html` op de tokens van `kantoor-designpass-v2.html` (neutrale fundering, licht + donker via ◐, teal
  uitsluitend voor acties, groen uitsluitend voor status, paars voor het ploeg-label zoals werkopdrachten in het echte grid) en het
  raster/de klassen van `planning-steigerbouw.html` (`.planner`-tabel met projectrijen, `.kaart`, `.btn`/`.btn.secundair`/`.linkbtn`,
  zijbalk-panelen, controle-meldingen). Inhoud en de keuzes K1–K3 zijn ongewijzigd; ontwerpnotitie 7 (designpass) toegevoegd.
- Klikbaar (JS-demo, geen backend): ploeg A/B vanuit de zijbalk op een projectregel slepen = alle leden ma–vr, met botsingsdetectie
  (persoon al elders gepland → niet gepland, melding, module kiest niet); ✕ haalt één persoon voor één dag weg (ploeg blijft intact);
  "⧉ kopieer vorige week" per project en "Kopieer week 36 → 37" voor alles; "neem week 36 over" voor het lidmaatschap; zijbalk-tabs.
- Urenstatus-stippen per blokje (grijs/blauw/groen/oranje, tooltip) en weektotaal-chip per project met link "weekstaten →" — dezelfde
  weergave als de opdracht "planning-urenstatus" (2026-09-15) bouwt.
- Headless-Chrome-render op 1440 gecontroleerd (geen overloop; mockup, niet in de overflow-sweep).

## De drie keuzes voor Peter/Haci (letterlijk uit de mockup; ja/nee volstaat)

- **K1 — Ploeg = snelkoppeling, geen harde structuur.** Onder water blijft alles per persoon per dag (de veld-app verandert niet).
  Een wisselaar op donderdag verplaats je gewoon; de ploeg "breekt" niet. Alternatief (afgeraden): ploeg als vaste eenheid die je
  alleen als geheel kunt plannen.
- **K2 — Lidmaatschap per week** mét één klik "neem vorige week over". Alternatief: vaste ploegen die je handmatig wijzigt (sneller als
  de ploegen zelden wisselen; kies dit als dat bij Universal zo is).
- **K3 — "Kopieer vorige week"** per project én voor de hele week; bij een conflict (persoon al ergens anders gepland) toont de module
  de botsing en kiest niet zelf.

## Status

Mockup ter beoordeling — geen bouwnorm tot akkoord. Bij akkoord: BESLISSINGEN-rij "PLANNING — PLOEGEN" + bouw op het bestaande grid
(`app/uren/planning.py`, `frontend/src/planning/PlanningScreen.tsx`), lidmaatschap per week als eigen tabel (migratie), veld-app ongewijzigd (K1).
