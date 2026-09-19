# Systeemfout 174 × `ic_spiegel_rood`, extractie-wachtrij 180 × vangnet en tellers BLOW — diagnose + fix (19-09-2026)

**Opdracht:** `opdrachten/gedaan/2026-09-19-ic-spiegel-rood-174-doorbelastingsparen-verkoop-niet-gevonden.md` (uit het rapport
`2026-09-19-kassarapport-autotype-en-signalering-sweep.md` deel B). **Werkt in productie: niet gemeten** — deploy volgt op de
commit van deze run; meetrecept + vervolg-opdracht `opdrachten/inbox/2026-09-19-nameting-ic-spiegel-rood-en-wachtrij-na-deploy.md`.
Geen migratie, geen RLZ-write, geen AI.

## Samenvatting

| # | Bevinding op Inzicht › Reconciliatie | Wortel | Fix |
|---|---|---|---|
| 1 | 174 × FOUT `ic_spiegel_rood` "verkoopfactuur niet gevonden bij de bron-administratie" (KF → Veldhoven 94, Oirschot Recreatie 34, Molenhof Verhuur 28, Molenhof Beheer 11, Mantelzorgwoningen 7) | De IC-verkoopkant las de RLZ-collectie `SalesInvoices`, die via de API aangemaakte verkoopfacturen **niet toont** (record-GET wél). Álle module-verkopen (doorbelasting, Vastly, omzet) waren onzichtbaar; het GUID en de IC-relaties waren correct. | `lees_verkoop_rlz` = `SalesInvoices` ∪ `Receipts` (zelfde filter, Receipts alleen `DocumentType` 10, ontdubbeld op id). |
| 2 | Blok `doorbelasting_aansluiting` "0 bevindingen" op dezelfde paren | Valse nul: `bronnen_met_whitelist` las `doorbelasting_mapping` zonder scope; FORCE RLS (alleen scope-policy) → in productie 0 rijen → "geen administratie met een actieve whitelist — niets te toetsen" sinds 16-09. Lokaal gemaskeerd door de superuser. | Whitelist per administratie in eigen scope; test onder de niet-superuser app-rol (rood op de oude code). |
| 3 | LET-OP `extractie_wachtrij: 180 overgeslagen [vangnet_scheduler]` | BLOW-bulk 18-09 11:00 UTC: 180 uploads = 180 losse job-triggers → 118 executies in één uur, 180 × `429 Too Many Requests` op de Jobs-API; parallelle executies verwerkten hetzelfde document tot 8×; opschalende service-instances zetten lopende bezig-runs terug. | Bundelvenster 30 s per job-resource (audit `gebundeld`, zachte teller `trigger_gebundeld`), job herhaalt de pas ≤ 5, startup-vangnet laat verse bezig-runs staan. |
| 4 | LET-OP werkvoorraad-tellers BLOW `te_controleren cache=151 telling=152` | Géén ontbrekende hook: document c9ba6d8d werd 11:05:20 als duplicaat afgevoerd (cache −1) en daarna door een nog open, tragere afrondingstransactie bij haar commit stil teruggezet op te_controleren (ORM-flush zonder statuscheck, geen tijdlijnregel). | Compare-and-set in `_schrijf_overgang` (`UPDATE … WHERE status = van`, rijlock) → `StatusIntussenGewijzigd`; de late schrijver schrijft niets. |

## 1. Diagnose ic_spiegel_rood (lees-only: leesreplica + `rlz-lezen`)

- **Bevindingen (replica, NULL-scope):** 174 rijen in run 772e6c3c (19-09 04:30 UTC), 100 % van de geboekte `doorbelasting_boeking`-rijen
  sinds 2025-08-15 voor de vijf doelen (Veldhoven 94/94, Oirschot Recreatie 34/34, Molenhof Verhuur 28/28, Molenhof Beheer 11/11,
  Mantelzorgwoningen 7/7); Rubicon (3 boekingen, IC-vlag uit) niet rood.
- **Drie paren (24713275 / 24713316 / 24713335, doel Mantelzorgwoningen MN):** `doorbelasting_boeking` in KF-scope: status geboekt, mapping
  df68665c (`doel_customer_guid` 90dbadcb), verkoop_rlz_id = het UUIDv5 uit `rlz_doorbelasting_verkoop_id` — géén herboeking/boek_cyclus.
  IC-relatie KF → MMN: basis `doorbelasting`, bevestigd, `entity_in_a` 90dbadcb = exact de whitelist-debiteur. Bron-factuurdatums
  2026-08-22/-24/09-02, ruim in het 400-dagenvenster.
- **RLZ live (KF):** `GET SalesInvoices/83f3487e-…` → 200, Entity 90dbadcb, Date 2026-08-22, € 924,92, Status 2, InvoiceNumber 24713275.
  `GET SalesInvoices?$filter=InvoiceNumber eq 24713275&$count` → **count 0**. `GET Receipts?$filter=Reference eq '24713275'` → count 1.
  `GET Receipts?$filter=Entity/id eq 90dbadcb… and Date ge 2026-08-01T00:00:00Z …&$expand=Entity&$orderby=Date asc,id asc` → count 8
  (7 doorbelastingen + 1 UI-factuur). Tabel + conclusies: api-verkenning "SalesInvoices-collectie ziet API-facturen niet, Receipts wél
  (STAP-0 19-09)".
- **Run-log 19-09 (Cloud Logging):** "KF → Mantelzorgwoningen: 44 verkoop / 51 inkoop gelezen, 44 gematcht, spiegelparen 0/7 groen" —
  de 7 spiegel-inkopen zonder verkooptegenhanger; kantoorbreed telden zulke spiegels als `ic_ontbreekt_bij_verkoper` (in meting).
- **Hypothese uit de opdracht ("verkeerde GUID-afleiding of bron-credential") weerlegd:** GUID, administratie en credential klopten; het was
  de collectie-blinde vlek die sinds Omzetmodule STAP 0 §2 (07-08) gedocumenteerd stond maar bij de bouw van het IC-blok (16-09) niet
  is meegenomen.

## 2. Diagnose aansluitingsblok (valse nul)

Run-log 19-09 04:43: "Venster …; **0 bron-administratie(s) mét whitelist.** OK geen administratie met een actieve
doorbelasting-whitelist — niets te toetsen", terwijl KF 8 mapping-rijen heeft (replica in KF-scope). `schema_referentie.sql`:
`doorbelasting_mapping_scope USING (administratie_id = current_administratie_id())`, FORCE RLS, geen NULL-/Beheerder-clausule →
`scoped_session(None)` ziet 0 rijen zodra de eigenaar geen superuser is (productie). Zelfde les als
[[security-definer-force-rls-cloud-sql]] (11-09): een owner-/superuser-test bewijst RLS niet.

## 3. Diagnose wachtrij-trigger + tellers (BLOW 18-09)

- LET-OP-detail: `HTTPStatusError: Client error '429 Too Many Requests' for url 'https://run.googleapis.com/v2/…/jobs/rlz-extractie-wachtrij:run'`.
- `gcloud run jobs executions list`: 6 executies/uur (scheduler-vangnet) élk uur, **118 om 11:00 UTC op 18-09**.
- Tijdlijnen BLOW (replica, BLOW-scope): 166 × ontvangen → extractie_wachtrij, **232 ×** extractie_bezig → te_controleren, 58 × bezig →
  wachtrij "opnieuw ingepland na een herstart van de verwerking" (startup-vangnet van opschalende service-instances, terwijl de job
  draaide); document 58b588e8 8 × bezig → te_controleren, 10c3b828 7 ×, 52622c5d 5 ×.
- Tellers: 3 × te_controleren → afgevoerd_duplicaat (11:05:14, 11:05:20, 11:25:37), maar nu 2 documenten op afgevoerd_duplicaat en
  **c9ba6d8d op te_controleren zonder gebeurtenis ná zijn afvoer om 11:05:20** — de trage afrondingstransactie (haar tijdlijnregel draagt
  11:05:17.41, de commit kwam ná 11:05:20) schreef bij de ORM-flush `status = te_controleren` over het afgevoerde document heen.
  Cache −1 (afvoer) zonder +1 (zelfde bucket) = 151 ↔ 152; de herberekening van 05:44 had de cache al hersteld. Bijvangst: een
  afgevoerd duplicaat stond stil weer in de werkvoorraad van BLOW (niets verdwijnt stil — en niets verschijnt stil).

## 4. Wat er gebouwd is

- `app/intercompany/factuurmatch.py`: `VERKOOP_COLLECTIES`, `RECEIPTS_DOCUMENTTYPE_VERKOOP`, `_lees_verkoop_collectie`, `_is_verkoop_rij`,
  `lees_verkoop_rlz` = unie ontdubbeld op id. Aansluitingsblok gebruikt dezelfde lezer.
- `app/doorbelasting/aansluiting.py::bronnen_met_whitelist`: administraties platformbreed, mapping per administratie-scope.
- `app/documenten/wachtrij.py`: `TRIGGER_BUNDEL_VENSTER_S` 30, uitkomsten geslaagd/gebundeld/mislukt, procesbreed venster per
  job-resource (`reset_bundelvenster` voor tests), `leg_trigger_uitkomst_vast(uitkomst=, gebundeld_na_s=)`.
- `app/reconciliatie/automatiseringen.py`: `TRIGGER_GEBUNDELD` (zacht, label "gebundeld met een trigger < 30 s eerder").
- `app/documenten/service.py`: `_claim_status` + `StatusIntussenGewijzigd` in `_schrijf_overgang`; `verwerk_extractie_wachtrij`
  herhaalt `_verwerk_extractie_wachtrij_pas` (≤ `WACHTRIJ_MAX_PASSEN` 5); `herstel_achtergebleven_extracties(stale_na=15 min)` laat
  mét de cloud-wachtrij verse bezig-runs staan.
- Tests: `tests/intercompany/test_factuurmatch.py` (+3: unie, zonder DocumentType, spiegelpaar groen via Receipts; call-telling 2→3/6→7),
  `tests/doorbelasting/test_aansluiting.py::TestBronnenMetWhitelist` (+2, onder de app-rol), `tests/documenten/test_async_extractie.py`
  (`TestBundelvenster` +5, cloud-variant herstel +1), `tests/reconciliatie/test_automatiseringen.py` (+1),
  `tests/documenten/test_statusovergang_cas.py` (nieuw, 2), gouden set `tests/keten/test_x_bulk_upload_bundelvenster_en_cas.py`
  (nieuw: Spot + Floor als bulk op de cloud-wachtrij → één trigger + `gebundeld`, job-drain verwerkt beide precies één keer, cache
  = telling, BLOW-race nagespeeld: late schrijver geweigerd, duplicaat blijft afgevoerd). Vijf bestanden 133 passed; volledige
  suite: zie de slotregel hieronder.

## 5. Keuzes (Peter kijkt niet mee)

- **Unie i.p.v. alleen Receipts:** Receipts is op VGG een unie van álle documenttypen; SalesInvoices blijft de eerste bron (UI-facturen
  incl. eventuele types die Receipts anders labelt), Receipts vult aan mét type-10-toets. Kost één extra GET per handelsrelatie.
- **CAS in `_schrijf_overgang` (platformbreed) i.p.v. alleen een claim in de wachtrij-worker:** het is dé enige plek die `status`
  muteert (KP 5 idempotentie), de trager-schrijver-race speelt bij élk parallel pad (boek-wachtrij, autoboek, duplicaat-afvoer), en de
  fout (`StatusIntussenGewijzigd` ⊂ `OngeldigeStatusovergang`) valt in de bestaande vangnetten. Bewust géén `version_id_col`/migratie.
- **Bundelvenster 30 s procesbreed + herhaalpas** i.p.v. een Jobs-API-check of een threading.Timer (Cloud Run request-based CPU laat
  achtergrondthreads stilvallen): het restrisico (upload ná een executie die < 30 s duurde) vangt de 10-minuten-scheduler, zichtbaar
  op 'in wachtrij' en telbaar als `trigger_gebundeld`.
- Niet gedaan: de 174 open bevindingen worden niet met de hand gesloten — de volgende run (06:30) sluit ze als verdwenen
  (`reconciliatie_auto_gesloten`); c9ba6d8d (afgevoerd duplicaat, nu te_controleren bij BLOW) is klikwerk: opnieuw als duplicaat afvoeren
  in de werkvoorraad (nazorg in de nameting-opdracht).

## 6. Meetrecept ná deploy (vervolg-opdracht in de inbox)

1. Deploy-check service ÉN jobs (`gh run view`, `gcloud run jobs describe rlz-reconciliatie … image`).
2. `NAMETING_VIA_GH=0 scripts/gcp/nameting.sh reconciliatie-alles --alleen intercompany --lees-only` → 0 × `ic_spiegel_rood`, KF-relaties
   "spiegelparen N/N groen", Mantelzorgwoningen "51 verkoop / 51 inkoop gelezen, 51 gematcht".
3. `… --alleen doorbelasting_aansluiting --lees-only` → "1 bron-administratie(s) mét whitelist", KF: 8 doelen, 0 afwijkingen verwacht.
4. Reconciliatiemail/Inzicht ná de run van 06:30: aandacht 340 → ≤ 166; `ic_ontbreekt_bij_verkoper` (in meting) daalt met de spiegels.
5. Volgende bulk-upload: audit `extractie_wachtrij_trigger` toont `gebundeld`; executies/uur ≈ 6 + 1 per batch; geen 429.

## Suite
Volledige backend-suite in twee delen op de gedeelde test-DB: eerste run 6029 passed tot `test_keten_guard` (rood zolang de gouden set
niet meebewoog → ketencasus `test_x_bulk_upload_bundelvenster_en_cas.py` toegevoegd), tweede run over de resterende mappen (unit, uren,
verkoop, verplichting, voorraad, vragen, waarborg, werkvoorraad, zoeken) + keten + intercompany: 1166 passed, 0 failed. Docs-guards
(CLAUDE.md↔BESLISSINGEN, regels-INDEX, rapporten-INDEX, gelezen regels) en changelog-vitest (5) groen.

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT):
- `docs/regels/reconciliatie.md` (115 regels — stand vóór de run; ná de run 130)
- `docs/regels/doorbelasting-intercompany.md` (144 regels — stand vóór de run; ná de run 157)
- `docs/regels/intake-extractie.md` (270 regels — stand vóór de run; ná de run 289)
