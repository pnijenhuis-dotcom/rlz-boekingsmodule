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

<!-- toegevoegd 22-09-2026, opdracht "nameting-activa-fase1-en-bua-kandidaten-na-deploy" -->
- **Fase 1 gemeten 22-09 — werkt in productie: JA voor sync, reconciliatieblok en kaart-route; kaart/aanmaken niet gemeten (22-09; BESLISSINGEN
  "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)" alinea "Gemeten 22-09"; rapport `docs/rapporten/2026-09-22-nameting-activa-fase1-en-bua.md`):**
  de `sync-alles` van 22-09 07:00 NL (eerste run op de fase-1-image) zette `is_activa` op 344 rekeningen over 75 RLZ-administraties (exact de
  nulmeting van 21-09; de drie Odoo-administraties 48 elk via `asset_fixed`, zonder `activa_instelling`-rij — fase 1 is RLZ-only), schreef per
  RLZ-administratie `activa_instelling` mét grens 450 / RLZ-grens 450 en de register-probe (73 leesbaar, Universal Steigerbouw + Rubicon Investments
  403 — klikpunt blijft), `automatisch_aanmaken_ingeschakeld` nergens aan. Het blok `activa` (lees-only, `ba2e231`): 75 getoetst, 22 afwijkingen
  (register 2, `activum_zonder_boeking` 19 — alle 2026-activa zijn buiten de module geboekt, `afschrijving_niet_gelopen` 1 Beauty by Tessa Elst,
  `mva_boeking_zonder_activum` 0, `activum_aanmaken_mislukt` 0), alles in `meten`, < 50 per soort. Kaart-route `GET …/activa-voorstel`: 8 × 200 sinds
  de deploy, 0 × 5xx; de kaart zelf is niet te tonen zolang geen module-document een regel op een `is_activa`-rekening draagt (Pilates Bloom: 0) —
  klikpunt Peter. **Regel uit de bijvangst: een lees-only reconciliatie schrijft óók geen probe-/cache-stand.** `cli_blok` liet `probe_register`
  `register_geprobeerd_op` op 75 administraties verplaatsen terwijl de run "niets vastgelegd" meldde; sinds 22-09 `probe_register(…, schrijf=False)`
  bij `verzamelaar is None` (alleen de GET, geen nieuwe rij), guards in `tests/activa/test_reconciliatie.py` + `test_instelling.py`. Voor élk blok dat
  een externe bron probet: de schrijvende kant zit achter dezelfde lees-only-vlag als de bevindingen. Meetlat: querybibliotheek `db-lezen activa-stand
  --administratie <naamdeel>` (rijen `is_activa_rekening` / `instelling` / `register_probe` / `koppeling`; `register_probe.tijdstip` blijft ná een
  lees-only run het sync-moment) — vervolg-opdracht `niet vóór: 2026-09-23 09:00`. Observatie: de sync duurde 79 min (jobtimeout 90) door de
  groepssaldi-stap (34 min, `Status`-enum, gefixt 22-09), niet door de activa-probe (seconden).

