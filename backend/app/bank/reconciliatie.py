"""Bank-reconciliatie (failsafe, zelfde patroon als app/documenten/reconciliatie.py):
vergelijkt de eigen bank-werkstaat met de werkelijke RLZ-staat en rapporteert afwijkingen —
nooit stil corrigeren, een mens beoordeelt het rapport.

Twee controles:
1. elke lokaal GEBOEKTE directe bankboeking ↔ het RLZ-document (bestaat het nog, staat het op
   Status 3, is de mutatie echt dicht?) — vangt o.a. een storno die rechtstreeks in de RLZ-UI
   is gedaan (het document staat dan op Status 1 en de mutatie is weer open, terwijl wij
   'geboekt' + open_bedrag 0 administreren; de gewone sync-verversronde ziet dat niet, want
   die ververst alleen lokaal-open mutaties);
2. elke GEVERIFIEERDE afletter-opdracht ↔ het verse OpenAmount van de mutatie — vangt een
   in RLZ teruggedraaide aflettering.

⚠️ Toetsen gebeurt op OpenAmount/documentstatus, nooit op IsComplete (stale na storno)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from sqlalchemy import select

from app.bank.models import AfletterOpdrachtStatus, BankAfletterOpdracht, BankBoeking, BankBoekingStatus
from app.db.models import Administratie
from app.db.session import scoped_session
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

# RLZ-documentstatus 3 = Gesloten; een directe bankboeking staat daar direct na de PUT op
# (schrijf-PoC §3) — alles anders (m.n. 1 = teruggezet naar concept) is een afwijking.
_STATUS_GESLOTEN = 3


@dataclass(frozen=True)
class BankAfwijking:
    record_id: uuid.UUID
    payment_transaction_id: uuid.UUID
    soort: str
    detail: str


@dataclass(frozen=True)
class BankReconciliatieRapport:
    administratie_id: uuid.UUID
    boekingen_gecontroleerd: int
    afletteringen_gecontroleerd: int
    afwijkingen: tuple[BankAfwijking, ...]


def reconcilieer_bank(*, administratie_id: uuid.UUID, client: RlzClient | None = None) -> BankReconciliatieRapport:
    with scoped_session(administratie_id) as session:
        boekingen = [
            (b.id, b.rlz_document_id, b.payment_transaction_id)
            for b in session.scalars(
                select(BankBoeking).where(
                    BankBoeking.administratie_id == administratie_id,
                    BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
                )
            )
        ]
        afletteringen = [
            (o.id, o.payment_transaction_id)
            for o in session.scalars(
                select(BankAfletterOpdracht).where(
                    BankAfletterOpdracht.administratie_id == administratie_id,
                    BankAfletterOpdracht.status == AfletterOpdrachtStatus.GEVERIFIEERD.value,
                )
            )
        ]

    if not boekingen and not afletteringen:
        return BankReconciliatieRapport(
            administratie_id=administratie_id,
            boekingen_gecontroleerd=0,
            afletteringen_gecontroleerd=0,
            afwijkingen=(),
        )

    eigen_client = client is None
    if client is None:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    try:
        afwijkingen: list[BankAfwijking] = []
        for boeking_id, rlz_document_id, payment_transaction_id in boekingen:
            try:
                document = client.get_bank_mutation_direct_booking(rlz_document_id)
            except RlzApiError as exc:
                afwijkingen.append(
                    BankAfwijking(boeking_id, payment_transaction_id, "document_ontbreekt_in_rlz", str(exc))
                )
                continue
            if document.get("Status") != _STATUS_GESLOTEN:
                afwijkingen.append(
                    BankAfwijking(
                        boeking_id,
                        payment_transaction_id,
                        "boeking_teruggedraaid_in_rlz",
                        f"RLZ-documentstatus={document.get('Status')} (verwacht {_STATUS_GESLOTEN}) — "
                        "vermoedelijk in de RLZ-UI gestorneerd; beoordeel en verwerk de storno ook hier",
                    )
                )

        for opdracht_id, payment_transaction_id in afletteringen:
            try:
                mutatie = client.get_payment_transaction(payment_transaction_id)
            except RlzApiError as exc:
                afwijkingen.append(
                    BankAfwijking(opdracht_id, payment_transaction_id, "mutatie_niet_leesbaar", str(exc))
                )
                continue
            open_amount = mutatie.get("OpenAmount")
            if open_amount is not None and float(open_amount) != 0.0:
                afwijkingen.append(
                    BankAfwijking(
                        opdracht_id,
                        payment_transaction_id,
                        "aflettering_teruggedraaid_in_rlz",
                        f"OpenAmount={open_amount} terwijl de opdracht als geverifieerd geregistreerd staat",
                    )
                )
    finally:
        if eigen_client:
            client.close()

    return BankReconciliatieRapport(
        administratie_id=administratie_id,
        boekingen_gecontroleerd=len(boekingen),
        afletteringen_gecontroleerd=len(afletteringen),
        afwijkingen=tuple(afwijkingen),
    )


def reconcilieer_bank_alle_administraties() -> dict[uuid.UUID, BankReconciliatieRapport | str]:
    """Zelfde tolerantie-patroon als de documenten-reconciliatie: één kapotte administratie
    stopt de rest niet."""
    with scoped_session(None) as session:
        administratie_ids = [row.id for row in session.scalars(select(Administratie))]

    resultaten: dict[uuid.UUID, BankReconciliatieRapport | str] = {}
    for administratie_id in administratie_ids:
        try:
            resultaten[administratie_id] = reconcilieer_bank(administratie_id=administratie_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie reconcilieer_alle_administraties
            resultaten[administratie_id] = str(exc)
    return resultaten
