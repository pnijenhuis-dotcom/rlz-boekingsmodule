"""Rol × endpoint-regressiematrix (rollen-gate-fix 2026-08-21, kliktest Peter).

Aanleiding: een zojuist geactiveerde ZZP'er landde via de web-app in de kantoor-console; de
datalaag hield toevallig dicht, maar server-side gaven kantoor-endpoints 200 aan veldrollen —
óók mét administratie-scope (veldwerkers en accordeurs hebben reguliere
gebruiker_administratie-rijen, dus vereis_administratie_scope alléén is géén rolpoort).

Twee lagen:
1. Expliciete matrix over representatieve endpoints per router — extern (veldrollen +
   accordeur) → 403, kantoor → géén rolweigering.
2. Fail-closed sweep over ÁLLE routes in de app: elke niet-expliciet-toegestane route moet
   een veldrol weigeren (401/403). Een nieuw endpoint zonder rolpoort laat deze sweep falen —
   dicht óf bewust in de allowlist, nooit stil open.
"""

from __future__ import annotations

import re
import uuid

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.auth import voorwaarden
from app.main import app
from app.security.tokens import create_access_token
from tests.uren.conftest import maak_gebruiker

client = TestClient(app)

DUMMY_ID = uuid.uuid4()


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def administratie_id(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id) "
                "VALUES (:id, 'Matrix (test)', :rlz)"
            ),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _extern_met_scope(
    admin_engine: Engine, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, rol: str
) -> uuid.UUID:
    """Externe rol in de staat van Peters kliktest: geactiveerd, mét administratie-scope en
    mét voorwaarden-akkoord — de rolpoort moet het verschil maken, niet een toevallig lege
    scope of ontbrekend akkoord."""
    gid = maak_gebruiker(admin_engine, rol, f"Extern {rol}")
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id
    )
    voorwaarden.leg_akkoord_vast(gebruiker_id=gid)
    return gid


@pytest.fixture
def zzper(admin_engine: Engine, beheerder_id, administratie_id) -> uuid.UUID:
    return _extern_met_scope(admin_engine, beheerder_id, administratie_id, "zzper")


@pytest.fixture
def uitvoerder(admin_engine: Engine, beheerder_id, administratie_id) -> uuid.UUID:
    return _extern_met_scope(admin_engine, beheerder_id, administratie_id, "uitvoerder")


@pytest.fixture
def detacheerder(admin_engine: Engine, beheerder_id, administratie_id) -> uuid.UUID:
    return _extern_met_scope(admin_engine, beheerder_id, administratie_id, "detacheerder")


@pytest.fixture
def accordeur(admin_engine: Engine, beheerder_id, administratie_id) -> uuid.UUID:
    return _extern_met_scope(admin_engine, beheerder_id, administratie_id, "klant_accordeur")


@pytest.fixture
def boekhouder(admin_engine: Engine, beheerder_id, administratie_id) -> uuid.UUID:
    gid = maak_gebruiker(admin_engine, "boekhouding", "Kantoor B.")
    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=administratie_id
    )
    return gid


VELD_ROLLEN = ["zzper", "uitvoerder", "detacheerder"]


def _kantoor_endpoints(aid: uuid.UUID) -> list[tuple[str, str]]:
    """Eén representatief endpoint per kantoor-router (methode, pad)."""
    return [
        ("GET", "/werkvoorraad/overzicht"),  # documenten
        ("GET", f"/administraties/{aid}/documenten/{DUMMY_ID}"),  # documenten-detail
        ("GET", "/bank/overzicht"),  # bank
        ("GET", f"/administraties/{aid}/bank/rekeningen"),  # bank per administratie
        ("GET", "/zoeken?term=test"),  # zoeken
        ("GET", f"/administraties/{aid}/archief"),  # archief
        ("GET", f"/administraties/{aid}/grootboek"),  # sync
        ("GET", f"/administraties/{aid}/crediteuren"),  # sync
        ("GET", "/verzamelbak"),  # intake
        ("GET", f"/administraties/{aid}/accordering/instellingen"),  # accordering kantoor
        ("GET", f"/administraties/{aid}/accordering/herinneringen"),  # accordering kantoor
        ("POST", f"/administraties/{aid}/omzet/documenten/{DUMMY_ID}/boeken"),  # omzet
        ("GET", "/auth/gebruikers"),  # gebruikersbeheer (beheerder-only)
        ("GET", f"/uren/kantoor/stand?administratie_id={aid}"),  # uren kantoorkant
        ("GET", f"/projecten/{aid}"),  # projectenmodule kantoor (22-08)
    ]


class TestExterneRollenGeweigerd:
    """Elke externe app-rol krijgt 403 op kantoor-endpoints — óók mét scope + akkoord."""

    @pytest.mark.parametrize("rol", [*VELD_ROLLEN, "klant_accordeur"])
    def test_kantoor_endpoints_403(self, rol, administratie_id, request):
        fixture = {"klant_accordeur": "accordeur"}.get(rol, rol)
        gid = request.getfixturevalue(fixture)
        # NB de accordering-endpoints in deze lijst zijn de kantoor-only-varianten
        # (instellingen/herinneringen) — de besluit-endpoints van de accordeur zelf
        # (wachtrij/akkoord/staande regels) blijven open en staan apart getest hieronder.
        for methode, pad in _kantoor_endpoints(administratie_id):
            resp = client.request(methode, pad, headers=_bearer(gid, rol=rol))
            assert resp.status_code == 403, f"{rol} {methode} {pad}: {resp.status_code}"

    def test_veldrol_geen_pdf_bestand(self, zzper, administratie_id):
        resp = client.get(
            f"/administraties/{administratie_id}/documenten/{DUMMY_ID}/bestand",
            headers=_bearer(zzper, rol="zzper"),
        )
        assert resp.status_code == 403

    def test_veldrol_geen_wachtrij(self, zzper):
        resp = client.get("/accordering/wachtrij", headers=_bearer(zzper, rol="zzper"))
        assert resp.status_code == 403


class TestAccordeurPadenBlijvenOpen:
    """De accordeur-PWA-flows mogen niet sneuvelen op de nieuwe rolpoorten."""

    def test_wachtrij_200(self, accordeur):
        resp = client.get("/accordering/wachtrij", headers=_bearer(accordeur, rol="klant_accordeur"))
        assert resp.status_code == 200

    def test_pdf_bestand_geen_rolweigering(self, accordeur, administratie_id):
        # 404 (onbekend document) is prima — het mag alleen géén 403-rolpoort zijn.
        resp = client.get(
            f"/administraties/{administratie_id}/documenten/{DUMMY_ID}/bestand",
            headers=_bearer(accordeur, rol="klant_accordeur"),
        )
        assert resp.status_code == 404

    def test_staande_regels_200(self, accordeur, administratie_id):
        resp = client.get(
            f"/administraties/{administratie_id}/accordering/staande-regels",
            headers=_bearer(accordeur, rol="klant_accordeur"),
        )
        assert resp.status_code == 200


class TestKantoorBlijftWerken:
    """Kantoorrollen worden nergens door de nieuwe rolpoort geraakt."""

    def test_kantoor_endpoints_geen_403_rolpoort(self, boekhouder, administratie_id):
        for methode, pad in _kantoor_endpoints(administratie_id):
            if pad == "/auth/gebruikers" or pad.startswith("/uren/kantoor"):
                # Beheerder-only resp. module-recht 'Meerwerk & urenstaten': 403 voor een
                # boekhouder zónder dat recht is correct bestaand gedrag, geen rolpoort-regressie.
                continue
            resp = client.request(methode, pad, headers=_bearer(boekhouder, rol="boekhouding"))
            assert resp.status_code != 403, f"boekhouding {methode} {pad}: onterecht 403"
            assert resp.status_code != 401, f"boekhouding {methode} {pad}: onterecht 401"

    def test_beheerder_gebruikerslijst_200(self, beheerder_id):
        resp = client.get("/auth/gebruikers", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200

    def test_kantoorrol_geen_veld_endpoints(self, boekhouder):
        resp = client.get("/uren/zzp/projecten", headers=_bearer(boekhouder, rol="boekhouding"))
        assert resp.status_code == 403


# --- Laag 2: fail-closed sweep over álle routes -------------------------------------------------

# Routes waar een VELDROL (zzper) légitiem iets anders dan 401/403 mag krijgen, of die geen
# bearer-auth dragen (eigen authenticatie of publiek). Bewust prefix-match op het RUWE
# routepad — een nieuw endpoint buiten deze lijst MOET een veldrol weigeren.
SWEEP_ALLOWLIST_PREFIXES = (
    "/auth/",  # login-/activatie-/eigen-sessie-endpoints (publiek of eigen account);
    #             beheer-endpoints eronder zijn require_beheerder en in de matrix gedekt
    "/.well-known/",  # passkey-associatiebestanden (publiek, fail-closed elders getest)
    "/privacy",  # voorwaarden-/privacypagina (publiek, informatieplicht)
    "/koppelvlak/vastgoed/",  # HMAC-authenticatie (geen bearer; eigen poorten + tests)
    "/notificaties/",  # eigen accordeur-poort (veldrol krijgt daar al 403; subscripties
    #                     per apparaat zijn eigen-account-data)
    "/uren/zzp/",  # veld-app: eigen flows (vereis_veldrol + voorwaarden-poort)
    "/uren/uitvoerder/",
    "/uren/detacheerder/",
    "/uren/weekstaten/",
    "/uren/meerwerk/",
    "/uren/projectdocumenten/",
    "/uren/dossier",  # ZZP-dossier veldkant (A1/A2, 25-08): eigen dossier + upload (vereis_veldrol)
    "/health",  # liveness (publiek)
)


def _alle_api_routes() -> list[APIRoute]:
    """app.routes bevat in deze FastAPI-versie lazy `_IncludedRouter`-wrappers per
    include_router-aanroep — uitpakken via original_router, anders ziet de sweep niets
    (en zou 'ie stil groen zijn: vandaar de len>0-assert in de test hieronder)."""
    routes: list[APIRoute] = []
    for route in app.routes:
        if isinstance(route, APIRoute):
            routes.append(route)
        else:
            binnenliggend = getattr(route, "original_router", None)
            if binnenliggend is not None:
                routes.extend(r for r in binnenliggend.routes if isinstance(r, APIRoute))
    return routes


def _sweep_routes() -> list[tuple[str, str]]:
    paren: list[tuple[str, str]] = []
    for route in _alle_api_routes():
        if not route.include_in_schema:
            continue  # SPA-fallback e.d.
        if route.path.startswith(SWEEP_ALLOWLIST_PREFIXES):
            continue
        for methode in sorted(route.methods - {"HEAD", "OPTIONS"}):
            paren.append((methode, route.path))
    return paren


class TestFailClosedSweep:
    def test_sweep_ziet_de_routes(self):
        """Vangnet op het vangnet: als een FastAPI-upgrade de route-introspectie breekt, moet
        deze test rood worden i.p.v. dat de sweep stil leeg draait (dat gebeurde op de eerste
        run met de _IncludedRouter-wrappers)."""
        assert len(_sweep_routes()) > 50

    @pytest.mark.parametrize("methode,pad", _sweep_routes())
    def test_veldrol_geweigerd(self, methode, pad, zzper, administratie_id):
        """Padparameters krijgen echte scope (administratie) resp. dummy-UUID's: de weigering
        moet van de rólpoort komen, niet van een toevallig ontbrekende scope-rij. Dependencies
        draaien vóór body-validatie, dus een lege body maskeert geen ontbrekende poort."""
        url = pad.replace("{administratie_id}", str(administratie_id))
        # Overige padparameters ({document_id}, {regel_id}, …) → dummy-UUID.
        url = re.sub(r"\{[^}]+\}", str(DUMMY_ID), url)
        resp = client.request(methode, url, headers=_bearer(zzper, rol="zzper"))
        assert resp.status_code in (401, 403), (
            f"OPEN ENDPOINT voor veldrol: {methode} {pad} gaf {resp.status_code} — "
            "voeg een rolpoort toe (vereis_kantoorrol/vereis_kantoor_of_accordeur) of neem het "
            "pad bewust op in SWEEP_ALLOWLIST_PREFIXES."
        )
