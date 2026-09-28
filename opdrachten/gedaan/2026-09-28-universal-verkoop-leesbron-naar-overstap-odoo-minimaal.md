> uitgevoerd 2026-09-28, rapport: docs/rapporten/2026-09-28-universal-verkoop-overstap.md (één blok, handmatige CC-sessie; IC-toets = vervolg beslispunt D; werkt in productie: niet gemeten — vervolg 2026-09-29-nameting-verkoop-overstap-na-deploy.md; Peter klikt de overstap zelf ná deploy)

# Universal Verkoop: RLZ los, Odoo aan — leesbron-koppeling promoveren naar overstap (MINIMAAL, geen evaluatie vooraf)

Besluit Peter 28-09 (letterlijk): "nee niet te moeilijk maken nu. Wat er nu moet gebeuren is RLZ los en Odoo aan. Er worden straks
allemaal facturen geboekt en dat wordt dan probleem alleen maar groter. Eerst over, daarna evalueren." Besluit 14-09 (Universal
Verkoop → Odoo per 01-09) was alleen als leesbron doorgevoerd.

Feit (Cowork, live `/instellingen/administraties` + code): Universal Verkoop B.V. (`0d66ff75…`) = `boekhoud_backend rlz`, RLZ-credential
probe groen, Odoo-koppeling company 3 op `https://universal-steigers.odoo.com` mét `alleen_lezen = true`, `voorraad_knip_datum
2026-09-01`, `overgangsdatum null`, api-gebruiker "N-Module". De bestaande overstap-wizard (`koppel_overstap`, mockup ingang B) doet
alles wat nodig is (backend → odoo, RLZ-id → sentinel, mapping, eerste sync, audit) maar weigert bij een bestaande leesbron-koppeling
(`toets_overstap_voorwaarden`, service.py ~731) en de wizardknop is voor een leesbron verborgen (`OdooBackend.tsx`, alleen "Knipdatum
wijzigen…"). Er is geen pad leesbron → volledige backend.

LEESPLICHT: CLAUDE.md, docs/regels/administraties-instellingen.md (Odoo-koppelwizard, overstap, dearchiveren-port 24-09),
docs/regels/vgg-odoo-migratie.md (alleen de company-pin/kill-switch-regels), werkloop-productie.md; docs/gesprekken/2026-09-28.md.

## Te bouwen (klein houden — één blok)
1. `toets_overstap_voorwaarden` + `koppel_overstap`: een bestaande ALLEEN-LEZEN koppeling op dezélfde URL én company blokkeert niet
   meer maar wordt in dezelfde transactie gepromoveerd (`alleen_lezen = False`, `overgangsdatum` = gekozen kanteldatum,
   `voorraad_knip_datum` blijft staan, envelope-key vervangen door de nieuw ingevoerde of — als het veld leeg blijft — de bestaande
   versleutelde sleutel hergebruiken ná groene probe). Andere URL/company = 422 zoals nu. Audit `odoo_leesbron_gepromoveerd` (oud →
   nieuw, nooit de sleutel). RLZ-id → sentinel, credential-rij blijft (zoals de gewone overstap).
2. Frontend `OdooBackend.tsx`: bij een leesbron-koppeling naast "Knipdatum wijzigen…" de knop "Overstappen op Odoo…" die de bestaande
   wizard opent mét URL/company/gebruiker voorgevuld en de sleutel optioneel ("leeg = bestaande sleutel"); mapping-stap zoals nu.
3. IC-toets (`app/intercompany`) leest een Odoo-administratie via de Odoo-verkoopbron vanaf de kanteldatum en vóór die datum via het
   bewaarde RLZ-id (lees-only) — alleen als dit met de bestaande adapters < 1 uur is; anders benoemen als vervolg (beslispunt D).
4. Tests: promotie groen, andere company 422, sleutel-hergebruik, RLZ-pad onveranderd, frontend-knop alleen bij leesbron.

## Niets in productie wijzigen in deze run
Peter voert de overstap zelf uit via de knop ná deploy (kanteldatum: zijn keuze — advies Cowork: de datum van vandaag, zodat wat
al in RLZ staat daar blijft; 01-09 kan ook, dan filtert de duplicaat-afhandeling wat al in RLZ stond). Rapport vermeldt: aantal
Verkoop-documenten sinds 01-09 geboekt in RLZ en open in de module (lees-only telling), zodat de evaluatie erna cijfers heeft.

## Definitie van af
Gouden set groen; deploy; nameting = Peters overstap-klik (kanteldatum, probe, mapping) + eerste Verkoop-inkoopfactuur die in Odoo
landt (dispatch-onderdeel `verkoop-overstap`); rapport `docs/rapporten/2026-09-28-universal-verkoop-overstap.md` + INDEX +
"werkt in productie"; BESLISSINGEN-rij; administraties-instellingen.md; WAT_IS_NIEUW; gespreksverslag; opdracht naar gedaan/.
