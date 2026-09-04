-- READ-ONLY controlequery (bugfix 04-09 "rolgroep volgt de ingang", BESLISSINGEN "BUGFIX 04-09 — ROLGROEP VOLGT DE INGANG").
-- Doel: kantoorrol-accounts opsporen die sinds de regressiecommit 0dfc6ca (2026-08-21) vermoedelijk vanaf een
-- VELDWERKER-ingang zijn aangemaakt. Vóór de fix droeg de audit géén ingang; de benadering:
--   (1) sterkste signaal: mail_uitgesteld = true — de checkbox "Uitnodiging later versturen" bestond alleen in de
--       veldwerker-ingangen (/gebruikers tab Veldwerkers + planning "+ ZZP'er");
--   (2) controle: de actor droeg het veldwerkerbeheer-recht (die kreeg sinds 31-08 al 403 — verwacht 0 rijen).
-- Draaien via de Cloud SQL Auth Proxy (recept 02/03-09) als boekhouding_app: platform.audit_event toont rijen mét
-- administratie_id IS NULL (uitnodiging-events) en platform.gebruiker is volledig leesbaar.
-- Sinds de fix draagt nieuwe_waarde->>'bron' de ingang: dan is `bron IN ('veldwerkers','planning') AND rol kantoorrol`
-- per definitie leeg (422 server-side).
SELECT
    ae.tijdstip,
    ae.correlatie_id                                            AS gebruiker_id,
    ae.nieuwe_waarde ->> 'naam'                                 AS naam,
    ae.nieuwe_waarde ->> 'e_mail'                               AS e_mail,
    ae.nieuwe_waarde ->> 'rol'                                  AS aangemaakte_rol,
    ae.nieuwe_waarde ->> 'bron'                                 AS ingang_sinds_fix,
    (ae.nieuwe_waarde ->> 'mail_uitgesteld')::boolean           AS uitnodiging_later,
    jsonb_array_length(ae.nieuwe_waarde -> 'administratie_ids') AS aantal_administraties,
    actor.naam                                                  AS aangemaakt_door,
    actor.rol                                                   AS actor_rol,
    EXISTS (
        SELECT 1 FROM platform.gebruiker_module_rol gmr
        WHERE gmr.gebruiker_id = ae.actor_id AND gmr.module = 'boekhouding.veldwerkerbeheer'
    )                                                           AS actor_heeft_veldwerkerbeheer,
    g.rol                                                       AS huidige_rol,
    g.status                                                    AS huidige_status
FROM platform.audit_event  ae
JOIN platform.gebruiker    actor ON actor.id = ae.actor_id
LEFT JOIN platform.gebruiker g   ON g.id     = ae.correlatie_id
WHERE ae.module = 'platform'
  AND ae.tabel  = 'uitnodiging'
  AND ae.actie  = 'gebruiker_uitgenodigd'
  AND ae.tijdstip >= '2026-08-21 00:00:00+02'::timestamptz
  AND ae.nieuwe_waarde ->> 'rol' IN ('boekhouding', 'boekhouding_projecten', 'beheerder')
  AND (
        (ae.nieuwe_waarde ->> 'mail_uitgesteld')::boolean IS TRUE
     OR EXISTS (
            SELECT 1 FROM platform.gebruiker_module_rol gmr
            WHERE gmr.gebruiker_id = ae.actor_id AND gmr.module = 'boekhouding.veldwerkerbeheer'
        )
  )
ORDER BY ae.tijdstip DESC;

-- Zwakkere sweep voor handmatige triage (geen bewijs): kantoorrol + precies één administratie + nooit geactiveerd.
-- SELECT ae.tijdstip, ae.nieuwe_waarde ->> 'naam', ae.nieuwe_waarde ->> 'e_mail', ae.nieuwe_waarde ->> 'rol', g.status
-- FROM platform.audit_event ae LEFT JOIN platform.gebruiker g ON g.id = ae.correlatie_id
-- WHERE ae.actie = 'gebruiker_uitgenodigd' AND ae.tijdstip >= '2026-08-21 00:00:00+02'
--   AND ae.nieuwe_waarde ->> 'rol' IN ('boekhouding', 'boekhouding_projecten', 'beheerder')
--   AND jsonb_array_length(ae.nieuwe_waarde -> 'administratie_ids') = 1 AND g.status = 'uitgenodigd'
-- ORDER BY ae.tijdstip DESC;
