uitgevoerd 2026-09-14, rapport: docs/rapporten/2026-09-14-nazorg-7d.md

OPDRACHT — NAZORG 7d + CC-INBOX STANDAARD AUTO (Cowork, 14-09; eerste echte inbox-opdracht)

0. scripts/cc_inbox.sh: de default permission-mode is door Cowork al op `auto` gezet (ongecommit). Documenteer dat in de kopcommentaar + CLAUDE.md-regel "Werkloop automatisch" (deny-lijst blijft gelden) en commit het mee.

1. Nazorg productienameting 7d (14-09, GROEN ZONDER DOEL — bewijs in verkenning/nameting-vgg-memoriaalregels-14-09.txt en nameting-vgg-replay-14-09.txt):
   a. rlz_bron.DOCUMENT_EVENTIDS: EventID 21 = memoriaal-documentpost (228 = 228 memorialen), EventID 240 = bank-direct (54 posten = 9 documenten + 45 systeemhulzen; toets telt documenten, hulzen apart benoemen). EventID 22 = memoriaal overig (214, STAP-0-feit, geen document). Volledigheidstoets memoriaal en bank-direct moet daarmee "sluit" geven i.p.v. "toets niet uitvoerbaar".
   b. CLAUDE.md § Reeleezee API, ManualJournals: `CreditOrDebit` (1=debet, 2=credit) is bewezen FOUT — 1 = CREDIT, 2 = DEBET (34/34 regels, 6 memorialen, STAP-0 14-09). Corrigeer en verwijs naar api-verkenning.
   c. verkenning/api-verkenning.md blok "Memoriaalregels — teken per regel, STAP-0 14-09": vul met letterlijke waarden uit het memoriaalregels-bestand: NetAmount is getekend naar de NORMALE zijde van de rekening (credit op type 4/1 positief, debet op type 3/2 positief; tegengestelde zijde negatief — RLZ-60-00000003 1602 debet → −1000; RLZ-06-00000122 4106 credit → −624,30), DebitAmount/CreditAmount eenduidig, CreditOrDebit 1=credit/2=debet, EventID 21/22/71/72/73/51/53/191/240. Valkuil: `JournalEntry/BookDate ge <datum>T00:00:00Z` schuift één dag (RLZ slaat lokale middernacht als UTC op).
   d. scripts/gcp/vgg_blok7_nameting.sh stap e: datumfilters zonder `Z` (lokale vorm), zodat 31-12/30-06/09-08 de juiste dag geven.
   e. BESLISSINGEN, sectie blok 7d, aanvulling "PRODUCTIENAMETING 14-09": GROEN ZONDER DOEL, werkt in productie: ja, plus bevinding `ongemapt:1001` −85.376,31 / +71.343,31: de PaymentTransactions dekken RLZ 1001 al exact (146.543,16 per 31-12); de 1001-poot van memorialen (RC, aandelenkapitaal, kruisposten) telt dubbel. Modelbesluit voor SCHRIJF b: memoriaal-1001-regels die tegen een statement line reconciliëren gaan in Odoo naar de outstanding/suspense-rekening van het bankdagboek, niet naar de bankrekening; vastleggen als open modelpunt (geen code nu).
   f. Flake tests/…/test_staande_voorstel_periodiek.py: oorzaak vinden en fixen (geen skip).

2. Definitie van af: gouden set groen, guards groen, rapport in docs/rapporten/2026-09-14-nazorg-7d.md + INDEX-regel, dit bestand naar opdrachten/gedaan/ met kopregel. Geen migratie, geen productie-writes; "werkt in productie: niet gemeten (geen productiegedrag geraakt)".
