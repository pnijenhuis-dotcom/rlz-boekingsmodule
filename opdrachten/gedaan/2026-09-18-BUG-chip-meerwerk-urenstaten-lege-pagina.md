uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-beoordelen-urenstaten-meerwerk.md

Domeinen: uren-planning-veldwerkers, werkvoorraad-controlescherm, kantoor-frontend

# BUG 18-09 — Chip "14 meerwerk/urenstaten te beoordelen" landt op een lege Meerwerk-pagina (0/0/0/0)

**Melding Peter 18-09 (screenshots):** klantpagina Universal Steigerbouw toont chip "⚡ 14 meerwerk/urenstaten te beoordelen"; klik →
`/…/meerwerk` met alle vier de tabs op 0 ("Geen meerwerk in deze status"). De 14 zijn dus geen meerwerk maar (vermoedelijk) ingediende
weekstaten — bewijs dat uit de data (lees-only: tel ingediende weekstaten + open meerwerkmeldingen voor deze administratie mét id's).

## Fix
1. **Eén landingsplek voor alles wat kantoor moet beoordelen in de steigerbouw-tak:** de Meerwerk-pagina wordt "Beoordelen" met twee
   tabs: **Urenstaten (N)** (ingediende weekstaten: veldwerker, project, week, uren, m², ingediend op; acties keuren/afkeuren mét reden
   + namens-keuring zoals nu in de kantoor-weekstaat) en **Meerwerk (M)** (bestaande vier statussen). Chip-tekst = "N urenstaten · M
   meerwerk te beoordelen" en linkt naar de juiste tab; teller en pagina komen uit dezelfde query (guard-test: chip-aantal == som van
   de tab-aantallen, nooit meer uit de pas).
2. Lege stand = actie (KP7): "Geen urenstaten te beoordelen — laatste keuring <datum>" i.p.v. een kale regel.
3. Zelfde kolomminima-/⋯-menu-patroon als Gebruikers & toegang; overflow-sweep; registry-anker.

## Samenhang met Irfan (uitvoerder, 18-09)
De keurlijst van een uitvoerder (`overzichten.te_keuren`) hangt aan `UrenProjectToewijzing` (planning/eigen weekstaat). Peter's
besluit 18-09: uitvoerder werkt los van planning. **Bouw daarom óók:** uitvoerder ziet standaard ÁLLE ingediende weekstaten van de
administratie(s) in zijn scope (behalve de eigen) — **besluit Peter 18-09, letterlijk: "uitvoerder moet gewoon alle ingediende
urenstaten controleren, los van welk project hij gepland staat."** GEEN beperking per project bouwen. `UrenProjectToewijzing` stuurt
alleen nog "gepland bovenaan" in de projectlijst, nooit de keurbevoegdheid. Guard-test: nieuw uitvoerder-account zonder koppelingen
ziet direct álle ingediende weekstaten van de administratie.

## Afronding
Gouden set/veld-app-tests; WAT_IS_NIEUW ("Urenstaten en meerwerk beoordeel je op één plek"; "Een uitvoerder ziet alle ingediende
urenstaten"); docs/regels; rapport + INDEX + Gelezen regels; nameting ná deploy op Universal Steigerbouw: chip-aantal = tab-aantallen,
Irfan ziet de N weekstaten in zijn app ("werkt in productie: ja/nee").
