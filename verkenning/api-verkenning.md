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

Achtergebleven testdocumenten uit dit experiment (nooit verwijderd, alle concept ná stornering):
vendor `f56b1c00-856e-41d2-a400-894e090f1251`; facturen A (`fe46f0d6-9b34-406d-8cd4-f55e603c2e26`,
`TEST-DUP-A`, geboekt geweest + gestorneerd), B (`14e1b412-d367-4ad1-bc08-ff5537ae10bf`,
`TEST-DUP-A`, geboekt geweest + gestorneerd), C (`4f5ff019-f85f-4785-9383-50abb6cbfcda`,
`TEST-DUP-CONTROL`, nooit geboekt).

## Rate-limit-observatie (5 juli 2026, tegen BLOw B.V, read-only)

20 opeenvolgende `GET Ledgers`-requests, sequentieel (geen parallelisme): alle 200, gemiddeld
3,2 req/s volgehouden over 6,16s, **geen enkele rate-limit- of `Retry-After`-header** in de
responses (niet bij succes, dus onbekend of ze bij een 429 wél verschijnen). Geen throttling
opgetreden bij dit tempo. Dit is een lichte, niet-agressieve steekproef — geen poging gedaan om de
daadwerkelijke bovengrens te vinden (BLOw is een productieadministratie van een echte klant, geen
testomgeving om tegen te stresstesten). De ingebouwde client (`app/rlz/client.py`) doet sowieso
altijd exponentiële backoff + respecteert een eventuele `Retry-After` op 429/5xx — voldoende
robuust voor nu, los van het exacte cijfer.

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
