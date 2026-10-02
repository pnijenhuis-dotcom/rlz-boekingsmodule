MISLUKT ná 3 pogingen (2026-09-21T13:31:49) — laatste: You're out of usage credits. Switch to another model, or manage usage credits at claude.ai/admin-settings/usage, to continue.

Domeinen: vgg-odoo-migratie, administraties-instellingen, bank, omzet, reconciliatie

# OPDRACHT 21-09 — Vastly op Odoo: pilot ARVUM B.V. in PARALLEL-MODUS (RLZ leidend t/m boekjaar 2026, Odoo spiegel) → schone
# overgang per 01-01-2027; fase 0/1 nu

**Besluiten Peter 21-09 (capture-at-acceptance — BESLISSINGEN + `docs/regels/vgg-odoo-migratie.md` + `docs/ONTWERP_VASTLY_ODOO.md` §3/§5):**
1. Pilot = **ARVUM B.V.** (advies ontwerp §3 gevolgd). Rubicon later.
2. **Parallel-modus i.p.v. schaduwmaand:** Peter rondt ARVUM boekhoudkundig gewoon af in RLZ t/m boekjaar 2026; Odoo krijgt vanaf de
   start van de pilot ALLES dubbel (inkoop, verkoop 380/381, waarborg, bank + afletteren), dagelijks cent-exact vergeleken, zodat de
   kinderziektes eruit zijn vóór de echte start; **kanteldatum = 01-01-2027** (boekjaarwissel, schone overgang). RLZ blijft tot dan
   de enige bron van waarheid (Kernprincipe 1), Odoo is in die periode een gespiegelde testboekhouding — nooit een aangifte uit Odoo.
3. Defaults uit ontwerp §5 akkoord: bank eerst brug A (wij schrijven statement lines), eindbeeld B (Odoo-banksync) — "ja defaults";
   addendum v1.21 als OPEN_ITEM naar het Platform; parallel aan de VGG-replay; creditnota 381 via de reversal-wizard.
4. Voorwaarden aan Peters kant (klikpunten, in het rapport noemen): Odoo-company voor ARVUM aanmaken (bestaat nog niet; koppeling
   daarna via Instellingen › Administraties, Odoo-wizard); Vastly-kant: huurfacturen/waarborgen ARVUM via de boekhoudmail aanzetten.

## Ontwerpvraag die deze opdracht beantwoordt vóór de bouw (blok A, ontwerp → §2.6 "Parallel-modus")
Een administratie krijgt een derde backend-stand náást `rlz`/`odoo`: **`rlz` leidend + `odoo` spiegel** (veldnaam voorstel
`spiegel_backend`). Regels: élke write die op RLZ slaagt wordt óók naar de spiegel geschreven (zelfde deterministische GUID-basis,
`odoo_uuid`), uitkomst per kant zichtbaar op het document (chip "Odoo-spiegel: geboekt / mislukt / niet ondersteund"); een spiegel-fout
blokkeert NOOIT de RLZ-boeking en gaat als bevinding `odoo_spiegel_mislukt` naar het reconciliatieblok `odoo_vs_rlz` (start in `meten`,
regel reconciliatie 2); dagelijkse cent-exacte vergelijking RLZ ↔ Odoo per document, per grootboekrekening en per bank-saldo; storno
aan één kant zonder de andere = ROOD. Webhooks blijven de RLZ-id's dragen tot de kanteldatum (contractnorm ongewijzigd); de
Odoo-id's lopen mee in een extra veld pas ná addendum v1.21. Kill-switch per administratie voor de spiegel (uit = alleen bevinding
"spiegel uit", nooit stil). Kanteldatum-wizard = de bestaande Universal-overstapwizard (ingang B) mét één extra stap: "spiegel wordt
leidend, RLZ wordt archief" — geen tweede migratiepad. Toets het ontwerp op de drie stromen die ARVUM NIET heeft (doorbelasting-doel,
omzet-Receipts, IC) — die blijven buiten scope voor de pilot maar mogen de parallel-modus niet kapotmaken.

## Bouw fase 0/1 (ontwerp §4), alleen wat nu kan zonder de ARVUM-company
- **Fase 0 (voorwaarden):** registerdrift ARVUM `is_vastgoed` AAN vs `Platform/registers/entiteiten.md` "pas bij het Vastly-moment" →
  register bijwerken (ARVUM is nu formeel het Vastly-moment); `afgeletterd_event`-tier voor ARVUM aan zodra de verkoopstroom loopt
  (niet eerder — geen no-op-events).
- **Fase 1 STAP-0 bank op Odoo:** bewijs de bestaande primitieven in `app/migratie/odoo_schrijf.py` (statement.line create +
  `unique_import_id`, statement `balance_end_real`, reconcile-route i/ii/iii, partial + write-off, `remove_move_reconcile`,
  `amount_residual`-semantiek) LIVE op een Odoo-TEST-company (company 3 = Universal-test volgens odoo-verkenning, óf de ARVUM-company
  zodra Peter die heeft — noem in het rapport welke), TEST-referenties, alles teruggedraaid via `button_cancel`/`remove_move_reconcile`
  (nooit unlink). Uitkomst: één gekozen reconcile-route in odoo-verkenning §14 + `BankPort`-interface (nog geen implementatie in
  `app/bank/`). Kill-switch blijft; `nameting.sh` weigert.
- **Fase 2 voorbereiding (geen writes):** `VerkoopPort` naast `InkoopPort` (registry, capability-contract) mét RLZ-implementatie =
  bestaande motor, Odoo-implementatie = `out_invoice` draft → post, huurder-`res.partner` (customer_rank, zoek-vóór-create) — gebouwd
  achter de kill-switch, getest tegen mocks + de Odoo-testcompany, NIET op ARVUM tot de company bestaat.
- Platform: OPEN_ITEM addendum v1.21 aanvullen mét de parallel-modus (twee id-sets tot de kanteldatum).

## Rapport
`docs/rapporten/2026-09-21-vastly-odoo-arvum-parallel-fase-0-1.md` + INDEX + Gelezen regels; ontwerpdocument §2.6/§3/§4 bijgewerkt
(status "AKKOORD Peter 21-09 — pilot ARVUM, parallel-modus, kanteldatum 01-01-2027"); BESLISSINGEN-rij; CLAUDE.md één verwijsregel
(vgg-odoo rij 4 bijwerken); klikpunten Peter expliciet: Odoo-company ARVUM, Vastly-boekhoudmail ARVUM.
