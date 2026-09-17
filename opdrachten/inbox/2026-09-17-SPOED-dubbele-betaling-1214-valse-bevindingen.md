# SPOEDOPDRACHT 17-09 — Actiemail "Mogelijk dubbel betaald": 1.214 bevindingen in één nacht = valse positieven; bevinding herdefiniëren, bestaande sluiten, nieuwe bevindingssoorten nooit meer op dag één in de actiemail

**Melding Peter 17-09 (actiemail 17-09 ochtend):** tien regels "Mogelijk dubbel betaald" (T&J Hoveniers — Google Cloud, Insify € −40,59,
T Hubers € −20, Helmink via Mollie; Abbegaa — Greenchoice, Alpina € −245,30, Administratiekantoor Nijenhuis, Ziton holding 3×) **"en
1204 andere"**. Peter: "dit moet anders want hier doe ik niks mee." Terecht: Google Cloud, Insify, Greenchoice, Nijenhuis, Ziton zijn
maandelijkse/periodieke betalingen — geen dubbelen. De bevinding `dubbele_betaling_vermoed` (16-09, migratie 0147-run) is over de
volledige historie (400 d) van álle administraties heen gelopen en de "niet periodiek"-uitsluiting heeft niet gewerkt.

Pre-feature-ritueel: BESLISSINGEN "DUPLICAAT-POORT OP HET BOEKMOMENT + DUBBELE BETALING + BEWUST VERWIJDERD (Peter 16-09)",
"RECONCILIATIEMAIL = ACTIEMAIL + SYSTEEMMAIL", "RECONCILIATIE-NAZORG 15-09", "STAANDE GOEDKEURING — PERIODIEK VS BATCH"
(`terugkerend/service.py::classificeer_reeks` = de bestaande periodiek-motor), `app/reconciliatie/`, `app/bank/`, `tests/reconciliatie/
test_actiemail_guard.py`. Kernprincipe 7(2): signaal zonder handeling is niet af — 1.214 signalen zonder handeling is erger dan geen.

## Blok A — Direct: mail stil, bestaande bevindingen sluiten (vóór alles)
- `dubbele_betaling_vermoed` uit de actiemail (categorie advies/stil) tot blok B live is; de 1.214 open bevindingen automatisch
  sluiten mét reden "herdefinitie 17-09 — valse positieven (periodiek)" + audit (`reconciliatie_auto_gesloten`), geen mens-klik.
  Lees-only vooraf: telling per administratie en per tegenpartij-IBAN (top-20) in het rapport, zodat we zien wát er matchte.

## Blok B — Herdefinitie: dubbel betaald = betaling ZONDER tegenoverstaande factuur
Een dubbele betaling is niet "twee gelijke bedragen aan dezelfde IBAN", maar "meer betaald dan er aan facturen tegenover staat".
Nieuwe regel (deterministisch, per crediteur-identiteit, venster 60 d):
1. Kandidaat = twee (of meer) uitgaande betalingen, zelfde tegenpartij-IBAN, cent-exact gelijk, ≤ 60 d uit elkaar.
2. **Uitsluiting periodiek** via `classificeer_reeks` op de betalingsreeks van die IBAN (≥ 3 gelijke bedragen mét maand-/kwartaal-
   /weekpatroon = periodiek → nooit een bevinding) én via bekende periodieke tegenpartijen (incasso-detectie/`terugkerend`,
   `QuickPaymentSelection` "wordt automatisch geïncasseerd").
3. **Factuurtoets (de kern):** tel de facturen van die crediteur (RLZ/Odoo, alle crediteurrecords van de identiteit) mét hetzelfde
   bedrag in het venster ± 30 d. Aantal betalingen > aantal facturen → bevinding; anders niets. Casus Hello Kitchen: 2 betalingen,
   1 factuur (de tweede was in RLZ verwijderd) → bevinding. Google Cloud: 2 betalingen, 2 facturen → niets.
4. Aflettering telt mee: twee betalingen die beide tegen een eigen open post zijn afgeletterd = nooit dubbel; één betaling die niet
   afgeletterd kon worden omdat de post al dicht was = sterk signaal (`OpenAmount`-toets, blok 1 bank).
5. Bevinding draagt de handeling: "Factuur ontbreekt (verwijderd/nooit geboekt) — terugvorderen of factuur alsnog boeken", mét de
   twee bankregels + de gevonden factuur/facturen; acceptatie = "bewust (bv. deelbetaling/creditnota)".
- Gouden-set-casus aa (Hello Kitchen) blijft groen; nieuwe casus "periodiek Google Cloud" = geen bevinding; casus "2 betalingen, 2
  facturen" = geen bevinding.

## Blok C — Structurele guard: een nieuwe bevindingssoort mailt nooit op dag één
- Élke nieuwe reconciliatie-bevindingssoort start in stand `meten` (alleen telling in de systeemmail/rapport + `Inzicht ›
  Reconciliatie` onder een aparte tab "in meting"), en gaat pas naar de actiemail ná een expliciete promotie (Beheerder-instelling of
  CLI) mét de meting erbij. Bovendien harde rem: een soort die in één run > 50 bevindingen produceert gaat automatisch terug naar
  `meten` + systeemfout-LET-OP "bevindingssoort X explodeert (N)" — nooit meer "en 1204 andere" in een actiemail. Guard-test in
  `test_actiemail_guard.py` (nieuwe soort zonder promotie = rood; > 50 = rem).
- Actiemail-tekst: bij afkap "en N andere" ook per administratie een teller, en nooit meer dan 3 regels per administratie.

## Afronding
Migratie alleen als de soort-status een kolom nodig heeft (anders JSON-setting); tests op blok B (periodiek, factuurtoets, aflettering)
en blok C; WAT_IS_NIEUW ("Mogelijk dubbel betaald kijkt nu of er echt een factuur ontbreekt"); BESLISSINGEN "DUBBELE BETALING —
HERDEFINITIE: BETALING ZONDER FACTUUR + BEVINDINGSSOORTEN STARTEN IN METING (Peter 17-09)"; CLAUDE.md verwijsregel; rapport + INDEX
mét "werkt in productie: ja/nee" (meetrecept: `reconciliatie-alles --alleen dubbele_betaling --lees-only` → verwachting: Hello
Kitchen wél, Google Cloud/Insify/Greenchoice/Ziton níét; actiemail 18-09 zonder de soort tenzij gepromoveerd). Les naar
`Platform/registers/verbeteringen.md`: "een nieuwe bevindingssoort eerst lees-only over de historie tellen vóór hij mailt".
