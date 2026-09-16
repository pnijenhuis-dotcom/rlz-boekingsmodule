# Rapport 16-09 — Intercompany-factuurmatch + rekening-courant-aansluiting als dagelijkse reconciliatieblokken (Peter 16-09)

Opdracht: `opdrachten/gedaan/2026-09-16-intercompany-factuurmatch-en-rc-aansluiting.md`. Canoniek: BESLISSINGEN "INTERCOMPANY-
FACTUURMATCH + RC-AANSLUITING (Peter 16-09)". Migratie 0148. **Werkt in productie: NIET GEMETEN** (geen deploy binnen de run;
meetrecept onderaan). Alles lees-only richting RLZ/Odoo; geen enkele write, geen actie.

## Wat er staat

**Blok A — fundament (afgeleid, niet ingevoerd).** Per administratie leest de stamgegevens-sync de identiteit uit de bron (RLZ
`AdministrationSettings`: bedrijfsnaam + KvK + SBI — STAP-0 16-09 bewees dat `Administrations` géén KvK/btw draagt en RLZ het
btw-nummer van de administratie nergens geeft; Odoo `res.company`: naam/vat/company_registry) in `administratie_identiteit`.
Daarna worden crediteuren (vendor-cache + kenmerken) en debiteuren (live `Customers`, één call per administratie) gematcht op
KvK > btw > genormaliseerde naam tegen de identiteiten van de ÁNDERE administraties → `intercompany_relatie` (richting, basis,
status afgeleid/bevestigd/uitgesloten). Bestaande doorbelasting-IC-rijen komen als basis 'doorbelasting'/bevestigd mee; naam-only
telt pas mee ná bevestiging. RC-koppelingen: balansrekeningen waarvan de naam een andere administratie (of een Beheerder-afkorting
zoals "KF") als heel woord noemt, over en weer gepaard; eenzijdig = "RC zonder tegenrekening". Beheerder-blok "Intercompany-relaties"
+ "Rekening-courant" op Instellingen › Boeken (bevestigen / uitsluiten mét reden / afkortingen / "Nu afleiden"). De oude IC-vlag
(`doorbelasting/intercompany.py`) leest ongewijzigd via de nieuwe module.

**Blok B — factuurmatch (`intercompany`).** Per actief paar: verkoopfacturen van A aan B (RLZ SalesInvoices server-side op
Entity + venster 400 d; Odoo out_invoice/out_refund) ↔ inkoopfacturen bij B van A (RLZ `find_purchase_invoices_kandidaten`; Odoo
in_invoice/in_refund). Verrekenparen (factuur + credit) eerst samengevouwen; match op nummer (genormaliseerd, heel token) >
bedrag + datum ± 7 d > bedrag-only (stil). Bevindingen mét handeling bij de juiste kant: `ic_ontbreekt_bij_ontvanger` (niet als de
factuur bij B nog in de module onderweg is), `ic_ontbreekt_bij_verkoper`, `ic_bedrag_verschilt` (beide bedragen + Δ),
`ic_status_verschilt` (concept > 7 dagen). Doorbelasting-spiegelparen MOETEN groen zijn: rood = systeemfout zonder administratie
(systeemmail) + audit `automatisering_regressie` — de bewijslast van de doorbelastingsmotor. Webfilter = "RLZ-blokkering — meting
ongeldig" zonder bevindingen; geen credential/koppeling = zichtbaar overgeslagen. Querytelling: calls per administratie alleen
afhankelijk van paginering, nooit van het aantal facturen.

**Blok C — rekening-courant (`rekening_courant`).** Per actieve koppeling: saldo A (Σ Debit − Σ Credit over `JournalEntryLines`
op de rekening; Odoo `account.move.line` posted) + saldo B = 0 → groen (+ `rc_stand`). Anders `rc_sluit_niet` mét Δ én de
verklaring: mutaties van beide kanten sinds de laatste groene stand (anders 400 d) paarsgewijs gematcht op bedrag tegengesteld
± 5 dagen + omschrijving-kern; wat overblijft = "ontbreekt bij B: 12-09 € 1.250,00 'huur september'" — meerdere kandidaten met
hetzelfde bedrag worden allemaal genoemd, sluit de restlijst de Δ niet dan "niet herleidbaar — vermoedelijk afronding/koers".
Actiemailregel: "Kempen B.V. — Kempen B.V. ↔ Kempen Facilities B.V. — RC wijkt € 1.250,00 af". Sluit alles: geen regel, wél teller.

**Blok D — keten.** Blokvolgorde bank → documenten → intercompany → rekening_courant → omzet → doorbelasting → rlz_dubbel;
`--alleen intercompany|rekening_courant --lees-only` als meetlat (allowlist-regel bestond al voor `reconciliatie-alles`); de
dagelijkse nameting-workflow draait `reconciliatie-alles --lees-only` en dekt de blokken automatisch. Teksten in mensentaal
(`teksten.py`), actiemail-guard uitgebreid, `BLOK_LABEL` +2, Inzicht › Reconciliatie toont de bevindingen zoals bestaand (filter
Groep werkt via de administratie-facet).

## Tests

- Blok A `tests/intercompany/test_relaties.py` 19; afhankelijke suite (doorbelasting/accordering/bank-IC/keten n/rol-matrix/
  proxy-prefixes/metadata-guard) 481 groen; frontend `IntercompanyRelaties.test.tsx` + registry + proxyDekking 117 groen,
  overflow-sweep `/instellingen/boeken` 8 metingen groen.
- Blok B `tests/intercompany/test_factuurmatch.py` + teksten + actiemail-guard 106 groen; `test_run.py` 25 groen.
- Blok C `tests/intercompany/test_rekening_courant.py` (34) + teksten + guard 98 groen.
- Coördinator: `tsc -b` groen; frontend instellingen/reconciliatie/changelog/dev 286 groen; lokale uvicorn: zes
  `/intercompany/*`-routes in de openapi, zonder token 401. Volledige backend-suite: zie het slotrapport van de run.
- Afsluitroutine 0148: dev-upgrade 0147 → 0148 gedraaid, `alembic check` schoon, schema-dump ververst ná de volledige suite.

## Beslispunten (default gekozen, zie `2026-09-16-beslispunten-peter.md`)

1. Venster 400 dagen (niet "vanaf boekjaar 2025"). 2. RC-tolerantie ± 5 dagen. 3. Naam-only-relaties alleen rapporteren tot een
Beheerder bevestigt. 4. IC-status-verschil pas ná 7 dagen. 5. RC-herkenning zonder "≥ 2 tokens"-eis ("Kempen B.V." = één woord);
te ruim → afkortingen als enige bron voor korte namen. 6. Handmatige IC-leveranciers zonder doorbelasting-mapping krijgen geen
relatie (KvK op de crediteur in RLZ zetten lost dat op). 7. Verrekend paar zonder tegenkant = teller, geen bevinding.
8. RLZ-mutaties in de RC-verklaring zonder boekstuknummer (JournalEntry geeft alleen id/BookDate/DocumentType/EventID).

## Meetrecept ná deploy (werkt in productie: ja/nee)

1. `sync-alles`-log (of `POST /intercompany/afleiden` als Beheerder): regels "identiteiten: gelezen=N", "relaties: nieuw=…",
   "rc-koppelingen: nieuw=… zonder_tegenrekening=…"; verwachting: KF-doorbelastingsparen als basis 'doorbelasting'/bevestigd,
   Universal Verkoop (Odoo) ↔ Universal Nederland/Steigerbouw als kvk-relaties.
2. `scripts/gcp/nameting.sh reconciliatie-alles --alleen intercompany --lees-only`: aantal handelsrelaties, per relatie
   "N verkoop / M inkoop gelezen, K gematcht", spiegelparen 100 % groen, geen "RLZ-blokkering".
3. `scripts/gcp/nameting.sh reconciliatie-alles --alleen rekening_courant --lees-only`: aantal koppelingen, per koppeling sluit/Δ +
   verklaring, calls per rekening (of `@odata.count` op JournalEntryLines terugkomt → noteren in api-verkenning).
4. Instellingen › Boeken: blok Intercompany-relaties gevuld; Inzicht › Reconciliatie toont blokken "Intercompany" en
   "Rekening-courant"; actiemail bevat de zaken mét handeling.
