# Nameting Universal Verkoop leesbron → overstap ná deploy — werkt in productie: ja/nee (Peters klik + eerste factuur in Odoo)

niet vóór: 2026-09-29 09:00
Domeinen: administraties-instellingen, werkloop-productie

Bron: rapport `docs/rapporten/2026-09-28-universal-verkoop-overstap.md` ("werkt in productie: niet gemeten"), BESLISSINGEN "UNIVERSAL VERKOOP — LEESBRON → OVERSTAP OP ODOO (Peter 28-09)",
gespreksverslag 28-09. Regel 21-09: "niet gemeten" is een schuld mét vervaldatum.

## Stap 0 — deploy-check
`git rev-list --count main..origin/main` (merge --no-ff bij divergentie, nooit rebase); service ÉN jobs op de verkoop-overstap-commit van
28-09 of later (`gcloud run services describe rlz-backend` + `gcloud run jobs describe … spec.template.spec.template.spec.containers[0].image`).
Niet live = opdracht terugleggen mét `niet vóór:` +1 dag (hoogstens drie pogingen).

## Stap 1 — dispatch-onderdeel (lees-only, bot-bestand op main)
`gh workflow run nameting -f onderdeel=verkoop-overstap` → `verkenning/nameting-verkoop-overstap-<dd-mm>.txt`: request-log POST
…/odoo/overstap(/voorbereiden) + /instellingen/odoo/verbinding-testen (201/422/5xx, latency) en `db-lezen verkoop-overstap --administratie
"Universal Verkoop" --param dagen=14` (koppeling-stand backend/alleen_lezen/kanteldatum/knip/oud RLZ-id, audit `odoo_leesbron_gepromoveerd`
+ `odoo_overstap` mét `sleutel: hergebruikt|vervangen`, documenten mét Odoo-boekstuk BILL/…). Oordeelregel: JA = promotie-audit + backend
odoo + ≥ 1 Odoo-boekstuk; DEELS = overgestapt zonder factuur in Odoo; NIET GEMETEN = Peter heeft nog niet geklikt; ROOD = 5xx.

## Stap 2 — klikpunt Peter (uitkomst in het rapport)
Instellingen › Administraties › Universal Verkoop B.V. › Algemeen › "Leesbron voorraad" → "Overstappen op Odoo…" (sleutel leeg, company 3
voorgeselecteerd, kanteldatum advies 01-09-2026, mapping bevestigen) → daarna één van de 3 open inkoopfacturen (te_controleren sinds
23-09) boeken → "Geboekt in Odoo · nr · company 3". Ongebruikt = `niet vóór:` +1 dag, hoogstens drie pogingen, daarna `mislukt/` mét het
klikpunt. Verwachte nulmeting-verschuiving: RLZ Verkoop blijft op 0 inkoopfacturen ≥ 01-09 (lees-only `rlz-lezen --count`).

## Definitie van af
Rapport `docs/rapporten/<datum>-nameting-verkoop-overstap-na-deploy.md` + INDEX + "Gelezen regels", BESLISSINGEN-alinea "Gemeten <datum>"
in de sectie hierboven, regels-alinea als het oordeel iets verandert (administraties-instellingen.md), gespreksverslag, opdracht → gedaan/.
Poort: guards (`test_rapporten_*`, `test_nameting_workflow`) groen. Beslispunt D (IC-toets RLZ-vóór/Odoo-ná) blijft in de IC-opdracht.
