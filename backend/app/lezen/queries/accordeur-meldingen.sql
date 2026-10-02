-- naam: accordeur-meldingen
-- versie: 1
-- doel: Run A 02-10 punt 14 (push-only): per dag en per soort hoe de automatische accordeur-meldingen bezorgd zijn — bundelmelding (accordeur_nieuw_gemeld) en 09:00-herinnering (accordeur_herinnering) per kanaal/status, plus de run-audits accordeur_melding_run mét verzonden_push/overgeslagen_geen_push; meetlat ná deploy = 0 rijen kanaal 'e-mail' ná de deploy én run-audits aanwezig (default laatste 14 dagen)
-- scope: platform
-- parameters: dagen
-- optioneel: dagen
-- kolommen: bron, dag, soort, kanaal_of_status, aantal
SELECT 'accordeur_nieuw_gemeld' AS bron,
       date(coalesce(g.verzonden_op, g.aangemaakt_op) AT TIME ZONE 'Europe/Amsterdam') AS dag,
       'nieuwe_facturen' AS soort,
       coalesce(g.kanaal, g.status) AS kanaal_of_status,
       count(*)::int AS aantal
  FROM platform.accordeur_nieuw_gemeld g
 WHERE coalesce(g.verzonden_op, g.aangemaakt_op) >= now() - COALESCE(CAST(:dagen AS int), 14) * INTERVAL '1 day'
 GROUP BY 1, 2, 3, 4
UNION ALL
SELECT 'accordeur_herinnering' AS bron,
       h.datum AS dag,
       'dag_herinnering' AS soort,
       coalesce(h.kanaal, h.status) AS kanaal_of_status,
       count(*)::int AS aantal
  FROM platform.accordeur_herinnering h
 WHERE h.datum >= (now() AT TIME ZONE 'Europe/Amsterdam')::date - COALESCE(CAST(:dagen AS int), 14)
 GROUP BY 1, 2, 3, 4
UNION ALL
SELECT 'audit accordeur_melding_run' AS bron,
       date(a.tijdstip AT TIME ZONE 'Europe/Amsterdam') AS dag,
       a.nieuwe_waarde ->> 'soort' AS soort,
       'verzonden_push=' || coalesce(a.nieuwe_waarde ->> 'verzonden_push', '0')
         || ' overgeslagen_geen_push=' || coalesce(a.nieuwe_waarde ->> 'overgeslagen_geen_push', '0')
         || ' mislukt=' || coalesce(a.nieuwe_waarde ->> 'mislukt', '0') AS kanaal_of_status,
       count(*)::int AS aantal
  FROM platform.audit_event a
 WHERE a.actie = 'accordeur_melding_run'
   AND a.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 14) * INTERVAL '1 day'
 GROUP BY 1, 2, 3, 4
 ORDER BY 2 DESC, 1, 3, 4
