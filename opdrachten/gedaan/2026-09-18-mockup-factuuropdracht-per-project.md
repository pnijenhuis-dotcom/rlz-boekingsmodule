uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-mockup-factuuropdracht.md

Domeinen: verplichtingen-projecten-voorraad, omzet, kantoor-frontend

# OPDRACHT 18-09 — MOCKUP "Factuuropdracht per project" (steigerbouw → verkoopfactuur klaarzetten in RLZ/Odoo); GEEN bouw

**Peter 18-09 (letterlijk):** "Vanuit onze module moeten wij een factuuropdracht klaar kunnen zetten voor steigerbouw (per project),
waarop wij onderdelen, termijnen etc. kunnen selecteren, waarna de factuur in RLZ (en straks Odoo) wordt klaargezet."

Dit is een nieuwe feature → mockup eerst (UX-review-regel), bouw pas ná akkoord Peter. Pre-feature-ritueel: BESLISSINGEN
"Vastly-verkoopfactuur-boekpad" (SalesInvoice-motor bestaat), "CONTRACT-ONTLEDING: KOPVELDEN + AUTO-FIRST" (specs/staffels/termijnen),
"VERPLICHTINGEN + FACTUUR↔OFFERTE-MATCH", meerwerk-kantoor (goedgekeurd, nog doorbelasten), doorbelasting-item-controle, Kempen-
doorbelasting (verkoop + spiegel), `docs/regels/verplichtingen-projecten-voorraad.md`, `omzet.md`.

## Wat de mockup toont (`mockup/factuuropdracht-project.html`, desktop kantoor, designpass v2)
1. **Projectdetail › tab "Facturatie"**: contractsom en termijnschema uit de contract-ontleding (bv. 30/40/30 of per m²), wat al
   gefactureerd is (RLZ/Odoo-verkoopfacturen op dit project), openstaand meerwerk "goedgekeurd, nog doorbelasten", verrekenbare
   inhuur-items (uit de item-controle), restant. Restant-balk.
2. **"Factuuropdracht maken"** = wizard in één scherm: vink aan wat op de factuur komt — termijn(en) uit het schema, meerwerkregels,
   verrekenbare items, vrije regel — per regel omschrijving, aantal, eenheid (m²/m¹/stuks/uur/termijn), prijs uit contract/staffel
   (herkomst-chip), btw (verlegd waar de bouwketen dat eist), project vooringevuld; debiteur = opdrachtgever van het project
   (RLZ Customer / Odoo partner), factuurdatum, referentie opdrachtgever (inkoopordernummer verplicht als de klant dat eist).
3. **Resultaat**: concept-verkoopfactuur (RLZ SalesInvoice concept via de bestaande motor; Odoo `out_invoice` draft via de adapter) mét
   PDF-preview; status in de module `klaargezet → geboekt (17) → verzonden`; boeken = bestaande boekknop mét harde checks; regel
   "meerwerk/item gefactureerd" terug op de bronrijen (status doorbelast). Nooit dubbel: een termijn/meerwerkregel kan maar in één
   factuuropdracht zitten (409 mét verwijzing).
4. **Kantoorbreed**: Inzicht › Facturatie-kandidaten: projecten met factureerbaar restant (termijn bereikt volgens planning/m²-voortgang,
   meerwerk goedgekeurd > 14 dagen) — signaal mét actie "Factuuropdracht maken" (KP7).
5. Ontwerpnotities: ① bron van prijzen (contract > staffel > handmatig, herkomst zichtbaar); ② termijnen bereikt = uit m²-voortgang/
   weekstaten of handmatig; ③ Odoo-pad = dezelfde port als inkoop; ④ verzenden van de factuur (mail naar opdrachtgever) = RLZ/Odoo
   zelf of module? beslispunt; ⑤ relatie met Kempen-doorbelasting (zelfde SalesInvoice-motor, andere bron); ⑥ accordering door de
   klant vóór verzenden? beslispunt (default: nee, kantoor boekt).

## Afronding
Alleen de mockup + `docs/rapporten/2026-09-18-mockup-factuuropdracht.md` + INDEX + BESLISSINGEN-rij "FACTUUROPDRACHT PER PROJECT —
MOCKUP (Peter 18-09)" status TER AKKOORD; beslispunten ④⑥ expliciet. Geen code, geen migratie.
