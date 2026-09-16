# Ontwerp — Materiële vaste activa (MVA) bijhouden en afschrijving automatiseren

**Status:** ONTWERP TER AKKOORD Peter (opdracht 16-09; STAP-0 lees-only uitgevoerd op RLZ én Odoo, geen bouw). Bouw volgt in een
aparte opdracht ná akkoord; UX-review-regel 15-08 geldt (het raakt het controlescherm → mockup-aanpassing controlescherm-v2).
Feiten: `verkenning/api-verkenning.md` "Activa-module — STAP-0 16-09", `verkenning/odoo-verkenning.md` §13; rapport
`docs/rapporten/2026-09-16-activa-stap0.md`.

## 1. Bron van waarheid

Het activaregister leeft in RLZ (`FixedAssets`) respectievelijk Odoo (`account.asset`) — kernprincipe 1: nooit een tweede
register in de module. De module (a) DETECTEERT bij het boeken dat een regel een activum is, (b) VULT het activum VOOR en maakt
het ná boeken aan (autoboek-patroon, opt-in), en (c) houdt dagelijks de AANSLUITING balans ↔ register in de reconciliatie:

- blok `activa` per administratie: saldo van élke activarekening (`IsFixedAssetAccount` / `asset_fixed`) = Σ boekwaarden van de
  registerposten op die rekening; saldo cumulatieve afschrijving idem; verschil = bevinding `activa_sluit_niet` mét de
  ontbrekende post(en) (regel op de activarekening zonder registerpost = "wél op de balans, niet in het register");
- registerpost zonder balansregel of afschrijving die niet gelopen is = eigen soorten (`activum_zonder_boeking`,
  `afschrijving_niet_gelopen`).

## 2. Detectie bij boeken (auto-first)

Een boekvoorstelregel op een MVA-rekening (uit de bron, geen eigen lijst: RLZ `Account.IsFixedAssetAccount` ÉN `AccountType` 3
ÉN code in de RGS-activa-reeks 0xxx — STAP-0 a9 bewees dat de vlag alleen te breed is (Universal vinkte 'm ook op voorraad- en
inkooprekeningen); Odoo `account_type == asset_fixed`; de grootboek-sync krijgt de uitkomst als kolom `grootboekrekening.is_activa`) krijgt in het
controlescherm de chip "wordt activum" + een klein blok met voorgevulde velden:

| Veld | Voorvulling | Bron |
|---|---|---|
| Aanschafwaarde | regelnetto | boekvoorstelregel |
| Aanschafdatum | factuurdatum | kop |
| Omschrijving | regeltekst | regel |
| Methode / termijn | default per rekening uit de bron (Odoo asset-model op de rekening; RLZ heeft géén default per rekening — dan de administratie-instelling per rekeningcategorie) | bron > instelling |
| Restwaarde | 0 | instelling (`LiquidationValue`) |
| Activeringsgrens | € 450 excl. btw (RLZ `AdministrationSettings.FixedAssetAlertAmount` staat op 450 bij Kempen Facilities — bron als die gevuld is, anders instelling) | bron > instelling |

Onder de grens: geen chip (kleine aanschaf direct ten laste van het resultaat), wél een oranje signaal als de regel tóch op een
activarekening staat. Bijkomende kosten (installatie, transport) op een bestaand activum: voorstel "toevoegen aan activum …" op
leverancier + omschrijving + datum ± 60 dagen; in de testfase bevestigt de mens. Ná boeken maakt de module het activum aan
achter de bestaande autoboek-patroon-regels: default UIT per administratie, harde checks, `automatisch`-markering + audit,
storno van de factuur = activum NIET verwijderen maar markeren ("factuur gestorneerd — activum beoordelen"; verwijderen doet
alleen een mens in RLZ/Odoo).

## 3. Fiscale regels — toetsen en signaleren, nooit zelf rekenen

De module berekent NOOIT zelf de afschrijving (kernprincipe 2: RLZ/Odoo boekt). Ze toetst de gekozen termijn/methode tegen de
grenzen en signaleert:
- afschrijving max 20 % van de aanschafwaarde per jaar (art. 3.30 Wet IB 2001) → termijn ≥ 5 jaar, anders signaal;
- goodwill max 10 % per jaar (≥ 10 jaar);
- gebouwen tot de bodemwaarde: WOZ-waarde — 100 % WOZ voor beleggingsvastgoed én (sinds 2024, IB) voor gebouwen in eigen gebruik;
  Vpb: 100 % WOZ voor alle gebouwen (art. 3.30a Wet IB / art. 8 Wet Vpb) → signaal "bodemwaarde controleren" bij een gebouw;
- willekeurige afschrijving, KIA, MIA/Vamil = signaal "mogelijk van toepassing" (nooit toepassen; de adviseur beslist);
- activeringsgrens € 450 excl. btw (instelbaar per administratie, default 450).

## 4. Desinvestering

Een verkoopfactuur of bankontvangst met een activum-verwijzing (registerpost in de omschrijving/relatie) → voorstel boekwinst/
-verlies (verkoopprijs − boekwaarde) als signaal met voorstel; fase 1 boekt niets, fase 3 kan het RLZ-afvoeren van het activum
(`AssetMutationType` desinvestering) aanbieden achter opt-in.

## 5. Afschrijving automatiseren

- **RLZ:** zie de STAP-0-uitkomst — de FixedAssets-DTO draagt `DepreciationMethod` (DepreciationMethodHeaders: "Lineair N jaar",
  `NumberOfMonths`, `DepreciationBaseMethod` 0/1/4), `FirstDepreciationMonth/Year`, `CalculatedDepreciationAmount`,
  `CurrentBookValue`, `JournalEntryList` en `FixedAssetMutationList`; de actie-route `FixedAssets/{id}/Actions` bestaat. Of RLZ
  periodiek zélf boekt of een actie per periode nodig heeft, is op de gelezen administraties (0 activa) niet vast te stellen — dat
  is de eerste STAP-0 van de bouw-opdracht op een administratie mét activa (zie rapport, open punt A3). Als een actie nodig is:
  dagelijkse job mét idempotentie (één afschrijving per activum per periode) en aangiftepoort (nooit in een ingediende
  btw-periode — `app/rlz/aangifte.py`).
- **Odoo:** `account.asset` maakt de afschrijvingsposten (`depreciation_move_ids`) zelf aan en post ze automatisch (`auto_post`);
  de module bewaakt alleen dat het gebeurd is (reconciliatie: laatste afschrijvingsdatum ≥ vorige periode).

## 6. Scope-afbakening

- Panden Vastgoedgroep Nederland = handelsvoorraad (RJ 220) — géén MVA, blijft bij het pandenregister/Odoo-migratie.
- Steigermateriaal Universal Steigerbouw = MVA (grote post) — het activaregister ≠ de voorraadmotor `mi` (aantallen/normalisatie);
  de grens: `mi` weet WAT er staat, het register weet WAT HET WAARD is en hoe het afschrijft. Koppeling later via de
  materiaal-normalisatie (één activum per aanschafpartij, geen per stuk).
- Vervoermiddelen, inventaris, computers, machines: MVA.

## 7. Fasering

| Fase | Inhoud | Migraties | Schermen | Tests |
|---|---|---|---|---|
| 1 | detectie + voorvullen + activum aanmaken ná boeken (opt-in) + register-lezing + reconciliatieblok `activa` | `grootboekrekening.is_activa`; `activa_instelling` per administratie (grens, methode/termijn per rekeningcategorie, opt-in); `activum_koppeling` (document/regel ↔ extern activum-id) | chip + blok in controlescherm-v2 (mockup), Instellingen › Administraties › ‹BV› › Boeken: blok Activa | gouden-set-casus (factuur op MVA-rekening), harde checks, reconciliatie-blok, RLZ-stub |
| 2 | afschrijving triggeren (RLZ, indien actie nodig) / bewaken (Odoo) | `afschrijving_run` | Inzicht › Activa lijstpatroon | idempotentie + aangiftepoort |
| 3 | desinvestering: boekwinst/-verlies-voorstel, RLZ-mutatie achter opt-in | — | actie op de verkoopfactuur/bankmutatie | — |

## 8. Beslispunten Peter (default gekozen)

1. Activeringsgrens € 450 excl. btw (default; RLZ-instelling `FixedAssetAlertAmount` als die gevuld is).
2. Methode default lineair; restwaarde 0.
3. Termijnen per rekeningcategorie: inventaris 5 jr, vervoermiddelen 5 jr, computers/software 3 jr, machines 5–10 jr (default
   5), gebouwen 30–50 jr tot bodemwaarde (WOZ), **steigermateriaal: ? (vraag aan Peter/Universal — fiscaal 20 % = 5 jaar; de
   praktijk bij steigerbouw is vaak 7–10 jaar)**.
4. Automatisch aanmaken ná boeken = opt-in per administratie (default UIT), zoals elk autoboek-pad.
5. Bijkomende kosten toevoegen aan een bestaand activum: voorstel + mens bevestigt (testfase), later autoboek-opt-in.
6. Bouwvolgorde: fase 1 eerst op één administratie mét activa (nulmeting bepaalt welke), RLZ vóór Odoo (Odoo company 3 heeft nul
   activa en geen asset-modellen — daar is niets te bewaken tot de eerste post).
