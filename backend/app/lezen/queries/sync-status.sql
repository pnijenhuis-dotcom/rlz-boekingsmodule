-- naam: sync-status
-- versie: 1
-- doel: Laatste sync-runs per administratie (stamgegevens/eerste sync + bank-sync) mét status, tijdstippen en fout_reden
-- scope: administratie
-- parameters: administratie_id
-- kolommen: bron, status, aangevraagd_op, gestart_op, beeindigd_op, fout_reden, detail
SELECT 'administratie_sync_run' AS bron, s.status, s.aangevraagd_op, s.gestart_op, s.beeindigd_op, s.fout_reden,
       s.onderdelen AS detail
  FROM (SELECT * FROM boekhouding.administratie_sync_run a WHERE a.administratie_id = CAST(:administratie_id AS uuid)
        ORDER BY a.aangevraagd_op DESC LIMIT 3) s
UNION ALL
SELECT 'bank_sync_run', b.status, b.aangevraagd_op, b.gestart_op, b.beeindigd_op, b.fout_reden, b.resultaat
  FROM (SELECT * FROM boekhouding.bank_sync_run a WHERE a.administratie_id = CAST(:administratie_id AS uuid)
        ORDER BY a.aangevraagd_op DESC LIMIT 3) b
