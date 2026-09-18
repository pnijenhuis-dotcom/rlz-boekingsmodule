# Rapport 18-09 — Veld-app PROJECT EERST: projectkaarten mét "+ Uren" en "Meerwerk melden" (Peter 18-09)

Opdracht: `opdrachten/gedaan/2026-09-18-veldapp-project-eerst-flow.md`. Domeinen: uren-planning-veldwerkers,
accordering-native-app. Geen migratie. Gebouwd + getest 18-09-2026 in de inbox-run; Peter keek niet mee — keuzes onder
"Beslispunten". Bouwnorm: `mockup/uren-uitvoerder-v2.html` scherm ① (kaarten), ② (uren mét project vooringevuld), ③ (project
toevoegen); notitie "Project eerst".

**Werkt in productie: NIET GEMETEN** — de code gaat mét deze run naar main; de Stop-hook pusht, de deploy volgt. Het meetrecept
staat in de inbox-opdracht `2026-09-18-veldapp-uitvoerder-nameting.md` (stap 1 uitgebreid met de kaartenflow: kaart → "+ Uren" →
Opslaan 200 → "Week indienen" 200; "+ Ander project" → kaart erbij).

## Peter's vraag en het antwoord in de flow

> "Niet beter om eerst het project te selecteren en dan de uren-/meerwerkknop? Anders druk je op een knop en moet je eerst gaan
> zoeken."

Vóór 18-09 (blok C, ochtend): week → één lange lijst van álle actieve projecten mét zoekveld → weekstaat → dag. Nu: week →
**projectkaarten** (alleen wat er voor jou toe doet) → op de kaart **"+ Uren"** of **"Meerwerk melden"** mét project én dag al
ingevuld. Zoeken gebeurt alleen nog in de uitzondering ("+ Ander project toevoegen aan mijn week").

## Gebouwd

**Backend (`app/uren/overzichten.py`, `schemas.py`, `router.py`).** `week_projecten_zzp(alles=False)` levert de
KAARTSAMENSTELLING: geplande projecten van de week ∪ projecten mét een staat (uren) ∪ projecten waarop de gebruiker die week
meerwerk meldde (`Meerwerk.gemeld_door` + `datum_uitgevoerd` in de week, alleen actieve projecten). `alles=True` (`GET
/uren/zzp/week-projecten?alles=true`) = álle actieve projecten in de scope — de keuzelijst. Nieuwe kaartvelden op
`WeekProjectKaartDto`: `dag_uren` (ISO-datum → uren), `laatste_omschrijving`, `dagen_niet_doorfactureren`,
`doorfactureren_standaard` (projectdefault blok B), `meerwerk_aantal`. Set-based: per administratie een vast aantal statements
(dagregels van de staten in de week, meerwerk in de week, verrekenbare staffels, projecten alleen bij `alles`);
**bijvangst:** `_planning_stand` deed twee `session.get`'s per item (projectnaam + specs) — nu één query per administratie,
zodat de querytelling-meetlat houdt (2 kaarten = 6 kaarten in statements; `alles` hooguit +1).

**Frontend (`frontend/src/uren/UrenFlow.tsx`, `urenApi.ts`, `accordeur/accordeur.css`).** `WeekProjectenView` = kaartenlijst
mét dagbalk (ma–zo, teller = uren die dag over alle kaarten; vooraf gekozen = vandaag in de week, anders maandag). Per kaart:
titel (tik = weekstaat van dat project: dagen, indienen, correctievoorstellen), chips gepland/niet gepland + status + doorfactureren
(N dagen niet doorfactureren, anders de projectdefault) + meerwerk-teller, meta "wo: 4,0 u · week 12,0 u · afbreken",
knoppen **"+ Uren"** (primair; `plusUren`: weekstaat-lookup → bestaande regel van die dag als prefill + projectdefault →
`DagInvoerView` mét terug naar de week) en **"Meerwerk melden"** (alleen uitvoerder, nooit namens; bestaande
`MeerwerkMeldenView` mét `MeerwerkDoel` = project vooringevuld, terug naar de week). Onderaan **"+ Ander project toevoegen aan
mijn week"** → `ProjectToevoegenView` (alles, doorzoekbaar, al-aanwezige kaarten weg) → kaart in `extraKaarten` (app-state per
week, `weekKaarten` dedupliceert; verdwijnt bij weekwissel). **"Week indienen (N u · M projecten)"** dient alle concept-/
corrigeren-staten mét uren in (`dienWeekIn` per weekstaat; 423 dossier zichtbaar als toast). Tikdoelen ≥ 48 px op dagbalk en
kaartknoppen (CSS `.acc-dagbalk`, `.acc-kaartknoppen`).

**Docs.** `docs/regels/uren-planning-veldwerkers.md` alinea "Veld-app — PROJECT EERST", BESLISSINGEN "VELD-APP — PROJECT EERST
(Peter 18-09)", CLAUDE.md één verwijsregel (regel 5 onder Uren & meerwerk), `WAT_IS_NIEUW.md` (bullet in het 18-09-blok), mockup
v2 kop "GEBOUWD 18-09".

## Beslispunten (gekozen)

1. **Dagkeuze via de dagbalk** boven de kaarten (niet in het formulier): één tik, "+ Uren" landt op die dag.
2. **"Week indienen" op de kaartenlijst** (mockup ① toont 'm) dient per project in; indienen per project blijft via de kaarttitel.
3. **Kaart zonder regels = app-state**, geen server-tabel — weg bij weekwissel/herstart (letterlijk de opdracht).
4. **Dezelfde kaartenflow voor ZZP'er en namens-detacheerder** (één component); meerwerk-knop alleen voor de uitvoerder
   (backend `meld_meerwerk` weigert anderen).
5. **Chip "N dagen niet doorfactureren" verschijnt ook als de regel de projectdefault Niet volgde** — dat is de werkelijke stand
   van de regel; wil Peter alleen expliciete afwijkingen tonen, dan is dat een extra veld (`doorfactureren_expliciet`).

## Tests

| Suite | Uitkomst |
|---|---|
| `backend/tests/uren` (eigen test-DB `boekhouding_test_inbox`, naast de lopende volledige suite) | 260 groen (nieuw `test_project_eerst_18_09.py` 6 tests; aangepast `test_planning_filters.py`, `test_uitvoerder_feedback_18_09.py`) |
| Frontend `vitest run src/uren src/auth src/changelog` | 15 bestanden / 56 tests groen (`UrenFlow.detacheerder.test.tsx` herschreven op de kaartenflow, +1 test kaart mét regels) |
| `tsc -b` | groen |
| Volledige frontend-suite + guards | zie `2026-09-18-inbox-afgewerkt.md` (één keer aan het einde van de inbox-run) |

## Open punten / vervolg

- Nameting ná deploy (inbox-opdracht, uitgebreid): kaart → "+ Uren" → 200; "+ Ander project" → kaart; "Week indienen" → 200.
- Run A van de 12 UX-punten (opdracht 6) bouwt op deze componenten (tikknoppen, chips, samenvatting bij indienen).

## Gelezen regels

- `docs/regels/uren-planning-veldwerkers.md` (300 regels) — volledig, vóór de start (Domeinen-kopregel).
- `docs/regels/accordering-native-app.md` (264 regels) — volledig, vóór de start (Domeinen-kopregel).
