"""Ketentest = het kliktest-script van de app-auth zonder passkey (besluit Peter 08-09), e2e via TestClient:

verse installatie → uitnodiging (mail mét code) → activatiecode invoeren → toegangscode kiezen (lokaal; hier alleen
het server-feit) → voorwaarden-akkoord → wachtrij (200) → app sluiten → stille refresh → 5× foute toegangscode →
toestel uitgesloten (sessie dood) → kantoor stuurt herstel-link → opnieuw activeren op het toestel → wachtrij weer
open. Elke stap tegen de echte routes; geen passkey, geen TOTP, geen wachtwoord."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from tests.auth.test_app_activatie import APP, _activeer, _audit_op, _nodig_uit, _toestel, client
from tests.auth.test_webauthn_cadans import _bearer, _beheerder_bearer


def test_keten_verse_installatie_tot_herstel(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
) -> None:
    from app.berichten import mail

    verzonden: list[dict] = []
    monkeypatch.setattr(mail, "verzend_mail", lambda **kw: verzonden.append(kw))

    # 1. Kantoor nodigt uit — de mail draagt link én activatiecode.
    uitnodiging = _nodig_uit(beheerder_id, administratie_id=administratie_id, naam="Jan de Accordeur")
    assert uitnodiging["mail_verzonden"] and uitnodiging["activatiecode"] in verzonden[-1]["tekst"]

    # 2. Verse installatie: geen sessie, alleen de code — activeren.
    resp = _activeer(
        {"activatiecode": uitnodiging["activatiecode"], "toestel_naam": "iPhone van Jan", "platform": "ios"}
    )
    assert resp.status_code == 200, resp.text
    sessie = resp.json()
    assert sessie["naam"] == "Jan de Accordeur"
    gid = uuid.UUID(uitnodiging["gebruiker_id"])
    toestel = _toestel(admin_engine, gid)
    assert toestel["soort"] == "toestel"

    # 3. Toegangscode kiezen gebeurt lokaal; de server ziet alleen een eventueel wijzig-feit later.
    headers = _bearer(sessie["access_token"])
    # Zonder akkoord geen wachtrij (bestaande poort), daarna wel.
    assert client.get("/accordering/wachtrij", headers=headers).status_code == 403
    assert client.post("/auth/accordeur/voorwaarden-akkoord", headers=headers).status_code == 204
    resp = client.get("/accordering/wachtrij", headers=headers)
    assert resp.status_code == 200, resp.text

    # 4. App sluiten en heropenen: stille refresh via het toestel-token — geen ontgrendel-ceremonie.
    resp = client.post("/auth/token/vernieuwen", headers={**APP, "X-Refresh-Token": sessie["refresh_token"]})
    assert resp.status_code == 200, resp.text
    vers = resp.json()
    assert "ontgrendeling_nodig" not in vers
    headers = _bearer(vers["access_token"])
    assert client.get("/accordering/wachtrij", headers=headers).status_code == 200

    # 5. Toegangscode gewijzigd in Instellingen — server krijgt alleen het feit.
    assert client.post("/auth/app/toegangscode-gewijzigd", headers=headers).status_code == 204
    assert _audit_op(admin_engine, toestel["id"], "toegangscode_gewijzigd")

    # 6. 5× foute toegangscode: het toestel meldt zich af — sessie is per direct dood.
    assert (
        client.post("/auth/app-lock/uitgesloten", json={"credential_id": sessie["apparaat_credential_id"]}).status_code
        == 204
    )
    assert client.get("/accordering/wachtrij", headers=headers).status_code == 401
    assert (
        client.post("/auth/token/vernieuwen", headers={**APP, "X-Refresh-Token": vers["refresh_token"]}).status_code
        == 401
    )
    # De oude code is verbruikt — opnieuw activeren met dezelfde code kan niet (409).
    assert _activeer({"activatiecode": uitnodiging["activatiecode"]}, ip="203.0.113.120").status_code == 409
    # Hulpvraag aan het kantoor.
    monkeypatch.setattr("app.config.settings.berichten_reply_to", "kantoor@test.local")
    assert (
        client.post("/auth/app-lock/hulp", json={"credential_id": sessie["apparaat_credential_id"]}).status_code == 204
    )
    assert verzonden[-1]["naar"] == "kantoor@test.local"

    # 7. Kantoor stuurt een herstel-link (nieuwe code) → opnieuw activeren → toegangscode kiezen → wachtrij open.
    resp = client.post(f"/auth/gebruikers/{gid}/herstel-link", headers=_beheerder_bearer(beheerder_id))
    assert resp.status_code == 200, resp.text
    herstel = resp.json()
    assert herstel["activatiecode"] in verzonden[-1]["tekst"]
    resp = _activeer(
        {"activatiecode": herstel["activatiecode"], "toestel_naam": "iPhone van Jan", "platform": "ios"},
        ip="203.0.113.121",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["herstel"] is True
    headers = _bearer(resp.json()["access_token"])
    assert client.get("/accordering/wachtrij", headers=headers).status_code == 200  # akkoord blijft staan

    with admin_engine.connect() as conn:
        toestellen = (
            conn.execute(
                text(
                    "SELECT ingetrokken_op IS NOT NULL FROM platform.webauthn_credential "
                    "WHERE gebruiker_id = :g ORDER BY aangemaakt_op"
                ),
                {"g": gid},
            )
            .scalars()
            .all()
        )
    assert toestellen == [True, False]  # oud toestel ingetrokken, nieuw actief — niets verwijderd
