# Rapport 17-09 (SPOED, inbox-run) — "Mogelijk dubbel betaald": 1.214 valse bevindingen → herdefinitie (betaling zonder factuur), bevindingssoorten starten in `meten`, explosie-rem

Opdracht: `opdrachten/gedaan/2026-09-17-SPOED-dubbele-betaling-1214-valse-bevindingen.md`. Geen RLZ-/Odoo-writes; migratie 0153
(afsluitroutine gedaan). **Werkt in productie: niet gemeten** — de herdefinitie draait pas in de eerste reconciliatie-run ná de deploy
(scheduler 18-09 of `nameting.sh reconciliatie-alles --alleen bank --lees-only`); meetrecept onderaan.

## Lees-only vooraf — wat er op 17-09 matchte (bron: `verkenning/nameting-reconciliatie-17-09.txt`, nameting-bot `d41dbdc`, run 35203722570 via `gh workflow run nameting -f onderdeel=reconciliatie`)

| Teller | Uitkomst |
|---|---|
| Bevindingen `dubbele_betaling_vermoed` | **1.214** over **67 administraties** (481 unieke tegenpartijen) |
| Aantal betalingen per bevinding | twee 682 · drie 153 · vier 99 · vijf 45 · acht 41 · zes 39 · zeven 35 · negen 30 · tien 15 · > 10: 83 (tot 56 betalingen in één cluster) |
| Zelfde-dag-"dubbels" (batch/deelleveringen, bv. 12 chalets) | 356 |
| Top-5 administraties (id; namen staan niet in de CLI-uitvoer) | `3ee6edf0…` 125 · `36dade86…` 118 · `66e1e296…` 104 · `cc07e461…` 77 · `55159e49…` 72 |
| Top-10 tegenpartijen | KEMPEN FACILITIES B.V. 78 (intercompany-doorbelasting) · Belastingdienst 106 (71 + 35, periodiek) · Administratiekantoor Nijenhuis 35 (periodiek) · FLOOR BOUWLIFTENSERVICE 31 (batch) · LUSSO-DESIGN 22 (batch, 12 chalets) · SPOT SERVICES 22 · Exact Software 25 (15 + 10, abonnement) · KPN Mobiel 12 · ALLROUND RENT 12 · WIJERS BEHEER 11 |

Conclusie uit de data: nul van de top-10 is een dubbele betaling — het zijn periodieke betalingen (belasting, abonnementen, het eigen
kantoor), intercompany-doorbelastingen met vaste bedragen en batches van gelijke facturen op één dag. De regel van 16-09 kende geen
factuurtoets en de periodiek-uitsluiting via `classificeer_reeks` (gebouwd voor "staande goedkeuring": twee ≤ 30 d = BATCH) liet vrijwel
alles door.

## Gedaan

**Blok A — mail stil, bestaande bevindingen sluiten.** `dubbele_betaling_vermoed` staat in stand `meten` (blok C) → nooit meer in de
actiemail. Bevindingen zijn per run; de eerste run ná deploy produceert de 1.214 niet meer en `run.py::_audit_verdwenen_dubbele_betaling`
schrijft per administratie één audit `reconciliatie_auto_gesloten` (aantal, vingerafdrukken, reden "herdefinitie 17-09 — valse
positieven (periodiek / betaling mét factuur)"); de systeemmail toont ze onder "Hersteld". Geen mens-klik.

**Blok B — herdefinitie (`app/bank/dubbele_betaling.py`).** Dubbel betaald = méér betaald dan er aan facturen tegenover staat:
periodiek (week…jaar-patroon ±35 %, `classificeer_reeks` PERIODIEK, incasso-/terugkerend-tegenpartij) = nooit; factuurtoets ± 30 d uit
drie eigen caches (module-documenten via `leverancier_iban`, RLZ-open-postencache via `bank_relatie_iban` incl. betaald/verdwenen,
RLZ-koppelingen van de mutaties) mét deduplicatie; betalingen > facturen → bevinding mét de gevonden facturen, mutatie-ids,
`bank_toets: bevestigd` en `sterk` (één betaling zonder RLZ-document naast een gekoppelde); crediteur in geen enkele cache = geen
uitspraak (geteld). Handeling: "Factuur ontbreekt (verwijderd of nooit geboekt): … vorder terug óf boek de factuur alsnog; bewust =
accepteer met reden". Casussen als tests: Hello Kitchen (2/1 → bevinding), Google Cloud (2/2 → niets), maandreeks (periodiek),
week/kwartaal, incasso, onbekende crediteur, sterk-signaal, dedup uit drie bronnen, DB-variant zonder RLZ-client. Gouden-set aa groen.

**Blok C — structurele guard (`app/reconciliatie/soort_stand.py`, migratie 0153).** Registry van álle 35 bevindingssoorten (guard:
elke soort mét tekst staat erin); soorten van vóór 17-09 = `actie`, nieuwe soorten en `dubbele_betaling_vermoed` = `meten`; onbekend =
`meten`. `meten` telt (blokstand, systeemrapport, facet **"in meting"** + chip op Inzicht › Reconciliatie) maar nooit actiemail/KPI.
Promotie: Beheerder `PUT /reconciliatie/instelling/soort-stand` of CLI `bevindingssoort-stand <soort> --stand actie --reden …`
(zonder `--stand` lees-only in de nameting-allowlist), audit oud→nieuw. Explosie-rem: > 50 afwijkingen van één soort in één run →
terug naar `meten` + LET-OP `bevindingssoort_explodeert` (regressie-categorie → systeemmail + audit `automatisering_regressie` +
bewaking). Actiemail: ≤ 3 regels per administratie, ≤ 10 totaal, afkap "en N andere (A 27, B 2)". Titels "Automatisering wacht op
voorwaarde"/"Automatisering stil" → "Wacht op instelling"/"Stil sinds zeven dagen" (actiemail-guard).

## Migratie 0153 (afsluitroutine)
`alembic upgrade head` dev-DB: `Running upgrade 0152 -> 0153` · `alembic check`: "No new upgrade operations detected" · live op uvicorn
8012: `GET /reconciliatie/instelling` 200 mét `soort_standen` (35 soorten), `PUT …/soort-stand` ongeldig soort → 422 ·
`scripts/dump_schema.sh` ververst (head 0153).

## Tests
`tests/reconciliatie/test_soort_stand.py` 11 · `tests/bank/test_dubbele_betaling.py` 20 (herschreven) · `test_teksten.py` +1 ·
`test_actiemail_guard.py` aangepast (per-administratie-cap) · `test_automatiseringen.py` titels · frontend `reconciliatie` 43 groen,
`tsc -b` groen · regressie tests/reconciliatie + tests/bank + tests/keten + guards: zie slotregel hieronder.

## Klikpunten Peter
Geen. De 1.214 bevindingen verdwijnen automatisch bij de eerste run ná deploy; promotie van de soort is pas aan de orde ná de meting.

## Beslispunten (default gekozen — `docs/rapporten/2026-09-17-beslispunten-peter.md` opdracht 2)
Onbekende crediteur = geen uitspraak; factuurbronnen = eigen caches (geen live RLZ-call); JSONB-kolom op de singleton; titels hernoemd;
geen promotie vóór de meting.

## Meetrecept (werkt in productie: ja/nee)
1. Ná deploy: `scripts/gcp/nameting.sh reconciliatie-alles --alleen bank --lees-only` (of `gh workflow run nameting -f onderdeel=reconciliatie`)
   → verwachting: Kempen Facilities → Hello Kitchen Duiven wél; Google Cloud, Insify, Greenchoice, Ziton, Belastingdienst, Nijenhuis níét;
   totaal ≪ 50.
2. Scheduler-run 18-09: actiemail zonder "Mogelijk dubbel betaald"; systeemmail "Hersteld — N afwijkingen niet meer gezien" + audit
   `reconciliatie_auto_gesloten` per administratie (67 verwacht).
3. `scripts/gcp/nameting.sh bevindingssoort-stand` → `dubbele_betaling_vermoed … meten`; Inzicht › Reconciliatie facet "in meting".
4. Pas daarna (Peter): promotie via Instellingen of `bevindingssoort-stand dubbele_betaling_vermoed --stand actie --reden "<meting>"`.
