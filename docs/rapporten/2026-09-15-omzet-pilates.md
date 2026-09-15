# Omzetbron pilates betalingsexport (Peter 15-09)

**In gewone taal.** De betalingsexport van de pilatesstudio wordt nu automatisch gelezen en opgeknipt in één omzetdocument per
uitbetaling van de betaalprovider, zodat elk document precies het bedrag draagt dat op de bank binnenkomt. Per uitbetaling staan de
lessen per soort (Pilates, Yoga), de terugboekingen en de transactiekosten klaar, en de module bewaakt dat dezelfde betaling nooit
twee keer wordt geboekt, ook niet als week- en maandexport overlappen. Klantnamen en e-mailadressen blijven in het brondocument en
komen nergens in de boeking.

**Vragen aan Peter (defaults gekozen, staat in de beslispuntenlijst):** btw-tarief sportlessen (9 of 21 %), waar "combi Abonnement"
onder valt, rittenkaarten als omzet bij verkoop of als vooruitontvangen, en welke betaalprovider (Mollie 21 % / Stripe verlegd) voor de
btw op de kosten.

## Gedaan

- Parser op het blad "Standaardweergave" (kopregel-detectie, alleen `Succeeded`, batches per Bankoverschrijving, contant als eigen batch); juli-export: 159 transacties, 23 uitbetalingen, bruto 14.288,98, kosten 196,35 — elke batch sluit.
- Categorie-mapping productnaam → categorie met defaults en per-administratie aanvulling (`bron_instellingen.product_categorieen`, Beheerder, audit); onbekend product = blokkerende controle.
- Veldvoorstel per uitbetaling (regels per categorie incl. btw, disputes negatief in de oorspronkelijke categorie, kostenregel, netto = totaal) mét controles som/categorieën/dedupe/datum.
- Splitsing: ouder `gesplitst`, één kinddocument per batch, idempotent; dedupe-sleutel `Factuurnummer|methode|bedrag|betaaldatum` (het nummer alleen komt bij betaling, chargeback én herbetaling terug).
- Blok "Bron" in het omzet-controlescherm (batch, bruto/kosten/netto, disputes, controles).
- Gouden set `ac_omzet_pilates` (PII vervangen) + ketentest; `tests/omzet/test_bronnen.py` incl. tweede overlappende export.
- BESLISSINGEN "OMZETBRON PILATES BETALINGSEXPORT (Peter 15-09)", CLAUDE.md-verwijsregel (gedeeld met de zonnestudio), WAT_IS_NIEUW.

## Niet gebouwd (bewust)

- Kruispost "PSP-uitbetaling" + bankmatch die de netto ontvangst groen maakt, en contant → kas als eigen tegenzijde: ná het PSP-beslispunt (aflettering loopt tot dan via het bestaande RLZ-pad).
- Beheerder-UI voor productcategorieën/PSP: alleen de route.

## UX-review

Bestaand omzet-controlescherm met het bron-blok; de "matchstatus bank per batch" uit de opdracht volgt met de kruispost-bouw.

## Werkt in productie: niet gemeten

**Meetrecept ná deploy:** upload `pilates-betalingen-2026-07.xlsx` als kassarapport bij de studio-administratie. Verwacht: het
document staat op "gesplitst" en er verschijnen 23 kassarapporten "… — uitbetaling ‹batch›"; open `2026-7-9-ca834c16`: netto 637,08,
dispute 06ead052 −175,00 als signaal, "Alle producten gecategoriseerd" rood tot "combi Abonnement" een categorie heeft. Upload dezelfde
export nogmaals → op de nieuwe kinderen "Geen transactie al geboekt" rood.
