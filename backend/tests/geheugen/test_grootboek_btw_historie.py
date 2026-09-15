"""Btw-default per grootboekrekening uit de historie (app/geheugen/grootboek_btw_historie.py; migratie 0143) — drempels
uit de opdrachttekst: 4 regels = niets, 5/5 = ja, 9/10 = ja, 8/10 = nee; venster 24 maanden; regels zonder tarief
tellen niet; herberekening schrijft alleen wijzigingen en zet een vervallen default terug op NULL."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from sqlalchemy import select

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.geheugen import grootboek_btw_historie as motor
from app.geheugen.models import BoekingObservatie

HOOG = uuid.UUID("55555555-0000-0000-0000-000000000021")
LAAG = uuid.UUID("55555555-0000-0000-0000-000000000009")
GB_4404 = uuid.UUID("44444444-0000-0000-0000-000000004404")
GB_4403 = uuid.UUID("44444444-0000-0000-0000-000000004403")
VANDAAG = date(2026, 9, 14)


class TestBepaalDefaultDrempels:
    def test_vier_regels_is_niets(self) -> None:
        uitkomst = motor.bepaal_default({HOOG: 4})
        assert uitkomst is not None and uitkomst.taxrate_id is None
        assert (uitkomst.n, uitkomst.aandeel) == (4, Decimal("1.0000"))

    def test_vijf_van_vijf_is_ja(self) -> None:
        assert motor.bepaal_default({HOOG: 5}) == motor.HistorieDefault(HOOG, 5, Decimal("1.0000"))

    def test_negen_van_tien_is_ja(self) -> None:
        assert motor.bepaal_default({HOOG: 9, LAAG: 1}) == motor.HistorieDefault(HOOG, 10, Decimal("0.9000"))

    def test_acht_van_tien_is_nee_maar_verdeling_blijft_zichtbaar(self) -> None:
        assert motor.bepaal_default({HOOG: 8, LAAG: 2}) == motor.HistorieDefault(None, 10, Decimal("0.8000"))

    def test_geen_regels_is_none_en_none_tarief_telt_niet(self) -> None:
        assert motor.bepaal_default({}) is None
        assert motor.bepaal_default({None: 7}) is None  # type: ignore[dict-item]
        assert motor.bepaal_default({HOOG: 5, None: 100}) == motor.HistorieDefault(HOOG, 5, Decimal("1.0000"))  # type: ignore[dict-item]


def _rekening(administratie_id: uuid.UUID, ledger_id: uuid.UUID, code: str) -> Grootboekrekening:
    return Grootboekrekening(
        ledger_id=ledger_id,
        administratie_id=administratie_id,
        code=code,
        naam=f"Rekening {code}",
        soort=2,
        is_totaalrekening=False,
    )


def _observatie(administratie_id: uuid.UUID, gb: uuid.UUID, btw: uuid.UUID | None, datum: date) -> BoekingObservatie:
    return BoekingObservatie(
        id=uuid.uuid4(),
        administratie_id=administratie_id,
        vendor_id=uuid.uuid4(),
        regel_sleutel=None,
        gb_id=gb,
        btw_id=btw,
        bron="rlz_seed",
        bron_datum=datum,
        boekstuk_ref="R-1",
    )


@pytest.fixture
def stam(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        session.add(_rekening(administratie_id, GB_4404, "4404"))
        session.add(_rekening(administratie_id, GB_4403, "4403"))


def _stand(administratie_id: uuid.UUID) -> dict[str, tuple]:
    with scoped_session(administratie_id) as session:
        return {
            r.code: (r.historie_taxrate_id, r.historie_taxrate_n, r.historie_taxrate_aandeel, r.historie_berekend_op is not None)
            for r in session.scalars(
                select(Grootboekrekening).where(Grootboekrekening.administratie_id == administratie_id)
            )
        }


def test_herbereken_schrijft_default_venster_en_regels_zonder_tarief(administratie_id: uuid.UUID, stam: None) -> None:
    recent = VANDAAG - timedelta(days=30)
    oud = VANDAAG - timedelta(days=motor.HISTORIE_DAGEN + 1)
    with scoped_session(administratie_id) as session:
        for _ in range(9):
            session.add(_observatie(administratie_id, GB_4404, HOOG, recent))
        session.add(_observatie(administratie_id, GB_4404, LAAG, recent))
        for _ in range(20):
            session.add(_observatie(administratie_id, GB_4404, LAAG, oud))  # buiten het venster: telt niet
        session.add(_observatie(administratie_id, GB_4404, None, recent))  # zonder tarief: telt niet
        for _ in range(4):
            session.add(_observatie(administratie_id, GB_4403, HOOG, recent))  # 4 regels: te weinig

    rapport = motor.herbereken_voor(administratie_id, vandaag=VANDAAG)
    assert (rapport.rekeningen, rapport.met_default, rapport.zonder_default_met_regels, rapport.gewijzigd) == (2, 1, 1, 2)
    assert rapport.observaties == 14 and rapport.voorbeelden == ["4404: 10× 90 %"]
    assert _stand(administratie_id) == {
        "4404": (HOOG, 10, Decimal("0.9000"), True),
        "4403": (None, 4, Decimal("1.0000"), True),
    }

    # Idempotent: een tweede run wijzigt niets.
    assert motor.herbereken_voor(administratie_id, vandaag=VANDAAG).gewijzigd == 0

    # Verdeling verschuift naar 8/10 → default vervalt, verdeling blijft zichtbaar.
    with scoped_session(administratie_id) as session:
        for _ in range(2):
            session.add(_observatie(administratie_id, GB_4404, LAAG, recent))
    rapport = motor.herbereken_voor(administratie_id, vandaag=VANDAAG)
    assert (rapport.met_default, rapport.gewijzigd) == (0, 1)
    assert _stand(administratie_id)["4404"] == (None, 12, Decimal("0.7500"), True)


def test_rekening_zonder_regels_in_venster_gaat_terug_naar_null(administratie_id: uuid.UUID, stam: None) -> None:
    with scoped_session(administratie_id) as session:
        for _ in range(5):
            session.add(_observatie(administratie_id, GB_4404, HOOG, VANDAAG - timedelta(days=700)))
    assert motor.herbereken_voor(administratie_id, vandaag=VANDAAG).met_default == 1
    # 60 dagen later valt alles buiten het venster: geen stale default.
    later = VANDAAG + timedelta(days=60)
    rapport = motor.herbereken_voor(administratie_id, vandaag=later)
    assert (rapport.met_default, rapport.gewijzigd, rapport.observaties) == (0, 1, 0)
    assert _stand(administratie_id)["4404"][:3] == (None, None, None)


def test_herbereken_alle_loopt_alle_actieve_administraties_en_isoleert_fouten(
    administratie_id: uuid.UUID, stam: None, monkeypatch
) -> None:
    echte = motor.herbereken_voor

    def kapot_voor_anderen(aid: uuid.UUID, *, vandaag=None):  # noqa: ANN001
        if aid == administratie_id:
            return echte(aid, vandaag=vandaag)
        raise RuntimeError("kapot")

    monkeypatch.setattr(motor, "herbereken_voor", kapot_voor_anderen)
    uit = motor.herbereken_alle(vandaag=VANDAAG)
    assert isinstance(uit[administratie_id], motor.HistorieRapport)
    assert all(isinstance(v, motor.HistorieRapport) or v == "RuntimeError: kapot" for v in uit.values())


def test_bank_direct_boekingen_van_een_mens_tellen_mee_automatisch_en_gestorneerd_niet(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, stam: None
) -> None:
    """15-09 (casus L.H.G. Holding: KPN-incasso vanuit het bankscherm op 4404 geboekt, nul inkoopregels in het
    boekingsgeheugen): de regels van directe bankboekingen tellen mee in de verdeling per rekening — alleen GEBOEKTE,
    niet-automatische boekingen binnen het venster."""
    from datetime import UTC, datetime

    from app.bank.models import BankBoeking, BankBoekingBron, BankBoekingRegel, BankBoekingStatus
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    recent = datetime(2026, 8, 20, 12, 0, tzinfo=UTC)
    oud = datetime.combine(VANDAAG - timedelta(days=motor.HISTORIE_DAGEN + 1), datetime.min.time(), tzinfo=UTC)

    def boeking(bron: BankBoekingBron, status: BankBoekingStatus, geboekt_op: datetime, btw: uuid.UUID | None) -> None:
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            rij = BankBoeking(
                administratie_id=administratie_id,
                payment_transaction_id=uuid.uuid4(),
                rlz_document_id=uuid.uuid4(),
                bron=bron.value,
                status=status.value,
                geboekt_door=SYSTEEM_ACTOR_ID if bron is BankBoekingBron.AUTOMATISCH else beheerder_id,
                geboekt_op=geboekt_op,
                **(
                    {"gestorneerd_door": beheerder_id, "gestorneerd_op": geboekt_op, "storno_reden": "test"}
                    if status is BankBoekingStatus.GESTORNEERD
                    else {}
                ),
            )
            session.add(rij)
            session.flush()
            session.add(
                BankBoekingRegel(
                    bank_boeking_id=rij.id,
                    volgnummer=1,
                    ledger_id=GB_4404,
                    taxrate_id=btw,
                    netto_bedrag=Decimal("-69.41"),
                    btw_bedrag=Decimal("-14.58"),
                )
            )

    for _ in range(4):
        boeking(BankBoekingBron.HANDMATIG, BankBoekingStatus.GEBOEKT, recent, HOOG)
    boeking(BankBoekingBron.VASTE_REGEL, BankBoekingStatus.GEBOEKT, recent, HOOG)  # mens bevestigde de regel: telt
    boeking(BankBoekingBron.AUTOMATISCH, BankBoekingStatus.GEBOEKT, recent, LAAG)  # systeem: telt niet
    boeking(BankBoekingBron.HANDMATIG, BankBoekingStatus.GESTORNEERD, recent, LAAG)  # teruggedraaid: telt niet
    boeking(BankBoekingBron.HANDMATIG, BankBoekingStatus.GEBOEKT, oud, LAAG)  # buiten het venster: telt niet
    boeking(BankBoekingBron.HANDMATIG, BankBoekingStatus.GEBOEKT, recent, None)  # zonder tarief: telt niet
    with scoped_session(administratie_id) as session:
        session.add(
            _observatie(administratie_id, GB_4404, HOOG, VANDAAG - timedelta(days=10))
        )  # inkoopregel telt gewoon mee

    rapport = motor.herbereken_voor(administratie_id, vandaag=VANDAAG)
    assert rapport.observaties == 6 and rapport.voorbeelden == ["4404: 6× 100 %"]
    assert _stand(administratie_id)["4404"] == (HOOG, 6, Decimal("1.0000"), True)
