> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-bank-zoekveld-batch.md

# OPDRACHT 16-09 — Bankscherm: zoekveld op tegenpartij + RLZ-boekstuknummer als match-token + batch-stap + compacte "gekoppeld"-tekst (feedback Peter 16-09, screenshot Bouwadvies Oost Nederland)

**Feedback Peter (16-09, screenshot Afletteren — Bouwadvies Oost Nederland B.V., NL04INGB0117244236, 17 open):** "in bank
graag een zoekveld zodat je kan zoeken op alle openstaande betalingen van 1 partij" (rood kader rechts van de kop
"ONVERWERKTE BANKMUTATIES").

**Wat Cowork verder in de screenshot ziet (zelf gevonden, hoort bij dezelfde run):**
- (Heren van Zuilichem-mutaties: door Peter 16-09 expliciet als GEEN gat aangemerkt — "mag je negeren"; niet analyseren,
  niet fixen. Blok B hieronder is daarmee VERVALLEN.)
- De mutatie van € −560.925,88 ("TOTAAL 14 VZ betaalkenmerk: PREF", deels afgeletterd, open € 40.723,85) is een
  betaalbatch — precies de casus van BESLISSINGEN "INCASSO-/BETAALBATCHES UIT RLZ — STAP-0 LEES-ONLY" (11-09), waar de
  matchmotor-stap "batch" nog "wacht op akkoord" staat. De Voorstel-kolom toont daar een blok van ~15 regels
  "gekoppeld: RLZ-04-00000497 · factuur 92953485 · € 1.053,71; …" — onleesbaar in een lijstrij.

Pre-feature-ritueel: BESLISSINGEN "MATCHMOTOR BANK — NAAM/IBAN + NUMMER + BEDRAG + TEKEN", "MATCHMOTOR BANK —
KLANTREFERENTIE ALS NUMMER (Peter 15-09)", "BANK — DEELS AFGELETTERDE MUTATIES", "BANKSCHERM BLOK E", "INCASSO-/BETAALBATCHES
UIT RLZ — STAP-0 LEES-ONLY", "UX-PATRONEN ALS NORM" (bundelen vóór tonen, één primaire knop + ⋯), mockup
`bank-voorstel-kaart.html`; `frontend/src/bank/`, `app/bank/matchmotor.py` / `doelpost.py` / `referentie_als_token`.

## Blok A — Zoekveld (Peters vraag)
- Zoekveld in de kop van "Onverwerkte bankmutaties" (plek van het rode kader), zelfde component als de documentenlijst-zoek
  (hergebruik, geen nieuwe UI-primitive), client-side over de geladen lijst: tegenpartijnaam, IBAN-tegenpartij, omschrijving,
  bedrag (met of zonder punt/komma, "560925,88" en "560.925,88" beide), factuur-/boekstuknummer in de omschrijving én in de
  voorstel-tekst (genormaliseerd via de referentie-normalisatie van 16-09). Teller "N van 17", Escape leegt, URL `?zoek=`
  zodat een deeplink werkt. Werkt samen met `?toon_oud=true`.
- Klik op een tegenpartijnaam in een rij = zoekveld vullen met die naam (één klik naar "alles van deze partij").
- Kop toont bij een actieve zoekterm het totaal van de getoonde mutaties ("€ 385.000,00 in 3 mutaties").

## Blok B — VERVALLEN (Peter 16-09: Zuilichem is geen gat)

## Blok C — Batch-stap (voorstel 11-09 nu bouwen; Peter zegt anders nee)
- Mutatie mét `PaymentBatchId` (`$expand=Batch`) → alle open posten waarvan `PaymentTermList.PaymentBatchInformation`
  dezelfde sleutel draagt; som cent-exact = bedrag → GROEN "betaalbatch PREF-…, 14 facturen", afletteren = N × actie 15 in
  één handeling (bestaande `link_payment_item`, idempotent per PaymentItem, deels al gekoppeld = alleen het restant); som
  ≠ bedrag → oranje mét het verschil en de niet-gevonden posten. Nooit bij `ReturnReason` (R-transactie).
- Deels-afgeletterde batch (de casus in de screenshot): restant € 40.723,85 tegen de nog open posten van dezelfde batch.

## Blok D — Compacte "gekoppeld"-tekst
- In de lijstrij: één regel "14 facturen gekoppeld · open € 40.723,85" + chip "deels afgeletterd in RLZ"; de volledige
  lijst pas in de uitklap/kaart (bestaand `VoorstelKaart`-patroon), monospace tabel boekstuk · factuur · bedrag. Rijhoogte
  constant (les C9). Overflow-sweep variant mét deze rij.

## Tests / af
- Frontend: zoekveld (naam/IBAN/bedrag/nummer, teller, URL, klik-op-naam), compacte rij + uitklap; backend: token-
  herkenning boekstuk RLZ/Odoo, deelbetalingsreeks, batch-som groen/oranje/R-transactie; nameting `bank-voorstellen-lezen
  --administratie "Bouwadvies Oost Nederland" --rekening-iban NL04INGB0117244236` als meetrecept (verwachting: batch-mutatie groen of oranje mét verschil; Zuilichem-mutaties blijven zoals ze zijn). Gouden set l uitgebreid; keten-guard.
- BESLISSINGEN "BANKSCHERM — ZOEKVELD, BATCH-STAP (Peter 16-09)", CLAUDE.md-verwijsregel, WAT_IS_NIEUW,
  rapport `docs/rapporten/2026-09-16-bank-zoekveld-batch.md` + INDEX. Werkt in productie: niet gemeten. Geen migratie.
