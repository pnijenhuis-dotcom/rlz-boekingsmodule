-- naam: documenten-open
-- versie: 1
-- doel: Open (niet-afgehandelde) documenten van één administratie mét bestandsnaam, soort, status, bron, intake-bericht, aantal opgeslagen boekvoorstel-regels en of het veldvoorstel bedragen draagt — meetlat bundelrun 24-09 (blok 1 Vastly-PDF-tweelingen, blok 7a Van Boxtel-bestandstypen, blok 7b samenvoegen zonder scanbedragen)
-- scope: administratie
-- parameters: administratie_id, soort, bestandsnaam
-- optioneel: soort, bestandsnaam
-- kolommen: document_id, soort, status, bestandsnaam, bron_bestandsnaam, bron, intake_bericht_id, aangemaakt_op, referentie, totaalbedrag, opgeslagen_regels, veldvoorstel_totaal_excl, veldvoorstel_regels_met_netto, samengevoegd_in_id
SELECT d.id AS document_id, d.soort, d.status::text AS status, d.bestandsnaam, d.bron_bestandsnaam, d.bron::text AS bron,
       d.intake_bericht_id, d.aangemaakt_op, b.referentie, b.totaalbedrag,
       (SELECT count(*) FROM boekhouding.boekvoorstel_regel r WHERE r.document_id = d.id) AS opgeslagen_regels,
       (vv.veldvoorstel ->> 'totaal_excl') AS veldvoorstel_totaal_excl,
       (SELECT count(*) FROM jsonb_array_elements(COALESCE(vv.veldvoorstel -> 'regels', '[]'::jsonb)) rg
         WHERE NULLIF(rg ->> 'netto_bedrag', '') IS NOT NULL) AS veldvoorstel_regels_met_netto,
       d.samengevoegd_in_id
  FROM boekhouding.document d
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
  LEFT JOIN LATERAL (
       SELECT g.detail -> 'veldvoorstel' AS veldvoorstel
         FROM boekhouding.document_gebeurtenis g
        WHERE g.document_id = d.id AND g.detail ? 'veldvoorstel'
        ORDER BY g.tijdstip DESC
        LIMIT 1) vv ON true
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND d.status::text NOT IN ('verwijderd', 'afgewezen', 'samengevoegd', 'afgevoerd_duplicaat', 'gesplitst', 'geboekt')
   AND (CAST(:soort AS text) IS NULL OR d.soort = CAST(:soort AS text))
   AND (CAST(:bestandsnaam AS text) IS NULL OR d.bestandsnaam ILIKE '%' || CAST(:bestandsnaam AS text) || '%')
 ORDER BY d.aangemaakt_op DESC
