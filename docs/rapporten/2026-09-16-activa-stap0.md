# Rapport 16-09 — Materiële vaste activa: STAP-0 lees-only + ontwerpnotitie, GEEN bouw (Peter 16-09)

Opdracht: `opdrachten/gedaan/2026-09-16-activa-mva-stap0.md`. Ontwerp: `docs/ONTWERP_ACTIVA_MVA.md` (TER AKKOORD). Feiten:
`verkenning/api-verkenning.md` "Activa-module — STAP-0 16-09", `verkenning/odoo-verkenning.md` §13. **Werkt in productie:
n.v.t. (lees-only STAP-0; de nulmeting over alle 76 administraties is een meetrecept ná deploy).** Geen writes naar RLZ/Odoo,
geen migratie, geen schermen; code alleen het lees-only meetinstrument `activa-nulmeting` + `rlz-lezen --root`.

## Wat de RLZ-API wél en niet kan (blok A)

- **Wél:** een volwaardig activaregister `FixedAssets` als DOCUMENT-type (ReceiptNumber, Status, Entity, Uploads) mét
  `BalanceAccount`, `DepreciationAccount`, `DepreciationMethod` (DepreciationMethodHeaders: "Lineair 1…50 jaar", "Vaste ronde
  bedragen 2 jaar", "Waardevast" — 20 standaardmethoden, `NumberOfMonths`), `LiquidationValue` (restwaarde),
  `FirstDepreciationMonth/Year`, `TotalAmountPurchase`, `CurrentBookValue`, `CurrentDepreciationValue`,
  `CalculatedDepreciationAmount`, `FixedAssetMutationList`, `JournalEntryList`, `Type` (AssetType); PUT met client-GUID en de
  actie-route `FixedAssets/{id}/Actions` (ActionKind). Activeringsdrempel staat al in RLZ: `AdministrationSettings.
  FixedAssetAlertAmount` = 450,00 (Kempen Facilities). MVA-vlag op de rekening: `Account.IsFixedAssetAccount`.
- **Niet / onbekend:** géén veld dat een activum aan een PurchaseInvoice-REGEL koppelt (haak = `InvoiceReference` + Entity + bedrag
  + eigen koppelrecord); enumeraties `AssetTypes`/`AssetMutationTypes`/`ActionKinds` zijn root-only (404 onder het
  administratie-prefix — `rlz-lezen --root` gebouwd, letterlijke waarden pas ná deploy leesbaar); of RLZ periodiek zélf
  afschrijft of een actie per periode verwacht is op de gelezen administraties niet vast te stellen (0 activa) → eerste stap van
  de bouw-opdracht op een administratie mét activa; **de vlag `IsFixedAssetAccount` is te breed** (Universal: ook voorraad- en
  inkooprekeningen 7000–7050 aangevinkt) → MVA = vlag ÉN AccountType 3 ÉN 0xxx-reeks; **rechten verschillen per administratie**
  (Universal: 403 op FixedAssets — probe verplicht).

## Odoo (blok B)

`account_asset` is geïnstalleerd maar ongebruikt op company 3: 0 activa in élke state, 0 asset-modellen (ook companies 1–10),
0 rekeningen met `create_asset ≠ 'no'`, 53 `asset_fixed`/`expense_depreciation`-rekeningen (NL-template, per categorie aanschaf +
afschrijving), 0 afschrijvingsposten. Het mechanisme (asset-model per rekening → factuurregel maakt concept-activum,
`original_move_line_ids` = koppeling naar de factuurregel, `depreciation_move_ids` auto-post) is exact wat het ontwerp in RLZ
nabouwt; veld `asset_type` bestaat niet in Odoo 19.

## Nulmeting (blok C) — deels

| Administratie | MVA-rekeningen (vlag+type 3+0xxx) | Register | Module-regels 400 d |
|---|---|---|---|
| Kempen Facilities B.V. | niet gelezen (Ledgers-call niet in deze run) | 0 activa | niet gelezen (eigen DB via Cloud Shell geweigerd) |
| Administratiekantoor Nijenhuis C.V. | — | 0 activa | — |
| Universal Steigerbouw B.V. | 0101 Gebouwen en terreinen, 0107 Kantoorinventaris, 0111 ICT-apparatuur, 0113 Computersoftware (vlag stond óók op 1100–1110 en 7000–7050) | **403 — recht ontbreekt** | — |
| Universal Verkoop (Odoo company 3) | 53 asset_fixed-rekeningen | 0 activa, 0 modellen | — |

De volledige nulmeting over alle 76 administraties (rekening, saldo, aantal module-regels, bedrag, FixedAssets-teller) is het
lees-only meetinstrument `activa-nulmeting` (nameting-allowlist): `scripts/gcp/nameting.sh activa-nulmeting` ná deploy —
eigen-DB-lezing was in deze run niet mogelijk (classifier weigerde Cloud-Shell-SQL) en per-administratie-RLZ-lezing kost ~1 min
per call via rlz-lezen. Verwachting: Universal Steigerbouw (steigermateriaal, 0107/0111) en de holdings/vastgoed-BV's (0101)
dragen saldo zonder registerpost.

## Advies bouwvolgorde

1. STAP-0 op een administratie MÉT activa (of één testactivum op de RLZ-testadministratie): `FixedAssets/{id}?$expand=
   JournalEntryList,FixedAssetMutationList`, `ActionKinds`/`AssetMutationTypes` via `--root`, en of een afschrijvingspost
   automatisch verschijnt — dit bepaalt fase 2.
2. Fase 1 (RLZ eerst): `grootboekrekening.is_activa` (drie voorwaarden), chip + blok in het controlescherm (mockup-aanpassing
   controlescherm-v2), activum aanmaken ná boeken achter opt-in, reconciliatieblok `activa`, rechten-probe FixedAssets.
3. Odoo volgt zodra Universal Verkoop asset-modellen inricht (Odoo-configuratie, geen module-code).

## Beslispunten (default gekozen, zie `2026-09-16-beslispunten-peter.md`)

Activeringsgrens 450 (RLZ-instelling leidend); lineair; restwaarde 0; termijnen inventaris 5 / vervoermiddelen 5 / computers 3 /
machines 5 / gebouwen 30–50 tot WOZ; **steigermateriaal: vraag aan Peter**; automatisch aanmaken = opt-in per administratie;
bijkomende kosten = voorstel + mens bevestigt; bouw start in RLZ.
