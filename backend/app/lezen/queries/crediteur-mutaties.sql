-- naam: crediteur-mutaties
-- versie: 1
-- doel: Crediteur aangemaakt/bewerkt vanuit het controlescherm (blok 5 feedbackrun 25-09, FV-14/FV-15): élk audit crediteur_aangemaakt_in_rlz / crediteur_gewijzigd mét oud→nieuw náást de huidige cache-rij (naam, adres, verdwenen) — meetlat nameting-onderdeel crediteur-paneel
-- scope: administratie
-- parameters: administratie_id, dagen
-- optioneel: dagen
-- kolommen: tijdstip, actie, actor_id, vendor_id, naam_nu, full_address_nu, verdwenen_uit_bron_op, oude_waarde, nieuwe_waarde
SELECT a.tijdstip,
       a.actie,
       a.actor_id,
       v.id AS vendor_id,
       v.naam AS naam_nu,
       v.brondata ->> 'FullAddress' AS full_address_nu,
       v.verdwenen_uit_bron_op,
       a.oude_waarde,
       a.nieuwe_waarde
  FROM platform.audit_event a
  JOIN boekhouding.vendor_cache v ON v.id = a.record_id AND v.administratie_id = CAST(:administratie_id AS uuid)
 WHERE a.administratie_id = CAST(:administratie_id AS uuid)
   AND a.actie IN ('crediteur_aangemaakt_in_rlz', 'crediteur_gewijzigd')
   AND a.tijdstip >= now() - COALESCE(CAST(:dagen AS int), 30) * INTERVAL '1 day'
 ORDER BY a.tijdstip DESC
