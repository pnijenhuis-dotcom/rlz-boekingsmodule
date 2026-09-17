> uitgevoerd 2026-09-17 (STAP-0 lees-only: 83 projecten, project op de inkoopregel, niet op bank/journaal; instrument Project-dekking in vgg-replay; pand.rlz_project_id + --bron project, migratie 0155; werkt in productie: samples ja, dekking/CLI niet gemeten), rapport: docs/rapporten/2026-09-17-vgg-blok-11-pand-uit-rlz-project.md

# OPDRACHT 17-09 — VGG → Odoo, run 2 blok 11: pand = RLZ-PROJECT (Peter 17-09: "in RLZ staat alles als project geboekt") — STAP-0 dekking + pandenregister op het projectveld i.p.v. adres-clustering

**Melding Peter 17-09:** in RLZ is bij Vastgoedgroep Nederland alles op project geboekt (project = pand). Het huidige pandenregister
(`app/panden/afleiding.py`) leidt panden af uit ADRESTEKST in omschrijvingen/notarisdossiers (94 clusters, meetlat < 80 niet gehaald,
straatnaam-varianten) en gebruikt het RLZ-veld `Project` op de documentregel NIET — terwijl `rlz_bron.REGEL_EXPAND` het al ophaalt
(`Account,TaxRate,Project`). Dat is een omissie van onze kant: een deterministische sleutel lag klaar en we clusterden op tekst.

Pre-feature-ritueel: BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 1: SCHOONLIJST + PANDENREGISTER-DATALAAG", "… RUN 2 (12-09)"
(pandenregister herbouwd, clustering), "… BLOK 7c" (pandenmodel op grootboekregels), "… BLOK 7d" (per-pand "sluit" = GO-eis
SCHRIJF c), `app/panden/*`, `app/migratie/rlz_bron.py`, `vertaling.py`, api-verkenning "Projects klant-loze schrijfroute" (Projects
top-level GET). Harde grenzen: lees-only, geen writes; meerduidig = nooit raden; RLZ = bron van waarheid.

## Blok A — STAP-0 lees-only (productie via nameting.sh, VGG-administratie)
- `Projects` van VGG: aantal, naam/nummer-conventie (is de projectnaam = adres/pandcode?), actief/inactief.
- Dekking op regelniveau over de replay-set (1.096 documenten): % regels mét `Project`, per DocumentType (inkoop / verkoop /
  memoriaal / bank-direct) en per grootboekgroep (7000 aankoop, opbrengst, 1405 aanbetalingen, vaste lasten); regels ZONDER project
  op pand-relevante rekeningen als lijst (boekstuk, rekening, bedrag). Ook: staat `Project` op bankmutaties/`BankMutationDirectBookings`
  (waarschijnlijk niet) en op de memoriaal-1001-regels?
- Kruistoets: RLZ-project ↔ ons adres-cluster per document — hoeveel clusters vallen samen met één project, hoeveel projecten zijn
  over meerdere clusters versnipperd (de 94 → verwacht ~N projecten). Uitkomst in het rapport als tabel.

## Blok B — Pandenregister op projectsleutel (alleen als blok A dekking ≥ ~90 % op pand-relevante regels)
- `pand` krijgt `rlz_project_id` als PRIMAIRE sleutel (herkomst `rlz_project`, mens wint); adres-clustering wordt terugval + signaal
  ("regel zonder project op pand-rekening — koppel in Toewijzing"), nooit meer de leidende afleiding. Bestaande handmatige toewijzingen
  blijven (herkomst `mens`). Migratie alleen als er een kolom bij moet (afsluitroutine).
- Replay: pand per regel uit `Project` → Odoo analytic account per pand (bestaand doelmodel: `analytic_distribution` op de regel,
  één analytic plan "Panden", account = RLZ-projectnaam + code); groepstoets krijgt de per-pand-sluitcontrole (7d GO-eis) op
  projectbasis: Σ aankoop/aanbetaling/kosten/verkoop per pand = RLZ per project (`JournalEntryLines` mét Project) cent-exact.
- Overhead-project (`OVERHEAD_PROJECTNAAM`) = geen pand; regels zonder project op W&V-rekeningen = overhead, op balans = signaal.
- CLI `pandenregister-afleiden` krijgt `--bron project|adres` (default project zodra blok A groen), rapportkolom "bron".

## Blok C — Meting
- Ná deploy: `pandenregister-afleiden --dry-run` op VGG → aantal panden = aantal RLZ-projecten (± overhead), lijst "regels zonder
  project" als klikwerk Peter in RLZ (of Toewijzing). Vijfde/zesde meting neemt de per-pand-toets mee; verwachting: per pand 0,00
  voor alle panden mét volledige projectcodering.

## Afronding
Tests (projectsleutel wint, terugval alleen zonder project, meerduidig = signaal); BESLISSINGEN "… RUN 2 BLOK 11: PAND = RLZ-PROJECT";
CLAUDE.md verwijsregel; api-verkenning "Projects op VGG — dekking STAP-0 17-09"; rapport + INDEX mét "werkt in productie: ja/nee";
beslispunt Peter alleen als dekking < 90 %: regels zonder project in RLZ alsnog coderen (Peter, RLZ) vs adres-terugval accepteren.
Les voor `Platform/registers/verbeteringen.md`: "een deterministische bronsleutel (RLZ Project) eerst uitputten vóór tekst-clustering".
