# Diagnose intake/verzamelbak — kliktest Peter 02-09-2026

> **Status: DIAGNOSE, niets gebouwd of gewijzigd.** Read-only onderzoek op de cloud-data (Cloud SQL
> Auth Proxy 5434, `boekhouding_app`, RLS-scope per query; GCS-leeskopieën van de bestanden; Cloud
> Logging). Fix-voorstellen staan per punt onderaan en wachten op Peters beoordeling. Geen migraties,
> geen RLZ-/Odoo-writes. Eén bewuste uitzondering: zes reproductie-AI-calls LOKAAL (dev-DB als
> kostenmeter, bron `diagnose_intake_02-09`, ≈ € 0,07) om het ruwe AI-antwoord te zien dat de
> productie niet bewaart — zie punt 1.4.

Tijden hieronder in Europe/Amsterdam (de DB slaat UTC op; UTC+2).

---

## Samenvatting

| # | Aanleiding | Oorzaak (bewezen) | Categorie |
|---|---|---|---|
| 1 | Kempenrecreatie-batch: 5+ PDF's "geen tenaamstelling gelezen" | De intake-AI **las de tenaamstelling wél** ("Kempen Facilities B.V."), maar antwoordde `sp=1, ep=2` op 1-pagina-PDF's; onze deterministische paginabereik-validatie verwerpt daarop het **hele** voorstel → verzamelbak mét `tenaamstelling=NULL`. 72 van 76 splitsings-fouten sinds 25-08 zijn deze ene fout. De reden is wél vastgelegd (intake-bericht, tijdlijn, Cloud Logging) maar de verzamelbak-UI toont 'm niet en labelt het misleidend als "geen tenaamstelling gelezen". | **Validatie-bug** (code verwerpt correct AI-resultaat) + zichtbaarheidsgat |
| 2 | 2026-8151.xml + .pdf als twee rijen; XML zonder voorbeeld | Beide bijlagen komen uit één mail en zijn dezelfde factuur (de UBL bevat de PDF letterlijk ingesloten — identieke sha256). De intake routeert élke bijlage onafhankelijk (XML → UBL-pad, PDF → AI-pad) en kent geen bundeling. De UBL is geldig; `AccountingCustomerParty` = **Belastingbutler B.V.** (geen administratie in de app → correct "niet eenduidig"). De PDF-rij faalde op de bug van punt 1. De preview kent voor XML geen paginabeeld, hoewel de PDF ín de XML zit. | Ontbrekende bundeling (ontwerp), geen fout |
| 3 | Tenaamstelling "Belastingbutler B.V." mét suggestie Universal Nederland | Afzender-regel `peter@ak-nijenhuis.nl → Universal Nederland B.V.`, geleerd 01-09 12:17 van een handmatige verzamelbak-toewijzing van een PDF **zonder** gelezen tenaamstelling. Afzender-leren leert op het eigen doorstuuradres; de regel voor dit adres is in 9 dagen 4× omgeklapt naar 4 verschillende administraties, die voor `admin@kempenrecreatie.nl` 12× naar 6 doelen. | Ontwerpfout afzender-leren (bevestigd) |

De drie punten hangen samen: bug 1 maakt `tenaamstelling=NULL`, waardoor de handmatige toewijzing
daarna **alleen** een afzender-regel leert (punt 3) en waardoor het PDF-deel van een UBL+PDF-paar
(punt 2) zonder tenaamstelling naast zijn UBL in de bak komt.

---

## 1. Kempenrecreatie-batch ("Deel 1/2/3", 02-09 14:04–14:40)

### 1.1 Intake-spoor

Drie mails van `admin@kempenrecreatie.nl`, bron `imap`, samen 25 PDF's + 1 JPEG:

| intake_bericht | Onderwerp | Ontvangen | Verwerkt | PDF's | Toegewezen (Kempen Facilities, `tenaamstelling_register`) | Verzamelbak |
|---|---|---|---|---|---|---|
| `056ce09c` | Deel 1 | 14:04:52 | 14:10:29 | 5 | 1 (2026-0261.pdf) | 4 |
| `588fe276` | Deel 2 | 14:16:30 | 14:20:18 | 4 (+1 JPEG→PDF) | 2 (+ de foto) | 3 |
| `ff371a67` | Deel 3 | 14:32:29 | 14:40:36 | 15 | 8 | 7 |

De zeven verzamelbak-rijen uit Deel 3 (de batch uit de aanleiding): `Factuur 260296.pdf`
(5109a799), `2026-0110.pdf` (775cb208), `226176996.pdf` (90a81483), `PSAProjInvoiceQ_73001845_…PDF`
(16dfb1d0), `BouwPartner Van de Wal Factuur-00017488.pdf` (e7180110) — plus uit Deel 1/2:
`Factuur_20260472.pdf`, `Kemp1.pdf`, `Factuur 260296.pdf` (nog een exemplaar), `Factuur_20260461.pdf`,
`Factuur-2026-06227.pdf.pdf`, `Dk Schoonmaakservice Ned. 2026-0006.pdf`, `0086.pdf`.

**Alle twaalf dragen exact dezelfde intake-reden** (`intake_bericht.detail.bijlagen[].detail` én
`document_gebeurtenis.detail.reden` op de overgang ontvangen → niet_toegewezen):

```
splitsingsdetectie_mislukt: Splitsingsvoorstel ongeldig: paginabereik 1–2 valt buiten het document (1 pagina's)
```

### 1.2 Draaide de AI, en wat gaf die terug?

- **Gates open.** `platform.intake_instelling.ai_ingeschakeld = true` (sinds 07-08);
  AI-kostenmeter september: € 5,72 van € 100 (207 calls), geen 80 %-/100 %-melding
  (`ai_kosten_maandstatus` leeg). Geen enkele bijlage kreeg `intake_ai_uitgeschakeld` of
  `ai_limiet_bereikt`.
- **Eén call per PDF, alle geslaagd.** `platform.ai_gebruik` (bron `intake_splitsing`,
  model `claude-sonnet-5`): Deel 1 → 5 calls, Deel 2 → 5, Deel 3 → **15 calls** tussen 14:40:40 en
  14:44:29 (€ 0,246), precies het aantal PDF's. Usage is gelogd, dus de API antwoordde; er was geen
  API-/timeout-fout (die zou als `Claude API-fout: …` in de reden staan).
- **De AI antwoordde, de code verwierp.** Het ruwe AI-antwoord wordt in productie niet bewaard; de
  reden zegt alleen dat het bereik `1–2` was op een document van 1 pagina. De reproductie (1.4)
  toont wat er in dat antwoord stond.

### 1.3 Tekstlaag of scan? (pypdf 6.14.2 op de GCS-kopieën)

| Bestand | Pagina's | Tekstlaag (tekens) | Producer | "Kempen Facilities" letterlijk in tekstlaag |
|---|---|---|---|---|
| 226176996.pdf | 1 | 1 136 | GPL Ghostscript 9.05 | ja — "Kempen Facilities B.V. Banstraat 25 5506 LA Veldhoven" bovenaan |
| BouwPartner …-00017488.pdf | 1 | 2 707 | Amyuni PDF Converter | ja |
| PSAProjInvoiceQ_….PDF | 1 | 1 395 | Lasernet PDF Merger | ja ("Pagina 1/1") |
| 2026-0110.pdf | 1 | 1 146 | Prince 16.2 | ja |
| Factuur 260296.pdf | 1 | 1 407 | Microsoft Excel 2021 | ja |
| Factuur_20260472.pdf | 1 | 1 280 | dompdf | nee (EXTRA B.V.-factuur; geadresseerde in tekst) |
| Factuur-2026-06227.pdf.pdf | 1 | 561 | Qt 4.8.7 | ja |
| Dk Schoonmaakservice … .pdf | 1 | 547 | Microsoft Word 2021 | ja |
| Vlassak 202600222 (07-08 dezelfde fout) | 1 | 1 092 | — | ja |
| Invoice_26732897.pdf (Peter, zelfde fout) | 1 | 1 384 | MS Reporting Services | n.v.t. (Dijkstel) |

Geen enkele is een scan, geen encryptie, geen pypdf-fout: `tel_paginas` telt correct **1**. Ter
vergelijking: de twee PDF's die wél een tenaamstelling kregen maar "niet eenduidig" waren
(5670379546.pdf Google Workspace, 1030257878_1.pdf Dijkstel) hebben **2** pagina's; het
8-pagina-document `Algemene voorwaarden triAV.pdf` gaf terecht "geen facturen herkend".

### 1.4 Reproductie (lokaal, productie-prompt, `claude-sonnet-5`)

Drie van de gefaalde PDF's door exact dezelfde `extraheer_json_uit_pdf`-call met
`splitsing.SYSTEM_PROMPT` / `OPDRACHT` / `SPLITSING_SCHEMA`:

| PDF | Variant A (productie-opdracht) | Variant B (+ zin "dit document heeft precies 1 pagina") |
|---|---|---|
| 226176996.pdf | `sp 1, ep 2, ten "Kempen Facilities B.V.", lev "Van Happen Containers …", nr 226176996, z 0.9` | `sp 1, ep 1`, verder identiek, z 0.95 |
| 2026-0110.pdf | `sp 1, ep 2, ten "Kempen Facilities B.V.", lev "Kimberly Kjaer", nr 2026-0110, z 0.95` | `sp 1, ep 1`, verder identiek |
| 2026-8151.pdf | `sp 1, ep 2, ten "Belastingbutler B.V. T.a.v. Peter Nijenhuis", lev "Saleswizard BV", nr 2026-8151, z 0.95` | `sp 1, ep 1`, verder identiek |

Conclusie: **de AI leest tenaamstelling, leverancier en nummer correct** en met hoge zekerheid, maar
geeft op een 1-pagina-PDF systematisch `ep=2`. `valideer_segmenten` (code) ziet
`eind_pagina 2 > paginas 1`, gooit een `AiExtractieFout`, en `_verwerk_pdf` vangt die in de brede
`except Exception` → `registreer_niet_toegewezen_document(... tenaamstelling=None)`. De correct
gelezen tenaamstelling gaat verloren. Waarom het model "2" zegt is niet bewezen (hypothese: Anthropic
levert per PDF-pagina tekst én paginabeeld, wat het model als twee pagina's kan tellen); wél bewezen
is dat het pagina-aantal als feit in de opdracht het antwoord corrigeert (3/3).

### 1.5 Omvang en ouderdom

`intake_bericht.detail` sinds 25-08 (IMAP live):

| Dag | paginabereik-fout | andere AI-fout | tenaamstelling niet eenduidig | toegewezen | splitsingsvoorstel |
|---|---|---|---|---|---|
| 25-08 | 1 | 0 | 0 | 7 | 0 |
| 26-08 | 27 | 1 | 11 | 60 | 0 |
| 27-08 | 3 | 0 | 7 | 2 | 0 |
| 28-08 | 1 | 0 | 0 | 0 | 0 |
| 31-08 | 7 | 0 | 11 | 10 | 0 |
| 01-09 | 12 | 0 | 11 | 24 | 0 |
| 02-09 | 22 | 2 | 4 | 23 | 2 |

Van de 76 `splitsingsdetectie_mislukt`-uitkomsten zijn 72 "paginabereik 1–2 … (1 pagina's)", 1
"paginabereik 2–2" en 3 "geen facturen herkend" (terecht: algemene voorwaarden). De fout is er sinds
de eerste volumedag; het is **geen regressie** van de schema-fix van 31-08 (die raakte het
inkoopschema, niet het splitsingsschema — dat draagt 3 nullable-velden, ruim onder de limiet). De
"toegewezen"-kolom bevat ook UBL's en meerpagina-PDF's; het aandeel 1-pagina-PDF's dat faalt ligt
dus hoger dan de kolommen suggereren.

### 1.6 Zichtbaar of stil? (kernprincipe 4)

- **Vastgelegd, ja:** `intake_bericht.detail`, `document_gebeurtenis` (tijdlijn-reden), en Cloud
  Logging (`rlz-intake-imap`, bv. `2026-09-02T12:41:33Z Intake-splitsingsdetectie mislukt voor
  226176996.pdf: …`).
- **Zichtbaar op de werkplek, nee:** `intake/verzamelbak.py::lijst_verzamelbak` zet `reden=None`
  op élk item (commentaar: "de intake-reden staat in de tijdlijn"), en `VerzamelbakPaneel.tsx`
  toont bij `tenaamstelling == null` de chip **"geen tenaamstelling gelezen"** — feitelijk onjuist
  (er ís gelezen, de code verwierp). Peter kon daardoor niet zien dat dit één systematische fout was.
- **Geen alarm:** de bewaking-probe `extractie_foutratio` telt alleen `ai_extractie_fout` op
  `document_gebeurtenis` (de extractie ná toewijzing), niet de intake-splitsing. Een fout die de helft
  van de intake-PDF's raakt bleef buiten élk signaal.
- **Gevolgschade in het geheugen:** bij handmatig toewijzen van zo'n rij is `tenaamstelling` NULL,
  dus `leer_toewijzing` leert **uitsluitend een afzender-regel** — de bron van punt 3.

### 1.7 Conclusie per document (aanleiding a)

| Document | Conclusie |
|---|---|
| 226176996.pdf, BouwPartner …-00017488.pdf, PSAProjInvoiceQ_….PDF, 2026-0110.pdf, Factuur 260296.pdf (2×), Factuur_20260472.pdf, Kemp1.pdf, Factuur_20260461.pdf, Factuur-2026-06227.pdf.pdf, Dk Schoonmaakservice, 0086.pdf | **Validatie-bug**: 1 pagina, tekstlaag aanwezig, AI-call geslaagd, tenaamstelling gelezen, door code verworpen op `ep=2`. Geen scan-grens, geen gate/limiet, geen API-fout. |
| Algemene voorwaarden triAV.pdf (2× dezelfde sha256, mails 10:20 en 10:21) | Correct AI-gedrag ("geen facturen herkend"); landt als `inkoopfactuur` in de bak — een eigen label "geen factuur" zou beter passen. |
| 5670379546.pdf (Google Workspace) | Correct: tenaamstelling "J Gerritsen / Veldhoven Recreatie B.V." matcht geen register-/regelnaam; suggestie via afzender-regel. |
| BEX Vakantiepark Latour/Molenvelden 2026-08 | Correct: splitsingsvoorstel (2 facturen) ter controle. |

Stand ná Peters kliktest: alle twaalf Deel-documenten zijn intussen handmatig aan Kempen Facilities
toegewezen (te_controleren/ter_accordering); in de verzamelbak staan nog `Termijnfactuur Energie
26254571.pdf`, `Invoice_26732897.pdf`, `2026-8151.pdf` met deze fout (plus 2 splitsingsvoorstellen
en 2 echte niet-eenduidige).

---

## 2. UBL + PDF-paar 2026-8151 (Saleswizard → Belastingbutler)

### 2.1 Eén mail, twee onafhankelijk gerouteerde bijlagen

`intake_bericht 4988b08f` — afzender `peter@ak-nijenhuis.nl`, onderwerp "Fwd: Factuur 2026-8151 van
Saleswizard BV", ontvangen 14:52:20, verwerkt 15:00:33. `detail.bijlagen`:

| Bijlage | Pad | Uitkomst | Reden | Tenaamstelling | Suggestie |
|---|---|---|---|---|---|
| 2026-8151.pdf (`8ee17ea3`) | PDF → intake-AI | verzamelbak | paginabereik 1–2 … (punt 1) | NULL | — |
| 2026-8151.xml (`2f4d16ed`) | XML → UBL-parser | verzamelbak | `tenaamstelling_niet_eenduidig` | "Belastingbutler B.V." | Universal Nederland B.V. (`afzender_regel_maar_onbekende_tenaamstelling`) |

Beide document-rijen dragen `intake_bericht_id = 4988b08f` — ze komen aantoonbaar uit dezelfde mail.
`verwerking.py::_routeer_bijlage` behandelt elke bijlage los: `is_xml` → `_verwerk_xml`, `is_pdf` →
`_verwerk_pdf`; er bestaat geen bundeling op mail, naamstam of ingesloten bestand.

### 2.2 Wat er ín de UBL staat

Geldige UBL 2.1 `Invoice` (parser slaagde — dus **niet** `ubl_invalide`/NLCIUS-incompleet):

- `cbc:ID` 2026-8151 · `IssueDate` 2026-09-02 · `InvoiceTypeCode` 380 · `PayableAmount` 35,70
  (29,50 + 21 %); `CustomizationID`/`ProfileID` ontbreken (kale UBL, geen NLCIUS-header — wordt door
  onze parser niet vereist).
- `AccountingSupplierParty`: **Saleswizard BV**, Arnhem, KvK 09219838, btw NL822236333B01.
- `AccountingCustomerParty`: **Belastingbutler B.V.**, Turfstraat 1 3, 6811HL Arnhem, btw
  NL856727118B01, KvK 66856736, contact **peter@ak-nijenhuis.nl**.
- `AdditionalDocumentReference` ID `2026-8151.pdf`, `DocumentType` PrimaryImage, mét
  `EmbeddedDocumentBinaryObject` = 57 510 bytes, **sha256 46d89728… — byte-identiek aan de losse
  PDF-bijlage** (`document.sha256_hash` van 8ee17ea3).

De PDF-tekstlaag noemt dezelfde geadresseerde ("Belastingbutler B.V. T.a.v. Peter Nijenhuis") en de
reproductie-AI las dat ook (1.4). Zonder bug 1 hadden beide rijen dus dezelfde tenaamstelling gehad —
maar nog altijd als twee rijen.

**Belastingbutler B.V. staat niet in het administratieregister** (30 rijen, geen match op naam of
geleerde regel) → "niet eenduidig" is de juiste uitkomst van de code. Datapunt voor Peter: op 01-09
kwam ook een mail van `belastingbutler@factuurinbox.reeleezee.nl` binnen; Belastingbutler lijkt dus een
RLZ-administratie van het kantoor die niet in de app is onboarded. Of dit een eigen entiteit is of een
verkeerd geadresseerde factuur, kan de intake niet weten.

### 2.3 Geen voorbeeld op de XML-rij

`VerzamelbakPreview.tsx` rendert voor `.pdf` de eerste pagina en voor afbeeldingen een `<img>`; voor
alles anders de tekst "UBL/XML-bestand — geen paginabeeld; tenaamstelling staat in de rij". De
ingesloten PDF in de UBL wordt nergens benut.

### 2.4 Afloop in de kliktest

Om 15:26:21 is de XML-rij gemarkeerd als "hoort niet bij ons" met reden **"dubbel"** (actor
`7ee63a62` = account niek@ak-nijenhuis.nl); de PDF-rij staat nog in de bak. Bijeffect: een echte
factuur staat nu als "afgewezen — hoort niet bij ons" in het archief, terwijl het probleem de
dubbele rij was, niet het document.

### 2.5 Hetzelfde patroon bij toegewezen documenten

Dezelfde dag kwamen `114164.pdf` + `114164.xml` (mail 10:20) en `Projectfactuur V01260706.pdf` +
`.xml` (10:21) binnen; beide paren zijn **elk als twee documenten** aan Kempen Facilities toegewezen.
Dat is dubbel werk in de werkvoorraad en steunt straks alleen op de harde duplicaatcheck bij boeken.
De bundeling is dus geen verzamelbak-cosmetica maar een intake-brede tekortkoming.

---

## 3. Suggestie "Universal Nederland" bij Belastingbutler

### 3.1 Herleiding

`document 2f4d16ed`: `toewijzing_suggestie_administratie_id = 36dade86` (Universal Nederland B.V.),
`toewijzing_suggestie_bron = afzender_regel_maar_onbekende_tenaamstelling`. Code-pad
(`toewijzing.py::bepaal_toewijzing`): tenaamstelling "belastingbutler" matcht geen regel/registernaam
→ er ís een actieve afzender-regel voor `peter@ak-nijenhuis.nl` → tegenstrijdig signaal → verzamelbak
mét die administratie als suggestie. De code deed wat ontworpen is.

De regel zelf (`toewijzing_regel 51c9c17d`): soort `afzender`, sleutel `peter@ak-nijenhuis.nl` →
Universal Nederland, aangemaakt **01-09 12:17:27** door `p.nijenhuis@kempengroep.nl`, audit
`toewijzing_regel_geleerd` met oude waarde `3ee6edf0` (Universal Steigerbouw). Op exact dat tijdstip
staat `verzamelbak_toegewezen` voor document `c61d2778` (`invoice-01bb48e9-….pdf`, **tenaamstelling
NULL**, afzender peter@ak-nijenhuis.nl) — een verzamelbak-toewijzing van een PDF die op bug 1 was
gestrand, waardoor alleen de afzender-regel geleerd werd.

### 3.2 Bevestiging: leren op het eigen doorstuuradres, en het klapt om

Volledige historie sleutel `peter@ak-nijenhuis.nl` (4 versies, 4 doelen in 9 dagen):

| Geleerd | Doel | Geleerd van (verzamelbak_toegewezen) | Tenaamstelling op dat document |
|---|---|---|---|
| 24-08 13:48 | Administratiekantoor Nijenhuis C.V. | order_F0000_2608_0011_7116.pdf | NULL |
| 01-09 09:35 | Universal Steigerbouw B.V. (door barbara@) | BMW_26VMA083891-L.pdf | "Universal Nederland B.V. T.a.v. H. Rissewijck" |
| 01-09 12:17 | Universal Nederland B.V. | invoice-01bb48e9-….pdf | NULL |
| 02-09 15:22 | Rubicon Investments B.V. (actor niek@) | Invoice_26753012.pdf | NULL |

Drie van de vier leermomenten hadden **geen** tenaamstelling (bug 1), zodat het geheugen precies het
verkeerde signaal overhield. Hetzelfde patroon over alle afzender-regels:

| Afzender | Versies | Verschillende doelen |
|---|---|---|
| admin@kempenrecreatie.nl | 12 | 6 (Veldhoven Recreatie ↔ Kempen Facilities ↔ Oirschot Recreatie ↔ Molenhof Verhuur …) |
| peter@ak-nijenhuis.nl | 4 | 4 |
| facturen@kempenrecreatie.nl | 4 | 3 |
| barbara@ak-nijenhuis.nl | 3 | 2 |
| overige 6 (echte leveranciers: bouwadviesoost, tjhoveniers, coffeeshopblow, …) | 1 | 1 |

Alle vier de "klappers" zijn kantoor-/doorstuuradressen van multi-entiteit-organisaties; alle
leveranciersadressen zijn stabiel. `leer_toewijzing` leert de afzender onvoorwaardelijk (geen
domein-uitsluiting, geen flip-detectie). Auto-toewijzing puur op afzender-regel is tot nu toe 1× voorgekomen
(`Dieren compleet LT.pdf`, 26-08, barbara@ → Kempen Facilities) — de risicoroute bestaat: bij
`tenaamstelling=None` én een afzender-regel wijst `bepaal_toewijzing` automatisch toe (`bron
afzender_regel`), en juist op de doorstuuradressen is die regel het minst betrouwbaar.

---

## Fix-voorstellen (nog niet bouwen — ter beoordeling)

**Punt 1 — paginabereik-bug + zichtbaarheid.** (a) Geef `tel_paginas` als feit mee in de
opdracht ("dit document heeft precies N pagina('s)") — bewezen effectief (3/3) en één regel; (b) maak
de validatie proportioneel: bij `paginas == 1` het bereik van een één-segment-voorstel normaliseren
naar 1–1 in plaats van het hele antwoord weg te gooien, en algemener: een ongeldig bereik verwerpt
alleen het *splitsings*-voorstel, nooit de gelezen tenaamstelling/leverancier/nummer (die gaan met
verlaagde zekerheid door naar de gewone toewijzing); (c) de verzamelbak-lijst levert de intake-reden
(uit `document_gebeurtenis`) en de UI toont die als chip in plaats van het onjuiste "geen
tenaamstelling gelezen" — onderscheid "AI-fout: …", "geen factuur herkend", "tenaamstelling onbekend:
…"; (d) bewaking: intake-splitsingsfouten meetellen in `extractie_foutratio` (of een eigen probe op
`intake_bericht.detail`), zodat een fout op de helft van de PDF's binnen een uur alarmeert; (e) nazorg:
de drie nog openstaande rijen met deze reden kunnen ná de fix via een "Opnieuw lezen"-knop op de
verzamelbak-rij (nieuwe intake-AI-call, zelfde gates) — de twaalf Deel-documenten heeft Peter al
toegewezen, daar is niets te herstellen behalve het ontbrekende tenaamstelling-geheugen (zie punt 3d).
Regressietest: 1-pagina-PDF mét AI-antwoord `ep=2` → toegewezen op tenaamstelling, geen verzamelbak.

**Punt 2 — bijlage-paren bundelen.** In `verwerk_eml` vóór de routing bijlagen paren op, in
volgorde: (a) een UBL met ingesloten `PrimaryImage` waarvan de sha256 gelijk is aan een PDF-bijlage
(deterministisch, dít geval); (b) anders gelijke naamstam `.xml`/`.pdf` in dezelfde mail. Een paar
wordt **één document**: UBL leidend voor velden en tenaamstelling (geen AI-call voor de PDF — spaart
kosten en omzeilt bug 1), de PDF als beeld via het bestaande `bron_bestand`-mechanisme van de
afbeeldingsroute (document = UBL, `bron_*` = PDF, of andersom als het controlescherm liever een PDF
als hoofdbestand heeft — te kiezen bij het bouwen). Eén verzamelbak-rij, één toewijzing, één
werkvoorraad-document — lost ook de dubbele rijen bij 114164 en V01260706 op. Preview: paar → het
PDF-beeld; losse UBL mét ingesloten PDF → die ingesloten PDF; losse UBL zonder beeld → een
gerenderde samenvatting (leverancier, afnemer, nummer, datum, totaal, regels) in plaats van "geen
paginabeeld". **Handmatige samenvoeg-actie (toevoeging Peter 02-09) als vangnet voor wat de
paar-detectie mist:** in de verzamelbak twee rijen selecteren → knop "Samenvoegen" → dialoog waarin
de mens kiest welk bestand **leidend** is voor de data (UBL → velden deterministisch; PDF → normale
extractie ná toewijzing) en het andere bestand bijlage/beeld wordt (zelfde `bron_bestand`-mechaniek
als het automatische paar); de tweede document-rij krijgt een terminale status `samengevoegd` mét
verwijzing naar het hoofddocument (nooit verwijderen — beide sha256's blijven terugvindbaar,
tijdlijn op beide kanten, audit oud→nieuw), het toewijzings-geheugen leert van het samengevoegde
document zoals van elk ander; server-side poorten: beide rijen echt in de verzamelbak
(administratie NULL + `niet_toegewezen`), bij voorkeur uit dezelfde mail (ander intake-bericht =
expliciete waarschuwing, geen blokkade), nooit twee UBL's of twee PDF's stil samenvoegen zonder
bevestiging; ongedaan maken = het hoofddocument opnieuw splitsen in twee verzamelbak-rijen zolang het
niet is toegewezen. Dezelfde actie past later ook op de documentenlijst van een administratie
(casus 114164/V01260706), maar begint in de verzamelbak. Aparte vraag voor Peter, buiten de bouw: is
Belastingbutler B.V. een eigen entiteit die als administratie onboarded moet worden?

**Punt 3 — afzender-leren begrenzen.** (a) Kantoor- en doorstuurdomeinen uitsluiten van
afzender-leren én van afzender-auto-toewijzing: Beheerder-instelling met een domein-/adreslijst,
initieel `ak-nijenhuis.nl`, `kempengroep.nl`, `kempenrecreatie.nl` (afzender blijft wél hint-tekst
op de rij); (b) flip-detectie: wordt een afzender-sleutel voor de tweede keer naar een ánder doel
geleerd, dan de regel deactiveren zónder nieuwe ("afzender is meerduidig", audit) in plaats van
eindeloos omklappen; (c) bij `tenaamstelling=None` uit een mislukte AI-lezing nooit auto-toewijzen op
afzender — "niet gelezen" ≠ "gelezen: niemand", twijfel = verzamelbak (raakt de 26-08-casus
`Dieren compleet LT.pdf`); (d) data-nazorg als losse, expliciete stap ná akkoord: de actieve
afzender-regels op de drie domeinen deactiveren (audit oud→nieuw, niets verwijderen) en optioneel
voor de twaalf handmatig toegewezen Deel-documenten alsnog tenaamstelling-regels leren uit de
tekstlaag (mens bevestigt per regel — geen stille backfill).

---

## Bronnen / reproduceerbaarheid

- Cloud-DB (read-only, RLS-scope per administratie waar nodig): `boekhouding.intake_bericht`,
  `boekhouding.document`, `boekhouding.document_gebeurtenis`, `boekhouding.toewijzing_regel`,
  `platform.ai_gebruik`, `platform.ai_kosten_*`, `platform.intake_instelling`, `platform.audit_event`,
  `platform.administratie`.
- Bestanden: GCS `rlz-boekhouding-documenten/niet_toegewezen/<document_id>.<ext>` (leeskopieën in de
  sessie-scratchpad, niet in de repo).
- Cloud Logging: `resource.type=cloud_run_job job_name=rlz-intake-imap textPayload:"splitsingsdetectie"`.
- Reproductiescript (scratchpad, niet gecommit): `ClaudeExtractieClient.extraheer_json_uit_pdf` met
  de productie-prompts uit `app/extractie/splitsing.py`, variant B = `OPDRACHT` + zin met
  `tel_paginas(pdf)`; 6 calls, lokaal gelogd in de dev-DB onder bron `diagnose_intake_02-09`.
- Code: `backend/app/intake/verwerking.py` (`_verwerk_pdf`, `_routeer_bijlage`),
  `backend/app/extractie/splitsing.py` (`valideer_segmenten`, `detecteer_facturen`),
  `backend/app/intake/toewijzing.py` (`bepaal_toewijzing`, `leer_toewijzing`),
  `backend/app/intake/verzamelbak.py` (`lijst_verzamelbak`: `reden=None`),
  `frontend/src/intake/VerzamelbakPaneel.tsx` (chip "geen tenaamstelling gelezen"),
  `frontend/src/intake/VerzamelbakPreview.tsx` (XML zonder beeld),
  `backend/app/bewaking/service.py::_probe_extractie_foutratio`.
