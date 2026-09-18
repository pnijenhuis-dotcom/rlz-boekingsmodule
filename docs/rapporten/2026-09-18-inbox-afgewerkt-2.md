# Rapport 18-09 — Inbox afgewerkt (run 2): zeven opdrachten in volgorde, één rapport per opdracht

Opdracht Peter 18-09 (middag): "Werk de inbox af, in deze volgorde, één rapport per opdracht." Uitvoering: opdracht 1 door de
coördinator, 2–6 door zeven parallelle bouwagenten (forks mét alle domeinregels in context; eigen test-DB per agent; bindende
contracten voor de gesplitste blokken 4 en 5), opdracht 7 = stap 0 uitgevoerd, meting bewust niet. Productie is in deze run
NIET geraakt; de deploy volgt via de Stop-hook ná de run.

**Werkt in productie: NIET GEMETEN voor 1–5 (deploy volgt); n.v.t. voor 6 (mockup); 7 = niet gemeten (wacht op de deploy van 1–5).**

## Per opdracht

| # | Opdracht | Gedaan | Werkt in productie | Rapport |
|---|---|---|---|---|
| 1 | Zoekveld klantenlijst + sticky dagkop planning | JA — klantZoek.ts (naam/groep, `?zoek=`, `/`, "N van M", sessie), beide plan-grids intern scrollend mét plakkende thead; 8 nieuwe vitest, overflow-sweep 40/40 | niet gemeten | `2026-09-18-zoekveld-klantenlijst-dagkop-sticky.md` |
| 2 | Bulk-upload meerdere bestanden | JA — één UploadZone mét `multiple` + map-drop op alle upload-plekken, wachtrij max 4, uitkomst per bestand, Stoppen/Mislukte opnieuw, samenvatting, één lijst-verversing; server ongewijzigd (feit: byte-identiek = nieuw document mét duplicaat-vlag, géén 409 — "al aanwezig" is de vlag) | niet gemeten | `2026-09-18-bulk-upload-meerdere-bestanden.md` |
| 3 | Projecten: status afgesloten + nummer uniek | JA — migratie 0160, afsluiten/heropenen bron-eerst (RLZ IsActive + teruglezen, Odoo archived), toggle "Toon afgesloten (N)", oranje signaal nagekomen factuur, kandidaat-chip, nummer uniek over cache + RLZ (409 + "Openen"), lees-only CLI's dubbelen/kandidaten, reconciliatie-soort `project_nummer_dubbel` (meten) | niet gemeten | `2026-09-18-projecten-status-afsluiten-nummer-uniek.md` |
| 4 | Planning v3 dag-eerst (mockup AKKOORD) | JA — migratie 0161 (reservering + afwezigheid), bulkroute atomisch/idempotent, dagkolommen mét projectkaarten, projectbalk, conflictenbalk, vulhandvat + toast/ongedaan (Cmd/Ctrl-Z), ploeg-paneel, toggle Per project, afwezig-kaartje; 34 nieuwe frontend-tests + 13 backend, overflow-sweep planning-harnas 24/24 | niet gemeten | `2026-09-18-planning-v3-dag-eerst.md` |
| 5 | Veld-app run B: herinnering + offline | JA — migratie 0162, motor + job `rlz-uren-herinneringen` (default 16:30 doorlopen, opt-out per gebruiker, claim per dag, tellers in de reconciliatiemail), offline-wachtrij op het slot-anker mét 409-conflict = beide standen, schakelaar ⚙ Toegang, tijdveld Uren & materiaal; mockup v3 ⑤/⑥ vóór de bouw; 19 backend + 15 frontend tests | niet gemeten — **klikpunt: scheduler aanmaken** | `2026-09-18-veldapp-ux-run-b.md` |
| 6 | Mockup factuuropdracht per project | JA — `mockup/factuuropdracht-project.html` ①–④ + Notities, pre-feature-ritueel (wat bestaat/wat nieuw), BESLISSINGEN TER AKKOORD; geen code | n.v.t. | `2026-09-18-mockup-factuuropdracht.md` |
| 7 | Nameting veld-app uitvoerder | NEE (bewust) — stap 0 gedaan: productie staat op `15566c4` (service én jobs), migraties 0157→0158→0159 live (executie `rlz-migratie-j8mcr` 09:55Z); de opdracht zegt "pas ná deploy van 1–5" en die deploy kan pas ná deze run — opdracht blijft in de inbox mét "Poging 2"-aantekening + aanwijzing voor stap 0 (upgrade 0159→0162) | niet gemeten | inbox-bestand, alinea "Poging 2" |

## Poorten en routine

| Poort | Uitkomst |
|---|---|
| Migraties dev (`make migrate`) | `0159 -> 0160`, `0160 -> 0161`, `0161 -> 0162`; `alembic check` "No new upgrade operations detected" |
| Live 200 dev (uvicorn 8011, Beheerder-token) | `/uren/kantoor/planning` (mét `reserveringen`/`afwezigheid`), `/uren/kantoor/afwezigheid`, `/uren/beheer/herinnering-tijd/{aid}` ("16:30", standaard), `/projecten/{aid}?alleen_actief=false`, `/projecten/kantoorbreed?toon_afgesloten=1` → 200; bulk mét lege lijst → 422 (poort) |
| Frontend volledige suite | 231 bestanden / 1804 tests groen; `tsc -b` groen op élke commit (pre-commit-hook) |
| Backend volledige suite (boekhouding_test) | 6591 groen, 1 skipped, 5 rood (56 min) → alle vijf verouderde verwachtingen, geen codefouten: `test_store_links` ×2 (Android-web-regel in de mail uit de ochtendrun d3857c0/9cf8b70, test verwachtte een leeg blok), `test_schema` (nieuwe kolom `gebruiker.uren_herinnering_uit` op de whitelist — geen financiële data), `test_rlz_dubbel` (blok `projecten` in `reconciliatie-alles`), `test_rapporten_index` (dit rapport zelf, INDEX-regel volgde). Ná de fixes: die drie bestanden 79 groen; de suite is niet in zijn geheel herdraaid |
| Gouden set frontend (`keten_sweep.sh`) | eerste run 5/11 rood (lijst-schermen): uploadzone was twee regels geworden (bulk-tekst) én de chip "te beoordelen" uit de ochtendrun stond nog niet in de baseline (16-09) → tekst terug op één regel (regel 27/28-08), baseline bewust ververst (`KETEN_UPDATE_BASELINE=1`), derde run 11/11 groen |
| Schema-dump (`scripts/dump_schema.sh`) | `schema_referentie.sql` ververst vanaf boekhouding_test @ head 0162 (+234 regels: project_cache-status, planning_reservering, veldwerker_afwezigheid, uren_herinnering, twee kolommen) |
| Docs-guards (CLAUDE.md↔BESLISSINGEN, rapporten-INDEX, gelezen regels, klikpunten, regels-INDEX, changelog) | groen ná élke docs-merge |

## Commits (per slice, oudste eerst)

`44e7bce` feat zoekveld + sticky dagkop · `da2a137` docs 1 · `5170a49` docs mockup 6 · `121ce2f` feat bulk-upload · `75b93e1` docs 2 ·
`aac27f9` feat projecten (0160) · `444f70f` feat backend uren (planning v3 + run B; 0161 + 0162 — één commit: gedeelde hunks in
uren/models/router/schemas/service) · `1b44d2a` feat frontend planning v3 · `1137443` feat frontend veld-app run B · `6e5e766` docs 3/4/5 ·
`3b9572f` fix uploadzone één regel · `6469e6d` test keten-baselines · laatste commit: tests-fix + schema-dump + dit rapport.

## Klikpunten Peter (ná de deploy)

1. **Scheduler `rlz-uren-herinneringen` aanmaken** (éénmalig; commando in `2026-09-18-veldapp-ux-run-b.md` deel A) — zonder scheduler
   geen herinneringen; de reconciliatiemail toont dat (teller `uren_herinnering` blijft 0 verwacht).
2. **Planning › Personeel (Universal week 39):** project uit de balk naar een dag slepen → grijze kaart "gereserveerd"; kaart → paneel
   rechts → ploeg aanvinken → Opslaan; bolletje pakken en de kaart ma→vr trekken → toast "Gekopieerd …" → Ongedaan maken; toggle
   "Per project" toont dezelfde aantallen. Screenshots graag terug als iets afwijkt.
3. **Projecten:** nieuw project mét een bestaand nummer → 409 "bestaat al … — openen?" (niets aangemaakt); TEST-project afsluiten →
   uit de keuzelijsten + RLZ IsActive uit → heropenen. Daarna via de nameting-job de lees-only rapporten `projecten-dubbele-nummers`
   en `projecten-afsluit-kandidaten` lezen en beslissen welke dubbeling samenvoegt (nooit automatisch, RLZ-project nooit verwijderen).
4. **BLOW 180 bestanden:** klantpagina BLOW → soort kiezen → álle bestanden (of de map) in één keer op de uploadzone; "al aanwezig" is
   geen fout. Beslispunt: wil Peter server-side een echte 409 op byte-identieke uploads (nu: nieuw document mét duplicaat-vlag)?
5. **Veld-app (testaccount):** vliegtuigstand → uren opslaan → bolletje "nog niet verzonden" → netwerk aan → verzonden; ⚙ Toegang ›
   Herinneringen schakelaar; Instellingen › Universal › Uren & materiaal tijdveld.
6. **Werkvoorraad:** zoekveld "Univ" → 3 rijen; Planning: scrollen → dagkop blijft staan.
7. **Mockup factuuropdracht:** akkoord + beslispunten ④ (verzenden: RLZ/Odoo zelf — voorstel) en ⑥ (klant-accordering vóór verzenden:
   nee — voorstel).

## Beslispunten die de agenten kozen (bevestigen of bijstellen)

- Kandidaat-afsluiten-criterium = 90 dagen stil ÉN gebouwd-m² ≥ contract-m² (het model kent geen contractsom).
- Planning: een conflict wordt WÉL gepland en oranje gemarkeerd (nooit blokkerend); reserveringsrij blijft als drager staan.
- Herinnering: opt-out per gebruiker (niet per toestel); één herinnering per veldwerker per dag over álle administraties; "geen
  kanaal" claimt de dag (morgen opnieuw) en is de enige harde voorwaarde (LET-OP mét deeplink `/veldwerkers`).
- Offline: indienen pas ná een lege wachtrij; conflict = kiezen (kantoor houden / mijn regel bewaren), nooit overschrijven.

## Niet verwerkt (buiten de opgegeven volgorde)

Vier nieuwe inbox-opdrachten kwamen tijdens de run binnen en zijn niet aangeraakt: `boeken-sneller-checks-en-doorloop`,
`btw-bedrag-volgt-tarief-harde-check`, `BUG-samenvoegen-toont-gesplitste-regels-en-geheugen-overschrijft-factuurbtw`,
`SPOED-volumerem-alleen-automatisch`. Volgorde = mtime; de cc-inbox pakt ze ná de push op.

## Gelezen regels

- `docs/regels/werkloop-productie.md` (55 regels), `docs/regels/kantoor-frontend.md` (113), `docs/regels/werkvoorraad-controlescherm.md` (185),
  `docs/regels/uren-planning-veldwerkers.md` (353), `docs/regels/intake-extractie.md` (252), `docs/regels/verplichtingen-projecten-voorraad.md` (178),
  `docs/regels/accordering-native-app.md` (271), `docs/regels/omzet.md` (232) — alle volledig door de coördinator vóór de start; de
  bouwagenten erfden die lezing (forks) en noemen per rapport hun eigen set.
