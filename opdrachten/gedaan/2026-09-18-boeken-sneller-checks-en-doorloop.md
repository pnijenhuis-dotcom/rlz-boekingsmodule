uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-boeken-sneller.md

Domeinen: werkvoorraad-controlescherm, autoboeken-ai, duplicaten-crediteuren, werkloop-productie, kantoor-frontend

# OPDRACHT 18-09 — Boeken sneller: checks in < 1 s zichtbaar, "Boeken in RLZ" = direct door naar de volgende (Peter 18-09)

**Peter 18-09 (letterlijk):** "als ik nu een factuur boek duurt het lang voordat alle controles groen worden (4 à 5 seconden). Als ik
daarna druk op Boeken in RLZ duurt het weer 4 à 5 seconden voordat ik bij de volgende boeking terecht kom. Vooral deze stap moet
sneller: meteen weg (backend draait rustig door) en mij de volgende boeking binnen een seconde geven."

## Diagnose Cowork (code 18-09 — verifieer met metingen vóór je bouwt, zie stap 0)
1. **Checks bij openen/wijzigen** (`boekvoorstel.voer_checks_uit`, `useAutoChecks.ts`): élke run opent een RLZ-client en doet live
   RLZ-calls in serie: `Vendors/{id}/BankRelations` (IBAN-seed, `leverancier_iban.seed_en_baseline_voor_checks`), per crediteurrecord
   van het dedup-cluster `find_purchase_invoices_by_reference`, plus de kandidatenquery ± 60 dagen (`extern_bestaan.zoek_extern_bestaand`).
   Drie tot zes RLZ-roundtrips à ~0,7–1,5 s in serie = de 4–5 s. De debounce herhaalt dat volledig bij élke wijziging, ook als alleen de
   omschrijving verandert (die raakt geen enkele externe check).
2. **Boeken** (`router.document_boeken` → `orkestratie.boek_document_met_doorbelasting` → `boeken.boek_document`): synchroon in één
   request: (a) `voer_checks_uit` NOGMAALS mét dezelfde live RLZ-calls (~4 s), (b) `rlz_inkoop.boek_inkoopfactuur` = PUT + /Uploads (PDF
   base64) + actie 17 + GET terug (~2–4 s), (c) doorbelasting, webhook-opslag, mini-voorraad, verplichting-verrekening (DB, snel), (d)
   post-commit template-leren + autoboek-activering (snel). Daarna haalt de frontend (`DocumentDetailScreen.naVerwerking`) de VOLLEDIGE
   documentenlijst opnieuw op om het volgende document te kiezen — terwijl `positie.volgende` uit de lijstcontext al bekend is — en het
   volgende document start bij openen wéér de checks van punt 1. Peter ziet dus: 4 s (checks) + 3 s (RLZ-write) + lijst + 4 s (checks
   volgende) — precies zijn beleving.

## Uitgangspunten (hard, onveranderd)
- Harde checks blijven blokkerend en server-side ("nooit de client-kant vertrouwen") — ze worden alleen niet twee keer met dezelfde
  externe data gedraaid. Geld in code, geen shortcut op idempotentie (client-GUID + eigen duplicaatquery vóór élke PUT).
- Niets verdwijnt stil: een boeking die op de achtergrond mislukt = zichtbare status `boeken_mislukt` in de werkvoorraad + retry, zoals
  nu al voor API-fouten. Peter accepteert daarmee: een RLZ-fout zie je niet meer als pop-up op het scherm, maar als rode rij in de lijst
  (plus toast als je nog op de lijst staat). Dat is het bestaande principe 4, geen nieuw besluit.

## Stap 0 — Feiten eerst: meten (zelfde run, vóór het bouwen)
Server-Timing per stap in de checks- én boek-route (`checks.lokaal`, `checks.ibanseed`, `checks.duplicaat`, `checks.kandidaten`,
`boek.put`, `boek.upload`, `boek.actie17`, `boek.get`, `boek.db`) als `Server-Timing`-header + gestructureerde log; meting in productie
op 10 échte boekingen (lees-only via de logs, nameting-SA) → tabel in het rapport. De stappen 1–3 hieronder bouw je hoe dan ook; de
metingen bewijzen achteraf waar de winst zit en zijn de nulmeting voor "werkt in productie".

## Stap 1 — Checks: extern één keer, lokaal direct
1. **Split de checks in lokaal en extern.** Lokaal (verplichte velden, regeltelling, vervaldatum, btw/centen, project verplicht,
   betaalstatus, module-duplicaat uit onze eigen DB) draait synchroon en is in < 300 ms terug — de check-rijen tonen dat meteen. Extern
   (IBAN-seed/BankRelations, RLZ-/Odoo-duplicaatquery, kandidaten ± 60 dagen) draait alleen als de **externe vingerafdruk** verandert:
   hash van (vendor_id/cluster, referentie genormaliseerd, factuurdatum, totaal, factuur-IBAN). Omschrijving, grootboek, project,
   btw-code wijzigen → geen externe run. Rijen tonen tot dan de vorige externe uitkomst mét tijdstip ("gecontroleerd 14:02").
2. **Externe calls parallel** (ThreadPool, max 4) i.p.v. in serie: BankRelations, referentie-queries per crediteurrecord en kandidaten
   tegelijk; RlzClient-throttling blijft gerespecteerd (één client, rate-limit-bewust).
3. **Extern rapport persistent** (nieuwe kolommen op het boekvoorstel of aparte tabel `check_extern_cache`: document, vingerafdruk,
   rapport-JSON, gecontroleerd_op, backend). Geldigheid: zelfde vingerafdruk én ≤ 15 min oud. **Bij boeken**: hetzelfde rapport
   hergebruiken als de vingerafdruk gelijk is en ≤ 15 min oud — anders (of bij `boeken_mislukt`-retry, of autoboek-pad) altijd verse
   externe run. Guard-test: voorstel gewijzigd in een extern veld → boeken draait de externe checks opnieuw; gewijzigd in omschrijving →
   hergebruik. Documenteer in `docs/regels/autoboeken-ai.md` (harde checks) en `duplicaten-crediteuren.md`.
4. **Volgende document voorverwarmen**: bij het openen van document X bepaalt de frontend al `positie.volgende`; roep voor dat document
   `POST …/boekvoorstel/checks?voorverwarm=1` aan (alleen extern + cache, geen opslaan, lage prioriteit, max 1 tegelijk). Wie doorloopt
   vindt de externe uitkomst al klaar. Aan/uit via setting `checks_voorverwarmen` (default aan), meetteller in de reconciliatiemail
   (verwacht/gedaan/overgeslagen — geen stille no-op).
5. `useAutoChecks`: debounce naar 400 ms, lokale checks direct, externe checks alleen bij vingerafdruk-wijziging; `checksBezig` splitst
   in "lokaal klaar / extern bezig" zodat de knop Boeken al groen kan zijn zodra alles wat wél moet groen is en de externe uitkomst
   vers is.

## Stap 2 — Boeken: direct door, schrijven op de achtergrond
1. **Synchroon deel (< 500 ms, DB-only)**: scope/rol, statusmachine, accorderingspoort (`AccorderingVereist`), match-/materiaal-
   afwijking-bevestiging (409's blijven synchroon — die vragen een menselijke keuze), doorbelasting-checks (DB), lokale harde checks,
   extern rapport uit cache (stap 1.3; is er géén geldig rapport → wél synchroon extern draaien, dan duurt deze ene keer langer, nooit
   stil overslaan). Groen → status **`wordt_geboekt`** (nieuwe status in de statusmachine, tussen `klaar_om_te_boeken` en `geboekt`;
   overgangen: → `geboekt`, → `boeken_mislukt`; niet bewerkbaar, niet nog eens te boeken, wél te bekijken) + audit + antwoord 202 met
   `{document_id, status: 'wordt_geboekt', volgende_document_id}` (de server kiest het volgende document met exact de
   `kiesVolgendDocument`-regels, zodat de frontend geen lijst hoeft op te halen).
2. **Achtergrond-schrijver**: nieuwe wachtrij `BoekWachtrij` naar het patroon van `wachtrij.py` (contract: enqueue(administratie_id,
   document_id, boek_cyclus, actor_id)). Cloud-implementatie: **Cloud Tasks** (per document één taak, taaknaam deterministisch =
   idempotency-key `boek-{document_id}-{boek_cyclus}`, doel = een interne route op de service met OIDC-token — draait als request, dus
   CPU zonder `--no-cpu-throttling`; retry met backoff max 5, dan `boeken_mislukt`). Valt Cloud Tasks om welke reden dan ook niet binnen
   deze run te bewijzen: het bestaande job-triggerpatroon (`CloudRunJobExtractieWachtrij`) als gelijkwaardig alternatief mét
   scheduler-vangnet elke 2 min; benoem de keuze in het rapport. Dev = in-process thread zoals nu. De worker doet exact het huidige
   `boek_document` vanaf de RLZ-write (PUT + Upload + 17 + GET + de DB-afwikkeling in één transactie + post-commit stappen), mét de
   bestaande client-GUID en de eigen duplicaatquery direct vóór de PUT (die blijft, is één call).
3. **Vangnetten**: startup-/scheduler-herstel voor documenten die > 10 min op `wordt_geboekt` staan (opnieuw enqueue; is de RLZ-PUT al
   gelukt → verder vanaf actie 17 — idempotent via GUID + `GET PurchaseInvoices/{guid}`); reconciliatie-blok documenten telt
   `wordt_geboekt` > 10 min als bevinding mét actie "Opnieuw proberen"; dagtellers (ingediend/geboekt/mislukt) in de reconciliatiemail.
4. **Frontend**: op 202 → toast "Wordt geboekt in RLZ — je gaat door naar ‹volgende›" + direct `navigate` naar `volgende_document_id`
   (geen lijst-fetch meer; geen volgende → lijst mét filter). In de documentenlijst: rij-status "Wordt geboekt…" (grijs, spinner-dot),
   verandert live naar "Geboekt · boekstuk RLZ-…" of rood "Boeken mislukt — ‹reden› · Opnieuw" (polling elke 5 s zolang er rijen
   `wordt_geboekt` zijn, of SSE als dat al bestaat). Toast bij mislukking als de gebruiker nog in dezelfde administratie zit.
   Doorbelasting-spiegel en webhook lopen in de worker; hun uitkomst landt in de tijdlijn zoals nu.
5. **Autoboek-pad en accordering-staande-goedkeuring** gebruiken dezelfde worker (één schrijfroute), maar zonder de 202-shortcut
   (zij hebben geen wachtende mens).

## Stap 3 — Doorloop zonder omweg
- `naVerwerking` gebruikt `volgende_document_id` uit het antwoord (fallback: `positie.volgende` uit de lijstcontext; pas als beide
  ontbreken de lijst ophalen). Detail van het volgende document **prefetchen** zodra het huidige geopend is (één GET, cache 60 s), zodat
  de navigatie < 1 s voelt; PDF-preview idem lazy maar gestart.
- Doelmeting: klik "Boeken in RLZ" → volgende document zichtbaar mét lokale checks groen ≤ 1 s (p95), externe check-rijen ≤ 1,5 s bij
  voorverwarmd, RLZ-boeking gereed in de lijst ≤ 15 s (p95).

## Guards & tests
Statusmachine-tests voor `wordt_geboekt` (geen dubbele boeking, geen bewerken, herstelpaden); idempotentie-test worker 2× dezelfde taak
= één RLZ-document; vingerafdruk-tests (welke velden wél/niet extern); cache-verval-test; test "geen geldig extern rapport bij boeken →
synchroon extern"; RLS/rolpoort op de interne worker-route (alleen OIDC-SA); reconciliatie-bevindingssoort start in `meten` (regel);
vitest op `naVerwerking` (geen lijst-fetch bij `volgende_document_id`), prefetch; `tsc -b`, contrast, overflow-sweep. Gouden set groen.

## Afronding
Migratie (status-enum + cache-tabel), migratie-routine volledig. WAT_IS_NIEUW ("Boeken gaat nu direct door naar de volgende factuur;
de boeking in RLZ loopt op de achtergrond en je ziet in de lijst wanneer hij klaar is"). `docs/regels/werkvoorraad-controlescherm.md`
volledige tekst (wordt_geboekt, doorloop, voorverwarmen) + `autoboeken-ai.md` (harde checks: cache-regel) + BESLISSINGEN "BOEKEN SNELLER —
CHECKS-CACHE + ACHTERGROND-SCHRIJVER (Peter 18-09)" + CLAUDE.md één verwijsregel. Rapport `docs/rapporten/2026-09-18-boeken-sneller.md`
+ INDEX + Gelezen regels; nul- en nameting (stap 0-tabel vóór/ná op 10 boekingen in productie) — "werkt in productie: ja/nee".
Één regel voor Peter: wat hij merkt en waar hij een mislukte boeking terugvindt.
