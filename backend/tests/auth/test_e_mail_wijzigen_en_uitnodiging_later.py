"""A4 (uitnodiging later versturen: account op 'uitgenodigd' zónder mail, alsnog mailen = de
bestaande Opnieuw-mailen-knop) + A5 (Beheerder wijzigt e-mailadres: uniciteit, audit, verse
uitnodiging naar het nieuwe adres voor niet-geactiveerde accounts, alleen-login voor
geactiveerde) — steigerbouw-run 25-08."""

from __future__ import annotations

import uuid

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service
from app.berichten import uitnodigingsmail
from app.db.models import GebruikerRol
from app.main import app
from app.security.tokens import create_access_token

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def mail_log(monkeypatch):
    verzonden: list[dict] = []
    monkeypatch.setattr(
        uitnodigingsmail, "verstuur_uitnodigingsmail", lambda **kw: verzonden.append(kw)
    )
    return verzonden


def _acties(admin_engine: Engine, record_id: uuid.UUID) -> list[tuple[str, dict | None, dict | None]]:
    with admin_engine.begin() as conn:
        return [
            (r[0], r[1], r[2])
            for r in conn.execute(
                text("SELECT actie, oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE record_id = :id ORDER BY tijdstip, id"),
                {"id": record_id},
            )
        ]


class TestUitnodigingLater:
    def test_zonder_mail_status_uitgenodigd_en_opnieuw_mailen_werkt(self, beheerder_id, mail_log, admin_engine):
        resp = client.post(
            "/auth/uitnodigingen",
            json={"naam": "Stefan B.", "e_mail": "stefan@test.local", "rol": "zzper", "administratie_ids": [], "uitnodiging_later": True},
            headers=_bearer(beheerder_id),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["mail_verzonden"] is False and body["mail_fout"] is None and body["mail_uitgesteld"] is True
        assert mail_log == []
        gid = uuid.UUID(body["gebruiker_id"])
        acties = _acties(admin_engine, uuid.UUID(body["uitnodiging_id"]))
        assert acties[0][0] == "gebruiker_uitgenodigd" and acties[0][2]["mail_uitgesteld"] is True
        resp = client.post(f"/auth/gebruikers/{gid}/uitnodiging-opnieuw", headers=_bearer(beheerder_id))
        assert resp.status_code == 200 and resp.json()["mail_verzonden"] is True
        assert mail_log[0]["e_mail"] == "stefan@test.local"

    def test_default_mailt_wel(self, beheerder_id, mail_log):
        resp = client.post(
            "/auth/uitnodigingen",
            json={"naam": "Rob T.", "e_mail": "rob@test.local", "rol": "boekhouding", "administratie_ids": []},
            headers=_bearer(beheerder_id),
        )
        assert resp.status_code == 200 and resp.json()["mail_verzonden"] is True and resp.json()["mail_uitgesteld"] is False
        assert len(mail_log) == 1


class TestEMailWijzigen:
    def test_niet_geactiveerd_krijgt_verse_uitnodiging_op_nieuw_adres(self, beheerder_id, mail_log, admin_engine):
        r = service.maak_uitnodiging(actor_id=beheerder_id, naam="Milan K.", e_mail="milan@oud.local", rol=GebruikerRol.ZZPER, administratie_ids=[])
        oud_token = r.token
        resp = client.patch(f"/auth/gebruikers/{r.gebruiker_id}/e-mail", json={"e_mail": "Milan@Nieuw.local "}, headers=_bearer(beheerder_id))
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["nieuw_e_mail"] == "milan@nieuw.local" and body["uitnodiging_vernieuwd"] is True and body["mail_verzonden"] is True
        assert mail_log[-1]["e_mail"] == "milan@nieuw.local"
        # Oude link is dood, de nieuwe werkt.
        with pytest.raises(service.AuthError):
            service.accepteer_uitnodiging(token=oud_token, wachtwoord="een-heel-lang-wachtwoord")
        acceptatie = service.accepteer_uitnodiging(token=body["token"], wachtwoord="een-heel-lang-wachtwoord")
        assert acceptatie.soort == "passkey"
        acties = _acties(admin_engine, r.gebruiker_id)
        e = next(a for a in acties if a[0] == "e_mail_gewijzigd")
        assert e[1] == {"e_mail": "milan@oud.local"} and e[2]["e_mail"] == "milan@nieuw.local" and e[2]["uitnodiging_vernieuwd"] is True

    def test_geactiveerd_alleen_login_wijzigt(self, beheerder_id, actieve_gebruiker, mail_log, admin_engine):
        resp = client.patch(f"/auth/gebruikers/{actieve_gebruiker.id}/e-mail", json={"e_mail": "nieuw@test.local"}, headers=_bearer(beheerder_id))
        assert resp.status_code == 200 and resp.json()["uitnodiging_vernieuwd"] is False and mail_log == []
        # Het oude adres is geen login meer; TOTP/wachtwoord/passkeys hangen aan het account-id
        # (een echte login-check hier loopt tegen het TOTP-replay-venster van de activatie aan —
        # zie tests/auth/conftest.py; de login-route zelf is elders gedekt).
        import pyotp

        code = pyotp.TOTP(actieve_gebruiker.secret).now()
        with pytest.raises(service.AuthError):
            service.login(e_mail=actieve_gebruiker.e_mail, wachtwoord=actieve_gebruiker.wachtwoord, totp_code=code)
        with admin_engine.begin() as conn:
            rij = conn.execute(
                text("SELECT e_mail, status, wachtwoord_hash IS NOT NULL FROM platform.gebruiker WHERE id = :id"),
                {"id": actieve_gebruiker.id},
            ).one()
        assert rij == ("nieuw@test.local", "actief", True)

    def test_uniciteit_en_poorten(self, beheerder_id, actieve_gebruiker, admin_engine):
        r = service.maak_uitnodiging(actor_id=beheerder_id, naam="X", e_mail="x@test.local", rol=GebruikerRol.ZZPER, administratie_ids=[])
        resp = client.patch(f"/auth/gebruikers/{r.gebruiker_id}/e-mail", json={"e_mail": actieve_gebruiker.e_mail.upper()}, headers=_bearer(beheerder_id))
        assert resp.status_code == 409
        resp = client.patch(f"/auth/gebruikers/{r.gebruiker_id}/e-mail", json={"e_mail": "x@test.local"}, headers=_bearer(beheerder_id))
        assert resp.status_code == 409
        resp = client.patch(f"/auth/gebruikers/{r.gebruiker_id}/e-mail", json={"e_mail": "geen-adres"}, headers=_bearer(beheerder_id))
        assert resp.status_code == 400
        resp = client.patch(f"/auth/gebruikers/{r.gebruiker_id}/e-mail", json={"e_mail": "y@test.local"}, headers=_bearer(actieve_gebruiker.id, rol="boekhouding"))
        assert resp.status_code == 403
        from app.db.systeem_actor import SYSTEEM_ACTOR_ID

        resp = client.patch(f"/auth/gebruikers/{SYSTEEM_ACTOR_ID}/e-mail", json={"e_mail": "y@test.local"}, headers=_bearer(beheerder_id))
        assert resp.status_code in (400, 403)
