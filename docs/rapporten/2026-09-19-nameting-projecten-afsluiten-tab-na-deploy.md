# Nameting ná deploy — Projecten › Afsluiten? (N) bij Universal Steigerbouw (19-09 avond)

**Opdracht:** `opdrachten/gedaan/2026-09-19-nameting-projecten-afsluiten-tab-na-deploy.md` (vervolg op
`docs/rapporten/2026-09-19-projecten-afsluiten-tab-bulk.md`). Lees-only nameting; geen afsluiten vanuit de run, geen RLZ-write,
geen migratie. Bijvangst: één deterministische fix in de kandidatenmotor + guard (zie § Bijvangst).

**Werkt in productie: JA** voor de kandidatenmotor op de gedeployde job-image (dezelfde acht kandidaten als op de replica vóór de
deploy); **NIET GEMETEN** voor de tab zelf: `GET /projecten/afsluit-kandidaten` is op 19-09 in productie door geen mens aangeroepen
(request-log leeg voor die route; andere `/projecten`-routes zijn wél zichtbaar, dus de query werkt). De tab-route is lokaal live-200
gemeten in de bouwrun; het productiebewijs komt zodra Peter of Haci de tab opent.

## Één regel voor Peter
De motor achter "Afsluiten? (N)" draait in productie en vindt bij Universal dezelfde acht "Afgesloten …"-projecten als vanochtend;
niemand heeft de tab nog geopend of iets afgevinkt (0 afgesloten, 0 uitgesteld, stil-venster 6 mnd). Eén correctie op het
bouwrapport: 25017 Kudo Arnhem heeft géén eindfactuur-reden — de jongste verkoopregel is een termijn (03-06), de "Eindafrekening"
was van 06-03; de motor doet dat goed.

## Stap 0 — deploy-check (groen)
| Toets | Uitkomst |
|---|---|
| `git rev-list --count main..origin/main` / `origin/main..main` | 0 / 0 (geen divergentie, geen stille push-blokkade) |
| Commit mét migratie 0167 + `app/projecten/afsluiten.py` | `86ecbad` |
| Deploy-runs deploy.yml | `1dab82c` (35449947839), `a731dd4`, `764072a`, `a3eac85` (35454193550) — alle groen |
| Service `rlz-backend` image | `backend:a3eac859986f…` |
| Jobs `rlz-reconciliatie`, `rlz-sync` image | `backend:a3eac859986f…` (= service) |
| `86ecbad` ∈ `1dab82c` ∈ `a3eac85` | ja (merge-base) |

## Meetrecept 1 — kandidatenmotor op de job-image
Twee nameting-runs (WIF `nameting@`, job-executies op de gedeployde image, `projecten-afsluit-kandidaten --administratie "Universal
Steigerbouw"` als onderdeel van `projecten-afgesloten`):

| Run | Image | Uitkomst |
|---|---|---|
| 35447853112 → bot-commit `d724769` (`verkenning/nameting-projecten-afgesloten-19-09.txt`, 16:28) | `0791109` ⊃ `86ecbad` | "Universal Steigerbouw B.V. (3ee6edf0…) — 83 lopende projecten, 8 kandidaat, 0 uitgesteld; per reden: geen activiteit 0, eindfactuur geboekt 0, naam zegt afgesloten 8, looptijd verstreken 0 … Totaal: 83 lopende projecten beoordeeld, 8 kandidaat afsluiten (…), 0 uitgesteld" — de acht: 25157 Harderwijk (laatste verkoop 30-03 € 800 [808010709]), 25017 Kudo Arnhem (verkoop 03-06 € 10.000 [808010818]), 26064 Apeldoorn (inkoop 11-06 € 688 [2026-424]), 25116 Oosterhout (inkoop 23-07 € 688 [2026-554]), 25147 Ommeren (inkoop 23-07 € 2.093,75 [2026-569]), 26012 Tilburg (inkoop 02-09 € 48,47 [F212604921]), 26051 Opijnen (inkoop 02-09 € 15,36 [F212604921]), 26091 Amersfoort (verkoop 15-09 € 10.454,75 [808010923]) |
| 35450280469 (14:57Z, `1dab82c`) | `1dab82c` | uitvoer byte-identiek → bot "geen wijzigingen — geen commit" (rapport 2026-09-19-projectnummer-uit-afgesloten-naam) |
| 35454573374 (deze opdracht, 16:19Z, gestart ná de a3eac85-deploy) | `a3eac85` | groen (16:39Z); executie `rlz-reconciliatie-4rdcp` (Cloud Logging, onafhankelijk uit het run-log gelezen): "Totaal: 83 lopende projecten beoordeeld, 8 kandidaat afsluiten (geen activiteit 0, eindfactuur geboekt 0, naam zegt afgesloten 8, looptijd verstreken 0), 0 uitgesteld" — byte-identiek aan `d724769`, dus bot-stap "geen wijzigingen — geen commit" (origin/main niet vooruit, geen push-blokkade); zusterexecuties: `xxcm4`/`sf976` facturen-zonder-project 0 bevindingen / 5 gedekt, `bf2dv` 8 actieve 'Afgesloten'-projecten + 10 geboekte verdelingsdelen, `vl45f` reconciliatie-alles --alleen projecten, `9pvgh` 4 dubbele nummers |

Verwachting uit het meetrecept ("83 beoordeeld, 8 kandidaat, naam zegt afgesloten 8") = gehaald. Niets afgevinkt, dus de
"of minder"-tak (tellen in `project_cache.status='afgesloten'` + audit) is de nulstand — gemeten op de leesreplica.

## Meetrecept 1b — leesreplica (`scripts/gcp/db_lezen.sh`, `nameting@…iam`, READ ONLY, scope Universal 3ee6edf0)
| Query | Uitkomst |
|---|---|
| `project_cache` per status × is_actief (niet verdwenen) | lopend + actief **83**, lopend + inactief 87, afgesloten **0** |
| `project_afsluit_uitstel` Universal | **0** rijen |
| `platform.administratie.project_afsluit_stil_maanden` | **6** (default, niet gewijzigd) |
| `audit_event` `project_afgesloten` / `project_afsluiten_uitgesteld` / `project_afsluit_stil_maanden_gewijzigd` Universal | **0** |
| verkoopregels project 25017 (`2aa11d10…`) datum desc | 03-06-2026 € 10.000 "Hefsteiger compleet 2e van 2 termijnen)" [808010818]; 10-04 € 10.000 "… 1e van 2 termijnen)" [808010733]; **06-03 € 13.670 "Eindafrekening" [808010670]**; ouder: termijnen/meerwerk |

## Meetrecept 2 — Cloud Logging `GET /projecten/afsluit-kandidaten`
Request-log `rlz-backend` 19-09 00:00Z → nu: **0 treffers** op `afsluit-kandidaten`, `afsluit-instelling`, `afsluiten-bulk`,
`niet-afsluiten`. Sanity: dezelfde query op `/projecten` toont wél 200's (06:51 `administraties/005e2bca…/projecten`, 11:25
`uren/uitvoerder/projecten`) en op `3ee6edf0` de planning-/dossierroutes → de tab is nog niet geopend. **Niet gemeten**, geen
fout; Peter/Haci openen de tab (klikpunt), daarna is dit één logregel. Zelf aanroepen kan niet: dat vergt een kantoor-login
tegen productie, en dat doet een run niet.

## Correctie op het bouwrapport: 25017 "óók eindfactuur" was fout
Het bouwrapport (§ Meting, replica ~09:30) en de BESLISSINGEN-rij zeiden dat 25017 náást de naam ook de reden `eindfactuur`
had. Productie zegt "eindfactuur geboekt 0" — en dat is juist: de regel is "de JONGSTE verkoopregel draagt eindfactuur/
eindafrekening/slotfactuur"; bij 25017 is de jongste verkoopregel de termijn van 03-06 (808010818), de "Eindafrekening"
(808010670) is van 06-03 en daarna zijn er nog twee termijnen gefactureerd. De regel is bewust zo (een eindafrekening mét
termijnen erna betekent dat het project doorliep). BESLISSINGEN en de regels-alinea zijn gecorrigeerd; het bouwrapport blijft
staan mét een verwijsregel bovenaan.

## Bijvangst — eindfactuur-reden was databasevolgorde-afhankelijk (gefixt + guard)
Bij het naspeuren van dat verschil: `afsluiten._laatste_regel_per_project` haalde álle regels op de jongste datum per project op
en nam de EERSTE rij zonder `ORDER BY`. Een verkoopfactuur heeft meestal meerdere regels op dezelfde datum; welke regel
"jongste verkoop" werd, hing dus af van de heap-volgorde — en die kan op de leesreplica anders zijn dan op de primary, zodat
de reden `eindfactuur` op de ene stand wél en op de andere níét uitviel. Voor 25017 speelt dat niet (één regel op 03-06), maar
het is precies de klasse fout die "deterministisch" verbiedt. Fix (`backend/app/projecten/afsluiten.py`): vaste volgorde
(`rlz_document_id`, `id`) én een regel mét de eindfactuur-tekst wint binnen de jongste datum — één regel "Eindfactuur" op een
factuur mét transport-/kraanregels is een eindfactuur. Guard
`tests/projecten/test_afsluiten.py::TestMotorOpDatabase::test_eindfactuur_meerdere_regels_op_jongste_datum_is_deterministisch`
(drie regels op één datum mét de eindfactuurregel als tweede ingevoegd → reden `eindfactuur`; de 25017-casus → géén reden;
driemaal herhaald = zelfde uitkomst). Tegenproef: zónder fix rood (`() == ('eindfactuur',)`), mét fix groen.
`tests/projecten/test_afsluiten.py` 11 passed; ruff schoon op de eigen regels (9 bestaande E501's in docstrings ongewijzigd).
Geen migratie, geen API-wijziging; deploy volgt via de Stop-hook-push. Productie-effect bij Universal: geen (0 → 0 eindfactuur).

## Keuzes in deze run (Peter kijkt niet mee)
- De fix is klein, in het gelezen domein en direct uit de nameting voortgekomen → in dezelfde run gefixt + guard (regel 19-09
  "systeemfout van de bouw = fix + guard in dezelfde run"), niet als vervolg-opdracht geparkeerd.
- Geen nieuwe vervolg-opdracht voor de tab-200: dat is één logregel ná de eerste klik van Peter/Haci; de eerstvolgende nameting die
  Universal raakt kan 'm meenemen. Wel als klikpunt hieronder.
- De verse run is gestart hoewel het bot-bestand van 16:28 al dezelfde meting op een 0167-image droeg: het meetrecept vraagt
  een meting ná de deploy die deze opdracht noemt, en de a3eac85-deploy was net live.

## Klikpunten Peter/Haci
1. Projecten › Universal Steigerbouw › tab "Afsluiten? (8)" openen (= de ontbrekende 200 in het log) en de acht afvinken; daarna
   verdwijnt de LET-OP "naam zegt afgesloten" uit reconciliatieblok `projecten` en neemt de verdeelsleutel ze niet meer mee.
2. Stil-venster 6 of 4 maanden (beslispunt uit het bouwrapport, ongewijzigd).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (376 regels bij het lezen; 395 ná deze run)
- `docs/regels/werkloop-productie.md` (162 regels)
