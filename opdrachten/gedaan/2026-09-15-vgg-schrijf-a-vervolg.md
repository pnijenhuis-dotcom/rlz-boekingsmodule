uitgevoerd 2026-09-15, rapport: docs/rapporten/2026-09-15-vgg-schrijf-a-vervolg.md

OPDRACHT — VGG → ODOO: EERSTE ECHTE WRITES (SCHRIJF a) + DERDE METING — DEEL 2 (vervolg op 2026-09-15-vgg-schrijf-a; Peter 15-09 "go"; run 2 blok 8)

Context: deel 1 (STAP 1 — mapping RLZ 1012 → Outstanding Payments, voorstel-kolom, replay leest Odoo zelf, SCHRIJF a idempotent) is
gebouwd, getest en gecommit in de vorige run (rapport docs/rapporten/2026-09-15-vgg-schrijf-a.md; BESLISSINGEN "VASTGOEDGROEP NEDERLAND →
ODOO — RUN 2 BLOK 8: SCHRIJF a + DERDE METING (Peter 15-09)"). Omdat `git push` voor de agent in de deny-lijst staat, volgde de deploy pas
op de Stop-hook ná die run; dit deel doet STAP 2–4 op de gedeployde job-image. Lees eerst die BESLISSINGEN-sectie + blok 7 t/m 7d,
scripts/gcp/vgg_blok7_odoo_writes.sh (plan | SCHRIJF a|c) en scripts/gcp/vgg_blok7_nameting.sh.

Dit is de eerste run die in Odoo company 6 SCHRIJFT. Grenzen ongewijzigd: harde company-pin 6, kill-switch, elke write terug-gelezen,
audit per call, alleen op de gedeployde job-image ná deploy-check (service = job-image), nooit via nameting.sh, nooit iets verwijderen.
Twijfel = stoppen en in het rapport zetten, niet gokken. Deze Mac is als owner ingelogd in gcloud (info@vastly.software): de
job-executies draai je zelf; Peter start niets.

STAP 0 — deploy-check (verplicht vóór alles)
Wacht tot de deploy-workflow van de commit van deel 1 groen is: `gh run list --limit 3` (workflow "deploy", status success) én
service = álle jobs op hetzelfde image (`gcloud run services describe rlz-backend --project rlz-boekhouding --region europe-west4
--format='value(spec.template.spec.containers[0].image)'` vs `gcloud run jobs describe <job> …` voor elke job; de image-tag = de sha
van de laatste commit op origin/main die `app/migratie/rekening_mapping.py` bevat). Nog niet groen → wachten (poll elke ~2 min, max 30
min); rood → STOP, rapport "deploy rood", niets uitvoeren. Doe vooraf `git pull --ff-only origin main` alleen als de werkboom schoon is.

STAP 2 — plan (lees-only)
`scripts/gcp/vgg_blok7_odoo_writes.sh plan` — volledige uitvoer opslaan als verkenning/vgg-writes-plan-15-09.txt. Toets: de vijf
rekeningen (325000 Voorraad panden, 326000 Vooruitbetaald op voorraad panden, 803100 Opbrengst verkoop panden, 701300 Kostprijs verkochte
panden — namen volgens rj220.py — + "Btw-afwikkeling historisch" 159000-reeks) + Overhead; migratiedoel = company 6 (Vastgoedgroep
Nederland B.V.) en géén bestaande koppeling-rij op host+company 6 (0140-index); de nieuwe probe-regel `outstanding_payments` (gevonden
mét code/naam/route óf "KLIKPUNT PETER" — beide zijn een uitkomst, letterlijk overnemen in odoo-verkenning §12.4 "Live-uitkomsten");
IBAN op BNK1 (leeg = stap 4/5 van SCHRIJF c straks overgeslagen, melden). Eén afwijking t.o.v. de verwachting = STOP, rapport, geen SCHRIJF.

STAP 3 — SCHRIJF a
`scripts/gcp/vgg_blok7_odoo_writes.sh SCHRIJF a` → DB-rij migratiedoel (odoo-koppeling-migratiedoel --schrijf) + vgg-rekeningen
--maak-aan. Uitvoer → verkenning/vgg-writes-a-15-09.txt. Terug-lezen: `scripts/gcp/nameting.sh vgg-rekeningen --administratie
Vastgoedgroep` (lees-only: kolom "bestaand (id · code)" per rol + huidige koppeling-rij) en `scripts/gcp/vgg_blok7_odoo_writes.sh plan`
opnieuw (migratiedoel-dry-run moet "AL MIGRATIEDOEL — ongewijzigd" zeggen): de zes rekeningen bestaan op company 6 met de juiste
code/type/naam, de koppeling-rij staat als migratiedoel (NIET als gewone administratie: de wizard toont company 6 grijs
"migratiedoel"). Idempotent: herhaal `SCHRIJF a` één keer — de tweede uitvoer moet "AL MIGRATIEDOEL — ongewijzigd" + alle rollen
"bestaand/hergebruikt" tonen en niets dubbel maken (bewijs = beide uitvoeren in verkenning/vgg-writes-a-15-09.txt, gescheiden door een kop).

STAP 4 — derde meting
Kopieer eerst het ochtendrapport: `cp verkenning/nameting-vgg-replay-15-09.txt verkenning/nameting-vgg-replay-15-09-ochtend.txt`
(het script overschrijft het dagbestand). Dan `scripts/gcp/vgg_blok7_nameting.sh alles` → nu mét doelkoppeling: verwacht oordeel GROEN
of ROOD mét échte getallen voor de groepstoets (bank/afletter-groepen incl. 1001 en 1012) en per pand; "niet meetbaar — doelkoppeling
ontbreekt" mag nergens meer voorkomen. 1096 "niet vertaalbaar" moet naar 0 (of per document een andere, echte reden — ongemapte
rekening mét de voorstel-kolom). Rapporteer de top-10 verschillen, de groepstoets en de tabel "Ongemapte RLZ-rekeningen" (mét
voorstellen) letterlijk; het 1001-modelpunt is verwacht rood in de bankgroep en wordt als zodanig benoemd (geen fix in deze run).

STAP 5 — NIET doen
Geen SCHRIJF c (posten/statement lines/reconcile): dat is de volgende opdracht ná Peters RLZ-opruimpunten (RLZ-01-00000006 concept,
dubbel 135.000 RLZ-28-00000061/062, bankregel "test") en ná het 1001-model. Geen code-wijzigingen behalve wat een gevonden fout in de
meting strikt vereist (dan: fix + test + melden; de meting daarna opnieuw pas ná een nieuwe deploy — dus in een volgende run).

Af: BESLISSINGEN-sectie blok 8 aangevuld mét de letterlijke uitkomsten en "werkt in productie: ja/nee" per stap (rekeningen aangemaakt
ja/nee, migratiedoel ja/nee, meting mét doel ja/nee), odoo-verkenning §12.4 "Live-uitkomsten" ingevuld (outstanding-rekening company 6,
exacte payloads zonder keys), verkenning/vgg-writes-plan-15-09.txt + vgg-writes-a-15-09.txt + nameting-vgg-*-15-09.txt gecommit;
rapport docs/rapporten/2026-09-15-vgg-schrijf-a-vervolg.md + INDEX (bovenaan in drie zinnen gewone taal: wat er nu in Odoo staat en wat
de meting zegt). Dit bestand ná afloop naar opdrachten/gedaan/ mét kopregel.
