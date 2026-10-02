-- naam: btw-afronding
-- versie: 1
-- doel: Meetlat run D 02-10 blok A (besluit Peter 29-09 "btw op de factuur is leidend, onder € 0,10 nooit blokkeren"): per administratie (1) check_groen_met_verschil = geboekte inkoopdocumenten waarvan Σ regel-btw 0,01–0,09 afwijkt van Σ netto × tariefpercentage (de check "Btw-bedrag past bij tarief" bleef groen en de factuur-btw ging naar RLZ), (2) acceptatie_btw_afronding = systeem-acceptaties mét audit btw_afronding_rlz (RLZ herrekende de btw per tarief en boekt méér voorbelasting), (3) rlz_lager_dan_factuur = bevindingen btw_rlz_lager_dan_factuur (meten) uit de laatste afgeronde reconciliatie-run
-- scope: administratie
-- parameters: administratie_id, dagen
-- optioneel: dagen
-- kolommen: soort, tijdstip, document_id, referentie, netto, btw_factuur, btw_tarief_of_rlz, verschil, detail
WITH venster AS (
  SELECT now() - make_interval(days => COALESCE(CAST(:dagen AS int), 14)) AS sinds
),
regels AS (
  SELECT d.id AS document_id,
         b.referentie,
         d.laatst_gewijzigd_op AS tijdstip,
         SUM(r.netto_bedrag) AS netto,
         SUM(COALESCE(r.btw_bedrag, 0)) AS btw_factuur,
         SUM(ROUND(r.netto_bedrag * COALESCE(t.percentage, 0), 2)) AS btw_tarief,
         BOOL_AND(t.id IS NOT NULL AND t.percentage IS NOT NULL) AS alle_tarieven_bekend
    FROM boekhouding.document d
    JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
    JOIN boekhouding.boekvoorstel_regel r ON r.document_id = d.id
    LEFT JOIN boekhouding.taxrate_cache t ON t.id = r.taxrate_id AND t.administratie_id = d.administratie_id
   WHERE d.administratie_id = CAST(:administratie_id AS uuid)
     AND d.status::text = 'geboekt'
     AND d.laatst_gewijzigd_op >= (SELECT sinds FROM venster)
     AND r.netto_bedrag IS NOT NULL
   GROUP BY d.id, b.referentie, d.laatst_gewijzigd_op
)
SELECT 'check_groen_met_verschil' AS soort,
       g.tijdstip,
       g.document_id,
       g.referentie,
       g.netto,
       g.btw_factuur,
       g.btw_tarief AS btw_tarief_of_rlz,
       g.btw_factuur - g.btw_tarief AS verschil,
       'Σ btw wijkt < 0,10 af van Σ netto × tarief — check groen, factuur-btw naar RLZ' AS detail
  FROM regels g
 WHERE g.alle_tarieven_bekend
   AND ABS(g.btw_factuur - g.btw_tarief) BETWEEN 0.01 AND 0.09
UNION ALL
SELECT 'acceptatie_btw_afronding' AS soort,
       a.tijdstip,
       CAST(a.nieuwe_waarde ->> 'record_id' AS uuid) AS document_id,
       b.referentie,
       NULL::numeric AS netto,
       NULL::numeric AS btw_factuur,
       NULL::numeric AS btw_tarief_of_rlz,
       CAST(a.nieuwe_waarde ->> 'verschil' AS numeric) AS verschil,
       a.nieuwe_waarde ->> 'detail' AS detail
  FROM platform.audit_event a
  LEFT JOIN boekhouding.boekvoorstel b ON b.document_id = CAST(a.nieuwe_waarde ->> 'record_id' AS uuid)
 WHERE a.actie = 'btw_afronding_rlz'
   AND a.administratie_id = CAST(:administratie_id AS uuid)
   AND a.tijdstip >= (SELECT sinds FROM venster)
UNION ALL
SELECT 'rlz_lager_dan_factuur' AS soort,
       r.afgerond_op AS tijdstip,
       CAST(bv.detail ->> 'document_id' AS uuid) AS document_id,
       bv.detail ->> 'factuurnummer' AS referentie,
       NULL::numeric AS netto,
       CAST(bv.detail ->> 'btw_lokaal' AS numeric) AS btw_factuur,
       CAST(bv.detail ->> 'btw_extern' AS numeric) AS btw_tarief_of_rlz,
       CAST(bv.detail ->> 'btw_extern' AS numeric) - CAST(bv.detail ->> 'btw_lokaal' AS numeric) AS verschil,
       bv.tekst AS detail
  FROM boekhouding.reconciliatie_bevinding bv
  JOIN boekhouding.reconciliatie_run r ON r.id = bv.run_id
 WHERE bv.administratie_id = CAST(:administratie_id AS uuid)
   AND bv.detail ->> 'afwijking_soort' = 'btw_rlz_lager_dan_factuur'
   AND r.id = (SELECT r2.id FROM boekhouding.reconciliatie_run r2
                WHERE r2.status = 'klaar' ORDER BY r2.afgerond_op DESC NULLS LAST LIMIT 1)
 ORDER BY soort, tijdstip DESC
