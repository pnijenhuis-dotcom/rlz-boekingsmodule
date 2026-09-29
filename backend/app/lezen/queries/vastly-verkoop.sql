-- naam: vastly-verkoop
-- versie: 1
-- doel: Vastly-verkoop volledig automatisch (Peter 29-09): platformbrede stand — runs van de heraanbieding (audit vastly_verkoop_heraanbieding_run: bron, kandidaten, per uitkomst), entiteitkoppelingen in het register (bron identiteit/mens), niet-gekoppelde Vastly-verkoopdocumenten (administratie NULL, soort verkoopfactuur, niet_toegewezen) en de kantoorbrede bevindingen vastly_entiteit_niet_gekoppeld van de laatste afgeronde run — meetlat nameting-onderdeel vastly-verkoop (de per-administratie-kant: db-lezen vastly-verkoop-administratie)
-- scope: platform
-- parameters: dagen
-- optioneel: dagen
-- kolommen: soort, tijdstip, sleutel, waarde
SELECT 'run' AS soort,
       CAST(e.tijdstip AS timestamptz) AS tijdstip,
       COALESCE(e.nieuwe_waarde ->> 'bron', '—') AS sleutel,
       concat_ws(' · ', 'kandidaten=' || COALESCE(e.nieuwe_waarde ->> 'kandidaten', '0'),
                 'dry_run=' || COALESCE(e.nieuwe_waarde ->> 'dry_run', '—'),
                 'per_uitkomst=' || COALESCE(CAST(e.nieuwe_waarde -> 'per_uitkomst' AS text), '{}')) AS waarde
  FROM platform.audit_event e
 WHERE e.actie = 'vastly_verkoop_heraanbieding_run'
   AND e.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 14) * INTERVAL '1 day'
UNION ALL
SELECT 'koppeling' AS soort,
       CAST(k.aangemaakt_op AS timestamptz) AS tijdstip,
       k.sleutel_soort || ' ' || k.sleutel AS sleutel,
       concat_ws(' · ', a.naam, 'bron=' || k.bron, COALESCE(k.weergave, '—')) AS waarde
  FROM boekhouding.vastly_entiteit_koppeling k
  JOIN platform.administratie a ON a.id = k.administratie_id
UNION ALL
SELECT 'niet_gekoppeld' AS soort,
       CAST(d.aangemaakt_op AS timestamptz) AS tijdstip,
       d.bestandsnaam AS sleutel,
       concat_ws(' · ', COALESCE(d.tenaamstelling, '—'), COALESCE(d.afzender_hint, '—'), d.status::text) AS waarde
  FROM boekhouding.document d
 WHERE d.administratie_id IS NULL
   AND d.soort = 'verkoopfactuur'
   AND d.status::text = 'niet_toegewezen'
UNION ALL
SELECT 'bevinding' AS soort,
       CAST(r.afgerond_op AS timestamptz) AS tijdstip,
       COALESCE(b.detail ->> 'afwijking_soort', b.soort) AS sleutel,
       concat_ws(' · ', COALESCE(b.detail ->> 'weergave', '—'), 'aantal=' || COALESCE(b.detail ->> 'aantal', '—'), left(b.tekst, 120)) AS waarde
  FROM boekhouding.reconciliatie_bevinding b
  JOIN boekhouding.reconciliatie_run r ON r.id = b.run_id
 WHERE b.blok = 'vastly_verkoop'
   AND b.administratie_id IS NULL
   AND r.id = (SELECT id FROM boekhouding.reconciliatie_run WHERE status = 'klaar' ORDER BY afgerond_op DESC LIMIT 1)
 ORDER BY soort, tijdstip DESC
