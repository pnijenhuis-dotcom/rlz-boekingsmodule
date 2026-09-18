uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-veldapp-project-eerst.md

Domeinen: uren-planning-veldwerkers, accordering-native-app

# OPDRACHT 18-09 (vervolg op veldapp-uitvoerder-feedback) — PROJECT EERST: kaart per project mét "+ Uren" en "Meerwerk melden"

**Peter 18-09:** "Niet beter om eerst het project te selecteren en dan de uren-/meerwerkknop? Anders druk je op een knop en moet je
eerst gaan zoeken." Akkoord Cowork. Bouwnorm = `mockup/uren-uitvoerder-v2.html` (scherm ① herzien, notitie "Project eerst").

- De weekweergave van de uitvoerder = lijst PROJECTKAARTEN: geplande projecten van die week (chip "gepland") + projecten waar deze week
  al uren/meerwerk op staan (chip "niet gepland" als ze niet gepland zijn). Per kaart: dagtotalen van deze week, laatste omschrijving,
  doorfactureren-chip, en twee knoppen: **"+ Uren"** en **"Meerwerk melden"** — beide starten met het project al ingevuld (geen
  projectkeuze meer in het formulier; wel te wijzigen via een klein "ander project"-linkje).
- Onderaan **"+ Ander project toevoegen aan mijn week"** → de projectkeuze (alle actieve projecten in scope, gepland bovenaan, zoeken)
  → voegt een kaart toe (zonder uren) zodat de knoppen daar beschikbaar zijn. Kaart zonder regels verdwijnt bij weekwissel.
- Meerwerk-tab in de onderbalk blijft als overzicht van gemelde meerwerken; bouw hergebruikt de bestaande meerwerk-flow met vooringevuld
  project. Werkbonnen ongewijzigd.
- Hangt af van de lopende opdracht (m² optioneel, doorfactureren, planning weg) — uitvoeren erná, dezelfde componenten. Set-based
  (één query voor de kaarten), tests op de kaartsamenstelling (gepland ∪ mét-regels), WAT_IS_NIEUW één regel, docs/regels bijwerken,
  rapport + INDEX + Gelezen regels, nameting ná deploy op het testaccount.
