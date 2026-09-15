# Bankmatch: klantreferentie als nummer + échte factuurdatum op de kaart (Peter 15-09, Clean Care Arnhem)

**In gewone taal:** Drie bijschrijvingen bij Clean Care Arnhem wezen in de module en in Reeleezee naar dezelfde factuur, maar de
module durfde het niet zeker te zeggen ("nummer niet gevonden"). De bank noemt namelijk het factuurnummer zoals het op de factuur
staat (2025689), terwijl de module alleen naar het interne Reeleezee-volgnummer van de open post (706) keek. Nu kijkt de motor ook
naar het factuurnummer van het document; met naam, bedrag en dat nummer is het voorstel groen. De kaart toonde bovendien de
vervaldatum als factuurdatum; dat is nu de echte factuurdatum.

**Werkt in productie:** niet gemeten (deploy volgt op de Stop-hook; meetrecept hieronder). STAP-0 is wél lees-only op productie
gedaan (job-executie `rlz-reconciliatie-wx4fp`).

## STAP-0 (lees-only, productie)

`nameting.sh rlz-lezen --administratie "Clean Care Arnhem" --pad PaymentItems --expand Document --filter "Document/ReceiptNumber eq
'RLZ-01-00000706'"` → `PaymentItem.Reference` "706", `Reference2` "RLZ-2025689 29-8-2026", `BookDate` = `DueDate` 12-9-2026;
`Document.Reference` = `InvoiceReference` = `InvoiceNumber` 2025689, `Document.Date` = `BookDate` 29-8-2026. Vastgelegd in
api-verkenning "PaymentItems — klantreferentie en factuurdatum van de open post (STAP-0 15-09)". ("Clean Care" alleen was niet
eenduidig: Arnhem én Holding.)

## Gebouwd

| Punt | Wat | Waar |
|---|---|---|
| 1 | `OpenPost.klantreferentie` uit `Document.Reference`/`InvoiceReference`/`InvoiceNumber` (bestaande cache-brondata, geen extra RLZ-call); nummer-criterium slaagt óók op die referentie als heel token (≥ 4 tekens, geen IBAN, geen placeholder — hergebruik `referentie_classificatie` + `rlz_dubbel`); label `bron` "naam + referentie 2025689 + bedrag", groen mét teken | `app/bank/matchmotor.py::klantreferentie_toetsbaar`, `score_post`, `PostScore.nummer_bron`; `app/bank/doelpost.py::klantreferentie_uit` |
| 2 | Factuurdatum op de kaart = `Document.Date` → datum in Reference2 → None; nooit meer `PaymentItem.BookDate`; DTO + kaart tonen klantreferentie als factuurnummer | `doelpost.factuurdatum_uit`, `schemas.OpenPostResponse.klantreferentie`, `frontend/src/bank/VoorstelKaart.tsx` |
| 3 | Gouden-set-casus y: drie mutaties + drie open posten Clean Care (geanonimiseerd), servicelaag-test: alle drie GROEN mét bron "referentie …", factuurdatum 29-8 | `tests/keten/fixtures/y_bank_klantreferentie_15-09/`, `tests/keten/test_y_bank_klantreferentie.py` |

## Tests

`tests/bank/test_matchmotor.py::TestKlantreferentieAlsNummer` (12), `tests/bank/test_doelpost.py` (+1, één bestaande verwachting
bijgesteld: Reference2-datum is nu een terugval), casus y (5), plus test_l, deels-afgeletterd, historie-regel, export-deterministisch,
keten-guard: 85 + 134 groen; frontend `VoorstelKaart` 10 groen; `tsc -b` groen (pre-commit).

## Meetrecept (ná deploy, lees-only)

```
scripts/gcp/nameting.sh bank-voorstellen-lezen --administratie "Clean Care Arnhem B.V."
```

Verwacht: de drie mutaties van 14-09 (1.261,43 / 91,05 / 1.594,18) GROEN mét bron "naam + referentie 2025689 / 2025682 / 2025696 +
bedrag" — mits nog niet afgeletterd. Op het bankscherm bij RLZ-01-00000706: "factuurdatum 29-8-2026", factuurnummer 2025689.

## Kanttekening

Reference2 op een PaymentItem is "RLZ-<factuurnummer> <factuurdatum>", niet "boekstuknummer + datum" zoals de api-verkenning
van 02-08 zei; de boekstuk-terugval in de kaart matcht daar terecht niet op en `Document.ReceiptNumber` blijft de bron.
