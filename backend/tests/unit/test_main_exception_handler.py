"""Globale exception-handler (app/main.py): elke onverwachte fout moet een nette Nederlandse
melding + correlatie-id geven, nooit een kale "Internal Server Error" — en de volledige traceback
moet naar de server-log (caplog), niet naar de client. Los van de HTTP-laag getest (geen TestClient
nodig) zodat Starlette's reraise-gedrag in ServerErrorMiddleware hier niet stoort — dat pad wordt
end-to-end gedekt door tests/documenten/test_router_boeken.py."""

from __future__ import annotations

import asyncio
import logging
from types import SimpleNamespace

import pytest
from starlette.requests import Request

from app import main


def _maak_request(*, method: str = "POST", route_path: str | None = None) -> Request:
    scope: dict[str, object] = {"type": "http", "method": method, "path": "/willekeurig/pad", "headers": []}
    if route_path is not None:
        scope["route"] = SimpleNamespace(path=route_path)
    return Request(scope)


class TestActieOmschrijving:
    def test_bekende_route_geeft_specifieke_omschrijving(self) -> None:
        request = _maak_request(
            method="POST", route_path="/administraties/{administratie_id}/documenten/{document_id}/boeken"
        )
        assert main._actie_omschrijving(request) == "het boeken van de factuur"

    def test_onbekende_route_valt_terug_op_generiek(self) -> None:
        request = _maak_request(method="GET", route_path="/health")
        assert main._actie_omschrijving(request) == "het verwerken van je aanvraag"

    def test_ontbrekende_route_valt_ook_terug_op_generiek(self) -> None:
        request = _maak_request(method="POST", route_path=None)
        assert main._actie_omschrijving(request) == "het verwerken van je aanvraag"


class TestOnverwachteFoutHandler:
    def test_geeft_nette_melding_met_correlatie_id_nooit_de_interne_foutdetail(self) -> None:
        request = _maak_request(
            method="POST", route_path="/administraties/{administratie_id}/documenten/{document_id}/boeken"
        )

        response = asyncio.run(main.onverwachte_fout_handler(request, RuntimeError("geheim interne detail")))

        assert response.status_code == 500
        body = response.body.decode()
        assert "Er ging iets mis bij het boeken van de factuur" in body
        assert "geheim interne detail" not in body
        assert "Internal Server Error" not in body

    def test_logt_de_volledige_traceback(self, caplog: pytest.LogCaptureFixture) -> None:
        # logger.exception() leest sys.exc_info() — dus de fout écht raisen/vangen, niet alleen
        # een kale exception-instantie doorgeven (die zou geen traceback-info opleveren).
        request = _maak_request(method="POST", route_path=None)

        try:
            raise ValueError("kapotte invoer")
        except ValueError as exc:
            with caplog.at_level(logging.ERROR):
                asyncio.run(main.onverwachte_fout_handler(request, exc))

        assert any("Onverwachte fout" in record.getMessage() for record in caplog.records)
        assert any(record.exc_info is not None for record in caplog.records)
