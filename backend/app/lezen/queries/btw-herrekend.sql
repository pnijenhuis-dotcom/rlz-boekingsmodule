-- naam: btw-herrekend
-- versie: 1
-- doel: Tijdlijnregels "btw herrekend" (sleutel btw_herrekend) per administratie mét aanleiding per regel (tarief = tariefwissel 18-09, netto = nettowijziging FV-09 25-09) — meetlat feedbackrun A blok 6 (onderdeel btw-netto in nameting.yml): bewijst dat het scherm ná een nettowijziging het btw-bedrag herrekende en de server dat vastlegde
-- scope: administratie
-- parameters: administratie_id, dagen, aanleiding
-- optioneel: dagen, aanleiding
-- kolommen: tijdstip, document_id, referentie, status, regel, aanleiding, netto_van, netto_naar, btw_van, btw_naar, in_kosten, actor_id
SELECT g.tijdstip,
       d.id AS document_id,
       b.referentie,
       d.status::text AS status,
       (r.value ->> 'regel')::int AS regel,
       COALESCE(r.value ->> 'aanleiding', 'tarief') AS aanleiding,
       r.value ->> 'netto_van' AS netto_van,
       r.value ->> 'netto_naar' AS netto_naar,
       r.value ->> 'btw_van' AS btw_van,
       r.value ->> 'btw_naar' AS btw_naar,
       COALESCE((r.value ->> 'in_kosten')::boolean, false) AS in_kosten,
       g.actor_id
  FROM boekhouding.document_gebeurtenis g
  JOIN boekhouding.document d ON d.id = g.document_id
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
  CROSS JOIN LATERAL jsonb_array_elements(g.detail -> 'btw_herrekend') AS r(value)
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND g.detail ? 'btw_herrekend'
   AND g.tijdstip >= now() - make_interval(days => COALESCE(CAST(:dagen AS int), 30))
   AND (CAST(:aanleiding AS text) IS NULL OR COALESCE(r.value ->> 'aanleiding', 'tarief') = CAST(:aanleiding AS text))
 ORDER BY g.tijdstip DESC
