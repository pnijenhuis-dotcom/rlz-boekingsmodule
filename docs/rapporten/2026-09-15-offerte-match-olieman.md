# Offerte-melding ontbrak op de eerste Olieman-termijnfactuur — oorzaak + fix (Peter 15-09)

**Oorzaak in twee zinnen:** De match kent alleen goedgekeurde verplichtingen als kandidaat en de Olieman-offerte wachtte nog op één
accordeur, dus de factuur kreeg de stille uitkomst "geen verplichting" en het controlescherm zei niets. Er was geen crediteur- of
projectprobleem: Bouwadvies Oost Nederland heeft geen projecten in Reeleezee en de match werkt zonder project.

**Werkt in productie:** niet gemeten (deploy volgt op de Stop-hook; meetrecept hieronder). De oorzaak is uit de code herleid; een
lees-only blik op de productie-matchrij was in deze run niet mogelijk (routes vragen een sessie, de nameting-allowlist kent geen
verplichtingen-commando) — het meetrecept bevestigt 'm ná deploy.

## Gebouwd

| Punt | Wat | Waar |
|---|---|---|
| 1 | Herleiding: `lopende_kandidaten` = alleen status geaccordeerd; ter accordering → nul kandidaten → `geen_verplichting` → component stil. STAP-0 lees-only: Bouwadvies 0 projecten in RLZ (executie `2jwlb`). | `app/verplichting/match_pipeline.py` |
| 2 | Wachtende verplichting zichtbaar: `Wachtende` (nog niet goedgekeurd mét status-reden, of ander crediteurrecord met dezelfde naam) → `niet_toetsbaar` mét reden + verwijzing; DTO `niet_toetsbaar_reden`; controlescherm toont chip "offerte nog niet toetsbaar", de zin, "Open de verplichting →" en "Koppel offerte…". Nooit blokkerend, geen migratie (sub-vorm van `niet_toetsbaar`). | `match.py`, `match_pipeline.py`, `service.py`, `schemas.py`, `router.py`, `frontend/src/document/OfferteMatchMelding.tsx` |
| 3 | Termijnen: cumulatief toetsen bestond al; nieuw `Kandidaat.aantal_gematcht` → `details.termijn`, melding en kaart "deze factuur (1e termijn, € 20.000,00) past; verbruik ná deze factuur € 20.000,00 van € 85.000,00"; `geen_match` op een ander project noemt de bestaande offertes | idem |
| 5 | Bij goedkeuring (bestaande hook) worden open én geboekte facturen herberekend; een geboekte factuur die nu binnen/buiten is wordt achteraf verrekend: verbruik bijgeschreven, tijdlijnregel "achteraf gekoppeld aan offerte OFF-… (1e termijn) — binnen …", audit `verplichting_achteraf_gekoppeld`; idempotent; meerduidig = melden, niet koppelen | `match_pipeline._verreken_achteraf` |
| 4 | Gouden-set-casus: casus z (factuur 32948) uitgebreid met de € 85.000-offerte ter accordering → niet toetsbaar mét reden; ná goedkeuring binnen, termijn 1, 24 % | `tests/keten/test_z_verlegd_kolomcode.py::TestOfferteMatchOpDeTermijnfactuur` |

## Tests

`tests/verplichting/test_match.py::TestWachtendeVerplichtingEnTermijn` (6), `tests/verplichting/test_achteraf_koppelen.py` (2),
keten casus z (+1); tests/verplichting + keten z + export-deterministisch + keten-guard: 112 groen. Frontend
`OfferteMatchMelding.test.tsx` 7 groen (2 nieuw); `tsc -b` groen (pre-commit).

## Meetrecept ná deploy

Open factuur 32948 bij Bouwadvies Oost Nederland: zolang de offerte op akkoord wacht staat er "Offerte van deze leverancier gevonden
maar niet toetsbaar: nog niet goedgekeurd (wacht op accordering)" mét link naar de offerte. Ná het laatste akkoord, zonder handeling:
"binnen offerte … (1e termijn) € 20.000,00 … van € 85.000,00", tijdlijnregel "achteraf gekoppeld aan offerte …", verbruik € 20.000 op de
verplichting in Inzicht › Verplichtingen.
