-- naam: project-prefill-herkomst
-- versie: 1
-- doel: Herkomst van het PROJECT per regel van open boekvoorstellen (blok 3 feedbackrun A 25-09, FV-02 bronvolgorde): uit het jongste prefill-snapshot per document — project_bron (factuur | factuur_onbevestigd | factuur_meerduidig | geheugen | factuur_conflict | geheugen_afgesloten | leeg) + herkomst-tag; meetlat "geheugen alleen als laatste bron en altijd zichtbaar"
-- scope: administratie
-- parameters: administratie_id, project_bron
-- optioneel: project_bron
-- kolommen: document_id, status, referentie, snapshot_op, volgnummer, project_id, project_bron, herkomst_project, project_tekst_aanwezig, project_bron_detail
SELECT d.id AS document_id,
       d.status::text AS status,
       b.referentie,
       snap.tijdstip AS snapshot_op,
       (rg ->> 'volgnummer')::int AS volgnummer,
       rg ->> 'project_id' AS project_id,
       rg ->> 'project_bron' AS project_bron,
       rg -> 'herkomst' ->> 'project' AS herkomst_project,
       NULLIF(rg ->> 'omschrijving', '') IS NOT NULL AS project_tekst_aanwezig,
       rg ->> 'project_bron_detail' AS project_bron_detail
  FROM boekhouding.document d
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
  JOIN LATERAL (
       SELECT g.tijdstip, g.detail -> 'boekvoorstel_prefill' AS snapshot
         FROM boekhouding.document_gebeurtenis g
        WHERE g.document_id = d.id AND g.detail ? 'boekvoorstel_prefill'
        ORDER BY g.tijdstip DESC
        LIMIT 1) snap ON true
  CROSS JOIN LATERAL jsonb_array_elements(COALESCE(snap.snapshot -> 'regels', '[]'::jsonb)) rg
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND d.status::text NOT IN ('verwijderd', 'afgewezen', 'samengevoegd', 'afgevoerd_duplicaat', 'gesplitst', 'geboekt')
   AND (CAST(:project_bron AS text) IS NULL OR rg ->> 'project_bron' = CAST(:project_bron AS text))
 ORDER BY snap.tijdstip DESC, d.id, (rg ->> 'volgnummer')::int
