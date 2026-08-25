"""Bankmutatie SPLITSEN over meerdere bestemmingen (besluit Peter 25-08, feedbackronde deel 4
punt 4; STAP-0 api-verkenning "Bankmutatie op een RELATIE + mutatie SPLITSEN" §2 is canoniek).

Een splitsing is een GEORDENDE COMPOSITIE van de drie bestaande motoren — per deel een eigen
RLZ-document/koppeling, nooit een nieuwe boekvorm (seam-eis):
  - `open_post`  → actie 15 met expliciet deelbedrag (`afletteren.zet_klaar_voor_afletteren(deelbedrag=)`);
  - `relatie`    → aanbetalingsdocument + actie 15 (`relatie.boek_mutatie_op_relatie(bedrag=, deel_id=)`);
  - `grootboek`  → deel-BankMutationDirectBooking (`boeken.boek_mutatie_direct(deel=)`); kruispost is
                   gewoon een grootboek-bestemming.
Volgorde van uitvoering: open posten → relaties → grootboek (de posten eerst, zodat een
grootboek-deel nooit "over" een open-post-match heen boekt — dezelfde lijn als de sync).

App-regels (server-side blokkerend): Σ delen = mutatiebedrag exact, elk deel ≠ 0 en met het teken
van de mutatie, één actieve splitsing per mutatie, geen splitsing over een mutatie die al een
volledige boeking/koppeling draagt. Half-verwerkt-patroon: faalt een deel, dan stopt de run,
het deel staat op `fout` mét reden, de rest op `wacht`, de splitsing op `half_verwerkt` — zichtbaar
in de UI, nooit stil; `hervat_splitsing` verwerkt de open delen alsnog tegen de VERSE OpenAmount.
Storno per deel via de storno van de onderliggende motor (grootboek/relatie komen netjes terug;
een afletter-deel draait alleen terug via storno van de gekoppelde factuur — RLZ laat dan een
huls achter, zie STAP-0 §2.5).
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.bank import afletteren, boeken, relatie
from app.bank.models import (
    BankBoeking,
    BankBoekingStatus,
    BankMutatie,
    BankRelatieBoeking,
    BankRelatieBoekingStatus,
    BankSplitsing,
    BankSplitsingDeel,
    BankSplitsingDeelSoort,
    BankSplitsingDeelStatus,
    BankSplitsingStatus,
)
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.rlz.client import RlzClient

logger = logging.getLogger(__name__)

_ACTIEVE_STATUSSEN = (
    BankSplitsingStatus.BEZIG.value,
    BankSplitsingStatus.VERWERKT.value,
    BankSplitsingStatus.HALF_VERWERKT.value,
)
_VOLGORDE = {
    BankSplitsingDeelSoort.OPEN_POST.value: 0,
    BankSplitsingDeelSoort.RELATIE.value: 1,
    BankSplitsingDeelSoort.GROOTBOEK.value: 2,
}


class SplitsenFout(Exception):
    pass


class SplitsingOngeldig(SplitsenFout):
    """Delen tellen niet op tot het mutatiebedrag, een deel is 0/verkeerd teken, of een deel mist
    zijn bestemming — blokkerend vóór de eerste RLZ-write."""


class SplitsingBestaatAl(SplitsenFout):
    def __init__(self, splitsing_id: uuid.UUID) -> None:
        self.splitsing_id = splitsing_id
        super().__init__("Deze mutatie heeft al een actieve splitsing")


class SplitsingNietGevonden(SplitsenFout):
    pass


@dataclass(frozen=True)
class DeelInvoer:
    soort: str
    bedrag: Decimal
    # grootboek: regels [{ledger_id, netto_bedrag, btw_bedrag, taxrate_id, project_id, omschrijving}]
    # open_post: payment_item_id
    # relatie:   relatie_soort + entity_id
    spec: dict[str, Any] = field(default_factory=dict)
    omschrijving: str | None = None


@dataclass(frozen=True)
class DeelResultaat:
    deel_id: uuid.UUID
    volgnummer: int
    soort: str
    bedrag: Decimal
    status: str
    fout: str | None
    bank_boeking_id: uuid.UUID | None
    afletter_opdracht_id: uuid.UUID | None
    relatie_boeking_id: uuid.UUID | None


@dataclass(frozen=True)
class SplitsingResultaat:
    splitsing_id: uuid.UUID
    payment_transaction_id: uuid.UUID
    status: str
    mutatie_bedrag: Decimal
    delen: list[DeelResultaat]
    aangemaakt_op: datetime | None = None


def valideer_delen(delen: list[DeelInvoer], *, mutatie_bedrag: Decimal) -> None:
    """Pure geldlogica (code rekent): Σ delen = mutatiebedrag exact, elk deel ≠ 0 met het teken
    van de mutatie, bestemming per soort compleet, minstens twee delen (anders is het geen
    splitsing maar een gewone boeking — die route bestaat al)."""
    if len(delen) < 2:
        raise SplitsingOngeldig("Een splitsing heeft minstens twee delen")
    som = Decimal("0")
    for i, deel in enumerate(delen, start=1):
        if deel.soort not in _VOLGORDE:
            raise SplitsingOngeldig(f"Deel {i}: onbekende bestemming {deel.soort!r}")
        if deel.bedrag == 0 or (deel.bedrag > 0) != (mutatie_bedrag > 0):
            raise SplitsingOngeldig(f"Deel {i}: bedrag {deel.bedrag} moet ≠ 0 zijn en het teken van de mutatie dragen")
        if deel.soort == BankSplitsingDeelSoort.GROOTBOEK.value:
            regels = deel.spec.get("regels") or []
            if not regels:
                raise SplitsingOngeldig(f"Deel {i}: grootboek-deel zonder regels")
            regelsom = sum(
                (Decimal(str(r.get("netto_bedrag", 0))) + Decimal(str(r.get("btw_bedrag") or 0)) for r in regels),
                Decimal("0"),
            )
            if regelsom.quantize(Decimal("0.01")) != deel.bedrag.quantize(Decimal("0.01")):
                raise SplitsingOngeldig(
                    f"Deel {i}: regels (netto + btw) tellen op tot {regelsom}, maar het deel is {deel.bedrag}"
                )
        elif deel.soort == BankSplitsingDeelSoort.OPEN_POST.value:
            if not deel.spec.get("payment_item_id"):
                raise SplitsingOngeldig(f"Deel {i}: open-post-deel zonder payment_item_id")
        elif deel.soort == BankSplitsingDeelSoort.RELATIE.value:
            if not deel.spec.get("entity_id") or deel.spec.get("relatie_soort") not in ("crediteur", "debiteur"):
                raise SplitsingOngeldig(f"Deel {i}: relatie-deel zonder relatie_soort/entity_id")
        som += deel.bedrag
    if som.quantize(Decimal("0.01")) != mutatie_bedrag.quantize(Decimal("0.01")):
        rest = (mutatie_bedrag - som).quantize(Decimal("0.01"))
        raise SplitsingOngeldig(
            f"De delen tellen op tot {som}, de mutatie is {mutatie_bedrag} — rest {rest} moet 0 zijn"
        )


def start_splitsing(
    *,
    administratie_id: uuid.UUID,
    payment_transaction_id: uuid.UUID,
    delen: list[DeelInvoer],
    actor_id: uuid.UUID,
    client: RlzClient,
) -> SplitsingResultaat:
    """Valideert, registreert de splitsing + delen (audit) en verwerkt ze direct in volgorde."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        mutatie = session.get(BankMutatie, (payment_transaction_id, administratie_id))
        if mutatie is None or mutatie.bedrag is None:
            raise boeken.BankMutatieNietGevonden("Bankmutatie niet gevonden in de cache — draai eerst de bank-sync")
        if mutatie.open_bedrag is None or mutatie.open_bedrag == 0:
            raise SplitsingOngeldig("De mutatie staat lokaal niet (meer) open")
        mutatie_bedrag = Decimal(mutatie.bedrag)
        valideer_delen(delen, mutatie_bedrag=mutatie_bedrag)
        if Decimal(mutatie.open_bedrag) != mutatie_bedrag:
            raise SplitsingOngeldig(
                f"De mutatie is al deels verwerkt (open {mutatie.open_bedrag} van {mutatie_bedrag}) — "
                "splitsen kan alleen op een volledig open mutatie"
            )
        bestaand = session.scalars(
            select(BankSplitsing).where(
                BankSplitsing.administratie_id == administratie_id,
                BankSplitsing.payment_transaction_id == payment_transaction_id,
                BankSplitsing.status.in_(_ACTIEVE_STATUSSEN),
            )
        ).first()
        if bestaand is not None:
            raise SplitsingBestaatAl(bestaand.id)
        volle_boeking = session.scalars(
            select(BankBoeking).where(
                BankBoeking.administratie_id == administratie_id,
                BankBoeking.payment_transaction_id == payment_transaction_id,
                BankBoeking.deel_id.is_(None),
                BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
            )
        ).first()
        volle_relatie = session.scalars(
            select(BankRelatieBoeking).where(
                BankRelatieBoeking.administratie_id == administratie_id,
                BankRelatieBoeking.payment_transaction_id == payment_transaction_id,
                BankRelatieBoeking.deel_id.is_(None),
                BankRelatieBoeking.status != BankRelatieBoekingStatus.GESTORNEERD.value,
            )
        ).first()
        if volle_boeking is not None or volle_relatie is not None:
            raise SplitsingOngeldig("Deze mutatie draagt al een volledige boeking of relatie-koppeling")

        splitsing = BankSplitsing(
            administratie_id=administratie_id,
            payment_transaction_id=payment_transaction_id,
            mutatie_bedrag=mutatie_bedrag,
            status=BankSplitsingStatus.BEZIG.value,
            aangemaakt_door=actor_id,
        )
        session.add(splitsing)
        session.flush()
        gesorteerd = sorted(enumerate(delen, start=1), key=lambda t: (_VOLGORDE[t[1].soort], t[0]))
        for volgnummer, (_, deel) in enumerate(gesorteerd, start=1):
            session.add(
                BankSplitsingDeel(
                    splitsing_id=splitsing.id,
                    administratie_id=administratie_id,
                    volgnummer=volgnummer,
                    soort=deel.soort,
                    bedrag=deel.bedrag,
                    spec={**deel.spec, "omschrijving": deel.omschrijving},
                    status=BankSplitsingDeelStatus.WACHT.value,
                )
            )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="bank_splitsing",
            record_id=splitsing.id,
            actie="bank_splitsing_aangemaakt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "payment_transaction_id": str(payment_transaction_id),
                "mutatie_bedrag": str(mutatie_bedrag),
                "delen": [{"soort": d.soort, "bedrag": str(d.bedrag), "spec": d.spec} for _, d in gesorteerd],
            },
            administratie_id=administratie_id,
        )
        splitsing_id = splitsing.id
    return hervat_splitsing(
        administratie_id=administratie_id, splitsing_id=splitsing_id, actor_id=actor_id, client=client
    )


def hervat_splitsing(
    *, administratie_id: uuid.UUID, splitsing_id: uuid.UUID, actor_id: uuid.UUID, client: RlzClient
) -> SplitsingResultaat:
    """Verwerkt alle delen die nog op `wacht`/`fout` staan, in volgorde; stopt bij de eerste
    fout (rest blijft `wacht`). Herstel = deze functie opnieuw (verse OpenAmount leidend in
    elke onderliggende motor). Idempotent per deel: een al verwerkt deel wordt overgeslagen."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        splitsing = session.get(BankSplitsing, splitsing_id)
        if splitsing is None or splitsing.administratie_id != administratie_id:
            raise SplitsingNietGevonden("Splitsing niet gevonden")
        if splitsing.status == BankSplitsingStatus.GESTORNEERD.value:
            raise SplitsenFout("Deze splitsing is gestorneerd")
        delen = list(
            session.scalars(
                select(BankSplitsingDeel)
                .where(BankSplitsingDeel.splitsing_id == splitsing_id)
                .order_by(BankSplitsingDeel.volgnummer)
            )
        )
        te_doen = [
            (d.id, d.soort, Decimal(d.bedrag), dict(d.spec or {}), d.cyclus)
            for d in delen
            if d.status in (BankSplitsingDeelStatus.WACHT.value, BankSplitsingDeelStatus.FOUT.value)
        ]
        tx_id = splitsing.payment_transaction_id

    for deel_id, soort, bedrag, spec, cyclus in te_doen:
        fout: str | None = None
        resultaat: dict[str, uuid.UUID | None] = {}
        try:
            resultaat = _verwerk_deel(
                administratie_id=administratie_id, tx_id=tx_id, deel_id=deel_id, soort=soort, bedrag=bedrag,
                spec=spec, cyclus=cyclus, actor_id=actor_id, client=client,
            )
        except Exception as exc:  # noqa: BLE001 — élke fout moet zichtbaar op het deel landen
            logger.warning("Splitsing %s deel %s faalt: %s", splitsing_id, deel_id, exc)
            fout = str(exc)
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            deel = session.get(BankSplitsingDeel, deel_id)
            assert deel is not None
            if fout is None:
                deel.status = BankSplitsingDeelStatus.VERWERKT.value
                deel.fout = None
                deel.verwerkt_op = datetime.now(UTC)
                deel.bank_boeking_id = resultaat.get("bank_boeking_id")
                deel.afletter_opdracht_id = resultaat.get("afletter_opdracht_id")
                deel.relatie_boeking_id = resultaat.get("relatie_boeking_id")
            else:
                deel.status = BankSplitsingDeelStatus.FOUT.value
                deel.fout = fout
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="bank_splitsing_deel",
                record_id=deel_id,
                actie="bank_splitsing_deel_verwerkt" if fout is None else "bank_splitsing_deel_mislukt",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"soort": soort, "bedrag": str(bedrag), "fout": fout,
                               **{k: str(v) for k, v in resultaat.items() if v}},
                administratie_id=administratie_id,
            )
        if fout is not None:
            break

    return _werk_status_bij(administratie_id=administratie_id, splitsing_id=splitsing_id, actor_id=actor_id)


def _verwerk_deel(
    *, administratie_id: uuid.UUID, tx_id: uuid.UUID, deel_id: uuid.UUID, soort: str, bedrag: Decimal,
    spec: dict[str, Any], cyclus: int, actor_id: uuid.UUID, client: RlzClient,
) -> dict[str, uuid.UUID | None]:
    omschrijving = spec.get("omschrijving")
    if soort == BankSplitsingDeelSoort.OPEN_POST.value:
        uitvoering = afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id,
            payment_transaction_id=tx_id,
            payment_item_id=uuid.UUID(str(spec["payment_item_id"])),
            actor_id=actor_id,
            voorstel_detail={"bron": "splitsing", "deel_id": str(deel_id)},
            client=client,
            deelbedrag=bedrag,
        )
        if uitvoering.uitkomst == "wacht_op_mens_in_rlz":
            raise SplitsenFout(uitvoering.fout or "koppeling niet gelegd (assist-opdracht klaargezet)")
        return {"afletter_opdracht_id": uitvoering.opdracht_id}
    if soort == BankSplitsingDeelSoort.RELATIE.value:
        r = relatie.boek_mutatie_op_relatie(
            administratie_id=administratie_id,
            payment_transaction_id=tx_id,
            relatie_soort=str(spec["relatie_soort"]),
            entity_id=uuid.UUID(str(spec["entity_id"])),
            actor_id=actor_id,
            client=client,
            bedrag=bedrag,
            omschrijving=omschrijving,
            deel_id=deel_id,
        )
        return {"relatie_boeking_id": r.boeking_id}
    regels = [
        boeken.BankBoekRegelInput(
            ledger_id=uuid.UUID(str(r["ledger_id"])),
            netto_bedrag=Decimal(str(r["netto_bedrag"])),
            btw_bedrag=Decimal(str(r["btw_bedrag"])) if r.get("btw_bedrag") is not None else None,
            taxrate_id=uuid.UUID(str(r["taxrate_id"])) if r.get("taxrate_id") else None,
            project_id=uuid.UUID(str(r["project_id"])) if r.get("project_id") else None,
            omschrijving=r.get("omschrijving"),
        )
        for r in spec.get("regels") or []
    ]
    b = boeken.boek_mutatie_direct(
        administratie_id=administratie_id,
        payment_transaction_id=tx_id,
        regels=regels,
        actor_id=actor_id,
        omschrijving=omschrijving,
        client=client,
        deel=boeken.DeelBoeking(deel_id=deel_id, bedrag=bedrag, cyclus=cyclus),
    )
    return {"bank_boeking_id": b.boeking_id}


def _werk_status_bij(*, administratie_id: uuid.UUID, splitsing_id: uuid.UUID, actor_id: uuid.UUID) -> SplitsingResultaat:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        splitsing = session.get(BankSplitsing, splitsing_id)
        assert splitsing is not None
        delen = list(
            session.scalars(
                select(BankSplitsingDeel)
                .where(BankSplitsingDeel.splitsing_id == splitsing_id)
                .order_by(BankSplitsingDeel.volgnummer)
            )
        )
        statussen = {d.status for d in delen}
        oud = splitsing.status
        if statussen <= {BankSplitsingDeelStatus.VERWERKT.value}:
            splitsing.status = BankSplitsingStatus.VERWERKT.value
        elif statussen <= {BankSplitsingDeelStatus.GESTORNEERD.value}:
            splitsing.status = BankSplitsingStatus.GESTORNEERD.value
            splitsing.gestorneerd_op = datetime.now(UTC)
        elif BankSplitsingDeelStatus.VERWERKT.value in statussen or BankSplitsingDeelStatus.FOUT.value in statussen:
            splitsing.status = BankSplitsingStatus.HALF_VERWERKT.value
        else:
            splitsing.status = BankSplitsingStatus.BEZIG.value
        splitsing.laatst_verwerkt_op = datetime.now(UTC)
        if oud != splitsing.status:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="bank_splitsing",
                record_id=splitsing_id,
                actie="bank_splitsing_status_gewijzigd",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"status": oud},
                nieuwe_waarde={"status": splitsing.status},
                administratie_id=administratie_id,
            )
        return _dto(splitsing, delen)


def _dto(splitsing: BankSplitsing, delen: list[BankSplitsingDeel]) -> SplitsingResultaat:
    return SplitsingResultaat(
        splitsing_id=splitsing.id,
        payment_transaction_id=splitsing.payment_transaction_id,
        status=splitsing.status,
        mutatie_bedrag=Decimal(splitsing.mutatie_bedrag),
        aangemaakt_op=splitsing.aangemaakt_op,
        delen=[
            DeelResultaat(
                deel_id=d.id, volgnummer=d.volgnummer, soort=d.soort, bedrag=Decimal(d.bedrag), status=d.status,
                fout=d.fout, bank_boeking_id=d.bank_boeking_id, afletter_opdracht_id=d.afletter_opdracht_id,
                relatie_boeking_id=d.relatie_boeking_id,
            )
            for d in delen
        ],
    )


def splitsingen_voor_rekening(
    *, administratie_id: uuid.UUID, payment_account_id: uuid.UUID | None = None
) -> list[SplitsingResultaat]:
    """Leeslijst voor het bankscherm: actieve splitsingen (bezig/verwerkt/half_verwerkt) mét delen."""
    with scoped_session(administratie_id) as session:
        q = select(BankSplitsing).where(
            BankSplitsing.administratie_id == administratie_id,
            BankSplitsing.status.in_(_ACTIEVE_STATUSSEN),
        )
        if payment_account_id is not None:
            q = q.join(
                BankMutatie,
                (BankMutatie.id == BankSplitsing.payment_transaction_id)
                & (BankMutatie.administratie_id == BankSplitsing.administratie_id),
            ).where(BankMutatie.payment_account_id == payment_account_id)
        uit = []
        for splitsing in session.scalars(q.order_by(BankSplitsing.aangemaakt_op.desc())):
            delen = list(
                session.scalars(
                    select(BankSplitsingDeel)
                    .where(BankSplitsingDeel.splitsing_id == splitsing.id)
                    .order_by(BankSplitsingDeel.volgnummer)
                )
            )
            uit.append(_dto(splitsing, delen))
        return uit


def storno_deel(
    *, administratie_id: uuid.UUID, deel_id: uuid.UUID, actor_id: uuid.UUID, reden: str, client: RlzClient
) -> SplitsingResultaat:
    """Storno van één verwerkt deel via de storno van de onderliggende motor (reden verplicht,
    aangifte-poort in die motor). Een open-post-deel is niet via de app te storneren (Type 16
    is dood; terugdraaien = storno van de gekoppelde factuur in RLZ) — zichtbare fout. Het deel
    gaat op `gestorneerd` en krijgt cyclus+1 zodat een herverwerking een nieuw GUID gebruikt."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        deel = session.get(BankSplitsingDeel, deel_id)
        if deel is None or deel.administratie_id != administratie_id:
            raise SplitsingNietGevonden("Deel niet gevonden")
        if deel.status != BankSplitsingDeelStatus.VERWERKT.value:
            raise SplitsenFout(f"Deel staat op {deel.status!r} en kan niet gestorneerd worden")
        soort, bank_boeking_id, relatie_boeking_id, splitsing_id = (
            deel.soort, deel.bank_boeking_id, deel.relatie_boeking_id, deel.splitsing_id,
        )
    if soort == BankSplitsingDeelSoort.OPEN_POST.value:
        raise SplitsenFout(
            "Een afletter-deel is via de API niet te ontkoppelen (Type 16 werkt in geen vorm) — draai het "
            "terug door de gekoppelde factuur in Reeleezee te storneren; de reconciliatie signaleert het"
        )
    if soort == BankSplitsingDeelSoort.GROOTBOEK.value and bank_boeking_id is not None:
        boeken.storno_bank_boeking(
            administratie_id=administratie_id, boeking_id=bank_boeking_id, actor_id=actor_id, reden=reden, client=client
        )
    elif soort == BankSplitsingDeelSoort.RELATIE.value and relatie_boeking_id is not None:
        relatie.storno_relatie_boeking(
            administratie_id=administratie_id, boeking_id=relatie_boeking_id, actor_id=actor_id, reden=reden, client=client
        )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        deel = session.get(BankSplitsingDeel, deel_id)
        assert deel is not None
        deel.status = BankSplitsingDeelStatus.GESTORNEERD.value
        deel.cyclus = (deel.cyclus or 0) + 1
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="bank_splitsing_deel",
            record_id=deel_id,
            actie="bank_splitsing_deel_gestorneerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"soort": soort, "reden": reden, "cyclus": deel.cyclus},
            administratie_id=administratie_id,
        )
    return _werk_status_bij(administratie_id=administratie_id, splitsing_id=splitsing_id, actor_id=actor_id)
