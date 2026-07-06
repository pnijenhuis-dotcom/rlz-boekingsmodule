# Documentanalyse Universal Steigerbouw (7 praktijkdocumenten, 3 juli 2026)

Geanalyseerd: creditfactuur Spot Services, inkoopfactuur Delta Steigers, getekende urenstaat wk 24
(Groesbeek/Janssen), huurfactuur Universal Verhuur (intercompany, met huuroverzicht-bijlage),
bouwliftfactuur Floor, onderaannemingscontract Wijnen Bouw (verkoopkant, € 81.000), en
onderaannemingscontract KUDO/Pleijweg (verkoopkant). Bevindingen → ontwerpaanpassingen.

## 1. Btw verlegd is de NORM, niet de uitzondering ⚠️ (aanpassing vereist)

Spot Services: verlegd. Delta Steigers: "BTW verlegd: NL866814024B01". Wijnen-contract: verleggings-
regeling expliciet van toepassing. In de bouwketen (onderaanneming) is vrijwel alle arbeid verlegd;
alleen materieelhuur van niet-onderaannemers (Floor bouwlift, Universal Verhuur) draagt 21%.

**Ontwerpgevolg:** de AI-extractie moet "btw verlegd" expliciet herkennen (tekstpatronen + btw 0 op
factuur ≠ 0%-tarief!) en de harde check wordt: factuur zonder btw van een arbeids-leverancier →
verlegd voorstellen, nooit 0% of vrijgesteld. Verkeerde keuze raakt de btw-aangifte (rubriek 2a).
Het boekingsgeheugen leert de btw-behandeling per leverancier.

## 2. Leveranciers gebruiken EIGEN werknummers ⚠️ (aanpassing vereist)

Spot: "Projectnummer 24208 / Zwolle" (hun nummer). Universal Verhuur: "Werknr W03501" naast
"25147 - van Kessel". Delta: alleen "Groesbeek week24". Wijnen: "ons werknummer 23065".

**Ontwerpgevolg:** projectherkenning kan niet alleen op Universal's eigen code matchen. Nodig:
mapping-tabel leverancier-werknummer ↔ RLZ-project in het boekingsgeheugen, plus fuzzy match op
plaats/opdrachtgever ("Zwolle", "Groesbeek") tegen de projectnamen ("25xxx Plaats (Opdrachtgever)").
Eerste keer handmatig bevestigen → daarna automatisch voorstel.

## 3. De week-drie-eenheid: urenstaat ↔ inkoopfactuur ↔ verkoopfactuur

De getekende urenstaat wk 24 (110 m² montage, 36 uur regie, handtekening opdrachtgever) matcht
exact de Delta-inkoopfactuur (110 × montage à € 6, 36 × regie à € 47,50). En de opmerking op de
staat is goud: "36 uur regie parkeren we totdat we akkoord van de uitvoerder van Janssen hebben".

**Ontwerpgevolg:** (a) urenstaat = eigen documenttype, gekoppeld aan project + week;
(b) controle inkoopfactuur onderaannemer ↔ getekende staat (aantallen) als harde check;
(c) "geparkeerde" uren zijn exact ons meerwerk-zonder-akkoord-signaal — inkoop komt binnen,
omzet mag nog niet gefactureerd → status "wacht op akkoord opdrachtgever" op de projectpagina.

## 4. Intercompany-huur met huuroverzicht = de m²-bron

Universal Verhuur B.V. (zusterbedrijf!) factureert maandelijks huur per werk, met bijlage per
item: leverdatum, aantal, STAND, dagen, dagprijs — inclusief regel "Vierkante meter: 794 → 836
→ 736" per datum.

**Ontwerpgevolg:** (a) intercompany-leverancier als vlag (eigen beheersing, geen externe
verplichting); (b) de huurbijlage wordt gepárst: de m²-standen per datum zijn de exacte bron voor
de voortgangsbalk én voor "steiger staat nog"-detectie (huurdagen lopen door zonder omzet) —
beter dan schatten uit omschrijvingen. RLZ-factuurnummer "RLZ-2080142038" bevestigt dat de
verhuur-BV zelf al uit RLZ factureert.

## 5. Getekende contracten = budget (verkoop) én verplichting (inkoop)

Wijnen-contract: aanneemsom € 81.000 vast, met prijsopbouw per onderdeel in m², m¹, stuks en
manuren (gevelsteiger 4.257 m² = € 59.598, opperssteiger 249 m², gaas 3.900 m², …), termijn-
regeling "100% naar rato werk gereed", meerwerk uitsluitend na schriftelijke opdracht, boete
€ 3.000/kalenderdag bij te laat, uurtarief verrekeningen € 55. KUDO-contract: huurweken niet
verrekenbaar tenzij overschrijding > 1 week, hoeveelheden niet verrekenbaar tenzij ontwerpwijziging.

**Ontwerpgevolg:** de offerte-ontleding moet eenheden aankunnen (m², m¹, stuks, manuren, posten)
— bevestigt het werksoort-budgetmodel en verfijnt het. Verrekenbaarheidsregels ("huurweken niet
verrekenbaar tenzij…") horen als contractkenmerk bij het project: het signaal "huurweek niet
gefactureerd" moet weten of die huur überhaupt factureerbaar ís. Boeteclausules → deadline-veld
met signaal.

## 6. WKA / G-rekening raakt de bankmodule ⚠️

Wijnen eist 40% van de loonsom op de G-rekening; facturen moeten contractnummer, tijdvak,
loonkostenbestanddeel en uren vermelden. Universal betaalt zijn eigen onderaannemers vermoedelijk
ook deels via G-rekening.

**Ontwerpgevolg:** één inkoopfactuur → twee betalingen (regulier + G-rekening). De bankmodule
moet gesplitste betalingen op één factuur kunnen afletteren (deelbetaling-matching was al ontworpen;
G-rekening is de standaard-case, niet de uitzondering). Contractnummer op facturen = extra
matchsleutel factuur ↔ contract.

## 7. Creditnota's met negatieve regels

Spot Services: creditfactuur met negatieve regels (credit −€ 1.000, parkeergeld −€ 350) in een
regellijst vol nulregels (tariefstaffel-layout).

**Ontwerpgevolg:** extractie filtert nulregels weg, accepteert negatieve bedragen, en de
regeltelling-check werkt met gesaldeerde bedragen. Creditnota krijgt eigen type-chip en telt
negatief mee in de projectkosten.

## 8. AVG: BSN en geboortedata op urenstaten ⚠️ (privacy-maatregel)

De urenstaat bevat BSN-kolom en geboortedata van medewerkers.

**Ontwerpgevolg:** de AI-extractie leest BSN's NOOIT uit en ze komen nooit in de zoekindex,
database of AI-output terecht. Het brondocument zelf blijft als bijlage bewaard (WKA-bewaarplicht),
maar de preview maskeert de BSN-kolom. Dit wordt een hard principe in CLAUDE.md.

## Samenvattend: wat wijzigt er

| # | Wijziging | Waar |
|---|-----------|------|
| 1 | Btw-verlegd-herkenning + harde check (geen 0%-verwarring) | extractie + checks |
| 2 | Leverancier-werknummer ↔ RLZ-project-mapping + fuzzy plaatsmatch | boekingsgeheugen |
| 3 | Documenttype urenstaat + match inkoopfactuur ↔ getekende staat | pipeline + projecten |
| 4 | Huurbijlage-parsing → m²-standen als voortgangs-/huurbron | projecten |
| 5 | Contract-ontleding: eenheden, verrekenbaarheid, boetes, termijnregeling | offerte-ontleding |
| 6 | G-rekening-deelbetalingen standaard in bankmatching | bank |
| 7 | Creditnota's: negatieve regels, nulregel-filter | extractie |
| 8 | BSN-maskering, nooit indexeren | privacy, hard principe |
