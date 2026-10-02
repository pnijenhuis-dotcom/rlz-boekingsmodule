uitgevoerd 2026-10-02, rapport: docs/rapporten/2026-10-02-run-a.md

# Opdracht 02-10 — Run A: boeken, projecten, meldingen, kleine bugs (punten 7–17 van de lijst 02-10)

Volgorde Peter 02-10: ná "Boeken prettig 1" (gebouwd 14:26) eerst run A, dan run B (planning/veld-app), dan run C (verhuur).
Regel Peter 30-09: "alles wat werkt moet af en af blijven; hou het simpel" — kleine afgebakende fixes, commit per punt, GEEN bijvangst,
geen nieuwe instellingen. Bron van de punten: `docs/gesprekken/2026-10-02.md`, `docs/feedback/2026-10-02-controlescherm-feedback-peter.md`.

LEESPLICHT per punt (lees het domeinbestand volledig vóór dat punt): werkvoorraad-controlescherm.md (7, 8, 9), kantoor-frontend.md (7),
verplichtingen-projecten-voorraad.md (11, 13), uren-planning-veldwerkers.md (10, 12), accordering-native-app.md + auth-toegang.md
(14, 16), intake-extractie.md (15), reconciliatie.md + koppelcontract §3 (17), werkloop-productie.md (alles).

## Controlescherm
7. "UIT DE E-MAIL" is nu een sectiekop in kapitalen onder Controles; wordt een gewone inklapregel in dezelfde stijl als
   Extractie-details / Opmerkingen / Tijdlijn. De regel-tabel (Boekingsregels) scrolt horizontaal zodat OMSCHRIJVING en het ×-knopje
   buiten beeld vallen op 1455 px — overflow-les 18-09: `.tabel-scroll` + `minWidth: 0` + kolombreedtes zó dat alles past op 1280 px
   zonder scroll; harnas-breedtes meten.
8. Grootboek-geheugen per leverancier wint nu van de inhoud (casus f00117f4: 7005 Inhuur steiger voor "brandstof diesel", Geheugen
   71 %). Regel: een geheugenvoorstel voor de grootboekrekening wordt NIET ingevuld als de regelomschrijving/factuurtekst
   deterministisch een andere rekening aanwijst (bestaande trefwoord-/omschrijvingsroute, geen AI) of als de zekerheid < 90 %; dan
   leeg + herkomst-info. Winnaarsvolgorde vastleggen in de regels; geen nieuwe drempel-instelling.
9. Verplaatsen naar een andere administratie: ná verplaatsen dezelfde doorloop als ná boeken — het server-gekozen VOLGENDE document in
   de bron-lijst (actief filter/administratie), nooit navigeren naar de doeladministratie. Tijdlijn/audit ongewijzigd.

## Projecten / meerwerk
10. Meerwerkbon (kantoor én app): projectnummer/-naam is een link naar de projectpagina; projectpagina linkt terug naar de bon.
11. Projectnummer 26149 bestaat twee keer in één administratie ondanks de 0160-uniciteit (cijfer-prefix per administratie, cache +
    RLZ, 409). Eerst DIAGNOSE (lees-only, leesreplica): beide records, bron/aanmaker/route (kantoor-invoer, veld-app quick-add,
    Vastly route A, RLZ-sync, Odoo), tijdstip; de route die de guard omzeilt dichten + guard-test. Daarna samenvoegen als nazorg-CLI
    `project-dubbel-samenvoegen --administratie … --nummer 26149` (dry-run default, `--uitvoeren` ná Peters "ja"): één project blijft
    (het oudste mét boekingen), het andere wordt gearchiveerd (RLZ IsActive false / Odoo archived via de bestaande 0160-flow), alle
    koppelingen (weekstaten, meerwerk, planning, documenten, verdelingen, offertes) omgehangen mét tijdlijn + audit; nooit verwijderen.
    Dry-run-uitvoer aan Cowork.
12. Projectpagina: blok "Meerwerk" met álle meldingen van het project en hun status (concept, ingediend, goedgekeurd, afgewezen,
    gefactureerd), dezelfde definitie als het Beoordelen-scherm, nieuwste bovenaan, klik = bon.
13. Zoekveld op Inzicht › Projecten: toetsen (typen + Enter gaf 02-10 geen filter, lijst bleef 240 — mogelijk alleen bij
    `?zoek=` in de URL); fixen zodat typen direct filtert op nummer/naam/opdrachtgever/werknummer én `?zoek=` werkt; test.

## Meldingen / kleine bugs
14. Accordeur-meldingen "Er staan N facturen voor u klaar" (10-min-job) en de 09:00-herinnering worden PUSH-ONLY: geen push-
    inschrijving of push mislukt = overslaan mét teller `overgeslagen_geen_push` in het joblog en de reconciliatiemail, nooit e-mail.
    De handmatige herinnering per document (kantoorknop) blijft push-anders-mail (bewuste mensactie). Besluit Peter 02-10 "geen mails
    meer". Guard-test op het afwezig-pad.
15. Upload KvK-uittreksel (ZZP-dossier, kantoor én app): "geldig_tot: invalid date separator" bij getypte datum. Frontend normaliseert
    dd-mm-jjjj / dd/mm/jjjj / jjjj-mm-dd naar ISO vóór verzenden; backend accepteert dezelfde drie vormen via één parser; foutmelding in
    gewone taal ("datum als 31-12-2026"). Test met alle drie.
16. Passkey-refresh-TTL-test rood door de zomertijdwissel (30 dagen vooruit = 1 uur te kort): TTL rekenen in UTC/absolute seconden,
    niet in kalenderdagen lokale tijd; test mét vaste peildata rond beide wissels.
17. Webhook-outbox: een `409` van Vastly ("nog niet koppelbaar") mag nooit ná 8 pogingen definitief `mislukt` worden. 409 = aparte
    status `wacht_op_ontvanger` met oplopende backoff (bv. 1 u → 6 u → 24 u, max 14 dagen), zichtbaar in de outbox-lijst en de
    reconciliatie (blok `webhooks`, soort `webhook_wacht_op_ontvanger`, actie "Nu opnieuw"), daarna pas `mislukt` mét reden. Antwoord
    op OPEN_ITEMS "voorstel-3c-409" als contract-eigenaar (koppelcontract §3-notitie, versiebump alleen als het gedrag voor Vastly
    verandert). De elf van 01-10 zijn al verwerkt — niets herzenden.

## Niet doen
Geen wijziging aan punten 1–6, btw, bank, Vastly-verkoop, planning (run B), verhuur (run C). Geen native release (23 = apart).

## Af
Per punt test(s) + guard op het afwezig-pad; volledige backend-suite, vitest, tsc, doc-guards groen (de passkey-DST-test nu óók groen);
WAT_IS_NIEUW per klantzichtbaar punt; BESLISSINGEN-sectie "RUN A 02-10 — BOEKEN, PROJECTEN, MELDINGEN, KLEINE BUGS (Peter 02-10)";
regels-alinea's in de geraakte domeinbestanden; CLAUDE.md hooguit één verwijsregel per domein; rapport docs/rapporten/2026-10-02-run-a.md
+ INDEX + "Gelezen regels" + per punt "werkt in productie: niet gemeten" + vervolg-nameting (dry-run `project-dubbel-samenvoegen`,
meetlat mails = 0 ná deploy, outbox-statussen). Committen; de Stop-hook pusht.
