from __future__ import annotations

import hashlib
import uuid
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.reconciliatie.models import ReconciliatieAcceptatie, ReconciliatieBron

# 16 hex = 64 bits. Lang genoeg dat een toevallige botsing tussen twee afwijkingen binnen één
# administratie verwaarloosbaar is, kort genoeg om uit een terminal over te typen. Dit is geen
# beveiligingsgrens (niemand valt zijn eigen reconciliatie aan) maar een leesbare sleutel.
_VINGERAFDRUK_LENGTE = 16
# Een reden van drie tekens ("ok", "n.v.t.") is geen reden. Zelfde ondergrens als bij afwijzen.
_MINIMALE_REDEN = 5


class AcceptatieFout(Exception):
    """Acceptatie geweigerd — nooit stil negeren, de aanroeper toont dit aan de mens."""


@dataclass(frozen=True)
class AcceptatieInfo:
    """Platte weergave van een actieve acceptatie (geen ORM-object over de grens, zodat de
    rapportlaag geen sessie meer nodig heeft)."""

    id: uuid.UUID
    reden: str
    geaccepteerd_door: uuid.UUID
    geaccepteerd_op: datetime


@dataclass(frozen=True)
class Beoordeeld:
    """Eén afwijking mét het oordeel erbij: `acceptatie is None` = telt mee (echt signaal),
    anders = beoordeeld en bewust blijvend (zichtbaar, maar niet blokkerend)."""

    record_id: uuid.UUID
    soort: str
    detail: str
    vingerafdruk: str
    acceptatie: AcceptatieInfo | None

    @property
    def telt_mee(self) -> bool:
        return self.acceptatie is None


def vingerafdruk(*, bron: str, soort: str, detail: str) -> str:
    """Stabiele sleutel van één afwijking. Bewust óók over `detail`: dat is precies wat een
    acceptatie zo smal houdt dat een veranderde situatie opnieuw alarmeert. `detail` is voor
    elke soort deterministisch opgebouwd (RLZ-foutregel, bedragen, statuscode) — een wisselend
    detail betekent dus een wisselende werkelijkheid en hoort een nieuw signaal te zijn."""
    ruw = f"{bron}|{soort}|{detail}".encode()
    return hashlib.sha256(ruw).hexdigest()[:_VINGERAFDRUK_LENGTE]


def _actieve_acceptaties(*, administratie_id: uuid.UUID, bron: str) -> dict[str, AcceptatieInfo]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(ReconciliatieAcceptatie).where(
                ReconciliatieAcceptatie.administratie_id == administratie_id,
                ReconciliatieAcceptatie.bron == bron,
                ReconciliatieAcceptatie.ingetrokken_op.is_(None),
            )
        ).all()
        return {
            rij.vingerafdruk: AcceptatieInfo(
                id=rij.id,
                reden=rij.reden,
                geaccepteerd_door=rij.geaccepteerd_door,
                geaccepteerd_op=rij.geaccepteerd_op,
            )
            for rij in rijen
        }


def beoordeel(
    *, bron: ReconciliatieBron | str, administratie_id: uuid.UUID, afwijkingen: Sequence[tuple[uuid.UUID, str, str]]
) -> list[Beoordeeld]:
    """Legt de afwijkingen (record_id, soort, detail) naast de actieve acceptaties van deze
    administratie. Doet geen enkele RLZ-aanroep en filtert niets weg — het rapport toont alles,
    alleen de telling voor de exit-code gebruikt `telt_mee`."""
    bron_waarde = str(bron)
    if not afwijkingen:
        return []
    acceptaties = _actieve_acceptaties(administratie_id=administratie_id, bron=bron_waarde)
    return [
        Beoordeeld(
            record_id=record_id,
            soort=soort,
            detail=detail,
            vingerafdruk=(vaf := vingerafdruk(bron=bron_waarde, soort=soort, detail=detail)),
            acceptatie=acceptaties.get(vaf),
        )
        for record_id, soort, detail in afwijkingen
    ]


def _vereis_beheerder(session: Session, beheerder_id: uuid.UUID) -> None:
    """Accepteren is een beheerdershandeling: het maakt een blokkerend signaal niet-blokkerend.
    De CLI heeft geen router-laag met `vereis_rol` voor zich, dus de check hoort hier."""
    gebruiker = session.get(Gebruiker, beheerder_id)
    if gebruiker is None or gebruiker.status != GebruikerStatus.ACTIEF:
        raise AcceptatieFout(f"Onbekende of niet-actieve gebruiker: {beheerder_id}")
    if gebruiker.rol != GebruikerRol.BEHEERDER:
        raise AcceptatieFout("Alleen een Beheerder kan een reconciliatie-afwijking accepteren of intrekken")


def accepteer(
    *,
    administratie_id: uuid.UUID,
    bron: ReconciliatieBron | str,
    record_id: uuid.UUID,
    soort: str,
    detail: str,
    reden: str,
    beheerder_id: uuid.UUID,
) -> uuid.UUID:
    """Markeert precies deze afwijking als beoordeeld-en-blijvend. Idempotent: een tweede
    acceptatie van dezelfde vingerafdruk hergebruikt de bestaande rij (de partiële unieke index
    dwingt dat ook op DB-niveau af)."""
    if len((reden or "").strip()) < _MINIMALE_REDEN:
        raise AcceptatieFout("Een acceptatie vereist een inhoudelijke reden")
    bron_waarde = str(bron)
    if bron_waarde not in {b.value for b in ReconciliatieBron}:
        raise AcceptatieFout(f"Onbekende bron: {bron_waarde}")
    vaf = vingerafdruk(bron=bron_waarde, soort=soort, detail=detail)

    with scoped_session(administratie_id, actor_id=beheerder_id) as session:
        _vereis_beheerder(session, beheerder_id)
        bestaand = session.scalars(
            select(ReconciliatieAcceptatie).where(
                ReconciliatieAcceptatie.administratie_id == administratie_id,
                ReconciliatieAcceptatie.bron == bron_waarde,
                ReconciliatieAcceptatie.vingerafdruk == vaf,
                ReconciliatieAcceptatie.ingetrokken_op.is_(None),
            )
        ).one_or_none()
        if bestaand is not None:
            return bestaand.id

        acceptatie = ReconciliatieAcceptatie(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            bron=bron_waarde,
            record_id=record_id,
            soort=soort,
            vingerafdruk=vaf,
            detail=detail,
            reden=reden.strip(),
            geaccepteerd_door=beheerder_id,
        )
        session.add(acceptatie)
        record_audit_event(
            session,
            actor_id=beheerder_id,
            module="boekhouding",
            tabel="reconciliatie_acceptatie",
            record_id=acceptatie.id,
            actie="reconciliatie_afwijking_geaccepteerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "bron": bron_waarde,
                "record_id": str(record_id),
                "soort": soort,
                "vingerafdruk": vaf,
                "detail": detail,
                "reden": reden.strip(),
            },
            administratie_id=administratie_id,
        )
        return acceptatie.id


def auto_accepteer(
    *,
    administratie_id: uuid.UUID,
    bron: ReconciliatieBron | str,
    record_id: uuid.UUID,
    soort: str,
    detail: str,
    reden: str,
    extra: dict | None = None,
) -> tuple[uuid.UUID, bool]:
    """Reconciliatie-nazorg 15-09: het SYSTEEM accepteert een afwijking die volgens een deterministische regel geen
    handeling vraagt (nu: `bedrag_wijkt_af` ≤ € 0,05 = btw-cent-afronding, `app/documenten/reconciliatie.py::
    afrondingsverschil`). Zelfde smalle vingerafdruk als een mens-acceptatie (verandert het bedrag, dan is het opnieuw
    een signaal), zelfde tabel, eigen audit-actie `reconciliatie_auto_geaccepteerd` met de regel als reden en de
    systeem-actor als acceptant — in Inzicht › Reconciliatie leesbaar als "automatisch (afronding ≤ 0,05)". Idempotent:
    → (acceptatie-id, nieuw). Een Beheerder kan 'm gewoon intrekken; dan blijft 'm de run daarna een open afwijking
    (er wordt nooit opnieuw automatisch geaccepteerd zolang er een ingetrokken acceptatie op deze vingerafdruk
    staat)."""
    bron_waarde = str(bron)
    if bron_waarde not in {b.value for b in ReconciliatieBron}:
        raise AcceptatieFout(f"Onbekende bron: {bron_waarde}")
    vaf = vingerafdruk(bron=bron_waarde, soort=soort, detail=detail)
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaand = session.scalars(
            select(ReconciliatieAcceptatie)
            .where(
                ReconciliatieAcceptatie.administratie_id == administratie_id,
                ReconciliatieAcceptatie.bron == bron_waarde,
                ReconciliatieAcceptatie.vingerafdruk == vaf,
            )
            .order_by(ReconciliatieAcceptatie.geaccepteerd_op.desc())
        ).first()
        if bestaand is not None:
            # Actief → hergebruik; ingetrokken door een mens → die wint, nooit stil opnieuw accepteren.
            return bestaand.id, False
        acceptatie = ReconciliatieAcceptatie(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            bron=bron_waarde,
            record_id=record_id,
            soort=soort,
            vingerafdruk=vaf,
            detail=detail,
            reden=f"automatisch ({reden})",
            geaccepteerd_door=SYSTEEM_ACTOR_ID,
        )
        session.add(acceptatie)
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="reconciliatie_acceptatie",
            record_id=acceptatie.id,
            actie="reconciliatie_auto_geaccepteerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "bron": bron_waarde,
                "record_id": str(record_id),
                "soort": soort,
                "vingerafdruk": vaf,
                "detail": detail,
                "reden": reden,
                **(extra or {}),
            },
            administratie_id=administratie_id,
        )
        return acceptatie.id, True


def trek_in(
    *,
    administratie_id: uuid.UUID,
    bron: ReconciliatieBron | str,
    vingerafdruk_waarde: str,
    reden: str,
    beheerder_id: uuid.UUID,
) -> uuid.UUID:
    """Zet de acceptatie terug: de afwijking telt vanaf de volgende run weer mee. Nooit een
    delete — de rij blijft met `ingetrokken_op/-door` staan."""
    if len((reden or "").strip()) < _MINIMALE_REDEN:
        raise AcceptatieFout("Intrekken vereist een inhoudelijke reden")
    bron_waarde = str(bron)
    with scoped_session(administratie_id, actor_id=beheerder_id) as session:
        _vereis_beheerder(session, beheerder_id)
        acceptatie = session.scalars(
            select(ReconciliatieAcceptatie).where(
                ReconciliatieAcceptatie.administratie_id == administratie_id,
                ReconciliatieAcceptatie.bron == bron_waarde,
                ReconciliatieAcceptatie.vingerafdruk == vingerafdruk_waarde,
                ReconciliatieAcceptatie.ingetrokken_op.is_(None),
            )
        ).one_or_none()
        if acceptatie is None:
            raise AcceptatieFout(
                f"Geen actieve acceptatie met vingerafdruk {vingerafdruk_waarde} voor bron {bron_waarde}"
            )
        acceptatie.ingetrokken_op = datetime.now(UTC)
        acceptatie.ingetrokken_door = beheerder_id
        record_audit_event(
            session,
            actor_id=beheerder_id,
            module="boekhouding",
            tabel="reconciliatie_acceptatie",
            record_id=acceptatie.id,
            actie="reconciliatie_acceptatie_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"vingerafdruk": vingerafdruk_waarde, "reden": acceptatie.reden},
            nieuwe_waarde={"ingetrokken_reden": reden.strip()},
            administratie_id=administratie_id,
        )
        return acceptatie.id


def uitgesloten_administraties() -> dict[uuid.UUID, str]:
    """administratie_id → reden, voor de administraties die van de exit-code zijn uitgesloten
    (migratie 0043). Bewust hier en niet in de drie reconciliatie-modules: die blijven puur
    "wat zegt RLZ", het wegen van de uitkomst hoort in de rapportlaag."""
    with scoped_session(None) as session:
        rijen = session.execute(
            select(Administratie.id, Administratie.reconciliatie_uitsluiting_reden).where(
                Administratie.reconciliatie_uitgesloten.is_(True)
            )
        ).all()
    return {rij.id: rij.reconciliatie_uitsluiting_reden or "geen reden vastgelegd" for rij in rijen}


def actieve_acceptaties_overzicht(*, administratie_id: uuid.UUID) -> list[ReconciliatieAcceptatie]:
    """Alle actieve acceptaties van één administratie — voor het overzichtscommando, zodat een
    acceptatie nooit onzichtbaar wordt als de afwijking zelf tijdelijk niet optreedt."""
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(ReconciliatieAcceptatie)
                .where(
                    ReconciliatieAcceptatie.administratie_id == administratie_id,
                    ReconciliatieAcceptatie.ingetrokken_op.is_(None),
                )
                .order_by(ReconciliatieAcceptatie.geaccepteerd_op)
            )
        )
