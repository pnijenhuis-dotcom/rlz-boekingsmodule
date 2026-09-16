# Slotrapport 16-09 (middag) — inbox afgewerkt, rij 2: acht opdrachten

**Opdracht Peter 16-09 middag:** `opdrachten/inbox/` één voor één afwerken (zes lopende opdrachten), aangevuld met de
vragen-dialoog-opdracht en de omzet-Receipts-opdracht. Regels: geen writes naar RLZ/Odoo (alleen lees-only productie via
`scripts/gcp/nameting.sh`), migraties volgens de afsluitroutine, beslispunt = default + notitie in
`2026-09-16-beslispunten-peter.md`, `git pull --ff-only` vóór élke commit-reeks, logische commits, rapport + INDEX per opdracht,
opdrachtbestand → `opdrachten/gedaan/` mét kopregel. Alle acht zijn gedaan; productie is nergens gemeten (deploy loopt via de
Stop-hook + GitHub Actions ná deze run), behalve de lees-only diagnose van opdracht 8.

| # | Opdracht | Status | Commits | Rapport | Werkt in productie |
| --- | --- | --- | --- | --- | --- |
| 1 | `2026-09-16-deploy-mailconfig-in-service-stap.md` | gedaan | `8b89bfb`, `25371a2` | `2026-09-16-deploy-envset.md` | niet gemeten (deploy ná deze run; smoketest toetst het mailkanaal live) |
| 2 | `2026-09-16-groep-bulk-toewijzen.md` | gedaan | `31b0452`, docs in `bdcbb30` + `6a63399` | `2026-09-16-groep-bulk.md` | niet gemeten |
| 3 | `2026-09-16-groepssaldi-debiteuren-crediteuren.md` | gedaan (migratie 0149) | `aac121b`, `bdcbb30` | `2026-09-16-groepssaldi.md` | niet gemeten |
| 4 | `2026-09-16-bank-zoekveld-boekstuknummer-batch.md` (blok B vervallen) | gedaan | `42f0968`, `bdcbb30` | `2026-09-16-bank-zoekveld-batch.md` | niet gemeten |
| 5 | `2026-09-16-documentenlijst-bulk-acties.md` | gedaan | `9b8fc21`, `e339630` | `2026-09-16-documentenlijst-bulk.md` | niet gemeten |
| 6 | `2026-09-16-omzet-coffeeshop-profx-journaal.md` (blokken A–G, mockup v2 = bouwnorm) | gedaan (migratie 0150) | `45374fc`, `58bfab3`, `6a63399` | `2026-09-16-omzet-profx.md` | niet gemeten |
| 7 | `2026-09-16-vragen-dialoog-open-houden.md` | gedaan | `7718e4d`, `6a63399` | `2026-09-16-vragen-dialoog.md` | niet gemeten |
| 8 | `2026-09-16-omzet-receipts-onder-uitgaven.md` | gedaan (diagnose lees-only gemeten) | `f76317d`, `3bd465e` | `2026-09-16-omzet-binder.md` | fix niet gemeten; diagnose wél |

## Kernuitkomsten per opdracht (één regel)
1. **Deploy-envset:** de service-stap zet alle 26 envs + 12 secrets in één keer (mail-envset ook op `rlz-kantoor-digest`), guards op
   volledigheid/scheidingstekens/beeld-uniformiteit, smoketest toetst het mailkanaal lees-only via de Cloud Run Admin API.
2. **Groep bulk:** `PUT /groepen/{id}/administraties` (Beheerder, één transactie, audit per administratie) + dialoog "Administraties
   toevoegen…" op de scope-lijst en bulk-actie in de administratielijst; overflow-sweep instellingen 56/56 groen (×2).
3. **Groepssaldi:** `groep-saldi --groep …` (lees-only, live) + nachtelijke stand `groep_saldo_stand` (RLS) + kaart op de
   klantenlijst bij een Groep-filter; drie kolommen bruto/zonder IC/IC.
4. **Bankscherm:** client-side zoekveld, matchmotor-stap 0 "betaalbatch" (PaymentBatchId == PaymentBatchInformation, N × actie 15
   via `…/afletteren-batch`), compacte koppelingstekst.
5. **Documentenlijst bulk:** `POST …/documenten/bulk` (verwijderen / type wijzigen / verplaatsen / afwijzen, uitkomst per rij) +
   selectie met shift-klik.
6. **ProfX-omzet:** herkenning op inhoud vóór de AI, parser per artikelgroep, margerapport = kostprijs (zelfde dag gebundeld,
   weekrapport als eigen document mét dekking), omzetscherm v2 naar de bouwnorm, klikbaar NETTO/BRUTO-kopje (ook inkoop), profiel
   "Winkel / kassa" (afgeleid + override, 0150), CLI `kassarapporten-in-inkoopstroom`; gouden set `ad_omzet_profx_journaal`.
7. **Vragen-dialoog:** wortel = beurt-gate alleen in de accordeur-app-UI; nu open voor beide kanten tot Afgehandeld, status afgeleid,
   "afgehandeld namens", "Heropenen", gebundelde meldingen, werkvoorraad-groepen op de afgeleide kant.
8. **Omzet onder Uitgaven:** diagnose = de Van Boxtel-omzetrapporten waren PurchaseInvoices (kassarapporten via de inkoopstroom),
   de Receipt-categorie was al Inkomsten; defensief: categorie op binder + harde check + keuze in het scherm; herstel: reconciliatie-
   bevinding `omzet_in_inkoopstroom` + "Herboeken als omzet…" (storno 19 achter de aangiftepoort + herclassificatie), CLI
   `omzet-binder-rapport`.

## Testbeeld (laatste run vóór de commits)
- Backend: gate-sweep + omzet/intake/documenten/keten/beheer/unit 2.523 + 63 groen (de 26 fixture-errors in de eerste achtergrondrun
  kwamen door een parallel gestarte pytest — herdraai 63/63 groen), omzet + reconciliatie + leesroutes 507 groen, gate-sweep 454 groen
  ná opdracht 8, doc-guards groen; `make migrate` 0148→0150 dev-DB, live 200 op de nieuwe routes, `schema_referentie.sql` head 0150.
- Frontend: `tsc -b` groen (pre-commit ×6), suites omzet/document/instellingen/vragen/accordeur/reconciliatie/changelog groen;
  overflow-sweep instellingen 56/56 (volledige sweep: 87 groen + Chrome-timeouts ná het gebruikers-harnas, geen overflow).

## Beslispunten
Alle defaults staan in `docs/rapporten/2026-09-16-beslispunten-peter.md` (opdrachten 1–11 van vandaag); de zwaarste: Edible
vrijgesteld mét bevestig-chip (6), legacy `beantwoord` niet omgezet + "namens" voor élke kantoorrol (7), leesroute
`DocumentCategories` buiten de probe-set + herstel via storno i.p.v. categorie-PUT (8), werkvoorraad-groep op de afgeleide kant (7).

## Meetrecepten ná deploy (volgorde)
1. **Deploy-check service én jobs** (`gcloud run services describe rlz-backend --format='value(spec.template.spec.containers[0].image)'`
   en `gcloud run jobs describe rlz-reconciliatie …`): zelfde beeld; smoketest-stap groen incl. mailkanaal.
2. **`scripts/gcp/nameting.sh groep-saldi --groep "Kempen groep"`** — zodra Peter de groep heeft toegewezen (opdracht 2: dialoog
   "Administraties toevoegen…" op Instellingen › Administraties › Groepen): per lid de drie kolommen + statusregel; de kaart op de
   klantenlijst toont de stand van vannacht ná de eerste `sync-alles`.
3. **`scripts/gcp/nameting.sh duplicaat-extern-rapport`** (alle administraties, lees-only): rapport "mogelijk eerder dubbel geboekt";
   verwachting Kempen Facilities/Hello Kitchen zoals in het rapport van de ochtendrun.
4. **Opdracht 6:** `kassarapporten-in-inkoopstroom --dagen 120` → De Bazar/Van Boxtel-documenten als `herclassificeren`/`melden (geboekt)`;
   daarna via "Type wijzigen → kassarapport" het omzetscherm mét 7 groepen, Σ € 10.998,16, kopje netto/bruto, chip "Winkel / kassa".
5. **Opdracht 8:** `omzet-binder-rapport --administratie "Van Boxtel"` → B-regels (RLZ-04-00000683..686) mét aangiftepoort-stand; ná de
   nachtelijke reconciliatie de bevindingen "Omzet als inkoopfactuur geboekt" mét "Herboeken als omzet…"; ná herstel A 0 · B 0.
6. **Opdracht 7:** Barbara/Sophia-thread: Sophia plaatst direct een tweede bericht; kantoor ziet "laatste bericht van Sophia";
   één gebundelde melding bij meerdere kantoorberichten (audit `vraag_accordeur_gemeld` mét `aantal_berichten`).
7. **Opdracht 4/5:** Bouwadvies Oost Nederland: zoekveld + batchvoorstel "betaalbatch …, N facturen"; documentenlijst: selectie + bulk.

## Niet gedaan / open
- Productiegedrag van 1–8 is niet gemeten (geen deploy binnen de run — regel Peter 08-09); de meetrecepten hierboven zijn de
  eerste stappen ná de deploy.
- Opdracht 8 blok C: geen automatische massale herboeking (Peter klikt per bevinding); een categorie-PUT op een geboekte
  SalesInvoice is niet als STAP-0 uitgevoerd (geen writes).
- Opdracht 6: het omzet-controlescherm heeft geen overflow-harnas (geen sweep-meting); de instellingen-pagina wél (56/56).
