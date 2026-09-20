# Nameting kassarapport automatisch typeren ná de ÉCHTE reconciliatie-run van 20-09 06:30 + kantoorbrede nazorg-CLI ná de fix: WERKT IN PRODUCTIE: JA (auto-sluiting 4 profx-bevindingen mét audit, aandacht-teller 341 → 176 proxy, kantoorbrede nazorg-CLI exit 0 / 78 administraties / 0 kandidaten, dagteller gedaan 0 = correct); KLIKPUNT: UI-teller Inzicht › Reconciliatie en Instellingen › Boeken (login)

**Opdracht:** `opdrachten/gedaan/2026-09-20-nameting-kassarapport-autotype-na-echte-run.md` (vervolg op
`docs/rapporten/2026-09-19-nameting-kassarapport-autotype-poging-2.md`). Domeinen: omzet, reconciliatie, werkloop-productie.
Uitgevoerd 20-09 ~08:40–09:20 CEST, lees-only behalve stap 1 (dry-run = 0 writes). Geen RLZ-write, geen migratie, geen code.

## Werkt in productie: ja

| Onderdeel | Uitkomst | Bewijs |
|---|---|---|
| Kantoorbrede nazorg-CLI `kassarapport-autotype-nazorg --dry-run` (zonder `--administratie`) — op 19-09 exit 1 `NameError` | **JA** — exit 0, "78 administratie(s), 0 kandidaat/kandidaten, zou omzetten 0, overgeslagen —" | executie `rlz-reconciliatie-qj4cx`, 08:45 CEST, image `backend:1b61fef` (bevat fix `4d4366b`); log via `gcloud logging read` op de executienaam |
| Auto-sluiting van de vier profx-bevindingen `kassarapport_in_werkvoorraad` Van Boxtel (Journaal 31-8/1-9/2-9/3-9) | **JA** — run `55facc7c` (scheduler, 04:30:20–04:44:52 UTC, status `klaar`) produceert voor Van Boxtel nog 1 × `kassarapport_in_werkvoorraad` (Journaal 4-9 `4e120087`, signaal omzetrekeningen) + 8 × `omzet_in_inkoopstroom`; run 19-09 `772e6c3c` had 5 + 8. Audit `reconciliatie_auto_gesloten` 04:44:54 UTC: één rij `soort` `kassarapport_in_werkvoorraad`, `aantal` 4, `nieuwe_waarde.administratie_id` = Van Boxtel `cd973c86`, reden "niet meer geproduceerd door run 55facc7c… — afwijking uit de vorige run verdwenen"; `samenvatting.delta.verdwenen_afwijkingen` 10 (waarvan deze 4) | leesreplica `db_lezen.sh`, scope-loop `.scratch/aandacht-19-09-run.tsv` / `aandacht-20-09.tsv` (van de ic_spiegel-nameting van vanochtend, zelfde run) |
| Inzicht › Reconciliatie aandacht-teller 340 → ≤ 336 | **JA (bovengrens)** — aandacht-proxy (afwijking + let_op + fout − meten) 341 → 176 over 80 administraties + NULL-scope; het kassarapport-aandeel daarvan is exact −4 (5 → 1). De UI-teller trekt gesnoozede LET-OP's en live-acceptaties nog af en is dus ≤ 176; exacte getal = klikpunt (login) | tabel stap 5 van `2026-09-20-nameting-ic-spiegel-rood-echte-run-poging-2.md` + eigen telling op de tsv's |
| Audit `kassarapport_autotype_run` van de run van 06:30 voor Van Boxtel: "verwacht 0 / gedaan 0" | **verwachting was fout, gedrag correct** — er is géén audit-rij: `verwerk_werkvoorraad` schrijft de run-rij alleen als er kandidaten waren (`if not dry_run and uit.documenten`, `app/omzet/autotype.py`). Een administratie zonder parser-treffer laat bewust geen rij achter (anders 78 lege audit-rijen per dag). Laatste rij Van Boxtel blijft die van 19-09 16:01:20 UTC {verwacht 4, gedaan 4} | leesreplica `platform.audit_event` mét `--administratie` Van Boxtel (5 rijen 19-09, 0 rijen ≥ 20-09 04:00 UTC) |
| "Voor élke andere administratie mét een parser-treffer: gedaan > 0" | **JA (leeg)** — scope-loop over alle 80 administraties: 0 rijen `soort_automatisch_gewijzigd` / `kassarapport_autotype_run` / `kassarapport_autotype_overgeslagen` sinds 20-09 04:00 UTC; er wás geen andere administratie mét een treffer (consistent met "0 kandidaten" kantoorbreed en met de lees-only meting van 19-09: 9 afwijkingen, alle Van Boxtel). Filter getoetst op de 5 bekende rijen van 19-09 (5/5) | `.scratch/autotype-audit-loop-20-09.sh` → `autotype-audit-20-09.tsv` (lokaal, niet gecommit) |
| Dagteller `kassarapport_autotype` 20-09: gedaan = aantal omgezette documenten in de run van 06:30 | **JA, afgeleid: 0** — de teller leest uitsluitend de drie audit-acties hierboven (`automatiseringen.py`); 0 rijen op 20-09 = gedaan 0, overgeslagen 0; de 4 van 19-09 vallen in het etmaal 19-09. Systeemmail staat in productie `uitgeschakeld` (`mail_status` `actie=verzonden;systeem=uitgeschakeld`), dus alleen Instellingen › Boeken toont de teller = klikpunt (login) | leesreplica `reconciliatie_run` + `audit_event` |
| Stand van de vier documenten | **ongewijzigd `vraag_open`** — `8631403e`/`37e1b23e`/`cbef27bc`/`0b571db4` soort `kassarapport`, status `vraag_open`, `laatst_gewijzigd_op` 19-09 16:01 UTC; 0 tijdlijnregels ná 19-09 16:05 UTC; Journaal 4-9 `inkoopfactuur`/`te_controleren` sinds 08-09. Het kantoor heeft de categorie-mapping (Dranken/Edible/Hash/Headshop/Joints/Snacks/Wiet) nog niet gezet — handeling kantoor, niets geforceerd | leesreplica `document` + `document_gebeurtenis` |

## Stap 0 — groen, in de opgedragen volgorde

- (a) `git fetch origin` → `main..origin/main` = 0, `origin/main..main` = 0; geen merge nodig.
- (b) deploy-runs `1b61fef` (20-09 05:34 UTC), `0453020`, `aef301f`, `ebf93ff` alle `success`; fix-commit `4d4366b` (`git log --grep=scoped_session`) is
  ancestor van alle vier.
- (c) service `rlz-backend` én job `rlz-reconciliatie` op `europe-west4-docker.pkg.dev/rlz-boekhouding/rlz/backend:1b61fefcec18…` (identiek).
- (d) leesreplica: run `55facc7c` scheduler `gestart_op` 2026-09-20 04:30:20 UTC, `afgerond_op` 04:44:52 UTC, status `klaar`, exit 1 (= afwijkingen
  gevonden, normaal), delta `{nieuwe_afwijkingen 111, nieuwe_let_op 10, nieuwe_fouten 0, verdwenen_afwijkingen 10, verdwenen_fouten 174, blokken_fout []}`.

## Wat er inhoudelijk staat

De motor van 19-09 heeft zijn werk op 19-09 18:01 al gedaan (nazorg per administratie); de échte run van 20-09 had niets meer om te zetten en
liet dat correct zien: kantoorbreed 0 kandidaten, geen enkele autotype-auditrij, en de vier oude bevindingen zijn door de generieke
auto-sluiting van 19-09 avond (`_audit_verdwenen_bevindingen`) mét audit gesloten. De enige blijvende Van Boxtel-meldingen zijn precies de
bedoelde: Journaal 4-9 (zacht signaal omzetrekeningen, knop "Type wijzigen → kassarapport") en de acht al in RLZ geboekte journalen
(`omzet_in_inkoopstroom`, herboeken achter de aangiftepoort — mens-werk).

**Meetrecept-les (herhaling van de les uit de ic_spiegel-nameting van vanochtend):** de verwachting "audit `kassarapport_autotype_run` verwacht 0 /
gedaan 0" stond in de opdracht zonder de schrijvende functie aan te wijzen; de code schrijft die rij bewust alleen bij ≥ 1 kandidaat. Geen fix
nodig — 78 lege rijen per dag zouden ruis zijn en de dagteller leest 0 rijen correct als 0/0. Regel blijft: een verwachting op een audit-/mail-spoor
eerst in de code aanwijzen (`docs/regels/reconciliatie.md`, alinea "Verdwenen FOUTEN verdwijnen niet stil", slotzin).

## Klikpunten (login nodig, lees-only)

- UI-teller "aandacht" op Inzicht › Reconciliatie ná run `55facc7c` van 20-09: verwacht ≤ 176 (proxy; bron `db-lezen` scope-loop van 20-09).
- Instellingen › Boeken, blok Automatiseringen, regel "Kassarapport automatisch typeren": verwacht 20-09 gedaan 0 / overgeslagen 0, 19-09 gedaan 4 (bron `db-lezen` `audit_event` 19-09 16:01 UTC).
- Van Boxtel: eenmalig de zeven rapportcategorieën mappen in het omzet-controlescherm van één van de vier `vraag_open`-documenten (bron `db-lezen` `document` 20-09; defaults 16-09: Wiet/Hash/Joints/Edible vrijgesteld, Dranken/Snacks laag, Headshop hoog) — daarna lopen de andere drie en élk volgend journaal zonder vraag.

## Keuzes die ik zelf gemaakt heb (Peter kijkt niet mee)

- Aandacht-teller niet opnieuw geloopt: de scope-loop van de ic_spiegel-nameting van vanochtend (zelfde run `55facc7c`, zelfde methode) lag er al;
  ik heb het kassarapport-aandeel (5 → 1) zelf op die tsv's nageteld in plaats van 80 queries te herhalen.
- De ontbrekende `kassarapport_autotype_run`-rij als CORRECT gedrag beoordeeld (code aangewezen), niet als bug; geen code gewijzigd.
- Kantoorbrede audit-loop gedraaid op een eigen proxy-poort (5441) naast de losse queries (5440) — `db_lezen.sh` bindt één vaste poort per aanroep.
- Job-log gefilterd op PDF-parser-ruis (pypdf "Ignoring wrong pointing object", fontTools-waarschuwingen): de dry-run leest élk kandidaat-PDF voor de
  herkenning, dat is verwacht; de ene CLI-regel staat letterlijk hierboven.
- Geen WAT_IS_NIEUW-regel (nameting, niets nieuws voor de klant); CLAUDE.md ongewijzigd (regel omzet 4 dekt de feature al); regels-aanvulling alleen in
  `docs/regels/omzet.md` (gemeten-alinea) en BESLISSINGEN-rij.

## Executies (chronologisch)

| Tijd CEST | Executie | Commando | Exit |
|---|---|---|---|
| 04:30–04:44 (UTC) | scheduler-run `55facc7c` | `reconciliatie-alles` (échte dagelijkse run) | 1 = afwijkingen (normaal) |
| 08:45 | `rlz-reconciliatie-qj4cx` | `kassarapport-autotype-nazorg --dry-run` (kantoorbreed, 0 writes) | 0 |

Leesreplica alleen via `scripts/gcp/db_lezen.sh` (READ ONLY, `rlz_lezer`, impersonatie `nameting@`).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/omzet.md` (271 regels)
- `docs/regels/reconciliatie.md` (166 regels)
- `docs/regels/werkloop-productie.md` (184 regels)
