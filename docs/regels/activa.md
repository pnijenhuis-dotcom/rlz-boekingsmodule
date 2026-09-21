# Regels — Activa / MVA

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** AKKOORD Peter 21-09 op het ontwerp (`docs/ONTWERP_ACTIVA_MVA.md`, alle defaults §8); fase 1 gebouwd 21-09: register in RLZ `FixedAssets` (Odoo later), detectie + voorvullen bij boeken, activum aanmaken ná boeken (mens bevestigt, opt-in automatisch), fiscale toetsing zonder zelf rekenen, reconciliatieblok `activa`; lees-only nulmeting `activa-nulmeting`.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Activa / MVA — STAP-0 + ontwerp (Peter 16-09; ONTWERP TER AKKOORD, geen bouw):** RLZ `FixedAssets` is een volwaardig register (document-DTO, DepreciationMethodHeaders "Lineair N jaar", actie-route; géén regel-koppeling naar de inkoopfactuur; enumeraties root-only → `rlz-lezen --root`; `IsFixedAssetAccount` te breed → MVA = vlag ÉN AccountType 3 ÉN 0xxx; Universal 403 = probe verplicht); Odoo `account_asset` ongebruikt; ontwerp = register in RLZ/Odoo, detectie + voorvullen bij boeken, fiscale toetsing zonder zelf rekenen, reconciliatieblok `activa`; lees-only nulmeting `activa-nulmeting` — zie `docs/ONTWERP_ACTIVA_MVA.md` + BESLISSINGEN "ACTIVA / MVA — STAP-0 + ONTWERP (Peter 16-09)".

<!-- toegevoegd 21-09-2026, opdracht "activa-mva-akkoord-fase-1-…" blok A (capture-at-acceptance) -->
- **Activa / MVA — AKKOORD Peter 21-09 ("activa, JA") op `docs/ONTWERP_ACTIVA_MVA.md` mét alle defaults §8 (activeringsgrens € 450 excl.
  btw — RLZ `FixedAssetAlertAmount` wint als gevuld; lineair, restwaarde 0; termijnen inventaris 5 / vervoermiddelen 5 / computers-software 3 /
  machines 5 / gebouwen 30 tot bodemwaarde WOZ / steigermateriaal 5 jr; automatisch aanmaken = opt-in per administratie default UIT; bijkomende
  kosten = voorstel + mens; RLZ vóór Odoo). Status ONTWERP TER AKKOORD (16-09) → AKKOORD + FASE 1 GEBOUWD (21-09, migratie 0168).**
  **Nulmeting 21-09 (`activa-nulmeting`, 78 administraties, verkenning/nameting-activa-nulmeting-21-09.txt):** 75 administraties mét
  MVA-rekeningen (344), 51 activa in 7 registers — Pilates Bloom B.V. 20 (rijkste → fase 1 eerst hier), Zilver Beheer 13, Mantelzorgwoningen
  Midden Nederland 11, Belastingbutler 3, Beauty by Tessa Elst 2, Dimo Living & Styles 1, L.H.G. Holding 1; Universal Steigerbouw (0113 € 9.690)
  en Rubicon Investments (28 MVA-rekeningen, 0113 Verhuurmateriaal € 5.225.769,67) = 403 "recht ontbreekt"; 1 module-regel op een MVA-rekening
  (€ 45,67, onder de grens). STAP-0 21-09 (Pilates Bloom): `FixedAssets` draagt per activum `CurrentBookValue`/`CurrentDepreciationValue`
  (RLZ schrijft dus zelf af: 10.000 op 18-11-2024 → 3.674 afgeschreven op 21-09-2026 = "Lineair 5 jaar"), `DepreciationMethod` via
  `$expand` op de collectie, `JournalEntryList`/`BalanceAccount`/`DepreciationAccount` komen op de collectie NIET mee (record-vorm = fase-2-
  STAP-0); root-enumeraties `AssetTypes` 1 Fixed / 2 Stock, `AssetMutationTypes` 1 Purchase / 3 Sale / 4 Revaluate / 5 Depreciate / 6 Manual —
  zie api-verkenning "Activa — STAP-0 21-09".

<!-- toegevoegd 21-09-2026, opdracht "corrigeren-knop-geboekt-document-storno-plus-opnieuw-klaarzetten" (bijvangst poging 2) -->
- **Activa-kaart is verrijking en valideert de vorm van haar antwoord (21-09; geen migratie; BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO +
  OPNIEUW KLAARZETTEN (Peter 21-09)", alinea "Bijvangst poging 2"):** `ActivaVoorstelKaart` toont niets als het antwoord van `GET …/activa-voorstel`
  geen `kandidaten`- én `onder_grens`-lijst draagt; tot 21-09 gooide `neemOver` op zo'n antwoord een `TypeError` in een render-effect en trok
  daarmee het HELE controlescherm leeg (gouden-set-sweep 5/5 detail-casussen rood op het keten-harnas). Het keten-harnas (`visueelHarnasKeten.tsx`)
  mockt de route sinds 21-09 mét een leeg voorstel; guard `ActivaVoorstelKaart.test.tsx` ("toont niets en crasht niet bij een antwoord zonder
  kandidaten-lijst"). Regel voor élke voorstel-/verrijkingskaart: vorm toetsen vóór itereren — een `catch` op de fetch vangt geen vorm-fout in de `then`.
