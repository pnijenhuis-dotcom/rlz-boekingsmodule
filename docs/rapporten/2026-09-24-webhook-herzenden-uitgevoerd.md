# Webhook-herzenden 11 `factuur_geboekt`-kostenevents aan Vastly — UITGEVOERD 24-09 avond (OPEN_ITEMS regel 13): poging 1 verklaard, afleveraar leest het samengestelde antwoord, poging 2 via de job-route mét bewijs per referentie

**Opdracht (Peter, 24-09 avond):** herzending 11 events afmaken, geen terminalwerk meer voor Peter. (1) Verifieer wat de zes Rubicon-rijen ná de
herzendactie voor status hebben en waarom de afleveraar ze niet oppakt; repareer de herzendactie zodat teruggezette rijen daadwerkelijk meegaan; test.
(2) ARVUM: vind het tweede "ARVUM B.V."-record, stel vast welk id de koppeling en de outbox dragen, herzend de vijf onder het juiste id; meld welk id
Vastly hoort te kennen. (3) Alles zelf via de job-route (gcloud in de run), per referentie de Vastly-respons controleren. (4) Registers + les.
**Bronnen gelezen:** CLAUDE.md, Platform `OPEN_ITEMS.md` regel 13 + het 409-item van 24-09, `app/documenten/webhook_afleveraar.py`, `app/cli.py`
(`_webhook_herzenden`, `_zoek_administratie_id`), `app/lezen/queries/webhook-outbox.sql`, `scripts/gcp/db_lezen.sh`, de twee inbox-/terminal-
opdrachten van 24-09, rapport 23-09; Vastly `src/layer1_functions/rlz_webhook.py` (lees-only: dispatch `_EVENT_VERWERKERS`, regels 365-392,
556-600, 880-1030) en Vastly-prod lees-only (`scripts/prod_db_sessie.sh --psql`, sessie geopend en gesloten).

## Uitkomst in één alinea
De herzendactie van 17:50 UTC werkte: de zes Rubicon-rijen stonden `openstaand`, de scheduler-run van 17:55:25 UTC leverde ze alle zes af. Vastly
antwoordde `200 {"resultaat": "genegeerd", "reden": "onbekend_document", "kostenvoorstellen": {"resultaat": "kostenintake_uit"}}` en onze
afleveraar las alleen het topniveau → zes rijen `mislukt` mét audit `webhook_genegeerd` (dat log zei het ook, exit 1; de runs erna meldden terecht
"Afgeleverd: 0"). Het topniveau is Vastly's verkoopfactuur-badge die bij een inkoopfactuur per definitie niet matcht; de echte uitkomst staat genest
en luidt **`kostenintake_uit`: Vastly's tier-vlag `entiteit_config.rlz_kostenintake` staat voor Rubicon Investments B.V. én ARVUM B.V. op false**
(Vastly-prod lees-only: 0 kostenvoorstellen, 0 signalen — precies wat Peter om 21:25 zag). ARVUM: de naam bestaat sinds 24-09 06:20 UTC twee keer
(RLZ-administratie `4e7732c5` is_vastgoed mét rlz_admin_id `9da1f3ab`, én Odoo-administratie `76929c4e` `odoo:universal-steigers.odoo.com:12` = de
parallel-modus-pilot van vanochtend — bewust, geen dubbel om samen te voegen); het gebruikte id `9da1f3ab` is de RLZ-GUID die Vastly's signalen als
`rlz_admin_id` dragen, niet onze platform-id, en het commando nam élke UUID letterlijk → "niet gevonden". **Vastly hoort `4e7732c5-8a2d-422b-823d-
fd5b9a8a4999` te kennen als `administratie_id` (dat doet ze al: `entiteit.rlz_administratie_id` = 4e7732c5) en `9da1f3ab-…` alleen als tekstuele
bron-sleutel `rlz_admin_id`.** Gebouwd: de afleveraar leest het geneste resultaat, `kostenintake_uit` = afgeleverd zónder verwerking (zichtbaar, geen
fout), `webhook-herzenden --afleveren` bewijst de herzending in dezelfde executie per referentie, `mislukt` is herzendbaar, en het administratie-
argument aanvaardt id, rlz_admin_id of naam (meerduidig → de enige vastgoed-administratie). Poging 2 via de job-route: zie tabel.

## Poging 1 (Peter, 24-09 17:41–17:52 UTC, job-route) — wat de outbox en de logs zeggen
| stap | executie(s) | uitkomst |
|---|---|---|
| Rubicon dry-run per referentie (6) | `2sxml` … `gtf6p` 17:41–17:43 | 6 × "zou herzenden", exit 0 |
| ARVUM dry-run `--administratie "ARVUM B.V."` (5) | `cjczl` … `w8c7j` 17:44–17:45 | exit 1: naam niet eenduidig (2 treffers sinds 06:20 UTC: RLZ `4e7732c5` + Odoo `76929c4e`) |
| Rubicon `--uitvoeren` per referentie (6) | `kvqs6` … `5vjmt` 17:50–17:52 | 6 × "herzonden 1", audit `webhook_herzonden` |
| scheduler-run 17:55:25 UTC | `wv7h5` | **6 afgeleverd, Vastly: `200 genegeerd/onbekend_document` → 6 × `mislukt`, audit `webhook_genegeerd`, exit 1** — "Afgeleverd: 0, …, genegeerd door de ontvanger: 6" |
| scheduler-runs 18:00–19:25 UTC | `xgpdq` … `v67dp` | "Afgeleverd: 0" — er stond niets meer open (terecht) |
| ARVUM `--administratie 9da1f3ab-…` (5) | `9hdfs` … `c2v22` 19:19–19:21 | 5 × "niet gevonden", exit 1 — `9da1f3ab` is de **rlz_admin_id**, niet de platform-id; het commando nam élke UUID letterlijk |

Vastly-kant (prod, lees-only ~21:40 NL): `entiteit` Rubicon Investments B.V. `10a3968b` (`rlz_administratie_id` = 35d106f2) en ARVUM B.V.
`4439ac2f` (`rlz_administratie_id` = 4e7732c5) hebben beide `entiteit_config_effectief.rlz_kostenintake = false`; 0 rijen in `rlz_kostenvoorstel`
voor de elf referenties, 0 `rlz_webhook_signaal` sinds 17:00 UTC. Dat is exact Vastly's gedrag bij `kostenintake_uit` (regel 71-77 van
`_verwerk_factuur_geboekt_kostenregels`: geen signaal, geen voorstel, `{"resultaat": "kostenintake_uit"}`).

## Gebouwd (commit `8fc1cd3`, deploy 24-09 ~22:40 NL; geen migratie)
1. `_lees_antwoord` leest bij topniveau `genegeerd` het geneste verwerker-resultaat; genest `genegeerd` blijft genegeerd mét de geneste reden.
2. `RESULTATEN_ZONDER_VERWERKING = {kostenintake_uit}`: rij `afgeleverd`, `AfleverRapport.zonder_verwerking` + LET-OP, audit `webhook_afgeleverd`
   mét `resultaat`, `topniveau_resultaat` en `ontvanger_antwoord` (letterlijke body ≤ 500 tekens, voortaan bij élke poging).
3. `herzend_afgeleverd` neemt `afgeleverd` én `mislukt` mee; `openstaand` = "al openstaand — niet herzonden".
4. `lever_rijen_direct_af` + CLI `webhook-herzenden --uitvoeren --afleveren`: directe afleverronde voor precies de teruggezette rijen, uitkomst per
   referentie in de uitvoer (`per_rij`).
5. `_zoek_administratie_id`: UUID = platform-id óf `rlz_admin_id` (altijd platform-id terug; onbekend = fout), meerduidige naam → de enige
   vastgoed-administratie mét NB-regel, anders kandidaten mét id/rlz_admin_id/vastgoed.
6. Tests: `tests/documenten/test_webhook_herzenden.py` (13) + gouden set casus **an** (`tests/keten/test_an_webhook_samengesteld_antwoord_vastly.py`:
   BDO geboekt in een vastgoed-administratie → outbox → samengesteld antwoord `kostenintake_uit` = afgeleverd zonder verwerking → herzenden mét
   directe afleverronde `voorstellen`). Volledige pytest 7433 passed (55:56), keten-guard groen mét casus an, vitest changelog groen, tsc -b groen.

## Poging 2 (CC, 24-09 20:52–20:54 UTC, job-image `8fc1cd3`, elf parallelle executies `--uitvoeren --afleveren`)
Dry-run-probes eerst: `pdjqq` (Rubicon 24713213, status_voor `mislukt` → "zou herzenden") en `mjrck` (`--administratie "ARVUM B.V."` → NB "2 treffers;
de enige vastgoed-administratie gekozen: 4e7732c5, rlz_admin_id 9da1f3ab" → 183727 "zou herzenden"). NB gcloud: `--args` weigert een herhaald
`--referentie` ("cannot be specified multiple times") → één executie per referentie (parkeerpost P-26: komma-gescheiden referenties in één vlag).

| administratie | referentie | outbox_id | status vóór | executie | uitkomst afleverronde (Vastly-respons letterlijk) |
|---|---|---|---|---|---|
| Rubicon | 24713213 | `cbce7816` | mislukt | `q6f9f` | afgeleverd — `kostenintake_uit` |
| Rubicon | 24713354 | `79a4322f` | mislukt | `277xb` | afgeleverd — `kostenintake_uit` |
| Rubicon | 265050202128 | `a3dc2989` | mislukt | `8k8jh` | afgeleverd — `kostenintake_uit` |
| Rubicon | 26753012 | `65b14f29` | mislukt | `mk269` | afgeleverd — `kostenintake_uit` |
| Rubicon | 26734257 | `3e0cb16c` | mislukt | `bqrwp` | afgeleverd — `kostenintake_uit` |
| Rubicon | 2026-017 | `a10498c1` | mislukt | `4v4z2` | afgeleverd — `kostenintake_uit` |
| ARVUM (4e7732c5) | 183727 | `df0c005d` | afgeleverd (18-09) | `vrnw8` | afgeleverd — `kostenintake_uit` |
| ARVUM | 26747235 | `21732250` | afgeleverd (18-09) | `wr5xz` | afgeleverd — `kostenintake_uit` |
| ARVUM | 26752091 | `524fd2d2` | afgeleverd (18-09) | `v57xl` | afgeleverd — `kostenintake_uit` |
| ARVUM | 522500062785 | `1aae82cf` | afgeleverd (18-09) | `b8sjl` | afgeleverd — `kostenintake_uit` |
| ARVUM | 537500100925 | `9134c1e0` | afgeleverd (18-09) | `mh6vv` | afgeleverd — `kostenintake_uit` |

Elke executie: "TOTAAL: herzonden 1 … AFLEVERRONDE direct ná herzenden: 1 rij(en) … afgeleverd 1 (waarvan zonder verwerking 1), genegeerd 0", exit 0,
LET-OP-regel per referentie. Audit `webhook_afgeleverd` 20:54:00–20:54:02 UTC mét `ontvanger_antwoord` =
`{"resultaat":"genegeerd","reden":"onbekend_document","kostenvoorstellen":{"resultaat":"kostenintake_uit"}}` (leesreplica, alle zes Rubicon-rijen;
ARVUM-rijen `afgeleverd` 20:54:00–20:54:02). **Per referentie: 11 × afgeleverd, 0 × 409 `niet_koppelbaar`, 0 × genegeerd, 0 × verwerkt.** Dat er
géén kostenvoorstel ontstaat is geen RLZ-fout meer: het is Vastly's tier-vlag. Vastly hoort als `administratie_id` te kennen: Rubicon
`35d106f2-91a3-4e65-8827-2d329fbfd716`, ARVUM `4e7732c5-8a2d-422b-823d-fd5b9a8a4999` (beide staan al zo in `entiteit.rlz_administratie_id`);
`be5e66b3-…`/`9da1f3ab-…` zijn alleen de tekstuele bron-sleutels `rlz_admin_id`.

## Beslispunt Peter (Vastly-kant) en het vervolg
- **`rlz_kostenintake` aanzetten voor Rubicon Investments B.V. en ARVUM B.V. in Vastly** (entiteit_config, klant-/tierinstelling — niet iets dat
  RLZ omzet). Daarna is herzenden één commando per administratie via de job-route (nu de rijen `afgeleverd` zijn: `webhook-herzenden --administratie
  <id> --referentie <ref> --beheerder-id … --uitvoeren --afleveren --reden …`, per referentie één executie); verwachte respons dan
  `kostenvoorstellen.resultaat = voorstellen`. Zolang de vlag uit staat is elke herzending "afgeleverd zonder verwerking".
- **Voorstel aan Vastly (OPEN_ITEMS):** topniveau-`resultaat` voor een inkoop-event = de kostenuitkomst (of geen `genegeerd` op het topniveau
  als een neven-verwerker iets deed), zodat een afzender die alleen het topniveau leest niet misleid wordt. RLZ leest sinds 8fc1cd3 sowieso genest.
- Retry-cadans op niet-2xx (409 `niet_koppelbaar`, OPEN_ITEMS-item 24-09) is **niet** in deze run gebouwd — blijft als inbox-opdracht
  `2026-09-24-webhook-herzenden-11-events-plus-retry-409-niet-koppelbaar.md` (de herzend-helft daarvan is hiermee gedaan).
- Werkt in productie: **ja voor de herzending en het lezen van het samengestelde antwoord** (11/11 afgeleverd op de gedeployde image, audit mét
  letterlijk antwoord); **nee voor de kostenintake** (Vastly-vlag uit, 0 kostenvoorstellen — verwacht gedrag, geen bug).

## Gelezen regels
CLAUDE.md (kernprincipes 3/4/5, migraties n.v.t., Bash-absolute-paden, pre-commit tsc); Platform `OPEN_ITEMS.md` regel 13 + 409-item 24-09;
koppelcontract §3 via `webhook_afleveraar.py`-docstring; `docs/regels/werkvoorraad-controlescherm.md` alinea webhook-herzenden 23-09; regel 08-09
"schrijvend alleen via `gcloud run jobs execute` op de gedeployde image" (nageleefd: dry-run-probes + 11 executies op `8fc1cd3`); db_lezen.sh
(replica, READ ONLY, RLS-scope per administratie); Vastly-prod uitsluitend lees-only via `prod_db_sessie.sh` (geopend + gesloten); gouden-set-guard
(casus an); parkeerposten-discipline (P-26).
