# Rapport 18-09 — Inbox afgewerkt (run 3): zes opdrachten in volgorde

Coördinator + vier parallelle forks (A accordering, B btw, C samenvoegen-bug, D boeken sneller); de coördinator bouwde de
SPOED-volumerem zelf en deed de nameting (6). Domeinregels vooraf volledig gelezen (alle negen geraakte `docs/regels/*.md`).
Deploy: volgt via de Stop-hook ná deze run — **werkt in productie: niet gemeten** voor alle bouwopdrachten; alleen de nameting (6)
meet productie (stap 0 ja, app-flows klikpunten).

## Per opdracht
| # | Opdracht | Gedaan | Werkt in productie | Rapport |
|---|---|---|---|---|
| 1 | SPOED volumerem alleen automatisch | ja — 20/dag alleen automatisch (markering), handmatig én ná klant-akkoord 500-noodrem (één teller), meldingen mét rem + teller + handeling, één helper over acht rem-plekken + herstel-CLI; geen migratie | niet gemeten | `2026-09-18-volumerem-handmatig.md` |
| 2 | Btw-bedrag volgt het tarief (deel A + B) | ja — herrekenen bij tariefwissel, 0 % mét factuur-btw = btw in kosten, harde check "Btw-bedrag past bij tarief" mét acties, hint weg, BUA-kenmerk (migratie 0163) + Beheer-blok mét voorstel, keuzelijst NL-eerst + buitenland ingeklapt + gebruiksfrequentie, lees-only CLI; feiten: 0 % op Rituals kwam van de mens, historie 2 BLOW-documenten | niet gemeten | `2026-09-18-btw-volgt-tarief.md` |
| 3 | BUG samenvoegen + regel-btw (+ extra 409) | ja — oorzaak hypothese 1 (autosave 21 regels onder voorkeur samengevoegd; 4 andere documenten), modus volgt de data, factuur-regelkolom wint (0 % = NL Nul), bruto uit factuur-tarief, pinbon-totaal mét toets, chip afgedekt, byte-identieke directe upload = 409 "al aanwezig" mét link; gouden-set-casus ae; geen migratie | niet gemeten | `2026-09-18-samenvoegen-en-regelbtw.md` |
| 4 | Klein klant-accordering (punt 0 eerst) + bovenop | ja — overflow 1385 px gefixt (tabellen in .tabel-scroll, knoppen links; sweep 1385/1280), zoekveld/filterchips/samenvatting/deeplink, "Geen accordeurs" = uitnodigen/koppelen, combobox leveranciers, route 'bovenop' (migratie 0164) | niet gemeten | `2026-09-18-accordering-zoekveld-uitnodigen-bovenop.md` |
| 5 | Boeken sneller | ja — checks lokaal/extern mét cache op vingerafdruk + voorverwarmen, 202 `wordt_geboekt` + achtergrond-schrijver (job `rlz-boek-wachtrij` + */2-vangnet; geen Cloud Tasks), doorloop zonder lijst-fetch + prefetch, Server-Timing, bevinding in `meten` (migratie 0165); **agent afgebroken op de tegoedlimiet ná het gros van het werk — coördinator verifieerde en rondde af** | niet gemeten (nulmeting vóór: checks p95 2,14 s, boeken p95 3,42 s) | `2026-09-18-boeken-sneller.md` |
| 6 | Nameting veld-app uitvoerder (ná deploy) | stap 0 voldaan (998336b service = jobs, 0158–0162 live, scheduler herinneringen aan); app-flows niet meetbaar vanuit de nameting (0 veld-app-requests sinds de deploy) → klikpunten; lees-only: Universal 14 ingediend/0 meerwerk, Orfan Ogur = uitvoerder, tokenketen zonder 401 | deels | `2026-09-18-veldapp-uitvoerder-nameting.md` |

Extra bij 3 (besluit Peter 18-09): uitgevoerd als route-poort op de twee directe upload-routes (verwijderd exemplaar telt niet als
"al aanwezig"); de mail-/IMAP-intake blijft de bundel-/nabundelmotor volgen. Het open beslispunt "server-side sha256-kortsluiting" is
daarmee besloten (`docs/regels/intake-extractie.md`).

## Poorten
- Backend volledige suite (boekhouding_test, 46 min): **6720 passed, 7 failed** — alle zeven verouderde verwachtingen (meldingstekst volumerem ×3, checkset mét de nieuwe btw-check ×2, btw-codes-DTO mét extra velden, INDEX-regel van dit rapport) gefixt en herdraaid: 11 groen. Nieuwe tests van de run: volumerem 9, btw/BUA/keuzelijst, samenvoegen/409/pinbon, accordering +6, boek-wachtrij/checks-extern.
- Frontend `tsc -b` groen; vitest volledig **239 bestanden / 1841 tests groen**; keten-sweep 11/11 groen ná bewuste baseline-verversing
  van vijf detail-schermen (land-chip "NL · uit btw-nummer" + check-rij "Btw-bedrag past bij tarief" — screenshot beoordeeld).
- Guards: rapport-klikpunten, rapport-index, gelezen-regels, CLAUDE.md↔BESLISSINGEN, regels-index, keten-guard, migratie-metadata,
  deploy-image-uniform, deploy-envset, vaste testconfig, rolpoort-matrix — groen op de coördinator-DB.
- Migratie-routine: `make migrate` dev-DB `0162 -> 0163 -> 0164 -> 0165` gezien; live-200 (dev-uvicorn 8011): `/accordering/overzicht`,
  `/accordering/accordeur-kandidaten`, `…/accordering/leverancier-kandidaten`, `…/btw-aftrek-uitgesloten`, `…/btw-codes` allemaal 200;
  `scripts/dump_schema.sh` → `schema_referentie.sql` @ head 0165 (139 regels nieuw: btw_aftrek_uitgesloten, leverancier_route modus/positie, check_extern_cache, boek_wachtrij_claim, enum wordt_geboekt).

## Klikpunten Peter (samengevat; details per rapport)
1. Ná de deploy: `scripts/gcp/f3_jobs.sh` stap 8b (IAM `run.invoker` + scheduler `*/2` voor `rlz-boek-wachtrij`) — tot dan blijft een
   ingediende boeking zichtbaar op "Wordt geboekt…" tot het startup-vangnet.
2. Beheer › BLOW › Boeken & AI › "Btw niet aftrekbaar": "Voorstel overnemen (3)" (4014/4508/4510); de twee BLOW-afwijkingen
   (RLZ-04-00000357 € −8,75, RLZ-04-00000358 € −4,50, 18-09, leesreplica) storneren/herboeken achter de aangiftepoort — Peter beslist.
3. `/instellingen/accordering?zoek=blow`; Bouwadvies op 1385 px; route "bovenop" voor de twee leveranciers.
4. Veld-app testaccount: het recept in het nameting-rapport (punten 1–6).
5. Optioneel vóór de deploy live is: `MAX_BOEKINGEN_PER_DAG_PER_ADMINISTRATIE=500` op de service (stond er 18-09 ~15:45 niet).

## Beslispunten (open)
- Volumerem: ná klant-akkoord = dezelfde 500 (gekozen); aparte lagere rem = één regel.
- Btw: factuuradres-land als vierde land-bron (AI-veld, niet gebouwd); BUA-voorstel in bulk over administraties.
- Boeken sneller: 15 → 30 min cache-geldigheid; Cloud Tasks alsnog; `wordt_geboekt_verouderd` van meten naar actie ná een week.
- Accordering: "Bestaande accordeur koppelen" doet alleen toevoegen; kantoorbreed overzicht = één statement per administratie (≫ 200 → Beheerder-leespolicy).

## Proces
- Vier forks parallel mét eigen test-DB's (a2–a5), coördinator a6; migratiestubs 0163–0165 vooraf. Lessen (memory bijgewerkt): stubs +
  model vóór migratie breken élke conftest-run in de werkboom; python-patchscripts overschreven elkaars edits in `router.py` en
  `regelVoorstelChips.ts` (twee keer hersteld door de agenten zelf); agent D afgebroken op de maandelijkse tegoedlimiet (429) — de
  coördinator rondde af op basis van de code en het voorlopige rapport.
- Commits per slice (zie git log); de Stop-hook pusht.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/autoboeken-ai.md` (122 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (297 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- `docs/regels/btw.md` (150 regels)
- `docs/regels/kantoor-frontend.md` (123 regels)
- `docs/regels/intake-extractie.md` (270 regels)
- `docs/regels/accordering-native-app.md` (321 regels)
- `docs/regels/duplicaten-crediteuren.md` (119 regels)
- `docs/regels/uren-planning-veldwerkers.md` (472 regels)
