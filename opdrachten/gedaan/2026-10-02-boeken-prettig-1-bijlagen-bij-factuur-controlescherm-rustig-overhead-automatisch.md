uitgevoerd 2026-10-02, rapport: docs/rapporten/2026-10-02-boeken-prettig-1.md

# Opdracht 02-10 — "Boeken moet weer prettig": bijlagen bij de factuur, rustig controlescherm, overhead automatisch (punten 1–6)

Prioriteit en volgorde = besluit Peter 02-10 ("nu: 1, 2, 3, 4, 5, 6 — daarna de rest"). Bouw in deze volgorde, commit per punt.
Casus om tegen te toetsen: Universal Steigerbouw `3ee6edf0`, document `f00117f4` (RLZ-2080142625, brandstof diesel, 2 regels) — zie
`docs/feedback/2026-10-02-controlescherm-feedback-peter.md` (letterlijke feedback + waarnemingen Cowork) en `docs/gesprekken/2026-10-02.md`.
Peter 30-09: "alles wat werkt moet af en af blijven; hou het simpel" → GEEN bijvangst, geen nieuwe instellingen, geen nieuwe knoppen
buiten wat hieronder staat.

LEESPLICHT: docs/regels/intake-extractie.md, docs/regels/werkvoorraad-controlescherm.md, docs/regels/verplichtingen-projecten-voorraad.md,
docs/regels/kantoor-frontend.md, docs/regels/werkloop-productie.md; BESLISSINGEN-secties die de regels noemen (samenvoegen 18-09/23-09,
project-bronvolgorde 25-09, comfort controlescherm 25-09, Universal omzetsleutel 21-09, nabundel-motor 03-09).

## 1. Eén mail = één document — bijlagen blijven bij de factuur (PRIORITEIT 1, Peter: "scheelt heel veel werk")
Regel bij intake (alle kanalen, incl. facturen@kempengroep.nl):
- Per mail bepaalt de bestaande deterministische detectie per bijlage of het een factuur is (factuurnummer + totaal + afzender/
  tenaamstelling; UBL = factuur). Precies ÉÉN factuur-bijlage → dát wordt het document; álle overige bijlagen (specificaties,
  huurstaten, werkbonnen, foto's, xlsx/csv) hangen eraan als bijlage: zichtbaar in het controlescherm náást de factuur (tabblad/
  keuzelijst in het bijlage-paneel), en bij boeken mee naar RLZ als extra `/Uploads`. Niet extraheren, niet splitsen, geen eigen
  werkvoorraad-rij.
- Meerdere factuur-bijlagen in één mail → wél per factuur een document; niet-factuur-bijlagen gaan naar de factuur waarvan het
  factuur- of werknummer in bestandsnaam of tekst staat; geen eenduidige treffer → bij álle facturen uit die mail mét chip
  "bijlage niet eenduidig" (liever dubbel dan kwijt). De 0106-regel "nooit splitsen binnen één PDF" blijft.
- Nul factuur-bijlagen → bestaand gedrag (verzamelbak), ongewijzigd.
- Nazorg-CLI `bijlagen-nabundelen` (dry-run default, `--uitvoeren` ná Peters "ja", job-image): per `intake_bericht` (Message-ID) de al
  gesplitste documenten volgens dezelfde regel samenvoegen; de bijlage-documenten krijgen status `samengevoegd` mét verwijzing
  (nooit verwijderen, terugdraaibaar), al GEBOEKTE facturen krijgen de bijlage alsnog als RLZ-upload. Dry-run-uitvoer = lijst
  "factuur ← bijlagen" per administratie + totalen; Cowork leest hem. Dagteller `bijlagen_gebundeld` in de reconciliatiemail.

## 2. Rustig scherm: groen = niets tonen
- Crediteur, kopgegevens en regels: alle herkomst-/zekerheidschips (AI %, "uit factuur", "herkend op btw-nummer", "Geheugen 71 %",
  "gesplitste stem", "btw via leverancier-niveau", "voorstel uit historie", KvK/btw-chips) verdwijnen uit de standaardweergave.
  Zichtbaar blijft uitsluitend een AFWIJKING (oranje/rood: conflict, onzeker < drempel, niet gevonden) als één regel onder het veld.
  Eén `linkbtn` "Herkomst tonen" per blok klapt alles uit voor wie het wil zien. Harde checks en de oranje aangifte-check ongewijzigd.
- Periode-chip "wk … (aanname)" alleen tonen als de periode NIET uit de factuur komt.

## 3. Samenvoeg-vinkje terug
- Bij ≥ 2 regels staat het vinkje "Regels samenvoegen" boven de tabel (regel 18-09/23-09: bron = opgeslagen regels, Σ netto/btw, één
  btw-code; kan het niet → chip mét reden). Toets op `f00117f4`: twee regels → één regel 751,15 / 157,74.

## 4. Project: niets uit de historie zonder factuurverwijzing, nooit een afgesloten project
- Projectprefill alleen uit factuur/werknummer of klant-loze cachecode (FV-02); het GEHEUGEN vult het projectveld NIET meer in (ook niet
  als "voorstel uit historie") — het mag hooguit onder "Herkomst tonen" staan. Een afgesloten project nooit, behalve bij exacte
  factuurverwijzing (bestaande regel). Autoboek-pad: idem.
- Grootboek-geheugen per leverancier (punt 8 van de lijst) NIET in deze opdracht.

## 5. Overhead automatisch via de omzetsleutel
- Regels zonder project op een kostenrekening = overhead: de projectverdeling staat bij openen al klaar voor het volledige bedrag
  volgens de standaardsleutel van de administratie (Universal = omzetsleutel, geen OVH-project; sleutelmaand = MAAND VAN DE
  FACTUURDATUM — besluit 02-10, herziet "huidige maand"). Boeken kan direct; geen klik op "Verdelen" nodig.
- "Verdelen over projecten" overrult: maakt de regelprojecten leeg (tijdlijnregel) en verdeelt alles; nooit meer "€ 0,00 · verdeeld
  100 %" zonder uitleg. De harde check "project verplicht" verwijst naar de verdeling in plaats van een project af te dwingen.

## 6. Balansrekeningen zonder project
- Projecteis en projectverdeling gelden uitsluitend voor kostenrekeningen (W&V-type uit de sync, RLZ `AccountType`/Odoo
  `account_type`). Voorraad (3xxx), activa (0xxx), tussenrekeningen: géén projectveld op de regel, geen verdeling, geen check.
  Deterministisch op rekeningtype — geen instelling, geen keuzelijst. Activa-kaart (0168) ongewijzigd.

## Niet doen
Geen nieuwe instellingen; geen wijziging aan btw-logica, bank, accordering, mails (punt 14 = aparte opdracht); geen Vastly-werk.

## Af
Per punt een test op de casus `f00117f4` (fixture) + guard op het afwezig-pad; volledige backend-suite, vitest, tsc, doc-guards groen;
WAT_IS_NIEUW (klantleesbaar, nieuwste bovenaan); BESLISSINGEN-sectie "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM,
OVERHEAD AUTOMATISCH (Peter 02-10)"; regels-alinea's in intake-extractie.md, werkvoorraad-controlescherm.md en
verplichtingen-projecten-voorraad.md; CLAUDE.md hooguit één verwijsregel per domein; rapport docs/rapporten/2026-10-02-boeken-prettig-1.md
+ INDEX + "Gelezen regels"; "werkt in productie: niet gemeten" + vervolg-nameting (dry-run `bijlagen-nabundelen` op productie via de
job = de meting; echte run ná Peters "ja"). Committen (ook de nog ongecommitte gespreksverslagen/terminalbestanden; de xlsx in
docs/rapporten blijft buiten git); de Stop-hook pusht.
