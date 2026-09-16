# Rapport 16-09 — Bankscherm: zoekveld, RLZ-betaalbatch-stap en compacte koppelingstekst

**Opdracht:** `opdrachten/gedaan/2026-09-16-bank-zoekveld-boekstuknummer-batch.md` (feedback Peter 16-09, screenshot Bouwadvies Oost
Nederland). Blok B (Zuilichem) vervallen op aanwijzing van Peter; blok C = het batch-voorstel van 11-09, nu gebouwd (akkoord Peter). Geen
migratie. **Werkt in productie: niet gemeten** — meetrecept onderaan.

## Gedaan
- **Blok A — zoekveld** (`frontend/src/bank/bankZoek.ts` + `BankDetailScreen.tsx`): client-side filter op tegenpartij, IBAN, omschrijving,
  bedrag (punt/komma vrij), nummers in omschrijving en voorstel-tekst (open post, batch-posten, RLZ-koppelingen; cijferkern-normalisatie),
  AND over termen; `?zoek=` deeplink, Escape leegt, teller "N van M · € X in N mutaties", lege stand met "zoekterm wissen", klik op de
  tegenpartijnaam vult het veld.
- **Blok C — batch-stap** (`app/bank/matchmotor.py` stap 0, `doelpost.batch_sleutel_uit`, `sync.ITEMS_EXPAND` mét terugval,
  `voorstellen._mutatie_gegevens` leest `PaymentBatchId`/`ReturnReason` uit `brondata`): sleutel-gelijkheid bankregel ↔ document, Σ|open
  posten| == |open bedrag| → groen, anders oranje mét verschil; R-transactie nooit; geen sleutel/post → stap 1–5. **Afletteren (N)** =
  `POST …/afletteren-batch` → `afletteren.letter_batch_af` (server herberekent, N × actie 15, idempotent per post via `rlz_koppelingen`, stop
  ná API-fout, uitkomst per post). Kaart `BatchKaart` mét posten in de uitklap.
- **Blok D — compacte koppelingstekst**: > 1 koppeling = "N facturen gekoppeld · open € X" + `<details>` met monospace tabel; rijhoogte
  constant.
- **Gouden set l** uitgebreid (`fixtures/l_bank_cv_08-09/batch.json`, additief): deels afgeletterde batch, twee open posten + één post zonder
  sleutel met hetzelfde bedrag (sleutel wint), DTO + afletteren-batch via de TestClient.

## Tests
- Backend: `tests/bank/test_batch.py` 12 + matchmotor/doelpost/sync/afletteren 101 = 113 groen; keten l + export-guard + keten-guard 23 groen.
- Frontend: `bankZoek.test.ts` 5, `BankDetailScreen.test.tsx` +4; bank-suite 73 groen; `tsc -b` groen. Overflow-sweep: geen bank-harnas in de
  sweep-lijst; de compacte regel en de kaart zijn `<details>`-gebaseerd (ingeklapt = constante rijhoogte).

## Niet vastgesteld (lees-only run, geen RLZ-calls)
- Of RLZ `PaymentItems?$expand=Document($expand=Entity,PaymentTermList)` accepteert. Terugval bij 400 is gebouwd en gelogd; dan blijft
  de batch-stap zonder sleutels (voorstellen als vóór 16-09). Zie api-verkenning "Incasso-/betaalbatches — STAP-0 11-09" §4b.

## Meetrecept ná deploy
```
scripts/gcp/nameting.sh bank-voorstellen-lezen --administratie "Bouwadvies Oost Nederland" --rekening-iban NL04INGB0117244236
```
Verwacht: mutatie −560.925,88 → soort `batch`, groen (som = open 40.723,85) of oranje mét verschil; Zuilichem-mutaties ongewijzigd. Cloud
Logging job `rlz-sync`/`rlz-bank-sync`: géén regel "RLZ weigert $expand=…PaymentTermList". Daarna in de UI: zoek "Bouwadvies" → 17 rijen,
"Afletteren (N)" op de batch → N koppelingen.

## Beslispunten (default gekozen)
- Batch-stap staat VÓÓR stap 1 (sleutel is deterministischer dan naam/nummer); een post met de sleutel maar tekenmismatch telt niet mee.
- Oranje batch is wél afletterbaar (de gevonden posten worden gekoppeld; het verschil blijft open) — Peter kan alsnog kiezen voor
  "alleen groen afletterbaar".
- Idempotentie op document-id in `rlz_koppelingen` (leesspoor van de verversronde); een tussentijds in RLZ gekoppelde post die de sync nog
  niet zag, vangt de bestaande vooraf-toets (404/al afgeletterd).
- Zoekveld is client-side (de lijst is per rekening al volledig geladen); geen server-side zoekroute.
