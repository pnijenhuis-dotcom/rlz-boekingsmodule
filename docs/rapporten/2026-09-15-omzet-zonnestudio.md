# Omzetbron zonnestudio dagstaat + kascheck (Peter 15-09)

**In gewone taal.** De dagelijkse verkooprapporten van de zonnestudio (het POS-bestand "Daily Sales" en de kascheck) worden nu
zonder AI en zonder overtypen gelezen: de module haalt per dag de categorieën, de btw, de betaalwijzen en de kastelling uit de
spreadsheets, voegt dagstaat en kascheck van dezelfde dag samen tot één omzetdocument bij de juiste studio en controleert of alles
cent-exact sluit. Wat niet klopt staat rood of oranje op het document, zodat niemand een dag hoeft na te rekenen. Alle zes de
voorbeelddagen (8 t/m 13 september) sluiten; het enige dat blokkeert is een vraag aan de klant over de puntenwaarde.

**Wat Peter aan de klant moet vragen (STAP 0):**
1. Wat is één punt waard in euro's, en zijn de "Points Redeemed" (921 op 8-9) punten of euro's? Tot het antwoord blokkeert elke dag met ingewisselde punten.
2. Hoe heet de tweede studio precies in het veld "Store Used:" van het POS-rapport? Die naam gaat in de bron-instellingen van die administratie.
3. Welke rekeningen per studio: kas, kruispost pin-ontvangsten, vooruitontvangen tegoeden (verkochte punten), kasverschillen.

## Gedaan

- Rasterlaag `.xls`/`.xlsx` → `Grid` (xlrd/openpyxl; dependencies in `pyproject.toml`), herkenning op inhoud.
- Parsers dagstaat en kascheck mét harde controles; veldvoorstel volgens het motor-contract (kassabedragen incl. btw, Points als balansregel).
- Bundeling dagstaat + kascheck per dag (wederhelft `samengevoegd`, nieuwe statusovergang `extractie_bezig → samengevoegd`); alleen één helft = zichtbaar "wacht op".
- Intake-routering op "Store Used" via Beheerder-instelling `bron_instellingen.stores` (migratie 0146); onbekende store → verzamelbak mét reden.
- Bron-controles als check-rijen in de harde checks; blok "Bron" in het omzet-controlescherm (betaalwijzen, kascheck, controles) + download i.p.v. PDF-viewer.
- Gouden set: fixtures `ab_omzet_zonnestudio` + ketentest; `tests/omzet/test_bronnen.py` (alle zes echte dagen cent-exact als de voorbeelden lokaal staan).
- Afsluitroutine 0146: dev-upgrade, `alembic check` schoon, dump ververst, live lokale uvicorn openapi 200 + route 401 zonder token.
- BESLISSINGEN "OMZETBRON ZONNESTUDIO DAGSTAAT (Peter 15-09)", CLAUDE.md-verwijsregel, WAT_IS_NIEUW.

## Niet gebouwd (bewust, staat in BESLISSINGEN)

- Tegenzijde per betaalwijze als eigen boeking (kas / kruispost pin / storting) en Points Redeemed → omzet vanaf de balans: wachten op de drie STAP-0-antwoorden.
- Beheerder-UI voor de bron-instellingen op Instellingen › Administraties › ‹studio› › Omzet: alleen de route `GET/PUT …/omzet/bron-instellingen` bestaat.

## UX-review

Bestaand omzet-controlescherm hergebruikt met één extra blok boven de banner; geen mockup nodig, geen nieuw scherm. Het documentvak
toont voor een spreadsheet een downloadlink in plaats van de PDF-viewer.

## Beslispunten

Zie `docs/rapporten/2026-09-15-beslispunten-peter.md` (puntenwaarde, tweede store, rekeningen per studio).

## Werkt in productie: niet gemeten

**Meetrecept ná deploy:** zet "Elderveld" in de bron-instellingen van de studio-administratie (PUT-route, Beheerder) en stuur
`8-9-26.xls` + `kascheck-2026-09-08.xlsx` naar facturen@. Verwacht: één kassarapport-document in de werkvoorraad van die studio mét de
regels 250,00 / 349,03 / 420,00, betaalwijzen Cash 86,81 / PIN 932,22, kascheck-blok, controle "Puntenwaarde bekend" rood en
kasverschil 0,99 oranje; de kascheck staat als "samengevoegd in …" achter de toggle afgehandeld.
