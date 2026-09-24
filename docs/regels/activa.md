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

<!-- toegevoegd 23-09-2026, opdracht "nameting-activa-lees-only-probe-na-deploy" (poging 2) -->
- **Gemeten 23-09 — lees-only reconciliatie schrijft de register-probe niet meer: WERKT IN PRODUCTIE JA; activa-kaart gebruikt, activum in RLZ NEE
  (23-09; BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)" alinea "Gemeten 23-09"; rapport `docs/rapporten/2026-09-23-nameting-activa-lees-only-probe.md`):**
  ná de lees-only executie `5sqzm` (17:25–17:47 UTC op `1ca9471`, blok `activa` 75 getoetst) staat `activa_instelling.register_geprobeerd_op` bij 75/75
  RLZ-administraties nog op het sync-moment (05:00:43–05:03:00 UTC; Pilates Bloom 05:01:45.738542, Universal Steigerbouw 403-pad 05:02:43.561762 — bot
  `3cab2fe`/`8169f02` vóór, `b6a93be`/`f87b1c9` ná), 0 in het meetvenster. **Eerste échte gebruik van de kaart (BLOw B.V, 23619 + 06052 op 0107):** kaart,
  "Aanmaken ná boeken" (`activum_gepland`, herkomst mens) en de boeking werken; `maak_aan_in_rlz` weigerde daarna beide keren op "geen
  afschrijvingsrekening" (combobox optioneel overgeslagen, `afschrijving_ledgers` leeg) → `activum_aanmaken_mislukt` in `meten`, geen `PUT FixedAssets`,
  register BLOw leeg — een mens koos bewust "aanmaken" en niemand zag dat het niet gebeurde (principe 4 + 7 (6)). Regels die hieruit volgen (BUG-opdracht
  `2026-09-24-BUG-activa-kaart-aanmaken-mislukt-geen-afschrijvingsrekening-blow.md`, nog te bouwen): (1) de afschrijvingsrekening wordt deterministisch
  voorgevuld uit de conventie code + 1 mét naam "Afschrijving …" (BLOw 0101→0102 … 0115→0116; precies één treffer, anders leeg); (2) zonder bekende
  afschrijvingsrekening geen `gepland` (422, combobox verplicht); (3) `activum_aanmaken_mislukt` ná een mens-klik is een actie-bevinding, niet `meten`.
  Bijvangst: `is_activa` staat bij BLOw op 4 van 8 0xxx-balansrekeningen (0103/0105/0109/0115 dragen in RLZ geen `IsFixedAssetAccount`) — een factuur op
  0109 Bedrijfsinventaris krijgt géén kaart; klant-instelling in RLZ, geen module-fout. Klikpunt Peter blijft: RLZ-recht "Vaste activa" op de logins van
  Universal Steigerbouw en Rubicon Investments (register 2 × niet leesbaar).

<!-- toegevoegd 23-09-2026 avond, opdracht "2026-09-24-BUG-activa-kaart-aanmaken-mislukt-geen-afschrijvingsrekening-blow" -->
- **BUG 24-09 GEBOUWD (23-09 avond; geen migratie; BESLISSINGEN "ACTIVA / MVA — FASE 1 GEBOUWD (Peter 21-09)" alinea "BUG 24-09";
  rapport `docs/rapporten/2026-09-23-activa-kaart-afschrijvingsrekening-conventie-422-actie-stap0.md`) — vier regels:**
  (1) **Afschrijvingsrekening deterministisch voorgevuld** (`app/activa/afschrijving.py`, winnaarsvolgorde in `voorstel.bepaal_afschrijving`):
  vastgelegd op de koppeling > instelling per categorie > CONVENTIE = de rekening van dezelfde administratie mét code = balansrekening-code + 1
  binnen dezelfde 0xxx-reeks (zelfde lengte, blijft met '0' beginnen: 0107→0108, 0001→0002, 01100→01101, 0999→niets) ÉN naam die begint met
  "Afschrijving", alleen niet-verdwenen, niet-totaalrekeningen soort 3; precies één treffer = voorgevuld mét herkomst `conventie` (chip
  "voorgevuld: conventie (code + 1)" op de kaart, `KandidaatDto.afschrijving_bron` koppeling|instelling|conventie|null), nul of meer = leeg.
  Nooit AI, nooit naam-raden (Peter 23-09: "kunnen wij de afschrijvingsregel ook niet automatiseren obv de gekozen activa-regel?" — ja, zo).
  Guards `tests/activa/test_afschrijving.py` (BLOw-schema acht paren + Rubicon 01100… zonder conventie + dubbel/verdwenen/totaal/kosten/andere
  administratie), gouden-set-casus ag (0107 → 0108 zonder instelling, POST zonder body). (2) **Nooit meer "gepland zonder
  afschrijvingsrekening":** `plan_of_maak_aan` weigert mét `AfschrijvingsrekeningVereist` (→ 422, tekst letterlijk "Kies een afschrijvingsrekening
  — RLZ vereist er één per activum", route-test) als mens-keuze én voorvulling leeg zijn; de kaart toont de combobox dan verplicht (`vereist`
  + `fout` = rode rand, `role=alert`-tekst) en de knop staat uit (zelfde patroon als `registerDicht`); "Niet activeren…" blijft aan. Het
  vangnet in `maak_aan_in_rlz` blijft en kent nu óók de conventie (koppelingen van vóór de fix mét `afschrijving_ledger_id` NULL — de BLOw-stand
  — krijgen ná boeken alsnog 0108). (3) **`mislukt` ná een MENS-klik = actie, niet meten:** nieuwe bevindingssoort
  `activum_aanmaken_mislukt_mens` (blok activa, `sinds` 24-09, code-default `actie` via `SoortDefinitie.direct_actie_reden` — derde uitzondering
  ná `intussen_extern_geboekt` en `intake_postvak_verschil`, guard pint de lijst; explosie-rem blijft) voor koppelingen `mislukt` mét herkomst
  `mens`; `herkomst automatisch` blijft `activum_aanmaken_mislukt` in `meten`. Handeling op de rij: `OpnieuwAanmakenActie` (Inzicht ›
  Reconciliatie, blok "Activa") = de bestaande route `POST …/activa-voorstel/{regel}/aanmaken` zonder body (server neemt de voorvulling);
  422 = de zin van de server op de rij + deeplink naar het controlescherm (`_doel_pad` kent nu blok activa). Detail draagt
  `herkomst`/`koppeling_id`/`document_id`/`regel_volgnummer`. Verwacht ná deploy: de 2 BLOw-rijen van 23-09 verschijnen in de run van 24-09
  06:30 als `activum_aanmaken_mislukt_mens` in `actie` (actiemail), de oude `activum_aanmaken_mislukt`-rijen sluiten mét
  `reconciliatie_auto_gesloten`. (4) **`PUT FixedAssets/{client-guid}` → 404 `NotFound_FixedAsset` (Peter 23-09, BLOw MK Illumination
  MK22507863):** `maak_aan_in_rlz` vangt een 404 op de PUT en zet de koppeling `mislukt` mét de nette reden `REDEN_AANMAAKROUTE_ONBEKEND`
  ("aanmaken in Reeleezee nog niet mogelijk — wordt onderzocht …"; ruwe RlzApiError in het audit `rlz_body.rlz_fout`); FakeBoekClient
  `faal_op="fixed_asset_put_404"`. **STAP-0 deel 1 (lees-only, api-verkenning "FixedAssets — aanmaakroute STAP-0"):** de publieke Help kent
  ALLEEN `PUT FixedAssets/{id}` ("Create or Update"), geen collectie-PUT/POST en geen aanmaak-ActionKind (112 = DepreciateFixedAsset); het échte
  Pilates-Bloom-activum (record-vorm) heeft **`DepreciationAccount` = 4706 Afschrijvingskosten (KOSTENrekening, AccountType 2)**, niet een
  0xxx-rekening, en begint mét een `FixedAssetMutation` Type 6 Manual ter grootte van de aanschaf op de aanschafdatum (afschrijvingsposten
  `EventID` 61). **Beslispunt/STAP-0 deel 2 = klikpunt Peter** (testadministratie dearchiveren, drie PUT-varianten V0/V1/V2 + V3 met een
  4xxx-kostenrekening — recept in api-verkenning); pas dan wordt `maak_aan_in_rlz` aangepast. De conventie 0xxx is exact zoals opgedragen
  gebouwd en niet geraden; of RLZ een balansrekening als `DepreciationAccount` accepteert is open. **Herstel BLOw (23619 € 935,00 /
  06052 € 680,00 / MK22507863 € 1.078,10) = klikpunt Peter ná deploy én ná STAP-0 deel 2** — vóór de aanmaakroute bewezen is geeft
  "Opnieuw aanmaken" opnieuw de nette 404-reden. Meetlat: dispatch-onderdeel `activa-kaart` (request-log POST aanmaken 200/422/5xx,
  job-log mislukt-regels, `db-lezen activa-stand`/`reconciliatie-bevindingen` BLOw + Pilates, `rlz-lezen FixedAssets` BLOw); vervolg-opdracht
  `opdrachten/inbox/2026-09-24-nameting-activa-kaart-na-deploy.md` (`niet vóór: 2026-09-24 07:15`). Werkt in productie: niet gemeten.

<!-- toegevoegd 24-09-2026, opdracht "bundelrun-zeven-punten" blok 6 -->
- **Afschrijvingsrekening = KOSTENrekening mét dezelfde omschrijving (besluit Peter 24-09 07:5x "eens moet kostenrekening van zelfde
  omschrijving zijn (kantoorinventaris, ICT etc)"; geen migratie; HERZIET BUG 24-09 regel (1) "conventie code + 1 op 0xxx"; BESLISSINGEN
  "ACTIVA — AFSCHRIJVINGSREKENING = KOSTENREKENING MÉT DEZELFDE OMSCHRIJVING (Peter 24-09)"):** `DepreciationAccount` is een 4xxx-KOSTENrekening
  (STAP-0 deel 1 23-09: Pilates Bloom 4706 Afschrijvingskosten, AccountType 2) — nooit een 0xxx-balansrekening; de balanskant blijft
  `BalanceAccount` (de activarekening zelf). Conventie (`app/activa/afschrijving.py::conventie_rekening`): de niet-verdwenen, niet-totaal
  4xxx-rekening soort 2 van dezelfde administratie waarvan de genormaliseerde omschrijving (lowercase, diakrieten weg, niet-alfanumeriek →
  spatie) ná het voorvoegsel "Afschrijving"/"Afschrijvingen"/"Afschrijvingskosten" (+ optioneel "op"/"van"; ook de omgekeerde vorm "‹naam›
  afschrijving") gelijk is aan de genormaliseerde omschrijving van de activarekening — 0107 Kantoorinventaris → "Afschrijving
  kantoorinventaris", 0110 ICT → "Afschrijvingskosten ICT". Precies één treffer = voorgevuld mét herkomst `conventie` (chip "voorgevuld:
  conventie (kostenrekening zelfde omschrijving)"); nul of meerdere treffers, of een kale naam zonder kern ("Afschrijvingskosten") = leeg →
  combobox verplicht + 422 (regel (2) van BUG 24-09 ongewijzigd). Winnaarsvolgorde koppeling > instelling per categorie > conventie
  ongewijzigd; de combobox (`instelling.afschrijving_ledger_opties`) biedt nu de 4xxx-kostenrekeningen aan ("afschrijving" in de naam
  eerst, dan op code); het vangnet in `maak_aan_in_rlz` volgt dezelfde conventie. Nooit AI, nooit fuzzy. Guards `tests/activa/
  test_afschrijving.py` (RGS-schema 0xxx + 4700-reeks, naamvarianten, oude code + 1-conventie = None), conftest 4708 soort 2,
  gouden-set-casus ag (`DepreciationAccount` = 4708). STAP-0 deel 2 (schrijvend, testadministratie `faae29c5` ná dearchiveren) en herstel
  BLOw 23619 € 935,00 / 06052 € 680,00 / MK22507863 € 1.078,10 (23-09) blijven klikpunten Peter (recept in het rapport); meetlat
  dispatch-onderdeel `activa-conventie`. Werkt in productie: niet gemeten.
