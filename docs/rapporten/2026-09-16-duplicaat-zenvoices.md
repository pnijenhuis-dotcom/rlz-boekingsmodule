# Rapport 16-09 — Waarom de module de Zenvoices-boeking miste (Hello Kitchen, Kempen Facilities) + dubbele betaling signaleren + "bewust verwijderd in RLZ" (Peter 16-09)

Opdracht: `opdrachten/gedaan/2026-09-16-duplicaat-zenvoices-en-dubbele-betaling.md`. Canoniek besluit: BESLISSINGEN "DUPLICAAT-POORT OP HET
BOEKMOMENT + DUBBELE BETALING + BEWUST VERWIJDERD (Peter 16-09)". Migratie 0147. **Werkt in productie: NIET GEMETEN** (geen deploy
binnen de run; meetrecept onderaan).

## Wortelanalyse in twee zinnen

De module boekte de twee Hello Kitchen-facturen opnieuw omdat de RLZ-bestaanscheck de referentie letterlijk vergeleek
(`Reference eq '2 4594 001722'`) terwijl Zenvoices `24594001722` had geboekt — een OData-filter kan die spaties niet
gelijkstellen, en de eigen module-normalisatie zou het paar óók gemist hebben omdat ze voorloopnullen per cijfergroep
stripte ("001722" → "1722"). Beide wortels zijn gedicht: één normalisatie (`app/documenten/referentie.py`) én een
kandidaten-leesroute in een datumvenster over de hele crediteur-identiteit, client-side genormaliseerd vergeleken, als
signaal bij intake en als blokkerende poort op het boekmoment.

## Blok A — bewijs (lees-only, productie 16-09 08:30–09:00)

**Bron eigen DB:** niet direct gelezen — de Cloud-Shell-SQL-route werd door de auto-mode-classifier geweigerd ("Production
Reads"); de documenthistorie is gereconstrueerd uit Cloud Logging (request-log op beide document-id's) en de
reconciliatie-jobuitvoer van 16-09 04:31 UTC. RLZ en bank: `scripts/gcp/nameting.sh rlz-lezen` op Kempen Facilities B.V.
(administratie 66e1e296…, RLZ-admin 7bc1e33a…).

| Stap | e7845955-d5f0-42b7-9e1c-9583794a1cd4 | 9ea6ca98-1572-48e1-b3b9-a50b98f99114 |
|---|---|---|
| Verzamelbak → toegewezen aan Kempen Facilities | 27-08 06:22 UTC | 26-08 14:34 UTC |
| Geopend, checks gedraaid (POST …/boekvoorstel/checks 200) | 27-08 07:14 | 26-08 14:36 |
| Her-extractie / veldopslag | 02-09 13:12 (extractie), 27-08 8× PUT | 02-09 10:07 8× PUT |
| Ter accordering aangeboden | 03-09 10:01 | 03-09 10:02 |
| Klant-akkoorden (drie lagen) | 08-09 21:15, 09-09 06:18, 11-09 06:50 | 08-09 21:15, 09-09 06:18, 11-09 06:50 |
| Geboekt (ná laatste akkoord) | 11-09 → RLZ-04-00004412 of -4415 | 11-09 → RLZ-04-00004415 of -4412 |
| Reconciliatie 16-09 04:31 | `ontbreekt_in_rlz` (GET PurchaseInvoices/1c3cb253… → 404) | `ontbreekt_in_rlz` (GET …/8adfb93c… → 404) |

Welk document welk bedrag droeg is zonder DB-lezing niet vast te stellen (beide reden-strings verwijzen alleen naar het
RLZ-id); voor het dossier is dat niet nodig — de boekstuknummers en bedragen zijn bekend uit de bankhulzen.

**RLZ (Zenvoices-exemplaren, nog aanwezig):** crediteur "Hello Kitchen Duiven B.V." (Entity 5fda3d7d…, KvK 89512871,
Origin 1). `24594001721` € 16.250,00 → RLZ-04-00004312, `24594001722` € 12.600,00 → RLZ-04-00004314, beide factuur- én
boekdatum 10-08-2026, Status 3 (betaald 18-08). De ReceiptNumbers van de module-exemplaren (RLZ-04-00004412 / -4415, uit
de bank-hulzen "2 4594 001722 / RLZ-04-00004412 10-8-2026") liggen ~100 boekstukken láter — Zenvoices boekte dus EERST
(kandidaat (c) vervalt), en al vóór onze intake van 26/27-08 (kandidaat (d) vervalt). Een tweede crediteurrecord
"H.K.S." (7b4b3ed8…) bestaat maar draagt geen facturen (kandidaat (b) is niet de oorzaak van dit paar, wél een reëel
risico → blok B toetst voortaan over de hele identiteit). Nog in RLZ: RLZ-04-00004414 `2 4594 001731` € 13.500,01
(Status 2, open) — óók een module-exemplaar mét spaties; er staat geen Zenvoices-tegenhanger 1731 in het venster.

**Code-wortel (bewezen in de code):** `RlzClient.find_purchase_invoices_by_reference` (`app/rlz/client.py`) filterde
`Entity/id eq … and Reference eq '<letterlijk>'`; `duplicaatsignaal.bereken_duplicaatsignaal` en `checks.check_duplicaat`
gaven de referentie ongewijzigd door. `rlz_dubbel` en de module-check gebruikten wél `normaliseer_referentie`, maar die
stripte voorloopnullen per cijfergroep: `"2 4594 001722"` → `245941722` ≠ `24594001722`. Twee verschillende
vergelijkingen dus, en géén van beide had dit paar gevonden — dat is waarom ook `rlz_dubbel` tussen 11-09 en 16-09 niets
meldde (jobuitvoer bevat geen "4594"-regel).

**Bank (tegenrekening …6324 = Hello Kitchen):** 18-08 −12.600,00 → afgeletterd tegen RLZ-04-00004314 (Zenvoices);
18-08 −16.250,00 → tegen RLZ-04-00004312 (Zenvoices); 14-09 −12.600,00 en −16.250,00 → OPEN (OpenAmount = bedrag), de
RLZ-hulzen verwijzen naar de verwijderde module-exemplaren, Peter zette er zelf "(Dubbele betaling, moet terug!)" op.
**Terug te vorderen: € 28.850,00.** Spiegelbeeld aan de ontvangstkant (…8146, doorbelaste partij): 12.600,00 én 16.250,00
zijn elk óók twee keer ONTVANGEN (18-08 en 14-09; per bedrag één verkoopfactuur 24713294/24713297) — de doorbelasting
lijkt dus ook dubbel te zijn uitgegaan en betaald; niet verder onderzocht (lees-only). Volledig dossier (mutatie-id's,
hulzen) in `verkenning/prive/hello-kitchen-dubbel-16-09.txt` (niet gecommit; IBAN's zijn door het lees-instrument
geanonimiseerd tot de laatste vier cijfers — de volledige tegenrekening staat op de mutaties in RLZ).

## Terugvorderingsdossier (geanonimiseerd)

| Wat | Bedrag | Datum | RLZ |
|---|---|---|---|
| Zenvoices-factuur 24594001721 | € 16.250,00 | 10-08-2026 | RLZ-04-00004312, betaald 18-08 (mutatie −16.250,00, IsComplete) |
| Zenvoices-factuur 24594001722 | € 12.600,00 | 10-08-2026 | RLZ-04-00004314, betaald 18-08 (mutatie −12.600,00, IsComplete) |
| Module-exemplaar "2 4594 001721" | € 16.250,00 | geboekt 11-09 | RLZ-04-00004415 — door Peter verwijderd |
| Module-exemplaar "2 4594 001722" | € 12.600,00 | geboekt 11-09 | RLZ-04-00004412 — door Peter verwijderd |
| **Tweede betaling** aan tegenrekening …6324 | **−€ 16.250,00** | 14-09-2026 | OPEN; huls RLZ-09-00007019 → RLZ-04-00004415 |
| **Tweede betaling** aan tegenrekening …6324 | **−€ 12.600,00** | 14-09-2026 | OPEN; huls RLZ-09-00007020 → RLZ-04-00004412 |

Terug te vorderen bij Hello Kitchen Duiven B.V.: **€ 28.850,00**. Advies: de twee open mutaties van 14-09 op een vordering op Hello
Kitchen afletteren (nooit tegen een nieuwe inkoopfactuur), terugontvangst tegen diezelfde vordering. Let op het spiegelbeeld aan de
ontvangstkant (…8146): beide bedragen zijn óók twee keer ONTVANGEN (18-08 en 14-09) tegenover één verkoopfactuur per bedrag
(24713294 / 24713297) — controleer of de doorbelasting eveneens dubbel is uitgegaan en betaald. Volledig dossier met mutatie-id's:
`verkenning/prive/hello-kitchen-dubbel-16-09.txt` (lokaal, niet gecommit).

## Blok B — fix op de wortel (gebouwd + getest)

- **Eén normalisatie** `app/documenten/referentie.py::normaliseer_referentie` (duplicaat_afvoer her-exporteert; rlz_dubbel, module-check,
  bank-matchmotor en de IC-match lezen dezelfde): spaties tussen cijfergroepen zijn groepering ("2 4594 001722" ≡ "24594001722",
  "2 4594 0123" ≡ "245940123"), witruimte ná een woord en `-/.:` scheiden nummerdelen mét voorloopnul-strip ("2026-0042" ≡ "2026-42").
  Kolom `boekvoorstel.referentie_norm` (migratie 0147) wordt bij élke opslag mee geschreven; data-stap `referentie-norm-backfill
  [--dry-run]` (idempotent; `--dry-run` in de nameting-allowlist).
- **Bestaanscheck over de identiteit** `app/documenten/extern_bestaan.py`: letterlijke `Reference eq` PLUS nieuwe leesroute
  `RlzClient.find_purchase_invoices_kandidaten` (alle inkoopfacturen incl. concepten van álle crediteurrecords met dezelfde KvK/btw/
  voorkeur in ± 60 dagen rond de factuurdatum; Odoo-tegenhanger in de leesfacade), client-side genormaliseerd vergeleken. Basis
  `referentie` (zelfde nummer + bedrag) = hard: signaal bij intake/extractie/veldopslag + directe afvoer bij een extern GEBOEKT
  origineel mét boekstuknummer (concept blijft onder de dagrem); `referentie_ander_bedrag` = blokkerend in de check; `bedrag_datum`
  (zelfde bedrag ± 30 d, ander nummer) = oranje signaal.
- **Poort op het boekmoment**: `checks.check_duplicaat` (in `voer_harde_checks_uit`, dus ook autoboeken en vlak vóór de PUT) toetst nu
  met factuurdatum + identiteit; rood = "… al geboekt in Reeleezee: RLZ-04-00004314 (referentie 24594001722, buiten de module)".
- **Lees-only rapport** `duplicaat-extern-rapport [--dagen 400] [--administratie …]` (nameting-allowlist): geboekte module-facturen ↔
  álle RLZ-inkoopfacturen in het venster via één gepagineerde leesroute per administratie (~5 calls, webfilter-veilig), "dubbel"
  (zelfde identiteit + genormaliseerde referentie) en "verdacht" (zelfde bedrag+datum). Odoo zichtbaar overgeslagen.

## Blok C — dubbele betaling signaleren (gebouwd + getest)

`app/bank/dubbele_betaling.py`: twee of meer uitgaande mutaties aan dezelfde tegenrekening-IBAN, cent-exact hetzelfde bedrag, binnen
60 dagen → bevinding `dubbele_betaling_vermoed` in het bank-blok van de reconciliatie ("Aan Hello Kitchen Duiven is € 12.600,00 twee
keer betaald (18-08 en 14-09) voor wat één factuur lijkt — controleer of terugvordering nodig is.") én oranje chip "mogelijk dubbel
betaald" op de bankmutatie. Uitgesloten: periodieke reeksen (`classificeer_reeks`), koppelingen naar twee verschillende referenties.
Geen automatische actie, geen RLZ-call, geen migratie. Bijvangst: `verrijking.bank` deed `session.get` op een samengestelde sleutel en
viel sinds 07-09 stil terug op `{}` — bank-bevindingen krijgen ná deploy voor het eerst tegenpartij/bedrag/datum.

## Blok D — "Bewust verwijderd in Reeleezee (dubbel/test)" (gebouwd + getest)

Derde knop op een `ontbreekt_in_rlz`/`ontbreekt_in_odoo`-rij (Beheerder): acceptatie via de bestaande schrijver met de vaste reden, het
document gaat GEBOEKT → `afgevoerd_duplicaat` met tijdlijnregel "In Reeleezee verwijderd door <naam> als dubbel/test (boekstuk …)" +
audit; terugweg "Terugdraaien…" op de geaccepteerde rij. Afwijking van de opdracht: géén `Afwijzing`-rij (DB-CHECK
`afwijzing_herkomst_herstelbaar` staat `geboekt` niet toe; migratie was voor dit blok niet beschikbaar) — beslispunt 5. **De drie
Kempen-bevindingen zijn NIET aangeraakt**: Peter klikt ze zelf weg zodra dit live is (twee Hello Kitchen + TEST-ONB ABC Hekwerk).

## Tests

- Gouden set: nieuwe casus `aa_zenvoices_dubbel` (6 tests groen: extern geboekt → afgevoerd mét boekstuk; concept → check rood; ander
  nummer/zelfde bedrag → signaal; geen exemplaar → groen); casussen a/h/l blijven groen; `l_bank_cv_08-09.json` groeit additief.
- Backend gericht: `test_extern_bestaan.py` (14), `test_referentie_backfill.py` (2), `test_duplicaat_module.py` (normalisatietabel +5),
  `test_rlz_bestaanscheck.py`, `test_duplicaatsignaal.py`, `test_checks.py`, `test_rlz_dubbel.py`, `test_matchmotor.py` — 329 groen;
  blok C `tests/bank/test_dubbele_betaling.py` (14) + reconciliatie-guards 98 groen; blok D `test_bewust_verwijderd.py` (10) +
  statusmachine + rol-endpoint-matrix 783 groen. Volledige suite: zie het slotrapport van de run.
- Frontend: `tsc -b` groen; BankDetailScreen (+2), ReconciliatieScreen (+3), changelog-guard: 38 groen.
- Afsluitroutine 0147: dev-upgrade 0146 → 0147 gedraaid, `alembic check` schoon, lokale uvicorn: openapi 200 mét de nieuwe DTO's,
  nieuwe routes zonder token 401; schema-dump ververst ná de volledige suite.

## Beslispunten (default gekozen, zie `2026-09-16-beslispunten-peter.md`)

1. Zelfde bedrag + datum met een ánder nummer = oranje signaal, geen blokkade (opdracht vroeg blokkerend).
2. Extern CONCEPT blijft onder de dagrem (blok 4 08-09), blokkeert wél de boeking.
3. Witruimte ná een woord blijft een nummerdeel-scheider ("document 03" ≡ "document 3").
4. `duplicaat-extern-rapport` RLZ-only; dubbele-betaling-venster 60 d / horizon 400 d vast; geen actie op de rij.
5. Blok D zonder Afwijzing-rij (DB-CHECK) — alsnog migratie om de CHECK te verbreden en naar wijs_af/heropen over te stappen?

## Meetrecept ná deploy (werkt in productie: ja/nee)

1. `scripts/gcp/nameting.sh reconciliatie-alles --alleen bank --lees-only` → Kempen Facilities: twee regels "Mogelijk dubbel betaald —
   Hello Kitchen Duiven" (€ 12.600,00 en € 16.250,00, 18-08 en 14-09). Bankscherm Kempen Facilities: chip op de open mutaties van 14-09.
2. `scripts/gcp/nameting.sh duplicaat-extern-rapport --administratie "Kempen Facilities"` → RLZ-04-00004414 (`2 4594 001731`) mag
   géén dubbel melden (geen Zenvoices-tegenhanger); daarna platformbreed zonder filter → antwoord op "is dit vaker gebeurd?".
3. `scripts/gcp/nameting.sh referentie-norm-backfill --dry-run` (telling), daarna de echte vulling via `gcloud run jobs execute
   rlz-reconciliatie --args="-m,app.cli,referentie-norm-backfill"`.
4. Peter: Inzicht › Reconciliatie › Kempen Facilities → drie rijen `ontbreekt_in_rlz` → "Bewust verwijderd in RLZ" → facet geaccepteerd
   + Archief toont de drie als afgevoerd mét tijdlijnregel.
5. Steekproef: een UBL met een factuurnummer mét spaties van een leverancier die al via Zenvoices geboekt is → bij intake
   `afgevoerd_duplicaat` mét boekstuk (Cloud Logging "Duplicaat afgevoerd — al geboekt in RLZ (buiten de module)").
