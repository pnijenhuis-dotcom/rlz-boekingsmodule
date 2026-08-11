"""Accordeur-auth-cadans over ECHTE HTTP (blok 1 accordeur-PWA, besluit 2026-08-11): de hele
cadans op de draad — registratie, assertion bij app-opening (ontgrendelen), 7-dagen-verval,
nieuw apparaat, kill-switch en de race met de bestaande single-flight refresh. WebAuthn met
échte crypto via SoftWebauthnApparaat (geen mocks); uvicorn-subprocess conform tests/e2e."""

from __future__ import annotations

import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta

import httpx
import pytest
from sqlalchemy import Engine, text

from app.security.passwords import hash_password
from tests.auth.soft_webauthn import SoftWebauthnApparaat

_CLIENT_TIMEOUT = 15.0
WACHTWOORD = "een-heel-lang-wachtwoord"


@pytest.fixture
def accordeur(admin_engine: Engine) -> tuple[uuid.UUID, str]:
    """Actieve klant-accordeur mét wachtwoord (activatie-flow zelf wordt apart getest in
    tests/auth/test_webauthn_cadans.py) + vastgelegd voorwaarden-akkoord."""
    gid = uuid.uuid4()
    e_mail = f"{gid}@test.local"
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status, wachtwoord_hash) "
                "VALUES (:id, 'E2E Accordeur', :mail, 'klant_accordeur', 'actief', :hash)"
            ),
            {"id": gid, "mail": e_mail, "hash": hash_password(WACHTWOORD)},
        )
    return gid, e_mail


def _volledige_login(server: str, apparaat: SoftWebauthnApparaat, e_mail: str, *, registreer: bool) -> httpx.Response:
    """Wachtwoordstap + registratie (nieuw apparaat) of assertion (bekend apparaat)."""
    resp = httpx.post(
        f"{server}/auth/accordeur/login",
        json={"e_mail": e_mail, "wachtwoord": WACHTWOORD},
        timeout=_CLIENT_TIMEOUT,
    )
    assert resp.status_code == 200, resp.text
    setup = {"Authorization": f"Bearer {resp.json()['passkey_setup_token']}"}
    assert resp.json()["heeft_passkeys"] is (not registreer)

    if registreer:
        opties = httpx.post(f"{server}/auth/webauthn/registratie/opties", headers=setup, timeout=_CLIENT_TIMEOUT)
        assert opties.status_code == 200, opties.text
        return httpx.post(
            f"{server}/auth/webauthn/registratie/voltooien",
            json={"credential": apparaat.registreer(opties.json()["opties"]), "apparaat_naam": "E2E-telefoon"},
            headers=setup,
            timeout=_CLIENT_TIMEOUT,
        )
    opties = httpx.post(f"{server}/auth/webauthn/login/opties", headers=setup, timeout=_CLIENT_TIMEOUT)
    assert opties.status_code == 200, opties.text
    return httpx.post(
        f"{server}/auth/webauthn/login/voltooien",
        json={"credential": apparaat.onderteken(opties.json()["opties"])},
        headers=setup,
        timeout=_CLIENT_TIMEOUT,
    )


def _ontgrendel(server: str, apparaat: SoftWebauthnApparaat, refresh_cookie: str) -> httpx.Response:
    """App-opening: assertion-options op de refresh-cookie, dan ontgrendelen (assertion +
    cookie-rotatie in één)."""
    cookies = {"refresh_token": refresh_cookie}
    opties = httpx.post(
        f"{server}/auth/token/vernieuwen/ontgrendel-opties", cookies=cookies, timeout=_CLIENT_TIMEOUT
    )
    if opties.status_code != 200:
        return opties
    return httpx.post(
        f"{server}/auth/token/vernieuwen/ontgrendelen",
        json={"credential": apparaat.onderteken(opties.json()["opties"])},
        cookies=cookies,
        timeout=_CLIENT_TIMEOUT,
    )


class TestAccordeurCadansE2E:
    def test_registratie_ontgrendelen_nieuw_apparaat_en_kill_switch(
        self, server: str, admin_engine: Engine, accordeur: tuple[uuid.UUID, str], beheerder_id: uuid.UUID
    ) -> None:
        gebruiker_id, e_mail = accordeur

        # 1. Eerste gebruik: volledige login mét passkey-registratie (apparaat A).
        apparaat_a = SoftWebauthnApparaat()
        login_a = _volledige_login(server, apparaat_a, e_mail, registreer=True)
        assert login_a.status_code == 200, login_a.text
        cookie_a = login_a.cookies["refresh_token"]
        access_a = login_a.json()["access_token"]

        # 2. App-opening op hetzelfde apparaat: assertion + rotatie — cadans "biometrie éénmaal
        # per opening", geen wachtwoord.
        heropening = _ontgrendel(server, apparaat_a, cookie_a)
        assert heropening.status_code == 200, heropening.text
        cookie_a2 = heropening.cookies["refresh_token"]
        assert cookie_a2 != cookie_a  # rotatie gebeurde echt

        # 3. Nieuw/onbekend apparaat B: geen cookie -> volledige login; er is al een passkey op
        # A, dus B registreert een tweede credential (assertion kan B niet leveren).
        apparaat_b = SoftWebauthnApparaat()
        resp = httpx.post(
            f"{server}/auth/accordeur/login",
            json={"e_mail": e_mail, "wachtwoord": WACHTWOORD},
            timeout=_CLIENT_TIMEOUT,
        )
        assert resp.status_code == 200 and resp.json()["heeft_passkeys"] is True
        setup_b = {"Authorization": f"Bearer {resp.json()['passkey_setup_token']}"}
        opties = httpx.post(
            f"{server}/auth/webauthn/registratie/opties", headers=setup_b, timeout=_CLIENT_TIMEOUT
        )
        login_b = httpx.post(
            f"{server}/auth/webauthn/registratie/voltooien",
            json={"credential": apparaat_b.registreer(opties.json()["opties"]), "apparaat_naam": "Tablet"},
            headers=setup_b,
            timeout=_CLIENT_TIMEOUT,
        )
        assert login_b.status_code == 200, login_b.text
        cookie_b = login_b.cookies["refresh_token"]

        # 4. Kill-switch op apparaat A (kantoor): apparatenlijst -> intrekken.
        from app.security.tokens import create_access_token

        admin = {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}
        lijst = httpx.get(
            f"{server}/auth/gebruikers/{gebruiker_id}/apparaten", headers=admin, timeout=_CLIENT_TIMEOUT
        )
        assert lijst.status_code == 200
        apparaten = lijst.json()["apparaten"]
        assert len(apparaten) == 2
        apparaat_a_id = next(a["id"] for a in apparaten if a["apparaat_naam"] == "E2E-telefoon")
        intrek = httpx.post(
            f"{server}/auth/apparaten/{apparaat_a_id}/intrekken", headers=admin, timeout=_CLIENT_TIMEOUT
        )
        assert intrek.status_code == 204

        # 5. Apparaat A is per direct dood op alle drie de lagen: access-token (deps-toets),
        # refresh-rotatie én ontgrendel-assertion. Apparaat B blijft gewoon werken.
        api_a = httpx.get(
            f"{server}/auth/administraties",
            headers={"Authorization": f"Bearer {access_a}"},
            timeout=_CLIENT_TIMEOUT,
        )
        assert api_a.status_code == 401
        refresh_a = httpx.post(
            f"{server}/auth/token/vernieuwen", cookies={"refresh_token": cookie_a2}, timeout=_CLIENT_TIMEOUT
        )
        assert refresh_a.status_code == 401
        ontgrendel_a = _ontgrendel(server, apparaat_a, cookie_a2)
        assert ontgrendel_a.status_code == 401
        refresh_b = httpx.post(
            f"{server}/auth/token/vernieuwen", cookies={"refresh_token": cookie_b}, timeout=_CLIENT_TIMEOUT
        )
        assert refresh_b.status_code == 200, refresh_b.text

    def test_7_dagen_inactiviteit_dwingt_volledige_login_met_assertion(
        self, server: str, admin_engine: Engine, accordeur: tuple[uuid.UUID, str]
    ) -> None:
        gebruiker_id, e_mail = accordeur
        apparaat = SoftWebauthnApparaat()
        login = _volledige_login(server, apparaat, e_mail, registreer=True)
        assert login.status_code == 200
        cookie = login.cookies["refresh_token"]

        # 7 dagen stil: het refresh-token is verlopen (sliding TTL) -> ontgrendelen weigert.
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.refresh_token SET verloopt_op = :verleden "
                    "WHERE gebruiker_id = :g AND ingetrokken_op IS NULL"
                ),
                {"verleden": datetime.now(UTC) - timedelta(minutes=1), "g": gebruiker_id},
            )
        verlopen = _ontgrendel(server, apparaat, cookie)
        assert verlopen.status_code == 401

        # Volledige login op het BEKENDE apparaat: wachtwoord + assertion (geen herregistratie).
        opnieuw = _volledige_login(server, apparaat, e_mail, registreer=False)
        assert opnieuw.status_code == 200, opnieuw.text
        assert _ontgrendel(server, apparaat, opnieuw.cookies["refresh_token"]).status_code == 200

    def test_race_met_single_flight_refresh_geen_revoke_all_op_apparaatsessie(
        self, server: str, admin_engine: Engine, accordeur: tuple[uuid.UUID, str]
    ) -> None:
        """De bestaande race-tolerantie (grace-sibling, geen revoke-all) blijft gelden voor een
        apparaat-gebonden accordeur-sessie — en de sibling behoudt de apparaatbinding."""
        _, e_mail = accordeur
        apparaat = SoftWebauthnApparaat()
        login = _volledige_login(server, apparaat, e_mail, registreer=True)
        token = login.cookies["refresh_token"]

        def vernieuw(t: str) -> httpx.Response:
            return httpx.post(
                f"{server}/auth/token/vernieuwen", cookies={"refresh_token": t}, timeout=_CLIENT_TIMEOUT
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            antwoorden = list(pool.map(lambda _: vernieuw(token), range(2)))
        assert [a.status_code for a in antwoorden] == [200, 200], [
            (a.status_code, a.text) for a in antwoorden
        ]
        # Beide uitgegeven tokens (winnaar + grace-sibling) zijn apparaat-gebonden gebleven én
        # bruikbaar: het ontgrendelen (assertion op de apparaatbinding) werkt op allebei.
        for antwoord in antwoorden:
            assert _ontgrendel(server, apparaat, antwoord.cookies["refresh_token"]).status_code == 200
