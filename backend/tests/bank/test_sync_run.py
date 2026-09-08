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


# --- BLOK 1 (bundel 08-09): nachtelijke lus over álle actieve administraties -------------------------------


def _geen_credential(administratie_id: uuid.UUID) -> None:
    from app.rlz.credentials import GeenRlzCredentials

    raise GeenRlzCredentials("Geen credential-prefix geregistreerd voor RLZ-adminId 'rlz-test'")


def test_nachtelijke_run_zonder_credential_is_zichtbaar_overgeslagen_zonder_rij(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_run, "resolve_credentials", lambda rlz_admin_id: _geen_credential(administratie_id))
    uit = sync_run.start_nachtelijke_run(administratie_id)
    assert isinstance(uit, sync_run.BankSyncOvergeslagen) and uit.reden == "geen_credential"
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM boekhouding.bank_sync_run WHERE administratie_id = :a"), {"a": administratie_id}
        ).scalar()
    assert n == 0  # geen run-rij: het bankscherm toont hierdoor géén fout


def test_nachtelijke_run_odoo_administratie_overgeslagen(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.odoo.ids import odoo_admin_sentinel

    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE platform.administratie SET rlz_admin_id = :s, boekhoud_backend = 'odoo' WHERE id = :a"),
            {"s": odoo_admin_sentinel("https://test.odoo.com", 1), "a": administratie_id},
        )
    uit = sync_run.start_nachtelijke_run(administratie_id)
    assert isinstance(uit, sync_run.BankSyncOvergeslagen) and uit.reden == "odoo_administratie"


def test_nachtelijke_run_schrijft_run_rij_met_bron_sync_alles(
    administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_run, "resolve_credentials", lambda rlz_admin_id: ("u", "p"))
    monkeypatch.setattr(sync_run.sync, "sync_bank_voor_administratie", lambda *, administratie_id, client=None: _resultaat())
    info = sync_run.start_nachtelijke_run(administratie_id)
    assert isinstance(info, sync_run.BankSyncRunInfo)
    assert info.status == "klaar" and info.resultaat["mutaties_nieuw"] == 3 and info.resultaat["bron"] == "sync_alles"
    with admin_engine.connect() as conn:
        rij = conn.execute(
            text("SELECT status, aangevraagd_door FROM boekhouding.bank_sync_run WHERE administratie_id = :a"),
            {"a": administratie_id},
        ).one()
    assert rij.status == "klaar" and rij.aangevraagd_door is None


def test_nachtelijke_run_fout_landt_zichtbaar_op_de_rij(
    administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_run, "resolve_credentials", lambda rlz_admin_id: ("u", "p"))

    def kapot(*, administratie_id, client=None):
        raise RuntimeError("RLZ 503")

    monkeypatch.setattr(sync_run.sync, "sync_bank_voor_administratie", kapot)
    info = sync_run.start_nachtelijke_run(administratie_id)
    assert isinstance(info, sync_run.BankSyncRunInfo) and info.status == "fout" and "RLZ 503" in (info.fout_reden or "")


def test_nachtelijke_run_hergebruikt_een_lopende_on_demand_run(
    administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(sync_run, "resolve_credentials", lambda rlz_admin_id: ("u", "p"))
    monkeypatch.setattr(sync_run, "_start_voertuig", lambda administratie_id: None)  # run blijft 'wachtrij' staan
    aangeroepen: list[uuid.UUID] = []

    def tel(*, administratie_id, client=None):
        aangeroepen.append(administratie_id)
        return _resultaat()

    monkeypatch.setattr(sync_run.sync, "sync_bank_voor_administratie", tel)
    open_run = sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=beheerder_id)
    assert open_run.status == "wachtrij"
    # Wachtrij-rij van de gebruiker: de nachtelijke lus voegt géén tweede rij toe maar verwerkt die ene.
    info = sync_run.start_nachtelijke_run(administratie_id)
    assert isinstance(info, sync_run.BankSyncRunInfo) and info.run_id == open_run.run_id and info.status == "klaar"
    assert len(aangeroepen) == 1
    with admin_engine.connect() as conn:
        n = conn.execute(
            text("SELECT count(*) FROM boekhouding.bank_sync_run WHERE administratie_id = :a"), {"a": administratie_id}
        ).scalar()
    assert n == 1
    # Een run die écht BEZIG is (ander voertuig) wordt teruggegeven zonder dubbel te draaien.
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.bank_sync_run (id, administratie_id, status, gestart_op, laatst_actief_op) "
                "VALUES (:id, :a, 'bezig', now(), now())"
            ),
            {"id": uuid.uuid4(), "a": administratie_id},
        )
    bezig = sync_run.start_nachtelijke_run(administratie_id)
    assert isinstance(bezig, sync_run.BankSyncRunInfo) and bezig.status == "bezig" and len(aangeroepen) == 1


def test_sync_alle_via_runs_een_kapotte_stopt_de_rest_niet(
    administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch
) -> None:
    def per_administratie(aid):
        if aid == administratie_id:
            raise RuntimeError("boem")
        return sync_run.BankSyncOvergeslagen("geen_credential", "x")

    monkeypatch.setattr(sync_run, "start_nachtelijke_run", per_administratie)
    uit = sync_run.sync_alle_via_runs()
    assert uit[administratie_id] == "RuntimeError: boem"
    assert all(isinstance(v, sync_run.BankSyncOvergeslagen) for k, v in uit.items() if k != administratie_id)
