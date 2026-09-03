"""Adapter-registry (besluit 0016 §2): `backend_voor(administratie_id)` leest de routeringssleutel,
`inkoop_port_voor(...)` levert de adapter. De RLZ-client wordt via een factory van de aanroeper
geopend (boeken.py::_rlz_client_voor) zodat de bestaande test-seam `boeken.client_voor_rlz_admin_id`
blijft werken; de Odoo-adapter opent zijn eigen verbinding uit de credential-store."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from typing import TYPE_CHECKING

from app.backends.port import Backend, InkoopPort
from app.db.models import Administratie
from app.db.session import scoped_session

if TYPE_CHECKING:
    from app.rlz.client import RlzClient


class OnbekendeBackend(Exception):
    """`boekhoud_backend` draagt een waarde zonder adapter — fail-loud, nooit stil RLZ kiezen."""


def backend_voor(administratie_id: uuid.UUID) -> Backend:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise OnbekendeBackend(f"Onbekende administratie: {administratie_id}")
        sleutel = administratie.boekhoud_backend
    try:
        return Backend(sleutel)
    except ValueError as exc:
        raise OnbekendeBackend(
            f"Administratie {administratie_id} heeft onbekende boekhoud-backend {sleutel!r}"
        ) from exc


def inkoop_port_voor(administratie_id: uuid.UUID, *, rlz_client_factory: Callable[[], RlzClient]) -> InkoopPort:
    backend = backend_voor(administratie_id)
    if backend is Backend.RLZ:
        from app.backends.rlz_inkoop import RlzInkoopPort

        return RlzInkoopPort(rlz_client_factory())
    if backend is Backend.ODOO:
        from app.odoo.inkoop import OdooInkoopPort

        return OdooInkoopPort.voor(administratie_id)
    raise OnbekendeBackend(f"Geen inkoop-adapter voor backend {backend}")


def standaard_regels_samenvoegen(administratie_id: uuid.UUID) -> bool:
    """Capability: de default voor "regels samenvoegen tot één boekingsregel" zolang er geen
    leverancier-voorkeur is. RLZ: AAN (fix 3, 2026-07-10). Odoo: UIT — eis Peter 03-09 (Jarvis/MI):
    regelniveau-data (product, aantal, prijs, project) moet in Odoo landen, en dat kan alleen per regel.
    De leverancier-voorkeur wint altijd van deze default."""
    return backend_voor(administratie_id) is not Backend.ODOO


def backend_label(backend: Backend) -> str:
    return {"rlz": "RLZ", "odoo": "Odoo"}[backend.value]
