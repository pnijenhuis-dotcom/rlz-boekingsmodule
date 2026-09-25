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

<!-- toegevoegd 24-09-2026, opdracht "bundelrun-zeven-punten" blok 7b (BUG 23-09 samenvoegen-vinkje) -->
- **Samenvoegen — bron = opgeslagen regels, nooit stil weg (BUG Peter 23-09 "bij boeking van inkoop is vinkje samenvoegen ineens
  weg?", casus BLOW Van Rumpt 2025135 € 1.277,50, document 3405157f…: 7 opgeslagen regels mét netto/bruto, scan zonder
  regelbedragen → `samengevoegde_regel` null → geen vinkje; geen migratie; BESLISSINGEN "SAMENVOEGEN — BRON = OPGESLAGEN REGELS,
  NOOIT STIL WEG (23-09)"):** `_samengevoegde_regel` heeft sinds 24-09 een tweede bron: staan er ≥ 2 OPGESLAGEN regels
  (`boekvoorstel_regel`), dan berekent `boekvoorstel._samengevoegde_regel_uit_opgeslagen` de één-regel-variant uit díe regels —
  Σ netto, Σ btw-bedrag (een lege regel-btw wordt cent-exact uit het tarief van die regel afgeleid via `regelsom.btw_uit_tarief`;
  geen percentage in de `taxrate_cache` = niet berekenbaar), één btw-code als alle regels dezelfde dragen (anders géén samenvoegen
  mét reden "verschillende btw-codes"), grootboek alleen als alle regels hetzelfde dragen, omschrijving "Factuur ‹nr› — samengevoegd
  (N regels)". De scan-uitkomst (`veldvoorstel`) blijft de bron zonder of bij één opgeslagen regel. **Niets verdwijnt stil:** kan er
  bij > 1 regel niet worden samengevoegd, dan draagt de boekvoorstel-response `samenvoegen_niet_mogelijk_reden` (ook "regelbedragen uit
  de scan onvolledig" op het prefill-pad) en toont het controlescherm de chip "samenvoegen niet mogelijk: ‹reden›" i.p.v. het vinkje
  weg te laten; zodra de server een variant meegeeft staat het vinkje er weer. De regelsom-check (Σ = factuurtotaal) blijft de poort;
  dit raakt uitsluitend de weergave-/boekvorm. Guards `tests/documenten/test_boekvoorstel_samenvoegen_23_09.py`, vitest
  `BoekvoorstelPanel.samenvoegen23.test.tsx`, keten-casus ae (projectplicht → veld None, geen chip). Werkt in productie: niet gemeten
  (klikpunt Peter: document 3405157f… openen ná deploy → vinkje terug).

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

<!-- toegevoegd 24-09-2026, opdracht "bundelrun-zeven-punten" blok 7a (BUG 23-09 vraag-thread → kassarapport in inkoopscherm) -->
- **Documentlink volgt de soort — één routefunctie, redirect op het inkoop-controlescherm (BUG Peter 23-09, casus Van Boxtel Horeca
  Exploitatie `Journaal 19-9.pdf` e7d89765-c4f5-42f3-82d9-71f8a11f5f7f, kassarapport mét open vraag "stel op het omzetreview-scherm …":
  de knop in de vraag-thread opende het INKOOP-controlescherm met een leeg crediteurformulier; geen migratie; BESLISSINGEN "DOCUMENTLINK
  VOLGT DE SOORT — VRAAG-THREAD OPENDE KASSARAPPORT IN INKOOPSCHERM (23-09)"):** (1) **Eén bron voor "open dit document"** =
  `frontend/src/werkvoorraad/format.ts::documentPad(administratieId, {id, soort?, status?}, context?)`: kassarapport → `/omzet/…`,
  verkoopfactuur → `/verkoop/…`, waarborg → `/waarborg/…`, verplichting → `/verplichting/…`, een open vraag (`vraag_open`, niet
  verwijderd) → de vráág op de klantpagina, al het andere én een onbekende soort → het inkoop-controlescherm (alleen dáár reist de
  lijstcontext mee). `documentRoute`, `zoeken/reviewPad` en `materiaal/miniVoorraadApi.documentPad` zijn dunne lagen erop; nergens
  anders in `frontend/src` staat nog een letterlijke `` `/documenten/${…}` ``-link (guard `werkvoorraad/documentPad.guard.test.ts`;
  API-paden `/administraties/…/documenten/…` zijn geen links). Server-spiegel `app/documenten/deeplink.py::document_pad(administratie_id,
  document_id, soort, status)` — `corrigeren.review_pad` en `rls_weigering.doel_pad_voor_route` lopen erlangs; guard
  `tests/unit/test_documentlink_deeplink_guard.py`. (2) **De DTO's dragen de soort:** `VraagResponse.document_soort`,
  `OpenVraagRijDto.document_soort` (default `inkoopfactuur`; frontend optioneel → oud antwoord = inkoop). (3) **Redirect-grendel:** opent
  iemand `/documenten/<adm>/<id>` van een document mét een eigen reviewscherm (oude link, mail, getypte URL, duplicaat-/tegenboek-
  verwijzing zonder soort), dan stuurt `DocumentDetailScreen` ná het laden door naar het juiste scherm — nooit een leeg inkoopformulier
  voor een niet-inkoopdocument. (4) **Copy:** de thread-knop heet "Document bekijken" en volgt de soort; bij soort kassarapport óf een
  vraag-tekst die naar het omzetreview-scherm verwijst staat er "Naar omzetreview →" (`btn secondary`) naast. Gouden set:
  `tests/keten/test_lijst_standaard_en_wachten.py::TestDocumentlinkVolgtDeSoort` (de Floor-vraag draagt `document_soort`, de spiegel
  kiest het pad). Werkt in productie: niet gemeten (meetrecept in het rapport `2026-09-24-bundelrun-zeven-punten.md`).

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 3 -->
- **Controlescherm — projectveld volgt de bronvolgorde factuur > cachecode > historie (Peter 25-09, FV-02):** het projectveld draagt
  sinds 25-09 altijd zijn herkomst als chip: "uit factuur" (groen), "uit factuur, nog niet bevestigd" (oranje), "voorstel uit historie"
  (oranje, geheugen als laatste bron — nooit meer stil gevuld), "factuur noemt een ander project — kies zelf" (oranje, leeg: conflict tussen
  factuur en historie) of "factuur noemt een project — meerdere passen, kies"; volledige tekst en motor in
  `docs/regels/verplichtingen-projecten-voorraad.md` alinea "Project-bronvolgorde (Peter 25-09)".

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 5 -->
- **Crediteur-zijpaneel + bewerken vanuit het controlescherm (Peter 25-09; gebruikersfeedback Universal FV-14 "crediteur aanmaken
  zonder zicht op de factuur" + FV-15 "crediteur achteraf aanpassen"; geen migratie; BESLISSINGEN "CREDITEUR AANMAKEN ALS ZIJPANEEL
  NAAST DE FACTUUR + CREDITEUR BEWERKEN (Peter 25-09)"):** (1) "+ Nieuwe crediteur in RLZ" is geen modale dialoog meer maar het
  niet-modale zijpaneel `ui/basis/Zijpaneel` (`document/CrediteurPaneel.tsx`; aside rechts, `role=dialog` `aria-modal=false`, geen
  overlay/scroll-lock/focus-trap, Escape/✕ sluit, focus terug naar de opener) — de factuur links blijft leesbaar en scrollbaar. Velden
  naam · KvK · btw-nummer · IBAN · adres (straat/postcode/plaats/land als vrije velden, voorgevuld uit het UBL-adres `leverancier_adres`,
  anders leeg — géén nieuw AI-veld), chips "uit factuur"/"uit UBL" per veld; opslaan = de bestaande Vendor-PUT (`POST …/crediteuren`, nu
  mét `adres`). Ontbrekend IBAN = waarschuwing "geen IBAN vastgelegd — incasso of buitenland? … via de IBAN-route (vier ogen)", nooit
  een blokkade. (2) Crediteur-kaart draagt bij een gekozen crediteur de `linkbtn` "Gegevens bewerken…" → hetzelfde paneel in bewerk-modus
  (`GET /administraties/{id}/crediteuren/{vendor_id}`: naam, KvK, btw, adres, vertrouwde IBAN's lees-only, backend) en opslaan via
  `PUT /administraties/{id}/crediteuren/{vendor_id}` (`sync/service.wijzig_crediteur`: zelfde schrijf-failsafe-poort als aanmaken, RLZ
  `put_vendor` op het BESTAANDE id, cache-rij bij, audit `crediteur_gewijzigd` oud→nieuw, melding "bijgewerkt in RLZ · let op: …").
  (3) IBAN's nooit via het bewerk-paneel: de `PUT` kent geen `iban` (422), het paneel toont de vertrouwde set lees-only en "IBAN
  toevoegen/wijzigen → IBAN-route (vier ogen)" opent de bestaande `IbanAanbiedenVorm` inline onder de crediteur-kaart. (4) Adres naar RLZ
  is fail-open (`FullAddress` + `City`; 4xx → PUT zonder adres + zichtbare waarschuwing "adres niet door Reeleezee geaccepteerd"; Odoo =
  waarschuwing "niet naar Odoo geschreven", bewerken op Odoo = 409 "niet ondersteund"). Harnas `harness.html?crediteurpaneel=1` in de
  overflow-sweep; keten-sweep 11/11 zonder nieuwe baseline. Guards: vitest `CrediteurPaneel.test.tsx`, `BoekvoorstelPanel.ubl.test.tsx`;
  backend `tests/sync/test_crediteur_bewerken.py`; keten `test_h_bdo_ubl_zonder_ai.py` (UBL-adresregel). Werkt in productie: niet
  gemeten (dispatch-onderdeel `crediteur-paneel`, meetlat `db-lezen crediteur-mutaties`).

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 8 -->
- **"Open (N)" + een échte "Alles (N)" + server-side zoeken over alles (Peter 25-09, feedbackrun A blok 8 / FV-20 "zoeken onder
  'alle' doorzoekt alleen te controleren — de Exact-factuur op 'wachten op anderen' is niet vindbaar"; geen migratie; BESLISSINGEN
  "DOCUMENTENLIJST — "OPEN (N)" EN EEN ÉCHTE "ALLES (N)" MÉT SERVER-SIDE ZOEKEN (Peter 25-09)"):** (1) het kantoorwerk-filter heet
  "Open (N)" (was "Alle"; semantiek en URL-waarde `alle` ongewijzigd, `status=open` is een synoniem via
  `lijstContext.normaliseerStatusParam`; regel 1 "de standaardlijst is kantoorwerk, Wachten op anderen apart" blijft). (2) "Alles (N)"
  = server-side `groep=alles` (`service.GROEP_ALLES`: kantoor ∪ wachten ∪ afgehandeld, élke status, geen toggles), altijd gepagineerd
  (`limit` default 200 / max 500, `offset`, respons `totaal`/`limit`/`offset`; `tel_documenten` = dezelfde voorwaarden als de lijst),
  N = `groepen.alles`; élke rij mét `StatusChip`, afgehandeld grijs, paginabalk "Rijen a–b van N · ← Vorige 200 · Volgende 200 →"
  (`btn secondary`) alleen bij N > 200; de toggle "Toon afgehandelde documenten" is in die weergave verborgen. (3) Een niet-lege
  zoekterm vanaf binnenkomst, "Open" of "Alles" schakelt de lijst op `groep=alles&q=` (debounce 400 ms; `isAllesWeergave`):
  `_zoek_voorwaarde` = ILIKE over bestandsnaam, vendor-cache-naam/referentie/totaalbedrag-als-tekst van het opgeslagen boekvoorstel
  én `leverancier_naam`/`factuurnummer`/`totaal_incl` van het laatste veldvoorstel in de tijdlijn ("938,06" ≡ "938.06"); geen
  treffer = "Geen documenten gevonden voor … — gezocht over alle statussen", leeg zoekveld = terug naar de gekozen groep; op een
  expliciet gekozen status-/signaaltab blijft de zoekterm bínnen die tab (duplicaat-bulk "Alle N op deze tab"). (4) Zonder
  `groep=alles` zijn `q`/`limit`/`offset` inert en het antwoord byte-gelijk; `_STATUSSEN_PER_GROEP` blijft de drie basisgroepen;
  rolpoort ongewijzigd; doorloop/‹ ›/sortering volgen `status=__alles` als lijstcontext. Guards
  `tests/documenten/test_lijst_alles_paginering.py`, gouden set `test_lijst_standaard_en_wachten.py::TestAllesEnZoeken`, vitest
  `DocumentenDeelscherm.alles.test.tsx`, sweep-variant `harness-werkvoorraad.html?alles=1`. Werkt in productie: niet gemeten
  (dispatch-onderdeel `lijst-alles`: request-log `groep=alles` + `db-lezen documenten-open`).

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 1 (FV-01) -->
- **Bijlage-paneel bij een XML-document — kaart, nooit ruwe XML (Peter 25-09, FV-01; geen migratie; BESLISSINGEN "UBL ZONDER BEELD —
  SAMENVATTINGSKAART I.P.V. RUWE XML, ONLEESBARE XML = HANDMATIG AFMAKEN MÉT REDEN (Peter 25-09)"):** serveert `/bestand` XML (UBL zonder
  PDF-beeld), dan rendert `DocumentDetailScreen` de `UblSamenvattingKaart` (`document/UblSamenvattingKaart.tsx`: chip "uit UBL —
  deterministisch gelezen", kop/partijen/totalen/identiteit/opmerking mét chip "project uit factuur", regeltabel in `.tabel-scroll`) uit
  `GET …/ubl-samenvatting`; de XML-bron staat uitsluitend achter de `linkbtn` "XML-bron tonen" (inklapbaar, standaard dicht). Niet leesbaar
  (`leesbaar=false`, of `onvolledig`) = chip "XML niet leesbaar: ‹reden›" in de kaart én — bij status handmatig_afmaken mét tijdlijn-detail
  `ubl_parse_fout` — dezelfde chip in het paneel "Handmatig afmaken" (`laatsteXmlNietLeesbaar`), zonder "Opnieuw extraheren" (alleen PDF's);
  het paneel en de tijdlijn spreken elkaar nooit tegen. Harnas-casus `a_ubl_zonder_beeld` (`keten_sweep.sh`, fixture-velden `bijlage_xml` +
  `ubl_samenvatting`), vitest `UblSamenvattingKaart.test.tsx` + `DocumentDetailScreen.test.tsx` "XML-bijlage".

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 7 -->
- **Tabwissel documentenlijst — gemeten, fetch per wissel en poll-storm weg (Peter 25-09, FV-18 "scherm loopt vast bij wisselen
  tabblad"; geen migratie; BESLISSINGEN "TABWISSEL DOCUMENTENLIJST — GEMETEN, FETCH PER WISSEL EN POLL-STORM WEG (Peter 25-09)"):**
  (1) **Meten vóór fixen.** Het werkvoorraad-harnas kent `?docs=N` (N gegenereerde documenten, mix zoals Universal Steigerbouw),
  `?tabwissel=K` (de pagina wisselt zelf K × te_controleren ↔ klaar_om_te_boeken en meet klik → gerenderd), `?latency=ms`, `?poll=1`
  (rijen in extractie_wachtrij/wordt_geboekt → de 3-s-poll actief) en `?strict=0`; `frontend/scripts/tabwissel_meting.mjs` drijft
  headless Chrome via CDP mét de échte klok (het overflow-sweep-recept `--virtual-time-budget` is hier onbruikbaar: onder virtuele
  tijd staat `performance.now()` stil tijdens een lange taak). `scripts/tabwissel_meting.sh` = de standaardset (400/2000 documenten,
  latency 300; grens 500/2000 ms per wissel, 0 open fetches, 0 paginafouten). Vóór de fix: 400 rijen max 298 ms/gem 85 ms per wissel,
  2000 rijen max 638/gem 429; 0 lijst-requests per wissel — een tabwissel is client-side. (2) **Wat wél gevonden is:** (a) mét
  klant-accordering aan deed `DocumentenBulkBalk` per tabwissel een `GET /auth/administraties` (mount per wissel; productie tot
  14/min per client) → de balk krijgt de lijst nu van het ouder (`useAdministraties(voorgeladen)`), een tabwissel start NOOIT een
  server-request; (b) de 3-s-poll hing aan `documenten`: élk antwoord herstartte de timer (productie-log 24-09 12:04–12:14: tien
  lijst-requests op rij, 4,1–5,7 s uiteen = 3 s + latency 1,1–2,6 s), tikken stapelden bij een trage server en élk antwoord verving
  de hele lijst (volledige re-render, 95–333 ms per poll bij 400–2000 rijen) → nu een vaste 3-s-tik op een boolean, overslaan zolang
  een request loopt, byte-gelijk antwoord = géén state-update; (c) geen abort: `laadDocumenten` en de vier zij-fetches lopen op een
  `AbortController` (ref; nieuwere lading breekt de oudere af — een trage oudere request overschrijft nooit een nieuwere stand;
  wissel/unmount breekt af; de client-timeout blijft via `maakAfbreker`); (d) `sortering` gememoïseerd op de string-param en tellers
  per status in één `Map` (geen dubbele filter + sort per wissel). Productiefeiten (lees-only): lijstroute Universal Steigerbouw p50
  1,56 s / p95 2,51 s (n = 59, 24–25-09), 219 open documenten. (3) **Niet gedaan (beslispunt):** rij-memoïsatie/virtualisatie —
  de kale renderkost per wissel is lineair in het aantal rijen (zonder StrictMode ~65 ms bij 130, ~270 ms bij 640 rijen, dev-build)
  en de rij-JSX wordt door blok 8 geraakt; de lijstroute-latency zelf. Guards: vitest `DocumentenDeelscherm.tabwissel.test.tsx`
  (rood op de code van vóór 25-09), `WerkvoorraadScreen.test.tsx` ongewijzigd groen, overflow-sweep werkvoorraad 48/48. Werkt in
  productie: niet gemeten (dispatch-onderdeel `tabwissel`: lijst-requests per minuut per client, `/auth/administraties` per
  minuut per client, cadans 3,0–3,3 s bij een actieve poll).

<!-- toegevoegd 25-09-2026, opdracht "feedbackrun-A-factuurverwerking" blok 9 -->
- **Comfort controlescherm 25-09 — bijlageverwijzing, kop → regels, rekenen in bedragvelden, splitter, periode van–tot (Peter 25-09;
  gebruikersfeedback Universal FV-05/07/08/10/11/13; geen migratie; BESLISSINGEN "COMFORT CONTROLESCHERM — BIJLAGEVERWIJZING, KOP →
  REGELS, REKENEN IN BEDRAGVELDEN, SPLITTER, VERDELEN-KNOP, PERIODE VAN–TOT (Peter 25-09)"):** (1) **Bijlageverwijzing gestript (FV-05).**
  `kop_omschrijving.strip_bijlageverwijzingen` haalt een verwijzing naar een bijlage ("conform bijgevoegd overzicht", "zie bijlage(n)",
  "volgens bijlage 2", "cfm. overzicht", "zie bijgevoegde specificatie voor details", "conform onderliggende specificatie", …;
  deterministische lijst, hoofdletterongevoelig) uitsluitend van de STAART van de automatische kop-omschrijving (regel- en
  betreft-bron); een tekst die alleen zo'n verwijzing is wordt leeg → volgende bron; midden in een zin wordt nooit geknipt ("zie
  bijlage voor de huur van juli" blijft); een handmatige omschrijving wordt nooit geraakt; nooit inhoud verzonnen.
  `KopOmschrijving.ingekort` → `omschrijving_ingekort` op de boekvoorstel-response → chip "ingekort" naast de herkomst-chip. (2)
  **Kop → regels (FV-07).** Bij ≥ 2 boekingsregels staan boven de tabel "Project voor alle regels" (alleen bij projectplicht) en
  "Btw-code voor alle regels"; een keuze wordt per regel doorgezet via dezelfde regelwijziging als een handmatige keuze (de
  18-09-regel "btw volgt het tarief" herrekent per regel), per regel daarna overschrijfbaar; de eerstvolgende PUT draagt
  `kop_doorgezet {project|btw: n, project_naam|btw_code}` en de server schrijft één tijdlijnregel "Kop → regels: project ‹naam› op N
  regels · btw ‹code› op N regels" (`DocumentGebeurtenis.detail.kop_doorgezet`, nooit op een autosave, nooit zonder aantal). (3)
  **Rekenen in bedragvelden (FV-08).** Netto/bruto- en btw-velden accepteren een rekenexpressie (`20+30`, `1.250,50*2`, `100/3`,
  `(10+5)*2`, `+ - * /`, haakjes, unaire min; komma = decimaal, punten dan duizendtallen; `×`/`÷`/`:` als synoniem), bij blur/Enter
  deterministisch uitgerekend door de eigen parser `document/bedragExpressie.ts` (shunting-yard, geen `eval`/`Function`; + en − in
  centen-integers, × en ÷ exact, eindresultaat ROUND_HALF_UP 2 decimalen); het veld toont het resultaat mét chip "= 20+30" tot de
  volgende wijziging; een kaal getal blijft ongewijzigd; tussentijds wordt een expressie nooit weggeschreven; ongeldig (lege
  operand, deling door 0, twee getallen zonder operator) = niets uitgerekend, terug op de laatst opgeslagen waarde. (4) **Geen
  horizontale overflow + formulier standaard breder + soepel slepen (FV-10/11).** Het controlescherm-harnas is op
  1440/1385/1280/1170/1024/768 (licht/donker, mét/zonder projectplicht) zonder pagina-overflow — de regeltabel scrolt intern in
  `.tabel-scroll` (kolomminima 27-08 ongewijzigd). De splitter-default is 42 % factuurbeeld / 58 % formulier (`ReviewSplitter.
  STANDAARD_PCT`, `.docpane` fallback); een bewaarde voorkeur per gebruiker (`localStorage rlz.controle.docpaneBreedtePct`) wint
  altijd; slepen = `setPointerCapture` op de grens, geen tekstselectie en `col-resize`-cursor op de pagina tijdens het slepen,
  rAF-throttling, breedte op 0,1 % afgerond; het verkoopscherm houdt zijn eigen 35 %. (5) **Periode "van … tot …" (FV-13).** Het
  enige periode-element op een scherm is het kopveld "Periode (weken)" op het controlescherm. De terugval zonder gelezen periode
  (ISO-week van de factuurdatum) heet letterlijk "week van de factuurdatum (aanname)" en draagt géén bereik; een periode uit de
  factuur draagt `datum_van`/`datum_tot` op `BoekvoorstelPeriodeDto` (exacte datums als de factuur die noemt — bij een opgeslagen
  periode opnieuw uit de bewaarde `periode_tekst` herleid zolang de weken kloppen —, anders maandag t/m zondag van het weekbereik;
  `periode.datumbereik`) → chip "1 jul – 31 jul 2026 (wk 27–31 · 2026) · uit factuur". De weeklogica en de kolommen van 0120 zijn
  ongewijzigd; er wordt niets extra gepersisteerd. Guards: `tests/documenten/test_kop_omschrijving_bijlage.py`, `test_kop_doorgezet.py`,
  `test_periode_datumbereik.py`, keten-casus c (Spot Services), vitest `bedragExpressie.test.ts`, `BedragModusInput.test.tsx`,
  `ReviewSplitter.test.tsx`, `BoekvoorstelPanel.kopDoorzetten.test.tsx`, `BoekvoorstelPanel.periode.test.tsx`,
  `kopDoorgezetTijdlijn.test.ts`; keten-baselines van de detail-casussen ververst (gewilde UI-wijziging). Werkt in productie: niet
  gemeten (dispatch-onderdeel `comfort-controlescherm`).

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

<!-- toegevoegd 21-09-2026, opdracht "BUG-iban-wissel-blijft-blokkerend-na-vier-ogen-akkoord-checks-cache" -->
- **Checks-cache — invalidatie op de bron, niet op tijd (BUG Peter 21-09, screenshot Beleggingsmaatschappij Meyer B.V.,
  Belastingdienst voorlopige aanslag Vpb 2025 0015.21.664.V.51.0112: "IBAN-wissel" Blokkerend "gecontroleerd 09:15 (ongewijzigd)"
  terwijl het paneel eronder live zei "Dit IBAN staat al in de vertrouwde set"; geen migratie; BESLISSINGEN "CHECKS-CACHE —
  INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09"):** het gecachte externe rapport (0165, ≤ 15 min) draagt de vertrouwde IBAN-set van
  het controlemoment; élke handeling die die set verandert maakt de cache in DEZELFDE transactie ongeldig
  (`checks_extern.maak_ongeldig_voor_vendor`: álle documenten van de crediteur + identiteitscluster, prefix `ongeldig:` op de
  vingerafdruk — geen DELETE-grant): het vier-ogen-akkoord (`iban_accordering.accordeer`), `leverancier_iban._voeg_toe` (bevestig,
  seed, baseline) en crediteur-samenvoegen (`verhuis_ibans`). Tweede slot: de vingerafdruk zelf bevat een hash van de gesorteerde
  vertrouwde set (lokale query) — een verouderd rapport matcht nooit meer, ook als een invalidatie-pad ooit vergeten wordt; de
  cache-rij krijgt de vingerafdruk van de stand ná de verse run. De IBAN-wissel toetst in `voer_checks_uit` ALTIJD tegen de live set
  (∪ seed-uitkomst); alleen de RLZ-seed en de duplicaatquery's komen uit de cache — dat geldt ook voor het boeken-pad (modus AUTO).
  **Scherm:** een check-rij en het paneel eronder mogen elkaar nooit tegenspreken — een 409 "staat al in de vertrouwde set" bij het
  aanbieden draait de checks vers (`POST …/boekvoorstel/checks?extern=vers`, melding "intussen vertrouwd — de controles worden opnieuw
  uitgevoerd") en de regel "Reeleezee/Odoo geraadpleegd om HH:MM (ongewijzigd …)" onder de controles-tabel draagt een `linkbtn`
  "Opnieuw controleren" (modus VERS) zodat een mens nooit op de klok van de cache wacht. **Nazorg:** CLI `checks-cache-legen
  --administratie <id>|--alles [--dry-run]` (schrijvend, eenmalig via `gcloud run jobs execute` op de job-image) markeert bestaande
  stale rapporten ongeldig. Guards: `tests/unit/test_leverancier_iban_invalidatie_guard.py` (élke `LeverancierIban(`-schrijver roept
  de invalidatie aan), `tests/documenten/test_checks_cache_invalidatie.py`, vitest `BoekvoorstelPanel.ibanCache.test.tsx`,
  gouden-set-casus af `tests/keten/test_af_iban_akkoord_checks_cache.py` (BDO-UBL mét andere baseline → akkoord → direct OK + boeken). Les
  (Platform `registers/verbeteringen.md` 21-09): bij élke nieuwe cache eerst de lijst "welke handelingen maken dit ongeldig".

<!-- toegevoegd 22-09-2026, opdracht "nameting-iban-wissel-cache-na-deploy" -->
- **Gemeten 22-09 (BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09" alinea "Gemeten 22-09"; rapport
  `docs/rapporten/2026-09-22-nameting-iban-wissel-cache-na-deploy.md`):** nazorg `checks-cache-legen --alles` uitgevoerd op de job-image
  (129 → 0 oude rijen, 78 administraties; "geldig" in de CLI = élke niet-gemarkeerde rij, ongeacht leeftijd). **Werkt in productie: ja
  voor het bevestig-pad** — request-log 21-09 17:38 NL: externe checks-run, 9 s later `bevestig_iban`, 3 s daarna opnieuw een externe run
  mét nieuwe cache-rij (zonder invalidatie/set-hash een cache-hit). Meyer 0015.21.664.V.51.0112: verse checks "doorstaan" om 10:17 NL
  (vóór de deploy, cache verlopen) → ter_accordering laag 3/3 open, niet herladen ná de deploy, niet geboekt = niet gemeten; `?extern=vers`
  0 × en vier-ogen-akkoord 0 × sinds de deploy = niet gemeten (geen mens raakte de route). Gedicht: `checks_cache_ongeldig` op élk
  `leverancier_iban_toegevoegd`-audit (ook bevestig/seed/baseline); `server_timing`-logregel bereikte Cloud Logging nooit →
  `app/logboek.py`. Vervolg `2026-09-23-nameting-iban-wissel-cache-mens-en-server-timing.md`.

<!-- toegevoegd 23-09-2026, opdracht "nameting-iban-wissel-cache-mens-en-server-timing" -->
- **Gemeten 23-09 + de al-vertrouwd-route is een 409 (BESLISSINGEN "CHECKS-CACHE — INVALIDATIE OP DE BRON (IBAN-akkoord) 21-09" alinea "Gemeten 23-09"; rapport `docs/rapporten/2026-09-23-nameting-iban-wissel-cache-mens-en-server-timing.md`):**
  `server_timing` komt sinds de deploy van 22-09 aan (126 regels; `checks.extern` mens-route p50 661 / p95 1.826 ms, n=20) en het
  audit-veld `checks_cache_ongeldig` staat op élke `leverancier_iban_toegevoegd`-rij (9 sinds de deploy, alle 0, geen akkoord). Meyer
  0015.21.664.V.51.0112 onveranderd (laag 3 open) en `?extern=vers` 0 × = niet gemeten. **ROOD gevonden en gefixt:** `POST
  …/iban-accordering` op een IBAN dat al in de vertrouwde set staat gaf **400**, het scherm herkende alleen **409** — op 23-09 07:50Z
  kreeg een mens (Kempen Facilities) de kale fout zonder verse controle. Regel: `IbanAlVertrouwd` = 409 (conflict mét de huidige
  set; zonder crediteur blijft 400), het scherm herkent 409 én 400 op de letterlijke tekst (`isAlVertrouwdAntwoord`); een
  status-contract tussen scherm en server staat in een ROUTE-test (`TestAanbiedenRouteStatuscode`, gouden-set-casus af) en in de
  vitest aan beide kanten — een service-level `pytest.raises` bewijst niets over de HTTP-status. Meetlat voortaan als
  dispatch-onderdeel `checks-cache` (`gh workflow run nameting -f onderdeel=checks-cache`).

<!-- toegevoegd 21-09-2026, opdracht "corrigeren-knop-geboekt-document-storno-plus-opnieuw-klaarzetten" -->
- **"Corrigeren…" op een geboekt document — storno (actie 19) + opnieuw klaarzetten vanuit de module (Peter 21-09 "laten we die
  terugboeken meenemen", casus BLOW RLZ-04-00000357/358 fout btw-bedrag, "ik kan de storno-knop niet meer vinden"; geen migratie;
  BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)"):** GEBOEKT is niet meer terminaal-zonder-
  uitweg. Op een geboekt inkoop-, verkoop- of kassarapport-document biedt het ⋯-menu (inkoop-controlescherm, archief `?corrigeren=1`,
  verkoop-/omzet-reviewscherm mét eigen ⋯) **"Corrigeren…"** = dialoog mét verplichte reden (≥ 5 tekens) → in één handeling en één
  rijvergrendeling (`app/documenten/corrigeren.py`, `FOR NO KEY UPDATE`; twee keer klikken = één storno, tweede = 409 `al_gecorrigeerd`):
  (1) poorten vóór de eerste externe write, alles-of-niets, élk mét route: aangifte (`app/rlz/aangifte.py`, fail-closed) → géén storno
  maar "Tegenboeken…" (inkoop; verkoop/kassarapport = creditnota in RLZ); (deels) betaald/afgeletterd (`BasePaidAmount` ≠ 0) → "eerst
  afletteren terugdraaien in de bankmodule" + link `/bank/{administratie}?zoek=<referentie>` (kassarapport = entity-loze Receipt zonder
  open post: geen afgeletterd-poort); doorbelasting-bron mét spiegel → beide kanten of geen (`storno_toets_voor_document`); verdwenen
  (404) → "Opnieuw boeken" vanuit Inzicht › Reconciliatie; Odoo → `NietOndersteund` zichtbaar mét "Tegenboeken…"; (2) storno extern:
  eerst de doorbelasting-spiegels (bestaande motor), dan het eigen stuk via `InkoopPort.storneer` (verkoop `correct_sales_invoice`;
  kassarapport memoriaal éérst, dan Receipt), terug-lezen Status 1; al concept = niets schrijven, lokaal wél klaarzetten; (3) lokaal het
  bestaande herboek-mechanisme: inkoop `boek_cyclus += 1` (vers GUID; de duplicaatcheck kent de hele keten als uitgezonderd),
  `rlz_boekstuknummer` leeg, GEBOEKT → KLAAR_OM_TE_BOEKEN, verplichting-verbruik/mini-voorraad/autoboek-leren terug, webhook
  `factuur_gestorneerd` (bron `module_storno`) voor vastgoed, tijdlijnregel `gecorrigeerd`, audit `document_gecorrigeerd` (reden, oud
  extern id, oud boekstuknummer); verkoop/kassarapport: registratierij → `gestorneerd`, kop-boekstuknummer leeg, herboeking her-PUT op
  hetzelfde GUID en maakt de registratie weer actief; (4) het document blijft/opent in het controlescherm mét gele balk "Gecorrigeerd —
  reden … · vorige boeking … gestorneerd (actie 19)" (`CorrectieBalk`, uit de tijdlijnregel, weg ná de herboeking), regels zoals ze
  waren, harde checks vers (vingerafdruk draagt de boek_cyclus). Klant-accordering: géén nieuwe ronde (het akkoord gold de factuur).
  Een mislukte externe stap laat lokaal álles staan en benoemt wat wél al terug is (audit `document_correctie_mislukt`; kassarapport:
  memoriaal terug, Receipt niet → registratie `HALF_GEBOEKT`). Rechten: élke kantoorrol. `storno_detectie.py` blijft de detectie voor
  storno's die tóch in de RLZ-UI gebeuren. Tests `tests/documenten/test_corrigeren.py`, `tests/verkoop/test_corrigeren.py`,
  `tests/omzet/test_corrigeren.py`, vitest `CorrigerenActie.test.tsx`, gouden-set-casus **ah** `tests/keten/test_ah_corrigeren_geboekt_document.py`
  (BDO boeken → corrigeren → herboeken op het nieuwe GUID, oud concept blijft; poging 2 21-09). Werkt in productie: niet gemeten (nameting-opdracht
  `2026-09-22-nameting-corrigeren-testadministratie.md`, TEST-referentie op de RLZ-testadministratie).

<!-- toegevoegd 21-09-2026, opdracht "BUG-rlz-boek-wachtrij-job-zonder-command-python-exec-failed-deploy-yml" -->
- **"Wordt geboekt…" is nooit een eeuwige stip — loopt-vast-label, trigger-reden op de tijdlijn, "Opnieuw indienen" (BUG 21-09,
  casus Administratiekantoor Nijenhuis C.V. Shine Employes € 480,13 + Reeleezee € 2.711,61 ingediend 12:46, om 13:02 nog
  `wordt_geboekt`; geen migratie; BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST + WORDT_GEBOEKT LET-OP (21-09)"):** (1) de rij in de documentenlijst
  toont ná `WORDT_GEBOEKT_VAST_MINUTEN` (5) "Wordt geboekt… (loopt vast — N min)" mét oranje dot (`StatusChip` leest
  `laatst_gewijzigd_op`; `werkvoorraad/status.ts::wordtGeboektLabel`), de lijst blijft pollen; (2) het controlescherm draagt bij
  status wordt_geboekt de balk `WordtGeboektBalk` (minuten meelopend; ná 5 min oranje "loopt vast" + primaire knop **"Opnieuw
  indienen"**); (3) `POST …/documenten/{id}/boek-wachtrij/opnieuw-indienen` (`boek_wachtrij.dien_opnieuw_in`) = géén nieuwe
  boeking en geen statuswissel — dezelfde sleutel/claim (idempotent, een gestrande claim wordt door de verwerker hervat), alleen
  de achtergrond-schrijver wordt opnieuw gestart; tijdlijnregel "Opnieuw ingediend …" (mens-actor) + audit
  `boek_wachtrij_opnieuw_ingediend`; het antwoord draagt `trigger_uitkomst` geslaagd | mislukt (mét `trigger_fout`; het
  scheduler-vangnet volgt) | lokaal en de toast noemt die letterlijk; niet op wordt_geboekt = 409 (nooit stil opnieuw indienen wat
  al geboekt/mislukt is); (4) een MISLUKTE job-trigger bij het indienen staat sinds 21-09 óók als systeemregel op de tijdlijn
  ("achtergrond-schrijver starten mislukt (job rlz-boek-wachtrij): <fout> — het scheduler-vangnet (elke 2 min) pakt de boeking op;
  … 'Opnieuw indienen'") — tot 21-09 alleen in het audit `boek_wachtrij_trigger`; een geslaagde trigger blijft alleen audit (geen
  ruis). Deze tijdlijnregels hebben van = naar = wordt_geboekt: `_wachtrij_detail` en het indienmoment (`_wordt_geboekt_documenten`)
  lezen uitsluitend de échte overgang (van ≠ wordt_geboekt), anders verloor de verwerker de actor/bevestigingsvlaggen en
  verschoof "sinds". Tests `tests/documenten/test_boek_wachtrij.py::TestNietsStil21_09`,
  `test_router_boeken.py::TestBoekWachtrijOpnieuwIndienenRoute`, vitest `status.wordtGeboekt.test.ts`, `WordtGeboektBalk.test.tsx`.
  Werkt in productie: niet gemeten (vervolg-opdracht `2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md`). Rapport `docs/rapporten/2026-09-21-f3-jobs-command-python-job-smoketest-wordt-geboekt-let-op.md`.

<!-- toegevoegd 22-09-2026, opdracht "nameting-corrigeren-testadministratie" (poging 2) -->
- **Gemeten 22-09 — "Corrigeren…" (BESLISSINGEN "CORRIGEREN VANUIT DE MODULE — STORNO + OPNIEUW KLAARZETTEN (Peter 21-09)" alinea "Gemeten
  22-09"; rapport `docs/rapporten/2026-09-22-nameting-corrigeren-testadministratie.md`):** de code staat sinds 21-09 17:59 NL in productie
  (service + 17 jobs `1018bcf`), maar de storno-cyclus mét TEST-referentie is NIET gedraaid: de RLZ-testadministratie "Administratiekantoor
  Nijenhuis (test)" (`faae29c5`) is op 30-08 gearchiveerd, boeken uit, 0 credentials (archiveren trekt de webservice-login in) → élke
  corrigeer-actie daar = 503 `GeenRlzCredentials`; dearchiveren vereist de TESTADMIN-login = klikpunt Peter (tien stappen in het rapport, incl.
  bonus: toets op een opgeruimd augustus-stuk = blokkade `verdwenen`). Request-log sinds de deploy: 0 × POST corrigeren 200, 0 × 5xx (alleen
  tokenloze probes); audit `document_gecorrigeerd` 0. **Werkt in productie: niet gemeten.** De meetlat staat nu als nameting-onderdeel
  `corrigeren` (request-log + `rlz-lezen` TEST-CORRIGEREN + `db-lezen correcties`) — ná Peters klik komt het bewijs als bot-bestand op main;
  vervolg-opdracht `2026-09-23-nameting-corrigeren-testadministratie-na-klikpunt.md`. De BLOW-stukken RLZ-04-00000357/358 zijn eveneens nog
  niet gecorrigeerd (klikwerk Peter, klantadministratie).

<!-- toegevoegd 22-09-2026, opdracht "nameting-jobs-start-en-boek-wachtrij-trigger" -->
- **Gemeten 22-09 — "Wordt geboekt…" mét achtergrond-schrijver die start (BESLISSINGEN "F3-JOBS — COMMAND PYTHON IN DEPLOY.YML + JOB-SMOKETEST +
  WORDT_GEBOEKT LET-OP (21-09)" alinea "Gemeten 22-09"; rapport `docs/rapporten/2026-09-22-nameting-jobs-start-en-boek-wachtrij-trigger.md`):**
  de job `rlz-boek-wachtrij` start sinds de deploy van 21-09 17:38 UTC élke 2 minuten (30/uur, 0 × "exec likely failed"), `db-lezen boek-wachtrij`
  = 0 × `wordt_geboekt_nu` en de vijf boekingen van 19→21-09 staan `afgerond geboekt`. **Het trigger-pad (klik "Boeken in RLZ" → 202 → job
  binnen 2 min) is NIET gemeten:** geen enkele indiening ná de deploy — request-log 21-09 17:38 → 22-09 13:20 UTC: 0 × POST `/boeken` 202, 0 ×
  `boek-wachtrij/opnieuw-indienen`, één 409 (Bouwadvies Oost Nederland, 08:52 UTC — poort vóór het indienen, geen `wordt_geboekt`). Ook de
  lijst-/balklabels "loopt vast" en "Opnieuw indienen" zijn daarmee ongebruikt in productie. Meting volgt uit gewoon kantoorgebruik of Peters klik
  op de testadministratie (gearchiveerd zonder credential — dearchiveren éérst); vervolg-opdracht poging 2 `niet vóór: 2026-09-23 09:00`.

<!-- toegevoegd 23-09-2026 avond, opdracht "webhook-herzenden 11 factuur_geboekt-events aan Vastly" (OPEN_ITEMS regel 13) -->
- **Webhook-outbox: "200 genegeerd" is géén aflevering + herzend-actie (23-09; geen migratie; BESLISSINGEN "WEBHOOK-HERZENDEN — 11 KOSTENEVENTS VASTLY
  (OPEN_ITEMS regel 13, 23-09)"):** de afleveraar (`app/documenten/webhook_afleveraar.py`) leest bij een 2xx het antwoord van de ontvanger
  (`{"resultaat": …, "reden": …}`, Vastly `rlz_webhook.py`): `resultaat == "genegeerd"` → rij `mislukt` mét "ontvanger negeerde het event: <reden>",
  audit `webhook_genegeerd`, geen herhaling (zelfde payload = zelfde antwoord; herstel = mens-besluit via `webhook-redrive`); élke aflevering draagt
  `resultaat` + `referentie` in het audit `webhook_afgeleverd`. Herzenden van AFGELEVERDE rijen = `herzend_afgeleverd` / CLI `webhook-herzenden
  --administratie … --referentie … --beheerder-id … [--uitvoeren --reden …]` (default dry-run; terug naar openstaand mét pogingen 0, payload
  onaangeraakt → zelfde `rlz_document_id`/`volgnummer`, verse timestamp/nonce/HMAC bij de volgende poging; audit `webhook_herzonden` mét reden;
  niet gevonden/niet afgeleverd = zichtbare regel + exit 1). Nooit een eenmalige SQL; `nameting.sh` weigert het commando (schrijvend); meetlat
  = querybibliotheek `db-lezen webhook-outbox` (status, laatste afleveraudit mét resultaat/ontvanger_reden, herzonden_op). Aanleiding: elf
  kostenevents Rubicon/ARVUM (24713213, 24713354, 265050202128, 26753012, 26734257, 2026-017; 183727, 26747235, 26752091, 522500062785,
  537500100925) stonden "afgeleverd" terwijl Vastly ze als `onbekende_administratie` negeerde (fix Vastly 20-09). Uitvoering ná deploy via
  `gcloud run jobs execute rlz-webhook-afleveraar --args=… webhook-herzenden …` (vervolg-opdracht `2026-09-24-webhook-herzenden-11-events-
  uitvoeren-na-deploy.md`); rapport `docs/rapporten/2026-09-23-webhook-herzenden-11-kostenevents-vastly.md`. Werkt in productie: niet gemeten.
<!-- toegevoegd 24-09-2026 avond, opdracht "herzending 11 events afmaken" (OPEN_ITEMS regel 13) -->
- **Webhook-outbox: samengesteld antwoord lezen, herzenden mét bewijs, `mislukt` herzendbaar (24-09; geen migratie; BESLISSINGEN "WEBHOOK-HERZENDEN
  — 11 KOSTENEVENTS VASTLY" alinea 5):** Vastly's `factuur_geboekt`-antwoord heeft twee lagen — topniveau = verkoopfactuur-badge (voor een
  inkoopfactuur per definitie `genegeerd`/`onbekend_document`), genest `kostenvoorstellen.resultaat` = de kostenuitkomst. `_lees_antwoord` neemt bij
  topniveau `genegeerd` het geneste resultaat (`voorstellen`/`al_verwerkt`/`kostenintake_uit`/…); alleen een (genest) `genegeerd` is genegeerd.
  `kostenintake_uit` (Vastly-tier-vlag `entiteit_config.rlz_kostenintake` uit) = afgeleverd zónder verwerking: rij `afgeleverd`, LET-OP in het
  rapport (`AfleverRapport.zonder_verwerking`/`let_op`), audit `webhook_afgeleverd` mét `resultaat`, `topniveau_resultaat` en `ontvanger_antwoord`
  (letterlijke body ≤ 500 tekens, bij élke poging). `herzend_afgeleverd` neemt `afgeleverd` én `mislukt` mee (`openstaand` = "al openstaand — niet
  herzonden"); `lever_rijen_direct_af` / CLI `webhook-herzenden --uitvoeren --afleveren` geeft de teruggezette rijen direct één afleverronde in
  dezelfde executie en print per referentie de uitkomst (`per_rij`) — een herzendactie bewijst zichzelf pas met een afleverronde erna.
  `_zoek_administratie_id`: UUID = platform-id óf `rlz_admin_id` (altijd platform-id terug, onbekend = fout); meerduidige naam → de enige
  vastgoed-administratie mét melding, anders kandidaten mét id. Aanleiding: poging 1 (24-09 17:50 UTC) zette 6 Rubicon-rijen `mislukt` op een
  topniveau-`genegeerd` terwijl de geneste uitkomst `kostenintake_uit` was; ARVUM "niet gevonden" op de rlz_admin_id én een tweede "ARVUM B.V."
  (Odoo-parallel-modus, bewust). Rapport `docs/rapporten/2026-09-24-webhook-herzenden-uitgevoerd.md`.
