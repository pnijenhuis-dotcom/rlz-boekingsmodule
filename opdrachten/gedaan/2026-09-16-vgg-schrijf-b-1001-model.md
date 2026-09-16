> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-vgg-schrijf-b.md

# OPDRACHT 16-09 (avond) — Vastgoedgroep Nederland → Odoo, run 2 blok 9: SCHRIJF b = het 1001-model in de replay + vierde meting (géén Odoo-writes)

**Aanleiding:** derde meting 15-09 (`2026-09-15-vgg-schrijf-a-vervolg.md`) is ROOD uitsluitend op de vier afletter-groepen
(crediteuren Δ −5,88 mln / −11,16 mln, debiteuren Δ 4,64 / 8,81 mln, tussenrekening Δ −214.916,85 / −713.449,59, bank Δ 61.166,85 /
216.201,20); buiten die groepen 0,00. Open modelpunt sinds 7d (14-09): memoriaal-1001-regels die tegen een statement line
reconciliëren horen op de outstanding-/suspense-rekening van het bankdagboek, anders telt 1001 dubbel (−85.376,31 / +71.343,31).
Dit is de laatste modelstap vóór SCHRIJF c; SCHRIJF c zelf wacht op Peters RLZ-opruimpunten (RLZ-01-00000006 concept, dubbel
135.000 RLZ-28-00000061/062, bankregel "test") en op de klikpunten outstanding-payments-rekening + IBAN op BNK1.

Pre-feature-ritueel: BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 7d …" (open modelpunt SCHRIJF b), "… BLOK 8: SCHRIJF a
+ DERDE METING", `app/migratie/rekening_mapping.py` (1001 als SCHRIJF-b-markering), `app/migratie/odoo_doel.py`, `vgg-replay`,
odoo-verkenning §11–12 (statement lines, reconciliatiemodellen zonder `rule_type` in 19), `scripts/gcp/vgg_blok7_nameting.sh`.
Harde grenzen: company-pin 6 + kill-switch, geen Odoo-writes in deze run (ook geen concepten), RLZ lees-only via de token-bucket,
webfilter = meting ongeldig, memoriaalregels alleen uit Debit/CreditAmount.

## Blok A — 1001-model (lees-only, in de replay)
- Per memoriaal-1001-regel bepalen of hij één-op-één tegen een RLZ-bankmutatie staat (cent-exact bedrag, ± 3 dagen, zelfde teken-
  richting; `PaymentReferenceList`/koppelingen als eerste bewijs, bedrag+datum als tweede) → in het Odoo-doelmodel landt die regel
  op de outstanding-/suspense-rekening van BNK1 (lees-only geresolved zoals 1012: payment-method-line → company-default → KLIKPUNT),
  en de statement line reconcilieert ertegen; 1001-regels ZONDER bankmutatie blijven op de tussenrekening mét reden
  ("geen bankmutatie binnen ± 3 d") in het rapport. Meerduidig (twee kandidaten) = niet toewijzen, aparte teller.
- Rapport per 1001-regel: boekstuk, bedrag, gekozen bestemming, bewijs. Balansguard blijft ROOD-bepalend.
- Resultaat in de groepstoets: de tussenrekening- en bankgroep horen ná dit model op 0,00 te sluiten VOOR ZOVER de verschillen door
  1001 werden veroorzaakt; wat overblijft krijgt een expliciete restcategorie (afletterstand debiteuren/crediteuren = SCHRIJF c,
  betalingsverschil, RLZ-opruimpunt) — nooit "onverklaard" zonder regel.

## Blok B — Bewijspaar buiten juli 2025
- Kies lees-only één factuur↔betaling-paar buiten juli 2025 (bij voorkeur 2026, mét pand) en leg de verwachte Odoo-vorm vast in het
  rapport (partner, rekeningen, RJ-220-rol, statement line, reconciliatie) — het recept voor SCHRIJF c, nog niet uitgevoerd.

## Blok C — Vierde meting (productie, lees-only)
- `scripts/gcp/vgg_blok7_nameting.sh` → `vgg-replay` op de gedeployde job-image ná de deploy van deze commit; rapport gedoseerd
  (`print_gedoseerd`, meetrecept uit 15-09: regels tellen tegen de JSON — dit is ook de eerste echte meting van die fix).
- Oordeel in drie standen; verwachting: ROOD alleen nog op debiteuren/crediteuren (afletterstand, SCHRIJF c), tussenrekening + bank
  0,00 of mét benoemde rest. Wijkt het af: rapport, geen doorrekenen.
- Bewaar als `verkenning/nameting-vgg-replay-<dd>-09.txt` — LET OP: de nameting-bot schrijft dezelfde bestandsnamen per datum (rebase-
  conflict 16-09 ochtend); gebruik suffix `-cc` voor CC-uitvoer.

## Afronding
- Geen migratie verwacht; tests op het 1001-model (matching, meerduidig, geen kandidaat, tekenrichting) + gouden-set-guard.
- BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 9: SCHRIJF b — 1001-MODEL + VIERDE METING", CLAUDE.md één verwijsregel,
  odoo-verkenning §12.x, api-verkenning als er een nieuw RLZ-feit is.
- Rapport `docs/rapporten/2026-09-1x-vgg-schrijf-b.md` + INDEX, "werkt in productie: ja/nee/niet gemeten", plus de resterende
  klikpunten voor Peter (outstanding-rekening BNK1, IBAN BNK1, drie RLZ-opruimpunten) als checklist vóór SCHRIJF c.
- Nazorg uit de vorige run: `docs/rapporten/2026-09-16-verplichting-projectveld.md` bevat nog de letterlijke tekst
  `SWEEPS_PLACEHOLDER` — invullen met de echte sweep-uitkomst (of "niet gedraaid, reden") in deze docs-commit.
