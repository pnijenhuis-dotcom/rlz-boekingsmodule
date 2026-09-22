# Nameting activa fase 1 (is_activa-sync, register-probe, reconciliatieblok `activa`) + lees-only `bua-kandidaten` ná de deploy van 21-09

**Opdracht:** `opdrachten/gedaan/2026-09-22-nameting-activa-fase1-en-bua-kandidaten-na-deploy.md` (uit inbox, `niet vóór: 2026-09-22 09:00`).
**Bouwrapport:** `docs/rapporten/2026-09-21-activa-fase1-bua-vgg-toewijzing-universal-overhead.md` secties A en B; BESLISSINGEN "ACTIVA / MVA — FASE 1
GEBOUWD (Peter 21-09)" en "BUA-KENMERK — LEES-ONLY METING + BULK-VOORSTEL (Peter 21-09)".
**Uitgevoerd:** 22-09-2026 10:10–12:59 UTC (poging 1, metingen + documentatie; poort niet gehaald → WIP-branch) en 15:52–18:25 UTC (poging 2: squash van de WIP, poort, commit), Peter kijkt niet mee — keuzes in de sectie "Keuzes".

## Werkt in productie

| onderdeel | oordeel | bewijs |
|---|---|---|
| Sync: `is_activa` + `activa_instelling` (grens, RLZ-grens, register-probe) | **JA** | leesreplica per administratie (RLS): 344 `is_activa` / 75 RLZ-administraties = nulmeting; grens 450/450 op 75; probe 73 leesbaar + 2 × 403 (Universal, Rubicon) |
| Reconciliatieblok `activa` | **JA** | `reconciliatie-alles --alleen activa --lees-only` op `ba2e231`: 75 getoetst, 22 afwijkingen in `meten`, < 50 per soort, 0 FOUT |
| Kaart "Activum aanmaken?" — route `GET …/activa-voorstel` | **JA** | request-log sinds de deploy: 8 × 200, 0 × 5xx |
| Kaart zichtbaar + `POST …/aanmaken` → activum in RLZ | **niet gemeten** | geen module-document mét een regel op een MVA-rekening (Pilates Bloom 0; `activum_koppeling` 0 rijen) — klikpunt |
| Lees-only run legt niets vast | **NEE → gefixt** | `register_geprobeerd_op` bij 75 administraties verplaatst naar 10:18–10:19 UTC; fix + guards in deze commit, meetlat 23-09 |
| `bua-kandidaten` (dispatch-onderdeel, meting) | **JA** | run 35715207462 → bot-commit `922eb28` `verkenning/nameting-bua-kandidaten-22-09.txt`: TOTAAL 297 in 75/78, 0 aan, zetten 149, 0 fouten = replica-meting 21-09 |

## Stap 0 — deploy-check

- `git rev-list --count main..origin/main` = 0 (en `origin/main..main` = 0) vóór de meting.
- Service `rlz-backend` revisie `rlz-backend-00666-c5c` + alle 17 jobs op image `…backend:ba2e2317…` (= HEAD `ba2e231`, deploy-run 35714284594,
  klaar 10:13 UTC). Fase 1 (`81f65d9`) is live sinds deploy `81f5de2` (21-09 13:36 UTC = 15:36 NL); de `sync-alles` van 22-09 05:00 UTC liep als
  `rlz-sync-dwfpj` op image `fb63be5` (21-09 17:38 UTC) — dus mét de activa-code.

## Stap 1 — `is_activa` + `activa_instelling` (leesreplica, per administratie)

Methode: `scripts/gcp/db_lezen.sh` als `nameting@…iam` (rol `rlz_lezer`, READ ONLY) mét `--administratie <id>` per administratie — `grootboekrekening`
en `activa_instelling` hebben alleen een scope-policy (FORCE RLS), één cross-administratie-query geeft 0 rijen (les 19-09). 80 rijen `administratie`,
78 actief (2 gearchiveerd: "Nijenhuis (test)", "Test-administratie (passkey-test)").

| meting | verwacht (meetlat 21-09) | gemeten 22-09 | oordeel |
|---|---|---|---|
| `is_activa`-rekeningen RLZ | ≈ 344 over 75 administraties | **344 over 75** (+ 3 Odoo-administraties × 48 via `asset_fixed` = 488 totaal) | exact |
| Pilates Bloom B.V. | 4: 0101/0107/0111/0113 | 0101 Gebouwen en terreinen, 0107 Kantoorinventaris, 0111 ICT apparatuur, 0113 Computersoftware; `laatst_gesynchroniseerd` 05:01:50 UTC | exact |
| `activa_instelling` grens | `activeringsgrens` 450,00 + `grens_rlz` 450,00 | 75/75 RLZ-administraties, `grens_rlz_gelezen_op` 05:00:35–05:01:50 UTC (= de sync) | exact |
| `register_leesbaar` | true; Universal false mét "recht ontbreekt (403)" | 73 × true; **Universal Steigerbouw B.V. en Rubicon Investments B.V.** false mét `register_fout` "recht ontbreekt (403) — RLZ-recht 'Vaste activa' op de webservice-login zetten" | exact (Rubicon stond ook al in de nulmeting) |
| `automatisch_aanmaken_ingeschakeld` | default UIT | 0 × aan | exact |
| Odoo-administraties (Bonte Hoeve, Camping "Nieuwenhoven", Recreatief Vastgoed Nederland) | — | 48 `is_activa` elk, géén `activa_instelling`-rij | bedoeld: `_activa_na_ledgers_sync` zit in het RLZ-syncpad, fase 1 is RLZ-only |

Afwijkende MVA-sets zijn échte rekeningschema's (geen bug): Rubicon Investments 28 (01100…0170, o.a. 0113 Verhuurmateriaal), B. van Rooijen /
G. Schaalje 19 (0101/0107/0111/0113 + 0120–0134), Stichting Shuto 7 (01011–01014 + 0107/0111/0113), Inpensas Beheer en Molenhof Beheer 5
(extra 01011 resp. 01012). Alle overige 69 RLZ-administraties: precies 0101/0107/0111/0113.

Sync-log `rlz-sync-dwfpj` (534 regels): 0 regels mét activa/FixedAsset/register — `probe_register` en `ververs_rlz_grens` loggen alleen bij een fout, de
DB-stand hierboven is het bewijs. **Observatie:** de run duurde 79,5 min (05:00:03–06:19:37 UTC; jobtimeout 5400 s = 90 min) tegen 44–47 min op
19/20/21-09. Tijdgaten > 2 min in het log: groepssaldi 2033 s (de `Status`-enumfout, gefixt 22-09 — verwacht weg ná de sync van 23-09), bank-sync
1194 s, projectcijfers 1188 s (Universal Steigerbouw 3072 documenten). De activa-stap (grens + probe per administratie) kostte seconden
(05:00:35 → 05:01:50 over 75 administraties, verweven met de ledgers-sync). Geen systeemfout in de sync → geen fix nodig; de timeout-marge (10 min)
verdient een blik als de groepssaldi-fix op 23-09 niet doorwerkt.

## Stap 2 — reconciliatieblok `activa` (lees-only)

`NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen activa --lees-only` (job `rlz-reconciliatie` op `ba2e231`, 10:17 UTC,
impersonatie `nameting@`). Slotregel:

```
activa-reconciliatie: 75 administratie(s) mét MVA-rekeningen getoetst, 22 afwijking(en) — activa_register_niet_leesbaar 2,
mva_boeking_zonder_activum 0, activum_zonder_boeking 19, afschrijving_niet_gelopen 1, activum_aanmaken_mislukt 0
LEES-ONLY afgerond — niets vastgelegd.   (exit 1 = afwijkingen aanwezig, bedoeld)
```

| soort | n | stand (`soort_stand.py`) | oordeel |
|---|---|---|---|
| `activa_register_niet_leesbaar` | 2 | meten | Universal Steigerbouw B.V., Rubicon Investments B.V. — klikpunt RLZ-recht "Vaste activa" |
| `activum_zonder_boeking` | 19 | meten | Pilates Bloom 11, Mantelzorgwoningen Midden Nederland 4, Zilver Beheer 4 — alle 2026-activa zijn buiten de module geboekt (verwacht: de MVA-regel in de module bestond nog niet) |
| `afschrijving_niet_gelopen` | 1 | meten | Beauty by Tessa Elst — RLZ's eigen `CurrentDepreciationValue` 0 ná > 12 mnd |
| `mva_boeking_zonder_activum` | 0 | meten | consistent met stap 3 (geen module-regel op een MVA-rekening ≥ grens) |
| `activum_aanmaken_mislukt` | 0 | meten | `activum_koppeling` leeg |

Explosie-rem: élke soort < 50. Odoo: 3 × "OVERGESLAGEN … Odoo-administratie — activa-aansluiting is in fase 1 RLZ-only". 0 × FOUT (élke RLZ-administratie
mét MVA-rekeningen had een credential; 403 is een afwijking, geen fout). Geen actiemail (alles `meten`, en lees-only legt niets vast).

Eerste tien bevindingen (administratie · tekst):
1. Beauty by Tessa Elst · `afschrijving_niet_gelopen`: activum nr 2 'Superwitgoed 2025070629' (aanschaf 2025-07-03, boekwaarde € 557,85) — nog geen afschrijving geboekt
2. Mantelzorgwoningen Midden Nederland · `activum_zonder_boeking`: nr 15 'Inventaris Lusso 215879 Mantelzorg' € 3.596,40 (2026-02-16)
3. Mantelzorgwoningen Midden Nederland · nr 16 'Demo woning Lusso 260125 Mantelzorg' € 1.450,00 (2026-02-05)
4. Mantelzorgwoningen Midden Nederland · nr 17 'Apple Retail Netherlands B.V. BC85514716' € 1.796,70 (2026-06-12)
5. Mantelzorgwoningen Midden Nederland · nr 19 'apple' € 299,00 (2026-06-12)
6. Pilates Bloom B.V. · nr 10 'Dezou Deren Fitness Pilates Bank' € 2.109,00 (2026-01-19)
7. Pilates Bloom B.V. · nr 11 'JCL Project- en Woningonderhoud' € 2.510,00 (2026-01-21)
8. Pilates Bloom B.V. · nr 12 'JCL Project- en Woningonderhoud' € 1.875,00 (2026-02-02)
9. Pilates Bloom B.V. · nr 13 'JCL Project- en Woningonderhoud Vloer' € 4.029,00 (2026-02-02)
10. Pilates Bloom B.V. · nr 14 'Dimo Led lampen' € 550,00 (2026-02-03)

Overige: Pilates Bloom nr 16/17/18/20/21/22 (€ 4.035 / 1.095 / 2.165 / 1.048,79 / 582,34 / 578,75); Zilver Beheer nr 9 '' € 182,50, nr 10 'C.A.T. Control
Systems B.V 12600376' € 5.975,00, **nr 11 'Bouwadvies Oost Nederland B.V. 20260010' € 325.000,00 (2026-03-06)**, nr 13 'Hoveniersbedrijf H. Versteeg B.V.
BTW-BEDRAG' € 4.977,14; Universal Steigerbouw en Rubicon `activa_register_niet_leesbaar`. Opvallend voor de accountant: Zilver Beheer nr 9 zonder
omschrijving (€ 182,50 — onder de grens van € 450 en tóch een activum) en nr 13 mét "BTW-BEDRAG" in de naam — beide een blik waard in RLZ, geen module-actie.

**Échte run van 22-09:** de scheduler-run `e315ceae` (04:30–04:46 UTC, image `fb63be5`, 782 bevindingen vastgelegd) draaide het blok wél
("=== activa-reconciliatie ===") maar meldde "0 administratie(s) mét MVA-rekeningen getoetst" — logisch: de reconciliatie loopt 06:30 NL vóór de
`sync-alles` van 07:00 NL, en `is_activa` stond op dat moment nog overal op false (eerste vulling 05:00–05:02 UTC). De eerste échte run mét de 22
activa-bevindingen (als `nieuwe_afwijkingen` in `meten`, facet "in meting") is die van 23-09 04:30 UTC; `reconciliatie_bevinding` blok `activa` is
vandaag dus nog leeg — zelfde volgorde-effect als "geen stand" bij de groepssaldi-detector (regel 21-09). Geen fix nodig; de volgorde is bewust
(alle blokken toetsen live tegen RLZ vóór de sync).

### Bijvangst — de lees-only run schreef tóch (gefixt)

Ná de meting stond op de replica bij álle 75 RLZ-administraties `activa_instelling.register_geprobeerd_op` = 10:18–10:19 UTC (het sync-moment 05:01
was overschreven), terwijl de run "LEES-ONLY afgerond — niets vastgelegd" meldde. Oorzaak: `activa/reconciliatie.py::cli_blok` roept
`instelling.probe_register` aan, die onvoorwaardelijk `register_geprobeerd_op` (+ `register_leesbaar`/`register_fout`) schrijft en zo nodig een rij
aanmaakt. Geen dataschade (zelfde stand, ander tijdstip, `grens_rlz_gelezen_op` bewijst de sync nog), wél een gebroken belofte van het lees-only-
instrument (regel 19-09 "een lees-only nameting legt niets vast"). **Fix in deze run:** `probe_register(session, client, aid, *, schrijf=True)` —
`schrijf=False` doet alleen de GET (403 → False; andere fout → de opgeslagen stand leidend; geen `_rij_of_nieuw`, geen tijdstip); `cli_blok` geeft
`schrijf=verzamelaar is not None` (de échte run schrijft wél). Guards: `tests/activa/test_reconciliatie.py::test_lees_only_run_schrijft_de_probe_stand_niet`
(lees-only 403-run → stand blijft `None`/`None`; tegenproef échte run → `False` + tijdstip) en `tests/activa/test_instelling.py::
test_probe_zonder_schrijven_raakt_de_instelling_niet` (ook geen nieuwe rij). Meetlat ná deploy: querybibliotheek **`db-lezen activa-stand`** (nieuw,
scope administratie: rijen `is_activa_rekening` / `instelling` / `register_probe` / `koppeling`; live getoetst op de replica voor Pilates Bloom: 6 rijen)
— ná een lees-only run blijft `register_probe.tijdstip` het sync-moment; vervolg-opdracht
`opdrachten/inbox/2026-09-23-nameting-activa-lees-only-probe-na-deploy.md` (`niet vóór: 2026-09-23 09:00`).

## Stap 3 — kaart in productie (klikpunt)

Request-log service `rlz-backend` sinds 21-09 13:36 UTC, URL bevat "activa":

| tijdstip (UTC) | administratie | route | status | duur |
|---|---|---|---|---|
| 21-09 15:27:43 | Administratiekantoor Nijenhuis C.V. | `GET …/activa-voorstel` | 200 | 0,43 s |
| 21-09 15:38:19 / 15:38:32 | Recreatief Vastgoed Nederland (Odoo) | `GET …/activa-voorstel` | 200 / 200 | 0,30 / 0,15 s |
| 21-09 15:38:58 | Recreapi B.V. | `GET …/activa-voorstel` | 200 | 0,44 s |
| 22-09 07:35:24 | Kempen Facilities B.V. | `GET …/activa-voorstel` | 200 | 0,45 s |
| 22-09 08:21:39 | Bonte Hoeve B.V. (Odoo) | `GET …/activa-voorstel` | 200 | 0,52 s |
| 22-09 08:28:39 | Universal Steigerbouw B.V. | `GET …/activa-voorstel` | 200 | 0,37 s |
| 22-09 08:52:55 | Bouwadvies Oost Nederland B.V. | `GET …/activa-voorstel` | 200 | 0,47 s |

8 × 200, 0 × 5xx, 0 × `POST …/aanmaken` of `…/overslaan`, 0 × `GET/PUT …/activa-instelling`. De route draait dus op élk geopend controlescherm (ook Odoo:
leeg voorstel, geen crash — de fail-safe van 21-09 werkt). **De kaart zelf: niet gemeten.** Pilates Bloom B.V. heeft in de module géén document (welke
status ook) mét een boekvoorstelregel op een `is_activa`-rekening (replica-query over `boekvoorstel_regel` × `grootboekrekening.is_activa`: 0 rijen);
`activum_koppeling` = 0 rijen. Geen zo'n factuur → geen kaart om te zien. Klikpunt Peter: één inkoopfactuur ≥ € 450 op 0107/0111/0113 bij Pilates Bloom
uploaden → kaart "Activum aanmaken?" → "Aanmaken ná boeken" → boeken → `activum_koppeling` `aangemaakt` + `rlz_fixed_asset_id`; meetlat `db-lezen
activa-stand --administratie 'Pilates Bloom'` rij `koppeling` (in de vervolg-opdracht van 23-09 als stap 4).

## Stap 4 — BUA (lees-only, dispatch-onderdeel `bua-kandidaten`)

`gh workflow run nameting -f onderdeel=bua-kandidaten` om 10:17 UTC → run 35715207462 wachtte in de concurrency-groep `nameting-production` achter de
dagelijkse `alles`-run (35714309386, 10:08–11:50 UTC) en liep daarna groen (job `rlz-reconciliatie` op `ba2e231`, `bua-kandidaten --jaar 2026 --detail`,
exit 0). Bot-commit `922eb28` op main: `verkenning/nameting-bua-kandidaten-22-09.txt` (311 regels; in deze run gemerged mét `--no-ff`).

| code | rekening | administraties | kenmerk aan | RLZ-/hist.-default | module 2026 | bank-direct | advies | = 21-09? |
|---|---|---|---|---|---|---|---|---|
| 4014 | Kantinekosten | 74 | 0 | geen | 0 | 0 | beoordelen | ja |
| 4503 | Kosten promotie/sponsoring | 74 | 0 | geen | 0 | 0 | niet_zetten | ja |
| 4508 | Relatiegeschenken (beperkt aftrekbaar) | 75 | 0 | geen | 0 | 0 | zetten | ja |
| 4510 | Representatiekosten (beperkt aftrekbaar) | 74 | 0 | geen | 2 regels, netto € 34,45, btw € 0,00 (T&J Hoveniers) | **1 regel, netto −260,00, btw 0,00 (Administratiekantoor Nijenhuis C.V.)** | zetten | ja (bank = bijvangst) |

Oordeelregel (letterlijk): `TOTAAL 297 kandidaat-rekening(en) in 75 van 78 administratie(s) · 0 mét kenmerk aan · advies zetten: 149 · module 2 regel(s)
netto 34.45 btw 0.00 · bank 1 regel(s) · 0 fout(en)` + `RLZ-kant niet gemeten (lees-only, geen RLZ-call)`. De replica-meting van 21-09 is exact bevestigd;
de drie administraties zonder BUA-rekening zijn de Odoo-administraties (Bonte Hoeve, Camping "Nieuwenhoven", Recreatief Vastgoed Nederland — Odoo-
rekeningschema zonder de RLZ-standaardnamen). Bijvangst: de bank-kolom (die de replica-meting van 21-09 niet had) toont één geboekte bank-direct-boeking
op 4510 bij Nijenhuis C.V. mét negatief netto (creditering/terugboeking, btw al 0) — verandert het bulk-advies niet.

`bua-kenmerk-zetten` is NIET gedraaid (ook niet `--dry-run`) — wacht op Peters "ja" op het rapport van 21-09.

## Keuzes (Peter kijkt niet mee)

1. **Stap 1 via `db_lezen.sh` per administratie i.p.v. het `query`-onderdeel:** er bestond geen bibliotheek-query voor `activa_instelling` en het
   `query`-onderdeel is één administratie per dispatch; 78 dispatches × ~2 min is geen meting. De replica-loop (80 × ~1,5 s) leverde het hele beeld. De
   query `activa-stand` is nu wél gebouwd zodat de vervolg-meting via de workflow als bot-bestand op main komt (regel 21-09).
2. **Stap 2 lokaal (`NAMETING_VIA_GH=0`) i.p.v. het `reconciliatie`-onderdeel:** dat onderdeel draait álle blokken (~15 min) en het bewijs moest per blok
   `activa`; de gcloud-sessie gaf een geldig token. De ruwe uitvoer staat in dit rapport (geen bot-bestand).
3. **Bijvangst-fix in dezelfde run** (probe schrijft in lees-only): klein, geïsoleerd (twee bestanden, twee guards), raakt geen geldpad en herstelt de
   belofte van het lees-only-instrument; de 22 bevindingen zelf zijn ongewijzigd. Alternatief (alleen melden) zou de volgende lees-only nameting weer laten
   schrijven.
4. **Geen WAT_IS_NIEUW-regel:** de fix raakt een intern meetinstrument, niet iets wat een klant of medewerker ziet.
5. **Sync-duur 79 min niet als systeemfout aangemerkt:** de oorzaak (groepssaldi 34 min) is de al gefixte `Status`-enumfout van 22-09; de activa-stap is
   niet de veroorzaker. Wél als observatie vastgelegd (timeout-marge 10 min).
6. **BUA-stap via `gh workflow run` (bot-bestand op main)** zoals het bouwrapport voorschrijft; de run wachtte in de concurrency-groep achter de
   dagelijkse `alles`-run van 10:08 UTC.

## Klikpunten Peter

- RLZ-recht "Vaste activa" op de webservice-logins van **Universal Steigerbouw B.V.** en **Rubicon Investments B.V.** (2 × `activa_register_niet_leesbaar`).
- Eén inkoopfactuur ≥ € 450 op 0107/0111/0113 bij Pilates Bloom uploaden en de kaart "Activum aanmaken?" doorlopen (stap 3).
- "ja" op het BUA-bulk-voorstel (4508 + 4510 kantoorbreed) → `gcloud run jobs execute rlz-reconciliatie --region europe-west4 --args="^|^-m|app.cli|bua-kenmerk-zetten|--alles|--dry-run"`, daarna zonder `--dry-run`.

## Poort

Poging 1 (10:10–12:59 UTC) haalde de poort niet: de run eindigde terwijl de volledige suite nog liep (73 %), het werk ging als WIP-commit
`afb18ea` op branch `wip/2026-09-22-nameting-activa-fase1-en-bua-kandidaten-na-deploy` (13 bestanden; blijft ter controle staan). Poging 2 begon met
`git merge --squash` van die branch (één conflict: de INDEX-regel, opgelost mét deze regel bovenaan) en draaide de volledige poort — alles groen:

| leg | uitkomst |
|---|---|
| pytest volledige suite (`backend/`, incl. `tests/keten`) | **7143 passed, 2 skipped, 21 deselected, 0 failed** (2:25:53 — traag door een verweesde pytest van een andere sessie op dezelfde Mac) |
| gerichte set + guards (`tests/activa`, `tests/lezen`, rapporten-index/gelezen-regels/klikpunten, claude_md-verwijzingen, regels-index, nameting-workflow) | 173 passed |
| `tsc -b` (frontend) | exit 0 |
| vitest | 248 bestanden, **1909 passed** (44 s) |
| gouden set `keten_sweep.sh` | **11/11 gelijk**, 0 nieuwe baselines |

Isolatie: bij de start draaide een verweesde `pytest tests --ignore=tests/keten` (pid 28339, ppid 1, 88 min oud, gestart 16:25 NL door een andere
sessie) op de gedeelde `boekhouding_test`; de eerste gerichte run gaf daardoor een fantoom-`IntegrityError` op `grootboekrekening`. Niet gekilld
(andermans proces), maar geïsoleerd op eigen databases `boekhouding_test_inbox2` (suite) en `boekhouding_test_guards2` (guards) — regel uit de memory
"parallelle sessie → eigen test-DB". Geen migratie in deze run, dus geen schema-dump. Ongecommit vreemd werk in `opdrachten/` (inbox
`2026-09-22-ter-accordering-…`, `2026-09-23-nameting-ter-accordering-…`, mislukt `2026-09-21-vastly-odoo-arvum-…`) is van andere runs en blijft staan.

## Gelezen regels
Volledig gelezen vóór de start van poging 2 (LEESPLICHT; poging 1 las dezelfde vier bestanden op de stand vóór de run: 37/196/226/260 regels):
- `docs/regels/activa.md` (56 regels — incl. de alinea van deze run)
- `docs/regels/btw.md` (206 regels — incl. de alinea van deze run)
- `docs/regels/reconciliatie.md` (238 regels)
- `docs/regels/werkloop-productie.md` (294 regels)
