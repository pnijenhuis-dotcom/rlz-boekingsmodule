uitgevoerd 2026-10-02, rapport: docs/rapporten/2026-10-02-run-b.md

# Opdracht 02-10 — Run B: planning + veld-app (punten 24, 25, 20, 26 van de lijst 02-10)

Ná run A. Regel Peter 30-09: "alles wat werkt moet af en af blijven; hou het simpel" — commit per punt, GEEN bijvangst. Bron:
`docs/feedback/2026-09-28-planning-steigerbouw-feedback-peter.md` (sectie 02-10) en `docs/gesprekken/2026-10-02.md`.
Planning v4 (28-09) is de norm: project × dag-matrix, ploeg-paneel als dé werkwijze, bulkroute voor élke kopie.

LEESPLICHT: docs/regels/uren-planning-veldwerkers.md, docs/regels/kantoor-frontend.md, docs/regels/accordering-native-app.md,
docs/regels/werkloop-productie.md; BESLISSINGEN "PLANNING V4 …", "VELD-APP UITVOERDER — FEEDBACK 18-09" (regel "geen planningstab"
wordt hieronder HERZIEN voor de rol uitvoerder), "VELD-APP — PROJECT EERST".

## Planning (kantoor)
24. Transport-icoon op de projectkaart in de tab Personeel: staat er voor dat project op die dag een transport gepland (Transport-tab,
    status ≠ geannuleerd), dan draagt de kaart een vrachtwagen-icoon mét tooltip "transport gepland: ‹tijd/soort›"; klik = Transport-
    tab op die dag. Peter: "zodat we weten dat daar een planning geleverd staat". Alleen lezen uit de bestaande transportplanning.
25. Beter onderscheid tussen de werk-vakjes ("door de bomen het bos niet meer"): per projectrij een stabiele, deterministische
    accentkleur (hash van projectnummer → palet van ≥ 8 contrastveilige tinten, beide modi; contrast-test), projectnummer vetter dan
    opdrachtgever, duidelijker scheiding tussen rijen, lege plancel visueel rustiger dan een geplande kaart. Geen nieuwe instelling;
    designpass-v2-tokens; contrast is een test.
20. Dagplanning kopiëren met toetsenbord: kaart/cel selecteren → ctrl/cmd-C, andere dagcel → ctrl/cmd-V = dezelfde bulkroute als
    "Kopiëren naar ‹weekdag› volgende week" (bron `kopie_dag`): project + ploeg naar die dag, afwezig overgeslagen mét melding,
    conflict oranje, bestaand samengevoegd, ongedaan. Ook als contextmenu-item "Kopiëren naar…" (één dag kiezen) voor wie geen
    toetsenbord gebruikt. Nooit buiten de eigen administratie-scope.

## Veld-app (rol uitvoerder)
26. Tab "Mijn uren" wordt voor de rol UITVOERDER vervangen door tab "Planning": lijst van álle geplande projecten van die dag binnen
    de scope (volgt de planning live: project, opdrachtgever, plaats, ploeg, transport-icoon als bij 24), swipe links = dag terug,
    swipe rechts = dag vooruit, datumkop mét "vandaag"-knop; tik op een project = bestaande projectkaart (+ Uren / Meerwerk melden).
    Uren schrijven blijft bereikbaar vanaf de projectkaart (project-eerst, 18-09). ZZP'er/detacheerder: ongewijzigd. Dit herziet
    "geen planningstab" (18-09) uitsluitend voor de uitvoerder — vastleggen in BESLISSINGEN + regels. Web-laag → via OTA, geen
    native release nodig; ≥ 48 px raakvlakken; offline = laatst geladen dag mét chip.

## Niet doen
Geen wijziging aan keuring, weekstaten, conflictenpaneel, transport-statusflow; geen native schil-wijziging (23 = apart).

## Af
Per punt test + vitest-component-tests (matrix, kaart, swipe-navigatie), contrast-test groen, volledige suites groen, WAT_IS_NIEUW,
BESLISSINGEN-sectie "RUN B 02-10 — PLANNING: TRANSPORT-ICOON, ONDERSCHEID, DAG KOPIËREN; VELD-APP: PLANNINGSTAB UITVOERDER (Peter
02-10)", regels-alinea in uren-planning-veldwerkers.md (incl. herziening 18-09), CLAUDE.md één verwijsregel, rapport
docs/rapporten/2026-10-02-run-b.md + INDEX + "Gelezen regels" + "werkt in productie: niet gemeten" (klikpunt Peter: week 41 plannen,
uitvoerder-app ná OTA). Committen; de Stop-hook pusht.
