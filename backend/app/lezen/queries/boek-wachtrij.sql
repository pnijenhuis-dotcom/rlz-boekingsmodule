-- naam: boek-wachtrij
-- versie: 1
-- doel: Achtergrond-schrijver "Boeken in RLZ" (21-09): documenten die nu op wordt_geboekt staan (mét minuten) en de audit-sporen boek_wachtrij_ingediend / _trigger / _afgerond / _opnieuw_ingediend van de laatste 7 dagen — per administratie; meetlat trigger-pad ná deploy (trigger geslaagd + afgerond binnen 2 min door verwerker 'job')
-- scope: administratie
-- parameters: administratie_id
-- kolommen: soort, tijdstip, document_id, uitkomst, verwerker, minuten, detail
SELECT 'wordt_geboekt_nu' AS soort,
       d.laatst_gewijzigd_op AS tijdstip,
       d.id AS document_id,
       d.status::text AS uitkomst,
       NULL::text AS verwerker,
       round(extract(epoch FROM (now() - d.laatst_gewijzigd_op)) / 60.0)::int AS minuten,
       d.bestandsnaam AS detail
  FROM boekhouding.document d
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND d.status::text = 'wordt_geboekt'
UNION ALL
SELECT replace(a.actie, 'boek_wachtrij_', '') AS soort,
       a.tijdstip,
       a.record_id AS document_id,
       a.nieuwe_waarde ->> 'uitkomst' AS uitkomst,
       a.nieuwe_waarde ->> 'verwerker' AS verwerker,
       CASE WHEN a.nieuwe_waarde ? 'duur_ms' THEN round((a.nieuwe_waarde ->> 'duur_ms')::numeric / 60000.0, 1)::int ELSE NULL END AS minuten,
       left(coalesce(a.nieuwe_waarde ->> 'fout', a.nieuwe_waarde ->> 'job', a.nieuwe_waarde ->> 'sleutel', ''), 300) AS detail
  FROM platform.audit_event a
 WHERE a.administratie_id = CAST(:administratie_id AS uuid)
   AND a.actie IN ('boek_wachtrij_ingediend', 'boek_wachtrij_trigger', 'boek_wachtrij_afgerond', 'boek_wachtrij_opnieuw_ingediend')
   AND a.tijdstip >= now() - interval '7 days'
 ORDER BY 2
