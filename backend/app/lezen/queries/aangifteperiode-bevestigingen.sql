-- naam: aangifteperiode-bevestigingen
-- versie: 1
-- doel: Blok 4 feedbackrun A 25-09 (FV-16): per administratie de bewuste keuzes "Boeken (btw in volgend tijdvak)" (audit aangifteperiode_bevestigd) én de tijdlijnregels van boekingen mét factuurdatum in een ingediende aangifte zonder voorafgaande bevestiging (aangifteperiode_geboekt_onbevestigd) — meetlat van de nameting (onderdeel aangifteperiode)
-- scope: administratie
-- parameters: administratie_id, dagen
-- optioneel: dagen
-- kolommen: tijdstip, soort, document_id, referentie, factuurdatum, status, periode_start, periode_eind, detail
SELECT x.tijdstip,
       x.soort,
       d.id AS document_id,
       b.referentie,
       b.factuurdatum,
       d.status::text AS status,
       x.periode_start,
       x.periode_eind,
       x.detail
  FROM (
       SELECT a.tijdstip, 'bevestigd'::text AS soort, a.record_id AS document_id,
              a.nieuwe_waarde ->> 'periode_start' AS periode_start,
              a.nieuwe_waarde ->> 'periode_eind' AS periode_eind,
              a.nieuwe_waarde AS detail
         FROM platform.audit_event a
        WHERE a.actie = 'aangifteperiode_bevestigd'
       UNION ALL
       SELECT g.tijdstip, 'geboekt_onbevestigd'::text AS soort, g.document_id,
              g.detail -> 'aangifteperiode_geboekt_onbevestigd' ->> 'periode_start' AS periode_start,
              g.detail -> 'aangifteperiode_geboekt_onbevestigd' ->> 'periode_eind' AS periode_eind,
              g.detail
         FROM boekhouding.document_gebeurtenis g
        WHERE g.detail ? 'aangifteperiode_geboekt_onbevestigd'
       ) x
  JOIN boekhouding.document d ON d.id = x.document_id
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND x.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 30) * INTERVAL '1 day'
 ORDER BY x.tijdstip DESC
