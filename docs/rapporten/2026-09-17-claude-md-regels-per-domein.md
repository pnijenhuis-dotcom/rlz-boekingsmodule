# Rapport 17-09 — CLAUDE.md: volledige regels per domein in `docs/regels/`, verplicht gelezen vóór werk; CLAUDE.md = harde kern + leesplicht

Opdracht: `opdrachten/gedaan/2026-09-17-claude-md-opschonen-onder-limiet.md`. Docs + guards + werkloop; geen functionele code, geen migratie. **Werkt in productie: n.v.t.**

## Uitkomst in cijfers (uit `scripts/eenmalig/claude_md_regels_splitsen_17-09.py`, bewijsstuk in de repo)
| Meting | Vóór | Ná |
|---|---|---|
| CLAUDE.md omvang | **145.479 tekens** (limiet 150k) | **50.514 tekens** (doel ≤ 90k) |
| CLAUDE.md woorden | 16.952 | 5.951 |
| Verhuisde blokken | — | **164** (Domeinbeslissingen 152, Stack & platform 5, Werkwijze 7), **13.416 woorden**, byte-gelijk als substring in het doelbestand: **164/164, 0 niet-verbatim** |
| Nieuwe tekst in CLAUDE.md (18 compacte blokken + leesplicht-intro + 3 pointer-regels) | — | 2.415 woorden |
| Identiteit vóór = ná − nieuw + verhuisd | 16.952 = 5.951 − 2.415 + 13.416 | **klopt** |
| Regelsbestanden | — | 18 (+ INDEX), 285.617 tekens totaal, incl. de kopie van de 07-09-historie uit BESLISSINGEN (47 subkoppen, 137k tekens; de BESLISSINGEN-sectie blijft staan) |

Domeinen: werkvoorraad-controlescherm, kantoor-frontend, administraties-instellingen, auth-toegang, btw, duplicaten-crediteuren, intake-extractie, autoboeken-ai, reconciliatie, verplichtingen-projecten-voorraad, uren-planning-veldwerkers, omzet, bank, doorbelasting-intercompany, accordering-native-app, vgg-odoo-migratie, activa, werkloop-productie.

## Gedaan
1. `docs/regels/<domein>.md` × 18: LEESPLICHT-kop, "Wat het is", "Regels (woordelijk uit CLAUDE.md, stand 17-09)" in CLAUDE.md-volgorde mét bronsectie per blok, "Historie — 07-09" (kopie). `docs/regels/INDEX.md`: domein → bestand → code-paden (élk pakket onder `backend/app/`, élke map onder `frontend/src/`, plus scripts/native/docs).
2. CLAUDE.md: Kernprincipes, Stack (mét pointer-regels voor administraties en auth), RLZ-API, per domein één blok (wat/hoofdregels/LEESPLICHT), Praktijklessen, Koppelvlak, Referenties, harde werkregels (BESLISSINGEN-check, git, productie, bash, pre-commit, tests, schrijfacties) + pointer naar `werkloop-productie.md`, Migraties.
3. Afdwingen: `scripts/cc_inbox.sh` leest de kopregel `Domeinen: a, b` → startprompt "LEESPLICHT … lees EERST volledig: docs/regels/a.md, …" (onbekende namen genegeerd; geen kopregel → "leid af via INDEX.md en noem dat expliciet") en eist de rapportsectie "## Gelezen regels"; guards `tests/unit/test_regels_index.py` (4: élk pakket/élke map ↔ precies één domein; bestanden + LEESPLICHT; élke LEESPLICHT-verwijzing ↔ INDEX; omvang > 120k rood / > 90k waarschuwing) en `tests/unit/test_rapporten_gelezen_regels.py` (rapporten ≥ 18-09 + de acht van deze run); `test_cc_inbox_herstel.py` (+2 prompt-tests). Bestaande guard `test_claude_md_beslissingen_verwijzingen.py` groen (3).
4. BESLISSINGEN "CLAUDE.md — REGELS PER DOMEIN MET LEESPLICHT (Peter 17-09)"; WERKWIJZE v1.18 sectie "Regels per domein met leesplicht" (Platform-repo).
5. De drie vervolg-opdrachten in de inbox dragen de kopregel `Domeinen:`.

## Keuzes (defaults)
- 18 domeinen i.p.v. de ~10 uit de opdracht: de grote clusters (accordering/native app, VGG, werkloop) kregen een eigen bestand; `btw` en `activa` klein maar apart (eigen leesplicht).
- De harde Autorisatie-tekst (RLS-lessen) staat volledig in `auth-toegang.md`; CLAUDE.md houdt de kern in het auth-blok + de pointer-regel.
- De omvang-waarschuwing (> 90k) is een pytest-`warnings.warn`, de rode grens 120k een assert.

## Gelezen regels

De regelsbestanden zijn in deze run uit CLAUDE.md afgesplitst (opdracht 6); vóór de splitsing is de volledige CLAUDE.md-tekst gelezen (sessiestart, 145.479 tekens = de bron van élk regelsbestand). Per domein de bestanden die dit blok raakt:
- `docs/regels/werkloop-productie.md` (55 regels)
- `docs/regels/kantoor-frontend.md` (106 regels)
