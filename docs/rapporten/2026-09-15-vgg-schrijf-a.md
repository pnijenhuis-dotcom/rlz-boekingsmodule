# VGG → Odoo, run 2 blok 8: SCHRIJF a + derde meting — deel 1 (STAP 1: mapping 1012, code + tests) — 15-09-2026

**In gewone taal:** In Odoo company 6 staat ná deze run nog niets nieuws — de eerste echte writes (koppeling-rij als migratiedoel en de
zes rekeningen) draaien pas ná de deploy van deze commit en staan als vervolg-opdracht in de inbox, die automatisch start zodra deze run
klaar is. De meting van vanochtend zei ROOD door één ongemapte rekening (RLZ 1012 "Betalingen onderweg", € −15.877,22); die rekening
heeft nu een vaste vertaling naar de Outstanding-Payments-rekening van het bankdagboek in Odoo, en de replay leest de Odoo-rekeningen
straks zelf zodat de derde meting met doelkoppeling echte getallen geeft. Wat de meting mét doelkoppeling zegt, weten we pas in deel 2.

**Werkt in productie: niet gemeten** — STAP 1 is code + tests (geen productie); rekeningen aangemaakt: nee (nog niet gedraaid);
migratiedoel: nee (nog niet gedraaid); meting mét doel: nee (nog niet gedraaid). Deel 2 (`…-vgg-schrijf-a-vervolg.md`) vult dit per stap in.

## Wat is gebouwd (STAP 1, opdracht Peter 15-09)

- **1a — 1012 → Outstanding Payments.** Nieuwe ene bron `backend/app/migratie/rekening_mapping.py`: tabel per RLZ-code (doel, groep,
  schrijffase, toelichting) + lees-only resolutie van de outstanding-rekening van het bankdagboek: eerst de uitgaande
  betaalmethode-regels van BNK1 (`payment_account_id`, precies één = gevonden, meerdere = meerduidig en niet gekozen), dan de
  company-default als dat veld in deze Odoo-versie bestaat, anders een leesbaar KLIKPUNT voor Peter mét naam-kandidaten (alleen
  gemeld). Nooit de bankrekening zelf, geen nieuwe RJ-220-rol. 1012 telt in de groepstoets bij de bankgroep. Dezelfde resolutie zit in
  de migratiedoel-probe, zodat `plan` 'm vóór enige write toont.
- **1b — ongemapte rekeningen mét voorstel.** ROOD blijft ROOD, maar het rapport benoemt per ongemapte rekening de voorgestelde
  Odoo-tegenhanger (naamgelijke rekening → kandidaat; anders "aanmaken als `<code>00` (<type>)" mét vrij/bezet). De replay leest —
  zodra de doelkoppeling er is — de Odoo-rekeningen en de outstanding-rekening zelf (lees-only via de doelclient), zodat de derde
  meting op de job-image geen JSON-bestand nodig heeft; `--odoo-rekeningen` blijft als overschrijving.
- **1c — 1001 als SCHRIJF-b-markering.** In dezelfde tabel, fase b: generieke vertaling ongewijzigd, wél een voluit geschreven
  "Modelpunt bankgroep"-regel onder de groepstoets; de bankgroep is in de derde meting verwacht rood en heet dan ook zo.
- **SCHRIJF a idempotent.** `odoo-koppeling-migratiedoel --schrijf` op een rij die al hetzelfde migratiedoel is (zelfde host + company)
  = "AL MIGRATIEDOEL — ongewijzigd", exit 0, geen tweede audit-rij; een andere company blijft een weigering. Een herhaalde
  `SCHRIJF a` maakt zo niets dubbel (de rekeningen waren al lookup-vóór-create).

## Tests

- Nieuw `backend/tests/migratie/test_rekening_mapping.py` (20), aangepast `test_odoo_schrijf.py` (idempotent + probe mét outstanding)
  en `test_replay.py` (voorstel-kolom). tests/migratie 278 groen, tests/odoo 282 groen, nameting-workflow-guard groen, ruff schoon.
- Geen migratie, geen schema-wijziging, geen Odoo-/RLZ-writes in deze run.

## Waarom twee delen

`git push` staat voor de agent in de deny-lijst; de deploy volgt pas op de push van de Stop-hook ná deze run. STAP 2 (plan), 3 (SCHRIJF a
+ idempotentiebewijs + terug-lezen) en 4 (derde meting) staan letterlijk in `opdrachten/inbox/2026-09-15-vgg-schrijf-a-vervolg.md`,
mét de eis "eerst deploy groen en service = job-image". De cc-inbox pakt die op zodra deze run klaar is (lock valt vrij) — Peter start niets. De inbox werkt op mtime: er stonden om 10:20 al
twee oudere opdrachten in de rij (reconciliatie-nazorg 08:37, inbox-wacht 09:36), dus STAP 2–4 lopen daarná — bewust niet voorgedrongen.

## Meetrecept vervolg-run (samengevat; canoniek in BESLISSINGEN blok 8)

1. `scripts/gcp/vgg_blok7_odoo_writes.sh plan` → `verkenning/vgg-writes-plan-15-09.txt`; vijf rollen + Overhead, company 6, geen bestaande
   koppeling-rij op host+company 6, regel `outstanding_payments`, IBAN op BNK1. Eén afwijking = STOP.
2. `… SCHRIJF a` → `verkenning/vgg-writes-a-15-09.txt`; herhalen = ongewijzigd; terug-lezen via `nameting.sh vgg-rekeningen` + migratiedoel dry-run.
3. `scripts/gcp/vgg_blok7_nameting.sh alles` → derde meting mét doelkoppeling; "niet meetbaar — doelkoppeling ontbreekt" mag nergens meer
   voorkomen; 1096 niet vertaalbaar → 0 of échte reden; bankgroep verwacht rood (1001-modelpunt); top-10 + groepstoets letterlijk.
4. Geen SCHRIJF c.

## Kanttekening werkboom

Bij de start liep een parallelle inbox-run (`claude -p`, opdracht btw-uit-factuur-leeg) in dezelfde werkboom; die is eerst afgerond en
gecommit (`80598e0`) vóór hier iets is gestaged. Alleen eigen paden zijn gecommit; de lock `opdrachten/.lock` draagt de pid van dit
claude-proces zodat de inbox de vervolg-opdracht pas ná deze run start.
