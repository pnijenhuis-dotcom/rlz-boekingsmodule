-- naam: verkoop-overstap
-- versie: 1
-- doel: Leesbron → overstap op Odoo (Peter 28-09, casus Universal Verkoop B.V.): koppeling-stand (backend, alleen_lezen, kanteldatum, knip, oud RLZ-id, sentinel), de audit-sporen odoo_leesbron_gepromoveerd / odoo_overstap / odoo_open_voorstellen_hervertaald / odoo_koppeling_dubbel_geweigerd en de documenten die in het venster via de module geboekt zijn (boekstuk = Odoo-nummer BILL/… ná de overstap) — meetlat nameting-onderdeel verkoop-overstap
-- scope: administratie
-- parameters: administratie_id, dagen
-- optioneel: dagen
-- kolommen: soort, tijdstip, sleutel, waarde
SELECT 'koppeling' AS soort,
       CAST(k.probe_op AS timestamptz) AS tijdstip,
       'backend · alleen_lezen · overgangsdatum · knip · oud_rlz_id · rlz_admin_id' AS sleutel,
       concat_ws(' · ', a.boekhoud_backend,
                 'alleen_lezen=' || COALESCE(CAST(k.alleen_lezen AS text), '—'),
                 'overgangsdatum=' || COALESCE(CAST(k.overgangsdatum AS text), '—'),
                 'knip=' || COALESCE(CAST(k.voorraad_knip_datum AS text), '—'),
                 'oud_rlz_id=' || COALESCE(k.rlz_admin_id_voor_overstap, '—'),
                 'rlz_admin_id=' || a.rlz_admin_id) AS waarde
  FROM platform.administratie a
  LEFT JOIN platform.odoo_koppeling k ON k.administratie_id = a.id
 WHERE a.id = CAST(:administratie_id AS uuid)
UNION ALL
SELECT 'audit' AS soort,
       CAST(e.tijdstip AS timestamptz) AS tijdstip,
       e.actie AS sleutel,
       concat_ws(' · ', 'sleutel=' || COALESCE(e.nieuwe_waarde ->> 'sleutel', '—'),
                 'overgangsdatum=' || COALESCE(e.nieuwe_waarde ->> 'overgangsdatum', '—'),
                 'leesbron_gepromoveerd=' || COALESCE(e.nieuwe_waarde ->> 'leesbron_gepromoveerd', '—'),
                 'documenten=' || COALESCE(e.nieuwe_waarde ->> 'documenten', '—')) AS waarde
  FROM platform.audit_event e
 WHERE (e.administratie_id = CAST(:administratie_id AS uuid) OR e.record_id = CAST(:administratie_id AS uuid))
   AND e.actie IN ('odoo_leesbron_gepromoveerd', 'odoo_overstap', 'odoo_open_voorstellen_hervertaald', 'odoo_koppeling_dubbel_geweigerd')
   AND e.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 14) * INTERVAL '1 day'
UNION ALL
SELECT 'geboekt' AS soort,
       CAST(d.laatst_gewijzigd_op AS timestamptz) AS tijdstip,
       COALESCE(b.rlz_boekstuknummer, '(geen boekstuk)') AS sleutel,
       concat_ws(' · ', d.soort, COALESCE(b.referentie, '—'), COALESCE(CAST(b.totaalbedrag AS text), '—'), COALESCE(CAST(b.factuurdatum AS text), '—')) AS waarde
  FROM boekhouding.document d
  JOIN boekhouding.boekvoorstel b ON b.document_id = d.id
 WHERE d.administratie_id = CAST(:administratie_id AS uuid)
   AND d.status::text = 'geboekt'
   AND d.laatst_gewijzigd_op >= now() - COALESCE(CAST(:dagen AS int), 14) * INTERVAL '1 day'
 ORDER BY soort, tijdstip DESC
