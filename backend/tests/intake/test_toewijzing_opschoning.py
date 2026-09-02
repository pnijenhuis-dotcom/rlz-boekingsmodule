"""Blok D 02-09 — data-nazorg afzender-geheugen: regels van config-uitgesloten kantoor-/doorstuurdomeinen
en sleutels die de flip-drempel al overschreden (admin@kempenrecreatie.nl: 12 versies / 6 doelen) worden
gedeactiveerd mét audit — nooit verwijderd; tenaamstelling-regels en gewone leveranciers blijven staan;
idempotent; dry-run wijzigt niets."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine, select, text

from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.intake.models import ToewijzingRegel, ToewijzingRegelSoort
from app.intake.toewijzing import AFZENDER_MEERDUIDIG_VANAF, schoon_afzender_regels_op


def _extra_administraties(admin_engine: Engine, aantal: int) -> list[uuid.UUID]:
    ids = [uuid.uuid4() for _ in range(aantal)]
    with admin_engine.begin() as conn:
        for i, aid in enumerate(ids):
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
                {"id": aid, "naam": f"Flipdoel {i} B.V.", "rlz": f"FLIP-{aid.hex[:8]}"},
            )
    return ids


def _regel(
    session,
    *,
    soort: ToewijzingRegelSoort,
    sleutel: str,
    administratie_id: uuid.UUID,
    actor: uuid.UUID,
    actief: bool = True,
):
    regel = ToewijzingRegel(
        soort=soort.value,
        sleutel=sleutel,
        administratie_id=administratie_id,
        aangemaakt_door=actor,
        actief=actief,
    )
    session.add(regel)
    session.flush()
    return regel.id


def _actief(session, sleutel: str) -> list[ToewijzingRegel]:
    return session.scalars(
        select(ToewijzingRegel).where(ToewijzingRegel.sleutel == sleutel, ToewijzingRegel.actief.is_(True))
    ).all()


def test_opschoning_deactiveert_uitgesloten_en_meerduidige_afzenders_met_audit(
    administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine
) -> None:
    doelen = [administratie_id, *_extra_administraties(admin_engine, AFZENDER_MEERDUIDIG_VANAF - 1)]
    with scoped_session(None, actor_id=gescoopte_gebruiker) as session:
        # (a) kantoor-/doorstuurdomein (config-default: ak-nijenhuis.nl, kempengroep.nl) — actief.
        _regel(
            session,
            soort=ToewijzingRegelSoort.AFZENDER,
            sleutel="peter@ak-nijenhuis.nl",
            administratie_id=administratie_id,
            actor=gescoopte_gebruiker,
        )
        _regel(
            session,
            soort=ToewijzingRegelSoort.AFZENDER,
            sleutel="facturen@kempengroep.nl",
            administratie_id=administratie_id,
            actor=gescoopte_gebruiker,
        )
        # (b) flip-historie: ≥ 3 doelen (twee gedeactiveerde versies + één actieve).
        for doel in doelen[:-1]:
            _regel(
                session,
                soort=ToewijzingRegelSoort.AFZENDER,
                sleutel="admin@kempenrecreatie.nl",
                administratie_id=doel,
                actor=gescoopte_gebruiker,
                actief=False,
            )
        _regel(
            session,
            soort=ToewijzingRegelSoort.AFZENDER,
            sleutel="admin@kempenrecreatie.nl",
            administratie_id=doelen[-1],
            actor=gescoopte_gebruiker,
        )
        # (c) gewone leverancier met één doel — blijft; (d) tenaamstelling-regel — nooit geraakt.
        _regel(
            session,
            soort=ToewijzingRegelSoort.AFZENDER,
            sleutel="info@bouwadviesoost.nl",
            administratie_id=administratie_id,
            actor=gescoopte_gebruiker,
        )
        _regel(
            session,
            soort=ToewijzingRegelSoort.TENAAMSTELLING,
            sleutel="kempen facilities",
            administratie_id=doelen[-1],
            actor=gescoopte_gebruiker,
        )

    # Dry-run: rapporteert, wijzigt niets.
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        droog = schoon_afzender_regels_op(session, actor_id=SYSTEEM_ACTOR_ID, dry_run=True)
    assert droog.gedeactiveerd == 3 and droog.reden_uitgesloten_domein == 2 and droog.reden_meerduidig == 1
    with scoped_session(None) as session:
        assert len(_actief(session, "peter@ak-nijenhuis.nl")) == 1

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        telling = schoon_afzender_regels_op(session, actor_id=SYSTEEM_ACTOR_ID)
    assert telling.gedeactiveerd == 3
    assert any("admin@kempenrecreatie.nl: 1 actieve regel(s) gedeactiveerd — meerduidig" in d for d in telling.details)
    with scoped_session(None) as session:
        assert _actief(session, "peter@ak-nijenhuis.nl") == []
        assert _actief(session, "facturen@kempengroep.nl") == []
        assert _actief(session, "admin@kempenrecreatie.nl") == []
        assert len(_actief(session, "info@bouwadviesoost.nl")) == 1
        assert len(_actief(session, "kempen facilities")) == 1
        # Niets verwijderd: alle rijen bestaan nog (historie blijft de meerduidigheid dragen).
        assert (
            session.scalar(
                select(ToewijzingRegel.id).where(ToewijzingRegel.sleutel == "admin@kempenrecreatie.nl").limit(1)
            )
            is not None
        )
        assert (
            len(
                session.scalars(
                    select(ToewijzingRegel).where(ToewijzingRegel.sleutel == "admin@kempenrecreatie.nl")
                ).all()
            )
            == AFZENDER_MEERDUIDIG_VANAF
        )
    with admin_engine.connect() as conn:
        audits = conn.execute(
            text(
                "SELECT nieuwe_waarde->>'sleutel', nieuwe_waarde->'redenen' FROM platform.audit_event "
                "WHERE actie = 'toewijzing_regel_opgeschoond' ORDER BY nieuwe_waarde->>'sleutel'"
            )
        ).all()
    assert [a[0] for a in audits] == ["admin@kempenrecreatie.nl", "facturen@kempengroep.nl", "peter@ak-nijenhuis.nl"]
    assert audits[0][1] == ["meerduidig"] and audits[2][1] == ["uitgesloten_domein"]

    # Idempotent: tweede run vindt niets.
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        tweede = schoon_afzender_regels_op(session, actor_id=SYSTEEM_ACTOR_ID)
    assert tweede.gedeactiveerd == 0


def test_cli_rapporteert(monkeypatch, capsys) -> None:
    from app import cli
    from app.intake import toewijzing

    def nep(session, *, actor_id, dry_run=False):
        return toewijzing.OpschoningTelling(
            sleutels_bekeken=10,
            gedeactiveerd=6,
            reden_uitgesloten_domein=4,
            reden_meerduidig=3,
            details=["x: 1 actieve regel(s) gedeactiveerd — meerduidig (12 versies, 6 doelen)"],
        )

    monkeypatch.setattr(toewijzing, "schoon_afzender_regels_op", nep)
    assert cli.main(["toewijzing-regels-opschonen", "--dry-run"]) == 0
    uit = capsys.readouterr().out
    assert (
        "[dry-run]: 10 afzender-sleutels bekeken, 6 regel(s) gedeactiveerd (4 uitgesloten domein, 3 meerduidig)" in uit
    )
    assert "12 versies, 6 doelen" in uit
