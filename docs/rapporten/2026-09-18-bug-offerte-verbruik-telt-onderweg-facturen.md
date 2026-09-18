# BUG offerte-match 18-09 — verbruik telt nu ook facturen mee die nog in de accordering zitten ("hij moet wel doortellen")

**Opdracht:** `opdrachten/gedaan/2026-09-18-BUG-offerte-verbruik-telt-onderweg-facturen-niet.md` (Peter 18-09 20:04, accordeur-app,
Bouwadvies Oost Nederland, offerte "zonder nummer" € 1.192.922,50).
**Status:** GEBOUWD + GETEST 18-09; migratie 0166 (index). **Werkt in productie: niet gemeten** — deploy volgt via de Stop-hook ná
deze run; de nazorg (stale matchrijen herberekenen) en de nameting staan als vervolg-opdracht in de inbox
(`opdrachten/inbox/2026-09-18-offerte-verbruik-onderweg-nameting.md`). De NULMETING van de casus ís gedaan op de leesreplica (§Nulmeting).
**BESLISSINGEN:** "OFFERTE-VERBRUIK = GEBOEKT + ONDERWEG (Peter 18-09)".

## Wat er mis was
`verplichting/match_pipeline.py::verreken_in_sessie` schreef het verbruik van een gematchte factuur pas bij GEBOEKT op de
verplichting; `match.py::Kandidaat.verbruikt_bedrag_excl` telde dus alleen geboekt (CONTRACT_B-besluit 04-09, bewust: "een open
factuur mag een tweede niet ten onrechte buiten maken"). Een factuur die ter accordering staat (drie lagen = dagen tot weken) telde
nergens mee, zodat twee facturen tegelijk "binnen offerte" waren terwijl de som erbuiten viel. Peter zag het live: 32949 (€ 50.000)
zei "€ 50.000,00 van € 1.192.922,50" terwijl 32948 (€ 20.000) net door hem geaccordeerd was.

## Wat er gebouwd is
| # | Regel (opdracht) | Bouw |
|---|---|---|
| 1 | Verbruik = geboekt + onderweg; boekstand ongewijzigd; onderweg per toets, nooit opgeslagen | `match.py`: `Kandidaat.onderweg_bedrag_excl/onderweg_aantal/onderweg_ter_accordering`, `_beoordeel` toetst op geboekt + onderweg + eigen, `details` draagt `verbruik_geboekt`/`verbruik_onderweg`/`onderweg_aantal`/`onderweg_ter_accordering`, `onderweg_tekst()` = de zin "waarvan € X nog niet geboekt (N facturen ter accordering/in behandeling)". `match_pipeline.py`: `ONDERWEG_UITGESLOTEN_STATUSSEN` (terminaal + geboekt), `telt_als_onderweg`, `onderweg_per_verplichting` (één groepsquery, `verrekend_op IS NULL`, eigen document uitgezonderd), `lopende_kandidaten` vult de velden; termijntelling telt alleen niet-terminale facturen. `verreken_in_sessie`/`draai_verbruik_terug_in_sessie` ongewijzigd. |
| 2 | Toets + tekst + balk, zelfde DTO voor accordeur-app en controlescherm | Backend: `MatchData`/`VerplichtingMatchDto`/`OfferteMatchKortDto` (verplichting + accordering) dragen `termijn`, `verbruik_geboekt`, `verbruik_onderweg`, `onderweg_aantal`, `onderweg_ter_accordering`. Frontend: `OfferteMatchMelding.tsx` ("… van … · waarvan … nog niet geboekt (…)", `termijn`), `GoedkeurenFlow.tsx::OfferteMelding` + `OfferteBalk` (zelfde zin, "(2e termijn)"), `VerbruiksBalk.tsx` drie segmenten (geboekt vol, onderweg gearceerd, eigen gemarkeerd; `labelBedrag` = cumulatief ná deze factuur), pure helpers `verplichting/verbruikPresentatie.ts` (`verbruikSegmenten`, `onderwegTekst` — zonder API-imports zodat de accordeur-chunk ze mag laden), CSS `.balk > span.onderweg/.eigen` in `components.css` en `accordeur.css`. |
| 3 | Herberekening bij statuswissel mét tijdlijnregel, nooit stil | `documenten/service.py::_schrijf_overgang` → `match_pipeline.registreer_statuswissel` (alleen als `telt_als_onderweg(van) != telt_als_onderweg(naar)` én een binnen/buiten-match) → `after_commit` op die sessie → `herbereken_na_statuswissel`: andere open documenten op dezelfde verplichting opnieuw via `bereken_match`; verandert uitkomst of verbruik-ná → `DocumentGebeurtenis` "offerte-toets herberekend: buiten → binnen — … (aanleiding: factuur ‹ref› afgewezen (was te controleren))" + audit `verplichting_match_herberekend` (systeem-actor). Fouten gelogd, nooit blokkerend. |
| 4 | Kantoorbreed + detail: drie getallen geboekt / onderweg / restant | `service.py::bereken_verbruik_stand` (puur, één bron) → `VerbruikStand`/`VerbruikDto`/`KantoorRijDto`: `onderweg_excl`, `onderweg_aantal`, `onderweg_ter_accordering`, `restant_excl`, `percentage` (geboekt + onderweg), `percentage_geboekt`; `open_facturen_*` gelijk gehouden. `kantoorbreed.py`: status "overschreden" = geboekt + onderweg > totaal. Frontend `VerplichtingenScreen`/`VerplichtingReviewScreen`: balk mét onderweg + regel "geboekt … · onderweg … · restant …". |
| 5 | Index (opdracht: "bestaat?") — nee | Migratie **0166** `ix_verplichting_match_administratie_verplichting (administratie_id, verplichting_document_id)`; model-index in `models.py`. |
| 6 | Nazorg stale matchrijen (niet in de opdracht, wél nodig — zie §Nulmeting) | CLI `verplichting-match-herberekenen [--administratie] [--dry-run]` (`app/verplichting/cli_cmd.py`, geregistreerd in `app/cli.py`; schrijvend, niet in de nameting-allowlist). |

## Keuzes zonder Peter (opdracht: zelf kiezen, vastleggen)
1. **Beide open facturen "buiten" zodra de som erbuiten valt.** De regel zegt letterlijk "binnen/buiten op (geboekt + onderweg + eigen
   bedrag) ≤ offertebedrag"; bij herberekening ziet elke factuur de ander als onderweg. Het alternatief (alleen de laatst getoetste
   vlaggen) zou de uitkomst van de volgorde laten afhangen. Buiten blijft niet-blokkerend; de zin "waarvan … nog niet geboekt" legt uit.
2. **Termijntelling** sluit afgewezen/verwijderde facturen uit (was: élke matchrij) — een afgewezen factuur is geen termijn.
3. **Tijdlijnregel alleen bij een échte verandering** van uitkomst of verbruik-ná: te_controleren → klaar_om_te_boeken → ter_accordering
   verandert niets aan onderweg en herberekent niets (geen ruis; test `test_statuswissel_binnen_onderweg_herberekent_niet`).
4. **"ter accordering" in de zin alleen als álle onderweg-facturen die status hebben**, anders "in behandeling" (eerlijk over gemengde
   stapels).
5. **Nazorg-CLI** toegevoegd: zonder trigger blijven productie-matchrijen op de oude stand (§Nulmeting toont dat 32949 dan "€ 50.000"
   zou blijven zeggen). Schrijvend, dus als job-executie ná deploy — vervolg-opdracht.
6. `open_facturen_*` (0.1) bleef als alias, zodat oudere lezers (projectdetail-paneel) niet breken; de semantiek is nu "telt mee".

## Nulmeting productie (leesreplica, lees-only, 18-09 20:50 — `scripts/gcp/db_lezen.sh … --als 2f2262cd… --administratie a265c010…`)
Bouwadvies Oost Nederland B.V. (`a265c010-91ee-4b72-a5d6-48ddb67652f4`), verplichting `34aaf45b` zonder nummer, goedgekeurd
€ 1.192.922,50, boekstand `verbruikt_bedrag_excl` 0,00. Matchrijen `binnen`, alle drie `ter_accordering`, `verbruik_voor` 0:

| factuur | referentie | bedrag excl. | berekend_op (UTC) |
|---|---|---|---|
| 269eef9d… | 32948 | 20.000,00 | 11:20 |
| d9b44b34… | 32949 | 50.000,00 | 18:03 |
| 8430932e… | 33122 | 80.000,00 | 18:04 |

Peters "70.000" gold op 20:04 NL, vóór 33122 een minuut later binnenkwam. **Verwacht ná deploy + `verplichting-match-herberekenen`:**
32949 → "€ 150.000,00 van € 1.192.922,50 · waarvan € 100.000,00 nog niet geboekt (2 facturen ter accordering)"; 32948 en 33122 idem
€ 150.000,00 (alle drie binnen). De tweede verplichting van Bouwadvies (2502090, geen goedgekeurd bedrag) heeft geen matches.

## Tests
- Backend nieuw: `tests/verplichting/test_match.py::TestOnderwegTeltMee` (5, puur: 20k onderweg + 50k op 1.192.922,50 → 70.000 binnen
  mét zin en details; 20k + 50k op 60k → buiten 10.000 over, zonder onderweg binnen; geboekt + onderweg 0 = bestaand gedrag;
  eigen_verrekend alleen van geboekt; `onderweg_tekst`). `tests/verplichting/test_verbruik.py`: `test_open_factuur_telt_mee_als_onderweg`
  (herschreven: 40k + 40k op 48.500 → buiten; reviewscherm onderweg 80.000 / restant −31.500 / 165 %), `TestOnderweg` (6: buiten mét
  termijn 2 + DTO's; afwijzen 20k → 30k binnen mét tijdlijnregel + audit `verplichting_match_herberekend` + termijn 1; statuswissel
  binnen onderweg herberekent niet; ter accordering = label + `onderweg_ter_accordering`; eigen document nooit dubbel; boeken van de
  eerste → tweede herberekend, zelfde verbruik, andere splitsing), `TestHerberekenCli` (dry-run schrijft niets, echt = 2 herberekend,
  1 gewijzigd). Gericht groen: `tests/verplichting` (41 + 21 + …), `tests/unit/test_migratie_metadata_guard.py`,
  `tests/accordering/test_wachtrij_querytelling.py` → 120 passed. **Volledige backend-suite (zonder keten): zie regel hieronder.**
- Frontend nieuw/aangepast: `verplichting/verbruikPresentatie.test.ts` (3), `OfferteMatchMelding.test.tsx` (+1: zin, segmenten,
  "€ 70.000,00 / € 1.192.922,50", termijn 2), `GoedkeurenFlow.verplichting.test.tsx` (+1: accordeur-kaart mét onderweg-zin en segmenten),
  `VerplichtingenScreen.test.tsx`/`VerplichtingReviewScreen.test.tsx`/`ProjectDetailVerrijking.test.tsx` (verwachting 0.1 "telt niet
  mee" → "telt mee" + drie getallen). `tsc -b` groen; volledige vitest-suite: 240 bestanden / 1853 tests groen ná de laatste aanpassing
  (de ene rode was de oude 0.1-verwachting in het projectdetail-paneel).
- Contrast-test ongewijzigd groen (geen nieuwe tokens; de arcering is een `background-image` over de standkleur).

**Suite-regel (ingevuld door de nameting-run 18-09 21:10 — de bugrun eindigde wachtend op de suite zónder te committen, zie
`docs/rapporten/2026-09-18-offerte-verbruik-onderweg-nameting-uitgesteld.md`):** de volledige backend-suite is NIET afgedraaid.
Gemeten: gouden set `tests/keten` (compleet) + `tests/verplichting` + migratie-metadata-guard + accordering-querytelling + docs-
guards = 290 passed; keten-guard eiste een tests/keten-aanraking → nieuwe casus `tests/keten/test_z_offerte_verbruik_onderweg.py`
(3, echte Bouwadvies-getallen: 150.000 / 70.000 / stale 50.000). `tsc -b` groen, vitest 7 bestanden / 53 tests groen, ruff:
alleen pre-existente E501's in HEAD.

## Migratie-afsluitroutine (0166)
1. `make migrate` tegen de dev-database `boekhouding`: `Running upgrade 0165 -> 0166` ✔.
2. Live 200: eigen uvicorn op 8011 (dev-DB), Beheerder-token via `create_access_token` → `GET /verplichtingen?pagina=1&status=alle`
   → **HTTP 200** mét de nieuwe `KantoorRijDto`-vorm (lege dev-lijst) ✔; uvicorn daarna gestopt.
3. `scripts/dump_schema.sh` vanuit de repo-root → `schema_referentie.sql` ververst vanaf `boekhouding_test` @ head 0166 ✔.

## Nameting (vervolg-opdracht, ná deploy)
Stap 0 deploy-check (service én jobs op de nieuwe sha, `Running upgrade 0165 -> 0166`); stap 1 `gcloud run jobs execute rlz-sync
--args="-m,app.cli,verplichting-match-herberekenen,--administratie,a265c010-91ee-4b72-a5d6-48ddb67652f4,--dry-run"` → verwacht 3
kandidaten; stap 2 zonder `--dry-run` → 3 herberekend, 3 gewijzigd; stap 3 leesreplica: matchrij 32949 `verbruik_na` 150000.00,
`details.verbruik_onderweg` 100000.00, `onderweg_aantal` 2; stap 4 accordeur-app (Peter of testaccount): kaart 32949 toont
"€ 150.000,00 van € 1.192.922,50 · waarvan € 100.000,00 nog niet geboekt (2 facturen ter accordering)". Rapportregel "werkt in
productie: ja/nee".

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (217 regels)
- `docs/regels/accordering-native-app.md` (361 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (297 regels)

## Bijgewerkt
`docs/regels/verplichtingen-projecten-voorraad.md` (alinea "Offerte-verbruik = geboekt + onderweg"), `docs/BESLISSINGEN.md` (nieuwe
sectie), `CLAUDE.md` (verwijsregel 5 onder Verplichtingen), `frontend/src/changelog/WAT_IS_NIEUW.md` ("Offertes tellen nu ook facturen
mee die nog in de goedkeuring zitten"), `backend/migrations/schema_referentie.sql` @ 0166, deze INDEX-regel, opdracht → gedaan,
vervolg-opdracht in de inbox.
