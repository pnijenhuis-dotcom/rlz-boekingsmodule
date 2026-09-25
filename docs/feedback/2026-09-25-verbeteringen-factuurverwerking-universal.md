# Verbeteringen factuurverwerkingsmodule

Bron: gebruikersfeedback uit de praktijk (boeken van inkoopfacturen).
Doel: dit bestand is de backlog. Werk items af op volgorde van prioriteit.

## Werkwijze voor Claude Code

- Pak één item per keer. Gebruik het ID in de commitmessage, bv. `FV-11: XML-parsing Reeleezee`.
- Status per item bijwerken: `[ ]` open, `[~]` in uitvoering, `[x]` afgerond.
- Acceptatiecriteria zijn de definition of done. Voeg toe als er iets ontbreekt, verwijder niets.

Prioriteiten: **P1** blokkeert dagelijks werk · **P2** kost veel tijd · **P3** comfort.

---

## 1. Data-extractie en herkenning

### [ ] FV-01 · XML van Reeleezee-facturen wordt verkeerd geparsed · Bug · P1
> **Status (CC feedbackrun A, 25-09):** gedaan (aangepaste vorm) — de XML was wél als UBL gelezen; het bijlage-paneel toonde de ruwe XML omdat de PDF-tweeling ontbrak. Nu: leesbare UBL-kaart i.p.v. XML (bron alleen op verzoek), onleesbare/onvolledige XML = "Handmatig afmaken" mét reden "XML niet leesbaar: …" in scherm en tijdlijn; lees-only rapport `xml-documenten-rapport` telt kantoorbreed de XML-documenten zonder beeld/niet leesbaar mét voorstel voor heraanbieding. Werkt in productie: niet gemeten (klikpunt: RLZ-2080142898 openen ná deploy).
Nu: factuur RLZ-2080142898 wordt ingelezen als blok ruwe code. De XML wordt niet als XML herkend.
Gewenst: XML-facturen worden gestructureerd uitgelezen; bij een parsefout een duidelijke melding in plaats van codeweergave.
Acceptatie:
- RLZ-2080142898 leest correct in (regels, bedragen, btw).
- Onbekende of kapotte XML geeft status "leesfout" met de oorzaak, nooit ruwe code in een veld.

### [ ] FV-02 · Project wordt uit geheugen per leverancier overgenomen · Bug · P1
> **Status (CC feedbackrun A, 25-09):** aangepaste vorm — het geheugen blijft (auto-first, autoboeken), maar het project komt eerst uit de factuur (werknummer/projectnummer, óók in de regeltekst en de e-factuur-notitie, in het nummerformaat van de administratie uit de projectcache); de historie is de laatste bron mét zichtbare chip "voorstel uit historie", noemt de factuur een ander nummer dan vult de module niets in (kies zelf), afgesloten projecten alleen bij letterlijke verwijzing, automatisch boeken nooit bij een conflict (feedbackrun A blok 3, 25-09; werkt in productie: niet gemeten).
Nu: de module selecteert bij elke leverancier het laatst gebruikte project.
Gewenst: elke factuur wordt afzonderlijk geanalyseerd. Historie mag nooit leiden tot automatische invulling zonder onderbouwing uit de factuur zelf.

### [ ] FV-03 · Automatische herkenning boekingsregels o.b.v. historie · Feature · P1
> **Status (CC feedbackrun A, 25-09):** run B — per-crediteur-templates voor Universal + meetbaarheid tegen de testset `crediteuren-historie-schoon.csv` (niet meegeleverd); Bijlage A hoort daarbij; geen hardcoded rubrieken in run A.
Nu: omschrijving, grootboekrekening, project en btw worden nauwelijks automatisch ingevuld. Bij Floor Bouwliftenservice gebeurt dit helemaal niet.
Gewenst: invullen op basis van eerdere facturen van dezelfde crediteur; bestand crediteuren als referentie/back-up gebruiken zodat duidelijk is waar de module naar moet kijken.
Onderbouwing: zie **Bijlage A** onderaan dit bestand — per crediteur welke signaalwoorden naar welke rubriek gaan en hoe de omschrijving eruit hoort te zien. `crediteuren-historie-schoon.csv` (1094 geboekte regels) is geen invoer voor de module, maar de testset om de herkenning tegen te meten.
Acceptatie:
- Werkt bij alle crediteuren, niet bij een deel ervan.
- Bij een crediteur met historie worden omschrijving, grootboekrekening, project en btw voorgesteld.
- De som van de rubrieken sluit aan op het factuurtotaal excl. btw; anders foutmelding.
- Creditnota's (negatieve bedragen) worden herkend en niet genegeerd.
- Herkenningspercentage per crediteur is meetbaar (logging), gemeten tegen de testset.

### [ ] FV-04 · Bijlagen worden niet uitgelezen · Feature · P1
> **Status (CC feedbackrun A, 25-09):** run B — bijlage-uitsplitsing (huur/transport/defecten) vraagt de voorbeeldfacturen van Universal Nederland; wacht op testset + voorbeeldfacturen.
Nu: bij facturen van Universal Nederland blijven de bijlagen buiten beschouwing, terwijl daar defecten en transporten op staan.
Gewenst: de bijlage zit in hetzelfde factuurbestand. Op de factuur staat één totaalbedrag, in de bijlage uitgesplitst naar huur, transport en defecten. Lees die uitsplitsing uit.
Acceptatie:
- De uitsplitsing uit de bijlage komt als aparte boekingsregels in het boekingsscherm.
- De som van die regels sluit aan op het totaalbedrag van de factuur.

### [ ] FV-05 · Omschrijving opschonen · Verbetering · P2
> **Status (CC feedbackrun A, 25-09):** gedaan — bijlageverwijzingen ("conform bijgevoegd overzicht", "zie bijlage", …) worden deterministisch van de staart van de automatische omschrijving gestript (chip "ingekort"); nooit midden in een zin, nooit op een eigen tekst, nooit inhoud verzonnen.
Nu: omschrijvingen als "huur juli conform bijgevoegd overzicht" worden letterlijk overgenomen.
Gewenst: verwijzingen naar bijlagen ("conform bijgevoegd overzicht") uit de omschrijving strippen.

### [ ] FV-21 · Crediteurnamen normaliseren · Bug · P1
> **Status (CC feedbackrun A, 25-09):** aangepaste vorm — naam-genormaliseerde clusters (casefold, rechtsvorm, leestekens; "Holding" blijft onderscheidend) als ORANJE cluster in Inzicht › Crediteuren; de mens bevestigt, nooit automatisch samenvoegen op naam; ná bevestiging koppelt een afwijkende schrijfwijze aan de voorkeur en leest de historie over het cluster; lees-only CLI `crediteuren-naamclusters`.
Nu: dezelfde crediteur komt in meerdere schrijfwijzen voor (`Floor Bouwliftenservice` / `Floor bouwliftenservice`, `Universal Nederland B.V.` / `Universal nederland B.V.`). Daardoor valt de historie van één crediteur uiteen en vindt de herkenning te weinig referentiemateriaal.
Gewenst: matchen op genormaliseerde naam — hoofdletterongevoelig, zonder rechtsvorm en zonder leestekens — met één canonieke naam per crediteur.
Acceptatie:
- Alle boekingen van Floor Bouwliftenservice vallen onder één crediteur.
- Een nieuwe factuur met afwijkende schrijfwijze koppelt aan de bestaande crediteur in plaats van een nieuwe aan te maken.

---

## 2. Boekingsscherm en invoer

### [ ] FV-07 · Project en btw één keer invullen voor de hele boeking · Feature · P1
> **Status (CC feedbackrun A, 25-09):** gedaan — project en btw-code op factuurniveau boven de regels-tabel (bij ≥ 2 regels), doorgezet naar alle regels en per regel overschrijfbaar; tijdlijnregel "kop → regels".
Gewenst: project en btw op factuurniveau instellen; waarde wordt doorgezet naar alle regels, per regel nog te overschrijven.

### [ ] FV-08 · Rekenen in bedragvelden · Feature · P1
> **Status (CC feedbackrun A, 25-09):** gedaan — rekenexpressies (`+ - * /`, haakjes, komma-decimalen) in netto/bruto- en btw-velden, uitgerekend bij het verlaten van het veld door een eigen parser (geen eval), resultaat zichtbaar mét chip "= 20+30".
Nu: bedragen moeten handmatig opgeteld worden, bv. defecten en transporten uit de bijlage van Universal Nederland.
Gewenst: invoer `20+30` levert `50`. Ondersteun `+ - * /`.

### [ ] FV-09 · Btw-bedrag automatisch herberekenen · Bug · P1
> **Status (CC feedbackrun A, 25-09):** gedaan — het btw-bedrag herrekent nu bij wijziging van het nettobedrag (ook op geladen regels en in de samengevoegde modus) én bij wijziging van het tarief (bestond al); een zelf getypt btw-bedrag blijft staan tot het netto wijzigt (dan herrekend mét chip + tijdlijnregel); zonder btw-code blijft het bedrag staan mét de chip "tarief onbekend"; de controle "Btw-bedrag past bij tarief" blijft de poort.
Gewenst: btw-bedrag herberekent bij wijziging van het btw-percentage én bij wijziging van het nettobedrag.

### [ ] FV-10 · Geen horizontale scrollbalk bij het boeken · Verbetering · P2
> **Status (CC feedbackrun A, 25-09):** gedaan — het controlescherm scrolt op 1440/1385/1280/1170/1024/768 niet horizontaal (harnas-sweep groen); de regeltabel scrolt bij een smal paneel intern (bestaande norm).
Gewenst: alle kolommen passen op één scherm zonder horizontaal scrollen.

### [ ] FV-11 · Boekingsscherm standaard breder dan de factuurweergave · Verbetering · P2
> **Status (CC feedbackrun A, 25-09):** gedaan — boekingskolom standaard 58 % (factuurbeeld 42 %), slepen mét pointer capture/zonder tekstselectie/per animatieframe; de gekozen breedte blijft per gebruiker onthouden (bestaande opslag).
Nu: de breedte is zelf aan te passen, maar dat werkt slecht en het slepen loopt stroef.
Gewenst: standaard een bredere boekingskolom dan de factuurweergave; soepel slepen met vasthouden van de gekozen breedte per gebruiker.

### [ ] FV-12 · Knop "verdelen over projecten" · Feature · P2
> **Status (CC feedbackrun A, 25-09):** aangepaste vorm — knop "Verdelen over projecten" bij het regelblok; de verdeelmethode is de standaardsleutel van de administratie afgeleid uit de geboekte verdelingen van de laatste 12 maanden (Universal = omzetsleutel, besluit 21-09; niet hardcoded), "Anders…" toont de overige methodes; verdeling achteraf aanpasbaar (bestaand).
Nu: handmatig kiezen uit circa 20 verdeelmethodes.
Gewenst: één knop "verdelen"; het systeem bepaalt zelf de methode en de verdeling. Verdeling achteraf aanpasbaar. Knop op een logischere plek in het scherm.

### [ ] FV-13 · Periode toont slechts één week · Bug · P2
> **Status (CC feedbackrun A, 25-09):** gedaan — vastgesteld dat het het kopveld "Periode (weken)" op het controlescherm is; de chip toont nu "van … tot …" uit de factuur naast de weeknummers, en zonder periode op de factuur staat er letterlijk "week van de factuurdatum (aanname)".
Nu: er staat één week.
Gewenst: periode als "van: … tot: …".

---

## 3. Crediteurenbeheer

### [ ] FV-14 · Crediteur aanmaken zonder zicht op de factuur · Bug · P1
> **Status (CC feedbackrun A, 25-09):** gedaan (25-09, blok 5) — "Nieuwe crediteur" is een niet-modaal zijpaneel naast de factuur; KvK, btw-nummer, IBAN én adres (uit de UBL) vooringevuld met chips per veld; opslaan = de bestaande Reeleezee-Vendor-PUT (adres fail-open); geen IBAN = waarschuwing, geen blokkade.
Nu: het nieuwe scherm vraagt om KVK-nummer, btw-nummer en IBAN, terwijl die gegevens op de factuur staan die op dat moment niet zichtbaar is; de rest van het scherm wordt grijs.
Gewenst: pop-up die naast de factuur te plaatsen is, factuur blijft leesbaar. Idealiter worden KVK, btw-nummer en IBAN automatisch uit de factuur gevuld.
Acceptatie:
- Crediteur aanmaken kan met de factuur zichtbaar in beeld.
- Herkende gegevens staan vooringevuld.

### [ ] FV-15 · Crediteur achteraf aanpassen en veldvalidatie · Bug · P2
> **Status (CC feedbackrun A, 25-09):** gedaan (25-09, blok 5, aangepaste vorm) — "Gegevens bewerken…" op de crediteur-kaart wijzigt naam/adres/KvK/btw via `PUT …/crediteuren/{id}` (Reeleezee + geheugen, audit oud→nieuw); een ontbrekend IBAN is een waarschuwing bij opslaan (niet blokkerend, incasso/buitenland); IBAN toevoegen/wijzigen loopt bewust altijd via de bestaande IBAN-wissel/vier-ogen-route, nooit als vrij veld.
Nu: een crediteur met alleen KVK- en btw-nummer wordt geaccepteerd; het bankrekeningnummer kan daarna niet meer worden toegevoegd.
Gewenst: crediteurgegevens blijven bewerkbaar. Ontbrekende verplichte velden (IBAN) geven een waarschuwing bij opslaan.

---

## 4. Status, periodes en workflow

### [ ] FV-16 · Boeken in geblokkeerde btw-periode wordt niet tegengehouden · Bug · P1
> **Status (CC feedbackrun A, 25-09):** aangepaste vorm — géén blokkade maar een ORANJE controle "Factuurdatum valt in een ingediende aangifteperiode" mét de bewuste keuze "Boeken (btw in volgend tijdvak)" (tijdlijn + audit); nagekomen facturen zijn legitiem en RLZ verschuift de btw zelf naar het volgende open tijdvak; automatisch boeken doet het nooit; doorbelasting toont een LET OP als één kant in een ingediende periode valt (gebouwd 25-09, blok 4).
Nu: facturen met factuurdatum mei/juni zijn te boeken terwijl die btw-aangifteperiodes al zijn afgesloten.
Gewenst: blokkade op boeken in een gesloten periode, met duidelijke melding.
Let op: betreft onder meer de interne facturen van Universal.

### [ ] FV-17 · Verkeerde status na terughalen uit de accorderingsflow · Bug · P1
> **Status (CC feedbackrun A, 25-09):** vervalt — besluit Peter 21-09 blijft: "Corrigeren…" zet een document terug op klaar_om_te_boeken mét gele balk (regels zoals ze waren, harde checks vers); een terugval naar te_controleren zou dat besluit herroepen. Hooguit later een knop "voorstel opnieuw beoordelen" (niet gebouwd).
Nu: een geboekte factuur die uit de accorderingsflow wordt gehaald (factuurdatum in Q2) komt terug als "klaar om te boeken".
Gewenst: status wordt "te controleren".

### [ ] FV-18 · Scherm loopt vast bij wisselen van tabblad · Bug · P1
> **Status (CC feedbackrun A, 25-09):** gedaan (aangepaste vorm) — gereproduceerd mét meting in het harnas (400/2000 rijen, 20 wissels): een tabwissel zelf start geen server-request, maar mét klant-accordering aan deed de bulk-balk per wissel een administraties-fetch en herstartte/stapelde de 3-seconden-verversing (productie-log 24-09: tien lijst-requests op rij bij een lijstroute van 1,6–2,5 s) mét een volledige her-tekening van alle rijen per antwoord; gefixt (geen fetch per wissel, vaste poll die niet stapelt en niets tekent bij een ongewijzigd antwoord, lopende requests afgebroken bij wissel/unmount) + regressietest + meetscript; de kale tekenkosten per wissel schalen nog met het aantal rijen (beslispunt rij-virtualisatie); werkt in productie: niet gemeten.
Nu: wisselen tussen "te controleren" en "klaar om te boeken" laat het scherm regelmatig vastlopen.
Acceptatie: 20x wisselen zonder vastlopen; oorzaak vastgelegd (reproductiestappen, console/log).

---

## 5. Zoeken

### [ ] FV-20 · Zoeken onder "alle" zoekt niet in alle statussen · Bug · P1
> **Status (CC feedbackrun A, 25-09):** gedaan (aangepaste vorm, 25-09) — het kantoorwerk-filter heet nu "Open (N)"; een echte "Alles (N)" toont ook wachten op anderen, geboekt en afgehandeld (server-side, per 200 rijen, statuschip per rij); zoeken op de klantpagina zoekt server-side over alle statussen, zodat de Exact-factuur op "wachten op anderen" én geboekte facturen vindbaar zijn.
Nu: zoeken onder "alle" doorzoekt alleen status "te controleren". De Exact-factuur met status "wachten op anderen" is niet vindbaar.
Acceptatie: zoeken onder "alle" geeft resultaten over elke status, inclusief geboekt en wachten op anderen.

---

## Bijlage A · Herkenningsregels per crediteur

Hoort bij FV-03. Regels voor het automatisch invullen van rubricering en omschrijving.

### Project

- **Elke boekingsregel heeft een projectnummer. Boeken zonder project kan niet.**
- Het projectnummer komt van de factuur zelf, per factuur opnieuw bepaald. Nooit overnemen van de vorige factuur van dezelfde leverancier (FV-02).
- Bronvolgorde: projectreferentie op de factuur of bijlage → koppeling in Zenvoices → voorstel op basis van historie, zichtbaar gemarkeerd als voorstel.
- Formaat: legacy 3-cijferig (100–189) of jaargebonden `JJnnn` (25xxx = 2025, 26xxx = 2026). Vrije tekst als projectnummer accepteren is fout.
- Afgesloten projecten worden niet voorgesteld, tenzij de factuur er expliciet naar verwijst.
- Is het project niet te bepalen: melden en tegenhouden. Niet leeg laten, niet gokken.
- Eén factuur kan over meerdere projecten lopen; dan verdelen (FV-12). De verdeling telt op tot het factuurtotaal.

### Algemeen

- Vier rubrieken, niets anders: **Diverse**, **Huur**, **Vrachtkosten**, **Onbruikbaar/defect**. Eén factuur mag meerdere rubrieken vullen.
- Som van de rubrieken = totaal excl. btw. Wijkt het af, dan is de uitsplitsing fout: melden, niet afronden.
- Negatieve bedragen zijn creditnota's. Herkennen, niet negeren.
- Crediteur matchen op genormaliseerde naam: hoofdletterongevoelig, zonder rechtsvorm, zonder leestekens (FV-21).
- Omschrijving: kort, kleine letters, geen leverancierstaal. Datums `dd-mm`, periodes `dd-mm tm dd-mm`, maanden voluit. Verwijzingen naar bijlagen strippen (FV-05).
- Omschrijving leeg laten mag als de factuur niets toevoegt. Niet verzinnen.

---

### Universal Nederland B.V.

Verhuur steigermateriaal, intern.

- *huur, huurperiode* → **Huur**. Staat vrijwel altijd op de factuur.
- *levering, geleverd, retour, vrachtkosten, transport* → **Vrachtkosten**.
- *defect, onbruikbaar, beschadigd* → **Onbruikbaar/defect**. Staat uitsluitend op de bijlage, nooit op het factuurhoofd — zonder bijlage uitlezen (FV-04) is de rubricering incompleet.
- *schoonmaak* → **Diverse**.
- Omschrijving, drie vormen:
  - `levering <dd-mm>` — bij Huur + Vrachtkosten
  - `retour <dd-mm>` — bij Huur + Vrachtkosten + defect
  - `huurperiode <maand>` — doorlopende huur, alleen Huur
- Controle: vrachtkosten zonder levering- of retourvermelding is verdacht.

### Floor Bouwliftenservice

Bouwliften: huur plus werkzaamheden.

- *huur* → **Huur**.
- *montage, demontage, optoppen, omzetten, regie, liftmontage, afslagen, keuring* → **Diverse**.
- *transport, heen, retour* → **Vrachtkosten**.
- Omschrijving: gevonden termen in die volgorde opsommen, met periode of maand erachter. `huur, montage, demontage, transport juli`, `huur, optoppen juli`, `montage 10,5m 3 afslagen huur 26-2 tm 28-2`.
- Vaak meerdere rubrieken op één factuur. Niet alles in Huur gooien.

### Hoogwerkservice Hardinxveld

- *huur, liftperiode* → **Huur**. Vast bedrag per twee weken (690 / 860 / 970) — bruikbaar als controle op de splitsing.
- *verzekering, keuring* → **Diverse**. Altijd, nooit in Huur.
- *montage, ophogen, slagen* → **Diverse**.
- *aanvoer, afvoer, transport* → **Vrachtkosten**.
- Omschrijving: periode voorop, dan de posten. `10-7 tm 23-7, verzekering, transport`, `23-01 aanvoer + montage + keuring`, `huur 20-02 tm 05-03 ophogen lift 2 slagen`.
- Creditregels komen hier voor: `credit op 3 weken bouwvak`.

### Huvanco Verhuur- en Handelmaatschappij B.V.

- Standaard alles → **Huur**.
- Alleen splitsen bij een expliciete vracht- of deelvrachtregel → **Vrachtkosten**.
- Omschrijving: transportmoment of periode. `heen 27-06`, `retour 3-10`, `01-07 tm 31-7`, `01-07 tm 31-7 en deelvracht 6-7`.

### Steigertekening.nl bv

- Altijd **Diverse**. Nooit Huur, vracht of defect.
- Omschrijving: `steigertekening`, aangevuld met doorbelastingsafspraken als die op de factuur staan.

### Universal Verkoop B.V.

- Materiaalverkoop → **Diverse**. Verhuurde onderdelen → **Huur**.
- Omschrijving: artikelomschrijving van de factuurregel overnemen. `Steigernet groen 4x`, `Schroefoog met plug`, `verankeringsbuis met platte plaat`.
- Niet verwarren met Universal Nederland B.V.

### Scafom-rux

- *huur ringscaff* → **Huur**. Transport → **Vrachtkosten** (vast bedrag 528 of 1056).
- Omschrijving: `huur ringscaff steiger <dd-mm> tm <dd-mm>`. De factuur schrijft `HUUR RINGSCAFF STEIGER periode 3 van 06-03-2026 t/m 22-03-2026`; normaliseren naar kleine letters en `tm`.

### Overige crediteuren

Metselbedrijf Ben Kuijer, Argos Packaging Systems, Damitech, ABS trading, H.T.I. Verhuur Wijchen, G.J. Rijksen en Zoon.

- Materiaal en diensten → **Diverse**. Transportfacturen (H.T.I., Rijksen) → **Vrachtkosten**.
- Omschrijving: artikelomschrijving van de factuur.
- Te weinig historie voor een patroon: voorstel doen, altijd ter controle aanbieden.
