uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-intercompany-rc.md

# OPDRACHT 16-09 — Intercompany-factuurmatch + rekening-courant-aansluiting als dagelijkse reconciliatieblokken (Peter 16-09)

**Aanleiding (Peter 16-09, letterlijk):** "Dagelijkse controle dat facturen tussen onze bedrijven altijd matchen. Als Universal
Verkoop bijvoorbeeld een verkoopfactuur heeft staan aan Universal Nederland maar Universal Nederland heeft die factuur niet bij
inkopen staan dan wil ik het weten (en dat voor al onze boekhoudingen)." en "rekening-courant (RC) aansluitingen — wij hebben op de
balans verschillende RC's tussen gelieerde bedrijven. Dagelijks wil ik een controle van die GB's of het eindsaldo aansluit en
indien het niet aansluit wil ik weten welke mutatie mist." Peter wil de ACTIEMAIL ("N zaken vragen je aandacht") behouden en
juist uitbreiden — de uitkomsten van deze twee blokken landen dáár als regels mét handeling.

Pre-feature-ritueel: lees BESLISSINGEN "RECONCILIATIE-MELDING + INZICHT", "RECONCILIATIEMAIL = ACTIEMAIL + SYSTEEMMAIL",
"RECONCILIATIE-NAZORG 15-09", "KEMPEN-DOORBELASTING" (IC-vlag, `intercompany_tegenpartij`, spiegel-inkoop),
"INTERCOMPANY-LEVERANCIERS INSTELBAAR", "A12 — RECONCILIATIE BACKEND-AGNOSTISCH" (Odoo-administraties!), "GROEPSKENMERK OP
ADMINISTRATIE", "RLZ-VERLEDEN VAN EEN OVERGESTAPTE ADMINISTRATIE", en api-verkenning "Webfilter-blokkering bij >N calls" +
"Incasso-/betaalbatches — STAP-0 11-09" (`rlz-lezen`). Geheugen: `rlz-todo-doorbelasting-aansluiting-kf` (KF-verkoop ↔ KF-inkoop
lees-only) — die TODO gaat hierin op, apart bouwen is niet meer nodig.

## Harde kaders
- Lees-only tegen RLZ en Odoo. Geen enkele write, geen actie 19/17, geen Odoo-post. Bevindingen = reconciliatie-bevindingen mét
  acceptatie-met-reden; het systeem herstelt niets zelf (het gaat om andermans boekhouding).
- Backend-agnostisch: Universal Verkoop is Odoo (company 3), Universal Steigerbouw in productie RLZ, VGG company 6 migratiedoel.
  Een IC-paar RLZ↔Odoo moet gewoon werken via de bestaande ports; een administratie zonder credential = zichtbaar overgeslagen,
  nooit stil (KP 6 geen stille no-op).
- Schaal: 76 administraties, RLZ-webfilter blokkeert bij ~700 calls. Lees per administratie ALLEEN documenten van/aan
  IC-tegenpartijen (server-side `$filter` op Entity-id's) en alleen een venster (default 400 dagen, instelbaar), incrementeel
  waar de bron het toelaat. Token-bucket van de gedeelde `RlzClient` blijft de rem. Blokkering = "meting ongeldig", nooit
  valse bevindingen.
- Minimale mens: de IC-relaties worden AFGELEID, niet ingevoerd. Beheerder kan alleen corrigeren (uitsluiten/toevoegen).

## Blok A — IC-relaties afleiden (fundament voor A en B)
1. Per administratie: identiteit = KvK-nummer + btw-nummer + naam uit de bron (RLZ `Administrations`/`Company`-route die de sync al
   leest; Odoo `res.company` vat/company_registry). Sla op in `administratie_identiteit` (migratie; kolommen kvk, btw, naam_norm,
   bron, gelezen_op).
2. Per administratie: crediteuren + debiteuren (bestaande caches) matchen op KvK → btw-nummer → genormaliseerde naam tegen de
   identiteiten van de ANDERE administraties → tabel `intercompany_relatie` (administratie_a, entity_in_a, administratie_b,
   richting crediteur/debiteur, basis kvk|btw|naam, actief, bron 'afgeleid'|'mens'). Naam-only = oranje "vermoedelijk IC,
   bevestigen" (nooit stil meetellen in de match; wél in het rapport). Bestaande `intercompany_tegenpartij`-rijen
   (doorbelasting) worden als bevestigd overgenomen — één leesbron `app/intercompany/relaties.py`, de doorbelasting-IC-vlag
   (`doorbelasting/intercompany.py`) blijft gedrag-identiek en leest voortaan via dezelfde module (test: bestaande
   tests groen).
3. Beheerder-UI: klein blok "Intercompany-relaties" op Instellingen › Boeken (platformbreed, lijstpatroon: A ↔ B, basis, chip
   afgeleid/bevestigd/uitgesloten, ⋯ → uitsluiten mét reden / bevestigen). Geen tegel, geen nieuwe pagina. Registry-entry +
   overflow-sweep.

## Blok B — IC-factuurmatch (dagelijks reconciliatieblok `intercompany`)
1. Voor élk actief IC-paar (A verkoopt aan B): verkoopfacturen van A aan entity_B (RLZ SalesInvoices / Odoo out_invoice,
   venster) ↔ inkoopfacturen van B van entity_A (RLZ PurchaseInvoices / Odoo in_invoice). Match-sleutel in volgorde:
   factuurnummer als heel token (A's InvoiceNumber ↔ B's Reference/`ref`, zelfde normalisatie als `rlz_dubbel`) → bedrag
   cent-exact + datum ± 7 dagen → bedrag cent-exact zonder datum (oranje).
2. Bevindingen (nieuwe soorten in `reconciliatie/teksten.py`, mensentaal titel/wat/doe):
   - `ic_ontbreekt_bij_ontvanger`: verkoop staat bij A, geen inkoop bij B → "Universal Verkoop factureerde 2026-0123 € 4.500,00
     aan Universal Nederland; bij Universal Nederland staat die inkoop niet." Handeling: link naar de verzamelbak/documentenlijst
     van B (staat de factuur misschien in de module nog te controleren? dan dát melden i.p.v. 'ontbreekt': status "onderweg in
     module" is GEEN bevinding).
   - `ic_ontbreekt_bij_verkoper`: inkoop bij B van A zonder verkoop bij A (omgekeerd — ook belangrijk: B boekt iets dat A niet
     gefactureerd heeft).
   - `ic_bedrag_verschilt`: zelfde nummer, ander totaal (mét beide bedragen en Δ).
   - `ic_status_verschilt`: één kant concept, andere kant geboekt (alleen als ouder dan 7 dagen).
   - Creditnota's tellen mee (negatief), verrekenparen (factuur+credit) als één.
3. Vingerafdruk stabiel per paar (administraties + nummer), acceptatie-met-reden blijft over runs heen; "onderweg in module"
   verdwijnt vanzelf zodra geboekt.
4. Doorbelasting-spiegelparen (bron-verkoop + spiegel-inkoop uit onze eigen motor) MOETEN 100 % groen zijn — dat is meteen de
   bewijslast van de doorbelastingsmotor; een rode spiegel = systeemfout "automatisch gemeld" (audit + bewakingsprobe), geen
   gewone bevinding.

## Blok C — Rekening-courant-aansluiting (dagelijks reconciliatieblok `rekening_courant`)
1. RC-rekeningen afleiden: per administratie de grootboekrekeningen waarvan de omschrijving een andere administratie-identiteit
   bevat (naam_norm-match, ook afkortingen die de Beheerder eenmalig bevestigt) én die in de balansgroep RC/vorderingen/
   schulden op groepsmaatschappijen vallen (RGS-achtige heuristiek op nummer + `AccountType`; Odoo `account_type`
   asset_current/liability_current + naam). Resultaat `rc_koppeling` (administratie_a, rekening_a, administratie_b,
   rekening_b, basis, actief, bron afgeleid|mens) — paren waar alleen één kant gevonden is = oranje "RC zonder tegenrekening".
   Zelfde Beheerder-blok als A3 (tab/sectie "Rekening-courant").
2. Dagelijkse toets per paar: eindsaldo rekening_a in A (per vandaag NL-kalenderdag, `app/tijd.py`) = −eindsaldo rekening_b in B.
   Sluit → groen (teller). Sluit niet → bevinding `rc_sluit_niet` mét Δ én de VERKLARING: mutaties van beide kanten (venster
   sinds laatste groene stand, anders 400 dagen) paarsgewijs matchen op bedrag (tegengesteld teken) + datum ± 5 dagen +
   omschrijving-kern; wat overblijft = "ontbreekt bij B: 12-09 € 1.250,00 'huur september' (RLZ-05-00000412)" en/of
   "ontbreekt bij A: …". Meerdere kandidaten met hetzelfde bedrag = allemaal noemen, niet raden. Als de restlijst de Δ niet
   verklaart: "Δ € 0,37 niet herleidbaar tot losse mutaties — vermoedelijk afronding/koers; controleer handmatig".
3. Saldo lezen: RLZ `JournalEntryLines?$filter=Account/id eq …&$expand=JournalEntry` (som Debit−Credit, datumfilter als NL-dag in
   UTC — les 14-09 `Z`-shift), Odoo `account.move.line` read_group op account_id (posted). Cache de laatste groene stand per paar
   zodat het venster klein blijft (`rc_stand`, migratie).
4. Actiemail-regel: "Rekening-courant Kempen B.V. ↔ Kempen Facilities wijkt € 1.250,00 af — 1 mutatie ontbreekt bij Facilities".
   Sluit alles: geen regel (mail blijft kort), wél teller in het systeemrapport en op Inzicht › Reconciliatie.

## Blok D — plek in de bestaande keten
- Twee nieuwe blokken in `reconciliatie-alles` (ná documenten, vóór rlz_dubbel), eigen tellers, eigen `--alleen intercompany|
  rekening_courant --lees-only` meetlat in de nameting-allowlist (`scripts/gcp/nameting.sh`), opgenomen in de dagelijkse
  nameting-workflow.
- Inzicht › Reconciliatie: bevindingen mét handeling zoals bestaand (geen nieuwe pagina); filter Groep werkt (KP7).
- Omgevallen blok (RLZ-blokkering, credential kapot) = blok-fout zichtbaar, andere blokken lopen door.
- Actiemail: regels volgen het bestaande patroon (max 10 + "en N andere"); guard `test_actiemail_guard.py` uitbreiden met de
  nieuwe soorten (mensentaal, geen id's/jargon).

## Tests / af
- Unit: relatie-afleiding (kvk > btw > naam; zelfde KvK bij twee administraties = beide IC), match-volgorde, creditnota's,
  verrekenparen, "onderweg in module" ≠ bevinding, RC-verklaring (1 ontbrekend, 2 kandidaten zelfde bedrag, niet herleidbaar).
- Backend-agnostisch: één test met RLZ↔Odoo-paar via gemockte ports.
- Querytelling-meetlat: aantal RLZ-calls per administratie onafhankelijk van het aantal documenten (filter server-side).
- Gouden set niet geraakt (geen intake/controlescherm) — keten-guard blijft groen; wél `test_rapporten_index`, CLAUDE.md-guard.
- Migratie(s) volgens afsluitroutine. BESLISSINGEN nieuwe sectie "INTERCOMPANY-FACTUURMATCH + RC-AANSLUITING (Peter 16-09)",
  CLAUDE.md één verwijsregel, WAT_IS_NIEUW-blok, rapport `docs/rapporten/2026-09-16-intercompany-rc.md` + INDEX mét meetrecept
  (eerste nameting: aantal afgeleide IC-paren, RC-paren, bevindingen per soort; verwachting: KF-doorbelastingsparen 100 % groen).
- Werkt in productie: niet gemeten (meetrecept), tenzij de nameting binnen de run mogelijk is.

## Beslispunten (default kiezen, doorgaan, noteren in `docs/rapporten/2026-09-16-beslispunten-peter.md`)
1. Venster 400 dagen (default) of vanaf boekjaar 2025?
2. RC-datumtolerantie ± 5 dagen (default) — bank-overboekingen tussen groepsmaatschappijen kunnen langer duren rond
   maandeinde; 10 dagen als alternatief.
3. Naam-only-relaties: alleen rapporteren (default) of na 1× Beheerder-bevestiging actief.
4. IC-status-verschil pas ná 7 dagen (default) — of direct.
