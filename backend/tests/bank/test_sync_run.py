"""Deel 4 punt 2 — bank auto-verversing bij openen: drempel, run-levenscyclus, fout zichtbaar."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import Engine, text

from app.bank import sync_run


def _telling(a: int = 0, b: int = 0) -> SimpleNamespace:
    return SimpleNamespace(aangemaakt=a, bijgewerkt=b, open_ververst=0)


def _resultaat() -> SimpleNamespace:
    return SimpleNamespace(rekeningen=_telling(), mutaties=_telling(3, 1), open_posten=_telling(),
                           afletteren_geverifieerd=0, automatisch_afgeletterd=0, afletter_fouten=[],
                           automatisch_geboekt=0, automatisch_fouten=[])


@pytest.fixture
def synchroon_voertuig(monkeypatch: pytest.MonkeyPatch) -> None:
    """Thread → direct in-proces verwerken (deterministische test), zonder RLZ."""
    monkeypatch.setattr(sync_run, "_start_voertuig", lambda administratie_id: sync_run.verwerk_wachtrij_voor(administratie_id))


def test_eerste_opening_start_run_en_werkt_klaar(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, synchroon_voertuig: None
) -> None:
    monkeypatch.setattr(sync_run.sync, "sync_bank_voor_administratie", lambda *, administratie_id, client=None: _resultaat())
    info = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    assert info.overgeslagen is False and info.run_id is not None
    status = sync_run.laatste_run(administratie_id)
    assert status.status == "klaar" and status.resultaat["mutaties_nieuw"] == 3


def test_drempel_slaat_verse_sync_over(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch, synchroon_voertuig: None
) -> None:
    aangeroepen: list[uuid.UUID] = []

    def fake_sync(*, administratie_id, client=None):
        aangeroepen.append(administratie_id)
        return _resultaat()

    monkeypatch.setattr(sync_run.sync, "sync_bank_voor_administratie", fake_sync)
    nu = datetime.now(UTC)
    with admin_engine.begin() as conn:
        conn.execute(text("INSERT INTO boekhouding.bank_sync_stand (administratie_id, laatste_sync_op) VALUES (:aid, :t)"),
                     {"aid": administratie_id, "t": nu - timedelta(minutes=2)})
    info = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    assert info.overgeslagen is True and info.status == "overgeslagen" and info.run_id is None
    assert info.laatste_sync_op is not None and aangeroepen == []
    # Ouder dan de drempel → wél een ronde.
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE boekhouding.bank_sync_stand SET laatste_sync_op = :t WHERE administratie_id = :aid"),
                     {"aid": administratie_id, "t": nu - timedelta(minutes=6)})
    info = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    assert info.overgeslagen is False and aangeroepen == [administratie_id]


def test_fout_landt_zichtbaar_op_de_run(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, synchroon_voertuig: None
) -> None:
    def kapot(*, administratie_id, client=None):
        raise RuntimeError("RLZ 502")

    monkeypatch.setattr(sync_run.sync, "sync_bank_voor_administratie", kapot)
    sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    status = sync_run.laatste_run(administratie_id)
    assert status.status == "fout" and "RLZ 502" in (status.fout_reden or "")


def test_actieve_run_wordt_hergebruikt_en_stale_wordt_fout(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_run, "_start_voertuig", lambda administratie_id: None)  # voertuig "hangt"
    eerste = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    tweede = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    assert eerste.run_id == tweede.run_id and tweede.status == "wachtrij"
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE boekhouding.bank_sync_run SET aangevraagd_op = now() - interval '20 minutes' WHERE id = :id"),
                     {"id": eerste.run_id})
    status = sync_run.laatste_run(administratie_id)
    assert status.status == "fout" and status.fout_reden == sync_run.AFGEBROKEN_REDEN


def test_forceer_slaat_alleen_de_drempel_over(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, synchroon_voertuig: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Blok E2 (01/02-09): het ⟳-icoon start via hetzelfde endpoint mét `forceer` — de 5-min-drempel
    wordt overgeslagen, een al lopende run wordt nog steeds hergebruikt."""
    from app.bank import sync as bank_sync

    aanroepen: list[uuid.UUID] = []

    def fake_sync(*, administratie_id, client=None):
        aanroepen.append(administratie_id)
        return _resultaat()

    monkeypatch.setattr(bank_sync, "sync_bank_voor_administratie", fake_sync)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.bank_sync_stand (administratie_id, laatste_sync_op) VALUES (:a, :t) "
                "ON CONFLICT (administratie_id) DO UPDATE SET laatste_sync_op = :t"
            ),
            {"a": administratie_id, "t": datetime.now(UTC) - timedelta(minutes=1)},
        )
    gewoon = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    assert gewoon.status == "overgeslagen" and aanroepen == []
    geforceerd = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id, forceer=True)
    assert geforceerd.overgeslagen is False and geforceerd.run_id is not None and len(aanroepen) == 1
    status = sync_run.laatste_run(administratie_id)
    assert status.status == "klaar" and status.resultaat is not None
    # Blok E3: de verificatie-telling reist mee in de run-samenvatting (0 zonder wachtende opdrachten).
    assert status.resultaat.get("afletteren_wachtend") == 0
