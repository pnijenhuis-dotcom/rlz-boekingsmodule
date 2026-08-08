"""Leesservices voor de bank-schermen (overzicht + bankdetail) en het vaste-regels-beheer.
Alles leest uit de eigen caches — nooit live uit RLZ in een request (dat doet alleen de
sync-trigger en de schrijfacties, die verse staat nodig hebben)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import func, select

from app.bank import matchmotor
from app.bank.models import BankMutatie, BankRegel, BankSyncStand, PaymentAccountCache
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session

# PaymentAccountTypes (STAP 0 §1): 3 = Cash (Kasdagboek) — kas heeft geen bankaanlevering nodig.
REKENING_TYPE_KAS = 3


class BankServiceFout(Exception):
    pass


class BankRegelBestaatAl(BankServiceFout):
    pass


@dataclass(frozen=True)
class BankKlant:
    administratie_id: uuid.UUID
    naam: str
    open_mutaties: int
    oudste_open_datum: date | None
    rekeningen: list[str]
    laatste_sync_op: datetime | None
    ooit_gesynchroniseerd: bool


def bank_overzicht(*, administratie_ids_met_naam: list[tuple[uuid.UUID, str]]) -> list[BankKlant]:
    """Tellers per administratie voor het bank-overzicht (mockup #bank). De aanroeper (router)
    levert uitsluitend administraties binnen de scope van de gebruiker aan."""
    klanten: list[BankKlant] = []
    for administratie_id, naam in administratie_ids_met_naam:
        with scoped_session(administratie_id) as session:
            open_stats = session.execute(
                select(func.count(), func.min(BankMutatie.boekdatum)).where(
                    BankMutatie.administratie_id == administratie_id,
                    BankMutatie.open_bedrag.isnot(None),
                    BankMutatie.open_bedrag != 0,
                )
            ).one()
            rekeningen = [
                rij_naam
                for rij_naam in session.scalars(
                    select(PaymentAccountCache.naam)
                    .where(
                        PaymentAccountCache.administratie_id == administratie_id,
                        PaymentAccountCache.verdwenen_uit_bron_op.is_(None),
                        PaymentAccountCache.is_gearchiveerd.isnot(True),
                    )
                    .order_by(PaymentAccountCache.naam)
                )
                if rij_naam
            ]
            stand = session.get(BankSyncStand, administratie_id)
        klanten.append(
            BankKlant(
                administratie_id=administratie_id,
                naam=naam,
                open_mutaties=open_stats[0] or 0,
                oudste_open_datum=open_stats[1],
                rekeningen=rekeningen,
                laatste_sync_op=stand.laatste_sync_op if stand else None,
                ooit_gesynchroniseerd=stand is not None and stand.laatste_sync_op is not None,
            )
        )
    return klanten


@dataclass(frozen=True)
class Rekening:
    id: uuid.UUID
    naam: str | None
    iban: str | None
    rekening_type: int | None
    is_kas: bool
    saldo: object
    saldo_datum: date | None
    open_mutaties: int
    heeft_aanlevering: bool
    laatste_import: dict | None
    probe_fout: str | None


@dataclass(frozen=True)
class RekeningOverzicht:
    rekeningen: list[Rekening]
    laatste_sync_op: datetime | None
    ooit_gesynchroniseerd: bool
    heeft_bankaanlevering: bool


def rekeningen_overzicht(*, administratie_id: uuid.UUID) -> RekeningOverzicht:
    """Bankpicker-data (mockup #bankdetail): alle niet-gearchiveerde rekeningen incl. kas, met
    saldo, versheid en open-teller. `heeft_bankaanlevering` is de onboarding-check (STAP 0):
    minstens één bankrekening met een LastBankImport óf een actieve PSD2-gateway — kas telt
    niet mee (die hééft geen aanlevering nodig)."""
    with scoped_session(administratie_id) as session:
        rijen = list(
            session.scalars(
                select(PaymentAccountCache)
                .where(
                    PaymentAccountCache.administratie_id == administratie_id,
                    PaymentAccountCache.verdwenen_uit_bron_op.is_(None),
                    PaymentAccountCache.is_gearchiveerd.isnot(True),
                )
                .order_by(PaymentAccountCache.rekening_type, PaymentAccountCache.naam)
            )
        )
        tellers = dict(
            session.execute(
                select(BankMutatie.payment_account_id, func.count())
                .where(
                    BankMutatie.administratie_id == administratie_id,
                    BankMutatie.open_bedrag.isnot(None),
                    BankMutatie.open_bedrag != 0,
                )
                .group_by(BankMutatie.payment_account_id)
            ).all()
        )
        stand = session.get(BankSyncStand, administratie_id)

    rekeningen: list[Rekening] = []
    heeft_bankaanlevering = False
    for rij in rijen:
        is_kas = rij.rekening_type == REKENING_TYPE_KAS
        # BankGatewayStates: 0 = Active (STAP 0 §1) — een actieve PSD2-koppeling telt als
        # aanlevering, ook als er (nog) geen importbestand is gezien.
        heeft_aanlevering = rij.laatste_import is not None or rij.gateway_state == 0
        if heeft_aanlevering and not is_kas:
            heeft_bankaanlevering = True
        rekeningen.append(
            Rekening(
                id=rij.id,
                naam=rij.naam,
                iban=rij.iban,
                rekening_type=rij.rekening_type,
                is_kas=is_kas,
                saldo=rij.saldo,
                saldo_datum=rij.saldo_datum,
                open_mutaties=tellers.get(rij.id, 0),
                heeft_aanlevering=heeft_aanlevering,
                laatste_import=rij.laatste_import,
                probe_fout=rij.laatste_import_probe_fout,
            )
        )
    return RekeningOverzicht(
        rekeningen=rekeningen,
        laatste_sync_op=stand.laatste_sync_op if stand else None,
        ooit_gesynchroniseerd=stand is not None and stand.laatste_sync_op is not None,
        heeft_bankaanlevering=heeft_bankaanlevering,
    )


def lijst_bank_regels(*, administratie_id: uuid.UUID) -> list[BankRegel]:
    with scoped_session(administratie_id) as session:
        return list(
            session.scalars(
                select(BankRegel)
                .where(BankRegel.administratie_id == administratie_id, BankRegel.actief.is_(True))
                .order_by(BankRegel.tegenpartij_sleutel)
            )
        )


def maak_bank_regel(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    tegenpartij_naam: str,
    ledger_id: uuid.UUID,
    taxrate_id: uuid.UUID | None = None,
    project_id: uuid.UUID | None = None,
    tegenrekening_iban: str | None = None,
    omschrijving: str | None = None,
) -> BankRegel:
    """Vaste regel aanmaken — altijd een menselijke actie (bevestiging van het 3×-voorstel of
    het vinkje bij een handmatige boeking), met audit_event. Eén actieve regel per
    tegenpartij-sleutel (ook door de partiële unique index afgedwongen)."""
    sleutel = matchmotor.tegenpartij_sleutel(tegenpartij_naam)
    if sleutel is None:
        raise BankServiceFout("Tegenpartijnaam levert geen bruikbare regel-sleutel op")

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BankServiceFout(f"Onbekende administratie: {administratie_id}")
        bestaande = session.scalars(
            select(BankRegel).where(
                BankRegel.administratie_id == administratie_id,
                BankRegel.tegenpartij_sleutel == sleutel,
                BankRegel.actief.is_(True),
            )
        ).first()
        if bestaande is not None:
            raise BankRegelBestaatAl(f"Er bestaat al een actieve vaste regel voor {tegenpartij_naam!r}")
        regel = BankRegel(
            administratie_id=administratie_id,
            tegenpartij_sleutel=sleutel,
            tegenrekening_iban=tegenrekening_iban,
            ledger_id=ledger_id,
            taxrate_id=taxrate_id,
            project_id=project_id,
            omschrijving=omschrijving,
            actief=True,
            aangemaakt_door=actor_id,
        )
        session.add(regel)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="bank_regel",
            record_id=regel.id,
            actie="bank_regel_aangemaakt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "tegenpartij_sleutel": sleutel,
                "ledger_id": str(ledger_id),
                "taxrate_id": str(taxrate_id) if taxrate_id else None,
            },
            administratie_id=administratie_id,
        )
        return regel
