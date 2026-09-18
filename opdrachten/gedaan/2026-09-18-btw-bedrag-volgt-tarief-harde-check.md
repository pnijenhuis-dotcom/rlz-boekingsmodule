uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-btw-volgt-tarief.md

Domeinen: btw, werkvoorraad-controlescherm, autoboeken-ai, kantoor-frontend

# OPDRACHT 18-09 — Btw-bedrag volgt het tarief; 0 % op een factuur mét btw = btw in de kosten; afwijking = HARDE check
# (Peter 18-09, screenshot Rituals-bon 88-186308)

**Peter 18-09 (letterlijk):** "dit kan niet. nul % btw invullen is auto btw bedrag op nul zetten." En op mijn eerste lezing ("zet 21 %"):
"nee want in dit geval is dit representatie (fles wijn) en daar mag je de btw niet in aftrek nemen, ook al staat die wel op de factuur."

**Wat het scherm toonde (Rituals Nieuwegein, bon 88-186308, 22-12-2025, totaal € 116,60 = 96,36 + 21 % 20,24):** één samengevoegde regel
4510 Representatiekosten, btw-code **"0% · NL, Nul"**, netto **96,36**, btw-bedrag **20,24**, grijze hint "tarief geeft € … — factuur
leidend", aansluiting groen (96,36 + 20,24 = 116,60), **Controles 11/11 groen**, Boeken actief. Onmogelijke combinatie: € 20,24 btw op een
0 %-code gaat als voorbelasting de aangifte in terwijl de bedoeling juist is dat er níets in aftrek komt.

**Gewenste boeking (Peter):** 4510 Representatiekosten, btw-code 0 % / geen btw, **netto 116,60, btw 0,00** — de niet-aftrekbare btw
zit in de kosten. Dat is de bestaande kantoorpraktijk voor aftrek-uitgesloten kosten (representatie, relatiegeschenken e.d.).

## Oorzaak (Cowork, code 18-09)
1. Besluit 25-08 "CONTROLESCHERM REGELRIJ-UI" (b): "factuur-btw leidend" — tarief × netto ≠ btw-bedrag werd een **hint** (`regel-btw-
   berekend-hint`) en géén check. Er is dus geen enkele blokkade op tarief ↔ btw-bedrag; alleen netto + btw = totaal wordt getoetst.
2. Tarief-veld en btw-veld leven los van elkaar: een tariefkeuze (mens of prefill) herrekent netto/btw niet. De prefill zette hier
   (waarschijnlijk) de grootboek-default 0 % van 4510 — dat is voor deze rekening óók wat Peter wil — maar liet netto 96,36 / btw 20,24
   uit de bon staan. **Waar de 0 % precies vandaan komt staat in de tijdlijn/herkomst-chip van dit document: uitlezen, niet aannemen.**
3. De winnaarsvolgorde (`regel_prefill.py`: mens > factuur berekend > geheugen > … > grootboek-default) kent het begrip "aftrek uitgesloten"
   niet: op een BUA-rekening zou "factuur berekend" (21 %) juist het verkeerde antwoord geven.

## Regels (bindend; volledige tekst naar `docs/regels/btw.md`)
1. **Btw-bedrag volgt het tarief, altijd.** Tarief kiezen of wijzigen (mens, geheugen, prefill) → btw-bedrag = netto × percentage
   (`regelsom.py`, één functie voor frontend én backend). Het btw-veld blijft bewerkbaar voor cent-correcties binnen de marge (punt 3);
   elke tariefwijziging overschrijft het, mét tijdlijnregel "btw herrekend uit tarief".
2. **0 % / geen btw op een regel die uit de factuur wél btw draagt = btw in de kosten:** netto := netto + factuur-btw, btw := 0,00, chip
   op de regel "btw in kosten (niet aftrekbaar)". Terug naar 21 % → splitst weer (netto = bruto / 1,21, btw = rest; cent-fix zoals nu).
   De aansluiting op het factuurtotaal blijft daardoor per definitie kloppen. Verlegd blijft verlegd (btw 0, netto ongewijzigd — daar
   staat immers géén btw op de factuur).
3. **Harde check "Btw-bedrag past bij tarief"** (nieuw, blokkerend, `checks.py` + spiegel frontend): |btw − netto × percentage| ≤ marge,
   marge = 1 cent × aantal samengevoegde factuurregels van die regel (min 1, max 5 cent). Daarbuiten ROOD mét twee acties: **"Btw in
   kosten (0 %)"** (regel 2) of **"Zet N %"** (deterministisch het RLZ-tarief dat de factuur-btw binnen de marge verklaart; géén of
   meerdere kandidaten → alleen de eerste actie). Vervangt de grijze hint volledig. Autoboek-pad: zelfde check, rood = niet boeken.
4. **Aftrek-uitgesloten grootboekrekeningen (BUA):** nieuw kenmerk per administratie × grootboek `btw_aftrek_uitgesloten` (Beheer ›
   Grootboek-instellingen of op de administratie-pagina; default uit RLZ-ledger-default-tarief 0 %/geen btw op 4xxx-kostenrekeningen
   met naam representatie/relatiegeschenk/personeelsvoorzien*/kantine — voorstel als lijst, Beheerder bevestigt; nooit stil
   aangezet). Op zo'n rekening wint in de prefill **grootboek-aftrek-uitgesloten > factuur berekend**: tarief 0 %/geen btw én regel 2
   (btw in kosten). Herkomst-chip "aftrek uitgesloten (4510)". Zonder het kenmerk blijft de bestaande volgorde gelden.
5. **Historie**: lees-only query over geboekte documenten sinds 25-08 (alle administraties) met tarief × netto ≠ btw buiten de marge →
   lijst in het rapport (document, administratie, boekstuk, tarief, netto, btw, verwacht). Niets corrigeren in RLZ; Peter beslist per
   geval (storno 19 → herboeken, achter de aangiftepoort).

## Bouw
`regelsom.py`: `btw_uit_tarief`, `btw_past_bij_tarief`, `zet_btw_in_kosten` / `splits_bruto`; backend-check in `voer_harde_checks_uit`
(lokaal, geen RLZ-call); `regel_prefill.py`: stap aftrek-uitgesloten vóór factuur-berekend; migratie (kenmerk-tabel of kolom op de
grootboek-cache, RLS zoals de sync-tabellen); frontend `BoekvoorstelPanel`: tarief-change-handler herrekent, chip, check-rij, twee acties;
Beheer-scherm voor het kenmerk (lijst mét voorstel-vinkjes). Tests: 0 % + 20,24 = rood; actie "btw in kosten" → 116,60 / 0,00 groen;
21 % + 20,24 groen; 21 % + 20,21 op 6 regels groen (marge 5 ct); 21 % + 20,10 rood; 21 % → 0 % → 21 % geeft de oorspronkelijke
splitsing terug (cent-exact); verlegd blijft netto ongewijzigd; prefill Rituals op 4510 mét kenmerk → 0 % + 116,60/0,00; zonder kenmerk
→ 21 % + 96,36/20,24. BESLISSINGEN "REGELRIJ-UI 25-08 (b)" status HERZIEN mét verwijzing. WAT_IS_NIEUW. Guard: hint verwijderd.

## Afronding
Migratie-routine volledig; gouden set groen; rapport `docs/rapporten/2026-09-18-btw-volgt-tarief.md` + INDEX + Gelezen regels + de
historie-lijst + de herkomst van de 0 % op 88-186308 + de voorgestelde BUA-rekeningenlijst per administratie (Peter bevestigt in Beheer);
nameting ná deploy op dit document: 0 % → check rood → "Btw in kosten" → 116,60 / 0,00 groen — "werkt in productie: ja/nee". Één regel
voor Peter.

---

# DEEL B (zelfde run, zelfde component) — Btw-keuzelijst: buitenland-tarieven inklappen bij een NL-leverancier (Peter 18-09)

**Peter 18-09 (letterlijk):** "ik zie telkens alle nul % tarieven, ook alle EU-regels. Als leverancier NLD adres heeft dan die hele rits
graag niet tonen."

## Feiten (Cowork, code + api-verkenning 18-09)
- De btw-combobox (`useTaxrateOpties`, `SearchableCombobox` in `BoekvoorstelPanel`) toont álle tarieven van de `taxrate_cache` van de
  administratie: NL hoog/laag/nul/vrijgesteld/verlegd én "EU, …", "Ex EU, …", "EU + Ex-EU, …", landcode-varianten — vaak 15–25 regels
  waarvan er in de praktijk vijf gebruikt worden.
- **Het land van de crediteur is via de RLZ-API NIET leesbaar** (probe 31-08, api-verkenning "Land en btw-nummer van een Vendor"):
  `Vendors/{id}` en `/Addresses` dragen geen land. "NLD-adres uit RLZ" bestaat dus niet als bron. Wél deterministisch beschikbaar:
  (1) btw-nummer van de crediteur in `crediteur_kenmerk.btw_nummer` (landprefix NL/BE/DE…), (2) btw-nummer op de factuur (extractie),
  (3) IBAN-landcode van de factuur/vertrouwde IBAN-set (`leverancier_iban`), (4) factuuradres uit de extractie (AI, lagere zekerheid).
- Buitenland-tarief herkennen = naam-prefix vóór de eerste komma ≠ NL (`checks.is_buitenland_tarief`, bestaand).

## Regels
1. **Land van de leverancier** = eerste treffer in deze volgorde: btw-nummer crediteur-kenmerk → btw-nummer factuur → IBAN-landcode →
   factuuradres-land (extractie) → onbekend. Één functie `leverancier_land(document, crediteur)` server-side, meegegeven in de
   boekvoorstel-respons als `leverancier_land` + `leverancier_land_bron` (chip in de kop: "NL · uit btw-nummer").
2. **Keuzelijst**: land = NL → alleen NL-tarieven zichtbaar; de buitenland-tarieven staan ingeklapt onder één regel onderaan
   **"Buitenland-tarieven tonen (N)"** (klik = uitvouwen voor deze regel; zoeken in de combobox zoekt altijd over álles, ook ingeklapt).
   Land ≠ NL → alles zichtbaar, buitenland-tarieven van dát land/EU bovenaan. Land onbekend → alles zichtbaar (nooit iets wegnemen op een
   gok). Een al gekozen buitenland-tarief blijft altijd zichtbaar/geselecteerd, ook bij NL (geen stille wijziging van een bestaande keuze).
3. **Volgorde binnen de lijst**: tarieven die deze administratie de laatste 12 maanden gebruikt heeft (uit het boekingsgeheugen/
   JournalEntryLines-historie) bovenaan, op gebruiksfrequentie; de rest alfabetisch. Dat haalt de vijf werk-tarieven naar boven, ongeacht
   land. Nul-tarieven blijven onderscheidbaar op RLZ-naam (nul / vrijgesteld / verlegd) — geen samenvoegen.
4. Zelfde lijstgedrag op álle plekken met de tarief-combobox (inkoop, verkoop-review, omzet, doorbelasting): één hook
   `useTaxrateOptiesGefilterd(landInfo)`; geen tweede implementatie. Het autoboek-/prefill-pad verandert hier NIET (dit is weergave).
   Buitenland-signaal (`check_buitenland_tarief_crediteurkaart`) blijft ongewijzigd.

## Bouw & tests
Backend: `leverancier_land` + bron in `BoekvoorstelResponse` (Pydantic, geen migratie — afgeleid veld); tests op de volgorde (kenmerk wint
van factuur, IBAN als fallback, onbekend bij niets). Frontend: groepering in `SearchableCombobox` (kopregel + inklapregel als optietype),
vitest: NL → EU-opties verborgen achter "Buitenland-tarieven tonen (7)"; zoeken "EU" vindt ze wél; geselecteerd EU-tarief blijft
zichtbaar; land onbekend → alles; gebruiksfrequentie-sortering. Contrast/overflow-sweep; toetsenbord (pijltjes slaan de ingeklapte groep
over tot uitgevouwen). WAT_IS_NIEUW ("Bij een Nederlandse leverancier zie je alleen de Nederlandse btw-codes; buitenland staat ingeklapt
onderaan"). Regels-tekst naar `docs/regels/btw.md`; nameting op de Rituals-bon: lijst toont NL-tarieven + "Buitenland-tarieven tonen (N)".
