# Planning: conflictenbalk → conflictenpaneel mét handeling, alleen vanaf vandaag, dubbele veldwerkers alleen op harde sleutels (21-09)

Opdracht `opdrachten/gedaan/2026-09-21-planning-conflictenbalk-onleesbaar-oude-week-dubbele-veldwerkers-zonder-handeling.md` (Peter
21-09, Universal Steigerbouw /planning: "17 conflicten deze week — ma 7-9: M. Demir op 25137 Bergeijk (van Stiphout) én 26082 Eindhoven
… ik kan er niet uithalen wat het conflict is"; correctie Peter 21-09: Ponchev/Panchev en de Demirs zijn broers in één ploeg, géén dubbele
records). Gebouwd + getest; migratie 0169; geen RLZ-write, geen AI. **Werkt in productie: niet gemeten** — de code deployt ná deze run;
meetrecept onderaan. Peter keek niet mee; keuzes staan in "Keuzes".

**Één regel voor Peter:** de balk is een paneel per dag geworden dat zegt wát het conflict is en er een knop bij zet ("Houd Bergeijk" /
"Houd Eindhoven" / "Beide (halve dagen)…" mét reden); het telt alleen vandaag en later (een dubbele planning van vorige week is historie),
zegt "deze week" alleen als dat zo is en toont bij een oude week de chip "verstreken week". Dubbele veldwerkers worden alleen nog op
KvK, IBAN of e-mail gezocht — nooit meer op gelijkende namen of dezelfde planning.

## Feit en oorzaak

| Probleem (opdracht) | Oorzaak in de code (gelezen) |
|---|---|
| 1. Onleesbaar, zegt niet wát het conflict is | `ConflictenBalk.tsx` zette élk conflict als `linkbtn` inline achter elkaar (`flex-wrap`), uitgeklapt één lap; de tekst was alleen `dagKort: naam op A én B` — de soort stond nergens. |
| 2. "deze week" maar week 37 | De week komt uit `?week=` (`parseWeekParam`), een bewuste deeplink vanuit het planning-signaal "geplande week zonder weekstaat" (`planningSignaalApi.ts:110`) en het projectdetail. Het grid deed dus wat de link vroeg; alleen de balk-tekst "deze week" was hard gecodeerd en `conflictenVoorWeek` kende geen "vandaag". |
| 3. "Dubbele veldwerkers" | Geen code-oorzaak: een leesfout op planningspatroon (zelfde projecten, zelfde dagen). Onderdeel C is daarom een lees-only detector op harde sleutels alleen. |
| 4. Signaal zonder handeling | Elk item had alleen `onSpring` (kaart oplichten). |

## Gebouwd

### A. Balk → paneel (`frontend/src/planning/ConflictenPaneel.tsx`, `dagEerst.ts`)

- Kop **"N conflicten in week 39"** — de getoonde week; **"deze week"** alleen als dat de huidige is (`conflictWeekLabel`).
- **Per dag gegroepeerd** (`groepeerConflictenPerDag`), per rij: dag · persoon · projecten · **soort** als oranje badge ("dubbel gepland" /
  "afwezig" / "> 5 op kaart" / "ZZP'er zonder dossier", `CONFLICT_SOORT_LABEL`) · **handeling**.
- Handelingen (Kernprincipe 7.2): dubbel → **"Houd ‹A›" / "Houd ‹B›"** (de andere kaart(en) van die persoon-dag weg via de bestaande
  bulkroute mét `verwijderen: true` en nieuwe bron `conflict`; audit `planning_verwijderd` mét `bron`; toast "Ongedaan maken" plaatst
  exact de verwijderde set terug via bron `ongedaan`) en **"Beide (halve dagen)…"** = dialoog mét verplichte reden →
  `POST /uren/kantoor/planning/conflict-akkoord`; afwezig → **"Van planning halen"** / **"Tóch plannen…"**; > 5 → **"Ploeg aanpassen"**
  (kaart + ploeg-paneel); dossier → **"Dossier openen →"** (`/veldwerkers`); élke rij óók "Toon in grid".
- Ingeklapt 3 rijen, "Alle N tonen" = tabel; de tabel staat **altijd** in `.tabel-scroll` (ook ingeklapt — de eerste sweep liep op
  768 px vast op de acties-kolom, zie "Poort"), acties-cel `flex-wrap`. Nooit blokkerend — kantoor beslist.
- Geen conflicten vanaf vandaag maar wél op verstreken dagen → één tekstregel "Geen conflicten deze week — N op verstreken dagen
  (historie, zie Per project)".

### A. Akkoord "bewust gehouden" (migratie 0169, `app/uren/planning.py::bevestig_conflict`, route `POST /uren/kantoor/planning/conflict-akkoord`)

- Tabel `boekhouding.planning_conflict_akkoord`: persoon × dag × soort (`dubbel` | `afwezig`), `project_ids` JSONB = de gesorteerde
  project-id's (planningsstand) op het moment van het akkoord, `reden` (≥ 3 tekens, CHECK), aangemaakt_door/op. RLS FORCE op
  administratie, grants SELECT/INSERT/UPDATE — geen DELETE (historie, niets verdwijnt stil).
- `halve_dagen=true` (dubbel): álle kaartjes van die persoon × dag → dagdeel `half`, audit `planning_dagdeel_gezet` mét
  `bron: conflict_akkoord` per kaartje; daarna de akkoord-rij mét de stand NÁ de wijziging + audit `planning_conflict_akkoord`.
- **De rij verdwijnt tot de planning wijzigt:** `zonderAkkoord` (frontend) verbergt een dubbel-/afwezig-conflict alleen zolang de huidige
  stand exact gelijk is aan `project_ids` van een akkoord van dezelfde soort; een extra of verdwenen kaart maakt het weer zichtbaar.
- Idempotent: dezelfde stand nog eens = dezelfde rij terug, geen tweede audit. 404 zonder planning die dag; 422 zonder dubbele
  planning bij soort `dubbel`, zonder reden of onbekende soort. `PlanningWeekDto.conflict_akkoorden` (leesroute).
- Bulkroute: `BULK_BRONNEN += conflict` (backend + `PlanningBulkBron`).

### B. Alleen huidige + toekomstige dagen; weeklabel; weekchip

- `conflictenVanaf(conflicten, vandaag)` → paneel toont alleen conflicten met datum ≥ vandaag; kaart-chips en "Per project" tonen
  álle conflicten (historie blijft leesbaar). Teller "N op verstreken dagen niet getoond".
- Subkop krijgt de chip **"verstreken week"** (grijs) / **"lopende week"** (info) — `weekStand(vrijdag, maandag, vandaag)`. De laatst
  bekeken week wordt niet buiten de URL onthouden: `?week=` blijft de bron (deelbaar, deeplink-doel).

### C. Dubbele veldwerkers — lees-only CLI `veldwerkers-dubbelen` (`app/uren/dubbelen.py`, `dubbelen_cli.py`)

- Per administratie de veldwerkers mét scope (ZZP'er/uitvoerder/detacheerder); harde sleutels: **KvK** (`veldwerker_dossier.kvk_nummer`),
  **IBAN** (via `veldwerker_crediteur.vendor_id` → `leverancier_iban`, genormaliseerd), **e-mail** (`gebruiker.e_mail`, lower/trim — de
  kolom is uniek, dus in de praktijk 0; de toets staat er tegen een import/pseudonimisering die dat ooit doorbreekt); **telefoon** =
  "niet toetsbaar" (geen veld op `platform.gebruiker`; alleen `materiaal.leverancier` heeft er een) — zichtbaar gemeld, nooit stil.
- ≥ 2 personen mét dezelfde waarde = KANDIDAAT (beoordelen); geen samenvoegen, geen UI-chip. Naam-afstand/planningspatroon komen in
  de code niet voor (guard `test_puur_alleen_harde_sleutels_nooit_naam`: broers Demir = 0, identieke naam mét eigen KvK = 0).
- Set-based (4 statements per administratie), één kapotte administratie stopt de rest niet (exit 1 mét FOUT-regel). Opgenomen in
  `scripts/gcp/nameting.sh` (allowlist + `via_gh_onderdeel`) en als dispatch-onderdeel `veldwerkers-dubbelen` in `nameting.yml`
  (oordeelregel = TOTAAL-regel; niet in "alles").

### Mockup / UX-review

`mockup/planning-v3-dag-eerst.html`: het balk-voorbeeld is vervangen door het paneel (tabel per dag mét soort + handelingen) en de
notitie "Conflictenbalk" beschrijft het paneel. IA-toets: zelfde plek boven het grid, geen nieuwe route of tegel, hergebruik
`.tabel-scroll`/`Badge`/`linkbtn`/dialoog-patroon "Niet afsluiten…" — past.

## Keuzes (Peter keek niet mee)

1. **"Beide (halve dagen)" zet écht beide kaartjes op ½** (niet alleen een vinkje) — dan klopt de planning mét de afspraak en telt de
   pool "geplande dagen" juist. Terugweg: dagdeel per kaartje weer op heel (bestaande ½-knop); het akkoord vervalt dan vanzelf niet
   (zelfde stand), maar is zichtbaar in het logboek.
2. **Akkoord verloopt op STAND-wijziging, niet op tijd** — precies "rij verdwijnt tot de planning wijzigt" uit de opdracht; nooit DELETE.
3. **"Houd ‹A›" verwijdert de andere kaart(en) direct** (mét toast + ongedaan maken, 10 s), zonder extra bevestiging — dezelfde
   waarborg als het vulhandvat; een kaart mét ingevulde uren blijft via het ploeg-paneel de weg mét bevestiging.
4. **Verstreken dagen: alleen de paneellijst filtert.** Kaart-chips en "Per project" tonen ze nog, zoals de opdracht vraagt ("wél in
   Per project lezen").
5. **Weekchip i.p.v. "laatst bekeken week onthouden":** de URL is al de bron (deeplinks, deelbaar); onthouden buiten de URL zou
   een tweede waarheid zijn. De chip maakt een oude week eerlijk.
6. **Dubbelen-CLI toetst óók e-mail en meldt telefoon als niet toetsbaar** (KP 7.6: geen stille no-op) i.p.v. de twee sleutels weg te
   laten. Detacheerders tellen mee als veldwerker (Beheer › Veldwerkers toont ze ook).
7. **Harnas mét vaste "vandaag" (di 15-9-2026):** anders zou het paneel in de sweep leeg zijn zodra week 38 verstreken is; het
   harnas faket alleen `Date` (patroon ook in de vitest-suite: `vi.useFakeTimers({ toFake: ['Date'] })`).

## Poort

| Toets | Uitkomst |
|---|---|
| `make migrate` dev-DB | `Running upgrade 0168 -> 0169` (in de sessie getoond) |
| `alembic check` | "No new upgrade operations detected." |
| `scripts/dump_schema.sh` (repo-root) | `schema_referentie.sql` ververst vanaf boekhouding_test @ 0169 (+74 regels), meegecommit |
| Live 200 | niet apart gemeten mét uvicorn — de route is via `TestClient` gedekt: `POST /uren/kantoor/planning/conflict-akkoord` → 200 mét DTO, 422 bij te korte reden, 403 veldrol/zonder recht/zonder scope; `GET /uren/kantoor/planning` → 200 mét `conflict_akkoorden` |
| `pytest tests/uren/test_planning_conflicten_21_09.py` (nieuw) | 9 groen: halve dagen + akkoord + audit + idempotent + leesroute; nieuwe stand = nieuwe rij, oude blijft (2 rijen, geen DELETE); afwezig-pad, 404/422/onbekende soort; route rolpoort/scope/200/422 + leesroute; "Houd" via bulk bron `conflict` + ongedaan = zelfde set + onbekende bron 422; dubbelen puur (broers 0, KvK/IBAN-cluster, identieke naam 0), normalisatie, DB-rapport (KvK-cluster + IBAN via twee crediteuren), CLI lees-only (audit-teller ongewijzigd, exit 2 zonder keuze) |
| Gerichte set (551) | `test_migratie_metadata_guard`, `test_rol_endpoint_gates`, `test_leverancier_iban_invalidatie_guard`, `test_planning_v3_18_09`, `test_planning`, nieuw — 551 passed (2:50) |
| `test_nameting_workflow.py` | 22 passed (incl. nieuwe `test_onderdeel_veldwerkers_dubbelen_alleen_op_verzoek_en_lees_only`) |
| Volledige backend-suite | 7019 passed, 2 skipped, 7 failed + 11 errors in 49:12 — alle 18 rode in `tests/auth/test_app_activatie*.py`/`test_archiveren.py` (DB-fixtures, samenvallend met mijn parallelle guard-run — procesfout, zie "Niet gedaan") en `test_nameting_workflow` (suite las de yml van vóór mijn wijziging). Geïsoleerd herdraaid ná de suite: die bestanden + docs-guards (`test_claude_md_beslissingen_verwijzingen`, `test_rapporten_index`, `test_rapporten_gelezen_regels`, `test_regels_index`, `test_migratie_metadata_guard`) = **89 passed, 0 rood** |
| `tsc -b` | groen |
| `vitest run src/planning` | 6 bestanden, 55 tests groen (PlanningScreen +4, dagEerst +2) |
| Volledige vitest | 244 bestanden, 1887 tests groen (incl. changelog-guard op WAT_IS_NIEUW) |
| `POORT=5202 HARNASSEN_ALLEEN=harness-planning scripts/overflow_sweep.sh` | eerste run 6/24 rood (`table.plan-conf-tabel` 768 px, `?kaart=1`) → tabel altijd in `.tabel-scroll` + acties `flex-wrap` → **24/24 groen** |
| Gouden set | niet gedraaid — geen document-/boekpad geraakt (planning-UI + lees-only CLI); zie "Niet gedaan" |

## Niet gedaan / open

- **Werkt in productie: niet gemeten.** Meetrecept ná de deploy (service én job-image, `gcloud run jobs describe … image`):
  1. `/planning?administratie=<Universal>` (huidige week 39): paneel-kop "N conflicten deze week", rijen mét soort + "Houd …"; open
     `?week=2026-W37` → chip "verstreken week", paneel toont geen rijen mét handeling (alleen de historie-regel).
  2. Één conflict "Beide (halve dagen)…" mét reden → rij weg, beide kaartjes ½, logboek `planning_conflict_akkoord`; daarna een derde
     kaart voor die persoon-dag → rij komt terug.
  3. `scripts/gcp/nameting.sh veldwerkers-dubbelen --alles` (of `gh workflow run nameting -f onderdeel=veldwerkers-dubbelen`) →
     `verkenning/nameting-veldwerkers-dubbelen-<dd-mm>.txt` mét "TOTAAL 0 kandidaat-cluster(s) … 0 fout(en)" (Universal verwacht 0).
  Vervolg-opdracht `opdrachten/inbox/2026-09-22-nameting-planning-conflictenpaneel-veldwerkers-dubbelen.md` (`niet vóór: 2026-09-22 09:00`).
- Geen samenvoegen-flow en geen UI-chip voor dubbele veldwerkers (bewust, opdracht C).
- `GET /uren/kantoor/planning` levert de akkoorden alleen voor de getoonde week; een akkoord ná wijziging + terugdraaien naar de oude
  stand wordt weer verborgen (de oude rij matcht) — bewust: de mens hield die stand eerder al bewust.
- Procesnotitie (les, herhaling van [geen parallelle pytest-runs]): ik draaide `test_nameting_workflow.py` één keer parallel aan de lopende
  volledige suite — de conftest raakt de gedeelde `boekhouding_test` óók voor DB-loze tests; 18 auth-tests werden daardoor rood en zijn
  geïsoleerd groen herdraaid. Geen productcode-oorzaak.

## Gelezen regels

Volledig gelezen vóór de start (LEESPLICHT): `docs/regels/uren-planning-veldwerkers.md` (472 regels bij het lezen; 520 ná deze run),
`docs/regels/kantoor-frontend.md` (133 regels; 144 ná deze run). Verder `docs/regels/werkloop-productie.md` niet opnieuw gelezen (werkloop
volgens CLAUDE.md § Werkwijze).

## Bestanden

Backend: `migrations/versions/0169_planning_conflict_akkoord.py`, `app/uren/models.py` (PlanningConflictAkkoord), `app/uren/planning.py`
(BULK_BRONNEN + conflict, `ConflictAkkoordData`, `bevestig_conflict`, akkoorden in `planning_overzicht`), `app/uren/schemas.py`,
`app/uren/router.py` (conflict-akkoord-route), `app/uren/dubbelen.py` + `dubbelen_cli.py`, `app/cli.py`, `migrations/schema_referentie.sql`,
tests `tests/uren/test_planning_conflicten_21_09.py`, `tests/security/test_rol_endpoint_gates.py`, `tests/unit/test_nameting_workflow.py`.
Frontend: `planning/ConflictenPaneel.tsx` (nieuw; `ConflictenBalk.tsx` verwijderd), `planning/dagEerst.ts` (+ tests),
`planning/PlanningScreen.tsx` (+ tests), `planning/planningApi.ts`, `planning/planBulkOngedaan.ts`, `styles/components.css`,
`dev/visueelHarnasPlanning.tsx`, `changelog/WAT_IS_NIEUW.md`. Overig: `mockup/planning-v3-dag-eerst.html`, `scripts/gcp/nameting.sh`,
`.github/workflows/nameting.yml`, `docs/regels/uren-planning-veldwerkers.md`, `docs/regels/kantoor-frontend.md`, `docs/BESLISSINGEN.md`,
`CLAUDE.md` (uren-domein rij 10).
