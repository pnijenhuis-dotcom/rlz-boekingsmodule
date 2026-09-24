-- naam: ai-heraanbieding
-- versie: 1
-- doel: AI-heraanbieding ná limiet (BUG 24-09): per run (audit ai_heraanbieding_run, status klaar) bron/tijdstip/kandidaten/gedaan/rest/overgeslagen/uitkomst-tellers/gestopt_reden, plus de live telling van verzamelbak-rijen `ai_limiet_bereikt` en van bespaarde AI-calls (ai_dubbel_voor_extractie) in dezelfde periode — meetlat voor de nameting (dry-run 202 + N, échte run → 0)
-- scope: platform
-- parameters: dagen
-- optioneel: dagen
-- kolommen: soort, tijdstip, bron, status, kandidaten_verzamelbak, kandidaten_documenten, gedaan, rest, overgeslagen, tellers, gestopt_reden
SELECT 'run' AS soort,
       e.tijdstip,
       e.nieuwe_waarde ->> 'bron' AS bron,
       e.nieuwe_waarde ->> 'status' AS status,
       (e.nieuwe_waarde ->> 'kandidaten_verzamelbak')::int AS kandidaten_verzamelbak,
       (e.nieuwe_waarde ->> 'kandidaten_documenten')::int AS kandidaten_documenten,
       (e.nieuwe_waarde ->> 'gedaan')::int AS gedaan,
       (e.nieuwe_waarde ->> 'rest')::int AS rest,
       (e.nieuwe_waarde -> 'overgeslagen')::text AS overgeslagen,
       (e.nieuwe_waarde -> 'tellers')::text AS tellers,
       e.nieuwe_waarde ->> 'gestopt_reden' AS gestopt_reden
  FROM platform.audit_event e
 WHERE e.actie = 'ai_heraanbieding_run'
   AND e.tijdstip >= now() - make_interval(days => COALESCE(CAST(:dagen AS int), 7))
UNION ALL
SELECT 'verzamelbak_ai_limiet_nu' AS soort,
       now() AS tijdstip,
       NULL, NULL,
       count(*)::int, NULL, NULL, NULL, NULL, NULL, NULL
  FROM boekhouding.document d
 WHERE d.administratie_id IS NULL AND d.status = 'niet_toegewezen'
   AND (SELECT g.detail ->> 'reden' FROM boekhouding.document_gebeurtenis g
         WHERE g.document_id = d.id AND g.naar_status = 'niet_toegewezen'
         ORDER BY g.tijdstip DESC LIMIT 1) = 'ai_limiet_bereikt'
UNION ALL
SELECT 'ai_bespaard_dubbel' AS soort,
       now() AS tijdstip,
       NULL, NULL,
       NULL, NULL, count(*)::int, NULL, NULL, NULL, NULL
  FROM platform.audit_event e
 WHERE e.actie = 'ai_dubbel_voor_extractie'
   AND e.tijdstip >= now() - make_interval(days => COALESCE(CAST(:dagen AS int), 7))
 ORDER BY 1, 2 DESC
