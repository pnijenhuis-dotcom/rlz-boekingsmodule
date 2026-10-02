# Feedback controlescherm — Peter 02-10-2026 (letterlijk), live meegekeken door Cowork

Casus: Universal Steigerbouw (administratie `3ee6edf0`), document `f00117f4`, factuur RLZ-2080142625 van Universal Nederland B.V.
(30-06-2026, € 908,89; twee regels brandstof diesel Floor/Ogur, 21 %). Scherm: `/documenten/3ee6edf0…/f00117f4…?soort=inkoopfactuur`.

## Peter (letterlijk)
1. "Die velden onder crediteuren (AI 85% · herkend op btw-nummer NL · uit btw-nummer crediteur btw NL826228525B01 KvK 72404272 uit
   factuur) hoef ik allemaal niet te zien, gewoon crediteur selecteren en achter de schermen matchen, maar dit is weer van die info waar
   je wel naar kijkt en niks mee doet. verbergen"
2. "dito met alle groene signalen onder kopgegevens. als het klopt niet tonen, maakt alleen het beeldscherm heel druk en als het niet
   klopt past de medewerker het wel aan"
3. "boekingsregels. Waar is mijn vinkje splitsen?"
4. "boekingsregels. waarom splits die deze automatisch? niet om gevraagd?"
5. "boekingsregels. in dit geval is dit brandstof, heeft niks met 1 project te maken en toch is project invullen verplicht. Niet goed"
6. "de knop verdelen over projecten doet hier niks? Onderin projectverdeling staat 0,00"
7. "waarom is controles uit de mail zo groot, maak die hetzelfde als de rest"
+ "graag even live meekijken want dit werkt rommelig"

## Waarneming Cowork (zelfde scherm, 02-10 ~09:45)
- Crediteur-blok: 5 chips onder het veld (AI 85 % · herkend op btw-nummer / NL · uit btw-nummer crediteur / btw … / KvK … / uit
  factuur). Kopgegevens: élk veld een groene "AI 98 %"/"uit factuur"-chip, plus een paarse periode-chip "wk 27 · 2026 … (aanname)".
- Boekingsregels: twee regels (= de twee factuurregels), géén samenvoeg-vinkje zichtbaar; de tabel scrolt horizontaal (kolom
  OMSCHRIJVING en het ×-knopje vallen buiten beeld — overflow-les 18-09 geschonden). Per regel 4–5 chips (Geheugen 71 %, gesplitste
  stem, factuur 21 %, Geheugen 100 %, btw via leverancier-niveau, voorstel uit historie, AI 95 %).
- **Project per regel = "Afgesloten 25147 On…" — voorstel uit historie.** Dat is een AFGESLOTEN project als prefill; regel FV-02
  (25-09): afgesloten alleen bij exacte factuurverwijzing, geheugen = laatste bron. Hier dus fout.
- **Grootboek 7005 Inhuur steiger** (Geheugen 71 %) voor brandstof diesel — het regel-geheugen per leverancier wint van de inhoud.
- "Verdelen over projecten" doet niets zichtbaar; Projectverdeling toont "Restant — pro rato omzet september 2026 · € 0,00 · verdeeld
  100 % ✓": de verdeling pakt alleen het bedrag dat géén project heeft, en beide regels hebben al (een verkeerd) project → restant 0.
  Verwarrend: de knop zou de projecten van de regels moeten leegmaken/overrulen, of melden waarom er niets te verdelen is.
- Onder "Controles 12/13 groen": kop "UIT DE E-MAIL" in groot kapitaal (sectiekop-stijl) terwijl Extractie-details/Opmerkingen/Tijdlijn
  kleine inklapregels zijn — punt 7.
- Oranje check "Factuurdatum valt in een ingediende aangifteperiode" (30-06 in Q2) staat vast onderin boven de knoppen; correct per
  FV-16, maar neemt bij elk oud document een derde van de knoppenbalk in.
