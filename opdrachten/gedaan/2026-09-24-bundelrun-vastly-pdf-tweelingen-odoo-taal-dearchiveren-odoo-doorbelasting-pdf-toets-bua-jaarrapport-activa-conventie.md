uitgevoerd 2026-09-24, rapport: docs/rapporten/2026-09-24-bundelrun-zeven-punten.md

# Bundelrun 24-09 — zeven open punten in één opdracht (Peter 24-09: "alles in 1 opdracht")

Handmatige CC-sessie, Peter start hem zelf, ná de AI-limiet-run (09d15a6/45509d6). Volgorde = urgentie. Elk blok een eigen commit
(feature/docs gescheiden), één rapport `docs/rapporten/2026-09-24-bundelrun-zeven-punten.md` mét per blok "werkt in productie:
ja/nee/niet gemeten" + meetrecept, INDEX-regel, sectie "Gelezen regels", BESLISSINGEN-rij per blok, `WAT_IS_NIEUW.md`, gespreksverslag
`docs/gesprekken/2026-09-24.md` aanvullen (0024). Regel 22-08/23-09: dit is de enige opdrachttekst; geen eigen interpretatie buiten de
blokken. Niets verwijderen in RLZ/Odoo; productie alleen via gedeployde jobs.

LEESPLICHT (volledig, vóór je begint): CLAUDE.md, docs/regels/intake-extractie.md, duplicaten-crediteuren.md,
administraties-instellingen.md, kantoor-frontend.md, doorbelasting-intercompany.md, btw.md, activa.md, werkloop-productie.md;
docs/gesprekken/2026-09-23.md en 2026-09-24.md; Platform/WERKWIJZE.md.

## Blok 1 — Vastly-PDF-tweelingen: bundeling faalt sinds 23-09 (URGENT, 23 documenten in de werkvoorraad)
Feit (Cowork `/zoeken`, 24-09 11:0x): de Vastly-batch van 23-09 (oktoberfacturen) leverde per factuur een UBL `factuur-XXX-2026-NNNN-ubl.xml`
(correct → verkoopfactuur, VASTLY-VERKOOP) én een PDF `factuur-XXX-2026-NNNN.pdf` die NIET gebundeld werd en als losse INKOOPFACTUUR
`te_controleren` staat: Rubicon 10, J.G.M. Elissen Holding 4, ARVUM 3, Beleggingsmaatschappij Meyer 3, Stichting Shuto 3 = 23. Geen
enkele geboekt (RUB-2026-0031: UBL geboekt, PDF-tweeling staat nog). Elissen 31-08 wél gebundeld (7 UBL / 4 PDF).
`app/intake/bundeling.py::bundel_bijlagen` paart op (1) sha256 van de in de UBL ingesloten PDF, (2) exacte naamstam. "-ubl" ≠ stam; de
hash-match faalde kennelijk óók.
Te doen: (a) oorzaak vaststellen aan het échte bericht (lees-only: `intake_bericht` van 23-09 voor Meyer/Rubicon — heeft de UBL nog een
`cac:AdditionalDocumentReference/…/EmbeddedDocumentBinaryObject`? is de hash gelijk aan de losse PDF? welke job/kanaal verwerkte het:
`facturen` of `facturen_kempengroep`?); rapporteer of het Vastly (ingesloten PDF weg/gewijzigd) of onze intake-deploy 0171 is;
(b) naamstam-normalisatie: strip een `-ubl`/`_ubl`/`-xml`-suffix vóór de vergelijking (ondubbelzinnig blijft de eis), plus als derde
regel: UBL-`cbc:ID` (factuurnummer) tekstueel in de PDF-bestandsnaam of in de PDF-tekst (pypdf, `normaliseer_tekst`) én precies één
kandidaat; (c) nazorg-CLI `vastly-pdf-tweelingen-herstel [--dry-run]`: de 23 PDF's koppelen als beeld (`beeld_bestandsnaam`/bijlage) aan
hun UBL-document, status → `samengevoegd` mét tijdlijn beide kanten + audit `gebundeld_achteraf`; is de UBL al geboekt (RUB-0031) dan
óók de PDF als RLZ-bijlage nazenden via `zorg_voor_bijlage`; (d) reconciliatie: een losse inkoopfactuur waarvan de bestandsnaam matcht
op een UBL-verkoopfactuur van dezelfde dag/administratie = bevinding `ubl_pdf_ongebundeld` in `meten` mét actie "Bundelen"; (e) als het
Vastly blijkt: OPEN_ITEM in Platform/OPEN_ITEMS.md (ingesloten PDF hoort identiek te zijn — koppelcontract §2d). Tests: suffix-stam,
cbc:ID-regel, twee kandidaten = niet bundelen, herstel-CLI idempotent.

## Blok 2 — Odoo: grootboeknamen Engels in de module (Bonte Hoeve)
`app/odoo/client.py:155` geeft alleen `allowed_company_ids` mee. Voeg `lang: "nl_NL"` toe aan de context van élke lees- én schrijfcall
(vertaalbare velden: rekeningnaam, journaalnaam, productnaam, btw-naam), hersync de grootboek-/journaal-/btw-cache van álle Odoo-
administraties (CLI bestaat: hergebruik de eerste-sync-route, geen nieuwe), guard-test op de context. Vastleggen in
administraties-instellingen.md. Meetrecept: `db-lezen` grootboeknamen Bonte Hoeve vóór/ná.

## Blok 3 — Dearchiveren Odoo-administratie vraagt Reeleezee-login (Recreatief Vastgoed Nederland)
Voer `opdrachten/inbox/2026-09-24-BUG-dearchiveren-odoo-administratie-vraagt-reeleezee-login.md` integraal uit (backend-bewust via de
port, Odoo-adapter hergebruikt OdooKoppeling + sleutel + probe, loginvelden optioneel, dialoog zonder loginvelden bij odoo, wizard toont
gearchiveerde claim grijs, tests). Niets in productie dearchiveren: Peter dearchiveert zelf 8ea9d28b-e743-4566-96d7-bb7d81531368
(company 13) ná de deploy; 59bf1f7f… (company 11) blijft gearchiveerd. Vastleggen wat archiveren met de Odoo-API-sleutel doet.

## Blok 4 — Doorbelasting: factuur-PDF "onvolledig" door cent-verschil? (lees-only eerst)
Casus: KF → Molenhof Verhuur B.V., Lusso 261004, € 4.741,55 + provisie € 237,08, chip "factuur ontbreekt — factuur-PDF onvolledig:
btw-som € 1.045,52, totaal incl € 6.024,15". Hypothese Cowork: RLZ rendert 21 % × 4.978,63 = 1.045,51 / 6.024,14; onze per-regel-
afronding boekte 1.045,52 → cent-exacte toets (`app/doorbelasting/factuur.py::controleer_factuur_tekst`) faalt.
Te doen: (a) lees-only: de verkoopfactuur-PDF van deze doorbelasting via `download_sales_invoice_pdf` ophalen (job-image, lees-only) en
de gerenderde bedragen náást de geboekte zetten; óók de RLZ-JournalEntry van de verkoop lezen: boekt RLZ 1.045,52 (regelsom) of 1.045,51?
(b) uitkomst A — PDF ≠ journaal (RLZ herrekent op de print): dan is de PDF fiscaal afwijkend van de boeking → melden aan Peter als
RLZ-bevinding, toets laten staan maar de melding herformuleren ("RLZ-factuur toont € 1.045,51, geboekt € 1.045,52 — cent-verschil door
RLZ-render"), géén lay-out-advies meer; uitkomst B — journaal = PDF = 1.045,51 en wíj boekten anders: bug in onze regel-btw-afronding
t.o.v. wat RLZ vastlegt → fix in `regelsom.py` alleen voor de doorbelastingsmotor ná Peters akkoord (rapporteer eerst); (c) tel
kantoorbreed hoeveel doorbelastingen `factuur_pdf_status = ontbreekt` dragen mét reden "onvolledig" en of het allemaal 1-cent-gevallen
zijn; (d) `make doorbelasting-facturen-herstel` NIET draaien vóór (a)–(c) gerapporteerd zijn.

## Blok 5 — BUA: jaareinde-rapport i.p.v. kenmerk (besluit Peter 24-09 "standaard 21 % btw aanhouden")
Geen bulk-zetting van het BUA-kenmerk. Bouw de lees-only CLI `bua-jaarrapport --jaar 2026 [--administratie]`: per administratie de btw
die in het jaar is afgetrokken op rekeningen uit de `bua-kandidaten`-set (naam-match 4xxx representatie/relatiegeschenken/personeel;
kantine/sponsoring apart gemarkeerd), per rekening netto/btw/aantal documenten, bron = module-boekingen én RLZ-JournalEntryLines
(lees-only), kolom "correctie laatste aangifte (voorstel)" = de btw-som (de € 227-drempel per begunstigde is niet uit de boekhouding te
halen → als LET-OP-tekst, nooit zelf toepassen). Dagelijkse bevinding vanaf 1 december: `bua_correctie_open` in `meten` per
administratie mét actie "Rapport openen". Vastleggen in btw.md (het kenmerk 0163 blijft beschikbaar per rekening).

## Blok 6 — Activa: afschrijvingsrekening = kostenrekening mét dezelfde omschrijving (besluit Peter 24-09 07:5x)
Vervang de conventie "code + 1 op 0xxx" (BUG-run 23-09 avond) door: `DepreciationAccount` = 4xxx-rekening waarvan de genormaliseerde
omschrijving overeenkomt met die van de activarekening ná het voorvoegsel "Afschrijving(en)/Afschrijvingskosten" (0107 Kantoorinventaris
→ "Afschrijving kantoorinventaris"; ICT → ICT; meerdere treffers = combobox verplicht, geen gok); balanskant blijft `BalanceAccount`.
Volgorde blijft koppeling > instelling > conventie, chip noemt de bron. Tests: naam-match, geen match = 422 + combobox, meerdere =
combobox. STAP-0 deel 2 (schrijvend, testadministratie faae29c5 ná dearchiveren door Peter) en herstel BLOw 23619/06052/MK22507863
blijven klikpunten Peter — niet in deze run uitvoeren, wél het recept in het rapport.

## Blok 7 — Twee bugs van 23-09 (bestaande inbox-bestanden, integraal uitvoeren)
- `2026-09-23-BUG-vraag-thread-opent-kassarapport-in-inkoopscherm.md` (`VraagThread.tsx:242` → `documentRoute`/`reviewPad`).
- `2026-09-23-BUG-samenvoegen-vinkje-weg-als-scan-geen-regelbedragen-heeft.md` (`BoekvoorstelPanel.tsx:978`, Van Rumpt 2025135).

## Niet doen
- Geen limiet-, kenmerk- of datawijziging in productie buiten de genoemde nazorg-CLI's (die dry-run-default hebben en pas ná Peters "ja").
- Geen tweede BEX-client, geen Department-schrijven, geen parkenmodel — dat is een aparte ontwerpronde.
- Blok 4: geen fix in geldlogica zonder gerapporteerde meting én akkoord.

## Definitie van af
Gouden set groen (volledige pytest/vitest/tsc/keten-sweep), deploy, per blok een meetrecept in het rapport; nametingen als
dispatch-onderdelen (`vastly-tweelingen`, `odoo-taal`, `dearchiveren-odoo`, `doorbelasting-pdf`, `bua-jaarrapport`, `activa-conventie`)
mét vervolgopdrachten `niet vóór:` ná de deploy. Alle zeven inbox-bestanden (dit + de drie genoemde) naar `opdrachten/gedaan/`.
