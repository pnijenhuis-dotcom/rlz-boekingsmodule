uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-duplicaat-zenvoices.md

# OPDRACHT 16-09 — Waarom miste de module de Zenvoices-boeking (Hello Kitchen, Kempen Facilities) + dubbele betaling signaleren + "bewust verwijderd in RLZ" als acceptatie (Peter 16-09)

**Aanleiding (Peter 16-09):** reconciliatie 16-09 meldt drie "RLZ-document verdwenen" bij Kempen Facilities. Peter: "de 2
Hello Kitchen facturen (€ 12.600,00 en € 16.250,00, referentie begint met '2 4594 0…') heb ik zelf bewust verwijderd. Die
waren eerst via Zenvoices geboekt en later nogmaals via ons, die zijn dubbel gegaan en helaas ook dubbel betaald (dus moet ik
nu achteraan). TEST-ONB-exemplaar van ABC Hekwerk heb ik ook verwijderd (hoort daar niet)."

Dit is géén verdwenen-document-probleem maar een gemiste duplicaatcheck: de RLZ-bestaanscheck (BESLISSINGEN "HERSTELRUN 'BASIS
EERST' 08-09 — BLOK 4": al geboekt in RLZ = `afgevoerd_duplicaat` mét boekstuknummer) hoorde de Zenvoices-boeking te zien.
Pre-feature-ritueel: lees die sectie, "DUPLICATEN HOOFDMODEL", "HERSTELRUN 07-09 — BLOK A" (RLZ-duplicaatcheck cent-exact
client-side), "RECONCILIATIE RLZ_DUBBEL — CLUSTERS EN REFERENTIE-CLASSIFICATIE", "A11 — DOCUMENTEN-RECONCILIATIE",
"MATCHMOTOR BANK — NAAM/IBAN + NUMMER + BEDRAG + TEKEN".

**Oorzaak al bevestigd door Peter (16-09 08:30):** het factuurnummer. Zenvoices boekte "2220300505", wij "222 0300 505" (spaties
uit de factuur-opmaak overgenomen). De bestaanscheck vergeleek dus ongenormaliseerd en zag geen match. Blok A is daarmee
grotendeels verificatie: bewijs het op deze twee documenten (welke referentie stond in RLZ, welke in ons boekvoorstel, welke
vergelijking deed de check) en toets meteen of `rlz_dubbel`'s normalisatie (die spaties wél strips) en de bestaanscheck twee
verschillende normalisaties gebruiken — dat is dan de code-wortel. Extractie-kant: de AI-extractie mag het nummer letterlijk
overnemen, maar ons opgeslagen `referentie`-veld hoort ALTIJD ook een genormaliseerde vorm te dragen (`referentie_norm`: alle
whitespace/koppeltekens/punten weg, leidende nullen behouden voor weergave maar niet voor vergelijking) — één functie, gebruikt
door duplicaat-check, bestaanscheck, rlz_dubbel, bank-matchmotor (nummer-token) en de IC-match uit de opdracht van vandaag.
Bestaande documenten: backfill-CLI voor `referentie_norm` (dry-run default) + herdraai van de bestaanscheck over geboekte
documenten van de laatste 400 dagen als lees-only rapport "mogelijk eerder dubbel geboekt" (per administratie, aantallen +
boekstuknummers) — Peter wil weten of dit vaker gebeurd is.

## Blok A — Wortelanalyse (lees-only, eerst)
1. Haal uit de eigen DB de twee documenten (document-id's in de reconciliatiebevindingen `e7845955-…` en `9ea6ca98-…`, Kempen
   Facilities RLZ-admin `7bc1e33a-…`): intake-datum, extractie-uitkomst (referentie, bedrag, crediteur), tijdlijn, welke checks
   liepen (duplicaat module / RLZ-bestaanscheck / rlz_dubbel) en wat ze zagen, boekmoment, boekstuknummer.
2. Lees-only in RLZ (`rlz-lezen`, geanonimiseerd, ≤ 50): PurchaseInvoices van dezelfde crediteur in het venster ± 60 dagen rond
   de factuurdatum, incl. concepten — welk exemplaar kwam van Zenvoices (Reference-vorm, Description, aanmaakdatum, Entity-id)
   en waarom heeft onze bestaanscheck 'm niet gematcht? Kandidaten: (a) Zenvoices schreef een andere referentie-vorm
   ("2 4594 0…" met spaties vs ons genormaliseerd), (b) ander crediteurrecord (dubbele crediteur — check `crediteuren/voorkeur`),
   (c) Zenvoices boekte NÁ ons (dan is niet wij maar Zenvoices de dubbelaar en hoort `rlz_dubbel` het te zien — check waarom die
   het paar niet meldde: placeholder-classificatie? venster? concept-status?), (d) bestaanscheck liep vóór de Zenvoices-import
   en er is geen tweede toets bij boeken. Benoem de échte oorzaak mét bewijs, geen hypotheseregen.
3. Bank: zoek de twee betalingen (PaymentTransactions Kempen Facilities, bedrag 12.600,00 / 16.250,00, tegenpartij Hello Kitchen)
   — zijn beide afgeletterd, en tegen welk exemplaar? Dat bepaalt Peters terugvorderingsdossier: noteer boekstuknummers,
   betaaldata, IBAN-tegenpartij (geanonimiseerd in het rapport, volledig in een lokaal niet-gecommit bestand
   `verkenning/prive/hello-kitchen-dubbel-16-09.txt` — map staat in .gitignore, anders toevoegen).

## Blok B — Fix op de gevonden oorzaak
- Wat de wortel ook is: de duplicaat-poort krijgt een TWEEDE toets op het boekmoment (vlak vóór de PUT): bestaat er in RLZ/Odoo al
  een document van dezelfde crediteur-identiteit (alle crediteurrecords van dezelfde KvK/btw) met dezelfde genormaliseerde
  referentie (spaties/koppeltekens/leidende nullen weg — zelfde normalisatie als `rlz_dubbel`) óf cent-exact hetzelfde
  totaal binnen ± 30 dagen → BLOKKEREND "al geboekt in Reeleezee: RLZ-xx-… (bron: extern/handmatig)" mét knop "Afvoeren als
  duplicaat" — nooit stil doorboeken. Zelfde toets in het autoboek-pad (harde check). Concepten tellen mee (een Zenvoices-
  concept wordt straks geboekt).
- Als de oorzaak (a) referentie-normalisatie is: normalisatie in één bron (`rlz_dubbel`/duplicaten-check gebruiken nu mogelijk
  twee varianten — samenvoegen, test met "2 4594 0123" ↔ "245940123").
- Als (b) dubbele crediteur: bestaanscheck over alle records van de identiteit (`crediteuren/voorkeur` kent ze al).

## Blok C — Dubbele betaling signaleren (bank)
- Nieuwe niet-blokkerende bevinding in het bank-blok van de reconciliatie én als oranje signaal op de bankmutatie:
  `dubbele_betaling_vermoed` — twee uitgaande mutaties aan dezelfde tegenpartij-IBAN, cent-exact hetzelfde bedrag, binnen
  60 dagen, terwijl er bij de crediteur maar één (of twee identieke) factuur van dat bedrag staat. Tekst: "Aan Hello Kitchen
  Duiven is € 12.600,00 twee keer betaald (12-08 en 03-09) voor wat één factuur lijkt — controleer of terugvordering nodig
  is." Periodieke gelijke bedragen (huur, abonnement) uitsluiten via `terugkerend/service.py::classificeer_reeks` (periodiek =
  geen signaal). Geen automatische actie.

## Blok D — Acceptatie "bewust verwijderd in RLZ"
- Op de bevinding `ontbreekt_in_rlz` een vaste acceptatiereden-keuze "Bewust verwijderd in Reeleezee (dubbel/test)" naast het
  vrije veld — één klik, audit ongewijzigd, én de module zet ons document op `afgevoerd_duplicaat` mét reden "in RLZ verwijderd
  door <naam> als dubbel" zodat het niet in Archief als 'geboekt' blijft staan met een dood boekstuknummer (tijdlijnregel +
  audit; terugdraaibaar). Herboeken-knop blijft voor het andere geval.
- Voer dit NIET automatisch uit voor de drie huidige bevindingen — Peter klikt ze zelf weg (één klik elk) zodra dit live is;
  noem ze in het rapport.

## Tests / af
- Gouden-set-casus: nieuwe fixture "aa_zenvoices_dubbel" (geanonimiseerd, UBL of pdf_tekst) waarin RLZ al een extern exemplaar
  heeft (stub-RLZ met concept + geboekt, andere referentie-vorm) → afgevoerd/blokkerend; keten-guard raakt app/documenten → tests/
  keten aanpassen. Bank-signaaltests (2× zelfde bedrag wel/niet periodiek). Acceptatiereden-test (status + audit).
- BESLISSINGEN nieuwe sectie "DUPLICAAT-POORT OP HET BOEKMOMENT + DUBBELE BETALING + BEWUST VERWIJDERD (Peter 16-09)", CLAUDE.md
  verwijsregel, WAT_IS_NIEUW, rapport `docs/rapporten/2026-09-16-duplicaat-zenvoices.md` + INDEX mét de wortelanalyse in twee
  zinnen bovenaan en het terugvorderingsdossier (geanonimiseerd) voor Peter. Werkt in productie: niet gemeten + meetrecept
  (bevinding `dubbele_betaling_vermoed` moet bij Kempen Facilities de twee Hello Kitchen-betalingen tonen).
