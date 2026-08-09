"""Regressietest op de afletter-URL-vorm (kliktest-fix 2026-08-09).

De RLZ-UI POST't naar `PaymentTransactions/{id}/actions` (kleine a); onze client naar
`/Actions` (hoofdletter A). De geslaagde STAP-0-replay (api-verkenning "Afletteren
betaal-kant — REPLAY GESLAAGD", `poc_afletteren_betaalkant.py::post_raw_actions`) bewees de
`/Actions`-vorm mét Basic Auth — dat is de bewezen vorm en deze test pint de client daarop,
inclusief de exacte capture-body (Type 15 + PaymentItemList + LinkedAmount +
IsCompletelyPaid + PaymentCorrectionMethod gepind op 1)."""

from __future__ import annotations

import json
import uuid

import httpx

from app.rlz.client import RlzClient

_TX_ID = uuid.UUID("7d1387be-1968-4d31-b191-b1d0dbdc0a6f")
_ITEM_ID = uuid.UUID("9c2fbc51-2c1d-4a3e-8a68-4f2f7a4dfd42")


def test_link_payment_item_gebruikt_exact_de_bewezen_replay_vorm() -> None:
    gezien: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        gezien.append(request)
        return httpx.Response(204)

    http = httpx.Client(
        transport=httpx.MockTransport(handler), base_url="https://apps.reeleezee.nl/api/v1"
    )
    client = RlzClient(username="", password="", client=http)

    client.link_payment_item(_TX_ID, payment_item_id=_ITEM_ID, linked_amount=-121.0)

    [request] = gezien
    assert request.method == "POST"
    # Hoofdlettergevoelige pin op de bewezen replay-vorm — nooit stil laten afdrijven naar
    # de UI-casing (/actions) of een andere route.
    assert request.url.path == f"/api/v1/PaymentTransactions/{_TX_ID}/Actions"
    assert json.loads(request.content) == {
        "Type": 15,
        "PaymentItemList": [{"id": str(_ITEM_ID)}],
        "LinkedAmount": -121.0,
        "IsCompletelyPaid": False,
        "PaymentCorrectionMethod": 1,
    }
