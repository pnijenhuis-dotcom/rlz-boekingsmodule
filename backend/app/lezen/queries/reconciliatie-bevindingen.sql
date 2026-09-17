-- naam: reconciliatie-bevindingen
-- versie: 1
-- doel: Bevindingen van de laatste afgeronde reconciliatie-run per administratie, gefilterd op afwijkingssoort en/of soort (afwijking|let_op|fout|geaccepteerd|uitgesloten)
-- scope: administratie
-- parameters: administratie_id, afwijking_soort, soort
-- optioneel: afwijking_soort, soort
-- kolommen: run_afgerond_op, blok, soort, afwijking_soort, stand, vingerafdruk, tekst
SELECT r.afgerond_op AS run_afgerond_op,
       b.blok,
       b.soort,
       b.detail ->> 'afwijking_soort' AS afwijking_soort,
       b.detail ->> 'stand' AS stand,
       b.vingerafdruk,
       b.tekst
  FROM boekhouding.reconciliatie_bevinding b
  JOIN boekhouding.reconciliatie_run r ON r.id = b.run_id
 WHERE b.administratie_id = CAST(:administratie_id AS uuid)
   AND r.id = (SELECT r2.id FROM boekhouding.reconciliatie_run r2
                WHERE r2.status = 'klaar' ORDER BY r2.afgerond_op DESC NULLS LAST LIMIT 1)
   AND (CAST(:afwijking_soort AS text) IS NULL OR b.detail ->> 'afwijking_soort' = CAST(:afwijking_soort AS text))
   AND (CAST(:soort AS text) IS NULL OR b.soort = CAST(:soort AS text))
 ORDER BY b.blok, b.soort, b.tekst
