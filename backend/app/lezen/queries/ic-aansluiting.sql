-- naam: ic-aansluiting
-- versie: 1
-- doel: IC-aansluiting per richting (run D 02-10 blok D) — bevindingen van blok intercompany uit de laatste afgeronde run voor één administratie, optioneel gefilterd op richting ("verkoper>ontvanger", naamdelen) en/of afwijkingssoort (ic_inkoop_ontbreekt | ic_verkoop_ontbreekt | ic_bedrag_afwijking | ic_status_verschilt)
-- scope: administratie
-- parameters: administratie_id, richting, afwijking_soort
-- optioneel: richting, afwijking_soort
-- kolommen: run_afgerond_op, soort, afwijking_soort, verkoper, ontvanger, nummer, datum, bedrag_verkoop, bedrag_inkoop, delta, vingerafdruk, acceptatie
SELECT r.afgerond_op AS run_afgerond_op,
       b.soort,
       b.detail ->> 'afwijking_soort' AS afwijking_soort,
       b.detail ->> 'verkoper_naam' AS verkoper,
       b.detail ->> 'ontvanger_naam' AS ontvanger,
       b.detail ->> 'nummer' AS nummer,
       b.detail ->> 'datum' AS datum,
       b.detail ->> 'bedrag_verkoop' AS bedrag_verkoop,
       b.detail ->> 'bedrag_inkoop' AS bedrag_inkoop,
       b.detail ->> 'delta' AS delta,
       b.vingerafdruk,
       CASE WHEN (b.detail ->> 'geaccepteerd') = 'true' THEN 'geaccepteerd' ELSE NULL END AS acceptatie
  FROM boekhouding.reconciliatie_bevinding b
  JOIN boekhouding.reconciliatie_run r ON r.id = b.run_id
 WHERE b.administratie_id = CAST(:administratie_id AS uuid)
   AND b.blok = 'intercompany'
   AND r.id = (SELECT r2.id FROM boekhouding.reconciliatie_run r2
                WHERE r2.status = 'klaar' ORDER BY r2.afgerond_op DESC NULLS LAST LIMIT 1)
   AND (CAST(:richting AS text) IS NULL
        OR (COALESCE(b.detail ->> 'verkoper_naam', '') || '>' || COALESCE(b.detail ->> 'ontvanger_naam', ''))
           ILIKE ('%' || split_part(CAST(:richting AS text), '>', 1) || '%>%' || split_part(CAST(:richting AS text), '>', 2) || '%'))
   AND (CAST(:afwijking_soort AS text) IS NULL OR b.detail ->> 'afwijking_soort' = CAST(:afwijking_soort AS text))
 ORDER BY b.detail ->> 'verkoper_naam', b.detail ->> 'ontvanger_naam', b.detail ->> 'afwijking_soort', b.detail ->> 'datum', b.detail ->> 'nummer'
