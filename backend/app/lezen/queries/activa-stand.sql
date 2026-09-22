-- naam: activa-stand
-- versie: 1
-- doel: Activa fase 1 (21-09) per administratie: de `is_activa`-rekeningen uit de Ledgers-sync, de stand van `activa_instelling` (grens, RLZ-grens + leesmoment, register-probe leesbaar/fout/tijdstip, opt-in automatisch) en de activum-koppelingen per status — meetlat van de nameting 22-09 (sync vult grens/probe; een lees-only reconciliatie mag `register_geprobeerd_op` NIET verplaatsen)
-- scope: administratie
-- parameters: administratie_id
-- kolommen: soort, sleutel, waarde, tijdstip, detail
SELECT 'is_activa_rekening' AS soort,
       g.code AS sleutel,
       g.naam AS waarde,
       g.laatst_gesynchroniseerd AS tijdstip,
       jsonb_build_object('soort', g.soort, 'verdwenen_uit_bron_op', g.verdwenen_uit_bron_op) AS detail
  FROM platform.grootboekrekening g
 WHERE g.administratie_id = CAST(:administratie_id AS uuid)
   AND g.is_activa
   AND g.verdwenen_uit_bron_op IS NULL
UNION ALL
SELECT 'instelling',
       'activeringsgrens',
       i.activeringsgrens::text,
       i.gewijzigd_op,
       jsonb_build_object('grens_rlz', i.grens_rlz, 'grens_rlz_gelezen_op', i.grens_rlz_gelezen_op,
                          'automatisch_aanmaken_ingeschakeld', i.automatisch_aanmaken_ingeschakeld,
                          'termijnen', i.termijnen)
  FROM boekhouding.activa_instelling i
 WHERE i.administratie_id = CAST(:administratie_id AS uuid)
UNION ALL
SELECT 'register_probe',
       CASE WHEN i.register_leesbaar IS NULL THEN 'onbekend' WHEN i.register_leesbaar THEN 'leesbaar' ELSE 'niet_leesbaar' END,
       COALESCE(i.register_fout, ''),
       i.register_geprobeerd_op,
       jsonb_build_object('register_leesbaar', i.register_leesbaar)
  FROM boekhouding.activa_instelling i
 WHERE i.administratie_id = CAST(:administratie_id AS uuid)
UNION ALL
SELECT 'koppeling',
       k.status,
       count(*)::text,
       max(k.gewijzigd_op),
       jsonb_build_object('herkomsten', jsonb_agg(DISTINCT k.herkomst))
  FROM boekhouding.activum_koppeling k
 WHERE k.administratie_id = CAST(:administratie_id AS uuid)
 GROUP BY k.status
