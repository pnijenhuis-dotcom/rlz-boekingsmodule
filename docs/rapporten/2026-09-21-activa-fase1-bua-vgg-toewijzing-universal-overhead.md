# Rapport 21-09 — Drie besluiten Peter: (A) Activa/MVA akkoord → fase 1 gebouwd; (B) BUA-rekeningen lees-only meting + bulk-voorstel; (C) VGG toewijzing pand + soort verkoop RLZ-01-00000082 (CLI, productie ná deploy); (D) capture Universal overhead = géén OVH-project

**Opdracht:** `opdrachten/gedaan/2026-09-21-activa-mva-akkoord-fase-1-plus-bua-rekeningen-meting-plus-vgg-toewijzing-schrijf-c.md` (Peter 21-09:
"activa, JA"; BUA-vraag; "ik volg jouw advies" op VGG-beslispunt 1; "Universal moet juist overhead verdelen over projecten, zo houden").
**Migratie 0168** (schema-only: `grootboekrekening.is_activa`, `activa_instelling`, `activum_koppeling`). Geen RLZ-/Odoo-write in deze run.
**Werkt in productie: niet gemeten** — álles gaat mét de deploy van deze commit live; de productiestappen staan als twee vervolg-opdrachten in
`opdrachten/inbox/` mét `niet vóór: 2026-09-22 09:00` (`2026-09-22-nameting-activa-fase1-en-bua-kandidaten-na-deploy.md`,
`2026-09-22-vgg-toewijzing-schoffelstraat-29-plus-schrijf-c.md`).

**Poging 1 → 2 (procesnotitie, rij j3).** Poging 1 (drie parallelle bouwagenten A-backend/A-frontend, B, C + coördinator) bouwde alles maar haalde
de poort niet binnen de run (de volledige suite liep nog toen de run eindigde — les "inbox-run eindigt niet wachtend op suite"); het werk ging als
WIP-commit `3113955` op branch `wip/2026-09-21-activa-mva-akkoord-fase-1-plus-bua-rekeningen-meting-plus-vgg-toewijzing-schrijf-c` (blijft ter controle staan). Poging 2 begon met
`git merge --squash` van die branch (68 bestanden, 0 conflicten), vond drie gaten en dichtte ze: (1) de BESLISSINGEN-sectie "ACTIVA / MVA — FASE 1
GEBOUWD (Peter 21-09)" ontbrak terwijl CLAUDE.md, `docs/regels/activa.md` en de migratie er al naar verwezen (guard
`test_claude_md_beslissingen_verwijzingen` zou rood zijn); (2) het eindrapport + INDEX-regel ontbraken (de scratch-rapporten per blok stonden in
`.scratch/2026-09-21-activa/`); (3) de referentiedump `schema_referentie.sql` was niet ververst. Verder: 15 × ruff E501 in twee docstrings herwrapt,
een achtergebleven agent-instructiecommentaar (`<!-- DOEL: … -->`) uit `docs/regels/btw.md` gehaald, twee placeholder-verwijzingen
(`<slug>`, `<21-09-rapport>`) in BESLISSINGEN vervangen door dit bestand.

## A. Activa / MVA — akkoord → fase 1 GEBOUWD (migratie 0168)

Capture: status ONTWERP TER AKKOORD (16-09) → AKKOORD 21-09 mét alle defaults §8, in BESLISSINGEN (registerrij 16-09 + nieuwe sectie "ACTIVA / MVA —
FASE 1 GEBOUWD (Peter 21-09)"), `docs/regels/activa.md` (alinea 21-09), CLAUDE.md (regel "geen bouw vóór akkoord" vervangen), `WAT_IS_NIEUW.md`
(release-blok 2026-09-21), api-verkenning "Activa — STAP-0 21-09", mockup `controlescherm-v2.html` notitie ⑨ (UX-review-regel 15-08).

**Nulmeting 21-09** (`nameting.sh activa-nulmeting`, executie `rlz-reconciliatie-hrtzq`, `verkenning/nameting-activa-nulmeting-21-09.txt`):

| meting | uitkomst |
|---|---|
| administraties / mét MVA-rekeningen / MVA-rekeningen | 78 / 75 / 344 |
| activa in RLZ-registers | 51 in 7 registers — Pilates Bloom B.V. 20 (rijkste → fase 1 eerst hier), Zilver Beheer 13, Mantelzorgwoningen Midden Nederland 11, Belastingbutler 3, Beauty by Tessa Elst 2, Dimo Living & Styles 1, L.H.G. Holding 1 |
| register 403 "recht ontbreekt" | Universal Steigerbouw (0113 € 9.690), Rubicon Investments (28 MVA-rekeningen, 0113 Verhuurmateriaal € 5.225.769,67) — klikpunt Peter: RLZ-recht "Vaste activa" op de webservice-login |
| module-regels op MVA-rekeningen (400 d) | 1 (€ 45,67, onder de grens) |

STAP-0 (Pilates Bloom): RLZ schrijft zelf af (`CurrentBookValue`/`CurrentDepreciationValue`: 10.000 op 18-11-2024 → 3.674 afgeschreven op 21-09-2026 =
"Lineair 5 jaar"), `DepreciationMethod` via `$expand` op de collectie, `JournalEntryList`/`BalanceAccount`/`DepreciationAccount` komen op de collectie niet
mee (record-vorm = fase-2-STAP-0); `AdministrationSettings.FixedAssetAlertAmount` 450,0; root-enumeraties `AssetTypes` 1 Fixed / 2 Stock,
`AssetMutationTypes` 1 Purchase / 3 Sale / 4 Revaluate / 5 Depreciate / 6 Manual.

**Gebouwd (ontwerp §7 fase 1; volledige tekst in BESLISSINGEN-sectie A, contract `.scratch/2026-09-21-activa/CONTRACT_A.md` + `contract_afwijkingen_A.md`):**
1. Datamodel 0168: `platform.grootboekrekening.is_activa` (RLZ `IsFixedAssetAccount` ÉN AccountType 3 ÉN 0xxx via `activa/categorie.is_mva_rekening`
   in de Ledgers-sync; Odoo `asset_fixed`), `boekhouding.activa_instelling` (opt-in default UIT, grens 450, RLZ-grens, termijnen/afschrijvingsrekening
   per categorie JSONB, register-probe), `boekhouding.activum_koppeling` (document × regel × boek_cyclus ↔ RLZ-activum; `gepland` | `aangemaakt` |
   `overgeslagen` | `mislukt` | `beoordelen`; geen DELETE-grant). RLS op administratie.
2. Register-lezer + probe (`activa/register.py`, `instelling.py`; nieuwe `RlzClient`-methoden `get_fixed_assets`, `get_fixed_asset`, `put_fixed_asset`,
   `get_depreciation_method_headers`, `get_administration_settings`) — in `sync_alles_voor_administratie` ná de ledgers-sync voor élke administratie mét
   ≥ 1 `is_activa`-rekening; 403 = zichtbaar "recht ontbreekt (403)", nooit blokkerend, nooit stil.
3. Detectie bij boeken (`activa/voorstel.py`, geen RLZ-call): kandidaat = opgeslagen boekvoorstelregel op een `is_activa`-rekening mét netto ≥ effectieve
   grens (RLZ > instelling); onder de grens = oranje signaal; categorie deterministisch op de rekeningnaam (steigermateriaal 60 mnd, restwaarde 0 —
   besluit 16-09); fiscale signalen als tekst (> 20 %/jaar art. 3.30 Wet IB, bodemwaarde WOZ, KIA/MIA mogelijk, categorie onbekend) — nooit een berekening.
4. Kaart "Activum aanmaken?" (`ActivaVoorstelKaart.tsx`, ná `OfferteMatchMelding`): voorstel-kaart-norm, `btn` "Activum aanmaken" / "Aanmaken ná boeken",
   `linkbtn` "Niet activeren…" mét verplichte reden, vijf standen, register dicht = RLZ-knoppen uit mét reden als `title`, chip "wordt activum" info-blauw
   (teal = actie, groen = status).
5. API (`activa/router.py`; rolpoort-sweep +5): `GET …/activa-voorstel`, `POST …/aanmaken`, `POST …/overslaan`, `GET/PUT …/activa-instelling` (Beheerder,
   audit `activa_instelling_gewijzigd`).
6. Schrijven in RLZ ná boeken (`activa/service.py`): client-GUID uuid5 (idempotent), `PUT FixedAssets/{guid}` → 204 → altijd terug-lezen → `aangemaakt`
   + tijdlijn + audit; élke fout = `mislukt` mét reden (zichtbaar, retry), nooit een exception in de boekflow; haak in `orkestratie.boek_document_met_
   doorbelasting` NÁ de geslaagde boeking (buiten de GEBOEKT-transactie); opt-in automatisch = herkomst `automatisch`, ontbrekende rekening = `mislukt`
   (geen stille no-op; guard afwezig-pad). Storno/tegenboeken → `beoordelen` ("activum beoordelen in RLZ (niet verwijderd)") — de module verwijdert nooit.
7. Instellingen › Boeken & AI › Activa (`ActivaInstellingenBlok.tsx`, registry `activa`): switch, grens mét RLZ-hint, categorie-tabel, activarekeningen,
   registerstand, tellers; Opslaan links onder het blok.
8. Reconciliatieblok `activa` (`activa/reconciliatie.py`, `run.BLOKKEN` + `reconciliatie-alles`): `activa_register_niet_leesbaar`, `mva_boeking_zonder_activum`,
   `activum_zonder_boeking`, `afschrijving_niet_gelopen` (RLZ's eigen `CurrentDepreciationValue`), `activum_aanmaken_mislukt` — alle in `meten`, `sinds 2026-09-21`,
   élk mét actie; Odoo zichtbaar overgeslagen.

**Contract-afwijkingen A-backend (allemaal additief):** bedragen als strings, POST-body `aanmaken` optioneel (`termijn_maanden` 12..600 veelvoud van 12),
negatieve/0-regels geen kandidaat, register dicht weigert plannen niet (RLZ-write geeft dan `mislukt` mét 403-reden), tijdlijn-detail
`activum.tekst`, boek-respons `activa.automatisch`. De frontend bouwde op het contract vóór dat bestand bestond; DTO-veldnamen backend ↔ frontend
zijn in poging 2 vergeleken: 1:1 (0 verschillen).

**Migratie-afsluitroutine:** (1) dev-DB `boekhouding` op `0168 (head)` (`alembic current`); (2) live 200 op de dev-backend (uvicorn 8011, Beheerder-token):
`GET /administraties/{aid}/activa-instelling` → 200 (`activeringsgrens "450.00"`, `grens_bron "instelling"`), `GET …/documenten/{did}/activa-voorstel`
→ 200 (`kandidaten []`); (3) `scripts/dump_schema.sh` ververst (+166 regels: `activa_instelling`, `activum_koppeling`, FORCE RLS, `is_activa`), gedumpt vanaf
`boekhouding_test_a2` @ 0168 omdat `boekhouding_test` op dat moment de volledige suite droeg (header op `boekhouding_test` gezet).

## B. BUA — welke rekeningen krijgen `btw_aftrek_uitgesloten`? Meting + bulk-voorstel

Capture: BESLISSINGEN "BUA-KENMERK — LEES-ONLY METING + BULK-VOORSTEL (Peter 21-09)", `docs/regels/btw.md` (alinea 21-09), CLAUDE.md btw-rij 5.

**Meting 21-09** (leesreplica, per administratie in RLS-scope, `.scratch/2026-09-21-activa/bua-meting.tsv`; 78 actieve administraties, 75 mét treffer;
Bonte Hoeve, Camping "Nieuwenhoven" en Recreatief Vastgoed Nederland zonder BUA-rekening — vermoedelijk geen grootboeksync). Alle 297 treffers zijn de vier
RLZ-standaardrekeningen; geen afwijkende naam:

| code | naam (RLZ-standaard) | administraties | kenmerk aan | RLZ-/hist.-default | module-geboekt 2026 | advies |
|---|---|---|---|---|---|---|
| 4014 | Kantinekosten | 74 | 0 | geen | 0 regels | **beoordelen** |
| 4503 | Kosten promotie/sponsoring | 74 | 0 | geen | 0 regels | **niet zetten** |
| 4508 | Relatiegeschenken (beperkt aftrekbaar) | 75 | 0 | geen | 0 regels | **zetten** |
| 4510 | Representatiekosten (beperkt aftrekbaar) | 74 | 0 | geen | 2 regels, netto € 34,45, btw € 0,00 (T&J Hoveniers) | **zetten** |

Correctie op de contracttekst van poging 1: de twee 4510-regels zijn T&J Hoveniers (btw al in de kosten), niet BLOW; de Rituals-bon 88-186308 van 18-09
is in 2026 niet als module-geboekte 4510-regel terug te zien. Bank-direct-boekingen zaten niet in de replica-meting; de CLI meet ze wél (kolom `bank_*`).

**Fiscale nuance (accountant, geen basisuitleg).** Het kenmerk zet 100 % van de btw in de kosten. Dat is alleen exact voor het horeca-deel (art. 15 lid 5
Wet OB: spijzen/dranken in een horecagelegenheid — nooit aftrekbaar, geen drempel). Voor het overige representatie-/geschenkdeel geldt het BUA (art. 1 lid 1
sub c BUA jo. art. 16 Wet OB) mét de € 227-drempel per begunstigde per jaar: eronder is de btw wél aftrekbaar. Het kenmerk is dus bewust CONSERVATIEF:
- **4510 Representatiekosten — zetten.** Te veel btw in de kosten bij kleine representatie zónder horeca-component; bij relatie-diners/borrels is de
  jaareinde-correctie per begunstigde in de praktijk niet te maken → conservatief is de verdedigbare stand.
- **4508 Relatiegeschenken — zetten.** Hier zet het kenmerk vaker te veel btw weg dan bij 4510 (het gros van de geschenken per relatie blijft onder € 227),
  maar de begunstigde is niet uit een inkoopfactuur te lezen en aftrek-claimen-en-corrigeren gebeurt niet — precies Peters opmerking van 18-09.
- **4014 Kantinekosten — beoordelen, niet in de bulk.** Kantineregeling (art. 3 BUA) gaat juist uit van aftrek; correctie pas als de bevoordeling per werknemer
  (kostprijs + 25 % − eigen bijdrage) > € 227/jaar. Het kenmerk zou álle kantine-btw wegzetten en de jaareindeberekening verstoren. Alleen bij klanten die
  kantine als catering-in-horeca gebruiken (handmatig via het bestaande Beheerder-blok).
- **4503 Promotie/sponsoring — niet zetten.** Reclame/sponsoring is zakelijk en aftrekbaar (mits prestatie + factuur mét btw); een geschenkdeel hoort op 4508.
- Overige BUA-woorden (horeca/lunch/diner/consumpties → zetten; personeelsfeest/-uitje/giften → beoordelen) komen als rekeningnaam niet voor; `advies_voor`
  dekt ze voor afwijkende rekeningschema's.

**Drempel-variant (voorstel, geen bouw): niet bouwen.** Een stand "BUA-drempel" (aftrek eerst toestaan, jaareinde-signaal Σ per begunstigde > € 227) vereist de
begunstigde per regel — niet deterministisch uit een inkoopfactuur te halen (alleen als crediteur = begunstigde, bij geschenken zelden). Wat wél zinvol en
goedkoop is: het jaareinde-overzicht Σ 4508 + 4510 per administratie (netto, btw in kosten) zodat de accountant per klant beslist of een BUA-correctie/
suppletie (in de richting te weinig aftrek geclaimd) de moeite waard is — `bua-kandidaten --jaar` levert dat al per rekening.

**Bulk vs per administratie — oordeel: BULK, 4508 + 4510 kantoorbreed, in één data-stap ná Peters "ja".** 74–75 van 78 administraties dragen exact
dezelfde RLZ-standaardrekeningen mét "(beperkt aftrekbaar)" in de naam, het kenmerk staat nergens aan, nergens een RLZ-/historie-default die overschreven
zou worden, en het huidige jaar draagt 2 module-regels (€ 34,45) — het kenmerk werkt alleen op de prefill van nieuwe boekingen, niets wordt herboekt. 75 ×
dezelfde Beheerder-klik zonder onderscheidend criterium is het "invulwerk" dat het principe minimale mens verbiedt. Terugdraaibaar per administratie via het
bestaande scherm (`zet` = exacte set), zichtbaar in `audit_event` mét `bron`.

**Gebouwd:** lees-only CLI `bua-kandidaten [--administratie <uuid|naamdeel>] [--jaar 2026] [--detail] [--json-uit]` (`app/beheer/bua_cli.py`; per
administratie in haar eigen `scoped_session(aid)` — één cross-administratie-query in `scoped_session(None)` geeft in productie stil 0 rijen; selectie 4xxx
AccountType 2 mét een van 14 `BUA_NAAMDELEN`; kenmerk-stand, RLZ-/historie-default, module-geboekt per jaar, bank-direct apart; geen RLZ-call, voettekst zegt
dat; nameting-allowlist + dispatch-onderdeel `bua-kandidaten` mét oordeelregel) en schrijvende CLI `bua-kenmerk-zetten (--administratie | --alles) [--codes
4508,4510] [--dry-run]` (`btw_aftrek.voeg_toe` = bestaande set ∪ nieuw, systeem-actor, audit `btw_aftrek_uitgesloten_gewijzigd` oud→nieuw mét
`bron = "cli bua-kenmerk-zetten (opdracht Peter 21-09)"`, alleen bij wijziging, idempotent; in de schrijvende weigerlijst van `nameting.sh`, nooit in de
workflow). **Bijvangst gefixt:** `groep-saldi` (dispatch-onderdeel van 21-09 ochtend) ontbrak in de VGG-uitsluitingslijst van `nameting.yml` → die nameting
van 22-09 zou rood eindigen vóór de eigen tak; `groep-saldi` + `bua-kandidaten` toegevoegd + generieke guard.

**Productierecept (ná deploy):** (1) `gh workflow run nameting -f onderdeel=bua-kandidaten` → verwacht "TOTAAL 297 kandidaat-rekening(en) in 75 van 78
administratie(s) · 0 mét kenmerk aan · advies zetten: 149 · … · 0 fout(en)"; (2) `gcloud run jobs execute rlz-reconciliatie --region europe-west4
--args="^|^-m|app.cli|bua-kenmerk-zetten|--alles|--dry-run"` → "TOTAAL 149 rekening(en) in 75 administratie(s) zou zetten"; (3) **pas ná Peters "ja" op dit
rapport** zonder `--dry-run`; (4) nameting stap 1 → "149 mét kenmerk aan" + chip "aftrek uitgesloten (4510)" op een controlescherm. Stap 1 zit in de
vervolg-opdracht van 22-09; stap 2–4 wachten op Peter.

## C. VGG — beslispunt 1 beslist: toewijzing pand + soort `verkoop` RLZ-01-00000082 → CLI gebouwd, productie ná deploy

Capture: BESLISSINGEN "VGG — BESLISPUNT 1 BESLIST: TOEWIJZING PAND + SOORT VERKOOP RLZ-01-00000082 (Peter 21-09)", `docs/regels/vgg-odoo-migratie.md`
(alinea 21-09).

**Deterministisch pand-bewijs (leesreplica + `rlz-lezen`, geen AI):** het bewijspaar (Receipt € 400.000,00, 19-03-2026, Status 3, `InvoiceNumber` 171384,
relatie "O.N." = Ouwerkerk Notariaat, RLZ-id `8b079e5c…`) is afgeletterd tegen bankmutatie TransactionId `00112` = 20-03-2026 € 52.142,09 Ouwerkerk Notariaat
"Betreft: schoffelstraat 29 te Purmerend, ons dossier: 2026.079950.01" — één adres, één dossier, één notaris. De afleiding kon dit niet zelf (het Receipt draagt
alleen "171384"), daarom mens. Het productie-pandenregister van VGG is leeg (0 `pand`, 0 `pand_boeking`).

**Gebouwd:** CLI `pand-toewijzen` (`app/panden/toewijzen_cli.py`) — het eerste mens-toewijzingspad van het pandenregister (`herkomst='mens'` werd nergens
geschreven): `--administratie --boekstuk --soort --adres [--plaats --postcode --dossier --reden --actor --schrijf --json-uit]`; RLZ uitsluitend GELEZEN
(`Receipts?$filter=ReceiptNumber eq '…'&$top=2&$expand=Entity`, terugval SalesInvoices/PurchaseInvoices; 0 = STOP "niet gevonden", 2 = STOP "meerduidig",
`RlzApiError` = STOP); pand-code = de adres-sleutel van de afleiding (`AdresVoorstel.code` → `schoffelstraat-29`), nooit een tweede normalisatie; bestaand
pand hergebruikt (alleen lege velden aangevuld), anders nieuw pand herkomst `mens`, status `verkocht` mét verkoopdatum = documentdatum; `pand_boeking` upsert
(soort, herkomst `mens`, zekerheid `hoog`, reden, datum/bedrag uit RLZ, `bevestigd_door`/`_op`); zelfde stand = "ongewijzigd" (idempotent); hetzelfde
document op een ÁNDER pand = STOP exit 2 vóór er iets geschreven is; audit `pand_toegewezen_mens` + `pand_boeking_toegewezen_mens` oud→nieuw mét
`opdracht`-referentie, actor = Peter per e-mail (systeem-actor → `namens`); default DRY-RUN (zelfde stappen, teruggedraaid), `--schrijf` voert uit;
`nameting.sh` weigert het commando hard. Ná `--schrijf` geldt `vertaling.pand_telt` en herclassificeert de 8000-regel naar rol `opbrengst_panden` (803100):
het paar wordt vertaalbaar voor SCHRIJF c (test `TestVertaling`).

**Niet uitgevoerd in deze run (regel: nooit lokaal tegen productie, CLI pas live ná deploy):** toewijzing, `plan`, SCHRIJF c. Recept staat letterlijk in de
vervolg-opdracht `2026-09-22-vgg-toewijzing-schoffelstraat-29-plus-schrijf-c.md`: stap 0 deploy-check service ÉN job op dezelfde image → stap 1 dry-run op
de job-image (verwacht precies één Receipts-treffer € 400.000,00, pand → nieuw, boeking → nieuw) → stap 2 `--schrijf` + idempotentie-toets + audit-rijen →
stap 3 `vgg_blok7_odoo_writes.sh plan` moet het bewijspaar VERTAALBAAR tonen (`pand schoffelstraat-29 (verkoop, hoog/mens)`, `regel → opbrengst_panden`);
blijft 8000 ongemapt → STOP mét de exacte reden, geen mapping verzinnen (beslispunt 2) → stap 4 `SCHRIJF c` (kill-switch als executie-override, terug-lezen;
per-pand-sluit-eis letterlijk in het rapport) = de GO-vraag aan Peter vóór `SCHRIJF d`.

## D. Capture — Universal Steigerbouw: overhead via de omzetsleutel, GÉÉN OVH-project

Vastgelegd in `docs/regels/verplichtingen-projecten-voorraad.md` (alinea 21-09), BESLISSINGEN "UNIVERSAL — OVERHEAD VIA DE OMZETSLEUTEL, GEEN OVH-PROJECT
(Peter 21-09)", CLAUDE.md verplichtingen-projecten regel 1 ("overhead → intern OVH-project óf pro rato over de actieve projecten per klantkeuze"). De regel
"overhead → OVH-project" is een KLANTKEUZE, geen systeemnorm; voor Universal is het patroon de omzet-gewogen pro-rato-verdeling over de actieve,
niet-afgesloten projecten (19-09-regel). De module maakt nooit zelf een OVH-project en stelt het voor Universal niet meer voor. Beslispunten GESLOTEN:
rapport 18-09 aanbeveling 3 en rapport 19-09 beslispunt 2 → nee; beslispunt 1 van 19-09 (€ 1.239,05 op twee "Afgesloten"-projecten) blijft klikpunt.
Guard `tests/projecten/test_zonder_project_universal_overhead.py`: `facturen-zonder-project` telt overhead mét bevroren pro-rato-verdeling (DCTE 4499,
Floor Beheer 4003, Kader 4606) niet als bevinding; dezelfde factuur zónder verdeling wél — bevestigt bestaand gedrag, geen codewijziging.

## Keuzes (Peter kijkt niet mee)
- **Fase 1 volledig gebouwd i.p.v. alleen de lezer** — het ontwerp §7 noemt fase 1 als één geheel en het akkoord dekte alle defaults; opt-in automatisch
  aanmaken staat default UIT, dus productiegedrag verandert pas na een menselijke klik op de kaart.
- **Categorie op rekeningnaam, niet op AI** — deterministisch en terugvindbaar; `onbekend` = chip "controleer", de mens kiest.
- **Register dicht weigert het plannen niet** (contract-afwijking 8): een `gepland` zonder recht wordt ná boeken `mislukt` mét 403-reden — zichtbaar, retry
  zodra het recht er is; de frontend schakelt de RLZ-knoppen wél uit.
- **BUA-bulk alleen 4508 + 4510** (zie fiscale nuance); 4014/4503 bewust niet, de CLI zet nooit meer dan `--codes`.
- **`pand-toewijzen` als generieke CLI** (élke soort, élke collectie) — schrijft exact de rijen die het Toewijzing-scherm (mockup `pandenregister-cowork.html`)
  later zou schrijven; status-overgangen van een bestaand pand blijven een aparte beslissing.
- **Schema-dump vanaf `boekhouding_test_a2`** met header op `boekhouding_test`: dezelfde migratie-head 0168, de suite bezette de standaard-DB.
- **Vreemde werkboom-bestanden laten staan:** `opdrachten/inbox/2026-09-21-BUG-rlz-boek-wachtrij-…`, `…-corrigeren-knop-…`, `…-planning-conflictenbalk-…`,
  `2026-09-22-nameting-corrigeren-testadministratie.md` en `opdrachten/mislukt/2026-09-21-vastly-odoo-arvum-…` zijn van andere runs/Peter — niet gecommit,
  niet verplaatst. Alleen de twee vervolg-opdrachten van déze opdracht gaan mee.

## Poort (poging 2, letterlijk)
- `npx tsc -b` → exit 0.
- `npx vitest run` → Test Files 244 passed (244), Tests 1881 passed (1881), 18,7 s.
- Gouden set `pytest tests/keten` (eigen DB `boekhouding_test_a2`) → 166 passed in 78,95 s (incl. nieuwe casus **ag**).
- Volledige suite `pytest --ignore=tests/keten` op `boekhouding_test` → **6862 passed, 1 skipped, 21 deselected in 3337 s (0:55:37), exit 0**
  (de run wachtte op de uitkomst — les 18/19-09).
- `ruff check` + `ruff format --check` op alle nieuwe/geraakte backend-bestanden van A/B/C/D → schoon (26 bestanden).
- Doc-guards (`test_claude_md_beslissingen_verwijzingen`, `test_rapporten_index`, `test_rapporten_gelezen_regels`, `test_regels_index`,
  `test_nameting_workflow`, changelog/registry/contrast) → `tests/unit` apart op DB a2 ná de doc-edits: 327 tests, exit 0; én in de volledige suite.
- Live-200 dev (uvicorn 8011): `GET …/activa-instelling` 200, `GET …/documenten/{did}/activa-voorstel` 200.

## Meetrecept ná deploy (vervolg-opdrachten `niet vóór: 2026-09-22 09:00`)
1. **Activa:** `is_activa`/`activa_instelling` ná de sync van 07:00 (Pilates Bloom 4 rekeningen 0101/0107/0111/0113, `grens_rlz` 450, `register_leesbaar` true;
   Universal false mét "recht ontbreekt (403)"; ≈ 344 `is_activa` over 75 administraties); `reconciliatie-alles --alleen activa --lees-only` → soorten in
   `meten`, explosie-rem < 50; kaart in productie = klikpunt (Pilates Bloom inkoopfactuur mét 0107/0111/0113 ≥ € 450, anders "niet gemeten").
2. **BUA:** `nameting -f onderdeel=bua-kandidaten` moet de replica-meting bevestigen; `bua-kenmerk-zetten` NIET draaien vóór Peters "ja".
3. **VGG:** dry-run → `--schrijf` → `plan` (vertaalbaar?) → `SCHRIJF c` → GO-vraag (aparte opdracht, sectie C).

## Klikpunten Peter
- "ja" op het BUA-bulk-voorstel (4508 + 4510 kantoorbreed) → dan `bua-kenmerk-zetten --alles` zonder `--dry-run` op de job-image.
- RLZ-recht "Vaste activa" op de webservice-logins van Universal Steigerbouw en Rubicon Investments.
- GO op het SCHRIJF-c-rapport (komt uit de vervolg-opdracht) vóór SCHRIJF d.

## Gelezen regels
- `docs/regels/activa.md` — 30 regels (14 vóór deze run)
- `docs/regels/btw.md` — 199 regels (150 vóór deze run)
- `docs/regels/vgg-odoo-migratie.md` — 56 regels (53 vóór deze run)
- `docs/regels/verplichtingen-projecten-voorraad.md` — 407 regels (395 vóór deze run)
- `docs/regels/werkloop-productie.md` — 195 regels (poging 1; poging 2 volgde de afsluitroutine eruit)
- Poging 1 (bouwagenten): óók `docs/regels/autoboeken-ai.md`, `docs/regels/kantoor-frontend.md`, `docs/regels/werkvoorraad-controlescherm.md` (volledig).
