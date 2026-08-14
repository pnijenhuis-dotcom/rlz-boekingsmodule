"""Rapportage-teller op de UITGESLOTEN-tak (F3.3, GCP-uitrol — BESLISSINGEN
"Rapportage-bug reconciliatie", geconstateerd 2026-08-14).

Acceptaties op een uitgesloten administratie verdwenen uit élke telling: de per-
administratieregel meldde "0 bevinding(en)" met GEACCEPTEERD-regels eronder en de
slotregel loog "0 geaccepteerd". In de cloud is de slotregel (naast de exit-code) het
enige dat een mens ziet — een vangrail die zichzelf verkeerd samenvat is daar
onbruikbaar. De fix: geaccepteerd-telling loopt op de uitgesloten-tak mee in een aparte
teller die de slotregel apart benoemt; de exit-code blijft ongewijzigd (uitgesloten
telt niet mee — besluit 0043 in de mildere vorm "zichtbaar blijven, niet meetellen").
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest

from app import cli
from app.bank.reconciliatie import BankAfwijking, BankReconciliatieRapport
from app.documenten.reconciliatie import ReconciliatieAfwijking, ReconciliatieRapport
from app.reconciliatie.service import AcceptatieInfo, Beoordeeld


def _acceptatie() -> AcceptatieInfo:
    return AcceptatieInfo(
        id=uuid.uuid4(),
        reden="bekend verschil, beoordeeld",
        geaccepteerd_door=uuid.uuid4(),
        geaccepteerd_op=datetime(2026, 8, 1, 9, 0, tzinfo=UTC),
    )


def _beoordeeld(record_id: uuid.UUID, *, geaccepteerd: bool) -> Beoordeeld:
    return Beoordeeld(
        record_id=record_id,
        soort="bedrag_wijkt_af",
        detail="lokaal 100.00, RLZ 90.00",
        vingerafdruk="vaf",
        acceptatie=_acceptatie() if geaccepteerd else None,
    )


class TestDocumentenUitgeslotenTak:
    def test_geaccepteerd_op_uitgesloten_administratie_blijft_zichtbaar_in_regel_en_slotregel(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        uitgesloten_id = uuid.uuid4()
        afwijkingen = tuple(
            ReconciliatieAfwijking(
                document_id=uuid.uuid4(), rlz_document_id=uuid.uuid4(), soort="bedrag_wijkt_af", detail="d"
            )
            for _ in range(3)
        )
        rapport = ReconciliatieRapport(
            administratie_id=uitgesloten_id, aantal_gecontroleerd=3, afwijkingen=afwijkingen
        )
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {uitgesloten_id: rapport})
        monkeypatch.setattr(
            cli.acceptatie_service, "uitgesloten_administraties", lambda: {uitgesloten_id: "testadministratie"}
        )
        monkeypatch.setattr(
            cli.acceptatie_service,
            "beoordeel",
            lambda **kwargs: [_beoordeeld(a[0], geaccepteerd=True) for a in kwargs["afwijkingen"]],
        )
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})

        exit_code = cli.main(["reconciliatie"])

        uitvoer = capsys.readouterr().out
        assert exit_code == 0  # uitgesloten blijft buiten de exit-code (besluit 0043)
        assert (
            f"UITGESLOTEN {uitgesloten_id}: 3 gecontroleerd, 0 open, 3 geaccepteerd — telt niet mee (testadministratie)"
            in uitvoer
        )
        assert (
            "0 afwijking(en) totaal (0 geaccepteerd; daarnaast 3 geaccepteerd op uitgesloten "
            "administraties — telt niet mee)." in uitvoer
        )

    def test_open_bevinding_op_uitgesloten_administratie_telt_als_open_in_de_regel(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        uitgesloten_id = uuid.uuid4()
        afwijking = ReconciliatieAfwijking(
            document_id=uuid.uuid4(), rlz_document_id=uuid.uuid4(), soort="bedrag_wijkt_af", detail="d"
        )
        rapport = ReconciliatieRapport(
            administratie_id=uitgesloten_id, aantal_gecontroleerd=1, afwijkingen=(afwijking,)
        )
        monkeypatch.setattr(cli.reconciliatie, "reconcilieer_alle_administraties", lambda: {uitgesloten_id: rapport})
        monkeypatch.setattr(
            cli.acceptatie_service, "uitgesloten_administraties", lambda: {uitgesloten_id: "testadministratie"}
        )
        monkeypatch.setattr(
            cli.acceptatie_service,
            "beoordeel",
            lambda **kwargs: [_beoordeeld(a[0], geaccepteerd=False) for a in kwargs["afwijkingen"]],
        )
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})

        exit_code = cli.main(["reconciliatie"])

        uitvoer = capsys.readouterr().out
        assert exit_code == 0
        assert "1 open, 0 geaccepteerd — telt niet mee" in uitvoer
        # Geen geaccepteerde uitgesloten regels → slotregel zonder naschrift (geen ruis).
        assert "0 afwijking(en) totaal (0 geaccepteerd)." in uitvoer

    def test_meetellende_administratie_blijft_ongewijzigd_naast_een_uitgesloten(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        meetellend_id, uitgesloten_id = uuid.uuid4(), uuid.uuid4()
        maak_afwijking = lambda: ReconciliatieAfwijking(  # noqa: E731
            document_id=uuid.uuid4(), rlz_document_id=uuid.uuid4(), soort="bedrag_wijkt_af", detail="d"
        )
        monkeypatch.setattr(
            cli.reconciliatie,
            "reconcilieer_alle_administraties",
            lambda: {
                meetellend_id: ReconciliatieRapport(
                    administratie_id=meetellend_id, aantal_gecontroleerd=2, afwijkingen=(maak_afwijking(),)
                ),
                uitgesloten_id: ReconciliatieRapport(
                    administratie_id=uitgesloten_id, aantal_gecontroleerd=1, afwijkingen=(maak_afwijking(),)
                ),
            },
        )
        monkeypatch.setattr(
            cli.acceptatie_service, "uitgesloten_administraties", lambda: {uitgesloten_id: "testadministratie"}
        )
        monkeypatch.setattr(
            cli.acceptatie_service,
            "beoordeel",
            lambda **kwargs: [_beoordeeld(a[0], geaccepteerd=True) for a in kwargs["afwijkingen"]],
        )
        monkeypatch.setattr(cli.storno_detectie, "detecteer_en_meld_gestorneerd_alle", lambda: {})

        exit_code = cli.main(["reconciliatie"])

        uitvoer = capsys.readouterr().out
        assert exit_code == 0
        assert f"OK         {meetellend_id}: 2 gecontroleerd, 0 afwijking(en), 1 geaccepteerd" in uitvoer
        assert (
            "0 afwijking(en) totaal (1 geaccepteerd; daarnaast 1 geaccepteerd op uitgesloten "
            "administraties — telt niet mee)." in uitvoer
        )


class TestBankUitgeslotenTak:
    def test_geaccepteerd_op_uitgesloten_administratie_blijft_zichtbaar_in_regel_en_slotregel(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        uitgesloten_id = uuid.uuid4()
        afwijkingen = tuple(
            BankAfwijking(
                record_id=uuid.uuid4(), payment_transaction_id=uuid.uuid4(), soort="boeking_verdwenen", detail="d"
            )
            for _ in range(2)
        )
        rapport = BankReconciliatieRapport(
            administratie_id=uitgesloten_id,
            boekingen_gecontroleerd=2,
            afletteringen_gecontroleerd=1,
            afwijkingen=afwijkingen,
        )
        monkeypatch.setattr(
            cli.bank_reconciliatie, "reconcilieer_bank_alle_administraties", lambda: {uitgesloten_id: rapport}
        )
        monkeypatch.setattr(
            cli.acceptatie_service, "uitgesloten_administraties", lambda: {uitgesloten_id: "testadministratie"}
        )
        monkeypatch.setattr(
            cli.acceptatie_service,
            "beoordeel",
            lambda **kwargs: [_beoordeeld(a[0], geaccepteerd=True) for a in kwargs["afwijkingen"]],
        )

        exit_code = cli.main(["bank-reconciliatie"])

        uitvoer = capsys.readouterr().out
        assert exit_code == 0
        assert (
            f"UITGESLOTEN {uitgesloten_id}: 3 gecontroleerd, 0 open, 2 geaccepteerd — telt niet mee (testadministratie)"
            in uitvoer
        )
        assert (
            "0 afwijking(en) totaal (0 geaccepteerd; daarnaast 2 geaccepteerd op uitgesloten "
            "administraties — telt niet mee)." in uitvoer
        )
