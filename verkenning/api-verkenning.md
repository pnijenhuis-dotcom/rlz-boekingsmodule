# Reeleezee API — verkenningsresultaat (2 juli 2026)

Geverifieerd met live credentials (login RLZ-Blow) tegen `https://apps.reeleezee.nl/api/v1`.
Help-pagina bevat 2.133 routes; hieronder de voor ons relevante bevindingen.

## Bevestigde ontwerpaannames

| # | Aanname | Status | Bewijs (endpoints) |
|---|---------|--------|--------------------|
| 1 | Multi-administratie met één login | ✅ | Elke route bestaat ook als `{adminId}/...`; `GET Administrations` |
| 2 | Inkoopfacturen via API boeken | ✅ | `PurchaseInvoices` CRUD + `/Lines` + `/Actions` (boeken) + `/Uploads` (PDF-bijlage!) + `/Totals` |
| 3 | Verkoopfacturen via API | ✅ | `SalesInvoices` CRUD + `/Lines` + `/Actions` + `SalesInvoiceImports` |
| 4 | Memoriaal/verzamelboeking (omzetrapporten) | ✅ | `ManualJournals` CRUD + `/Uploads` + `ManualJournalImports/Actions` |
| 5 | Boekingshistorie lezen (boekingsgeheugen) | ✅ | `JournalEntries`, `JournalEntryLines` (read), `JournalEntryDiaries` |
| 6 | Grootboek per administratie synchen | ✅ | `Ledgers` (+`?search=`, subsets `SalesAccounts`, `PurchaseAccounts`), zelfs `PUT Ledgers/{id}` |
| 7 | Crediteuren lezen/schrijven | ✅ | `Vendors` CRUD + `/BankRelations` + `VendorImports/Actions` |
| 8 | Btw-codes ophalen | ✅ | `TaxRates`, `TaxRateSynonyms`, per factuurregel `/Lines/{id}/TaxRates` |
| 9 | Bankmutaties lezen + boeken | ✅ | `PaymentAccounts/{id}/Statements`, `BankStatements`, `BankImports` (+POST Actions), `BankMutationDirectBookings` (PUT = mutatie direct op grootboek boeken, incl. TaxRates) |
| 10 | Afletteren op openstaande facturen | ✅ (mechanisme in PoC verifiëren) | `PurchaseInvoices/{id}/QuickPaymentSelections`, `PaymentTransactions` (search/PUT/Actions) |

## Bonusvondsten

- `PurchaseInvoiceScans` + `PurchaseInvoiceScanUploads`: RLZ heeft een eigen scan-inbox; onze PDF kan als bijlage bij de boeking (`/Uploads`) — factuurbeeld zichtbaar in RLZ zelf.
- `Financials/Balances`, `ProfitAndLosses`, `LedgerBalances` met periodefilters: rapportage/controlecijfers direct uit de API.
- `CashRegisters/DailyTurnovers`: als een klant Cashr als kassa gebruikt, kan dagomzet mogelijk zónder PDF-rapport.
- `InboxEmailAddresses`: RLZ kent inbox-e-mailadressen per administratie.
- `Files/{id}/Download`, `DocumentTaskHistory` op vrijwel alles (audit).

## Technische karakteristiek

- ASP.NET Web API, OData v4-conventies; JSON via `Accept: application/json`.
- Basic Auth over HTTPS (header `Authorization: Basic base64(user:pass)`).
- Aanmaken gebeurt bij RLZ met `PUT` + client-gegenereerde GUID (geen POST), actions via `POST .../Actions`.
- Volledige routelijst: `GET /Help` (HTML) met credentials.

## PoC-resultaat (2 juli 2026, BLOw B.V) — GESLAAGD

Volledige keten werkt, empirisch bevestigd:

1. `PUT {adminId}/Vendors/{guid}` met `{id, Name, PaymentDueDays}` → 204 (leverancier aangemaakt)
2. `PUT {adminId}/PurchaseInvoices/{guid}` met `Entity: {id: vendorGuid}` + `DocumentLineList` (regel met `Account: {id}`, `TaxRate: {id}`, `NetAmount`, `TaxAmount`) → 204; RLZ berekent totalen correct (€ 1,00 net + 21% = € 1,21)
3. Factuurstatus: 1 = concept, 2 = definitief geboekt
4. Boeken: `POST .../PurchaseInvoices/{id}/Actions` met `{Type: 17}` (Book) → 204, status → 2
5. Beschikbare acties per factuur: 17 Book, 34 Factuur verrekenen, 109 Kopieer; collectie-acties: 133 Document berekenen; verder ActionKind 15/16 LinkPaymentItems/UnlinkPayment (afletteren), 19 Correct, 138 "Bepaal of factuur al bestaat" — **per-document-actie, bewezen zonder bruikbaar signaal, niet gebruiken voor idempotentie** (zie "Actie 138" hieronder)
6. Testdata in BLOw B.V: leverancier "TEST PoC Boekingsmodule — verwijderen" (4abedc58-2504-4229-b2d2-6e9924ba6146), factuur TEST-POC-001 (4a27719a-051f-41a1-b60d-dc05e07a11e7) — na controle door Peter opruimen via actie 19 (Correct) + verwijderen

## PoC 2: memoriaal weekomzet (2 juli 2026) — GESLAAGD

`PUT {adminId}/ManualJournals/{guid}?autoCorrect=false` met `JournalEntryDiary: {id}` (dagboek "Systeemboek voor Algemene Memoriaalboekingen", b4407a30-6f3d-f7f6-be6c-e2a8ba43ab1e) en `DocumentLineList` met per regel `Account:{id}`, `CreditOrDebit` (1=debet, 2=credit), `DebitAmount`/`CreditAmount` → 204. Twaalf regels (omzet + kostprijs per productgroep, wk 15–21 sept 2025), BalanceAmount 0.0000, `POST .../Actions {Type:17}` → status 3 (definitief). Boekdatum in boekjaar 2025 geaccepteerd. RLZ-id: f111e09b-b806-424f-8f94-d2231635ff44, referentie TEST-OMZET-WK38.

## Verkenning Universal Steigerbouw (2 juli 2026) — projectadministratie

- Administratie-id: `3d954fc7-fe8d-4067-8cfb-73b4fe48c0ac` (bestaat sinds aug 2024, echte historie, dagelijkse facturatie)
- **`GET {adminId}/Projects` bestaat top-level**: 145 projecten (60 actief), naamconventie "25xxx Plaats (Opdrachtgever)". Velden: IsActive, IsBillable, BeginDate/EndDate, TotalBudgetAmount, TotalBudgetHours, DefaultRate — budgetvelden overal leeg (kans: onze offerte-ontleding kan totaalbudget terugschrijven)
- **Werksoorten bestaan als omzet-GB's**: Omzet huur / Omzet montage-demontage / Omzet transport / Omzet tekenwerk en veiligheidsplan
- **Kosten spiegelen bijna 1-op-1**: Inhuur steiger / Inhuur montage-demontage / Inhuur transport / Inhuur tekeningen → default mapping per administratie is hier vrijwel triviaal
- **Factuurregels dragen Project + GB aan béíde kanten** (verkoop én inkoop), op te vragen met `$expand=Account,Project` op `/Lines`. Kopregels (€ 0 tekstregels zoals "Meerwerk 2x oppersteiger") en algemene kosten (zonder project) vallen er netjes buiten
- Meerwerk staat in de praktijk als factuurregel — sluit aan op ons budgetversie-model
- Huuromzet is duurgebonden (wekelijks doorlopend) — "nog te factureren" heeft bij huur een tijdscomponent, anders dan eenmalige montage

## Open punten voor de bouw

1. ✅ **Opgelost (2026-07-09):** payloadstructuur `PUT PurchaseInvoices/{guid}` + regels +
   actie 17 — gebouwd in `app/documenten/boeken.py` (zie "Boekstuknummer, factuurdatum en
   /Uploads").
2. ✅ **Opgelost (2026-08-02):** `BankMutationDirectBookings` koppelt via
   `PaymentTransaction:{id}` in de PUT-payload — zie "Bankmodule schrijf-PoC".
3. ✅ **Opgelost (2026-08-02):** `QuickPaymentSelections` is géén afletterkanaal (zie
   "Bankmodule schrijf-PoC" §4); afletteren-tegen-open-post kan via de API in geen enkele vorm
   (FALLBACK-PoC) — assist-seam gebouwd, supportvraag uit.
4. Rate limits (docs-pagina "REST API limits") — deels geobserveerd, zie hieronder; exacte
   drempel nog niet bepaald.
5. ⚠️ De RLZ-Blow-login lijkt de productie-administratie van klant BLOW B.V. — schrijf-acties in de PoC alléén op een testadministratie.
6. ✅ **Opgelost (6 juli 2026): TESTADMIN-schrijfrechten uitgebreid.** Was 5 juli 2026 geblokkeerd
   op `403` (zie git-historie); Peter heeft het "niets wijzigen"-vinkje op de AK_NijenClaude-login
   uitgezet. `write_integration`-suite draait nu volledig — zie "Actie 19 Correct — geverifieerd
   gedrag" hieronder.

## Actie 19 Correct — geverifieerd gedrag (6 juli 2026, test-administratie) — GESLAAGD

Volledige boekflow (vendor → inkoopfactuur → boeken (17) → storneren (19)) tweemaal end-to-end
gedraaid tegen de RLZ-test-administratie ("Administratiekantoor Nijenhuis", `8dbfb856-…3fc5`),
laatste run via `pytest -m write_integration`. Belangrijkste bevinding — dit was nog onbekend
terrein (koppelcontract §7.3 nam "storneren = actie 19 + creditboeking" aan zonder het ooit
end-to-end te hebben getest):

- **Actie 19 zet `Status` van het bestaande document terug naar `1` (concept) — hetzelfde
  document-id, geen apart creditdocument.** Vóór actie 19: `Status: 2` (definitief geboekt). Na
  actie 19: `Status: 1`, zelfde `id`, `ReceiptNumber`, `Reference` en bedragen ongewijzigd.
  `DocumentLineList`/`Lines` blijven intact (zelfde regel, geen negatieve tegenregel toegevoegd).
- Er verschijnt **geen nieuw document** (geen aparte creditnota-achtige entiteit met eigen id) —
  RLZ's "Correct" is dus een **heropen-actie**, niet een stornering-met-tegenboeking in de zin
  van "twee documenten die samen optellen tot nul". Het effect op de onderliggende
  journaalposten/grootboeksaldi is niet direct via de `PurchaseInvoices`-resource te zien (geen
  `SourceDocumentId`-achtig veld op `JournalEntries` gevonden — `400 Could not find a property
  named 'SourceDocumentId'`); aanname: het origineel geboekte journaalpost wordt door RLZ intern
  teruggedraaid zodra het document weer concept wordt, maar dat is **niet bevestigd** via de API
  en moet nog apart geverifieerd worden (bv. door grootboeksaldo vóór/na actie 19 te vergelijken
  via `LedgerBalances`).
- **Praktische consequentie voor de bouwlaag:** "storneren" in onze werkvoorraad-taal is dus geen
  los creditdocument boeken — het is **actie 19 aanroepen en het document daarna opnieuw
  corrigeren + herboeken (actie 17)** als je de correctie definitief wilt maken, of laten staan
  als concept als je het gewoon wilt intrekken. Domeinbeslissingen die uitgaan van "stornering +
  creditboeking als apart, zichtbaar tweede document" (CLAUDE.md, koppelcontract §7.3) moeten
  hierop worden herzien.
- `Reference` wordt door RLZ **afgekapt op 30 tekens** (ons `TEST-{uuid}` is 41 tekens; opgeslagen
  als bv. `TEST-543de493-4ef4-4fed-ae87-4`). Relevant voor duplicaatcheck-criteria en voor de
  referentie-prefix-conventie (`Platform/registers/reference-prefixen.md`) — prefixen + korte
  hash passen, een volledige UUID niet.
- Testdocumenten blijven staan (nooit hard verwijderd, conform §7.3): twee inkoopfacturen in
  concept-status na actie 19 (id's `2b3f958f-a168-4e2f-b7e0-5c4c55eb0a7f` en
  `543de493-4ef4-4fed-ae87-4b46cfa0aa15`, beide referentie-prefix `TEST-`), plus de leverancier
  "TEST PoC RLZ-boekingsmodule — verwijderen" (`f56b1c00-856e-41d2-a400-894e090f1251`).

### Actie 138 (duplicaatcheck) — DEFINITIEF: geen bruikbaar signaal, niet gebruiken

Drie experimenten (6 juli 2026, test-administratie) sluiten dit open punt af — met een andere
uitkomst dan verwacht: **actie 138 werkt technisch, maar levert nooit een bruikbaar
duplicaat-signaal.**

**Experiment 1 — payload/endpoint.** `POST PurchaseInvoices/Actions` (collectie, zonder `{id}`)
geeft met élke geprobeerde body **`400 _InvalidData`** (criteria-vorm, volledige documentvorm,
kale `{Type: 138}`). Reden: 138 is, net als 17/19, een **per-document-actie**. Op
`POST PurchaseInvoices/{id}/Actions` met kale `{"Type": 138}` (dezelfde minimale `ApiAction`-vorm
als elke andere actie) geeft de API **`204`**. `GET ActionKinds/138` bevestigt
`Name: DetermineDuplicateInvoice`, `Description: "Bepaal of de factuur al bestaat"`.

**Experiment 2 — echt duplicaat vs uniek document.** Drie concept-inkoopfacturen aangemaakt bij
dezelfde vendor, zelfde regel/bedrag (€1,21): A en B met **identieke** `Reference` (`TEST-DUP-A`),
C met een unieke `Reference` (`TEST-DUP-CONTROL`) als controle. Actie 138 gedraaid op B (het
duplicaat) én op C (uniek):
- Response **exact gelijk** in beide gevallen: `204`, lege raw body, identieke headerset (alleen
  de load-balancer-cookie `AWSALB`/`AWSALBCORS` verschilt — routing, geen data).
- `GET` vóór/ná op beide documenten: het enige veld dat verandert is `Token`. Controlemeting op
  document A — waarop **geen** actie is uitgevoerd, alleen twee keer `GET` — toont dezelfde
  `Token`-drift. `Token` roteert dus bij élke `GET`, los van actie 138; geen signaal.
- `PurchaseInvoices/{id}/DocumentTaskHistory` is voor B en C identiek leeg
  (`DetailDataCollection: []`) — ook hier geen onderscheid.

**Experiment 3 — blokkeert Book (17) zelf duplicaten?** Binnen besluit 0005 (boeken mag in de
test-administratie, mits meteen gestorneerd): A geboekt (uniek op dat moment) → `204`, Status 2.
Vervolgens B (het byte-identieke duplicaat qua Entity+Reference+bedrag, nog concept) óók geboekt →
**`204`, Status 2 — geen enkele blokkade.** RLZ boekt het duplicaat gewoon, met een eigen
`ReceiptNumber`. Actie 138 nogmaals op het inmiddels geboekte B: nog steeds `204`, geen effect. Een
tweede boekpoging op het al-geboekte B geeft wél een fout — **`409 APIActions_NotAllowed`** — maar
dat is de generieke statusmachine-guard ("kan niet twee keer boeken vanuit Status 2"), niet een
duplicaatmelding. Beide (A en B) meteen na het experiment gestorneerd (actie 19 → Status 1, conform
besluit 0005); niets hard verwijderd.

**Conclusie:** RLZ heeft **geen server-side duplicaatbescherming** bij het boeken van
inkoopfacturen, en actie 138 geeft **in geen enkele geteste toestand** (concept/geboekt,
duplicaat/uniek) een waarneembaar signaal terug. Actie 138 is voor idempotentie-doeleinden
**onbruikbaar** — niet omdat de payload-vorm ontbrak (dat was de aanvankelijke misvatting), maar
omdat de actie zelf geen extern waarneembaar resultaat heeft.

**Idempotentie-fundament wordt daarmee volledig eigen verantwoordelijkheid** (koppelcontract-
principe 5, CLAUDE.md):
1. **Deterministische client-GUID's** (UUIDv5 waar het brondocument dat toelaat) — een herhaalde
   PUT met dezelfde GUID raakt vanzelf hetzelfde document, RLZ's PUT-semantiek is hier al
   idempotent voor.
2. **Eigen duplicaatquery vóór elke PUT**, als vangnet voor niet-deterministische GUID's:
   `GET PurchaseInvoices?$filter=Entity/id eq {vendorGuid} and Reference eq '{ref}'` — **werkend
   geverifieerd** (test-administratie: 2 hits op de identieke-Reference-paar A/B, 1 hit op de
   unieke C). Optioneel `and BaseInvoiceAmount eq {bedrag}` erbij voor extra precisie — ook
   geverifieerd. **Filter op de afgekapte (30-tekens) `Reference`**, anders mist de query facturen
   met een lange referentie (zie hierboven). Geïmplementeerd als
   `RlzClient.find_purchase_invoices_by_reference()`.
3. RLZ's actie 138 blijft beschikbaar in de client
   (`RlzClient.run_unreliable_duplicate_check_action()`) puur voor volledigheid/toekomstig
   support-antwoord — nooit aanroepen vóór het gedrag hierboven is herzien door Reeleezee-support.

**Openstaand:** supportvraag aan Reeleezee (zie onderaan dit document) — is dit het bedoelde
gedrag van actie 138, of ontbreekt er server-side configuratie/rechten om het functioneel te
maken?

## Boekstuknummer, factuurdatum en `/Uploads` (geverifieerd 9 juli 2026, boekflow)

PoC tegen de RLZ-test-administratie (`8dbfb856-d75b-4ec3-9124-c8b739fe3bc5`), testdocument
`Reference` beginnend met `TEST-POC-`, meteen na het experiment gestorneerd (actie 19) —
consistent met "niets hard verwijderen in externe systemen".

- **Factuurdatum**: veld `Date` op `PurchaseInvoices` (ISO-datetime, bv. `"2026-07-01T00:00:00"`)
  — meegegeven bij de `PUT` en ongewijzigd terugleesbaar. Niet te verwarren met `BookDate`
  (automatisch de dag van boeken) of `DueDate` (afgeleid, betaaltermijn).
- **Boekstuknummer**: veld `ReceiptNumber` (bv. `"RLZ-04-00002001"`) — wordt al bij de `PUT`
  (concept, Status 1) toegekend, niet pas bij boeken (Status 2); blijft ongewijzigd na actie 17.
  Dit is het nummer dat we als "RLZ-boekstuknummer" teruglaten zien in de werkvoorraad.
- **`/Uploads` (PDF-bijlage), exacte vorm**: **`PUT` — niet `POST`** (RLZ geeft `405 "Must use PUT
  instead of POST"` op een `POST`). Client-GUID-vorm, net als de documenten zelf:
  `PUT {adminId}/PurchaseInvoices/{invoiceId}/Uploads/{uploadId}` met body
  `{"id": "<uploadId>", "FileName": "<naam.pdf>", "Content": "<base64>"}` → `204`. Terugleesbaar
  via `GET .../Uploads/{uploadId}`: `{id, CreateDate, FileName, Token, LogicalFileType,
  PhysicalFileType}` — `Content` komt niet terug in de GET (verwacht, geen bijlage-inhoud in een
  metadata-response). Geïmplementeerd als `RlzClient.upload_bijlage()`.

Achtergebleven testdocumenten uit dit experiment (nooit verwijderd, alle concept ná stornering):
vendor `f56b1c00-856e-41d2-a400-894e090f1251`; facturen A (`fe46f0d6-9b34-406d-8cd4-f55e603c2e26`,
`TEST-DUP-A`, geboekt geweest + gestorneerd), B (`14e1b412-d367-4ad1-bc08-ff5537ae10bf`,
`TEST-DUP-A`, geboekt geweest + gestorneerd), C (`4f5ff019-f85f-4785-9383-50abb6cbfcda`,
`TEST-DUP-CONTROL`, nooit geboekt).

## TaxRate.Percentage — empirisch geverifieerd (11 juli 2026, design-pass taak 3)

`GET TaxRates` geeft betrouwbaar een `Percentage`-veld terug (fractie, bv. `0.21` voor 21%,
`0.0` voor 0%/vrijgesteld/verlegd) — geverifieerd op de live sync-data van meerdere
administraties (BLOw, Universal, de RLZ-test-administratie), niet alleen een PoC. Dit weerspreekt
niets van de eerdere aanname in `app/sync/models.py` dat TaxRate's officiële resource-model-
documentatie een serverfout gaf (dat blijft zo voor de documentatie-pagina zelf) — het veld
werkt gewoon in de praktijk. Nu apart gemodelleerd (`taxrate_cache.percentage`, migratie 0011)
i.p.v. alleen in `brondata`, nodig om het btw-bedrag automatisch af te leiden (netto ×
percentage) in het controlescherm. Andere velden op TaxRate die ook meekwamen maar (nog) niet
gebruikt worden: `IsExcempt` (vrijgesteld), `IsRelayed` (verlegd), `IsMixed`, `TaxKind` —
potentieel relevant voor een latere "btw verlegd is de norm in de bouwketen"-suggestie
(CLAUDE.md), niet meegenomen in deze ronde.

**Aanvulling (13 juli 2026, e2e-boektest creditnota 20260064, test-administratie):** `IsRelayed`
is live geverifieerd als de verlegd-vlag: "NL, BTW verlegd (hoog)" (`10a0f271-…`) heeft
`IsRelayed: true`, `IsExcempt: false`, `Percentage: 0.0`, `TaxKind: 1` — onderscheidbaar van
"NL, Geen BTW (Vrijgesteld)" en "NL, Nul tarief", die ook 0.0 zijn maar níét relayed. Een apart
aangifte-rubriek-veld heeft TaxRate niet; `IsRelayed`/`IsExcempt` zijn het signaal. Dezelfde test
bewees dat RLZ een **negatieve PurchaseInvoice (creditnota)** accepteert door de hele flow heen:
PUT met één regel `NetAmount: -20009.34` + verlegd-TaxRate + `TaxAmount: 0`, `/Uploads`, actie 17
→ Status 2, `BaseInvoiceAmount: -20009.34`, boekstuknummer toegekend (RLZ-04-00002014). RLZ
leidde bovendien zelf `DueDate` af (factuurdatum + betalingstermijn crediteur), zonder dat wij
die meestuurden.

## Inkoopcreditnota = negatieve PurchaseInvoice, géén apart documenttype (13 juli 2026, read-only)

Drie onafhankelijke bronnen, alle live geverifieerd tegen de test-administratie:

1. **`GET /Help` (volledige routelijst)** bevat géén creditnota-route aan de inkoopkant. De enige
   "credit"-treffers: `CreditDebits` (een kale enumeratie-collectie — id/naam/omschrijving, het
   debet/credit-begrip zelf, aansluitend op `CreditOrDebit` in memoriaalregels), `CreditTransfers`
   (betalingsverkeer/SEPA) en `PaymentRecommendationCreditSalesinvoicesFilters` — die laatste
   noemt "credit salesinvoices" als filter, wat impliceert dat ook verkoopcreditnota's gewoon
   (negatieve) SalesInvoices zijn.
2. **`Help/ResourceModel?modelName=PurchaseInvoice`**: nul credit-gerelateerde velden in het
   volledige veldenmodel. Wel `DocumentType`/`Type`-velden, maar de bijbehorende enum-
   documentatiepagina's geven een serverfout (zelfde patroon als eerder bij TaxRate).
3. **Empirisch**: onze geboekte creditnota (−20.009,34) heeft `DocumentType: 1, Type: 1` —
   exact dezelfde waarden als reguliere positieve inkoopfacturen in dezelfde administratie.
   RLZ onderscheidt een inkoopcreditnota dus niet op type-niveau.

Conclusie: negatief boeken op PurchaseInvoices is niet een workaround maar dé representatie —
de bestaande boeklogica is correct.

## Documentstatus definitief opgehelderd: 1/2/3 = Concept/Openstaand/Gesloten (13 juli 2026)

De zij-observatie hierboven ("verwerkte inkoopfacturen op Status 3") is uitgezocht via RLZ's
eigen enumeratie — **`GET DocumentStatuses`** (root-route, géén `{adminId}/`-prefix; de
admin-gescoopte vorm geeft een 404-HTML-pagina):

```json
{"id": 1, "Name": "Tentative", "Description": "Concept"}
{"id": 2, "Name": "Open",      "Description": "Openstaand"}
{"id": 3, "Name": "Closed",    "Description": "Gesloten"}
```

Empirisch bevestigd op de test-administratie: alle 40 recentst verwerkte inkoopfacturen met
`Status: 3` hebben `BaseRemainingAmount: 0` en `BasePaidAmount > 0` (volledig afgeletterd);
onze net geboekte, onbetaalde creditnota staat op `Status: 2`. **De eerdere aanname
"2 = definitief (inkoopfactuur), 3 = definitief (memoriaal)" was dus fout**: 3 is geen
memoriaal-variant van "definitief" maar de afgeletterd-status. Dat een memoriaal direct na
boeken op 3 stond, komt doordat een memoriaal geen openstaand bedrag heeft (saldo 0) en dus
meteen "Gesloten" is. Consequentie voor eigen logica: **geboekt = Status 2 óf 3** — toetsen op
alléén `Status == 2` markeert elke betaalde factuur ten onrechte als afwijking (raakt
`app/documenten/reconciliatie.py::_RLZ_STATUS_DEFINITIEF`, zie BOUWPLAN).

Bijvangst: OData-filteren op status vereist de enum-typering — `$filter=Status eq 2` geeft een
400 ("incompatible types 'Reeleezee.DTO.DocumentStatus' and 'Edm.Int32'"); status dus lokaal
filteren of met de volledige enum-literal.

## Vendor-bankrelaties: `GET Vendors/{baseId}/BankRelations` (13 juli 2026, read-only)

De gedocumenteerde Vendor-/Entity-/PurchaseInvoice-resourcemodellen tonen géén IBAN-veld, maar de
subresource `Vendors/{baseId}/BankRelations` (staat wél in de Help-routelijst) levert per
bankrelatie o.a. `IBAN`, `SwiftCode`, `OwnerName`, `IsArchived`, `DirectDebitAuthorization` —
live geverifieerd op meerdere crediteuren in de test-administratie (gevuld bij echte
leveranciers; een app-aangemaakte kale vendor heeft één relatie met `IBAN: null`). Gebruikt als
seed voor de vertrouwde-IBAN-set van de IBAN-wissel-fraudecontrole
(app/documenten/leverancier_iban.py::seed_uit_rlz).

## Rate-limit-observatie (5 juli 2026, tegen BLOw B.V, read-only)

20 opeenvolgende `GET Ledgers`-requests, sequentieel (geen parallelisme): alle 200, gemiddeld
3,2 req/s volgehouden over 6,16s, **geen enkele rate-limit- of `Retry-After`-header** in de
responses (niet bij succes, dus onbekend of ze bij een 429 wél verschijnen). Geen throttling
opgetreden bij dit tempo. Dit is een lichte, niet-agressieve steekproef — geen poging gedaan om de
daadwerkelijke bovengrens te vinden (BLOw is een productieadministratie van een echte klant, geen
testomgeving om tegen te stresstesten). De ingebouwde client (`app/rlz/client.py`) doet sowieso
altijd exponentiële backoff + respecteert een eventuele `Retry-After` op 429/5xx — voldoende
robuust voor nu, los van het exacte cijfer.

## Bankmodule STAP 0 — read-only verificatie bankbron (2 augustus 2026) — AFGEROND

Live geverifieerd tegen de test-administratie én Rubicon Investments B.V.
(`be5e66b3-b38c-4927-85c1-670490f16e3a`, echte administratie met dagelijkse bankaanlevering),
uitsluitend GET-requests. Beantwoordt het open architectuurpunt uit mockup `#bankdetail`
(Reeleezee lezen vs zelf CAMT.053/MT940 importeren).

### CONCLUSIE: lezen uit Reeleezee volstaat — geen eigen CAMT/MT940-import bouwen

Alles wat de bankmodule nodig heeft is read-only beschikbaar, met één belangrijke nuance
(RLZ's "eigen voorstellen" leveren géén bruikbaar signaal, zie onder) en één randvoorwaarde:
**de klant-administratie moet bankaanlevering in RLZ hebben** (bankkoppeling of periodieke
MT940/CAMT-import). Zonder aanlevering is er niets te lezen — dat is een
klant-onboarding-check (probe: `LastBankImport` + `BankGatewayState`), geen reden om zelf een
importfunctie te bouwen. Consistent met het al-genomen besluit: optie-2-klanten lezen we uit
RLZ; PSD2-aggregatie is exclusief Vastly's (optie 1/standalone).

### 1. PaymentAccounts — rekeningen incl. kas

`GET {adminId}/PaymentAccounts` geeft álle rekeningen (Rubicon en de test-administratie elk 7):
`IBAN`, `CurrentBalance`, `LastBalanceDate`, `AccountNumber`, namen, `IsArchived`, `IsDefault`,
plus PSD2-velden (`BankGatewayState/Type/ConsentExpirationDate` — enums `BankGatewayTypes`
0=NonPsd2/1=Psd2, `BankGatewayStates` 0=Active…3=Deleted). `Type` = `PaymentAccountTypes`-enum:
1 Bank, 2 CreditCard, **3 Cash (Kasdagboek)**, 4 Settling (verrekeningen), 5 Balance
(RC-rekeningen), 6 Privé, 7 Tussenrekening, 8 Cheque. Kas is dus gewoon een PaymentAccount —
één leesroute voor bank én kas, zoals het mockup-ontwerp aanneemt. Het resource-model kent ook
`OpenPaymentTransactions` (teller) en `LastBankImport` (navigatie; ook als subroute
`PaymentAccounts/{id}/LastBankImport`).

### 2. Ruwe mutaties = `PaymentTransactions` (niet Statements)

**`Statements` bevat alleen afschrift-koppen** (`Number`, `Date`, `Series`, `Debits`, `Credits`,
saldi, `Complete`) — géén regels; vier kandidaat-subroutes (`/Transactions`, `/Lines`,
`/StatementEntries`, `/PaymentTransactions`) geven alle 404. De regels leven top-level in
**`GET {adminId}/PaymentTransactions`**, met per mutatie:

- `BookDate` (datum), `Amount` (+`DebitAmount`/`CreditAmount` in het model), **`CounterAccount`
  (tegenrekening-IBAN)**, `Name` (tegenpartijnaam), `Reference` (omschrijving/betalingskenmerk,
  meerregelig), `TransactionId`, `Type` (`PaymentTransactionTypes`: 1 Bankregel, 2 Verwachte
  bankregel, 3 Bank import file), `IsImported`
- **Afgeletterd-status: `IsComplete` + `OpenAmount`/`BaseOpenAmount`** (open bedrag > 0 = nog
  niet (volledig) afgeletterd)
- Navigaties (werkend via `$expand`, ook genest): `PaymentAccount`, `Statement`,
  `MatchedPaymentItem`, `Batch`

OData werkt volwaardig: `$filter=PaymentAccount/id eq {guid}` (per rekening),
`IsComplete eq false` (werkvoorraad), `CreateDate ge {iso}` (incrementele sync — pakt ook
laat binnengekomen mutaties met oudere `BookDate`), `$count=true`, `$orderby`, `$top`.
Gemeten op Rubicon: 2.208 mutaties totaal, historie 2022-01-01 t/m 2026-07-31 (= volledige
levensduur van de administratie), 34 open. Bankkoppeling-/importregels hangen aan een virtueel
"lopend afschrift" (`Number: 99999999`, datum 2070) — afschriftnummer is dus geen betrouwbare
sleutel; de mutatie-id wél.

⚠️ Er bestaat een `DELETE PaymentTransactions/{id}`-route — **nooit gebruiken** (kernprincipe 3).

### 3. Aanleverpad zichtbaar per rekening (versheid-probe)

`PaymentAccounts/{id}/LastBankImport` geeft bestandsnaam, datum, `ImportedLines`/`LinesToDo`,
`BankImportSource` (0 Unknown, 1 Manual, 2 BankLink) en `BankImportType` (MT940, CAMT053,
BankGateway, …). Rubicon draait op dagelijkse MT940-import gelabeld `Manual` (~06:04 uur, geen
PSD2-gateway op de rekening). Voor de UI kunnen we dus per rekening tonen wáár de data vandaan
komt en hoe vers die is — en bij onboarding checken óf er aanlevering is.
**⚠️ Aanvulling 2026-08-08: de probe antwoordt op de meeste rekeningen NIET met 404 maar met
`400 _InvalidData` of zelfs een HTML-pagina — zie "LastBankImport per rekeningtype" verderop.**

### 4. RLZ's eigen voorstellen (`BankMutationDirectBookings`): bestaat, maar zonder bruikbaar signaal

De eerdere aanname "`BankMutationDirectBookings` met `IsSystemGenerated:true` = RLZ's eigen
bankvoorstellen" klopt maar half. Het ís een documenttype (`DocumentType` 19, eigen
`ReceiptNumber`, `Status`, regels met GB-rekening, navigaties `PaymentTransaction`,
`PaymentAccount`, `Entity`) en RLZ maakt per open bankmutatie automatisch zo'n concept aan
(Rubicon: 34 stuks `IsSystemGenerated:true`, Status 1, bedragen matchen de open mutaties). Maar
**inhoudelijk signaal ontbreekt**: de recentste tien hebben een lege `DocumentLineList` en lege
omschrijving; een oudere had één regel naar "Nog te rubriceren uitgaven" (parkeerrekening). Geen
voorgestelde GB-rekening met intelligentie, geen gekoppelde factuur, geen zekerheids-/
confidence-veld. Ook elders in de Help-routelijst bestaat geen suggestion-/recommendation-route
voor bankmatching (alleen `PaymentRecommendationCreditSalesinvoicesFilters`, een filter-enum).
**Consequentie voor het goedgekeurde bankontwerp: stap 4 van de voorstel-volgorde ("RLZ's eigen
voorstel, bron tonen") heeft via de API geen voedingsbron** — herzien bij het scherm-ontwerp
(stap vervalt, of blijft leeg-tenzij-RLZ-het-ooit-vult). De route blijft wél relevant als
mogelijk schrijfkanaal ("mutatie direct op grootboek boeken", voorstel-volgorde stap 3/5) —
schrijf-PoC in fase 2.

### 5. Afletteren: acties 15/16 + PaymentItems (BEANTWOORD 2026-08-02 — niet bouwbaar via de API, zie "Bankmodule FALLBACK-PoC")

- `ActionKinds/15` = `LinkPaymentItems` ("Koppel een betaal item"), `16` = `UnlinkPayment` —
  beschikbaar als `POST {adminId}/PaymentTransactions/{id}/Actions`.
- Help documenteert als body alleen de kale `ApiAction` (`id`, `Type`, `Description`) — **hoe het
  doel-betaal-item wordt aangewezen is niet gedocumenteerd.** Werkhypothese:
  `PUT PaymentTransactions/{id}` met `MatchedPaymentItem: {id}` (het PUT-model accepteert dat
  veld) gevolgd door actie 15, óf de `id` in de action-body is het PaymentItem-id. **Uitsluitend
  te verifiëren met een schrijf-PoC tegen de test-administratie (fase 2)** — niet uitgevoerd in
  deze read-only STAP 0.
- `GET {adminId}/PaymentItems` = de open posten om tegen af te letteren: `Amount`, `BookDate`,
  `DueDate`, `Reference` (factuurreferentie), `Reference2` (RLZ-boekstuknummer + datum),
  `Document`-navigatie, `PaymentStatus` (enum: 1 NotPaid, 2 AutoPaid/onderweg, 3 UserPaid,
  4 PayCanceled, 5 PartialPaid, 6 ReceiveConfirmed).
- `QuickPaymentSelections` (op PurchaseInvoices/SalesInvoices/ManualJournals/OpenBalances) bleek
  géén afletter-voorstellenlijst maar een keuze-enum van drie opties ("Nog te betalen", "Wordt
  automatisch geïncasseerd", "Betaald per bank") — het open punt 3 uit juli ("
  QuickPaymentSelections-flow bevestigen") is daarmee beantwoord: niet het afletterkanaal.
- **Open leespunt:** `MatchedPaymentItem` was `null` op álle gesamplede afgeletterde, geïmporteerde
  mutaties — het "waartegen is dit afgeletterd"-spoor is read-only (nog) niet gevonden. Voor de
  afgeletterd-terugkoppeling per factuur (o.a. tier-model naar Vastly) is dit geen blokkade: die
  loopt via de documentstatus zelf (Status 2→3 + `BaseRemainingAmount`/`BasePaidAmount`). Voor de
  tijdlijn-weergave ("betaald op … met mutatie …") in fase 2 verder uitzoeken — kandidaten:
  gedrag van 15/16 in de schrijf-PoC, `JournalEntryLines` van de bankrekening.

### Openstaand voor de fase-2-schrijf-PoC (test-administratie, storneren conform besluit 0005)

**→ Uitgevoerd 2 augustus 2026, zie "Bankmodule schrijf-PoC" hieronder.** Kort: punt 3 en 4
volledig beantwoord, punt 1 en 2 stuiten op een niet-gedocumenteerde payload (supportvraag aan
RLZ opgesteld). Twee STAP-0-conclusies zijn herzien: RLZ hééft een eigen matchvoorstel-signaal
(`MatchedPaymentItem` wordt automatisch gevuld), en het "waartegen afgeletterd"-leesspoor
bestaat wél (`PaymentReferenceList`).

1. Actie 15/16: exacte payload en effect op `IsComplete`/`OpenAmount`/`MatchedPaymentItem`.
2. Gedeeltelijk afletteren (G-rekening-split!) — hoe representeert RLZ een deelkoppeling.
3. `PUT BankMutationDirectBookings/{guid}` (mutatie direct op GB boeken) — payload + effect.
4. Het "waartegen afgeletterd"-leesspoor (punt 5 hierboven).

## Bankmodule schrijf-PoC (2 augustus 2026, test-administratie) — AFGEROND

Uitgevoerd tegen de RLZ-test-administratie (`8dbfb856-…3fc5`), conform besluit 0005: alles
teruggedraaid via actie 19, niets verwijderd. Harness: `verkenning/poc_bank_schrijf.py`
(admin-pin + kill-switch-bestand + TEST-referenties + append-only audit
`verkenning/output/bankpoc_audit.jsonl`; aangemaakte id's in `output/bankpoc_state.json`).
Testopstelling: crediteur "TEST PoC bankmodule — storneren", inkoopfactuur `TEST-BANKPOC-INV1`
(€121 = 100 + 21 btw, RLZ-04-00002012), zelf aangemaakte bankmutaties `TEST-BANKPOC-TX1/TX2/TX3`
op ING Zakelijk.

### 1. Bankmutaties aanmaken: `PUT PaymentTransactions/{client-guid}` werkt

Minimale payload volstaat: `{id, PaymentAccount:{id}, BookDate, Amount, Name, Reference}` → 204.
Bruikbaar voor testdata in integratietests (productie-mutaties komen uit de bankaanlevering).
Direct bij aanmaak doet RLZ twee dingen:

- **Systeemhuls**: per open mutatie ontstaat automatisch een concept-`BankMutationDirectBooking`
  (`IsSystemGenerated: true`, eigen reeks RLZ-09, Status 1, geen regels) mét een
  `PaymentReference` die de volle som claimt. Dit zijn de "lege hulzen" uit STAP 0 — plumbing,
  geen voorstel. De huls is inert: `/Actions` leeg, boeken (17) → 409, `PUT Account` erop wordt
  stil genegeerd.
- **Matchvoorstel**: bij een openstaand betaal-item met exact hetzelfde bedrag vult RLZ
  `MatchedPaymentItem` automatisch (TX2 kreeg ons item zonder enige eigen actie). **Herziening
  van de STAP-0-conclusie "stap 4 (RLZ's eigen voorstel) heeft geen voedingsbron": die is er
  dus wél** — `MatchedPaymentItem` op open mutaties is RLZ's eigen suggestie (STAP 0 sampelde
  alleen afgeletterde mutaties, daar is het veld leeg). Het veld is ook zelf te PUT-ten, maar
  alleen met een exact bedrag: een deelbedrag-match wordt stil geweigerd (204 zonder effect).
  Het is een pointer/voorstel — er gebeurt financieel niets door.

### 2. Actie 15/16 (Link/UnlinkPaymentItems): payload niet gekraakt → supportvraag

Alle gedocumenteerde vormen van de `ApiAction`-body geven `400 _InvalidData`, in elke staat
(met/zonder matchvoorstel, item NotPaid én "onderweg", exact én afwijkend bedrag):
`{Type:15}` kaal, `id` = betaal-item / factuur / mutatie-zelf / PaymentReference / nieuw GUID,
item-id in `Description`, combinaties, form-urlencoded/multipart (415), query-parameters
(`?id=` herbindt zelfs het route-doel naar het item → `APIActions_NotApplicable`). De
Help-documentatie beschrijft alleen de kale `ApiAction {id, Type, Description}`; `$metadata`
bestaat niet op deze API. Contrast: een verkeerd-toepasbare actie geeft netjes
`APIActions_NotApplicable`, dus 15/16 zijn hier wel degelijk "van toepassing" — alleen de
verwachte gegevens ontbreken. **Concept-supportvraag aan Reeleezee staat onderaan dit
document.** Consequentie: afletteren-tegen-bestaande-open-post is via de publieke API nog
niet bouwbaar; zie §6 voor wat wél kan en het vervolgspoor.

### 3. Mutatie direct op grootboek (bankkosten e.d.): volledig geverifieerd ✅

**`PUT BankMutationDirectBookings/{nieuw-client-guid}` met
`{id, PaymentTransaction:{id}, Description, DocumentLineList:[{Account:{id}, NetAmount,
Description}]}` boekt in één klap**: document meteen Status 3 (reeks RLZ-07, geen actie 17
nodig — die geeft 409), mutatie afgeletterd (`OpenAmount` 0), `PaymentReference` wijst naar
het nieuwe document. Regelmodel (`BankMutationDirectBookingLine`) kent ook `TaxRate`,
`Project`, `Department` — btw en projectkoppeling per regel dus mogelijk.
**Terugdraaien: actie 19 op het document** → Status 1, mutatie weer open (`OpenAmount`
hersteld). Niet elke regel-`Account` mag: de crediteuren-koppelrekening (1600) + `Entity`
gaf een 500 "Onverwachte fout" — koppelrekeningen zijn geen geldig direct-boekingsdoel.

### 4. Verwachte-betaling-flow (QuickPaymentSelection + actie 148): werkt, met bijwerking

- Betaal-items zijn óók zichtbaar als **"verwachte bankregels"** (Type 2, zélfde id als het
  `PaymentItem`) via `PaymentTransactions?searchstring=…&showExpectedPaymentTransactions=true`.
  (`$filter=Type eq 2` faalt overigens op een enum-typebug in RLZ's OData.)
- `PUT PurchaseInvoices/{id}` met `QuickPaymentSelection:{id}` (keuze-id's uit
  `GET …/QuickPaymentSelections`, bv. "Betaald per bank") + `PaymentAccount:{id}` → 204;
  het betaal-item springt van PaymentStatus 1 (NotPaid) naar 2 (onderweg).
- **`POST PaymentTransactions/{item-id}/Actions {Type:148}`** ("Boek verwachte bankregel",
  de enige actie die de verwachte regel aanbiedt) **boekt de betaling volledig**: factuur
  Status 2→3, `BasePaidAmount` gevuld, betaal-item weg — én RLZ maakt daarbij een **eigen
  nieuwe bankregel** aan (Type 1, `IsImported: false`, boekdatum = vervaldatum).
- Bruikbaar voor kas-/handmatige-betaling-flows; **niet** voor het afletteren van een échte
  bankfeed-mutatie (de aangemaakte regel zou naast de geïmporteerde regel staan = duplicaat).
- Terugdraaien: actie 19 op de factuur maakt óók de betaling/aflettering ongedaan (Status→1,
  bedragen terug naar 0; de door 148 aangemaakte bankregel blijft als open regel achter met
  een verse systeemhuls).

### 5. Leesspoor "waartegen afgeletterd": `PaymentReferenceList` ✅

`GET {adminId}/PaymentTransactions/{id}?$expand=PaymentReferenceList($expand=Document)` geeft
per koppeling `{id, Sequence, Amount, PaymentReconciliationSource, Document}`:

- Bij een **echt afgeletterde** mutatie wijst `Document` naar het afgeletterde document zelf
  (onze factuur, incl. `ReceiptNumber`); `Amount` is het gekoppelde bedrag per koppeling
  (teken t.o.v. het document: betaling van een inkoopfactuur = +121 op een −121-mutatie),
  `Sequence` nummert meerdere koppelingen. Het model draagt dus deelkoppelingen en
  meerdere documenten per mutatie — al is dat schrijvend nog niet bereikbaar (zie §2).
- Bij een **open** mutatie wijst de referentie naar de systeemhuls — onderscheid maken op
  `Document.IsSystemGenerated == true` (en/of `DocumentType 19` + Status 1).
- Enum `GET PaymentReconciliationSources` (top-level route, niet onder `{adminId}`):
  −1 None, 1 Reeleezee, 2 Manual, 3 CashRegister — "bron van de koppeling" voor de tijdlijn.
- `MatchedPaymentItem` is het **voorstel**-veld, niet het spoor (STAP 0 zocht daar).
- `PaymentItems` kent alleen een collectie-GET; per-id `GET PaymentItems/{id}` is 404 —
  altijd filteren (`$filter=Document/id eq {guid}`).

### 6. ⚠️ `IsComplete` is stale na terugdraaien — `OpenAmount` is leidend

Na actie 19 op het gekoppelde document komt `OpenAmount` correct terug op het open bedrag,
maar **`IsComplete` blijft `true`** (drie keer gereproduceerd: directe boeking, 161-document,
factuur-storno). Voor werkvoorraad/afgeletterd-status dus altijd op
`OpenAmount`/`BaseOpenAmount` toetsen, nooit op `IsComplete` alleen — zelfde les als
DocumentStatus 2-vs-3 bij facturen.

### Overige geverifieerde acties op bankmutaties

`GET PaymentTransactions/{id}/Actions` biedt: 15/16 (zie §2), 148 (alleen zinvol op verwachte
regels), **160 "Stel nieuw document voor" / 161 "Creëer en koppel nieuw document"**: maakt van
de bankregel een nieuw, direct geboekt-en-afgeletterd inkoopdocument met default-rubricering
(21%-splitsing, eigen RLZ-04-nummer) — RLZ's "boek bankregel als nieuw document"-knop. Voor
onze flows niet bruikbaar (wij hébben de factuur al; dit zou een duplicaat-document maken),
maar wél netjes terug te draaien met 19 op dat document. Er bestaat ook
`GET PaymentTransactions/{id}/CancellationCandidates` (niet verder verkend).

### Consequenties voor het bankmodule-ontwerp (mockup `#bankdetail`)

1. **Voorstel-volgorde stap 4 herstellen**: RLZ's eigen voorstel bestaat (auto-gevuld
   `MatchedPaymentItem` bij exacte bedrag-match) en is te tonen mét bron ("voorstel RLZ").
2. **Stap 1/2 (auto-/deel-afletteren tegen open post) is via de publieke API nog niet
   uitvoerbaar** zolang actie 15/16 dicht zit → supportvraag verzonden vóór scherm-ontwerp;
   alternatieve sporen als het antwoord uitblijft: (a) verwachte-betaling-flow per factuur
   (werkt, maar maakt eigen bankregel — alleen zinvol zonder bankfeed), (b) betaling boeken
   via ManualJournal op de crediteurenrekening + verrekenen (actie 34) — **getest in de
   fallback-PoC (2 augustus 2026, zie hieronder): afgevallen** — actie 34 zit achter dezelfde
   ongedocumenteerde-payload-muur als 15/16 en een memoriaal kan geen crediteurenpost dragen.
3. **Direct-op-grootboek (bankkosten, rente, privé) is klaar om te bouwen** (§3), inclusief
   btw/project per regel en nette storno.
4. G-rekening-split: representatie bestaat (meerdere `PaymentReference`s met eigen bedragen),
   schrijfroute wacht op het 15/16-antwoord.

Blijvend in de test-administratie (bewust, verwijderen verboden): drie open TEST-mutaties
(`TEST-BANKPOC-TX1/TX2/TX3`) + één door 148 aangemaakte open regel, elk met systeemhuls;
factuur `TEST-BANKPOC-INV1` en de 160/161- en directe-boeking-documenten staan op concept
(Status 1).

## Bankmodule FALLBACK-PoC — afletteren zonder 15/16 via ManualJournal + actie 34 (2 augustus 2026) — AFGEROND, FALLBACK NIET BOUWBAAR

Vervolg op de schrijf-PoC (consequentie 2, spoor b): kan een bankmutatie tegen een open
inkoopfactuur afgeletterd worden via een betaal-memoriaal op de crediteurenrekening +
actie 34 (verrekenen)? Uitgevoerd tegen de test-administratie (`8dbfb856-…3fc5`), conform
besluit 0005 alles gestorneerd via actie 19, niets verwijderd. Harness:
`verkenning/poc_bank_fallback.py` (zelfde waarborgen als de schrijf-PoC: admin-pin,
kill-switch, TEST-referenties `TEST-BANKFB-`, append-only audit in
`output/bankpoc_audit.jsonl`; eigen state in `output/bankfallback_state.json`).
Testopstelling: crediteur "TEST PoC bank-fallback — storneren", geboekte inkoopfactuur
`TEST-BANKFB-INV1` (€121, RLZ-04-00002014, open PaymentItem), bankmutatie `TEST-BANKFB-TX1`
(−121), betaal-memoriaal `TEST-BANKFB-MEM1` (RLZ-06-00000501), creditnota `TEST-BANKFB-CN1`
(RLZ-04-00002015, als bewezen open tegenpost).

### CONCLUSIE: afletteren-tegen-open-post kan via de publieke API in géén enkele vorm

Alle drie de resterende kandidaat-routes zijn nu empirisch dichtgetest. Samen met het
15/16-resultaat uit de schrijf-PoC betekent dit: **de crediteuren-/debiteurensubadministratie
is via de publieke API alleen te muteren door documenten te boeken (factuur/creditnota) —
elke koppel-, verreken- of betaalactie op bestaande open posten is onbereikbaar.** De
supportvraag aan RLZ is daarmee niet één van de sporen maar het énige spoor; hij is
hieronder verbreed naar 34 en 218.

### 1. Actie 34 (Factuur verrekenen): zelfde muur als 15/16 — `400 _InvalidData` in elke vorm

- Aangeboden op een geboekte inkoopfactuur (`GET .../Actions`: 19, **34 "Factuur
  verrekenen"**, 109, **218 "Betaal een inkoopfactuur"** — die laatste was nog niet eerder
  waargenomen).
- Geprobeerd zónder tegenpost én mét een perfecte open tegenpost (geboekte creditnota
  −121 op dezelfde crediteur, open item +121): `{Type:34}` kaal, `id` = memoriaal /
  creditnota / creditnota-item / factuur / factuur-item, item-id in `Description`, en
  omgekeerd (actie op de creditnota, `id` = factuur(-item)). **Alles `400 _InvalidData`** —
  byte-hetzelfde foutbeeld als actie 15/16. RLZ verrekent een exact matchende
  factuur+creditnota ook niet zelf (beide bleven open; het creditnota-item krijgt wel
  `PaymentStatus 2` "onderweg", maar dat is weergave, geen geplande verrekening).
- Help documenteert opnieuw alleen de kale `ApiAction {id, Type, Description}`.

### 2. Actie 218 (Betaal een inkoopfactuur): `500 Onverwachte fout` in elke vorm

Nieuw ontdekte actie, klinkt als hét betaalkanaal — maar elke vorm (`id` = bankmutatie /
bankrekening / betaal-item, en kaal) geeft een 500 zonder detail. Onbruikbaar; meegenomen
in de supportvraag.

### 3. Een ManualJournal kan geen crediteurenpost dragen

- **Regelniveau**: het `ManualJournalLine`-model (Help) heeft géén relatie-/Entity-veld;
  een meegestuurde `Entity` op de regel wordt **stil genegeerd** (PUT 204, veld leeg bij
  teruglezen). Het betaal-memoriaal (debet Crediteuren / credit Kruisposten, saldo 0)
  boekt gewoon (17 → direct Status 3, niets open) maar raakt uitsluitend het grootboek:
  géén PaymentItem, geen effect op factuur (`BaseRemainingAmount` blijft 121) of mutatie.
- **Documentniveau**: `Entity` bestaat wél in het `ManualJournal`-model, maar
  `PUT ManualJournals/{guid}` mét `Entity` → **`500 Onverwachte fout`** (consistent over
  retries). Zelfde familie als de 500 op de crediteuren-koppelrekening in
  `BankMutationDirectBookings` (schrijf-PoC §3): de subadministratie is voor deze
  documenttypen dicht.
- ⚠️ Lees-observatie: RLZ geeft memoriaalregels terug met **gespiegelde `CreditOrDebit`**
  t.o.v. wat wij stuurden (regel verstuurd als `CreditOrDebit:1` + `DebitAmount` komt terug
  als `CreditOrDebit:2` mét gevulde `DebitAmount`). De bedragvelden bleven correct — bij
  lezen dus op `DebitAmount`/`CreditAmount` varen, niet op `CreditOrDebit`, tot RLZ dit
  opheldert (PoC 2 uit juli nam 1=debet aan op basis van het schrijfmodel).
- `ManualJournals/{id}/Lines` bestaat niet (404) — regels lezen via
  `$expand=DocumentLineList($expand=Account,…)` op het document.

### 4. Parkeren op Kruisposten kán, maar is geen afletteren

`PUT BankMutationDirectBookings/{guid}` met regel-`Account` = Kruisposten werkt gewoon
(document direct Status 3, mutatie `OpenAmount` 0) — anders dan de crediteuren-
koppelrekening (500). Een bankmutatie "parkeren" om de bankwerkvoorraad leeg te krijgen is
dus technisch mogelijk, maar de open post op de factuur blijft staan en het latere
afletteren moet dan alsnog handmatig in de RLZ-UI — dubbel werk plus een vervuilde
tussenrekening. **Geen bruikbaar fallback-pad**, hooguit een bewuste uitzondering.

### 5. Storno-observaties (herbevestigd + nieuw)

- Volledige keten netjes teruggedraaid met actie 19: factuur, creditnota, memoriaal en
  directe boeking → Status 1; mutatie weer open (`OpenAmount` −121).
- `IsComplete` blijft na storno opnieuw stale op `true` (vierde reproductie).
- **Nieuw**: na storno van een directe boeking wijst de `PaymentReferenceList` van de
  mutatie nog steeds naar dat (nu concept-)document, en dat document staat dan zelf op
  `IsSystemGenerated: true` — het gestorneerde document neemt de rol van systeemhuls over.
  Het leesspoor-onderscheid "echt afgeletterd vs huls" moet dus op de combinatie
  `DocumentType 19 + Status 1` (of `OpenAmount` van de mutatie) toetsen, nooit op
  `IsSystemGenerated` alleen.

### Consequenties voor het bankmodule-ontwerp

1. **Voorstel-volgorde stap 1/2 (auto-/deel-afletteren, incl. G-rekening-split) is via de
   publieke API niet bouwbaar — er is geen fallback.** De G-rekening-deelbetaling was
   daardoor niet eens toetsbaar: er bestaat geen enkel API-pad om ook maar één koppeling
   te leggen. Alles hangt aan het supportantwoord van RLZ (vraag hieronder, verbreed).
2. Tot dat antwoord er is kan de bankmodule wél: mutaties lezen + voorstellen tonen
   (stap 3/4/5), direct-op-grootboek boeken (bankkosten e.d.), en voor
   afletteren-tegen-open-post het voorstel klaarzetten waarna **de mens de koppeling in de
   RLZ-UI zelf legt** (app registreert en verifieert daarna op `OpenAmount`/documentstatus).
   Dat laatste als expliciete ontwerpkeuze aan Peter voorleggen bij het scherm-ontwerp.
3. Verwachte-betaling-flow (148) blijft het enige volautomatische betaalspoor, maar alleen
   voor administraties zónder bankfeed (maakt eigen bankregel).

Blijvend in de test-administratie (bewust, verwijderen verboden): open TEST-mutatie
`TEST-BANKFB-TX1`, crediteur "TEST PoC bank-fallback — storneren", en op concept (Status 1):
factuur `TEST-BANKFB-INV1`, creditnota `TEST-BANKFB-CN1`, memoriaal `TEST-BANKFB-MEM1`
(RLZ-06-00000501) en de Kruisposten-directboeking (RLZ-07-00002274).

## Concept-supportvraag aan Reeleezee (actie 138)

Openstaand, nog niet verstuurd — Peter's akkoord + eventueel contactkanaal (support-portal/
accountmanager) nodig.

> Onderwerp: ActionKind 138 "DetermineDuplicateInvoice" — verwacht gedrag?
>
> Wij gebruiken de REST-API (`/api/v1`, webservice-login) om inkoopfacturen te boeken en willen
> vóór het boeken een duplicaatcheck doen via actie 138 (`POST PurchaseInvoices/{id}/Actions`,
> body `{"Type": 138}`). De aanroep slaagt altijd (`204`), maar we kunnen geen enkel verschil
> vinden tussen een duplicaat en een unieke factuur:
>
> - Twee inkoopfacturen aangemaakt bij dezelfde vendor, met identieke `Reference`, `Entity` en
>   bedrag (€1,21) — puur als test in onze eigen test-administratie.
> - Actie 138 op beide (en op een derde, unieke controlefactuur): altijd `204`, lege response
>   body, geen headers die verschillen (behalve de load-balancer-cookie).
> - `GET` op het document vóór/na de actie: geen enkel veld verandert (op een blijkbaar bij elke
>   `GET` roterend `Token`-veld na, dat ook zonder actie 138 verandert).
> - `PurchaseInvoices/{id}/DocumentTaskHistory`: leeg, identiek voor duplicaat en unieke factuur.
> - Ter volledigheid ook getest of `Book` (actie 17) zelf duplicaten blokkeert: nee — we konden
>   de byte-identieke duplicaat-factuur zonder enige foutmelding boeken (`204`, eigen
>   `ReceiptNumber`). Beide testfacturen zijn meteen na het boeken gecorrigeerd (actie 19).
>
> Vragen:
> 1. Is dit het bedoelde gedrag van actie 138, of ontbreekt er iets aan onze aanroep (bv. extra
>    parameters, een `$expand`, of rechten/instellingen op de administratie) om een daadwerkelijk
>    duplicaat-resultaat terug te krijgen?
> 2. Is er wél server-side duplicaatbescherming bij het boeken van inkoopfacturen (actie 17) die
>    per ongeluk niet aansloeg op onze testadministratie, of is dit inderdaad afwezig?
> 3. Is er een andere/aanbevolen manier om duplicaten te detecteren via de API, of is een eigen
>    query op `Entity`+`Reference`+bedrag (zoals wij nu doen als tijdelijke oplossing) de
>    aangewezen weg?
>
> Testomgeving: RLZ-test-administratie "Administratiekantoor Nijenhuis"
> (`8dbfb856-d75b-4ec3-9124-c8b739fe3bc5`), webservice-login AK_NijenClaude. Testdocumenten
> herkenbaar aan `Reference` beginnend met `TEST-`.

## Concept-supportvraag aan Reeleezee (acties 15/16 + 34 + 218, bankafletteren/verrekenen)

Openstaand, nog niet verstuurd — Peter's akkoord nodig (zelfde kanaal als de 138-vraag).
Verbreed na de fallback-PoC (2 augustus 2026): acties 34 en 218 toegevoegd.

> Onderwerp: ActionKind 15 (LinkPaymentItems) / 16 (UnlinkPayment) op PaymentTransactions,
> 34 (Factuur verrekenen) en 218 (Betaal een inkoopfactuur) op PurchaseInvoices —
> welke request-body wordt verwacht?
>
> Wij verwerken bankmutaties via de REST-API (`/api/v1`, webservice-login) en willen een
> (geïmporteerde) `PaymentTransaction` via de API afletteren tegen een openstaande post
> (`PaymentItem`), zoals dat in het Reeleezee-scherm "bankmutaties verwerken" kan.
> `GET PaymentTransactions/{id}/Actions` biedt actie 15 "Koppel een betaal item" en
> 16 "Ontkoppel een betaal item" aan, maar elke aanroep faalt met `400 _InvalidData`:
>
> - `POST {adminId}/PaymentTransactions/{id}/Actions` met `{"Type": 15}` en met elke door ons
>   bedachte vorm om het doel-betaal-item mee te geven: `id` = PaymentItem-id, factuur-id of
>   een nieuw GUID, het item-id in `Description`, met en zonder vooraf gezet
>   `MatchedPaymentItem` (dat veld wordt door de API zelf automatisch gevuld bij een exacte
>   bedrag-match, en accepteert onze PUT ook — maar actie 15 blijft `_InvalidData` geven).
> - Het betaal-item stond daarbij zowel op "Nog te betalen" als (via QuickPaymentSelection
>   "Betaald per bank") op "onderweg"; bedragen exact gelijk én afwijkend geprobeerd.
> - De Help-pagina documenteert als body alleen `ApiAction {id, Type, Description}`;
>   een `$metadata`-document is er niet, dus verder komen we niet.
>
> Hetzelfde beeld zien we bij het verrekenen en betalen van inkoopfacturen:
>
> - `POST {adminId}/PurchaseInvoices/{id}/Actions` met `{"Type": 34}` ("Factuur verrekenen")
>   geeft altijd `400 _InvalidData` — kaal én met `id` = creditnota, creditnota-betaal-item,
>   factuur of betaal-item, ook wanneer er op dezelfde crediteur een exact matchende geboekte
>   creditnota met open post klaarstaat.
> - `{"Type": 218}` ("Betaal een inkoopfactuur") geeft altijd `500 "Onverwachte fout"` —
>   kaal én met `id` = bankmutatie, bankrekening of betaal-item.
> - Een alternatieve route via een betaal-memoriaal vonden we ook niet: het
>   `ManualJournalLine`-model kent geen relatie-veld (een meegestuurde `Entity` op de regel
>   wordt stil genegeerd) en `PUT ManualJournals/{guid}` met `Entity` op documentniveau
>   geeft `500 "Onverwachte fout"`.
>
> Vragen:
> 1. Welke body (of welk voorbereidend veld/endpoint) verwachten acties 15 en 16 om het
>    doel-`PaymentItem` aan te wijzen? Een concreet request-voorbeeld zou enorm helpen.
> 2. Idem voor actie 34 (verrekenen van een factuur met bv. een creditnota) en actie 218
>    (betalen van een inkoopfactuur): welke body verwachten die, en is de 500 op 218 een
>    fout aan onze kant of een bekend probleem?
> 3. Ondersteunt het koppelen ook gedeeltelijk afletteren (één mutatie tegen een deel van een
>    post, of één post over meerdere mutaties — bv. een G-rekening-splitbetaling)? Wij zien
>    in het model `PaymentReferenceList` met `Amount` en `Sequence` per koppeling, maar die
>    lijst lijkt via PUT niet muteerbaar (wijzigingen worden stil genegeerd of geven
>    `The request is invalid.`).
> 4. Zijn deze acties beperkt tot bepaalde mutatiesoorten (alleen geïmporteerde regels, alleen
>    verwachte regels uit betaalbatches, …)? Onze tests draaiden op via de API aangemaakte
>    regels in onze eigen test-administratie.
> 5. Is er, los van deze acties, een aanbevolen API-route om een open post in de
>    crediteuren-subadministratie af te boeken tegen een bankmutatie?
>
> Testomgeving: RLZ-test-administratie "Administratiekantoor Nijenhuis"
> (`8dbfb856-d75b-4ec3-9124-c8b739fe3bc5`), webservice-login AK_NijenClaude. Testdata
> herkenbaar aan referenties die met `TEST-BANKPOC-` of `TEST-BANKFB-` beginnen.

**Aanscherping n.a.v. de betaal-kant-STAP-0 (9 augustus 2026) — toevoegen aan de vraag vóór
verzending:**

> Aanvulling: wij hebben inmiddels ontdekt dat het `ApiAction`-model op
> `POST {adminId}/PaymentTransactions/{id}/Actions` een ongedocumenteerd veld
> `PaymentItemList` accepteert: `{"Type": 15, "PaymentItemList": [{"id": "<paymentItemId>"}]}`
> geeft `204` (elke andere veldnaam geeft `400 _InvalidData`), maar er gebeurt daarna niets —
> `OpenAmount`, `PaymentReferenceList` en de doelfactuur blijven ongewijzigd. Ook varianten
> met `Amount` per item, het volledige PaymentItem-object of een vers item (PaymentStatus 1)
> hebben geen effect. Ter vergelijking: actie 161 ("Creëer en koppel nieuw document") werkt
> op dezelfde route en login wél direct. Wat mist er in onze `PaymentItemList`-aanroep om
> een bestaand open item te koppelen — of is die werking beperkt tot geïmporteerde
> mutaties/afschriftregels? Testreferenties van deze ronde: `TEST-AFLETTERPOC-`.

## Omzetmodule STAP 0 — write-path SalesInvoice + ManualJournal + Kasomzet (7 augustus 2026) — GESLAAGD, geen blockers

Uitgevoerd tegen de test-administratie (`8dbfb856-…3fc5`) met `verkenning/poc_omzet_schrijf.py`
(zelfde waarborgen als de bank-PoC's: admin-pin, kill switch, TEST-referenties, audit-JSONL in
`output/omzetpoc_audit.jsonl`, opruimen via actie 19). Alles gestorneerd; de testdebiteur en de
concept-documenten blijven bewust staan (nooit delete).

### 1. SalesInvoice: PUT + /Uploads + actie 17 werken — mét twee verrassingen

- `PUT SalesInvoices/{client-guid}` met `Entity:{id: customerGuid}` + `DocumentLineList`
  (per regel `Account`, `TaxRate`, `NetAmount`, `TaxAmount`, `Description`) + `Date`
  (ISO-datetime) → 204. RLZ berekent totalen zelf (100+21+50+10,50 → `BaseInvoiceAmount`
  181,50 ✓). `ReceiptNumber` (RLZ-01-reeks) al gezet bij de PUT, zelfde als inkoop.
- `PUT SalesInvoices/{id}/Uploads/{upload-guid}` (PDF-bijlage) → 204, zelfde vorm als inkoop.
- **⚠️ `Reference` is bij SalesInvoices NIET van ons**: RLZ overschrijft de meegegeven waarde
  met zijn eigen verkoopnummering (`RLZ-{InvoiceNumber}`, prefix uit de
  administratie-instellingen). `InvoiceNumber` (int) is wél expliciet zetbaar via PUT.
- **⚠️ Auto-toegekend `InvoiceNumber` kan botsen bij boeken**: RLZ's nummerteller stond in de
  test-administratie op 1 terwijl er een geboekte `RLZ-1` uit 2014 (import) bestond → actie 17
  gaf `400 "Dit factuurnummer is al in gebruik"`. Na expliciete `PUT {id, InvoiceNumber: 90001}`
  (partiële PUT liet de regels intact) boekte actie 17 wél: Status 2, open post 181,50.
  Bouwlijn: RLZ's nummer laten toekennen; bij deze specifieke 400 een deterministische
  herstel-PUT met expliciet nummer, daarna zichtbare boekfout.
- Actie 19 op een geboekte SalesInvoice → Status 1 (zelfde heropen-gedrag als inkoop/memoriaal).

### 2. ⚠️ De SalesInvoices-COLLECTIE ziet API-aangemaakte facturen niet

`GET SalesInvoices` (collectie) toont uitsluitend de historische (UI-/import-)facturen —
ons via de API aangemaakte en geboekte document verschijnt er niet in, ook niet na 45s, zelfs
niet met `$filter=id eq {guid}` (terwijl `GET SalesInvoices/{guid}` het document gewoon geeft,
en de PurchaseInvoices- en ManualJournals-collecties wél vers zijn — TEST-BANKPOC-INV1 en
TEST-OMZETPOC-MEM1 direct vindbaar op `$filter=Reference eq …`).
**Consequentie: een RLZ-side duplicaatquery à la `find_purchase_invoices_by_reference` bestaat
voor de verkoopkant niet.** Duplicaatbewaking omzet = (a) lokaal per (administratie, periode),
(b) idempotente client-GUID's + GET-op-eigen-GUID als retry-inhaal, (c) RLZ-side check op de
gekoppelde kostprijsmemoriaal-Reference (ManualJournals-collectie is wél betrouwbaar).
Handmatig in de RLZ-UI geboekte omzet voor dezelfde periode is via de API dus niet
detecteerbaar op de verkoopfactuur — beperking benoemd in het reviewscherm-ontwerp.

### 3. ManualJournal: her-verificatie PoC 2 tegen de test-administratie, nu mét bijlage

- `PUT ManualJournals/{client-guid}?autoCorrect=false` met `JournalEntryDiary:{id}` + regels
  (`CreditOrDebit` 1=debet/2=credit, `DebitAmount`/`CreditAmount`) → 204, `BalanceAmount` 0.
  Dagboek "Systeemboek voor Algemene Memoriaalboekingen" heeft in de test-administratie
  hetzelfde GUID als bij BLOW (`b4407a30-6f3d-f7f6-be6c-e2a8ba43ab1e`) — lijkt een RLZ-breed
  systeem-GUID, maar blijft per administratie opgevraagd worden (nooit hardcoden).
- `PUT ManualJournals/{id}/Uploads/{upload-guid}` → 204 (bijlage-mechanisme ook hier bevestigd).
- Actie 17 → **Status 3** (saldo 0, niets open — conform de DocumentStatus-semantiek),
  `ReceiptNumber` RLZ-06-reeks, `Reference` blijft de ónze (TEST-OMZETPOC-MEM1) — anders dan
  bij SalesInvoices. Actie 19 → Status 1.

### 4. Saldo ≠ 0: RLZ accepteert de PUT, maar weigert boeken

Niet-sluitend memoriaal (debet 10 / credit 7, `autoCorrect=false`): PUT → 204, concept met
`BalanceAmount` −3,00 (teken: credit − debet). Actie 17 → `400 "De credit- en debetbedragen
van de regels zijn niet aan elkaar gelijk …"`. **Onze harde check memoriaal-saldo-0 is dus een
dubbele waarborg (fail-fast in het reviewscherm), RLZ dwingt het bij boeken zelf ook af.**

### 5. Systeemdebiteur "Kasomzet": bestaat niet per definitie — aanmaken werkt als bij crediteuren

Geen Customer met "Kasomzet" in de test-administratie. `PUT Customers/{client-guid}`
`{id, Name}` → 204, `EntityKind` 1, `DueDays` 14 default — exact dezelfde vorm als
Vendors-aanmaak (fix 2-patroon). Bouwlijn: per administratie bij de eerste omzetboeking de
systeemdebiteur idempotent aanmaken (deterministisch UUIDv5 op administratie+naam).

### 6. "Als één transactie" is per definitie ónze verantwoordelijkheid

Elke stap (PUT verkoop, PUT memoriaal, uploads, twee keer actie 17) is een losse HTTP-call;
RLZ kent geen enkele transactionele koppeling ertussen. De één-transactie-garantie komt dus
volledig uit de app: idempotente GUID's, vaste boekvolgorde, en bij een halve mislukking óf
storno (actie 19) van de eerste helft óf een zichtbare "half geboekt"-foutstatus + herstel-
retry — nooit stil één helft laten staan.

## Omzetmodule — Receipts-verkenning: "losse inkomstenboeking" zonder debiteur (7 augustus 2026) — GESLAAGD

Aanleiding: UI-walkthrough Peter+Claude 2026-08-07 — RLZ-UI "Verkopen → Boekingen" =
documenttype Receipts; de UI schrijft alles via `POST /api/v1/{adminId}/Receipts/actions`.
Rosetta-steen: concept RLZ-01-00000395 (Reference RLZ-11, € 12,10 incl., 21%, GB 8000
"Omzet 1", géén relatie), in de UI aangemaakt en hier via de API ontleed. PoC-script:
`verkenning/poc_receipts_schrijf.py`; audit `output/receiptspoc_audit.jsonl`, id's
`output/receiptspoc_state.json`. Alle testboekingen gestorneerd (actie 19, geverifieerd:
TaxSources weer leeg); de rosetta-steen en concepten blijven bewust staan.

### 1. Wat een "Receipt" werkelijk is (rosetta-ontleding, read-only)

- **Een Receipt ís een SalesInvoice zonder `Entity`** (`Entity: null`): DocumentType 10,
  `DocumentCategory` "Verkoopfactuur (Omzet)" (`9138fa50-…`, systeem-categorie) met
  `DocumentBinder` "Inkomsten" (`invoice`). Regels zijn gewone verkoopregels
  (`Account` + `TaxRate` + `NetAmount`/`TaxAmount`, `InvoiceLineType` 4) — zelfde reeks
  (RLZ-01) als verkoopfacturen.
- **Routes**: er bestaat GÉÉN `Receipts/{id}` — alleen `{adminId}/Receipts` (collectie),
  `Receipts/Actions` (collectie-niveau) en `Receipts/Totals`. Het individuele document is
  volledig leesbaar via `SalesInvoices/{id}` mét
  `$expand=DocumentLineList($expand=Account,TaxRate),TaxSummaryList,PaymentTermList`.
  De Receipts-collectie zelf expandeert die lijsten NIET (blijven null).
- ⚠️ **De Receipts-collectie ziet óók API-aangemaakte documenten** — anders dan de
  SalesInvoices-collectie (blinde vlek uit "Omzetmodule STAP 0"). Getest met de
  API-gemaakte vergelijkingsfactuur: 1 treffer op `Receipts?$filter=id eq …`. De
  duplicaatbewaking-op-afstand kan hiermee dus wél (aanvulling op de lokale DB-bewaking).

### 2. Schrijfvorm: POST Receipts/Actions is met Basic Auth NIET bruikbaar; PUT SalesInvoices zonder Entity WEL

`POST {adminId}/Receipts/Actions` met webservice-Basic-Auth, alle geprobeerde vormen →
`400 {"Message":"The request is invalid."}` (of kale 400): document-als-body,
`{Type: 1, …document}`, `{Type: 0/17, Document: {…}}`, `{Document: {…}}`, `{Value: {…}}`.
De UI-route loopt vermoedelijk op sessie-auth met een ander envelop-formaat; voor ons
irrelevant, want:

**`PUT SalesInvoices/{client-guid}` ZONDER `Entity` werkt gewoon** (payload: id, Description,
Date, `DocumentCategory {id: 9138fa50-…}`, DocumentLineList) → 204, concept Status 1, eigen
ReceiptNumber (RLZ-01-00000396), `Entity: null`. Boeken = normale actie 17 op
`SalesInvoices/{id}` → Status 2, RLZ kent zelf het volgende `InvoiceNumber` toe (90003 —
in deze run géén nummer-botsing; het bekende herstel-pad uit Omzetmodule STAP 0 blijft:
botsing → hoogste `InvoiceNumber` uit de Receipts-collectie + 1 expliciet zetten, opnieuw 17).

### 3. BESLISSENDE CHECK — btw landt correct in de aangifte, identiek aan een SalesInvoice

Concept-btw-aangifte (`TaxDeclarations/1d7b1fa1-…`, periode vanaf 2026-07-01, TaxSources
vooraf leeg). Na boeken van de entity-loze boeking (€ 10 + € 2,10):
`TaxSources` → `{DeclaredAmount: 2.1, NetAmount: 10.0, TaxAmount: 2.1, DocumentType: 10,
VATSourceCategory: 1}` — zelfde rubriek-categorie (1 = omzet hoog) en bedragvorm als een
geboekte SalesInvoice mét debiteur (vergelijkingsmeting eerder die dag: identieke entry,
DocumentType 10). RLZ toont entity-loze boekingen in de aangifte-bron als "Onbekende klant".

Gemengd rapport (BLOW-case) in één document: regel 1 vrijgesteld (`4c8a31dd-…` "NL, Geen BTW
(Vrijgesteld)", € 50, btw 0) + regel 2 21% (€ 100 + € 21) → beide regels blijven staan
(multi-regel werkt bij SalesInvoices/Receipts gewoon — anders dan bij
BankMutationDirectBookings, zie hieronder), TaxSummaryList per tarief, boekt op € 171.
Aangifte: alléén de 21%-regel verschijnt (correct — vrijgestelde omzet hoort niet in de
btw-aangifte); de vrijgestelde regel komt nergens als rubriek terecht.

### 4. Betaling-veld: kaal `PaymentAccount` in de PUT wordt stil genegeerd; QuickPaymentSelection "Betaald met contant" + actie 148 werkt volledig

- `PUT SalesInvoices/{id}` mét `PaymentAccount: {id: kas}` in de payload → 204, maar geen
  effect (PaymentTermList onveranderd, geen koppeling) — stil genegeerd veld.
- Wél werkend (zelfde mechaniek als de verwachte-betaling-flow uit de bank-schrijf-PoC):
  `GET SalesInvoices/{id}/QuickPaymentSelections` geeft de UI-keuzes ("Betaald per bank",
  "Betaald met PIN", …, **"Betaald met contant"** `b1f1beac-…`). `PUT` van
  `{QuickPaymentSelection: {id}, PaymentAccount: {id: KAS (Type 3)}}` → 204; daarna actie 17
  → Status 2 met een verwacht betaal-item (`PaymentItems`, PaymentStatus 2); **actie 148 op
  dat betaal-item → 204: document Status 3, BasePaidAmount gevuld, en RLZ maakt ZELF de
  kas-PaymentTransaction aan** (€ 24,20, OpenAmount 0). Voor de KAS is de bekende
  "maakt eigen bankregel aan"-bijwerking precies gewenst gedrag (kas heeft geen feed).
- ⚠️ Reconciliatie-detail: na storno (19) van het document blijft die door RLZ aangemaakte
  kas-transactie STAAN (OpenAmount terug op 24,20, IsComplete stale true — zelfde stale-
  gedrag als bekend). Storno van een contant-geboekte Receipt laat dus een open kas-regel
  achter die een mens (of de reconciliatie) moet opruimen/herkoppelen.

### 5. Vergelijkingsmateriaal: de achterhaalde kas-directboeking-PoC (zelfde dag)

De eerdere STAP-0 via `BankMutationDirectBookings` tegen de kas (script
`verkenning/poc_kasomzet_direct.py`, audit `output/kaspoc_audit.jsonl`) blijft als meting
bruikbaar: (a) directboeking op omzet-GB + TaxRate zonder Entity boekt óók direct (Status 3)
en landt óók correct als `VATSourceCategory: 1` in TaxSources (DocumentType 19); (b) ⚠️
**multi-regel wordt daar STIL gereduceerd tot de laatste regel** (ook met expliciete
regel-id's — één regel per directboeking; deelboekingen tegen dezelfde PaymentTransaction
werken wel en sluiten de mutatie op OpenAmount 0); (c) totaalrekening als regel-Account →
duidelijke 400 "…is een Totaalrekening…"; (d) vrijgesteld-tarief solo boekt prima en blijft
terecht buiten de aangifte. Alles gestorneerd; één concept-huls (MIX1) bleek later door RLZ
zelf opgeruimd (404) — concept-directboekingen zijn kennelijk niet permanent. De vier
kas-test-PaymentTransactions (TEST-KASPOC-*) blijven bewust staan.

### Conclusie voor de omzetmotor (BOUWEN = VERVOLGOPDRACHT, na review Peter)

Stap 2 + 4 zijn geslaagd → de omzetmotor kan van SalesInvoice+systeemdebiteur-"Kasomzet"
naar **entity-loze Receipts** (zelfde PUT-route, `DocumentCategory` "Verkoopfactuur (Omzet)",
Entity weglaten): geen dummy-debiteur meer nodig, btw-aangifte identiek, multi-regel intact,
en optioneel de contant/kas-koppeling via QuickPaymentSelection + 148. De
`DocumentCategory`-id is administratie-specifiek te syncen (systeem-categorie met
`HasSystemId: true` — per administratie ophalen, nooit hardcoden).

### Aanvulling read-only verificatie 2026-08-09 (bouw omzetmotor → Receipts)

Drie punten gemeten op de test-administratie vóór de ombouw (BLOK 1, besluit Peter 2026-08-08):

1. **Categorie-selectie**: `GET DocumentCategories` (46 stuks) — ⚠️ de "Verkoopfactuur
   (Omzet)"-categorie heeft `HasSystemId: false` (de aanname hierboven "systeem-categorie met
   HasSystemId: true" klopt dus niet; er bestaat ook een aparte categorie "Kasomzet" met
   DocumentType 19 en wél HasSystemId true — niet de onze). Deterministische selectie:
   **`DocumentType == 10` + `Name == "Verkoopfactuur (Omzet)"`** — er zijn 4
   DocumentType-10-categorieën (Diverse opbrengsten, Door te belasten kosten, Verkoopfactuur
   (Omzet), BTW Prive bijdrage auto), de naam is daarbinnen uniek. GUID per administratie
   ophalen + cachen (`omzet_instelling.verkoop_categorie_id`), nooit hardcoden.
2. **Duplicaatbewaking-op-afstand**: de Receipts-collectie geeft `Description` terug én is er
   op filterbaar (`$filter=Description eq '…'` → correcte treffers). De motor zet daarom de
   deterministische periode-omschrijving (`OMZ-YYYYMMDD-YYYYMMDD-VK`) in Description; de
   duplicaatcheck telt vreemde hits (eigen GUID uitgesloten) — fail-closed naast de lokale
   DB-bewaking en de memoriaal-Reference-check.
3. **Nummer-herstel**: `InvoiceNumber` is op de Receipts-collectie GEEN filter-/sorteerveld
   (`$orderby`/`$filter` → 400 "Could not find a property named 'InvoiceNumber' on type
   'Reeleezee.DTO.Document.Document'" — het veld zit wél in de response-JSON). Het herstel-pad
   blijft dus max(SalesInvoices-collectie-max, eigen lokale max) + 1.

## LastBankImport per rekeningtype + RLZ-systeemrekening-GUID's (8 augustus 2026) — kliktest-fix bank-sync

Aanleiding: `make bank-sync` faalde op 0/3 administraties (kliktest Peter 2026-08-08). Oorzaak:
de versheid-probe `GET PaymentAccounts/{id}/LastBankImport` gooide op meerdere rekeningen een
fout die de hele administratie-sync afbrak. Read-only geverifieerd over alle rekeningen van
alle drie de administraties (Universal, Rubicon, test-administratie).

### 1. De probe kent drie "geen aanlevering"-antwoorden — 404 is de zeldzaamste

| Situatie | Antwoord |
|---|---|
| Bankrekening (Type 1), actieve aanlevering | `200` + JSON (bestandsnaam, datum, ImportedLines, …) |
| Kas (3), Verrekeningen (4), RC/privé (5) | `400 {"Message":"_InvalidData"}` — **altijd**, op elke administratie |
| Gearchiveerde rekening (`IsArchived: true`), ook Type 1 | `400 _InvalidData` |
| Bankrekening (Type 1) die nooit een import zag (bv. Spaarrekening) | ⚠️ **`200` mét een HTML-foutpagina als body** (geen JSON!) |

Alle drie betekenen hetzelfde: er is geen bankaanlevering (te zien). De client
(`app/rlz/client.py::get_last_bank_import`) vertaalt ze alle drie naar `None`; een 400 met een
ándere body blijft een echte fout. De sync probet rekeningtypes 3/4/5 en gearchiveerde
rekeningen niet eens meer, en heeft een failsafe: een onverwacht falende probe markeert de
rekening zichtbaar (`laatste_import_probe_fout`, migratie 0030) en laat de rest van de sync
doordraaien — een probe mag nooit meer een hele administratie-sync afbreken.
Regressietests: `tests/unit/test_rlz_client_bank_probe.py` + `tests/bank/test_sync.py`.

### 2. RLZ-systeemrekeningen hebben VASTE GUID's, identiek over administraties heen

De standaardrekeningen die RLZ bij elke administratie aanmaakt dragen overal hetzelfde id —
het zijn template-GUID's, géén gedeelde rekeningen (de data erachter is gewoon per
administratie gescheiden):

- `33f82534-4a00-…` — kas-type (Type 3; heet "Kas" bij Universal, "Overloop" bij Rubicon)
- `6612f68f-e781-…` — "Verrekeningen" (Type 4)
- `3e506870-e3b5-…` — "Privé betaalde facturen" (Type 5, standaard gearchiveerd)
- `4526f136-58da-…` / `e7f43cd2-9520-…` — RC-rekeningen (Type 5)
- `055ad4bc-f9e1-…` — de default-bankrekening (Type 1; "Universal Steigerbouw B.V." bij
  Universal, "Rubicon Investments B.V." bij Rubicon)

**Consequentie:** een rekening-GUID identificeert alléén samen met de administratie-id — nooit
een rekening cross-administratie op GUID opzoeken of ontdubbelen. Onze
`payment_account_cache` heeft niet voor niets een samengestelde sleutel (id, administratie_id);
dat patroon aanhouden bij alles wat naar PaymentAccounts verwijst.

## Afletteren via de betaal-kant — UI-walkthrough (8 augustus 2026, meegekeken via extensie)

**DOORBRAAK: afletteren-tegen-open-post gaat via de PaymentTransaction, niet via het document.**
De RLZ-UI ("Kas & Bank" → mutatie → groene suggestie → knop **Koppelen**) vuurt:

  `POST /api/v1/{adminId}/PaymentTransactions/{transactionId}/actions`  → **204**

gevolgd door een GET-refetch van diezelfde PaymentTransaction met
`$expand=...,MatchedPaymentItem($expand=...)`. RLZ's eigen matchsuggestie zit dus al als
`MatchedPaymentItem` op de mutatie; de Koppelen-actie **accepteert** die match en lettert af.

Dit verklaart waarom ALLE eerdere schrijf-PoC's faalden: die zaten op de DOCUMENT-kant
(acties 15/16 LinkPaymentItems, 34 verrekenen, 218 betalen op PurchaseInvoices/SalesInvoices/
ManualJournals → `_InvalidData`/500). De UI lettert af via de BETAAL-kant
(`PaymentTransactions/{id}/actions`), een route die we nooit beproefd hebben.

Waargenomen (Rubicon, 2026-08-08, transactie 19251249-1a85-4274-90b8-f88f6c67d4dc): status 204;
totaal-afgeboekt sprong van €37,29 naar €188,54 (koppeling €151,25 verwerkt).

**Nog onbekend (in-page fetch-interceptor werd geblokkeerd, vermoedelijk CSP/early-bound fetch —
netwerklog toont geen body):** de exacte action-body (het `Type`-nummer, en of `MatchedPaymentItem`
of een PaymentItem-id meegestuurd moet worden, of dat de reeds-gezette MatchedPaymentItem volstaat).
→ STAP-0 op de TEST-administratie: `POST PaymentTransactions/{id}/actions` met Basic Auth,
`{Type: n}` voor de plausibele actienummers, op een mutatie die een MatchedPaymentItem draagt;
toets op `OpenAmount` 0. Werkt het met Basic Auth → seam `voer_afletter_actie_uit` vervangen →
stap 1 van de voorstel-volgorde lettert voortaan automatisch af. Werkt Basic Auth niet →
sessie-only endpoint, assist-model blijft.

## Afletteren betaal-kant STAP-0 (9 augustus 2026, test-administratie) — UITGEVOERD, body nog niet gekraakt

Harness: `verkenning/poc_afletteren_betaalkant.py` (zelfde waarborgen als de bank-PoC's:
admin-pin, kill switch, TEST-referenties, append-only audit `output/afletterpoc_audit.jsonl`,
storno-only cleanup). Testpaar: verse factuur TEST-AFLETTERPOC-INV1 (€153,67, geboekt →
open PaymentItem) + verse mutatie TEST-AFLETTERPOC-TX5 (−153,67) — `MatchedPaymentItem`
vulde direct automatisch (bevestigt het schrijf-PoC-beeld). Alles na afloop teruggedraaid
en eindstaat geverifieerd (factuur + 161-document op concept, TX weer open, geen open items).

### Hoofdconclusie

**De exacte koppel-body is óók in deze STAP-0 niet gevonden — maar de zoekruimte is nu
uitputtend in kaart en er zijn drie nieuwe feiten die de supportvraag en een volgende
UI-capture veel scherper maken.** Het assist-model blijft tot die tijd staan.

### Nieuwe feiten

1. **Volledige actie-inventaris op een PaymentTransaction (sweep Type 1–250, kaal):** alleen
   15 en 16 antwoorden `_InvalidData` ("van toepassing, data ontbreekt"), alleen **116, 160 en
   161** geven `204`; 148 `APIActions_NotApplicable`; ál het andere is 400-ruis. Er bestaat
   dus géén verborgen "accepteer matchvoorstel"-actienummer dat we gemist hebben.
2. **Het `ApiAction`-model heeft een ongedocumenteerd veld `PaymentItemList`.** Herkennings-
   probe: elk ander verzonnen veld (`Bogus`, `PaymentItems`, `PaymentReference`, `Document`,
   …) → `_InvalidData`; `PaymentItemList` → **204**. Sterker: `{Type:15, id:<guid>}` is
   `_InvalidData`, maar mét `PaymentItemList` erbij wordt dezelfde body geaccepteerd — de
   validatie leest het veld dus echt. **Maar het effect blijft in élke vorm uit** (OpenAmount,
   PaymentReferenceList en factuur onveranderd): entries als `{id}`, `{id, Amount}` (beide
   tekens), volledig item-object, vers item (PaymentStatus 1) én na id/Description-combinaties.
   Geen async effect (staat blijft ook later ongewijzigd).
3. **Actie 161 kaal ("Creëer en koppel nieuw document") wérkt financieel met Basic Auth:**
   204 → OpenAmount 0, `PaymentReferenceList` wijst naar een NIEUW aangemaakt, direct geboekt
   inkoopdocument (Status 3). Dat is dus een vals positief voor afletteren-tegen-open-post
   (onze factuur bleef gewoon open), maar het bewijst dat **auth niet de blokkade is**: de
   actions-route kan met de webservice-login boekhoudkundige effecten hebben. Actie 160
   ("Stel nieuw document voor") en 116 geven 204 zonder waarneembaar effect; 161-storno
   (actie 19 op het nieuwe document) zet OpenAmount terug en het matchvoorstel komt vanzelf
   terug — terugdraaipad dus geverifieerd.

### Overige uitsluitingen (deze ronde)

- Query-parameter-vormen (`?type=`, `?actionType=`, `?paymentItemId=`) en lege/array-bodies: 400.
- `PUT PaymentTransactions/{id}` met `PaymentReferenceList` naar de factuur: bindt niet
  ("request is invalid"); `IsImported: true` wordt stil genegeerd (blijft false) — een
  PUT-aangemaakte mutatie is en blijft Type 1/niet-geïmporteerd.
- BMDB-document als koppel-vehikel: `PUT BankMutationDirectBookings` met
  `PaymentReferenceList` → bindt niet; met `Entity` (crediteur) → `500 Onverwachte fout`
  (zelfde muur als document-`Entity` op het memoriaal, fallback-PoC).
- De systeemhuls (DocumentType 19) biedt zelf **geen** acties (`GET .../Actions` = leeg).
- `ActionKinds/{n}` geeft (nu) 404 op de admin-scope; de nummers komen uit
  `GET PaymentTransactions/{id}/Actions`.
- ⚠️ Bijvangst: na een koppel+storno-cyclus komt het PaymentItem terug met **PaymentStatus 4
  (PayCanceled)**; een vers item (status 1) vereist storno + herboeken van de factuur. Voor
  latere experimenten relevant — en mogelijk verklaart zo'n status-eis ook stille no-ops.

### Openstaande verklaring + vervolg

De UI-waarneming (204 mét koppeling aan een bestáánd document) is met Basic Auth niet
gereproduceerd. Meest waarschijnlijke verklaringen: (a) de UI stuurt een body-vorm die wij
niet geraden hebben (met `PaymentItemList` in een specifieke gedaante), of (b) de handler
gedraagt zich anders op echte geïmporteerde mutaties (Statement/afschrift-context — via de
API niet na te bootsen: `IsImported` niet zetbaar, geen Statements-write).

**Vervolg (concreet):**
1. Bij de eerstvolgende gelegenheid in de RLZ-UI de Koppelen-request **via DevTools →
   Network → Payload** capturen (geen fetch-interceptor nodig; "Copy as cURL" pakt de body
   mee). Nu we weten dat het veld `PaymentItemList` heet, is één blik op de echte payload
   waarschijnlijk genoeg.
2. Supportvraag aan RLZ aangescherpt met de `PaymentItemList`-ontdekking (zie de bijgewerkte
   conceptvraag onderaan dit document).
3. Tot die tijd: assist-model blijft; seam `app/bank/afletteren.py::voer_afletter_actie_uit`
   ongewijzigd.

### Afletteren betaal-kant — BODY GEVANGEN (9 augustus 2026, DevTools-capture Peter, Rubicon-UI)

De ontbrekende action-body van de UI-knop "Koppelen" (zie "Afletteren betaal-kant STAP-0"):

    POST /api/v1/{adminId}/PaymentTransactions/{txId}/actions   -> 204
    {
      "Type": 15,
      "PaymentItemList": [{ "id": "<PaymentItem-id>" }],
      "LinkedAmount": -151.25,
      "IsCompletelyPaid": false,
      "PaymentCorrectionMethod": 1
    }

Waargenomen op twee koppelingen (tx 19251249-… en 2ffa7259-…, beide 204, koppeling aantoonbaar
verwerkt). Duiding: actie 15 (LinkPaymentItems) was al die tijd het juiste nummer, maar hoort op
de PAYMENTTRANSACTION, niet op het document (alle eerdere _InvalidData-PoC's zaten op de
factuur-kant); `PaymentItemList` = de open post(en) — die id's syncen wij al
(payment_item_cache); `LinkedAmount` draagt het teken van de mutatie (afschrijving negatief);
`IsCompletelyPaid` en `PaymentCorrectionMethod` (hier false / 1) zijn vermoedelijk de
betalingsverschil-afhandeling — semantiek per STAP-0 vaststellen. NB de eerdere kale
`{Type:15}`-sweep gaf 204-zonder-effect: de extra velden zijn dus dragend. Initiator in de UI is
xhook.min.js (Reeleezee hookt zelf fetch/XHR — verklaart waarom onze in-page interceptor niets
ving). Vervolg: STAP-0 replay met Basic Auth op de TEST-administratie → daarna seam-swap
(voer_afletter_actie_uit). Ontkoppel-variant (vermoedelijk Type 16) in dezelfde STAP-0 vangen.

## Verkoopfactuur-boekpad STAP-0 — SalesInvoice mét Entity + creditvariant (9 augustus 2026) — GESLAAGD, mét twee nieuwe API-feiten

Blok 1e van de verkoopfactuur-bouw (koppelcontract §2d): live verificatie van wat de gedeelde
SalesInvoice-motor nieuw doet. Test-administratie, alles gestorneerd (actie 19); script
`verkenning/poc_verkoop_schrijf.py`, audit `output/verkooppoc_audit.jsonl`. De testdebiteur
"TEST-VERKOOPPOC Huurder" en twee PROBE-concepten blijven bewust staan (nooit verwijderen).

1. **Idempotente debiteur-aanmaak werkt volledig**: `GET Customers?$filter=Name eq '…'` ziet
   API-aangemaakte debiteuren (lookup-vóór-PUT dus betrouwbaar), `PUT Customers/{client-guid}`
   maakt aan, herhaal-PUT met zelfde GUID is een no-op. Patroon crediteur-aanmaken bevestigd.
2. **SalesInvoice mét `Entity` boekt gewoon** (PUT → actie 17 → Status 2, RLZ-nummering 90006);
   ⚠️ het kale `GET SalesInvoices/{id}` toont `Entity: null` — de debiteur is alleen zichtbaar
   mét `$expand=Entity` (hij stáát er wel; niet op het kale veld toetsen).
3. **Creditvariant bevestigd**: negatieve regelbedragen op dezelfde debiteur → concept
   `BaseInvoiceAmount -121.00`, actie 17 → Status 2, storno 19 → Status 1. Verkoopcreditnota =
   negatieve SalesInvoice, geen apart documenttype (consistent met de inkoopkant).
4. **⚠️ NIEUW API-FEIT — RLZ negeert de document-`Description` op SalesInvoices** en leidt hem
   af uit de ÉÉRSTE regel-Description (één regel zonder Description → document-Description
   null; twee regels → "regel een"; een kale herstel-PUT met alleen Description heeft géén
   effect). Gevolg: een duplicaat-marker die alleen op documentniveau gezet wordt landt nooit
   in de Receipts-collectie. **Dit raakte óók de omzetmotor** (de periode-omschrijving
   `OMZ-…-VK` stond alleen op documentniveau → de Receipts-duplicaatcheck-op-afstand kon nooit
   een treffer zien; de lokale DB-unieke periode-bewaking + memoriaal-Reference-check bleven de
   werkende waarborgen). Fix in beide motoren (2026-08-09): de deterministische marker staat nu
   als PREFIX in de Description van regel 1.
5. **`startswith(...)` én `contains(...)` werken als Receipts-`$filter`** — de duplicaatcheck
   filtert nu op `startswith(Description,'<marker>')`
   (`RlzClient.find_receipts_by_description_prefix`). De Receipts-collectie ziet ook
   entity-facturen (getest op id én Description). Marker-vormen zijn zelf-afsluitend tegen
   prefix-botsingen: verkoop `VASTLY-VERKOOP {nr} ·`, credit `VASTLY-CREDIT {nr} ·` (disjuncte
   soortprefix + terminator ná het nummer), omzet `OMZ-YYYYMMDD-YYYYMMDD-VK` (vaste lengte).

### Afletteren betaal-kant — REPLAY GESLAAGD, AFLETTEREN GEKRAAKT (9 augustus 2026, STAP-0-replay op de DevTools-capture)

Replay van de door Peter gevangen UI-body op de test-administratie (script
`poc_afletteren_betaalkant.py`, stappen setup/replay/deel/dicht/ontkoppel/cleanup; audit
`output/afletterpoc_audit.jsonl`; alles teruggedraaid met actie 19 — de kale test-TX'en
TX5/TX6 blijven bewust staan):

1. **De gevangen body werkt met Basic Auth** — auth was nooit de blokkade, de body-vorm was
   het: `POST PaymentTransactions/{tx}/Actions {Type: 15, PaymentItemList: [{id}],
   LinkedAmount: <teken van de mutatie>, IsCompletelyPaid: false, PaymentCorrectionMethod: 1}`
   → 204, `OpenAmount` −153,67 → 0 op mutatie én post, `MatchedPaymentItem` leeg,
   `PaymentReferenceList` wijst naar de échte factuur (DocumentType 1). Het gekoppelde
   PaymentItem verdwijnt uit de open-items-collectie.
2. **Deelbetaling (G-rekening-case) klopt exact**: `LinkedAmount` −50,00 op een post van
   −105,42 → mutatie-open −55,42, factuur `BasePaidAmount` 50,00 / `BaseRemainingAmount`
   55,42. ⚠️ **Het restant krijgt een NIEUW PaymentItem-id** — het oude id geeft daarna
   404 `_NotFound`; vóór elke koppeling verse open-items lezen.
3. **`IsCompletelyPaid: true` = betalingsverschil-afboeking**: restant-koppeling van −55,00
   op een post van 55,42 mét true → post DICHT (factuur Status 3, `BaseRemainingAmount` 0,
   betaald geregistreerd 105,00 — 0,42 afgeboekt als verschil), de mutatie houdt −0,42 open.
4. **`PaymentCorrectionMethod`**: niet read-only afleidbaar — het Help-model van `ApiAction`
   kent alléén id/Type/Description (alle vier de extra velden zijn ongedocumenteerd). Waarde
   gepind op 1 (de UI-waarde); nooit blind variëren.
5. **Ontkoppelen (Type 16) werkt NIET**: de capture-vorm geeft 204-zonder-effect, elke
   variant (referentie-id, positief bedrag, PaymentReferenceList, DocumentList, zonder
   LinkedAmount) geeft `400 _InvalidData`. Terugdraaien blijft **storno (actie 19)** van het
   gekoppelde document. ⚠️ Nieuw leesfeit: bij een méérvoudig/deels gekoppelde mutatie laat
   die storno de koppelingen als systeemhulzen (DocumentType 19, Status 1) op de mutatie
   achter — `OpenAmount` komt dan NIET volledig terug (TX6 bleef op −0,42); een enkelvoudige
   volledige koppeling (TX5) kwam wél volledig open. Reconciliatie-aandachtspunt.
6. **Consequentie (seam-swap 2026-08-09):** `app/bank/afletteren.py::voer_afletter_actie_uit`
   legt de koppeling nu écht via de API (`RlzClient.link_payment_item`) mét directe
   verificatie; assist = expliciete fallback bij een API-fout. Stap 1 (exacte match) lettert
   automatisch af in de bank-sync achter `bank_autoboeken_ingeschakeld` + eigen volumerem;
   stap 2 (deelmatch) blijft één-klik. De open supportvraag aan Reeleezee is hiermee
   **beantwoord door eigen capture** — een supportantwoord is alleen nog ter bevestiging.
7. **Randgeval 404 op "Nu afletteren" (kliktest Peter 2026-08-09 middag) — URL-casing
   uitgesloten:** de UI POST't naar `PaymentTransactions/{id}/actions` (kleine a), maar deze
   replay slaagde met `/Actions` (hoofdletter A, `post_raw_actions`) — de client staat dus al
   op de bewezen vorm en is daarop gepind (`tests/unit/test_rlz_client_afletteren_url.py`).
   De 404 kwam volledig uit de verouderde lokale staat: de mutatie was intussen in RLZ
   afgeletterd, waardoor het doel-PaymentItem uit de open-items-collectie was verdwenen
   (zie punt 2: verdwenen/vervangen item-id → `404 _NotFound`). Fix: vooraf-toets tegen de
   actuele RLZ-staat vóór elke link-call (`OpenAmount` 0 → "geverifieerd — al afgeletterd in
   RLZ", geen fout; post niet meer open → duidelijke fout vóór de call).

## Doorbelasting STAP-0 — tweezijdige motor gesimuleerd (13 augustus 2026, test-administratie) — GESLAAGD

BLOK 0b van de doorbelastingsbouw (besluit Peter 2026-08-13; canoniek patroon:
`verkenning/16_DOORBELASTING_KEMPEN.md` incl. de nieuwe §2c-spiegelkantverificatie via
Rubicon). Script: `verkenning/poc_doorbelasting_schrijf.py` (PoC-waarborgen: admin-pin,
kill switch, TEST-referenties, append-only audit `output/doorbpoc_audit.jsonl`, storno na
afloop — Facilities-productie is NIET beschreven). Alles tegen de test-administratie
`8dbfb856-…`; beide kanten gesimuleerd binnen die ene administratie (de motor gebruikt
straks twee administraties — de mechanics per kant zijn identiek).

1. **Idempotente crediteur-aanmaak + direct gebruik (de motor-voorwaarde voor de eerste
   spiegel per doelentiteit): WERKT.** `PUT Vendors/{uuid5}` met alleen `{id, Name}` →
   herhaal-PUT idempotent; de verse vendor is **direct** terugleesbaar via
   `Vendors?$filter=Name eq '…'` én direct bruikbaar als `Entity` van een PurchaseInvoice
   in dezelfde run (geen vertraging/verversing nodig). Debiteur-kant idem
   (lookup-vóór-PUT-patroon van `zorg_voor_debiteur` bevestigd).
2. **Bron-kant (Kempen-patroon exact): WERKT.** SalesInvoice mét Entity + twee regels —
   kostenregel met bron-referentie in de omschrijving van regel 1 (document-Description
   wordt daaruit afgeleid, bekend feit) + losse regel "Provisie 5% over nettobedrag",
   beide GB 8000 / 21% — boekt via actie 17 naar Status 2; `InvoiceNumber`/`Reference`
   (`RLZ-{nr}`) direct terugleesbaar. RLZ rekent het totaal zelf correct op (127,05 =
   105,00 netto + 22,05 btw).
3. **Spiegel-kant met gedeelde referentie: WERKT.** PurchaseInvoice met `Reference` = het
   verkoopnummer van de bron-factuur (zoals Rubicon de 247xxxxx-nummers van Facilities
   draagt, §2c) → boekt naar Status 2; de eigen duplicaatquery
   (`Entity/id eq … and Reference eq '…'`) vindt exact 1 treffer. **Volgorde-consequentie
   voor de motor:** het verkoopnummer bestaat pas ná het boeken van de bron-kant — de
   spiegel-referentie kan dus pas in stap 2 worden bepaald (bron eerst, dan spiegel; bij
   falen van de spiegel: storno bron of open taak, half-geboekt-patroon omzetmotor).
4. **Storno-cyclus beide kanten: WERKT.** Actie 19 in motor-volgorde (spiegel eerst, dan
   bron): beide documenten van Status 2 → 1 (concept), geen creditdocument (bekend gedrag).
5. **Rekeningschema-verschil bevestigd:** GB `4604` heet in de test-administratie "Kosten
   rechtsbijstandverzekering", bij Rubicon "Administratiekosten" — kosten-GB's zijn per
   administratie verschillend ondanks gelijke nummers. De motor mag de doel-kosten-GB dus
   nooit op nummer hardcoden: eerste keer per doelentiteit = mens kiest, daarna leert het
   boekingsgeheugen (conform opdracht blok 1c). TaxRate-GUID 21% (`1e44993a-…`) is wél
   administratie-overstijgend identiek (opnieuw bevestigd, nu ook in Rubicon).

## Projects-schrijfroute STAP-0 — PUT via Customers-route (14 augustus 2026, test-administratie) — GESLAAGD, CONCLUSIE §1 GECORRIGEERD

> ⚠️ **CORRECTIE (zelfde dag, screencheck Peter):** de conclusie in §1 hieronder — "de
> Customers-route is de enige schrijfvorm" — is FOUT gebleken. Peters browsercapture in de
> Universal-administratie + de Basic-Auth-hertest bewezen een klant-loze top-level
> `PUT {adminId}/Projects/{id}`, die de Help-lijst níét kent. De fout: deze PoC bewees dat de
> Customers-route wérkt, niet dat er geen andere bestaat, en de Help-lijst is géén volledig
> route-inventaris. Zie de sectie "Projects klant-loze schrijfroute (browsercapture Peter +
> hertest)" hieronder — die is leidend voor de motor. De overige feiten van deze STAP-0
> (create-or-update, IsActive-default false, customer-binding vía deze route, 404-foutpad)
> blijven geldig en zijn in de hertest herbevestigd.

Verificatie #3 uit het BOUWPLAN (route A, koppelcontract §5/§6.1 v1.14 — projectaanmaak
on-demand voor vastgoed). Script: `verkenning/poc_projects_schrijf.py` (PoC-waarborgen:
admin-pin, kill switch, TEST-naam, append-only audit `output/projectspoc_audit.jsonl`,
NOOIT DELETE). Alles tegen de test-administratie `8dbfb856-…`. Realisme vooraf bevestigd:
een project kent GEEN actie 19 (acties zijn document-gebonden) — het testproject
`TEST-PROJECTPOC Pand Dorpsstraat 1` (id `4861d1d3-f963-5d9a-b2c9-1ae876a1f676`) blijft
bewust staan, `IsActive` is aan het eind teruggezet op `true`.

1. **Schrijfroute bevestigd: `PUT {adminId}/Customers/{baseId}/Projects/{client-guid}`** met
   minimale body `{id, Name}` → **204** (lege respons — de motor leest het resultaat dus
   altijd terug met een GET ná de PUT). De Help-lijst (`output/help.html`) kent **géén
   top-level `PUT Projects/{id}`** — de Customers-route is de enige schrijfvorm; er bestaat
   ook een DELETE, die wij per hard principe nooit gebruiken.
2. **Het project is direct top-level zichtbaar**: `GET {adminId}/Projects/{id}` en de
   collectie tonen het record meteen (zelfde run, geen verversing nodig) — de bestaande
   lees-sync (`project_cache`) pikt API-aangemaakte projecten dus gewoon op, en de motor kan
   de cache direct zelf bijwerken.
3. **Het project is écht customer-gebonden — de baseId is géén decoratief route-anker**:
   `GET Customers/{andere}/Projects/{id}` → 404 `_NotFound`, en `$expand=Customer` op het
   project toont de eigenaar-customer volledig. Het kale projectrecord draagt geen
   Customer-veld — de relatie is alleen via `$expand` zichtbaar.
4. **PUT onder een niet-bestaande customer → 404 `_NotFound`, er ontstaat niets** (schoon
   foutpad, geen zwerfproject). De anker-customer moet dus bestaan vóór de project-PUT —
   lookup-vóór-PUT op de customer hoort in de motor.
5. **Herhaalde PUT met zelfde GUID + zelfde body → 204, géén duplicaat** (collectie blijft
   op 1 treffer). **PUT is create-or-update**: zelfde GUID met gewijzigde `Name` → 204 en
   de naam is aangepast. Idempotentie op deterministisch client-GUID werkt dus, maar een
   herhaal-PUT met afwijkende body muteert — de motor doet daarom lookup-vóór-PUT en PUT
   alleen bij afwezigheid (patroon debiteur-/crediteur-aanmaak).
6. **Defaults bij minimale body — LET OP: `IsActive` staat na aanmaak op `false`**
   (verder: `IsBillable:false`, `Description:"Onbekend"`, `BeginDate` = vandaag,
   `EndDate` = +5 jaar, budgetvelden leeg). De motor stuurt `IsActive: true` expliciet mee,
   anders is het project in RLZ onzichtbaar/inactief voor gebruik.
7. **`IsActive` is via PUT beide kanten zetbaar** (false → true → bevestigd in de respons):
   de archief-vlag is daarmee het correctiemechanisme voor projecten (geen storno mogelijk;
   "verwijderen" bestaat voor ons niet).

**Consequentie motorontwerp:** de aanvraag van vastgoed draagt geen customer, dus de motor
heeft per administratie een bestaand customer-anker nodig om de PUT-route te kunnen vormen.
Keuze + onderbouwing: zie docs/BESLISSINGEN.md "Route A — projectaanmaak" (systeemanker per
administratie, idempotent aangemaakt; bewust bespreekpunt richting Peter omdat het
kasomzet-besluit "geen dummy-debiteur" hier niet 1-op-1 opgaat — RLZ's route dwingt een
customer af). **Inmiddels BESLOTEN (Peter 2026-08-14)** — zie de nazorg-sectie
"Projectgebruik op vreemde documentregels" hieronder én BESLISSINGEN "Systeemanker route A".

## Projectgebruik op vreemde documentregels — route-A-nazorg (14 augustus 2026, test-administratie) — GESLAAGD

Nazorg-verificatie bij route A (opdracht Peter 2026-08-14): een pand-project hangt
noodgedwongen onder het systeemanker "Pandprojecten (systeem)" (de schrijfroute dwingt een
customer af — zie STAP-0 hierboven), maar het bestaansrecht van die projecten is
kostenregistratie op INKOOPfacturen van willekeurige leveranciers (kostenflow-omkering §3a:
pand = `project_id` per regel). De vraag: bindt RLZ een project regel-technisch aan zijn
customer? Script: `verkenning/poc_project_regelgebruik.py` (zelfde waarborgen; audit
`output/projectregelpoc_audit.jsonl`); alles tegen de test-administratie `8dbfb856-…`.

1. **Anker-binding bevestigd**: `Projects?$filter=Name eq 'TEST-ROUTE-A Pand Dorpsstraat 1'
   &$expand=Customer` → precies één hit, Customer = "Pandprojecten (systeem)"
   (`d2102424-9862-5254-8e54-87d4ef9fc706`, het route-A-live-verificatie-anker).
2. **Concept op een vreemde entiteit**: `PUT PurchaseInvoices/{client-guid}` met Entity = de
   bewezen PoC-vendor (`f7a74265-…`, níét het anker) en op de regel `Project:{id}` van het
   anker-gebonden project → **204**; teruglezen via `Lines?$expand=Account,Project` toont de
   volledige Project-ref op de regel. **RLZ legt géén entiteit-beperking op projectgebruik**
   — de customer-binding van de schrijfroute is puur een ophangpunt, geen scope.
3. **Boeken**: actie 17 → 204, Status 1→2; de Project-ref op de regel **overleeft het
   boeken** ongewijzigd.
4. **Storno** (testdata-afspraak v1.3): actie 19 → 204, Status 2→1; ref blijft ook dan
   staan. Testdocument `TEST-PROJECTREGELPOC-1` (id `dcd59047-2810-52aa-bf92-45e9eaad71d4`)
   blijft als concept staan (nooit verwijderen).

**Conclusie: route A's premisse is bewezen** — anker-gebonden projecten zijn onbeperkt
bruikbaar op documentregels van elke entiteit, vóór én ná boeken. De keerzijde (op het
anker zélf mag nooit geboekt worden) is dezelfde dag afgedwongen als blokkerende check:
`check_geen_ankerdebiteur` in het verkoop-checksrapport + fail-closed slot in
`zorg_voor_debiteur` (naam- én GUID-toets, vangt ook een in RLZ hernoemd anker) + de
whitelist-toets in de doorbelasting-checks (`app/projecten/anker.py` is de ene bron).

## Projects klant-loze schrijfroute (browsercapture Peter + hertest) — 14 augustus 2026 — WERKT, motor omgebouwd

Aanleiding: Peters live browsercapture in de Universal-administratie (derde UI-correctie op
een RLZ-aanname): de RLZ-UI maakt een project ZONDER klant aan via
`PUT https://apps.reeleezee.nl/api/v1/{adminId}/Projects/{guid}?$expand=*($levels=max)` → 200,
géén Customers-segment (testproject "TEST-LOSPROJECT screencheck", inmiddels inactief). De
capture droeg alleen method/URL/status (payload onbekend, UI = sessie-auth) — deze hertest
(`verkenning/poc_projects_toplevel.py`, Basic Auth, test-administratie `8dbfb856-…`, zelfde
PoC-waarborgen) beantwoordt de API-vorm. De STAP-0-conclusie "Customers-route is de enige
schrijfvorm" is hiermee gecorrigeerd (zie de correctie-kop dáár); les: **een geslaagde PoC op
route X bewijst nooit de afwezigheid van route Y, en de Help-lijst is géén volledig
route-inventaris** (WERKWIJZE v1.8 + registers/verbeteringen.md 2026-08-14).

1. **De route werkt via Basic Auth, minimale body**: `PUT {adminId}/Projects/{client-guid}`
   met `{id, Name}` → **204** (leeg; teruglezen met GET — zelfde patroon als elders). Géén
   `$expand`-query nodig; die in de capture bepaalt vermoedelijk alleen de responsvorm van
   de UI. Het project is direct top-level zichtbaar (collectie: 1 treffer).
2. **Het project is écht klant-loos**: `$expand=Customer` → `Customer: null`. De baseId van
   de Customers-route is dus een ophangpunt dat je wel of niet kiest — geen vereiste.
3. **`IsActive`-default opnieuw false** bij minimale body (verder identiek aan STAP-0:
   IsBillable false, Description "Onbekend", BeginDate vandaag, EndDate +5 jaar) — de motor
   blijft `IsActive: true` expliciet meesturen.
4. **PUT = create-or-update, idempotent op zelfde body** (herbevestigd): zelfde GUID + zelfde
   body → 204, collectie blijft 1; zelfde GUID + andere naam → 204 en de naam is gewijzigd.
   Lookup-vóór-PUT blijft dus verplicht in de motor.
5. **⚠️ NIEUW — harde naamlengte-limiet: 50 tekens** (kolom `PRJNAM`): 50 → 204, 51 →
   `400 "Waarde … voor kolom PRJNAM in tabel PRJ is te lang"`. De naamconventie-poort
   (`MAX_NAAM_LENGTE`) is van 120 naar 50 gezet zodat dit een deterministische 400
   `naam_ongeldig` naar vastgoed is i.p.v. een 502-RLZ-fout achteraf.
6. **Klant-loos gedraagt zich op documentregels identiek aan anker-gebonden**: concept-
   PurchaseInvoice op de bewezen PoC-vendor met het project op de regel → 204; ref intact
   ná boeken (17) én storno (19). ⚠️ Opvallend: het project stond tijdens deze hele cyclus
   op `IsActive: false` — **RLZ weigert een inactief project niet op documentregels via de
   API** (relevant voor toekomstige eigen checks; de RLZ-UI verbergt inactieve projecten
   vermoedelijk alleen). Testdocument `TEST-LOSPROJECTPOC-1` blijft als concept staan.
7. **De top-level PUT werkt óók als update op een vía de Customers-route aangemaakt project**
   (TEST-ROUTE-A op IsActive:false gezet); de bestaande customer-binding blijft daarbij
   intact — de twee routes muteren hetzelfde record.
8. **⚠️ Customer archiveren kan NIET via de API**: `PUT Customers/{id}` met `IsArchived: true`
   én met `RecordStatus: 1` geven beide 204 maar het record verandert niet (stil genegeerd).
   Het anker "Pandprojecten (systeem)" in de test-administratie blijft daarom bestaan
   (nooit verwijderen); deactiveren kan alleen een mens in de RLZ-UI.

**Consequentie motor (gebouwd zelfde dag):** `RlzClient.put_project` (top-level) vervangt
`put_customer_project`; het systeemanker verdwijnt uit het aanmaakpad (geen
`zorg_voor_anker_customer` meer), de anker-checklaag (`app/projecten/anker.py`) blijft als
vangnet zolang er ergens een anker-debiteur bestaat. Koppelvlak §5 extern ongewijzigd.
Opruiming teststand: hertest-project + `TEST-ROUTE-A Pand Dorpsstraat 1` op IsActive:false
(archief-vlag = het correctiemechanisme voor projecten); concept-PoC-documenten
(`TEST-PROJECTREGELPOC-1`, `TEST-LOSPROJECTPOC-1`) blijven conform testdata-afspraak v1.3
als concept staan.

## DocumentCategory & boekstuk-reeksen — kliktest-nazorg doorbelasting (16 augustus 2026) — GEVERIFIEERD

Aanleiding: kliktest-bevinding Peter (spiegel-inkoopfacturen niet zichtbaar onder RLZ-UI
"Inkopen/uitgaven", doorbelasting-verkoopfacturen niet onder "Verkopen/facturen"), met als
werkhypothese "DocumentCategory ontbreekt" (omzetmodule-les). **De hypothese is weerlegd** —
read-only vergelijking over Facilities, Molenhof Beheer, Rubicon en de test-administratie,
plus één schrijfexperiment (TEST-DOORB-CAT-01, test-administratie, geboekt + gestorneerd):

1. **RLZ kent zélf een DocumentCategory toe** aan API-geboekte documenten zonder expliciete
   categorie. PurchaseInvoices krijgen een per administratie afgeleide type-1-categorie
   (Facilities/doelen: "Overige kosten"; test-administratie bij GB 4302: "Verkoopkosten" —
   de afleiding verschilt dus per administratie/GB, er is geen vaste default). SalesInvoices
   mét Entity krijgen automatisch **"Verkoopfactuur (Omzet)" (type 10)** — exact dezelfde
   categorie als Peters eigen (UI-)verkoopfacturen, incl. de historische
   doorbelasting-facturen van Facilities.
2. **Het boekstuknummer-prefix (`RLZ-XX-…`) volgt de categorie, niet het documenttype**:
   "Overige kosten" → `RLZ-04`, "Algemene kosten" → `RLZ-17`, "Verkoopfactuur (Omzet)" →
   `RLZ-01`, memoriaal → `RLZ-06`, bank → `RLZ-07`, btw-aangifte → `RLZ-05`. Het volgnummer
   erachter is één administratie-brede reeks (opeenvolgende boekingen in verschillende
   prefixen kregen …2027 en …2028). UI-geboekte facturen met "Overige kosten" krijgen óók
   `RLZ-04` — het prefix onderscheidt dus NIET "API vs UI".
3. **DocumentCategory is op PurchaseInvoices gewoon PUT-baar** (body
   `DocumentCategory: {id: …}`, zelfde vorm als SalesInvoices), overleeft boeken en stuurt
   het prefix (experiment: expliciet "Algemene kosten" → `RLZ-17-00002027`).
4. **De spiegel-inkoopfacturen van de motor zijn identiek aan Peters historische praktijk**:
   de échte 2025/2026-spiegels in Rubicon (crediteur Kempen Facilities, referentie =
   verkoopnummer) dragen óók "Overige kosten" + `RLZ-04`. Er valt aan de spiegel-kant dus
   niets te "repareren" met een categorie.
5. **Verkopen → Facturen-lijst**: de niet-vindbaarheid van API-verkoopfacturen dáár is
   consistent met het bestaande feit dat de SalesInvoices-COLLECTIE API-aangemaakte facturen
   niet ziet (Omzetmodule STAP 0 §2); GET-op-id werkt wel, en de Receipts-collectie (RLZ-UI
   "Verkopen → Boekingen") ziet ze wél. Met een categorie is dat niet te veranderen —
   vervolgpad is een screencheck/browsercapture van de Facturen-lijst-request of een
   supportvraag.

NB leesspoor kliktest zelf: de vijf bron-verkoopfacturen van de kliktest (24713188–24713192)
zijn ná Peters storno volledig uit RLZ verdwenen (404 op GET-op-id, geen treffer in de
Receipts-collectie op datum of omschrijving) — verwijderen kan alleen een mens in de RLZ-UI
en alleen op een concept, wat indirect bevestigt dat de storno ze eerst naar Status 1 zette.
De vijf spiegel-inkoopfacturen staan alle vijf geverifieerd op Status 1.

## Actie 19 in een periode met ingediende btw-aangifte — GEEN weigering; RLZ verschuift de btw zelf (16 augustus 2026, test-administratie) — GESLAAGD

Vraag Peter (15-08): wat doet RLZ bij een storno op een document in een periode waarvan de
btw-aangifte al is ingediend? Drie schrijfexperimenten tegen de test-administratie
(TEST-STORNO-AANGIFTE-01/-02/-03, alle drie als concept achtergelaten conform
testdata-afspraak):

- **Aangifte-leesroute**: `GET TaxDeclarations` (DocumentType 7) per administratie;
  `StartDate`/`Date` = periode, statusmodel analoog aan documenten: **1 = concept,
  2 = ingediend/open, 3 = afgehandeld**. `GET TaxDeclarations/{id}/TaxSources` = de
  bron-regels (per document: NetAmount/TaxAmount/DocumentType/VATSourceCategory).
  Test-administratie: 2023-Q1 = Status 2; 2018-Q3 en ouder = Status 3.
- **Boeken in een ingediende periode wordt NIET geweigerd**: PUT + actie 17 met
  `Date: 2023-02-15` (Q1-2023 ingediend) → 204/geboekt. `BookDate` wordt de systeemdatum
  (vandaag), `Date` blijft de factuurdatum. **De TaxSource landt automatisch in de
  eerstvolgende NIET-ingediende aangifte-periode** (onze +2,10 verscheen in de
  2023-Q2-aangifte, niet in Q1) — RLZ's ingebouwde suppletie-verschuiving.
- **Actie 19 wordt NIET geweigerd — geen foutcode, geen melding**: 204 en Status 1, in álle
  drie varianten: inkoopfactuur in een Status-2-periode, inkoopfactuur in een
  Status-3-periode (2018-Q3) én verkoopfactuur in een Status-2-periode. De ingediende
  aangifte zelf blijft ongewijzigd: RLZ verwerkt de terugdraai als **negatieve TaxSource in
  de eerstvolgende open periode**. Historisch bewijs in de test-administratie: de
  Q2-2023-aangifte draagt negatieve spiegel-sources (−93,73 / −160,68 / −67,50, gedateerd
  2023-03-31) die exact de ingediende Q1-posten spiegelen — storno's van ná de indiening.
  Stond de source al in een open periode, dan verdwijnt hij bij storno gewoon (geen
  negatieve rij).

**Consequentie app**: de geplande foutvertaling ("storno geweigerd: periode zit in een
ingediende btw-aangifte") vervalt — er ís geen RLZ-fout om te vertalen, dus ook het
alles-of-niets-risico voor de doorbelasting-storno (één kant geweigerd → half) kan uit deze
hoek niet ontstaan. De boekhoudkundige keerzijde is reëel: zo'n storno creëert stil een
suppletie-effect in de eerstvolgende open aangifte. Signalering daarvan (pre-storno-
waarschuwing op basis van TaxDeclarations-status + het suppletie-signaal > € 1.000 + het
tegenboek-pad) is bewust GEPARKEERD voor een eigen ontwerp-/UX-ronde — zie BESLISSINGEN
"Doorbelasting-kliktest-nazorg ronde 2".

## Her-PUT op een bestaand concept VERVANGT DocumentLineList (16 augustus 2026, test-administratie) — GESLAAGD

Aanleiding: de kliktest-herstart van TEST-ONB-KLIKTEST-01. De vijf spiegel-inkoopfacturen
staan ná Peters storno nog als concept (Status 1) in de doel-administraties; een nieuwe
doorbelasting-run doet via de motor-idempotentie (GET-op-eigen-GUID → Status niet 2/3 → PUT)
een **her-PUT op hetzelfde deterministische GUID mét DocumentLineList**. Nergens was
geverifieerd of RLZ die regels dan vervángt of stápelt (dubbele bedragen). Experiment
(poc_herput_en_aangiftepoort.py `herput`, PurchaseInvoice TEST-HERPUT-01,
0bd2d2d1-741b-5b9d-a6fe-23d99bb92e6d):

1. PUT (2 regels, € 12,71 incl.) → boek 17 → Status 2, 2 regels.
2. Storno 19 → Status 1, regels intact (consistent met het bekende actie-19-gedrag).
3. **Her-PUT zelfde GUID, zelfde DocumentLineList → nog steeds 2 regels, € 12,71** — geen
   stapeling; boek 17 → Status 2, bedragen correct; afgesloten met storno 19 (concept blijft
   staan, testdata-afspraak).
4. **Bewijs vervang-semantiek** (niet slechts idempotentie): her-PUT op het concept met een
   ÁNDERE regelset (1 regel, € 8,47 incl.) → document draagt daarna exact 1 regel, totaal
   € 8,47. PUT op een bestaand document vervangt de DocumentLineList dus integraal.

Consequentie: de herstart van een doorbelasting-run over bestaande concept-spiegels heen is
veilig (correcte bedragen, ook bij een gewijzigde verdeling); hetzelfde geldt voor elk
retry-/her-PUT-pad in de motoren.

## Aangifte-leesroute + bankdocument-datum voor de storno-poort (16 augustus 2026) — bevestigd

Voor de storno-blokkade ná ingediende btw-aangifte (besluit Peter 15-08, zie BESLISSINGEN):

- `GET TaxDeclarations` (test-administratie, 54 rijen): elke rij draagt `Status`
  (1 concept / 2 ingediend / 3 afgehandeld) + `StartDate`/`Date` als periodegrenzen; geen
  enkele ingediende rij zonder leesbare periode. Leesroute in de client:
  `RlzClient.list_tax_declarations`; poort: `app/rlz/aangifte.py` (fail-closed).
- `BankMutationDirectBookings`-documenten dragen een bruikbaar `Date`-veld (afgeleid van de
  transactiedatum) — de bank-storno-poort toetst dáárop; ontbreekt het veld dan blokkeert de
  poort fail-closed.

## Uploads bij een herstart-boekcyclus — /Uploads kent GÉÉN her-PUT (16 augustus 2026, test-administratie + productie-waarneming) — GESLAAGD

Aanleiding: kliktest 2 van TEST-ONB-KLIKTEST-01 strandde per doelentiteit op
`PUT SalesInvoices/{id}/Uploads/{uploadId}` → **404 `_NotFound`** — direct ná een geslaagde
her-PUT van het document zelf. Reconstructie: Peter had de vijf bron-verkoop-concepten van
cyclus 1 handmatig in de RLZ-UI verwijderd; run 2 herschiep het document via PUT op het
deterministische GUID (dat werkt), maar het deterministische upload-GUID was in cyclus 1 al
verbruikt. De aanname in `rlz_ids.py::rlz_upload_id` ("een retry ... overschrijft (PUT)
dezelfde bijlage") was nooit tegen de live API getest en is FOUT.

Experiment (poc_upload_herstart.py, PurchaseInvoice TEST-HERPUT-01, mini-PDF's):

1. **`GET .../Uploads` is een betrouwbare aanwezigheids-check**: 200 + lijst (0 → 1 → 2
   correct meegegroeid), werkt op PurchaseInvoices, SalesInvoices (leeg bevestigd op de
   herschapen productie-concepten) én ManualJournals (read-only geverifieerd), in concept-
   én geboekte staat.
2. Upload met een vers GUID → 204 (zoals bekend).
3. **HER-PUT op een bestaand upload-GUID (levend document) → `400 _InvalidData`** — géén
   overschrijven; het document houdt de oorspronkelijke bijlage (FileName ongewijzigd).
4. Een **tweede bijlage naast de eerste** (vers GUID) → 204, lijst = 2 — meerdere bijlagen
   per document kunnen dus wél.
5. **Bijlagen overleven boek (17), storno (19) én een her-PUT van het document** (die
   vervangt alleen de DocumentLineList — lijst bleef 2).
6. Productie-waarneming (run 2, Facilities): een upload-GUID dat verbruikt is op een
   intussen VERWIJDERD document geeft op het herschapen document **404 `_NotFound`** (dus
   400 = GUID bestaat nog, 404 = GUID verbruikt-en-weg; beide betekenen "onbruikbaar").

Consequentie (fix zelfde dag): bijlage-idempotentie loopt via de LEESROUTE, niet via
PUT-overschrijven — `app/rlz/bijlage.py::zorg_voor_bijlage` (alle vier motoren: inkoop,
verkoop/omzet, memoriaal, doorbelasting-spiegel): bijlage al aanwezig = overslaan (dekt de
herstart op een storno-concept én de crash-retry); lijst leeg → PUT met het basis-GUID; bij
400/404 door naar een deterministisch cyclus-GUID (`uuid5` over het basis-GUID, begrensd op
5 cycli, daarna zichtbare fout). Onleesbare Uploads-lijst = fail-open naar gewoon uploaden
(een dubbele bijlage is cosmetisch, een gestrande boeking niet).
