uitgevoerd 2026-09-15 (deel 1 = STAP 1; STAP 2–4 lopen als opdrachten/inbox/2026-09-15-vgg-schrijf-a-vervolg.md ná deploy), rapport: docs/rapporten/2026-09-15-vgg-schrijf-a.md

OPDRACHT — VGG → ODOO: EERSTE ECHTE WRITES (SCHRIJF a) + DERDE METING (Peter 15-09 "go"; run 2 blok 8)

NB: Peter kan deze opdracht óók handmatig in CC geplakt hebben — controleer opdrachten/lopend/ en docs/rapporten/INDEX.md op 2026-09-15-vgg-schrijf-a vóór je begint; bestaat het rapport al, verplaats dit bestand naar gedaan/ en stop.

Lees eerst BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 7" t/m "7d", scripts/gcp/vgg_blok7_odoo_writes.sh (plan | SCHRIJF a|c) en verkenning/nameting-vgg-replay-15-09.txt (Oordeel ROOD door één nieuwe post: RLZ 1012 "Betalingen onderweg" € −15.877,22 per 15-09, ongemapt).

Grenzen: harde company-pin 6, kill-switch, elke write terug-gelezen, audit per call, alleen op de gedeployde job-image ná deploy-check, nooit via nameting.sh, nooit iets verwijderen. Twijfel = stoppen en rapporteren. Job-executies draai je zelf (gcloud is ingelogd).

STAP 1 — Mapping 1012 vóór de writes (code): RLZ 1012 → Odoo Outstanding Payments van BNK1 (Odoo 19 payment_account_id op de outbound payment method line, óf company-default); lees-only vaststellen op company 6 (odoo-verkenning §12.x). Geen nieuwe RJ-220-rol; hoort in de bankgroep van de groepstoets, net als 1001. Rapport benoemt per ongemapte rekening de voorgestelde tegenhanger. 1001-modelpunt (memoriaal-1001 tegen statement line → outstanding/suspense; dubbeltelling −85.376,31/+71.343,31) NIET bouwen, wél als "SCHRIJF b"-markering in de mappingtabel. Unit-test op de mappingtabel. Commit, deploy groen, service = job-image.

STAP 2 — plan: `scripts/gcp/vgg_blok7_odoo_writes.sh plan` → verkenning/vgg-writes-plan-15-09.txt. Toets: vijf rekeningen (325000/326000/803100/701300 + Btw-afwikkeling historisch) + Overhead; migratiedoel company 6, geen bestaande koppeling-rij host+company 6; IBAN BNK1 (leeg = melden). Afwijking = STOP.

STAP 3 — `scripts/gcp/vgg_blok7_odoo_writes.sh SCHRIJF a` → verkenning/vgg-writes-a-15-09.txt. Terug-lezen: rekeningen bestaan met juiste code/type/naam; koppeling-rij = migratiedoel (wizard toont company 6 grijs). Idempotentie bewijzen door herhaling.

STAP 4 — `scripts/gcp/vgg_blok7_nameting.sh alles`: mét doelkoppeling; "niet meetbaar — doelkoppeling ontbreekt" mag nergens meer; 1096 niet-vertaalbaar → 0 of echte reden per document; groepstoets + per pand + top-10 verschillen letterlijk; 1001 verwacht rood in bankgroep, benoemen, niet fixen.

STAP 5 — GEEN SCHRIJF c in deze run.

Af: tests groen; BESLISSINGEN "VASTGOEDGROEP NEDERLAND → ODOO — RUN 2 BLOK 8: SCHRIJF a + DERDE METING (Peter 15-09)" met letterlijke uitkomsten + "werkt in productie: ja/nee" per stap; CLAUDE.md-verwijsregel; odoo-verkenning; rapport docs/rapporten/2026-09-15-vgg-schrijf-a.md + INDEX (drie zinnen gewone taal bovenaan); dit bestand naar gedaan/.
