-- naam: document-feiten
-- versie: 1
-- doel: Alle feiten van één module-document: kop, boekvoorstel, status, RLZ-boekstuk, laatste tijdlijnstappen, audit-acties (bron voor "is dit dubbel/verdwenen?")
-- scope: administratie
-- parameters: administratie_id, document_id, boekstuk
-- optioneel: document_id, boekstuk
-- kolommen: document_id, status, soort, bestandsnaam, aangemaakt_op, vendor_id, referentie, factuurdatum, totaalbedrag, rlz_boekstuknummer, betaalstatus, samengevoegd_in_id, mogelijk_duplicaat_van_id, tijdlijn, audit_acties
SELECT d.id AS document_id,
       d.status::text AS status,
       d.soort,
       d.bestandsnaam,
       d.aangemaakt_op,
       b.vendor_id,
       b.referentie,
       b.factuurdatum,
       b.totaalbedrag,
       b.rlz_boekstuknummer,
       b.betaalstatus,
       d.samengevoegd_in_id,
       d.mogelijk_duplicaat_van_id,
       (SELECT jsonb_agg(jsonb_build_object('tijdstip', g.tijdstip, 'van', g.van_status, 'naar', g.naar_status,
                                            'detail', g.detail) ORDER BY g.tijdstip DESC)
          FROM (SELECT * FROM boekhouding.document_gebeurtenis g0 WHERE g0.document_id = d.id
                ORDER BY g0.tijdstip DESC LIMIT 25) g) AS tijdlijn,
       (SELECT jsonb_agg(jsonb_build_object('tijdstip', a.tijdstip, 'actie', a.actie, 'nieuw', a.nieuwe_waarde)
                         ORDER BY a.tijdstip DESC)
          FROM (SELECT * FROM platform.audit_event a0 WHERE a0.record_id = d.id
                ORDER BY a0.tijdstip DESC LIMIT 25) a) AS audit_acties
  FROM boekhouding.document d
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND (CAST(:document_id AS text) IS NULL OR d.id = CAST(:document_id AS uuid))
   AND (CAST(:boekstuk AS text) IS NULL OR b.rlz_boekstuknummer = CAST(:boekstuk AS text))
 ORDER BY d.aangemaakt_op DESC
