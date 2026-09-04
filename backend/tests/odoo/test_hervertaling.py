# ruff: noqa: F811 — pytest-fixtures als parameters
"""Open boekvoorstellen hervertalen bij een Odoo-overstap (slotstuk 04-09, blok C1; migratie 0112;
`app/odoo/hervertaling.py`): grootboek/btw/project van OPEN documenten via de mapping vertaald mét spoor per veld,
onvertaalbaar = veld leeg mét reden, terminale documenten ongemoeid, audit mét tellingen, DTO draagt het spoor en
een PUT door de mens wist het (bewust)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.boekvoorstel import BoekvoorstelRegelData
from app.documenten.models import BoekvoorstelRegel
from app.documenten.storage import LokaleBestandsopslag
from app.odoo import hervertaling
from app.odoo.ids import odoo_uuid
from app.odoo.mapping import RekeningMapping
from app.odoo.models import OdooRekeningMapping
from app.sync.models import ProjectCache, TaxRateCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker, opslag  # noqa: F401

RLZ_GB = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004808")
RLZ_GB_ZONDER = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004999")  # niet in de mapping
RLZ_BTW = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000021")
RLZ_PROJECT = uuid.UUID("dddddddd-0000-0000-0000-000000026127")
ODOO_GB = odoo_uuid(1, "account.account", 11)
ODOO_BTW = odoo_uuid(1, "account.tax", 21)
ODOO_PROJECT = odoo_uuid(1, "account.analytic.account", 5)


@dataclass(frozen=True)
class _MappingMetProject(RekeningMapping):
    """Blok B voegt `project` toe aan RekeningMapping — hier gesimuleerd zodat deze test niet op B wacht."""

    project: dict[uuid.UUID, uuid.UUID] = field(default_factory=dict)


def _seed_caches(aid: uuid.UUID, actor: uuid.UUID) -> None:
    with scoped_session(aid, actor_id=actor) as session:
        session.add_all(
            [
                Grootboekrekening(
                    ledger_id=RLZ_GB,
                    administratie_id=aid,
                    code="4808",
                    naam="Huur materieel",
                    soort=2,
                    is_totaalrekening=False,
                ),  # fmt: skip
                Grootboekrekening(
                    ledger_id=ODOO_GB,
                    administratie_id=aid,
                    code="480800",
                    naam="Huur materieel (Odoo)",
                    soort=2,
                    is_totaalrekening=False,
                ),  # fmt: skip
                TaxRateCache(
                    id=RLZ_BTW, administratie_id=aid, naam="NL, Hoog Tarief", percentage=Decimal("0.21"), brondata={}
                ),  # fmt: skip
                TaxRateCache(id=ODOO_BTW, administratie_id=aid, naam="21%", percentage=Decimal("0.21"), brondata={}),
                ProjectCache(id=RLZ_PROJECT, administratie_id=aid, naam="26127 Tilburg (Heijmans)", brondata={}),
                ProjectCache(
                    id=ODOO_PROJECT, administratie_id=aid, naam="[26127] 26127 Tilburg (Heijmans)", brondata={}
                ),  # fmt: skip
            ]
        )


def _document_met_regels(
    aid: uuid.UUID, actor: uuid.UUID, opslag: LokaleBestandsopslag, *, naam: str, regels: list[BoekvoorstelRegelData]
) -> uuid.UUID:
    r = service.upload_document(
        administratie_id=aid, bestandsnaam=naam, inhoud=b"%PDF-1.4 " + naam.encode(), actor_id=actor, opslag=opslag
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=aid,
        document_id=r.document_id,
        actor_id=actor,
        vendor_id=uuid.uuid4(),
        referentie=f"F-{naam}",
        factuurdatum=date(2026, 8, 20),
        totaalbedrag=Decimal("121.00"),
        regels=regels,
    )
    return r.document_id


def _regel(gb=RLZ_GB, btw=RLZ_BTW, project=RLZ_PROJECT, oms="Diesel") -> BoekvoorstelRegelData:
    return BoekvoorstelRegelData(
        ledger_id=gb, taxrate_id=btw, project_id=project, netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"), omschrijving=oms,
    )  # fmt: skip


def _regels_db(aid: uuid.UUID, document_id: uuid.UUID) -> list[BoekvoorstelRegel]:
    with scoped_session(aid) as session:
        rijen = session.query(BoekvoorstelRegel).filter_by(document_id=document_id).order_by(
            BoekvoorstelRegel.volgnummer
        ).all()  # fmt: skip
        for r in rijen:
            session.expunge(r)
        return rijen


def _audit(admin_engine: Engine, aid: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            dict(r)
            for r in conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'odoo_open_voorstellen_hervertaald' "
                    "AND record_id = :id ORDER BY tijdstip"
                ),
                {"id": aid},
            )
            .mappings()
            .all()
        ]


class TestHervertaling:
    def test_gb_btw_project_vertaald_met_spoor_en_audit(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        _seed_caches(administratie_id, beheerder_id)
        doc = _document_met_regels(
            administratie_id, gescoopte_gebruiker, opslag, naam="open.pdf", regels=[_regel(), _regel(oms="Olie")]
        )
        mapping = _MappingMetProject(
            grootboek={RLZ_GB: ODOO_GB}, btw={RLZ_BTW: ODOO_BTW}, project={RLZ_PROJECT: ODOO_PROJECT}
        )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            res = hervertaling.hervertaal_open_boekvoorstellen(
                session, administratie_id=administratie_id, mapping=mapping, actor_id=beheerder_id
            )
        assert res == hervertaling.HervertaalResultaat(
            documenten=1, regels=2, vertaald={"grootboek": 2, "btw": 2, "project": 2}, leeg={}
        )
        for regel in _regels_db(administratie_id, doc):
            assert (regel.ledger_id, regel.taxrate_id, regel.project_id) == (ODOO_GB, ODOO_BTW, ODOO_PROJECT)
            spoor = regel.overstap_vertaling
            assert spoor is not None and spoor["op"]
            assert spoor["grootboek"] == {
                "van_id": str(RLZ_GB), "van_code": "4808", "van_naam": "Huur materieel",
                "naar_id": str(ODOO_GB), "naar_code": "480800", "naar_naam": "Huur materieel (Odoo)",
            }  # fmt: skip
            assert spoor["btw"]["van_naam"] == "NL, Hoog Tarief" and spoor["btw"]["naar_naam"] == "21%"
            assert spoor["btw"]["naar_id"] == str(ODOO_BTW) and spoor["btw"]["van_code"] is None
            assert spoor["project"]["van_naam"] == "26127 Tilburg (Heijmans)"
            assert spoor["project"]["naar_naam"] == "[26127] 26127 Tilburg (Heijmans)"
        [audit] = _audit(admin_engine, administratie_id)
        assert audit["nieuwe_waarde"]["documenten"] == 1 and audit["nieuwe_waarde"]["regels"] == 2
        assert audit["nieuwe_waarde"]["vertaald"] == {"grootboek": 2, "btw": 2, "project": 2}
        assert audit["nieuwe_waarde"]["mapping"] == {"grootboek": 1, "btw": 1, "project": 1}

    def test_onvertaalbaar_veld_leeg_met_reden_en_zonder_project_attribuut(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        """Mapping zónder `project`-veld (blok B nog niet aanwezig) én een grootboek buiten de mapping: beide velden
        worden LEEG gelaten mét reden — nooit een RLZ-id stil laten staan, nooit gokken."""
        _seed_caches(administratie_id, beheerder_id)
        doc = _document_met_regels(
            administratie_id, gescoopte_gebruiker, opslag, naam="deels.pdf", regels=[_regel(gb=RLZ_GB_ZONDER)]
        )
        mapping = RekeningMapping(grootboek={RLZ_GB: ODOO_GB}, btw={RLZ_BTW: ODOO_BTW})
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            res = hervertaling.hervertaal_open_boekvoorstellen(
                session, administratie_id=administratie_id, mapping=mapping, actor_id=beheerder_id
            )
        assert res.documenten == 1 and res.regels == 1
        assert res.vertaald == {"btw": 1} and res.leeg == {"grootboek": 1, "project": 1}
        [regel] = _regels_db(administratie_id, doc)
        assert regel.ledger_id is None and regel.project_id is None and regel.taxrate_id == ODOO_BTW
        assert regel.overstap_vertaling["grootboek"] == {
            "van_id": str(RLZ_GB_ZONDER), "van_code": None, "van_naam": None,  # niet (meer) in de cache
            "naar_id": None, "reden": hervertaling.REDEN_GEEN_TEGENHANGER,
        }  # fmt: skip
        assert regel.overstap_vertaling["project"]["naar_id"] is None
        assert regel.overstap_vertaling["project"]["van_naam"] == "26127 Tilburg (Heijmans)"

    def test_namen_uit_mapping_rijen_als_de_odoo_cache_nog_leeg_is(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag
    ) -> None:
        """Ín de overstap-transactie is de Odoo-sync nog niet gedraaid: de codes/namen van de Odoo-kant komen dan uit
        de (in dezelfde sessie geschreven) mapping-rijen van 0111."""
        doc = _document_met_regels(
            administratie_id, gescoopte_gebruiker, opslag, naam="mapping.pdf", regels=[_regel(project=None)]
        )
        mapping = RekeningMapping(grootboek={RLZ_GB: ODOO_GB}, btw={RLZ_BTW: ODOO_BTW})
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(
                OdooRekeningMapping(
                    administratie_id=administratie_id,
                    soort="grootboek",
                    rlz_id=RLZ_GB,
                    rlz_code="4808",
                    rlz_naam="Huur materieel",
                    odoo_lokaal_id=ODOO_GB,
                    odoo_id=11,
                    odoo_code="480800",
                    odoo_naam="Huur materieel (Odoo)",
                    bron="code_verlengd",
                    versie=1,
                    bevestigd_door=beheerder_id,
                )  # fmt: skip
            )
            session.add(
                OdooRekeningMapping(
                    administratie_id=administratie_id,
                    soort="btw",
                    rlz_id=RLZ_BTW,
                    rlz_code=None,
                    rlz_naam="NL, Hoog Tarief",
                    odoo_lokaal_id=ODOO_BTW,
                    odoo_id=21,
                    odoo_code=None,
                    odoo_naam="21%",
                    bron="tarief",
                    versie=1,
                    bevestigd_door=beheerder_id,
                )  # fmt: skip
            )
            res = hervertaling.hervertaal_open_boekvoorstellen(
                session, administratie_id=administratie_id, mapping=mapping, actor_id=beheerder_id
            )
        assert res.vertaald == {"grootboek": 1, "btw": 1} and res.leeg == {}
        [regel] = _regels_db(administratie_id, doc)
        assert regel.overstap_vertaling["grootboek"]["naar_code"] == "480800"
        assert regel.overstap_vertaling["grootboek"]["van_naam"] == "Huur materieel"
        assert regel.overstap_vertaling["btw"]["naar_naam"] == "21%"
        assert "project" not in regel.overstap_vertaling  # veld was leeg → niet geraakt

    def test_terminale_documenten_ongemoeid_en_herhaalde_aanroep_idempotent(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag, admin_engine: Engine
    ) -> None:
        _seed_caches(administratie_id, beheerder_id)
        open_doc = _document_met_regels(administratie_id, gescoopte_gebruiker, opslag, naam="o.pdf", regels=[_regel()])
        geboekt = _document_met_regels(administratie_id, gescoopte_gebruiker, opslag, naam="g.pdf", regels=[_regel()])
        afgewezen = _document_met_regels(administratie_id, gescoopte_gebruiker, opslag, naam="a.pdf", regels=[_regel()])
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": geboekt})
            conn.execute(text("UPDATE boekhouding.document SET status = 'afgewezen' WHERE id = :id"), {"id": afgewezen})
        mapping = _MappingMetProject(
            grootboek={RLZ_GB: ODOO_GB}, btw={RLZ_BTW: ODOO_BTW}, project={RLZ_PROJECT: ODOO_PROJECT}
        )
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            res = hervertaling.hervertaal_open_boekvoorstellen(
                session, administratie_id=administratie_id, mapping=mapping, actor_id=beheerder_id
            )
        assert res.documenten == 1 and res.regels == 1
        for terminaal in (geboekt, afgewezen):
            [regel] = _regels_db(administratie_id, terminaal)
            assert regel.ledger_id == RLZ_GB and regel.overstap_vertaling is None  # historie blijft RLZ
        [regel] = _regels_db(administratie_id, open_doc)
        assert regel.ledger_id == ODOO_GB
        # Tweede aanroep: alles draagt al Odoo-waarden → niets geraakt, wél een (tweede) audit-event.
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            res2 = hervertaling.hervertaal_open_boekvoorstellen(
                session, administratie_id=administratie_id, mapping=mapping, actor_id=beheerder_id
            )
        assert res2 == hervertaling.HervertaalResultaat(documenten=0, regels=0, vertaald={}, leeg={})
        assert len(_audit(admin_engine, administratie_id)) == 2
        [regel] = _regels_db(administratie_id, open_doc)
        assert regel.overstap_vertaling["grootboek"]["van_id"] == str(RLZ_GB)  # spoor van de eerste keer intact

    def test_lege_administratie_tellingen_nul_met_audit(self, administratie_id, beheerder_id, admin_engine) -> None:
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            res = hervertaling.hervertaal_open_boekvoorstellen(
                session, administratie_id=administratie_id, mapping=RekeningMapping(), actor_id=beheerder_id
            )
        assert res == hervertaling.HervertaalResultaat(documenten=0, regels=0, vertaald={}, leeg={})
        assert len(_audit(admin_engine, administratie_id)) == 1

    def test_dto_draagt_het_spoor_en_een_put_door_de_mens_wist_het(
        self, administratie_id, beheerder_id, gescoopte_gebruiker, opslag
    ) -> None:
        _seed_caches(administratie_id, beheerder_id)
        doc = _document_met_regels(administratie_id, gescoopte_gebruiker, opslag, naam="dto.pdf", regels=[_regel()])
        mapping = RekeningMapping(grootboek={RLZ_GB: ODOO_GB}, btw={RLZ_BTW: ODOO_BTW})
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            hervertaling.hervertaal_open_boekvoorstellen(
                session, administratie_id=administratie_id, mapping=mapping, actor_id=beheerder_id
            )
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc)
        [regel] = data.regels
        assert regel.ledger_id == ODOO_GB and regel.project_id is None
        assert regel.overstap_vertaling is not None
        assert regel.overstap_vertaling["grootboek"]["naar_id"] == str(ODOO_GB)
        assert regel.overstap_vertaling["project"]["naar_id"] is None
        # De controleur slaat de regel op (kiest een project) → het spoor is weg: de keuze is nu de mens z'n keuze.
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=doc,
            actor_id=gescoopte_gebruiker,
            vendor_id=data.vendor_id,
            referentie=data.referentie,
            factuurdatum=data.factuurdatum,
            totaalbedrag=data.totaalbedrag,
            regels=[_regel(gb=ODOO_GB, btw=ODOO_BTW, project=ODOO_PROJECT)],
        )
        [regel] = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=doc).regels
        assert regel.overstap_vertaling is None and regel.project_id == ODOO_PROJECT

    @pytest.mark.parametrize("project_attr", [False, True])
    def test_signatuur_voor_de_coordinator(self, project_attr: bool) -> None:
        """De coördinator wired `hervertaal_open_boekvoorstellen(session, *, administratie_id, mapping, actor_id)` in
        `koppel_overstap`; `project` op de mapping is optioneel (getattr)."""
        import inspect

        sig = inspect.signature(hervertaling.hervertaal_open_boekvoorstellen)
        assert list(sig.parameters) == ["session", "administratie_id", "mapping", "actor_id"]
        mapping = _MappingMetProject() if project_attr else RekeningMapping()
        assert hervertaling._mapping_per_veld(mapping) == {"grootboek": {}, "btw": {}, "project": {}}
