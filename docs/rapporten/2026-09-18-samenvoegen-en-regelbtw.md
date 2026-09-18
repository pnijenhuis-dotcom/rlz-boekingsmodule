# Samenvoegen-bug, regel-btw uit de factuurkolom en upload 409 "al aanwezig" — 18-09 (agent C, inbox-run 3)

**Opdracht:** `opdrachten/gedaan/2026-09-18-BUG-samenvoegen-toont-gesplitste-regels-en-geheugen-overschrijft-factuurbtw.md` + extra
besluit Peter 18-09 (byte-identieke upload = 409). **Werkt in productie: niet gemeten** (een deploy binnen de run bestaat niet; nameting-
recept onderaan). Gouden set: casus **ae** toegevoegd; `tests/unit/test_keten_guard.py` groen.

## Samenvatting (één regel voor Peter)
Het scherm toonde 21 regels als "samengevoegd" omdat de server bij het openen 21 losse regels had opgeslagen (er was geen één-regel-variant:
geen factuurtotaal, twee regels zonder bedrag) terwijl de leverancier-voorkeur "samenvoegen" bleef zeggen; de btw-kolom "9 %/0 %" van de
factuur werd genegeerd en de 9 % uit het geheugen won op de Emballage-regels. Nu volgt de weergave de opgeslagen data (chip "weergave
hersteld" + tijdlijnregel), wint de factuurkolom per regel van het geheugen (Emballage → "NL, Nul tarief", bruto = 10,80), staat een afgedekt
bedrag als "niet gelezen (afgedekt)", wordt een pinbon-totaal alleen overgenomen als de regels erop sluiten, en geeft een tweede upload van
hetzelfde bestand "al aanwezig" mét link i.p.v. een nieuw document.

## Feiten (lees-only, replica `rlz-sql2-lees`, 18-09 ~14:30–15:00, `scripts/gcp/db_lezen.sh`, actor Beheerder `2f2262cd…`, scope BLOw B.V `5419878c…`)
- Document `c73e7590-5fa1-4305-ba14-29a307210c1e` = `2025-12-17_Zilver Horeca B.V._25-022711.pdf`, bron email (verzamelbak → toegewezen
  11:08:28 door Peter), status te_controleren, vendor `7b7d0014…`, referentie Fac-25-022711, factuurdatum 17-12-2025, totaalbedrag NULL.
- Veldvoorstel (AI, 11:08:40): 21 regels; élke regel `btw_bedrag` NULL, `btw_afleiding_reden` "onbepaalbaar", `btw_kolom` = "9%" (13 regels)
  / "0%" (8 Emballage-regels); regels 1–2 (Balisto Yobbery, AA Drink) zonder netto; kop `totaal_incl/excl/btw_bedrag` NULL (het totaal staat
  alleen op de pinbon).
- Leverancier-voorkeur BLOW × Zilver Horeca: `regels_samenvoegen = true`.
- Autosave-snapshot 12:10:42 (A10, systeem-actor): **21 regels**, `regels_samenvoegen: false` in het snapshot (geen samengevoegde regel
  berekenbaar), herkomst per regel grootboek + btw = `leverancier_geheugen` (taxrate 3a44e504 = "NL, Laag tarief" 9 %).
- Ná Peters PUT's (12:18:58 / 12:19:06, kop-omschrijving) staan er 2 opgeslagen regels (Maaza Tropical 31,90 op 9 % en een lege regel op
  673fa83a = "NL, Nul tarief") — de combinatie "voorkeur samenvoegen + > 1 regel" staat er dus nog.
- BLOW-tarieven (22): twee 9 %-codes ("NL, Laag tarief" favoriet, "(vooruit)"), 0 % niet-verlegd/niet-vrijgesteld: "NL, Nul tarief" en
  "NL, BTW-bedrag zelf specificeren" (gemengd) → de kolom "0%" is eenduidig "NL, Nul tarief".
- **Hypothese-uitslag: hypothese 1.** De modus-vlag in de respons komt uit de leverancier-voorkeur (`_samenvoeg_velden`); de opgeslagen regels
  zijn de gesplitste set. De frontend behandelde `dto.regels` bij `opgeslagen && regels_samenvoegen` als de samengevoegde variant → 21 rijen
  onder een uit-vinkje. Het regel-GB-geheugen (hypothese 2) vulde alleen GB/btw per regel en zette de modus niet.
- **Andere documenten met dezelfde combinatie** (telling per administratie wegens RLS op `boekvoorstel_regel`; werkvoorraad-statussen, > 1
  opgeslagen regel): BLOW 1 (de casus, voorkeur aan), Camping "Nieuwenhoven" B.V. 3 (geen voorkeur → RLZ-default samenvoegen) + 1 (voorkeur
  uit, consistent), Universal Steigerbouw 7 (geen voorkeur, Odoo-default gesplitst → consistent). Netto **4 documenten** die de leesroute nu bij
  het openen herstelt; geen backfill nodig.

## Gedaan / niet gedaan
| Punt | Stand |
|---|---|
| Fix 1 — één waarheid voor de modus (server laat `regels_samenvoegen` de data volgen, `regels_modus_hersteld`, tijdlijnregel idempotent, chip + tweede grendel in het scherm) | GEBOUWD + GETEST |
| Fix 2 — factuur-btw per regel wint van het geheugen (btw-kolom "9%"/"0%" → `factuur_regel`, kolom 0 % = "NL, Nul tarief", regel-btw = netto × p, chip "factuur 0 %") | GEBOUWD + GETEST |
| Fix 3 — bruto per regel uit het factuur-regeltarief (nooit geheugen-tarief) | GEBOUWD + GETEST (vitest: 10,80 blijft 10,80; 17,95 → 19,57) |
| Fix 4 — totaal uit de pinbon (AI-veld `pt` sentinel, toets Σ regels ± 5 ct → groen "uit pinbon", anders oranje, veld leeg) | GEBOUWD + GETEST |
| Fix 5 — afgedekt bedrag → chip "niet gelezen (afgedekt)" (AI-veld `ng` sentinel) | GEBOUWD + GETEST |
| Extra besluit — byte-identieke DIRECTE upload = 409 "al aanwezig" mét verwijzing + link, audit; verwijderd exemplaar telt niet; mail/IMAP/splitsing ongewijzigd | GEBOUWD + GETEST (klantpagina-route, sleepzone-route, service) |
| Open beslispunt bulk-upload ("server-side sha256-kortsluiting") | BESLOTEN (regels_C.md → intake-extractie.md) |
| Gouden set casus ae | TOEGEVOEGD (3 tests groen; modus-herstel-scenario in tests/documenten omdat de keten-administratie projectplicht heeft en dus nooit samenvoegt) |
| AI-prompt/schema union-limiet | `tests/extractie/test_schema_unionlimiet.py` groen (sentinel-strings, geen unions) |
| Nameting in productie | NIET GEMETEN — deploy volgt via de Stop-hook; recept onderaan |

## Tests (eigen test-DB `boekhouding_test_a4`)
- `tests/extractie/test_controle_kolom_pinbon_18_09.py` (14) · `tests/extractie/test_controle.py` · `tests/extractie/test_schema_unionlimiet.py` · `tests/documenten/test_upload_al_aanwezig.py` (5) · `tests/documenten/test_service.py` · `tests/documenten/test_router.py` (twee tests herschreven op het 409-besluit) → **groen** (batch 1: 120 passed ná de twee correcties).
- `tests/documenten/test_regel_prefill_factuur_regel_18_09.py` (4, incl. modus-herstel mét tijdlijnregel, idempotent) → **groen**.
- `tests/keten/test_ae_zilver_horeca_regelkolom.py` (3) → **groen**; `tests/unit/test_keten_guard.py` → groen.
- `tests/intake/test_upload_al_aanwezig_sleepzone.py` (1) → zie "Brede run".
- Vitest `src/document` + `src/werkvoorraad` (61 bestanden, 489 tests) → **groen**, incl. `BoekvoorstelPanel.modus18.test.tsx` (4) en `uploadWachtrij.test.ts` (+1).
- **Brede run** `tests/documenten tests/intake tests/extractie tests/keten` (1935 tests, 16 min): eerste ronde 25 failed / 3 errors.
  Oorzaken en afhandeling: (a) 15+ bestaande tests modelleren dubbelen als "twee keer dezelfde bytes via `upload_document`"
  (duplicaat-module, tegenboeken, webhook-redrive, autoboeken, keten z/c_f) — de eerste, bron-gebaseerde 409 brak die alle;
  daarom is de poort verplaatst naar de twee DIRECTE ROUTES (`directe_upload_poort`, contextvar) en blijft `upload_document`
  generiek → herdraai van die set: **219 passed, 1 failed**; (b) `test_ae_rituals…` (agent B) ERROR door een taxrate-id-
  botsing met mijn keten-stamgegevens (…0010) → mijn id's verplaatst naar …9009/…9000 → B's casus draait weer (herdraai groen);
  (c) `test_router_boeken` (202 i.p.v. 200, 500 op PUT) en `test_checks` = agent D's achtergrond-boeken/Server-Timing in
  aanbouw — niet C; (d) de ene resterende rode test `test_autoboeken::test_volumerem_weigert` verwacht "limiet" in de
  volumerem-melding die de coördinator (opdracht 1, SPOED volumerem) herschreef naar "Volumerem automatisch boeken: 0 van 0 …"
  — niet C, hoort bij opdracht 1; en `test_router_boeken::TestBoekvoorstelEndpoints` (2) verwacht de vaste set checknamen en
  ziet agent B's nieuwe check 'Btw-bedrag past bij tarief' — hoort bij B (`verzoeken_B.md`). Agent B's keten-casus
  `test_ae_rituals…` draait ná mijn id-verplaatsing groen (herdraai 30 passed).
- `tsc -b`: mijn bestanden schoon; resterende fouten staan in agent B's regio (`leverancierLand`, ongebruikte `percentage` na het weghalen van de hint) — gemeld in `verzoeken_B.md`.
- Tijdelijke regressie van AGENT D (niet C) tijdens de run: `router.py::_zet_server_timing` gebruikte `logger` zonder definitie → élke PUT /boekvoorstel 500 (batch 2, `test_router.py::TestBoekvoorstelSamenvoegVeldenViaApi`); D heeft `logger` intussen toegevoegd (router.py r. 59) — gemeld in `verzoeken_D.md`; de brede run hieronder startte deels vóór die fix.

## Migratie-routine
Geen migratie (alle nieuwe velden zijn afgeleid/DTO of JSON in het veldvoorstel/prefill-snapshot). Niets voor de coördinator.

## Klikpunten Peter
- Document Fac-25-022711 (BLOW, 17-12-2025, pinbon € 738,27, bron: replica-uitlezing 18-09) ná de deploy openen — zie nameting.
- Camping "Nieuwenhoven" B.V.: drie te_controleren-documenten met > 1 opgeslagen regel onder de standaard "samenvoegen" — bij openen herstelt de
  leesroute de weergave (chip); geen handeling vereist, wel even kijken of de regels kloppen.

## Beslispunten
1. Een regel mét kolom "9%" maar afgedekt bedrag krijgt de btw-code wél klaar (kolom = factuurfeit), het bedrag nooit — zo gebouwd; Peter kan anders beslissen.
2. De leesroute herstelt de modus zonder de leverancier-voorkeur te wijzigen; de mens kan alsnog samenvoegen zodra er een één-regel-variant is.
3. 409-scope: alleen DIRECTE uploads (klantpagina, documentenlijst, sleepzone) via de poort `service.directe_upload_poort()` op de twee routes; `upload_document` zelf blijft buiten de poort de generieke registratie mét duplicaatvlag (intake, splitsing, verzamelbak, CLI's, bestaande tests — 15+ tests modelleren dubbelen zo; een bron-gebaseerde variant brak ze alle). Mail/IMAP/splitsing blijven de duplicaatregel volgen (byte-identiek uit een tweede mail → `afgevoerd_duplicaat`, casus a). Gouden-set-casus a is daardoor ONGEWIJZIGD gebleven.

## Nameting-recept (ná deploy, lees-only tenzij vermeld)
1. Kantoor-web → BLOW → Fac-25-022711 (`/documenten/5419878c-ca11-4f02-98d7-b14325ff8206/c73e7590-5fa1-4305-ba14-29a307210c1e`): vinkje "Splitsen per regel" aan
   óf geen vinkje, hint "Losse factuurregels", tabel = de opgeslagen regels, chip "weergave hersteld: 2 opgeslagen regels, modus stond op
   samengevoegd"; tijdlijn draagt één regel "weergave hersteld …" (replica: `SELECT detail->>'reden' FROM boekhouding.document_gebeurtenis WHERE
   document_id='c73e7590-…' AND detail ? 'weergave_hersteld'` mét `--administratie 5419878c…` → precies 1 rij, ook ná herladen).
2. Zelfde document → ⋯ "Opnieuw extraheren" (klik Peter, kost één AI-call): Emballage-regels krijgen "NL, Nul tarief" mét chip "factuur 0 %",
   artikelregels "NL, Laag tarief" mét chip "factuur 9 %" en btw-bedrag = netto × 9 %; regels Balisto/AA Drink tonen "niet gelezen (afgedekt)";
   totaalveld leeg mét oranje chip "pinbon zegt € 738,27 — regels niet volledig gelezen"; knop Netto→Bruto: Emballage 10,80 blijft 10,80.
   Peter vult de twee afgedekte bedragen in vanaf het origineel → Σ regels = 738,27 → aansluiting groen.
3. Klantpagina BLOW → hetzelfde PDF nogmaals uploaden: batchblok toont "al aanwezig als "2025-12-17_Zilver Horeca B.V._25-022711.pdf" (te
   controleren, Fac-25-022711) — niet opnieuw aangemaakt" + link "→ bestaand document"; request-log: `POST /administraties/5419878c…/documenten` 409;
   replica: `audit_event` actie `upload_geweigerd_al_aanwezig` op record c73e7590…; documentenlijst BLOW krijgt géén nieuwe rij.
4. Rapportregel "werkt in productie: ja/nee" per punt.

## Geraakte bestanden
Backend: `app/extractie/service.py`, `app/extractie/controle.py`, `app/documenten/boekvoorstel.py`, `app/documenten/regel_prefill.py`,
`app/documenten/schemas.py`, `app/documenten/router.py`, `app/documenten/service.py`, `app/intake/router.py`; tests:
`tests/extractie/test_controle_kolom_pinbon_18_09.py`, `tests/documenten/test_upload_al_aanwezig.py`,
`tests/documenten/test_regel_prefill_factuur_regel_18_09.py`, `tests/intake/test_upload_al_aanwezig_sleepzone.py`,
`tests/documenten/test_service.py`, `tests/documenten/test_router.py`, `tests/keten/test_ae_zilver_horeca_regelkolom.py`,
`tests/keten/fixtures/ae_zilver_horeca_regelkolom/{bron,ai_antwoord,pdf_tekst}.json`, `tests/keten/casussen.py`, `tests/keten/conftest.py`.
Frontend: `api/types.ts`, `document/aiVoorstel.ts`, `document/regelVoorstelChips.ts`, `document/BoekvoorstelPanel.tsx`,
`document/BoekvoorstelPanel.modus18.test.tsx`, `werkvoorraad/uploadWachtrij.ts`, `werkvoorraad/uploadWachtrij.test.ts`,
`werkvoorraad/useUploadWachtrij.tsx`, `werkvoorraad/KlantStanden.tsx`.

## Gelezen regels
- `docs/regels/werkvoorraad-controlescherm.md` (297 regels)
- `docs/regels/btw.md` (150 regels)
- `docs/regels/intake-extractie.md` (270 regels)
- `docs/regels/kantoor-frontend.md` (123 regels)
- `docs/regels/werkloop-productie.md` (55 regels)
- Overige domeinen van deze inbox-run (door de coördinator vooraf volledig gelezen): `docs/regels/autoboeken-ai.md` (122 regels), `docs/regels/accordering-native-app.md` (321 regels), `docs/regels/duplicaten-crediteuren.md` (119 regels), `docs/regels/uren-planning-veldwerkers.md` (472 regels)
