-- naam: whitelist-doelen
-- versie: 1
-- doel: Doorbelasting-whitelist van een bron-administratie: doelentiteit, RLZ-klant-GUID, gekoppelde doel-administratie (leeg = niet gekoppeld), IC-vlag, actief
-- scope: administratie
-- parameters: administratie_id
-- kolommen: doelentiteit_naam, doel_customer_guid, doel_administratie_id, intercompany, actief, gewijzigd_op
SELECT m.doelentiteit_naam, m.doel_customer_guid, m.doel_administratie_id, m.intercompany, m.actief, m.gewijzigd_op
  FROM boekhouding.doorbelasting_mapping m
 WHERE m.administratie_id = CAST(:administratie_id AS uuid)
 ORDER BY m.actief DESC, m.doelentiteit_naam
