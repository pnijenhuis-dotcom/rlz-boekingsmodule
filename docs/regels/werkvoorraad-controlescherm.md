# Regels — Werkvoorraad, documentenlijst en controlescherm

> **LEESPLICHT:** lees dit bestand volledig vóór élke wijziging, opdracht of advies in dit domein (CLAUDE.md, Peter 17-09).
> Woordelijk verhuisd uit CLAUDE.md op 17-09-2026 (opdracht "CLAUDE.md: volledige regels per domein"); niets samengevat,
> niets weggelaten. Volgorde = de volgorde in CLAUDE.md (chronologisch per onderwerp). Elke alinea draagt zijn eigen datum,
> migratie en BESLISSINGEN-sectie. Nieuwe besluiten komen hier woordelijk bij (capture-at-acceptance) + BESLISSINGEN-rij +
> hooguit één verwijsregel in CLAUDE.md. Code-paden van dit domein: zie `docs/regels/INDEX.md`.

**Wat het is:** Klantenlijst met tellers → documentenlijst → controlescherm; boekingsgeheugen, vragen, afwijzen, doorloop na boeken, kalenderdag, zoeken/archief.

## Regels (woordelijk uit CLAUDE.md, stand 17-09-2026)

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Werkvoorraad** = klantenlijst met tellers (alleen klanten mét openstaand werk) → klantpagina →
  controlescherm. Overal breadcrumbs, lijst→detail-patroon consistent.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Na boeken direct door + lijstcontext in de URL + sneltoetsen + actiebalk ónder "Doorbelasten na boeken" +
  boekingsregels-kolomminima** (besluiten Peter 25-08 t/m 01-09) — zie BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08 DEEL 4",
  "WERKSTROOM- + UI-RUN 27/28-08", "VERZAMELRUN 27-08" punt 4, "KANTOOR-MINI-RUN 27-08" punt 4, "GECOMBINEERDE RUN
  01-09" blok D; `werkvoorraad/volgendDocument.ts`, `werkvoorraad/lijstContext.ts`, `document/sneltoetsen.ts`.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Doorloop na boeken POSITIONEEL (blok 7 vervolgrun 07-09; herziet de soort-voorkeur van 25-08) + DatePicker-blurfix (blok 8) + "+ Nieuwe crediteur in RLZ" altijd bereikbaar (blok 6):** het eerstvolgende verwerkbare document ná het huidige in de getoonde lijstvolgorde, daarna cyclisch; een datum verdwijnt nooit meer stil bij Tab/blur (soepel parsen, anders rode rand + melding); crediteur aanmaken als vaste combobox-voetoptie + linkbtn — zie BESLISSINGEN "FIXRUN 07-09 — BLOK 7+8" en "FIXRUN 07-09 — BLOK 6".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Vervaldatum inkoopfactuur** (`boekvoorstel.vervaldatum`, harde check, `DueDate`; migratie 0078) — zie BESLISSINGEN
  "GECOMBINEERDE RUN 26-08" blok C.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **RLZ-betaalstatus inkoopfactuur + intake-kanaal declaraties@ (blok 3 bundel 08-09 avond; STAP-0 08-09; migratie 0126):** het RLZ-veld "Betaling" = `QuickPaymentSelection`, kaal zetbaar vóór én ná boeken (post blijft open, uit de betaallijst); acht RLZ-waarden letterlijk, herkomst kanaal (declaraties@ → "Betaald per bank") > factuur (deterministische incasso-detectie / UBL PaymentMeansCode 59 → "Wordt automatisch geïncasseerd" + verwachte betaaldatum) > mens wint; harde check "Betaalstatus (declaraties)"; tweede IMAP-postvak `intake-postvak-verwerken --kanaal declaraties`; Odoo = parkeerpost (geen niet-afsluitend equivalent) — zie BESLISSINGEN "RLZ-BETAALSTATUS INKOOPFACTUUR + INTAKE-KANAAL DECLARATIES" + api-verkenning "Betaalstatus inkoopfactuur — STAP-0 08-09".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Documentenlijst — bulk-acties (Peter 16-09 "nu moet dat 1 voor 1"; geen migratie):** checkbox per rij + "alle N in deze weergave" + shift-klik op élke weergave zonder eigen bulk-balk, primaire knop Verwijderen… + ⋯ Type wijzigen… / Verplaatsen… / Afwijzen…, één reden; `POST …/documenten/bulk` = N × de bestaande per-document-route mét uitkomst per rij (geboekt = overgeslagen, buiten scope = geen_toegang); type wijzigen = nieuw `documenten/soort.py` (→ ONTVANGEN, extractie opnieuw via het juiste pad) — zie BESLISSINGEN "DOCUMENTENLIJST — BULK-ACTIES (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Afgehandelde documenten — één toggle (definitieve aanvulling blok 3, Peter 08-09):** eindstatussen `samengevoegd`/`afgevoerd_duplicaat`/`verwijderd`/`afgewezen` (`AFGEHANDELDE_STATUSSEN`) standaard niet in de documentenlijst en niet in "Alle"; toggle "Toon afgehandelde documenten (N)" toont ze grijs mét reden + "→ samengevoegd in ‹document›"/"→ duplicaat van ‹document›"; tellers reizen altijd mee (`tel_afgehandeld`, chip afgewezen blijft); ⋯-menu op zo'n rij alleen Openen/Toon origineel (+ Herstellen bij verwijderd); chip "N exemplaren samengevoegd" op het echte document; boeken/aanbieden = 409 (`DocumentNietAanbiedbaar`). Plus de live-uitkomsten van de cloud-scripts (wachtrij-restoorzaak = doorbelasting-`review_data` per item, `rlz_dubbel` bij Kempen 516 paren = niet inzetbaar, backfills uitgevoerd) — zie BESLISSINGEN "NAZORGRUN 08-09 — CLOUD-UITKOMSTEN BUNDEL 08-09 + AANVULLING BLOK 3".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Lijst-aanvulling — de standaardlijst is kantoorwerk (blok 11, besluit Peter 08-09):** `geboekt` onder de toggle afgehandeld (grijs, boekstuknummer, "Open in Reeleezee/Odoo"), tab "Geboekt (N)" vervalt, "Wachten op anderen (N)" = ter accordering + open vraag en telt niet in "Alle", `?groep=kantoor|wachten|afgehandeld`; klantenlijst-tellers/KPI's tellen alles — zie BESLISSINGEN "LIJST-AANVULLING — DE STANDAARDLIJST IS KANTOORWERK".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Boekingsgeheugen**: RLZ-historie + app-correcties; correcties wegen zwaarder (recency). Default
  voorstel, nooit blind boeken. Afwijkingen markeren (oranje), niet overnemen. **Seed-only = oranje
  (aangescherpt 2026-07-14): een waarde die uitsluitend op RLZ-historie steunt blijft oranje ("uit
  historie, nog niet bevestigd"), óók bij hoge stem-confidence — pas de eerste app-bevestiging van
  die waarde maakt 'm groen (`app_bevestigd` per veld in engine + voorstel-response).**

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Boekingsgeheugen — recency wint (blok 3.1 nametingen-run 10-09 avond, besluit Peter; geen migratie):** de laatste drie MENS-boekingen identiek (gegroepeerd per boekstuk) → die waarde groen + app-bevestigd, oudere afwijkende waarden tellen niet meer mee in de tie-break maar blijven zichtbaar als "eerder ook: …" (`VeldVoorstel.recent_consensus`/`eerder_ook`); B-A-A-A groen, A-A-B/A-B-A-A oranje, seed-only oranje; automatische boekingen schrijven geen observatie meer (`leg_boeking_vast(automatisch=True)`); activatie-motor ongewijzigd, rapportteller `eerder_afwijkend` — zie BESLISSINGEN "BOEKINGSGEHEUGEN — RECENCY WINT".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Prefill-autosave bij openen (A10 07-09):** leverancier-geheugen server-side in de prefill; `GET …/boekvoorstel` persisteert geheugen-/template-/default-prefills direct (herkomst-chip blijft, mens wint, idempotent, tijdlijn + audit) zodat checks en doorbelasten-blok dezelfde stand zien — zie BESLISSINGEN "STALE CHECK BIJ GEHEUGEN-PREFILL".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Controlescherm auto-first velden (blokken 9/10 vervolgrun 07-09, besluit Peter "auto-first"):** kop-omschrijving deterministisch (één regel → regeltekst; anders AI-veld `betreft`; anders leverancier + factuurnummer; mens wint als tijdlijn-override) en mee als RLZ `Description` / Odoo `narration`; projectnummer uit de factuur op kop- én regelniveau (AI-veld `proj`, gedeelde motor `app/projecten/match.py`: exacte code > leverancier-werknummer > plaats/opdrachtgever alleen oranje; meerduidig = nooit invullen; eerste keer per leverancier oranje, ná één boeking groen) — zie BESLISSINGEN "KOP-OMSCHRIJVING AUTOMATISCH" en "PROJECTNUMMER UIT DE FACTUUR".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Controlescherm Spot Services (blok 4 bundel 08-09; geen migratie):** tariefstaffel-regels (aantal 0, bedrag 0) zijn bron, geen boekingsregel (`documenten/veldvoorstel_regels.py`); één regel-projectnummer = kop-default; "btw verlegd" + btw 0 → verlegd-tarief oranje; winnaarsvolgorde btw mens > factuur berekend > geheugen > factuur verlegd > default > leeg (`regel_prefill.py`); chips één regel, kolomminima 184/168/200, verplichte velden geaggregeerd — zie BESLISSINGEN "CONTROLESCHERM SPOT SERVICES 2026-608".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Factuurperiode op weekniveau — datalaag (blok 11 vervolgrun 07-09; migratie 0120):** AI-veld `periode` (sentinel) deterministisch genormaliseerd naar ISO-week(s) (`app/documenten/periode.py`, weeklogica uit `app/uren`), terugval = week van de factuurdatum, kolommen op `boekvoorstel`, chip "Periode (weken)" met herkomst in het controlescherm (mens wint), niet-blokkerend signaal in de factuurmatch; GEEN weekweergave van kosten per project (schermimpact → mockup) — zie BESLISSINGEN "FACTUURPERIODE WEEKNIVEAU — DATALAAG".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Periode-backfill (blok 7 bundel 08-09):** CLI `periode-backfill [--dry-run] [--administratie] [--alle-statussen]` vult de 0120-kolommen van geboekte documenten deterministisch (AI-veld → terugval factuurdatum, mens wint, tijdlijn + audit, idempotent; `app/documenten/periode_backfill.py`) — zie BESLISSINGEN "PERIODE-BACKFILL".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Vragenworkflow**: vraag blokkeert boeken, toegewezen aan eigenaar per administratie, antwoord
  voedt het geheugen. Vragen zijn een status in de werkvoorraad (geen apart menu).
  **DIALOOG-model (besluit Peter 25-08, migratie 0064): een vraag is een thread; blokkeert boeken tot "Afgehandeld"
  door de oorspronkelijke vraagsteller.** Vraag aan de klant-accordeur (26-08 blok B5, migratie 0079). Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt B + "GECOMBINEERDE RUN 26-08" blok B.
  **Dialoog open tot Afgehandeld (Peter 16-09, casus Barbara → Sophia; geen migratie):** geen beurt-regel meer — beide kanten
  plaatsen zoveel berichten als nodig (de gate zat alleen in de accordeur-app-UI), status afgeleid uit het laatste bericht
  (`laatste_bericht_door/_op`), kantoor mag "namens" afhandelen (audit `vraag_afgehandeld_namens`), afgehandeld → "Heropenen"
  (`POST …/vragen/{id}/heropenen`), meldingen gebundeld ("N nieuwe berichten", 10-min-venster per beurt), werkvoorraad-groepen op de
  afgeleide kant (klant aan zet = wachten, kantoor aan zet = standaardlijst) — zie BESLISSINGEN "VRAGEN-DIALOOG OPEN TOT AFGEHANDELD (Peter 16-09)".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Leeg = doorlopen — toewijzing optioneel (blok 2 herstelrun 07-09; migratie 0121):** geen eigenaar/toegewezene houdt geen automatisering meer tegen (afwijzen, vragen, duplicaat-afvoer, autovraag, verplaatsen → `toegewezen_aan = NULL`, kantoorbreed zichtbaar als "niet toegewezen"; `GeenToewijzingMogelijk` vervallen); guard `tests/unit/test_optin_afwezig_pad_guard.py` + marker `afwezig_pad` per opt-in — zie BESLISSINGEN "LEEG = DOORLOPEN — TOEWIJZING OPTIONEEL".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Afwijzen** = verplichte reden, blijft zichtbaar ("Afgewezen — ter controle").

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Zoeken**: globaal over boekingen (incl. archief + RLZ-boekstuk + PDF), accorderingshistorie — GEBOUWD + GETEST
  (2026-08-09), `backend/app/zoeken/` + `frontend/src/zoeken/`, scope-veilig (RLS + server-side), bewust geen nieuwe
  AI-calls; tijdlijn per boeking. Zie mockup #zoeken.

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Archief**: geboekte documenten 7 jaar terugvindbaar met PDF (bewaarplicht).

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Kalenderdag = Nederlandse dag (blok 2 run 11-09 middag; middernacht-flake 10/11-09; geen migratie):** geldigheids-, verval-, factuur-, boek- en periodedatums én dagtellers zijn NL-kalenderdagen via het ene anker `app/tijd.py` (`vandaag_nl()`, `kalenderdag_nl()`, monkeypatch `_klok`); tijdstempels blijven `datetime.now(UTC)` zonder `.date()`; 66 call-sites gesweept, guard `tests/unit/test_kalenderdag_guard.py` (whitelist leeg), gouden set pint `_klok` op `REFERENTIE_TIJDSTIP` — zie BESLISSINGEN "KALENDERDAG = NEDERLANDSE DAG".

<!-- uit CLAUDE.md § Domeinbeslissingen -->
- **Beginscherm kantoor-web set-based + tellers-cache (blok 6 run 11-09 middag; kliktest Peter 11-09, 71 administraties; migratie 0136):** `GET /werkvoorraad/overzicht` leest de tellers-cache `werkvoorraad_teller_cache` in ÉÉN statement over de hele scope (`app/werkvoorraad/tellers.py::lees_voor_scope`, RLS-policy met actor-scope; N=5 = N=200 = 3 statements, meetlat `tests/werkvoorraad/test_tellers_querytelling.py`), cache incrementeel via `_schrijf_overgang`/aanmaak/vragen/spiegel-hooks, nachtelijk herrekend in `sync-alles` (CLI `werkvoorraad-tellers-herrekenen`, `--dry-run` in de nameting-allowlist), fail-safe bij ontbreken, reconciliatie-LET-OP `werkvoorraad_tellers`; `spiegel_taken` server-side in de rij (de 71 losse spiegel-taken-calls zijn weg), lijst rendert vóór het bank-overzicht mét skeleton — zie BESLISSINGEN "BEGINSCHERM KANTOOR-WEB — SET-BASED + TELLERS-CACHE (blok 6 run 11-09 middag)".

<!-- toegevoegd 18-09-2026, opdracht "klein-zoekveld-klantenlijst-en-planning-dagkop-sticky" -->
- **Zoekveld op de klantenlijst (Peter 18-09 "graag zoekveld bij administraties, zodat je niet de hele lijst door hoeft te
  scrollen"; geen migratie; BESLISSINGEN "ZOEKVELD KLANTENLIJST + STICKY DAGKOP PLANNING (Peter 18-09)"):** Werkvoorraad ›
  Overzicht per klant draagt links van het Groep-filter een zoekveld (`werkvoorraad/klantZoek.ts`): client-side over de rijen
  uit de tellers-cache-respons (géén server-call), op administratienaam én groepsnaam, diakriet-loos en hoofdletter-ongevoelig
  (dezelfde `normaliseerTekst` als `bankZoek.ts`), elke spatie-gescheiden term moet treffen; teller "N van M" (M = klanten mét
  werk), `/` focust het veld (binding uit `document/sneltoetsen.ts`, nooit vanuit een invoerveld), leeg = alles; de term staat in
  de URL (`?zoek=`, deeplink wint) en wordt per browsersessie onthouden (sessionStorage `werkvoorraad-klantzoek`); lege uitkomst =
  melding mét "wis het zoekveld" (nooit een lege tabel zonder uitleg). Het Groep-filter blijft server-side en werkt eronder samen.
  Guard `werkvoorraad/klantZoek.test.tsx`; overflow-sweep harness-werkvoorraad groen.

<!-- toegevoegd 18-09-2026, opdracht "btw-bedrag-volgt-tarief-harde-check" -->
- **Controlescherm — check-rij mét acties + btw volgt het tarief (Peter 18-09, casus Rituals 88-186308; migratie 0163; BESLISSINGEN
  "BTW-BEDRAG VOLGT HET TARIEF + BUA + KEUZELIJST NL-EERST (Peter 18-09)"):** een blokkerende check-rij mag handelingen dragen
  (`CheckResultaatDto.acties`, `btn secondary` onder de melding in de controles-tabel; "signalering zonder handeling is niet af") — eerste
  afnemer "Btw-bedrag past bij tarief" mét "Btw in kosten (0 %)" en "Zet N %"; de knop past de regelstate aan, de autosave + checks
  draaien opnieuw, de server blijft de poort. De tariefkeuze op een regel herrekent het btw-bedrag ALTIJD (ook een handmatig getypt
  bedrag; 0 % op een regel mét btw = btw in de kosten, chip "btw in kosten (niet aftrekbaar)"); de grijze hint "tarief geeft € … —
  factuur leidend" (REGELRIJ-UI 25-08 (b)) bestaat niet meer. De crediteur-kaart toont het afgeleide leverancier-land ("NL · uit
  btw-nummer factuur") en de btw-combobox toont bij NL alleen de NL-codes mét "Buitenland-tarieven tonen (N)" onderaan — volledige
  tekst in `docs/regels/btw.md`.

<!-- toegevoegd 18-09-2026, opdracht "BUG-samenvoegen-toont-gesplitste-regels-en-geheugen-overschrijft-factuurbtw" -->
- **Samenvoegen-modus volgt de data + regel-btw uit de factuurkolom + pinbon-totaal (BUG Peter 18-09 "hij splitst nu per
  regel zonder het vinkje?", casus Zilver Horeca Fac-25-022711, BLOW; geen migratie; BESLISSINGEN "SAMENVOEGEN-BUG, REGEL-BTW
  UIT DE FACTUURKOLOM EN UPLOAD 409 'AL AANWEZIG' (Peter 18-09)"):** (1) **Eén waarheid voor de modus.** De leesroute
  (`boekvoorstel._lees_opgeslagen_voorstel`) laat `regels_samenvoegen` de OPGESLAGEN data volgen: zegt de leverancier-voorkeur
  "samenvoegen" maar staan er > 1 regel opgeslagen (de A10-autosave persisteert de gesplitste set als er geen samengevoegde
  variant te berekenen is — geen totalen, regels zonder bedrag; of de mens sloeg losse regels op), dan is `regels_samenvoegen`
  False en `regels_modus_hersteld` True; het openen van het controlescherm schrijft één tijdlijnregel "weergave hersteld: N
  opgeslagen regels, modus stond op samengevoegd" (`registreer_modus_herstel`, idempotent per document × N, systeem-actor). Het
  scherm toont vinkje, hint ("Losse factuurregels") en tabel uit dezelfde stand mét chip "weergave hersteld" en heeft een tweede
  grendel: bij > 1 opgeslagen regels is `dto.regels` nooit de samengevoegde variant. Nooit stil de data wegdrukken, nooit de
  modus liegen. Productie 18-09: c73e7590 (BLOW) had 21 gesplitste regels gepersisteerd (autosave 12:10, snapshot
  `regels_samenvoegen: false`) onder voorkeur `true`. (2) **Factuur-btw per regel wint van het geheugen.** De extractie leest de
  btw-KOLOM van de regel voor (`bc`: "9%", "0%", "V"); `controle.parse_btw_kolom_percentage` + `leid_btw_af_uit_kolom` matchen
  het percentage exact op de gesyncte tarieven (verlegd/vrijgesteld/gemengd doen niet mee; favoriet wint bij twee codes met
  hetzelfde percentage) zodra netto × tarief ≈ btw niets oplevert → `btw_bron='factuur_regel'` (chip "factuur 0 %"),
  `btw_afleiding_basis='kolom'`, regel-btw = netto × p (`btw_bedrag_berekend`). Een factuurkolom **0 % IS de basis**
  (Emballage/statiegeld → "NL, Nul tarief"), nooit verlegd of vrijgesteld raden; zonder kolom blijft de bestaande regel "0 %
  zonder basis = leeg". Het leverancier-/regel-geheugen vult uitsluitend een lege btw en levert hier alleen het grootboek. Het
  kolom-percentage reist als `factuur_btw_percentage` mee (DTO, prefill-snapshot, opgeslagen regel). (3) **Bruto/netto per regel
  uit de factuur:** de bruto-kolom rekent netto × (1 + factuur-regeltarief) zolang de mens de btw-code niet zelf koos — nooit
  netto × geheugen-tarief (10,80 → 11,77 was fout). (4) **Totaal uit de pinbon:** kop-veld `pt` (sentinel) = het totaal van een
  meegefotografeerde pin-/kassabon; code toetst `toets_pinbon_totaal`: bon = Σ(netto + btw) van álle regels binnen 5 ct →
  `totaal_incl` := bon, `totaal_bron='pinbon'`, chip groen "uit pinbon"; regels zonder bedrag → `niet_toetsbaar`, som sluit niet
  → `afwijkend`: oranje chip "pinbon zegt € X — …", het totaalveld blijft leeg, de mens beslist. Een gelezen factuurtotaal wint
  altijd (`totaal_bron='factuur'`). (5) **Afgedekt/onleesbaar bedrag:** regel-veld `ng` ("afgedekt"/"onleesbaar") →
  `bedrag_niet_gelezen` + chip "niet gelezen (afgedekt)" i.p.v. een kale lege cel; de btw-code uit de kolom staat wél klaar, een
  bedrag wordt nooit geraden. Guards: `tests/extractie/test_controle_kolom_pinbon_18_09.py`,
  `tests/documenten/test_regel_prefill_factuur_regel_18_09.py`, gouden-set-casus **ae**
  (`tests/keten/test_ae_zilver_horeca_regelkolom.py`, fixtures `ae_zilver_horeca_regelkolom`, stamgegevens + "NL, Laag tarief"
  en "NL, Nul tarief"), vitest `BoekvoorstelPanel.modus18.test.tsx`. Telling productie 18-09 (lees-only, per administratie):
  werkvoorraad-documenten met > 1 opgeslagen regel onder voorkeur/default "samenvoegen": BLOW 1 (de casus), Camping
  "Nieuwenhoven" 3 (geen voorkeur, RLZ-default aan) — de leesroute herstelt ze bij het openen; Universal Steigerbouw 7 zijn Odoo
  (default gesplitst) en dus consistent.

<!-- toegevoegd 18-09-2026, opdracht "boeken-sneller-checks-en-doorloop" -->
- **Boeken sneller — checks lokaal/extern, `wordt_geboekt` + achtergrond-schrijver, doorloop zonder omweg (Peter 18-09
  letterlijk: "als ik nu een factuur boek duurt het lang voordat alle controles groen worden (4 à 5 seconden). Als ik daarna
  druk op Boeken in RLZ duurt het weer 4 à 5 seconden voordat ik bij de volgende boeking terecht kom. Vooral deze stap moet
  sneller: meteen weg (backend draait rustig door) en mij de volgende boeking binnen een seconde geven."; migratie 0165 =
  PG-enumwaarde `wordt_geboekt` + `boekhouding.check_extern_cache` + `boekhouding.boek_wachtrij_claim`; BESLISSINGEN "BOEKEN
  SNELLER — CHECKS-CACHE + ACHTERGROND-SCHRIJVER (Peter 18-09)"):** (1) **Checks in twee delen.** LOKAAL (verplichte velden,
  afdeling, betaalstatus, projectverdeling, regeltelling, btw-bedrag past bij tarief, vervaldatum, buitenland-tarief, IBAN-wissel
  tegen de opgeslagen set, module-duplicaat) draait synchroon bij élke opslag; EXTERN (IBAN-seed uit RLZ-BankRelations, RLZ-/Odoo-
  duplicaatquery mét kandidaten ± 60 d, duplicaat over crediteuren heen — `app/documenten/checks_extern.py`) draait PARALLEL
  (ThreadPool, één RlzClient) en alleen als de EXTERNE VINGERAFDRUK verandert: crediteur + identiteitscluster, referentie
  genormaliseerd, factuurdatum, totaalbedrag, factuur-IBAN, boek_cyclus, backend. Omschrijving, grootboek, project en btw-code
  wijzigen start géén externe run. Het externe rapport is persistent (`check_extern_cache`, één rij per document) en geldig zolang
  de vingerafdruk gelijk is én de run ≤ `CHECKS_EXTERN_CACHE_MINUTEN` (15) oud is; de check-rijen tonen "gecontroleerd HH:MM"
  (uit de cache = "(ongewijzigd)") en "Loopt…" zolang de externe run bezig is. Een storing (verbinding, RLZ-fout in de
  duplicaatquery) wordt NOOIT gecachet. `PUT …/boekvoorstel?checks=lokaal` = het snelle pad (externe rijen uit de cache of
  "loopt nog", blokkerend); `POST …/boekvoorstel/checks?extern=auto|vers|cache`. Frontend `useAutoChecks`: debounce 400 ms,
  `checksBezig` gesplitst in lokaal/extern. (2) **Boeken = direct door.** `POST …/boeken` doet standaard alleen het SYNCHRONE deel
  (statusmachine, klant-accorderingspoort, factuurmatch-/materiaalmatch-bevestiging — alle 409's blijven synchroon —, de harde
  checks mét het externe rapport uit de cache als de vingerafdruk gelijk is en ≤ 15 min, anders deze ene keer wél synchroon
  extern; nooit stil overslaan; boeken-toggle, volumerem) en antwoordt **202 `wordt_geboekt`** mét `volgende_document_id` +
  `volgende_document_soort` — de server kiest het volgende document met exact de `kiesVolgendDocument`-regels (positie in de
  GETOONDE lijstvolgorde uit `lijst_volgorde` in de body, cyclisch, alleen verwerkbare statussen, statussen vers uit de
  database; zonder lijst = backend-volgorde nieuwste eerst). `?direct=1` = het synchrone pad van vóór 18-09 (herstel/tests).
  Nieuwe status **`wordt_geboekt`** (tussen klaar_om_te_boeken en geboekt; uitgangen → geboekt, → boeken_mislukt; óók vanuit
  boeken_mislukt via "Opnieuw"): niet bewerkbaar, niet verwijderbaar, niet nog eens in te dienen (409), wél te bekijken; telt in de
  standaardlijst (kantoorwerk) en in de tellers-bucket "klaar om te boeken"; lijstlabel "Wordt geboekt…" (grijs, pulserende dot,
  lijst pollt elke 3 s) → "Geboekt · boekstuk" of rood "Boeken mislukt — reden" mét toast in dezelfde administratie. (3)
  **Achtergrond-schrijver** `app/documenten/boek_wachtrij.py`: de worker doet exact het bestaande `boek_document` (client-GUID +
  eigen duplicaatquery vóór de PUT, PUT + Upload + actie 17 + GET, DB-afwikkeling in één transactie, post-commit-stappen) plús de
  klaargezette doorbelasting en de webhook (via `orkestratie.boek_document_met_doorbelasting`), mét de bij het indienen
  vastgelegde actor en bevestigingsvlaggen; élke fout = zichtbaar `boeken_mislukt` mét reden (principe 4: rode rij + toast, geen
  pop-up). Idempotency-key `boek-{document_id}-{boek_cyclus}` (`boek_wachtrij_claim`): twee verwerkers pakken nooit dezelfde
  boeking; de RLZ-adapter hervat idempotent (GET op het GUID — al geboekt = niets opnieuw schrijven, alleen het boekstuknummer);
  een claim mét uitkomst 'mislukt' blokkeert "Opnieuw" niet, 'geboekt' is definitief. Cloud = het bestaande job-triggerpatroon:
  on-demand job **`rlz-boek-wachtrij`** (CLI `boek-wachtrij-verwerken`, `BOEK_WACHTRIJ_JOB_RESOURCE`) + scheduler-vangnet elke
  2 min; Cloud Tasks is bewust NIET gekozen (nieuwe dependency + queue/IAM/OIDC-route, in deze run niet live te bewijzen; het
  job-patroon werkt aantoonbaar sinds 26-08). Dev/tests = in-process thread / directe wachtrij. Vangnetten: startup + job
  hervatten élk document dat > `BOEK_WACHTRIJ_HERSTEL_MINUTEN` (10) op wordt_geboekt staat; reconciliatie-bevinding
  `wordt_geboekt_verouderd` (blok documenten, start in `meten`, actie "Opnieuw proberen" = deeplink naar het document);
  dagtellers in de reconciliatiemail (automatisering `boek_wachtrij`: ingediend/geboekt/mislukt + LET-OP vangnet scheduler bij
  een mislukte trigger). Het autoboek-pad en de accordering-staande-goedkeuring gebruiken dezelfde schrijfroute
  (`boek_document`) zonder 202-shortcut — zij draaien al in een achtergrondproces. (4) **Doorloop.** `naVerwerking` gebruikt
  `volgende_document_id` uit het 202-antwoord (route uit `volgende_document_soort`), anders de al geladen lijst
  (`positie.volgende`/`kiesVolgendDocument` zonder fetch), pas dán de lijst ophalen; het detail van het volgende document wordt
  geprefetcht (cache 60 s, één keer gebruikt) én zijn externe checks worden **voorverwarmd**
  (`POST …/boekvoorstel/checks?voorverwarm=1`: alleen extern + cache, max 1 tegelijk per proces, setting `CHECKS_VOORVERWARMEN`
  default AAN; uit/bezet = zichtbaar in de reconciliatiemail als automatisering `checks_voorverwarmen`, nooit stil).
  (5) **Server-Timing** (stap 0): de checks- en boek-routes dragen `Server-Timing` (`checks.lokaal`, `checks.cache`,
  `checks.extern`, `checks.ibanseed`, `checks.duplicaat`, `checks.kandidaten`, `boek.db`, `boek.volgende`; de worker logt
  `boek.rlz`/`boek.db` in `boek_wachtrij_afgerond.stappen_ms`) + gestructureerde logregel `server_timing` — het meetrecept
  voor de nameting. Nulmeting productie 18-09 (request-log vóór de fix): checks p50 0,79 s / p95 2,14 s (n=51); boeken p50 2,65 s /
  p95 3,42 s (n=24, waarvan 4× 429 volumerem). Doelmeting: klik → volgende document ≤ 1 s (p95), externe rijen ≤ 1,5 s bij
  voorverwarmd, RLZ-boeking gereed in de lijst ≤ 15 s (p95).

## Historie — op 07-09-2026 uit CLAUDE.md naar BESLISSINGEN verplaatst (kopie; BESLISSINGEN "VERPLAATST UIT CLAUDE.md (07-09-2026)" blijft de historische vindplaats)

### Domeinbeslissingen — Na boeken direct door, lijstcontext, sneltoetsen, actiebalk, boekingsregels-kolommen (CLAUDE.md `ed6d176` r. 271–294)

- **Na boeken direct door (besluit Peter 25-08, deel 4 punt 1, GEBOUWD):** ná boeken/"Boeken +
  doorbelasten"/afwijzen/ter accordering toont het controlescherm een toast (referentie +
  boekstuknummer) en opent automatisch het volgende te-verwerken document van dezelfde klant
  (zelfde soort eerst, dan de soort-tab-volgorde; `werkvoorraad/volgendDocument.ts`); stapel
  leeg → documentenlijst van de klant. Uitzondering: ter accordering mét `boek_fout` blijft staan.
  **Lijstcontext reist mee (werkstroom-run 27/28-08, punt 1): soort-tab + status-filter + zoekterm
  van de documentenlijst staan in de URL (`soort=/status=/q=`) en reizen mee naar het inkoop-
  controlescherm — de doorloop blijft BINNEN het actieve filter (`kiesVolgendDocument(…, context)`),
  de topbar toont ‹ › mét "n van m", Esc/"← Werkvoorraad" gaan terug mét filter; élke kolom-teller in
  "Overzicht per klant" opent de lijst voorgefilterd; één filterbron `werkvoorraad/lijstContext.ts`.
  **Binnenkomst-default = "Te controleren" (wens Peter 01-09): zonder `status=`/`soort=` in de URL
  opent de lijst op het werk — expliciete status in de URL wint altijd, niets te controleren =
  terugval "Alle" (nooit leeg), tab-klik houdt de bestaande status-reset; BESLISSINGEN
  "GECOMBINEERDE RUN 01-09" blok D.**
  Sneltoetsen (punt 5): B = actieve besluitknop, A = afwijzen, ←/→, Esc, ? = overzicht, / = zoekveld —
  alleen buiten invoervelden/dialogen (`document/sneltoetsen.ts`). Onopgeslagen (debounce loopt) →
  bevestiging vóór verlaten. BESLISSINGEN "WERKSTROOM- + UI-RUN 27/28-08".**
  **Actiebalk (Afwijzen / Vraag stellen / Ter accordering / Boeken, ± doorbelasten) staat sinds
  27-08 ÓNDER het blok "Doorbelasten na boeken"** (portal-anker `actiebalkDoel`, alleen volgorde
  — BESLISSINGEN "VERZAMELRUN 27-08" punt 4). **Boekingsregels-tabel: kolomminima in px uit één bron
  (`document/boekingsregelsKolommen.ts`, tabel-min-width = de som; te smal paneel = horizontale
  scroll in `.tabel-scroll`, omschrijving wrapt op woordgrenzen — nooit meer per letter; eigen
  regressietests náást de overflow-sweep, die kolom-implosie niet ziet — BESLISSINGEN
  "KANTOOR-MINI-RUN 27-08" punt 4).**

### Domeinbeslissingen — Vervaldatum inkoopfactuur (CLAUDE.md `ed6d176` r. 367–373)

- **Vervaldatum inkoopfactuur (C1 gecombineerde run 26-08, migratie 0078):** kopveld
  `boekvoorstel.vervaldatum` uit de scan (herkomst-chip), harde check "Vervaldatum" (vóór
  factuurdatum = blokkerend; leeg mag), oranje signaal > 90 dagen (geen blokkade), naar RLZ als
  `DueDate` (live geverifieerd — zonder DueDate leidt RLZ 'm af uit Date + PaymentDueDays). De
  documentenlijst-kolom "Toegewezen" toont bij `ter_accordering` de accordeur die aan de beurt is
  (naam · laag, C2); de regelsom-badge op het veldvoorstel gebruikt exact de netto+btw=incl-logica
  van de boekingsregels-toets (C3). Zie BESLISSINGEN "GECOMBINEERDE RUN 26-08" blok C.

### Domeinbeslissingen — Vragenworkflow (dialoog-model, vraag aan de klant-accordeur) (CLAUDE.md `ed6d176` r. 481–492)

- **Vragenworkflow**: vraag blokkeert boeken, toegewezen aan eigenaar per administratie, antwoord
  voedt het geheugen. Vragen zijn een status in de werkvoorraad (geen apart menu).
  **DIALOOG (besluit Peter 25-08, migratie 0064 — herziet het één-antwoord-model van 14-07):**
  een vraag is een thread (append-only `vraag_bericht`, auteur + tijdstip per bijdrage, onbeperkt
  heen en weer; `aan_de_beurt` stuurt de bestaande melding `Document.toegewezen_aan`); de vraag
  blokkeert boeken tot **"Afgehandeld" door de oorspronkelijke vraagsteller** (server 403 voor
  anderen; systeem-vraag → toegewezene) — niet al bij het eerste antwoord. Controlescherm:
  tabs "Tijdlijn" (statusgebeurtenissen) en "Opmerkingen" (de threads, nieuwste onderaan). Zie
  BESLISSINGEN "RLZ-FEEDBACKRONDE 25-08" punt B. **Vraag aan de klant-accordeur (26-08 blok B5,
  migratie 0079): toewijzen aan een accordeur = thread in de app (alleen eigen vragen zichtbaar),
  geen statusovergang op ter_accordering/geboekt, akkoord mogelijk, boeken wacht — zie
  "Accordeur-app-ronde 26-08" hieronder.**

### Domeinbeslissingen — Zoeken (CLAUDE.md `ed6d176` r. 1362–1369)

- **Zoeken**: globaal over boekingen (incl. archief + RLZ-boekstuk + PDF), accorderingshistorie
  — **GEBOUWD + GETEST (2026-08-09)**: `backend/app/zoeken/` + `frontend/src/zoeken/`,
  scope-veilig per administratie (RLS + server-side), doorzoekt kopgegevens + lokaal
  aanwezige extractietekst (veldvoorstel — bewust geen nieuwe AI-calls), vragen en
  accorderingshistorie inline, audit-sectie conform mockup #zoeken. Zie hieronder;
  archiefweergave per administratie idem gebouwd.
  inline, vragen, audit. **Tijdlijn** per boeking (binnenkomst → extractie → vraag → accordering →
  boeking, met datum+tijd).

### Referenties — controlescherm-v2 / doorbelasten-blok-v2 / bank-voorstel-kaart (bouwnorm 02-09 + aanvullingen 03-09/04-09) (CLAUDE.md `ed6d176` r. 1531–1550)

- `mockup/controlescherm-v2.html` + `mockup/doorbelasten-blok-v2.html` + `mockup/bank-voorstel-kaart.html`
  (iteratie 2) — **bouwnorm 02-09 (akkoorden Peter 02-09, ontwerpnotities incl.; GEBOUWD 02-09,
  BESLISSINGEN "UX-/INTAKE-VERBETER-RUN 02-09" + "UX-PATRONEN ALS NORM"):** controlescherm in
  werkvolgorde mét checks onzichtbaar-tot-relevant, sticky actiebalk, crediteur-kaart mét
  KvK-mismatch-guard + "+ Nieuwe crediteur in RLZ"; doorbelasten-blok mét restant-balk, %↔bedrag,
  één sleutel-menu, auto-opslaan; bankscherm mét chip "handmatig" + één primaire knop + ⋯-menu.
  Nieuwe schermen volgen de vastgelegde UX-patronen (voorstel-kaart, restant-balk, lege stand = actie,
  één primaire knop + ⋯, werkvolgorde-regel, bundelen vóór tonen).
  **Aanvulling 03-09 (blok D, screenshot Peter): "+ Doelentiteit" = dezelfde `btn secondary` als "+ Regel
  toevoegen"; `.linkbtn` heeft sinds 03-09 een BASISSTIJL (tekstactie in teal) — daarvóór viel élke linkbtn
  buiten `.userbox`/`.rijmenu` terug op de grijze browser-default. Een tekstknop = `linkbtn`, een echte knop =
  `btn`/`btn secondary`; nooit een kale `<button>`. BESLISSINGEN "MINI-RUN 03-09 (2)" rij D.**
  **Aanvulling 04-09 (blok C, besluiten Peter): (C1) een "kies één van twee/drie"-stap in een wizard = `KeuzeKaarten` (hele kaart klikvlak,
  geselecteerd = teal rand + accent-vulling, native radio blijft erin); radio's erven sinds 04-09 nergens meer de `input{width:100%}`-regel.
  (C2) PDF-`<object>`-viewers openen via `document/pdfWeergaveUrl.ts::metViewerOpties` (`#pagemode=none&navpanes=0&view=FitH`) zónder
  miniaturen-zijbalk, ☰ blijft; nooit `toolbar=0`. (C3) `SearchableCombobox` kent een `voetActie` (vaste onderste rij buiten het
  virtualisatievenster); de project-kolom en de projectverdeling dragen "+ Nieuw project aanmaken…" → `projecten/NieuwProjectModal` (bestaande
  RLZ-projectmotor; ná aanmaken direct geselecteerd); projecten AANMAKEN mag élke kantoorrol incl. Boekhouding (`app/projecten/kantoor.py::
  _vereis_aanmaakrol`, frontend-spiegel `auth/rollen.ts::magProjectAanmaken`), overige projectmutaties blijven Beheerder + B+P. BESLISSINGEN
  "UI-FIXES 04-09 BLOK C".**
