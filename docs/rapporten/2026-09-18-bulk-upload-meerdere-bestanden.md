# Rapport 18-09 — Bulk-upload: meerdere bestanden tegelijk slepen/kiezen (Peter 18-09: "180 documenten bij BLOW, gaat niet")

Opdracht: `opdrachten/gedaan/2026-09-18-bulk-upload-meerdere-bestanden.md`. Domeinen: intake-extractie, werkvoorraad-controlescherm,
kantoor-frontend. Geen migratie, geen backend-wijziging (zie "Server-toets" — de server kon dit al aan).

**Werkt in productie: NIET GEMETEN** — deploy volgt via de Stop-hook. Meetrecept ná deploy: testaccount → klantpagina van de
testadministratie → 20 testbestanden in één drop (mix PDF/UBL/foto, twee ervan byte-identiek) → statusblok "Bezig: N van 20", daarna
samenvatting "20 aangeboden · 18 nieuw · 2 al aanwezig" (de twee identieke exemplaren als "al aanwezig als … — mogelijk duplicaat"),
lijst ververst één keer met 20 nieuwe rijen ("Wordt verwerkt…"), request-log Cloud Logging: 20 × `POST /administraties/{id}/documenten`
201, extractie-wachtrij-job-executies gestart; alle 20 documenten ná X min uit `extractie_wachtrij` (X rapporteren).

**Één regel voor Peter:** open de klantpagina van BLOW, kies rechts de soort (inkoopfactuur), selecteer in de Verkenner/Finder álle 180
bestanden (of sleep de hele map) naar de uploadzone — het blok eronder toont "Bezig: 37 van 180", per bestand de uitkomst, en ná afloop
"180 aangeboden · … nieuw · … al aanwezig · … fouten"; mislukte bestanden gaan met één klik "Mislukte opnieuw" alsnog mee.

## Feiten vooraf (code gelezen)

| Vraag | Bevinding |
|---|---|
| Waarom ging er één omhoog? | `UploadZone.tsx` las `files?.[0]` bij drop én bij kiezen; geen `multiple`. De callers (KlantUpload op klantpagina + documentenlijst, EmlUploadZone op de werkvoorraad) hadden elk een eigen enkelvoudige `uploadBestand`. |
| Geeft de server 409 bij een duplicaat? | **Nee.** `upload_document` registreert byte-identieke bytes in dezelfde administratie als NIEUW document mét `mogelijk_duplicaat_van` (sha256-vlag → chip "Mogelijk duplicaat", daarna de duplicaten-motor). Een 409 bestaat alleen voor `.eml` (Message-ID, via `al_eerder_verwerkt`). De opdracht-aanname "409 = al aanwezig, 180 × dezelfde PDF = 1 document" klopt dus niet met de code — zie beslispunt 1. |
| 413/415/422/429? | 413 "Bestand te groot" (> `document_max_bytes` = 20 MB) op beide routes; 415 bij kassarapport/verplichting als XML en onbekend type; 422 "Afbeelding onbruikbaar"; **een 429 op uploaden bestaat niet** (de enige 429 is de boek-volumerem). De wachtrij vertaalt een 429 wél leesbaar ("server vraagt even te wachten — opnieuw proberen", herkansbaar) voor het geval hij ooit komt. |
| Timeout-geval (blok 1c 08-09) | Blijft: `BackendOnbereikbaarError('timeout')` → status **onzeker** "antwoord bleef uit — staat waarschijnlijk al in de lijst; niet opnieuw aanbieden" (nooit herkansbaar, wél lijst-verversing). |

## Gebouwd (frontend; één component op álle upload-plekken)

- `werkvoorraad/uploadWachtrij.ts` (puur): `voerWachtrijUit` (max 4 gelijktijdig, immutabele statusupdates, Stoppen = lopende af / rest
  "niet gestart"), `classificeerFout` (409 → al aanwezig, 413 → te groot, 415/422 → reden niet herkansbaar, 429/5xx/netwerk → opnieuw,
  timeout → onzeker), `samenvatting` ("180 aangeboden · 176 nieuw · 3 al aanwezig · 1 fout"), `voortgangTekst` ("37 van 180 · 2 fouten"),
  `filterToegestaan` (accept-lijst; .DS_Store weg; geweigerd type = zichtbare fout-rij), `verzamelBestanden` (gesleepte MAP via
  `webkitGetAsEntry` recursief, `readEntries` in porties), `markeerVoorHerkansing`.
- `werkvoorraad/useUploadWachtrij.tsx`: hook (`start/stop/opnieuw/wis`, `beforeunload`-waarschuwing zolang de batch loopt, `onAfgerond`
  precies één keer ná de batch) + `UploadBatchStatus` (voortgangsregel, `<progress>`, per bestand chip + naam + reden, knoppen Stoppen /
  Mislukte opnieuw (N) / Sluiten, > 8 bestanden = alleen afwijkingen tonen + "Toon alle N").
- `UploadZone.tsx`: `<input multiple>`, `onBestanden(File[])`, drop = alle items incl. mappen; input-reset zodat dezelfde selectie opnieuw kan.
- `KlantStanden.tsx::KlantUpload` (klantpagina én documentenlijst via `DocumentenDeelscherm`) en `WerkvoorraadScreen.tsx::EmlUploadZone`
  (verzamelbak/werkvoorraad, tenaamstelling-routing): elk nog één per-bestand-`uploader` (bestaande routes ongewijzigd; soort-select geldt
  voor de hele batch; `mogelijk_duplicaat_van` → "al aanwezig als ‹bestand› — gemarkeerd als mogelijk duplicaat, ter controle"; `.eml`
  `al_eerder_verwerkt` → al aanwezig). Extractie loopt zoals nu (wachtrij-job); AI-kostengrens blijft de harde poort in de server
  (bereikt = chip "AI-limiet bereikt — handmatig verwerken" op het document, nooit stil).
- `styles/components.css`: `.upload-batch*` (paneel, kop, balk, lijst met ellipsis-namen).

## Server-toets (punt 4 — feiten, niet gemeten)

| Onderdeel | Feit (code/deploy.yml) | Past 180 × POST? |
|---|---|---|
| Request-grootte | `document_max_bytes` = 20 MB per bestand < Cloud Run-grens 32 MB (HTTP/1) | ja |
| Service | `--cpu 1 --memory 1Gi --min-instances 1`, géén `--concurrency` → Cloud Run-default 80 gelijktijdige requests per instance; de client houdt het op 4 tegelijk | ja — 4 parallel is ver onder 80; autoscaling pakt meer instances als het nodig is |
| Blokkerend werk | upload-route is `async def` + `run_in_threadpool` (sha, opslag, afbeelding→PDF) — 4 parallelle uploads bezetten 4 threadpool-tokens (anyio default 40) | ja |
| Extractie | `ai_extractie_in_request=False` in productie → élke AI-dragende PDF gaat naar `extractie_wachtrij` (201 < 2 s); élke enqueue triggert één executie van de job `rlz-extractie-wachtrij` (task-timeout 1800 s, `ai_extractie_worker_concurrency=1`, geen trigger-dedupe) — 180 uploads = tot 180 job-executies die elk de resterende wachtrij opeten (idempotent via de statusmachine; scheduler-vangnet */10 min). | ja; meetlat: serieel worst case 180 × ~20–30 s Claude-call ≈ 60–90 min; met parallelle executies realistisch < 15 min. **X is niet gemeten** — meten in de nameting (Cloud Logging job-executies + `extractie_wachtrij`-rijen). |
| AI-kostengrens | harde poort vóór élke call; 180 facturen ≈ € 5–10 | ja; bij bereiken: documenten zichtbaar als "AI-limiet bereikt", rest wacht op handmatig/volgende maand |
| Rate-limit | geen 429 op uploaden in de code; Anthropic-429's vangt de extractie-client zelf (retry/backoff) | n.v.t. — wachtrij toont een 429 wél leesbaar |

## Tests

| Toets | Uitkomst |
|---|---|
| `vitest run src/werkvoorraad/uploadWachtrij.test.ts` (nieuw) | 7 groen: piek = 4 gelijktijdig en alle 10 klaar; Stoppen (4 klaar, 2 niet gestart, herkansbaar); 409/413/netwerk/422-vertaling + samenvatting + alleen herkansbare opnieuw; timeout/429/5xx-classificatie; accept-filter; map-drop recursief; zonder mappen = files |
| `vitest run src/werkvoorraad/useUploadWachtrij.test.tsx` (nieuw) | 3 groen: `multiple` + alle bestanden doorgegeven; 6 bestanden mét soort kassarapport voor de hele batch, samenvatting "6 aangeboden · 4 nieuw · 1 al aanwezig · 1 fout", `onGeupload` 1×, 413 niet herkansbaar; netwerkfout → "Mislukte opnieuw (1)" stuurt alleen dat bestand, beforeunload geregistreerd, verversing opnieuw ná herkansing |
| `BuitenOfferte.test.tsx`, `WerkvoorraadScreen.test.tsx`, `KlantStanden.test.tsx` | 65 groen (bestaand gedrag, soort-select ongewijzigd) |
| `tsc -b` | groen voor blok 2 (de twee TS6133-fouten in `src/planning/dagEerst.ts` zijn van blok 4F, niet van dit blok) |
| `POORT=5201 HARNASSEN_ALLEEN=harness-werkvoorraad.html scripts/overflow_sweep.sh` | 40/40 ✅ (5 varianten × licht/donker × 4 breedtes), geen pagina-overflow |
| Gouden set | niet geraakt: geen wijziging onder `app/intake`, `app/extractie`, `app/documenten`, `frontend/src/document` |

## Beslispunten

1. **Byte-identiek = "al aanwezig" is een FRONTEND-vertaling van de bestaande `mogelijk_duplicaat_van`-vlag; de server registreert het
   exemplaar wél** (zoals altijd: sha256-vlag → chip → duplicaten-motor voert cent-exacte dubbelen af). 180 × dezelfde PDF geeft dus 180
   documenten mét vlag, niet 1 + 179 zoals de opdracht aannam. Bewust NIET gewijzigd in deze run: een server-side sha256-kortsluiting raakt de
   intake-keten (gouden set) en de opzet "duplicaat = signaal, mens beoordeelt". Voorstel als vervolg (klein blok, apart besluit Peter): op de
   DIRECTE upload-route (klantpagina) byte-identiek t.o.v. een niet-afgehandeld document → 409 `al_aanwezig` mét het bestaande document i.p.v.
   een nieuw exemplaar; mail-/verzamelbak-pad ongewijzigd.
2. Herkansbaar = netwerk, timeout-loos 5xx, 429, "niet gestart"; NIET herkansbaar = 413/415/422 (zelfde bestand faalt weer) en onzeker
   (timeout — het document staat er meestal al; opnieuw = duplicaat).
3. Lijst-verversing één keer ná de batch (óók ná een herkansingsronde) — niet per bestand; tijdens een grote batch zie je dus de voortgang
   in het blok, niet in de lijst.
4. Verborgen OS-bestanden uit een gesleepte map (.DS_Store, ._x) vallen stil weg — dat zijn geen documenten; elk ander niet-ondersteund type
   krijgt een zichtbare fout-rij.

## Klikpunten Peter

- BLOW: 180 bestanden in één keer (zie "Één regel"), ná afloop de samenvatting lezen; "al aanwezig"-regels zijn géén fouten.
- Nameting (zie kop): 20 testbestanden op het testaccount; X minuten tot alle extracties klaar rapporteren.

## Gelezen regels

- `docs/regels/intake-extractie.md` (252 regels) — volledig, vóór de start.
- `docs/regels/werkvoorraad-controlescherm.md` (185 regels) — volledig, vóór de start.
- `docs/regels/kantoor-frontend.md` (113 regels) — volledig, vóór de start.
- `docs/regels/werkloop-productie.md` (55 regels) — volledig (run-brede werkloop).
