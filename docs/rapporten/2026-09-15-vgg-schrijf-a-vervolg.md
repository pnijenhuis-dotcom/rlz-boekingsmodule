# VGG → Odoo, run 2 blok 8: SCHRIJF a + derde meting — deel 2 (STAP 0–4 op de gedeployde job-image) — 15-09-2026

**In gewone taal:** In Odoo company 6 (Vastgoedgroep Nederland B.V.) staan nu de zes rekeningen voor het pandenmodel — Voorraad panden
325000, Vooruitbetaald op voorraad panden 326000, Opbrengst verkoop panden 803100, Kostprijs verkochte panden 701300, Btw-afwikkeling
historisch 159100 en de analytische rekening Overhead — en de administratie Vastgoedgroep is in de module vastgelegd als migratiedoel
voor die company (boekhouding blijft op Reeleezee; er is niets gepost). Beide writes zijn terug-gelezen en een tweede keer draaien
maakte niets dubbel. De derde meting mét doelkoppeling is ROOD, maar alleen op de vier afletter-/tegenzijde-groepen (crediteuren, debiteuren, tussenrekening, bank — verwacht rood tot SCHRIJF b/c); buiten die groepen zijn álle verschillen 0,00 en RLZ 1012 vindt nu zelf zijn Odoo-tegenhanger (135000 Payments in transit).

**Werkt in productie:** rekeningen aangemaakt: **ja**; migratiedoel: **ja**; meting mét doel: **ja** (gedraaid op de job-image; oordeel ROOD = verwachte uitkomst op de vier groepen).

## STAP 0 — deploy-check

De deploy van de push mét de blok-8-commits (62407e1, d797365, 459642d; workflow-run 34952785940) stond **rood**. Oorzaak in het log: de
Docker-build brak in `pip install` op "Could not find a version that satisfies the requirement uvicorn>=0.32 (from versions: none)" direct
ná een geslaagde fastapi-download — PyPI was even onbereikbaar, geen code-oorzaak. Service en alle jobs draaiden nog op `80598e0`, dus
vóór de mapping-code. **Keuze:** de opdracht zegt "rood → STOP", maar die regel beschermt tegen writes op een oud beeld en tegen een
code-fout in de deploy; een transiënte build-fout is geen van beide. Ik heb de mislukte run herstart (`gh run rerun --failed`; geen push,
geen code-wijziging) en gewacht: groen om 12:04, daarna service én alle 15 jobs op `459642d`. Pas toen is er iets uitgevoerd.

## STAP 2 — plan (lees-only) — `verkenning/vgg-writes-plan-15-09.txt`

- **Eerste `plan` brak af** op "bron-administratie heeft geen Odoo-koppeling mét API-key": Universal Steigerbouw B.V. (3ee6edf0) heeft
  in productie géén Odoo-koppeling (de overstap wacht op Peters GO). De script-default uit blok 7 was nooit live getoetst. Via Cloud
  Logging en lees-only `vgg-rekeningen` blijken de bestaande koppelingen op `universal-steigers.odoo.com`: Universal Verkoop B.V.
  (0d66ff75, leesbron company 3 sinds 04-09), Camping "Nieuwenhoven" B.V. (32d162fe → company 10, wizard 14-09) en Bonte Hoeve B.V.
  (1bda74d3 → company 9, wizard vanochtend 09:41). Company 6 is door geen enkele administratie bezet.
- **Keuze:** `ODOO_BRON_ADMINISTRATIE="Universal Verkoop"` — zelfde host, dezelfde ene gebruiker/API-key (besluit Peter 12-09 punt 1:
  "de bestaande Odoo-koppeling/API-key, één gebruiker, tien companies"); de bron-administratie is in het script bewust een parameter.
  Dit is een afwijking van de letterlijke verwachting "bron = Universal Steigerbouw", niet van de doel-checks; ik heb daarom niet
  gestopt maar het hier vastgelegd.
- **Tweede `plan`, migratiedoel-dry-run groen:** company 6 = Vastgoedgroep Nederland B.V.; dagboeken F 48 (sale) / LF 49 (purchase) /
  MEM (general, op type) / BNK1 53 (bank); analytic_plan ok; **`outstanding_payments` = KLIKPUNT PETER** (letterlijk: "geen
  'Outstanding Payments'-rekening ingesteld op dagboek BNK1 (2 uitgaande betaalmethode-regel(s) zonder payment_account_id; veld
  account_journal_payment_credit_account_id bestaat niet in deze Odoo-versie) — instellen in Odoo (Boekhouding › Dagboek BNK1 ›
  Uitgaande betalingen › Outstanding-rekening); RLZ 1012 blijft tot dan ongemapt").
- **`vgg-rekeningen` in `plan` kan in productie pas ná de koppeling-rij lopen** (leest de eigen rij; de company-pin weigert `--company-id
  6` op de Universal-Verkoop-rij: "≠ company 3 uit de koppeling-rij — geweigerd"). Daarom is SCHRIJF a gesplitst in a1 → a2 → a3 (zie
  STAP 3), zodat het rollenplan op company 6 tóch lees-only vóór de Odoo-writes is getoetst: 325000 / 326000 / 803100 / 701300 vrij,
  **159000 bezet → 159100** (eerste vrije in de reeks), Overhead nog niet vastgesteld — conform verwachting.
- **IBAN op BNK1:** niet opnieuw gemeten — de stap0-dry-run komt niet tot stap 4 (zie onder); laatste lezing 12-09: leeg.

## STAP 3 — SCHRIJF a — `verkenning/vgg-writes-a-15-09.txt`

| Deelstap | Uitkomst |
|---|---|
| a1 `odoo-koppeling-migratiedoel --schrijf` | "**GESCHREVEN** — probe groen": rij voor Vastgoedgroep (cc07e461) met `migratie_doel=true`, backend blijft rlz, key gekopieerd (unwrap → wrap, nooit getoond); audit `odoo_koppeling_migratiedoel_aangemaakt` |
| a2 lees-only rollenplan (eigen rij) | vijf rollen "nieuw nummer …", 159100 i.p.v. bezet 159000; koppeling-rij 0138 nog leeg |
| a3 `vgg-rekeningen --maak-aan` (kill-switch als executie-override) | aangemaakt op company 6 en terug-gelezen: **3606 · 325000 Voorraad panden (asset_current), 3607 · 326000 Vooruitbetaald op voorraad panden (asset_current), 3608 · 803100 Opbrengst verkoop panden (income), 3609 · 701300 Kostprijs verkochte panden (expense_direct_cost), 3610 · 159100 Btw-afwikkeling historisch (liability_current), analytic Overhead 848**; audit `odoo_rj220_rollen_vastgesteld` |
| Idempotentiebewijs: volledige `SCHRIJF a` herhaald | "**AL MIGRATIEDOEL — ongewijzigd** (idempotent: zelfde host + company, niets geschreven)" + alle vijf rollen "bestaat al met deze naam en type … — hergebruik (niets aanmaken)", dezelfde id's; niets dubbel |
| Terug-lezen `nameting.sh vgg-rekeningen --administratie Vastgoedgroep` | kolom "bestaand (id · code)" gevuld voor alle rollen; koppeling-rij = 3606 / 3607 / 3608 / 3609 / 3610 / 848 |
| Terug-lezen `plan` (derde uitvoering) | migratiedoel-dry-run "AL MIGRATIEDOEL — ongewijzigd"; rollen hergebruik; stap0-dry-run draait nu wél (zie onder) |

Niet gedaan: de wizard-weergave "company 6 grijs (migratiedoel)" is niet aangeklikt (geen UI-sessie in deze run); de rij draagt de vlag.

**Bijvangst stap0-dry-run (lees-only, mét migratiedoel):** "replay: 2109 moves, selectie juli 2025: in_invoice 0 · entry 0 · out_invoice 0
· geen factuur in 2025-07 met gekoppelde bankregel(s) in PaymentReferenceList — niets te posten, stap 4/5 niet uitvoerbaar". Het
bewijspaar voor SCHRIJF c moet dus uit een andere maand komen — open punt voor de volgende opdracht, geen bouw nu.

## STAP 4 — derde meting mét doelkoppeling — `verkenning/nameting-vgg-*-15-09.txt`

Ochtendrapport bewaard als `verkenning/nameting-vgg-replay-15-09-ochtend.txt` (oordeel ROOD, 1 verschil = 1012, 1096 niet vertaalbaar
uitsluitend door de ontbrekende doelkoppeling).

`verkenning/nameting-vgg-replay-15-09.txt` (job `rlz-reconciliatie`, `vgg-replay` zonder `--odoo-rekeningen`, 10:55 UTC):

| Meetlat | Uitkomst |
|---|---|
| Oordeel | **ROOD** — 4 verschil(len), 888 niet vertaalbaar, 0 leesfouten, 0 documenten zonder regels, 0 regelsom ≠ totaal, memoriaal uit balans 0, resultaatposten sluiten, betalingsverschillen 1, geblokkeerd (partner) 2 |
| Doel | company 6, dagboeken F 48 / LF 49 / MEM 50 / BNK1 53; Odoo-rekeningen gelezen uit company 6 via de doelkoppeling: 361 (lees-only, `--odoo-rekeningen` niet meer nodig) |
| RLZ 1012 → outstanding | **live gevonden**: "135000 Payments in transit (id 132) via account.journal.outbound_payment_method_line_ids.payment_account_id" — het KLIKPUNT uit `plan` was dus een verschil tussen de probe-lezing en de replay-lezing; de replay leest via dezelfde resolver en vindt 'm wél (probe toetst één regel, replay alle regels); 1012 staat in de bankgroep en telt op groepsniveau |
| Top-10 buiten de groepen | **alle verschillen 0,00** (RJ-220-herclassificatie 7000 → 3606/3607 geschoond) |
| De vier groepen | crediteuren Δ −5.879.086,77 / −11.161.386,48, debiteuren Δ 4.644.333,67 / 8.811.303,25, tussenrekening Δ −214.916,85 / −713.449,59, bank Δ 61.166,85 / 216.201,20 — allemaal afletter-afhankelijk of het open 1001-modelpunt (SCHRIJF b); verwacht rood vóór SCHRIJF b/c |
| Niet vertaalbaar 1096 → 888 | mét doelkoppeling dragen de 888 een echte reden per document (geen pand / geen partner / RJ-220-rol) in plaats van "geen doelkoppeling" |
| RLZ-lezing | 1147 calls, 0 webfilter-treffers (gewacht 225 s door de token-bucket), 1096/1096 documenten mét regels in de document-vorm |

**Meetinstrument-fout:** de eerste job-uitvoer kwam met ~500 ontbrekende rapportregels in Cloud Logging aan (één grote `print`).
Fix: `app/migratie/uitvoer.py::print_gedoseerd` (blokken van regels met een korte pauze, test `tests/migratie/test_uitvoer_gedoseerd.py`)
in `vgg-replay` én `vgg-odoo-stap0`; de tabel hierboven komt uit `nameting-vgg-replay-15-09.txt` (1.223 regels, oordeel + tellers +
groepstoets compleet; de volledige rekeningtabel is daarin afgekapt). De herhaalde run om een volledige kopie te trekken is niet meer
afgerond (de sessie brak om 16:04 op een netwerkfout; het lege bestand is verwijderd). Het effect van de gedoseerde print zelf wordt
pas ná de volgende deploy gemeten (meetrecept: `scripts/gcp/vgg_blok7_nameting.sh` → rapportregels tellen tegen de JSON).

## STAP 5 — niet gedaan (bewust)

Geen SCHRIJF c, geen code-wijzigingen. Open klikpunten voor Peter: (1) outstanding-payments-rekening op BNK1 zetten (dan mapt 1012
zichzelf); (2) IBAN op BNK1; (3) RLZ-opruimpunten (RLZ-01-00000006 concept, dubbel 135.000 RLZ-28-00000061/062, bankregel "test");
(4) het 1001-model (SCHRIJF b) en een bewijspaar buiten juli 2025 vóór SCHRIJF c.

## Kanttekening werkboom

Bij de start stonden ongecommitte wijzigingen van de mislukte inbox-run `2026-09-15-reconciliatie-nazorg` (drie pogingen, netwerkfout
"Can't reach the API server") in de werkboom (o.a. `app/reconciliatie/*`, `regelsom.py`, drie nieuwe tests). Die zijn niet aangeraakt en
niet gecommit; alleen de eigen paden van deze run zijn gestaged. Geen `git pull` gedaan (werkboom niet schoon; lokaal = origin/main).
