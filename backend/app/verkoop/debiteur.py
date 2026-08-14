"""Idempotente debiteur-aanmaak uit de UBL-afnemergegevens (besluit Peter 2026-08-08,
BESLISSINGEN "Vastly-verkoopfacturen: debiteur = de ÉCHTE huurder"): zelfde patroon als
crediteur-aanmaken (app/sync/service.py::maak_crediteur_aan) — deterministisch client-GUID
(rlz_customer_id, UUIDv5 over administratie+genormaliseerde naam) + eigen duplicaatcheck vóór
de PUT. Géén verzameldebiteur: elke huurder wordt een eigen RLZ-debiteur, zodat het
bank-afletteren van huurontvangsten per debiteur kan matchen (tier-model optie 2)."""

from __future__ import annotations

import logging
import uuid

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.rlz_ids import rlz_customer_id
from app.projecten.anker import ANKER_CUSTOMER_NAAM, anker_customer_id, is_anker_naam
from app.rlz.client import RlzClient

logger = logging.getLogger(__name__)


class DebiteurAanmakenMislukt(Exception):
    """De debiteur kon niet gevonden of aangemaakt worden — de boekpoging stopt zichtbaar
    (fail-closed), er wordt nooit zonder Entity of tegen een gok-debiteur geboekt."""


def zorg_voor_debiteur(
    *,
    client: RlzClient,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    naam: str,
) -> uuid.UUID:
    """Vindt of maakt de RLZ-debiteur voor deze huurder, idempotent:

    1. Eigen duplicaatcheck vóór de PUT (patroon crediteur-aanmaken): bestaat er in RLZ al een
       debiteur met exact deze naam, dan wordt díe hergebruikt — nooit een tweede debiteur
       naast een bestaande. Meerdere naamgenoten = fout (mens lost op in RLZ; nooit gokken).
    2. Anders: PUT met het deterministische client-GUID (rlz_customer_id) — een retry raakt
       exact dezelfde debiteur, en zelfs als de Customers-collectie API-debiteuren niet zou
       tonen blijft de PUT daardoor idempotent.

    Een RLZ-fout tijdens de lookup is blokkerend (DebiteurAanmakenMislukt) — fail-closed."""
    naam = " ".join(naam.split())
    if not naam:
        raise DebiteurAanmakenMislukt("Debiteurnaam is leeg")
    if is_anker_naam(naam):
        # Tweede slot naast check_geen_ankerdebiteur (route-A-besluit 2026-08-14): het
        # projectanker krijgt nooit een boeking, dus ook nooit via dit aanmaak-/lookup-pad.
        raise DebiteurAanmakenMislukt(
            f"'{ANKER_CUSTOMER_NAAM}' is het projectanker-systeemrecord (route A) — "
            "hier mag nooit op geboekt worden"
        )

    try:
        bestaand = client.find_customers_by_name(name=naam)
    except Exception as exc:  # noqa: BLE001 — fail-closed: nooit blind een tweede debiteur PUTten
        raise DebiteurAanmakenMislukt(f"Debiteur-duplicaatcheck kon niet uitgevoerd worden: {exc}") from exc

    if len(bestaand) == 1:
        gevonden = uuid.UUID(bestaand[0]["id"])
        if gevonden == anker_customer_id(administratie_id):
            raise DebiteurAanmakenMislukt(
                f"De gevonden RLZ-debiteur is het projectanker '{ANKER_CUSTOMER_NAAM}' "
                "(route A) — hier mag nooit op geboekt worden"
            )
        return gevonden
    if len(bestaand) > 1:
        raise DebiteurAanmakenMislukt(
            f"Meerdere bestaande RLZ-debiteuren heten exact '{naam}' ({len(bestaand)}) — "
            "los de dubbeling eerst op in Reeleezee"
        )

    customer_id = rlz_customer_id(administratie_id, naam)
    client.put_customer(customer_id, name=naam)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="verkoop_boeking",
            record_id=customer_id,
            actie="debiteur_aangemaakt_in_rlz",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"customer_id": str(customer_id), "naam": naam},
            administratie_id=administratie_id,
        )
    return customer_id
