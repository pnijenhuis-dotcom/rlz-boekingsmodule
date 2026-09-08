"""Blok 1 spoedrun 08-09 — wachtrij accordeur-app 10 s (live: 9,8–11,5 s voor Peter; de app
breekt af op 10 s). Wortel: N+1 in `wachtrij_voor_accordeur` (per open ronde 8–12 losse lookups,
per item twee eigen sessies, staande-regel-check kwadratisch). Deze tests borgen de herbouw:

1. het aantal SQL-statements schaalt NIET met het aantal rondes (3 administraties × 1 ronde
   = 3 administraties × 5 rondes) en blijft onder de gedocumenteerde bovengrens per administratie;
2. de aan-de-beurt-definitie van wachtrij en teller/meldingen blijft één bron;
3. de payload van de lijst-DTO blijft compact (geen PDF/regels/review-detail).
"""

from __future__ import annotations

import json
import uuid
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, event, text

from app.accordering import service
from app.auth import service as auth_service
from app.auth import voorwaarden
from app.db import session as db_session
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.accordering.conftest import maak_accordeur, maak_klaar_document, zet_schema
from tests.accordering.test_service import _laag as _laag_input
from tests.doorbelasting.conftest import (  # noqa: F401 — fixtures via import geregistreerd
    doel_administratie_id,
    doorbelasting_aan,
    instelling_compleet,
)

client = TestClient(app)


def _maak_administratie(admin_engine: Engine, naam: str) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, :naam, :rlz)"),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}"},
        )
    return aid


class _Teller:
    """Telt élk statement dat via de service-engine naar Postgres gaat (incl. set_config)."""

    def __init__(self) -> None:
        self.statements: list[str] = []

    def __call__(self, conn, cursor, statement, parameters, context, executemany) -> None:  # noqa: ANN001
        self.statements.append(statement)

    def __enter__(self) -> _Teller:
        event.listen(db_session.engine, "before_cursor_execute", self)
        return self

    def __exit__(self, *exc: object) -> None:
        event.remove(db_session.engine, "before_cursor_execute", self)


@pytest.fixture
def drie_administraties(administratie_id: uuid.UUID, admin_engine: Engine) -> list[uuid.UUID]:
    return [
        administratie_id,
        _maak_administratie(admin_engine, "Tweede B.V."),
        _maak_administratie(admin_engine, "Derde B.V."),
    ]


@pytest.fixture
def accordeur_overal(
    admin_engine: Engine, beheerder_id: uuid.UUID, drie_administraties: list[uuid.UUID]
) -> uuid.UUID:
    """Eén klant-accordeur met scope op alle drie de administraties (de Peter-casus in het klein)."""
    gid = maak_accordeur(admin_engine, beheerder_id, drie_administraties[0], "P. Accordeur")
    for aid in drie_administraties[1:]:
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=aid)
    return gid


def _bied_aan(
    *,
    administraties: list[uuid.UUID],
    per_administratie: int,
    accordeur: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    admin_engine: Engine,
    opslag: LokaleBestandsopslag,
) -> list[uuid.UUID]:
    documenten: list[uuid.UUID] = []
    for aid in administraties:
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=aid)
        zet_schema(administratie_id=aid, beheerder_id=beheerder_id, lagen=[_laag_input(1, accordeur)])
        for n in range(per_administratie):
            doc = maak_klaar_document(gescoopte_gebruiker, aid, admin_engine, opslag, naam=f"factuur-{n}.pdf")
            service.bied_ter_accordering_aan(
                administratie_id=aid, document_id=doc, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
            )
            documenten.append(doc)
    return documenten


def _tel(actor: uuid.UUID, administraties: list[uuid.UUID]) -> tuple[int, list[service.WachtrijItem]]:
    with _Teller() as teller:
        items = service.wachtrij_voor_accordeur(actor_id=actor, administratie_ids=administraties)
    return len(teller.statements), items


def test_querytelling_schaalt_niet_met_rondes(
    drie_administraties: list[uuid.UUID],
    accordeur_overal: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    admin_engine: Engine,
    opslag: LokaleBestandsopslag,
) -> None:
    # 1 ronde per administratie
    docs_1 = _bied_aan(
        administraties=drie_administraties,
        per_administratie=1,
        accordeur=accordeur_overal,
        beheerder_id=beheerder_id,
        gescoopte_gebruiker=gescoopte_gebruiker,
        admin_engine=admin_engine,
        opslag=opslag,
    )
    aantal_1, items_1 = _tel(accordeur_overal, drie_administraties)
    assert {i.document_id for i in items_1} == set(docs_1)

    # + 4 rondes per administratie (zelfde leverancier/bedrag → óók de staande-regel-kandidaat-
    # logica krijgt werk: eerdere rondes met dezelfde vendor bestaan nu)
    docs_5 = docs_1 + _bied_aan(
        administraties=drie_administraties,
        per_administratie=4,
        accordeur=accordeur_overal,
        beheerder_id=beheerder_id,
        gescoopte_gebruiker=gescoopte_gebruiker,
        admin_engine=admin_engine,
        opslag=opslag,
    )
    aantal_5, items_5 = _tel(accordeur_overal, drie_administraties)
    assert {i.document_id for i in items_5} == set(docs_5)
    assert len(items_5) == 15
    assert [i.aangeboden_op for i in items_5] == sorted(i.aangeboden_op for i in items_5)

    # Kern: constant per administratie, ongeacht het aantal rondes.
    print(f"\nWACHTRIJ-QUERYTELLING: 3 administraties × 1 ronde = {aantal_1}, × 5 rondes = {aantal_5} statements")
    assert aantal_5 == aantal_1, (aantal_1, aantal_5)
    assert aantal_5 <= 3 * service.WACHTRIJ_MAX_STATEMENTS_PER_ADMINISTRATIE, aantal_5

    # Een accordeur ZONDER stap in deze administraties laadt geen rondes: 3 statements per
    # administratie (2 set_config + de EXISTS-gefilterde rondes-query).
    andere = maak_accordeur(admin_engine, beheerder_id, drie_administraties[0], "Q. Ander")
    aantal_leeg, items_leeg = _tel(andere, drie_administraties)
    assert items_leeg == []
    assert aantal_leeg == 3 * 3, aantal_leeg


def test_teller_en_wachtrij_delen_de_aan_de_beurt_bron(
    drie_administraties: list[uuid.UUID],
    accordeur_overal: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    admin_engine: Engine,
    opslag: LokaleBestandsopslag,
) -> None:
    docs = _bied_aan(
        administraties=drie_administraties[:2],
        per_administratie=2,
        accordeur=accordeur_overal,
        beheerder_id=beheerder_id,
        gescoopte_gebruiker=gescoopte_gebruiker,
        admin_engine=admin_engine,
        opslag=opslag,
    )
    wachtrij = {
        i.document_id
        for i in service.wachtrij_voor_accordeur(actor_id=accordeur_overal, administratie_ids=drie_administraties)
    }
    teller: set[uuid.UUID] = set()
    for aid in drie_administraties:
        teller.update(service.documenten_aan_de_beurt(administratie_id=aid).get(accordeur_overal, []))
    assert wachtrij == teller == set(docs)
    assert service.aantallen_aan_de_beurt(administratie_id=drie_administraties[2]) == {}


def test_payload_lijst_dto_blijft_compact(
    drie_administraties: list[uuid.UUID],
    accordeur_overal: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    admin_engine: Engine,
    opslag: LokaleBestandsopslag,
) -> None:
    """1b: de lijst-DTO draagt alleen wat de kaart toont — geen PDF/base64, geen boekingsregels,
    geen doorbelasting-review of offerte-match-detail. Meting: bytes per item (json), gelogd in het
    blok-rapport (vóór/ná identiek: de DTO is niet gewijzigd; de 52 KB live = ±70 items)."""
    _bied_aan(
        administraties=drie_administraties,
        per_administratie=3,
        accordeur=accordeur_overal,
        beheerder_id=beheerder_id,
        gescoopte_gebruiker=gescoopte_gebruiker,
        admin_engine=admin_engine,
        opslag=opslag,
    )
    voorwaarden.leg_akkoord_vast(gebruiker_id=accordeur_overal)
    resp = client.get(
        "/accordering/wachtrij",
        headers={"Authorization": f"Bearer {create_access_token(accordeur_overal, rol='klant_accordeur')}"},
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["items"]) == 9
    bytes_totaal = len(resp.content)
    per_item = bytes_totaal / len(body["items"])
    print(f"\nWACHTRIJ-PAYLOAD: {bytes_totaal} bytes voor 9 items = {per_item:.0f} bytes/item")
    assert per_item < 900, per_item
    verboden = {"base64", "inhoud", "regels", "previews", "kandidaten", "pdf", "checks"}
    sleutels = set()

    def verzamel(obj: object) -> None:
        if isinstance(obj, dict):
            for k, v in obj.items():
                sleutels.add(k)
                verzamel(v)
        elif isinstance(obj, list):
            for v in obj:
                verzamel(v)

    verzamel(body)
    assert not (sleutels & verboden), sleutels & verboden
    assert json.dumps(body["items"][0]).count("null") <= 8  # géén lange staart optionele velden


# --- herstelrun "Basis eerst" 08-09, blok 1: doorbelasting-items schalen niet meer --------------------------------


def _zet_doorbelasting_klaar(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    mapping,  # noqa: ANN001
) -> None:
    from app.documenten import boekvoorstel
    from app.doorbelasting import service as doorbelasting_service
    from app.doorbelasting.service import VerdeelRegelInvoerData
    from tests.doorbelasting.conftest import DOEL_KOSTEN_LEDGER_ID

    voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    run = doorbelasting_service.start_of_haal_run(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
    )
    doorbelasting_service.sla_verdeling_op(
        administratie_id=administratie_id,
        run_id=run.id,
        actor_id=actor_id,
        regels=[
            VerdeelRegelInvoerData(
                bron_regel_id=voorstel.regels[0].id,
                mapping_id=mapping.id,
                percentage=Decimal("100"),
                doel_kosten_ledger_id=DOEL_KOSTEN_LEDGER_ID,
            )
        ],
    )


def _bied_aan_met_doorbelasting(
    *,
    administratie_id: uuid.UUID,
    aantal: int,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    admin_engine: Engine,
    opslag: LokaleBestandsopslag,
    mapping,  # noqa: ANN001
) -> list[uuid.UUID]:
    documenten: list[uuid.UUID] = []
    for n in range(aantal):
        doc = maak_klaar_document(
            gescoopte_gebruiker, administratie_id, admin_engine, opslag, naam=f"doorbelast-{n}.pdf"
        )
        _zet_doorbelasting_klaar(
            administratie_id=administratie_id, document_id=doc, actor_id=gescoopte_gebruiker, mapping=mapping
        )
        # Aanbieden toetst óók de doel-scope (A2): de Beheerder heeft scope op alles.
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=doc, actor_id=beheerder_id, actor_rol="beheerder"
        )
        documenten.append(doc)
    return documenten


def test_querytelling_doorbelasting_schaalt_niet_met_items(
    doorbelasting_aan: None,  # noqa: F811
    instelling_compleet: None,  # noqa: F811
    doel_administratie_id: uuid.UUID,  # noqa: F811
    administratie_id: uuid.UUID,
    accordeur_overal: uuid.UUID,
    beheerder_id: uuid.UUID,
    gescoopte_gebruiker: uuid.UUID,
    admin_engine: Engine,
    opslag: LokaleBestandsopslag,
) -> None:
    """Herstelrun 08-09 blok 1 — productie-nameting ná de set-based deploy: p50 6,2 s / p95 12,6 s voor Peter,
    omdat per item mét klaargezette doorbelasting `review_data` draaide (17 queries + checks-rapport; 55 van 58
    items bij Kempen Facilities). Nu: één bulk-verdeling per administratie (3 queries), dus 1 doorbelasting-item
    kost precies zoveel statements als 4 — en de kaartgegevens (naam, %, netto excl., provisie) zijn identiek
    aan wat `review_data` gaf (regressie `test_doorbelasting_in_flow`)."""
    from tests.doorbelasting.conftest import PROVISIE_KOSTEN_LEDGER_ID, maak_mapping

    auth_service.voeg_scope_toe(
        actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=administratie_id
    )
    zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag_input(1, accordeur_overal)])
    mapping = maak_mapping(
        administratie_id=administratie_id,
        actor_id=beheerder_id,
        naam="Oirschot Recreatie B.V.",
        doel_administratie_id=doel_administratie_id,
        provisie_kosten_ledger_id=PROVISIE_KOSTEN_LEDGER_ID,
    )
    docs_1 = _bied_aan_met_doorbelasting(
        administratie_id=administratie_id,
        aantal=1,
        beheerder_id=beheerder_id,
        gescoopte_gebruiker=gescoopte_gebruiker,
        admin_engine=admin_engine,
        opslag=opslag,
        mapping=mapping,
    )
    aantal_1, items_1 = _tel(accordeur_overal, [administratie_id])
    assert [i.document_id for i in items_1] == docs_1

    docs_4 = docs_1 + _bied_aan_met_doorbelasting(
        administratie_id=administratie_id,
        aantal=3,
        beheerder_id=beheerder_id,
        gescoopte_gebruiker=gescoopte_gebruiker,
        admin_engine=admin_engine,
        opslag=opslag,
        mapping=mapping,
    )
    aantal_4, items_4 = _tel(accordeur_overal, [administratie_id])
    assert {i.document_id for i in items_4} == set(docs_4)

    print(f"\nWACHTRIJ-QUERYTELLING DOORBELASTING: 1 item = {aantal_1}, 4 items = {aantal_4} statements")
    assert aantal_4 == aantal_1, (aantal_1, aantal_4)
    assert aantal_4 <= service.WACHTRIJ_MAX_STATEMENTS_PER_ADMINISTRATIE, aantal_4

    # Kaartgegevens ongewijzigd t.o.v. de oude review_data-route (naam, aandeel-%, netto excl., provisie 5 %).
    for item in items_4:
        assert item.doorbelasting is not None and len(item.doorbelasting) == 1, item
        (regel,) = item.doorbelasting
        assert regel.doelentiteit_naam == "Oirschot Recreatie B.V."
        assert regel.percentage == Decimal("100.00")
        assert regel.netto_totaal == Decimal("100.00")
        assert regel.provisie_bedrag == Decimal("5.00")
