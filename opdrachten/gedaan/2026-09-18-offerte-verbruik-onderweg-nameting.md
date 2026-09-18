uitgevoerd 2026-09-18, rapport: docs/rapporten/2026-09-18-offerte-verbruik-onderweg-nameting.md (werkt in productie: ja; kaarttekst stap 4 = klikpunt Peter)

> **Teruggelegd 2026-09-18 21:15 door de nameting-run (rapport `docs/rapporten/2026-09-18-offerte-verbruik-onderweg-nameting-uitgesteld.md`):**
> stap 0 faalde omdat de bugrun de fix (migratie 0166) nooit gecommit had; die run heeft het werk geverifieerd en alsnog gecommit,
> de Stop-hook pusht en de deploy volgt. **Aanscherping stap 0 voor de volgende run:** zoek de deploy-run op de commit mét
> `0166_verplichting_match_index_verplichting` (`gh run list --workflow deploy.yml --limit 5`); LOOPT die nog → `gh run watch <id>`
> (max 20 min) en dan pas service én jobs toetsen; alleen rood of afwezig = stoppen, melden, terug in de inbox mét gewiste
> `opdrachten/log/<slug>.pogingen`. Stappen 1–4 zijn nog niet uitgevoerd.

Domeinen: verplichtingen-projecten-voorraad, werkloop-productie

# OPDRACHT 18-09 — Nazorg + nameting ná deploy: offerte-verbruik = geboekt + onderweg (casus Bouwadvies 32949)

Vervolg op `docs/rapporten/2026-09-18-bug-offerte-verbruik-telt-onderweg-facturen.md` (werkt in productie: niet gemeten). Eén
schrijvende stap (de nazorg-CLI op de job-image), de rest lees-only. Nooit een lokaal proces tegen de productiedatabase.

## Stap 0 — deploy-check (service ÉN jobs)
`gh run list --workflow deploy.yml --limit 3` → de run op de commit mét migratie 0166 groen incl. migratie-job
(`Running upgrade 0165 -> 0166`) en smoketest; `gcloud run services describe rlz-boekhouding …` én `gcloud run jobs describe rlz-sync
--format='value(template.template.containers[0].image)'` op dezelfde image. Niet live = stoppen, melden, opdracht terug in de inbox.

## Stap 1 — nazorg dry-run (lees-only, job-image)
`gcloud run jobs execute rlz-sync --region europe-west4 --wait --args="-m,app.cli,verplichting-match-herberekenen,--administratie,a265c010-91ee-4b72-a5d6-48ddb67652f4,--dry-run"`
→ verwacht "3 open gematchte factu(u)r(en)" (32948 € 20.000, 32949 € 50.000, 33122 € 80.000, alle `binnen`, verbruik_na = eigen
bedrag) en "Totaal: 3 kandidaten, 0 herberekend". Afwijkend aantal = eerst verklaren (nieuwe factuur? geboekt/afgewezen?) vóór stap 2.

## Stap 2 — nazorg uitvoeren (SCHRIJVEND, alleen matchrijen)
Zelfde commando zonder `--dry-run` → verwacht "3 herberekend, 3 gewijzigd", per regel `verbruik_na … → 150000.00 (onderweg 100000.00,
2 facturen)`. Daarna kantoorbreed (alle administraties) éérst `--dry-run` zonder `--administratie` → aantal noteren → uitvoeren.

## Stap 3 — nameting leesreplica (lees-only)
`scripts/gcp/db_lezen.sh "SELECT m.document_id, b.referentie, d.status, m.uitkomst, m.verbruik_voor, m.verbruik_na,
m.details->>'verbruik_onderweg' AS onderweg, m.details->>'onderweg_aantal' AS n FROM boekhouding.verplichting_match m JOIN
boekhouding.document d ON d.id=m.document_id LEFT JOIN boekhouding.boekvoorstel b ON b.document_id=m.document_id WHERE
m.verplichting_document_id='34aaf45b-69b7-41e8-93d7-dbcf1f84c08d' ORDER BY b.referentie" --als 2f2262cd-0423-4910-b7b5-335ba37a6ef5
--administratie a265c010-91ee-4b72-a5d6-48ddb67652f4` → 32949: verbruik_na 150000.00, onderweg 100000.00, n 2 (mits de statussen
ongewijzigd zijn; is er inmiddels geboekt/afgewezen, herleid de verwachting uit de statussen: geboekt → boekstand, afgewezen → weg).

## Stap 4 — kaarttekst (klikpunt Peter of testaccount in de accordeur-app / kantoor-controlescherm 32949)
"✓ Binnen de goedgekeurde offerte zonder nummer · Deze factuur van € 50.000,00 (Ne termijn) past. · € 150.000,00 van € 1.192.922,50 ·
waarvan € 100.000,00 nog niet geboekt (2 facturen ter accordering)"; balk: onderweg gearceerd, deze factuur gemarkeerd.
Inzicht › Verplichtingen: rij Bouwadvies zonder nummer toont "geboekt € 0,00 · onderweg € 150.000,00 · restant € 1.042.922,50".

## Afronding
Rapport `docs/rapporten/<datum>-offerte-verbruik-onderweg-nameting.md` + INDEX-regel mét "werkt in productie: ja/nee", sectie
"## Gelezen regels"; BESLISSINGEN-sectie "OFFERTE-VERBRUIK = GEBOEKT + ONDERWEG (Peter 18-09)" status bijwerken; dit bestand → gedaan.
