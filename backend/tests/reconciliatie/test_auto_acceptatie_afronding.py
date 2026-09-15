# ruff: noqa: F811 — pytest-fixtures als parameters
"""Reconciliatie-nazorg 15-09, punt 1 (besluit Peter 14-09 "systeem bepaalt of actie nodig is"): een bedragverschil
≤ € 0,05 tussen module en RLZ/Odoo op een geboekt document is een btw-cent-afronding → geen actie-bevinding maar een
automatische acceptatie door het systeem (audit `reconciliatie_auto_geaccepteerd`, reden "afronding ≤ 0,05") mét
dagteller `auto_geaccepteerd` op het documenten-blok. Groter blijft een afwijking (Booking Experts Δ 0,97). Lees-only en
losse CLI schrijven niets (markering in de regel); een door een Beheerder ingetrokken acceptatie wint blijvend."""

from __future__ import annotations

import argparse
import uuid
from decimal import Decimal

import pytest
from sqlalchemy import select

from app import cli
from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import reconciliatie
from app.documenten.reconciliatie import ReconciliatieAfwijking, ReconciliatieRapport
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.models import ReconciliatieAcceptatie, ReconciliatieBron
from app.reconciliatie.run import Verzamelaar
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401

ARGS = argparse.Namespace()


def _afw(
    lokaal: str, extern: str, *, soort: str = "bedrag_wijkt_af", doc: uuid.UUID | None = None
) -> ReconciliatieAfwijking:
    doc = doc or uuid.uuid4()
    return ReconciliatieAfwijking(
        document_id=doc,
        rlz_document_id=uuid.uuid4(),
        soort=soort,
        detail=f"eigen=€{lokaal} rlz=€{extern}",
        context={"bedrag_lokaal": lokaal, "bedrag_extern": extern, "leverancier_naam": "Lusso", "factuurnummer": "L-1"},
    )


class TestAfrondingsverschilPuur:
    @pytest.mark.parametrize(
        ("lokaal", "extern", "verwacht"),
        [
            ("5255.61", "5255.64", "0.03"),  # Kempen Facilities 15-09 (Lusso)
            ("7834.73", "7834.7", "0.03"),
            ("5737.25", "5737.28", "0.03"),
            ("100.00", "100.05", "0.05"),  # grens inclusief
            ("100.05", "100.00", "0.05"),  # richting maakt niet uit
        ],
    )
    def test_binnen_de_grens(self, lokaal: str, extern: str, verwacht: str) -> None:
        assert reconciliatie.afrondingsverschil(_afw(lokaal, extern)) == Decimal(verwacht)

    @pytest.mark.parametrize(
        ("lokaal", "extern"),
        [
            ("20959.79", "20960.76"),  # Booking Experts 20260205347 Δ 0,97 = echte wijziging
            ("667.24", "666.99"),  # Δ 0,25
            ("274.89", "279.51"),  # Δ 4,62
            ("100.00", "100.06"),  # net buiten de grens
        ],
    )
    def test_buiten_de_grens_blijft_afwijking(self, lokaal: str, extern: str) -> None:
        assert reconciliatie.afrondingsverschil(_afw(lokaal, extern)) is None

    def test_andere_soort_of_onleesbaar_bedrag_is_nooit_afronding(self) -> None:
        assert reconciliatie.afrondingsverschil(_afw("1.00", "1.01", soort="boekstuknummer_wijkt_af")) is None
        kaal = ReconciliatieAfwijking(uuid.uuid4(), uuid.uuid4(), "bedrag_wijkt_af", "eigen=€1 rlz=€1.01")
        assert reconciliatie.afrondingsverschil(kaal) is None  # geen context-bedragen → fail-closed
        raar = _afw("abc", "1.00")
        assert reconciliatie.afrondingsverschil(raar) is None
        assert Decimal("0.05") == reconciliatie.AFRONDING_TOLERANTIE and "0,05" in reconciliatie.AFRONDING_REDEN


def _run(monkeypatch, administratie_id: uuid.UUID, afwijkingen, *, met_verzamelaar: bool = True):  # noqa: ANN001
    rapport = ReconciliatieRapport(
        administratie_id=administratie_id, aantal_gecontroleerd=9, afwijkingen=tuple(afwijkingen)
    )
    monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {administratie_id: rapport})
    monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})
    verzamelaar = Verzamelaar() if met_verzamelaar else None
    if verzamelaar is not None:
        verzamelaar.start_blok("documenten")
    code = cli._reconciliatie(ARGS, verzamelaar=verzamelaar)
    return code, verzamelaar


def _acceptaties(administratie_id: uuid.UUID) -> list[ReconciliatieAcceptatie]:
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(ReconciliatieAcceptatie).where(ReconciliatieAcceptatie.administratie_id == administratie_id)
        ).all()
        for r in rijen:
            session.expunge(r)
        return rijen


class TestAutoAcceptatieInDeRun:
    def test_afronding_wordt_geaccepteerd_groter_blijft_afwijking(self, administratie_id, monkeypatch, capsys) -> None:
        klein = _afw("5255.61", "5255.64")
        groot = _afw("20959.79", "20960.76")
        code, v = _run(monkeypatch, administratie_id, [klein, groot])
        assert code == 1  # de echte afwijking houdt de exit-code op 1
        stand = v.blokken["documenten"]
        assert (stand.afwijkingen, stand.geaccepteerd, stand.auto_geaccepteerd) == (1, 1, 1)
        soorten = {b.detail["record_id"]: b.soort for b in v.bevindingen}
        assert soorten[str(klein.document_id)] == "geaccepteerd" and soorten[str(groot.document_id)] == "afwijking"
        uit = capsys.readouterr().out
        assert "automatisch geaccepteerd (afronding ≤ 0,05, verschil € 0.03)" in uit
        assert "GEACCEPTEERD document=" in uit and "reden: automatisch (afronding ≤ 0,05)" in uit
        (acc,) = _acceptaties(administratie_id)
        assert acc.geaccepteerd_door == SYSTEEM_ACTOR_ID and acc.soort == "bedrag_wijkt_af"
        assert acc.reden == "automatisch (afronding ≤ 0,05)" and acc.record_id == klein.document_id
        assert acc.vingerafdruk == acceptatie_service.vingerafdruk(
            bron="documenten", soort=klein.soort, detail=klein.detail
        )
        # audit_event mét administratie_id is RLS-gescoped: lezen binnen de scope van de administratie.
        with scoped_session(administratie_id) as session:
            audit = session.scalars(
                select(AuditEvent).where(AuditEvent.actie == "reconciliatie_auto_geaccepteerd")
            ).all()
        assert len(audit) == 1 and audit[0].actor_id == SYSTEEM_ACTOR_ID
        nw = audit[0].nieuwe_waarde
        assert (
            nw["reden"] == "afronding ≤ 0,05" and nw["verschil"] == "0.03" and nw["record_id"] == str(klein.document_id)
        )
        assert audit[0].administratie_id == administratie_id

    def test_tweede_run_is_idempotent_en_telt_niet_opnieuw(self, administratie_id, monkeypatch) -> None:
        klein = _afw("100.00", "100.02")
        _run(monkeypatch, administratie_id, [klein])
        code, v = _run(monkeypatch, administratie_id, [klein])
        assert code == 0
        stand = v.blokken["documenten"]
        assert (stand.afwijkingen, stand.geaccepteerd, stand.auto_geaccepteerd) == (0, 1, 0)
        assert len(_acceptaties(administratie_id)) == 1

    def test_ander_bedrag_is_een_nieuwe_vingerafdruk_en_wordt_opnieuw_beoordeeld(
        self, administratie_id, monkeypatch
    ) -> None:
        doc = uuid.uuid4()
        _run(monkeypatch, administratie_id, [_afw("100.00", "100.02", doc=doc)])
        code, v = _run(monkeypatch, administratie_id, [_afw("100.00", "100.90", doc=doc)])
        assert code == 1 and v.blokken["documenten"].afwijkingen == 1 and v.blokken["documenten"].auto_geaccepteerd == 0

    def test_ingetrokken_door_beheerder_wint_blijvend(self, administratie_id, beheerder_id, monkeypatch) -> None:
        klein = _afw("100.00", "100.03")
        _run(monkeypatch, administratie_id, [klein])
        (acc,) = _acceptaties(administratie_id)
        acceptatie_service.trek_in(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            vingerafdruk_waarde=acc.vingerafdruk,
            reden="toch bekijken, bewust",
            beheerder_id=beheerder_id,
        )
        code, v = _run(monkeypatch, administratie_id, [klein])
        assert code == 1 and v.blokken["documenten"].afwijkingen == 1 and v.blokken["documenten"].auto_geaccepteerd == 0
        assert len(_acceptaties(administratie_id)) == 1  # geen tweede rij

    def test_mens_acceptatie_blijft_mens_acceptatie(self, administratie_id, beheerder_id, monkeypatch) -> None:
        klein = _afw("100.00", "100.03")
        acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=ReconciliatieBron.DOCUMENTEN,
            record_id=klein.document_id,
            soort=klein.soort,
            detail=klein.detail,
            reden="bekend, beoordeeld door mens",
            beheerder_id=beheerder_id,
        )
        code, v = _run(monkeypatch, administratie_id, [klein])
        assert code == 0 and v.blokken["documenten"].auto_geaccepteerd == 0
        (acc,) = _acceptaties(administratie_id)
        assert acc.geaccepteerd_door == beheerder_id

    def test_lees_only_en_losse_cli_schrijven_niets_maar_markeren(self, administratie_id, monkeypatch, capsys) -> None:
        klein = _afw("100.00", "100.03")
        code, v = _run(monkeypatch, administratie_id, [klein], met_verzamelaar=False)
        assert code == 1 and v is None
        assert _acceptaties(administratie_id) == []
        assert "afronding ≤ 0,05: wordt in de dagelijkse run automatisch geaccepteerd" in capsys.readouterr().out

    def test_systeemrapport_draagt_de_dagteller(self, administratie_id, monkeypatch) -> None:
        from datetime import UTC, datetime

        from app.reconciliatie.run import Delta, bouw_mail

        _, v = _run(monkeypatch, administratie_id, [_afw("100.00", "100.03")])
        v.sluit_blok("documenten", 0)
        _, tekst = bouw_mail(
            run_id=uuid.uuid4(),
            bron="cli",
            afgerond_op=datetime.now(UTC),
            exit_code=0,
            samenvatting=v.samenvatting(),
            delta=Delta(),
            open_afwijkingen=0,
            namen={},
        )
        assert "1 geaccepteerd" in tekst and "1 automatisch geaccepteerd (afronding ≤ 0,05)" in tekst
