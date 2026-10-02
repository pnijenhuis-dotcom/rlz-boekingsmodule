> uitgevoerd 2026-10-02, rapport: docs/rapporten/2026-10-01-vastly-verkoop-administratie-id-terugval-uit.md

# Opdracht 01-10 — Vastly-verkoop: administratie-id uit de UBL als eerste bron, terugval en historie-afleiding UIT

Besluit Peter 01-10 (letterlijk): "ik wil gewoon dat de vastly facturen automatisch per BV op de juiste GB geboekt worden" en "we hebben
afgesproken dat vastly facturen 100% auto gaan zonder menselijk tussenstap … zo moet het ook blijven, hou het simpel". Herziet twee
onderdelen van de opdracht van 29-09 (migratie 0172): de omzetrekening-terugval en de naam-koppeling door een mens.

LEESPLICHT: docs/regels/omzet.md, docs/regels/intake-extractie.md, docs/regels/reconciliatie.md, docs/regels/werkloop-productie.md;
Platform/OPEN_ITEMS.md (nieuw item "administratie-id van de verhuurder in élke boekhoudmail-UBL" + het item over `cbc:AccountingCost`
met het Vastly-antwoord van 01-10); BESLISSINGEN "VASTLY-VERKOOP VOLLEDIG AUTOMATISCH …". Geen UX-impact behalve bevindingsteksten.

## Wat er moet veranderen (alleen dit — geen bijvangst)

1. **Administratie uit de UBL.** Vastly zet een tweede `cac:AdditionalDocumentReference` naast `VASTLY-VERKOOP` met
   `cbc:ID` = `RLZ-ADMINISTRATIE:<platform administratie-uuid>` (vorm nog door Vastly te bevestigen in OPEN_ITEMS — bouw de lezer zó dat
   het pad/prefix één constante is). `app/verkoop/entiteit.py::resolve_administratie` krijgt dat id als EERSTE bron: bestaat de
   administratie, is ze actief en niet gearchiveerd → klaar (koppelingsrij vastleggen met bron `ubl`). Daarna de bestaande KvK-route
   ongewijzigd. De NAAM-route (bron 'mens') vervalt: geen koppel-handeling meer in de bevinding; `vastly_entiteit_niet_gekoppeld` blijft
   bestaan als bevinding mét tekst "UBL draagt geen administratie-id en geen bekende KvK — melden bij Vastly" en zonder knop die een mens
   laat kiezen. Bestaande mens-koppelingen blijven werken (lezen), er komen geen nieuwe bij.
2. **Omzetrekening: alleen `AccountingCost`.** `app/verkoop/omzetrekening.py`: `leid_af` (eigen historie + rekeningschema) en de
   instelling "Vastly-omzetrekeningen" (rij in Instellingen › Administratie › Algemeen, `PUT …/vastly-omzetrekeningen`) vervallen als
   BRON voor het boeken. Een regel zonder `AccountingCost` of met een code die niet in het rekeningschema van de administratie staat =
   weigeren met reden `omzetrekening_ontbreekt` → bevinding `vastly_omzetrekening_ontbreekt` in `actie` mét alleen "Opnieuw aanbieden"
   (ná herzending door Vastly); knop "Rekening kiezen" weg. De instellingenrij verwijderen uit het scherm; tabel `vastly_omzetrekening`
   mag blijven (lees-only historie), geen migratie nodig. De koppelcontract-regel "AccountingCost = winnaar" blijft; §2d-notitie: de
   terugval van 29-09 was een tijdelijke afwijking en is per 01-10 afgezet (Platform-contract, versiebump, OPEN_ITEMS-item afvinken).
3. **Nazorg-CLI** `vastly-verkoop-heraanbieden` ongewijzigd in vorm; de uitvoer noemt per weigering de reden zoals nu.
4. **Test op het afwezig-pad** (guard): UBL mét administratie-id en zónder KvK → geboekt; UBL zonder code → geweigerd, nooit op een
   afgeleide rekening; gouden-set-casus ao-vastly-verkoop bijwerken.

## Niet doen
- Geen nieuwe keuzelijsten, geen nieuwe instellingen, geen "mens kiest"-knop, geen fuzzy match op naam.
- De 39 her-aanleveringen van Vastly en het terugdraaien van de al geboekte nota's zijn GEEN onderdeel van deze opdracht (Cowork/Peter
  in de module; OPEN_ITEMS r.14-item).

## Af = 
Volledige suite groen, vitest/tsc groen, WAT_IS_NIEUW-regel (klantleesbaar: "Vastly-huurnota's boeken alleen nog op de rekening die
Vastly meestuurt"), BESLISSINGEN-sectie, regels-alinea in omzet.md, CLAUDE.md één verwijsregel onder Omzet, rapport docs/rapporten/
2026-10-01-vastly-verkoop-administratie-id-terugval-uit.md + INDEX + "Gelezen regels", "werkt in productie: niet gemeten" + vervolg-
nameting (dispatch-onderdeel `vastly-verkoop`) ná de eerste herzending van Vastly. Committen; de Stop-hook pusht.
