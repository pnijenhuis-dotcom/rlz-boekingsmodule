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

1. Exacte payloadstructuur `PUT PurchaseInvoices/{guid}` + regels + boek-action (welke action-naam).
2. Hoe `BankMutationDirectBookings` aan een statement-regel gekoppeld wordt.
3. Afletteren: `QuickPaymentSelections`-flow bevestigen.
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

### 5. Afletteren: acties 15/16 + PaymentItems (payload nog te verifiëren, fase 2)

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
