uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-samenvoegen-en-regelbtw.md

Domeinen: werkvoorraad-controlescherm, btw, intake-extractie, kantoor-frontend

# BUG 18-09 — "Splitsen per regel" staat UIT maar het scherm toont 21 losse regels; regel-geheugen overschrijft de factuur-btw (0 % → 9 %)
# (Peter 18-09, screenshot Zilver Horeca Fac-25-022711, 17-12-2025, BLOW, totaal € 738,27 op de pinbon)

**Peter 18-09 (letterlijk):** "hij splitst nu per regel zonder het vinkje?"

## Wat het scherm toont
- Vinkje "Splitsen per regel" **uit**, hint-tekst "Samengevoegd tot één boekingsregel (21 factuurregels gelezen)", maar de tabel toont
  **21 regels** (alle 7049 Diverse inkopen, chip "Geheugen 100 %" op grootboek én btw). Tekst en tabel spreken elkaar tegen.
- Alle 21 regels **9 % · NL, Laag** uit het geheugen — terwijl de factuur per regel een btw-kolom heeft: de acht **Emballage (24 stuks)**-
  regels staan op de factuur op **0 %** (statiegeld). Het scherm rekent er 9 % bij: Emballage 3 × 3,60 = 10,80 → bruto **11,77**
  (= 10,80 × 1,09). Twix 17,95 → 19,57, Snicker 18,95 → 20,66 enz. De factuurregels zijn netto-bedragen; de bruto-kolom is dus uit netto
  + geheugen-tarief berekend, niet uit de factuur. Voor de 0 %-regels is dat fout, en het totaal sluit daardoor nooit op € 738,27.
- Regels 1 en 2 (Balisto Yobbery, AA Drink) zonder bedrag — op de foto liggen die bedragen onder de pinbon; verklaarbaar, blijft handwerk.
- Totaalbedrag leeg: het totaal staat alleen op de pinbon ("Totaal: 738,27 EUR"), niet op de factuur zelf.

## Te onderzoeken (Feiten eerst — dit document, niet redeneren vanuit de code alleen)
1. **Modus vs. inhoud.** `BoekvoorstelPanel.tsx` r. 861–881: als `dto.opgeslagen && dto.regels_samenvoegen` waar is, wordt
   `dto.regels` als de SAMENGEVOEGDE variant getoond. Hypothese: voor dit document staat `regels_samenvoegen = true` (voorkeur per
   crediteur / standaard) terwijl `dto.regels` 21 opgeslagen regels bevat (eerder gesplitst opgeslagen via autosave of het regel-
   geheugenvoorstel, r. 909 e.v., dat per regel vult). Lees het opgeslagen boekvoorstel + tijdlijn van dit document uit en stel vast
   welke combinatie het is. Tweede kandidaat: het regel-GB-geheugen (medewerker-wens 04-09) overschrijft `regels` met een gesplitste
   set zonder de modus mee te zetten.
2. **Btw per regel uit de factuur.** De extractie heeft per regel een btw-percentage gelezen (kolom "BTW" op de factuur: 9 %/0 %). Ga na
   of dat veld in het AI-/regelvoorstel zit en waarom het regel-geheugen (9 %) het wint — de winnaarsvolgorde zegt factuur > geheugen.
3. **Bruto-kolom.** Waar komt 11,77 vandaan (`bedragModus.ts` / `regelsom.ts`)? Bruto mag alleen uit netto × (1 + tarief) volgen als het
   tarief van de FACTUURREGEL is, niet van het geheugen.

## Fix (regels; volledige tekst naar `docs/regels/werkvoorraad-controlescherm.md` en `btw.md`)
1. **Eén waarheid voor de modus**: het vinkje, de hint-tekst en de getoonde regels komen uit dezelfde afgeleide stand. Opgeslagen regels
   die niet bij de modus passen (N > 1 bij samengevoegd) → modus volgt de data (vinkje aan, hint "Losse factuurregels") mét tijdlijnregel
   "weergave hersteld: 21 opgeslagen regels, modus stond op samengevoegd" — nooit stil de data wegdrukken, nooit stil de modus liegen.
   Guard-test op deze combinatie.
2. **Factuur-btw per regel wint van het geheugen** (bestaande winnaarsvolgorde, nu ook op regelniveau): heeft de factuurregel een
   btw-percentage dat als RLZ-tarief bestaat, dan dát tarief (chip "factuur 0 %"); het geheugen mag alleen het grootboek leveren en het
   tarief als de factuurregel geen percentage draagt. Emballage/statiegeld 0 % → "NL, Nul" (of het in deze administratie gebruikte
   0 %-tarief; nooit verlegd, nooit vrijgesteld raden — de bestaande regel "0 % zonder basis = leeg" geldt, maar een factuurkolom 0 % IS
   de basis).
3. **Bruto/netto per regel uit de factuur**: regelbedrag netto + factuur-tarief → bruto; nooit netto + geheugen-tarief. Mét de opdracht
   van vandaag (btw volgt tarief) hoort dit in dezelfde `regelsom.py`-functies.
4. **Totaal uit de pinbon**: als de factuur geen totaal draagt maar het document een pin-/kassabon mét "Totaal" bevat, mag de extractie dat
   als totaal voorstellen mét chip "uit pinbon" (AI-veld + deterministische toets: bon-totaal = Σ regels binnen 5 ct → groen; anders
   oranje, mens beslist). Geen stil overnemen.
5. **Gezamenlijke bon-in-de-foto**: regels waarvan het bedrag onleesbaar is (afgedekt) blijven leeg mét chip "niet gelezen (afgedekt)"
   i.p.v. een kale lege cel, zodat de gebruiker ziet waarom.

## Tests & afronding
Vitest: modus-herstel bij N > 1 opgeslagen regels + samengevoegd-vlag; factuur-0 %-regel krijgt Nul-tarief ondanks geheugen 9 %; bruto
= netto × factuur-tarief. Backend-test op regel_prefill (factuur-regeltarief > geheugen). Nameting ná deploy op DIT document (Zilver
Horeca Fac-25-022711, BLOW): vinkje/hint/tabel consistent, Emballage 0 %, totaal 738,27 sluit. Rapport `docs/rapporten/2026-09-18-
samenvoegen-en-regelbtw.md` + INDEX + Gelezen regels + de gevonden oorzaak (welke van de hypotheses) + hoeveel andere documenten in de
werkvoorraad dezelfde inconsistentie dragen (lees-only query). WAT_IS_NIEUW. Één regel voor Peter.
