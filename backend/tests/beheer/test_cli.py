from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.beheer import service


def _audit_acties(admin_engine: Engine, *, administratie_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'administratie' AND record_id = :id "
                    "ORDER BY tijdstip"
                ),
                {"id": administratie_id},
            )
            .scalars()
            .all()
        )


class TestBoekenAanUit:
    def test_boeken_aan_zet_de_toggle_en_print_bevestiging(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exitcode = cli.main(
            ["boeken-aan", "--administratie-id", str(administratie_id), "--beheerder-id", str(beheerder_id)]
        )
        uit = capsys.readouterr()

        assert exitcode == 0
        assert "boeken_ingeschakeld=True" in uit.out
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is True

    def test_boeken_uit_zet_de_toggle_terug(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.main(["boeken-aan", "--administratie-id", str(administratie_id), "--beheerder-id", str(beheerder_id)])
        capsys.readouterr()

        exitcode = cli.main(
            ["boeken-uit", "--administratie-id", str(administratie_id), "--beheerder-id", str(beheerder_id)]
        )
        uit = capsys.readouterr()

        assert exitcode == 0
        assert "boeken_ingeschakeld=False" in uit.out
        assert service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id) is False

    def test_elke_wijziging_wordt_geaudit(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        cli.main(["boeken-aan", "--administratie-id", str(administratie_id), "--beheerder-id", str(beheerder_id)])
        cli.main(["boeken-uit", "--administratie-id", str(administratie_id), "--beheerder-id", str(beheerder_id)])

        acties = _audit_acties(admin_engine, administratie_id=administratie_id)
        assert acties == ["boeken_ingeschakeld_gewijzigd", "boeken_ingeschakeld_gewijzigd"]

    def test_onbekende_administratie_geeft_foutmelding_en_exitcode_1(
        self, beheerder_id: uuid.UUID, capsys: pytest.CaptureFixture[str]
    ) -> None:
        exitcode = cli.main(
            ["boeken-aan", "--administratie-id", str(uuid.uuid4()), "--beheerder-id", str(beheerder_id)]
        )
        uit = capsys.readouterr()

        assert exitcode == 1
        assert "FOUT" in uit.err

    def test_waarschuwt_als_globale_kill_switch_uit_staat(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, capsys: pytest.CaptureFixture[str]
    ) -> None:
        service.zet_globale_kill_switch(actor_id=beheerder_id, ingeschakeld=False)
        capsys.readouterr()

        exitcode = cli.main(
            ["boeken-aan", "--administratie-id", str(administratie_id), "--beheerder-id", str(beheerder_id)]
        )
        uit = capsys.readouterr()

        assert exitcode == 0
        assert "kill switch staat uit" in uit.out


class TestBoekenStatus:
    def test_toont_globale_kill_switch_en_per_administratie_toggle(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, capsys: pytest.CaptureFixture[str]
    ) -> None:
        cli.main(["boeken-aan", "--administratie-id", str(administratie_id), "--beheerder-id", str(beheerder_id)])
        capsys.readouterr()

        exitcode = cli.main(["boeken-status"])
        uit = capsys.readouterr()

        assert exitcode == 0
        assert "Globale kill switch: AAN" in uit.out
        assert str(administratie_id) in uit.out
        assert "AAN" in uit.out

    def test_geen_administraties_geeft_duidelijke_melding(self, capsys: pytest.CaptureFixture[str]) -> None:
        exitcode = cli.main(["boeken-status"])
        uit = capsys.readouterr()

        assert exitcode == 0
        assert "geen administraties" in uit.out
