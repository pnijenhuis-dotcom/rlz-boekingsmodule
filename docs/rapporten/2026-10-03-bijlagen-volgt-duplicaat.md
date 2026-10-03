# Bijlage volgt het duplicaat naar het origineel — nazorg, live-pad en afvoer (BUG Peter 03-10, uitgevoerd 03-10-2026)

**Opdracht:** `opdrachten/gedaan/2026-10-03-bijlagen-nabundelen-volgt-duplicaat-naar-origineel.md` (Peter 03-10: "werkdetails zonder
factuur kan niet"). CC-inbox-run 03-10, geen bijvangst (regel Peter 30-09), niets schrijvends in productie vanuit CC. Geen migratie.
**Werkt in productie: niet gemeten** — de échte nazorgrun doet Peter via `opdrachten/terminal/2026-10-03-bijlagen-nabundelen-herhaling.md`
(dry-run Steigerbouw → échte run → kantoorbreed, ná deploy); de lees-only meetlat = nameting-opdracht
`opdrachten/inbox/2026-10-03-nameting-bijlagen-volgt-duplicaat.md` (`niet vóór:` deploy + 1 u, dispatch-onderdeel `bijlagen-factuur`).
BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)" subkop "Bijlage volgt het
duplicaat naar het origineel (03-10)"; regeltekst `docs/regels/intake-extractie.md` alinea 03-10; CLAUDE.md intake-blok punt 11.

## Samenvatting

De nazorg `bijlagen-nabundelen` liet op Universal Steigerbouw 7 bijlagen (`factuurdetails-….pdf`) los staan met "geen factuur-document in
deze mail", terwijl de factuur in élk van die mails zat — zes keer als `afgevoerd_duplicaat`, één keer als `afgewezen`. De code filterde die
statussen weg en gooide daarmee de kennis "deze bijlage hoort bij díe factuur" weg. Sinds deze run:

1. **Volg het duplicaat naar het origineel.** Nieuwe motor `app/documenten/bijlage_doel.py::volg_naar_origineel`: een afgevoerde of afgewezen
   factuur wordt gevolgd via (a) de afwijzing-kruisverwijzing `duplicaat_van_document_id`, (b) de vlag `mogelijk_duplicaat_van_id`,
   (c) hetzelfde factuurnummer (`boekvoorstel.referentie_norm`, precies één treffer) binnen dezelfde administratie. Een geboekt origineel is
   ook een doel (bijlage gaat dan als RLZ-upload mee — bestaand gedrag). Een doel dat zelf weer afgevoerd/afgewezen is wordt doorgevolgd
   (keten, max 5). Nooit raden, nooit buiten de administratie.
2. **Afgewezen factuur in de mail.** Tegenhanger mét hetzelfde factuurnummer gevonden → doel ("via afgewezen factuur → …"). Niet gevonden →
   de bijlage blijft los met uitkomst "factuur afgewezen (‹reden›) — bijlage ook afwijzen?", de échte run zet één idempotente
   tijdlijn-notitie op de bijlage en het controlescherm toont bovenin de chip "factuur uit dezelfde e-mail afgewezen" mét link naar de
   afgewezen factuur. Nooit automatisch afwijzen.
3. **Live-intakepad.** Een factuur die vóór de AI-stap als byte-identiek duplicaat wordt afgevoerd (of huls wordt) geeft het origineel als
   drager mee; de bijlagen uit die mail hangen aan het origineel, nooit aan het afgevoerde exemplaar. De referentie-afvoer ná extractie
   (`duplicaat_afvoer._voer_af`, automatisch én één-klik) verhuist bijlagen die al aan het duplicaat hingen naar het origineel.
4. **Dry-run-uitvoer.** "‹origineel› ← ‹bijlage› […]: kandidaat — via duplicaat → ‹origineel› — zou koppelen aan …"; de TOTAAL-regel
   draagt de teller "… N mislukt, K via duplicaat — …" (het vaste voorvoegsel voor de nameting-grep is ongewijzigd).
5. **Tests** op de drie bronnen, het afgewezen-pad zonder tegenhanger, verhuizen, live-pad, `_voer_af`, de CLI-vormen uit het
   meetrecept en de gouden set (casus ap uitgebreid; bestaande casussen ongewijzigd groen).

## Feiten (uit de opdracht; productie, leesreplica 03-10 ~10:55, scope Universal Steigerbouw `3ee6edf0-5cb8-4f98-bba1-16fb97ae6873`)

Échte run `bijlagen-nabundelen --uitvoeren --administratie "Universal Steigerbouw"` (executie `rlz-reconciliatie-z8dj8`): 94 e-mails,
24 gekoppeld, 0 mislukt, 7 × "overgeslagen — geen factuur-document in deze mail".

| Mail | Bijlage (los, te_controleren) | Factuur in dezelfde mail | Status factuur | Verwacht ná deze fix |
|---|---|---|---|---|
| Factuur RLZ-2080143044 (24-09) | factuurdetails-3445-2026-7.pdf | …3044 1-8-2026.pdf (gebundeld) + .xml | afgewezen (beide) | tegenhanger mét nummer 3044 → "via afgewezen factuur"; anders "bijlage ook afwijzen?" + chip |
| Factuur RLZ-2080143088 (28-09) | factuurdetails-3501-2026-8.pdf | …3088 19-8-2026.pdf | afgevoerd_duplicaat | kandidaat — via duplicaat → origineel |
| Factuur RLZ-2080143092 (28-09) | factuurdetails-3428-2026-7.pdf | …3092 21-8-2026.pdf | afgevoerd_duplicaat | idem |
| Factuur RLZ-2080143093 (28-09) | factuurdetails-3673-2026-7.pdf | …3093 21-8-2026.pdf | afgevoerd_duplicaat | idem |
| Factuur RLZ-2080143094 (28-09) | factuurdetails-3160-2026-7.pdf | …3094 21-8-2026.pdf | afgevoerd_duplicaat | idem |
| Factuur RLZ-2080143125 (28-09) | factuurdetails-3531-2026-7.pdf | …3125 28-8-2026.pdf | afgevoerd_duplicaat | idem |
| Factuur RLZ-2080143131 (28-09) | factuurdetails-3335-2026-7.pdf | …3131 31-8-2026.pdf | (afgekapt; zelfde patroon verwacht) | idem |

Is het origineel van een afgevoerd duplicaat alleen buiten de module (RLZ-geboekt, geen app-document), dan meldt de dry-run dat als
"afgevoerd als duplicaat zonder origineel in de module — …" (overgeslagen, zichtbaar). Dat is in de feiten hierboven niet te zien;
de dry-run ná deploy geeft uitsluitsel.

## Gebouwd — per bestand

| Bestand | Wat |
|---|---|
| `backend/app/documenten/bijlage_doel.py` (nieuw) | `volg_naar_origineel` (drie bronnen, keten, `Doel`/`GeenDoel` mét afwijsreden), `verhuis_bijlagen_naar_origineel` (+ `verhuis_na_afvoer`-haakje, audit `bijlage_naar_origineel`, tijdlijn beide kanten), `noteer_factuur_afgewezen` (idempotente notitie `bijlage_factuur_afgewezen`), `factuur_afgewezen_uit_tijdlijn` (DTO-bron). |
| `backend/app/intake/bijlagen_nabundelen.py` | `DocRef.via/via_document_id/samengevoegd_in_id/samenvoeg_rol`, `BijlageKandidaat.via_duplicaat/afgewezen_factuur/afwijs_reden/verhuizen_van`, `_doel_via_duplicaat`, `_geen_doel_kandidaat`, `_noteer_afgewezen`, `_verhuis_een`, teller `Telling.via_duplicaat` + TOTAAL-regel, `als_regel` mét "via duplicaat → …"; `_FACTUUR_UITGESLOTEN` = `bijlage_doel.UITGESLOTEN` (één bron). |
| `backend/app/intake/verwerking.py` | `BijlageResultaat.drager_document_id/-administratie_id/-bestandsnaam` (intern), `_dubbel_voor_ai` geeft het origineel als drager mee (sleutels uit zijn boekvoorstel via `_sleutels_van_document`), `_drager_van` + `_administratie_uit_resultaat` kennen `dubbel`, detail "— via duplicaat: …". |
| `backend/app/documenten/duplicaat_afvoer.py` | `_voer_af` roept ná `wijs_af` `bijlage_doel.verhuis_na_afvoer` aan. |
| `backend/app/documenten/schemas.py` + `router.py` | `FactuurAfgewezenInMailDto`, `DocumentDetailResponse.factuur_afgewezen_in_mail` (alleen op een open document). |
| `frontend/src/api/types.ts`, `document/DocumentDetailScreen.tsx` | DTO-type + chip "factuur uit dezelfde e-mail afgewezen" mét `Link` (via `documentPad`) náást de correctiebalk; `data-testid="factuur-afgewezen-in-mail"`. |
| `frontend/src/changelog/WAT_IS_NIEUW.md` | blok 2026-10-03. |
| Tests | `tests/documenten/test_bijlage_doel.py` (10), `tests/intake/test_bijlagen_bij_factuur.py::TestBijlageVolgtDuplicaatNaarOrigineel` (7), `tests/keten/test_ap_bijlagen_bij_factuur.py::TestBijlageVolgtDuplicaatNaarOrigineel` (1), vitest `DocumentDetailScreen.test.tsx` (+2). |

## Keuzes zonder Peter

- **"Hetzelfde factuurnummer" = `boekvoorstel.referentie_norm`** (de ENE normalisatie van 16-09, dezelfde vergelijkingsvorm als de
  duplicaatcheck). De opdracht noemde de `bh`-sleutels; twee normalisaties naast elkaar zouden een tweede waarheid zijn. Gevolg: een
  document zonder opgeslagen boekvoorstel (nooit geëxtraheerd) heeft geen factuurnummer en valt op bron 1/2 of "geen tegenhanger".
- **De afgewezen-notitie alleen in de échte run.** De dry-run blijft lees-only (nameting-allowlist); de chip verschijnt dus pas ná
  `--uitvoeren`.
- **Eén teller `via_duplicaat`** voor beide routes (afgevoerd duplicaat én afgewezen-mét-tegenhanger), zoals gevraagd; de regel zelf
  zegt welke van de twee.
- **Chip bovenin het controlescherm** (náást de correctiebalk) in plaats van alleen in de standaard ingeklapte tijdlijn — anders ziet de
  mens 'm niet.
- **Al-gekoppelde bijlagen verhuizen mee.** De opdracht vroeg het live-pad voor de byte-identieke route; de referentie-afvoer ná extractie
  (`_voer_af`) laat sinds 02-10 bijlagen aan het duplicaat hangen — dezelfde regel, dus hetzelfde haakje, en de nazorg vangt een gemiste
  verhuizing (verhuizen i.p.v. opnieuw koppelen). Geen nieuwe knop, geen instelling.

## Poort

- Backend gericht: `tests/documenten/test_bijlage_doel.py` + `tests/intake/test_bijlagen_bij_factuur.py` + `tests/keten/test_ap_bijlagen_bij_factuur.py`
  + `test_am_dubbel_voor_ai.py` + `tests/intake/test_dubbel_voor_ai.py` + `tests/documenten/test_duplicaat_afvoer.py`: 57 groen.
- Backend volledige suite (`pytest -q`, 03-10 11:40–12:38): **7974 passed, 0 failed**, 21 deselected (opt-in live-RLZ), 57:55 min.
- Frontend: vitest `DocumentDetailScreen.test.tsx` + `changelog` 61 groen; `tsc -b` groen.
- Doc-guards ná de documentatie (`test_claude_md_beslissingen_verwijzingen`, `test_regels_index`, `test_rapporten_index`, `test_rapporten_gelezen_regels`, `test_rapporten_klikpunten`, `test_keten_guard`, `test_nameting_workflow`, `test_cli_smoketest`, `test_export_deterministisch`): 135 groen.
- Keten-sweep (`frontend/scripts/keten_sweep.sh`): 13/13 groen, 0 nieuwe baselines.
- Gouden-set-exports (`frontend/src/dev/keten/*.json`): de detail-DTO draagt het nieuwe veld `factuur_afgewezen_in_mail: null` →
  exports gewild ververst door de keten-run (geen renderverschil; de chip verschijnt alleen bij een gevuld veld).

## Werkt in productie: niet gemeten

**Meetrecept (lees-only, dispatch-onderdeel `bijlagen-factuur` = `bijlagen-nabundelen --dry-run` kantoorbreed + `db-lezen documenten-open`
Universal Steigerbouw):** in het bot-bestand `verkenning/nameting-bijlagen-factuur-<dd-mm>.txt` de TOTAAL-regel mét de nieuwe teller
"… K via duplicaat" (K ≥ 6 zolang Peters échte run nog niet gedraaid heeft; ná die run 0 en de zeven `factuurdetails-….pdf` op
`samengevoegd` mét `samengevoegd_in_id` = het origineel) en per Steigerbouw-mail de regel "… kandidaat — via duplicaat → Factuur
RLZ-20801430xx …". Voor RLZ-2080143044: "via afgewezen factuur → …" óf "overgeslagen · factuur afgewezen (…) — bijlage ook afwijzen?".
Request-log ná de échte run: `GET …/documenten/<bijlage-id>` 200 op een losse bijlage mét `factuur_afgewezen_in_mail` ≠ null = chip
getoond.

**Klikpunten Peter:** (1) terminal-opdracht `opdrachten/terminal/2026-10-03-bijlagen-nabundelen-herhaling.md` ná deploy (machine kan dit
niet omdat: schrijvende nazorg = `gcloud run jobs execute` in de owner-sessie, regel 08-09); (2) de 3044-mail: als er geen tegenhanger
is, bewust beslissen of `factuurdetails-3445-2026-7.pdf` ook afgewezen wordt (de chip + link staan dan op dat document).

## Gelezen regels

- `docs/regels/intake-extractie.md` — 498 regels (vóór deze run)
- `docs/regels/werkvoorraad-controlescherm.md` — 777 regels
- `docs/regels/werkloop-productie.md` — 362 regels
- BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)" punt 1, "AI-LIMIET — …
  DUBBELENCHECK VÓÓR DE AI-STAP (Peter 24-09)" (C), "Afgehandelde documenten — één toggle (Peter 08-09)".
