# Rapport 16-09 — Omzetbronnen zonnestudio + pilates: besluiten Peter verwerkt (tegenzijde, stores, btw, combi, Stripe)

Opdracht: `opdrachten/gedaan/2026-09-16-omzetbronnen-besluiten-peter.md` (binnengekomen tijdens de run, ná de drie genoemde).
Canoniek: BESLISSINGEN "OMZETBRONNEN — BESLUITEN PETER 16-09 (tegenzijde, stores, btw, combi, Stripe)" + subkop "BESLUITEN PETER
16-09" in beide 15-09-secties. Geen migratie (alles in `omzet_instelling.bron_instellingen`). **Werkt in productie: NIET
GEMETEN** (geen deploy binnen de run; meetrecept onderaan). Geen writes naar RLZ/Odoo.

## Wat er staat

- **Punten = omzet (besluit Peter 16-09):** categorie Points is gewone omzet zonnebank 21 % op de dag van verkoop; "Points Redeemed"
  wordt genegeerd; de blokkerende check "Puntenwaarde bekend" is vervallen; kascheck en categorie-sluitcontroles blijven.
- **Tegenzijde per betaalwijze (blok A):** instelling `tegenrekeningen` (pin/cash/stripe/kasverschil/storting) mét defaults op
  NAAM uit het rekeningschema (kruispost/pin/kas/kasverschil/stripe/psp; meerduidig = mens kiest). Per document staat in het
  Bron-blok per betaalwijze bedrag, datum, tegenrekening en herkomst; ontbreekt een tegenrekening dan blokkeert de check "Bron:
  Tegenrekening ‹betaalwijze›" mét de plek om 'm in te stellen. **RLZ-vorm = AFLETTERING (default gekozen):** de Receipt blijft het
  enige omzetdocument (open post), PIN-/Stripe-ontvangst wordt via het bewezen actie-15-pad afgeletterd, de storting kas → bank
  boekt direct op kas. Een memoriaal-tussenrekening is bewust niet gebouwd (credit-kant van een entity-loze Receipt is niet
  geverifieerd) — het cash-deel blijft in RLZ op de Receipt open tot de kas-vorm gekozen is (beslispunt 4).
- **Bank-matchmotor stap "omzetbatch-post":** een bijschrijving die cent-exact bij een geboekte omzetbatch past (Stripe +1…+7 dagen
  ná de uitbetaaldatum en nooit ervoor; storting ± 3 d; PIN 0…+5 d) + omschrijvingskern → groen ("omzetbatch 2026-7-9 · Stripe"),
  zonder kern oranje; automatisch afletteren/boeken via de bestaande opt-ins en de AI-toets als poort.
- **Reconciliatie `tussenrekening_open`:** omzetontvangst ná 14 dagen niet op de bank = bevinding mét handeling; tekst in mensentaal
  ("Omzetontvangst nog niet op de bank"), actiemail-guard uitgebreid.
- **Pilates btw + combi (blok C):** lessen/yoga laag, kleding & producten hoog, eten/drinken laag (instelbaar), altijd het RLZ-tarief
  van de administratie; mens-override per categorie geldt vanaf de volgende batch; combi-abonnement pro rato Pilates/Yoga (batch →
  30 dagen → 50/50 oranje), cent-exact, verdeling zichtbaar.
- **Stripe (blok D):** PSP-kosten = EU-dienst verlegd ("Stripe · EU-dienst verlegd"), kostenrekening op naam; Mollie = 21 %
  voorbelasting; disputes negatief + fee als kosten.
- **Beheerder-UI (blok B):** blok "Omzetbronnen" op Instellingen › Administraties › ‹administratie› › Boeken & AI (stores,
  tegenrekening per betaalwijze, btw per categorie + productmapping, combi-regel, PSP/kostenrekening/eten-drinken; één "Opslaan" + ⋯),
  registry-anker, overflow-sweep groen; Bron-blok toont tegenzijde + combi-verdeling. Sunshine Island wordt NIET in code gezet —
  Peter/Cowork voegt de store ná deploy toe (default zelfde administratie als Elderveld).

## Tests

Backend blok X: gerichte suites 927 groen (omzet, bank, keten ab/ac/l/y, teksten, actiemail-guard, rol-matrix, keten-guard);
frontend Y: tsc groen, OmzetBronnenBlok (4) + OmzetReviewScreen (+1) + registry (+1), overflow-sweep 8/8; coördinator: tekst-tak
`tussenrekening_open` geplakt + guard-fixture + test, bank `voorstel.soort` +'omzetbatch_post', frontend bank/omzet/instellingen
93 groen. Volledige suite: zie het slotrapport.

## Beslispunten (default gekozen, zie `2026-09-16-beslispunten-peter.md`)

1. Sunshine Island eigen BV? Default zelfde administratie. 2. Eten/drinken 9 %. 3. Rittenkaart = omzet bij verkoop. 4. Tegenzijde
in RLZ = aflettering (cash-deel blijft open op de Receipt) vs memoriaal-tussenrekening ná STAP-0. 5. Stripe-kosten als negatieve
Receipt-regel landen in rubriek 1e, niet 4b/5b — rubriek-correct = maandelijkse inkoopfactuur op crediteur Stripe. 6. PIN-venster
en -kernen zijn aannames tot de eerste echte PIN-afrekening. 7. Blok op tab Boeken & AI, geen eigen tab Omzet.

## Meetrecept ná deploy

1. Eerste dagstaat Elderveld én Sunshine Island (store via het blok toegevoegd) → voorstel toont per betaalwijze de tegenrekening,
   punten als omzet 21 %, geen puntenblokkade; eerste Stripe-payout +1…+7 d → bankvoorstel "omzetbatch … · Stripe" groen.
2. `scripts/gcp/nameting.sh reconciliatie-alles --alleen omzet --lees-only` ná 14 dagen zonder match → `tussenrekening_open`.
3. Instellingen › Administraties › zonnestudio › Boeken & AI › Omzetbronnen: defaults-chips gevuld op naam; opslaan → GET toont de keuze.
