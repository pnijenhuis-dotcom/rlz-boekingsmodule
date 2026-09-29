# Nameting Vastly-verkoop volledig automatisch ná deploy + échte heraanbieding 23 + 9 (ná Peters "ja") — werkt in productie: ja/nee

niet vóór: 2026-09-30 09:00
Domeinen: omzet, reconciliatie, werkloop-productie

Bron: rapport `docs/rapporten/2026-09-29-vastly-verkoop-automatisch.md` ("werkt in productie: niet gemeten"), BESLISSINGEN
"VASTLY-VERKOOP VOLLEDIG AUTOMATISCH — ENTITEITENREGISTER, OMZETREKENING PER ADMINISTRATIE, GEEN VERZAMELBAK (Peter 29-09)",
gespreksverslag 29-09. Regel 21-09: "niet gemeten" is een schuld mét vervaldatum.

## Stap 0 — deploy-check
`git rev-list --count main..origin/main` (merge --no-ff bij divergentie, nooit rebase); service ÉN jobs op de vastly-verkoop-commit van 29-09
of later (`gcloud run services describe rlz-backend` + `gcloud run jobs describe rlz-reconciliatie --format='value(spec.template.spec.template.spec.containers[0].image)'`).
Migratie 0172 gelopen (job `rlz-migratie` in de deploy). Niet live = opdracht terugleggen mét `niet vóór:` +1 dag (hoogstens drie pogingen).

## Stap 1 — dry-run kantoorbreed (lees-only, bot-bestand op main)
`gh workflow run nameting -f onderdeel=vastly-verkoop` → `verkenning/nameting-vastly-verkoop-<dd-mm>.txt`:
`vastly-verkoop-heraanbieden --dry-run` (verwacht vóór de echte run: TOTAAL 32 kandidaten = 23 open + 9 niet-gekoppeld; per uitkomst
`zou_boeken` voor de UBL's mét AccountingCost óf een afleidbare omzetrekening, `geweigerd` mét reden voor de rest, `entiteit_niet_gekoppeld 9`
voor Van Rooijen/Schaalje zolang de koppeling ontbreekt), `db-lezen vastly-verkoop` (runs/koppelingen/niet-gekoppeld/bevinding
`vastly_entiteit_niet_gekoppeld` uit de scheduler-run van 06:30) en `db-lezen vastly-verkoop-administratie` per vastgoed-administratie
(open documenten, omzetrekeningen bron historie — verwacht ná de eerste `haal_verkoop_voorstel_op`-lezing, autoboek-audits).
Leg de dry-run-telling per administratie en per uitkomst in het rapport, náást de verwachting (23 + 9).

## Stap 2 — klikpunten Peter (uitkomst in het rapport)
(a) Inzicht › Reconciliatie › blok "Vastly-verkoop": bevinding "Vastly-verhuurder niet gekoppeld: B. van Rooijen · 9 facturen" →
"Koppel aan administratie…" → B. van Rooijen / G. Schaalje (`c28dfbd0`) → melding "9 facturen zijn direct automatisch als omzet geboekt"
(of: N geboekt, rest mét reden op de rij ná de volgende run). (b) Peters "ja" op de dry-run → échte run:
`gcloud run jobs execute rlz-reconciliatie --region europe-west4 --args=-m,app.cli,vastly-verkoop-heraanbieden,--uitvoeren --wait`
(owner-sessie, regel 08-09 — nooit via nameting.sh) → job-log: TOTAAL/PER UITKOMST; daarna opnieuw stap 1 (verwacht: 0 kandidaten óf
alleen `geweigerd` mét reden = bevindingen `vastly_omzetrekening_ontbreekt`/`vastly_verkoop_niet_geboekt`). (c) Eventueel "Rekening kiezen"
per administratie × regelsoort (Beheerder) en "Opnieuw aanbieden" per document; request-log van de drie handelingen staat in het onderdeel.
Ongebruikt = `niet vóór:` +1 dag, hoogstens drie pogingen, daarna `mislukt/` mét het klikpunt.

## Stap 3 — bewijs "geen AI, geen verzamelbak"
`db-lezen ai-heraanbieding --param dagen=3` → 0 verkoopfactuur-documenten in de uitkomsten; verzamelbak-telling (Cowork `/verzamelbak`) toont
geen Vastly-UBL's meer; reconciliatiemail van 30-09: dagteller "Vastly-verkoop automatisch (heraanbieding …)" verwacht/gedaan/overgeslagen.

## Definitie van af
Rapport `docs/rapporten/<datum>-nameting-vastly-verkoop-na-deploy.md` + INDEX + "Gelezen regels", BESLISSINGEN-alinea "Gemeten <datum>" in de
sectie hierboven (werkt in productie: ja/nee per onderdeel: intake-routering via register, heraanbieding, bevindingen + handelingen, UBL-AI-guard),
regels-alinea als het oordeel iets verandert (omzet.md), gespreksverslag, opdracht → gedaan/. Beslispunt Peter uit het bouwrapport
meenemen: werkvoorraad-tellers per administratie voor geweigerde Vastly-documenten (nu ongewijzigd).
