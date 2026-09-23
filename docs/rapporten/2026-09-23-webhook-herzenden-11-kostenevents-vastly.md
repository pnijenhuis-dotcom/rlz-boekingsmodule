# Webhook-herzenden — 11 `factuur_geboekt`-kostenevents aan Vastly (OPEN_ITEMS regel 13): herzend-actie + "200 genegeerd = zichtbaar mislukt" — GEBOUWD, uitvoering ná deploy

**Opdracht (Peter, 23-09 avond, Cowork-tekst):** elf `factuur_geboekt`-events (Rubicon Investments 6, ARVUM 5) die Vastly vóór de matchsleutel-fix
van 20-09 met 200 "genegeerd" beantwoordde opnieuw afleveren; herbruikbaar (geen eenmalige SQL), audit, dry-run eerst, per referentie de uitkomst.
**Bronnen gelezen:** CLAUDE.md, Platform `OPEN_ITEMS.md` regel 12/13, koppelcontract §3, `app/documenten/webhook_afleveraar.py`, migraties 0009/0025/0046,
Vastly `src/layer1_functions/rlz_webhook.py` (antwoordvorm `{"resultaat": …, "reden": …}`, lees-only).

## Uitkomst in één alinea
De herzend-actie is gebouwd als herbruikbare motor + CLI (`webhook-herzenden`, default dry-run, `--uitvoeren` mét verplichte reden, audit
`webhook_herzonden` per rij), en de afleveraar herkent Vastly's `200 {"resultaat": "genegeerd"}` voortaan als FOUT (rij `mislukt` mét de reden uit de
body, audit `webhook_genegeerd`, geen herhaling) en legt bij élke aflevering het `resultaat` in het audit vast. De dry-run op de leesreplica toont
alle elf rijen (`afgeleverd`, 1 poging). **De uitvoering kan pas ná deploy** (regel 08-09: schrijvend alleen via `gcloud run jobs execute` op de
gedeployde image) en staat als vervolg-opdracht in de inbox; OPEN_ITEMS regel 13 wordt dáár afgevinkt. Werkt in productie: niet gemeten.
Geen payload-wijziging nodig (de payload droeg al `administratie_id` én `rlz_admin_id`) → geen les in `Platform/registers/verbeteringen.md`.

## Dry-run (leesreplica `rlz-sql2-lees`, `scripts/gcp/db_lezen.sh` per administratie in eigen RLS-scope, 23-09 22:1x NL)
| administratie | outbox_id | referentie | rlz_document_id | volgnr | aangemaakt | afgeleverd | leverancier | regels | spiegel |
|---|---|---|---|---|---|---|---|---|---|
| Rubicon Investments B.V. (`35d106f2`) | `cbce7816` | 24713213 | `b7cbea71…` | 1 | 27-08 07:24 | 27-08 07:25 | Kempen Facilities B.V. | 2 | ja |
| Rubicon | `79a4322f` | 24713354 | `2c95f5b7…` | 1 | 11-09 09:20 | 11-09 09:25 | Kempen Facilities B.V. | 2 | ja |
| Rubicon | `a3dc2989` | 265050202128 | `0094b4bb…` | 1 | 18-09 11:15 | 18-09 11:20 | Sepa Green Energy | 1 | nee |
| Rubicon | `65b14f29` | 26753012 | `cb4d721f…` | 1 | 18-09 11:15 | 18-09 11:20 | Greenfoot Energy B.V. | 1 | nee |
| Rubicon | `3e0cb16c` | 26734257 | `f3801a32…` | 1 | 18-09 11:15 | 18-09 11:20 | Greenfoot Energy B.V. | 1 | nee |
| Rubicon | `a10498c1` | 2026-017 | `d9b269db…` | 1 | 18-09 11:15 | 18-09 11:20 | VvE Zamenhofdreef II | 1 | nee |
| ARVUM B.V. (`4e7732c5`) | `df0c005d` | 183727 | `edccb8ce…` | 1 | 18-09 11:16 | 18-09 11:20 | Havenbedrijf Rotterdam N.V. | 2 | nee |
| ARVUM | `21732250` | 26747235 | `a2bf4f64…` | 1 | 18-09 11:16 | 18-09 11:20 | Greenfoot Energy B.V. | 1 | nee |
| ARVUM | `524fd2d2` | 26752091 | `4b676940…` | 1 | 18-09 11:16 | 18-09 11:20 | Greenfoot Energy B.V. | 1 | nee |
| ARVUM | `1aae82cf` | 522500062785 | `773f3723…` | 1 | 18-09 11:16 | 18-09 11:20 | Stedin Netbeheer B.V. | 1 | nee |
| ARVUM | `9134c1e0` | 537500100925 | `64f9c94b…` | 1 | 18-09 11:16 | 18-09 11:20 | Stedin Netbeheer B.V. | 1 | nee |

Alle elf: `event` factuur_geboekt, `status` afgeleverd, `pogingen` 1, `schema_version` 1.2, `laatste_fout` leeg. Twee nieuwere Rubicon-rijen
(RUB-2026-0025/0031, 23-09 20:21, ná de Vastly-fix) vallen buiten scope en worden niet herzonden. "Spiegel ja" = `webhook_uitgaand.administratie_id`
gevuld (doorbelasting-spiegel Kempen Facilities → Rubicon, migratie 0046).

## Gebouwd
1. **`webhook_afleveraar._verstuur` → `OntvangerAntwoord`** (fout | resultaat | reden | body): bij 2xx wordt de JSON-body gelezen. `_lever_rij_af`:
   `resultaat == "genegeerd"` → `mislukt`, `laatste_fout` "ontvanger negeerde het event: <reden>", `volgende_poging_op` leeg, audit `webhook_genegeerd`
   (`resultaat`, `ontvanger_reden`, `referentie`), `AfleverRapport.genegeerd`, CLI `webhook-afleveren` exit 1 — niet herhaald. Élke aflevering
   draagt `resultaat` + `referentie` in het audit-detail (`webhook_afgeleverd`). Een 200 zonder JSON blijft een gewone aflevering.
2. **`herzend_afgeleverd(actor_id, administratie_id, referenties, reden, event, dry_run)`** + `HerzendRij`: afgeleverde rijen op
   `payload.data.referentie` → openstaand (pogingen 0, afgeleverd_op/laatste_fout leeg; payload onaangeraakt), `FOR UPDATE SKIP LOCKED`, audit
   `webhook_herzonden` (oud: status/pogingen/afgeleverd_op/laatste_poging_op; nieuw: referentie, rlz_document_id, volgnummer, reden); niet gevonden /
   niet afgeleverd = zichtbare regel; reden ≥ 5 tekens verplicht bij uitvoeren; dry-run schrijft niets.
3. **CLI `webhook-herzenden --administratie <naamdeel|uuid> --referentie … [--referentie …] [--event] --beheerder-id <uuid> [--uitvoeren --reden …]`**
   (tabel per referentie + TOTAAL; exit 1 bij een niet-gevonden/niet-afgeleverde referentie of ontbrekende reden); `_zoek_administratie_id` = één
   treffer op naamdeel (contract rlz-lezen). `nameting.sh` weigert `webhook-herzenden` en `webhook-redrive` (schrijvend, ook de dry-run).
4. **Querybibliotheek `webhook-outbox`** (scope administratie, `referentie`/`event` optioneel): status, pogingen, afgeleverd_op, laatste_fout,
   referentie/rlz_document_id/volgnummer, laatste afleveraudit mét `resultaat`/`ontvanger_reden`, `herzonden_op` — de lees-only meetlat
   (`db-lezen webhook-outbox --administratie Rubicon`, ook via dispatch-onderdeel `query`).
5. **Tests** `tests/documenten/test_webhook_herzenden.py` (7): genegeerd → mislukt + audit + niet herhaald; verwerkt/al_verwerkt/zonder body =
   aflevering mét resultaat; dry-run schrijft niets + "niet gevonden"; uitvoeren → openstaand + audit → dezelfde payload opnieuw verstuurd (zelfde
   referentie/volgnummer, verse nonce) → resultaat in audit; mislukte rij niet herzonden; CLI dry-run/uitvoeren/reden/onbekende administratie.
   Bestaande `test_webhook_afleveraar.py` (22) + `test_lezen.py` groen.

## Uitvoering (vervolg-opdracht `opdrachten/inbox/2026-09-24-webhook-herzenden-11-events-uitvoeren-na-deploy.md`, `niet vóór: 2026-09-24 00:30`)
Stap 0 deploy-check (service + job `rlz-webhook-afleveraar`), stap 1 dry-run op de job-image (2 × `gcloud run jobs execute … webhook-herzenden`),
stap 2 `--uitvoeren --reden …` (alleen deze elf), stap 3 ≥ 10 min later `db-lezen webhook-outbox` per administratie → per referentie GOED
(`webhook_afgeleverd` mét resultaat verwerkt/voorstellen/al_verwerkt) of FOUT (`webhook_genegeerd` + reden, niet herhalen), stap 4 OPEN_ITEMS regel 13
afvinken + rapport. De job-scheduler `rlz-webhook-afleveraar` (*/5) verstuurt; geen handmatige `webhook-afleveren` nodig.

## Beslispunten / opmerkingen
1. Regel 1 ("genegeerd = mislukt, niet herhalen") geldt voor álle afleveringen, niet alleen herzonden rijen — kernprincipe 4. Gevolg ná deploy:
   de vijf terecht genegeerde events van "Administratiekantoor Nijenhuis (test)" (geen verhuurder) worden bij een volgende levering zichtbaar
   `mislukt`; bestaande afgeleverde rijen blijven ongemoeid.
2. Vastly's kostenpad antwoordt "voorstellen" (niet "kostenvoorstel" zoals de opdracht zei) — GOED = alles behalve "genegeerd".

## Poort
- pytest: `test_webhook_herzenden.py` 7, `test_webhook_afleveraar.py` + `test_lezen.py` + `test_cli_smoketest.py` + `test_soort_stand.py` +
  `test_geen_bug_in_klanttekst.py` groen (targeted, ná de volledige suite van de activa-run); ruff op de eigen regels schoon; geen frontend-code.
- Volledige suite: niet opnieuw gedraaid ná deze wijziging (raakt alleen `webhook_afleveraar.py`, `cli.py`, één query-bestand, één tekstregel
  in `soort_stand.py`; de bestaande afleveraar-tests dekken de gewijzigde paden).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/werkvoorraad-controlescherm.md` (413 regels)
- `docs/regels/doorbelasting-intercompany.md` (185 regels)
- `docs/regels/werkloop-productie.md` (332 regels)
