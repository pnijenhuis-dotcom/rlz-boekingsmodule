# Rapport 17-09 (middag, inbox-run) — Doorbelasting-aansluiting Kempen Facilities: productienameting via de nameting-workflow (lees-only)

Opdracht: `opdrachten/gedaan/2026-09-17-doorbelasting-aansluiting-nameting-2.md` (vervolg op `2026-09-17-doorbelasting-aansluiting-nameting.md`).
Geen writes. **Werkt in productie: ja** — de herkoppeling koppelde Kempen Chalets zelf (Cloud Logging `rlz-sync` 17-09 05:04:10 UTC:
`GEKOPPELD 'Kempen Chalets B.V.' → 'Kempen Chalets B.V.' (3206a747-…)`, `open=1 gekoppeld=1 bijna_match=0 meerdere=0 geen=0`) en het
aansluitingsblok draaide op de job-image (CLI exit 1 = afwijkingen gevonden = uitkomst; geen webfilter/exit 3).

## Stap 0 / 1
- Deploy `fb54c58` (06:19 UTC): stappen 8+9 groen, alleen stap 10 (OTA-bundel, bucket-404) rood → voorwaarde voldaan; `gh auth status` groen.
- `gh workflow run nameting -f onderdeel=doorbelasting-aansluiting` → run 35212801971 (success) → nameting-bot commit `08685c6`
  `verkenning/nameting-doorbelasting-aansluiting-17-09.txt` (1.189 regels; bron Kempen Facilities `66e1e296…`, venster 2026-01-01 t/m 2026-09-17,
  whitelist-rijen 8 (8 mét doel in de module), verkoopfacturen gelezen 992).

## Overzicht per doelentiteit (letterlijk uit het bot-bestand)
| Doelentiteit | Doel in module | Basis crediteur | Verkoop | Inkoop | Sluit | Ontbreekt in doel | Bedrag afwijkt | Status verschilt | Inkoop zonder verkoop | Onderweg | Stand |
|---|---|---|---|---|---|---|---|---|---|---|---|
| Kempen Chalets B.V. | ja — Kempen Chalets B.V. | naam (1) | 50 (€ 6.911,35) | 50 | 50 | 0 | 0 | 0 | 0 | 0 | OK |
| Mantelzorgwoning Midden Nederland B.V. | ja — Mantelzorgwoningen Midden Nederland | ic_relatie (1) | 31 (€ 59.951,03) | 38 | 31 | 0 | 0 | 0 | 7 | 0 | AFWIJKING |
| Molenhof Beheer B.V. | ja — Molenhof Beheer B.V. | ic_relatie (1) | 56 (€ 1.015.518,55) | 11 | 0 | 54 | 0 | 0 | 9 | 0 | AFWIJKING |
| Molenhof Verhuur B.V. | ja — Molenhof Verhuur B.V. | ic_relatie (1) | 185 (€ 1.108.595,72) | 212 | 184 | 1 | 0 | 0 | 28 | 0 | AFWIJKING |
| Oirschot Recreatie B.V. | ja — Oirschot Recreatie B.V. | ic_relatie (1) | 208 (€ 190.543,34) | 237 | 205 | 3 | 0 | 0 | 32 | 0 | AFWIJKING |
| Oirschot Vastgoed Beheer B.V. | ja — Oirschot Vastgoed Beheer B.V. | ic_relatie (1) | 13 (€ 227.194,00) | 13 | 13 | 0 | 0 | 0 | 0 | 0 | OK |
| Rubicon Investments B.V. | ja — Rubicon Investments B.V. | naam (1) | 7 (€ 3.112,73) | 9 | 7 | 0 | 0 | 0 | 2 | 0 | AFWIJKING |

**Sluit: 928.** Kempen Chalets (50/50, basis naam) en Oirschot Vastgoed Beheer (13/13) sluiten volledig. Verwachting Peter "alles sluit"
is NIET gehaald: drie structurele categorieën hieronder.

## Ontbreekt in doel (verkoop zónder inkoop) — 59
| Doelentiteit | Nummer | Datum | Bedrag verkoop | Bedrag inkoop | Boekstuk verkoop | Boekstuk inkoop |
|---|---|---|---|---|---|---|
| Molenhof Beheer B.V. | 24712225 | 2026-01-15 | 365.27 | — | 24712225 | — |
| Molenhof Beheer B.V. | 24712221 | 2026-01-15 | 11064.94 | — | 24712221 | — |
| Molenhof Beheer B.V. | 24712308 | 2026-01-22 | 3625.00 | — | 24712308 | — |
| Molenhof Beheer B.V. | 24712372 | 2026-01-22 | 11341.29 | — | 24712372 | — |
| Molenhof Beheer B.V. | 24712332 | 2026-02-05 | 1515.08 | — | 24712332 | — |
| Molenhof Beheer B.V. | 24712334 | 2026-02-05 | 587.61 | — | 24712334 | — |
| Molenhof Beheer B.V. | 24712387 | 2026-02-06 | 14458.29 | — | 24712387 | — |
| Molenhof Beheer B.V. | 24712398 | 2026-02-16 | 946.52 | — | 24712398 | — |
| Molenhof Beheer B.V. | 24712373 | 2026-02-16 | 7521.20 | — | 24712373 | — |
| Molenhof Beheer B.V. | 24712388 | 2026-02-16 | 600.95 | — | 24712388 | — |
| Molenhof Beheer B.V. | 24712479 | 2026-03-03 | 851.78 | — | 24712479 | — |
| Molenhof Beheer B.V. | 24712473 | 2026-03-03 | 14610.75 | — | 24712473 | — |
| Molenhof Beheer B.V. | 24712477 | 2026-03-03 | 5815.82 | — | 24712477 | — |
| Molenhof Beheer B.V. | 24712475 | 2026-03-03 | 181.05 | — | 24712475 | — |
| Molenhof Beheer B.V. | 24712512 | 2026-03-08 | 13975.50 | — | 24712512 | — |
| Molenhof Beheer B.V. | 24712500 | 2026-03-08 | 1320.87 | — | 24712500 | — |
| Molenhof Beheer B.V. | 24712535 | 2026-03-15 | 1.27 | — | 24712535 | — |
| Molenhof Beheer B.V. | 24712544 | 2026-03-20 | 515.82 | — | 24712544 | — |
| Molenhof Beheer B.V. | 24712559 | 2026-03-24 | 5914.14 | — | 24712559 | — |
| Molenhof Beheer B.V. | 24712556 | 2026-03-24 | 158812.50 | — | 24712556 | — |
| Molenhof Beheer B.V. | 24712549 | 2026-03-25 | -1449.01 | — | 24712549 | — |
| Molenhof Beheer B.V. | 24712569 | 2026-03-27 | 12723.04 | — | 24712569 | — |
| Molenhof Beheer B.V. | 24712572 | 2026-03-27 | 492.43 | — | 24712572 | — |
| Molenhof Beheer B.V. | 24712592 | 2026-04-02 | 567.41 | — | 24712592 | — |
| Molenhof Beheer B.V. | 24712644 | 2026-04-20 | 457.38 | — | 24712644 | — |
| Molenhof Beheer B.V. | 24712704 | 2026-04-26 | 3849.62 | — | 24712704 | — |
| Molenhof Beheer B.V. | 24712698 | 2026-04-26 | 7178.33 | — | 24712698 | — |
| Molenhof Beheer B.V. | 24712693 | 2026-04-26 | 1397.55 | — | 24712693 | — |
| Molenhof Beheer B.V. | 24712746 | 2026-05-01 | 1954.67 | — | 24712746 | — |
| Molenhof Beheer B.V. | 24712785 | 2026-05-08 | 3201.66 | — | 24712785 | — |
| Molenhof Beheer B.V. | 24712777 | 2026-05-08 | 7295.21 | — | 24712777 | — |
| Molenhof Beheer B.V. | 24712799 | 2026-05-10 | 567.41 | — | 24712799 | — |
| Molenhof Beheer B.V. | 24712783 | 2026-05-10 | 2348.79 | — | 24712783 | — |
| Molenhof Beheer B.V. | 24712815 | 2026-05-13 | 127050.00 | — | 24712815 | — |
| Molenhof Beheer B.V. | 24712835 | 2026-05-18 | 378.61 | — | 24712835 | — |
| Molenhof Beheer B.V. | 24712912 | 2026-06-05 | 158812.50 | — | 24712912 | — |
| Molenhof Beheer B.V. | 24712931 | 2026-06-10 | 16496.03 | — | 24712931 | — |
| Molenhof Beheer B.V. | 24712932 | 2026-06-10 | 1356.26 | — | 24712932 | — |
| Molenhof Beheer B.V. | 24712926 | 2026-06-10 | 1674.52 | — | 24712926 | — |
| Molenhof Beheer B.V. | 24712916 | 2026-06-10 | 40020.75 | — | 24712916 | — |
| Molenhof Beheer B.V. | 24712930 | 2026-06-10 | 95287.50 | — | 24712930 | — |
| Molenhof Beheer B.V. | 24712957 | 2026-06-17 | 8062.15 | — | 24712957 | — |
| Molenhof Beheer B.V. | 24712973 | 2026-06-17 | 1079.93 | — | 24712973 | — |
| Molenhof Beheer B.V. | 24712993 | 2026-06-26 | 3125.12 | — | 24712993 | — |
| Molenhof Beheer B.V. | 24713024 | 2026-07-10 | 13135.55 | — | 24713024 | — |
| Molenhof Beheer B.V. | 24713022 | 2026-07-10 | 6352.50 | — | 24713022 | — |
| Molenhof Beheer B.V. | 24713070 | 2026-07-10 | 5539.69 | — | 24713070 | — |
| Molenhof Beheer B.V. | 24713017 | 2026-07-10 | 567.41 | — | 24713017 | — |
| Molenhof Beheer B.V. | 24713095 | 2026-07-15 | 9528.75 | — | 24713095 | — |
| Molenhof Beheer B.V. | 24713126 | 2026-07-27 | 15909.47 | — | 24713126 | — |
| Molenhof Beheer B.V. | 24713150 | 2026-07-27 | 20328.00 | — | 24713150 | — |
| Molenhof Beheer B.V. | 24713149 | 2026-07-27 | 15246.00 | — | 24713149 | — |
| Molenhof Beheer B.V. | 24713160 | 2026-07-29 | 2657.12 | — | 24713160 | — |
| Molenhof Beheer B.V. | 24713197 | 2026-08-11 | 158812.50 | — | 24713197 | — |
| Molenhof Verhuur B.V. | ? | 2026-08-28 | 5374.22 | — | — | — |
| Oirschot Recreatie B.V. | 24712615 | 2026-04-02 | 245.21 | — | 24712615 | — |
| Oirschot Recreatie B.V. | 24712648 | 2026-04-20 | 275.28 | — | 24712648 | — |
| Oirschot Recreatie B.V. | 24712802 | 2026-05-11 | 102.73 | — | 24712802 | — |
| Veldhoven Recreatie B.V. | ? | 2026-08-28 | 701.96 | — | — | — |

Duiding: **54 van de 59 bij Molenhof Beheer B.V.** (56 verkoopfacturen KF → Molenhof Beheer, slechts 11 inkoopfacturen in het doel,
0 sluitend) — structureel: de doorbelastingsfacturen van KF aan Molenhof Beheer worden in Molenhof Beheer niet (als inkoop) geboekt, of
op een crediteurrecord dat niet aan de KF-identiteit hangt. Twee rijen zonder nummer ("?", 28-08-2026, Molenhof Verhuur € 5.374,22 en
Veldhoven Recreatie € 701,96) = verkoopfactuur zonder RLZ-nummer (concept/onderweg). Drie Oirschot Recreatie-regels (€ 245,21 / 275,28 /
102,73) = kleine bedragen zonder inkoop.

## Bedrag afwijkt — 2
| Doelentiteit | Nummer | Datum | Bedrag verkoop | Bedrag inkoop | Boekstuk verkoop | Boekstuk inkoop |
|---|---|---|---|---|---|---|
| Veldhoven Recreatie B.V. | 24712873 | 2026-05-28 | 0.00 | 69.82 | 24712873 | RLZ-04-00004183 |
| Veldhoven Recreatie B.V. | 24712869 | 2026-05-28 | 69.82 | 0.00 | 24712869 | RLZ-04-00004181 |

Duiding: Veldhoven Recreatie 24712873/24712869 (28-05-2026): verkoop 0,00 ↔ inkoop 69,82 én verkoop 69,82 ↔ inkoop 0,00 — een
gekruiste match op nummer (nulfactuur náást een factuur van € 69,82); netto sluit het paar. Klikpunt: in RLZ nakijken waarom er een
verkoopfactuur van € 0,00 bestaat (24712873).

## Inkoop in doel zónder verkoop bij de bron — 166 (per doelentiteit: Veldhoven Recreatie B.V. 88, Oirschot Recreatie B.V. 32, Molenhof Verhuur B.V. 28, Molenhof Beheer B.V. 9, Mantelzorgwoning Midden Nederland B.V. 7, Rubicon Investments B.V. 2)
| Doelentiteit | Nummer | Datum | Bedrag verkoop | Bedrag inkoop | Boekstuk verkoop | Boekstuk inkoop |
|---|---|---|---|---|---|---|
| Mantelzorgwoning Midden Nederland B.V. | 24713297 | 2026-08-10 | — | 17062.50 | — | RLZ-04-00000387 |
| Mantelzorgwoning Midden Nederland B.V. | 24713294 | 2026-08-10 | — | 13229.99 | — | RLZ-04-00000384 |
| Mantelzorgwoning Midden Nederland B.V. | 24713295 | 2026-08-10 | — | 12075.00 | — | RLZ-04-00000385 |
| Mantelzorgwoning Midden Nederland B.V. | 24713296 | 2026-08-10 | — | 14175.00 | — | RLZ-04-00000386 |
| Mantelzorgwoning Midden Nederland B.V. | 24713275 | 2026-08-22 | — | 924.92 | — | RLZ-04-00000383 |
| Mantelzorgwoning Midden Nederland B.V. | 24713316 | 2026-08-24 | — | 877.92 | — | RLZ-04-00000388 |
| Mantelzorgwoning Midden Nederland B.V. | 24713335 | 2026-09-02 | — | 1270.50 | — | RLZ-04-00000389 |
| Molenhof Beheer B.V. | 24713272 | 2026-07-06 | — | 962.41 | — | RLZ-04-00001123 |
| Molenhof Beheer B.V. | 24713247 | 2026-07-31 | — | 9221.18 | — | RLZ-04-00001122 |
| Molenhof Beheer B.V. | 24713245 | 2026-07-31 | — | 1799.98 | — | RLZ-04-00001120 |
| Molenhof Beheer B.V. | 24713287 | 2026-08-04 | — | 2537.83 | — | RLZ-04-00001127 |
| Molenhof Beheer B.V. | 24713246 | 2026-08-25 | — | 1628.78 | — | RLZ-04-00001121 |
| Molenhof Beheer B.V. | 24713208 | 2026-08-27 | — | 6860.70 | — | RLZ-04-00001116 |
| Molenhof Beheer B.V. | 24713229 | 2026-08-28 | — | 8238.99 | — | RLZ-04-00001117 |
| Molenhof Beheer B.V. | 24713233 | 2026-08-28 | — | 511.38 | — | RLZ-04-00001119 |
| Molenhof Beheer B.V. | 24713334 | 2026-09-01 | — | 466.91 | — | RLZ-04-00001128 |
| Molenhof Verhuur B.V. | 24713268 | 2026-07-21 | — | 1810.46 | — | RLZ-04-00000612 |
| Molenhof Verhuur B.V. | 24713251 | 2026-08-11 | — | 6058.17 | — | RLZ-04-00000602 |
| Molenhof Verhuur B.V. | 24713253 | 2026-08-11 | — | 6058.17 | — | RLZ-04-00000604 |
| Molenhof Verhuur B.V. | 24713252 | 2026-08-11 | — | 6058.17 | — | RLZ-04-00000603 |
| Molenhof Verhuur B.V. | 24713256 | 2026-08-13 | — | 1338.41 | — | RLZ-04-00000607 |
| Molenhof Verhuur B.V. | 24713257 | 2026-08-13 | — | 1338.41 | — | RLZ-04-00000608 |
| Molenhof Verhuur B.V. | 24713254 | 2026-08-13 | — | 2477.48 | — | RLZ-04-00000605 |
| Molenhof Verhuur B.V. | 24713259 | 2026-08-13 | — | 1338.41 | — | RLZ-04-00000610 |
| Molenhof Verhuur B.V. | 24713255 | 2026-08-13 | — | 1189.13 | — | RLZ-04-00000606 |
| Molenhof Verhuur B.V. | 24713258 | 2026-08-13 | — | 1338.41 | — | RLZ-04-00000609 |
| Molenhof Verhuur B.V. | 24713260 | 2026-08-14 | — | 12434.13 | — | RLZ-04-00000611 |
| Molenhof Verhuur B.V. | 24713191 | 2026-08-16 | — | 25.41 | — | RLZ-04-00000598 |
| Molenhof Verhuur B.V. | 24713313 | 2026-08-21 | — | 621.46 | — | RLZ-04-00000615 |
| Molenhof Verhuur B.V. | 24713312 | 2026-08-21 | — | 6024.14 | — | RLZ-04-00000614 |
| Molenhof Verhuur B.V. | 24713211 | 2026-08-27 | — | 5518.42 | — | RLZ-04-00000600 |
| Molenhof Verhuur B.V. | 24713207 | 2026-08-27 | — | 1189.13 | — | RLZ-04-00000599 |
| Molenhof Verhuur B.V. | 24713324 | 2026-08-27 | — | 10138.59 | — | RLZ-04-00000616 |
| Molenhof Verhuur B.V. | 24713343 | 2026-08-31 | — | 2676.82 | — | RLZ-04-00000623 |
| Molenhof Verhuur B.V. | 24713345 | 2026-08-31 | — | 1189.13 | — | RLZ-04-00000625 |
| Molenhof Verhuur B.V. | 24713340 | 2026-08-31 | — | 6058.17 | — | RLZ-04-00000620 |
| Molenhof Verhuur B.V. | 24713338 | 2026-08-31 | — | 1338.41 | — | RLZ-04-00000618 |
| Molenhof Verhuur B.V. | 24713341 | 2026-08-31 | — | 1338.41 | — | RLZ-04-00000621 |
| Molenhof Verhuur B.V. | 24713346 | 2026-08-31 | — | 5995.17 | — | RLZ-04-00000626 |
| Molenhof Verhuur B.V. | 24713344 | 2026-08-31 | — | 2676.82 | — | RLZ-04-00000624 |
| Molenhof Verhuur B.V. | 24713342 | 2026-08-31 | — | 1338.41 | — | RLZ-04-00000622 |
| Molenhof Verhuur B.V. | 24713347 | 2026-08-31 | — | 6024.14 | — | RLZ-04-00000627 |
| Molenhof Verhuur B.V. | 24713339 | 2026-08-31 | — | 6097.19 | — | RLZ-04-00000619 |
| Molenhof Verhuur B.V. | 24713327 | 2026-09-02 | — | 1185.45 | — | RLZ-04-00000617 |
| Oirschot Recreatie B.V. | 24713277 | 2026-07-22 | — | 2713.18 | — | RLZ-04-00002615 |
| Oirschot Recreatie B.V. | 24713274 | 2026-07-30 | — | 125.05 | — | RLZ-04-00002594 |
| Oirschot Recreatie B.V. | 24713234 | 2026-07-31 | — | 2452.07 | — | RLZ-04-00002584 |
| Oirschot Recreatie B.V. | 24713282 | 2026-07-31 | — | 82.04 | — | RLZ-04-00002617 |
| Oirschot Recreatie B.V. | 24713279 | 2026-07-31 | — | 4615.88 | — | RLZ-04-00002616 |
| Oirschot Recreatie B.V. | 24713242 | 2026-08-01 | — | 290.32 | — | RLZ-04-00002586 |
| Oirschot Recreatie B.V. | 24713371 | 2026-08-01 | — | 2074.57 | — | RLZ-04-00002635 |
| Oirschot Recreatie B.V. | 24713238 | 2026-08-03 | — | 89.83 | — | RLZ-04-00002585 |
| Oirschot Recreatie B.V. | 24713261 | 2026-08-05 | — | 681.50 | — | RLZ-04-00002587 |
| Oirschot Recreatie B.V. | 24713289 | 2026-08-05 | — | 75.53 | — | RLZ-04-00002618 |
| Oirschot Recreatie B.V. | 24713291 | 2026-08-06 | — | 512.10 | — | RLZ-04-00002619 |
| Oirschot Recreatie B.V. | 24713264 | 2026-08-07 | — | 362.83 | — | RLZ-04-00002588 |
| Oirschot Recreatie B.V. | 24713298 | 2026-08-10 | — | 13.24 | — | RLZ-04-00002620 |
| Oirschot Recreatie B.V. | 24713301 | 2026-08-14 | — | 90.19 | — | RLZ-04-00002621 |
| Oirschot Recreatie B.V. | 24713314 | 2026-08-22 | — | 941.44 | — | RLZ-04-00002622 |
| Oirschot Recreatie B.V. | 24713323 | 2026-08-26 | — | 284.56 | — | RLZ-04-00002623 |
| Oirschot Recreatie B.V. | 24713210 | 2026-08-27 | — | 699.90 | — | RLZ-04-00002569 |
| Oirschot Recreatie B.V. | 24713214 | 2026-08-27 | — | 177.24 | — | RLZ-04-00002575 |
| Oirschot Recreatie B.V. | 24713209 | 2026-08-27 | — | 115.37 | — | RLZ-04-00002568 |
| Oirschot Recreatie B.V. | 24713225 | 2026-08-28 | — | 623.21 | — | RLZ-04-00002580 |
| Oirschot Recreatie B.V. | 24713351 | 2026-08-31 | — | 2731.58 | — | RLZ-04-00002627 |
| Oirschot Recreatie B.V. | 24713332 | 2026-08-31 | — | 57.74 | — | RLZ-04-00002625 |
| Oirschot Recreatie B.V. | 24713367 | 2026-08-31 | — | 2642.92 | — | RLZ-04-00002633 |
| Oirschot Recreatie B.V. | 24713353 | 2026-08-31 | — | 2864.60 | — | RLZ-04-00002628 |
| Oirschot Recreatie B.V. | 24713333 | 2026-08-31 | — | 39.99 | — | RLZ-04-00002626 |
| Oirschot Recreatie B.V. | 24713355 | 2026-09-01 | — | 290.32 | — | RLZ-04-00002629 |
| Oirschot Recreatie B.V. | 24713357 | 2026-09-01 | — | 187.63 | — | RLZ-04-00002630 |
| Oirschot Recreatie B.V. | 24713369 | 2026-09-01 | — | 2074.57 | — | RLZ-04-00002634 |
| Oirschot Recreatie B.V. | 24713362 | 2026-09-02 | — | 1669.03 | — | RLZ-04-00002631 |
| Oirschot Recreatie B.V. | 24713325 | 2026-09-03 | — | 86.90 | — | RLZ-04-00002624 |
| Oirschot Recreatie B.V. | 24713363 | 2026-09-04 | — | 30.72 | — | RLZ-04-00002632 |
| Oirschot Recreatie B.V. | 24713375 | 2026-09-07 | — | 75.79 | — | RLZ-04-00002636 |
| Rubicon Investments B.V. | 24713213 | 2026-08-27 | — | 453.57 | — | RLZ-04-00002338 |
| Rubicon Investments B.V. | 24713354 | 2026-09-01 | — | 453.57 | — | RLZ-04-00002357 |
| Veldhoven Recreatie B.V. | 24712615 | 2026-04-02 | — | 245.21 | — | RLZ-04-00003929 |
| Veldhoven Recreatie B.V. | 24712648 | 2026-04-20 | — | 275.28 | — | RLZ-04-00003965 |
| Veldhoven Recreatie B.V. | 24712802 | 2026-05-11 | — | 102.73 | — | RLZ-04-00004092 |
| Veldhoven Recreatie B.V. | 24713276 | 2026-07-21 | — | 501.94 | — | RLZ-04-00004592 |
| Veldhoven Recreatie B.V. | 24713278 | 2026-07-27 | — | 355.74 | — | RLZ-04-00004593 |
| Veldhoven Recreatie B.V. | 24713235 | 2026-07-31 | — | 5872.13 | — | RLZ-04-00004530 |
| Veldhoven Recreatie B.V. | 24713281 | 2026-07-31 | — | 99.35 | — | RLZ-04-00004595 |
| Veldhoven Recreatie B.V. | 24713248 | 2026-07-31 | — | 442.92 | — | RLZ-04-00004538 |
| Veldhoven Recreatie B.V. | 24713267 | 2026-07-31 | — | 188.57 | — | RLZ-04-00004545 |
| Veldhoven Recreatie B.V. | 24713280 | 2026-07-31 | — | 17392.92 | — | RLZ-04-00004594 |
| Veldhoven Recreatie B.V. | 24713237 | 2026-07-31 | — | 5783.41 | — | RLZ-04-00004532 |
| Veldhoven Recreatie B.V. | 24713236 | 2026-07-31 | — | 2837.03 | — | RLZ-04-00004531 |
| Veldhoven Recreatie B.V. | 24713263 | 2026-07-31 | — | 2302.88 | — | RLZ-04-00004542 |
| Veldhoven Recreatie B.V. | 24713283 | 2026-08-01 | — | 1347.24 | — | RLZ-04-00004596 |
| Veldhoven Recreatie B.V. | 24713285 | 2026-08-01 | — | 119.89 | — | RLZ-04-00004598 |
| Veldhoven Recreatie B.V. | 24713372 | 2026-08-01 | — | 2074.57 | — | RLZ-04-00004643 |
| Veldhoven Recreatie B.V. | 24713243 | 2026-08-01 | — | 290.32 | — | RLZ-04-00004536 |
| Veldhoven Recreatie B.V. | 24713284 | 2026-08-03 | — | 1422.31 | — | RLZ-04-00004597 |
| Veldhoven Recreatie B.V. | 24713286 | 2026-08-04 | — | 397.56 | — | RLZ-04-00004599 |
| Veldhoven Recreatie B.V. | 24713373 | 2026-08-04 | — | 800.42 | — | RLZ-04-00004644 |
| Veldhoven Recreatie B.V. | 24713270 | 2026-08-04 | — | -381.15 | — | RLZ-04-00004552 |
| Veldhoven Recreatie B.V. | 24713288 | 2026-08-04 | — | 1993.33 | — | RLZ-04-00004600 |
| Veldhoven Recreatie B.V. | 24713290 | 2026-08-05 | — | 161.62 | — | RLZ-04-00004601 |
| Veldhoven Recreatie B.V. | 24713249 | 2026-08-06 | — | 2350.43 | — | RLZ-04-00004539 |
| Veldhoven Recreatie B.V. | 24713239 | 2026-08-06 | — | 267.52 | — | RLZ-04-00004533 |
| Veldhoven Recreatie B.V. | 24713244 | 2026-08-06 | — | 2085.22 | — | RLZ-04-00004537 |
| Veldhoven Recreatie B.V. | 24713250 | 2026-08-06 | — | 508.20 | — | RLZ-04-00004540 |
| Veldhoven Recreatie B.V. | 24713262 | 2026-08-07 | — | 283.75 | — | RLZ-04-00004541 |
| Veldhoven Recreatie B.V. | 24713292 | 2026-08-10 | — | 251.92 | — | RLZ-04-00004602 |
| Veldhoven Recreatie B.V. | 24713293 | 2026-08-10 | — | 524.43 | — | RLZ-04-00004603 |
| Veldhoven Recreatie B.V. | 24713265 | 2026-08-10 | — | 107.99 | — | RLZ-04-00004543 |
| Veldhoven Recreatie B.V. | 24713299 | 2026-08-11 | — | 1550.53 | — | RLZ-04-00004604 |
| Veldhoven Recreatie B.V. | 24713241 | 2026-08-11 | — | 532.34 | — | RLZ-04-00004535 |
| Veldhoven Recreatie B.V. | 24713266 | 2026-08-13 | — | 4.71 | — | RLZ-04-00004544 |
| Veldhoven Recreatie B.V. | 24713300 | 2026-08-13 | — | 189.62 | — | RLZ-04-00004605 |
| Veldhoven Recreatie B.V. | 24713273 | 2026-08-14 | — | 2026.45 | — | RLZ-04-00004590 |
| Veldhoven Recreatie B.V. | 24713271 | 2026-08-14 | — | 5806.87 | — | RLZ-04-00004553 |
| Veldhoven Recreatie B.V. | 24713303 | 2026-08-17 | — | 579.35 | — | RLZ-04-00004607 |
| Veldhoven Recreatie B.V. | 24713302 | 2026-08-17 | — | 2612.47 | — | RLZ-04-00004606 |
| Veldhoven Recreatie B.V. | 24713306 | 2026-08-18 | — | 559.92 | — | RLZ-04-00004610 |
| Veldhoven Recreatie B.V. | 24713304 | 2026-08-18 | — | 2633.65 | — | RLZ-04-00004608 |
| Veldhoven Recreatie B.V. | 24713305 | 2026-08-18 | — | 69.62 | — | RLZ-04-00004609 |
| Veldhoven Recreatie B.V. | 24713308 | 2026-08-19 | — | 578.08 | — | RLZ-04-00004612 |
| Veldhoven Recreatie B.V. | 24713307 | 2026-08-19 | — | 744.37 | — | RLZ-04-00004611 |
| Veldhoven Recreatie B.V. | 24713311 | 2026-08-20 | — | 28.52 | — | RLZ-04-00004615 |
| Veldhoven Recreatie B.V. | 24713309 | 2026-08-20 | — | 705.54 | — | RLZ-04-00004613 |
| Veldhoven Recreatie B.V. | 24713310 | 2026-08-20 | — | 322.56 | — | RLZ-04-00004614 |
| Veldhoven Recreatie B.V. | 24713315 | 2026-08-22 | — | 313.81 | — | RLZ-04-00004616 |
| Veldhoven Recreatie B.V. | 24713317 | 2026-08-24 | — | 1734.23 | — | RLZ-04-00004617 |
| Veldhoven Recreatie B.V. | 24713321 | 2026-08-24 | — | 89.25 | — | RLZ-04-00004621 |
| Veldhoven Recreatie B.V. | 24713240 | 2026-08-24 | — | 89.25 | — | RLZ-04-00004534 |
| Veldhoven Recreatie B.V. | 24713320 | 2026-08-24 | — | 89.24 | — | RLZ-04-00004620 |
| Veldhoven Recreatie B.V. | 24713269 | 2026-08-24 | — | 545.69 | — | RLZ-04-00004551 |
| Veldhoven Recreatie B.V. | 24713318 | 2026-08-24 | — | 89.25 | — | RLZ-04-00004618 |
| Veldhoven Recreatie B.V. | 24713319 | 2026-08-24 | — | 89.25 | — | RLZ-04-00004619 |
| Veldhoven Recreatie B.V. | 24713322 | 2026-08-26 | — | 367.26 | — | RLZ-04-00004622 |
| Veldhoven Recreatie B.V. | 24713206 | 2026-08-26 | — | 158.23 | — | RLZ-04-00004490 |
| Veldhoven Recreatie B.V. | 24713215 | 2026-08-27 | — | 177.24 | — | RLZ-04-00004503 |
| Veldhoven Recreatie B.V. | 24713212 | 2026-08-27 | — | 460.59 | — | RLZ-04-00004491 |
| Veldhoven Recreatie B.V. | 24713216 | 2026-08-27 | — | 825.83 | — | RLZ-04-00004504 |
| Veldhoven Recreatie B.V. | 24713226 | 2026-08-28 | — | 37.76 | — | RLZ-04-00004517 |
| Veldhoven Recreatie B.V. | 24713232 | 2026-08-28 | — | 33.44 | — | RLZ-04-00004521 |
| Veldhoven Recreatie B.V. | 24713231 | 2026-08-28 | — | 293.49 | — | RLZ-04-00004520 |
| Veldhoven Recreatie B.V. | 24713228 | 2026-08-28 | — | 6352.50 | — | RLZ-04-00004519 |
| Veldhoven Recreatie B.V. | 24713227 | 2026-08-28 | — | 180.07 | — | RLZ-04-00004518 |
| Veldhoven Recreatie B.V. | 24713365 | 2026-08-31 | — | 1329.28 | — | RLZ-04-00004639 |
| Veldhoven Recreatie B.V. | 24713359 | 2026-08-31 | — | 38.88 | — | RLZ-04-00004635 |
| Veldhoven Recreatie B.V. | 24713329 | 2026-08-31 | — | 24.78 | — | RLZ-04-00004625 |
| Veldhoven Recreatie B.V. | 24713358 | 2026-08-31 | — | 127.05 | — | RLZ-04-00004634 |
| Veldhoven Recreatie B.V. | 24713349 | 2026-08-31 | — | 5425.04 | — | RLZ-04-00004630 |
| Veldhoven Recreatie B.V. | 24713360 | 2026-08-31 | — | 104.82 | — | RLZ-04-00004636 |
| Veldhoven Recreatie B.V. | 24713368 | 2026-08-31 | — | 5583.52 | — | RLZ-04-00004641 |
| Veldhoven Recreatie B.V. | 24713350 | 2026-08-31 | — | 22.91 | — | RLZ-04-00004631 |
| Veldhoven Recreatie B.V. | 24713352 | 2026-08-31 | — | 6156.21 | — | RLZ-04-00004632 |
| Veldhoven Recreatie B.V. | 24713356 | 2026-09-01 | — | 290.32 | — | RLZ-04-00004633 |
| Veldhoven Recreatie B.V. | 24713336 | 2026-09-01 | — | 561.71 | — | RLZ-04-00004628 |
| Veldhoven Recreatie B.V. | 24713370 | 2026-09-01 | — | 2074.57 | — | RLZ-04-00004642 |
| Veldhoven Recreatie B.V. | 24713330 | 2026-09-01 | — | 1347.24 | — | RLZ-04-00004626 |
| Veldhoven Recreatie B.V. | 24713348 | 2026-09-01 | — | 386.50 | — | RLZ-04-00004629 |
| Veldhoven Recreatie B.V. | 24713366 | 2026-09-01 | — | 65.87 | — | RLZ-04-00004640 |
| Veldhoven Recreatie B.V. | 24713331 | 2026-09-02 | — | 1016.40 | — | RLZ-04-00004627 |
| Veldhoven Recreatie B.V. | 24713328 | 2026-09-02 | — | 16.44 | — | RLZ-04-00004624 |
| Veldhoven Recreatie B.V. | 24713361 | 2026-09-02 | — | 184.54 | — | RLZ-04-00004637 |
| Veldhoven Recreatie B.V. | 24713326 | 2026-09-03 | — | 350.17 | — | RLZ-04-00004623 |
| Veldhoven Recreatie B.V. | 24713364 | 2026-09-04 | — | 89.54 | — | RLZ-04-00004638 |
| Veldhoven Recreatie B.V. | 24713374 | 2026-09-04 | — | 400.44 | — | RLZ-04-00004645 |
| Veldhoven Recreatie B.V. | 24713376 | 2026-09-07 | — | 143.75 | — | RLZ-04-00004646 |
| Veldhoven Recreatie B.V. | 24713377 | 2026-09-08 | — | 59.86 | — | RLZ-04-00004647 |

Duiding: de inkoopfacturen dragen KF-verkoopnummers (24713xxx, augustus/september 2026) maar de bron-verkoop is niet gevonden in
het venster op de KF-Entity/crediteurrecords van de doelentiteit — hypothesen: (a) de verkoopfactuur staat bij KF op een ándere
debiteur-relatie (naam-variant) dan de whitelist-rij; (b) de verkoop is in KF nog concept zonder nummer terwijl het doel al boekte
(Zenvoices-volgorde); (c) leesvenster/expand. Niet gebouwd — beslispunt (structureel bij Veldhoven 88, Oirschot 32, Molenhof Verhuur 28).

## Status verschilt (> 7 d) — 0 · Doel niet in module — 0

## Cloud Logging — herkoppeling doelentiteiten (job rlz-sync, 17-09 05:04 UTC)
```
2026-09-17T05:04:09Z  Doorbelasting — herkoppeling doelentiteiten (whitelist zonder doel):
2026-09-17T05:04:10Z    herkoppeling doelentiteiten: open=1 gekoppeld=1 bijna_match=0 meerdere=0 geen=0
2026-09-17T05:04:10Z    GEKOPPELD  'Kempen Chalets B.V.' → 'Kempen Chalets B.V.' (3206a747-45ec-430f-98ec-fe58496679de)
```
Verwachting "Kempen Chalets GEKOPPELD (exact), Mantelzorgwoning al gekoppeld" = **gehaald**.

## Beslispunten Peter (structureel — `2026-09-17-beslispunten-peter.md` opdracht 9)
1. Molenhof Beheer: 54 verkoopfacturen KF zonder inkoop in het doel (o.a. 24712556/24712912/24713197 € 158.812,50 op 24-03/05-06/11-08-2026,
   24712815 € 127.050,00 13-05-2026) — inkoop niet geboekt of ander crediteurrecord? Controle in RLZ Molenhof Beheer.
2. 166 inkoopfacturen mét KF-nummer zonder gevonden bron-verkoop (Veldhoven 88, Oirschot 32, Molenhof Verhuur 28, Molenhof Beheer 9,
   Mantelzorg 6, Rubicon 2) — welke debiteur-relatie gebruikt KF voor deze doelen? (module leest de whitelist-Entity + IC-relatie.)
3. Nulfactuur 24712873 (Veldhoven, 28-05-2026, € 0,00).
