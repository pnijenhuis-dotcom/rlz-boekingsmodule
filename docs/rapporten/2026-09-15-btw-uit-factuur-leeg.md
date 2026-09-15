# Btw-code bleef leeg (L.H.G. Holding "Kosten mobiele telefonie") — bug-onderzoek + fix, eindrapport 15-09

**Oorzaak in twee zinnen:** het "document" van 14-09 was géén inkoopfactuur maar een **KPN-incasso die Peter vanuit het
bankscherm direct op 4404 boekte** (RLZ-07-00002805, −83,99 incl. → −69,41 + 21 % −14,58) — er liep dus geen AI-extractie
en het handmatig-boeken-formulier op het bankscherm had geen enkele btw-voeding (geen grootboek-default in RLZ, nul
inkoopregels in LHG's boekingsgeheugen). Los daarvan zat er wél een echt gat in het documentpad: `leid_btw_af` rekende
uitsluitend per regel, zodat facturen met regels excl. btw en één btw-totaal onderaan (telecom, energie, abonnementen)
altijd een lege btw-code kregen — dat gat is nu dicht met het factuurtotaal als tweede bewijs.

**Opdracht:** `opdrachten/gedaan/2026-09-15-btw-uit-factuur-leeg-lhg.md`. Canoniek: BESLISSINGEN "BTW UIT HET FACTUURTOTAAL +
BANKFORMULIER VOLGT DE REKENING (bug-onderzoek 15-09)"; RLZ-feiten in api-verkenning "BankMutationDirectBookings —
collectie negeert `$expand`, record-vorm mét regels; casus LHG 14-09".

**Werkt in productie: niet gemeten** — de bouw gaat vóór de deploy; meetrecept onderaan. De diagnose zélf is wél op
productie gedaan (lees-only, geen writes).

## 1. Diagnose (lees-only op productie)

| Stap | Instrument | Uitkomst |
|---|---|---|
| Inkoopfacturen LHG ná 13-09 | `nameting.sh rlz-lezen PurchaseInvoices` (BookDate-filter, lambda-filter op 4404, top 30) | géén module-inkoopfactuur; geen enkele PurchaseInvoice met een 4404-regel |
| Boekingsgeheugen LHG | `nameting.sh btw-default-rapport --administratie "L.H.G. Holding" --alles` | **0 observaties**, 4404 "geen (geen regels)" — de defaults van 14-09 (0142/0143) konden niets vullen |
| Wat deed Peter op 14-09 | Cloud Logging `rlz-backend`, `textPayload:"8299910f…"` | 13:46–13:55 uitsluitend bankscherm-routes; **twee `POST …/bank/mutaties/…/direct-boeken`** (13:47:40, 13:55:32); geen `documenten/…/boekvoorstel`, geen upload |
| De boekingen in RLZ | `rlz-lezen BankMutationDirectBookings --record-via-filter "ReceiptNumber eq 'RLZ-07-00002805'"` | 4404 Kosten mobiele telefonie, net −69,41, tax −14,58 (21 %), regeltekst "Factuur 04-09-2026, klantnummer …, kpn.com/mobielefactuur" (mutatie 11-09); RLZ-07-00002806 = 4303 verzekering, 0 btw |
| TaxRates LHG | `rlz-lezen TaxRates` | 22 tarieven; twee 21 %-tarieven waarvan één `IsFavorite` — `leid_btw_af` kiest bij gelijk percentage de favoriet (ongewijzigd, nu ook op factuurniveau) |

Peters premisse "de AI leest toch alles" gold hier niet: er was geen document. De opdrachttekst "geboekt 14-09 op de
mobiele-telefonie-rekening" klopte wél — via de bank. De twee 14-09-fixes (grootboek-default RLZ, historie-default) zaten
alleen in het controlescherm; het bankformulier volgde de rekening niet, en LHG had bovendien geen historie omdat die
alleen inkoopregels telde.

## 2. Gebouwd (geen migratie)

1. **Factuur-niveau-afleiding** — `app/extractie/controle.py::leid_btw_af_uit_totaal` (puur code): regels mét netto en
   zonder eigen btw-bedrag krijgen het ene tarief dat restant-netto × tarief ≈ restant-btw bewijst (factuur-btw = gelezen
   btw-totaal, anders incl − excl; regels mét eigen btw houden hun regel-afleiding, hun btw wordt van het totaal
   afgetrokken). Voorwaarden: álle netto's gelezen en cent-exact sluitend op het excl-totaal; één cent speling per regel;
   0 %/geen match/meerduidig blijft leeg. Regel-btw wordt deterministisch berekend (half-up, afrondingsrestant op de
   grootste regel, Σ = factuur-btw) zodat de regelsom-toets op incl sluit. Herkomst `btw_bron='factuur'` (groen),
   `btw_afleiding_basis` "regel"/"factuur_totaal", top-level `btw_factuur_totaal`. De één-regel-terugval (AI zonder
   regels) neemt de code over; UBL ongewijzigd.
2. **Bankformulier volgt de gekozen rekening** — `HandmatigBoekenForm` en `SplitsenForm`: btw = grootboek-default (RLZ >
   historie) mét dezelfde chips als het controlescherm; mens wint; rekening zonder default maakt leeg. Eén bron
   `frontend/src/document/grootboekBtwDefault.ts` (BoekvoorstelPanel gerefactord, gedrag gelijk).
3. **Historie-default telt bank-direct-boekingen mee** — `grootboek_btw_historie.tellingen_per_rekening`: + regels van
   GEBOEKTE, niet-automatische `bank_boeking`en (mens/vaste regel) in het venster; gestorneerd, automatisch, zonder tarief
   en oud tellen niet. Zelfde drempels (≥ 5, ≥ 90 %). CLI `btw-default-rapport` zegt "boekingsregels (inkoop + bank)".

## 3. Tests

- Backend: `tests/extractie/test_controle.py::TestLeidBtwAfUitTotaal` (11 nieuw), `tests/documenten/
  test_btw_uit_factuur_totaal.py` (3 nieuw), `tests/geheugen/test_grootboek_btw_historie.py` (+1), CLI-test-tekst
  aangepast; gouden set: **casus (w)** `tests/keten/test_w_btw_uit_factuur_totaal.py` + fixture `w_telefonie_btw_totaal`
  (gereconstrueerd KPN-patroon met de bedragen van RLZ-07-00002805; herkomst eerlijk in bron.json), casussen u/v spelen
  bewust de Floor-variant zonder btw-/incl-totaal (`casussen.zonder_btw_totaal`) — mét totaal krijgt Floor nu terecht de
  factuur-afleiding. `tests/keten` volledig: 116 geslaagd / 1 overgeslagen (casus w 2/2 groen in de herdraai ná de projectplicht-correctie op de samengevoegde-regel-assert). Export-fixtures (`frontend/src/dev/keten/*.json`) byte-gelijk
  (`test_export_deterministisch` groen), keten-baselines onaangeraakt.
- Overige backend-suites (extractie, documenten, geheugen, unit incl. guards keten/CLAUDE.md/rapporten/changelog):
  1692 geslaagd (15 min), 0 rood; guards keten/CLAUDE.md/rapporten-index herdraaid op de eindstand: groen. Ruff: alleen pre-existente E501-regels blijven, eigen bereiken geformatteerd.
- Frontend: `HandmatigBoekenBtwDefault.test.tsx` (3 nieuw: historie-default + oranje chip + splitsing −69,41/−14,58,
  RLZ-default wint + rekening zonder default maakt leeg, mens wint); `src/document` + `src/bank` + `src/changelog`: 48
  bestanden / 390 tests groen; `tsc -b` groen; `scripts/keten_sweep.sh` groen (11 metingen, 0 nieuwe baselines — de export-fixtures c/m kregen alleen de nieuwe sleutels `btw_afleiding_basis`/`btw_factuur_totaal`, pixels gelijk).

## 4. Meetrecept ná deploy (werkt in productie: ja/nee)

1. `scripts/gcp/nameting.sh btw-default-rapport --administratie "L.H.G. Holding"` — kopregel "boekingsregels (inkoop +
   bank)"; ná de eerstvolgende `sync-alles` (07:00) telt 4404 de bankboeking(en) mee (15-09: 1× hoog; default pas bij
   ≥ 5). Loopt dagelijks mee in de nameting-workflow (onderdeel `btw-default`).
2. Peter: LHG › Bank › volgende KPN-mutatie › "Boeken…" › rekening 4404 → btw-code vooringevuld zodra 4404 een default
   draagt (chip "meestal op deze rekening (n×)"); tot die tijd leeg = correct. Alternatief nú al: "Onthoud als vaste
   regel" bij de eerstvolgende KPN-boeking — de vaste regel draagt de btw mee.
3. Een geüploade telecom-/energiefactuur (regels excl., één btw-totaal) → controlescherm: per regel de btw-code groen
   "uit factuur", regelsom-badge sluit op incl.

## 5. Keuzes zonder Peter + beslispunten

- **Keuze:** de opdracht ging uit van een factuur; ik heb het factuurpad gefixt zoals gevraagd (punt 2) én de werkelijke
  plek (bankformulier + historie-bron) — zonder dat laatste zou de gemelde situatie zich bij de volgende KPN-incasso
  herhalen. Geen AI-keuze van een btw-code (kernprincipe 2).
- **Keuze:** casus (w) is gereconstrueerd (geen echt document bestond); bron.json zegt dat letterlijk.
- **Beslispunt 1:** sneller een default voor bank-administraties dan ≥ 5 boekingen (bv. na één bevestigde vaste regel)?
- **Beslispunt 2:** historie-default óók seeden uit RLZ-JournalEntries van bankdagboeken (extra leesroute per
  administratie; LHG zou dan direct een default hebben)?
- **Kanttekening:** de collectie-vorm van `BankMutationDirectBookings`/`PurchaseInvoices` negeert `$expand` stil;
  regels alleen via de record-vorm (api-verkenning). Cloud Logging is een bruikbaar lees-only spoor om te reconstrueren
  welke route een mens gebruikte — vastgelegd als werkwijze.
