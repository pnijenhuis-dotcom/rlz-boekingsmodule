Domeinen: uren-planning-veldwerkers, werkloop-productie
niet vóór: 2026-09-29 09:00

# NAMETING poging 2 — Conflictenpaneel handelingen (Houd ‹A› / Beide halve dagen) — tellen, niet forceren

Vervolg op `docs/rapporten/2026-09-22-nameting-planning-conflictenpaneel.md` (poging 1: lees-kant ja, handelingen niet gemeten — Universal had
0 dubbel geplande persoon-dagen vanaf vandaag en 0 akkoord-rijen). Poging 2 van hoogstens 3 (regel 22-09 corrigeren-nameting punt 3 + rij (k)).
Stap 0: deploy-check service ÉN jobs + `main..origin/main` leeg.

1. Cloud Logging `rlz-backend`, sinds 2026-09-22T12:00Z: `POST /uren/kantoor/planning/conflict-akkoord` (aantal, status) en
   `POST /uren/kantoor/planning/bulk` waarvan audit `planning_verwijderd`/`planning_bulk` mét `bron: conflict` (leesreplica, `--administratie`
   Universal `3ee6edf0-5cb8-4f98-bba1-16fb97ae6873`).
2. `db_lezen.sh` op `boekhouding.planning_conflict_akkoord` (Universal): rijen + soort + reden-lengte; en het aantal dubbel geplande persoon-dagen
   vanaf vandaag in `planning_toewijzing` (query in het rapport van 22-09).
3. Bij ≥ 1 akkoord of ≥ 1 bulk bron `conflict`: rapport "werkt in productie: ja" mét de audit-rijen als bewijs. Bij 0 én 0 conflicten vanaf vandaag:
   rapport mét de stand + deze opdracht naar `opdrachten/mislukt/` mét kopregel (eindstand "lees-kant ja, handelingen ongebruikt") — géén derde
   lege poging tenzij er wél conflicten zijn maar niemand het paneel gebruikte (dan poging 3, `niet vóór:` +7 dagen).
4. Rapport `docs/rapporten/<datum>-nameting-planning-conflictenpaneel-poging-2.md` + INDEX + "Gelezen regels"; verwijsregel in het rapport van 22-09.
