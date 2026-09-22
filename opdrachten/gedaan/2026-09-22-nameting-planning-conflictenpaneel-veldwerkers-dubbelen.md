uitgevoerd 2026-09-22, rapport: docs/rapporten/2026-09-22-nameting-planning-conflictenpaneel.md

Domeinen: uren-planning-veldwerkers, werkloop-productie
niet vóór: 2026-09-22 09:00

# NAMETING 22-09 — Planning conflictenpaneel + dubbele veldwerkers (rapport 21-09)

Vervolg op `docs/rapporten/2026-09-21-planning-conflictenpaneel-dubbele-veldwerkers.md` ("werkt in productie: niet gemeten"). Stap 0:
deploy-check service ÉN jobs (`gcloud run jobs describe … image`) op de commit van 21-09 (migratie 0169) én `main..origin/main` leeg.

1. `scripts/gcp/nameting.sh veldwerkers-dubbelen --alles` (zonder TTY: `gh workflow run nameting -f onderdeel=veldwerkers-dubbelen`)
   → `verkenning/nameting-veldwerkers-dubbelen-<dd-mm>.txt`; verwachting Universal: 0 kandidaat-clusters, 0 fouten. Een KANDIDAAT-regel
   = beoordelen (klikpunt Peter), nooit samenvoegen.
2. Lees-only via Cloud Logging / request-log: `POST /uren/kantoor/planning/conflict-akkoord` en `planning/bulk` mét bron `conflict`
   komen voor zodra Peter het paneel gebruikt heeft — tellen, niet forceren. `db-lezen` (nameting-SA) op
   `boekhouding.planning_conflict_akkoord` mét `--administratie <Universal>`: aantal rijen + soort.
3. Rapport `docs/rapporten/2026-09-22-nameting-planning-conflictenpaneel.md` + INDEX + "Gelezen regels"; regel "werkt in productie:
   ja/nee" in de rapportkop van 21-09 bijwerken (verwijzing, geen herschrijving).
