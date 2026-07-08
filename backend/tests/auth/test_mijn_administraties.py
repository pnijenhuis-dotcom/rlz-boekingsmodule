from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.auth import service
from app.main import app
from app.security.tokens import create_access_token

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def test_beheerder_ziet_alle_administraties(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    andere_administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere', :rlz)"),
            {"id": andere_administratie_id, "rlz": f"rlz-{andere_administratie_id}"},
        )

    resp = client.get("/auth/administraties", headers=_bearer(beheerder_id, rol="beheerder"))
    assert resp.status_code == 200, resp.text
    ids = {a["id"] for a in resp.json()["administraties"]}
    assert {str(administratie_id), str(andere_administratie_id)} <= ids


def _actieve_gebruiker_zonder_scope(admin_engine: Engine) -> uuid.UUID:
    """Rechtstreeks als actief aangemaakt (zoals beheerder_id/gescoopte_gebruiker) — de
    uitnodig-/TOTP-flow is hier niet de kern van de test."""
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Geen scope', :mail, 'boekhouding', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    return gid


def test_gebruiker_ziet_alleen_eigen_administraties(
    beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
) -> None:
    """Regressietest voor migratie 0007: zonder de RLS-uitbreiding (lees je eigen
    gebruiker_administratie-rijen) zou dit een lege lijst geven — een sessie is maar op één
    administratie tegelijk gescoped, dus de oude policy liet niet-Beheerders nooit hun volledige
    scope in één keer zien."""
    doel = _actieve_gebruiker_zonder_scope(admin_engine)

    andere_administratie_id = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Onzichtbaar', :rlz)"),
            {"id": andere_administratie_id, "rlz": f"rlz-{andere_administratie_id}"},
        )
    service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=doel, administratie_id=administratie_id)

    resp = client.get("/auth/administraties", headers=_bearer(doel, rol="boekhouding"))
    assert resp.status_code == 200, resp.text
    administraties = resp.json()["administraties"]
    assert [a["id"] for a in administraties] == [str(administratie_id)]


def test_gebruiker_zonder_scope_ziet_lege_lijst(admin_engine: Engine) -> None:
    doel = _actieve_gebruiker_zonder_scope(admin_engine)

    resp = client.get("/auth/administraties", headers=_bearer(doel, rol="boekhouding"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["administraties"] == []
