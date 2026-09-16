> uitgevoerd 2026-09-16, rapport: docs/rapporten/2026-09-16-groepssaldi.md

# OPDRACHT 16-09 — Groepssaldi debiteuren/crediteuren per groep, lees-only (vraag Peter 16-09)

**Aanleiding (Peter 16-09 09:20):** "kan jij voor mij van de Kempengroep een huidig saldo van de (cumulatieve) debiteuren en
crediteuren geven?" — Cowork kan niet bij RLZ/productie; de module kan dit wél en hoort het te kunnen tonen. Bouwt voort op de
zojuist afgeronde opdracht `2026-09-16-intercompany-factuurmatch-en-rc-aansluiting.md` (identiteiten, IC-relaties,
saldo-leesroutes, `rc_stand`) en het groepskenmerk (BESLISSINGEN "GROEPSKENMERK OP ADMINISTRATIE").

## Te doen (lees-only, geen writes, geen migratie tenzij een cache-tabel nodig is)
1. Saldo per administratie per vandaag (NL-dag, `app/tijd.py`) op de debiteuren- en crediteurenrekeningen — rekeningen uit
   de bron-vlaggen (RLZ `Account.UseForSalesInvoiceDetails`/`UseForPurchaseInvoiceDetails` + AccountType/subadministratie;
   Odoo `account_type` asset_receivable/liability_payable), nooit hardgecodeerd 1300/1600. Bron: `JournalEntryLines`
   Debit−Credit met datumfilter als NL-dag in UTC (les 14-09) / Odoo `account.move.line` read_group posted. Webfilter-
   blokkering = "meting ongeldig" per administratie, geen fout in het totaal.
2. Twee kolommen: BRUTO (som over de administraties in de groep — dat is Peters "cumulatief") en ZONDER INTERCOMPANY
   (vorderingen/schulden op groepsmaatschappijen — uit `intercompany_relatie` — apart getoond en uit het totaal gehaald).
   Ook de IC-post zelf tonen als derde kolom, zodat bruto = zonder-IC + IC controleerbaar is.
3. Levering: (a) lees-only CLI `groep-saldi --groep <naam|code> [--datum JJJJ-MM-DD]` in de nameting-allowlist (tabel per
   administratie + totalen, geen debiteur-/crediteurnamen dus geen PII); (b) kaart "Groepssaldi" bovenaan de klantenlijst
   zodra het Groep-filter actief is (KP7: administratie = filter; lijstpatroon, geen nieuwe pagina, geen knop "verversen" —
   regel 08-09): debiteuren / crediteuren / per <datum>, mét de twee kolommen en een uitklap per administratie. Bron voor
   de kaart = de nachtelijke stand uit blok C van de IC/RC-opdracht (`rc_stand`-lezing uitbreiden met deze twee saldi, één
   extra call per administratie), label "stand van vannacht"; live lezen bij openen niet (76 administraties).
4. Groep bestaat nog niet → CLI en kaart melden dat leesbaar ("groep 'Kempen groep' niet gevonden — maak hem aan op
   Instellingen › Administraties"); nooit stil leeg.
5. Tests: saldo-berekening (Debit−Credit, datumgrens, ontbrekende rekening = "geen debiteurenrekening gevonden" per
   administratie), IC-eliminatie (bruto = zonder-IC + IC cent-exact), Odoo↔RLZ gemengd, RLS/scope (Boekhouding-rol ziet
   alleen administraties in eigen scope — de groepstotalen dan met "N van M administraties in je scope").
6. BESLISSINGEN "GROEPSSALDI DEBITEUREN/CREDITEUREN (Peter 16-09)", CLAUDE.md-verwijsregel, WAT_IS_NIEUW, rapport
   `docs/rapporten/2026-09-16-groepssaldi.md` + INDEX. Meetrecept ná deploy: `groep-saldi --groep "Kempen groep"` via
   `scripts/gcp/nameting.sh`; de uitvoer is Peters antwoord. Werkt in productie: niet gemeten.
