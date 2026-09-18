# Regels — Btw: codes, defaults, verlegd, buitenland

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Btw-code uit de scan en het factuurtotaal, defaults uit de RLZ-grootboekrekening en de eigen historie, verlegd-herkenning (vermelding, kolomcode, onderaannemer), buitenland-signaal, verlegd-tarief deterministisch.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw-tarief buitenland** (casus Labo Derva: crediteur-datakwaliteit, onvoorwaardelijk oranje signaal + foutvertaling
  `vertaal_rlz_boekfout`) — zie BESLISSINGEN "VERZAMELRUN 31-08 AVOND" blok A.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw-code uit de scan** (`extractie/controle.py::leid_btw_af`; 0/onbepaalbaar/meerduidig = NOOIT invullen) — zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 26-08" punt 3.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw-default uit de RLZ-grootboekrekening (opdracht Peter 14-09, casus L.H.G. Holding "Kosten mobiele telefonie"; migratie 0142):** RLZ `Account.PreferentialTaxRate` (alleen mét `Ledgers?$expand=PreferentialTaxRate`, één leesroute voor probe én sync) → `grootboekrekening.standaard_taxrate_id` (Odoo: de enige inkoop-belasting in `account.account.tax_ids`); winnaarsvolgorde btw in `regel_prefill.py` nu mens > factuur berekend > geheugen > factuur verlegd > **grootboek-default (`btw_bron='grootboek'`, chip "standaard grootboek")** > administratie-default > leeg, A3-"bewust leeg" remt deze stap niet; grootboek-wissel in het controlescherm laat een lege/default-btw de rekening volgen, mens/factuur/geheugen winnen. STAP-0: het veld bestaat maar is op LHG 4404 én in vijf administraties overal null — zie BESLISSINGEN "BTW-DEFAULT UIT DE RLZ-GROOTBOEKREKENING (Peter 14-09)" + api-verkenning "Ledgers — standaard btw-code, STAP-0 14-09". **Vervolg (besluit Cowork/Peter 14-09 "geen invulwerk in RLZ"; migratie 0143): dezelfde default AFGELEID uit de eigen historie** — per administratie × rekening de tariefverdeling over de inkoopregels in `boeking_observatie` (24 maanden; ≥ 5 regels én één tarief ≥ 90 % → `historie_taxrate_id` + `_n`/`_aandeel`; `app/geheugen/grootboek_btw_historie.py`, nachtelijk in `sync-alles` + ná de eerste sync), winnaarsvolgorde stap 5b `btw_bron='grootboek_historie'` (ORANJE "meestal op deze rekening (n×)", ná de RLZ-default, vóór de administratie-default, bewust-leeg remt WÉL), zelfde grootboek-wissel, lees-only CLI `btw-default-rapport` in de nameting-allowlist — zie BESLISSINGEN "BTW-DEFAULT UIT HISTORIE PER GROOTBOEKREKENING (Cowork/Peter 14-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw uit het factuurtotaal + bankformulier volgt de rekening (bug-onderzoek 15-09; casus LHG bleek een BANK-direct-boeking van een KPN-incasso, geen document; geen migratie):** `controle.py::leid_btw_af_uit_totaal` = tweede bewijs op factuurniveau (regels excl. btw + één btw-totaal → restant-netto × tarief ≈ restant-btw, één cent speling per regel, regel-btw deterministisch berekend en cent-exact sluitend, `btw_bron='factuur'` groen, top-level `btw_factuur_totaal`; 0 %/geen match/meerduidig blijft leeg), één-regel-terugval neemt 'm over; bank `HandmatigBoekenForm`/`SplitsenForm` volgen de grootboek-default (RLZ > historie, één bron `document/grootboekBtwDefault.ts`, mens wint); historie-default 0143 telt óók GEBOEKTE niet-automatische bank-direct-boekingen; gouden-set-casus w — zie BESLISSINGEN "BTW UIT HET FACTUURTOTAAL + BANKFORMULIER VOLGT DE REKENING (bug-onderzoek 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Btw verlegd — herkenning op kolomcode en onderaannemer (Peter 15-09, casus Olieman 32948 "V" in de BTW-kolom; geen migratie):** verlegd = (a) vermelding (bestaand) óf (b) verlegd-kolomcode ("V"/"VL"/"verl.") op álle regels mét bedrag (AI leest alleen de kolomtekst, regel-key `bc`, sentinel; `controle.is_verlegd_kolomcode`) óf (c) verlegd-leverancier (eerdere boekingen op een `IsRelayed`-tarief in het leverancier-geheugen, anders KvK-SBI 41/42/43 via de bestaande lookup, nooit vanuit de testomgeving) — telkens ÉN factuur-btw 0 (`boekvoorstel.bepaal_verlegd_basis`); uitkomst = verlegd-tarief oranje `factuur_verlegd` mét basis in `btw_bron_detail`; 0 % zonder basis blijft leeg (vrijgesteld ≠ verlegd); gouden-set-casus z — zie BESLISSINGEN "BTW VERLEGD — HERKENNING OP KOLOMCODE EN ONDERAANNEMER (Peter 15-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verlegd-tarief deterministisch (blok 6; migratie 0123):** `voorkeurs_verlegd_taxrate_id` per administratie (Beheerder) → meest gebruikt in RLZ-historie → bestaand pad → default, mét herkomst-chip — zie BESLISSINGEN "VERLEGD-TARIEF DETERMINISTISCH KIEZEN".

<!-- toegevoegd 18-09-2026, opdracht "btw-bedrag-volgt-tarief-harde-check" -->
- **Btw-bedrag volgt het tarief + aftrek-uitgesloten rekeningen (BUA) + keuzelijst NL-eerst (Peter 18-09, screenshot Rituals
  Nieuwegein bon 88-186308, BLOW: "dit kan niet. nul % btw invullen is auto btw bedrag op nul zetten" en "representatie (fles wijn):
  daar mag je de btw niet in aftrek nemen, ook al staat die wel op de factuur"; migratie 0163 = `platform.grootboekrekening.
  btw_aftrek_uitgesloten` + `_op`; BESLISSINGEN "BTW-BEDRAG VOLGT HET TARIEF + BUA + KEUZELIJST NL-EERST (Peter 18-09)"; HERZIET
  "CONTROLESCHERM REGELRIJ-UI 25-08" (b) "factuur-btw leidend" — de grijze hint `regel-btw-berekend-hint` ("tarief geeft € … — factuur
  leidend") is VERVALLEN, guard `tests/keten/test_ae_rituals_btw_volgt_tarief.py::test_geen_grijze_hint_meer_in_de_frontend`):**
  (1) **Btw-bedrag volgt het tarief, altijd.** Tarief kiezen of wijzigen (mens, geheugen, prefill, check-actie) → btw-bedrag = netto ×
  percentage, cent-exact ROUND_HALF_UP (`regelsom.py::btw_uit_tarief`, frontend-spiegel `document/regelsom.ts`); het btw-veld blijft
  bewerkbaar voor cent-correcties binnen de marge (3); élke tariefwijziging overschrijft het btw-veld — óók een eerder handmatig
  ingevoerd bedrag (`BoekvoorstelPanel.wijzigRegel` tak `taxrateId`) — mét tijdlijnregel "Btw herrekend uit tarief — regel n: btw
  € a → € b" (server `boekvoorstel._btw_herrekend_notities`, sleutel `btw_herrekend`, alleen op een échte PUT, nooit op autosave).
  (2) **0 %/geen btw op een regel die uit de factuur wél btw draagt = btw in de kosten:** netto := netto + factuur-btw, btw := 0,00
  (`regelsom.zet_btw_in_kosten`), chip "btw in kosten (niet aftrekbaar)" (`btw_in_kosten` op regel-DTO/RegelState); terug naar een
  %-tarief splitst het bruto weer cent-exact (`regelsom.splits_bruto`: netto = bruto/(1+p), btw = rest — 21 → 0 → 21 geeft de
  oorspronkelijke splitsing terug). De aansluiting op het factuurtotaal blijft daardoor per definitie kloppen. Verlegd/vrijgesteld/
  buitenland-tarief = btw 0, netto ongewijzigd (daar staat géén btw op de factuur). (3) **Harde check "Btw-bedrag past bij tarief"**
  (`checks.py::check_btw_past_bij_tarief`, lokaal — geen RLZ-call, dus óók in de storings-tak en op het autoboek-pad: rood = niet boeken)
  direct ná "Regeltelling vs totaal": per regel |btw − netto × percentage| ≤ marge, marge = 1 cent × aantal samengevoegde factuurregels
  van die regel (min 1, max 5 cent; `regelsom.marge_voor`; `boekvoorstel._samengevoegd_n` = het aantal gelezen factuurregels als het
  scherm de ene samengevoegde regel toont, anders 1); verlegd/vrijgesteld/buitenland (`TariefInfo.verwacht_nul`) verwacht 0,00; een regel
  zonder tarief/netto/btw telt niet, een tarief zonder percentage in de cache = "niet toetsbaar" (groen mét tekst). Rood draagt TWEE
  acties (`CheckActie`, DTO `acties`): **"Btw in kosten (0 %)"** (regel 2; `taxrate_id` = het huidige tarief als dat al een NL-0 %-tarief
  is, anders de RLZ-favoriet onder de NL-0 %-tarieven — nooit verlegd/vrijgesteld/buitenland — anders de eerste op naam;
  `checks.nul_tarief_voor`) en **"Zet N %"** (deterministisch het ene NL-percentage dat de factuur-btw binnen de marge verklaart,
  `regelsom.verklarende_percentages`; favoriet wint bij meerdere tarieven met dat percentage; géén of meerdere kandidaten → alleen de
  eerste actie). De frontend voert de actie uit op de regelstate en slaat op; de server vertrouwt nooit de knop. (4) **Aftrek-
  uitgesloten grootboekrekeningen (BUA):** kenmerk `btw_aftrek_uitgesloten` per administratie × grootboekrekening (kolom op de bestaande
  sync-tabel, zelfde plek als `standaard_taxrate_id` 0142 en de historie-default 0143 — RLS `grootboekrekening_scope` dekt 'm, de
  Ledgers-sync schrijft alleen zijn eigen kolommen dus het kenmerk overleeft élke sync); Beheerder-blok "Btw niet aftrekbaar" op
  Instellingen › administratie › tab Boeken & AI (anker `btw-aftrek`, registry-entry; `GET/PUT /administraties/{id}/
  btw-aftrek-uitgesloten`, `app/beheer/btw_aftrek.py`, `require_beheerder`, audit `btw_aftrek_uitgesloten_gewijzigd` oud→nieuw mét
  codes, onbekende rekening 422) mét een deterministisch VOORSTEL (`is_voorstel`: 4xxx-kostenrekening (AccountType 2) waarvan de naam
  representatie / relatiegeschenk / personeelsvoorzien* / kantine bevat én de RLZ-default 0 %/geen btw is of ontbreekt) als vinkjes
  "voorstel" + knop "Voorstel overnemen (N)" — de Beheerder bevestigt, nooit stil aangezet. Op zo'n rekening wint in de prefill de stap
  **`grootboek_aftrek_uitgesloten` > factuur berekend** (`regel_prefill._met_aftrek_uitgesloten`, vóór de leverancier-geheugen-stap;
  tarief = het NL-0 %-tarief van de administratie via `regel_prefill.nul_taxrate_voor` (RLZ-default van de rekening als dat 0 % is,
  anders favoriet, anders eerste op naam; geen 0 %-tarief in de cache = tarief leeg mét chip — de mens kiest, de check blijft de poort),
  netto + btw in de kosten, `btw_bron='grootboek_aftrek_uitgesloten'`, chip "aftrek uitgesloten (4510)", `prefill_herkomst.btw`;
  snapshot-herstel via `btw_in_kosten` in de regel-snapshot). Zonder het kenmerk blijft de bestaande winnaarsvolgorde gelden: mens >
  **aftrek uitgesloten** > factuur berekend > factuur-regelkolom > geheugen > factuur verlegd > grootboek-default > grootboek-historie >
  administratie-default > leeg. (5) **Historie:** lees-only CLI `btw-tarief-afwijking-rapport [--sinds 2026-08-25] [--administratie]
  [--marge-ct 1]` (`app/documenten/btw_tarief_cli.py`, nameting-allowlist) = geboekte inkoopdocumenten met een regel |btw − netto × p| >
  marge; niets wordt in RLZ gecorrigeerd — Peter beslist per geval (storno 19 → herboeken, achter de aangiftepoort). Lezing 18-09 via de
  leesreplica (RLS: per administratie): sinds 25-08 alleen BLOW, twee documenten (rapport). Herkomst van de 0 % op 88-186308: geen
  prefill-snapshot, geen geheugen vóór 18-09, 4510 zonder RLZ-/historie-default → de mens koos 0 % en de frontend herrekende niet
  (`btwHandmatig` op een geladen regel mét btw) — precies de bug van regel 1. **DEEL B — keuzelijst NL-eerst** (Peter: "ik zie
  telkens alle nul % tarieven, ook alle EU-regels. Als leverancier NLD adres heeft dan die hele rits graag niet tonen"; feit: het land van
  de crediteur is via de RLZ-API NIET leesbaar, probe 31-08): **land van de leverancier** = eerste treffer btw-nummer crediteur-kenmerk →
  btw-nummer factuur → IBAN-landcode (factuur-IBAN, anders de vertrouwde IBAN-set als die één land geeft) → onbekend
  (`app/documenten/btw_keuzelijst.py::bepaal_leverancier_land`; het factuuradres-land is bewust NIET gebouwd — het inkoopschema kent geen
  adresveld, een nieuw AI-veld is een schema-uitbreiding, beslispunt), als `leverancier_land` + `leverancier_land_bron` op de
  boekvoorstel-respons (chip in de crediteur-kaart "NL · uit btw-nummer factuur"). **Keuzelijst**: land NL → alleen NL-tarieven zichtbaar,
  buitenland (naam-prefix ≠ NL, `is_buitenland_tarief`) ingeklapt onder één regel onderaan **"Buitenland-tarieven tonen (N)"**
  (`SearchableCombobox.ingeklapteGroep`; klik/Enter = uitvouwen voor déze combobox; zoeken doorzoekt altijd álles; pijltjes slaan de
  ingeklapte groep over tot uitgevouwen); land ≠ NL → alles zichtbaar mét de tarieven van dát land/EU bovenaan; onbekend → alles (nooit
  iets wegnemen op een gok); een al gekozen buitenland-tarief blijft altijd zichtbaar/geselecteerd. **Volgorde**: tarieven die deze
  administratie de laatste 12 maanden gebruikte bovenaan op frequentie (`GET …/btw-codes` levert `gebruik_12m` uit `boeking_observatie`,
  één statement, plus de vlaggen `verlegd`/`vrijgesteld`/`buitenland`/`favoriet`), de rest alfabetisch; nul-tarieven blijven
  onderscheidbaar op RLZ-naam. Eén hook `document/useTaxrateOptiesGefilterd.ts` op álle tarief-comboboxen (inkoop mét land; verkoop-
  review, omzet, doorbelasting, bank zonder land = alleen de sortering); het prefill-/autoboek-pad verandert NIET;
  `check_buitenland_tarief_crediteurkaart` ongewijzigd. Guards: `tests/documenten/test_regelsom_btw_tarief.py`,
  `tests/beheer/test_btw_aftrek.py`, gouden-set-casus **ae** (`tests/keten/test_ae_rituals_btw_volgt_tarief.py`, fixture
  `ae_rituals_bua_0pct`), vitest `regelsomBtwTarief`, `useTaxrateOptiesGefilterd`, `SearchableCombobox.inklap`, `BtwAftrekUitgeslotenBlok`,
  `BoekvoorstelPanel.test` (twee 25-08-tests herschreven naar de 18-09-regel).

<!-- toegevoegd 18-09-2026, opdracht "BUG-samenvoegen-toont-gesplitste-regels-en-geheugen-overschrijft-factuurbtw" -->
- **Btw-code uit de btw-KOLOM van de factuurregel (BUG 18-09, casus Zilver Horeca Fac-25-022711; geen migratie; BESLISSINGEN
  "SAMENVOEGEN-BUG, REGEL-BTW UIT DE FACTUURKOLOM EN UPLOAD 409 'AL AANWEZIG' (Peter 18-09)"):** de winnaarsvolgorde
  (`regel_prefill.py`) kent op REGELNIVEAU de bron `factuur_regel`: draagt de factuurregel een percentage in de btw-kolom ("9%",
  "0 %", "21,0%" — `controle.parse_btw_kolom_percentage`, kale cijfers/kolomcodes tellen niet) dat exact op één gesynct tarief past
  (`leid_btw_af_uit_kolom`; favoriet wint bij twee codes met hetzelfde percentage; verlegd/vrijgesteld/gemengd nooit), dan dát
  tarief mét regel-btw = netto × p — als tweede factuurbewijs ná "netto × tarief ≈ btw" (regel) en vóór het factuur-totaal-bewijs,
  het geheugen en de defaults. **Een kolom 0 % is een basis** (het 0 %-tarief van de administratie, "NL, Nul tarief"), anders dan
  een 0 %-bedrag zonder context (blijft leeg, vrijgesteld ≠ verlegd ≠ nul). Chip "factuur 0 %" (groen), `btw_afleiding_basis
  ='kolom'`, `btw_kolom_percentage` op de regel. De harde checks blijven de poort; de check "Btw-bedrag past bij tarief"
  (opdracht 18-09 btw-volgt-tarief) toetst óók deze regels.

<!-- DOEL: docs/regels/intake-extractie.md — de alinea "Bulk-upload — meerdere bestanden tegelijk" eindigt met "Open beslispunt:
     server-side sha256-kortsluiting (409 `al_aanwezig` …) — apart besluit, raakt de gouden set." → daaronder toevoegen -->

<!-- toegevoegd 18-09-2026, opdracht "BUG-samenvoegen-…" (extra besluit Peter 18-09) -->
- **Byte-identieke directe upload = 409 "al aanwezig" mét verwijzing, geen nieuw document (besluit Peter 18-09 — sluit het open
  beslispunt van de bulk-upload; geen migratie; BESLISSINGEN "SAMENVOEGEN-BUG, REGEL-BTW UIT DE FACTUURKOLOM EN UPLOAD 409 'AL
  AANWEZIG' (Peter 18-09)"):** op de DIRECTE upload-routes (`POST /administraties/{id}/documenten`, `POST /intake/bestand`; bron
  `upload`, geen intake-bericht, geen splitsing) weigert `documenten/service.py::upload_document` bytes die in dezelfde
  administratie al als document bestaan — uitsluitend binnen de POORT van die twee routes (`service.directe_upload_poort()`, contextvar; `upload_document` zelf blijft buiten de poort de generieke registratie mét mogelijk-duplicaat-vlag voor intake, splitsing, verzamelbak en CLI's) — (`DocumentAlAanwezig` → HTTP 409, detail `{code: "al_aanwezig", bestaand_document_id,
  bestaand_administratie_id, bestaand_status, bestaand_bestandsnaam, bestaand_referentie, melding}`), audit
  `upload_geweigerd_al_aanwezig` (eigen transactie). Telt als aanwezig: élk exemplaar behalve een door een mens VERWIJDERD
  exemplaar (bewust weggedaan → opnieuw aanbieden mag; het nieuwe document draagt dan de bestaande mogelijk-duplicaat-vlag);
  samengevoegd/afgevoerd_duplicaat/afgewezen/geboekt/werkvoorraad tellen wél — de verwijzing wijst bij voorkeur naar het échte
  werkstuk (niet naar een huls). De mail-/IMAP-intake (bron email, intake_bericht_id), splitsing en verzamelbak-toewijzing volgen
  onverkort de bundel-/nabundelmotor en de duplicaatregel (daar kiest geen mens per bestand; gouden-set-casus a ongewijzigd). De
  upload-wachtrij (`werkvoorraad/uploadWachtrij.ts::classificeerFout`) vertaalt het 409-detail naar status `al_aanwezig` mét
  leesbare melding ("al aanwezig als "…" (te controleren, Fac-…) — niet opnieuw aangemaakt") en de link "→ bestaand document"
  (`/documenten/<administratie>/<id>`) in het batchblok. Guards: `tests/documenten/test_upload_al_aanwezig.py`,
  `test_service.py`/`test_router.py` (aangepast), vitest `uploadWachtrij.test.ts`.

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Btw-tarief buitenland (CLAUDE.md `ed6d176` r. 354–360)

- **Btw-tarief buitenland (verzamelrun 31-08 blok A, casus Labo Derva):** RLZ weigert de
  boekactie (17) van een EU-/buitenland-tarief met 400 "ongeldig belastingtarief" zolang de
  crediteurkaart in RLZ geen land/btw-nummer draagt — crediteur-datakwaliteit, geen tarief-fout;
  land/btw-nummer zijn via de API níét leesbaar (api-verkenning "EU-tarieven op
  PurchaseInvoice-Actions"). Daarom: onvoorwaardelijk oranje signaal "Btw-tarief buitenland"
  bij élk buitenland-tarief (naam-prefix ≠ NL) + foutvertaling `vertaal_rlz_boekfout` mét
  handelingsperspectief op controlescherm/boek_fout/herstel-CLI.

### Domeinbeslissingen — Btw-code uit de scan (CLAUDE.md `ed6d176` r. 361–366)

- **Btw-code uit de scan (feedbackronde 26-08 punt 3):** ná AI-extractie leidt CODE per regel het
  tarief af (`extractie/controle.py::leid_btw_af`: netto × tarief ≈ btw ±1 ct tegen de gesyncte
  TaxRates; gelijk percentage → RLZ-favoriet `IsFavorite` wint; verlegd/vrijgesteld/gemengd doen
  niet mee) → vooraf ingevuld mét chip "uit factuur (21%)"; 0/onbepaalbaar/meerduidig = NOOIT
  invullen (0% is ambigu: geheugen per leverancier wint, anders mens); "btw verlegd"-vermelding
  = alleen een hint-chip. Harde checks blijven de poort.
