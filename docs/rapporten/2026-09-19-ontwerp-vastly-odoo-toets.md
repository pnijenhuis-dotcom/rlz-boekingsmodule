# Ontwerp "Vastly-klant op Odoo" — bron-vs-realiteit-toets, pilotmeting ARVUM/Rubicon, contract-check (19-09-2026)

**Opdracht:** `opdrachten/gedaan/2026-09-19-ontwerp-vastly-odoo-toetsen-en-pilotmeting.md` (Cowork 19-09; GEEN bouw).
**Ontwerp:** `docs/ONTWERP_VASTLY_ODOO.md` — status ONTWERP TER AKKOORD Peter; correcties staan ín het document als "gecorrigeerd door CC 19-09".
**Werkt in productie: n.v.t.** (lees-only toets + meting; geen code, geen migratie, geen RLZ-/Odoo-write, geen Odoo-koppeling aangemaakt).

## Één regel voor Peter

**Pilot-advies: ARVUM B.V.** (kleinste bank, geen doorbelastingsspiegel, geen live Vastly-push, `is_vastgoed` staat al) — mits Vastly ARVUM eerst
onboardt en er een Odoo-company voor komt, want **geen van beide administraties heeft ooit een VASTLY-VERKOOP- of WAARBORG-document via de module
ontvangen** (verkoop/waarborg is voor élke administratie greenfield). Beslispunten: (1) pilot ARVUM ↔ Rubicon, (2) bank "B eindbeeld, A brug",
(3) contract-addendum v1.21 als OPEN_ITEM (concept staat), (4) volgorde t.o.v. VGG, (5) Vastly toont de boekhouding-naam per klant, plus nieuw
(6) creditnota-vorm op Odoo (reversal-wizard vs losse `out_refund`, want `reversed_entry_id` is readonly).

## 1. Bron-vs-realiteit-toets van het ontwerp (§1-tabel + §2)

Methode: élke bewering tegen de code (`app/backends/*`, `app/odoo/*`, `app/migratie/odoo_schrijf.py`, `app/verkoop/boeken.py`,
`app/waarborg/boeken.py`, `app/bank/*`, `app/documenten/webhook.py`, `app/registersync/*`), odoo-verkenning §2.4/§3/§11/§12.4 en
koppelcontract v1.20 §2c/§2d/§3/§8; plus een lees-only `fields_get`/`read_group` op Odoo company 3 (Universal Verkoop, leesbron; 5 calls, geen writes).

| Ontwerp-bewering | Uitkomst | Bron |
|---|---|---|
| Inkoop op Odoo = klaar | **Klopt.** Eén port `InkoopPort` (6 operaties) + `OdooInkoopPort`; routering alleen in `registry.py::inkoop_port_voor` | `app/backends/port.py:120-146`, `app/odoo/inkoop.py:321-1075`, `app/backends/registry.py:40-49` |
| Verkoop op Odoo = te bouwen, "alleen mapping" | **Klopt, mét nuance:** een `out_invoice`-create bestaat alleen in de VGG-replay achter de kill-switch (`migratie/vertaling.py`, `cli_odoo.py`), nooit gepost; `verkoop/boeken.py` roept `_rlz_client_voor` direct aan en faalt op Odoo met `GeenRlzCredentials` — geen `NietOndersteund`-capabilitymelding | `verkoop/boeken.py:43,209`; `rlz/credentials.py:147-151`; `backends/port.py:35` |
| Waarborg = half, "bewezen in de VGG-replay" | **Gecorrigeerd:** bewezen in STAP-0 cyclus B (02-09, company 1), niet in de replay (SCHRIJF c is nog niet uitgevoerd — bewijspaar niet vertaalbaar, regels vgg-odoo blok 12); primitieven `maak_concept_move`/`post_move` bestaan; `waarborg/boeken.py:80` is hard RLZ; 0 treffers "waarborg" in `app/odoo`/`app/migratie` | odoo-verkenning §4.2; `migratie/odoo_schrijf.py:197,396` |
| Bank = te bouwen + STAP-0, "vóór er een regel code komt" | **Gecorrigeerd:** de primitieven bestaan al — statement line create mét anker (`maak_statement_line`), reconcile-routes i/ii/iii (`set_line_bank_statement_line` / `write`+`account.move.line.reconcile` / `action_reconcile`), `koppel_los` = `remove_move_reconcile`; alle achter `migratie_odoo_writes_ingeschakeld`, geen van drie live bewezen. `app/bank/` slaat Odoo zichtbaar over | `migratie/odoo_schrijf.py:476-755`; `bank/sync_run.py:261-284`; `bank/reconciliatie.py:207-211` |
| `is_reconciled`/`amount_residual` als afgeletterd-signaal | **Getoetst (fields_get):** `account.move.amount_residual(_signed)` monetary readonly **stored**; `payment_state` stored selection `not_paid/in_payment/paid/partial/reversed/blocked/invoicing_legacy`; statement line heeft óók `amount_residual` (float, stored) naast `is_reconciled`. Live company 3: not_paid 104 / € 228.010,99 · paid 6 · reversed 1. **Aanscherping:** `in_payment` zet residual al op 0 vóór de bankmatch → nooit als `afgeletterd` melden (alleen `paid`/`reversed` + residual 0; `partial` → deel; `in_payment` → wachten + LET-OP > 14 d) | `.scratch/vastly-odoo/odoo_fields_toets.py` (sessie), ontwerp §2.3 |
| `unique_import_id` zetbaar via create | **Onbeslist, blijft aanname:** `readonly=True` in fields_get; bewijs = STAP-0 stap 1 | fields_get 19-09; odoo-verkenning §11.1 |
| Creditnota = `out_refund` + `reversed_entry_id` | **Gecorrigeerd:** `reversed_entry_id` en `invoice_origin` zijn readonly → reversal-wizard óf losse refund mét bron in `ref` → nieuw beslispunt 6 | fields_get 19-09; odoo-verkenning §3.3 |
| Grootboek §2c "klaar aan onze kant" | **Klopt:** `lees_grootboek` → zelfde cache/upsert; `code text` zonder limiet (Bonte Hoeve: 356 rekeningen, alle 6 tekens); `ledger_id` = UUIDv5, `is_totaalrekening` altijd False, `soort` vertaald via `soort_voor_account_type` | `odoo/sync.py:121-148,313-344`; leesreplica 19-09 |
| Registersync §8 "debiteur = res.partner klaar" | **Gecorrigeerd:** `partners.py` doet alleen crediteuren (`supplier_rank`); huurder-partner is nieuw. Registersync levert Odoo-administraties mee mét `rlz_admin_id` = sentinel `odoo:<host>:<company>` (geen UUID) — contractpunt | `odoo/partners.py:69,79`; `registersync/service.py:69`; `odoo/ids.py:70-76` |
| Webhook: "veldnaam blijft, waarde = backend-id + backend-veld, addendum nodig" | **Klopt, maar het gebeurt vandaag al zonder addendum:** `factuur_geboekt` vuurt voor élke is_vastgoed-administratie met `rlz_document_id` = extern id (Odoo: UUIDv5), `rlz_admin_id` = sentinel, `rlz_boekstuknummer` = Odoo `name`; geen `backend`-veld. `factuur_afgeletterd` vuurt voor Odoo nooit (bank-sync slaat Odoo over, leest `BaseRemainingAmount`). Geen productiefout vandaag: alle 6 is_vastgoed-administraties draaien `rlz` | `documenten/boeken.py:311-333,549,622-629`; `documenten/webhook.py:26-49,104-151`; `bank/vastly.py:82-127` |
| §2.5 "de bankmodule is de enige plek zonder seam" | **Fout, gecorrigeerd:** verkoop, waarborg, omzet én doorbelasting roepen alle `RlzClient` direct aan; guardrail 0016 op ~15 plekken omzeild via `is_odoo_sentinel`/`actieve_administraties_per_backend` (overslaan). Werk = drie ports + vier motoren achter de port | `omzet/boeken.py:432`; `doorbelasting/boeken.py:502-1364` |
| Ontbrekende stromen | **Toegevoegd:** Kempen-doorbelasting (Rubicon = DOEL) en route A projectaanmaak §5 (RLZ-only, `rlz_project_id` moet analytic-UUIDv5 worden) → fasering 2b/3b | BESLISSINGEN "Spiegelkant geverifieerd via Rubicon"; `app/projecten/` |
| §3 "ARVUM 3 lagen, 4 accordeurs" | **Gecorrigeerd:** 3 lagen, **3** accordeurs — dezelfde drie als bij Rubicon; `is_vastgoed` staat op ARVUM al AAN (register zegt "pas bij het Vastly-moment") | leesreplica 19-09 (§2) |

## 2. Pilotmeting ARVUM B.V. en Rubicon Investments B.V. (lees-only)

Bronnen: leesreplica `rlz-sql2-lees` via `scripts/gcp/db_lezen.sh` (nameting@, rol `rlz_lezer`, READ ONLY, Beheerder-actor, `--administratie`-scope per
tabel) + RLZ GET via `nameting.sh rlz-lezen` op de job-image (executies `rlz-reconciliatie-vcnsr/rb99z/pp9jq` Rubicon, `-w72qx/7ddxj/rx6jp` ARVUM; `NAMETING_VIA_GH=0`
omdat rlz-lezen geen dispatch-onderdeel is). Geen Odoo-writes, geen Odoo-koppeling aangemaakt. Peildatum 19-09-2026, laatste 6 maanden = maart–september.

| Meting | ARVUM B.V. (`4e7732c5…`, RLZ `9da1f3ab…`) | Rubicon Investments B.V. (`35d106f2…`, RLZ `be5e66b3…`) |
|---|---|---|
| Backend / is_vastgoed / verkoop-autoboeken (spiegel) / afgeletterd-event / project_verplicht / groep | rlz · **AAN** · AAN · uit · **AAN** · Kempen groep | rlz · AAN · AAN · **AAN** · uit · Kempen groep |
| Odoo-koppeling | geen (`platform.odoo_koppeling`: alleen company 3/6/9/10/11) | geen |
| VASTLY-VERKOOP-documenten per maand (module) | **0** (alle maanden; `document.soort='verkoopfactuur'` = 0, `verkoop_boeking` = 0) | **0** |
| Creditnota's 381 | 0 | 0 |
| RLZ `SalesInvoices` sinds 01-03-2026 (`$count`) | 2 (geen Vastly-nummers) | 0 |
| Waarborgberichten (`waarborg_bericht`) | 0 | 0 |
| RLZ `ManualJournals` 2026 | 20 | 30 |
| Bankmutaties per maand (betaalrekening) mrt/apr/mei/jun/jul/aug/sep | 17 · 17 · 10 · 10 · 20 · 10 · 4 (totaal 88; ≈ 10–20/mnd) | 37 · 37 · 35 · 41 · 45 · 36 · 15 (totaal 246; ≈ 35–45/mnd) |
| Rekeningen (`payment_account_cache`) | 2: betaalrekening ING `…3366` + spaarrekening | 7: betaalrekening ING `…4753` (saldo € 62.807,44 per 17-09, MT940-import 18-09), spaarrekening € 700.000, RC Inpensas Beheer −€ 49.500, Verrekeningen, Overloop, RC 2 (BV), Privé betaalde facturen (gearchiveerd) |
| Bankmutaties totaal in cache / nog open (`open_bedrag ≠ 0`) / eerste mutatie | 1.274 / **15** / 2017 | 2.259 / **52** / 2022 |
| Bankmodule-gebruik (`bank_boeking` / afletteropdrachten / relatie-boekingen) | 2 / 3 / 0 | 2 / 5 / 0 |
| Open posten (`payment_item_cache`, status 2 = open) | 9 posten, saldo € 57.480,26 (7 debet, 2 credit; oudste verval 2023-11-19) | 36 posten, saldo € 62.692,68 (23 debet, 13 credit; oudste verval 2025-03-31) |
| Accordering | 3 lagen (volgnummer 1–3, geen drempel, geen afdeling/leveranciersroute), 3 accordeurs; 0 leveranciersroutes; 8 gebruikers met scope | 3 lagen, **dezelfde 3 accordeurs**; 0 leveranciersroutes; 7 gebruikers met scope |
| Documenten in de module (sinds aug) | 8 inkoopfacturen (5 geboekt, 3 te controleren) | 11 inkoopfacturen in sept (4 geboekt, 1 te controleren, 6 ter accordering) |
| Webhooks aan Vastly (`webhook_uitgaand`) | 0 | 2 × `factuur_geboekt` afgeleverd (27-08 ref 24713213, 11-09 ref 24713354; leverancier Kempen Facilities = doorbelastingsspiegel) |
| Entiteitenregister Vastly (`../Platform/registers/entiteiten.md`) | rij 22: "geoormerkt Vastly-kandidaat, `is_vastgoed` pas bij het Vastly-moment" — **drift: DB zegt AAN** (noot toegevoegd 19-09) | rij 12: eerste concrete Vastly-scope (0009-b), waarborg-GB 0204 |
| Registersync §8 | reist mee (niet gearchiveerd), 4-cijferig grootboek: 298 rekeningen à 4 tekens (+ 20/22/6 kortere/langere), 0204 en 1806 aanwezig | idem: 322 à 4 tekens (+ 22/40/2), 0204 en 1806 aanwezig |
| Huurders (RLZ `Customers`) / objecten (`project_cache`, actief) | 5 / 4 | 19 / 11 |
| Intercompany-rijen / doorbelasting | 0 / — | 0 IC-rijen / **doorbelasting-DOEL** (spiegel-inkoop uit Kempen Facilities, zie webhooks) |

**Lees-fouten in de RLZ GET (gemeld, geen meting):** `$filter=Status eq 2` op Sales-/PurchaseInvoices = HTTP 400 (enum-type vs Int32) en
`PaymentTransactions` kent geen `Date` (wel `BookDate`) — open posten komen daarom uit `payment_item_cache`, bank uit `bank_mutatie`.

**Advies kleinste volledige pilot = ARVUM B.V.**, om vier redenen: (a) één betaalrekening met 10–20 mutaties/maand en 15 open regels tegen
Rubicons 7 rekeningen, 35–45/maand en 52 open; (b) geen doorbelastingsspiegel en geen live `factuur_geboekt`-push die je raakt; (c) 5 huurders/
4 objecten = één maand cent-exact sluiten is klein werk; (d) `is_vastgoed` en de accordeursketen staan al. Voorwaarde die de meting blootlegt:
**"volledig" bestaat nog nergens** — verkoop en waarborg zijn voor beide 0. Vastly moet ARVUM onboarden (register + huurfacturen via de
boekhoudmail) én Peter moet een Odoo-company voor ARVUM aanmaken vóór fase 2 meetbaar is. Rubicon als tweede, ná de eerste sluitende maand.

## 3. Contract-check: RLZ-aannames aan Vastly's kant (read-only in `/Users/mr.x/Vastgoed software`)

Onze payload (`documenten/webhook.py:129-151`) draagt `administratie_id` = platform-UUID én `rlz_admin_id` = RLZ-adminId. Aan Vastly's kant:

| Aanname | Vastly-locatie | Odoo-impact |
|---|---|---|
| `rlz_admin_id` (of `administratie_id`) moet UUID zijn en gelijk aan `entiteit.rlz_administratie_id` | `src/layer1_functions/rlz_webhook.py:456-467`; kolom `rlz_kostenvoorstel.rlz_admin_id uuid` (migratie 0075:77) | **Breekt stil** bij sentinel `odoo:<host>:<company>`: `uuid.UUID()` faalt → `onbekende_administratie` + `200 genegeerd`; onze outbox zegt "afgeleverd" |
| `grootboekrekening.soort` = int 1..4 (Reeleezee AccountType, DB-check) | `registersync.py:153-157`, migratie `0017:68` | Vertaalslag bestaat al aan onze kant (`soort_voor_account_type`); contractueel vastleggen als backend-neutrale vierdeling |
| Waarborg-default `0204` + UI-label "(Waarborgsommen)" + XML-attribuut `rlzAdminId` | `waarborg_bericht.py:93,140,171,221`; `config_defaults.py:134`; `schema.sql:2701`; `WaarborgVerzendDialog.tsx:112` | Ongeldig op Odoo (6-cijferig) → gereedheid-signaal; override per administratie bestaat |
| Klantzichtbare "RLZ"-teksten en `backend` hard `'rlz'` | `verhuurder_gegevens.py:41,171`; `gereedheid.py:641`; app `mijn-gegevens/index.tsx:107`; `grootboek.py:113`; `repos.py:5995`; `api.ts:186-210` | Fout voor een Odoo-klant; label-map `BOEKHOUDING_BACKEND_LABELS` bestaat, onbekende backend rendert "ODOO" |
| `bron ∈ {module_storno, rlz_ui_detectie}`; schema-versies per event 1.0/1.1/1.2 en 2.0 hard | `rlz_webhook.py:75-80,703-705` | Semantiek klopt voor Odoo (reversal = module_storno); naam RLZ-gekleurd |
| `rlz_document_id`/`ledger_id`/`administratie_id` = UUID | `rlz_webhook.py:190,237,325,698`; `registersync.py:143-144` | **OK** met UUIDv5; rauw Odoo-int niet |
| `code` lengte/formaat; `cbc:AccountingCost`; `rlz_boekstuknummer`-regex | nergens gevalideerd / `ubl.py:222,293,373,434` / bestaat niet | **OK** — alleen `ORDER BY code` lexicografisch (gemengde lengtes) |
| GB → kostensoort op `code`, niet op `ledger_id` | migraties `0017:83-88`, `0075:55-60` | Her-mappen per administratie bij overstap; geen codewijziging |
| Entiteit ↔ administratie op platform-UUID `platform.administratie.id` | `grootboek.py:156,194-223`; `boekhouding.ts:22` | **OK** — de sentinel blijft een `text`-label |

**Verificatie Vastly (vraag, geen bevinding — buiten mijn zicht):** dezelfde lookup neemt bij een RLZ-administratie éérst `rlz_admin_id`
(RLZ-GUID `be5e66b3…` in onze Rubicon-payloads van 27-08 en 11-09) en vergelijkt die met `entiteit.rlz_administratie_id`, die volgens
`grootboek.py:156` (`JOIN … ON e.rlz_administratie_id = a.id`) de **platform**-UUID (`35d106f2…`) draagt. Als dat klopt, zijn de twee Rubicon-
kostenevents aan Vastly-kant als `onbekende_administratie` genegeerd (200) en staat er niets in Vastly's kostenintake. Recept voor Vastly:
`SELECT * FROM rlz_webhook_signaal WHERE soort='onbekende_administratie' AND referentie IN ('24713213','24713354')`. Als OPEN_ITEM gemeld
(niet zelf beslist; het zit buiten deze opdracht maar raakt het pilot-advies: Rubicons "live push" is dan geen live push).

**Concept-addendum v1.21 (voorstel, in `../Platform/OPEN_ITEMS.md` — niets in het contract gewijzigd):** (1) nieuw optioneel veld `backend`
(`"rlz" | "odoo"`) in `factuur_geboekt`/`factuur_gestorneerd`/`factuur_afgeletterd` en op de §8-administratie-rij; (2) `rlz_document_id`,
`ledger_id`, `rlz_project_id` = "extern document-/rekening-/project-id van de backend, altijd UUID (RLZ-GUID of UUIDv5 van het Odoo-id)" — veldnamen
blijven; (3) `rlz_admin_id` = "backend-sleutel van de administratie, `text`" mét de sentinelvorm; Vastly's lookup op `administratie_id`
(platform-UUID) als primaire sleutel; (4) `rlz_boekstuknummer` = "boekstuknummer in de backend-vorm" (RLZ `RLZ-xx-…`, Odoo `F/2026/…`);
(5) §2c/§8 `code` = backend-code (4 of 6 cijfers, geen formaatbelofte), `soort` = backend-neutrale vierdeling 1..4, `is_totaalrekening` false
voor Odoo; (6) §2d `balans_gb_code` = code in de backend van de administratie (default 0204 alleen RLZ); (7) `factuur_afgeletterd` bron =
"open bedrag van het document in de backend" (RLZ `BaseRemainingAmount`, Odoo `amount_residual` + `payment_state ∈ {paid, reversed}`; `in_payment`
= geen event). `schema_version`: geboekt 1.2 → 1.3, afgeletterd 2.0 → 2.1, registersync 1.0 → 1.1 — additief, ontvanger op de oude versie weigert
expliciet. Akkoord van beide projecten vereist (contract v1.5-regel).

## 4. Wat is vastgelegd

- `docs/ONTWERP_VASTLY_ODOO.md`: correcties in §1 (tabel + twee ontbrekende stromen), §2.1 (readonly `reversed_entry_id`, dagboek uit de koppeling),
  §2.3 (fields_get-toets + `in_payment`-regel), §2.4a (Vastly-kant), §2.5 (seam-claim), §3 (meting + bijgesteld advies), §4 (fase 0, 2b, 3b), §5 (beslispunt 6).
- `docs/BESLISSINGEN.md`: registerrij + sectie "VASTLY OP ODOO — ONTWERP TER AKKOORD (Peter 19-09)"; `CLAUDE.md`: één verwijsregel onder VGG/Odoo.
- `../Platform/OPEN_ITEMS.md`: concept-addendum v1.21 + verificatievraag webhook-lookup; `../Platform/registers/entiteiten.md`: ARVUM-noot (is_vastgoed AAN sinds de DB-stand 19-09).
- Geen regels-alinea: dit is een ontwerp ter akkoord, geen besluit (zelfde lijn als Activa/MVA 16-09 en Factuuropdracht 18-09).

## 5. Keuzes zonder Peter (vastgelegd)

- Pilot-advies ARVUM in plaats van "eerst meten": de meting is gedaan; de voorwaarde (Vastly-onboarding + Odoo-company) staat er expliciet bij.
- Bank: RLZ-open-posten via `payment_item_cache` i.p.v. een live `Status`-filter (RLZ weigert de int-vorm); bankvolume uit de cache (RLZ `PaymentTransactions` kent geen `Date`).
- De Vastly-lookup-kwestie als vraag aan Vastly gemeld, niet als bevinding: Vastly's productiedata is buiten mijn zicht.
- Bestaand ongecommit werk van parallelle runs (Afsluiten-tab, kassarapport-autotype) niet aangeraakt en niet meegecommit; gedeelde docs gestaged via HEAD-herbouw (eigen regels alleen).

## 6. Aanvulling parallelle agent (tweede, onafhankelijke pilotmeting 19-09 ± 10:30–10:45 CEST)

Een tweede CC-agent voerde dezelfde opdracht onafhankelijk uit (eigen leesreplica-queries mét `--administratie`-scope, eigen RLZ GET-executies
`rlz-reconciliatie-jdnjw/rpmm2/hpk6s/254c6` ARVUM en `-hsqpz/8h8dn/kqdjw/lnb5j` Rubicon). De uitkomsten sluiten op de tabel in §2 (SalesInvoices 2/0,
bank ≈ 12 vs ≈ 35 per maand, 3 accordeurslagen, `odoo_koppeling` 0, `factuur_geboekt` 2 bij Rubicon); wat de tweede meting toevoegt:

| Meetpunt | ARVUM B.V. | Rubicon Investments B.V. |
|---|---|---|
| Route A projectaanmaak §5 (audit `platform.audit_event`, tabel `projectaanvraag`) | **4 × `projectaanvraag_verwerkt` + 4 × `project_aangemaakt_in_rlz` (01/02-09-2026)** — de vier objecten zijn adressen (Cavalier 4 Emmeloord, Hanzeweg 17 Barneveld, Moezelweg 136A/136B Europoort); RLZ `Projects` `@odata.count` 4, alle `IsActive`, `BeginDate` 01-09-2026 | **11 × beide acties (01/02-09)**; RLZ `Projects` 11 |
| Gevolg voor de onboarding-voorwaarde | Vastly heeft ARVUM aan de objectkant al bediend (route A live); alleen de boekhoudmail-stroom (380/381 + waarborg) staat nog niet aan — de voorwaarde in §2 is dus kleiner dan "onboarden" | idem |
| Waarborg-balansrekening | `0204 Waarborgsommen` (soort 3) aanwezig in `platform.grootboekrekening` → §6.4-inventarisatie impliciet gedaan | idem |
| RLZ `Receipts` sinds 01-03-2026 (alle documenttypen, incl. bank-direct type 19; `$count`) | 89 (jongste 18-09: inkoopfactuur € 19,30 open) | 235 (jongste 17-09: bank-direct € 4.435,22) |
| Bankmutaties april–september (`bank_mutatie`, niet verdwenen) | 17 · 10 · 10 · 20 · 10 · 4 = 71; open (`open_bedrag ≠ 0`) 14 in dit venster, Σ open −€ 72.641,49 | 37 · 35 · 41 · 45 · 36 · 15 = 209; open 50 (jul 18 / aug 19 / sep 13; apr–jun 0), Σ open −€ 16.743,55 |
| Open posten `payment_item_cache` (niet verdwenen, per teken) | crediteuren 8 / −€ 410.232,55 (31-01…18-10-2026); debiteuren 4 / € 25.342,16 (oudste 19-11-2023) — bruto per kant, §2 telt netto op status 2 | crediteuren 24 / −€ 164.981,80 (18-07-2025…03-10-2026); debiteuren 8 / € 22.555,35 (oudste 31-03-2025) |
| Rekeningen extra | RC Rijnvallei Beheer € 224.022 (01-07), RC Midden Nederland Beheer € 5.000, Kas, Verrekeningen (naast betaal- en spaarrekening …3366) | — (zie §2) |
| `accordering_laag` inactief | 3 inactieve lagen naast de 3 actieve | 5 inactieve naast de 3 actieve |
| Registersync laatste levering | 19-09 05:30 UTC: 78 administraties / 27.358 GB-rijen (18-09: 77 / 27.001) | idem |
| Audit op de `is_vastgoed`-vlag | geen `audit_event`-rij met "vastgoed"/"verkoop_autoboeken" in de actie, tabel `administratie` 0 rijen — herkomst van AAN niet uit het audit-log herleidbaar (CLI-terugval `make is-vastgoed-aan` of seed) | — |

Aanvullingen op §1/§3 uit de tweede toets: (a) creditnota's: `amount_residual` is op een `out_refund` positief — `app/groepen/saldi.py:307` gebruikt
daarom `amount_residual_signed`; het `factuur_afgeletterd`-pad voor Odoo moet dat ook doen, anders telt een open creditnota als schuld; (b) de
Vastly-ontvanger kent een harde allowlist `BEKENDE_SCHEMA_VERSIES = {1.0, 1.1, 1.2, 2.0}` + `EVENT_SCHEMA_VERSIES` (`rlz_webhook.py:75-76`,
`829-847`, onbekend = 400) — élke versiebump uit het addendum is een Vastly-wijziging vóór activatie; (c) `grootboek_code` aan Vastly-kant is
`text` mét mapping-PK `(administratie_id, grootboek_code)` (migraties 0017/0075, `src/api/routes/grootboek.py`) zonder lengte-/regex-validatie;
(d) `verkoop/boeken.py` en `waarborg/boeken.py` falen op een Odoo-administratie met `GeenRlzCredentials` (sentinel fail-loud in
`app/rlz/credentials.py`) en niet met `NietOndersteund` uit de port — het document krijgt een credential-fout in plaats van een
capability-melding (bouwpunt fase 2/3). De tweede agent deed géén Odoo-call (geen lees-only route zonder `odoo_koppeling`-rij) en géén pytest.

## 5. Aanvulling coördinator (tweede run, zelfde dag — eigen metingen, geen herhaling van het bovenstaande)

- **`fields_get` + `read_group` live op Odoo company 3 (lees-only, 5 calls, `.scratch/vastly-odoo/odoo_fields_toets.py` in de sessie):**
  `account.move.amount_residual` én `amount_residual_signed` = monetary, readonly, **stored**; `payment_state` stored selection
  `not_paid | in_payment | paid | partial | reversed | blocked | invoicing_legacy`; `reversed_entry_id` en `invoice_origin` **readonly**
  (→ ontwerp §2.1 gecorrigeerd, beslispunt 6 creditnota-vorm); `account.bank.statement.line`: `is_reconciled` boolean stored, `amount_residual`
  float stored, `unique_import_id` readonly=True (aanname §11.1 blijft), `ref` niet stored; `account.move.line.reconciled`/`full_reconcile_id`/
  `matched_debit_ids` readonly stored. Verdeling geposte verkoopfacturen company 3: `not_paid` 104 (residual € 228.010,99 = total) · `paid` 6
  (€ 6.178,15, residual 0) · `reversed` 1 (€ 1.573,00, residual 0) — het signaal werkt op echte data.
- **RLZ GET aanvullend (executies `rlz-reconciliatie-vcnsr/rb99z/pp9jq` Rubicon, `-w72qx/7ddxj/rx6jp` ARVUM):** `ManualJournals` 2026:
  ARVUM 20, Rubicon 30; `SalesInvoices` sinds 01-03: 2 / 0 (bevestigt §3); `$filter=Status eq 2` op Sales-/PurchaseInvoices = HTTP 400
  (enum ≠ Int32) en `PaymentTransactions` kent geen `Date` (wel `BookDate`) — meetles voor `rlz-lezen`.
- **Bank incl. maart (6-maandsvenster mrt–sep):** ARVUM 17·17·10·10·20·10·4 = 88; Rubicon 37·37·35·41·45·36·15 = 246 (betaalrekening).
  Cache totaal/open: ARVUM 1.274 / 15 (sinds 2017), Rubicon 2.259 / 52 (sinds 2022). Grootboek: ARVUM 298 rekeningen à 4 tekens (+ 20/22/6
  andere lengtes), Rubicon 322 (+ 22/40/2); Bonte Hoeve (Odoo, company 9): 356 rekeningen, álle 6 tekens.
- **Webhook-payload Rubicon (leesreplica, `webhook_uitgaand.payload->'data'`):** beide `factuur_geboekt`-events (27-08 ref 24713213,
  11-09 ref 24713354, leverancier Kempen Facilities, schema 1.2) dragen `rlz_admin_id` = `be5e66b3-…` (RLZ-adminId) én `administratie_id` =
  `35d106f2-…` (platform-UUID). Vastly's kostenpad (`rlz_webhook.py:456-467`) neemt éérst `rlz_admin_id` en vergelijkt met
  `entiteit.rlz_administratie_id`, dat volgens `grootboek.py:156/196-223` de platform-UUID draagt → **verificatievraag aan Vastly** als eigen
  OPEN_ITEM ("RLZ → Vastly: VERIFICATIEVRAAG — komen de factuur_geboekt-kostenevents van Rubicon wél aan?") mét read-only recept
  (`rlz_webhook_signaal` soort `onbekende_administratie`, referenties 24713213/24713354). Géén bevinding — Vastly's data is buiten ons zicht;
  raakt wel het pilot-advies: Rubicons "live push" is dan geen bewezen live push.
- **Registerdrift vastgelegd:** noot bij de ARVUM-rij in `../Platform/registers/entiteiten.md` (is_vastgoed AAN per leesreplica 19-09, 0
  VASTLY-documenten, pilot-advies ARVUM).
- **Ontwerp-correcties geplaatst door deze run** (als "gecorrigeerd door CC 19-09"): §1-tabel + twee ontbrekende stromen (Kempen-doorbelasting
  Rubicon = DOEL, route A §5 RLZ-only → fasering 2b/3b), §2.1, §2.3 (`in_payment`-regel), §2.4a Vastly-kant, §2.5 seam-claim, §3 meting +
  advies ARVUM onder voorwaarde, §4 fase 0, §5 beslispunt 6.
- **Vastgelegd:** BESLISSINGEN registerrij + sectie "VASTLY OP ODOO — ONTWERP TER AKKOORD (Peter 19-09)"; CLAUDE.md verwijsregel 4 onder
  VGG/Odoo; INDEX-regel; opdracht → gedaan; Platform: OPEN_ITEMS (addendum-item van de inbox-run + verificatievraag), entiteiten-noot.
  Geen regels-alinea (ontwerp ter akkoord, geen besluit — lijn Activa 16-09 / Factuuropdracht 18-09). Guards (CLAUDE.md-verwijzingen,
  rapporten-index, gelezen-regels, klikpunten) groen, direct gedraaid zonder pytest omdat een parallelle suite op de gedeelde test-DB liep.
- **Keuze zonder Peter:** de dubbele run is samengevoegd tot één rapport i.p.v. twee; ongecommit werk van andere runs (Afsluiten-tab,
  kassarapport-autotype) niet aangeraakt; gedeelde docs gestaged via HEAD-herbouw (alleen eigen regels).

## Gelezen regels
Volledig gelezen vóór de start (LEESPLICHT, Domeinen-kopregel):
- `docs/regels/vgg-odoo-migratie.md` (53 regels)
- `docs/regels/bank.md` (116 regels)
- `docs/regels/omzet.md` (232 regels)
- `docs/regels/administraties-instellingen.md` (114 regels)
- `docs/regels/werkloop-productie.md` (76 regels)
