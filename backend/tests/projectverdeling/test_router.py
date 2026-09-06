"""Endpoints projectverdeling (HTTP-niveau): GET/PUT per document, per-leverancier-opt-in en instellingen
Beheerder-only (boekhouder = 403), kantoorbrede hercontrole-lijst, en de lijst-chip op de documentenlijst."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.main import app
from app.projectverdeling import hercontrole
from app.security.tokens import create_access_token
from tests.projectverdeling.conftest import PERIODE, seed_omzet
from tests.projectverdeling.test_service import geboekt_met_verdeling  # noqa: F401 — fixture (geboekt + signaal-basis)

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


class TestDocumentEndpoints:
    def test_get_put_en_blokkade(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project, projecten
    ) -> None:
        pad = f"/administraties/{administratie_id}/documenten/{document_zonder_project}/projectverdeling"
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        leeg = client.get(pad, headers=headers).json()
        # B1/B2 (04-09): zonder opt-in is het blok leeg maar BESCHIKBAAR (actieve projecten) — geen poort meer.
        assert leeg["status"] == "geen" and leeg["beschikbaar"] is True

        antwoord = client.put(
            pad,
            headers=headers,
            json={
                "vaste_regels": [{"project_id": str(projecten["tilburg"]), "bedrag": "600.00", "hint": "rechtstreeks"}],
                "pro_rato_periode": PERIODE.isoformat(),
            },
        )
        assert antwoord.status_code == 200, antwoord.text
        body = antwoord.json()
        assert body["status"] == "voorstel" and body["compleet"] is True
        assert body["pro_rato_bedrag"] == "1400.00" and body["pro_rato_periode_label"] == "juli 2026"
        assert body["aantal_projecten_met_omzet"] == 3
        assert sum(Decimal(d["bedrag"]) for d in body["delen"]) == Decimal("2000.00")
        assert body["vaste_regels"][0]["project_naam"] == "26127 Tilburg (Heijmans)"

        te_veel = client.put(
            pad,
            headers=headers,
            json={
                "vaste_regels": [{"project_id": str(projecten["tilburg"]), "bedrag": "9999.00"}],
                "pro_rato_periode": None,
            },
        )
        assert te_veel.status_code == 200
        assert te_veel.json()["compleet"] is False and "meer vast verdeeld" in te_veel.json()["blokkade"]

        onbekend_project = client.put(
            pad,
            headers=headers,
            json={"vaste_regels": [{"project_id": str(uuid.uuid4()), "bedrag": "10.00"}], "pro_rato_periode": None},
        )
        assert onbekend_project.status_code == 422

    def test_herverdelen_zonder_signaal_422(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project
    ) -> None:
        pad = f"/administraties/{administratie_id}/documenten/{document_zonder_project}/projectverdeling/herverdelen"
        antwoord = client.post(
            pad, headers=_bearer(gescoopte_gebruiker, rol="boekhouding"), json={"reden": "omzet gewijzigd"}
        )
        assert antwoord.status_code == 422


class TestBeheerderEndpoints:
    def test_leverancier_opt_in_beheerder_only(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, admin_engine: Engine
    ) -> None:
        vendor = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                    "VALUES (:id, :aid, 'Derks', '{}')"
                ),
                {"id": vendor, "aid": administratie_id},
            )
        pad = f"/administraties/{administratie_id}/leveranciers/{vendor}/projectverdeling-instelling"
        assert (
            client.put(
                pad, headers=_bearer(gescoopte_gebruiker, rol="boekhouding"), json={"ingeschakeld": True}
            ).status_code
            == 403
        )
        ok = client.put(pad, headers=_bearer(beheerder_id, rol="beheerder"), json={"ingeschakeld": True})
        assert ok.status_code == 200 and ok.json() == {
            "vendor_id": str(vendor),
            "naam": "Derks",
            "projectverdeling_pro_rato": True,
        }
        lijst = client.get(
            f"/administraties/{administratie_id}/leveranciers-projectverdeling",
            headers=_bearer(beheerder_id, rol="beheerder"),
        )
        assert lijst.status_code == 200 and lijst.json()["leveranciers"][0]["projectverdeling_pro_rato"] is True
        assert (
            client.get(
                f"/administraties/{administratie_id}/leveranciers-projectverdeling",
                headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
            ).status_code
            == 403
        )

    def test_instellingen_get_put(self, administratie_id, beheerder_id, gescoopte_gebruiker) -> None:
        pad = f"/administraties/{administratie_id}/projectverdeling-instellingen"
        assert client.get(pad, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code == 403
        stand = client.get(pad, headers=_bearer(beheerder_id, rol="beheerder"))
        assert stand.status_code == 200 and stand.json() == {"drempel_pct": "5.00", "wachtweken": 4}
        nieuw = client.put(
            pad, headers=_bearer(beheerder_id, rol="beheerder"), json={"drempel_pct": "7.5", "wachtweken": 6}
        )
        assert nieuw.status_code == 200 and nieuw.json() == {"drempel_pct": "7.5", "wachtweken": 6}
        assert (
            client.put(pad, headers=_bearer(beheerder_id, rol="beheerder"), json={"wachtweken": 99}).status_code == 422
        )


class TestKantoorbreed:
    def test_hercontrole_signalen_leeg(self, gescoopte_gebruiker, administratie_id) -> None:
        antwoord = client.get(
            "/projectverdeling/hercontrole-signalen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert antwoord.status_code == 200
        assert antwoord.json() == {
            "rijen": [],
            "totaal": 0,
            "pagina": 1,
            "per_pagina": 25,
            "administraties": 0,
            "tellers": {"signalen": 0, "administraties": 0},
        }

    def _signaleer(self, administratie_id, projecten, admin_engine, vendor_id) -> None:
        """Nagekomen factuur Venlo (+ € 1.000) → 7,73 % > 5 % drempel (zelfde casus als TestHercontrole)."""
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO boekhouding.vendor_cache (id, administratie_id, naam, brondata) "
                    "VALUES (:id, :aid, 'Floorbeheer B.V.', '{}')"
                ),
                {"id": vendor_id, "aid": administratie_id},
            )
        seed_omzet(admin_engine, administratie_id, projecten["venlo"], "1000.00", date(2026, 7, 20))
        hercontrole.herbereken_administratie(administratie_id=administratie_id, vandaag=date(2026, 9, 2), forceer=True)

    def test_signalen_rij_velden_facet_en_zoekterm(
        self, geboekt_met_verdeling, administratie_id, beheerder_id, projecten, admin_engine, vendor_id  # noqa: F811
    ) -> None:
        """Inzicht › Projectverdeling (blok B 06-09): de rij draagt alles wat het scherm nodig heeft (leverancier,
        referentie, totaal, geboekt_op, delen oud → nieuw mét projectnaam); facet + zoekterm versmallen de selectie
        terwijl de kantoorbrede tellers gelijk blijven."""
        document_id, _ = geboekt_met_verdeling
        self._signaleer(administratie_id, projecten, admin_engine, vendor_id)
        headers = _bearer(beheerder_id, rol="beheerder")

        alles = client.get("/projectverdeling/hercontrole-signalen", headers=headers)
        assert alles.status_code == 200, alles.text
        body = alles.json()
        assert body["totaal"] == 1 and body["administraties"] == 1
        assert body["tellers"] == {"signalen": 1, "administraties": 1}
        [rij] = body["rijen"]
        assert rij["document_id"] == str(document_id)
        assert rij["leverancier"] == "Floorbeheer B.V." and rij["referentie"] == "FB-2026-0731"
        assert rij["totaalbedrag"] == "2420.00" and rij["geboekt_op"] is not None
        assert rij["afwijking_pct"] == "7.73" and rij["drempel_pct"] == "5.00"
        assert sum(Decimal(d["bedrag"]) for d in rij["delen_oud"]) == Decimal("2000.00")
        assert sum(Decimal(d["bedrag"]) for d in rij["delen_nieuw"]) == Decimal("2000.00")
        venlo_oud = [d for d in rij["delen_oud"] if d["project_id"] == str(projecten["venlo"])]
        venlo_nieuw = [d for d in rij["delen_nieuw"] if d["project_id"] == str(projecten["venlo"])]
        assert venlo_oud[0]["bedrag"] == "210.00" and venlo_nieuw[0]["bedrag"] == "318.18"
        assert venlo_nieuw[0]["project_naam"] == "26131 Venlo (Dura)"
        # Vaste regel (Tilburg € 600) staat in beide kanten ongewijzigd.
        assert [d["bedrag"] for d in rij["delen_nieuw"] if d["wijze"] == "vast"] == ["600.00"]

        # Facet administratie: een andere administratie = lege selectie, tellers blijven kantoorbreed.
        andere = client.get(
            f"/projectverdeling/hercontrole-signalen?administratie_id={uuid.uuid4()}", headers=headers
        ).json()
        assert andere["totaal"] == 0 and andere["rijen"] == [] and andere["tellers"]["signalen"] == 1
        eigen = client.get(
            f"/projectverdeling/hercontrole-signalen?administratie_id={administratie_id}", headers=headers
        ).json()
        assert eigen["totaal"] == 1

        # Zoekterm op leverancier / referentie (hoofdletterongevoelig); geen treffer = leeg mét tellers.
        for term in ("floorbeheer", "fb-2026", "FLOORBEHEER-2026-07"):
            treffer = client.get(f"/projectverdeling/hercontrole-signalen?q={term}", headers=headers).json()
            assert treffer["totaal"] == 1, term
        niets = client.get("/projectverdeling/hercontrole-signalen?q=bestaat-niet", headers=headers).json()
        assert niets["totaal"] == 0 and niets["tellers"] == {"signalen": 1, "administraties": 1}

    def test_signalen_rls_echte_niet_beheerder_met_en_zonder_scope(
        self, geboekt_met_verdeling, administratie_id, gescoopte_gebruiker, projecten, admin_engine, vendor_id  # noqa: F811
    ) -> None:
        """RLS-les: het groene pad is een ECHTE niet-Beheerder MÉT scope (ziet het signaal); een collega zonder
        scope op de administratie ziet niets — ook de kantoorbrede tellers zijn dan 0."""
        self._signaleer(administratie_id, projecten, admin_engine, vendor_id)
        met_scope = client.get(
            "/projectverdeling/hercontrole-signalen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert met_scope.status_code == 200
        assert met_scope.json()["totaal"] == 1 and met_scope.json()["tellers"]["signalen"] == 1
        assert met_scope.json()["rijen"][0]["administratie_id"] == str(administratie_id)

        zonder_scope = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                    "VALUES (:id, 'Collega zonder scope', :mail, 'boekhouding', 'actief')"
                ),
                {"id": zonder_scope, "mail": f"{zonder_scope}@test.local"},
            )
        leeg = client.get("/projectverdeling/hercontrole-signalen", headers=_bearer(zonder_scope, rol="boekhouding"))
        assert leeg.status_code == 200
        assert leeg.json()["totaal"] == 0 and leeg.json()["tellers"] == {"signalen": 0, "administraties": 0}

    def test_lijst_item_draagt_afwijking_veld(
        self, administratie_id, gescoopte_gebruiker, document_zonder_project
    ) -> None:
        antwoord = client.get(
            f"/administraties/{administratie_id}/documenten", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")
        )
        assert antwoord.status_code == 200
        [item] = [d for d in antwoord.json()["documenten"] if d["id"] == str(document_zonder_project)]
        assert item["projectverdeling_afwijking_pct"] is None
