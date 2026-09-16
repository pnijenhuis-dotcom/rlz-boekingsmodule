uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-omzetbronnen-besluiten.md

# OPDRACHT 16-09 — Omzetbronnen zonnestudio + pilates: besluiten Peter verwerken (tegenzijde, stores, btw, combi, Stripe)

**Antwoorden Peter 16-09 (letterlijk):** "alleen de omzet boeken, dagstaten worden afgeboekt op bankontvangsten. 2e studio heet
Sunshine Island" en "Pilates 9% is sport en 21% zijn de producten (kleding etc). Combi verdelen pro rato. Betaalprovider is
Stripe." Dit sluit de beslispunten uit `docs/rapporten/2026-09-15-beslispunten-peter.md` (zonnestudio 2 en 3, pilates 1, 2 en 4)
en de twee "bewust niet gebouwd"-onderdelen uit `2026-09-15-omzet-zonnestudio.md` / `-omzet-pilates.md` (tegenzijde per
betaalwijze, Beheerder-UI bron-instellingen). Niet beantwoord: puntenwaarde zonnestudio (blokkerende check blijft) en
rittenkaart vooruitontvangen-vs-omzet (default omzet bij verkoop blijft).

Pre-feature-ritueel: BESLISSINGEN "OMZETBRON ZONNESTUDIO DAGSTAAT (Peter 15-09)", "OMZETBRON PILATES BETALINGSEXPORT (Peter
15-09)", "Omzetmodule — GEBOUWD + GETEST" (entity-loze Receipts), "MATCHMOTOR BANK — …" (open-post-match), api-verkenning
"Receipts-verkenning" (welke tegenrekening een Receipt draagt — kas/bank/tussenrekening).

**Aanvulling Peter 16-09 (2):** "Stripe-betalingen lopen altijd achter t.o.v. de omzet: omzet van 09-10 wordt gestort op
10-10." en "zonnestudio alleen de omzet boeken, points hoef je niks mee te doen."
- Stripe-match: bankdatum ≥ batch-/omzetdatum, venster +1 … +7 dagen (weekend/feestdag), nooit vóór de omzetdatum; batch mét
  uitbetalingsdatum in de export gebruikt die datum als anker. Vervangt "± 3 d" in blok A.
- Punten (BESLUIT Peter 16-09 op voorstel Cowork — "klopt, heb jij gelijk in"; geen beslispunt meer, capture in BESLISSINGEN): "niks doen" kan niet
  letterlijk, want de € 250,00 puntenverkoop zit in Grand Total én in de cash/PIN-ontvangst (1.019,03) — zonder tegenpost sluit
  de bankmatch nooit. Een zonnebankpunt is een single-purpose voucher (één dienst, één btw-tarief) → btw en omzet zijn
  verschuldigd bij VERKOOP. Dus: categorie Points = omzet zonnebank 21 % (bedrag incl. btw, deterministisch gesplitst) op de
  dag van verkoop; "Points Redeemed" wordt genegeerd (geen boeking, geen vooruitontvangen-post, geen check). De blokkerende
  check "Puntenwaarde bekend" VERVALT; kascheck en categorie-sluitcontroles blijven. Voegt het rapport 15-09 uitdrukkelijk
  als herzien toe.

## Blok A — Tegenzijde: "alleen omzet boeken, bank lettert af"
Interpretatie (default, noteren als beslispunt met default): de Receipt boekt omzet per categorie + btw tegen een
TUSSENREKENING per betaalwijze; de echte bankontvangst wordt daarna door de bank-matchmotor tegen die tussenrekening
afgeletterd/geboekt. Per administratie instelbaar (Beheerder, blok B), defaults afgeleid uit het RLZ-rekeningschema op
naam ("kruispost", "PIN onderweg", "te ontvangen", "kas") — nooit hardgecodeerde nummers.
- Zonnestudio: PIN → tussenrekening "PIN/kruispost"; Cash → kas (het kasboek is de kascheck: beginsaldo, contante omzet,
  storting automaat, eindsaldo); "storting automaat" = kas → bank (bank-matchmotor: bankontvangst met omschrijving
  sealbag/storting + bedrag = kas-tegenrekening). Punten verkocht → vooruitontvangen (balans), punten ingewisseld →
  vooruitontvangen → omzet. Kasverschil → rekening "kasverschillen" (oranje signaal blijft).
- Pilates: netto uitbetaling per batch → tussenrekening "Stripe/PSP onderweg"; bank-matchmotor matcht de Stripe-payout
  (omschrijving "STRIPE" + cent-exact netto + datum ± 3 d) → groen automatisch kandidaat. Contant-batch → kas.
- Bank-matchmotor: nieuwe stap "tussenrekening-post" naast open posten: een Receipt-tegenzijde op een tussenrekening is een
  matchbare post (bedrag cent-exact, datum-venster, omschrijvingskern STRIPE/SEPA-storting); label `bron` zegt "omzetbatch
  2026-7-9 · Stripe". Reconciliatie: tussenrekening-saldo ouder dan 14 dagen zonder bankmatch = bevinding mét handeling.

## Blok B — Beheerder-UI bron-instellingen (was open) + data
- Blok "Omzetbronnen" op Instellingen › Administraties › ‹administratie› › Omzet: stores (naam in "Store Used" → deze
  administratie), tegenrekeningen per betaalwijze (combobox op het rekeningschema, defaults voorgevuld), categorie-mapping
  pilates (productnaam → categorie → omzetrekening + btw), combi-verdeelregel. Registry-entry, overflow-sweep, één primaire
  knop + ⋯. Route bestaat (`GET/PUT …/omzet/bron-instellingen`) — uitbreiden.
- Data ná deploy via de bestaande route/CLI (geen job-stap met hardgecodeerde namen in code): stores "Elderveld" én
  "Sunshine Island" → de zonnestudio-administratie(s). Als Sunshine Island een EIGEN administratie/BV is: in het rapport
  melden mét de vraag; default = zelfde administratie als Elderveld tot Peter anders zegt.

## Blok C — Pilates btw en combi
- Categorie-defaults: Pilateslessen, Yoga, rittenkaarten/abonnementen lessen → **9 %** (sportbeoefening — het tarief volgt
  het RLZ-tarief van de administratie, nooit een hardgecodeerd percentage); Omzet kleding & producten → **21 %**; Omzet
  eten/drinken → 9 % (default, beslispunt: alcohol/horeca-uitzonderingen 21 %). Mens kan per categorie overrulen; wijziging
  geldt vanaf de volgende batch, nooit met terugwerkende kracht op geboekte batches.
- "combi Abonnement" → pro rato over Pilates en Yoga naar de netto-omzet van diezelfde categorieën in DEZELFDE
  uitbetalingsbatch; geen basis in de batch → laatste 30 dagen van de administratie; nog geen basis → 50/50 mét oranje
  signaal (deterministisch, cent-exact sluitend, restcent op de grootste). Verdeling zichtbaar in blok "Bron".
- Rittenkaart/abonnement blijft omzet bij verkoop (default; beslispunt herhalen — fiscaal is dit btw-correct, commercieel
  is vooruitontvangen zuiverder; alleen relevant bij jaarafsluiting).

## Blok D — Stripe
- PSP = Stripe (Stripe Payments Europe Ltd, Ierland): kosten = EU-dienst, **btw verlegd** (rubriek 4b, verlegd-tarief via het
  bestaande `bepaal_verlegd_taxrate`-pad, herkomst-chip "Stripe · EU-dienst verlegd"), kostenrekening default "Transactiekosten
  PSP"/"Bankkosten" uit het schema op naam. Disputes/chargebacks: negatieve omzetregel in dezelfde categorie (bestaand) +
  Stripe-dispute-fee als kosten. Instelbaar per administratie (PSP-keuze: Stripe/Mollie/anders → Mollie = NL 21 % voorbelasting).

## Tests / af
- Gouden-set-casussen ab/ac uitbreiden (tegenzijde-regels, combi-verdeling cent-exact, Stripe verlegd, tweede store), bank-
  matchmotor-test tussenrekening-post (payout groen, storting kas→bank), reconciliatie-bevinding tussenrekening > 14 d.
- Migratie alleen als de instellingen-JSON niet volstaat (voorkeur: uitbreiden `omzet_instelling.bron_instellingen`).
- BESLISSINGEN: aanvulling op beide 15-09-secties ("BESLUITEN PETER 16-09" subkop), CLAUDE.md-verwijsregel bijwerken,
  WAT_IS_NIEUW, rapport `docs/rapporten/2026-09-16-omzetbronnen-besluiten.md` + INDEX mét meetrecept (eerste echte dagstaat
  Elderveld + Sunshine Island ná deploy; eerste Stripe-payout groen gematcht). Werkt in productie: niet gemeten.
- Beslispunten (default kiezen, noteren): Sunshine Island eigen administratie?; eten/drinken 9 % default; puntenwaarde
  blijft open (blokkerend); rittenkaart omzet-bij-verkoop.
