# OPDRACHT 17-09 — VGG schoonlijst: "dubbel € 135.000 RLZ-28-00000061/062" was GEEN dubbel (correctie Peter 17-09) — dubbel-toets herzien op richting + tegenrekening + bankbevestiging; RLZ-01-00000006 herleiden

**Correctie Peter 17-09:** "RLZ-28-00000061 en -00000062 zijn niet dubbel: één is een ontvangen betaling van Midden Nederland, de ander
een betaling aan Tupker Beheer. Als je de bank had gecontroleerd (regel nummer 1: bank is altijd leidend) had je dat ontdekt."
Bevestigd in `verkenning/nameting-vgg-replay-13-09.txt` r.1105–1106: 00000061 = 1603 ↔ 1001, 00000062 = 1602 ↔ 1001 — verschillende
tegenrekening, tegengestelde richting, zelfde dag, zelfde bedrag. De schoonlijst-toets "dubbelen bedrag + datum + relatie" (run 1,
`app/migratie/schoonlijst.py`) heeft richting, tegenrekening en de bankregel niet meegenomen — in strijd met het besluit van 12-09
"bank leidend bij dubbelen" en de blok-7-regel "kopie zonder omschrijving alleen bank-bevestigd".

**Tweede punt:** "RLZ-01-00000006 (concept)" staat sinds het rapport 15-09 als opruimpunt zonder bron, dagboek, bedrag of link; Peter
kan het niet vinden. Herkomst is onduidelijk (mogelijk systeemhuls, mogelijk verkoopfactuur-concept dagboek 01).

Pre-feature-ritueel: BESLISSINGEN "SCHOONLIJST VGG HERZIEN", "… RUN 2 (12-09)" (bank leidend), "… BLOK 7" (kopie bank-bevestigd),
"DUBBEL-SNEDE 2 OVER ALLE ADMINISTRATIES", `app/migratie/schoonlijst.py`, `app/migratie/rlz_bron.py`.

## Blok A — Dubbel-toets herzien (lees-only)
- Twee documenten zijn pas dubbel-kandidaat als: zelfde DocumentType, zelfde relatie/tegenpartij, zelfde bedrag, ± 3 d, **dezelfde
  richting** (memoriaal: zelfde debet-/creditzijde per rekening) én **dezelfde tegenrekening(en)**. Memorialen met 1001: bovendien
  bankbevestiging verplicht — twee documenten die elk tegen een EIGEN bankmutatie staan (PaymentReferenceList of cent-exact + richting
  ± 3 d) zijn per definitie geen dubbel; alleen twee documenten tegen DEZELFDE mutatie (of één zonder mutatie) blijven kandidaat.
- Uitkomst per kandidaat mét beide bankregels (datum, tegenpartij, richting) in de tabel, zodat een mens het in één oogopslag ziet.
- Casus 00000061/062 als test (verwacht: geen kandidaat); snede 2 (alle administraties) dezelfde regel.

## Blok B — RLZ-01-00000006 herleiden
- Lees-only via `rlz-lezen` op VGG: bestaat het document, welk dagboek/type, bedrag, status, datum, relatie; is het een systeemhuls (blok
  7d: 45 hulzen op type 19)? Rapporteer mét RLZ-deeplink of "bestaat niet (meer) — opruimpunt vervalt". Nooit meer een opruimpunt zonder
  bron + link in een rapport (regel opnemen in het rapportsjabloon van de nameting).

## Blok C — Bankregel "test" herleiden (Peter 17-09: "bedoel je J. Koppe en/of W.L.J.F. Koppe test op 15-08?")
- Het opruimpunt "bankregel 'test'" staat sinds 15-09 in de rapporten zonder datum, bedrag, tegenpartij of mutatie-id; Cowork kan de
  herkomst niet terugvinden. Lees-only via `rlz-lezen` (PaymentTransactions VGG, omschrijving bevat "test", alle rekeningen) → tabel
  mét datum, bedrag, tegenpartij (geanonimiseerd), IBAN-suffix, mutatie-id, afgeletterd-status; is het de Koppe-mutatie van 15-08, zeg
  dat letterlijk. Niets gevonden → opruimpunt vervalt mét die conclusie. Peter onderneemt NIETS tot dit rapport er is.
- Regel (ook voor blok B): drie van de drie SCHRIJF-c-opruimpunten bleken onvoldoende onderbouwd → élk toekomstig klikpunt voor Peter
  draagt verplicht bron-id + datum + bedrag + link; guard in het rapportsjabloon/`test_rapporten_index.py` waar dat kan.

## Afronding
Tests; BESLISSINGEN "SCHOONLIJST — DUBBEL = RICHTING + TEGENREKENING + BANKBEVESTIGD (correctie Peter 17-09)"; CLAUDE.md verwijsregel;
`Platform/registers/verbeteringen.md`: "een dubbel-signaal zonder richting, tegenrekening en bankbevestiging is geen signaal — bank is
leidend (Peter 12-09, herhaald 17-09)"; rapport + INDEX; klikpuntenlijst SCHRIJF c herschreven: alleen bankregel "test" + IBAN BNK1 (+ wat
blok B oplevert).
