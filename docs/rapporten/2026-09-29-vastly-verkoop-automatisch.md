# Vastly-verkoopfacturen volledig automatisch — entiteitenregister, omzetrekening per administratie, geen verzamelbak, geen drempels (29-09-2026)

**Opdracht:** `opdrachten/gedaan/2026-09-29-vastly-verkoop-volledig-automatisch-geen-verzamelbak-geen-drempels.md` (Peter 28-09:
"nee, deze huurfacturen horen daar sowieso niet in te staan (ik wil ze niet eens zien). De koppeling met de boekhouding staat en dan
moet het gewoon als omzet geboekt worden, punt"; 29-09: "ik hoef al die uitleg niet, concreet. wat moet er gebeuren want ik wil dit nu
opgelost hebben"). Handmatige CC-sessie, één run. Herziet de opt-in/drempels van 15-08 (verkoop-autoboeken) en 30-08 (v2).
**Werkt in productie: niet gemeten** — de échte heraanbieding van de 23 + 9 is een job-executie ná Peters "ja"; dry-run + nameting =
vervolg-opdracht `opdrachten/inbox/2026-09-30-nameting-vastly-verkoop-na-deploy-en-echte-run.md` (niet vóór 30-09 09:00), dispatch-onderdeel
`vastly-verkoop`. BESLISSINGEN-sectie "VASTLY-VERKOOP VOLLEDIG AUTOMATISCH — ENTITEITENREGISTER, OMZETREKENING PER ADMINISTRATIE, GEEN
VERZAMELBAK (Peter 29-09)"; regeltekst `docs/regels/omzet.md` alinea "Vastly-verkoop volledig automatisch (Peter 29-09)". Migratie 0172.

## Samenvatting

Een Vastly-huurfactuur (UBL mét markering `VASTLY-VERKOOP`) gaat sinds deze run zonder mens van intake naar geboekte omzet in Reeleezee:
de verhuurder wordt herkend via het entiteitenregister (KvK → identiteit van de administratie, of een éénmalig door een mens gekoppelde
naam), de grootboekrekening komt uit de UBL (`AccountingCost`) of anders uit de vaste Vastly-omzetrekening van de administratie per
regelsoort, en de btw volgt de UBL-categorie mét het standaardtarief van de administratie als er twee passende codes zijn. De twee
weigerredenen die de 23 open UBL's van 23-09 blokkeerden — "geen grootboekcode in de UBL — mens kiest" en "factuur-btw is ambigu … geen
onthouden keuze" — bestaan niet meer. Een Vastly-verkoopdocument staat nooit meer in de verzamelbak; alleen een échte onmogelijkheid
(verhuurder onbekend, omzetrekening niet afleidbaar, boeking gestrand) is één bevinding mét één handeling in het nieuwe reconciliatieblok
"Vastly-verkoop". De 23 + 9 wachtende documenten gaan ná Peters "ja" in één job-executie door hetzelfde pad.

## Vastgesteld vóór de bouw (code + regels, geen productie-toegang in deze run)

- `app/intake/verwerking.py` wees een Vastly-verkoop-UBL toe op de TENAAMSTELLING van de leverancier (`_wijs_toe_of_verzamelbak`,
  hetzelfde geheugen als inkoop) en zette de rest in de verzamelbak mét reden `vastly_verkoop_zonder_eenduidige_entiteit` — precies de 9
  Van Rooijen/Schaalje-rijen (de administratie heet "B. van Rooijen / G. Schaalje", de UBL zegt "B. van Rooijen").
- `app/verkoop/autoboeken.py::_regels_geblokkeerd` weigerde een regel zónder `AccountingCost` ("mens kiest") en een btw-ambiguïteit zonder
  `verkoop_btw_voorkeur` — het koppelcontract §2d v1.10 zegt dat Vastly de code per regel vult, de 23 + 9 UBL's droegen 'm niet
  (OPEN_ITEMS-vraag aan Vastly, punt 8).
- De verkoop-boekmotor schreef bij een AUTOMATISCHE boeking geen voorstel-rijen (`verkoop_voorstel_regel` alleen bij een mens-opslag) — er
  was dus geen eigen historie om een omzetrekening uit af te leiden.
- Er is geen JournalEntryLines-cache; "RLZ-historie: verkoopregels op 8xxx" zou een live GET in het boekpad zijn.
- De AI-heraanbied-motor en `_pdf_extractie_detail` kenden geen soort-poort: een verkoopfactuur met een PDF-suffix op het hoofdbestand kon
  de AI bereiken (bijvangst RUB-2026-0034, 24-09 07:11).

## Gebouwd (acht punten van de opdracht)

| # | Opdracht | Gebouwd |
|---|---|---|
| 1 | Entiteit → administratie via het register | `app/verkoop/entiteit.py` + tabel `boekhouding.vastly_entiteit_koppeling` (0172): KvK-koppelingsrij → `administratie_identiteit.kvk` (precies één actieve administratie; treffer vastgelegd, bron `identiteit`) → naam-koppelingsrij (uitsluitend mens). Nooit tenaamstelling/afzender/toewijzings-geheugen. Onbekend = geregistreerd zónder administratie mét reden `vastly_entiteit_niet_gekoppeld: kvk=…\|naam=…\|weergave=…`; `lijst_verzamelbak` filtert deze én de oude reden weg (`redenen.is_vastly_verkoop_reden`); één kantoorbrede bevinding per entiteit mét "Koppel aan administratie…" (`POST /reconciliatie/vastly/entiteit-koppelen`, élke kantoorrol → rij bron `mens` + audit `vastly_entiteit_gekoppeld` + directe heraanbieding van díé documenten). |
| 2 | Omzetrekening per administratie | `app/verkoop/omzetrekening.py` + tabel `boekhouding.vastly_omzetrekening` (0172): `AccountingCost` bekend wint (onbekende code blijft blokkerend + autovraag, §2d); anders de rij per (administratie, regelsoort huur/servicekosten/waarborg/overig — pure tekst op `Item/Name`); geen rij → afgeleid + vastgelegd (bron `historie`): eigen geboekte Vastly-verkoopregels (meest gebruikt per regelsoort, anders over alle) → rekeningschema (precies één actieve omzetrekening 8xxx soort 1 mét de regelsoort in de naam) → precies één 8xxx in het schema; niets = `omzetrekening_ontbreekt` → bevinding `vastly_omzetrekening_ontbreekt` mét "Rekening kiezen" (`PUT /administraties/{id}/vastly-omzetrekeningen`, Beheerder, bron `mens` wint). Instellingen › Administratie › Algemeen: rij "Vastly-omzetrekeningen" (`VastlyOmzetrekeningenRij.tsx`, GET `…/vastly-instellingen`) mét de gekoppelde entiteiten eronder. In `voorstel.py` krijgt een regel zonder code `ledger_id` + `gb_code_status='bekend'` + `gb_bron='omzetrekening'`. |
| 3 | Btw deterministisch | `voorstel._resolve_btw`: > 1 dekkend tarief zonder onthouden keuze → `_administratie_standaard_tarief` (administratie-default `standaard_taxrate_id` als die in de set zit → meest gebruikt in eigen geboekte verkoopregels → basistarief = kortste naam, "NL, Hoog Tarief" vóór "(vooruit)"), vergrendeld, bron `administratie_default`. Een eerdere mens-keuze (`verkoop_btw_voorkeur`) wint. 0 %/vrijgesteld volgt de UBL-categorie (ongewijzigd, 22-09-regel niet-btw-plichtig ongewijzigd). |
| 4 | Autoboek zonder drempels | `autoboeken._regels_geblokkeerd` mét reden-sleutels `omzetrekening_ontbreekt: regel N (regelsoort): …`, `gb_code_onbekend: …`, `btw_niet_bepaalbaar: …`; toegestane btw-bronnen + `administratie_default` + `niet_btw_plichtig`; `beoordeel_lees_only` = dezelfde poorten zonder boeken. Harde checks, volumerem (alleen automatisch), mogelijk-duplicaat en "mens-opgeslagen voorstel wint" onverkort. `boeken.py` legt nu óók bij een automatische boeking het gebruikte voorstel (kop + regels) vast — herleidbaarheid + bron voor de historie van punt 2. Werkvoorraad-tellers per administratie: ONGEWIJZIGD (zie Beslispunten). |
| 5 | UBL nooit door de AI | `documenten/service._pdf_extractie_detail` → soort `verkoopfactuur` = `ai_extractie_overgeslagen: ubl_deterministisch_geen_ai` (ook mét PDF-suffix), `herextraheer_document` weigert een verkoopfactuur, `aikosten/heraanbieden.vind_kandidaten_documenten` slaat verkoopfacturen over. |
| 6 | Nazorg-CLI | `vastly-verkoop-heraanbieden [--dry-run] [--uitvoeren] [--administratie <uuid\|naamdeel>]` (`app/verkoop/heraanbieden.py`; dry-run default; alle vormen uit het meetrecept letterlijk in de suite): (a) niet-gekoppeld → UBL opnieuw gelezen → register → administratie zetten (tijdlijn `vanuit: entiteitenregister`, audit `vastly_entiteit_toegewezen`, géén toewijzings-geheugen) + gewone extractieroute (post-commit-hook = autoboek); (b) open `te_controleren` per is_vastgoed-administratie → `probeer_verkoop_autoboeken_na_intake`. Eén audit `vastly_verkoop_heraanbieding_run` per run → dagteller `vastly_verkoop_heraanbieding` in de reconciliatiemail. Dezelfde motor: dagelijkse stap in `reconciliatie-alles` (échte run vóór de blokken; lees-only = telling) + ná élke koppeling. Nameting-allowlist alleen `--dry-run`. |
| 7 | Reconciliatieblok `vastly_verkoop` | `app/verkoop/reconciliatie.py` (in `run.BLOKKEN` ná `intake`): `vastly_entiteit_niet_gekoppeld` (platformbreed, één per sleutel), `vastly_omzetrekening_ontbreekt` (administratie × regelsoort), `vastly_verkoop_niet_geboekt` (per open Vastly-verkoopdocument > 1 dag mét reden; "Opnieuw aanbieden" = `POST /reconciliatie/vastly/documenten/{id}/opnieuw-aanbieden`, boeken_mislukt → te_controleren → autoboek; 409 geen kandidaat, 404 buiten scope). Alle drie DIRECT in `actie` (`direct_actie_reden`; explosie-rem blijft). Teksten `teksten._vastly_verkoop`; frontend `VastlyActies.tsx` + BLOK_LABEL "Vastly-verkoop". |
| 8 | Vraag aan Vastly | `Platform/OPEN_ITEMS.md`: "RLZ → Vastly: VRAAG — wordt `cbc:AccountingCost` per factuurregel nog gevuld?" (geen blokkade; een code die er staat wint). |

Meetlat: `db-lezen vastly-verkoop` (platform: runs, koppelingen, niet-gekoppelde documenten, kantoorbrede bevindingen) +
`db-lezen vastly-verkoop-administratie --administratie …` (open documenten, omzetrekeningen, autoboek-audits, bevindingen — RLS per
administratie); dispatch-onderdeel `vastly-verkoop` (if-tak + `options:` + `via_gh_onderdeel` + OORDEEL_BRON; dry-run kantoorbreed + beide
queries voor Rubicon/Elissen/ARVUM/Meyer/Shuto/Inpensas/Rooijen + request-log van de handelingen).

## Migratie 0172 (afsluit-routine)

1. `alembic upgrade head` tegen de dev-database `boekhouding`: `Running upgrade 0171 -> 0172` (gedraaid in deze sessie, < 2 s).
2. Live 200 ná de upgrade op de draaiende backend (poort 8000, eigen uvicorn): `GET /administraties/{id}/vastly-instellingen` → 200
   (vier regelsoorten leeg, keuzelijst leeg — dev-administratie zonder 8xxx-cache); `POST /reconciliatie/vastly/entiteit-koppelen` mét
   sleutelsoort `iban` → 422 (poort werkt).
3. `scripts/dump_schema.sh` vanuit de repo-root: `schema_referentie.sql ververst vanaf boekhouding_test (head 0172)` (+111 regels).

## Dry-run 23 + 9 — niet in deze run gedraaid (productie alleen via de gedeployde job)

De opdracht vroeg "dry-run in het rapport". Productie is uitsluitend bereikbaar via de gedeployde job-image (regel Peter 08-09); de code
van deze run staat pas ná de deploy op die image. De dry-run-telling kantoorbreed komt daarom uit stap 1 van de vervolg-opdracht
(`gh workflow run nameting -f onderdeel=vastly-verkoop` → `vastly-verkoop-heraanbieden --dry-run` als bot-bestand op main). Verwachting op
de stand van 28-09: TOTAAL 32 kandidaten = 23 `open_in_administratie` + 9 `niet_gekoppeld`; per uitkomst `zou_boeken` voor élke UBL waarvan
de administratie een afleidbare omzetrekening heeft (precies één 8xxx of één mét "huur"/"service" in de naam, of eigen historie — Elissen
en Rubicon hebben 6 geboekte facturen als historie), `geweigerd` mét `omzetrekening_ontbreekt` voor administraties mét meerdere
omzetrekeningen zonder naam-treffer (→ bevinding "Rekening kiezen", éénmalig), `entiteit_niet_gekoppeld 9` voor Van Rooijen/Schaalje tot
Peter de koppeling in de bevinding zet (KvK ontbreekt op die UBL's als natuurlijke persoon → naam-sleutel `b van rooijen`). De échte run =
`gcloud run jobs execute rlz-reconciliatie --region europe-west4 --args=-m,app.cli,vastly-verkoop-heraanbieden,--uitvoeren --wait` in
Peters owner-sessie ná zijn "ja" op de dry-run.

## Keuzes zonder Peter en beslispunten

- **Werkvoorraad-tellers per administratie ongewijzigd (beslispunt).** De opdracht (punt 4) vroeg "geblokkeerd = bevinding … NIET in de
  werkvoorraad-tellers van de administratie". De teller-cache (`werkvoorraad/tellers.py`) telt statusovergangen zonder documentsoort; een
  soort-uitzondering raakt élk scherm en de nachtelijke herberekening. Gekozen: een geweigerd Vastly-document staat als `te_controleren`
  in zijn administratie (telt dus mee) totdat de bevinding is afgehandeld — de kantoorbrede bevinding is de handeling. Zodra alles boekt
  (verwachting ná de échte run) is de teller vanzelf 0. Wil Peter de teller-uitzondering alsnog, dan is dat een eigen kleine opdracht.
- **RLZ-historie niet live gelezen.** Geen JournalEntryLines-cache; een GET per administratie in het boekpad = latentie- en
  storingsrisico. Eigen historie + eenduidig rekeningschema dekken de zes vastgoed-administraties; de rest is één "Rekening kiezen".
- **Mens-opgeslagen voorstel blijft winnen** (autoboek weigert, bevinding zegt het): een controleur die aan een voorstel zat is de
  eigenaar — zelfde lijn als 15-08.
- **Dagelijkse heraanbieding vóór de blokken** in `reconciliatie-alles`: wat boekt is geen bevinding meer; lees-only = alleen telling.
- **Regelsoort-woordenboek** is pure tekst (waarborg → servicekosten → huur → overig), geen AI.
- **Drie soorten direct in `actie`** (uitzondering op "nieuw start in meten", zoals `intussen_extern_geboekt`): het is het bestaande
  deterministische boekpad dat op één registerrij wacht, elk mét één handeling; de explosie-rem (> 50/run) blijft.

## Poorten

- Backend gericht: `tests/verkoop/test_vastly_automatisch.py` (12: register KvK/naam/fouten/roundtrip, omzetrekening classificatie +
  afleiding + Beheerder wint + 422, heraanbieden dry-run/echt/CLI-vormen/koppelen, dagteller, drie AI-guards, reconciliatieblok drie
  soorten + leesbare teksten + `--alleen vastly_verkoop --lees-only`, routes koppelen/instellingen/PUT 403/422/opnieuw-aanbieden 200/409/404),
  `test_autoboeken.py` aangepast (geen grootboekcode → boekt op de afgeleide omzetrekening; btw ambigu → boekt mét `administratie_default`;
  niets afleidbaar → `omzetrekening_ontbreekt`), `test_btw_uit_factuur.py` + `test_voorstel_en_checks.py` aangepast aan de 29-09-regels,
  `test_creditnote_gate.py` (routering via het register), `test_soort_stand.py` (lijst direct-actie-soorten), `test_nameting_workflow.py`
  (+ guard `test_onderdeel_vastly_verkoop_…`). Gouden set: casus **ao** `tests/keten/test_ao_vastly_verkoop_automatisch.py` (3: KvK →
  toegewezen + geboekt zonder AI + webhook + regels 1000/0 + 200/42; zonder AccountingCost → vaste omzetrekening bron `historie`;
  onbekende verhuurder → geen verzamelbak, bevinding, koppelen via de route → geboekt), fixture `ao_vastly_verkoop_rub_2026_0099`
  (Vastly-golden-case-vorm, geanonimiseerd). Gerichte runs: verkoop + intake + reconciliatie + unit-guards + keten **groen** (149 + 172 + 93 + 31).
- Frontend: `VastlyActies.test.tsx` (5) + `VastlyOmzetrekeningenRij.test.tsx` (2); volledige vitest **276 bestanden / 2076 tests groen**;
  `tsc -b` groen.
- Volledige backend-suite op de werkboom: zie de regel "Volledige suite" hieronder (ingevuld ná afloop).
- Ruff schoon op de nieuwe bestanden; bestaande niet-format-schone bestanden alleen op de eigen regels geraakt.

## Volledige suite

Volledige backend-suite op de werkboom (boekhouding_test, 1:04:42): **7691 passed, 8 failed, 1 skipped, 31 deselected**; de acht rode
pinden de OUDE regels en zijn in dezelfde run bijgewerkt en opnieuw groen gedraaid (98 passed): `tests/intake/test_golden_cases_vastly.py`
(6: de golden-cases routeerden op de tenaamstelling "Rubicon Investments B.V." → nu via `administratie_identiteit.kvk` 87654321 uit de
golden UBL), `tests/intake/test_verwerking.py::test_vastly_verkoop_markering_routeert_naar_omzetkant` (naam-koppeling via het register
i.p.v. tenaamstelling), `tests/reconciliatie/test_rlz_dubbel.py::test_zonder_opties_ongewijzigd_alle_blokken_via_voer_uit` (blokkenlijst +
`vastly_verkoop`). Eerder in de run al bijgewerkt vóór de suite: `tests/activa/test_reconciliatie.py::test_blok_staat_in_run_blokken`
(pinde `BLOKKEN[-2:]`). `tests/auth/test_kantoor_passkeys.py` gedeselecteerd (bekend DST-kalender-artefact, rood 26-09 t/m 25-10, rapporten
25-09/28-09). Bijvangst: het rapport `2026-09-28-universal-mi-extract.md` (vorige sessie) miste de vorm van "## Gelezen regels" en maakte de
guard `test_rapporten_gelezen_regels` rood — één regel "geen domeinregels gelezen — reden: …" toegevoegd. Volledige vitest 276 bestanden /
2076 tests groen, `tsc -b` groen. Frontend-pixelsweep (`keten_sweep.sh`) niet gedraaid: geen wijziging onder `frontend/src/document` of aan
de controlescherm-/lijst-DTO's (de nieuwe schermdelen zijn Inzicht › Reconciliatie-acties en een instellingenrij).

## Werkt in productie

**Niet gemeten.** Meetrecept = vervolg-opdracht `2026-09-30-nameting-vastly-verkoop-na-deploy-en-echte-run.md`: (1) deploy-check service ÉN
jobs op deze commit + migratie 0172; (2) `gh workflow run nameting -f onderdeel=vastly-verkoop` (dry-run kantoorbreed + `db-lezen
vastly-verkoop` + `db-lezen vastly-verkoop-administratie` per vastgoed-administratie + request-log van de handelingen); (3) klikpunten Peter:
"Koppel aan administratie…" voor B. van Rooijen (9) en zijn "ja" → échte job-executie `--uitvoeren`, daarna opnieuw (2): verwacht 0
kandidaten óf alleen `geweigerd` mét reden als bevinding; (4) `db-lezen ai-heraanbieding` → 0 verkoopfacturen; reconciliatiemail 30-09 mét de
dagteller "Vastly-verkoop automatisch".

## Gelezen regels
- `docs/regels/omzet.md` (276 regels vóór deze run) — volledig
- `docs/regels/intake-extractie.md` (430 regels) — volledig
- `docs/regels/autoboeken-ai.md` (134 regels) — volledig
- `docs/regels/reconciliatie.md` (306 regels) — volledig
- `docs/regels/werkloop-productie.md` (332 regels) — volledig
- Verder: CLAUDE.md volledig (548 regels vóór deze run), `Platform/contracten/KOPPELCONTRACT_RLZ_VASTGOED.md` §2d + §8,
  `docs/gesprekken/2026-09-28.md` + `2026-09-29.md`, `Platform/registers/entiteiten.md`.
