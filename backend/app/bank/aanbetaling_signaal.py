"""Aanbetaling-open-signaal bij boeken (besluit Peter 25-08, feedbackronde deel 4 punt 3,
aansluitend — eerder punt 14): staat er voor de crediteur van deze inkoopfactuur nog een
vooruitbetaling/aanbetaling open (punt-3-koppeling, status `geboekt`), dan meldt het
controlescherm "Voor deze leverancier staat nog een aanbetaling open (€ X, dd-mm)" mét
verwijzing en biedt de tegenregel aan. SIGNAAL, geen blokkade; alleen op het boekmoment (zelfde
lijn als het al-betaald-signaal) — geen werkvoorraad-chip, geen status, geen audit (puur lezen).

Herkenning: match op Entity (vendor_id van het boekvoorstel); als extra herkenning de
leverancier-IBAN's (leverancier_iban, vertrouwde IBAN's van deze crediteur) tegen de
tegenrekening van de aanbetalings-mutatie — vangt een aanbetaling die op een ándere
crediteurkaart (duplicaat-crediteur) is geboekt maar van dezelfde bankrekening kwam.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.bank.models import BankMutatie, BankRelatieBoeking, BankRelatieBoekingStatus, RelatieSoort
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentSoort, LeverancierIban


@dataclass(frozen=True)
class AanbetalingTreffer:
    boeking_id: uuid.UUID
    payment_transaction_id: uuid.UUID
    bedrag: Decimal  # positief: het openstaande aanbetalingsbedrag
    boekdatum: date | None
    geboekt_op: datetime
    rlz_boekstuknummer: str | None
    entity_naam: str | None
    vooruit_ledger_id: uuid.UUID
    herkenning: str  # "entity" | "iban"


@dataclass(frozen=True)
class AanbetalingSignaal:
    toetsbaar: bool
    treffers: list[AanbetalingTreffer]


def zoek_open_aanbetalingen(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, vendor_ibans: set[str] | None = None
) -> list[AanbetalingTreffer]:
    ibans = {i.replace(" ", "").upper() for i in (vendor_ibans or set()) if i}
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(BankRelatieBoeking, BankMutatie.boekdatum, BankMutatie.tegenrekening_iban)
            .outerjoin(
                BankMutatie,
                (BankMutatie.id == BankRelatieBoeking.payment_transaction_id)
                & (BankMutatie.administratie_id == BankRelatieBoeking.administratie_id),
            )
            .where(
                BankRelatieBoeking.administratie_id == administratie_id,
                BankRelatieBoeking.relatie_soort == RelatieSoort.CREDITEUR.value,
                BankRelatieBoeking.status == BankRelatieBoekingStatus.GEBOEKT.value,
            )
            .order_by(BankRelatieBoeking.geboekt_op.asc())
        ).all()
    treffers: list[AanbetalingTreffer] = []
    for rij, boekdatum, tegen_iban in rijen:
        if rij.entity_id == vendor_id:
            herkenning = "entity"
        elif ibans and tegen_iban and tegen_iban.replace(" ", "").upper() in ibans:
            herkenning = "iban"
        else:
            continue
        treffers.append(
            AanbetalingTreffer(
                boeking_id=rij.id,
                payment_transaction_id=rij.payment_transaction_id,
                bedrag=abs(Decimal(rij.bedrag)),
                boekdatum=boekdatum,
                geboekt_op=rij.geboekt_op,
                rlz_boekstuknummer=rij.rlz_boekstuknummer,
                entity_naam=rij.entity_naam,
                vooruit_ledger_id=rij.vooruit_ledger_id,
                herkenning=herkenning,
            )
        )
    return treffers


def signaal_voor_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> AanbetalingSignaal:
    """Glue voor het controlescherm: crediteur uit het (opgeslagen of geëxtraheerde) boekvoorstel,
    IBAN's uit leverancier_iban; niet toetsbaar zonder crediteur of buiten inkoopfacturen."""
    from app.documenten.boekvoorstel import haal_boekvoorstel_op  # lokaal: boekvoorstel is zwaar

    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return AanbetalingSignaal(toetsbaar=False, treffers=[])
    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    if voorstel.vendor_id is None:
        return AanbetalingSignaal(toetsbaar=False, treffers=[])
    with scoped_session(administratie_id) as session:
        ibans = set(
            session.scalars(
                select(LeverancierIban.iban).where(
                    LeverancierIban.administratie_id == administratie_id,
                    LeverancierIban.vendor_id == voorstel.vendor_id,
                )
            )
        )
    return AanbetalingSignaal(
        toetsbaar=True,
        treffers=zoek_open_aanbetalingen(
            administratie_id=administratie_id, vendor_id=voorstel.vendor_id, vendor_ibans=ibans
        ),
    )
