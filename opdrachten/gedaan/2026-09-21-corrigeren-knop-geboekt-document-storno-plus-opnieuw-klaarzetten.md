uitgevoerd 2026-09-21 (poging 2 ná WIP-branch `wip/2026-09-21-corrigeren-knop-geboekt-document-storno-plus-opnieuw-klaarzetten` 25be9fb), rapport: docs/rapporten/2026-09-21-corrigeren-geboekt-document.md

Domeinen: werkvoorraad-controlescherm, doorbelasting-intercompany, reconciliatie

# OPDRACHT 21-09 — "Corrigeren…" op een geboekt document: storno (actie 19) + opnieuw klaarzetten, vanuit de module

**Aanleiding (Peter 21-09):** twee BLOW-boekingen met een fout btw-bedrag (RLZ-04-00000357 Fac-25-023465 btw 48,18 i.p.v. 56,93;
RLZ-04-00000358 "cb" 3,37 i.p.v. 7,87) moesten in de RLZ-UI gecorrigeerd worden: "ik kan de storno-knop niet meer vinden". Die knop
bestaat niet — GEBOEKT is lokaal terminaal (`storno_detectie.py`: "een storno gebeurt dáár uitsluitend via actie 19 in de RLZ-UI").
Dat is een gat tegen Kernprincipe 7 (minimale mens): een fout die de module zelf heeft geboekt, moet de module zelf kunnen herstellen.
Peter 21-09: "laten we die terugboeken meenemen".

## Wat het wordt
Op een GEBOEKT inkoop-/verkoop-/kassarapport-document in het ⋯-menu: **"Corrigeren…"** = dialoog mét verplichte reden (≥ 5 tekens) →
in één stap: (1) actie 19 op het externe document via de port (`InkoopPort`/verkoop-motor; Odoo = `button_draft`/reversal volgens de
adapter-semantiek, capability-contract 0016: niet ondersteund = zichtbare fout), terug-lezen dat het document Status 1 heeft;
(2) lokaal het BESTAANDE herboek-mechanisme (`herboeken.py`: `boek_cyclus += 1`, `rlz_boekstuknummer` leeg, GEBOEKT →
KLAAR_OM_TE_BOEKEN, neveneffecten terugdraaien: verplichting-verbruik, mini-voorraad, doorbelasting-spiegel mee-storneren via het
bestaande spiegelpad, webhook `factuur_gestorneerd` voor vastgoed-administraties); (3) het document opent direct in het controlescherm
mét een gele balk "Gecorrigeerd — reden: … · vorige boeking RLZ-04-00000357" en de regels als ze waren, zodat de mens alleen de fout
aanpast en opnieuw boekt (harde checks vers, modus VERS; duplicaatcheck kent de eigen vorige boeking als uitgezonderd, zoals bij het
tegenboek-pad).

## Poorten (bestaand hergebruiken, niets nieuws verzinnen)
- **Aangiftepoort** (`app/rlz/aangifte.py`): boekdatum in een ingediende btw-periode → géén storno maar het TEGENBOEK-PAD (bestaande
  knop), mét uitleg waarom. De 357/358-casus (factuurdatum 2025/2026?) toetst CC in het rapport als voorbeeld.
- **Afgeletterd** (`OpenAmount` < totaal of Status 3): storno van een (deels) betaalde factuur laat huls-koppelingen achter
  (api-verkenning actie 15/19) → blokkeren mét tekst "eerst afletteren terugdraaien in de bankmodule" + link naar de mutatie; nooit stil.
- Doorbelasting-bron mét spiegel: beide kanten of geen — bestaande motor.
- Klant-accordering: een gecorrigeerd document dat opnieuw ter accordering moet? Nee — het akkoord gold de factuur, niet de
  boekingsregels (regel accordering 1); tijdlijnregel "opnieuw geboekt ná correctie" naar de accordeur-app is genoeg.
- Rechten: Medewerker+; audit `document_gecorrigeerd` mét reden, oud extern id, oud boekstuknummer.

## Sweep + tests + nazorg
- `storno_detectie.py` docstring + `docs/regels/werkvoorraad-controlescherm.md` bijwerken (GEBOEKT niet meer terminaal-zonder-uitweg).
- Tests: statusmachine, aangiftepoort → tegenboeken, afgeletterd → blok, spiegel mee, webhook-event, idempotentie (tweemaal klikken =
  één storno), Odoo niet-ondersteund = zichtbaar.
- Nameting ná deploy: TEST-referentie op de RLZ-testadministratie (nooit een klantadministratie).
- Rapport + INDEX + Gelezen regels; BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)"; WAT_IS_NIEUW;
  CLAUDE.md één verwijsregel onder werkvoorraad.
