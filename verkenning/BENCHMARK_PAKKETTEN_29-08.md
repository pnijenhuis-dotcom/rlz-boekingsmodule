# Benchmark factuurverwerkingspakketten — gap-analyse (29-08-2026)

Verzoek Peter 29-08: welke functies hebben vergelijkbare pakketten die wij missen —
verbeteren op basis van best practices i.p.v. alles zelf verzinnen. Onderzocht (websites/
support-docs, 29-08): **Zenvoices**, **Basecone** (Wolters Kluwer), **TriFact365**,
**Klippa SpendControl**. Opgesteld door Cowork; bronnen onderaan.

## Wat wij al hebben en zij ook (geen gap)

Scan & herken mét zelflerend boekingsvoorstel, UBL/e-factuur-intake, mail-intake +
splitsing van multi-factuur-PDF's, meerlaagse autorisatie mét bedragdrempels en staande
goedkeuringen, mobiele goedkeur-app, duplicaatbewaking (bij ons zelfs cross-crediteur op
btw-nummer — sterker dan de benchmark), fiscaal archief (7 jaar), audit-trail,
wachttijd-inzicht per factuur, herinneringen. Op accorderings-beveiliging (passkeys,
geen e-mail-goedkeurlinks) zitten wij bewust bóven de markt.

## Gaps — wat zij hebben en wij (nog) niet

| # | Functie | Wie | Wat het is | Relevantie voor ons | Advies |
|---|---------|-----|-----------|--------------------| -------|
| 1 | **Betaalmodule / SEPA-betaalbatch** | Zenvoices | Betaalopdrachten aanmaken uit open posten → PAIN.001-bestand voor de bank; betaalstatus + vervaldatum-bewaking; per rekening collectief of individueel | HOOG. Wij lezen de bank wél maar maken geen betaalopdrachten; klanten doen dat nu handmatig in RLZ/bank. Onze G-rekening-praktijk (WKA-splitsing regulier/G) is hier juist een pluspunt dat de benchmark níét goed doet | Serieuze kandidaat-module: "Te betalen"-scherm (AP-aging op vervaldatum, die hebben we al als veld) → selectie → PAIN.001-export mét G-rekening-splitsing. Geen API-writes nodig, alleen export |
| 2 | **Inkooporder / three-way matching (generiek)** | Zenvoices, Klippa | Factuurregels automatisch matchen met openstaande orders en goederenontvangsten | MIDDEL. Wij hebben domein-specifieke varianten die dieper gaan (urenstaat-match, materiaalmatch, doorbelastingscontrole, bestellingen steigerbouw) maar geen generieke PO-module | Niet generiek nabouwen; wél de bestaande bestellingen-module (blok D) doortrekken naar bestelling↔factuur-match zodra een tweede branche erom vraagt |
| 3 | **Terugkerende-facturen/contract-signalen** | markt-breed ("spend insights") | Detectie van abonnementen: "factuur ontbreekt deze maand", prijsstijging t.o.v. vorige periode | MIDDEL-HOOG en goedkoop: ons boekingsgeheugen kent de historie per leverancier al | Mooi mi-/Jarvis-signaal: verwachte-factuur-ontbreekt + prijsstijging-alert per leverancier. Kleine run, hoge waarde |
| 4 | **Peppol / e-facturatie-aansluiting** | TriFact365 (PDF→UBL), markt beweegt naar Peppol | Ontvangen (en later versturen) via het Peppol-netwerk; EU-regelgeving (ViDA) duwt e-invoicing richting verplicht | HOOG op termijn. Wij doen UBL alleen via mail | Verkenning inplannen: Peppol-accesspoint-provider (bv. via bestaande NL-providers) als extra intake-kanaal naast facturen@. Geen bouw nu, wel richtinggevend |
| 5 | **Fraude-/echtheidsdetectie op documentniveau** | Klippa | Beeldmanipulatie-detectie, phantom-invoice-detectie | LAAG-MIDDEL. Onze IBAN-wissel-check + cross-crediteur-duplicaat dekken de grootste risico's | Parkeren; eventueel later metadata-checks (PDF-aanmaakdatum vs factuurdatum) als goedkoop signaal |
| 6 | **Declaraties/bonnetjes & bedrijfskaarten** | Klippa SpendControl | Employee expenses, kaartkoppelingen | LAAG voor kantoorklanten; foto→PDF-intake bestaat al bij ons | Alleen oppakken als een klant erom vraagt |
| 7 | **Goedkeuren per e-mail** | Zenvoices, Basecone | Accorderen direct vanuit de mail | GEEN gap — bewuste afwijking: e-mail-goedkeurlinks omzeilen de passkey-laag (hard principe 15-08). Niet doen | — |

## Aanbevolen volgorde (voorstel)

1. **Terugkerende-facturen-signaal** (#3): klein, bestaande data, direct klantwaarde.
2. **"Te betalen"-scherm + SEPA-betaalbatch** (#1): grootste functionele gap; eigen
   ontwerpronde waard (mét G-rekening als onderscheidend punt).
3. **Peppol-verkenning** (#4): één verkenningsdocument, beslissen ná de storerelease.
4. #2/#5/#6: geparkeerd tot een concrete klantvraag.

## Bronnen

- Zenvoices: functies/autorisatiemanagement, betaalmodule, three-way matching, purchase-to-pay (zenvoices.com + help.zenvoices.com)
- Basecone: autorisatie-workflowdocs (support.basecone.com, wolterskluwer.com)
- TriFact365: scan/herken, PDF→UBL (trifact365.com)
- Klippa SpendControl: approval management, fraud detection, matching (klippa.com, getapp.com)
