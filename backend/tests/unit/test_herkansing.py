"""Eén herkansing per item bij een verbroken databaseverbinding (`app/db/herkansing.py`, 03-09):
classificatie (alleen verbindingsfouten), precies één herkansing, andere fouten ongewijzigd door,
tweede verbindingsfout = VerbindingVerbroken, herstel-hook vóór de tweede poging."""

from __future__ import annotations

import pytest
from sqlalchemy.exc import IntegrityError, OperationalError

from app.db import herkansing


class _PsycopgOperationalError(Exception):
    """Naamgelijk aan psycopg.OperationalError — de classificatie kijkt naar de typenaam + tekst."""


_PsycopgOperationalError.__name__ = "OperationalError"


def _disconnect(
    tekst: str = "server closed the connection unexpectedly", *, invalidated: bool = True
) -> OperationalError:
    return OperationalError("SELECT 1", {}, _PsycopgOperationalError(tekst), connection_invalidated=invalidated)


class TestClassificatie:
    def test_sqlalchemy_disconnect_en_libpq_teksten_zijn_verbroken(self) -> None:
        assert herkansing.is_verbroken_verbinding(_disconnect())
        assert herkansing.is_verbroken_verbinding(_disconnect("connection refused (proxy dicht)", invalidated=False))
        assert herkansing.is_verbroken_verbinding(_PsycopgOperationalError("SSL SYSCALL error: EOF detected"))
        # Verpakt in een eigen fout (raise … from …) blijft herkenbaar via de keten.
        try:
            try:
                raise _disconnect()
            except OperationalError as exc:
                raise RuntimeError("nabundelen mislukt") from exc
        except RuntimeError as buiten:
            assert herkansing.is_verbroken_verbinding(buiten)

    def test_gewone_fouten_zijn_geen_blip(self) -> None:
        assert not herkansing.is_verbroken_verbinding(IntegrityError("INSERT", {}, Exception("unique violation")))
        assert not herkansing.is_verbroken_verbinding(_disconnect("syntax error at or near", invalidated=False))
        assert not herkansing.is_verbroken_verbinding(ValueError("geen geldige UBL"))


class TestHerkansing:
    def test_geslaagd_zonder_blip_herkanst_niet(self) -> None:
        slaap: list[float] = []
        resultaat, herkanst = herkansing.voer_uit_met_herkansing(lambda: 42, label="x", slaap=slaap.append)
        assert (resultaat, herkanst) == (42, False) and slaap == []

    def test_een_blip_wordt_precies_een_keer_herkanst(self) -> None:
        pogingen: list[int] = []
        herstel: list[str] = []
        slaap: list[float] = []

        def item() -> str:
            pogingen.append(1)
            if len(pogingen) == 1:
                raise _disconnect()
            return "klaar"

        resultaat, herkanst = herkansing.voer_uit_met_herkansing(
            item, label="paar 1", wacht_seconds=3.0, slaap=slaap.append, voor_herkansing=lambda: herstel.append("reset")
        )
        assert (resultaat, herkanst) == ("klaar", True)
        assert len(pogingen) == 2 and slaap == [3.0] and herstel == ["reset"]

    def test_tweede_blip_is_verbinding_verbroken(self) -> None:
        pogingen: list[int] = []

        def item() -> None:
            pogingen.append(1)
            raise _disconnect()

        with pytest.raises(herkansing.VerbindingVerbroken, match="paar 2") as exc_info:
            herkansing.voer_uit_met_herkansing(item, label="paar 2", wacht_seconds=0, slaap=lambda _s: None)
        assert len(pogingen) == 2 and isinstance(exc_info.value.__cause__, OperationalError)

    def test_andere_fout_gaat_ongewijzigd_door_zonder_herkansing(self) -> None:
        pogingen: list[int] = []

        def item() -> None:
            pogingen.append(1)
            raise ValueError("geen geldige UBL")

        with pytest.raises(ValueError, match="geen geldige UBL"):
            herkansing.voer_uit_met_herkansing(item, label="paar 3", slaap=lambda _s: None)
        assert len(pogingen) == 1

    def test_andere_fout_in_de_herkansing_gaat_ook_door(self) -> None:
        pogingen: list[int] = []

        def item() -> None:
            pogingen.append(1)
            if len(pogingen) == 1:
                raise _disconnect()
            raise IntegrityError("INSERT", {}, Exception("unique violation"))

        with pytest.raises(IntegrityError):
            herkansing.voer_uit_met_herkansing(item, label="paar 4", wacht_seconds=0, slaap=lambda _s: None)
        assert len(pogingen) == 2
