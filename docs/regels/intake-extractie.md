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
