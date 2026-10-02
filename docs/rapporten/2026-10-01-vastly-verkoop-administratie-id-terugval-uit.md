# Vastly-verkoop — administratie-id uit de UBL als eerste bron, terugval en historie-afleiding UIT (opdracht 01-10, uitgevoerd 02-10-2026)

**Opdracht:** `opdrachten/gedaan/2026-10-01-vastly-verkoop-administratie-id-uit-ubl-terugval-uit.md` (besluit Peter 01-10, letterlijk:
"ik wil gewoon dat de vastly facturen automatisch per BV op de juiste GB geboekt worden" en "we hebben afgesproken dat vastly facturen
100% auto gaan zonder menselijke tussenstap … zo moet het ook blijven, hou het simpel"). Handmatige CC-sessie 02-10 (deel 2 van de
sessie; deel 1 = terminal-opdracht webhook-herzenden, zie onder "Bijvangst"). Herziet onderdeel 1 en 2 van de opdracht van 29-09
(migratie 0172). Migratie **0173**; koppelcontract **v1.21**.
**Werkt in productie: niet gemeten** — de verandering is pas meetbaar zodra Vastly de eerste UBL mét `RLZ-ADMINISTRATIE:<uuid>` én
`AccountingCost` herzendt (her-aanlevering van de 39 nota's, OPEN_ITEMS r.14 — seintje = Cowork/Peter); vervolg-opdracht
`opdrachten/inbox/2026-10-03-nameting-vastly-verkoop-administratie-id-na-herzending.md` (niet vóór 03-10 09:00, hoogstens drie pogingen),
dispatch-onderdeel `vastly-verkoop`. BESLISSINGEN-sectie "VASTLY-VERKOOP — ADMINISTRATIE-ID UIT DE UBL ALS EERSTE BRON, TERUGVAL EN
HISTORIE-AFLEIDING UIT (Peter 01-10)"; regeltekst `docs/regels/omzet.md` alinea 02-10.

## Samenvatting

Een Vastly-huurnota landt voortaan uitsluitend op wat Vastly zelf in de UBL meestuurt: het platform-administratie-id van de verhuurder
(tweede `cac:AdditionalDocumentReference`, `RLZ-ADMINISTRATIE:<uuid>` — vorm door Vastly bevestigd 01-10 avond en in prod) bepaalt de
administratie, de grootboekcode per regel (`cbc:AccountingCost`) bepaalt de rekening. Ontbreekt één van beide, dan boekt de module niets en
raadt ze niets: het document blijft open mét een reden en één bevinding "melden bij Vastly" op Inzicht › Reconciliatie; ná de herzending
volstaat "Opnieuw aanbieden". De twee tussenstappen van 29-09 — de mens-koppeling op naam ("Koppel aan administratie…") en de vaste
Vastly-omzetrekening per administratie (afleiding uit historie/rekeningschema, instelling "Vastly-omzetrekeningen", knop "Rekening
kiezen") — zijn weg. Bestaande koppelingen (bron identiteit/mens) blijven werken; de tabel `vastly_omzetrekening` blijft als lees-only
historie staan.

## Vastgesteld vóór de bouw (code + regels + productie-stand, geen productie-writes)

- Koppelcontract §2d-notitie 01-10 (avond): Vastly levert het id als PLATFORM-id (`platform.administratie.id`), alleen bij een gekoppelde
  verhuurder, in Invoice én CreditNote; leesregel punt 3: een id dat RLZ niet kent = zichtbaar weigeren, nooit stil een andere
  administratie. §2d-notitie 01-10 (middag): Vastly vraagt de terugval van 29-09 af te zetten; OPEN_ITEMS r.18: RLZ/Cowork 01-10 "én de
  historie-afleiding gaat uit".
- `vastly_entiteit_koppeling.bron` droeg een CHECK `IN ('identiteit','mens')` (migratie 0172) — een rij mét bron `ubl` vergt een migratie.
- Nameting-bot 02-10 04:30 (`812a43b`, `verkenning/nameting-vastly-verkoop-02-10.txt`, gestart als stap 4 van de terminal-opdracht): 14
  open Vastly-UBL's, alle 14 geweigerd `omzetrekening_ontbreekt` (Rubicon 8, ARVUM 3, Shuto 3) — de terugval van 29-09 leidde voor deze
  drie administraties niets af (meerdere 8xxx-rekeningen, geen eigen historie); door de module geboekt sinds 23-09: Rubicon RUB-2026-0025/
  0031, Elissen JGM-2026-0036/37/38/39/41, Meyer MEY-2026-0025/26/27/29 (11); Inpensas INP-2026-0025 staat `te_controleren` maar is géén
  kandidaat (administratie niet `is_vastgoed` — feit voor Cowork bij r.14); Van Rooijen: 0 rijen in scope (de 9 staan zonder administratie).
  Bijvangst meetrecept: `--administratie ARVUM` is in productie niet eenduidig (3 treffers) → in `nameting.yml` naar "ARVUM B.V.".

## Gebouwd (opdracht punt 1–4)

| # | Opdracht | Gebouwd |
|---|---|---|
| 1 | Administratie uit de UBL | `app/documenten/ubl.py`: constante `RLZ_ADMINISTRATIE_PREFIX` + `administratie_verwijzing()` (precies één geldige UUID = id; meerdere/ongeldig = aanwezig zonder id). `app/verkoop/entiteit.py::resolve_administratie`: id eerst — actieve, niet-gearchiveerde administratie → bron `ubl`, koppelingsrij op de primaire sleutel (KvK, anders naam) mét bron `ubl` als die er nog niet is (bestaande rij nooit stil overschreven); ontbreekt het element → KvK-route ongewijzigd; bestaande mens-rij op naam wordt nog gelezen. Onbekend/inactief/gearchiveerd/ongeldig/meerdere id = weigering `administratie_id_onbekend` zónder KvK-terugval (contract punt 3). Verwijderd: `koppel_entiteit`, `heraanbied_voor_sleutel`, `POST /reconciliatie/vastly/entiteit-koppelen` + DTO's, knop "Koppel aan administratie…". Bevinding `vastly_entiteit_niet_gekoppeld` blijft (direct `actie`) mét tekst "UBL draagt geen administratie-id en geen bekende KvK — melden bij Vastly" / "… administratie-id X dat de module niet kent …", detail `administratie_id_ubl` + `reden`, geen knop (`MeldBijVastlyHint`). Reden in tijdlijn/intake draagt `administratie_id=<ruw>`. **Migratie 0173**: CHECK `bron IN ('identiteit','mens','ubl')`. |
| 2 | Omzetrekening: alleen `AccountingCost` | `app/verkoop/omzetrekening.py` → alleen `classificeer_regel` + `REDEN_OMZETREKENING_ONTBREEKT`; `voorstel._met_regelsoort` vult niets aan (geen code = `ontbreekt`/leeg, onbekende code = `onbekend`/leeg); `autoboeken._regels_geblokkeerd`: beide → `omzetrekening_ontbreekt: regel N (regelsoort): geen grootboekcode (cbc:AccountingCost) in de UBL — melden bij Vastly; ná de herzending 'Opnieuw aanbieden' (nooit een afgeleide rekening)` resp. "… is onbekend in het rekeningschema …". Bevinding `vastly_omzetrekening_ontbreekt` nu PER DOCUMENT (detail `document_id`, `reden`, `regelsoort`, deeplink) mét alleen "Opnieuw aanbieden". Verwijderd: `GET …/vastly-instellingen`, `PUT …/vastly-omzetrekeningen` + schema's, `VastlyOmzetrekeningenRij` (+ test) van Instellingen › Administratie › Algemeen, `RekeningKiezenActie`. Tabel blijft (lees-only, meetlat), geen migratie. Koppelcontract v1.21: §2d-uitbreiding v1.10 "ontbrekende code = mens kiest" herzien naar "zichtbaar weigeren — melden bij Vastly"; notitie 01-10 status "terugval AFGEZET 02-10". |
| 3 | Nazorg-CLI | `vastly-verkoop-heraanbieden` ongewijzigd in vorm; een niet-gekoppeld document noemt de weigering ("entiteit X: UBL draagt geen administratie-id en geen bekende KvK — melden bij Vastly"). |
| 4 | Guards afwezig-pad | `tests/verkoop/test_vastly_automatisch.py`: id zonder KvK → geboekt + rij `ubl`; id wint van KvK, bestaande rij blijft; onbekend/ongeldig/leeg id → geweigerd zonder KvK-terugval (parametrisch); mens-rij leest nog, geen nieuwe (`koppel_entiteit` bestaat niet); regel zonder code nooit afgeleid — óók niet met een bestaande historie-rij in `vastly_omzetrekening`; vervallen routes 404; "Opnieuw aanbieden" zonder code = geweigerd mét reden. Gouden set **ao** (`tests/keten/test_ao_vastly_verkoop_automatisch.py`): zonder AccountingCost = geweigerd + bevinding per document; id-route boekt zonder KvK en zonder mens; onbekende verhuurder = "melden bij Vastly", koppelroute 404. Bijgewerkt: `test_autoboeken.py`, `test_voorstel_en_checks.py`, `test_creditnote_gate.py`, `test_verwerking.py` (bestaande mens-rij direct ingevoegd), `test_nameting_workflow.py`; vitest `VastlyActies.test.tsx`. `test_soort_stand.py` ongewijzigd groen (dezelfde drie soorten, teksten `direct_actie_reden` herschreven). |

## Migratie 0173 (afsluit-routine)

1. `make migrate` tegen de dev-database `boekhouding`: `Running upgrade 0172 -> 0173` (gedraaid 02-10 09:4x, < 2 s); CHECK op de dev-DB
   gelezen: `bron = ANY (ARRAY['identiteit','mens','ubl'])`.
2. Live ná de upgrade op een eigen uvicorn (poort 8000, dev-DB): `GET /reconciliatie/bevindingen` → **200**;
   `POST /reconciliatie/vastly/entiteit-koppelen` → **404** (route weg, bedoeld); `GET /health` → 200.
3. `scripts/dump_schema.sh` vanuit de repo-root: `schema_referentie.sql ververst vanaf boekhouding_test (head 0173)` (2 regels gewijzigd).

## Poorten

- Gerichte run (tests/verkoop, keten ao, intake creditnote/verwerking, soort-stand, nameting-workflow, migratie-guard, cli-smoketest):
  233 groen ná twee testcorrecties (tekst "onbekend in het rekeningschema" behouden; telling 2 entiteiten in de CLI-regel).
- Volledige backend-suite, vitest en `tsc -b`: zie de regel "Poort" onderaan (ingevuld ná de run).
- Doc-guards: rapporten-index, gelezen-regels, CLAUDE.md-verwijzingen, regels-index — zie "Poort".

## Keuzes zonder Peter

1. **Onbekend id = weigeren zonder KvK-terugval.** De opdrachttekst zegt "daarna de bestaande KvK-route ongewijzigd"; dat geldt als het
   element ONTBREEKT. Draagt de UBL een id dat de module niet kent, dan zou een KvK-treffer "stil een andere administratie kiezen" zijn —
   precies wat koppelcontract §2d-notitie 01-10 punt 3 verbiedt. De bevinding noemt het id.
2. **Entiteit-bevinding zonder module-handeling.** Afwijking van reconciliatie-regel 1 ("élke bevinding draagt een actie"), per opdracht:
   de handeling is "melden bij Vastly" (de UBL hoort het id te dragen); de rij blijft in stand `actie` (actiemail) zodat het kantoor het ziet.
3. **`vastly_omzetrekening_ontbreekt` per document** i.p.v. per (administratie, regelsoort): de enige handeling ("Opnieuw aanbieden")
   is per document; de regelsoort staat in het detail.
4. **Migratie 0173** hoewel de opdracht "geen migratie nodig" zei — dat ging over `vastly_omzetrekening` (klopt, die blijft); de CHECK op
   `vastly_entiteit_koppeling.bron` kende `ubl` niet.
5. **OPEN_ITEMS**: item `AccountingCost` AFGEVINKT (RLZ-deel klaar) hoewel het item zelf "seintje gegeven" als tweede afvinkvoorwaarde
   noemt — het seintje loopt onder r.14 (Cowork/Peter) en is geen onderdeel van deze opdracht; item administratie-id NIET afgevinkt
   (afvinken ná de her-aanlevering, zoals Vastly vroeg).

## Bijvangst (deel 1 van de sessie — terminal-opdracht `opdrachten/terminal/2026-10-01-webhook-herzenden-11-events-afleveren.md`)

Elf job-executies `webhook-herzenden --uitvoeren --afleveren` (Rubicon 6, ARVUM 5), alle elf `afgeleverd — resultaat verwerkt`
(executies 88xsq, js76r, czmmh, cg6cl, rcd4h, 7hg9s, dc4kp, nx2fj, gjkc2, 4gzqz, 9w9hn; geen `kostenintake_uit`, geen waarschuwing in het
job-log). De job-uitvoer print alleen het effectieve `resultaat`; het geneste `kostenvoorstellen.resultaat` staat uitsluitend in het
audit (`ontvanger_antwoord`, ≤ 500 tekens) en is zonder DB-toegang niet in deze sessie uitgelezen — meetlat `db-lezen webhook-outbox`
toont `laatste_resultaat`, niet het ruwe lichaam (mogelijke verbetering: kolom `ontvanger_antwoord` in de query). Stap 4 (nameting
`vastly-verkoop`) → bot-commit `812a43b`, gepulled. Terminal-opdracht niet gecommit (opdrachttekst: "niets committen bij het terminaldeel").

## Nazorg / open

- Passkey-refresh-TTL over de zomertijdwissel (zie Poort b): aparte opdracht, auth-domein (LEESPLICHT auth-toegang).
- Inpensas INP-2026-0025 open maar geen autoboek-kandidaat (administratie niet `is_vastgoed`) — feit voor Cowork bij r.14.
- Meetlat-bijvangst gefixt: `--administratie ARVUM` → "ARVUM B.V." in `nameting.yml`.

## Gelezen regels

- `docs/regels/omzet.md` — 354 regels (323 vóór deze run)
- `docs/regels/intake-extractie.md` — 430 regels
- `docs/regels/reconciliatie.md` — 306 regels
- `docs/regels/werkloop-productie.md` — 350 regels
- Platform/OPEN_ITEMS.md (items administratie-id + AccountingCost), BESLISSINGEN "VASTLY-VERKOOP VOLLEDIG AUTOMATISCH …",
  koppelcontract §2d + notities 01-10.

## Poort

- Backend volledige suite (zonder `-x`, 68 min): 7715 groen, 5 rood — (a) 4 × gouden-set-casus k `test_k_projectverdeling_hercontrole.py`: latente datumafhankelijkheid (vaste peildatum `date(2026, 10, 2)` valt vanaf 02-10 in de boekmaand van de fixture → hercontrole slaat over); gefixt in deze run met de bestaande helper `na_boekmaand()` (precies waarvoor die helper 08/11-09 is gebouwd) → casus k 8 groen; (b) 1 × `tests/auth/test_kantoor_passkeys.py::test_registratie_en_passkey_login_met_bestaande_jwt_semantiek`: refresh-token-TTL komt 1 uur te kort uit (30 dagen vooruit valt nu over de zomertijdwissel 25-10; `verloopt_op − aangemaakt_op` = 29 d 23 u) — PRE-EXISTEND, auth onaangeraakt in deze run, faalt ook los op HEAD; niet gefixt (domein auth, buiten de opdracht) → **klikpunt/vervolg: DST-vaste TTL-berekening in het passkey-refreshpad + test**. Eerste run mét `-x` strandde op diezelfde passkey-test (481 groen tot dan).
- Vitest volledig: 275 bestanden / 2072 tests groen · `tsc -b`: exit 0
- Doc-guards (rapporten-index, gelezen-regels, CLAUDE.md-verwijzingen, regels-index, klikpunten, keten-guard): 16 groen
