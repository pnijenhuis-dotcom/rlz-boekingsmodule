# BUG AI-limiet (Peter 24-09) — sticky banner, geen heraanbieding ná verhoging, dubbelen kostten AI-geld — GEBOUWD

**Opdracht (Peter 24-09, handmatige CC-sessie, prioriteit boven alles):** `opdrachten/gedaan/2026-09-24-BUG-ai-limiet-banner-sticky-plus-heraanbieden-verzamelbak-en-overgeslagen-extracties-plus-dedup-voor-ai.md`.
Peter letterlijk: "dat Ai limiet voor alle nieuwe facturen trouwens is nog steeds niet opgelost, dat wil ik nu als eerste (medewerkers lopen daar
tegenaan en waarschijnlijk vist die er nog wel redelijk wat dubbele uit)" → "doe eerst die opdracht maar, dat moet nu gefixt worden".
**Bronnen gelezen:** LEESPLICHT (zie onderaan), `docs/gesprekken/2026-09-23.md` (Herstelrun + Aanvulling 22:0x) en `2026-09-24.md` (10:xx),
`app/aikosten/service.py`, `app/beheer/router.py`, `app/intake/verwerking.py`, `app/intake/herlezen.py`, `app/documenten/service.py`
(`heraanbied_gefaalde_extracties`, `herextraheer_document`, `_pdf_extractie_detail`), `app/intake/verzamelbak.py`, `app/intake/nu_verwerken.py`,
`app/reconciliatie/automatiseringen.py`, `.github/workflows/deploy.yml` (welke jobs de Anthropic-key dragen), migratie 0004 (RLS `document`).

## Uitkomst in één alinea
De drie oorzaken uit de opdracht zijn gebouwd zonder migratie. (A) De rode banner "AI-verwerking is geblokkeerd" op de werkvoorraad én de
rode regel op Instellingen toetsen nu uitsluitend de LIVE stand `geblokkeerd`; het sticky maandfeit `limiet_bereikt_op` is historie ("limiet
bereikt op … bij € 100,00; daarna verhoogd naar € 150,00") en ná een verhoging staat er één status-regel "AI-verwerking weer actief sinds …;
N documenten wachten op heraanbieding" mét de knop naar de verzamelbak. (B) Eén motor `app/aikosten/heraanbieden.py` biedt de verzamelbak-rijen
`ai_limiet_bereikt` (202 op 23-09) en de documenten mét `ai_extractie_overgeslagen: ai_limiet_bereikt` automatisch opnieuw aan — aan het einde
van élke intake-job-run (beide postvakken, elke 10 min) en als dagelijkse stap — zolang de kostenpoort open is, oud → nieuw, en stopt zichtbaar
zodra de poort dichtgaat; met tijdlijn, audit, dagteller in de reconciliatiemail, de knop "Opnieuw verwerken (N)" op de verzamelbak (202 →
uitkomst per rij) en de nazorg-CLI `ai-heraanbieden [--dry-run]`. (C) Vóór élke splitsings-AI-call loopt een byte-identieke dubbelencheck
kantoorbreed: bestaat het bestand al, dan wordt het exemplaar zonder AI-call als `samengevoegd`-huls bij het origineel gelegd, mét tijdlijn op
beide kanten en dagteller `ai_bespaard_dubbel`. **Werkt in productie: niet gemeten** — de échte heraanbieding van de 202 loopt automatisch in de
eerstvolgende intake-job-run ná de deploy (dat ís de regel); Peters "ja" gaat over de limiet voor september (advies Cowork € 250: 1.277
extracties/maand + 202 inhaal ≈ opnieuw vol vóór 30-09 bij € 150). Meetrecept = dispatch-onderdeel `ai-heraanbieden` + vervolg-opdracht.

## Feiten (bron: opdracht/Cowork 24-09 10:4x, productie lees-only)
| feit | waarde |
|---|---|
| AI-kosten september | € 102,23 van € 150,00 (68 %), `geblokkeerd=false`, `limiet_bereikt=true` (bereikt bij € 100, verhoogd 23-09 21:2x) |
| Verzamelbak | 208 rijen, waarvan 202 × `ai_limiet_bereikt` — alle 23-09 19:11 (herstelrun kempengroep `--sinds 2026-09-01`) |
| Extracties deze maand | 1.277 AI + 82 template |
| Oorzaak banner | `beheer/router.py`: `limiet_bereikt = limiet_bereikt_op is not None` (éénmaal per maand gezet, nooit teruggezet) → `WerkvoorraadScreen`/`InstellingenScreen` toonden daarop "geblokkeerd" |
| Oorzaak heraanbieding | `heraanbied_gefaalde_extracties` filtert op `ai_extractie_fout` en draait alleen handmatig; de verzamelbak-rijen stopten VÓÓR toewijzing (splitsingsdetectie) |
| Oorzaak dubbelen | sha256-dedup liep pas ná de extractie (`upload_document` → `mogelijk_duplicaat_van` → afvoer); het verzamelbak-pad kende geen dedup vóór de AI |

## Gebouwd
1. **Kostenmeter-status (`aikosten/service.py::haal_status_op`)**: `weer_actief_sinds` (jongste audit `ai_kosten_maandlimiet_gewijzigd` ná
   `limiet_bereikt_op`, alleen als verbruik < limiet) en `limiet_bij_bereiken_eur` (uit audit `ai_kosten_limiet_bereikt` van de maand). DTO
   `AiKostenStatusDto` + `limiet_bereikt_op`, `wachten_op_heraanbieding` (N(a) live + rest van de jongste run). Frontend: één bron
   `instellingen/aiKostenStand.ts` → `werkvoorraad/AiKostenBanner.tsx` (uit WerkvoorraadScreen gelicht) en het verbruiksblok op Instellingen;
   rood uitsluitend op `geblokkeerd`; `weer_actief` = `role="status"` mét `linkbtn` "Naar de verzamelbak" (anker `#verzamelbak`).
2. **Motor `app/aikosten/heraanbieden.py`**: selectie (a) `vind_kandidaten_verzamelbak` (PDF, jongste intake-reden `ai_limiet_bereikt`,
   geen open splitsingsvoorstel — pure notities dragen `notitie: true` en tellen niet als nieuwe reden), (b) `vind_kandidaten_documenten`
   per administratie in eigen RLS-scope (te_controleren/handmatig_afmaken, PDF, laatste extractie-uitkomst = limiet; een niet-systeem-
   gebeurtenis ná de limiet = `mens_bezig`, overgeslagen). `draai(bron, dry_run, max_per_run, deadline)`: poort dicht = alles `kostengrens`
   + run-audit, geen exception; (a) via `herlezen._herlees_een(label="ai_heraanbieding")` (splitsingsdetectie → documentsoort onduidelijk/
   verplichting → toewijzing → `start_extractie_na_toewijzing`; zelfde intake-bericht/afzender/mail-body; geheugen leert niet) mét de
   dubbelencheck ervóór; (b) via `herextraheer_document` (wachtrij-status = `naar_wachtrij`, de worker schrijft zijn eigen uitkomst).
   `AiKostenLimietBereikt` tijdens de run → dát document "wacht op AI-budget" (tijdlijn), de rest `kostengrens`, stop. Volumerem 300
   (`volumerem`, hard), tijdbudget 780 s vanaf de jobstart (`tijdbudget`, zacht). Per document audit `ai_heraanbieding` (oude reden →
   uitkomst, run_id, administratie); per run audit `ai_heraanbieding_run` bezig → klaar mét uitkomst per rij (≤ 300).
   `vraag_aan()` start de facturen-intake-job on-demand (`nu_verwerken.start`; audit `ai_heraanbieding_aangevraagd`); `stand()` voor
   knop/banner. **Hooks:** `cli._intake_postvak_verwerken` = postvak-pas + heraanbieding (ook bij niet-geconfigureerd postvak, exit-code van
   de pas blijft); `cli._reconciliatie_alles` = dagelijkse stap (lees-only: telling; échte run: telling + delegatie aan de intake-job, of de
   `kostengrens`-run als de poort dicht is). Reden voor de delegatie: `deploy.yml` geeft alleen `rlz-intake-imap(-kempengroep)`,
   `rlz-extractie-wachtrij` en `rlz-bewaking` de `ANTHROPIC_API_KEY` — `rlz-reconciliatie`/`rlz-sync` kunnen geen AI doen (least privilege).
3. **Routes** `POST /verzamelbak/ai-heraanbieden` (kantoorrollen; 202 `{voertuig, kandidaten_verzamelbak, kandidaten_documenten}`; 409 mét
   reden bij dichte poort; 502 als de job niet start) en `GET /verzamelbak/ai-heraanbieden/stand` (`bezig`, `kandidaten_verzamelbak`,
   `wachten`, `laatste_run` mét `tellers`/`overgeslagen`/`uitkomsten`). Frontend `intake/AiHeraanbiedenKnop.tsx` in het verzamelbak-paneel:
   N = rijen `ai_limiet_bereikt`, klik → 202 → poll (3 s, ≤ 15 min) → uitkomstlijst per rij (toegewezen / blijft in de bak mét andere reden /
   splitsingsvoorstel / dubbel / voorstel opgesteld / via de wachtrij / wacht op AI-budget / overgeslagen / mislukt) + lijst-refresh.
4. **CLI `ai-heraanbieden [--dry-run] [--max N]`** (`cli._ai_heraanbieden`; dry-run in de nameting-allowlist mét dry-run-dwang, via_gh
   `ai-heraanbieden`), querybibliotheek `app/lezen/queries/ai-heraanbieding.sql` (runs + live telling + bespaard), dispatch-onderdeel
   `ai-heraanbieden` in `nameting.yml` (if-tak + options + via_gh + OORDEEL_BRON + VGG-uitsluiting).
5. **Dubbelencheck `app/intake/dubbel_voor_ai.py`** + `verwerking._dubbel_voor_ai` in `_verwerk_pdf` (ná ProfX, vóór "nooit splitsen"/
   AVG-gate/AI): `zoek_byte_identiek` (verzamelbak + élke actieve administratie in eigen scope; oudste écht exemplaar, verwijderd/huls
   tellen niet); zelfde bericht → `registreer_zelfde_bericht` (bestaande rij, tijdlijn origineel, audit); ander bericht →
   `registreer_niet_toegewezen_document(reden dubbel_voor_ai: …)` + `handel_exemplaar_af`: origineel in een administratie → toewijzing
   aan die administratie, extractie-uitkomst zonder AI (`ai_extractie_overgeslagen: dubbel_voor_ai`) en `duplicaat_afvoer._voer_af`
   (systeem-actor) → `afgevoerd_duplicaat` mét kruisverwijzing (+ audit `duplicaat_afgevoerd`); origineel in de bak → huls
   SAMENGEVOEGD; tijdlijn beide kanten; audit `ai_dubbel_voor_extractie`. Directe mens-upload (`/intake/bestand`, poort 18-09) →
   `DocumentAlAanwezig` (409) al vóór de AI. Intake-uitkomst `dubbel`.
6. **Dagtellers** (`automatiseringen.py`): `ai_heraanbiedingen` (run-audit: gedaan/overgeslagen per reden; `kostengrens`/`volumerem`/
   `avg_gate`/`api_key` → HardeVoorwaarde → LET-OP mét deeplink Instellingen; `tijdbudget`/`mens_bezig` zacht) en `ai_bespaard_dubbel`
   (één gedaan per bespaarde call); VOLGORDE/LABEL/_ACTIES/VASTE_CATEGORIEEN bijgewerkt.
7. **Settings** `ai_heraanbieden_max_per_run` 300, `ai_heraanbieden_tijdbudget_s` 780 (task-timeout intake-job 900 s; toets vóór élk item).

## Keuzes zonder Peter
1. **Byte-dubbel = `afgevoerd_duplicaat` in de administratie van het origineel** (kruisverwijzing, heropenen = bestaande route). De eerste
   bouwvariant maakte er een `samengevoegd`-huls van; gouden-set-casus g ("PDF twee keer uit twee mails" → afgevoerd mét afwijzing-rij)
   werd daar rood van en is de bindende norm — dus teruggedraaid naar de bestaande eindstand, nu zonder AI-call. Alleen een origineel dat
   zelf nog in de verzamelbak ligt (geen administratie om in af te voeren) krijgt de huls-vorm. Het exemplaar wordt altijd geregistreerd
   (bewaarplicht, "afgehandeld → duplicaat van ‹document›"); een directe mens-upload houdt de 409-poort van 18-09 (nu vóór de AI).
2. **Knop = job on-demand, niet het werk in de request:** 202 en de intake-job doet de heraanbieding (de service heeft de key niet en de
   regel 08-09 verbiedt minutenlang werk buiten de jobs); in dev/test een daemon-thread (`nu_verwerken`). Uitkomst per rij komt uit de
   run-audit (administratie-loos, dus leesbaar zonder RLS-doorbraak).
3. **Dagelijkse stap delegeert** (reconciliatie-job zonder key): telling in de log + `:run` van de intake-job; met dichte poort schrijft de
   motor zelf de `kostengrens`-run (LET-OP). Trigger-IAM job → job is niet bewezen (de service triggert vandaag); een mislukte trigger is een
   zichtbare regel, de */10-scheduler is het vangnet.
4. **`mens_bezig`**: een niet-systeem-gebeurtenis ná de limiet-uitkomst = overslaan mét reden — nooit een voorstel over een mens heen.
5. **Wachtrij (b):** sinds 08-09 gaat élke AI-extractie via de wachtrij; in productie is de (b)-uitkomst dus `naar_wachtrij` en schrijft de
   worker het voorstel; treft de worker de limiet, dan is het document bij de volgende run gewoon weer kandidaat.

## Poort
- pytest nieuw: `tests/intake/test_ai_heraanbieden.py` 14 passed, `tests/intake/test_dubbel_voor_ai.py` 4 passed, `tests/keten/test_am_dubbel_voor_ai.py` 1 passed, `tests/unit/test_nameting_workflow.py` 45 passed.
- pytest subset (intake, keten, reconciliatie, unit, lezen, aikosten, ai_extractie, rol-gates): 1825 — vijf rood in de eerste ronde (gouden-set-casus g verlangde `afgevoerd_duplicaat` i.p.v. de samengevoegd-huls; sleepzone-409 vóór de AI; CLI-help mét het woord "bug"; twee doc-guards die het rapport nog niet zagen) → alle gefixt, daarna groen.
- Volledige suite: **7308 passed, 21 deselected, 0 failed** (59:59).
- vitest: volledig **259 bestanden / 1954 passed**; `tsc -b` schoon.
- Gouden set: casus am groen + `keten_sweep.sh` **11/11 gelijk** (0 nieuwe baselines).
- Geen migratie (migratie-routine n.v.t.); geen schema-dump.

## Nameting (recept vooraf) — werkt in productie: niet gemeten
1. Ná deploy: `gh workflow run nameting -f onderdeel=ai-heraanbieden` → `ai-heraanbieden --dry-run` noemt "kandidaten 202 (verzamelbak 202,
   documenten N)" (vóór de eerste intake-run) en `db-lezen ai-heraanbieding` toont daarna runs mét bron `intake_job:facturen[_kempengroep]`,
   gedaan/rest/overgeslagen; `verzamelbak_ai_limiet_nu` daalt per run (≤ 300, tijdbudget 780 s) tot 0; `kostengrens` in een run = poort dicht →
   limiet (klikpunt Peter).
2. `/instellingen/ai-kosten`: `geblokkeerd=false`, `weer_actief_sinds` gevuld, `wachten_op_heraanbieding` = 202 + N → banner zonder
   "geblokkeerd" (screenshot Peter als Beheerder).
3. Job-log `rlz-intake-imap(-kempengroep)`: "AI-heraanbieding ná limiet (intake_job:…)" mét tellers en uitkomst per document.
4. Reconciliatiemail volgende ochtend: dagtellers `ai_heraanbiedingen` en `ai_bespaard_dubbel`.
5. Knop: alleen meetbaar als iemand klikt (request-log `POST /verzamelbak/ai-heraanbieden`).
Vervolg-opdracht `opdrachten/inbox/2026-09-25-nameting-ai-heraanbieden-na-deploy.md` (`niet vóór: 2026-09-24 14:00`).

## Klikpunten Peter
- Limiet september: € 150 raakt met 202 inhaal-extracties waarschijnlijk vóór 30-09 opnieuw vol → advies € 250 (tijdelijk); de motor stopt
  dan zichtbaar en meldt `kostengrens` als LET-OP.
- Screenshot werkvoorraad ná deploy (banner).
- Bijvangst: geen — de opdracht raakte geen andere domeinen.

## Gelezen regels
- `docs/regels/intake-extractie.md` (322 regels)
- `docs/regels/werkvoorraad-controlescherm.md` (428 regels)
- `docs/regels/duplicaten-crediteuren.md` (152 regels)
- `docs/regels/kantoor-frontend.md` (144 regels)
- `docs/regels/reconciliatie.md` (306 regels)
- `docs/regels/werkloop-productie.md` (332 regels)
