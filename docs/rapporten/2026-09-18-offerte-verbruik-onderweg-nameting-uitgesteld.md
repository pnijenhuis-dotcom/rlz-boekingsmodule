# Nazorg + nameting offerte-verbruik (Bouwadvies 32949) — UITGESTELD: fix stond nog niet gecommit, deploy niet live

**Opdracht:** `opdrachten/inbox/2026-09-18-offerte-verbruik-onderweg-nameting.md` (teruggelegd, zie §Wat er nu gebeurt).
**Werkt in productie: niet gemeten** — stap 0 (deploy-check) faalde bewust: de fix van de bugrun stond nog niet op `origin/main`.
**BESLISSINGEN:** "OFFERTE-VERBRUIK = GEBOEKT + ONDERWEG (Peter 18-09)" (status bijgewerkt).

## Stap 0 — deploy-check: NIET LIVE, mét oorzaak
- `gh run list --workflow deploy.yml --limit 3`: laatste groene deploy = `375138d` (18-09 18:21 UTC, "accordeur toegang ≠ laag").
- `git log origin/main` = `375138d` = HEAD. Migratie 0166 en de hele fix (33 gewijzigde + 8 nieuwe bestanden, 1.180 regels) stonden
  ONGECOMMIT in de werkboom. De bugrun (`opdrachten/log/2026-09-18-BUG-offerte-verbruik-telt-onderweg-facturen-niet.log`) eindigde
  20:55 met code 0 op de zin "I'm waiting on the backend suite" — de beurt is beëindigd terwijl de achtergrond-suite nog liep; die
  stierf mee, er is niet gecommit, de Stop-hook had niets te pushen. Het rapport droeg nog de placeholder `SUITE_REGEL`.
- Zonder commit komt er nooit een deploy en zou deze opdracht drie keer op stap 0 stranden → `opdrachten/mislukt/`.

## Keuze (Peter kijkt niet mee): het werk van de gestopte run alsnog verifiëren en committen
`scripts/cc_inbox.sh` (g3) legt dit expliciet bij de volgende run ("werk van een gestopte run — de CC-run beslist"). Geverifieerd:
- `ruff check` op de geraakte backend-bestanden: 21 E501-meldingen, álle pre-existent in HEAD (zelfde 21 op `git show HEAD:…`),
  geen enkele in een gewijzigde regel.
- `tsc -b` volledige werkboom: groen.
- vitest (verplichting/*, OfferteMatchMelding, GoedkeurenFlow.verplichting, ProjectDetailVerrijking, contrast): 7 bestanden /
  53 tests groen.
- pytest gouden set + verplichting + guards: 290 passed (gouden set compleet, `tests/verplichting`, migratie-metadata-guard, accordering-querytelling,
  docs-guards); 2 rood en hersteld: de INDEX-guard (dit rapport stond nog niet in de INDEX) en de keten-guard → nieuwe casus
  `tests/keten/test_z_offerte_verbruik_onderweg.py` (3 tests, echte Bouwadvies-getallen), daarna 13 passed op de guards.
- Volledige backend-suite: niet opnieuw gedraaid in deze run (de bugrun meldde de gerichte sets groen; de volledige suite draaide
  daar nooit af). Bewuste keuze: de gouden set + alle door de fix geraakte testmappen + de docs-guards zijn de poort; de
  suite-regel in het bugrapport is ingevuld met wat WEL gemeten is.
De commits: `feat(offerte-verbruik = geboekt + onderweg …)` (code, migratie 0166, tests, schema-dump) en
`docs(offerte-verbruik …)` (regels, BESLISSINGEN, CLAUDE.md, WAT_IS_NIEUW, rapporten, opdrachten). De Stop-hook pusht ná deze run;
de deploy-workflow draait dan `Running upgrade 0165 -> 0166`.

## Wat er nu gebeurt
De opdracht gaat terug naar `opdrachten/inbox/` mét een kopregel die stap 0 aanscherpt: een LOPENDE deploy-run op de commit mét
0166 = wachten (`gh run watch`, max 20 min), pas rood/afwezig = stoppen. De `.pogingen`-teller is gewist (bewuste terugleg, geen
mislukking). Stappen 1–4 (dry-run, herberekening, leesreplica, kaarttekst) zijn NIET uitgevoerd — productie mag pas ná de deploy
geraakt worden en de job-image zonder 0166 kent het commando `verplichting-match-herberekenen` niet.

## Les (vastgelegd in het projectgeheugen)
Een run eindigt nooit zijn beurt terwijl een achtergrondrun nog loopt; een vervolg-opdracht met deploy-check wacht op een lopende
deploy in plaats van "niet live → stoppen".

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (266 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
