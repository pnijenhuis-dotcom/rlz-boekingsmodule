-- naam: documenten-zonder
-- versie: 1
-- doel: Niet-afgehandelde documenten waarvan een kopveld leeg is (veld = vendor | referentie | factuurdatum | totaalbedrag | betaalstatus) — inventaris per administratie
-- scope: administratie
-- parameters: administratie_id, veld
-- kolommen: document_id, status, aangemaakt_op, vendor_id, referentie, factuurdatum, totaalbedrag, betaalstatus
SELECT d.id AS document_id, d.status::text AS status, d.aangemaakt_op, b.vendor_id, b.referentie, b.factuurdatum,
       b.totaalbedrag, b.betaalstatus
  FROM boekhouding.document d
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND d.status::text NOT IN ('verwijderd', 'afgewezen', 'samengevoegd', 'afgevoerd_duplicaat', 'gesplitst', 'geboekt')
   AND CASE CAST(:veld AS text)
         WHEN 'vendor' THEN b.vendor_id IS NULL
         WHEN 'referentie' THEN b.referentie IS NULL
         WHEN 'factuurdatum' THEN b.factuurdatum IS NULL
         WHEN 'totaalbedrag' THEN b.totaalbedrag IS NULL
         WHEN 'betaalstatus' THEN b.betaalstatus IS NULL
         ELSE false
       END
 ORDER BY d.aangemaakt_op DESC
