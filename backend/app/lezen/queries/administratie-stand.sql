-- naam: administratie-stand
-- versie: 1
-- doel: Stand van administraties (actief, gearchiveerd_op, backend, Odoo-company + probe_op, RLZ-credential aanwezig) op naamdeel — meetlat dearchiveren Odoo-administratie (bundelrun 24-09 blok 3), platformbreed leesbaar
-- scope: platform
-- parameters: naam
-- optioneel: naam
-- kolommen: administratie_id, naam, actief, gearchiveerd_op, boekhoud_backend, rlz_admin_id, odoo_company_id, odoo_company_naam, odoo_probe_op, odoo_alleen_lezen, rlz_credential_aanwezig
SELECT a.id AS administratie_id, a.naam, a.actief, a.gearchiveerd_op, a.boekhoud_backend, a.rlz_admin_id,
       k.company_id AS odoo_company_id, k.company_naam AS odoo_company_naam, k.probe_op AS odoo_probe_op, k.alleen_lezen AS odoo_alleen_lezen,
       EXISTS (SELECT 1 FROM platform.rlz_credential c WHERE c.administratie_id = a.id) AS rlz_credential_aanwezig
  FROM platform.administratie a
  LEFT JOIN platform.odoo_koppeling k ON k.administratie_id = a.id
 WHERE (CAST(:naam AS text) IS NULL OR a.naam ILIKE '%' || CAST(:naam AS text) || '%')
 ORDER BY a.naam
