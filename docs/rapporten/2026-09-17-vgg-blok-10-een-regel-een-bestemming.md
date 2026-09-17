# Rapport 17-09 (inbox-run) — VGG → Odoo run 2 blok 10: één regel, één bestemming (3606/3607) — modelfix + herleiding van de 24 regels zonder bankmutatie; vijfde meting ná deploy

Opdracht: `opdrachten/gedaan/2026-09-17-vgg-blok-10-3606-3607-schoning-en-vijfde-meting.md`. Geen migratie, geen RLZ-/Odoo-writes.
**Werkt in productie: nee — nog niet gedeployd; blok B is lees-only op productie gemeten (`rlz-lezen`, job-image, 17-09 ~13:00–13:25);
de vijfde meting volgt ná deploy (vervolg-opdracht `opdrachten/inbox/2026-09-17-vgg-vijfde-meting.md`).**

## Blok A — modelfix (Cowork-diagnose bevestigd)
`vertaling._kies_rolregel` koos voor `aanbetaling` de activa-regel met de grootste debet; bij een ONTVANGEN aanbetaling
(1001 D / 16xx C, RLZ-28-00000061) is dat de BANKregel (1001 is óók AccountType 3) — dezelfde regel die het 1001-model naar
outstanding BNK1 stuurt → 3606 −363.300,00 (13 documenten) / 3607 −20.000,00 (1) in de vierde meting. Fix: liquide middelen
(10xx + `bank_statement_lines`-codes) nooit in de rol-pool; aanbetaling = tegenzijde met het grootste |bedrag|; alleen bankregels =
geen rol mét reden; `Vertaald.rol_regel_index` + overlap-guard in het 1001-model (`overlappen`, ROOD-bepalend via
`ReplayRapport.overlappen_1001`, tabel "TWEE bestemmingen"); 1001-tabel kolom "RJ-220-tegenzijde → rol"; de herclassificatietabel
toont daardoor de tegenzijde-rekening i.p.v. `ongemapt:1001`. Tests: casus RLZ-28-00000061 + geforceerde overlap = ROOD; migratie-suite
273 + 16 groen.

## Blok B — 24 regels zonder bankmutatie, lees-only herleid (documentvorm mét regels; bankvensters ± 10 d)

| Boekstuk | Datum | Bedrag | Regels (D/C) | Omschrijving (ontknipt) | Hypothese | Controle Peter in RLZ |
|---|---|---|---|---|---|---|
| RLZ-06-00000068 | 17-11-2025 | € 75.000,00 | 1011 Kruisposten C / 1001 ING D | Overdracht Oosterdiepswal 7 te Kollum, dossier 2025.078955.01 | notaris-ontvangst geboekt via **kruisposten** (1011 → 1001); in het bankvenster 07-11…27-11 (47 mutaties, 24 leesbaar) geen +75.000 op ING | staat de ontvangst op het ING-afschrift van ±17-11? Zo nee: kruispost zonder bankimport → afletteren/opschonen |
| RLZ-06-00000222 | 29-06-2026 | € 100.000,00 | 1011 C / 1001 D | Gustaaf Gelderstraat 60 te Almere, dossier 2025.078957.01 | idem kruispost-ontvangst; venster 19-06…09-07 (75 mutaties, 22 leesbaar) geen +100.000 zichtbaar — **niet volledig gemeten** | idem |
| RLZ-06-00000099 | 12-01-2026 | € 32.500,00 | 1011 C / 1001 D | Overdracht Goeverneurlaan 310 te Den Haag, dossier 2025.079008.01 | idem; venster 02-01…22-01 (40 mutaties, 26 leesbaar) geen +32.500 zichtbaar | idem |
| RLZ-06-00000102 | 12-01-2026 | € 22.000,00 | 1011 C / 1001 D | Overdracht Azielaan 334 te Utrecht, dossier 2025.078804.01 | idem; geen +22.000 zichtbaar | idem |
| RLZ-28-00000013 | 29-08-2025 | € 20.000,00 | 1002 Spaar C / 1001 ING D | Van Zakelijke Oranje Spaarrekening | **interne overboeking spaar → betaal** (bank-direct reeks RLZ-28) | beide rekeningen: staat de tegenmutatie op het spaar-afschrift (1002)? |
| RLZ-28-00000014 | 22-08-2025 | € 8.100,00 | 1002 D / 1001 C | Belasting Kapershoek 34 | interne overboeking betaal → spaar (reservering belasting) | idem |
| RLZ-28-00000015 | 13-08-2025 | € 12.000,00 | 1002 D / 1001 C | Rijswijkseweg te Den Haag + 1000 aanbetaling | interne overboeking → spaar | idem |
| RLZ-28-00000016 | 12-08-2025 | € 1.000,00 | 1002 C / 1001 D | Aanbetaling Koraalerf 45 Heerlen | interne overboeking spaar → betaal | idem |
| RLZ-28-00000017 | 31-07-2025 | € 9.880,00 | 1002 D / 1001 C | Belasting verkoop Verschoorstraat 70-2 te Rotterdam | interne overboeking → spaar; ING-mutatie **−9.880,00 op 31-07-2025 bestaat** (venster 01-07…05-09, 115 mutaties, 27 leesbaar) maar het model koppelde niet | waarom niet gekoppeld: is die mutatie via `PaymentReferenceList` aan een ánder document gehangen? |

Kern: de 4 RLZ-06-regels zijn notaris-ontvangsten via **1011 Kruisposten** en de 5 RLZ-28-regels zijn **interne overboekingen
spaar ↔ betaal (1002 ↔ 1001)**. Geen van beide is een "1001-regel tegenover een vreemde bankmutatie": de kruispost hoort tegenover
een latere/andere bankregel, en een interne overboeking hoort in Odoo als bank→bank (twee statement lines, geen outstanding tegenover
een derde). **Modelpunt voor SCHRIJF b/c:** (1) regels op 1011/1002 = liquide middelen (niet 1001) — het 1001-model behandelt nu
alleen de `bank_statement_lines`-codes + `UseForPaymentAccount`; 1002 Spaar zou als eigen bankjournal moeten meelopen; (2) een
memoriaal met TWEE liquide regels (1001 ↔ 1002/1011) = interne overboeking → geen RJ-220-rol (blok 10 zet dat al: alleen bankregels =
geen rol) en in de replay een transfer-post. Niet gebouwd (regel "rapporteren, niets bouwen"); beslispunt.

**Meetbeperking (eerlijk):** de bankvensters zijn via `rlz-lezen --top 50` gelezen en de uitvoer komt via Cloud Logging, dat regels
laat vallen (les 14-09): per venster 22–27 van de 40–115 mutaties leesbaar → "geen +75.000 zichtbaar" is géén bewijs van afwezigheid.
Volledige toets ná deploy: `nameting.sh rlz-feiten bank --administratie Vastgoedgroep --bedrag 75000.00 --van 2025-11-01 --tot 2025-12-15`
(compacte uitvoer) per regel.

## Blok C — vijfde meting
Niet gemeten (deploy nodig). Vervolg-opdracht `2026-09-17-vgg-vijfde-meting.md`: verwachting 3606/3607 = 0,00, overlappen 0,
ROOD alleen debiteuren/crediteuren (afletterstand SCHRIJF c), tussenrekening/bank mét benoemde rest; plus de Project-dekking (blok 11).

## Checklist Peter vóór SCHRIJF c (herhaald, mét bron)
1. Outstanding BNK1 = Odoo 135000 Payments in transit id 132 (blok 8, 15-09) — staat.
2. IBAN BNK1 (Odoo company 6) — `docs/rapporten/2026-09-16-vgg-schrijf-b.md`.
3. Bankregel "test" € −1,00 15-08-2026 (mutatie `aa06acac…`, Koppe) — boeken of terugboeken (`2026-09-17-vgg-schoonlijst-dubbelen-richting-bank.md`).
4. RLZ-01-00000006 Receipt-concept € 43.666,14 13-08-2025 Rijswijkseweg 409 (`e37e36fb…`) — beoordelen.
5. Blok B hierboven: kruisposten 1011 (4×) en spaar-overboekingen 1002 (5×) — controle op beide afschriften.

## Beslispunten (default — `2026-09-17-beslispunten-peter.md` opdracht 6)
Overlap = ROOD maar herbestemming loopt door; liquide = 10xx + mapping-codes; alleen-bankregels = geen rol; 24 regels niet gebouwd;
vijfde meting ná deploy.

## Meetrecept
`gh workflow run nameting -f onderdeel=c` → saldibalans 3606/3607 0,00, 1001-sectie mét kolom "RJ-220-tegenzijde → rol" op de 14
memorialen, `overlappen` 0, herclassificatietabel 16xx/1405 → 3606/3607.
