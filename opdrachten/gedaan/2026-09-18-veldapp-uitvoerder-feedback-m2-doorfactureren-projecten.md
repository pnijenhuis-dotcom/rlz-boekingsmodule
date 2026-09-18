uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-veldapp-uitvoerder-feedback.md

Domeinen: uren-planning-veldwerkers, accordering-native-app

# OPDRACHT 18-09 — Veld-app uitvoerder: feedback Peter 18-09 (m² optioneel, doorfactureren-keuze, alle projecten, planning weg)

**Feedback uitvoerder via Peter 18-09 (letterlijk):**
1. "m² invullen geen verplicht veld."
2. "Extra toevoeging: wel doorfactureren / niet doorfactureren → dropdown."
3. "Uitvoerder moet alle projecten zien, niet alleen waar hij op gepland is — dus die mag van de planning af, maar moet wel altijd
   willekeurig op een project mee kunnen helpen en m² kunnen invullen (soort urenstaat achteraf, niet gepland)."
4. "Planning kan bij uitvoerder af."

**Feiten vooraf (Cowork, code gelezen 18-09):** `uren/schemas.py` heeft `m2: Decimal | None` — de eis zit dus in de frontend-validatie of
in `service.py`, niet in het schema; `GET /uren/zzp/projecten-keuze` ("+ ander project", A1 04-09) geeft al álle actieve projecten in
de scope — de uitvoerder vindt die uitwijk kennelijk niet of hij staat achter de geplande lijst. Bewijs dat eerst (waar zit de
m²-verplichting; waar staat "+ ander project" in de flow) vóór je bouwt; rapporteer letterlijk.

## Blok A — m² optioneel
Weekstaat-regel opslaan/indienen zonder m² mag (uren verplicht blijven). Waar m² leeg is: geen 0 invullen, veld leeg laten (null); in
het planning-grid en de kantoor-weekstaat toont de chip dan alleen uren ("8 u", geen "· 0 m²"). Factuurmatch/m²-voortgang tellen
alleen ingevulde regels; een regel zonder m² is geen fout en geen signaal. Guard-test: indienen zonder m² = 200.

## Blok B — Doorfactureren-keuze per regel
Dropdown op de weekstaat-regel: **"Doorfactureren" / "Niet doorfactureren"**. Default = afgeleid uit het project/contract
(verrekenbaar volgens de contract-ontleding → Doorfactureren; anders Niet), zichtbaar als default-chip; mens wint, audit oud→nieuw.
Kolom `doorfactureren: bool` op de weekstaat-regel (migratie), mee in de weekstaat-DTO's, keuring, kantoor-weekstaat (filter
"niet doorfactureren") en de factuurmatch (regels "Niet doorfactureren" tellen niet mee in wat aan de klant doorbelast mag worden;
meerwerk-kantoor toont ze apart). Beslispunt (default gekozen, noteer): de keuze staat op regelniveau (dag × project), niet op de
hele weekstaat.

## Blok C — Alle projecten, gepland bovenaan; "achteraf"-staat
De projectlijst in de weekstaat toont álle actieve projecten van de administratie(s) in scope, mét de geplande projecten van die week
bovenaan (chip "gepland") en de rest eronder, doorzoekbaar; "+ ander project" als aparte stap vervalt. Een regel op een niet-gepland
project krijgt chip "niet gepland" (informatief, geen blokkade) en telt in het bestaande kantoor-signaal `achteraf`/planning-afwijking
zodat het kantoor het ziet zonder dat de uitvoerder wordt gehinderd. Set-based (één query voor de lijst; querytelling-meetlat).

## Blok D — Planning uit de uitvoerder-app
De planning-weergave in de veld-app verdwijnt voor de rol uitvoerder (tab/route weg, allowlist `frontend/src/auth/rollen.ts` fail-closed);
planning blijft bestaan voor kantoor (grid) en als bron voor "gepland bovenaan" in blok C. Meldingen "planning gewijzigd" blijven
(die zijn juist nuttig zonder planningstab) — beslispunt: ook uit? default: blijven. Kantoor-web ongewijzigd.

## Afronding
Gouden set / veld-app-tests groen; migratie-afsluitroutine (blok B); WAT_IS_NIEUW ("m² is niet meer verplicht", "kies per regel of
werk wordt doorgefactureerd", "je kunt uren op elk project schrijven"); `docs/regels/uren-planning-veldwerkers.md` bijwerken +
BESLISSINGEN "VELD-APP UITVOERDER — FEEDBACK 18-09"; rapport + INDEX + "Gelezen regels"; nameting ná deploy: weekstaat indienen zonder
m² op het testaccount = 200, "werkt in productie: ja/nee".
