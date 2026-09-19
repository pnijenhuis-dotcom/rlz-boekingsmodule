# Pro-rato projectverdeling sluit afgesloten projecten uit + RLZ-kant-meting facturen zonder project (nazorg 18-09)

**Opdracht:** `opdrachten/gedaan/2026-09-19-projectverdeling-sluit-afgesloten-projecten-uit-en-rlz-kant-meting.md` (19-09, nazorg
rapport `2026-09-18-facturen-zonder-project.md` beslispunt 3). **Geen migratie, geen RLZ-write.**
**Werkt in productie: niet gemeten** voor blok A (de code deployt ná deze run — meetrecept onderaan, vervolg-opdracht in de inbox);
**blok B (RLZ-kant-meting) is WEL gemeten** op de gedeployde job-image (`e6c8ca3`, service én jobs, deploy-run 35396454022 groen
18-09 21:22): executies `rlz-reconciliatie-5z68r` (Universal) en `rlz-reconciliatie-45mb9` (alle project-verplichte administraties).
**BESLISSINGEN:** "PROJECTVERDELING SLUIT AFGESLOTEN PROJECTEN UIT + RLZ-KANT-METING FACTUREN ZONDER PROJECT (19-09)".

## Één regel voor Peter
De verdeelsleutel neemt sinds deze run alleen projecten die lopend én actief zijn; Universal heeft 8 projecten die "Afgesloten …"
heten maar in RLZ nog actief staan (die krijgen nu een let-op "afsluiten?" en blijven tot dan meetellen), 5 geboekte verdelingen
legden samen € 1.239,05 op twee daarvan, en de RLZ-kant heeft in 2026 bij alle vijf project-verplichte administraties **0** facturen
zonder project. Drie beslispunten: (1) de € 1.239,05 op "Afgesloten 26012 Tilburg" en "Afgesloten 26051 Opijnen" laten staan of
storneren + herverdelen — voorstel: eerst de 8 projecten afsluiten, geboekte rijen laten staan; (2) OVH-project voor Universal
aanmaken (via Projecten, synct naar RLZ) zodat telecom, management fee en advies (€ 12.229 geboekt tot nu) bewust op overhead landen
in plaats van omzet-gewogen over lopende projecten; (3) bulk-herstel RLZ-kant: niet nodig (0).

## A. Verdeelsleutel: alleen actieve projecten (gebouwd + getest)

**Wat er al stond.** `omzet_per_project` filterde al op `is_actief` (de bron-spiegel van RLZ `IsActive`). Het gat was tweeledig: de
module-status van 0160 (`project_cache.status`) telde niet mee (een project dat in de module is afgesloten maar in RLZ buiten de
module om weer actief wordt gezet, kwam terug in de sleutel), en de twee "Afgesloten"-projecten uit het 18-09-rapport staan in RLZ
gewoon op `IsActive = true` — de sleutel was dus conform zijn eigen regel, de naam zei iets anders dan de status.

**A1 — sleutel.** `app/projectverdeling/omzet.py`: filter `is_actief` ÉN `status != 'afgesloten'`. Een project waarvan de NAAM met
"Afgesloten" begint (`naam_zegt_afgesloten`, eerste woord, hoofdletterongevoelig) maar dat actief staat, blijft in de sleutel —
nooit stil uitsluiten op naam — en is een LET-OP `project_naam_afgesloten_status_actief` in het reconciliatieblok `projecten`
("Project heet 'Afgesloten' maar staat actief … Sluit het project af via Projecten › Afsluiten…"; registry `meten`, vingerafdruk
administratie + project, geen exit 1). `OmzetSelectie.naam_afgesloten_actief` draagt dezelfde lijst.

**A2 — herberekening bij afsluiten/heropenen.** `app/projectverdeling/afgesloten.py::herbereken_na_projectstatus` wordt uit
`status._wissel` aangeroepen ná de bron-write en de statuswissel (eigen transactie, nooit blokkerend — fout = logregel, de volgende
lezing rekent tóch live). Voorstel-verdelingen waarvan het snapshot het project draagt worden live herrekend, het snapshot
(`verdeling`/`omzetstanden`/`pro_rato_bedrag`) teruggeschreven, en per gewijzigd document komt één tijdlijnregel "verdeling
herberekend: ‹project› afgesloten" (heropenen: "… heropend", dan álle pro-rato-voorstellen van de administratie) + audit
`projectverdeling_herberekend` oud→nieuw. Geboekte verdelingen blijven staan (boekstand); geboekte/verwijderde documenten worden
overgeslagen.

**A3 — lees-only rapport.** CLI `projectverdeling-afgesloten-rapport (--administratie X | --alle-projectverplicht)`
(`app/projectverdeling/cli_cmd.py`; nameting-allowlist; workflow-onderdeel `projecten-afgesloten` dat ook de RLZ-kant-meting van blok B
draait): actieve projecten mét "Afgesloten"-naam, geboekte verdelingsdelen op projecten die nú afgesloten/inactief zijn of "Afgesloten"
heten (boekstuk, referentie, leverancier, factuurdatum, geboekt-op, project, bedrag) mét voorstel per rij, en de overhead die via de
sleutel loopt. Niets wordt uitgevoerd. Omdat de CLI pas ná deploy op de job-image staat, is de Universal-lijst hieronder op de
leesreplica gemeten (READ ONLY als `nameting@`, scope administratie 3ee6edf0, 19-09 ~08:45).

### Meting Universal Steigerbouw (leesreplica 19-09)

| feit | waarde |
|---|---:|
| projecten in de cache (niet verdwenen) | 170 (83 actief, 87 inactief) |
| naam begint met "Afgesloten" | 94 |
| daarvan in RLZ nog actief (`is_actief = true`) | **8** |
| module-status `afgesloten` | 0 |
| projectverdelingen | 7 (5 geboekt, 2 voorstel) |

De 8 actieve "Afgesloten"-projecten: 25017 Kudo Arnhem-Kronenburg fase 2, 25116 Oosterhout (Huvanco), 25147 Ommeren (van Kessel),
25157 Harderwijk (Wessels), 26012 Tilburg (van Kasteren), 26051 Opijnen (van kessel bouw), 26064 Apeldoorn (Ben Kuijer), 26091
Amersfoort (Ben Kuijer). Twee ervan hadden omzet in augustus 2026 en zitten daardoor in de 5 geboekte verdelingen (pro rato
**augustus 2026**, 8 delen — het 18-09-rapport noemde "juli"; de kolom `pro_rato_periode` zegt 2026-08-01):

| boekstuk | referentie | leverancier | factuurdatum | 26012 Tilburg (7,69 %, omzet € 4.418) | 26051 Opijnen (2,44 %, omzet € 1.400) |
|---|---|---|---|---:|---:|
| RLZ-04-00003215 | 202611050 | DCTE B.V. | 2026-07-27 | 9,14 | 2,90 |
| RLZ-04-00003234 | 202611101 | DCTE B.V. | 2026-08-01 | 12,93 | 4,10 |
| RLZ-04-00003236 | 26008 | Floor Beheer B.V. | 2026-08-03 | 846,31 | 268,18 |
| RLZ-04-00003235 | 202611203 | DCTE B.V. | 2026-08-26 | 24,04 | 7,62 |
| RLZ-04-00003213 | F212604921 | Kader Consultancy & Interim B.V. | 2026-09-02 | 48,47 | 15,36 |
| **totaal** | | | | **940,89** | **298,16** |

Samen **€ 1.239,05** op projecten met een "Afgesloten"-naam (geboekt 08-09, Q3 2026 open → route (a) storno 19 → her-PUT → 17 zou
kunnen). Voorstel per rij in de CLI: "laten staan tot het project is afgesloten (Projecten › afsluiten); daarna storno 19 +
herverdeling — klikpunt Peter". Mijn advies: de 8 projecten afsluiten (dan valt het uit de sleutel voor álle volgende facturen) en de
geboekte € 1.239,05 laten staan — vijf storno's + her-PUT's voor dat bedrag is meer werk en meer audit-ruis dan waarde.

Voorstel-verdelingen (worden bij de volgende lezing live herrekend; blijven de 8 actieve projecten meenemen tot ze afgesloten zijn):
Exact Software RLZ-2026053923 € 31,50 (ter accordering, gb 4410) en Floor Beheer 26009 € 11.000 (document verwijderd, telt nergens).

### A4 — Overhead via de sleutel, OVH-project (beslispunt Peter, niet zelf aangemaakt)

Álle 5 geboekte pro-rato-documenten van Universal zijn overhead in de zin van de opdracht (grootboek 4xxx, geen projectreferentie op
de factuur): DCTE 4499 Diverse kantoorkosten 3× € 599,32; Floor Beheer 4003 Management fee € 11.000,00; Kader 4606 Diverse
advieskosten € 630,00 — **€ 12.229,32 geboekt**, € 31,50 onderweg (Exact 4410 Contributies/abonnementen). Dat is precies wat een
OVH-project zou vangen; Universal heeft er geen (0 van 170 namen bevat OVH/overhead). Keuze Peter: OVH-project aanmaken via de
Projecten-module (naamconventie, synct naar RLZ; de sleutel sluit OVH al uit) óf de omzetsleutel houden. De module maakt het project
nooit zelf aan.

## B. RLZ-kant-meting facturen zonder project (job-image, alleen GET) — GEMETEN

Meetrecept uit het 18-09-rapport, uitgevoerd lokaal via `scripts/gcp/nameting.sh` (impersonatie `nameting@`, geldige gcloud-sessie):

| administratie | in module geboekt 2026 | zonder project (module) | gedekt door verdeling | RLZ geboekte PurchaseInvoices gelezen | RLZ mét kostenregel zonder Project | van vóór/buiten de module |
|---|---:|---:|---:|---:|---:|---:|
| ARVUM B.V. | 5 | 0 | 0 | 45 | **0** | 0 |
| Beleggingsmaatschappij Meyer BV | 0 | 0 | 0 | 77 | **0** | 0 |
| B. van Rooijen / G. Schaalje | 0 | 0 | 0 | 152 | **0** | 0 |
| J.G.M. Elissen Holding BV | 0 | 0 | 0 | 58 | **0** | 0 |
| Universal Steigerbouw B.V. | 59 | 0 | 5 | 1.296 | **0** | 0 |
| **totaal** | 64 | 0 | 5 | **1.628** | **0** | 0 |

0 leesfouten. Module-kant 0 ↔ RLZ-kant 0 verklaard; **bulk-herstel is niet nodig**. Logs: `.scratch/fzp-universal-rlz-19-09.txt`,
`.scratch/fzp-alle-rlz-19-09.txt` (niet gecommit; executies 5z68r en 45mb9 in Cloud Logging).

## Werkloop-observaties
- **Les:** ik bewerkte `nameting.sh` (allowlist + `via_gh_onderdeel`) terwijl de achtergrondrun ervan liep; bash leest een script
  incrementeel en strandde ná de job-executie op "regel 122: efail: opdracht niet gevonden" (het staartje van `pipefail`). De
  executie zelf was groen; het log is via `gcloud logging read` op de executienaam gelezen. Vastgelegd in het geheugen.
- De geplande nameting-workflow-run van 18-09 09:56 (35332118963) is rood; niet onderzocht in deze run (buiten scope), wel gezien.
- Het 18-09-rapport noemde de pro-rato-periode "juli 2026"; de kolom zegt augustus 2026. Hier gecorrigeerd.

## Gebouwd
- `backend/app/projectverdeling/omzet.py` — status-filter, `naam_zegt_afgesloten`, `OmzetSelectie.naam_afgesloten_actief`,
  `actieve_projecten_met_afgesloten_naam`.
- `backend/app/projectverdeling/afgesloten.py` (nieuw) — herberekening bij statuswissel (tijdlijn + audit), LET-OP-bevindingen,
  rapport geboekt-op-afgesloten + overhead-via-sleutel, rapportregels.
- `backend/app/projectverdeling/cli_cmd.py` (nieuw) + `app/cli.py` — CLI `projectverdeling-afgesloten-rapport`.
- `backend/app/projecten/status.py` — aanroep ná de statuswissel; `app/projecten/nummer.py::cli_blok` — LET-OP in blok `projecten`;
  `app/reconciliatie/teksten.py` + `soort_stand.py` — tekst + registry (`meten`).
- `scripts/gcp/nameting.sh` (allowlist, onderdeel-mapping), `.github/workflows/nameting.yml` (onderdeel `projecten-afgesloten`).
- Tests `backend/tests/projectverdeling/test_afgesloten.py` (8); gerichte run 81 passed (projectverdeling, projecten status/nummer,
  zonder_project, soort_stand, nameting-workflow); guards CLAUDE.md-verwijzingen/regels-index/keten 18 passed; vitest changelog 5.
- Docs: regels-alinea `verplichtingen-projecten-voorraad.md`, BESLISSINGEN-sectie, CLAUDE.md verwijsregel 7, WAT_IS_NIEUW
  "Kosten worden niet meer over afgesloten projecten verdeeld".

## Meetrecept ná deploy (vervolg-opdracht in de inbox: `2026-09-19-nameting-projectverdeling-afgesloten-na-deploy.md`)
```
scripts/gcp/nameting.sh projectverdeling-afgesloten-rapport --administratie "Universal Steigerbouw"
scripts/gcp/nameting.sh reconciliatie-alles --alleen projecten --lees-only
```
Verwacht: 8 actieve projecten mét "Afgesloten"-naam als LET-OP (blok `projecten`, facet "in meting"), 10 geboekte verdelingsdelen
(€ 1.239,05) mét voorstel "laten staan tot afgesloten", overhead € 12.229,32 geboekt, "OVH-project aanwezig: nee". Daarna, zodra
Peter één van de 8 via Projecten › Afsluiten… afsluit: tijdlijnregel "verdeling herberekend: … afgesloten" op Exact RLZ-2026053923
en het project weg uit die verdeling — dát is de regel "werkt in productie: ja". Let wel: zolang de 8 niet afgesloten zijn, bevat
een nieuwe Universal-verdeling nog steeds die projecten — per de regel (status leidend, nooit de naam).

## Beslispunten Peter
1. Herverdeling van de geboekte € 1.239,05 op "Afgesloten 26012 Tilburg" / "Afgesloten 26051 Opijnen": laten staan (advies) of
   storno 19 + herverdeling (Q3 open, 5 documenten).
2. OVH-project Universal aanmaken via Projecten (vangt vanaf dan € 12.229-achtige overhead) of de omzetsleutel houden.
3. Bulk-herstel RLZ-kant: niet nodig — 0 facturen zonder project bij alle vijf administraties.
En: de 8 actieve "Afgesloten"-projecten afsluiten via Projecten › Afsluiten… (de LET-OP wijst ze aan; de inbox-opdracht
"projecten-afsluit-kandidaten-scherm-bulk-afsluiten" van vanochtend gaat precies daarover).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (282 regels)
- `docs/regels/reconciliatie.md` (94 regels)
- `docs/regels/werkloop-productie.md` (65 regels)
