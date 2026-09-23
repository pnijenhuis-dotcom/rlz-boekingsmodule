uitgevoerd 2026-09-23 (avond), rapport: docs/rapporten/2026-09-23-activa-kaart-afschrijvingsrekening-conventie-422-actie-stap0.md

Domeinen: activa, reconciliatie, werkvoorraad-controlescherm, kantoor-frontend

# BUG — activa-kaart: "Activum aanmaken" slaagt op de kaart, mislukt ná boeken op "geen afschrijvingsrekening" (BLOw 23-09, 2 ×); geen mens ziet het

**Aanleiding (nameting 23-09, rapport `docs/rapporten/2026-09-23-nameting-activa-lees-only-probe.md` stap 4; BESLISSINGEN "ACTIVA / MVA — FASE 1
GEBOUWD (Peter 21-09)" alinea "Gemeten 23-09"):** de eerste twee échte gebruiken van de kaart in productie — administratie BLOw B.V (`5419878c`),
inkoopfacturen 23619 (€ 935,00, RLZ-04-00000400, 23-09 09:44 UTC) en 06052 (€ 680,00, RLZ-04-00000459, 23-09 11:53 UTC), beide regel 1 op
0107 Kantoorinventaris, categorie `inventaris`, 60 maanden — eindigden allebei als `activum_koppeling.status = mislukt` mét reden "geen
afschrijvingsrekening — kies op de kaart of stel in onder Instellingen › Activa". Volgorde per document: mens klikt "Aanmaken ná boeken" (audit
`activum_gepland`, `afschrijving_ledger_id` NULL), 2–4 s later "Boeken in RLZ", boeking slaagt in de achtergrond-schrijver, `maak_aan_in_rlz` weigert
vóór de PUT omdat `koppeling.afschrijving_ledger_id` én `activa_instelling.afschrijving_ledgers[inventaris]` leeg zijn → audit
`activum_aanmaken_mislukt`, `rlz_fixed_asset_id` NULL, geen `PUT FixedAssets`. Er staat dus NIETS in het RLZ-activaregister van BLOw terwijl de
mens tweemaal bewust "aanmaken" koos. De keuzelijst op de kaart HAD opties (BLOw: 0102/0104/0106/0108/0110/0112/0114/0116 "Afschrijving …", allemaal
0xxx soort 3) — de mens sloeg de optionele combobox over; de bevindingssoort `activum_aanmaken_mislukt` staat in `meten` (geen actiemail) en de kaart
is ná boeken alleen zichtbaar als iemand het geboekte document opnieuw opent. Kernprincipe 4 (niets verdwijnt stil) en principe 7 (6) (geen stille
no-op; signalering zonder handeling is niet af) worden hier beide geraakt.

## Wat te bouwen (alle drie; deterministisch, geen AI, geen migratie tenzij de instelling een kolom mist)

1. **Afschrijvingsrekening deterministisch voorvullen (code, niet naam-raden):** kandidaat zonder mens-keuze en zonder instelling-default krijgt de
   rekening van dezelfde administratie mét (a) code = balansrekening-code + 1 binnen dezelfde 0xxx-reeks ÉN (b) naam die begint met "Afschrijving"
   (RGS-conventie, BLOw: 0101→0102, 0103→0104, 0105→0106, 0107→0108, 0109→0110, 0111→0112, 0113→0114, 0115→0116, 0001→0002); is er precies één
   treffer → voorgevuld mét herkomst-chip "conventie (code + 1)"; nul of meer dan één → leeg, en dan geldt punt 2. Alleen niet-verdwenen, niet-
   totaalrekeningen, soort 3. Guard-tests op het BLOw-schema (fixture uit `verkenning/` of test-seed) + een schema zónder conventie (Rubicon 01100…).
2. **Nooit meer "gepland zonder afschrijvingsrekening":** `plan_of_maak_aan` weigert mét 422 (`ActivaFout` → tekst "Kies een afschrijvingsrekening —
   RLZ vereist er één per activum") als ná punt 1 nog geen rekening bekend is; de kaart toont de combobox dan als verplicht (rode rand + tekst) en de
   knop blijft `disabled` tot er een keuze staat (zelfde patroon als `registerDicht`). Het foutpad in `maak_aan_in_rlz` blijft als vangnet (instelling
   kan intussen gewist zijn), maar wordt in de praktijk onbereikbaar. Vitest: knop disabled zonder keuze mét opties; route-test 422 letterlijk.
3. **`activum_aanmaken_mislukt` ná een MENS-klik = actie, niet meten:** een koppeling `mislukt` mét `herkomst = mens` is een bevestigde handeling die
   niet is uitgevoerd → `SoortDefinitie.direct_actie_reden` (derde uitzondering ná `intussen_extern_geboekt`/`intake_postvak_verschil`; guard pint de
   lijst) óf een aparte soort `activum_aanmaken_mislukt_mens` direct in `actie` mét handeling "Opnieuw aanmaken" (bestaande route
   `POST …/activa-voorstel/{regel}/aanmaken` mét `afschrijving_ledger_id`) + deeplink naar het document; `herkomst = automatisch` blijft in `meten`.
   Explosie-rem blijft. Het rapport van 23-09 telt 2 zulke rijen (BLOw) — verwacht ná deploy: 2 actie-bevindingen in de run van 06:30, actiemail.

## Herstel BLOw (klikpunt, geen CC-write in RLZ zonder TEST-referentie/akkoord)
- Ná deploy: open in de module BLOw B.V → inkoopfactuur 23619 (RLZ-04-00000400, € 935,00, 23-09) en 06052 (RLZ-04-00000459, € 680,00, 23-09) →
  kaart "Activum aanmaken?" → kies 0108 Afschrijving kantoormeubilair (of ná punt 1 voorgevuld) → "Activum aanmaken" (document is geboekt → direct
  `PUT FixedAssets`). Verwacht: koppeling `aangemaakt`, `rlz_fixed_asset_id` gevuld, audit `activum_aangemaakt`, RLZ-register BLOw 0 → 2.
- Meetlat: `db-lezen activa-stand --administratie BLOw` (rij `koppeling` = `aangemaakt` 2) + `rlz-lezen --administratie BLOw FixedAssets` (2 records,
  `InvoiceReference` 23619/06052). Dispatch-onderdeel toevoegen: `activa-kaart` (request-log POST aanmaken 200/422/5xx + db-lezen koppelingen per
  status kantoorbreed via loop — vier plekken: if-tak, `options:`, `via_gh_onderdeel`, `OORDEEL_BRON`).

## Afsluiting
Rapport + INDEX + "## Gelezen regels"; alinea in `docs/regels/activa.md` + BESLISSINGEN-sectie "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)";
`WAT_IS_NIEUW.md`; vervolg-nameting mét `niet vóór:` (deploy + run 06:30) als `opdrachten/inbox/`-bestand. Volledige poort (pytest + vitest + tsc -b +
gouden set — de kaart zit in het keten-harnas).

## Aanvulling Cowork 23-09 18:3x — DERDE fout: `PUT FixedAssets/{client-guid}` → 404 `NotFound_FixedAsset` (Peter, BLOw, MK Illumination
Holland / Multilight B.V., factuur MK22507863, samengevoegd 6 regels, 0107 Kantoorinventaris, € 1.078,10, aanschaf 18-12-2025, Lineair 60 mnd)
De kaart liep hier WEL door tot de PUT (dus mét afschrijvingsrekening of ná punt 1) en RLZ antwoordde
`PUT /3d30c36b-f46b-4124-8301-906169c9432b/FixedAssets/619639aa-7426-59f5-8cb9-8bf78b2eeebd -> 404 {"Message":"NotFound_FixedAsset"}`.
Een 404 op een PUT-met-client-GUID betekent dat RLZ `FixedAssets` NIET als aanmaakroute-met-eigen-id accepteert (anders dan
PurchaseInvoices/SalesInvoices/ManualJournals). Vóór verder bouwen: **STAP-0 op de RLZ-testadministratie (nooit op BLOw)** — welke vorm maakt
een activum aan: (a) PUT zonder id / POST op de collectie, (b) een actie op de geboekte inkoopfactuur (`POST PurchaseInvoices/{id}/Actions`
mét een activeer-type — `ActionKinds` root-only lezen), (c) `FixedAssetMutationList` als onderdeel van een bestaand document, (d) een
verplicht veld dat ontbreekt (Type/AssetType, DepreciationMethod-id, BalanceAccount) waardoor RLZ 404 i.p.v. 400 geeft. Vastleggen in
api-verkenning "FixedAssets — aanmaakroute STAP-0"; pas daarna `maak_aan_in_rlz` aanpassen. Tot dan: kaart toont bij deze fout
"aanmaken in Reeleezee nog niet mogelijk — wordt onderzocht" i.p.v. de ruwe RlzApiError, en de bevinding is actie (punt 3).
Peter 23-09: "kunnen wij de afschrijvingsregel ook niet automatiseren obv de gekozen activa-regel?" — ja, dat is punt 1; blijft
deterministisch (code + 1 én naam "Afschrijving…"), nooit AI.
