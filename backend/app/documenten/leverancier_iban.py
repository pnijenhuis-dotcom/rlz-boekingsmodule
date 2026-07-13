from __future__ import annotations

import uuid

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.models import LeverancierIban, LeverancierIbanBron
from app.extractie.iban import is_geldig_iban, normaliseer_iban
from app.rlz.client import RlzApiError, RlzClient

# Vertrouwde-IBAN-set per crediteur (IBAN-wissel-fraudecontrole, open item 2026-07-13).
# Meerwaardig: meerdere bevestigde rekeningen per leverancier (G-rekening/WKA) is de norm.
# Privacy: IBAN's gaan nooit door de logger of in URL's — wel volledig in het audit_event
# (append-only, toegangsgecontroleerd): de IBAN-mutatie is juist het controlewaardige feit.


class OngeldigIban(Exception):
    """Het aangeboden IBAN doorstaat de mod-97-proef niet — wordt nooit vastgelegd."""


def vertrouwde_ibans(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> set[str]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(LeverancierIban.iban).where(
                LeverancierIban.administratie_id == administratie_id,
                LeverancierIban.vendor_id == vendor_id,
            )
        ).all()
    return set(rijen)


def _voeg_toe(
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    iban: str,
    bron: LeverancierIbanBron,
    actor_id: uuid.UUID,
    bevestigd_door: uuid.UUID | None = None,
) -> bool:
    """Idempotente insert + audit_event. False = bestond al (geen tweede audit-rij: een herhaalde
    vastlegging van hetzelfde IBAN is geen nieuwe handeling op de set)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bestaand = session.get(LeverancierIban, (administratie_id, vendor_id, iban))
        if bestaand is not None:
            return False
        session.add(
            LeverancierIban(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                iban=iban,
                bron=bron.value,
                bevestigd_door=bevestigd_door,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_iban",
            record_id=vendor_id,
            actie="leverancier_iban_toegevoegd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"iban": iban, "bron": bron.value},
            administratie_id=administratie_id,
        )
    return True


def seed_uit_rlz(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, client: RlzClient, actor_id: uuid.UUID
) -> set[str]:
    """Vertrouwde set vullen uit RLZ's `Vendors/{id}/BankRelations` (IBAN-veld live geverifieerd
    13 juli 2026, zie verkenning/api-verkenning.md) — zo is "eerste keer" niet blind: een
    crediteur die in RLZ al een bankrelatie heeft, heeft meteen een vergelijkingsbasis. Alleen
    niet-gearchiveerde relaties met een geldig IBAN tellen. Propagateert RlzApiError — de
    aanroeper beslist wat een mislukte seed betekent (geen stille lege set)."""
    relaties = client.get(f"Vendors/{vendor_id}/BankRelations").get("value", [])
    geseed: set[str] = set()
    for relatie in relaties:
        if relatie.get("IsArchived"):
            continue
        iban = normaliseer_iban(relatie.get("IBAN"))
        if iban is None or not is_geldig_iban(iban):
            continue
        _voeg_toe(
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            iban=iban,
            bron=LeverancierIbanBron.RLZ_SEED,
            actor_id=actor_id,
        )
        geseed.add(iban)
    return geseed


def leg_baseline_vast(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, iban: str, actor_id: uuid.UUID
) -> None:
    """Eerste factuur-IBAN van een crediteur zonder RLZ-seed: vastleggen als baseline (zichtbaar
    ter bevestiging in de checkmelding), niet blokkeren — er is niets om mee te vergelijken."""
    if not is_geldig_iban(iban):
        raise OngeldigIban("IBAN doorstaat de mod-97-proef niet")
    genormaliseerd = normaliseer_iban(iban)
    assert genormaliseerd is not None
    _voeg_toe(
        administratie_id=administratie_id,
        vendor_id=vendor_id,
        iban=genormaliseerd,
        bron=LeverancierIbanBron.BASELINE,
        actor_id=actor_id,
    )


def bevestig_iban(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, iban: str, actor_id: uuid.UUID
) -> str:
    """Menselijke bevestiging van een (afwijkend) IBAN — de enige route waarlangs een nieuw IBAN
    na een wissel-blokkade aan de vertrouwde set wordt toegevoegd (bv. de G-rekening op een
    WKA-factuur). Geen auto-classificatie als G-rekening: de bevestiging zelf maakt hem
    vertrouwd. Retourneert het genormaliseerde IBAN."""
    if not is_geldig_iban(iban):
        raise OngeldigIban("IBAN doorstaat de mod-97-proef niet")
    genormaliseerd = normaliseer_iban(iban)
    assert genormaliseerd is not None
    _voeg_toe(
        administratie_id=administratie_id,
        vendor_id=vendor_id,
        iban=genormaliseerd,
        bron=LeverancierIbanBron.BEVESTIGD,
        actor_id=actor_id,
        bevestigd_door=actor_id,
    )
    return genormaliseerd


def seed_en_baseline_voor_checks(
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    factuur_iban: str | None,
    client: RlzClient,
    actor_id: uuid.UUID,
) -> tuple[set[str], bool, bool]:
    """Orkestratie voor de harde checks (app/documenten/boekvoorstel.py::voer_checks_uit):
    (vertrouwde set vóór eventuele baseline, is er nu een baseline vastgelegd?, is de
    RLZ-seed-poging mislukt?).

    Volgorde is bewust: (1) bestaande set laden; (2) leeg -> éénmalige RLZ-seed-poging
    (BankRelations); (3) nóg leeg én geldig factuur-IBAN -> baseline vastleggen. De baseline
    wordt alleen ná een gesláágde (lege) seed-poging gezet: mislukt de RLZ-aanroep, dan weten we
    niet of RLZ een tegensprekende bankrelatie heeft — geen baseline, én `seed_mislukt=True`
    zodat check_iban_wissel zelfstandig fail-closed blokkeert (nooit leunen op de
    duplicaatcheck)."""
    if vendor_id is None:
        return set(), False, False
    vertrouwd = vertrouwde_ibans(administratie_id=administratie_id, vendor_id=vendor_id)
    if vertrouwd:
        return vertrouwd, False, False
    try:
        vertrouwd = seed_uit_rlz(
            administratie_id=administratie_id, vendor_id=vendor_id, client=client, actor_id=actor_id
        )
    except RlzApiError:
        return set(), False, True
    if vertrouwd or factuur_iban is None or not is_geldig_iban(factuur_iban):
        return vertrouwd, False, False
    leg_baseline_vast(
        administratie_id=administratie_id, vendor_id=vendor_id, iban=factuur_iban, actor_id=actor_id
    )
    return set(), True, False
