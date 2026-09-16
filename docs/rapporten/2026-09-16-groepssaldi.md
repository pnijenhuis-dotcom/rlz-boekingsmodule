# Rapport 16-09 — Groepssaldi debiteuren/crediteuren per groep (lees-only)

**Opdracht:** `opdrachten/gedaan/2026-09-16-groepssaldi-debiteuren-crediteuren.md` (Peter 16-09 09:20). Migratie **0149**
(cache-tabel `groep_saldo_stand`). **Werkt in productie: niet gemeten** — meetrecept onderaan; de uitvoer van dat recept is
Peters antwoord.

## Gedaan
1. **Motor `app/groepen/saldi.py`** — rekeningen uit de bron (RLZ RGS `BVorDeb…`/`BSchCre…` via `Ledgers?$expand=SystemAccountList`,
   anders naam; Odoo `account_type`), saldo Σ Debit − Credit (crediteuren als positieve schuld), peildatum als NL-dag in UTC
   (`nl_dag_einde_utc`), IC = open posten (RLZ `BaseRemainingAmount` Status 2 / Odoo `amount_residual_signed`) op IC-entity's met
   een tegenpartij in de groep; statussen ok/geen_rekening/ongeldig(webfilter)/fout/overgeslagen; totalen alleen over `ok`.
2. **CLI `groep-saldi --groep <naam|code|id> [--datum]`** (lees-only, live, in `scripts/gcp/nameting.sh`) — tabel per administratie
   (deb. bruto/IC/zonder IC, cred. idem, status) + totalen + herkende rekeningen; groep onbekend = leesbare melding, exit 2.
3. **Nachtelijke stand** in `sync-alles` (`meet_en_schrijf_alle`, ná de intercompany-stap): per administratie in een actieve groep
   één upsert-rij per dag; fouten per administratie in het sync-rapport, nooit een stop.
4. **Route `GET /groepen/{id}/saldi`** (kantoorrol) + **kaart `GroepSaldiKaart`** op de klantenlijst zodra `?groep=` actief is:
   "stand van vannacht (dd-mm)", drie kolommen, uitklap per administratie, "N van M administraties in je scope" (RLS op de cache),
   "nog geen stand" en 404-tekst leesbaar; geen verversknop.
5. **Tests:** `tests/groepen/test_saldi.py` 10 groen; `GroepSaldiKaart.test.tsx` 3 groen; WerkvoorraadScreen-tests groen;
   rol-matrix + sweep 471 groen; migratie-guard groen; tsc groen.
6. **Migratie-routine:** `make migrate` gedraaid op de dev-DB (alembic current = 0149 head); live 200 op `GET /groepen/{id}/saldi`
   én `PUT /groepen/{id}/administraties` (uvicorn 8011, Beheerder-token; dev-DB had geen groep → testgroep "TESTLIVE" aangemaakt
   via de API); `backend/migrations/schema_referentie.sql` ververst (+54 regels).
7. Docs: BESLISSINGEN "GROEPSSALDI DEBITEUREN/CREDITEUREN (Peter 16-09)", CLAUDE.md-verwijsregel, WAT_IS_NIEUW, beslispunten.

## Afwijking van de opdrachttekst
De opdracht noemde `Account.UseForSalesInvoiceDetails`/`UseForPurchaseInvoiceDetails` als bron-vlaggen. Die markeren in RLZ de
rekeningen die als DETAILREGEL op een verkoop-/inkoopfactuur mogen (omzet/kosten; api-verkenning: 4404 "Kosten mobiele telefonie"
heeft `UseForPurchaseInvoiceDetails true`), niet de subadministratie debiteuren/crediteuren. Gekozen: RGS-code uit
`SystemAccountList` (bewezen aanwezig op de collectie mét expand, 14-09) met naam-terugval. Zie beslispunten.

## Meetrecept ná deploy
```
scripts/gcp/nameting.sh groep-saldi --groep "Kempen groep"          # zodra Peter de groep heeft toegewezen (bulk-dialoog)
scripts/gcp/nameting.sh groep-saldi --groep "Kempen groep" --datum 2026-08-31   # optioneel: peildatum maandeinde
```
Verwacht: per administratie status `ok` met herkende rekeningen (bv. "1300 Debiteuren · 1600 Crediteuren"), totalenregel, en
bruto = zonder IC + IC. Een `ongeldig`-rij = RLZ-webfilter → later opnieuw. De kaart toont dezelfde cijfers vanaf de eerste
`sync-alles` ná deploy (07:00). Werkt in productie: niet gemeten.
