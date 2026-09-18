# ruff: noqa: F811 — pytest-fixtures als parameters
"""Lees-only rapport `facturen-zonder-project` (18-09 avond, TODO Peter 23-08 "eerst rapport, dan beslissen").

Module-kant: een geboekte inkoopfactuur met een regel zonder project telt als bevinding, tenzij het document een BEVROREN
projectverdeling draagt (de RLZ-adapter splitst dan per project — gedekt, geen bevinding). Geboekt-door leest de jongste
GEBOEKT-overgang (`automatisch_geboekt` → "automatisch"). Aangifte-toets → route (a) storno/her-PUT bij open periode, (b)
tegenboek-pad bij ingediend, "toets nodig" zonder credential. Projectvoorstel alleen deterministisch (één bevestigde
werknummer-mapping óf één project in ≥ 3 eigen facturen; meerduidig = mens). RLZ-kant: regel zonder Project op 4xxx/7xxx,
module-documenten herkend op client-GUID. Geen write, geen RLZ-call buiten de fake."""

from __future__ import annotations

import hashlib
import uuid
from datetime import date
from decimal import Decimal
from functools import partial

from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentBron,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
)
from app.projecten import zonder_project as zp
from app.projectverdeling.models import Projectverdeling
from app.rlz.aangifte import KantToets
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.uren.conftest import maak_project


def _zet_project_verplicht(admin_engine: Engine, aid: uuid.UUID) -> None:
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE platform.administratie SET project_verplicht = true WHERE id = :id"), {"id": aid})


def _maak_geboekt(
    aid: uuid.UUID,
    actor: uuid.UUID,
    *,
    referentie: str,
    vendor_id: uuid.UUID,
    factuurdatum: date,
    regels: list[tuple[uuid.UUID | None, Decimal]],
    automatisch: bool = False,
    boek_cyclus: int = 0,
) -> uuid.UUID:
    did = uuid.uuid4()
    with scoped_session(aid, actor_id=actor) as session:
        session.add(
            Document(
                id=did,
                administratie_id=aid,
                bron=DocumentBron.UPLOAD,
                soort=DocumentSoort.INKOOPFACTUUR.value,
                bestandsnaam=f"{referentie}.pdf",
                sha256_hash=hashlib.sha256(referentie.encode()).hexdigest(),
                status=DocumentStatus.GEBOEKT,
                opslag_pad=f"test/{did}.pdf",
            )
        )
        session.flush()  # RLS-policy boekvoorstel_scope toetst via het document — dat moet eerst staan
        session.add(
            Boekvoorstel(
                document_id=did,
                vendor_id=vendor_id,
                referentie=referentie,
                factuurdatum=factuurdatum,
                totaalbedrag=sum(n for _, n in regels),
                rlz_boekstuknummer=f"RLZ-04-{referentie}",
                boek_cyclus=boek_cyclus,
            )
        )
        for i, (pid, netto) in enumerate(regels, start=1):
            session.add(
                BoekvoorstelRegel(
                    document_id=did,
                    volgnummer=i,
                    project_id=pid,
                    netto_bedrag=netto,
                    btw_bedrag=netto * Decimal("0.21"),
                )
            )
        session.add(
            DocumentGebeurtenis(
                document_id=did,
                van_status=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                naar_status=DocumentStatus.GEBOEKT,
                actor_id=actor,
                detail={"automatisch_geboekt": True, "bron": "leverancier"} if automatisch else {"backend": "rlz"},
            )
        )
    return did


def test_regel_zonder_project_is_bevinding_tenzij_gedekt_door_bevroren_verdeling(
    admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    aid, actor = administratie_id, beheerder_id
    _zet_project_verplicht(admin_engine, aid)
    p1 = maak_project(admin_engine, aid, "26001 Tilburg (Heijmans)")
    vendor = uuid.uuid4()
    zonder = _maak_geboekt(
        aid,
        actor,
        referentie="Z-1",
        vendor_id=vendor,
        factuurdatum=date(2026, 8, 3),
        regels=[(None, Decimal("100.00")), (p1, Decimal("50.00"))],
    )
    gedekt = _maak_geboekt(
        aid,
        actor,
        referentie="G-1",
        vendor_id=vendor,
        factuurdatum=date(2026, 8, 4),
        regels=[(None, Decimal("630.00"))],
        automatisch=True,
    )
    met_project = _maak_geboekt(
        aid, actor, referentie="P-1", vendor_id=vendor, factuurdatum=date(2026, 8, 5), regels=[(p1, Decimal("10.00"))]
    )
    _maak_geboekt(
        aid,
        actor,
        referentie="OUD-2025",
        vendor_id=vendor,
        factuurdatum=date(2025, 3, 1),
        regels=[(None, Decimal("1.00"))],
    )
    with scoped_session(aid, actor_id=actor) as session:
        session.add(
            Projectverdeling(
                administratie_id=aid,
                document_id=gedekt,
                status="geboekt",
                boek_cyclus=0,
                pro_rato_bedrag=Decimal("630.00"),
                verdeling=[{"project_id": str(p1), "bedrag": "630.00", "wijze": "pro_rato"}],
            )
        )
    with scoped_session(aid) as session:
        uitkomst = zp.module_kant(session, administratie_id=aid, administratie_naam="Test", jaar=2026)
    assert uitkomst.geboekt_in_module == 3, "jaarfilter: het 2025-document telt niet mee"
    assert {r.document_id for r in uitkomst.rijen} == {zonder, gedekt}
    assert met_project not in {r.document_id for r in uitkomst.rijen}
    bevinding = [r for r in uitkomst.bevindingen]
    assert [r.document_id for r in bevinding] == [zonder]
    assert bevinding[0].regelnummer == 1 and bevinding[0].aantal_regels == 2 and bevinding[0].netto == Decimal("100.00")
    assert bevinding[0].boekdatum == date(2026, 8, 3) and bevinding[0].geboekt_door == "Test-Beheerder"
    assert bevinding[0].rlz_document_id == zp.rlz_document_id_voor(zonder, 0)
    gedekte = [r for r in uitkomst.rijen if r.gedekt_door_verdeling]
    assert len(gedekte) == 1 and gedekte[0].document_id == gedekt and gedekte[0].verdeling_delen == 1
    assert gedekte[0].geboekt_door == "automatisch"
    assert uitkomst.documenten_zonder_project == 1 and uitkomst.documenten_gedekt == 1
    # zonder jaarfilter telt het 2025-document wél als bevinding
    with scoped_session(aid) as session:
        alles = zp.module_kant(session, administratie_id=aid, administratie_naam="Test", jaar=None)
    assert alles.documenten_zonder_project == 2


def test_verdeling_van_een_andere_boek_cyclus_dekt_niet(
    admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    aid, actor = administratie_id, beheerder_id
    _zet_project_verplicht(admin_engine, aid)
    p1 = maak_project(admin_engine, aid, "26002 Ede (Welling)")
    did = _maak_geboekt(
        aid,
        actor,
        referentie="C-1",
        vendor_id=uuid.uuid4(),
        factuurdatum=date(2026, 8, 3),
        regels=[(None, Decimal("100.00"))],
        boek_cyclus=1,
    )
    with scoped_session(aid, actor_id=actor) as session:
        session.add(
            Projectverdeling(
                administratie_id=aid,
                document_id=did,
                status="geboekt",
                boek_cyclus=0,
                verdeling=[{"project_id": str(p1), "bedrag": "100.00"}],
            )
        )
    with scoped_session(aid) as session:
        uitkomst = zp.module_kant(session, administratie_id=aid, administratie_naam="Test", jaar=None)
    assert uitkomst.documenten_zonder_project == 1 and uitkomst.documenten_gedekt == 0
    assert uitkomst.rijen[0].rlz_document_id == zp.rlz_document_id_voor(did, 1)


def test_routes_volgen_de_aangiftepoort_en_zonder_credential_zichtbaar_niet_toetsbaar(
    admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    aid, actor = administratie_id, beheerder_id
    _zet_project_verplicht(admin_engine, aid)
    vendor = uuid.uuid4()
    _maak_geboekt(
        aid, actor, referentie="OPEN", vendor_id=vendor, factuurdatum=date(2026, 8, 3), regels=[(None, Decimal("1.00"))]
    )
    _maak_geboekt(
        aid,
        actor,
        referentie="DICHT",
        vendor_id=vendor,
        factuurdatum=date(2026, 5, 3),
        regels=[(None, Decimal("1.00"))],
    )
    with scoped_session(aid) as session:
        uitkomst = zp.module_kant(session, administratie_id=aid, administratie_naam="Test", jaar=2026)

    def toets(datum: date, *, kant: str) -> KantToets:
        if date(2026, 4, 1) <= datum <= date(2026, 6, 30):
            return KantToets(
                kant=kant,
                toegestaan=False,
                reden="ingediend",
                periode_start=date(2026, 4, 1),
                periode_eind=date(2026, 6, 30),
            )
        return KantToets(kant=kant, toegestaan=True)

    zp.bepaal_routes(uitkomst, partial(toets, kant="inkoop"))
    per_ref = {r.referentie: r for r in uitkomst.rijen}
    assert per_ref["OPEN"].route == zp.ROUTE_STORNO and per_ref["OPEN"].aangifte == "open"
    assert (
        per_ref["DICHT"].route == zp.ROUTE_TEGENBOEK
        and per_ref["DICHT"].aangifte == "ingediend (2026-04-01 t/m 2026-06-30)"
    )
    assert uitkomst.routes == {zp.ROUTE_STORNO: 1, zp.ROUTE_TEGENBOEK: 1}
    zp.bepaal_routes(uitkomst, None, reden_niet_toetsbaar="geen RLZ-credential")
    assert all(
        r.route == zp.ROUTE_ONBEKEND and r.aangifte.startswith("niet toetsbaar (geen RLZ-credential")
        for r in uitkomst.rijen
    )
    tekst = "\n".join(zp.rapportregels(uitkomst))
    assert "BEVINDING RLZ-04-OPEN" in tekst and "project: mens nodig" in tekst and "RLZ-kant: niet gemeten" in tekst


def test_projectvoorstel_alleen_deterministisch(
    admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    aid, actor = administratie_id, beheerder_id
    _zet_project_verplicht(admin_engine, aid)
    p1 = maak_project(admin_engine, aid, "26003 Venlo (Wijnen)")
    p2 = maak_project(admin_engine, aid, "26004 Dronten (Wessels)")
    eenduidig, meerduidig, te_weinig, werknummer = uuid.uuid4(), uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    for i in range(3):
        _maak_geboekt(
            aid,
            actor,
            referentie=f"E-{i}",
            vendor_id=eenduidig,
            factuurdatum=date(2026, 7, 1 + i),
            regels=[(p1, Decimal("10.00"))],
        )
    _maak_geboekt(
        aid,
        actor,
        referentie="M-1",
        vendor_id=meerduidig,
        factuurdatum=date(2026, 7, 1),
        regels=[(p1, Decimal("10.00"))],
    )
    _maak_geboekt(
        aid,
        actor,
        referentie="M-2",
        vendor_id=meerduidig,
        factuurdatum=date(2026, 7, 2),
        regels=[(p2, Decimal("10.00"))],
    )
    _maak_geboekt(
        aid,
        actor,
        referentie="M-3",
        vendor_id=meerduidig,
        factuurdatum=date(2026, 7, 3),
        regels=[(p1, Decimal("10.00"))],
    )
    _maak_geboekt(
        aid,
        actor,
        referentie="W-1",
        vendor_id=te_weinig,
        factuurdatum=date(2026, 7, 3),
        regels=[(p1, Decimal("10.00"))],
    )
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.leverancier_werknummer (id, administratie_id, project_id, vendor_id, werknummer, bron, bevestigd, aangemaakt_door) "
                "VALUES (:id, :aid, :pid, :vid, '26097', 'factuur', true, :actor)"
            ),
            {"id": uuid.uuid4(), "aid": aid, "pid": p2, "vid": werknummer, "actor": actor},
        )
    zonder = {
        v: _maak_geboekt(
            aid,
            actor,
            referentie=f"Z-{v.hex[:6]}",
            vendor_id=v,
            factuurdatum=date(2026, 8, 1),
            regels=[(None, Decimal("5.00"))],
        )
        for v in (eenduidig, meerduidig, te_weinig, werknummer)
    }
    with scoped_session(aid) as session:
        uitkomst = zp.module_kant(session, administratie_id=aid, administratie_naam="Test", jaar=2026)
    per_doc = {r.document_id: r for r in uitkomst.rijen}
    assert per_doc[zonder[eenduidig]].voorstel is not None
    assert (
        per_doc[zonder[eenduidig]].voorstel.project_id == p1
        and per_doc[zonder[eenduidig]].voorstel.herkomst == "geheugen 3× bevestigd"
    )
    assert per_doc[zonder[meerduidig]].voorstel is None, "twee projecten in de historie = mens nodig, nooit raden"
    assert per_doc[zonder[te_weinig]].voorstel is None, "één factuur is geen geheugen (minimum 3)"
    assert per_doc[zonder[werknummer]].voorstel is not None
    assert (
        per_doc[zonder[werknummer]].voorstel.project_id == p2
        and per_doc[zonder[werknummer]].voorstel.herkomst == "werknummer-geheugen (bevestigd)"
    )


class _FakeRlz:
    """Lees-only fake: PurchaseInvoices-pagina + Lines per document; élke andere methode bestaat niet."""

    def __init__(self, docs: list[dict], lines: dict[str, list[dict]]) -> None:
        self.docs, self.lines, self.calls = docs, lines, []

    def get(self, path: str, *, params: dict | None = None) -> dict:
        self.calls.append((path, params))
        assert path == "PurchaseInvoices"
        return {"value": self.docs}

    def get_lines(self, entity_path: str, entity_id, *, expand: str = "Account,Project") -> list[dict]:
        return self.lines.get(str(entity_id), [])


def test_rlz_kant_telt_kostenregels_zonder_project_en_herkent_module_documenten(
    admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID
) -> None:
    aid, actor = administratie_id, beheerder_id
    _zet_project_verplicht(admin_engine, aid)
    did = _maak_geboekt(
        aid,
        actor,
        referentie="MOD-1",
        vendor_id=uuid.uuid4(),
        factuurdatum=date(2026, 8, 3),
        regels=[(None, Decimal("100.00"))],
    )
    with scoped_session(aid) as session:
        uitkomst = zp.module_kant(session, administratie_id=aid, administratie_naam="Test", jaar=2026)
    module_rlz = zp.rlz_document_id_voor(did, 0)
    oud = uuid.uuid4()
    concept = uuid.uuid4()
    fake = _FakeRlz(
        docs=[
            {
                "id": str(module_rlz),
                "Status": 2,
                "ReceiptNumber": "RLZ-04-1",
                "Reference": "MOD-1",
                "Date": "2026-08-03T00:00:00",
                "BookDate": "2026-08-03T00:00:00",
            },
            {
                "id": str(oud),
                "Status": 3,
                "ReceiptNumber": "RLZ-04-0",
                "Reference": "OUD",
                "Date": "2026-02-01T00:00:00",
                "BookDate": "2026-02-01T00:00:00",
            },
            {
                "id": str(concept),
                "Status": 1,
                "ReceiptNumber": "RLZ-04-9",
                "Reference": "CONCEPT",
                "Date": "2026-08-01T00:00:00",
            },
        ],
        lines={
            str(module_rlz): [
                {
                    "id": str(uuid.uuid4()),
                    "Account": {"Code": "4499", "Name": "Overige"},
                    "Project": None,
                    "NetAmount": 100.0,
                    "TaxAmount": 21.0,
                }
            ],
            str(oud): [
                {
                    "id": str(uuid.uuid4()),
                    "Account": {"Code": "7000", "Name": "Inkoop"},
                    "NetAmount": 5.0,
                    "TaxAmount": 1.05,
                },
                {"id": str(uuid.uuid4()), "Account": {"Code": "1600", "Name": "Crediteuren"}, "NetAmount": -5.0},
                {
                    "id": str(uuid.uuid4()),
                    "Account": {"Code": "4000"},
                    "Project": {"id": str(uuid.uuid4())},
                    "NetAmount": 9.0,
                },
            ],
            str(concept): [{"id": str(uuid.uuid4()), "Account": {"Code": "4000"}, "NetAmount": 1.0}],
        },
    )
    zp.rlz_kant(uitkomst, fake, jaar=2026)
    assert uitkomst.rlz_documenten_gelezen == 2, "concept (Status 1) telt niet"
    assert uitkomst.rlz_documenten_zonder_project == 2 and uitkomst.rlz_alleen == 1
    van_module = [r for r in uitkomst.rlz_rijen if r.van_module]
    assert (
        len(van_module) == 1
        and van_module[0].rlz_document_id == module_rlz
        and van_module[0].grootboek == "4499 Overige"
    )
    oude = [r for r in uitkomst.rlz_rijen if not r.van_module]
    assert len(oude) == 1 and oude[0].netto == Decimal("5.0") and oude[0].boekdatum == date(2026, 2, 1)
    assert fake.calls[0][1]["$filter"] == "Date ge 2026-01-01"
    tekst = "\n".join(zp.rapportregels(uitkomst))
    assert (
        "RLZ-kant: 2 geboekte PurchaseInvoices gelezen (0 leesfouten), 2 documenten mét kostenregel zonder Project, waarvan 1 niet"
        in tekst
    )


def test_is_kostenregel_zonder_project_raadt_nooit() -> None:
    assert zp.is_kostenregel_zonder_project({"Account": {"Code": "4499"}})
    assert zp.is_kostenregel_zonder_project({"Account": {"Number": "7001"}, "Project": None})
    assert not zp.is_kostenregel_zonder_project({"Account": {"Code": "4499"}, "Project": {"id": str(uuid.uuid4())}})
    assert not zp.is_kostenregel_zonder_project({"Account": {"Code": "1600"}})
    assert not zp.is_kostenregel_zonder_project({"Account": {"id": "abc"}}), "zonder Code geen oordeel"
    assert not zp.is_kostenregel_zonder_project({})


def test_cli_facturen_zonder_project_vereist_een_keuze_en_draait_lees_only(
    admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, capsys, monkeypatch
) -> None:
    import argparse

    from app.projecten import cli_cmd
    from app.rlz.credentials import GeenRlzCredentials

    aid, actor = administratie_id, beheerder_id
    _zet_project_verplicht(admin_engine, aid)
    _maak_geboekt(
        aid,
        actor,
        referentie="CLI-1",
        vendor_id=uuid.uuid4(),
        factuurdatum=date(2026, 8, 3),
        regels=[(None, Decimal("100.00"))],
    )
    monkeypatch.setattr(
        "app.rlz.credentials.client_voor_rlz_admin_id",
        lambda rlz_admin_id: (_ for _ in ()).throw(GeenRlzCredentials("test: geen login")),
    )
    rc = cli_cmd.run_projecten(
        argparse.Namespace(
            commando="facturen-zonder-project", administratie=None, alle_projectverplicht=False, jaar=None, rlz=False
        )
    )
    assert rc == 2
    rc = cli_cmd.run_projecten(
        argparse.Namespace(
            commando="facturen-zonder-project",
            administratie=str(aid),
            alle_projectverplicht=False,
            jaar=2026,
            rlz=False,
        )
    )
    assert rc == 0
    uit = capsys.readouterr().out
    assert "1 zonder project (bevinding)" in uit and "niet toetsbaar (geen RLZ-credential" in uit and "LEES-ONLY" in uit
    assert "Totaal: 1 document(en) zonder project" in uit
    # --rlz zonder --jaar = 2 (begrensd lezen)
    rc = cli_cmd.run_projecten(
        argparse.Namespace(
            commando="facturen-zonder-project", administratie=str(aid), alle_projectverplicht=False, jaar=None, rlz=True
        )
    )
    assert rc == 2
