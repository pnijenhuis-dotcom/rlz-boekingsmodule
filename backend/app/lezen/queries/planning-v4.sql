-- naam: planning-v4
-- versie: 2
-- doel: Planning v4 (Peter 28-09): audit-sporen van "Kopiëren naar ‹weekdag› volgende week" (planning_bulk + planning_gepland mét bron kopie_volgende_week) en sinds 02-10 (run B punt 20) de dag-kopie via ctrl/cmd-C/V of "Kopiëren naar…" (bron kopie_dag), het ploeg-paneel als dé werkwijze (planning_bulk bron ploeg) en de quick-add uit het paneel (veldwerker_aangemaakt bron planning_paneel — administratie-loze rij, gematcht op administratie_ids) — meetlat nameting-onderdeel planning-v4
-- scope: administratie
-- parameters: administratie_id, dagen
-- optioneel: dagen
-- kolommen: tijdstip, actie, bron, actor_id, record_id, nieuwe_waarde
SELECT a.tijdstip,
       a.actie,
       a.nieuwe_waarde ->> 'bron' AS bron,
       a.actor_id,
       a.record_id,
       a.nieuwe_waarde
  FROM platform.audit_event a
 WHERE (
         (a.administratie_id = CAST(:administratie_id AS uuid)
          AND a.actie IN ('planning_bulk', 'planning_gepland')
          AND a.nieuwe_waarde ->> 'bron' IN ('kopie_volgende_week', 'kopie_dag', 'ploeg'))
      OR (a.actie = 'veldwerker_aangemaakt'
          AND a.nieuwe_waarde ->> 'bron' = 'planning_paneel'
          AND jsonb_exists(a.nieuwe_waarde -> 'administratie_ids', CAST(:administratie_id AS text)))
       )
   AND a.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 14) * INTERVAL '1 day'
 ORDER BY a.tijdstip DESC
