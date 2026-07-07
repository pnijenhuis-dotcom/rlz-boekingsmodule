# Doorbelasting Kempen Facilities B.V. (live verkenning, 7 juli 2026)

> Genummerd 16 i.p.v. 13: `13_UPDATE_AAN_VASTGOEDPROJECT.md` bestaat al met dat nummer.
> Alle data via KEMPEN_*-login (`GET .../{adminId}/...`, administratie
> `7bc1e33a-8860-40d7-aef3-08ecad3ad7cf`), read-only. Rechten van deze login zijn tijdens de
> sessie aangepast door Peter (eerst 403 op alles behalve Administrations/TaxRates); na de
> aanpassing volledige leestoegang.

## 0. Belangrijke beperking: geen spiegelkant-verificatie mogelijk

**Stap 2c (spiegelkant in 2 doelentiteiten: crediteur Facilities, kosten-GB's, btw) is niet
uitgevoerd.** KEMPEN_* ziet uitsluitend Kempen Facilities B.V. zelf — geen enkele login in
`verkenning/.env` heeft toegang tot de doelentiteiten (Veldhoven Recreatie, Oirschot Recreatie,
Molenhof Beheer/Verhuur, Kempen Chalets, enz.) als eigen administratie. Elk account bleek bij
navraag single-administratie (bevestigd via `list_administrations()` voor alle vijf accounts in
`.env` — RLZ_*, UNIVERSAL_*, TESTADMIN_* zien ook elk precies één administratie). Actie: Peter
levert webservice-logins voor minimaal 2 doelentiteiten aan als de spiegelkant alsnog geverifieerd
moet worden — tot die tijd is alles hieronder eenzijdig (alleen de Facilities-boeking), niet de
volledige journaalpost aan de andere kant.

## 1. Kempen Facilities B.V. en de doelentiteiten

Administratie-GUID: `7bc1e33a-8860-40d7-aef3-08ecad3ad7cf`. `GET Customers` in deze administratie
geeft 21 records; op adres (Jansbuitensingel 29 Arnhem / Ekkersrijt 2012 Son en Breugel / Banstraat
25 Veldhoven) en e-mail (`facturen@kempengroep.nl`) zijn minimaal deze groepsentiteiten te
herkennen als doorbelastingsdoel (naam — customer-GUID binnen Facilities):

| Doelentiteit | Customer-GUID (in Facilities) |
|---|---|
| Veldhoven Recreatie B.V. | `c997e324-bfda-4a84-afc7-a416d367db3a` |
| Oirschot Recreatie B.V. | `f0ce5e77-ca6b-48e1-bd00-325cf635c7ec` |
| Molenhof Beheer B.V. | `cc58e167-4c6b-4d31-91ea-573ad6b616fa` |
| Molenhof Verhuur B.V. | `5027c79b-f6de-4b67-80db-867028ac35c0` |
| Kempen Chalets B.V. | `f5d427fa-2d63-4b19-bdb0-e3120fcbd92b` |
| Oirschot Vastgoed Beheer B.V. | `c945e48e-b92f-4328-97f8-7c088155989e` |
| Mantelzorgwoning Midden Nederland B.V. | `90dbadcb-5066-4822-a374-0b454a4a9180` |
| Rubicon Investments B.V. | `2f432363-127b-40e4-b331-ea8c03d4653d` |

(Let op: dit zijn de Customer-GUID's *binnen Facilities' eigen boekhouding*, niet de
RLZ-administratie-GUID van die entiteiten zelf — bijv. Rubicon Investments B.V. heeft hier een
Customer-record met een ander GUID dan zijn eigen administratie `be5e66b3-…`.)

Overige Customers in de lijst (Arvum B.V., Boscafé Molenvelden, Bouwadvies Oost Nederland,
Recradroom, SaaSIT, Stichting BenMax, Universal Nederland, Zilver Beheer, Kempen Airco, Kempen
B.V., Midden Nederland Beheer — twee varianten met/zonder punten in de naam) zijn niet onderzocht;
sommige zijn mogelijk externe klanten van Facilities, geen doorbelastingsdoel.

## 2. Hoe worden doorbelastingen nu geboekt in Facilities?

### 2a/2b — SalesInvoices: het patroon is per origineel inkoopdocument, niet per percentage-vlak

`GET SalesInvoices` telt **2.281 documenten** in deze administratie (`$count`). Header-conventie:
`"Door te belasten <ENTITEITCODE>"` (bijv. `VELDR` = Veldhoven Recreatie, `OIRR` = Oirschot
Recreatie, `MZM`, `MOLB`, `MOLV`), soms `"Door te belasten Nader te bepalen"` wanneer de
doelentiteit nog niet vaststond op boekmoment.

**Huidig patroon (juli 2026)** — voorbeeld factuur `24713012` aan Veldhoven Recreatie B.V.
(`Entity` via `$expand`), regels via `SalesInvoices/{id}/Lines?$expand=Account,TaxRate`:

```
Header: "Door te belasten VELDR"
Description: "Marketing Meer Leisure 2026-0264 Veldhoven"
Regel 1: "Marketing Meer Leisure 2026-0264 Veldhoven"   net=2549.00  Account 8000 (Omzet 1)  TaxRate 21% hoog
Regel 2: "Provisie 5% over nettobedrag"                  net= 127.45  Account 8000 (Omzet 1)  TaxRate 21% hoog
```

Dit patroon is **100% consistent** over een steekproef van 40 recente facturen (86 regels): elke
regel — kostenregel én provisieregel — wordt geboekt op **exact dezelfde grootboekrekening 8000
"Omzet 1"** en met **exact hetzelfde vlakke btw-tarief 21% hoog** (`1e44993a-…`), ongeacht de aard
van de onderliggende kosten (techniek, tuinonderhoud, marketing, zwembadonderhoud, IT). Dat is een
concrete afwijking van "tariefvolgend": het onderliggende inkooptarief (soms ook 21%, maar in
principe zou bijv. een laag-tarief product een andere rubriek raken) wordt **niet** doorgezet —
Facilities factureert de doorbelasting altijd op het hoge tarief, ongeacht de btw-behandeling van
de onderliggende inkoop.

**Provisie is een aparte regel, geen opslag in de eenheidsprijs**: steekproef van 40 facturen →
40 provisieregels (1 per factuur), altijd 5% over het netto kostenbedrag van diezelfde factuur.

### Ontwikkeling in de tijd — het verzamelniveau is veranderd

Het huidige "1 origineel document = 1 doorbelastingsfactuur"-patroon is **niet** hoe het altijd
ging. Oudere data laat een duidelijke evolutie zien:

- **H2 2024**: maandverzamelfacturen per entiteit, gesplitst naar **kostensoort**
  ("Betreft: Veldhoven investeringen Juli 2024", "Betreft: Molenhof beheer Investeringen kosten
  September 2024") — één factuur per maand per entiteit met een vrije-tekstlijst van onderliggende
  leveranciersfacturen (datum + naam + bedrag) in de Description, soms met forse
  correctie-verzamelfacturen achteraf (bijv. "Kempen Chalets Investeringen correctie mrt -
  September 2024" — € 18.877; "Molenhof beheer Investeringen kosten Augustus 2024" — € 273.595,47).
  Hier was een expliciet onderscheid **investeringen vs. lopende kosten** (twee aparte
  factuurstromen), en het verzamelniveau was **niet per origineel document** maar batch-per-maand.
- **Januari 2025**: overgang zichtbaar — nog steeds gebundelde facturen (tot ~15 onderliggende
  documenten per factuur), maar nu wél met een 5%-provisieregel aan het eind. Het
  investeringen/kosten-onderscheid is dan al verdwenen (bijv. "KC052 investeerder door belasten"
  staat gewoon als vrije tekst ín een reguliere kostenregel).
- **Vanaf medio 2025/2026** (steekproef): granulariteit verder verfijnd tot **1 origineel document
  = 1 doorbelastingsfactuur**, met de vaste 2-regelstructuur (kosten + provisie).

**Consequentie voor het datamodel**: het collectieniveau is bewijsbaar niet stabiel over de tijd —
een boekingsgeheugen/mapping die uitgaat van "altijd per-losse-inkoopfactuur" klopt voor het
huidige patroon maar niet voor historische data (H2 2024), en zelfs de huidige situatie is het
resultaat van minstens twee eerdere procesveranderingen. Aanname bij het bouwen: **huidig
(granulair, per-document + vaste 5%) is leidend voor nieuwe boekingen**, historie is
archiefmateriaal, geen sjabloon.

### RC-rekeningen (2b, "check op RC-/memoriaalstromen")

Facilities' rekeningschema bevat een eigen rekening-courant-rekening **per groepsentiteit**
(gevonden via `GET Ledgers?search=RC`, AccountType 4 — zie §3 voor de AccountType-classificatie):

| Rekening | Omschrijving |
|---|---|
| 1602 | RC Oirschot Recreatie BV |
| 1603 | RC Veldhoven Recreatie BV |
| 1604 | RC Molenhof Beheer BV |
| 16041 | RC Molenhof Verhuur BV |
| 16042 | RC Oirschot Vastgoed Beheer BV |
| 16043 | RC Dimo Living en Styles |
| 16044 | RC Necol Beheer B.V. |
| 16045 | RC Kempen Chalets BV |
| 16046 | RC Rijnvallei Beheer B.V. |
| 16047 | RC Midden Nederland Beheer B.V. |

**Bevinding, geverifieerd via `JournalEntryLines?$filter=Account/AccountNumber eq '1603'
&$expand=JournalEntry`**: de debiteurenkant van de doorbelastings-SalesInvoices aan groepsentiteiten
wordt **niet** geboekt op de generieke systeemrekening "1200 Debiteuren", maar rechtstreeks op de
RC-rekening van die entiteit. De `JournalEntry.DocumentType` van deze RC-boekingen is **10**
(SalesInvoice) — het is dus geen apart/parallel memoriaal-verrekeningscircuit, maar de intercompany
RC-rekening functioneert **als vervangende debiteurenrekening** voor groepsklanten: afhandeling
loopt via de lopende rekening-courant, niet via een aparte betaling/aflettering. Dit is relevant
voor de boekingsmodule: **voor intercompany-doelentiteiten is de "afgeletterd"-status niet de juiste
graadmeter voor afgehandeld** — het saldo leeft door op de RC, wordt niet per factuur vereffend.

### 2e — Personeel en investeringen apart?

- **Personeel**: geen enkele hit op "salaris", "loon" of "personeel" in `SalesInvoices.Description`
  (steekproef + gerichte `$filter contains(...)`). Personeelskosten (grootboek 4000-serie,
  AccountType 2 "Personeelskosten") lijken dus **niet** te worden doorbelast via dit
  SalesInvoice-mechanisme — ze blijven in Facilities' eigen resultaat. Niet geverifieerd: of
  personeelskosten via een geheel ander mechanisme (bijv. jaarlijkse handmatige verrekening,
  buiten RLZ om) alsnog aan entiteiten worden toegerekend — dat valt buiten wat in de API zichtbaar
  is.
- **Investeringen**: in H2 2024 (zie hierboven) wél een apart label/factuurstroom
  ("Investeringen kosten"), inmiddels verdwenen — in de huidige (2025/2026) documenten staat een
  investeringspost gewoon tussen de reguliere doorbelaste kosten (bijv. "Bol.com … KC052
  investeerder door belasten" als vrije tekst in een gewone kostenregel, `Account 8000`, geen apart
  activa-/investeringslabel of -rekening zichtbaar op de Facilities-kant). Zonder de spiegelkant
  (§0) kan niet worden geverifieerd of de doelentiteit dit bedrag activeert (vaste activa,
  AccountType 3) of als kostenpost boekt.

## 3. AccountType als bruikbaar "soort"-veld (relevant voor Grootboek-koppeling, §4 van dit
   antwoord aan vastgoed)

Bijvangst, direct bruikbaar voor de Grootboek-koppeling (OPEN_ITEMS "Grootboek-koppeling"): het
`Ledgers`-endpoint geeft een veld **`AccountType`** dat oud maar consistent een kosten/opbrengst/
activa/passiva-classificatie geeft — geen afgeleid/geraden veld nodig. Verificatie: volledige
`GET Ledgers` in Facilities (379 rekeningen) gegroepeerd op `AccountType`:

| AccountType | Betekenis (afgeleid uit rekeningnamen) | Voorbeeld |
|---|---|---|
| 1 | Opbrengsten | 8000 Omzet 1, 81 Diverse opbrengsten |
| 2 | Kosten | 40 Personeelskosten, 4000 Brutosalarissen |
| 3 | Activa (balans) | 00 Vaste activa, 1003 Bankrekening 3, 1200 Debiteuren |
| 4 | Passiva/vermogen (balans) | 05 Eigen vermogen, 1602 RC Oirschot Recreatie BV, 1700 BTW ontvangen hoog |

Zie taak 3 hieronder voor bevestiging dat dit ook in Rubicon geldt.

## 4. Voorstel-datamodel voor doorbelasting (concept, ter bespreking)

Op basis van het **huidige** (2025/2026) patroon:

```
doorbelasting_regel
  id (uuid, client-gegenereerd)
  bron_administratie_id      -- Facilities
  bron_document_type          -- 'PurchaseInvoice' | ...
  bron_document_referentie    -- InvoiceReference/Reference van de originele inkoopfactuur
  bron_leverancier_naam        -- vrije tekst, zoals nu in Description (geen eigen leverancier-FK
                                  in de RLZ-data zichtbaar op de sales-kant)
  doel_administratie_id        -- doelentiteit (uit registers/entiteiten.md-achtig register)
  doel_customer_guid_in_bron    -- Customer-GUID zoals gebruikt in Facilities' SalesInvoices.Entity
  net_bedrag
  provisie_percentage          -- vast 5% in de steekproef; behandel als config, niet hardcoded
  provisie_bedrag
  btw_tarief                   -- vlak 21% hoog, ONAFHANKELIJK van onderliggend inkooptarief
  rc_rekening_nummer            -- vervangt "Debiteuren" als afhandelingsroute (§2b)
  status                        -- concept/definitief, RLZ Status-veld
  reeleezee_salesinvoice_id
```

**Afwijkingen t.o.v. de aanname "intercompany-factuur, direct, per regel + percentages"**:

1. **Klopt gedeeltelijk**: het ís een percentage-opslag (5%) over een direct doorbelaste kostenpost
   — maar de opslag staat als **losse regel**, niet verwerkt in de regelprijs.
2. **Klopt niet — géén cost-type-GB-mapping**: alle doorbelaste kosten landen op één generieke
   omzetrekening (8000) aan de Facilities-kant, ongeacht kostensoort. Er is dus geen "GB →
   doorbelastings-GB"-mapping per categorie te bouwen op basis van wat Facilities zelf boekt.
3. **Klopt niet — vlak btw-tarief, niet tariefvolgend**: altijd 21% hoog, los van het
   onderliggende inkooptarief.
4. **Nieuw/onverwacht — RC vervangt Debiteuren**: afhandeling via intercompany rekening-courant,
   niet via reguliere debiteurenaflettering (§2b) — belangrijk voor eventuele
   afletteringslogica als deze module ooit ook Facilities-boekingen zou verwerken.
5. **Nieuw/onverwacht — verzamelniveau is over de tijd veranderd** (batch-per-maand →
   granulair per-document): een datamodel dat uitgaat van een vaste 1:1-relatie
   inkoopfactuur↔doorbelastingsfactuur klopt niet voor historische data.
6. **Onbevestigd — geen spiegelkant**: kosten-GB, btw-behandeling en eventuele activering bij de
   doelentiteiten zelf zijn niet geverifieerd (§0) — het datamodel hierboven dekt alleen de
   Facilities-kant.

**Vervolgstap**: credentials voor minstens 2 doelentiteiten aanvragen bij Peter om §2c alsnog te
verifiëren, vóórdat dit datamodel als basis voor bouwwerk wordt gebruikt.
