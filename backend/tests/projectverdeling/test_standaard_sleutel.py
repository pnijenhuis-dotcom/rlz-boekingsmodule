"""FV-12 (feedbackrun A 25-09): de knop "Verdelen over projecten" kiest STANDAARD de verdeelsleutel van de administratie —
nooit hardcoded per klant: (1) administratie-instelling (bestaat nog niet), (2) de meest gebruikte sleutel in de
geboekte verdelingen van de laatste 12 maanden, (3) default `omzet_maand`. Een Universal-achtige historie (pro rato
omzet per maand) geeft zo vanzelf de omzetsleutel (besluit Peter 21-09)."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.projectverdeling import service
from app.projectverdeling.service import SLEUTEL_OMZET_JAAR, SLEUTEL_OMZET_MAAND, SLEUTEL_VASTE_REGELS

VANDAAG = date(2026, 9, 25)


def _document(admin_engine: Engine, aid: uuid.UUID) -> uuid.UUID:
    did = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.document (id, administratie_id, bron, bestandsnaam, opslag_pad, sha256_hash, status, soort) "
                "VALUES (:id, :aid, 'upload', :naam, :pad, :sha, 'geboekt', 'inkoopfactuur')"
            ),
            {"id": did, "aid": aid, "naam": f"{did}.pdf", "pad": f"x/{did}", "sha": uuid.uuid4().hex * 2},
        )
    return did


def _geboekte_verdeling(
    admin_engine: Engine, aid: uuid.UUID, *, periode: date | None, soort: str = "maand", geboekt_op: datetime | None = None
) -> None:
    did = _document(admin_engine, aid)
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.projectverdeling (id, administratie_id, document_id, vaste_regels, pro_rato_periode, "
                "pro_rato_soort, status, geboekt_op) VALUES (:id, :aid, :did, '[]', :periode, :soort, 'geboekt', :op)"
            ),
            {
                "id": uuid.uuid4(),
                "aid": aid,
                "did": did,
                "periode": periode,
                "soort": soort,
                "op": geboekt_op or datetime(2026, 8, 1, tzinfo=UTC),
            },
        )


def _sleutel(aid: uuid.UUID) -> str:
    with scoped_session(aid) as session:
        return service.standaard_sleutel(session, administratie_id=aid, vandaag=VANDAAG)


def test_zonder_historie_is_de_default_omzet_maand(administratie_id) -> None:
    assert _sleutel(administratie_id) == SLEUTEL_OMZET_MAAND
    assert service.standaard_sleutel_voor(administratie_id=administratie_id, vandaag=VANDAAG) == SLEUTEL_OMZET_MAAND


def test_universal_achtige_historie_geeft_de_omzetsleutel(administratie_id, admin_engine) -> None:
    # Universal (besluit Peter 21-09): overhead pro rato over de omzet per maand — vijf geboekte verdelingen, één vast.
    for m in (3, 4, 5, 6, 7):
        _geboekte_verdeling(admin_engine, administratie_id, periode=date(2026, m, 1))
    _geboekte_verdeling(admin_engine, administratie_id, periode=None)
    assert _sleutel(administratie_id) == SLEUTEL_OMZET_MAAND


def test_meest_gebruikte_wint_en_oude_historie_telt_niet(administratie_id, admin_engine) -> None:
    for _ in range(2):
        _geboekte_verdeling(admin_engine, administratie_id, periode=None)
    _geboekte_verdeling(admin_engine, administratie_id, periode=date(2026, 1, 1), soort="jaar")
    assert _sleutel(administratie_id) == SLEUTEL_VASTE_REGELS
    # Ouder dan 12 maanden telt niet mee: drie oude jaar-verdelingen veranderen niets.
    oud = datetime(2025, 6, 1, tzinfo=UTC)
    for _ in range(3):
        _geboekte_verdeling(admin_engine, administratie_id, periode=date(2025, 1, 1), soort="jaar", geboekt_op=oud)
    assert _sleutel(administratie_id) == SLEUTEL_VASTE_REGELS


def test_gelijkspel_valt_op_omzet_maand_dan_jaar(administratie_id, admin_engine) -> None:
    _geboekte_verdeling(admin_engine, administratie_id, periode=date(2026, 1, 1), soort="jaar")
    _geboekte_verdeling(admin_engine, administratie_id, periode=None)
    assert _sleutel(administratie_id) == SLEUTEL_OMZET_JAAR
    _geboekte_verdeling(admin_engine, administratie_id, periode=date(2026, 7, 1), geboekt_op=datetime.now(UTC) - timedelta(days=1))
    assert _sleutel(administratie_id) == SLEUTEL_OMZET_MAAND
