# Planning: urenstatus in het grid + planning met terugwerkende kracht in de app (Peter/Haci 15-09, Universal Steigerbouw)

**In gewone taal:** Het kantoor ziet nu in het planningsgrid per persoon en dag of de uren zijn ingevuld, gekeurd of afgekeurd, met
een weektotaal per project en een filter op "zonder uren"/"ongekeurd". Plant het kantoor iets in een week die al voorbij is of loopt,
dan krijgt de veldwerker één gebundelde melding "planning week N aangepast" die de app op die week opent, en staat er "achteraf" bij
het kaartje. Geen blokkade, wel audit.

**Werkt in productie:** niet gemeten (deploy volgt op de Stop-hook; meetrecept hieronder). Migratie 0145: dev-upgrade gedaan,
`alembic check` schoon, dump ververst (head 0145), live-check op een lokale uvicorn tegen de dev-database ná de upgrade: `GET /openapi.json` 200 mét `WeekUrenDto`, `GET /uren/kantoor/planning` zonder token 401 (route staat, DTO uitgebreid).

## Gebouwd

| Punt | Wat | Waar |
|---|---|---|
| A1 | Urenstatus per kaartje uit de weekstaat (één statement per week): grijs geen · blauw ingevuld "8 u · 42 m²" · groen gekeurd (door wie/wanneer) · oranje afgekeurd/vraag (afkeurder + reden); tooltip; klik opent de weekstaat (`/meerwerk?administratie=…&weekstaat=<id>`) | `app/uren/planning.py::_urenstanden_voor_week`, `PlanningKaartData/Dto`, `frontend/src/planning/PlanningScreen.tsx` |
| A2 | Weektotaal-chip per projectrij "24 u ingevuld · 16 u gekeurd · 2 open · N zonder uren" → link naar de weekstaten van dat project | `WeekUrenData/Dto`, `planningApi.ts::weekUrenTekst` |
| A3 | Filterchips bovenaan (URL-param `uren=zonder|ongekeurd`), client-side op de ene weekrequest | `PlanningScreen.tsx`, `parseUrenFilter`/`kaartPastInFilter` |
| A4 | Querytelling constant in het aantal projecten (N=3 = N=12 statements) | `tests/uren/test_planning_urenstatus.py` |
| B1 | Vastgesteld: de veld-app opende op de huidige week met vrije ‹ ›-navigatie; nieuw: chips "week N−2 · N−1 · deze week" en deep-link `/accordeur?planning=JJJJ-Wnn`. Melding: één open rij per (administratie, veldwerker, week) bij een wijziging in een verstreken/lopende week (`planning_wijziging_melding`, migratie 0145), gebundeld verstuurd door de bestaande 10-min-job (push-anders-mail, stille uren), audit `planning_wijziging_gemeld` | `app/uren/planning.py::_registreer_wijziging_in_week`, `app/uren/planning_meldingen.py`, `app/cli.py::_nieuwe_facturen_melden`, `frontend/src/uren/UrenFlow.tsx` |
| B2 | Audit van elke planningmutatie draagt `achteraf`, `week_status`, `veldwerker_gemeld`; chip "achteraf" op het kaartje; geen blokkade. Er is geen project-tijdlijn in de module — de audit is het spoor (beslispunt) | `planning.py`, `PlanningScreen.tsx` |
| B3 | Test: mutatie in week N−1 → audit-vlag, één gebundelde rij (3 mutaties), job → één push met deep-link, rij gesloten, herhaling stil; toekomstige week = niets | `tests/uren/test_planning_urenstatus.py` (8) |

## Tests

Backend `tests/uren/test_planning_urenstatus.py` (8) + test_planning + test_planning_signaal: 47 groen. Frontend `src/planning`
(PlanningScreen +2, `urenStatus.test.ts` 3) + `src/uren/planningWeekUitZoekdeel.test.ts`: groen; `tsc -b` groen (pre-commit).
Overflow-sweep: het planningsgrid zit niet in de sweep-harnassen (bestaande situatie); de nieuwe elementen zijn inline in bestaande
cellen (stip + tekst ≤ 10 px, chip in de rijkop) en de tabel is `table-layout: fixed`.

## Meetrecept ná deploy

1. Kantoor: `/planning?administratie=<Universal>&week=2026-W37` → blokje Hakim Lali vr 11-9 toont een statusstip mét tekst; tooltip
   noemt de weekstaat-stand; rijkop toont het weektotaal; `&uren=zonder` filtert.
2. App Fatih: Planning → chips "week 36 · week 37 · deze week"; week 36 opent met één tik.
3. Kantoor wijzigt een kaartje in week 36 → binnen 10 min (buiten 20:00–08:00) één push "Planning week 36 aangepast" bij Fatih,
   deep-link opent week 36; job-uitvoer `rlz-nieuwe-facturen`: `planning-meldingen: … berichten=1 push=1`.

## Beslispunten (default gekozen)

- Project-tijdlijnregel bij achteraf plannen: bestaat niet als concept in de module; audit + chip zijn het spoor. Default: zo laten.
- Melding ook bij een wijziging in de LOPENDE week (niet alleen verstreken): ja, gebundeld per week — de veldwerker moet weten dat
  vandaag/morgen anders is. Default: aan.
