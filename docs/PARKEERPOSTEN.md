# PARKEERPOSTEN — index (RLZ-boekingsmodule)

> **Pure INDEX, geen tweede waarheid.** Aangelegd 2026-09-02 (drift-audit-fixronde) omdat
> `Platform/WERKWIJZE.md` (leespad-regel besluit 0026) dit register in élk project verplicht stelt en RLZ
> het als enige project miste. Elke post hier is uitsluitend **titel + datum + verwijzing** naar de
> canonieke rij in `docs/BESLISSINGEN.md`; inhoud, status en trigger leven DÁÁR (regel wijzigen =
> dáár, dan de verwijzing hier). Regelnummers = stand 2026-09-02; verschuiven ze, zoek dan op de
> rij-titel. Onderhoud: elke bewuste versimpeling ("voor nu niet", "aparte ronde") die in een run
> in BESLISSINGEN landt krijgt in dezelfde commit een regel hier (capture-at-acceptance-discipline);
> een post verdwijnt als de BESLISSINGEN-rij op gebouwd/vervallen staat.

| # | Parkeerpost (titel) | Datum | `docs/BESLISSINGEN.md` |
|---|---|---|---|
| P-01 | Kernflow-follow-up: live visuele verificatie groen/oranje chips + voorstel-op-blur voor handmatige regels | 2026-07-14 | regel 38 |
| P-02 | Volledige NLCIUS-schematron in de RLZ-intake + vlag "consument-afnemer" (BR-NL-10-nuance v1.10) — nu alleen de kernvelden-proxy (`app/documenten/ubl.py`) | 2026-08-07 (status 02-09: geparkeerd, Platform/OPEN_ITEMS) | regel 68 |
| P-03 | WOZ-zij-extractie uit de OZB-aanslag + jaargebonden levering `platform.woz_beschikking` (koppelcontract §2e) — bouw fase 2 | 2026-08-02 | regel 83 |
| P-04 | Autoboek-afweging overige deterministische paden (doorbelasting-spiegels e.a.) — gedocumenteerd, niet bouwen zonder apart akkoord | 2026-08-16 | regel 149 |
| P-05 | Teal Akkoord-knop accordeur-app (designpass-nazorg) — open beslispunt, bewust niets gebouwd | 2026-08-27 | regel 570 |
| P-06 | Parkeerposten feedbackronde 25-08 deel 4 (bank): al-betaald-combinatiematch/G-rekening, debiteur-aanbetaling live verifiëren, open-posten-lijst-endpoint splits-editor, gemengde tekens in één splitsing, reconciliatie Σ koppelingen vs OpenAmount (huls-koppelingen) | 2026-08-25 | regel 420 |
| P-07 | Parkeerposten feedbackronde 25-08 deel 2: gewone regel-splitsing zonder doorbelasting via de verdeelhulp (pure motor staat klaar, UI niet) | 2026-08-25 | regel 540 |
| P-08 | Parkeerposten bundel-opdracht 22-08: offline-invoer weekstaten veld-app e.a. (elk een eigen ronde) | 2026-08-22 | regel 541 |
| P-09 | Steigerbouw-run 25-08 blok A: BSN-maskering ín de scan (OCR), 30-dagen-vooraankondigingsmail dossier, bureau-dossier detacheerder, AVG-register-aanvulling dossierdocumenten | 2026-08-25 | regel 434 |
| P-10 | Steigerbouw-run 25-08 blok B: prijsafspraak per m² voor uitvoerders/andere eenheden, automatische herberekening open matches bij afspraak-wijziging | 2026-08-25 | regel 472 |
| P-11 | Steigerbouw-run 25-08 blok D: verhuursysteem-koppeling Universal Verhuur (seam `zet_transport_status`), veld-app-aftekening leveringen, aantal×weken-extractie huurfacturen, herberekening materiaalmatch bij retour | 2026-08-25 | regel 495 |
| P-12 | IBAN-wissel vier-ogen-accordering (accordeur-set per administratie, `wacht_op_iban_accordering`) — ontwerp geparkeerd | 2026-07 (Geparkeerd-tabel) | regel 543 |
| P-13 | Multi-backend boekhoud-port + Odoo-adapter (besluit 0016) — STAP-0 uitgevoerd 02-09, adapter NIET gebouwd; 10 beslispunten + 8 klikpunten Peter | 2026-07-15 / STAP-0 2026-09-02 | regel 544 |
| P-14 | Betaalmodule via Ponto PIS — capture, roadmap ná go-live, platformbreed (geen bouw) | 2026-08-19 | regel 549 |
| P-15 | Geofence native achtergrondlocatie — gebouwd op branch `feat/geofence-native`, NIET gemerged/gereleased; versie 1.1 ná eerste store-goedkeuring | 2026-08-28/29 | regel 697 |
| P-16 | Voorraad-parkeerposten 29-08: Odoo-JSON-2-stand als systeemstand, maandelijkse werkvoorraad-melding (artikelcode-sleutel = GEBOUWD 30-08) | 2026-08-29 | regel 734 |
| P-17 | iPad-ronde 29-08 — niet gedaan/parkeerposten: split-view/twee-koloms-layout op iPad e.a. | 2026-08-29 | regel 874 |
| P-18 | Planning-uitbreiding 31-08: seam-bronnen zonder materiaallijst-poort, N+1 `transport_week`, werkbakje-chips per browser | 2026-08-31 | regel 893 |
| P-19 | Bank-reconciliatie-aandachtspunt: OpenAmount tijdelijk stale (huls) ná storno van een factuur-deel op een meervoudig gekoppelde mutatie | 2026-08-25 | regel 420 |
| P-20 | Intake-diagnose 02-09 punt 2 (UBL+PDF-paren bundelen + handmatige samenvoeg-actie) en punt 3 (afzender-leren begrenzen op kantoor-/doorstuuradressen) — aparte run ná beoordeling | 2026-09-02 | regel 1181 |
| P-21 | Open AVG-stap-1-restpunten (ZDR-besluit, model-check, klantinformatie, gevoelige administraties) terwijl de AI-gate live AAN staat — klikpunt Peter | 2026-09-02 | regel 1213 |
| P-22 | Openstaande review-/browserchecks Peter: Vastly-verkoopfactuur-boekpad (sinds 09-08), e-mail-intake + verzamelbak en omzetmodule (sinds 07-08), responsive-fix controlescherm (sinds 15-07), zoeken + archief (09-08) | 2026-07/08 | regel 69 |

Cross-project parkeerposten staan niet hier maar in `Platform/OPEN_ITEMS.md` (o.a. `--verwacht-productie`-vlag/
omgevingsbanner, EU-verwerkingsroute Claude, schematron/BR-NL-10-status 02-09).
