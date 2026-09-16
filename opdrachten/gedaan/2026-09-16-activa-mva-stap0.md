uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-activa-stap0.md

# OPDRACHT 16-09 — Materiële vaste activa (MVA): STAP-0 lees-only + ontwerpnotitie, GEEN bouw (Peter 16-09)

**Aanleiding (Peter 16-09, letterlijk):** "Ik wil ook graag dat jij voortaan de activa bij gaat houden en daarop onze MVA
(materiële vaste activa) staat gaat bijwerken zodat dat altijd up to date is en de afschrijving daarop geautomatiseerd kan
worden. RLZ heeft een activa module, Odoo denk ik ook."

Doel van deze opdracht: feiten verzamelen en één ontwerpvoorstel schrijven. Geen schrijfacties in RLZ of Odoo, geen migratie,
geen schermen. Bouw volgt in een aparte opdracht ná akkoord Peter op het ontwerp (UX-review-regel 15-08 geldt: het raakt het
controlescherm).

Pre-feature-ritueel: BESLISSINGEN "CONTROLESCHERM AUTO-FIRST", "Harde/blokkerende checks", "REGEL-NIVEAU GB-VOORSTEL"
(medewerker-wensen D), "VASTGOEDGROEP … RUN 1" (RJ 220: panden zijn HANDELSvoorraad, géén MVA — buiten scope), api-verkenning
`Ledgers` (`IsFixedAssetAccount`-vlag op het Account-DTO, STAP-0 13/14-09), odoo-verkenning §… (`account_asset` staat geïnstalleerd
op universal-steigers.odoo.com, regel 199; `asset_fixed` 48 rekeningen, `expense_depreciation` 5).

## Blok A — RLZ activa-API, lees-only (`rlz-lezen`, geanonimiseerd, ≤ 50 per route)
De `GET /Help`-lijst kent o.a. `FixedAssets`, `FixedAssets/{id}`, `AssetTypes`, `AssetMutationTypes`, `DepreciateFixedAsset`
(actie?) — nooit gebruikt. Vast te stellen op één administratie mét bestaande activa (kies er een uit de 76 waar
`IsFixedAssetAccount`-rekeningen saldo dragen; noem welke):
1. `GET FixedAssets` (+ `$expand` van alles wat het DTO aanbiedt): velden (aanschafdatum, aanschafwaarde, restwaarde,
   afschrijvingsmethode/-termijn, gekoppelde grootboekrekeningen activa/afschrijvingskosten/cumulatieve afschrijving, status,
   koppeling naar het inkoopdocument/de regel?), aantallen, voorbeeldrecord geanonimiseerd.
2. `AssetTypes`, `AssetMutationTypes`: enumeraties letterlijk vastleggen (dit zijn onze toekomstige defaults per rekening).
3. Hoe boekt RLZ de afschrijving: periodiek automatisch (welke journaalpost, EventID?) of via de actie `DepreciateFixedAsset`
   per activum/periode? Lees de JournalEntries van een bestaand activum (EventID-verdeling) — GEEN actie uitvoeren.
4. Schrijfvorm ALLEEN documenteren (PUT met client-GUID zoals de rest?), niet proberen. Is een activum koppelbaar aan een
   PurchaseInvoice-regel (veld in het DTO)? Zo ja: dat is de natuurlijke haak vanuit ons boekpad.
5. Rate-limit-inschatting voor een dagelijkse lees-sync over 76 administraties.
Alles in api-verkenning, nieuwe sectie "Activa-module — STAP-0 16-09".

## Blok B — Odoo `account_asset`, lees-only (company 3 Universal Verkoop, JSON-2)
1. `account.asset`: velden (original_value, salvage_value, method linear/degressive, method_number/period, account_asset_id,
   account_depreciation_id, account_depreciation_expense_id, journal_id, state draft/open/close, original_move_line_ids),
   aantal bestaande activa, `account.asset.model`-defaults (asset models per rekening!) — dat is exact het mechanisme dat we
   in RLZ zelf moeten nabouwen.
2. Hoe activeert Odoo: `create_asset` op de rekening (`account.account.create_asset` = no/draft/validate) → een factuurregel op
   zo'n rekening maakt automatisch een concept-activum. Documenteer welke rekeningen dat nu hebben.
3. Afschrijvingsposten: `depreciation_move_ids`, auto-post per maand. Alles in odoo-verkenning §13.

## Blok C — Eigen datalaag nu al inventariseren (lees-only, eigen DB + RLZ/Odoo)
- Per administratie: welke rekeningen zijn `IsFixedAssetAccount` (RLZ) / `asset_fixed` (Odoo), saldo per vandaag, en hoeveel
  inkoopfactuurregels boekte de MODULE de laatste 400 dagen op zo'n rekening (dat zijn de activa die nu al "bijgehouden" hadden
  moeten worden). Tabel in het rapport per administratie: rekening, saldo, aantal module-regels, bedrag, of er in RLZ al een
  FixedAsset tegenover staat (koppelen op bedrag+datum).
- Dit is de nulmeting: "hoeveel activa staan er wél op de balans maar niet in de activamodule".

## Blok D — Ontwerpnotitie (docs/ONTWERP_ACTIVA_MVA.md, ter akkoord Peter)
Uitwerken als accountant + architect, kort en beslisbaar:
1. **Bron van waarheid:** het activaregister leeft in RLZ/Odoo (KP1 — nooit een tweede register in de module); de module
   detecteert, vult voor en houdt de aansluiting balans ↔ register dagelijks in de reconciliatie (blok `activa`: saldo
   activarekening = Σ boekwaarden register; cumulatieve afschrijving idem; verschil = bevinding mét de ontbrekende post).
2. **Detectie bij boeken (auto-first):** regel op een MVA-rekening (vlag uit de bron, geen eigen lijst) → chip "wordt
   activum" + voorgevulde velden (aanschafwaarde = regelnetto, datum = factuurdatum, omschrijving = regeltekst, methode/termijn
   = default per rekening uit de bron (Odoo asset model / RLZ AssetType) anders per administratie-instelling, restwaarde 0),
   ná boeken automatisch het activum aanmaken (autoboek-patroon: default UIT per administratie, harde checks, audit, storno =
   activum terug naar concept/verwijderen NIET — markeren). Bijkomende kosten op een bestaand activum (installatie, transport)
   = "toevoegen aan activum …" i.p.v. nieuw — voorstel via leverancier/omschrijving, mens bevestigt in de testfase.
3. **Fiscale regels expliciet noemen, niet zelf bedenken:** afschrijving max 20 % per jaar op aanschaf (art. 3.30 Wet IB),
   goodwill max 10 %, gebouwen tot bodemwaarde (WOZ; 100 % voor beleggingsvastgoed én sinds 2024 ook eigen gebruik in de IB —
   vennootschapsbelasting: 100 % WOZ) — de module rekent NOOIT zelf de afschrijving (KP2: RLZ/Odoo boekt), maar toetst de
   gekozen termijn tegen deze grenzen en signaleert. Willekeurige afschrijving / KIA / MIA-Vamil = signaal "mogelijk van
   toepassing", nooit toepassen. Investeringsdrempel activeren: € 450 excl. btw (kleine aanschaffingen direct ten laste van
   het resultaat) — als instelbare grens per administratie, default 450.
4. **Desinvestering:** verkoopfactuur/bank-ontvangst met een activum-verwijzing → boekwinst/-verlies-voorstel; alleen signaal +
   voorstel in fase 1.
5. **Afschrijving automatiseren:** in RLZ = wat de activamodule zelf doet (uitkomst blok A bepaalt of wij een actie moeten
   triggeren per periode; dan een dagelijkse job mét idempotentie en aangiftepoort — een afschrijving in een ingediende periode
   nooit); in Odoo = `account.asset` auto-post. De module bewaakt alleen dat het gebeurd is (reconciliatie).
6. **Scope-afbakening:** panden VGG = handelsvoorraad (RJ 220), geen MVA; steigermateriaal Universal = MVA (grote post!) —
   voorraadmotor `mi` ≠ activaregister; noem de grens.
7. **Fasering:** fase 1 = detectie + voorvullen + register-aansluiting + reconciliatieblok (lees-only naar RLZ/Odoo, schrijven
   alleen het activum bij boeken achter opt-in); fase 2 = afschrijving triggeren/bewaken; fase 3 = desinvestering. Per fase
   migraties/schermen/tests benoemen. UX: chip + klein blok in het controlescherm (mockup-aanpassing controlescherm-v2 nodig →
   mockup-bestand leveren), Inzicht › Activa als lijstpatroon later.
8. Beslispunten voor Peter mét default (activeringsgrens 450; methode default lineair; termijnen per rekeningcategorie —
   inventaris 5 jr, vervoermiddelen 5 jr, computers 3 jr, machines 5–10 jr, steigermateriaal ? — vraag; restwaarde 0; opt-in
   autom. aanmaken per administratie).

## Af
- api-verkenning + odoo-verkenning secties, `docs/ONTWERP_ACTIVA_MVA.md`, rapport `docs/rapporten/2026-09-16-activa-stap0.md`
  + INDEX (nulmeting-tabel, wat de RLZ-API wél/niet kan, advies bouwvolgorde, beslispunten), BESLISSINGEN registerrij
  "ACTIVA / MVA — STAP-0 + ONTWERP (Peter 16-09), status ONTWERP TER AKKOORD", CLAUDE.md één verwijsregel, memory-regel voor
  Cowork niet nodig (rapport is de bron). Werkt in productie: n.v.t. (lees-only). Geen code behalve eventueel een lees-only
  `rlz-lezen`-uitbreiding als de FixedAssets-route een niet-standaard vorm heeft (dan in de nameting-allowlist).
