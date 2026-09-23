-- naam: webhook-outbox
-- versie: 1
-- doel: Webhook-outbox (koppelcontract §3) van één administratie per rij: event, status, pogingen, afgeleverd_op, laatste_fout, referentie/rlz_document_id/volgnummer uit de payload én het laatste afleverantwoord uit het audit (resultaat van de ontvanger: verwerkt/al_verwerkt/voorstellen/genegeerd + reden) — meetlat voor webhook-herzenden (OPEN_ITEMS regel 13)
-- scope: administratie
-- parameters: administratie_id, referentie, event
-- optioneel: referentie, event
-- kolommen: outbox_id, event, status, pogingen, aangemaakt_op, afgeleverd_op, laatste_fout, referentie, rlz_document_id, volgnummer, eigen_administratie, laatste_audit_actie, laatste_audit_op, laatste_resultaat, laatste_ontvanger_reden, herzonden_op
SELECT w.id AS outbox_id,
       w.event,
       w.status,
       w.pogingen,
       w.aangemaakt_op,
       w.afgeleverd_op,
       w.laatste_fout,
       w.payload -> 'data' ->> 'referentie' AS referentie,
       w.payload -> 'data' ->> 'rlz_document_id' AS rlz_document_id,
       (w.payload -> 'data' ->> 'volgnummer')::int AS volgnummer,
       w.administratie_id IS NOT NULL AS eigen_administratie,
       a.actie AS laatste_audit_actie,
       a.tijdstip AS laatste_audit_op,
       a.nieuwe_waarde ->> 'resultaat' AS laatste_resultaat,
       a.nieuwe_waarde ->> 'ontvanger_reden' AS laatste_ontvanger_reden,
       h.tijdstip AS herzonden_op
  FROM boekhouding.webhook_uitgaand w
  LEFT JOIN boekhouding.document d ON d.id = w.document_id
  LEFT JOIN LATERAL (
        SELECT e.actie, e.tijdstip, e.nieuwe_waarde
          FROM platform.audit_event e
         WHERE e.tabel = 'webhook_uitgaand' AND e.record_id = w.id
           AND e.actie IN ('webhook_afgeleverd', 'webhook_genegeerd', 'webhook_poging_mislukt', 'webhook_dead_letter')
         ORDER BY e.tijdstip DESC
         LIMIT 1
       ) a ON TRUE
  LEFT JOIN LATERAL (
        SELECT e.tijdstip
          FROM platform.audit_event e
         WHERE e.tabel = 'webhook_uitgaand' AND e.record_id = w.id AND e.actie = 'webhook_herzonden'
         ORDER BY e.tijdstip DESC
         LIMIT 1
       ) h ON TRUE
 WHERE COALESCE(w.administratie_id, d.administratie_id) = CAST(:administratie_id AS uuid)
   AND (CAST(:referentie AS text) IS NULL OR w.payload -> 'data' ->> 'referentie' = CAST(:referentie AS text))
   AND (CAST(:event AS text) IS NULL OR w.event = CAST(:event AS text))
 ORDER BY w.aangemaakt_op
