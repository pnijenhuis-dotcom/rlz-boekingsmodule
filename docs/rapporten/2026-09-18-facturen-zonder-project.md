# Facturen zonder project (Universal Steigerbouw + alle project-verplichte administraties) — lees-only rapport + inbox-hygiëne

**Opdracht:** `opdrachten/gedaan/2026-09-18-facturen-zonder-project-universal-rapport-en-inbox-hygiene.md` (18-09 avond, TODO
Peter 23-08 "eerst rapport, dan beslissen"). **Lees-only:** geen RLZ-write, geen statuswissel, geen migratie.
**Werkt in productie: n.v.t. (lees-only).** De module-kant is vanavond gemeten op de leesreplica (`scripts/gcp/db_lezen.sh`, READ
ONLY als `nameting@`), de RLZ-aangiftestatus via `nameting.sh rlz-lezen` (Cloud Run-job `rlz-reconciliatie-n9969`, alleen GET); de
RLZ-kant-telling vraagt de nieuwe CLI op de job-image en is **niet gemeten** (deploy volgt ná deze run — meetrecept onderaan).
**BESLISSINGEN:** "FACTUREN ZONDER PROJECT — LEES-ONLY RAPPORT + INBOX-HYGIËNE (18-09 avond)".

## Één regel voor Peter
Universal Steigerbouw heeft in de module **0 geboekte inkoopfacturen die écht zonder project in RLZ staan**: de 5 documenten mét
een lege projectkolom dragen alle een bevroren pro-rato-projectverdeling (8 projecten) en zijn in RLZ per project geboekt; 0
automatisch herstelbaar nodig, 0 achter de aangiftepoort (btw-kwartaal Q3 2026 staat open). De RLZ-kant (facturen van vóór de
module, 2.194 inkoopdocumenten mét project in de cache sinds 2025) is pas meetbaar mét de CLI ná deploy.

## A1 — Wat is gemeten (module-kant, leesreplica 18-09 ~23:05)

Project-verplichte, actieve administraties (`platform.administratie.project_verplicht = true`): 5.

| Administratie | rlz_admin_id | geboekte inkoopfacturen in de module | mét regel zonder project | gedekt door projectverdeling | échte bevinding |
|---|---|---:|---:|---:|---:|
| ARVUM B.V. | 9da1f3ab-… | 5 (6 regels) | 0 | — | 0 |
| Beleggingsmaatschappij Meyer BV | 8d87b05c-… | 0 | 0 | — | 0 |
| B. van Rooijen / G. Schaalje | c28dfbd0-… | 0 | 0 | — | 0 |
| J.G.M. Elissen Holding BV | 291d2d57-… | 0 | 0 | — | 0 |
| **Universal Steigerbouw B.V.** | 3d954fc7-… | **59 (109 regels)** | **5 (5 regels)** | **5** | **0** |

Universal — de vijf documenten (bron: `boekhouding.boekvoorstel_regel.project_id IS NULL` op geboekte inkoopfacturen; geboekt-door
uit de jongste GEBOEKT-overgang in `document_gebeurtenis`; leverancier uit `vendor_cache`; grootboek uit `platform.grootboekrekening`):

| boekstuk RLZ | referentie | leverancier | factuurdatum = boekdatum | geboekt op | regel | gb | netto | btw | geboekt door | dekking |
|---|---|---|---|---|---|---|---:|---:|---|---|
| RLZ-04-00003215 | 202611050 | DCTE B.V. | 2026-07-27 | 2026-09-08 | 1/1 | 4499 | 118,75 | 24,94 | systeem ná klant-akkoord Peter N. (accordering, laag 1) | pro rato juli, 8 projecten, bevroren |
| RLZ-04-00003234 | 202611101 | DCTE B.V. | 2026-08-01 | 2026-09-08 | 1/1 | 4499 | 168,06 | 35,29 | idem | idem |
| RLZ-04-00003236 | 26008 | Floor Beheer B.V. | 2026-08-03 | 2026-09-08 | 1/1 | 4003 | 11.000,00 | 2.310,00 | idem | idem |
| RLZ-04-00003235 | 202611203 | DCTE B.V. | 2026-08-26 | 2026-09-08 | 1/1 | 4499 | 312,51 | 65,63 | idem | idem |
| RLZ-04-00003213 | F212604921 | Kader Consultancy & Interim B.V. | 2026-09-02 | 2026-09-08 | 1/1 | 4606 | 630,00 | 132,30 | idem | idem |

Module-document-id's: b5a0805c-09a7-4979-aaee-8d1638d581de, b6befce8-40f3-4157-ac52-ba68a8c58d3f, 647bc61d-2850-4371-8c53-e56928100072,
167769c0-e0b2-4a76-8837-2d2e5ed90c95, 5485d087-b4fd-48c1-9b7d-c6cf7f7f9be8 (RLZ-document-GUID's in de tijdlijn: 3f422dc6…, 48e1971e…,
e03b7d2c…, f8e82b87…, 83d87ba0…). Geen van de vijf is `automatisch_geboekt`; alle vijf zijn handmatig gecontroleerd (medewerker iris,
"harde checks doorstaan" 07/08-09), door Peter geaccordeerd (laag 1) en door de achtergrondverwerking geboekt.

**Waarom dit géén bevinding is.** `project_verplicht` staat voor Universal aan sinds 21-08 19:51 (audit `project_verplicht_gewijzigd`).
De harde check "Verplichte velden" telt een regel zonder kolom-project als gedekt zodra het document een GELDIGE projectverdeling draagt
(`boekvoorstel._project_verplicht_per_regel`, B3-dekking 04-09, casus Kader Consultancy F212604921 — precies deze leverancier). De
RLZ-adapter splitst zo'n regel bij het boeken in N regels mét `Project` (`app/backends/rlz_inkoop.py::regels_naar_rlz_lines`,
grootste-rest sluitend). Op de replica staat voor alle vijf een `projectverdeling`-rij status `geboekt`, `boek_cyclus 0`,
`geboekt_op 2026-09-08`, pro rato maand juli 2026 op omzet, 8 delen — in RLZ staan dus 8 regels mét project per factuur. De check
heeft dus gewerkt; er is geen lek in het boekpad.

**Observatie voor Peter (geen bevinding, wel iets om te weten):** de pro-rato-verdeling van juli legt kosten op twee projecten
waarvan de RLZ-naam met "Afgesloten" begint (26012 Tilburg (van Kasteren) 22,1 %-aandeel… nee: 26012 draagt 7,7 %, 26051 Opijnen
2,4 %) — omdat die projecten in juli nog omzet hadden. Dat is conform de omzetsleutel; of overhead op een afgesloten project hoort,
is een inhoudelijke keuze (projectstatus 18-09 sluit die projecten nu uit álle keuzelijsten, maar de omzetsleutel kijkt naar omzet,
niet naar status).

**Universal heeft geen OVH-/overheadproject** (0 van 169 projecten heet OVH/overhead/algemeen) — telecom (DCTE, gb 4499) en
consultancy (Kader, gb 4606) gaan nu via de omzetsleutel over lopende projecten. Kernprincipe "overhead → intern OVH-project"
(CLAUDE.md Projecten) is voor Universal dus niet ingericht; dat is een beslispunt, geen fout van de module.

**Leveranciersgeheugen Universal:** DCTE (3 facturen), Floor Beheer (1), Kader (1) hebben géén eigen geboekte regel mét project —
een deterministisch projectvoorstel bestaat voor geen van drie ("mens nodig"). Werknummer-geheugen: één rij (Spot Services 26097 →
25047 Ede (Welling bouw), bron factuur, bevestigd) — niet van toepassing op deze drie.

## A1b — Aangiftestatus Universal (RLZ `TaxDeclarations`, alleen GET, job-executie `rlz-reconciliatie-n9969`)
16 aangiften gelezen: Q3 2026 (01-07 t/m 30-09) **status 1 = open**; Q2 2026 status 3 + suppletie status 2 (ingediend); Q1 2026 en
alle 2025-kwartalen status 3. Alle vijf boekdatums (27-07 … 02-09) vallen in het open kwartaal → zou herstel nodig zijn, dan route (a)
storno 19 → project → her-PUT → 17 voor alle vijf, geen enkele achter de aangiftepoort. Herstel is echter niet nodig (zie A1).

## A1c — RLZ-kant: niet gemeten (meetrecept)
Er bestaat géén cache van RLZ-`JournalEntryLines`/inkoopregels ZONDER project (`project_regel_cache` bevat uitsluitend regels mét
project: 2.194 inkoopdocumenten / 2.638 regels sinds 01-01-2025, sync 18-09). De RLZ-kant leest de nieuwe CLI live (Status 2/3,
`/Lines?$expand=Account,Project`, regel zonder Project op 4xxx/7xxx) en verklaart het verschil op het client-GUID van de module
(`rlz_purchase_invoice_id`/`rlz_herboeking_id`): alles wat RLZ-kant zonder project staat en niet van de module is, is van vóór/
buiten de module. Meetrecept ná deploy (allowlist `scripts/gcp/nameting.sh`):

```
scripts/gcp/nameting.sh facturen-zonder-project --administratie "Universal Steigerbouw" --jaar 2026 --rlz
scripts/gcp/nameting.sh facturen-zonder-project --alle-projectverplicht --jaar 2026
```
Verwachting: module-kant Universal "5 gedekt door projectverdeling, 0 bevinding" (identiek aan dit rapport); RLZ-kant = het aantal
facturen van vóór de module zonder project — nu onbekend, dat getal ís het beslispunt "in bulk herstellen of laten staan".

## A2 — Herstelroute (voorstel, NIET uitgevoerd)
Per rij bepaalt de CLI: (a) btw-periode open → storno 19 → project op de regel(s) → her-PUT (zelfde client-GUID's, idempotent) →
actie 17; (b) periode ingediend (`app/rlz/aangifte.py`, fail-closed bij onleesbaar) → tegenboek-pad; geen credential → "toets nodig",
zichtbaar. Projectvoorstel uitsluitend deterministisch: één bevestigde werknummer-mapping van de leverancier, óf één en hetzelfde
project in ≥ 3 eigen geboekte facturen ("project X, herkomst geheugen N× bevestigd"); meerduidig/te weinig = "mens nodig", nooit
raden. **Schatting per route voor Universal module-kant: (a) 0, (b) 0, mens nodig 0 — alles gedekt.** RLZ-kant: pas ná de meting.

## A3 — Gebouwd (lees-only)
- `backend/app/projecten/zonder_project.py`: module-kant (`module_kant`), dekking door bevroren verdeling (zelfde `boek_cyclus`),
  geboekt-door uit de tijdlijn, routes (`bepaal_routes`), deterministisch voorstel (`project_voorstel`), RLZ-kant (`rlz_kant`,
  uitsluitend `client.get`/`get_lines`), rapportregels.
- CLI `facturen-zonder-project (--administratie X | --alle-projectverplicht) [--jaar] [--rlz]` in `app/projecten/cli_cmd.py`;
  toegevoegd aan de nameting-allowlist (`scripts/gcp/nameting.sh`). Geen migratie.
- Tests `backend/tests/projecten/test_zonder_project.py` (7): bevinding vs gedekt, andere boek_cyclus dekt niet, routes via de
  aangiftepoort + zichtbaar niet-toetsbaar, voorstel alleen deterministisch (eenduidig 3× / meerduidig / te weinig / werknummer),
  RLZ-kant mét fake (concept telt niet, 1600 telt niet, module-GUID herkend), `is_kostenregel_zonder_project` raadt nooit, CLI-poort.

## B — Inbox-hygiëne
**Premisse gecontroleerd.** Bij de start van deze run (22:54) was `opdrachten/lopend/` leeg (alleen `.gitkeep`, mtime 21:25 = het
moment waarop de nameting-run zijn eigen opdracht naar gedaan/ verplaatste). De vijf genoemde opdrachten staan uitsluitend in
`gedaan/` mét kopregel "uitgevoerd 2026-09-18, rapport: …" en hun rapporten bestaan. Er is nooit een `opdrachten/log/<slug>.log` voor
ze geweest en het launchd-log (`~/Library/Logs/cc-inbox.log`) noemt de slugs nergens: ze zijn niet door `cc_inbox.sh` gelopen maar
door de handmatige `rlz cc`-sessie van vandaag (pid 41765, 09:27–19:34, parallelle agenten) afgewerkt en via de commits van 11:52,
13:45, 14:28 en 17:38 in gedaan/ gezet. Bij de eerste tick zonder die lock (19:54) meldde de tick géén verweesde lopend-bestanden, dus
ook toen stond er niets in lopend/. De dubbele kopieën heb ik niet aangetroffen en dus niet kunnen verplaatsen; waarschijnlijk zag
Cowork een tussenstand van die handmatige sessie (of een andere werkkopie).

**Oorzaak-analyse en fix (het gat is echt, ook zonder reproductie).** `herstel_verweesd` in `cc_inbox.sh` zette élk .md in lopend/
zonder levende lock terug in inbox/ en draaide het opnieuw (tot 3×) — óók als dezelfde opdracht al in gedaan/ stond. Een handmatige/
parallelle run die naar gedaan/ kopieert zonder lopend/ op te ruimen zou zo afgerond werk drie keer opnieuw laten draaien én
`lopend/` als "loopt" laten lezen. Sinds deze run: (i) een lopend-bestand waarvan de gedaan-kopie begint met "uitgevoerd " is AF →
kopie opgeruimd, pogingen-teller weg, logregel, geen herstart; (ii) `rlz inbox status` somt lopend/ op als "loopt" (alleen bij een
levende lock), "af (staat in gedaan/…)" of "gestrand (geen levende lock…)" — nooit meer "loopt" voor werk dat af is. Guards:
`tests/unit/test_cc_inbox_herstel.py::test_lopend_kopie_van_afgeronde_opdracht_*` (+ tegenproef zonder kopregel) en
`tests/unit/test_cc_inbox_parallel.py::test_rlz_inbox_status_toont_lopend_*`.

## Beslispunten Peter
1. **Bulk-herstel of laten staan:** module-kant is er niets te herstellen. Het echte getal zit RLZ-kant (facturen van vóór 21-08 en
   buiten de module) — eerst de meting ná deploy draaien (recept A1c); pas dán kiezen. Voorstel: laten staan tenzij Inzicht › Projecten
   die kosten mist voor lopende projecten.
2. **Dagelijkse reconciliatie-bevinding "regel zonder project op een project-verplichte administratie"** (start in `meten`, nooit
   actiemail vóór promotie): ja — als RLZ-kant-toets (module-kant is al hard geblokkeerd). Kost per administratie één Lines-lezing per
   nieuw geboekt document per dag; alleen bouwen ná GO.
3. **OVH-project voor Universal Steigerbouw** aanmaken (overhead-kosten bewust, i.p.v. via de omzetsleutel over lopende én
   afgesloten projecten)? En: mag de pro-rato-sleutel projecten met status afgesloten overslaan?

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/verplichtingen-projecten-voorraad.md` (266 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- `docs/regels/reconciliatie.md` (94 regels)
