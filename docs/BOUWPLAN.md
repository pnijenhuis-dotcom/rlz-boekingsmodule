# Bouwplan RLZ Boekingsmodule

> Fasering vastgesteld 3 juli 2026. Elke fase heeft een definition of done en eindigt met een
> werkende, door Peter te testen oplevering. Geen fase 2 vóór fase 1 in gebruik is.

## Fase 1 — Fundament + inkoopflow (de kern)

**Doel:** één klant-administratie end-to-end: PDF/UBL erin → gecontroleerd → geboekt in RLZ.

Backend:
1. Repo-setup: FastAPI + PostgreSQL (schema's `platform` + `boekhouding`), Docker Compose voor
   lokale dev, Alembic-migraties, pytest. Deploy-doel: **Cloud Run** (europe-west4) + gedeelde
   **Cloud SQL** + **Secret Manager** + **Cloud Storage** (documenten) + **Cloud Scheduler/jobs**
   (achtergrondwerk) — conform koppelcontract v1.2. Dev→prod pariteit via container.
2. Platform-basis: gebruikers (uitnodiging + TOTP-2FA), rollen, administratie-register,
   credential-store (envelope encryption via Secret Manager/KMS), append-only audit log in het
   **uniforme `audit_event`-schema** (v1.3), **PII gescheiden van financiële data**
   (pseudonimiseerbaar), **Row-Level Security** op administratie-scope (`SET LOCAL` per transactie).
   Migratie 0002 + endpoints + tests staan (2026-07-06). **Credential-store gebouwd (2026-07-08)
   — zie punt 4 hieronder.** **Besloten (Peter, 2026-07-06) — eerste taken volgende sessie:**
   - **Bootstrap-CLI voor de allereerste Beheerder — gebouwd (2026-07-08).** Uitnodigen is
     Beheerder-only, dus zonder dit was er geen manier om de eerste Beheerder aan te maken zonder
     rechtstreeks in de database te schrijven (kip-ei). **CLI-only** (`python -m app.cli
     bootstrap-beheerder` / `make bootstrap-beheerder`) — géén seed-logica in migraties: een
     Alembic-migratie draait bij elke deploy/omgeving en is niet de juiste plek voor een
     eenmalige, omgevingsspecifieke actie met een echte e-mail/naam als invoer. Idempotent:
     weigert zodra er al een Beheerder bestaat, schrijft een eigen audit_event (migratie 0002's
     rol-trigger vuurt alleen op UPDATE, niet op deze eerste INSERT).
   - **Refresh-tokens revocable gemaakt (2026-07-08)** — migratie 0003 (`refresh_token`-tabel,
     hash-only) i.p.v. stateless JWT: rotatie bij elke `token/vernieuwen`-aanroep, hergebruik van
     een al-geroteerd token trekt alle sessies van die gebruiker in, levering als
     httpOnly+Secure+SameSite=Strict-cookie (nooit meer in de JSON-respons) **+ audit_event voor
     login (geslaagd/mislukt), TOTP-fouten en refresh-hergebruik** (nu alleen
     rol-/scope-wijzigingen, bewust beperkt gehouden bij het bouwen van de auth-basis). IP wordt
     uitsluitend als anomalie-metadata in het audit-record gezet, nooit als auth-anker (conform
     Auth-0010-b). Zie Platform/OPEN_ITEMS.md voor het volledige antwoord aan vastgoed; MFA-cadans/
     passkeys/step-up (punten 2–4 van Auth-0010-b) volgen in fase 3, zoals daar voorgesteld.
   - **E-mailverzending van uitnodigingen via een Cloud Run-job** (nu retourneert de
     uitnodig-endpoint het token synchroon in de API-respons, geen SMTP-integratie).
   - **Wachtwoordbeleid** (sterkte-eisen boven de minimumlengte van 12 tekens) bewust uitgesteld
     — geen actie vóór een volgende sessie het oppakt.
3. RLZ-client: Basic auth per administratie, `{adminId}`-routing, throttling/retry, PUT+GUID-
   conventie, acties (17/19/138), `$expand`-helpers. Integratietests tegen BLOW (read-only).
4. **Sync-laag per administratie — Ledgers/TaxRates/Vendors/Projects gebouwd (2026-07-08).**
   Migratie 0005: gedeelde `platform.grootboekrekening` (koppelcontract §2c v1.8, RLZ-sync is
   enige schrijver, vastgoed leest read-only via GRANT SELECT + RLS) + niet-gedeelde
   `boekhouding.{taxrate,vendor,project}_cache` (eigen controlescherm — crediteurkeuze, btw-code,
   projectkoppeling; `brondata`-JSONB als vangnet naast de wél-geverifieerde velden, want
   TaxRate's officiële resource-model-documentatie gaf herhaaldelijk een serverfout). Generieke
   upsert + `verdwenen_uit_bron_op`-markering (nooit hard verwijderen; terugkeer = NULL, conform
   §2c) — één implementatie voor alle vier de bronnen (`app/sync/service.py`).
   - **On-demand trigger** `POST /administraties/{id}/sync/ledgers` — nu met gebruikers-auth +
     administratie-scope (zelfde dependency als document-upload); het service-to-service
     platform-JWT voor vastgoed's eigen ververs-knop komt bij de Cloud-uitrol.
   - **Nachtelijke sync** is nu een aanroepbaar commando (`make sync-alles` /
     `python -m app.cli sync-alles`) — de **Cloud Scheduler-koppeling zelf volgt bij de
     GCP-uitrol** (fase 5-platformverbetering), dit commando is exact het werk-item dat de
     Cloud Run-job straks aanroept. Eén administratie zonder werkende credentials stopt de rest
     van de run niet.
   - **Credentials tijdelijk via .env-logins** (`app/rlz/credentials.py`, prefix per
     RLZ-adminId — Universal/TESTADMIN/Rubicon; BLOw ontbreekt bewust, het volledige adminId
     staat nergens in de repo) — vervalt zodra de credential-store er is (fase 1, punt 2 hierboven
     legde het fundament, de RLZ-credential-koppeling zelf is nog niet gedaan).
   - **Aanname, nog te bevestigen door vastgoed:** de GRANT aan hun leesrol gaat naar
     `vastgoed_app` (naar analogie van `boekhouding_app`) — zie Platform/OPEN_ITEMS.md. Lokaal is
     de GRANT voorwaardelijk (rol bestaat hier niet), dus geen migratiefout, maar wél een
     bevestiging nodig vóór de éérste keer dat vastgoed dit in de gedeelde Cloud SQL verwacht.
   - JournalEntries (historie → boekingsgeheugen-seed) blijft open voor een volgende sessie —
     hoort inhoudelijk bij het boekingsgeheugen (fase-vervolg), niet bij deze read-only
     referentiedata-sync.
   - **Credential-store + koppel-flow gebouwd (2026-07-08).** Migratie 0006:
     `platform.rlz_credential` (webservice-login per administratie, wachtwoord versleuteld at
     rest via hetzelfde envelope-patroon als `totp_secret` — geen tweede
     encryptie-implementatie) + `platform.rlz_rechten_probe` (laatste rechten-check). Geen RLS
     op beide tabellen — platformbrede beheertabellen, toegang via applicatielaag (Beheerder-only
     endpoints voor `rlz_credential`; administratie-scope voor de probe), niet via
     administratie-scoping zoals `grootboekrekening`. `app/rlz/credentials.py` is nu
     **store-first met .env-fallback**: bestaande `.env`-logins blijven werken zolang niet elke
     administratie in de store zit. Eenmalig CLI-importcommando
     (`make import-env-credentials BEHEERDER_ID=<uuid>`) zet de bekende `.env`-logins
     (RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_) de store in — slaat BLOw en Kempen Facilities
     bewust over (hun volledige RLZ-adminId staat nergens in de repo, geen aanname/gok).
     Beheer-endpoints: `PUT`/`GET /administraties/{id}/rlz-credential` (Beheerder-only,
     wachtwoord write-only — komt nooit in een response of audit_event terug, alleen de
     username en het feit van de wijziging).
   - **Rechten-probe** `POST /administraties/{id}/rlz-check` (administratie-scope, geen
     Beheerder-only — hoort bij het aansluiten van een klant, geen platformbeheer): read-only
     probes over `Administrations` (root-client, top-level endpoint), `Ledgers`, `TaxRates`,
     `Vendors`, `Customers`, `Projects`, `SalesInvoices`, `PurchaseInvoices`, `JournalEntries`,
     `PaymentAccounts` (administratie-gescoped), rapport (endpoint → `ok`/HTTP-statuscode)
     opgeslagen per administratie + audit_event. **Voor de mockup-onboarding (fase-vervolg,
     frontend nog niet gebouwd):** dit rapport is bedoeld als directe input voor het
     koppel-scherm bij het aansluiten van een nieuwe administratie — een tabel met per endpoint
     een groen vinkje (ok) of een rode kruis+statuscode, plus een herkenbare hint bij bekende
     patronen (bv. "alle documentendpoints 403 → waarschijnlijk ontbrekend
     'documenten'-rechtenprofiel op de webservice-login, zie verkenning/16_DOORBELASTING_KEMPEN.md
     §KEMPEN_*-ervaring"). Een "niets wijzigen"-vinkje/leesrechten-profiel-indicator kan uit
     `is_totaalrekening`/afwezigheid van schrijfrechten-probes worden afgeleid; dat scherm zelf
     bouwen is fase-vervolg.
   - **Overbrugging vastgoed:** Rubicons grootboekrekeningen live gesynchroniseerd (read-only,
     `RUBICON_*`-login, 403 rekeningen — zie
     `tests/integration/test_sync_ledgers_read_integration.py::test_sync_ledgers_tegen_rubicon`,
     reproduceerbaar via `make test-read-integration`) en geëxporteerd naar
     `Platform/uitwisseling/rubicon_ledgers_2026-07-08.json` (alleen rekeningschema — code/naam/
     soort/GUID's, geen andere data) zodat vastgoed tegen echte data kan bouwen vóór de gedeelde
     Cloud SQL er is. Zie `Platform/uitwisseling/README.md`.
5. **Document-pipeline (statusmachine) — fundament gebouwd (2026-07-08).** Migratie 0004:
   `boekhouding.document` (client-UUID, RLS conform besluit 0004 — `administratie_id` mag NULL
   voor de niet_toegewezen-verzamelbak, zelfde patroon als `audit_event`) + `document_gebeurtenis`
   (append-only tijdlijn, voedt de mockup-tijdlijn). Statusmachine als expliciete, geteste graaf
   (`app/documenten/statusmachine.py`, alle paren getest): ontvangen → extractie_bezig →
   te_controleren → klaar_om_te_boeken → geboekt, zijtakken vraag_open/afgewezen/boeken_mislukt/
   niet_toegewezen; elke overgang schrijft zowel document_gebeurtenis als audit_event, ongeldige
   overgangen zijn een harde fout. Upload-endpoint (PDF/XML, max-size, administratie-scope
   afgedwongen) + storage-interface (lokaal FS in dev, Cloud Storage-klaar). Sha256-duplicaatcheck
   bij binnenkomst (per administratie) zet `mogelijk_duplicaat_van_id` — een losse vlag, geen
   aparte status (mockup: chip "Mogelijk duplicaat van ... — beoordelen", het document doorloopt
   gewoon de normale flow). UBL/XML wordt al deterministisch geparst naar veldvoorstellen
   (`app/documenten/ubl.py`); de AI-extractie voor PDF's is inmiddels gebouwd — zie punt 5b.
   ~~**Bekend openstaand punt:** elke statusovergang vereist nu een menselijke actor_id (geen
   systeem-actor-sentinel)~~ — **opgelost (2026-07-10, zie punt 5c): systeem-actor gebouwd**,
   het patroon geldt voortaan voor alle achtergrondverwerking. Multi-factuur-PDF-splitsing en
   e-mail-intake blijven fase 3.
5b. **AI-extractie sessie 1 — Claude-API-extractie van inkoopfactuur-PDF's, gebouwd (2026-07-10).**
   Kernprincipe onverkort: **AI leest, code rekent, mens drukt** — de AI levert uitsluitend
   veld-suggesties met zekerheidsscores, boeken blijft mens + harde checks. Nieuw pakket
   `app/extractie/`:
   - `client.py`: config-gedreven Claude-client (kern-AI-koppeling, geregistreerd in
     `Platform/registers/koppelingen.md`) op de officiële `anthropic`-SDK — model/key uit
     settings (`ai_extractie_model`; `ANTHROPIC_API_KEY` via .env/Secret Manager, besluit 0012,
     géén fallback), retry/backoff via de SDK (429/5xx én timeouts/connectiefouten —
     APITimeoutError valt onder de SDK-retries), eigen throttle-gate (conventie
     registers/conventies.md). Structured outputs (`output_config.format`, json_schema) dwingen
     valide JSON af — geen parse-gok; refusal/max_tokens/ongeldige JSON/timeout worden
     uitlegbare fouten.
   - **Timeout-fix (2026-07-10, na eerste echte factuur):** de eerste versie (Opus,
     niet-streamend, 120s timeout) liep op een normale factuur in een API-timeout; het faalpad
     werkte correct (nette melding, document op te_controleren). Drie wijzigingen: (1) default
     model is nu **`claude-sonnet-5`** — gestructureerde factuurextractie heeft geen Opus-diepte
     nodig, Sonnet levert op dit taaktype gelijke kwaliteit bij duidelijk lagere latency en
     kosten; Opus was overkill en juist de latency-bron (blijft via config kiesbaar). (2) De
     messages-call is nu **streamend** (Anthropic-aanbeveling voor lange document-requests): de
     timeout telt per chunk i.p.v. over de hele respons; `get_final_message()` verzamelt het
     complete antwoord, de max_tokens-afkapdetectie blijft werken. (3) **"Opnieuw extraheren"**
     op het controlescherm (`POST .../documenten/{id}/extractie` →
     `service.herextraheer_document`): bij een transiënte fout (timeout, 529) draait de
     extractie opnieuw zonder her-upload — statusgraaf kreeg daarvoor de overgang
     te_controleren → extractie_bezig, tijdlijn + audit per stap, AVG-gate/key-check gelden
     onverkort, alleen PDF's en alleen vanaf te_controleren; het nieuwste veldvoorstel wint in
     detail én boekvoorstel-prefill.
   - `service.py`: PDF (base64 document-block, bestaande opslag-seam) → strak JSON-schema voor
     kop (leverancier, factuurnummer, factuur-/vervaldatum, totalen, btw) + regels
     (omschrijving, netto, btw, hoeveelheid), per veld een zekerheidsscore 0..1 (geclampt in
     code). **AVG hard:** prompt verbiedt BSN's in de output én `bsn.py` verwijdert
     deterministisch BSN's vóór persistentie — alleen het áántal verwijderingen wordt bewaard,
     nooit het nummer. **Correctie (2026-07-10, Peters controle van een echte factuur,
     20260064.pdf): de eerste versie ("elfproef-post-filter" op elk veld) was te grof** — een
     9-cijferig factuurnummer dat toevallig de elfproef doorstaat werd gemaskeerd en vernielde
     daarmee juist controleursdata. Het filter is nu context-vereist (elfproef ÉN een
     BSN-contextwoord — BSN/burgerservicenummer/sofinummer — nabij het getal, waarbij een
     dichterbij staand ander label zoals factuurnummer/IBAN wint) en draait uitsluitend op
     vrije-tekstvelden (leveranciersnaam, regelomschrijving) — nooit op gestructureerde velden
     (factuurnummer, datums, bedragen, hoeveelheid), die zijn per definitie geen BSN. Vangnet
     voor de losse-BSN-zonder-label-case blijft de promptinstructie + Cloud DLP
     (platformverbetering 4).
   - `controle.py`: deterministische controlelaag (geen AI in de cijfers, pure functies zoals
     checks.py): bedragen/datums valide parsen of leeg laten + benoemen (`onparseerbaar`),
     regelsom vs. gelezen totaal, leverancier exact/fuzzy (genormaliseerd op rechtsvorm) matchen
     tegen de vendor-cache (voorstel, alleen bij uniek resultaat), btw-code-suggestie uitsluitend
     uit de taxrate-cache (uniek percentage; 0%/verlegd bewust nooit — aangifte-kritisch).
     **GB-suggesties bewust nog niet: het boekingsgeheugen is sessie 2.**
   - Ingeplugd op `_start_extractie` — synchroon na upload voor kleine documenten (paar
     seconden; grote documenten gaan sinds 2026-07-10 via de async-route, zie punt 5c).
     extractie_bezig → te_controleren met het voorstel als `veldvoorstel` in de tijdlijn (zelfde
     sleutel als UBL; UBL blijft de deterministische bron en gaat nooit via de AI). Elke uitkomst
     zichtbaar: voorstel, `ai_extractie_overgeslagen` (gate/key) of `ai_extractie_fout` — een
     AI-fout laat de upload nooit falen. Boekvoorstel-prefill neemt AI-regels, vendor- en
     btw-suggesties over; controlescherm toont per veld/regel de zekerheid (oranje onder de
     drempel of bij fuzzy match, chips verdwijnen zodra de controleur het veld aanraakt).
   - **AVG-gate (migratie 0014):** `platform.administratie.ai_extractie_ingeschakeld`, default
     UIT — zonder opt-in gaat er geen byte klantdata naar de Claude API. Beheer via
     instellingen-scherm/endpoints + `make ai-extractie-aan/uit`. **AVG-volgorde (hard): echte
     klantfacturen pas ná (1) DPA met Anthropic, (2) bevestiging EU-verwerking/dataresidentie,
     (3) opname in het verwerkersregister — tot die drie rond zijn staat de gate alleen aan voor
     de test-administratie/eigen facturen.**
   - Tests: gemockte API (schema/refusal/afkap/JSON-fouten), BSN-filter (elfproef, maskering,
     geen valse hits op IBAN/datums/bedragen), controlelaag-guardrails (nooit gokken), gate-
     gedrag (default uit = nul AI-verkeer), voorstel-boekt-nooit-automatisch. Echte-API-test
     achter de aparte `ai_integration`-marker (`make test-ai-integration`, synthetische factuur,
     skipt zonder key) — nooit in de kale run.
   - **Groottevrij-besluit (2026-07-10, Peter): grote facturen robuust, projectadministratie
     gewaarborgd.** Vier onderdelen:
     (1) **Compact uitvoerschema**: korte JSON-keys op de API-draad (kop/kz + regels als
     {o,n,b,h,z}), één zekerheidsgetal per kopveld en per regel, prompt verbiedt het echoën van
     documenttekst — een normale factuur blijft daarmee ruim binnen het tokenbudget. Alleen het
     draadformaat is compact; intern en richting tijdlijn/frontend blijven de volledige
     veldnamen. Tokenmeting per extractie (input/output/aanroepen/chunked + regelaantal) gaat
     als `ai_metriek` de tijdlijn in én de log.
     (2) **Adaptieve chunking**: eerst één aanroep; kapt die af (stop_reason=max_tokens), dan
     automatisch chunked — kop in één call (schrijft meteen de prompt-cache op het
     document-block; de regel-calls lezen 'm tegen ~0.1x inputprijs), regels per indexblok van
     25 met halvering bij afkap (ondergrens 5), deterministische merge in documentvolgorde met
     naad-ontdubbeling. Geen handmatige drempel — het schaalt op factuurgrootte; elke deelstap
     houdt streaming + SDK-retries. Vangnet: max ~40 regel-calls per document.
     (3) **Harde waarborg projectadministratie** (migratie 0015, status `handmatig_afmaken`):
     krijgt chunking de regelset niet aantoonbaar compleet bij een administratie met
     projectplicht (dat dekt vandaag ook de centrale-inkoopcase — zelfde toggle), dan eindigt
     het document blokkerend op handmatig_afmaken mét uitlegbare melding, tijdlijn en audit —
     er wordt bewust GEEN (totalen-only) voorstel opgeslagen dat regeldetail/projecttoerekening
     zou laten wegvallen. Vanuit die status: alles handmatig invullen (de harde checks — project
     verplicht per regel, regelsom vs. totaal — blijven de poort naar boeken) of opnieuw
     extraheren. Zonder projectplicht krijgt de controleur het gedeeltelijke voorstel wél, met
     een oranje onvolledig-signaal naast de bestaande regelsom-check.
     (4) De deterministische controlelaag is ongewijzigd de rekenlaag: samengevoegde regelsom
     vs. factuurtotaal, afwijking oranje — AI stelt voor, boekt nooit.
   - **Sessie 2 (open): het boekingsgeheugen** — RLZ-historie (JournalEntries) + app-correcties
     als bron voor GB-/btw-/leverancier-defaults; pas daarna worden GB-suggesties zinvol.
5c. **Async extractie — gebouwd (2026-07-10).** Aanleiding: de synchrone chunked extractie van
   een uitzonderlijk grote factuur (20260063.pdf) hield het scherm 90s+ vast en belastte de
   machine zwaar. Een groot/zwaar document bezet het scherm en de machine nu nooit meer.
   - **Klein-vs-groot-routing** (`service._groot_document_detail`): een PDF die daadwerkelijk de
     AI-route in gaat (AVG-gate aan + key) en boven een configureerbare drempel zit
     (`ai_extractie_sync_max_paginas`, default 8, paginatelling via pypdf — robuust voor object
     streams; of `ai_extractie_sync_max_bytes`, default 3 MB, tevens fallback als de telling
     faalt) gaat bij upload én her-extractie direct naar de nieuwe status `extractie_wachtrij`
     (migratie 0016); de request keert meteen terug. Kleine documenten houden exact de bestaande
     snelle synchrone happy-path. Gate-uit/key-loos blijft altijd synchroon — "achtergrond" zou
     daar alleen een tragere no-op zijn.
   - **Wachtrij-interface, bewust cloud-klaar** (`app/documenten/wachtrij.py`): het contract is
     payload-gedreven — `enqueue(administratie_id, document_id)`, nooit een callable of open
     sessie — en past daarmee één-op-één op de geplande Cloud Tasks/Cloud Run-variant
     (platformverbetering 1: taaknaam = deterministische idempotency-key uit dezelfde twee id's).
     Dev-implementatie: in-process threadpool met configureerbare limiet
     (`ai_extractie_worker_concurrency`, default 1 — de overbelastingsbescherming: één
     monsterfactuur trekt de machine niet plat, volgende taken wachten in de queue). De worker
     (`service.verwerk_extractie_taak`) is idempotent via de statusmachine: alleen een document
     dat écht op extractie_wachtrij staat wordt opgepakt (intussen verwijderd of dubbele taak =
     gelogde no-op); wachtrij→bezig commit apart zodat de UI "bezig" live ziet; een onverwachte
     worker-fout eindigt zichtbaar op te_controleren met de fout in de tijdlijn. De
     projectwaarborg (5b punt 3) loopt ongewijzigd door de gedeelde `_rond_extractie_af`.
   - **Systeem-actor (migratie 0016, patroon voor álle achtergrondverwerking** — vastgelegd in
     `Platform/registers/conventies.md`): elke worker-overgang draagt de vaste platform-gebruiker
     `Systeem (achtergrondverwerking)` (UUID `...0001`, `app/db/systeem_actor.py`) in tijdlijn én
     audit_event — nooit de gebruiker die toevallig uploadde, nooit NULL (FK's blijven gelden).
     Kan nooit inloggen: status geblokkeerd, geen wachtwoord, geen scope. De tijdlijn-DTO kreeg
     `actor_is_systeem`; de UI toont "⚙ systeem" bij die overgangen.
   - **Herstart-vangnet** (`herstel_achtergebleven_extracties`, lifespan na de migratie-guard):
     de in-process queue overleeft een herstart niet — wachtrij-documenten worden opnieuw
     ge-enqueued, op bezig gestrande documenten gaan eerst zichtbaar terug de wachtrij in
     (systeem-actor + detail). "Niets verdwijnt stil."
   - **Frontend:** werkvoorraad en detailscherm pollen (3s) zolang een document in
     wachtrij/bezig staat en verversen vanzelf — nooit een blokkerende spinner. Grote uploads
     melden direct "wordt op de achtergrond verwerkt"; het detailscherm toont een banner en
     verbergt intussen het (misleidende, want zo-overschreven) voorstel/boekvoorstel-formulier.
   - Tests: async-flow end-to-end met de échte in-process worker (gemockte AI), systeem-actor in
     tijdlijn + audit_event, routing op byte- én paginadrempel, projectwaarborg via de worker,
     worker-fout/verwijderd-document, herstart-herstel, en de kleine factuur die synchroon
     blijft. Frontend: polling aan/uit, banner, systeem-chip.
5d. **Controlescherm-fixes na Peters controle van echte facturen — gebouwd (2026-07-11).** Drie
   bevindingen uit de kliktest met echte facturen (20260063/20260064.pdf); fix 1 (BSN-filter
   context-vereist) staat hierboven bij 5b.
   - **Fix 2 — crediteur-voorstel zonder cache-match:** las de AI de leveranciersnaam maar matcht
     de cache niet (uniek), dan is het crediteur-veld nooit meer kaal-leeg: een klikbaar
     voorstelblok toont de gelezen naam + zekerheid met twee acties. (a) **Koppelen aan een
     bestaande crediteur**: maximaal drie fuzzy-suggesties uit de vendor-cache
     (`crediteurSuggesties.ts`, Dice-bigram op genormaliseerde naam — zelfde
     rechtsvorm-normalisatie als de backend-controlelaag; puur presentatie-ordening, de klik
     blijft de keuze). (b) **"Nieuwe crediteur aanmaken in RLZ"** met de naam voorgevuld:
     `POST /administraties/{id}/crediteuren` → `sync/service.maak_crediteur_aan` — idempotent
     client-GUID (UUIDv5 op administratie + genormaliseerde naam, dubbele klik raakt dezelfde
     RLZ-vendor), eigen duplicaatcheck op naam (409 draagt de bestaande vendor_id; de frontend
     selecteert die dan gewoon), en **dezelfde schrijf-failsafe-poort als boeken** (toggle per
     administratie + globale kill switch) — audit_event `crediteur_aangemaakt_in_rlz`, cache-rij
     direct kiesbaar, eerstvolgende vendors-sync verrijkt met RLZ's volledige record. Directe
     cache-match blijft automatisch voorvullen (bestaand gedrag).
   - **Fix 3 — regels standaard samengevoegd, splitsen als keuze:** het controlescherm toont bij
     een meerregelig voorstel standaard ÉÉN samengevoegde boekingsregel (deterministisch berekend:
     netto = gelezen totaal excl., btw = gelezen btw of incl−excl, vangnet = som van volledig
     geparste regels — nooit een gedeeltelijke som; btw-code alleen bij uniforme suggestie) met
     een vinkje **"Splitsen per regel"**; beide weergaven bewaren hun eigen invoer bij het
     schakelen. De keuze reist mee met opslaan en wordt per (administratie, crediteur) onthouden
     (migratie 0017 `boekhouding.leverancier_voorkeur`, RLS, audit alleen bij échte wijziging).
     **Harde uitzondering: projectplicht** (dekt ook centrale inkoop — zelfde toggle) blijft
     per-regel verplicht: samenvoegen niet toegestaan, geen vinkje, en een meegegeven keuze wordt
     bij opslaan genegeerd (geen stiekeme voorkeur-rij). **De AI blijft altijd alle regels
     extraheren** — samenvoegen is puur de weergave-/boekvorm; gesplitst prefillt altijd uit het
     volledige AI-voorstel.
   - Tests: BSN (elfproef-doorstaand factuurnummer blijft ongemoeid — op bsn- én servicelaag),
     crediteur-aanmaken (idempotent GUID, duplicaat-409 met vendor_id, failsafe-poort, audit),
     samenvoegen (default aan, één-regel-berekening incl. vangnetten, voorkeur onthouden over
     documenten heen, projectplicht-uitzondering, audit-éénmaligheid, API-niveau response-velden),
     frontend (voorstelblok met zekerheid, koppelen, aanmaken incl. 409-pad, vinkje + schakelen
     zonder invoerverlies, PUT-voorkeur, projectplicht zonder vinkje).
6. **Boeken — gebouwd (2026-07-09).** Migratie 0008: `boekhouding.boekvoorstel`/`boekvoorstel_regel`
   (het controlescherm-voorstel per document, RLS via het onderliggende document — zelfde
   subquery-patroon als `document_gebeurtenis`). `app/documenten/checks.py`: de drie harde checks
   (duplicaatquery Entity+Reference(30 tekens)+bedrag — eigen client-GUID telt niet als duplicaat
   bij een retry; regeltelling vs factuurtotaal; verplichte velden), altijd alle drie getoond,
   nooit stil overgeslagen.
   - **Checkstatus (audit 2026-07-13, gedocumenteerd ≠ gebouwd — hier actueel houden):**
     duplicaat, regeltelling, verplichte velden (incl. projectplicht) én IBAN-wissel: gebouwd
     (`app/documenten/checks.py`) + getest (`tests/documenten/test_checks.py`,
     projectplicht via `test_boekvoorstel.py`, IBAN-wissel via `test_iban_wissel.py`/
     `tests/extractie/test_iban.py`). IBAN-wissel (2026-07-13): IBAN als gestructureerd
     extractieveld (mod-97-validatie `app/extractie/iban.py`, buiten het BSN-filter net als het
     factuurnummer), vertrouwde meerwaardige set per crediteur in
     `boekhouding.leverancier_iban` (migratie 0019; bron rlz_seed uit
     `Vendors/{id}/BankRelations` / baseline / bevestigd, audit_event per toevoeging), eerste
     keer = baseline zonder blok (na geslaagde lege seed-poging), afwijking = hard blok tot
     menselijke bevestiging (`POST .../crediteuren/{vendor_id}/ibans`, IBAN in body — nooit in
     URL/logs), G-rekening/WKA: tweede bevestigde rekening is de norm, geen wissel-signaal.
     **Vragenworkflow backend — gebouwd + getest (2026-07-14, PART A; UI volgt als PART B):**
     `boekhouding.vraag` (migratie 0022: één open vraag per document via partiële unique index,
     CHECK's op tekst-niet-leeg en antwoord-consistentie, RLS, geen DELETE-grant — historie
     blijft, ook na boeken) + `platform.administratie.eigenaar_gebruiker_id` (migratie 0021,
     mockup Instellingen "Eigenaar (krijgt vragen)", GET/PUT `/administraties/{id}/eigenaar`,
     wijzigen Beheerder-only, audit). `app/documenten/vragen.py` + endpoints: `POST
     .../documenten/{id}/vraag` (tekst verplicht, toewijzing default eigenaar, override alleen
     binnen scope — actieve gebruiker mét administratie-toegang of Beheerder), `POST
     .../vragen/{id}/beantwoorden` (antwoord verplicht) en `POST .../vragen/{id}/intrekken`
     (reden optioneel) — beantwoorden én intrekken herstellen exact de **herkomst-status** van
     vóór de vraag (`vraag.status_voor_vraag`: te_controleren, handmatig_afmaken óf
     klaar_om_te_boeken; nooit hardgecodeerd te_controleren), `GET .../vragen` (filter
     status/document). **Twee bewuste uitbreidingen op de mockup (akkoord 2026-07-14, zie
     BESLISSINGEN.md): intrekken** (voorkomt pro-forma nep-antwoorden in de historie) **en
     stellen vanuit klaar_om_te_boeken** (statusmachine-uitbreiding, herstel terug naar
     klaar_om_te_boeken). Boeken blijft vanuit vraag_open geweigerd (bestaande
     `_KAN_BOEKPOGING_STARTEN_VANUIT`-poort). audit_event op stellen, beantwoorden én
     intrekken; `document.toegewezen_aan` volgt de open vraag (werkvoorraad-kolom).
     "Antwoord voedt geheugen" v1 = via de bestaande boek-leerlus (correctie + boeken → app-
     observatie); **latere verrijking (genoteerd):** doorzoekbare Q&A-kennisbank per crediteur.
     Tests: `tests/documenten/test_vragen.py` + eigenaar-tests in `tests/beheer/test_service.py`.
     **Nog niet gebouwd, met implementerende fase:**
     afwijzen-met-verplichte-reden (status zit al in `statusmachine.py` en blokkeert het
     boekpad, maar workflow/endpoint/reden-afdwinging ontbreken → afwijs-workflow, punt 8
     hieronder); memoriaal-saldo-0 (→ fase 2, omzet/kostprijsmemoriaal); VGB-prefixfilter
     (→ vóórdat documenten uit gedeelde vastgoed-administraties gelezen worden);
     per-leverancier-autoboeken-opt-in (→ vóór de eerste autoboek-functie);
     webhook-HMAC-per-verzendpoging (→ mét de afleveraar, open item 2026-07-13). `app/documenten/boeken.py`: `boek_document()` herhaalt de checks
   server-side (nooit de client-kant vertrouwen), dan de failsafes, dan de echte RLZ-schrijfacties
   — deterministisch client-GUID (`app/documenten/rlz_ids.py`, UUIDv5 op document-id, óók voor de
   PDF-bijlage) → PUT PurchaseInvoice → **PUT** `/Uploads/{uploadId}` (geverifieerd: RLZ wil hier
   expliciet PUT, geen POST — zie verkenning/api-verkenning.md) → actie 17 → boekstuknummer terug
   (RLZ's `ReceiptNumber`, geverifieerd al gezet bij de PUT, niet pas na boeken). Status →
   `geboekt` met tijdlijn+audit; een RLZ-fout zet `boeken_mislukt` met de échte foutmelding, een
   volgende poging is idempotent (zelfde client-GUID's).
   - **Drie failsafes (CLAUDE.md-taak 2.4):** (a) `platform.administratie.boeken_ingeschakeld`
     (per-administratie opt-in, default UIT) + `platform.boeken_instelling` (globale kill switch,
     singleton) — nieuwe `app/beheer/`-module, Beheerder-only endpoints, beide moeten aan staan.
     (b) Reconciliatiejob (`app/documenten/reconciliatie.py`, `make reconciliatie` /
     `python -m app.cli reconciliatie`): vergelijkt elk lokaal `geboekt` document met de
     werkelijke RLZ-staat (bestaat, Status 2/3 = geboekt/afgeletterd, bedrag, boekstuknummer),
     rapporteert afwijkingen. **Statusmapping gecorrigeerd (2026-07-13):** RLZ-status 3 =
     Gesloten/afgeletterd (DocumentStatuses-enumeratie, zie api-verkenning "Documentstatus
     definitief opgehelderd") — geboekt = Status ∈ {2, 3}, dus een betaalde factuur is geen
     afwijking meer; Status 1 (teruggezet naar concept, bv. actie 19) blijft wél gemeld;
     één kapotte administratie stopt de rest niet (zelfde patroon als `sync_alle_administraties`).
     (c) Volumerem: `settings.max_boekingen_per_dag_per_administratie` (default 20), telt op de
     al bestaande `document_gebeurtenis`-rijen van vandaag, geen eigen tabel nodig.
   - **Alleen de test-administratie heeft boeken aanstaan** — voor alle andere blijft de toggle op
     zijn default (uit) totdat een Beheerder 'm expliciet aanzet.
7. **Webhook-stub "factuur geboekt" — gebouwd (2026-07-09).** Migratie 0009:
   `boekhouding.webhook_uitgaand` (outbox, `afgeleverd_op` blijft NULL). `app/documenten/webhook.py`
   bouwt en ondertekent de payload (HMAC-SHA256 over timestamp+nonce+payload, koppelcontract §3) —
   RLZ-GUID, project-GUID, datum, bedragen per regel, GB-code, leverancier, referentie, adminId.
   Aflevering (HTTP-push naar vastgoed) is bewust nog niet gebouwd — dat is een fase-vervolg.
   **Scope-filter gebouwd (2026-07-13, hardening-audit):** de outbox-rij ontstaat alleen nog voor
   vastgoed-administraties (`platform.administratie.is_vastgoed`, migratie 0018 — default UIT,
   expliciet zetten; koppelcontract §3). Gefilterd bij het aanmaken, niet pas in de afleveraar.
   Voor de afleveraar blijft open (OPEN_ITEMS 2026-07-13): timestamp/nonce/HMAC pas bij de
   verzendpoging berekenen — de nu opgeslagen handtekening overleeft het replay-venster (~5 min)
   niet bij uitgestelde aflevering.

7b. **Boekingsgeheugen (backend) — gebouwd + getest (2026-07-13).** CLAUDE.md: "RLZ-historie +
   app-correcties; correcties wegen zwaarder; default voorstel, nooit blind boeken." Nieuw
   pakket `app/geheugen/`:
   - **Opslag (B2, migratie 0020):** `boekhouding.boeking_observatie`, append-only (geen
     UPDATE-grant: correcties = nieuwe observaties), RLS+FORCE, index (administratie, vendor,
     regel_sleutel). Deterministische observatie-id's (UUIDv5, eigen namespace) maken seed én
     leerlus idempotent. `regel_sleutel` = genormaliseerde token-set van de regelomschrijving
     (lowercase, leestekens weg, volgorde-onafhankelijk — `normalisatie.py`); raw omschrijving
     reist mee, nooit in logs/URL's.
   - **Seed (B3):** uit `GET PurchaseInvoices` (+`$expand=Entity`) + `/Lines`
     (Account/TaxRate/Project) per factuur — **bewust NIET JournalEntries**: geen crediteur op
     regel-/entry-niveau (geneste `Document($expand=Entity)` wordt stil genegeerd) en de
     collectie bleek jaren achter te lopen (B1-verkenning 2026-07-13, api-verkenning);
     **JournalEntries blijft gereserveerd voor memoriaal-/bankhistorie in fase 2.**
     Recency-cap `boekingsgeheugen_seed_maanden` (default 36), bron_datum = factuurdatum,
     idempotent/hervatbaar (transactie per factuur), overslagen expliciet geteld
     (zonder Entity / zonder bruikbare regels). Achtergrond-batch: CLI
     `seed-boekingsgeheugen` / `make seed-boekingsgeheugen` (Cloud Run job later), nooit
     synchroon in een request.
   - **Engine (B4, puur/deterministisch):** gewogen meerderheid per veld (GB/btw/project);
     gewicht = basisgewicht(bron) × 0.5^(leeftijd/halfwaardetijd) — app (3.0) > rlz_seed (1.0),
     halfwaardetijd default 365 dagen (settings). GB/project: leverancier-niveau primair,
     regel-niveau verfijnt bij een gesplitste stem; btw: regel-niveau eerst met
     leverancier-fallback — fallback en gesplitste stem ALTIJD oranje. Per veld confidence
     (winnend/totaal gewicht) + telling; voorstellen vanaf 1 observatie maar **oranje zolang de
     winnende waarde geen enkele app-observatie heeft (seed-only, `app_bevestigd` per veld in de
     response — Peters ontwerp, aangescherpt 2026-07-14; verving "≥2 consistente observaties is
     genoeg")**. Projectvoorstel heft de harde projectplicht-check nooit op (expliciet getest).
   - **Leerlus (B5):** elke geslaagde boeking (actie 17) → observaties bron='app' in dezelfde
     transactie als de GEBOEKT-overgang; samengevoegd → leverancier-niveau (sleutel NULL),
     gesplitst → regel-niveau; idempotent per boekstuk (retry legt niets dubbel vast).
   - **Expose (B6):** `POST /administraties/{id}/boekingsgeheugen/voorstel` (vendor +
     optionele regelomschrijving in de bódy) → per veld waarde/confidence/telling/oranje/reden/
     app_bevestigd — zelfde service voedt straks de autoboek-gate.
   - **UI-koppeling controlescherm — gebouwd + getest (2026-07-14)**
     (`frontend/src/document/geheugenVoorstel.ts` + `BoekvoorstelPanel.tsx`): voorstel ophalen
     zodra de crediteur bekend is (samengevoegd = leverancier-niveau, gesplitst = per unieke
     regelomschrijving, altijd in de body); prefill uitsluitend lege én niet-aangeraakte velden
     (handmatige keuze wint altijd); chips groen bij app-bevestigd/hoog vertrouwen, oranje bij
     laag vertrouwen of afwijking t.o.v. extractie/opgeslagen waarde (markeren, nooit
     overnemen); mislukte voorstel-call → rustige inline-indicatie "Geheugenvoorstel niet
     beschikbaar" (nooit blokkerend, nooit stil).
     **Latere verfijning (genoteerd 2026-07-14): voorstel-op-blur voor handmatige regels** —
     nu krijgt een regel die ná het ophalen wordt toegevoegd (of waarvan de omschrijving daarna
     wijzigt) geen voorstel; ophalen bij verlaten van het omschrijving-veld lost dat op zonder
     refetch-per-toetsaanslag.
     **Follow-ups (browserreview Peter, 2026-07-14):**
     - **Responsive:** de rechterkolom van het controlescherm klipt onder ~1560px
       viewportbreedte (bevestigd op 1512px) — fixen voor de gangbare laptopbreedtes
       1440/1536.
     - **Openstaande visuele verificatie:** de groen/oranje geheugen-chips (incl. het
       seed-only-oranje "uit historie, nog niet bevestigd") live bevestigen zodra er een
       factuur van een geseede crediteur in de werkvoorraad staat — kon in deze review nog
       niet, er lag geen geschikt document klaar.

Frontend (Vite + React, design tokens uit mockup — die blijven leidend, ook voor onderstaande
UI-eisen):
8. Login + 2FA, werkvoorraad (klantenlijst → klantpagina), controlescherm (PDF-viewer + voorstel +
   correcties) — **kopgegevens + boekingsregels + harde checks + boekactie gebouwd (2026-07-09)**,
   zie punt 6 en `frontend/src/document/BoekvoorstelPanel.tsx` + `SearchableCombobox.tsx` (zoekbare,
   gevirtualiseerde, debounced combobox conform de UI-eisen hieronder) — vragenworkflow,
   afwijzen-met-reden, verzamelbak "Niet toegewezen", instellingen-lite
   (administratie koppelen, gebruikers, eigenaren), audit log, globaal zoeken (boekingen + audit)
   blijven open voor een volgende sessie.
   - **Design-pass na Peters derde kliktest (2026-07-11, mijlpaal: twee echte boekingen gelukt)
     — vier punten afgerond:** PDF-preview vult nu de volledige beschikbare viewport-hoogte
     (sticky, `calc(100vh - 52px)`, geen restruimte meer onder de bijlage); de portal-listbox van
     `SearchableCombobox` is naar mockup-niveau gebracht (panel/border/schaduw, optie-rijen met
     code vet + omschrijving — GB-code, en nu ook het btw-percentage als code); btw-bedrag wordt
     automatisch afgeleid (netto × taxrate-percentage, `TaxRateCache.percentage` — migratie 0011,
     empirisch geverifieerd op RLZ's live respons) en blijft overschrijfbaar met een oranje
     "Berekend: € ..."-hint bij afwijking; documenten kunnen zacht verwijderd worden vanuit de
     werkvoorraad (prullenbak-icoon → bevestigingsdialoog met optionele reden → status
     `verwijderd`, migratie 0012 — bestand/record blijven bestaan, "toon verwijderde"-filter +
     herstelknop zet ze terug op hun status van vóór de verwijdering; geboekte documenten blijven
     hard onverwijderbaar, bewaarplicht). Zie `app/documenten/statusmachine.py` (VERWIJDERD is de
     enige status die nog overal — behalve vanuit GEBOEKT — een uitgang naartoe heeft) en
     `app/documenten/service.py::verwijder_document`/`herstel_document`.
   - **Eerstvolgende fronttaak (2026-07-13): bevestigings-UI voor een IBAN-wisselblokkade.**
     De IBAN-wissel-check (punt 6) toont zijn rij al generiek in het controlescherm, maar bij een
     blokkade is er nog geen knop die `POST /administraties/{id}/crediteuren/{vendor_id}/ibans`
     aanroept (IBAN in de body) — tot die bestaat is het endpoint zelf het enige pad om een
     nieuw rekeningnummer te bevestigen. UI-eisen: toon het afwijkende IBAN naast de vertrouwde
     rekening(en), bevestigen = bewuste actie met de crediteurnaam in beeld (knop op geld).
   - **Openstaand (2026-07-09): het instellingen-scherm is de échte UI voor de drie toggles.**
     De mockup's administraties-tab (project verplicht / boeken-toggle / globale kill switch) is
     nog niet gebouwd — tot die tijd zijn `make boeken-aan`/`boeken-uit`/`boeken-status`
     (`app/cli.py`, hergebruikt `app.beheer.service`) en de `PUT`-endpoints zelf (curl/Postman)
     het enige beheerpad. Die CLI-commando's blijven ook daarna nuttig (server-toegang zonder
     ingelogde sessie, bv. bij een incident), maar worden geen vervanging voor het scherm.
   **UI-eisen (vastgesteld 2026-07-08), van toepassing op elk GB-/project-/entiteitveld:**
   - Zoekbare combobox met toetsenbordnavigatie (pijltjes, Enter, Esc) i.p.v. een kale `<select>`
     — deze velden hebben per administratie honderden tot duizenden opties (bv. Universal: 145
     projecten), typen-om-te-filteren is dan geen "nice to have" maar een harde eis.
   - Gevirtualiseerde lijsten voor elke lijstweergave die uit een sync-cache render (GB-schema,
     projectenlijst, entiteitenlijst) — anders schaalt het scherm niet mee met een groeiende
     administratie.
   - Debounced zoeken op de lokale sync-cache (geen request per toetsaanslag; de sync-laag zelf
     is al lokaal, dus dit is puur UI-throttling, geen netwerklatentie-mitigatie).
   - Aria-labels op elk van deze velden (en op de gevirtualiseerde lijst-items) — dit scherm is
     de kern van de dagelijkse workflow, toegankelijkheid is hier geen achteraf-toevoeging.

**Definition of done fase 1:** Peter verwerkt een echte stapel inkoopfacturen van één klant
(BLOW of Kempen) sneller dan nu in RLZ zelf, met audit trail en zonder één handmatige RLZ-handeling.

## Fase 2 — Omzetboekingen + bank

- Omzetflow: kassarapport-herkenning (profiel per administratie, periode uit rapport,
  duplicaat per periode, plausibiliteit), SalesInvoice + gekoppelde kostprijsmemoriaal als één
  transactie, systeemdebiteur per administratie. Pilot: BLOW Margerapport.
- Bankmodule: PaymentAccounts/Statements lezen, voorstel-volgorde (exacte match → gedeeltelijk →
  vaste regels → RLZ-voorstel → handmatig), auto-afletteren bij naam+factuurnr+bedrag,
  regel-leren (3×), BankMutationDirectBookings schrijven. PoC afletteren (acties 15/16) eerst.
- Bulk-boeken, archief-weergave, tijdlijn per boeking. **Let op (koppelcontract v1.7, §7.3):**
  actie 19 (Correct) zet een RLZ-document terug naar concept i.p.v. een apart creditdocument —
  archief/tijdlijn kunnen dus geen zichtbaar stornering-/credit-spoor uit RLZ's documentstatus
  lezen. Het correctiespoor ("wanneer gestorneerd, door wie, waarom") moet uit ons eigen
  `audit_event` komen. Nu nog niet uitwerken — check bij het bouwen van dit scherm.

## Fase 3 — Klantportaal + intake

- Autorisatiemodule: accordeurs, sequentiële lagen met drempels, "Ter accordering"-flow,
  goedkeuren via e-maillink, PWA (installeerbaar, push: direct + dagelijks 09:00).
- Platform-auth-uitbreiding (besluit 0010, akkoord 2026-07-05): auth-niveau per rol (TOTP
  verplicht voor kantoor/beheer/accordeur; mobiele token-flow + biometrie + Sign in with Apple
  voor huurder-accounts t.b.v. vastgoed native app) + push als platform-service met topics per
  module — moet af vóór vastgoed-fase 3.
- E-mail intake (centraal adres, IMAP/Graph), multi-factuur-PDF-splitsing, verzamelbak-leren.
- Rollenmodel volledig (module-zichtbaarheid per rol).

## Fase 4 — Projectenmodule

- Projects-write PoC, projectregister per klant (archief-toggle), projectdetail (werksoorten,
  weekanalyse, m²-voortgang, meerwerk-tab, integrale marge + dekkingscontrole), offerte-ontleding
  → budgetversies (offerte/opdracht-status), projectcode-generatie, OVH-project bij inrichting,
  dagelijkse signalering naar werkvoorraad.
- Pilot: Universal Steigerbouw (60 actieve projecten).

## Fase 5 — Integraties & schaal

- Vastgoedmodule-webhook live (HMAC + timestamp/nonce + schema_version; integratietest tegen de
  aparte RLZ-test-administratie, testboekingen storneren — koppelcontract v1.3 §7.3).
- MI-dashboard-module (read-only, Financials-endpoints + read-models).
  - **Groepsconsolidatie = pure reporting-overlay (platformbesluit 0015, 2026-07-14 — alleen
    documenteren, hier niets bouwen vóór de MI-fase):** geconsolideerde cijfers worden alleen
    berekend/gerapporteerd, nooit geboekt — geen consolidatie-administratie, geen
    eliminatieboekingen in enig pakket; IC-/deelnemingseliminaties zijn rekenstappen in de
    overlay. **Randvoorwaarden die eerdere fasen al respecteren moeten** (datamodel/autorisatie
    niet dichttimmeren op één-entiteit-aannames): (1) consolidatie leest bóven de
    boekhoud-backend-port → die port biedt backend-agnostische lees-ops (saldibalans per
    entiteit per periode; groep met gemengde backends RLZ/Odoo blijft consolideerbaar);
    (2) prerequisite: gemeenschappelijke grootboek-referentie/mapping (kandidaat RGS) —
    `platform.grootboekrekening` per administratie moet daarheen mapbaar blijven;
    (3) consolidatiekring-model: groep + lidmaatschap, temporeel (ingangs-/einddatum) +
    eigendoms-% (minderheidsbelang), met een groep-scope bóven de per-administratie-scope;
    (4) intercompany-tagging (doorbelasting/centrale inkoop, IC-leveranciersvlag, VGB-prefix)
    is het zaad voor de eliminaties. Details: `Platform/besluiten/0015-…`.
- Peppol-intake, hardening (rate-limit-gedrag, backup/restore, monitoring), uitrol alle klanten.

## Platform-verbeteringen (vastgesteld 2026-07-04, mogelijk gemaakt door GCP-keuze)

| # | Verbetering | Waarom | Fase |
|---|-------------|--------|------|
| 1 | Boeken via **Cloud Tasks-queue** (idempotency-key = taaknaam, retry/backoff, dead-letter → foutstatus werkvoorraad) | robuustste "niets verdwijnt stil"; dubbel boeken technisch onmogelijk | **1** |
| 2 | **Staging-omgeving** (scale-to-zero, eigen kleine Cloud SQL + bucket); alles eerst tegen testadministratie | dev→prod zonder risico op klantdata | **1** |
| 3 | Audit log-export naar Cloud Storage met **bucket retention lock (WORM)** | audit log aantoonbaar onvervalsbaar (kantoor-waardig) | 2 |
| 4 | **Cloud DLP** als BSN-vangnet (NL-BSN-detectie + maskering vóór indexering) | machinale waarborg op het AVG-hard-principe | 2 |
| 5 | **Extractiekwaliteit-meting**: elke menselijke correctie = meetpunt per veld; drempels voor auto-boeken op data i.p.v. gevoel | objectieve basis voor auto-boeken per leverancier | 2 |
| 6 | **Signed URLs** (kortlevend, per gebruiker) voor factuur-PDF's in klant-app en zoekresultaten | documenten nooit publiek benaderbaar | 3 |
| 7 | **Cloud Monitoring-alerts**: RLZ-foutpercentage, sync-achterstand, signaleringsjob niet gedraaid, dead-letter niet leeg, budget | stille degradatie bestaat niet meer | 2 |
| 8 | **Secret-rotatie** RLZ-logins (halfjaarlijks, gelogd) | boekhoudtoegang verdient een rotatieproces | 5 |

Bewust afgewezen: Kubernetes (overkill), microservices binnen de module (één service + jobs
volstaat), multi-region (cross-region backup volstaat), AlloyDB (alleen MI-groeipad).

## Openstaande verificaties (inplannen in de fase waar ze nodig zijn)

| # | Wat | Fase |
|---|-----|------|
| 1 | Rate limits exact | 1 |
| 2 | Afletteren via acties 15/16 + QuickPaymentSelections | 2 |
| 3 | Projects-write (PUT via Customers-route) | 4 |
| 4 | CodeEventSubscriptions (RLZ-events) | 5 |
| 5 | Waarborg-GB per vastgoed-administratie | 5 |
