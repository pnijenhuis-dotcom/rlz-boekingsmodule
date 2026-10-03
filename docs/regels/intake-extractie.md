# Regels — E-mail-intake, verzamelbak, splitsing en AI-extractie

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Eén intake-adres, splitsen op factuurgrenzen, toewijzen op tenaamstelling, verzamelbak "Niet toegewezen", één extractiepad achter de AVG-/API-key-/kostengrens-gates, deterministische templates, UBL deterministisch, wachtrij-trigger, union-limiet.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Extractie-wachtrij-trigger (blok 2):** trigger werkt in productie sinds revisie 00462 (13/13 uploads → job-executie < 1 s); audit-spoor `extractie_wachtrij_trigger` + teller in de reconciliatiemail — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 2".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **UBL is deterministisch (blok 3):** kop, crediteur (btw → KvK → IBAN → naam), regels en datums rechtstreeks uit de XML bij intake (`app/documenten/ubl_voorstel.py`), AI hooguit aanvullend; crediteur-dialoog gevuld uit UBL, PDF-in-verwerking toont "Verwerking loopt — velden volgen" — zie BESLISSINGEN "HERSTELRUN 'BASIS EERST' 08-09 — BLOK 3".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verzamelbak "Niet toegewezen"**: alles wat niet eenduidig aan een administratie koppelt
  (tenaamstelling leidend, afzender = hint); leert van handmatige toewijzingen; "hoort niet bij
  ons" met reden. Nooit auto-toewijzen bij twijfel.
  Bouwstatus, preview per rij (`AnkerPopup`), OPTIMISTISCH toewijzen, "Verplaats naar andere administratie…"
  (`app/documenten/verplaatsen.py`), documentenlijst-hiërarchie + sorteerbare kolommen: zie BESLISSINGEN
  "E-mail-intake + verzamelbak — GEBOUWD + GETEST", "AVONDRUN 26-08", "KANTOOR-MINI-RUN 27-08" punt 5, "WERKSTROOM-
  + UI-RUN 27/28-08", "OPRUIMRUN 28-08" punt 21. Bindend blijft: Administratie-kiezers zijn overal in de kantoor-UI
  een doorzoekbare combobox (`ui/AdministratieCombobox`, punt 13) — nooit meer een kale select; nooit meer een
  absoluut gepositioneerde popup bínnen `.tabel-scroll`/`table{overflow:hidden}`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Verzamelbak-rij (C9 07-09):** soort-keuze = chip-toggle Factuur/Offerte onder de twijfelchip, kolombreedtes uit één bron (`VERZAMELBAK_KOLOMMEN`), constante rijhoogte, sweep-variant `?twijfel=1` — zie BESLISSINGEN "FIXRUN 07-09 — BLOK C9".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **E-mail intake**: één centraal adres — **`facturen@ak-nijenhuis.nl`** (adreskeuze Peter
  2026-08-15, bewust kort; Google Workspace) — splitsen van multi-factuur-PDF's op
  factuurgrenzen, toewijzen op tenaamstelling.
  GEBOUWD + GETEST 2026-08-07; live IMAP-fetch GEACTIVEERD (F3.4, 2026-08-15); PDF → intake-AI achter de
  platform-brede AVG-gate `intake_ai_ingeschakeld`; **Eén extractiepad voor álle ingangen** via
  `upload_document`/`start_extractie_na_toewijzing` achter dezelfde gates (per-administratie
  `ai_extractie_ingeschakeld` + API-key + AI-kostengrens); mail-body + afbeeldingen (migraties 0069/0070). Zie
  BESLISSINGEN "E-mail-intake + verzamelbak — GEBOUWD + GETEST", "RLZ-FEEDBACKRONDE 26-08" punt 4, "RLZ-FEEDBACKRONDE
  25-08 DEEL 3", GCP_UITROL §F3.4. Bindend blijft: Dependencies staan in `pyproject.toml` (geen requirements.txt) en
  worden bewaakt door `tests/unit/test_dependencies_gedeclareerd.py`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **AI-kostengrens intake** (max € 100 per kalendermaand, deterministische kostenmeter `backend/app/aikosten/`, harde
  poort vóór élke call, boven de grens NOOIT stil wegvallen; migratie 0047) — zie BESLISSINGEN "AI-KOSTENGRENS INTAKE".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **AI-schema's onder Anthropic's union-limiet (bugfix 31-08, BESLISSINGEN "BUGFIX 31-08"):**
  structured-output-schema's dragen max 16 union-/nullable-parameters (anyOf/type-array, ook in
  array-items) — het inkoopschema groeide met e/p/a naar 19 en élke extractie faalde met een 400.
  Het inkoopschema is sinds 31-08 sentinel-gebaseerd (verplichte strings, `""` = onbekend →
  deterministisch None); een NIEUW AI-veld nooit als nullable/union toevoegen maar via dit
  patroon. Testpoort: `tests/extractie/test_schema_unionlimiet.py` (alle live schema's ≤ 16 +
  fail-closed sweep op `json_schema=`-aanroepers). Nazorg-CLI `extractie-heraanbieden` biedt
  gefaalde extracties bulk opnieuw aan via de bestaande opnieuw-route. De teller/limiet leven
  sinds 31-08 runtime in `app/extractie/schema_poort.py` (de test importeert ze dáár) — de
  bewaking en de deploy-smoketest draaien dezelfde zelftest live.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Deterministische extractie-terugval — template per bekende leverancier** (`app/extractie/template_terugval.py`,
  NIET achter de AI-AVG-gate, één rood = VOLLEDIG verworpen; migratie 0094) — zie BESLISSINGEN "EXTRACTIE-TERUGVAL
  TEMPLATES".

<!-- toegevoegd 18-09-2026, opdracht "bulk-upload-meerdere-bestanden" -->
- **Bulk-upload — meerdere bestanden tegelijk (Peter 18-09 "180 documenten bij BLOW, gaat niet"; geen migratie, geen serverwijziging;
  BESLISSINGEN "BULK-UPLOAD — MEERDERE BESTANDEN TEGELIJK (Peter 18-09)"):** élke upload-plek (klantpagina, documentenlijst,
  werkvoorraad-sleepzone/verzamelbak) draait dezelfde `UploadZone` mét `<input multiple>` en neemt álle gesleepte bestanden — óók een
  gesleepte MAP (`webkitGetAsEntry` recursief) — als één batch; de soort-keuze geldt voor de hele batch. De wachtrij
  (`werkvoorraad/uploadWachtrij.ts`, puur; `useUploadWachtrij.tsx`) verstuurt maximaal 4 tegelijk over de BESTAANDE per-bestand-routes
  (`POST /administraties/{id}/documenten`, `/intake/bestand`, `/intake/eml` — server ongewijzigd, extractie via de wachtrij-job, AI-kostengrens
  blijft de harde poort). Per bestand een status mét leesbare reden: `klaar` · `al_aanwezig` (server-vlag `mogelijk_duplicaat_van` of een al
  verwerkte .eml — géén fout; de server registreert het exemplaar wél, de duplicaten-motor voert cent-exacte dubbelen af) · `fout` (413 te groot
  · 415/422 reden — niet herkansbaar; 429/5xx/netwerk — herkansbaar) · `onzeker` (timeout: staat waarschijnlijk al in de lijst, nooit opnieuw
  aanbieden) · `gestopt`. Voortgang "37 van 180 · 2 fouten", knoppen "Stoppen" (lopende af, rest niet gestart) en "Mislukte opnieuw (N)"
  (alleen herkansbare), samenvatting "180 aangeboden · 176 nieuw · 3 al aanwezig · 1 fout", de lijst ververst precies één keer ná de batch,
  pagina verlaten tijdens een batch = browserwaarschuwing (`beforeunload`). Niet-ondersteund type = zichtbare fout-rij; verborgen OS-bestanden
  (.DS_Store) vallen weg. Server-toets: 20 MB per bestand < 32 MB Cloud Run, concurrency-default 80 per instance, 4 parallel = ruim; élke
  AI-upload triggert een executie van `rlz-extractie-wachtrij` (geen trigger-dedupe, idempotent via de statusmachine) — doorlooptijd van
  180 uploads is NIET gemeten (nameting). Guards `uploadWachtrij.test.ts` + `useUploadWachtrij.test.tsx`. Open beslispunt: server-side
  sha256-kortsluiting (409 `al_aanwezig` op de directe upload-route) — apart besluit, raakt de gouden set.

<!-- toegevoegd 19-09-2026, opdracht "ic-spiegel-rood-174-doorbelastingsparen-verkoop-niet-gevonden" -->
- **Extractie-wachtrij-trigger gebundeld + één verwerker per document (BLOW-bulk 18-09; 19-09; geen migratie; BESLISSINGEN
  "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)", rij "Systeemfout ic_spiegel_rood 174×"):** de bulk-upload van 180 BLOW-documenten (18-09 11:00 UTC) triggerde per
  upload één job-executie: 118 executies in één uur, 180 × `429 Too Many Requests` op de Cloud Run Jobs-API (LET-OP
  `extractie_wachtrij: 180 overgeslagen [vangnet_scheduler]`), parallelle executies die hetzelfde document tot 8× verwerkten (tijdlijn
  58b588e8: 8 × bezig → te_controleren; AI-kosten), en opschalende service-instances die lopende bezig-runs terugzetten ("opnieuw
  ingepland na een herstart van de verwerking" 11:05:13 en 11:05:17 op c9ba6d8d). Sinds 19-09: (a) **bundelvenster 30 s** per
  job-resource in `CloudRunJobExtractieWachtrij` — ná een geslaagde trigger geen tweede executie binnen het venster, audit
  `extractie_wachtrij_trigger` mét `uitkomst: gebundeld` (+ `gebundeld_na_s`), teller-categorie `trigger_gebundeld` (zacht, geen
  LET-OP); een mislukte trigger opent géén venster; (b) de job `verwerk_extractie_wachtrij` herhaalt de pas zolang er werk was
  (≤ `WACHTRIJ_MAX_PASSEN` 5) zodat uploads binnen het venster door de lopende executie worden meegenomen — anders het
  10-minuten-scheduler-vangnet, zichtbaar op 'in wachtrij'; (c) het startup-vangnet `herstel_achtergebleven_extracties` laat mét de
  cloud-wachtrij een bezig-run mét een gebeurtenis jonger dan 15 min staan (zelfde regel als de job; de in-process wachtrij zet
  zoals altijd alles terug); (d) **compare-and-set op élke statusovergang** (`_schrijf_overgang` → `_claim_status`: `UPDATE … WHERE
  status = van`, rijlock): de trage verwerker die om 11:05:20 een al afgevoerd duplicaat (c9ba6d8d) stil terugzette op
  te_controleren — zonder tijdlijnregel, tellers-cache 151 ↔ 152 — krijgt nu `StatusIntussenGewijzigd` en schrijft niets. De
  tellers-afwijking was dus géén ontbrekende cache-hook maar een dubbele schrijver; de nachtelijke herberekening had 'm 19-09 05:44
  al gelijkgetrokken. Bulk-upload-regel 18-09 "élke AI-upload triggert een executie (geen trigger-dedupe)" is hiermee HERZIEN.

<!-- toegevoegd 23-09-2026, opdracht "intake-tweede-postvak-facturen-kempengroep-direct-plus-postvakbewaking-en-message-id" -->
- **Tweede facturenpostvak facturen@kempengroep.nl DIRECT gelezen + verwerkt-administratie op Message-ID + spam-map (Peter 22-09
  "er zijn facturen gemaild die niet in onze module staan"; migratie 0171; BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)"):** (1) **Kanaal
  `facturen_kempengroep`** naast `facturen` en `declaraties` (`betaalstatus.KANALEN`, `POSTVAK_ADRES_PER_KANAAL`; CHECK op
  `intake_bericht.kanaal` verruimd), settings `intake_kempengroep_imap_*`, eigen job `rlz-intake-imap-kempengroep` (CLI-alias
  `intake-postvak-kempengroep-verwerken` — de F3-lus draagt één CLI-woord per job, de smoketest start élke job mét `--smoketest <cli>`),
  scheduler */10 ACTIEF, secret `INTAKE_KEMPENGROEP_IMAP_WACHTWOORD` (door Peter gevuld 22-09). Verwerking identiek (tenaamstelling
  leidend, afzender hint); het kanaal staat op het intake-bericht en op "Uit de e-mail"/de tijdlijn ("via facturen@kempengroep.nl").
  De Gmail-forward kempengroep → ak-nijenhuis gaat UIT ná de eerste groene run (klikpunt Peter); tot dan vangt de bestaande dedup het:
  zelfde Message-ID = op de kop `al_bekend` (body wordt niet eens opgehaald), handmatige Fwd mét zelfde bijlage = `mogelijk_duplicaat_van`
  + duplicaat-afvoer, teller "dubbel via forward" (`detail.bijlage_hashes` op het intake-bericht, `verwerkt.dubbel_via_forward`).
  (2) **Een gelezen-vlag is geen verwerkt-administratie.** Tot 23-09 las de fetch `UNSEEN` in INBOX; wie de mailbox opende en las haalde
  het bericht ongemerkt uit de verwerking, en Spam (SPF-breuk door de forward → strikte-DMARC-afzenders) werd nooit gelezen. Sinds 23-09
  leest `ImapPostvakBron` ALLE berichten van de laatste `intake_postvak_venster_dagen` (14) dagen in INBOX én `intake_imap_spam_map`
  (`[Gmail]/Spam`; een spam-map die niet SELECT'baar is = PostvakFout, nooit stil), haalt eerst alleen de kop (Message-ID, FLAGS, From,
  Subject, Date, References) en slaat over wat al in `boekhouding.intake_bericht_verwerkt` (kanaal, message_id, uid, postvak_map,
  verwerkt_op, uitkomst verwerkt/al_bekend/niet_verwerkbaar, intake_bericht_id, detail) óf als `intake_bericht.message_id` (élk kanaal,
  ook .eml-upload) staat; sleutel zonder Message-ID = `uid:<map>:<uid>`. De gelezen-vlag wordt ná verwerking nog gezet, maar alleen als
  bijproduct. Een niet-parsebaar bericht wordt als `niet_verwerkbaar` geregistreerd (geen eeuwige retry-lus, exit 1 blijft). Spam-treffers
  worden gewoon verwerkt mét `intake_bericht.detail.postvak_map`, chip "uit Spam" op controlescherm/tijdlijn en LET-OP `intake_uit_spam`
  (afzender + domein, blok `intake`). Élke run schrijft één audit `intake_postvak_run` per kanaal (gezien/verwerkt/al_bekend/
  niet_verwerkbaar/uit_spam/dubbel_via_forward) → dagteller "Intake-postvakken" in de reconciliatiemail (`automatiseringen.INTAKE_POSTVAK`).
  **Herstelrun** = `intake-postvak-verwerken --sinds JJJJ-MM-DD` / `intake-postvak-kempengroep-verwerken --sinds …` op de job-image
  (`gcloud run jobs execute … --args`): laatste 60 dagen van beide postvakken incl. Spam, rapport per bericht VERWERKT / AL-VERWERKT /
  NIET-VERWERKBAAR / DUBBEL-VIA-FORWARD. (3) **Lees-only audit** `intake-postvak-audit --sinds 2026-07-01 [--detail]`
  (`app/intake/postvak_audit.py`; allowlist + dispatch-onderdeel `intake-postvak-audit`; draait op `rlz-reconciliatie` mét de
  INTAKE-envset): bron kempengroep (INBOX + Spam + "[Gmail]/All Mail", mét factuurbijlage) → doorgifte ak-nijenhuis (koppel Message-ID →
  References/In-Reply-To → bijlage-sha256 → bestandsnaam, gelabeld) → module (`intake_bericht.message_id` / `detail.bijlage_hashes` /
  `document.sha256_hash` per administratie-scope); uitval (a) nooit doorgestuurd, (b) in Spam overgeslagen, (c) in INBOX niet verwerkt
  (gelezen vóór de intake / anders) + omgekeerde controle (rechtstreeks in ak-nijenhuis zonder module-spoor). BODY.PEEK, geen writes.
  Tests `tests/intake/test_postvak_imap.py` (nieuwe FakeImap mét mappen/vlaggen/kop-fetch), `test_postvak_kempengroep.py`,
  `test_postvak_audit.py`, gouden-set-casus al `tests/keten/test_al_postvak_kempengroep_kanaal.py`. Rapport `docs/rapporten/2026-09-23-intake-tweede-postvak-kempengroep-message-id-postvakbewaking.md`; audit-rapport `docs/rapporten/2026-09-23-intake-postvak-audit.md`.

<!-- toegevoegd 24-09-2026, opdracht "BUG-ai-limiet-banner-sticky-plus-heraanbieden-verzamelbak-en-overgeslagen-extracties-plus-dedup-voor-ai" -->
- **AI-limiet: banner op de LIVE stand, automatische heraanbieding ná een verhoging, byte-identieke dubbelencheck vóór de AI-stap
  (BUG Peter 24-09 "dat AI limiet voor alle nieuwe facturen is nog steeds niet opgelost, dat wil ik nu als eerste"; geen migratie;
  BESLISSINGEN "AI-LIMIET — BANNER OP DE LIVE STAND, HERAANBIEDING NÁ VERHOGING, DUBBELENCHECK VÓÓR DE AI-STAP (Peter 24-09)"):**
  (A) **Banner = werkelijke stand.** `AiKostenMaandstatus.limiet_bereikt_op` is een HISTORISCH maandfeit (éénmaal gezet, nooit
  teruggezet); de blokkade is uitsluitend `geblokkeerd` (live verbruik ≥ limiet). Werkvoorraad-banner én het verbruiksblok op
  Instellingen lezen één bron (`frontend/src/instellingen/aiKostenStand.ts`): rood "AI-verwerking is geblokkeerd" alleen op
  `geblokkeerd`; ná een verhoging één status-regel "AI-verwerking weer actief sinds ‹jongste limietwijziging ná het bereik-moment›
  (limiet bereikt op … bij € …; daarna verhoogd naar € …); N documenten wachten op heraanbieding" mét `linkbtn` "Naar de verzamelbak"
  (`AiKostenStatusDto.limiet_bereikt_op/limiet_bij_bereiken_eur/weer_actief_sinds/wachten_op_heraanbieding`; N = verzamelbak-rijen
  `ai_limiet_bereikt` + de rest van de jongste heraanbiedingsrun). (B) **Heraanbieding automatisch, geen stille no-op** (kernprincipe
  7.6): één motor `app/aikosten/heraanbieden.py` selecteert (a) verzamelbak-PDF's waarvan de jongste intake-reden `ai_limiet_bereikt`
  is (zonder open splitsingsvoorstel) en (b) documenten mét administratie (te_controleren/handmatig_afmaken, PDF) waarvan de LAATSTE
  extractie-uitkomst `ai_extractie_overgeslagen: ai_limiet_bereikt` is — een document waar een mens ná de limiet aan werkte
  (niet-systeem-actor in de tijdlijn) wordt overgeslagen mét reden `mens_bezig`; oud → nieuw; draait aan het einde van ÉLKE
  intake-job-run (`intake-postvak-verwerken` én `intake-postvak-kempengroep-verwerken`, elke 10 min — de enige jobs mét de
  Anthropic-key; ook als de postvak-pas faalde/niet geconfigureerd is) én als dagelijkse stap in `reconciliatie-alles` (échte run:
  telling + delegatie aan de intake-job via het on-demand `:run`; lees-only: alleen de telling); alleen bij `geblokkeerd=false` —
  poort dicht = álle kandidaten overgeslagen `kostengrens` mét run-audit, geen exception. (a) loopt door de herbruikbare
  herlees-motor (`app/intake/herlezen._herlees_een` mét `label=ai_heraanbieding`: splitsingsdetectie → documentsoort → toewijzing
  op tenaamstelling → `start_extractie_na_toewijzing`, zelfde intake-bericht/afzender-hint/mail-body; het toewijzings-geheugen leert
  niet — geen mens-besluit), (b) door `herextraheer_document` (AVG-gate administratie, klein/groot via de wachtrij, template-terugval).
  Stopt zichtbaar zodra de poort tijdens de run dichtgaat: dát document krijgt de tijdlijnregel "wacht op AI-budget", de rest telt als
  overgeslagen `kostengrens` (geen tijdlijnruis) en is bij de volgende run gewoon weer kandidaat; pure notities op een bak-rij dragen
  `notitie: true` en veranderen de verzamelbak-reden niet (`verzamelbak._jongste_intake_redenen`). Volumerem `ai_heraanbieden_max_per_run`
  (300; rest = `volumerem` → LET-OP) en tijdbudget `ai_heraanbieden_tijdbudget_s` (780 s vanaf de jobstart; rest = `tijdbudget`, zacht).
  Élke heraanbieding = tijdlijnregel + audit `ai_heraanbieding` (oude reden → uitkomst, `run_id`); élke run één audit
  `ai_heraanbieding_run` (bezig → klaar: kandidaten/gedaan/rest/overgeslagen per reden/uitkomst per rij ≤ 300) → dagteller
  `ai_heraanbiedingen` verwacht/gedaan/overgeslagen in de reconciliatiemail (`kostengrens`/`volumerem`/`avg_gate`/`api_key` = harde
  voorwaarde → LET-OP mét deeplink Instellingen; `tijdbudget`/`mens_bezig` zacht). Knop **"Opnieuw verwerken (N)"** op de verzamelbak
  (kantoorrollen; N = rijen `ai_limiet_bereikt`) = `POST /verzamelbak/ai-heraanbieden` → 202 (start de facturen-intake-job on-demand
  — dezelfde motor, de service doet zelf geen minutenlang AI-werk in een request; audit `ai_heraanbieding_aangevraagd`), 409 mét reden
  bij gesloten poort; `GET /verzamelbak/ai-heraanbieden/stand` (bezig, N, wachten, jongste run mét uitkomst per rij) → uitkomstlijst
  zoals bulk-upload (toegewezen / blijft in de bak mét andere reden / splitsingsvoorstel / dubbel / voorstel opgesteld / via de wachtrij
  / wacht op AI-budget / overgeslagen / mislukt), `frontend/src/intake/AiHeraanbiedenKnop.tsx`. Nazorg-CLI `ai-heraanbieden [--dry-run]
  [--max N]` (dry-run = lees-only telling N(a)+N(b) — in de nameting-allowlist; de échte run = `gcloud run jobs execute rlz-intake-imap
  --args=-m,app.cli,ai-heraanbieden` ná Peters "ja"), querybibliotheek `db-lezen ai-heraanbieding`, dispatch-onderdeel `ai-heraanbieden`.
  (C) **Dubbelencheck vóór de AI-stap** (`app/intake/dubbel_voor_ai.py`, in `_verwerk_pdf` ná de ProfX-herkenning en vóór de
  "nooit splitsen"-regel/AVG-gate/AI, én in de heraanbieding vóór de splitsingsdetectie): sha256 kantoorbreed (verzamelbak + élke
  actieve administratie in haar eigen RLS-scope — geen SECURITY-DEFINER-doorbraak), oudste échte exemplaar (niet verwijderd, geen
  huls) telt. Zelfde intake-bericht = de bestaande rij is de uitkomst (`dubbel`, geen nieuwe registratie); ander bericht/kanaal = het
  exemplaar wordt geregistreerd (niets verdwijnt stil) en volgt direct de BESTAANDE duplicatenregels: origineel in een administratie →
  toegewezen aan die administratie, eerlijke extractie-uitkomst zonder AI (`ai_extractie_overgeslagen: dubbel_voor_ai`, te_controleren)
  en meteen afgevoerd als duplicaat via `duplicaat_afvoer._voer_af` (categorie (a) sha256, `afgevoerd_duplicaat` mét kruisverwijzing,
  systeem-actor — exact de eindstand van gouden-set-casus g "PDF twee keer uit twee mails", nu zonder AI-call; zichtbaar onder "Toon
  afgehandelde documenten → duplicaat van ‹document›", heropenen = bestaande route); origineel zelf nog in de verzamelbak → de huls
  (`samengevoegd` mét `samengevoegd_in_id`, chip op de bak-rij van het origineel). Tijdlijn "dubbel vóór extractie herkend (bespaard)"
  op beide kanten, audit `ai_dubbel_voor_extractie` → dagteller `ai_bespaard_dubbel`. Een DIRECTE mens-upload (`/intake/bestand`,
  poort 18-09) van bytes die in een administratie bestaan krijgt de 409 "al aanwezig" nu al vóór de AI-stap. Nooit verwijderen;
  referentie-dubbelen (andere bytes) blijven bij de duplicaten-motor ná extractie. Intake-uitkomst `dubbel` naast toegewezen/
  verzamelbak/splitsingsvoorstel/niet_verwerkbaar. (D) **Guards:** `tests/intake/test_ai_heraanbieden.py` (D5 poort dicht = overgeslagen
  mét teller; D2 stopt zichtbaar tijdens de run; D3 bak-rij → toegewezen mét zelfde intake-bericht; (b)-route; mens_bezig; dubbel in de
  heraanbieding; dagteller + LET-OP; CLI `--dry-run` letterlijk; job-entrypoint zonder postvak; routes 202/409/stand; banner-feiten),
  `tests/intake/test_dubbel_voor_ai.py` (D4: 0 AI-calls, huls, zelfde bericht, bak-origineel, verwijderd origineel), gouden-set-casus
  **am** `tests/keten/test_am_dubbel_voor_ai.py`, `tests/reconciliatie` via `bereken`, vitest `aiKostenStand.test.ts` (D1),
  `AiKostenBanner.test.tsx`, `AiHeraanbiedenKnop.test.tsx`, `test_nameting_workflow.py` (onderdeel `ai-heraanbieden`). Geen limiet in
  code (Peter zet zelf tijdelijk € 250 voor september — advies Cowork), geen tweede extractiepad.

<!-- toegevoegd 24-09-2026, opdracht "bundelrun-zeven-punten" blok 1 -->
- **Vastly-PDF-tweelingen — stam-normalisatie, factuurnummer-regel, herstel-CLI en bevinding (Peter 24-09, casus Vastly-batch
  23-09: 23 losse PDF's als inkoopfactuur naast hun UBL-verkoopfactuur; geen migratie; BESLISSINGEN "VASTLY-PDF-TWEELINGEN —
  STAM-NORMALISATIE, FACTUURNUMMER-REGEL, HERSTEL-CLI EN BEVINDING (Peter 24-09)"):** (1) de bundeling vóór de routing
  (`app/intake/bundeling.py`) vergelijkt de naamstam GENORMALISEERD — een exporteur-suffix `-ubl`/`_ubl`/`-xml`/`_xml`
  (hoofdletterongevoelig, alleen als staart) wordt aan beide kanten gestript (`factuur-RUB-2026-0031-ubl.xml` ≡
  `factuur-RUB-2026-0031.pdf`); ondubbelzinnigheid blijft de eis. Derde regel: het UBL-factuurnummer (`cbc:ID`, ≥ 4 tekens) komt
  tekstueel voor in de PDF-bestandsnaam óf in de PDF-tekstlaag (pypdf, witruimte weg + casefold) én er is precies één zo'n PDF.
  Volgorde: ingesloten-PDF-hash → genormaliseerde stam → factuurnummer → ingesloten PDF als beeld; twijfel (meerdere kandidaten)
  = nooit bundelen. (2) Nazorg `vastly-pdf-tweelingen-herstel [--dry-run] [--uitvoeren] [--administratie <uuid|naamdeel>]`
  (`app/intake/tweelingen_herstel.py`, dry-run is de default; échte run = `gcloud run jobs execute rlz-reconciliatie --args=… --uitvoeren`
  ná Peters "ja"): per administratie in eigen RLS-scope een losse open inkoopfactuur-PDF (te_controleren/handmatig_afmaken/
  klaar_om_te_boeken, bron e-mail) × verkoopfactuur-UBL uit hetzelfde intake-bericht (zonder bericht: zelfde kalenderdag) op
  genormaliseerde stam of factuurnummer, precies één aan beide kanten; herstel = het UBL-document blijft HET document, de PDF wordt zijn
  beeld (`bron_*`), het PDF-document gaat terminaal naar `samengevoegd` mét `samengevoegd_in_id` (nooit verwijderd), tijdlijnregel op
  beide kanten, audit `gebundeld_achteraf` op beide rijen; is het UBL-document al geboekt (`verkoop_boeking`), dan gaat de PDF óók als
  RLZ-bijlage mee via `zorg_voor_bijlage` op `SalesInvoices/{verkoop_rlz_id}` (idempotent op bestandsnaam; een bijlage-fout is een
  zichtbare regel, de lokale bundeling staat); Odoo-administratie = bijlage overgeslagen mét reden; tweede run = 0 kandidaten.
  (3) Reconciliatieblok `documenten` toetst dezelfde kandidaten-motor lees-only en meldt per eenduidig paar `ubl_pdf_ongebundeld`
  (start in `meten`, `sinds` 24-09) mét actie "Bundelen" op de rij (`POST /reconciliatie/documenten/{document_id}/bundelen`,
  kantoorrol, mens-actor = exact het herstel; 404 geen paar, 409 twijfel/intussen verwerkt, 403 buiten scope;
  `frontend/src/reconciliatie/BundelenActie.tsx`). Guards: `tests/intake/test_bundeling_stam_factuurnummer.py`,
  `tests/intake/test_tweelingen_herstel.py`, gouden-set-casus b `TestVastlySuffixStam`, vitest `BundelenActie.test.tsx`.
  Werkt in productie: niet gemeten (dispatch-onderdeel `vastly-tweelingen`).

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 1 (FV-01) -->
- **UBL zonder beeld = samenvattingskaart, onleesbare XML = handmatig afmaken mét reden (Peter 25-09; FV-01, casus Universal
  Nederland RLZ-2080142898 → Universal Steigerbouw, document 250895e8; geen migratie; BESLISSINGEN "UBL ZONDER BEELD —
  SAMENVATTINGSKAART I.P.V. RUWE XML, ONLEESBARE XML = HANDMATIG AFMAKEN MÉT REDEN (Peter 25-09)"):** (1) **Vaststelling:** de UBL van
  02-09 was deterministisch geparst (referentie, 775,26 / 938,06, 1 regel) maar kwam zónder haar PDF binnen (PDF → splitsingsvoorstel,
  UBL → verzamelbak → handmatig toegewezen; `bron_bestandsnaam` leeg) en het bijlage-paneel toonde voor een XML-hoofdbestand zonder
  beeld (`beeld.py` stap 3) de RUWE XML — dat was "het blok code". (2) **Parser** (`documenten/ubl.py`): `GeenGeldigeUbl` draagt altijd
  een leesbare reden — vóór het parsen gzip/zip/PDF-met-xml-naam/leeg (`_herken_geen_xml`), daarna "Geen geldige XML: …" of "root-element
  <X> is geen UBL Invoice of CreditNote" (root op de LOKALE naam: RLZ `doc:`-prefix én exporteurs zonder default-namespace lezen; BOM/UTF-16
  las expat al); `ubl_onvolledig_reden` = geen factuurnummer/totaal/regels ("UBL onvolledig — ontbreekt: …"); `cbc:Note` "Werk: …" →
  `note` + kop-`project_tekst` (tekst ná "Werk:", deterministisch via `project_tekst_uit_note`; de bestaande match-motor maakt er
  exacte code 26084 = groen van — casus a prefillt sindsdien het project uit de UBL). (3) **Extractie-afronding** (`service._rond_
  extractie_af`): een niet-parsebare óf onvolledige XML gaat naar HANDMATIG_AFMAKEN mét detail `ubl_parse_fout` (kop-voorstel blijft
  bewaard bij onvolledig) en tijdlijnregel "XML niet leesbaar — handmatig afmaken: ‹reden›" (was: te_controleren zonder voorstel). Het
  intake-pad blijft: onleesbare UBL → verzamelbak `ubl_invalide` (§2d-failsafe). (4) **Route** `GET /administraties/{id}/documenten/{doc}/
  ubl-samenvatting` (`documenten/ubl_samenvatting.py`, kantoor + accordeur, scope, lees-only, geen AI): 200 mét kop, partijen, totalen,
  KvK/btw/IBAN, betalingskenmerk, note/project_tekst, regels (aantal/netto/btw%/btw-bedrag) en `onvolledig`; niet leesbaar = 200
  `leesbaar=false` + dezelfde reden als de tijdlijn; geen XML-hoofdbestand = 422. (5) **Nazorg lees-only** `xml-documenten-rapport
  [--administratie <uuid|naamdeel>] [--alles] [--detail] [--json-uit]` (`documenten/xml_rapport.py`; per administratie in eigen RLS-scope):
  status, beeld (bron_pdf/ingesloten_pdf/geen), reden, PDF-tweeling in hetzelfde intake-bericht (administratie + verzamelbak), voorstel
  (`verzamelbak-nabundelen --ook-toegewezen` / `intake-herlezen --alleen-ubl`), oordeelregel "TOTAAL N xml-documenten · M zonder beeld ·
  K niet leesbaar · T mét PDF-tweeling · fouten F"; nameting-allowlist, dispatch-onderdeel `xml-documenten`. Guards
  `tests/documenten/test_ubl_rlz_export.py`, `test_xml_niet_leesbaar.py`, gouden-set-casus **a2** `tests/keten/test_a2_ubl_zonder_beeld.py`.
  Werkt in productie: niet gemeten (klikpunt: 250895e8 openen ná deploy → kaart; PDF-tweeling koppelen via nabundelen).

<!-- toegevoegd 02-10-2026, opdracht "boeken-prettig-1-bijlagen-bij-factuur-controlescherm-rustig-overhead-automatisch" punt 1 -->
- **Eén mail = één document — bijlagen blijven bij de factuur (Peter 02-10 "nu zijn nog steeds alle bijlagen vanuit de verhuur
  losgekoppeld van de factuur … dat moet zodadelijk als eerste gefixt worden want dat scheelt heel veel werk"; migratie 0174 =
  `document.samenvoeg_rol` + `verplaats_document`/policy `document_verplaatsing` nemen bijlage-rijen mee; BESLISSINGEN "BOEKEN PRETTIG 1 —
  BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)" punt 1):** (1) **Herkenning per bijlage, deterministisch,
  vóór élke AI-stap** (`app/intake/bijlage_herkenning.py`): FACTUUR = een UBL, óf een PDF mét tekstlaag die de drie factuursignalen samen
  draagt (factuurwoord factuur/invoice/creditnota + totaalsignaal totaal/te betalen/amount due + btw-/bedragsignaal btw/vat/€); KANDIDAAT
  = niet deterministisch te zeggen — PDF zonder tekstlaag (scan/foto-naar-PDF), ProfX-kassarapport, omzetbron-spreadsheet, inline of te
  kleine afbeelding (logo-filter), onbekend bijlagetype — en loopt de BESTAANDE route (AI-splitsing/verzamelbak/niet_verwerkbaar,
  ongewijzigd); BIJLAGE = PDF mét tekstlaag zonder factuursignalen (huurstaat, specificatie, werkbon), spreadsheet die geen omzetbron is,
  csv/doc(x)/txt (whitelist — vCards/.ics/.p7s blijven mailgruis) en een niet-inline, groot genoege foto. (2) **De mail-regel**
  (`verwerking._verwerk_items_met_bijlagen`, alle kanalen incl. facturen@kempengroep.nl): eerst lopen álle niet-BIJLAGE-items de bestaande
  routing; precies één factuur-document (toegewezen/verzamelbak/splitsingsvoorstel) → élke BIJLAGE hangt eraan; meerdere → per bijlage de
  factuur waarvan een sleutel (UBL `cbc:ID` ≥ 4 tekens, cijfer-tokens uit `cbc:Note`, het AI-gelezen factuurnummer van een PDF-factuur)
  in de bestandsnaam of — bij een PDF — in de tekstlaag staat; geen eenduidige treffer → bij álle facturen uit die mail mét rol
  `bijlage_niet_eenduidig` (chip "niet eenduidig" — liever dubbel dan kwijt); nul facturen → bestaand gedrag (de bijlagen lopen alsnog
  de oude route, nooit stil weg). De 0106-regel "nooit splitsen binnen één PDF" blijft; de bundeling-regel 24-09 (factuurnummer in
  PDF-naam/-tekst) maakt een PDF mét tekstlaag ZONDER factuursignalen nooit meer het factuurbeeld (die wordt bijlage). (3) **Een bijlage
  is een `document`-rij** (`app/documenten/bijlagen.py` — de enige schrijver van `samenvoeg_rol`): status `samengevoegd`,
  `samengevoegd_in_id` = de factuur, `samenvoeg_rol` 'bijlage' | 'bijlage_niet_eenduidig' (NULL = de hulzen van vóór 02-10: byte-identiek
  exemplaar / UBL-beeld), opslag onder de scope van de factuur (administratie óf `niet_toegewezen/`), idempotent op (intake-bericht, sha256,
  factuur). Geen werkvoorraad-rij, nooit geëxtraheerd, nooit gesplitst, nooit verwijderd; tijdlijnregel op beide kanten (sleutel
  `bijlage_bij_factuur`, `vorige_status` voor ongedaan) + audit `bijlage_gekoppeld` → dagteller `bijlagen_gebundeld` in de reconciliatiemail
  (`niet_eenduidig` als zachte categorie); intake-bericht-uitkomst `bijlage`. Verzamelbak-factuur: `verzamelbak.wijs_toe` neemt de
  bijlage-rijen mee (`bijlagen.verhuis_bijlagen_mee`); verplaatsen: de SECURITY DEFINER-functie verhuist ze mee. (4) **Zichtbaar en mee
  naar RLZ:** `DocumentDetailResponse.bijlagen` → tabbladen "Factuur · ‹bijlage›…" boven het bijlage-paneel (`document/BijlageTabs.tsx`:
  PDF inline, foto als beeld, overig = downloadknop; chip "niet eenduidig"), route `GET …/documenten/{factuur}/bijlagen/{id}/bestand`
  (kantoor + accordeur; 404 als de bijlage niet aan dít document hangt); documentenlijst: chip "N bijlagen" op de factuur (bijlagen tellen
  NIET als `samengevoegde_exemplaren`) en "→ bijlage van ‹factuur› (niet eenduidig)" op de bijlage-rij onder "Toon afgehandelde documenten".
  Boeken (`InkoopPort.boek_inkoopfactuur(extra_bijlagen=…)`, `bijlagen.extra_bijlagen_voor_boeking`): RLZ = élke bijlage als EXTRA
  `/Uploads` naast het factuurbeeld (`rlz_ids.rlz_bijlage_upload_id(bijlage, boek_cyclus)`, aanwezigheid op bestandsnaam via
  `zorg_voor_bijlage(op_bestandsnaam=True)`); een mislukte extra bijlage = zichtbare waarschuwing in het boekdetail, nooit
  `boeken_mislukt`; Odoo = extra `ir.attachment` (niet main). (5) **Nazorg** `bijlagen-nabundelen [--dry-run] [--uitvoeren]
  [--administratie <uuid|naamdeel>] [--sinds JJJJ-MM-DD] [--ongedaan <bijlage-id> --reden …]` (`app/intake/bijlagen_nabundelen.py`,
  dry-run default, nameting-allowlist alleen mét `--dry-run`; de échte run = `gcloud run jobs execute rlz-reconciliatie
  --args=-m,app.cli,bijlagen-nabundelen,--uitvoeren` ná Peters "ja"): per `intake_bericht` mét ≥ 2 documenten dezelfde herkenning op de
  opgeslagen bytes + dezelfde mail-regel; alleen OPEN bijlage-documenten (ontvangen/te_controleren/handmatig_afmaken/klaar_om_te_boeken/
  niet_toegewezen), een document waar een mens al over oordeelde (vraag, accordering, geboekt, afgewezen) = overgeslagen mét reden; andere
  administratie = "eerst verplaatsen"; verzamelbak-bijlage verhuist mee naar de factuur; niet eenduidig = het bestaande document aan de
  eerste factuur, een KOPIE-rij per volgende; geboekte factuur → bijlage alsnog als RLZ-upload (`PurchaseInvoices/{herboeking-GUID}` resp.
  `SalesInvoices/{verkoop_rlz_id}`, Odoo = overgeslagen mét reden); dry-run = "factuur ← bijlagen" per administratie + TOTAAL-regel;
  ongedaan = `bijlagen.maak_bijlage_ongedaan` (terug naar `vorige_status`; intake-bijlage → ontvangen en de normale keten; geweigerd zodra
  de factuur geboekt is). Statusmachine: ontvangen/klaar_om_te_boeken → samengevoegd, samengevoegd → ontvangen/klaar_om_te_boeken.
  **Keuzes zonder Peter:** scan zonder tekstlaag = kandidaat (nooit raden), foto's alleen bijlage als de mail een factuur draagt,
  ongedaan als CLI-vorm (geen nieuwe knop), bijlage als `samengevoegd`-rij i.p.v. een nieuwe tabel (één representatie voor intake én
  nazorg; RLS/verplaatsen/archief/zoeken ongewijzigd). **Beperking:** een splitsingsvoorstel-bron krijgt de bijlagen; de kinderen ná
  bevestiging niet (de nazorg-CLI vangt ze op hetzelfde bericht). Guards `tests/intake/test_bijlagen_bij_factuur.py` (herkenning,
  één factuur, routes, meerdere facturen, nul facturen, scan = AI-route, verzamelbak, boeken mét extra uploads, RLZ-fout zichtbaar, nazorg
  dry-run/uitvoeren/idempotent/ongedaan/mens-oordeel/geboekt-upload, dagteller), gouden-set-casus **ap**
  `tests/keten/test_ap_bijlagen_bij_factuur.py`, vitest `DocumentDetailScreen.test.tsx` + `WerkvoorraadScreen.test.tsx`; dispatch-onderdeel
  `bijlagen-factuur`. Werkt in productie: niet gemeten.

<!-- toegevoegd 03-10-2026, opdracht "bijlagen-nabundelen-volgt-duplicaat-naar-origineel" -->
- **Bijlage volgt het duplicaat naar het origineel (BUG 03-10, Peter "werkdetails zonder factuur kan niet"; casus Universal
  Steigerbouw `3ee6edf0`: de échte nazorgrun `bijlagen-nabundelen --uitvoeren --administratie "Universal Steigerbouw"` (executie
  `rlz-reconciliatie-z8dj8`, 94 e-mails, 24 gekoppeld) gaf 7 × "overgeslagen — geen factuur-document in deze mail" terwijl de
  factuur `Factuur RLZ-20801430xx ….pdf` wél in die mails zat — zes keer als `afgevoerd_duplicaat`, één keer (3044, PDF én XML)
  als `afgewezen` — en de `factuurdetails-….pdf` los op te_controleren bleef; geen migratie; BESLISSINGEN "BOEKEN PRETTIG 1 —
  BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)" subkop "Bijlage volgt het duplicaat naar het
  origineel (03-10)"):** de mail zei bij welke factuur de bijlage hoort; die kennis gooien we niet meer weg. (1) **Motor**
  `app/documenten/bijlage_doel.py::volg_naar_origineel`: een factuur mét status `afgevoerd_duplicaat` of `afgewezen` wordt gevolgd
  naar het document dat wél telt — (a) `afwijzing.duplicaat_van_document_id` van de open afvoer-afwijzing, (b) anders de vlag
  `document.mogelijk_duplicaat_van_id`, (c) anders hetzelfde factuurnummer binnen dezelfde administratie (precies één treffer op
  `boekvoorstel.referentie_norm` — de ENE normalisatie van 16-09, dezelfde vergelijkingsvorm als de duplicaatcheck; meerdere
  treffers = nooit raden). Een doel mag GEBOEKT zijn (bestaand gedrag "(geboekt)" → bijlage óók als RLZ-upload); een doel dat zelf
  weer afgevoerd/afgewezen is wordt doorgevolgd (keten, max 5 stappen); verwijderd/samengevoegd/gesplitst = geen doel; nooit een
  doel buiten de administratie. Geen doel = `GeenDoel` mét leesbare reden én de afwijsreden. (2) **Nazorg `bijlagen-nabundelen`:**
  zijn er in de mail geen dragers meer maar wél volgbare facturen, dan zijn de via-duplicaat-doelen de facturen; de dry-run-regel
  luidt "‹origineel› ← ‹bijlage› […]: kandidaat — via duplicaat → ‹origineel› — zou koppelen aan …" (afgewezen mét tegenhanger:
  "via afgewezen factuur → …"), de TOTAAL-regel krijgt de teller "… N mislukt, K via duplicaat — …" (de nameting-grep op het vaste
  voorvoegsel blijft werken). Afgewezen factuur ZONDER tegenhanger → de bijlage blijft los mét uitkomst "overgeslagen — factuur
  afgewezen (‹reden›) — bijlage ook afwijzen? [‹factuur›; ‹zoekreden›]"; de ÉCHTE run zet daarbij één idempotente tijdlijn-notitie
  `bijlage_factuur_afgewezen` op de bijlage (dry-run blijft lees-only, nameting-allowlist) → `DocumentDetailResponse.
  factuur_afgewezen_in_mail` → chip "factuur uit dezelfde e-mail afgewezen" mét link naar de afgewezen factuur + "bijlage ook
  afwijzen?" bovenin het controlescherm van de bijlage. Nooit automatisch afwijzen. Afgevoerd duplicaat zonder origineel ín de
  module (origineel buiten de module geboekt) = overgeslagen mét reden. Een bijlage die al aan het duplicaat HING (live-pad van vóór
  deze fix: `samengevoegd` mét rol, `samengevoegd_in_id` = het duplicaat) wordt niet opnieuw gekoppeld maar VERHUISD
  (`bijlage_doel.verhuis_bijlagen_naar_origineel`: zelfde rol, tijdlijn op bijlage én origineel, audit `bijlage_naar_origineel`),
  uitkomst "gekoppeld — verhuisd van duplicaat ‹naam›"; geboekt origineel → alsnog de RLZ-upload. (3) **Live-intakepad:**
  `verwerking._dubbel_voor_ai` geeft bij uitkomst `dubbel` (byte-identiek vóór de AI-stap: exemplaar afgevoerd óf huls in de
  verzamelbak) het ORIGINEEL als drager mee (`BijlageResultaat.drager_document_id/-administratie_id/-bestandsnaam`, sleutels uit het
  boekvoorstel van het origineel); `_verwerk_items_met_bijlagen` neemt via `_drager_van` dat origineel als factuur — de bijlagen uit
  die mail hangen aan het origineel, detail "— via duplicaat: de factuur uit deze mail was al bekend", nooit aan het afgevoerde
  exemplaar en nooit los. De referentie-afvoer ná extractie (`duplicaat_afvoer._voer_af`: opt-in automatisch én één-klik door een
  mens) roept ná de afwijzing `bijlage_doel.verhuis_na_afvoer` aan: bijlagen die al aan het duplicaat hingen verhuizen naar het
  origineel ín de module (eigen transactie; een fout stopt de afvoer niet maar staat in het log, de nazorg vangt 'm op). (4)
  **Keuzes zonder Peter:** (a) "hetzelfde factuurnummer" = `referentie_norm` (de opdracht noemde de bh-sleutels; één normalisatie
  i.p.v. twee), (b) de afgewezen-notitie alleen in de échte run (dry-run = lees-only), (c) de teller `via_duplicaat` telt óók de
  via-afgewezen-factuur-doelen (één teller zoals gevraagd), (d) de chip staat bovenin het controlescherm (náást de correctiebalk), niet
  alleen in de ingeklapte tijdlijn. (5) **Guards:** `tests/documenten/test_bijlage_doel.py` (drie bronnen, keten, meerdere treffers,
  afgewezen zonder tegenhanger, verhuizen idempotent, notitie idempotent + DTO), `tests/intake/test_bijlagen_bij_factuur.py::
  TestBijlageVolgtDuplicaatNaarOrigineel` (dry-run-regel + TOTAAL-teller, échte run aan het origineel, geboekt origineel mét
  upload, afgewezen zonder/mét tegenhanger incl. detail-route, al-gekoppelde bijlage verhuist, live-pad `dubbel`, `_voer_af`),
  gouden-set-casus ap `TestBijlageVolgtDuplicaatNaarOrigineel` (casus c tweemaal: werkbon aan het origineel, 0 AI-calls, standaardlijst
  1), vitest `DocumentDetailScreen.test.tsx` (chip mét link / geen chip). Testles: de automatische duplicaat-afvoer staat in de suite
  platformbreed AAN — een tweede document mét hetzelfde factuurnummer én bedrag voert de motor in de test zelf af (fixtures variëren het
  bedrag). Werkt in productie: niet gemeten (terminal-opdracht `opdrachten/terminal/2026-10-03-bijlagen-nabundelen-herhaling.md`:
  dry-run Steigerbouw → verwacht 6–7 "via duplicaat" → échte run → kantoorbreed; nameting-opdracht
  `opdrachten/inbox/2026-10-03-nameting-bijlagen-volgt-duplicaat.md`, dispatch-onderdeel `bijlagen-factuur`).

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Verzamelbak "Niet toegewezen" (preview, optimistisch toewijzen, verplaatsen, documentenlijst) (CLAUDE.md `ed6d176` r. 494–528)

- **Verzamelbak "Niet toegewezen"**: alles wat niet eenduidig aan een administratie koppelt
  (tenaamstelling leidend, afzender = hint); leert van handmatige toewijzingen; "hoort niet bij
  ons" met reden. Nooit auto-toewijzen bij twijfel.
  **Bouwstatus: GEBOUWD + GETEST (2026-08-07, met de e-mail-intake)** — migratie 0028 +
  `backend/app/intake/` + `frontend/src/intake/`; details BESLISSINGEN "E-mail-intake +
  verzamelbak — GEBOUWD + GETEST". **Preview per rij (besluit Peter 25-08, D1): hover toont lazy
  de eerste PDF-pagina, klik de volledige weergave — leesroute `GET /verzamelbak/{id}/bestand`,
  fail-closed tot echte verzamelbak-documenten. Popup sinds 26-08 via `ui/basis/AnkerPopup.tsx`
  (portal + fixed, flipt aan de viewport-rand) — nooit meer een absoluut gepositioneerde popup
  bínnen `.tabel-scroll`/`table{overflow:hidden}` (feedbackronde 26-08 punt 2). **Toewijzen/hoort-niet
  OPTIMISTISCH (avondrun 26-08): rij direct weg, request async, mislukt = rij LUID terug mét rode
  reden; server idempotent (tweede klik = 200 `al_verwerkt` + rustige melding, conflicten in
  leesbare taal — geen enum-jargon); DB blijft bron van waarheid. Zie BESLISSINGEN "AVONDRUN 26-08".**
  **Foute toewijzing herstellen = "Verplaats naar andere administratie…" (⋯-menu controlescherm,
  besluit Peter 27-08, migratie 0080): alleen inkoopfacturen op te_controleren/handmatig_afmaken/
  klaar_om_te_boeken/vraag_open/afgewezen (geboekt = storno/tegenboeken, ter_accordering = eerst
  intrekken — server-side 409 mét uitleg); boek-/veldvoorstel vervallen en de extractie draait
  opnieuw achter de gates van het dóél; open vragen verhuizen mee; het toewijzings-geheugen
  corrigeert de regel die naar de oude administratie wees; RLS-doorbraak uitsluitend via de
  zelf-gepoorte SECURITY DEFINER-functie `boekhouding.verplaats_document` (bron-scope + status
  ontvangen). `app/documenten/verplaatsen.py`; BESLISSINGEN "KANTOOR-MINI-RUN 27-08" punt 5.
  Optionele checkbox "onthoud: deze tenaamstelling hoort bij <doel>" (default UIT, alleen de
  tenaamstelling, géén automatische leer-regel — werkstroom-run 27/28-08 punt 6a).**
  **Documentenlijst (werkstroom-run 27/28-08, punt 3/4): leverancier = vette hoofdregel, bestandsnaam ·
  bron · binnenkomst = metaregel; dichtheid normaal/compact per gebruiker (localStorage, geen
  migratie); status-dot "Geboekt" = `--ok`-groen (pil-chip blijft grijs); uploadzone één regel + ⓘ;
  verwijderen uitsluitend via het ⋯-rijmenu mét bevestiging en VERPLICHTE reden (server 422 zonder).
  Sorteerbare kolomkoppen (opruimrun 28-08 punt 21): Leverancier/Factuurdatum/Bedrag/Status/Toegewezen,
  klik = oplopend → aflopend → uit, pijl + aria-sort; de sortering is onderdeel van de lijstcontext
  (`sort=<kolom>:<richting>` in de URL) zodat ‹ ›, "n van m" en de na-boeken-doorloop dezelfde volgorde
  volgen. Administratie-kiezers zijn overal in de kantoor-UI een doorzoekbare combobox
  (`ui/AdministratieCombobox`, punt 13) — nooit meer een kale select.**
  Eigen naamnormalisatie: "Holding" blijft onderscheidend
  (mockup-casus); afzender-regel wijst alleen auto toe zonder tegenstrijdig
  tenaamstelling-signaal.

### Domeinbeslissingen — E-mail intake (IMAP, routing, één extractiepad, mail-body, afbeeldingen) (CLAUDE.md `ed6d176` r. 529–574)

- **E-mail intake**: één centraal adres — **`facturen@ak-nijenhuis.nl`** (adreskeuze Peter
  2026-08-15, bewust kort; Google Workspace) — splitsen van multi-factuur-PDF's op
  factuurgrenzen, toewijzen op tenaamstelling.
  **Bouwstatus: GEBOUWD + GETEST (2026-08-07)** — .eml-upload (`POST /intake/eml` + werkvoorraad-
  uploadzone) is het werkende kanaal, idempotent op Message-ID; **de live IMAP-fetch is
  GEACTIVEERD (F3.4, 2026-08-15)**: echte imaplib-bron in `app/intake/postvak.py` (UNSEEN +
  BODY.PEEK, gelezen-vlag pas ná geslaagde verwerking = crash-veilige retry, zelfde
  idempotente codepad als de upload, systeem-actor, bron `imap`), job-config in deploy.yml
  (imap.gmail.com SSL 993, wachtwoord via secret `INTAKE_IMAP_WACHTWOORD`) — zie GCP_UITROL
  §F3.4-uitvoering; de .eml-upload blijft het lokale werkkanaal tot tranche 2. Routing per bijlage: kapotte/NLCIUS-invalide UBL → verzamelbak (§2d-
  failsafe), VGB → genegeerd-maar-zichtbaar, VASTLY-VERKOOP → soort 'verkoopfactuur' (het
  boekpad is sinds 2026-08-09 GEBOUWD — zie "Verkoopfactuur-boekpad" hieronder; een 381-
  CreditNote zit achter de config-gate `creditnota_381_ingeschakeld` — AAN sinds 2026-08-10
  na de golden-case-verificatie; uit-zetten kan via de env-var, gate dicht = zichtbaar in de
  verzamelbak), inkoop-UBL → tenaamstelling-toewijzing,
  PDF → intake-AI achter de platform-brede AVG-gate `intake_ai_ingeschakeld` (default UIT;
  sinds migratie 0029 een Beheerder-instelling `platform.intake_instelling` — knop op
  Instellingen + `make intake-ai-aan/-uit`, env-setting alleen nog fallback zolang die rij
  ontbreekt). Her-upload van een bericht dat op "bezig" bleef hangen (afgebroken run) wordt
  herverwerkt i.p.v. vroeg terug te keren, idempotent op (intake_bericht_id, sha256) —
  fix 2026-08-07. Multi-factuur-splitsing: AI-voorstel ALTIJD eerst ter controle, bevestigen =
  deterministische pypdf-splitsing, bron-document terminaal `gesplitst`.
  **Eén extractiepad voor álle ingangen (feedbackronde 26-08 punt 4):** mail/IMAP, sleepzone
  (`/intake/bestand`), klantpagina-upload, verzamelbak-toewijzen en splitsing lopen alle via
  `upload_document`/`start_extractie_na_toewijzing` achter dezelfde gates (per-administratie
  `ai_extractie_ingeschakeld` + API-key + AI-kostengrens) — regressietests per ingang in
  `tests/intake/test_extractie_per_ingang.py`. Grote documenten (> 3 MB / > 8 pag.) gaan naar de
  extractie-wachtrij: in de cloud sinds 26-08 de on-demand job `rlz-extractie-wachtrij` +
  */10-scheduler-vangnet (een in-process thread valt op Cloud Run met request-based CPU stil —
  dát was "geüploade factuur krijgt geen AI-extractie"); controlescherm toont een overgeslagen
  extractie mét reden.
  **Mail-body bij het boekingsvoorstel (feedbackronde 25-08 deel 3 punt 1, migratie 0069):**
  de intake bewaart de platte mail-body op `intake_bericht.body_tekst` (HTML → tekst, ruis
  deterministisch gestript — `app/intake/mailbody.py`), gedeeld door álle documenten uit die
  mail (FK), zichtbaar als inklapbaar blok "Uit de e-mail" op het controlescherm, en als HINT in
  toewijzing (uitsluitend een verzamelbak-suggestie `mail_body`, tenaamstelling blijft leidend)
  én AI-extractie (BSN-gefilterd, begrensd, achter de bestaande gates). Geen backfill.
  **Afbeeldingen (punt 2, migratie 0070):** JPEG/PNG/HEIC via mail én alle upload-zones →
  bij binnenkomst deterministisch + verliesvrij naar PDF (`app/documenten/afbeelding.py`,
  eigen PDF-writer; HEIC eerst naar JPEG) zodat de keten uniform PDF blijft; origineel =
  brondocument (`document.bron_*`, route `/bronbestand`); onbruikbaar → verzamelbak met reden
  (mailpad) of 422 (directe upload); inline logo's/< 600 px blijven `niet_verwerkbaar`. De
  werkvoorraad-sleepzone accepteert sindsdien ook losse PDF/UBL/foto via `POST /intake/bestand`
  (zelfde tenaamstelling-routing als een mailbijlage). Dependencies staan in `pyproject.toml`
  (geen requirements.txt) en worden bewaakt door `tests/unit/test_dependencies_gedeclareerd.py`.
  Zie BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 3".

### Domeinbeslissingen — AI-kostengrens intake (CLAUDE.md `ed6d176` r. 575–584)

- **AI-kostengrens intake (besluit Peter 2026-08-14, GEBOUWD + GETEST zelfde dag, migratie
  0047)**: Anthropic-API-kosten voor intake-AI max € 100 per kalendermaand (Europe/Amsterdam) —
  deterministische kostenmeter (`backend/app/aikosten/`): élke Claude-call append-only gelogd
  met wérkelijke token-usage (incl. cache), kosten in code uit gepinde prijstabel × gepinde
  USD→EUR-koers 1,00 (conservatief), harde poort vóór élke call ín de client (≥ limiet = call
  niet doen; onbekend model fail-closed). Boven de grens NOOIT stil wegvallen: zelfde pad als
  intake_ai=uit (verzamelbak-reden/chip "AI-limiet bereikt — handmatig verwerken"); 80%- en
  100%-melding éénmalig per maand (werkvoorraad-banner + audit); limiet Beheerder-only op
  Instellingen (verbruiksblok naast de AI-gate-knop). Tweede laag = klikwerk Peter: spend-limit
  ~$110 in de Anthropic-console. Zie BESLISSINGEN "AI-KOSTENGRENS INTAKE".

### Domeinbeslissingen — Deterministische extractie-terugval: template per bekende leverancier (CLAUDE.md `ed6d176` r. 595–619)

- **Deterministische extractie-terugval — template per bekende leverancier (best-practice-besluit 2,
  31-08, GEBOUWD + GETEST 01-09, migratie 0094 — BESLISSINGEN "EXTRACTIE-TERUGVAL TEMPLATES" is
  canoniek):** `app/extractie/template_terugval.py` (pure logica) + `template_service.py` (DB/audit).
  Per crediteur (sleutel: btw-nummer > KvK-nummer uit `crediteur_kenmerk` — werkt dan over
  administraties heen — anders administratie+crediteur) leert het systeem uit de laatste N ≥ 3 door een
  MENS geboekte PDF-facturen ankers per kopveld uit de tekstlaag (label ervoor / label erboven /
  kolomkop, pypdf layout-modus); een template is pas geldig als hij álle N exact reproduceert
  (cent-exact, datums exact, referentie letterlijk) — anders géén template, nooit half. Runtime-volgorde
  per PDF (`documenten/service.py::_pdf_extractie_detail`): (a) geldig template + tekstlaag →
  template-parse mét interne validaties (excl + btw = incl cent-exact, vormpatroon referentie,
  geleerde btw-percentages, vervaldatum ≥ factuurdatum; één rood = VOLLEDIG verworpen + template
  ongeldig mét reden + audit) — NIET achter de AI-AVG-gate (lokale code, geen data naar buiten, werkt
  dus ook bij AI uit/limiet bereikt); (b) AI-pad ongewijzigd; (c) handmatig-pad ongewijzigd.
  Regelniveau alleen de veilige vorm (één regel = kop-totalen als álle leerdocumenten zo bevestigd
  zijn), anders kop-only + boekingsgeheugen. Crediteur-herkenning zonder AI: btw → KvK → IBAN → exacte
  naam, precies één kandidaat. Downstream ongewijzigd: zelfde veldvoorstel-contract (`bron:
  "template"`, zekerheid 1.0, `template`-blok), zelfde harde checks, autoboek-poorten tellen een
  template-extractie exact als een AI-extractie; chip "uit template" per veld, tijdlijn benoemt de bron.
  Leren/vervallen post-commit ná élke boeking (`boeken.py` → `leer_na_boeking_stil`): correctie door
  de controleur of layoutwijziging = ongeldig + direct opnieuw leren; `automatisch_geboekt` telt niet
  als leerbron; geen handmatig templatebeheer. Teller op Instellingen naast het AI-verbruiksblok ("N
  via template · M via AI · K actieve templates", `AiKostenStatusDto`). Bewaking-foutratio telt
  template-extracties niet als AI-poging. Tests: `tests/extractie/test_template_terugval.py` (pure,
  40) + `tests/documenten/test_template_terugval_pad.py` (keten, 9) + `tests/extractie/pdf_helper.py`
  (PDF-generator mét tekstlaag).

### Referenties — docs/DIAGNOSE_INTAKE_VERZAMELBAK_02-09.md (diagnose, fixes, nabundel-nazorg, mini-run 03-09 (2)) (CLAUDE.md `ed6d176` r. 1573–1613)

- `docs/DIAGNOSE_INTAKE_VERZAMELBAK_02-09.md` — **diagnose kliktest 02-09:** intake-AI leest de
  tenaamstelling wél maar antwoordt `ep=2` op 1-pagina-PDF's → de oude alles-of-niets-validatie verwierp het
  hele voorstel (72/76 splitsingsfouten sinds 25-08). **Punt 1 GEFIXT (spoedopdracht 02-09, BESLISSINGEN
  "INTAKE-SPLITSINGSBUG GEFIXT 02-09"):** pagina-aantal als feit in de opdracht
  (`opdracht_met_paginatelling`, géén schema-wijziging), proportionele validatie (`beoordeel_segmenten`:
  één factuur = hele document, bij meerdere alleen het ongeldige deel `ongeldig_reden` — `valideer_segmenten`
  blijft de harde poort voor mens-bevestigde bereiken), verzamelbak-rij toont de échte reden
  (`app/intake/redenen.py`; "geen tenaamstelling gelezen" alleen als er niets gelezen is), bewakingsprobe
  `intake_verwerpingsratio` (≥ 50 % verworpen bij ≥ 3 pogingen/uur) en nazorg-CLI `intake-herlezen`
  (`app/intake/herlezen.py`, idempotent, systeem-actor, geen geheugen-leren). **Punten 2 en 3 GEBOUWD 02-09 (blok B4, migratie
  0098 — BESLISSINGEN "UX-/INTAKE-VERBETER-RUN 02-09" rij B4):** UBL+PDF-paren bundelen vóór de routing
  (`app/intake/bundeling.py`: ingesloten-PDF-hash → naamstam; UBL leidend, PDF als beeld via `bron_*`,
  `/bestand?vorm=data` = de UBL), handmatig "Samenvoegen" in de verzamelbak (status `samengevoegd`, ongedaan
  te maken, nooit verwijderen), UBL-samenvatting als preview, afzender-leren uitgesloten voor
  kantoor-/doorstuurdomeinen (config `intake_afzender_uitgesloten_domeinen`) + flip-detectie (≥ 3 doelen =
  meerduidig, nooit meer gesuggereerd). **Vervolgronde 02-09 (BESLISSINGEN "VERVOLGRONDE 02-09"):**
  UBL-parser leest partijnamen óók uit `cac:PartyName/cbc:Name` (RLZ's eigen export, SI-UBL 1.1 — 97
  IC-facturen zonder tenaamstelling); één beeld-bron `documenten/beeld.py::bepaal_beeld` (bron-PDF →
  ingesloten PDF → hoofdbestand) voor preview, controlescherm én de RLZ-bijlage; `intake-herlezen
  --alleen-ubl --zonder-toewijzen` (deterministisch, geen AI); bulk-toewijzen / bulk-hoort-niet-bij-ons in de
  verzamelbak (orkestratie over de per-rij-routes, uitkomst per rij); zusje-signaal "tegenhanger al
  toegewezen" (93 IC-PDF's waren vóór de bundeling al via AI toegewezen — UBL's bulk-toewijzen = dubbele
  documenten); "Geboekt in RLZ · boekstuk · tegenpartij" +
  vindplaats-hint op lijst/detail/reviewschermen (`documenten/geboekt_in_rlz.py`, Elissen-casus);
  CLI `toewijzing-regels-opschonen` (cloud-run 02-09: 6 afzender-regels gedeactiveerd). **Nabundel-nazorg
  (akkoord Peter 02-09, GEBOUWD 03-09 — BESLISSINGEN "NABUNDEL-NAZORG 03-09"):** `app/intake/nabundelen.py` +
  CLI `verzamelbak-nabundelen [--dry-run]` (`make verzamelbak-nabundelen DRY_RUN=1`) koppelt een verzamelbak-UBL
  aan zijn al toegewezen PDF-tegenhanger uit dezelfde mail volgens het bundelingsmodel — het PDF-document blijft
  HET document, UBL = hoofdbestand/data, PDF = beeld (`bron_*`), deterministische her-extractie via het bestaande
  pad, UBL-rij → `samengevoegd`; uitsluitend te_controleren/handmatig_afmaken, opgeslagen boekvoorstel nooit
  overschreven (alleen koppelen), twijfel = overslaan mét reden, geheugen leert niets; ongedaan via de bestaande
  `samenvoegen-ongedaan`-route (alleen vóór boeken). **Cloud-run UITGEVOERD 03-09: 68 samengevoegd, 25 mislukt op een
  proxy-storing (schoon teruggerold) en daarna door Barbara bulk-toegewezen → 25 UBL+PDF-dubbelparen in Universal Steigerbouw =
  nazorg-beslispunt (BESLISSINGEN "NABUNDEL-NAZORG 03-09").** **Mini-run 03-09 (2) (BESLISSINGEN "MINI-RUN 03-09 (2)"):
  (A) nabundelen óók voor DUBBELPAREN — een al toegewezen UBL-document naast zijn PDF-document in dezelfde administratie
  uit hetzelfde intake-bericht (`--ook-toegewezen`, `--administratie` begrenst; UBL-document → terminaal `samengevoegd`,
  ongedaan = terug naar zijn vorige status); cloud-run Universal Steigerbouw 03-09 (dry-run 142 kandidaten — niet ~25:
  de hele deel-2–10-mailreeks van 02-09 stond dubbel). (B) `app/db/herkansing.py`: precies één herkansing per item bij
  een verbroken databaseverbinding in de nazorg-CLI's (pre-ping stond al aan sinds 0001); noodrem ná 3 opeenvolgende
  verbindingsfouten. (C) Webhook-diagnose Elissen: alle drie de geboekt-events op 31-08 16:15 afgeleverd (HTTP 2xx) —
  concept-antwoord `Platform/uitwisseling/rlz-antwoord-geboekt-events-2026-09-03.md`.**

### Referenties — docs/avg/ (AVG stap 1 voorbereid + besluiten Peter 02-09) (CLAUDE.md `ed6d176` r. 1614–1622)

- `docs/avg/` — AVG-pakket (jurist-akkoord 12-08); **stap 1 van `05-activatie-checklist.md` is op 02-09
  beslisklaar gemaakt (blok A): `09-zdr-beslisnotitie.md` (besluit Peter), `10-model-check.md` (sonnet-5 +
  haiku-4-5, ZDR-compatibel; register mist voorraad-normalisatie + contract-ontleding), `11-klantinformatie-
  tekst-concept.md` (Peter/jurist verstuurt), `12-beoordelingskader-gevoelige-administraties.md` (voorstel:
  Mantelzorgwoningen MN + Stichting Shuto UIT tot bevestiging). Feit cloud-DB 02-09: AI-gate AAN voor alle 30
  actieve administraties. BESLISSINGEN "AVG STAP 1 — VOORBEREID". **Besluiten Peter 02-09
  vastgelegd (BESLISSINGEN "VERVOLGRONDE 02-09" blok E): ZDR doorzetten via Sales + tijdelijke acceptatie
  default-retentie (doc 9 §4); ALLE administraties AAN incl. Mantelzorgwoningen MN en Stichting Shuto
  (doc 12); doc 11 gefinaliseerd; registeraanvulling V8 (doc 1 §7b).**

<!-- bundel-08-09 blok 2 -->

## Verwijsregels uit CLAUDE.md — WOORDELIJK verplaatst 02-10-2026 avond (run D 02-10 blok G; CLAUDE.md < 85k tekens)

> De volledige regelalinea's hierboven blijven canoniek; dit zijn de letterlijke verwijsregels zoals ze tot 02-10 avond in CLAUDE.md stonden (per punt staat in CLAUDE.md nu één regel + verwijzing).

- (CLAUDE.md blok "E-mail-intake, verzamelbak, splitsing en AI-extractie", regel 6) Tweede postvak facturen@kempengroep.nl DIRECT gelezen (Peter 22-09, migratie 0171): kanaal `facturen_kempengroep` + job `rlz-intake-imap-kempengroep`; een gelezen-vlag is geen verwerkt-administratie — de fetch leest INBOX + Spam, gelezen én ongelezen, en slaat over wat in `intake_bericht_verwerkt`/`intake_bericht` staat (Message-ID); spam = chip "uit Spam" + LET-OP; herstelrun `--sinds`; lees-only `intake-postvak-audit` — zie BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE + POSTVAKBEWAKING (Peter 22-09)".

- (CLAUDE.md blok "E-mail-intake, verzamelbak, splitsing en AI-extractie", regel 7) AI-limiet (BUG Peter 24-09): banner/Instellingen "geblokkeerd" uitsluitend op de LIVE stand `geblokkeerd` (`limiet_bereikt_op` = historisch maandfeit → "weer actief sinds … ; N wachten op heraanbieding"); motor `app/aikosten/heraanbieden.py` biedt verzamelbak-rijen `ai_limiet_bereikt` + documenten mét overgeslagen extractie automatisch opnieuw aan (élke intake-job-run + dagelijkse stap, oud → nieuw, stopt zichtbaar bij dichte poort, tijdlijn + audit + dagteller `ai_heraanbiedingen`, volumerem 300, knop "Opnieuw verwerken (N)" 202 + stand, CLI `ai-heraanbieden --dry-run`); byte-identieke dubbelencheck vóór élke AI-stap (`app/intake/dubbel_voor_ai.py`: exemplaar = huls `samengevoegd`, dagteller `ai_bespaard_dubbel`) — zie BESLISSINGEN "AI-LIMIET — BANNER OP DE LIVE STAND, HERAANBIEDING NÁ VERHOGING, DUBBELENCHECK VÓÓR DE AI-STAP (Peter 24-09)".

- (CLAUDE.md blok "E-mail-intake, verzamelbak, splitsing en AI-extractie", regel 8) Vastly-PDF-tweelingen (Peter 24-09): Vastly-UBL's dragen geen ingesloten PDF en heten `…-ubl.xml` → bundeling faalde stil bij intake (23 losse PDF's als inkoopfactuur, óók 31-08); stam-normalisatie (`-ubl`/`_ubl`/`-xml`) + derde regel UBL-`cbc:ID` in PDF-naam/-tekst (precies één kandidaat), nazorg-CLI `vastly-pdf-tweelingen-herstel` (dry-run default; geboekt UBL → PDF als RLZ-bijlage), bevinding `ubl_pdf_ongebundeld` (meten) mét actie "Bundelen"; dispatch-onderdeel `vastly-tweelingen` — zie BESLISSINGEN "VASTLY-PDF-TWEELINGEN — STAM-NORMALISATIE, FACTUURNUMMER-REGEL, HERSTEL-CLI EN BEVINDING (Peter 24-09)".

- (CLAUDE.md blok "E-mail-intake, verzamelbak, splitsing en AI-extractie", regel 9) UBL zonder beeld (Peter 25-09, FV-01): een XML-hoofdbestand zonder PDF toont de deterministische UBL-samenvattingskaart (`GET …/documenten/{id}/ubl-samenvatting`), XML-bron alleen achter "XML-bron tonen"; elke XML die geen (volledige) UBL is = `handmatig_afmaken` mét chip "XML niet leesbaar: ‹reden›" (leesbare parser-redenen, root op lokale naam, `cbc:Note` "Werk:" → kop-projecttekst); lees-only CLI `xml-documenten-rapport`, dispatch-onderdeel `xml-documenten` — zie BESLISSINGEN "UBL ZONDER BEELD — SAMENVATTINGSKAART I.P.V. RUWE XML, ONLEESBARE XML = HANDMATIG AFMAKEN MÉT REDEN (Peter 25-09)".

- (CLAUDE.md blok "E-mail-intake, verzamelbak, splitsing en AI-extractie", regel 10) Eén mail = één document (Peter 02-10, migratie 0174): per bijlage deterministisch factuur/kandidaat/bijlage vóór élke AI-stap; precies één factuur → álle niet-factuur-bijlagen (specificatie, huurstaat, werkbon, foto, xlsx/csv) hangen eraan als `samengevoegd`-rij mét `samenvoeg_rol` (tabbladen in het bijlage-paneel, extra `/Uploads` bij boeken), meerdere facturen → sleutel-match anders bij álle mét "niet eenduidig", nul facturen = bestaand gedrag; nazorg-CLI `bijlagen-nabundelen` (dry-run default, echte run ná Peters "ja"), dagteller `bijlagen_gebundeld` — zie BESLISSINGEN "BOEKEN PRETTIG 1 — BIJLAGEN BIJ DE FACTUUR, RUSTIG SCHERM, OVERHEAD AUTOMATISCH (Peter 02-10)".

- (CLAUDE.md blok "E-mail-intake, verzamelbak, splitsing en AI-extractie", regel 5) Wachtrij-trigger gebundeld (30 s per job, audit `gebundeld`, job herhaalt de pas ≤ 5), startup-vangnet laat verse bezig-runs staan, élke statusovergang compare-and-set (`StatusIntussenGewijzigd`) — BLOW-bulk 18-09: 118 executies, 429, 8× dubbel verwerkt, stil teruggezet duplicaat — zie BESLISSINGEN "KASSARAPPORT AUTOMATISCH TYPEREN + SIGNALERING ZONDER HANDELING SWEEP (Peter 19-09)".
