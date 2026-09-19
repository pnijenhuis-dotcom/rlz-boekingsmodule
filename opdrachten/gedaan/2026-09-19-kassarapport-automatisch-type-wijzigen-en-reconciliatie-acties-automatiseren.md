uitgevoerd 2026-09-19, rapport: docs/rapporten/2026-09-19-kassarapport-autotype-en-signalering-sweep.md

Domeinen: omzet, intake-extractie, reconciliatie, werkvoorraad-controlescherm

# OPDRACHT 19-09 — Herkend kassarapport in de inkoopstroom = AUTOMATISCH type wijzigen (geen melding meer) + sweep: welke
# reconciliatie-bevindingen hebben een vaststaande actie die het systeem zelf kan doen (Peter 19-09, screenshot Reconciliatie)

**Peter 19-09 (letterlijk, screenshot Inzicht › Reconciliatie, Van Boxtel Horeca Exploitatie, Journaal 1-9.pdf / 2-9.pdf / 3-9.pdf,
sinds 17-09):** "dit zijn meldingen waar ik dus niks mee doe. Als de module weet dat het verkoopboekingen zijn, wijzig het dan
automatisch. Mocht er een fout tussen zitten dan valt dat op tijdens het boeken en corrigeren we het dan weer, wordt het model steeds
slimmer."

**Stand nu (regel omzet 3):** kassarapport in de inkoopstroom = dagelijkse bevinding mét knop "Type wijzigen → kassarapport". De
herkenning zelf is deterministisch (bron-parsers ProfX-journaal / dagstaat-kascheck / pilates-export, géén AI, geen AVG-gate). De actie
is altijd dezelfde. Een mens laten klikken is dus een testfase-drempel die voorbij is (principe 7 (2)+(3), WERKWIJZE v1.13 "geen
stille no-op").

## A. Automatisch type wijzigen bij een deterministische parser-treffer
1. **Bij intake** (mail, upload, bulk): een document dat als inkoopfactuur binnenkomt maar waarop een bron-parser deterministisch
   aanslaat (ProfX-journaal, dagstaat/kascheck, pilates-export — de bestaande parsers, zelfde drempel als de huidige bevinding) krijgt
   DIRECT soort `kassarapport`, gaat de omzet-verwerking in en verschijnt in het omzet-controlescherm. Tijdlijnregel "type automatisch
   gewijzigd: inkoopfactuur → kassarapport (ProfX-journaal herkend: <kenmerken>)", audit `soort_automatisch_gewijzigd`, chip
   "automatisch getypeerd" op het document. Terugweg op het omzet-controlescherm: "Tóch inkoopfactuur" mét verplichte reden → terug
   naar de inkoopstroom + audit (bestaande verplaats-/soortroute hergebruiken, `documenten/soort.py`).
2. **Dagelijkse reconciliatie**: de bevinding "kassarapport in de werkvoorraad" blijft alleen bestaan voor documenten waar de parser
   NIET eenduidig is (meerdere parsers, of parser-score onder de drempel) — dan wél melding mét de bestaande knop. Eenduidig = systeem.
   Teller in de reconciliatiemail: `kassarapport_autotype` verwacht/gedaan/overgeslagen (geen stille no-op).
3. **Leren**: een "Tóch inkoopfactuur"-correctie op een document van leverancier/afzender X schrijft een observatie
   (`typering_correctie`) zodat de parser voor die afzender ná 2 correcties terugvalt op melden i.p.v. doen (zelfde recency-regel als
   het boekingsgeheugen). Nooit een LLM in deze beslissing.
4. **Nazorg (eenmalig, ná deploy, via de job-image):** alle bestaande open bevindingen "kassarapport in de werkvoorraad" met eenduidige
   parser-treffer alsnog automatisch omzetten (CLI `kassarapport-autotype-nazorg [--administratie] [--dry-run]`), mét tijdlijn + audit
   per document en één rapportregel per administratie; Van Boxtel eerst in de dry-run. De 340 "aandacht nodig" van vandaag: hoeveel
   verdwijnen hiermee?

## B. Sweep: signalering zonder handeling
Lees-only over de bevindingssoorten in productie (leesreplica): per soort aantal open, de actie op de rij, en het antwoord op "is de
actie deterministisch en altijd dezelfde?" Ja → voorstel automatiseren volgens het patroon van A (doen + tijdlijn + audit + terugweg
+ dagteller; opt-out per administratie alleen als testfase). Nee → blijft melding. Bijzondere aandacht voor de **174 "fouten"** en de
492 "in meting": wat zijn dat per soort, sinds wanneer, en welke zijn systeemfouten die geen mens kunnen wachten? Tabel in het rapport;
per soort een regel "automatiseren / melding blijft / systeemfout — opdracht". Niets bouwen buiten A; de sweep is de agenda voor
de volgende run.

## Afronding
Tests: parser-eenduidig → soort kassarapport + tijdlijn + audit; niet-eenduidig → bevinding zoals nu; "Tóch inkoopfactuur" → terug +
observatie; ná 2 correcties → melden; nazorg-CLI idempotent (dry-run = 0 writes). Regels-tekst `omzet.md` (regel 3 herzien) +
`reconciliatie.md` (patroon "vaststaande actie = systeem doet het"), BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING
ZONDER HANDELING SWEEP (Peter 19-09)", CLAUDE.md één verwijsregel, WAT_IS_NIEUW ("Kassarapporten die als inkoopfactuur binnenkomen
worden nu automatisch herkend en omgezet"). Rapport + INDEX + Gelezen regels; nameting ná deploy: Van Boxtel Journaal 1-9/2-9/3-9 →
omzet-controlescherm, bevindingen weg — "werkt in productie: ja/nee". Één regel voor Peter: hoeveel meldingen verdwijnen, en de
sweep-tabel mét mijn voorstel per soort.
