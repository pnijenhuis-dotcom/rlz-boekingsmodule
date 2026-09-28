# Universal Verkoop: leesbron → overstap op Odoo — minimaal, geen evaluatie vooraf (Peter 28-09)

Opdracht `opdrachten/gedaan/2026-09-28-universal-verkoop-leesbron-naar-overstap-odoo-minimaal.md` (besluit Peter 28-09, letterlijk:
"nee niet te moeilijk maken nu. Wat er nu moet gebeuren is RLZ los en Odoo aan. Er worden straks allemaal facturen geboekt en dat
wordt dan probleem alleen maar groter. Eerst over, daarna evalueren"). Handmatige CC-sessie 28-09 (Peter startte 'm zelf ná de
planning-v4-run). Geen migratie. **Niets in productie gewijzigd: Peter voert de overstap zelf uit via de nieuwe knop ná deploy.**

## Vastgesteld vóór de bouw (lees-only, 28-09 14:00–14:35)

Bron: leesreplica `scripts/gcp/db_lezen.sh` (als nameting@, actor Beheerder-uuid, RLS-scope 0d66ff75) + `nameting.sh rlz-lezen` op de
job-image (executies `rlz-reconciliatie-b48fb` e.v.; uitvoer in de scratchpad van deze sessie, cijfers hieronder letterlijk).

| Feit | Waarde |
|---|---|
| Administratie | Universal Verkoop B.V. `0d66ff75-07d8-426a-8127-4698c62c2f06`, `boekhoud_backend = rlz`, actief, RLZ-id `2d69fcfd…`, 1 RLZ-credential |
| Odoo-koppeling | company 3 "Universal Verkoop B.V.", api-gebruiker N-Module, `alleen_lezen = true`, knip 2026-09-01, overgangsdatum leeg, oud RLZ-id leeg, probe 04-09 |
| RLZ `PurchaseInvoices` totaal | 4.513 |
| RLZ factuurdatum ≥ 01-08-2026 | 42 |
| RLZ factuurdatum ≥ 01-09-2026 | **0** |
| RLZ `BookDate` ≥ 01-09-2026 | **0** |
| RLZ jongste factuurdatum | 31-08-2026 (vijf facturen: 2026034 € 2.520,83 status 3; 26700572 € 363,00; "20230718 / -" € 37.731,67; 190 € 199,65; 189 € 149,75 — status 2) |
| Module: documenten Verkoop sinds 01-09 | 4 = 1 `geboekt` (inkoopfactuur, geboekt 11-09, € 9.801,00, factuurdatum ≤ 31-08 — vandaar `BookDate` < 01-09) + 3 `te_controleren` (inkoopfacturen, binnen 23-09) |
| Module: alle documenten Verkoop ooit | dezelfde 4 |

**Lezing:** er staat nog géén september-factuur van Verkoop in RLZ; de "stapel die groter wordt" zijn de 3 open inkoopfacturen in de
module (te_controleren sinds 23-09). Die worden ná de overstap met hun bewaarde RLZ-rekeningen hervertaald via de mapping en boeken
dan in Odoo. **Advies kanteldatum: 01-09-2026** (= de bestaande knip en het besluit van 14-09); de datum van vandaag (28-09) geeft
hetzelfde resultaat omdat RLZ ná 31-08 niets heeft — de kanteldatum is een kanteldatum, geen poort (slotstuk 04-09).

## Gebouwd (één blok, minimaal)

1. **Backend — promotie in de bestaande overstap** (`app/odoo/service.py`, `app/odoo/mapping.py`): `toets_overstap_voorwaarden`
   weigert een ALLEEN-LEZEN koppeling niet meer als host én company gelijk zijn aan de gevraagde (andere host/company = 422 mét beide
   genoemd, niets gewijzigd; de eigen leesbron-claim telt niet als bezet in failsafe laag 2). `koppel_overstap` promoveert dan in
   DEZELFDE transactie de bestaande rij: `alleen_lezen = False`, `overgangsdatum` = kanteldatum, `voorraad_knip_datum` blijft, dagboeken/
   plan/probe uit de verse schrijvende probe, RLZ-id → sentinel, oud RLZ-id bewaard, credential-rij blijft, mapping + hervertaling +
   eerste sync zoals de gewone overstap. Sleutel: nieuw ingevoerd = vervangen (ná groene probe), veld leeg = de bewaarde sleutel
   (`leesbron_sleutel_voor`, alleen op dezelfde host + company, anders 422 — nooit stil een andere sleutel); leeg zónder leesbron = 422
   "vul de API-sleutel in". Audit `odoo_leesbron_gepromoveerd` oud → nieuw (`alleen_lezen`, overgangsdatum, knip, gebruiker, `sleutel:
   hergebruikt|vervangen`, nooit de sleutel) náást `odoo_overstap` (mét `leesbron_gepromoveerd: true`); `odoo_koppeling_aangemaakt`
   alleen nog op het nieuwe-rij-pad. `overstap/voorbereiden` en `verbinding-testen` werken op dezelfde poort zonder sleutel
   (`administratie_id` in de verbindingstest); de verbindingstest markeert de eigen leesbron-company als `eigen_leesbron` mét label
   "huidige leesbron — overstappen" (additief DTO-veld). Gewone overstap en ingang A: byte-gelijk gedrag (sleutel blijft daar verplicht).
2. **Frontend** (`OdooBackend.tsx`, `OdooKoppelWizard.tsx`, `instellingenApi.ts`): rij "Leesbron voorraad" mét leesbron krijgt naast
   "Knipdatum wijzigen…" de knop **"Overstappen op Odoo…"** → dezelfde wizard mét `promotie` (URL, company, gebruikerslabel): geen
   koppelvorm-stap (vier stappen, titel "Overstappen op Odoo — ‹naam› — stap x van 4"), URL/gebruiker voorgevuld, "API-sleutel
   (optioneel)" mét hint "leeg = bewaarde sleutel", de eigen leesbron-company kiesbaar én voorgeselecteerd (chip groen), andere claims
   grijs; voorbereiden/overstap reizen zónder `api_key` bij hergebruik; mapping-stap en resultaat ongewijzigd.
3. **IC-toets (opdracht punt 3): NIET gebouwd — vervolg (beslispunt D).** `intercompany/factuurmatch.open_bron` kiest per
   administratie één bron op `boekhoud_backend`; ná de overstap leest de IC-toets Verkoop dus volledig uit Odoo (partner-vertaling via
   de bestaande drie routes). RLZ-vóór/Odoo-ná de kanteldatum vergt een gesplitste bron (RLZ-verleden via `client_voor_rlz_verleden`
   + Odoo, venster per kant knippen, entity-vertaling twee kanten) + tests — dat is met de bestaande adapters geen uur en hoort in de
   al afgesproken IC-opdracht (gesprek 28-09 12:3x: 12 richtingen + Verkoop uit Odoo vanaf kanteldatum + onderweg-detectie).
4. **Meetlat** (regel 21-09 "niet gemeten = schuld mét vervaldatum"): bibliotheek-query `db-lezen verkoop-overstap` (koppeling-stand,
   audit-sporen, documenten mét Odoo-boekstuk), dispatch-onderdeel `verkoop-overstap` in `nameting.yml` (if-tak + options +
   `via_gh_onderdeel` + OORDEEL_BRON-tak; request-log `odoo/overstap` + `verbinding-testen`; oordeel JA/DEELS/NIET GEMETEN/ROOD),
   guard `test_verkoop_overstap_onderdeel_…`, vervolg-opdracht `opdrachten/inbox/2026-09-29-nameting-verkoop-overstap-na-deploy.md`.

## Keuzes zonder Peter
- **Andere company/host vanuit de knop = 422**, niet "wijzig eerst de leesbron": een overstap op een andere company dan de leesbron is
  een ander besluit (en zou twee koppelingen op één administratie betekenen — de PK laat dat niet toe).
- **Gebruikerslabel leeg = label van de leesbron-rij blijft** (N-Module); ingevuld = overschreven.
- **Verbindingstest zonder sleutel vereist `administratie_id`** en gebruikt uitsluitend een leesbron op dezelfde host — de wizard stuurt
  'm alleen mee bij een leeg sleutelveld in promotie-modus.
- **Kanteldatum = keuze van Peter in de wizard** (verplicht veld, geen default): advies 01-09-2026 (zie Vastgesteld).

## Tests en poorten
- Backend nieuw `tests/odoo/test_leesbron_promotie.py` (8): promotie zelfde host+company (rij, sentinel, knip blijft, audits, geen tweede
  rij, credential blijft, stand + lijst), andere company 422, andere host 422, sleutel leeg = hergebruikt (probe mét de bewaarde
  sleutel, ciphertext ongewijzigd, audit `hergebruikt`), leeg zonder leesbron 422, te korte sleutel 422, voorbereiden zonder sleutel
  (+ andere company 422 vóór de probe), verbinding-testen zonder sleutel (`eigen_leesbron`, 422 zonder administratie, mét sleutel grijs).
  Bestaand `test_router.py::test_alleen_lezen_koppeling_aanwezig_422` = nu het andere-company-pad (company 1 vs leesbron 3), ongewijzigd
  groen; één exact-dict-assert kreeg het additieve veld. Odoo-set (`test_router`, `test_mapping`, `test_projectmapping`,
  `test_hervertaling`, `test_dearchiveren_odoo`, `test_duplicaat_historie`) 137 passed; `test_nameting_workflow` + `test_lezen` +
  deploy-guard 114 passed.
- Frontend: vitest `OdooKoppelWizard.test.tsx` (+2: promotie-flow zonder sleutel t/m overstap-body zónder `api_key`; mét sleutel reist
  de sleutel mee) en `InstellingenScreen.test.tsx` (+1 knop → wizard voorgevuld; RLZ zonder leesbron: geen knop) — 62 groen in beide
  bestanden, `tsc -b` groen. Volledige vitest en volledige backend-suite: zie onder.

## Werkt in productie: niet gemeten
Deploy volgt op de push van deze commit (Stop-hook). Meetrecept = dispatch-onderdeel `verkoop-overstap` (bot-bestand
`verkenning/nameting-verkoop-overstap-<dd-mm>.txt`) ná Peters klik; vervolg-opdracht `niet vóór: 2026-09-29 09:00`, hoogstens drie
pogingen (regel 22-09 (3)).

## Klikpunten (Peter, ná deploy)
1. Instellingen › Administraties › Universal Verkoop B.V. › Algemeen › rij "Leesbron voorraad" → **"Overstappen op Odoo…"** →
   Verbinding testen (sleutel leeg) → company 3 staat voorgeselecteerd → kanteldatum (advies 01-09-2026) → Verder → mapping bevestigen
   → Koppeling opslaan. Verwacht: backend-blok toont "Odoo · company Universal Verkoop B.V. (3) · overgestapt per …", rij Leesbron
   voorraad "n.v.t. — volledige backend", eerste stamgegevens-sync groen.
2. Daarna één van de 3 open inkoopfacturen van Verkoop (te_controleren sinds 23-09, controlescherm) boeken → "Geboekt in Odoo · nr ·
   company 3" — dat is de eerste Verkoop-inkoopfactuur in Odoo (meetlat: Odoo-boekstukken ≥ 1 in `db-lezen verkoop-overstap`).

## Beslispunten (Peter)
- **D — IC-toets Verkoop RLZ-vóór/Odoo-ná de kanteldatum**: vervolg in de IC-opdracht (12 richtingen); tot dan leest de IC-toets
  Verkoop ná de overstap alleen uit Odoo, het RLZ-verleden (t/m 31-08) niet. Geen bevinding-explosie te verwachten: Verkoop → Steigerbouw
  telde 28-09 3 open paren, alle ouder dan de knip.
- **Evaluatie ná de overstap** (Peters "daarna evalueren"): de cijfers hierboven zijn de nulmeting; de vervolg-nameting levert de
  stand ná de klik.

## Gelezen regels
- `docs/regels/administraties-instellingen.md` (210 regels vóór deze run) — volledig
- `docs/regels/werkloop-productie.md` (332 regels) — volledig
- `docs/regels/vgg-odoo-migratie.md` — alinea's company-pin/kill-switch (opdracht: alleen die)
- Verder: CLAUDE.md volledig, `docs/gesprekken/2026-09-28.md`, koppelvlak-regels in CLAUDE.md § Reeleezee API (BookDate) voor de meting.

## Volledige suite
Volledige backend-suite op de werkboom (boekhouding_test, 58:54): **7679 passed, 1 failed, 2 skipped, 21 deselected**. De ene rode:
`tests/auth/test_kantoor_passkeys.py::test_registratie_en_passkey_login_met_bestaande_jwt_semantiek` — het bekende DST-kalender-artefact
(rapport 25-09 en 28-09 planning v4; rood tussen 26-09 en 25-10, niet van deze run). Volledige vitest 2068 groen, `tsc -b` groen, ruff
schoon op de geraakte bestanden. Overflow-sweep niet gedraaid: het instellingen-harnas kent geen leesbron-administratie; de knop staat in
de bestaande flex-wrap-rij naast "Knipdatum wijzigen…".
