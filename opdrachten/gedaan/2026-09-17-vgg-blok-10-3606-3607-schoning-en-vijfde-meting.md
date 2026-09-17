> uitgevoerd 2026-09-17 (modelfix één regel, één bestemming + overlap-guard + kolom RJ-220-tegenzijde; 24 regels lees-only herleid (kruisposten 1011 / spaar 1002, meetbeperking Cloud Logging); vijfde meting ná deploy → vervolg-opdracht vgg-vijfde-meting; werkt in productie: nee), rapport: docs/rapporten/2026-09-17-vgg-blok-10-een-regel-een-bestemming.md

# OPDRACHT 17-09 — VGG → Odoo, run 2 blok 10: 1001-model en RJ-220-herclassificatie claimen dezelfde regel (3606/3607) — modelfix in de replay + vijfde meting (géén writes)

**Aanleiding (vierde meting 16-09 22:45, `docs/rapporten/2026-09-16-vgg-vierde-meting.md`):** ROOD 6 i.p.v. 4. De twee nieuwe
verschillen (3606 −363.300,00; 3607 −20.000,00 per 16-09) vallen exact samen met de herclassificatierijen `ongemapt:1001 → 3606`
(13 documenten) en `ongemapt:1001 → 3607` (1). Sinds blok 9 gaat de 1001-zijde van die 14 aanbetalings-memorialen via het
1001-model naar outstanding BNK1 (132); de RJ-220-herclassificatie rekent diezelfde regel nog als 1001 → rol-rekening. Eén regel,
twee bestemmingen = dubbel in het doelmodel.

**Diagnose Cowork (te bevestigen):** de herclassificatie zat op de VERKEERDE zijde van het memoriaal. Een aanbetaling die als
memoriaal op 1001 staat heeft twee regels: de bankzijde (1001 — dat is de betaling, en die hoort via het 1001-model op
outstanding tegenover de statement line) en de tegenzijde (de aanbetaling zelf, RLZ vermoedelijk 7000/1300/aanbetalingsrekening —
dát is de RJ-220-rol `vooruitbetaald_op_voorraad` 3606 resp. 3607). De herclassificatie moet dus de tegenregel van het memoriaal
naar 3606/3607 sturen, nooit de 1001-regel. Klopt dat, dan verdwijnen beide nieuwe verschillen én blijft het 1001-model intact.

Pre-feature-ritueel: BESLISSINGEN "… RUN 2 BLOK 9 …" (Blok C vierde meting), "… BLOK 8" (rekening_mapping), "RJ-220-ROLLEN OP ODOO
COMPANY 6", `app/migratie/model_1001.py`, `app/migratie/rekening_mapping.py`, `app/odoo/rj220.py`, `vgg-replay`. Harde grenzen
ongewijzigd: lees-only, company-pin 6, geen Odoo-/RLZ-writes, memoriaalregels uit Debit/CreditAmount.

## Blok A — Modelfix
- Herclassificatie-regel per aanbetalings-memoriaal: bron-regel = de NIET-bankzijde (rekening ≠ 1001/bankgrootboek); de 1001-zijde
  blijft exclusief van het 1001-model. Een regel krijgt in de replay precies één bestemming (assert + test: "één regel, één
  bestemming"; overlap = ROOD-bepalend mét de regel erbij, nooit stil).
- Rapport: de 14 documenten expliciet in de 1001-tabel gemarkeerd (kolom "RJ-220-tegenzijde → 3606/3607"), zodat de koppeling
  zichtbaar is; herclassificatietabel toont bron-rekening van de tegenzijde i.p.v. "ongemapt:1001".
- Blijkt de tegenzijde géén eenduidige rekening te hebben (bv. rechtstreeks 7000 aankoop): rapporteren per document, niet raden;
  dan is het een beslispunt Peter (aanbetaling = 3606 of direct kostprijs).

## Blok B — 24 regels zonder bankmutatie
- Per regel (o.a. RLZ-06-00000068 € 75.000 17-11-2025, RLZ-06-00000222 € 100.000 29-06-2026, RLZ-06-00000099/102, RLZ-28-00000013…17)
  lees-only nagaan wat het is: notaris-afrekening zonder bankregel in RLZ (bank nog niet geïmporteerd?), interne overboeking,
  of RLZ-opruimpunt. Tabel mét hypothese per regel + wat Peter in RLZ moet controleren. Geen doorrekenen.

## Blok C — Vijfde meting (productie, lees-only, ná deploy)
- `scripts/gcp/vgg_blok7_nameting.sh c` → `verkenning/nameting-vgg-replay-<dd>-09-cc.txt`; verwachting: ROOD alleen nog op
  debiteuren/crediteuren (afletterstand SCHRIJF c), 3606/3607 0,00, tussenrekening/bank mét benoemde rest; anders rapport, niet
  doorrekenen. Rijtellingen tegen de JSON (print_gedoseerd).

## Afronding
Tests op de één-bestemming-regel + herclassificatie op tegenzijde; BESLISSINGEN "… RUN 2 BLOK 10: ÉÉN REGEL, ÉÉN BESTEMMING (3606/3607)";
CLAUDE.md één verwijsregel; rapport + INDEX mét "werkt in productie: ja/nee"; checklist Peter vóór SCHRIJF c herhalen (outstanding
BNK1 staat nu — id 132 gevonden; IBAN BNK1; drie RLZ-opruimpunten; uitkomst blok B).
