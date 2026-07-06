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
5. Beschikbare acties per factuur: 17 Book, 34 Factuur verrekenen, 109 Kopieer; collectie-acties: 133 Document berekenen, **138 "Bepaal of factuur al bestaat" (duplicaatcheck — gebruiken voor idempotentie!)**; verder ActionKind 15/16 LinkPaymentItems/UnlinkPayment (afletteren), 19 Correct
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

### Actie 138 (duplicaatcheck) — payload-vorm nog steeds onbekend

Blijft een open punt (was al onbekend terrein, zie boven). `POST PurchaseInvoices/Actions` met
`{Type: 138}` geeft in elke geprobeerde vorm **`400 _InvalidData`**:
- `{Type: 138, Reference: "..."}` (criteria-vorm)
- `{Type: 138, Entity: {id}, Reference: "..."}`
- volledige documentvorm (`Entity` + `DocumentLineList` + `Reference`) met `Type: 138`
- kale `{Type: 138, Description: "..."}`

De Help-pagina (`GET Help/Api/POST-adminId-PurchaseInvoices-Actions`) documenteert alleen de
generieke `ApiAction`-vorm (`id`, `Type`, `Description`) — geen schema specifiek voor actie 138.
Duplicaatcheck is daarmee **nog niet inzetbaar als idempotentie-hard-rule** in de bouwlaag; de
`write_integration`-test laat deze stap nu non-blocking falen (loggen, niet hard assert) zodat de
rest van de flow (17/19) wél getest kan worden. **Actie: navraag bij Reeleezee-support over het
exacte requestschema voor ActionKind 138**, of reverse-engineeren via de RLZ-webinterface
(netwerktab) tijdens een handmatige duplicaatcheck.

## Rate-limit-observatie (5 juli 2026, tegen BLOw B.V, read-only)

20 opeenvolgende `GET Ledgers`-requests, sequentieel (geen parallelisme): alle 200, gemiddeld
3,2 req/s volgehouden over 6,16s, **geen enkele rate-limit- of `Retry-After`-header** in de
responses (niet bij succes, dus onbekend of ze bij een 429 wél verschijnen). Geen throttling
opgetreden bij dit tempo. Dit is een lichte, niet-agressieve steekproef — geen poging gedaan om de
daadwerkelijke bovengrens te vinden (BLOw is een productieadministratie van een echte klant, geen
testomgeving om tegen te stresstesten). De ingebouwde client (`app/rlz/client.py`) doet sowieso
altijd exponentiële backoff + respecteert een eventuele `Retry-After` op 429/5xx — voldoende
robuust voor nu, los van het exacte cijfer.
