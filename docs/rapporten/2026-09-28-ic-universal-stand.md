# IC-stand Universal-BV's — lees-only meting op de leesreplica (28-09-2026)

**Opdracht (Feiten eerst, blok A/C):** intercompany-stand tussen Universal Verkoop, Universal Nederland, Universal Materiaal en
Universal Steigerbouw uit de leesreplica `rlz-sql2-lees` (`scripts/gcp/db_lezen.sh`, rol `rlz_lezer`, READ ONLY, actor = Peters
Beheerder-id) + het job-log van de reconciliatie-run van vanochtend (Cloud Logging, `rlz-reconciliatie`). Alleen SELECT; niets
gemuteerd; geen persoonsgegevens buiten bedrijfsnamen. Werkt in productie: n.v.t. (meting, geen bouw).

## Samenvatting (≤ 10 regels)

1. **Van de 12 mogelijke richtingen tussen de vier BV's zijn er 2 actief getoetst** (Nederland → Steigerbouw, Verkoop → Steigerbouw);
   de andere 10 hebben wél een afgeleide relatie maar op **basis `naam`, status `afgeleid`** → per regel 16-09 *niet actief* tot een
   Beheerder ze bevestigt (Instellingen › Boeken › Intercompany). Niet getoetst = geen bevinding; dat is zelf de eerste bevinding.
2. **Nederland → Steigerbouw: 98 verkoopfacturen zonder inkoop in RLZ-Steigerbouw, € 238.537,77** (503 verkoop / 405 inkoop gelezen,
   405 op nummer gematcht). Alle 98 staan al drie dagen stabiel (25→26-09 van 101 naar 98 door het schuivende 400-dagenvenster).
3. **Daarvan staan 53 (€ 143.029,43) gewoon OPEN in de module van Steigerbouw** (te_controleren/klaar_om_te_boeken/ter_accordering) —
   het blok telt ze niet als "onderweg" omdat `referentie_norm` leeg is (oude documenten) of `rlz…` heet (voorvoegsel `RLZ-` van de
   RLZ-export-UBL wordt niet gestript) en bij 14 het origineel géén referentie draagt. **Systeemfout in de onderweg-detectie**, geen
   boekhoudkundig gat; het werkelijke gat is kleiner.
4. **36 facturen (€ 84.376,56) zijn nergens in de module** en niet in RLZ-Steigerbouw: nooit aangeleverd. Grootste: 2080143084
   € 21.420,63 (19-08), 2080143318 € 12.200,09 (07-09), 2080143131 € 11.130,84 (31-08).
5. **4 facturen (€ 11.131,78) zijn in de module verwijderd of afgewezen** zonder boeking in RLZ (2080143036, 2080143044 ×2, 2080143048,
   2080143113) — bewust afgewezen of per ongeluk?
6. **Verkoop → Steigerbouw: 3 verkoopfacturen zonder inkoop (€ 1.642,34)** — 2 staan open in de module, 1 (50212076, € 756,26) is nooit
   aangeleverd; én **1 inkoop bij Steigerbouw zonder verkoop bij Verkoop: F/2026/00066, € 692,58, RLZ-04-00003297** — een
   Odoo-nummer, terwijl de module Verkoop als RLZ-administratie toetst (Odoo-koppeling company 3 staat op *alleen lezen*).
7. **Stand per soort:** `ic_ontbreekt_bij_ontvanger` = **meten** (DB-override; dus geen actiemail, geen KPI), `ic_ontbreekt_bij_verkoper`
   = actie (code-default). 0 geaccepteerd, 0 uitgesloten. Er is geen intercompany-leveranciersrij (`intercompany_tegenpartij`) voor
   één van de vier — de eenmalige rij Nederland → Steigerbouw van 08-09 is nooit gezet (0 rijen in scope).
8. **Meting geldig:** venster 2025-08-24 t/m 2026-09-28 (400 dagen), 0 administraties overgeslagen, 0 fouten, geen webfilter; alle vier
   hebben een RLZ-credential en zijn niet uitgesloten.

## Wat Peter moet beslissen

- **A. Richtingen activeren:** de 10 naam-relaties tussen de vier bevestigen (of uitsluiten mét reden) zodat óók Materiaal ↔ Nederland/
  Verkoop en Steigerbouw → Nederland/Verkoop getoetst worden. Nu is alleen "Steigerbouw koopt in" zichtbaar.
- **B. Onderweg-detectie repareren (bouwopdracht):** `module_onderweg` moet (1) het voorvoegsel `RLZ-` strippen (of `normaliseer_referentie`
  krijgt `rlz` als voorvoegsel), (2) lege `referentie_norm` backfillen (`referentie_backfill`), (3) het origineel achter een
  `afgevoerd_duplicaat` meenemen. Verwacht effect: 53 van de 98 bevindingen worden "onderweg in de module".
- **C. De 36 nooit aangeleverde Nederland-facturen** (€ 84.376,56): worden die buiten de module geboekt, of moeten ze via de RLZ-export-
  intake alsnog komen? Pas ná dat antwoord mag `ic_ontbreekt_bij_ontvanger` terug naar `actie`.
- **D. Universal Verkoop — welk systeem is de verkoopbron?** F/2026/00066 komt uit Odoo; de module leest Verkoop als RLZ. Zolang Verkoop
  in twee systemen factureert, mist de IC-toets de Odoo-kant.
- **E. De 4 verwijderde/afgewezen facturen** (€ 11.131,78): terecht?

## 1. Actieve IC-paren tussen de vier (intercompany_relatie)

Alle 14 rijen tussen de vier zijn op 17-09 afgeleid (`bron afgeleid`, `status afgeleid`). Actief = status `bevestigd` óf (`afgeleid` én
basis ≠ `naam`) (`relaties.is_actief`). Identiteiten (KvK) van alle vier zijn op 28-09 uit RLZ gelezen.

| Administratie A | richting (vanuit A) | Administratie B | basis | status | actief? |
|---|---|---|---|---|---|
| Universal Nederland | debiteur (A verkoopt aan B) | Universal Steigerbouw | kvk | afgeleid | **ja** |
| Universal Steigerbouw | crediteur (B levert aan A) | Universal Nederland | kvk | afgeleid | **ja** (tegenrelatie) |
| Universal Verkoop | debiteur | Universal Steigerbouw | kvk | afgeleid | **ja** |
| Universal Steigerbouw | crediteur | Universal Verkoop | kvk | afgeleid | **ja** (tegenrelatie) |
| Universal Materiaal | crediteur | Universal Nederland | naam | afgeleid | nee |
| Universal Materiaal | crediteur | Universal Verkoop | naam | afgeleid | nee |
| Universal Materiaal | debiteur | Universal Nederland ("Universal Nederland BV") | naam | afgeleid | nee |
| Universal Materiaal | debiteur | Universal Verkoop | naam | afgeleid | nee |
| Universal Nederland | debiteur | Universal Materiaal | naam | afgeleid | nee |
| Universal Nederland | debiteur | Universal Verkoop | naam | afgeleid | nee |
| Universal Verkoop | crediteur | Universal Materiaal | naam | afgeleid | nee |
| Universal Verkoop | crediteur | Universal Nederland | naam | afgeleid | nee |
| Universal Verkoop | debiteur | Universal Materiaal ("Universal Materiaal BV") | naam | afgeleid | nee |
| Universal Verkoop | debiteur | Universal Nederland | naam | afgeleid | nee |

**Handelsrelaties (verkoper → ontvanger) en hun toetsstand:**

| verkoper → ontvanger | stand | reden |
|---|---|---|
| Nederland → Steigerbouw | getoetst | kvk-paar + tegenrelatie |
| Verkoop → Steigerbouw | getoetst | kvk-paar + tegenrelatie |
| Materiaal → Nederland | **niet getoetst** | alleen naam-relaties (beide kanten), niet bevestigd |
| Materiaal → Verkoop | **niet getoetst** | idem |
| Nederland → Materiaal | **niet getoetst** | idem |
| Nederland → Verkoop | **niet getoetst** | idem |
| Verkoop → Materiaal | **niet getoetst** | idem |
| Verkoop → Nederland | **niet getoetst** | idem |
| Steigerbouw → Nederland / Verkoop / Materiaal | **ontbreekt** | geen debiteur-relatie vanuit Steigerbouw afgeleid (geen KvK-/naam-treffer onder de debiteuren van Steigerbouw) |
| Materiaal → Steigerbouw, Nederland → Materiaal e.a. | zie boven | — |

Waarom `naam` en niet `kvk`: de crediteur-/debiteurrecords van deze BV's bij elkaar dragen kennelijk geen KvK-nummer, behalve
Steigerbouw-records (KvK 94539820) — die matchten op KvK. Alleen naam-treffers vereisen per regel 16-09 een Beheerder-bevestiging.

**`intercompany_tegenpartij`** (leveranciersvlag "accordering overslaan"): **0 rijen** in de scope van elk van de vier. De eenmalige rij
Nederland → Steigerbouw (BESLISSINGEN "INTERCOMPANY-LEVERANCIERS INSTELBAAR + EENMALIGE RIJ UNIVERSAL", script
`scripts/gcp/intercompany_universal_08-09.sh`) stond op 09-09 als "NIET UITGEVOERD (gcloud-sessie verlopen)" en is dat nog.

## 2. Bevindingen uit de laatste afgeronde run

Run `80464c0b` (scheduler, 28-09 04:30–04:50 UTC, exit 1). Blok `intercompany`: 4.381 gecontroleerd, 208 afwijkingen kantoorbreed,
17 LET-OP, 0 fouten, 0 geaccepteerd; job-log: "14/31 handelsrelatie(s) getoetst, 1 onderweg in de module, spiegelparen 185 groen /
0 rood, 0 administratie(s) overgeslagen, 0 fout(en)". Venster **2025-08-24 t/m 2026-09-28 (400 dagen, `VENSTER_DAGEN`)**.
Stand per soort (`reconciliatie_instelling.soort_standen`): `ic_ontbreekt_bij_ontvanger` **meten**; `ic_ontbreekt_bij_verkoper`,
`ic_bedrag_verschilt`, `ic_status_verschilt` code-default **actie**. Voor de vier BV's: 0 × `ic_bedrag_verschilt`, 0 ×
`ic_status_verschilt`, 0 geaccepteerd (`reconciliatie_acceptatie` leeg voor Steigerbouw en Verkoop).

### Overzicht per handelsrelatie en soort

| verkoper → ontvanger | soort | stand | aantal | totaal |
|---|---|---|---|---|
| Universal Nederland → Universal Steigerbouw | `ic_ontbreekt_bij_ontvanger` | meten | 98 | € 238.537,77 |
| Universal Verkoop → Universal Steigerbouw | `ic_ontbreekt_bij_ontvanger` | meten | 3 | € 1.642,34 |
| Universal Verkoop → Universal Steigerbouw | `ic_ontbreekt_bij_verkoper` | actie | 1 | € 692,58 |

**Waar staat het ontbrekende stuk werkelijk?** (module-documenten van Steigerbouw op referentie/nummer, leesreplica)

| verkoper | klasse | aantal | totaal |
|---|---|---|---|
| Universal Nederland | staat OPEN in de module van Steigerbouw — onderweg, niet als zodanig herkend | 39 | € 117.156,50 |
| Universal Nederland | NIET in de module en NIET in RLZ van Steigerbouw — nooit aangeleverd | 36 | € 84.376,56 |
| Universal Nederland | staat OPEN in de module (origineel zonder referentie), kopie als duplicaat afgevoerd | 14 | € 25.872,93 |
| Universal Nederland | RLZ-concept bij de verkoper (Status 1, € 0,00, geen nummer) — huls, geen factuur | 5 | € 0,00 |
| Universal Nederland | in de module alleen verwijderd/afgewezen — nergens geboekt | 4 | € 11.131,78 |
| Universal Verkoop | staat OPEN in de module van Steigerbouw — onderweg, niet als zodanig herkend | 2 | € 886,08 |
| Universal Verkoop | NIET in de module en NIET in RLZ van Steigerbouw — nooit aangeleverd | 1 | € 756,26 |

Leesbewijs onderweg-detectie (`factuurmatch.module_onderweg` vergelijkt `boekvoorstel.referentie_norm` met het genormaliseerde
RLZ-nummer): `RLZ-2080142200` → `referentie_norm` = `rlz2080142200` (≠ `2080142200`; `rlz` staat niet in `_REFERENTIE_VOORVOEGSELS`),
`RLZ-2080142898` en `50212045` → `referentie_norm` LEEG (documenten van 02-09, vóór de backfill?); `50211705` → `50211705` = de ene
"onderweg" die het blok wél zag. Van de 129 open documenten in Steigerbouw dragen 32 een `rlz…`-norm.


### Universal Nederland B.V. → Universal Steigerbouw B.V. — `ic_ontbreekt_bij_ontvanger` (98 rijen, € 238.537,77)

Verkoop in RLZ-Nederland/-Verkoop (Status 2 = geboekt/open, 3 = betaald, 1 = concept); geen inkoop in RLZ-Steigerbouw. Kolom "module" = documenten in de module van Steigerbouw met dit nummer.

| factuurnummer | datum | bedrag | RLZ-status verkoper | module Steigerbouw (document, binnen, referentie_norm) | wat ontbreekt waar |
|---|---|---|---|---|---|
| 2080141882 | 2026-03-27 | −€ 338,38 | 2 | — | niet aangeleverd |
| 2080142200 | 2026-05-04 | € 1.225,13 | 2 | klaar_om_te_boeken (3dccd27e, binnen 2026-09-02, norm `rlz2080142200`) | open in module |
| 2080142536 | 2026-06-01 | € 7.780,48 | 2 | — | niet aangeleverd |
| — (RLZ-concept zonder nummer) | 2026-06-01 | € 0,00 | 1 | — | concept-huls verkoper |
| 2080142604 | 2026-06-11 | € 8.601,61 | 2 | — | niet aangeleverd |
| 2080142619 | 2026-06-23 | € 402,88 | 2 | — | niet aangeleverd |
| 2080142625 | 2026-06-30 | € 908,89 | 2 | — | niet aangeleverd |
| — (RLZ-concept zonder nummer) | 2026-07-01 | € 0,00 | 1 | — | concept-huls verkoper |
| 2080142870 | 2026-07-13 | € 2.420,00 | 2 | — | niet aangeleverd |
| 2080142898 | 2026-07-20 | € 938,06 | 2 | te_controleren (250895e8, binnen 2026-09-02, norm leeg) | open in module |
| 2080143029 | 2026-08-01 | € 155,56 | 2 | — | niet aangeleverd |
| 2080143030 | 2026-08-01 | € 1.246,72 | 2 | — | niet aangeleverd |
| 2080143031 | 2026-08-01 | € 105,96 | 2 | — | niet aangeleverd |
| 2080143032 | 2026-08-01 | € 392,48 | 2 | te_controleren (1047ce1b, binnen 2026-09-02, norm `rlz2080143032`) | open in module |
| 2080143033 | 2026-08-01 | € 1.251,68 | 2 | — | niet aangeleverd |
| 2080143034 | 2026-08-01 | € 902,67 | 2 | — | niet aangeleverd |
| 2080143035 | 2026-08-01 | € 2.162,75 | 2 | — | niet aangeleverd |
| 2080143036 | 2026-08-01 | € 783,17 | 2 | verwijderd (3cf08a56, binnen 2026-09-02) | alleen verwijderd/afgewezen in module |
| 2080143038 | 2026-08-01 | € 2.540,14 | 2 | — | niet aangeleverd |
| 2080143040 | 2026-08-01 | € 1.395,41 | 2 | — | niet aangeleverd |
| 2080143041 | 2026-08-01 | € 529,07 | 2 | — | niet aangeleverd |
| 2080143042 | 2026-08-01 | € 2.258,31 | 2 | — | niet aangeleverd |
| 2080143043 | 2026-08-01 | € 254,31 | 2 | — | niet aangeleverd |
| 2080143044 | 2026-08-01 | € 2.319,44 | 2 | afgewezen (bc807ffd, binnen 2026-09-24); afgewezen (0184111d, binnen 2026-09-24) | alleen verwijderd/afgewezen in module |
| 2080143047 | 2026-08-01 | € 315,01 | 2 | — | niet aangeleverd |
| 2080143048 | 2026-08-01 | € 6.621,04 | 2 | verwijderd (7bb1ec97, binnen 2026-09-02) | alleen verwijderd/afgewezen in module |
| 2080143049 | 2026-08-01 | € 187,45 | 2 | — | niet aangeleverd |
| 2080143050 | 2026-08-01 | € 2.333,09 | 2 | — | niet aangeleverd |
| 2080143052 | 2026-08-01 | € 650,34 | 2 | klaar_om_te_boeken (7e3a8d73, binnen 2026-09-02, norm leeg) | open in module |
| 2080143053 | 2026-08-01 | € 3.008,18 | 2 | — | niet aangeleverd |
| 2080143056 | 2026-08-01 | € 6.536,88 | 2 | klaar_om_te_boeken (80aae760, binnen 2026-09-02, norm leeg) | open in module |
| — (RLZ-concept zonder nummer) | 2026-08-01 | € 0,00 | 1 | — | concept-huls verkoper |
| 2080143086 | 2026-08-17 | € 2.295,55 | 2 | — | niet aangeleverd |
| 2080143084 | 2026-08-19 | € 21.420,63 | 2 | te_controleren (8e19d9de, binnen 2026-09-02, norm leeg) | open in module |
| 2080143087 | 2026-08-19 | € 80,08 | 2 | te_controleren (7070f71a, binnen 2026-09-02, norm leeg) | open in module |
| 2080143088 | 2026-08-19 | € 36,30 | 2 | — | niet aangeleverd |
| 2080143089 | 2026-08-19 | € 212,15 | 2 | te_controleren (dc4d8bf3, binnen 2026-09-02, norm `rlz2080143089`) | open in module |
| 2080143091 | 2026-08-21 | € 9.526,85 | 2 | — | niet aangeleverd |
| 2080143092 | 2026-08-21 | € 8.373,68 | 2 | — | niet aangeleverd |
| 2080143093 | 2026-08-21 | € 96,80 | 2 | — | niet aangeleverd |
| 2080143094 | 2026-08-21 | € 214,01 | 2 | — | niet aangeleverd |
| 2080143099 | 2026-08-24 | −€ 2.065,57 | 3 | te_controleren (1f1528d9, binnen 2026-09-02, norm leeg) | open in module |
| 2080143100 | 2026-08-24 | € 1.247,13 | 2 | — | niet aangeleverd |
| 2080143101 | 2026-08-24 | € 3.427,59 | 2 | — | niet aangeleverd |
| 2080143102 | 2026-08-24 | € 1.422,79 | 2 | — | niet aangeleverd |
| 2080143110 | 2026-08-26 | € 1.632,51 | 2 | — | niet aangeleverd |
| 2080143113 | 2026-08-26 | € 1.408,13 | 2 | verwijderd (977b3921, binnen 2026-09-02) | alleen verwijderd/afgewezen in module |
| 2080143115 | 2026-08-27 | € 237,16 | 2 | — | niet aangeleverd |
| 2080143117 | 2026-08-28 | € 1.342,59 | 2 | — | niet aangeleverd |
| 2080143118 | 2026-08-28 | € 3.016,57 | 2 | te_controleren (336d694e, binnen 2026-09-02, norm `rlz2080143118`); te_controleren (ac15816f, binnen 2026-09-25, norm `rlz2080143118`) | open in module |
| 2080143125 | 2026-08-28 | € 4.733,81 | 2 | — | niet aangeleverd |
| 2080143126 | 2026-08-31 | € 237,16 | 2 | — | niet aangeleverd |
| 2080143130 | 2026-08-31 | € 129,09 | 2 | te_controleren (9c9dc98d, binnen 2026-09-02, norm `rlz2080143130`) | open in module |
| 2080143131 | 2026-08-31 | € 11.130,84 | 2 | — | niet aangeleverd |
| 2080143132 | 2026-08-31 | € 1.172,36 | 2 | te_controleren (f27adc33, binnen 2026-09-23, norm `rlz2080143132`) | open in module |
| 2080143261 | 2026-09-01 | € 540,69 | 2 | origineel te_controleren (ca68a337) zónder referentie; kopie afgevoerd_duplicaat (5458ca39) | open in module (origineel zonder ref.) |
| 2080143262 | 2026-09-01 | € 15.594,49 | 2 | te_controleren (4af98d21, binnen 2026-09-02, norm leeg) | open in module |
| 2080143263 | 2026-09-01 | € 2.379,02 | 2 | ter_accordering (a9bbccb3, binnen 2026-09-02, norm `rlz2080143263`) | open in module |
| 2080143264 | 2026-09-01 | € 3.213,09 | 2 | origineel te_controleren (18dd088c) zónder referentie; kopie afgevoerd_duplicaat (cb9d4f96) | open in module (origineel zonder ref.) |
| 2080143265 | 2026-09-01 | € 1.553,57 | 2 | te_controleren (c037773e, binnen 2026-09-23, norm `rlz2080143265`) | open in module |
| 2080143266 | 2026-09-01 | € 8.099,38 | 2 | te_controleren (3721ed92, binnen 2026-09-02, norm leeg) | open in module |
| 2080143267 | 2026-09-01 | € 297,18 | 2 | origineel te_controleren (d31415fd) zónder referentie; kopie afgevoerd_duplicaat (683e4dbf) | open in module (origineel zonder ref.) |
| 2080143268 | 2026-09-01 | € 1.293,49 | 2 | te_controleren (415263a5, binnen 2026-09-02, norm `rlz2080143268`) | open in module |
| 2080143269 | 2026-09-01 | € 112,87 | 3 | te_controleren (a78cf016, binnen 2026-09-23, norm `rlz2080143269`) | open in module |
| 2080143270 | 2026-09-01 | € 2.130,48 | 2 | te_controleren (cd82616d, binnen 2026-09-23, norm `rlz2080143270`) | open in module |
| 2080143271 | 2026-09-01 | € 239,92 | 2 | te_controleren (b9464630, binnen 2026-09-23, norm `rlz2080143271`) | open in module |
| 2080143272 | 2026-09-01 | € 1.072,40 | 2 | te_controleren (3dbc0461, binnen 2026-09-23, norm `rlz2080143272`) | open in module |
| 2080143273 | 2026-09-01 | € 6.246,26 | 2 | origineel te_controleren (c5dca47f) zónder referentie; kopie afgevoerd_duplicaat (70cf8da3) | open in module (origineel zonder ref.) |
| 2080143274 | 2026-09-01 | € 2.225,23 | 2 | te_controleren (f4f3c8d3, binnen 2026-09-23, norm `rlz2080143274`) | open in module |
| 2080143275 | 2026-09-01 | € 1.153,34 | 2 | origineel te_controleren (edd5177d) zónder referentie; kopie afgevoerd_duplicaat (971b7304) | open in module (origineel zonder ref.) |
| 2080143276 | 2026-09-01 | € 2.270,00 | 2 | origineel te_controleren (572fde47) zónder referentie; kopie afgevoerd_duplicaat (4720eff3) | open in module (origineel zonder ref.) |
| 2080143277 | 2026-09-01 | € 153,11 | 2 | origineel te_controleren (3dc873c1) zónder referentie; kopie afgevoerd_duplicaat (89fd6589) | open in module (origineel zonder ref.) |
| 2080143278 | 2026-09-01 | € 2.837,91 | 2 | origineel te_controleren (6d92d033) zónder referentie; kopie afgevoerd_duplicaat (158ba8fe) | open in module (origineel zonder ref.) |
| 2080143279 | 2026-09-01 | € 4.526,46 | 2 | origineel te_controleren (c3c68e18) zónder referentie; kopie afgevoerd_duplicaat (bc221414) | open in module (origineel zonder ref.) |
| 2080143280 | 2026-09-01 | € 555,69 | 2 | origineel te_controleren (28a38785) zónder referentie; kopie afgevoerd_duplicaat (44dfeccc) | open in module (origineel zonder ref.) |
| 2080143281 | 2026-09-01 | € 2.564,15 | 2 | origineel te_controleren (0e9e4496) zónder referentie; kopie afgevoerd_duplicaat (dfb1395e) | open in module (origineel zonder ref.) |
| 2080143282 | 2026-09-01 | € 831,46 | 2 | te_controleren (2fa53233, binnen 2026-09-23, norm `rlz2080143282`) | open in module |
| 2080143283 | 2026-09-01 | € 75,63 | 2 | origineel te_controleren (c7124a5b) zónder referentie; kopie afgevoerd_duplicaat (6be770aa) | open in module (origineel zonder ref.) |
| 2080143284 | 2026-09-01 | € 700,26 | 2 | origineel te_controleren (53c7683c) zónder referentie; kopie afgevoerd_duplicaat (3386ecc0) | open in module (origineel zonder ref.) |
| 2080143285 | 2026-09-01 | € 1.210,27 | 2 | te_controleren (b8b32253, binnen 2026-09-23, norm `rlz2080143285`) | open in module |
| 2080143286 | 2026-09-01 | € 739,16 | 2 | origineel te_controleren (cbe5cc04) zónder referentie; kopie afgevoerd_duplicaat (933a5ef4) | open in module (origineel zonder ref.) |
| 2080143287 | 2026-09-01 | € 469,58 | 2 | te_controleren (d1f5ac71, binnen 2026-09-23, norm `rlz2080143287`) | open in module |
| 2080143288 | 2026-09-01 | € 2.705,50 | 2 | te_controleren (a6ee377b, binnen 2026-09-23, norm `rlz2080143288`) | open in module |
| 2080143289 | 2026-09-01 | € 253,56 | 2 | te_controleren (e853ba65, binnen 2026-09-23, norm `rlz2080143289`) | open in module |
| 2080143290 | 2026-09-01 | € 1.038,70 | 2 | te_controleren (2fdcb388, binnen 2026-09-23, norm `rlz2080143290`) | open in module |
| 2080143291 | 2026-09-01 | € 1.555,64 | 2 | te_controleren (465cba80, binnen 2026-09-23, norm `rlz2080143291`) | open in module |
| — (RLZ-concept zonder nummer) | 2026-09-01 | € 0,00 | 1 | — | concept-huls verkoper |
| 2080143314 | 2026-09-03 | € 2.576,27 | 2 | te_controleren (f3405299, binnen 2026-09-23, norm `rlz2080143314`) | open in module |
| 2080143315 | 2026-09-04 | € 151,59 | 2 | te_controleren (2a83eeea, binnen 2026-09-23, norm `rlz2080143315`) | open in module |
| 2080143318 | 2026-09-07 | € 12.200,09 | 2 | te_controleren (40004a7f, binnen 2026-09-23, norm `rlz2080143318`) | open in module |
| 2080143323 | 2026-09-09 | € 1.843,25 | 2 | te_controleren (e2dd9a23, binnen 2026-09-23, norm `rlz2080143323`) | open in module |
| 2080143324 | 2026-09-09 | € 9.132,04 | 2 | te_controleren (ff0424bb, binnen 2026-09-23, norm `rlz2080143324`) | open in module |
| — (RLZ-concept zonder nummer) | 2026-09-09 | € 0,00 | 1 | — | concept-huls verkoper |
| 2080143331 | 2026-09-11 | € 2.994,98 | 2 | te_controleren (1a2456ee, binnen 2026-09-23, norm `rlz2080143331`) | open in module |
| 2080143332 | 2026-09-16 | € 118,58 | 2 | te_controleren (a7a21207, binnen 2026-09-23, norm `rlz2080143332`) | open in module |
| 2080143334 | 2026-09-16 | € 6.938,81 | 2 | te_controleren (09791a3f, binnen 2026-09-23, norm `rlz2080143334`) | open in module |
| 2080143335 | 2026-09-16 | −€ 112,87 | 3 | te_controleren (6fb90253, binnen 2026-09-23, norm `rlz2080143335`) | open in module |
| 2080143336 | 2026-09-16 | € 4.840,00 | 2 | te_controleren (88e22502, binnen 2026-09-23, norm `rlz2080143336`) | open in module |

### Universal Verkoop B.V. → Universal Steigerbouw B.V. — `ic_ontbreekt_bij_ontvanger` (3 rijen, € 1.642,34)

Verkoop in RLZ-Nederland/-Verkoop (Status 2 = geboekt/open, 3 = betaald, 1 = concept); geen inkoop in RLZ-Steigerbouw. Kolom "module" = documenten in de module van Steigerbouw met dit nummer.

| factuurnummer | datum | bedrag | RLZ-status verkoper | module Steigerbouw (document, binnen, referentie_norm) | wat ontbreekt waar |
|---|---|---|---|---|---|
| 50212045 | 2026-07-06 | € 711,84 | 2 | te_controleren (e8365349, binnen 2026-09-02, norm leeg) | open in module |
| 50212076 | 2026-07-09 | € 756,26 | 2 | — | niet aangeleverd |
| 50212138 | 2026-07-20 | € 174,24 | 2 | te_controleren (fbdc6284, binnen 2026-09-02, norm leeg) | open in module |

### Universal Verkoop B.V. → Universal Steigerbouw B.V. — `ic_ontbreekt_bij_verkoper` (1 rij, stand actie)

| factuurnummer | datum | bedrag | inkoop Steigerbouw | verkoop Verkoop | wat ontbreekt waar |
|---|---|---|---|---|---|
| F/2026/00066 | 2026-09-10 | € 692,58 | RLZ-04-00003297 (module-document 625d6b10, geboekt, binnen 17-09) | niet in RLZ-Verkoop (20 verkopen aan Steigerbouw in het venster, alle 50212xxx) | verkoopfactuur ontbreekt bij de verkoper zoals de module hem leest; nummer heeft Odoo-vorm (koppeling company 3 "Universal Verkoop B.V.", alleen_lezen = true, aangemaakt 04-09) |

Vingerafdrukken: staan per rij in `reconciliatie_bevinding.vingerafdruk` van run `80464c0b` (blok `intercompany`, administratie
Steigerbouw `3ee6edf0` resp. Verkoop `0d66ff75`); in het job-log als `[vaf:…]`. Voorbeelden: 2080143084 `[vaf:…]` zie log 04:35:39–40Z,
F/2026/00066 `b412088025014388`, 50212045 `d45b8fbb0caf3c03`, 50212076 `13522b13fa78b3a3`, 50212138 `091c67ae4eed581e`,
2080143335 `9840867052919390`, 2080143336 `17c52b7ef67a3028`.

### Trend (afwijkingen bij Steigerbouw, laatste 6 runs)

| dag | Nederland → Steigerbouw | Verkoop → Steigerbouw |
|---|---|---|
| 23-09, 24-09, 25-09 | 101 | 3 |
| 26-09, 27-09, 28-09 | 98 | 3 |

De daling 101 → 98 is het venster dat van 2025-08-22 naar 2025-08-24 schoof, geen herstel.

## 3. Venster, overgeslagen administraties en geldigheid

- `VENSTER_DAGEN` = 400 → venster **2025-08-24 t/m 2026-09-28** (job-log: "39 actieve IC-paren → 31 handelsrelatie(s)").
- **Overgeslagen: 0. Ongeldig (RlzWebfilterError/leesfout): 0. Fouten: 0.** Alle vier BV's: `boekhoud_backend rlz`, 1 RLZ-credential,
  `reconciliatie_uitgesloten` false, niet gearchiveerd. Er staan geen `fout`-/`uitgesloten`-rijen in het IC-blok van deze run
  (run-samenvatting `fouten 0, uitgesloten 0`).
- De meting voor de twee getoetste relaties is dus **geldig**. Voor de tien niet-actieve richtingen is er géén meting (zie §1).
- Universal Verkoop heeft náást de RLZ-credential een Odoo-koppeling (company 3, alleen lezen). Het IC-blok leest Verkoop
  uitsluitend via RLZ (`boekhoud_backend`); Odoo-verkoopfacturen van Verkoop vallen buiten deze toets.

## Meetrecept (herhaalbaar, lees-only)

1. `scripts/gcp/db_lezen.sh "<SELECT>" --als <Beheerder-uuid>` op `platform.administratie`, `boekhouding.intercompany_relatie`,
   `administratie_identiteit`, `reconciliatie_run`, `reconciliatie_instelling` (geen scope nodig).
2. Per administratie mét `--administratie <uuid>` (scope-only RLS): `reconciliatie_bevinding` (blok `intercompany`, run-id),
   `intercompany_tegenpartij`, `reconciliatie_acceptatie`, `document` ⋈ `boekvoorstel` op referentie.
3. `gcloud logging read` op job `rlz-reconciliatie` 04:30–04:51 UTC voor de regels `Venster …`, `N/M handelsrelatie(s) getoetst …`
   en de paar-regels `AFWIJKING <uuid> (A → B): … verkoop / … inkoop gelezen …`.

## Gelezen regels

- `docs/regels/doorbelasting-intercompany.md` (232 regels)
- `docs/regels/reconciliatie.md` (306 regels)
- `docs/regels/werkloop-productie.md` (332 regels)
- CLAUDE.md; `backend/app/intercompany/{models,relaties,factuurmatch}.py`; `app/reconciliatie/soort_stand.py`; `app/documenten/referentie.py`;
  `app/doorbelasting/models.py` (IntercompanyTegenpartij); `scripts/gcp/db_lezen.sh`, `scripts/gcp/intercompany_universal_08-09.sh`;
  BESLISSINGEN "INTERCOMPANY-LEVERANCIERS INSTELBAAR + EENMALIGE RIJ UNIVERSAL".
