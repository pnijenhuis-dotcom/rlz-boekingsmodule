from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.beheer import service


def _audit_acties(admin_engine: Engine, *, tabel: str, record_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = :tabel AND record_id = :id ORDER BY tijdstip"
                ),
                {"tabel": tabel, "id": record_id},
            )
            .scalars()
            .all()
        )


class TestPerAdministratieToggle:
    def test_default_uit(self, administratie_id: uuid.UUID) -> None:
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is False

    def test_aanzetten_en_uitzetten(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is True

        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=False)
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is False

    def test_elke_wijziging_wordt_geaudit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        acties = _audit_acties(admin_engine, tabel="administratie", record_id=administratie_id)
        assert acties == ["boeken_ingeschakeld_gewijzigd", "boeken_ingeschakeld_gewijzigd"]

    def test_onbekende_administratie_geeft_beheerfout(self, beheerder_id: uuid.UUID) -> None:
        with pytest.raises(service.BeheerFout):
            service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=uuid.uuid4(), ingeschakeld=True)


class TestGlobaleKillSwitch:
    def test_default_aan(self) -> None:
        assert service.haal_globale_kill_switch_op() is True

    def test_uitzetten_en_aanzetten(self, beheerder_id: uuid.UUID) -> None:
        service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=False)
        assert service.haal_globale_kill_switch_op() is False

        service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=True)
        assert service.haal_globale_kill_switch_op() is True
