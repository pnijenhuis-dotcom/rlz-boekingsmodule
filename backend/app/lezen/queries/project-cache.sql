-- naam: project-cache
-- versie: 1
-- doel: RLZ-projecten in de cache van één administratie (naam, actief, verdwenen) — dekking van het projectveld
-- scope: administratie
-- parameters: administratie_id
-- kolommen: project_id, naam, is_actief, laatst_gesynchroniseerd, verdwenen_uit_bron_op
SELECT p.id AS project_id, p.naam, p.is_actief, p.laatst_gesynchroniseerd, p.verdwenen_uit_bron_op
  FROM boekhouding.project_cache p
 WHERE p.administratie_id = CAST(:administratie_id AS uuid)
 ORDER BY p.is_actief DESC NULLS LAST, p.naam
