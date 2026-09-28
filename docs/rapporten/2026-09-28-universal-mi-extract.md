# Universal MI-extract 2026 — lees-only extract voor het Jarvis MI-rapport (28-09-2026)

**Opdracht (Peter 28-09, Feiten eerst blok A/C; nooit de primary, nooit schrijven):** per administratie Universal Materiaal,
Universal Nederland, Universal Steigerbouw, BWC Steigers, Bradwolff Constructie (Reeleezee) en Universal Verkoop (Odoo, koppeling
company 3 alleen lezen) over 2025-01 t/m 2026-08: (1) grootboek-journaalregels + saldibalans, (2) bankmutaties met intercompany-
markering, (3) CSV's met bron-id naar `../Jarvis/analyse/werk/universal_mi_2026/` + dit leesverslag. Eenmalig, herleidbaar extract
voor één rapport (afwijking van Jarvis J-070, vastgelegd in Jarvis J-117); de structurele GL-spiegel loopt via Platform OPEN_ITEMS.
Alleen SELECT op de leesreplica `rlz-sql2-lees` (`scripts/gcp/db_lezen.sh`, rol `rlz_lezer`, `BEGIN READ ONLY`, actor = Peters
Beheerder-id, per administratie gescoped waar RLS dat vereist). Geen RLZ-API-call, geen Odoo-call, niets gemuteerd, geen secrets.
**Werkt in productie: n.v.t.** (meting/extract, geen bouw).

## Samenvatting (≤ 10 regels)

1. **Deel (2) BANK en het rekeningschema zijn volledig geleverd:** 15.586 bankmutaties over 6 administraties × 20 maanden,
   **0 ontbrekende maanden**, elke regel mét `bron_mutatie_id`; 2.426 grootboekrekeningen (`rlz_rekeningschema.csv`).
2. **Deel (1) GROOTBOEK is ONVOLLEDIG — niet geleverd, met reden:** de journaalregels (RLZ `JournalEntryLines`, Odoo
   `account.move.line`) zijn met de bestaande lees-only instrumenten niet volledig en niet herleidbaar te lezen. `rlz-lezen` is
   een steekproef-instrument (`--top` ≤ 50, uitvoer altijd geanonimiseerd, GUID's afgekapt) en de RLZ-/Odoo-credentials leven
   uitsluitend in de cloud-credential-store (KMS); een lokale lezing tegen productie is verboden (regel 08-09). Er is géén
   journaalregel-cache op de replica. Dus: **geen saldibalans, geen Σ debet = Σ credit-toets, geen top-5 kostenrekeningen** —
   een cijfer hier zou een gok zijn.
3. De RGS-code per rekening zit niet in de cache (`platform.grootboekrekening`); kolom `rgs_code` is leeg = onbepaalbaar.
4. Intercompany is deterministisch op IBAN gemarkeerd tegen de eigen bankrekeningen van álle 74 platform-administraties met een
   IBAN in `payment_account_cache` (120 unieke IBAN's): 2.821 mutaties tussen de zes (`intercompany_zes`), plus 461 naar andere
   platform-administraties (`tegenpartij_platform_administratie`: o.a. Bradwolff Holding, Inpensas Beheer, De Wit Beheer Oss,
   Administratiekantoor Nijenhuis C.V.) — welke daarvan holdings/aandeelhouders zijn, is een registervraag aan Peter.
5. Privacy: rechtspersonen letterlijk alleen bij een expliciete rechtsvorm/overheidsnaam in de tegenpartijnaam (B.V., N.V., VOF,
   Holding, Beheer, Stichting, GmbH, Ltd, bank, Belastingdienst, …); alle overige tegenpartijen (incl. eenmanszaken op
   persoonsnaam) gehasht én de omschrijving weggelaten. IBAN's gemaskeerd tot 4+4. 4.593 van de 15.586 regels gehasht.
6. Volledigheid van de bankcache t.o.v. RLZ is hier **niet** live getoetst (geen RLZ-call); de cache is incrementeel op
   CreateDate + open-post-verversing, laatste sync 28-09 05:48–13:21 UTC, watermark 27/28-09; oudste mutatie per administratie
   ligt vóór of op 2025-01-02 (Bradwolff Constructie start exact 02-01-2025 — de horizon van de historie-backfill).

## Wat Peter moet beslissen

- **A. Grootboekroute.** Voor het GL-deel zijn er twee schone routes; beide vragen een opdracht, geen omweg:
  (a) een lees-only CLI-commando in de job-image (`rlz-grootboek-extract`: `JournalEntryLines?$expand=Account,JournalEntry` per
  administratie, gepagineerd, filter `JournalEntry/BookDate` per maand, ongeanonimiseerd naar een GCS-bucket met retentie — niet
  naar Cloud Logging; Odoo `account.move.line` posted via `odoo_client_voor(read_only=True)`); of (b) de structurele weg: het
  RLZ-leescontract 05a (Jarvis) mét journaalregels als leveringsonderdeel. Mijn positie: (b) is de regel (J-070), (a) alleen als
  het rapport niet op 05a kan wachten.
- **B. Holdings/aandeelhouders.** Welke platform-administraties gelden als holding/aandeelhouder van de zes? Nu alleen als
  tegenpartij benoemd; een registerrij (Jarvis `consolidatiekring`/`ic_partij`) maakt de markering definitief.
- **C. Universal Verkoop — Odoo-kant.** De bankmutaties van Verkoop komen uit RLZ (PaymentAccounts van de RLZ-administratie);
  Odoo-bankjournalen zijn niet gelezen. Sinds de overstap (kanteldatum 01-09-2026, buiten deze periode) verschuift dat.

## 1. Bankmutaties per administratie per maand (`boekhouding.bank_mutatie`, boekdatum 2025-01 t/m 2026-08)

| maand | Materiaal | Nederland | Steigerbouw | BWC | Bradwolff | Verkoop |
|---|---:|---:|---:|---:|---:|---:|
| 2025-01 | 11 | 227 | 56 | 65 | 69 | 201 |
| 2025-02 | 12 | 207 | 42 | 28 | 53 | 186 |
| 2025-03 | 7 | 263 | 65 | 8 | 48 | 183 |
| 2025-04 | 44 | 278 | 110 | 4 | 34 | 206 |
| 2025-05 | 41 | 332 | 209 | 16 | 121 | 341 |
| 2025-06 | 26 | 332 | 172 | 8 | 83 | 221 |
| 2025-07 | 44 | 333 | 205 | 4 | 54 | 203 |
| 2025-08 | 14 | 320 | 85 | 19 | 60 | 169 |
| 2025-09 | 28 | 305 | 161 | 5 | 38 | 162 |
| 2025-10 | 33 | 391 | 157 | 6 | 118 | 263 |
| 2025-11 | 13 | 331 | 219 | 5 | 62 | 189 |
| 2025-12 | 17 | 348 | 240 | 7 | 37 | 205 |
| 2026-01 | 8 | 272 | 120 | 5 | 60 | 122 |
| 2026-02 | 24 | 306 | 144 | 10 | 52 | 189 |
| 2026-03 | 21 | 398 | 189 | 6 | 80 | 205 |
| 2026-04 | 37 | 319 | 199 | 6 | 57 | 262 |
| 2026-05 | 20 | 378 | 275 | 6 | 60 | 242 |
| 2026-06 | 14 | 258 | 182 | 3 | 61 | 168 |
| 2026-07 | 31 | 449 | 354 | 6 | 60 | 284 |
| 2026-08 | 14 | 211 | 83 | 3 | 54 | 120 |
| **totaal** | **459** | **6.258** | **3.267** | **220** | **1.261** | **4.121** |

Ontbrekende maanden: **geen** (alle 6 × 20). Elke administratie heeft 1 bankrekening in de cache. Cache-horizon (oudste
mutatie): Materiaal 2022-03, Nederland 2019-07, Steigerbouw 2024-10, BWC 2023-02, Bradwolff Constructie **2025-01-02**,
Verkoop 2020-02. Laatste sync 28-09 (05:48–13:21 UTC), watermark 27/28-09 06:xx UTC.

### Intercompany op IBAN (deterministisch; geen naam-matching)

| administratie | IC tussen de zes (n) | netto IC-bedrag | overige platform-tegenpartijen (n) | grootste tegenadministraties |
|---|---:|---:|---:|---|
| Universal Materiaal | 303 | +852.546,56 | 59 | Verkoop 266, Inpensas Beheer 40, Nederland 37 |
| Universal Nederland | 780 | +311.955,60 | 124 | Steigerbouw 642, Inpensas Beheer 109, Verkoop 100, Materiaal 37 |
| Universal Steigerbouw | 638 | −1.261.105,84 | 23 | Nederland 608, Verkoop 30, Adda Import-Export 5 |
| BWC Steigers | 119 | −81.515,36 | 23 | Verkoop 100, Bradwolff Constructie 19, Bradwolff Holding 5 |
| Bradwolff Constructie | 245 | +3.740.225,81 | 48 | Verkoop 222, BWC 22, Bradwolff Holding 17, De Wit Beheer Oss 14 |
| Universal Verkoop | 736 | −3.438.788,98 | 57 | Materiaal 281, Bradwolff Constructie 218, Nederland 101, BWC 100, Steigerbouw 36, Inpensas Beheer 57 |

Netto IC-bedrag = Σ bedrag van de mutaties met `intercompany = intercompany_zes` (positief = ontvangen). De tellingen van
"Administratiekantoor Nijenhuis C.V." (kantoorfacturen) tellen mee onder "overige platform-tegenpartijen". Eigen-rekening-
overboekingen (`eigen_rekening`): Materiaal 28, Nederland 62, Bradwolff 24, overige 0.

Kolommen `rlz_bank_<adm>.csv`: administratie, administratie_id, bron_mutatie_id, payment_account_id, boekdatum, maand, bedrag,
open_bedrag, tegenrekening_iban (4+4), tegenpartij, tegenpartij_soort (rechtspersoon | administratie_platform |
natuurlijk_persoon_of_onbekend_gehasht | leeg), omschrijving, mutatie_type (RLZ `Type`), intercompany (intercompany_zes |
tegenpartij_platform_administratie | eigen_rekening | leeg), ic_tegenadministratie(+_id), rlz_koppelingen (JSON), verdwenen_uit_bron_op,
bron, laatst_gesynchroniseerd.

## 2. Rekeningschema (`platform.grootboekrekening`, cache van RLZ `Ledgers`)

| administratie | rekeningen | opbrengsten (1) | kosten (2) | activa (3) | passiva (4) |
|---|---:|---:|---:|---:|---:|
| Universal Materiaal | 336 | 22 | 142 | 63 | 109 |
| Universal Nederland | 360 | 26 | 149 | 67 | 118 |
| Universal Steigerbouw | 340 | 22 | 146 | 63 | 109 |
| BWC Steigers | 335 | 21 | 141 | 63 | 110 |
| Bradwolff Constructie | 336 | 21 | 141 | 64 | 110 |
| Universal Verkoop | 719 | 67 | 305 | 136 | 211 |

`soort` = RLZ `AccountType` onvertaald (1 opbrengsten, 2 kosten, 3 activa, 4 passiva — `app/db/models.py`). Verkoop heeft
719 rekeningen: de cache draagt ook verdwenen/gearchiveerde rekeningen (`verdwenen_uit_bron_op` gevuld) — in de CSV zichtbaar.
**RGS-code: niet beschikbaar** in de cache; alleen live via `Ledgers?$expand=SystemAccountList` (groep-saldi-patroon).

## 3. Grootboek-journaalregels en saldibalans — ONVOLLEDIG (niet geleverd)

Per administratie (alle zes): **ONVOLLEDIG — reden: geen lees-only instrument dat een volledige, ongeanonimiseerde
journaalregel-extractie toestaat.** Concreet getoetst:

| instrument | kan het? | waarom niet |
|---|---|---|
| `nameting.sh rlz-lezen` (job-image) | nee | `--top` ≤ 50 (afgedwongen, exit 2), uitvoer altijd geanonimiseerd (GUID's 8 tekens, namen initialen) — een nameting is een steekproef, geen export (`app/rlz/lezen_cli.py`) |
| `rlz-feiten rlz/bank` | nee | één document of bankzoekopdracht per aanroep, geanonimiseerd |
| lokale `LeesOnlyClient`/`lees_collectie` tegen RLZ | niet toegestaan | credentials alleen in de cloud-store (KMS); productie-regel 08-09: alleen via de gedeployde job-image, geen lokale backend |
| Odoo `account.move.line` via `odoo_client_voor(read_only=True)` | niet toegestaan | idem: API-key in `platform.odoo_koppeling` (KMS-gewrapt); koppeling company 3 is alleen-lezen maar de sleutel is niet lokaal |
| leesreplica | geen bron | er is geen journaalregel-cache; `groep_saldo_stand` bevat alleen debiteuren-/crediteurensaldi |

Gevolg: geen saldibalans per maand, geen Σ debet = Σ credit-toets, geen top-5 kostenrekeningen. Wat er wél is: het volledige
rekeningschema (§2) als kapstok voor de toekomstige GL-levering. Voorstel: beslispunt A.

## Meetrecept (herhaalbaar, lees-only)

1. `scripts/gcp/db_lezen.sh "<SELECT>" --als <Beheerder-uuid> [--administratie <uuid>] --max 5000` (replica, `rlz_lezer`,
   READ ONLY) — elke SELECT gewrapt in `row_to_json` (verliesvrij parsen); scripts `lees.py`/`haal.py`/`verwerk.py` naast de CSV's.
2. Ongescoped: `platform.administratie`, `platform.groep`, `platform.odoo_koppeling` (zonder sleutelkolommen),
   `boekhouding.intercompany_relatie`. Gescoped per administratie (RLS zonder Beheerder-clausule): `payment_account_cache` (74
   administraties, 151 rijen, 120 unieke IBAN's), `platform.grootboekrekening` (6×), `boekhouding.bank_mutatie` in vier
   halfjaarblokken (plafond 5.000 nooit geraakt), `bank_sync_stand`.
3. Verwerking deterministisch in Python (Decimal, sha256); geen AI.

## Gelezen regels

- CLAUDE.md (RLZ) kernprincipes; `scripts/gcp/db_lezen.sh`, `nameting.sh` (allowlist), `nameting_env.sh`;
  `app/rlz/lezen_cli.py`, `app/rlz/feiten_cli.py`, `app/rlz/lezen.py`, `app/migratie/rlz_bron.py` (JournalEntryLines-feiten
  STAP-0 13-09), `app/intercompany/rekening_courant.py`, `app/groepen/saldi.py`, `app/odoo/credentials.py`, `app/bank/sync.py`,
  `app/db/models.py` (Grootboekrekening); `migrations/schema_referentie.sql`; rapport `2026-09-28-ic-universal-stand.md`;
  BESLISSINGEN §STAP-0 13-09 en productie-regel 08-09.
