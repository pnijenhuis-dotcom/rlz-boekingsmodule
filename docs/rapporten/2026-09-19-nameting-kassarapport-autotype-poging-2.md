# Nameting + nazorg kassarapport automatisch typeren — poging 2 (19-09, 18:00–18:15): WERKT IN PRODUCTIE: JA (motor, nazorg per administratie, tijdlijn, audit, omzetpad, bevinding-verdwijning); NEE voor de kantoorbrede nazorg-CLI (NameError, gefixt in deze run, deploy volgt); niet gemeten: aandacht-teller, auto-sluiting, dagteller-UI (pas ná de échte run van 20-09 06:30)

**Opdracht:** `opdrachten/gedaan/2026-09-19-nameting-kassarapport-autotype-na-deploy-poging-2.md` (vervolg op
`docs/rapporten/2026-09-19-nameting-kassarapport-autotype-poging-1-deploy-geblokkeerd.md`, waar de nulmeting Van Boxtel staat).
Domeinen: omzet, reconciliatie, werkloop-productie.

## Werkt in productie: ja (mét één nee)

| Onderdeel | Uitkomst | Bewijs |
|---|---|---|
| Nazorg-CLI `--dry-run --administratie "Van Boxtel"` | **JA** — "1 administratie(s), 4 kandidaat/kandidaten, zou omzetten 4, overgeslagen —" = Journaal 31-8, 1-9, 2-9, 3-9; Journaal 4-9 géén kandidaat | executie `rlz-reconciliatie-bcc6b`, 18:00 CEST, image `backend:764072a` |
| Nazorg-CLI echt, Van Boxtel | **JA** — "omgezet 4, overgeslagen —", 4 × `gedaan … ProfX-journaal` | executie `rlz-reconciliatie-hpjtd`, 18:01 |
| Vier documenten soort `kassarapport` | **JA** — `8631403e`/`37e1b23e`/`cbef27bc`/`0b571db4` soort `kassarapport`, `laatst_gewijzigd_op` 18:01:18–19; Journaal 4-9 (`4e120087`) ongewijzigd `inkoopfactuur`/`te_controleren` | leesreplica, 18:05 |
| Tijdlijn per document | **JA** — `te_controleren → ontvangen` "type automatisch gewijzigd: inkoopfactuur → kassarapport (ProfX-journaal herkend)" → `extractie_bezig` → `te_controleren` "omzetbron deterministisch gelezen (geen AI) — ter controle" (veldvoorstel bron `profx_journaal`, regels per artikelgroep) → `vraag_open` "Nieuwe rapportcategorie(ën) zonder GB/btw-mapping: Dranken, Edible, Hash, Headshop, Joints, Snacks, Wiet" | leesreplica `document_gebeurtenis`, 16 rijen |
| Audit | **JA** — 4 × `soort_automatisch_gewijzigd` (nieuwe waarde: bron `profx_journaal`, ingang `werkvoorraad`, afzender debazarapeldoorn@…) + 1 × `kassarapport_autotype_run` `{"verwacht": 4, "gedaan": 4, "overgeslagen": {}, "bronnen": ["profx_journaal"]}`, actor = systeem (`00000000…`) | leesreplica `platform.audit_event`, 18:01:17–20 |
| `reconciliatie-alles --alleen omzet --lees-only` | **JA** — Van Boxtel: **1 × `kassarapport_in_werkvoorraad`** (Journaal 4-9, "signaal omzetrekeningen, 1/1 regels op een omzetrekening — type wijzigen naar kassarapport"), **0 × profx**, **8 × `omzet_in_inkoopstroom`** (RLZ-04-00000684…699, Journaal 5-9 t/m 13-9) ongewijzigd; kantoorbreed 9 afwijkingen, alle Van Boxtel, 0 mislukte administraties | executie `rlz-reconciliatie-tp6ng` via `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh`, ruwe uitvoer `.scratch/nameting-omzet-19-09-poging2.txt` (lokaal, niet gecommit) |
| Nazorg-CLI kantoorbreed `--dry-run` (zonder `--administratie`) | **NEE** — `NameError: name 'scoped_session' is not defined` (`app/cli.py:549`), exit 1 | executie `rlz-reconciliatie-m6pst`, 18:02 — zie "Bug gevonden + gefixt" |
| Dagteller `kassarapport_autotype` gedaan 4 (Instellingen › Boeken / systeemmail) | **afgeleid, UI niet gemeten** — de teller leest exact de vijf audit-rijen hierboven (`automatiseringen.py` KASSARAPPORT_AUTOTYPE); de systeemmail komt pas bij de échte run | — |
| Inzicht › Reconciliatie 340 → 336 aandacht; auto-sluiting van de 4 profx-bevindingen (`reconciliatie_auto_gesloten`) | **niet gemeten** — een lees-only run legt niets vast (regel werkloop-productie 19-09 punt 3); meetbaar ná de échte run 20-09 06:30 | vervolg-opdracht in de inbox |

## Stap 0 (deploy-check) — groen

- `git fetch origin` → `main..origin/main` = 0, `origin/main..main` = 0 (geen divergentie, geen merge nodig).
- Deploy-runs 35453174871 (`764072a`), 35451558371 (`a731dd4`), 35449947839 (`1dab82c`) alle groen; `git merge-base --is-ancestor a5c0663` waar voor
  alle drie.
- Service `rlz-backend` én job `rlz-reconciliatie` op `europe-west4-docker.pkg.dev/rlz-boekhouding/rlz/backend:764072ad…` (identiek).

## Wat er inhoudelijk gebeurde (Van Boxtel Horeca Exploitatie B.V.)

De vier ProfX-journalen die sinds 08-09 als inkoopfactuur `te_controleren` stonden, zijn door de nazorg-run in één seconde per document
omgezet: soort → `kassarapport`, status → ONTVANGEN, extractie opnieuw via het omzetpad (deterministische ProfX-parser, géén AI) →
`te_controleren` mét veldvoorstel per artikelgroep → **automatische vraag** "Nieuwe rapportcategorie(ën) zonder GB/btw-mapping" → `vraag_open`.
Dat laatste is bestaand, bedoeld gedrag van de omzetmodule (mapping-loze categorie = blokkerende check + automatische vraag, regel omzet.md
"Omzetboekingen"): Van Boxtel heeft nog geen categorie → grootboek/btw-mapping. **Handeling kantoor (eenmalig, in het omzet-controlescherm van
één van de vier documenten):** de zeven categorieën Dranken/Edible/Hash/Headshop/Joints/Snacks/Wiet mappen (defaults uit 16-09: Wiet/Hash/Joints/
Edible vrijgesteld, Dranken/Snacks laag, Headshop hoog); daarna lopen de andere drie en élk volgend journaal zonder vraag. De vier documenten
staan nu in de omzet-werkvoorraad mét de chip "automatisch getypeerd" en de terugweg "Tóch inkoopfactuur…".

Journaal 4-9 (`4e120087`) blijft terecht een melding mét knop: geen parser-treffer (alleen het zachte signaal "alle regels op een
omzetrekening"), precies zoals de regel van 19-09 zegt. De acht al in RLZ geboekte journalen (5-9 t/m 13-9) blijven `omzet_in_inkoopstroom`
— mens-werk achter de aangiftepoort, buiten deze opdracht.

## Bug gevonden + gefixt: kantoorbrede nazorg-CLI strandde op een ontbrekende import

De kantoorbrede vorm `kassarapport-autotype-nazorg --dry-run` (zonder `--administratie`) gaf op de job-image `NameError: name
'scoped_session' is not defined` (`_kassarapport_autotype_nazorg`, `app/cli.py:549`): de import stond alleen in `_zoek_administraties`,
de tak die de `--administratie`-vorm gebruikt. De bestaande test `test_nazorg_cli_dry_run_schrijft_niets_en_de_echte_run_is_idempotent`
dekte uitsluitend de `--administratie`-tak — de meetlat van de opdracht ("daarna kantoorbreed `--dry-run` = 0 kandidaten") liep dus een
vorm die nooit gedraaid was.

- **Fix (deze run):** `from app.db.session import scoped_session` in `_kassarapport_autotype_nazorg` (één regel, `backend/app/cli.py`).
- **Guard:** `tests/omzet/test_autotype.py::TestReconciliatieRun::test_nazorg_cli_kantoorbreed_zonder_administratie_loopt` — kantoorbrede
  dry-run ("zou omzetten 1"), echte run ("omgezet 1"), tweede dry-run ("0 kandidaat/kandidaten"). Tegenproef gedaan: zonder de fix rood op
  exact de productie-NameError; mét fix 2 passed (beide nazorg-CLI-tests, 3,9 s).
- **Impact productie:** géén. De dagelijkse run gebruikt `autotype.verwerk_werkvoorraad` rechtstreeks (`app/omzet/reconciliatie.py:122`),
  niet de CLI; de per-administratie-nazorg werkte. Alleen de eenmalige kantoorbrede nazorg (andere administraties mét parser-treffers in de
  werkvoorraad) kon niet draaien — de dagelijkse run van 20-09 06:30 doet hetzelfde werk per administratie, dus er blijft niets liggen.
- **Meetlat ná deploy van de fix:** `gcloud run jobs execute rlz-reconciliatie … --args="-m,app.cli,kassarapport-autotype-nazorg,--dry-run"`
  → exit 0, "N administratie(s), 0 kandidaat/kandidaten" (of de kandidaten die de run van 06:30 al omzette). In de vervolg-opdracht.
- **Les (werkloop):** een meetrecept noemt de exacte CLI-vorm; élke vorm die het meetrecept noemt moet in de suite gedraaid zijn (niet
  alleen een zustervorm). Alinea in `docs/regels/werkloop-productie.md`.

## Keuzes die ik zelf gemaakt heb (Peter kijkt niet mee)

- Echte nazorg-run direct ná de groene dry-run (opdracht stap 1), niet wachten op de reconciliatie van 06:30: de dry-run was exact als
  verwacht en de opdracht noemde de echte run als eerste optie.
- De `vraag_open`-uitkomst als CORRECT beoordeeld, geen ingreep: het is het bestaande omzetpad; de mapping is een mens-keuze per administratie
  (categorie → grootboek/btw) en hoort niet in een nameting.
- Bug meteen gefixt + guard toegevoegd in plaats van alleen melden: één regel, bewezen met tegenproef, geen gedragswijziging elders.
- Aandacht-teller en auto-sluiting NIET geforceerd via "Nu draaien" of een échte job-run: dat geeft een actiemail buiten het dagritme
  (regel werkloop-productie 19-09 punt 3). Vervolg-opdracht `opdrachten/inbox/2026-09-20-nameting-kassarapport-autotype-na-echte-run.md`
  mét stap 0 op de fix-commit.
- Ruwe nameting-uitvoer (`.scratch/…`) niet gecommit (geen bot-bestand: `NAMETING_VIA_GH=0`); de tellingen staan letterlijk hierboven.
- Geen WAT_IS_NIEUW-regel: interne CLI-fix, niet klantleesbaar; de feature zelf staat al in WAT_IS_NIEUW van 19-09.

## Executies (chronologisch, alle op `backend:764072a`)

| Tijd CEST | Executie | Commando | Exit |
|---|---|---|---|
| 18:00 | `rlz-reconciliatie-bcc6b` | `kassarapport-autotype-nazorg --dry-run --administratie "Van Boxtel"` | 0 |
| 18:01 | `rlz-reconciliatie-hpjtd` | `kassarapport-autotype-nazorg --administratie "Van Boxtel"` (SCHRIJVEND: 4 documenten) | 0 |
| 18:02 | `rlz-reconciliatie-m6pst` | `kassarapport-autotype-nazorg --dry-run` (kantoorbreed) | 1 — NameError |
| 18:10 | `rlz-reconciliatie-tp6ng` | `reconciliatie-alles --alleen omzet --lees-only` (via nameting.sh, impersonatie nameting@) | 1 = afwijkingen gevonden (normaal) |

Geen RLZ-write, geen migratie, geen lokaal proces tegen de primary (leesreplica alleen via `db_lezen.sh`, READ ONLY).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/omzet.md` (266 regels)
- `docs/regels/reconciliatie.md` (138 regels)
- `docs/regels/werkloop-productie.md` (154 regels)
