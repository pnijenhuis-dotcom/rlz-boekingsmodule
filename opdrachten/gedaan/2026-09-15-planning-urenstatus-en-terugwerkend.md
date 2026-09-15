uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-planning-urenstatus.md

OPDRACHT — PLANNING: URENSTATUS IN HET GRID + PLANNING MET TERUGWERKENDE KRACHT IN DE APP (feedback Peter/Haci 15-09, Universal Steigerbouw)

Lees BESLISSINGEN "PLANNING-AGENDA STEIGERBOUW", "PLANNING-UITBREIDING 31-08", "UREN & MEERWERK — BOUW", "PLANNING-SIGNAAL 'GEPLANDE WEEK ZONDER WEEKSTAAT'" en mockup/planning-steigerbouw.html. UX-review: dit is een verrijking van het bestaande grid (geen nieuwe IA); geen mockup nodig, wél de UX-patronen (chips één regel, kolomminima, geen kale button).

A. Urenstatus zichtbaar in het kantoor-planningsgrid (kantoor kan nu niet zien wat Fatih invulde)
1. Per persoon×dag-blokje een statusstip + korte tekst uit de bestaande weekstaat-/keuringsdata (één leesbron, geen nieuwe berekening): grijs "geen uren", blauw "8 u · 42 m²" (ingevuld, tijdstip in tooltip), groen "gekeurd" (door wie/wanneer in tooltip), oranje "afgekeurd/vraag". Kleuren volgens de semantiek-regel (groen = status, teal = actie).
2. Per projectregel in de weekkolom een weektotaal-chip "24 u ingevuld · 16 u gekeurd · 2 open" die naar de bestaande weekstaat-/keuringspagina linkt; klik op een blokje opent de weekstaat van die persoon/week (deeplink, bestaande route).
3. Filter "alleen zonder uren" / "alleen ongekeurd" bovenaan (chips, URL-param), kantoorbreed patroon.
4. Query set-based per week (één statement voor het hele grid), meetlat-test op querytelling zoals `test_tellers_querytelling.py`.

B. Planning met terugwerkende kracht in de veld-app
1. Vaststellen: welk weekvenster toont de app nu (alleen huidige/komende week?). De app toont voortaan ook de twee voorgaande weken (lees-only voor uren die al gekeurd zijn), en een planningwijziging in een verstreken/lopende week geeft de betrokken veldwerker een push/bundelmelding "planning week N aangepast" (bestaand notificatiepatroon, geen nieuw kanaal).
2. Kantoor: wijziging in een verstreken week krijgt audit + tijdlijnregel op het project; geen blokkade (besluit minimale mens), wél chip "achteraf gepland".
3. Test: planning-mutatie in week N−1 → zichtbaar in de app-weekweergave N−1 en melding aangemaakt.

C. Af: gouden set/keten_sweep waar geraakt, overflow-sweep, tsc; BESLISSINGEN "PLANNING — URENSTATUS IN HET GRID + TERUGWERKENDE KRACHT (Peter/Haci 15-09)" + CLAUDE.md-verwijsregel + WAT_IS_NIEUW (twee regels, klanttaal); rapport docs/rapporten/2026-09-15-planning-urenstatus.md + INDEX; meetrecept ná deploy: Universal week 37, blokje Hakim Lali vr 11-9 toont status; app Fatih toont week 36. Dit bestand naar gedaan/.
