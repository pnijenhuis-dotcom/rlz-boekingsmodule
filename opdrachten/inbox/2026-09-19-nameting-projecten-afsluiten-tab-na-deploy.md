Domeinen: verplichtingen-projecten-voorraad, werkloop-productie

# OPDRACHT 19-09 — Nameting ná deploy: Projecten › Afsluiten? (N) bij Universal Steigerbouw (vervolg op
# docs/rapporten/2026-09-19-projecten-afsluiten-tab-bulk.md)

**Voorwaarde (stap 0):** de commit met migratie 0167 + `app/projecten/afsluiten.py` is gedeployd op service ÉN jobs
(`gh run view` van deploy.yml groen; `gcloud run jobs describe rlz-reconciliatie --format='value(template.template.containers[0].image)'`
= dezelfde image als de service). Niet gedeployd = wachten, nooit een lokaal proces tegen productie.
**Stand 19-09 ~11:00:** het werk is in de run "inbox-afgewerkt" alsnog door de poort gehaald en gecommit (zie
`docs/rapporten/2026-09-19-inbox-afgewerkt.md`); de deploy start ná de push van die run — deze opdracht pas daarna oppakken.

## Meetrecept
1. `gh workflow run nameting.yml -f onderdeel=projecten-afgesloten` (of `scripts/gcp/nameting.sh projecten-afsluit-kandidaten --administratie "Universal Steigerbouw"`
   zonder TTY = via gh). Verwacht in `verkenning/nameting-projecten-afgesloten-<datum>.txt`: "Totaal: 83 lopende projecten beoordeeld,
   8 kandidaat afsluiten (… naam zegt afgesloten 8 …)" — of minder als Peter/Haci al hebben afgevinkt (dan: aantal afgesloten in
   `project_cache.status='afgesloten'` via db_lezen.sh op de leesreplica, en audit `project_afgesloten` mét `afsluit_reden`).
2. Cloud Logging: `GET /projecten/afsluit-kandidaten` 200 voor Universal (request-log op administratie-id 3ee6edf0-5cb8-4f98-bba1-16fb97ae6873).
3. Rapportregel "werkt in productie: ja/nee" + INDEX; BESLISSINGEN-status van "niet gemeten" naar "gemeten <datum>".
Lees-only; geen afsluiten vanuit de run (dat doen Peter/Haci in de tab).
