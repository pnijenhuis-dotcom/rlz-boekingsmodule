-- naam: correcties
-- versie: 1
-- doel: "Corrigeren…" vanuit de module (21-09) per administratie: élk audit document_gecorrigeerd / document_correctie_mislukt mét reden, oud boekstuk en oud extern id náást de huidige stand van het document (status, boek_cyclus, boekstuknummer) — meetlat van de nameting (onderdeel corrigeren in nameting.yml)
-- scope: administratie
-- parameters: administratie_id, dagen
-- optioneel: dagen
-- kolommen: tijdstip, actie, document_id, soort, referentie, status, boek_cyclus, rlz_boekstuknummer, detail
SELECT a.tijdstip,
       a.actie,
       d.id AS document_id,
       d.soort,
       b.referentie,
       d.status::text AS status,
       b.boek_cyclus,
       b.rlz_boekstuknummer,
       a.nieuwe_waarde AS detail
  FROM platform.audit_event a
  JOIN boekhouding.document d ON d.id = a.record_id
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND a.actie IN ('document_gecorrigeerd', 'document_correctie_mislukt')
   AND a.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 30) * INTERVAL '1 day'
 ORDER BY a.tijdstip DESC
