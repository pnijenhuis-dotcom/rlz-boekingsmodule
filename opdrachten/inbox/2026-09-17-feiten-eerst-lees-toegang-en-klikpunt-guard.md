# OPDRACHT 17-09 — "Feiten eerst": lees-only toegang tot ALLE relevante productiedata voor analyses/controles + guard dat elk klikpunt/signaal op data staat, nooit op een aanname (Peter 17-09: "100 % audit is een must")

**Aanleiding (17-09 ochtend, drie keer op één dag):** (1) "dubbel € 135.000 RLZ-28-00000061/062" bleek een ontvangst + een betaling
(bank niet gecontroleerd); (2) "RLZ-01-00000006 concept" en (3) "bankregel 'test'" stonden als klikpunt in rapporten zonder bron-id,
datum, bedrag of link — niemand kan ze terugvinden. Daarnaast 1.214 valse "dubbel betaald"-bevindingen (aparte spoedopdracht).
Gemene deler: conclusies zijn uit samenvattingen/geheugen overgenomen in plaats van uit de data gelezen, en de lees-toegang tot
productie is te smal (CC alleen via de nameting-allowlist; de eigen DB in productie is voor CC niet leesbaar — 16-09 "Cloud-Shell-SQL
geweigerd", documenthistorie uit Cloud Logging gereconstrueerd; Cowork heeft helemaal geen datatoegang).

Pre-feature-ritueel: BESLISSINGEN "PRODUCTIE-NAMETINGEN STRUCTUREEL", "NAMETINGEN-RUN 10-09", "INCASSO-/BETAALBATCHES — STAP-0" (`rlz-lezen`),
"WERKLOOP AUTOMATISCH", Jarvis CLAUDE.md-principe "versioneerde querybibliotheek, nooit vrije SQL op productie", Platform `conventies.md`
§RLS; regel Peter 08-09 (productie alleen via gedeployde jobs/lees-only) blijft onverkort — dit VERBREEDT de lees-only kant, niet de
schrijfkant. Kernprincipe 2 (code voor cijfers) en 4 (niets stil).

> **BESLUIT PETER 17-09 (bindend, vervangt de smalle variant hieronder waar die botst):** "Vragen en opmerkingen uit halve informatie zijn
> levensgevaarlijk en pertinent verboden. We doen zaken op basis van volledige data en anders niet." Leestoegang gaat daarom VOLLEDIG
> open: (1) een **Cloud SQL-leesreplica** van `rlz-sql2` (`rlz-sql2-lees`, zelfde CMEK, zelfde regio) mét een SELECT-only rol `rlz_lezer`
> (geen writes mogelijk, geen last op de primary, `pgaudit`/`log_statement=all` op de replica = 100 % audit van élke leesquery);
> (2) CC mag daar **vrije SELECT** op draaien via de Cloud SQL Auth Proxy + IAM-auth als `nameting@` (amendement op de regel van 08-09:
> die regel verbiedt lokale processen tegen de PRODUCTIE-database — een SELECT-only rol op een replica kan niets schrijven en is
> daarmee geen "proces tegen productie"; vastleggen als BESLISSINGEN-amendement + CLAUDE.md-regel); (3) RLZ/Odoo lees-only zonder
> `--top`-plafond voor analyses (`rlz-lezen --alles` mét token-bucket/webfilter-backoff); (4) Cowork krijgt dezelfde data via een
> Beheerder-only leesroute `POST /lezen/sql` op de service (SELECT-only, replica, rijenplafond 5.000, audit) die vanuit de Chrome-
> extensie onder Peters login te gebruiken is, plus `workflow_dispatch`-input `sql`/`query` in de nameting-workflow (bot commit de uitkomst).
> De querybibliotheek (blok A) blijft bestaan als HERBRUIKBARE, gereviewde queries voor terugkerende controles; ze is geen poort meer.
> Jarvis: is de MI-leeslaag, maar staat op bouwopdracht 01 (UVA-sync) en heeft RLZ-feiten nog niet (bouwopdracht 02 via uitleverkontract)
> — niet op wachten; Jarvis leest later dezelfde replica (0028-conform: leesmodel), zodat er één leeswaarheid ontstaat.

## Blok A — Lees-only DB-toegang voor analyses: `db-lezen` met een querybibliotheek (+ vrije SELECT op de replica, zie besluit)
- Nieuwe CLI `db-lezen <querynaam> [--param …]` op de gedeployde job-image, in de nameting-allowlist, draait onder een **read-only
  DB-rol** (`rlz_lezer`: alleen SELECT op `platform`/`boekhouding`/`mi`, RLS-bypass NIET — scope via een systeem-actor mét alle
  administraties, audit_event `db_lezen` per aanroep mét querynaam + params). Queries leven in `backend/app/lezen/queries/*.sql` mét
  naam, versie, doel, parameters en verwachte kolommen (Jarvis-patroon); een nieuwe query = commit + review, nooit ad hoc.
- Startset (wat we deze week nodig hadden): `document-feiten <document_id|boekstuk>` (kop, regels, status, tijdlijn, audit, RLZ-/Odoo-id,
  bankkoppelingen), `bankmutatie-feiten <id|iban|omschrijving>` (mutatie, richting, tegenpartij, afletterstand, koppelingen),
  `reconciliatie-bevindingen --soort --administratie --status` (tellingen + top-N), `sync-status <administratie>`, `project-cache
  <administratie>`, `whitelist-doelen <bron>`, `documenten-zonder <veld>` (project/crediteur/…). Uitvoer: markdown-tabel + JSON,
  geanonimiseerd waar PII (naam → initialen + IBAN-suffix), max 500 rijen mét teller.
- Migratie: rol + grants (afsluitroutine). Cloud SQL IAM-auth voor de nameting-SA op die rol; geen wachtwoord.

## Blok B — Lees-only RLZ/Odoo-feiten: `rlz-lezen` uitbreiden tot `feiten`
- `feiten rlz <administratie> <boekstuk|id>`: document + regels + `PaymentReferenceList` + gekoppelde bankmutaties (richting, datum,
  tegenpartij) in één tabel; `feiten bank <administratie> --omschrijving "test" | --iban | --bedrag | --datum`: alle mutaties die
  matchen mét koppelingen; Odoo-variant via de adapter. Dit is het instrument waarmee blok B/C van de schoonlijst-opdracht en élk
  toekomstig opruimpunt worden onderbouwd — "bank is leidend" wordt zo een leesstap die altijd gedaan wordt.

## Blok C — Guard: geen klikpunt of signaal zonder bron
- Rapportsjabloon + test `tests/unit/test_rapporten_klikpunten.py`: élke regel onder "Klikpunten"/"Opruimpunten"/"Beslispunten" die een
  RLZ-/Odoo-/bank-object noemt, draagt bron-id + datum + bedrag + (RLZ-)link, óf de letterlijke uitkomst van `feiten`/`db-lezen` als
  citaat; een kaal "RLZ-01-00000006 concept" = rood. Bestaande open klikpunten zonder bron worden ingetrokken tot ze herleid zijn.
- Reconciliatie-/schoonlijst-signalen over dubbelen/duplicaten dragen verplicht het bank-toetsresultaat in de DTO (`bank_toets:
  bevestigd|weerlegd|geen_mutatie`); een signaal zonder bank-toets kan niet worden aangemaakt (guard-test) — codificatie van "bank is
  altijd leidend" (Peter 12-09/17-09).

## Blok D — Cowork-lees-toegang (geen bouw, wel afspraak)
- Cowork (Peter's chat-assistent) leest productie via de kantoor-web in de Chrome-extensie onder Peters login (toestemming 16-09) en via
  de rapporten die `db-lezen`/`feiten` produceren; nooit via lokale DB-verbindingen. Vastleggen in WERKWIJZE + BESLISSINGEN; de
  nameting-workflow krijgt een `workflow_dispatch`-input `query` zodat Cowork óók zonder CC een `db-lezen`-rapport kan laten draaien
  (uitkomst als `verkenning/lezen-<datum>-<query>.txt` gecommit door de bot).

## Afronding
Migratie (rol/grants) volgens afsluitroutine; tests (read-only rol kan niet schrijven — echte niet-owner-test; allowlist weigert onbekende
querynaam; guard-tests blok C); BESLISSINGEN "FEITEN EERST — LEES-ONLY DB-/RLZ-TOEGANG VOOR ANALYSES + KLIKPUNT-GUARD (Peter 17-09)";
CLAUDE.md verwijsregel onder Werkwijze; `Platform/registers/verbeteringen.md` les 17-09; rapport + INDEX mét "werkt in productie: ja/nee"
(meetrecept: `nameting.sh db-lezen document-feiten RLZ-28-00000061` en `feiten bank <VGG> --omschrijving test` geven de echte
gegevens terug, incl. de Koppe-vraag van Peter).
