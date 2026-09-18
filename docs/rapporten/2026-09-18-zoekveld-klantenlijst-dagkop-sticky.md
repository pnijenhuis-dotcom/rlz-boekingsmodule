# Rapport 18-09 — Twee kleine fixes: zoekveld klantenlijst + dagkop planning blijft staan bij scrollen

Opdracht: `opdrachten/gedaan/2026-09-18-klein-zoekveld-klantenlijst-en-planning-dagkop-sticky.md` (Peter 18-09, screenshots).
Domeinen: werkvoorraad-controlescherm, uren-planning-veldwerkers, kantoor-frontend. Geen migratie, geen backend.

**Werkt in productie: NIET GEMETEN** — de deploy volgt via de Stop-hook ná deze run (push is voor de agent geblokkeerd). Meetrecept
ná deploy: (A) Werkvoorraad › Overzicht per klant → typ "Univ" → teller "3 van N", drie Universal-rijen; `/` zet de cursor in het
veld; herlaad de pagina → de term staat er nog (sessie). (B) Planning › Personeel, Universal week 39 → 800 px naar beneden scrollen →
de kopregel MA … VR + "Project" staat nog bovenaan het grid (screenshot), idem de Transport-tab.

## A — Zoekveld op de klantenlijst

- `frontend/src/werkvoorraad/klantZoek.ts`: `filterKlanten`/`klantMatcht` op administratienaam én groepsnaam, diakriet-loos en
  hoofdletter-ongevoelig via dezelfde `normaliseerTekst` als het bankzoekveld; elke spatie-gescheiden term moet treffen; leeg = alles.
- `Klantenlijst.tsx`: zoekveld links van "Groep", teller "N van M" (M = klanten mét openstaand werk), `/` focust (binding
  `SNELTOETSEN_LIJST`, nooit vanuit een invoerveld/dialoog), lege uitkomst = melding "Geen administratie past bij …" + linkbtn
  "wis het zoekveld".
- `WerkvoorraadScreen.tsx`: `?zoek=` in de URL (deeplink wint), laatste term per browsersessie in sessionStorage
  (`werkvoorraad-klantzoek`); het Groep-filter blijft server-side en werkt eronder samen. Geen server-call: de lijst staat al in de
  tellers-cache-respons.

## B — Planning: dagkoppen blijven staan

- Oorzaak: het grid stond in een kale `.tabel-scroll` (door `overflow-x: auto` een scrollcontainer zonder hoogte) — de pagina
  scrolde, de kopregel scrolde mee.
- Fix: Personeel-grid (`PlanningScreen.tsx`) én Transport-dagagenda (`TransportTab.tsx`) staan in
  `.tabel-scroll.sticky-koppen.plan-scroll` — intern scrollen (max-hoogte `max(420px, 100vh − 250px)`, zelfde patroon als
  klantenlijst/administraties), `thead th` sticky mét dekkende achtergrond `--panel` (vandaag-tint blijft) + onderrand/schaduw
  (`styles/components.css`). Rij-koppen in de `tbody` zijn door hun rij begrensd en bewegen niet.
- Beslispunt: intern scrollen i.p.v. paginabrede sticky (zie BESLISSINGEN); de rechter ZZP-kolom (sticky `top: 16`) sluit erop aan.
  Het patroon wordt hergebruikt door de v3-dagkop (planning dag-eerst, opdracht 4 van deze run).

## Tests

| Toets | Uitkomst |
|---|---|
| `vitest run src/werkvoorraad/klantZoek.test.tsx` (nieuw) | 6 groen: filter (diakrieten, AND, groepsnaam, leeg), sessie-onthouden, teller + live filter, lege uitkomst + wis, `/`-focus |
| `vitest run src/planning/stickyDagkop.test.ts` (nieuw) | 2 groen: beide grids in de sticky wrapper, CSS-regels aanwezig |
| `PlanningScreen.test.tsx`, `TransportTab.test.tsx`, `WerkvoorraadScreen.test.tsx`, `styles/contrast.test.ts` | 104 groen (bestaand gedrag ongewijzigd) |
| `tsc -b` | groen |
| `HARNASSEN_ALLEEN=harness-werkvoorraad.html scripts/overflow_sweep.sh` | 40/40 ✅ (5 varianten × licht/donker × 4 breedtes), geen pagina-overflow |
| Kliktest scroll 800 px | niet uitvoerbaar in de run (geen Playwright in de repo) — klikpunt Peter, zie meetrecept |

## Klikpunten Peter

- Werkvoorraad: zoekveld "Univ" → 3 rijen, `/` focust, herladen houdt de term.
- Planning › Personeel én Transport: scrollen → dagkop blijft staan (screenshot graag terug als het niet zo is).

## Gelezen regels

- `docs/regels/werkvoorraad-controlescherm.md` (185 regels) — volledig, vóór de start.
- `docs/regels/uren-planning-veldwerkers.md` (353 regels) — volledig, vóór de start.
- `docs/regels/kantoor-frontend.md` (113 regels) — volledig, vóór de start.
- `docs/regels/werkloop-productie.md` (55 regels) — volledig, vóór de start (run-brede werkloop).
