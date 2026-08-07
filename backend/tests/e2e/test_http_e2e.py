"""Echte-HTTP-e2e per muterend endpoint (Vastly-port c, 2026-08-07): elk request loopt hier door
h11, de socketlaag en de ECHTE middleware-stack van een uvicorn-subprocess — precies wat een
in-process TestClient overslaat. Dekt de muterende werkwoorden (PUT/PATCH) + de browser-realiteit
eromheen: preflight, CORS-headers op foutantwoorden, en het extra="forbid"-contract op de body."""

from __future__ import annotations

import uuid

import httpx
import pytest

from app.config import settings
from app.security.tokens import create_access_token

_ORIGIN = settings.cors_allowed_origins[0]


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class TestPreflightOverEchteHttp:
    @pytest.mark.parametrize("methode", ["PUT", "PATCH", "DELETE"])
    def test_preflight_muterende_methoden(self, server: str, methode: str) -> None:
        antwoord = httpx.options(
            f"{server}/instellingen/intake-ai",
            headers={
                "Origin": _ORIGIN,
                "Access-Control-Request-Method": methode,
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )
        assert antwoord.status_code == 200, f"{methode}: {antwoord.text}"
        assert methode in antwoord.headers.get("access-control-allow-methods", "")


class TestPutOverEchteHttp:
    def test_put_instelling_persisteert_en_leest_terug(self, server: str, beheerder_id: uuid.UUID) -> None:
        headers = {**_bearer(beheerder_id, rol="beheerder"), "Origin": _ORIGIN}

        zet = httpx.put(f"{server}/instellingen/intake-ai", headers=headers, json={"ingeschakeld": True})
        assert zet.status_code == 200, zet.text
        assert zet.json() == {"ingeschakeld": True}
        assert zet.headers.get("access-control-allow-origin") == _ORIGIN

        lees = httpx.get(f"{server}/instellingen/intake-ai", headers=headers)
        assert lees.json() == {"ingeschakeld": True}

        terug = httpx.put(f"{server}/instellingen/intake-ai", headers=headers, json={"ingeschakeld": False})
        assert terug.status_code == 200

    def test_onbekend_veld_is_422_met_veldnaam(self, server: str, beheerder_id: uuid.UUID) -> None:
        """extra="forbid" over echte HTTP: een typefout in de veldnaam komt terug als 422 mét de
        naam — niet als stil genegeerde no-op (de Vastly-'checkbox sloeg nooit op'-bugklasse)."""
        headers = _bearer(beheerder_id, rol="beheerder")
        antwoord = httpx.put(
            f"{server}/instellingen/intake-ai", headers=headers, json={"ingeschekeld": True}
        )
        assert antwoord.status_code == 422
        assert "ingeschekeld" in antwoord.text

    def test_boeken_instelling_per_administratie(
        self, server: str, beheerder_id: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        zet = httpx.put(
            f"{server}/administraties/{administratie_id}/boeken-instelling",
            headers=headers,
            json={"ingeschakeld": True},
        )
        assert zet.status_code == 200, zet.text
        lees = httpx.get(f"{server}/administraties/{administratie_id}/boeken-instelling", headers=headers)
        assert lees.json() == {"ingeschakeld": True}


class TestPatchOverEchteHttp:
    def test_patch_rol_wijzigen(self, server: str, beheerder_id: uuid.UUID, actieve_medewerker: uuid.UUID) -> None:
        headers = _bearer(beheerder_id, rol="beheerder")
        antwoord = httpx.patch(
            f"{server}/auth/gebruikers/{actieve_medewerker}/rol",
            headers=headers,
            json={"rol": "boekhouding_projecten"},
        )
        assert antwoord.status_code == 204, antwoord.text


class TestFoutpadenOverEchteHttp:
    def test_404_draagt_cors_headers(self, server: str) -> None:
        antwoord = httpx.get(f"{server}/bestaat-niet", headers={"Origin": _ORIGIN})
        assert antwoord.status_code == 404
        assert antwoord.headers.get("access-control-allow-origin") == _ORIGIN

    def test_niet_uuid_in_pad_is_nette_422(self, server: str, beheerder_id: uuid.UUID) -> None:
        headers = {**_bearer(beheerder_id, rol="beheerder"), "Origin": _ORIGIN}
        antwoord = httpx.put(
            f"{server}/administraties/geen-uuid/boeken-instelling",
            headers=headers,
            json={"ingeschakeld": True},
        )
        assert antwoord.status_code == 422
        assert antwoord.headers.get("access-control-allow-origin") == _ORIGIN
