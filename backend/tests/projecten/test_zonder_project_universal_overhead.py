# ruff: noqa: F811 — pytest-fixtures als parameters
"""Capture Peter 21-09 — Universal Steigerbouw: overhead blijft via de omzetsleutel over de actieve projecten, GÉÉN
OVH-project ("Universal moet juist overhead verdelen over projecten, zo houden"; BESLISSINGEN "UNIVERSAL —
OVERHEAD VIA DE OMZETSLEUTEL, GEEN OVH-PROJECT (Peter 21-09)"). Regel verplichtingen-projecten 1 ("overhead →
intern OVH-project") is voor Universal bewust NIET van toepassing.

Guard: het lees-only rapport `facturen-zonder-project` telt Universal-overhead — een geboekte inkoopfactuur
zonder project mét een BEVROREN pro-rato-projectverdeling over de actieve projecten (het 19-09-patroon: DCTE
4499, Floor Beheer 4003, Kader 4606) — NIET als bevinding; het ontbreken van een OVH-project is geen bevinding
en geen voorstel. Tegenproef: dezelfde factuur zónder verdeling is wél een bevinding (de dekking komt uit de
verdeling, niet uit een naam)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine

from app.db.session import scoped_session
from app.projecten import zonder_project as zp
from app.projectverdeling.models import Projectverdeling
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.projecten.test_zonder_project import _maak_geboekt, _zet_project_verplicht
from tests.uren.conftest import maak_project

OVERHEAD_UNIVERSAL_19_09 = (
    ("DCTE-4499", Decimal("599.32")),
    ("FLOOR-4003", Decimal("11000.00")),
    ("KADER-4606", Decimal("630.00")),
)


def test_universal_overhead_via_omzetsleutel_is_geen_bevinding_en_vergt_geen_ovh_project(
    admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    aid, actor = administratie_id, beheerder_id
    _zet_project_verplicht(admin_engine, aid)
    # Alleen échte projecten — bewust géén "OVH"-/"Overhead"-project (0 van 170 namen bij Universal, meting 19-09).
    p1 = maak_project(admin_engine, aid, "26127 Tilburg (Heijmans)")
    p2 = maak_project(admin_engine, aid, "26140 Apeldoorn (Kuijer)")
    vendor = uuid.uuid4()
    overhead_docs: list[uuid.UUID] = []
    with scoped_session(aid, actor_id=actor) as session:
        for referentie, netto in OVERHEAD_UNIVERSAL_19_09:
            did = _maak_geboekt(
                aid,
                actor,
                referentie=referentie,
                vendor_id=vendor,
                factuurdatum=date(2026, 8, 12),
                regels=[(None, netto)],
                automatisch=True,
            )
            overhead_docs.append(did)
            deel = (netto / 2).quantize(Decimal("0.01"))
            session.add(
                Projectverdeling(
                    administratie_id=aid,
                    document_id=did,
                    status="geboekt",
                    boek_cyclus=0,
                    pro_rato_bedrag=netto,
                    verdeling=[
                        {"project_id": str(p1), "bedrag": str(deel), "wijze": "pro_rato"},
                        {"project_id": str(p2), "bedrag": str(netto - deel), "wijze": "pro_rato"},
                    ],
                )
            )
    # Tegenproef: dezelfde soort overhead-factuur zónder bevroren verdeling is wél een bevinding.
    los = _maak_geboekt(
        aid,
        actor,
        referentie="EXACT-4410",
        vendor_id=vendor,
        factuurdatum=date(2026, 8, 13),
        regels=[(None, Decimal("31.50"))],
    )

    with scoped_session(aid) as session:
        uitkomst = zp.module_kant(
            session, administratie_id=aid, administratie_naam="Universal Steigerbouw B.V.", jaar=2026
        )

    assert {r.document_id for r in uitkomst.rijen} == {*overhead_docs, los}
    assert [r.document_id for r in uitkomst.bevindingen] == [los], (
        "overhead mét omzetsleutel-verdeling is géén bevinding"
    )
    gedekt = {r.document_id for r in uitkomst.rijen if r.gedekt_door_verdeling}
    assert gedekt == set(overhead_docs)
    assert all(r.verdeling_delen == 2 for r in uitkomst.rijen if r.gedekt_door_verdeling)
    assert uitkomst.documenten_gedekt == 3 and uitkomst.documenten_zonder_project == 1
    # Geen enkel rapportregel-woord vraagt om een OVH-project: het patroon voor Universal is de omzetsleutel.
    tekst = "\n".join(zp.rapportregels(uitkomst))
    assert "ovh" not in tekst.lower() and "overhead-project" not in tekst.lower()
    assert "3 gedekt door projectverdeling" in tekst
