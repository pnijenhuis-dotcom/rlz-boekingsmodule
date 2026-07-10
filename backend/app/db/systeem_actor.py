"""Systeem-actor voor achtergrondverwerking (patroon, vastgelegd 2026-07-10).

Elke statusovergang of audit_event die door een proces zónder mens wordt gezet (extractie-worker,
straks ook sync-jobs, webhook-aflevering, e-mail-intake) gebruikt deze vaste, herkenbare actor —
nooit de actor_id van de gebruiker die de taak toevallig triggerde: in tijdlijn en audit moet
zichtbaar zijn wát een mens deed en wát het systeem deed.

De actor is een échte `platform.gebruiker`-rij (geseed in migratie 0016), zodat de bestaande
FK's op `document_gebeurtenis.actor_id` en `audit_event.actor_id` onverkort gelden. Inloggen kan
nooit: status `geblokkeerd`, geen wachtwoord-hash, geen uitnodiging, geen administratie-scope.

Herkenning in responses loopt via deze constante (bv. `actor_is_systeem` in de tijdlijn-DTO) —
vergelijk altijd tegen SYSTEEM_ACTOR_ID, nooit tegen naam of e-mail.
"""

from __future__ import annotations

import uuid

SYSTEEM_ACTOR_ID = uuid.UUID("00000000-0000-0000-0000-000000000001")
