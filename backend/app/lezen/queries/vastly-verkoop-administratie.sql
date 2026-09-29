-- naam: vastly-verkoop-administratie
-- versie: 1
-- doel: Vastly-verkoop volledig automatisch (Peter 29-09), per administratie (RLS): open verkoopfactuur-documenten mét status, de vaste Vastly-omzetrekeningen per regelsoort (bron historie/mens), de autoboek-uitkomsten (audit automatisch_geboekt / autoboeken_geweigerd bron verkoop_opt_in mét reden) en de bevindingen vastly_omzetrekening_ontbreekt / vastly_verkoop_niet_geboekt van de laatste afgeronde run — meetlat nameting-onderdeel vastly-verkoop
-- scope: administratie
-- parameters: administratie_id, dagen
-- optioneel: dagen
-- kolommen: soort, tijdstip, sleutel, waarde
SELECT 'open_document' AS soort,
       CAST(d.aangemaakt_op AS timestamptz) AS tijdstip,
       d.bestandsnaam AS sleutel,
       d.status::text AS waarde
  FROM boekhouding.document d
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND d.soort = 'verkoopfactuur'
   AND d.status::text NOT IN ('geboekt', 'verwijderd', 'samengevoegd', 'gesplitst', 'afgevoerd_duplicaat', 'afgewezen')
UNION ALL
SELECT 'omzetrekening' AS soort,
       CAST(o.gewijzigd_op AS timestamptz) AS tijdstip,
       o.regelsoort AS sleutel,
       concat_ws(' · ', COALESCE(g.code, '?'), COALESCE(g.naam, '?'), 'bron=' || o.bron) AS waarde
  FROM boekhouding.vastly_omzetrekening o
  LEFT JOIN platform.grootboekrekening g ON g.ledger_id = o.ledger_id AND g.administratie_id = o.administratie_id
 WHERE o.administratie_id = CAST(:administratie_id AS uuid)
UNION ALL
SELECT 'autoboek' AS soort,
       CAST(e.tijdstip AS timestamptz) AS tijdstip,
       e.actie AS sleutel,
       concat_ws(' · ', COALESCE(e.nieuwe_waarde ->> 'factuurnummer', '—'), left(COALESCE(e.nieuwe_waarde ->> 'reden', '—'), 200)) AS waarde
  FROM platform.audit_event e
 WHERE e.administratie_id = CAST(:administratie_id AS uuid)
   AND e.actie IN ('automatisch_geboekt', 'autoboeken_geweigerd')
   AND e.nieuwe_waarde ->> 'bron' = 'verkoop_opt_in'
   AND e.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 14) * INTERVAL '1 day'
UNION ALL
SELECT 'bevinding' AS soort,
       CAST(r.afgerond_op AS timestamptz) AS tijdstip,
       COALESCE(b.detail ->> 'afwijking_soort', b.soort) AS sleutel,
       left(b.tekst, 160) AS waarde
  FROM boekhouding.reconciliatie_bevinding b
  JOIN boekhouding.reconciliatie_run r ON r.id = b.run_id
 WHERE b.blok = 'vastly_verkoop'
   AND b.administratie_id = CAST(:administratie_id AS uuid)
   AND r.id = (SELECT id FROM boekhouding.reconciliatie_run WHERE status = 'klaar' ORDER BY afgerond_op DESC LIMIT 1)
 ORDER BY soort, tijdstip DESC
