# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/odoo/test_mapping.py)
"""Projectmapping RLZ-project → Odoo-analytic-account bij een overstap (Odoo-slotstuk 04-09, besluit Peter;
migratie 0113, `app/odoo/mapping.py` soort 'project'):

- puur: projectnummer uit de naam, "[code] "-prefix, voorstel (nummer = groen / naam = oranje / geen / meerdere
  kandidaten = nooit gokken), validatie (projectrijen NIET verplicht; onbekend/dubbel/aanmaken-zonder-sleutel = 422),
  aanmaak-verzoeken en `maak_odoo_projecten_aan` mét fake client (gevonden / aangemaakt / gearchiveerd / dubbel /
  Odoo-fout / company-mismatch = zichtbaar overgeslagen, nooit unlink);
- DB + endpoints (Beheerder-only): in-gebruik-projecten (geheugen ∪ open regels ∪ open projectverdeling),
  voorbereiden mét projectblok + telling + kan_aanmaken, overstap mét projectmapping (rijen, id-koppeling +
  project-cache voor aangemaakte accounts, response-velden, geheugen vertaalt project), aanmaken mislukt =
  overgeslagen mét 201, GET stand, PUT correctie soort project (0 = 422).
Probe + stamgegevenssync + live Odoo-lees + Odoo-client gemonkeypatcht — geen netwerk, geen echte Odoo-writes."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from typing import Any

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.storage import LokaleBestandsopslag
from app.geheugen import service as geheugen_service
from app.geheugen.engine import Observatie
from app.geheugen.models import BoekingObservatie
from app.main import app
from app.odoo import mapping as odoo_mapping
from app.odoo import service as odoo_service
from app.odoo.client import OdooFout
from app.odoo.ids import odoo_uuid
from app.odoo.models import OdooIdKoppeling, OdooRekeningMapping
from app.projectverdeling.models import Projectverdeling
from app.security.tokens import create_access_token
from app.sync.models import ProjectCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401
from tests.odoo.test_mapping import _audit, _mapping_rijen
from tests.odoo.test_router import COMPANY, KEY, OVERGANG, URL, _overstap, probe_groen, sync_gefaked  # noqa: F401

client = TestClient(app)

ANALYTIC = "account.analytic.account"
PLAN = 2  # `_groene_probe().analytic_plan_id`

RLZ_P_26127 = uuid.UUID("dddddddd-0000-0000-0000-000000026127")
RLZ_P_26200 = uuid.UUID("dddddddd-0000-0000-0000-000000026200")
RLZ_P_OVH = uuid.UUID("dddddddd-0000-0000-0000-000000000001")  # "Overhead" — geen nummer
RLZ_P_ONBEKEND = uuid.UUID("dddddddd-0000-0000-0000-000000009999")  # niet (meer) in de cache
VENDOR = uuid.UUID("cccccccc-0000-0000-0000-000000000002")


def _odoo_project(odoo_id: int, naam: str, code: str | None) -> odoo_mapping.OdooProject:
    return odoo_mapping.OdooProject(
        odoo_id=odoo_id, lokaal_id=odoo_uuid(COMPANY, ANALYTIC, odoo_id), naam=naam, code=code
    )


def _rlz_project(rlz_id: uuid.UUID, naam: str | None, *, obs: int = 1, open_regels: int = 0) -> odoo_mapping.RlzProject:
    return odoo_mapping.RlzProject(
        rlz_id=rlz_id,
        naam=naam,
        nummer=odoo_mapping.projectnummer_uit_naam(naam),
        actief=True,
        in_gebruik_observaties=obs,
        in_gebruik_open_regels=open_regels,
    )


ODOO_PROJECTEN = [
    _odoo_project(847, "Tilburg (Heijmans)", "26127"),
    _odoo_project(848, "26200 Eindhoven (BAM)", None),  # nummer alleen in de naam
    _odoo_project(849, "Overhead", "OVH"),
    _odoo_project(850, "Test Thomas", None),
]


# --------------------------------------------------------------------------- puur


class TestProjectnummerEnPrefix:
    def test_projectnummer_uit_naam(self) -> None:
        assert odoo_mapping.projectnummer_uit_naam("26127 Tilburg (Heijmans)") == "26127"
        assert odoo_mapping.projectnummer_uit_naam("  2612 Kort") == "2612"
        assert odoo_mapping.projectnummer_uit_naam("123 Te kort") is None
        assert odoo_mapping.projectnummer_uit_naam("1234567 Te lang") is None
        assert odoo_mapping.projectnummer_uit_naam("Overhead") is None
        assert odoo_mapping.projectnummer_uit_naam(None) is None

    def test_zonder_code_prefix(self) -> None:
        assert odoo_mapping.zonder_code_prefix("[26127] Tilburg (Heijmans)") == "Tilburg (Heijmans)"
        assert odoo_mapping.zonder_code_prefix("Tilburg (Heijmans)") == "Tilburg (Heijmans)"
        assert odoo_mapping.zonder_code_prefix(None) == ""

    def test_odoo_projecten_uit_sync_strips_prefix(self) -> None:
        [p] = odoo_mapping.odoo_projecten_uit_sync(
            [{"id": str(odoo_uuid(COMPANY, ANALYTIC, 847)), "Name": "[26127] Tilburg", "odoo_id": 847, "code": "26127"}]
        )
        assert p.naam == "Tilburg" and p.code == "26127" and p.odoo_id == 847


class TestProjectVoorstel:
    def test_nummer_via_odoo_code_is_groen(self) -> None:
        [rij] = odoo_mapping.bepaal_project_voorstel(
            [_rlz_project(RLZ_P_26127, "26127 Tilburg (Heijmans)")], ODOO_PROJECTEN
        )
        assert rij.voorstel is not None and rij.voorstel.odoo_id == 847 and rij.reden == "projectnummer"

    def test_nummer_via_leidende_cijfers_odoo_naam(self) -> None:
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_26200, "26200 Eindhoven")], ODOO_PROJECTEN)
        assert rij.voorstel is not None and rij.voorstel.odoo_id == 848 and rij.reden == "projectnummer"

    def test_naamgelijkheid_is_oranje(self) -> None:
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_OVH, "  overhead ")], ODOO_PROJECTEN)
        assert rij.voorstel is not None and rij.voorstel.odoo_id == 849 and rij.reden == "projectnaam"

    def test_geen_match_geen_voorstel(self) -> None:
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_OVH, "Kantoor algemeen")], ODOO_PROJECTEN)
        assert rij.voorstel is None and rij.reden is None

    def test_meerdere_kandidaten_nooit_gokken(self) -> None:
        odoo = [*ODOO_PROJECTEN, _odoo_project(851, "Tilburg fase 2", "26127")]
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_26127, "26127 Tilburg (Heijmans)")], odoo)
        assert rij.voorstel is None  # twee accounts met code 26127; ook géén terugval op naam (die matcht niet)
        odoo = [_odoo_project(1, "Overhead", None), _odoo_project(2, "Overhead", "OVH")]
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_OVH, "Overhead")], odoo)
        assert rij.voorstel is None

    def test_nummer_zonder_match_valt_terug_op_naam(self) -> None:
        odoo = [_odoo_project(5, "Tilburg (Heijmans)", None)]
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_26127, "26127 Tilburg (Heijmans)")], odoo)
        assert rij.voorstel is None  # RLZ-naam draagt het nummer, de Odoo-naam niet → genormaliseerd ongelijk
        odoo = [_odoo_project(5, "26127 Tilburg (Heijmans)", "ANDERS")]
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_26127, "26127 Tilburg (Heijmans)")], odoo)
        assert rij.voorstel is not None and rij.reden == "projectnummer"  # leidende cijfers in de Odoo-naam

    def test_onbekend_rlz_project_geen_voorstel_maar_wel_rij(self) -> None:
        [rij] = odoo_mapping.bepaal_project_voorstel([_rlz_project(RLZ_P_ONBEKEND, None)], ODOO_PROJECTEN)
        assert rij.voorstel is None and rij.rlz.rlz_id == RLZ_P_ONBEKEND and rij.rlz.nummer is None

    def test_kan_aanmaken_vergt_nummer_en_plan(self) -> None:
        met = _rlz_project(RLZ_P_26127, "26127 Tilburg (Heijmans)")
        zonder = _rlz_project(RLZ_P_OVH, "Overhead")
        assert odoo_mapping.kan_project_aanmaken(met, PLAN) is True
        assert odoo_mapping.kan_project_aanmaken(met, None) is False
        assert odoo_mapping.kan_project_aanmaken(zonder, PLAN) is False


def _voorstel():
    return odoo_mapping.bepaal_project_voorstel(
        [
            _rlz_project(RLZ_P_26127, "26127 Tilburg (Heijmans)"),
            _rlz_project(RLZ_P_26200, "26200 Eindhoven"),
            _rlz_project(RLZ_P_OVH, "Overhead"),
        ],
        ODOO_PROJECTEN,
    )


def _valideer(invoer: odoo_mapping.MappingInvoer | None, *, plan: int | None = PLAN):
    return odoo_mapping.valideer_mapping(
        grootboek=[],
        btw=[],
        odoo_grootboek=[],
        odoo_btw=[],
        invoer=invoer,
        project=_voorstel(),
        odoo_projecten=ODOO_PROJECTEN,
        analytic_plan_id=plan,
    )


class TestValideerProjectmapping:
    def test_projectrijen_niet_verplicht_leeg_mag(self) -> None:
        assert _valideer(None) == []
        inv = odoo_mapping.MappingInvoer(project=[odoo_mapping.ProjectMappingRijInvoer(RLZ_P_26127)])
        assert _valideer(inv) == []  # expliciet leeg = project vervalt, geen fout

    def test_bron_voorstelreden_of_handmatig_en_rlz_code_is_nummer(self) -> None:
        inv = odoo_mapping.MappingInvoer(
            project=[
                odoo_mapping.ProjectMappingRijInvoer(RLZ_P_26127, odoo_id=847),  # = voorstel
                odoo_mapping.ProjectMappingRijInvoer(RLZ_P_OVH, odoo_id=850),  # anders dan voorstel 849
            ]
        )
        rijen = _valideer(inv)
        per = {r.rlz_id: r for r in rijen}
        assert per[RLZ_P_26127].bron == "projectnummer" and per[RLZ_P_26127].rlz_code == "26127"
        assert per[RLZ_P_26127].odoo_code == "26127" and per[RLZ_P_26127].odoo_naam == "Tilburg (Heijmans)"
        assert (
            per[RLZ_P_26127].odoo_lokaal_id == odoo_uuid(COMPANY, ANALYTIC, 847) and per[RLZ_P_26127].soort == "project"
        )
        assert per[RLZ_P_OVH].bron == "handmatig" and per[RLZ_P_OVH].rlz_code is None and per[RLZ_P_OVH].odoo_id == 850

    def test_onbekende_rlz_id_422(self) -> None:
        inv = odoo_mapping.MappingInvoer(project=[odoo_mapping.ProjectMappingRijInvoer(uuid.uuid4(), odoo_id=847)])
        with pytest.raises(odoo_service.OdooKoppelFout, match="1 project\\(en\\) die niet in gebruik zijn"):
            _valideer(inv)

    def test_odoo_id_niet_in_plan_422(self) -> None:
        inv = odoo_mapping.MappingInvoer(project=[odoo_mapping.ProjectMappingRijInvoer(RLZ_P_26127, odoo_id=999)])
        with pytest.raises(odoo_service.OdooKoppelFout, match="staat niet \\(meer\\) in het analytic plan"):
            _valideer(inv)

    def test_aanmaken_en_kiezen_tegelijk_422(self) -> None:
        inv = odoo_mapping.MappingInvoer(
            project=[odoo_mapping.ProjectMappingRijInvoer(RLZ_P_26127, odoo_id=847, aanmaken=True)]
        )
        with pytest.raises(odoo_service.OdooKoppelFout, match="niet beide"):
            _valideer(inv)

    def test_aanmaken_zonder_nummer_of_plan_422(self) -> None:
        inv = odoo_mapping.MappingInvoer(project=[odoo_mapping.ProjectMappingRijInvoer(RLZ_P_OVH, aanmaken=True)])
        with pytest.raises(odoo_service.OdooKoppelFout, match="geen projectnummer in de naam"):
            _valideer(inv)
        inv = odoo_mapping.MappingInvoer(project=[odoo_mapping.ProjectMappingRijInvoer(RLZ_P_26127, aanmaken=True)])
        with pytest.raises(odoo_service.OdooKoppelFout, match="geen analytic plan"):
            _valideer(inv, plan=None)

    def test_aanmaak_rijen_komen_niet_uit_valideer_maar_uit_verzoeken(self) -> None:
        inv = odoo_mapping.MappingInvoer(
            project=[
                odoo_mapping.ProjectMappingRijInvoer(RLZ_P_26127, aanmaken=True),
                odoo_mapping.ProjectMappingRijInvoer(RLZ_P_26200, odoo_id=848),
                odoo_mapping.ProjectMappingRijInvoer(RLZ_P_OVH),
            ]
        )
        rijen = _valideer(inv)
        assert [r.rlz_id for r in rijen] == [RLZ_P_26200]
        verzoeken = odoo_mapping.project_aanmaak_verzoeken(_voorstel(), inv)
        assert [v.rlz_id for v in verzoeken] == [RLZ_P_26127] and verzoeken[0].nummer == "26127"


class FakeOdooClient:
    """Minimale Odoo-client: `search_read` uit een vaste lijst, `create` telt op, `read_een` leest terug.
    Registreert élke methode-aanroep zodat de test kan bewijzen dat er nooit `unlink`/`write` gebeurt."""

    def __init__(self, bestaand: list[dict[str, Any]] | None = None, *, create_fout: Exception | None = None,
                 company_bij_create: int | None = COMPANY) -> None:  # fmt: skip
        self.bestaand = list(bestaand or [])
        self.create_fout = create_fout
        self.company_bij_create = company_bij_create
        self.aanroepen: list[tuple[str, Any]] = []
        self.volgend_id = 900
        self.company_id = COMPANY

    def __enter__(self) -> FakeOdooClient:
        return self

    def __exit__(self, *exc: object) -> None:
        return None

    def search_read(self, model: str, domain: list, fields: list[str], **kw: Any) -> list[dict[str, Any]]:
        self.aanroepen.append(("search_read", domain))
        assert model == ANALYTIC
        code = next(v for f, op, v in domain if f == "code")
        return [dict(r) for r in self.bestaand if r.get("code") == code]

    def create(self, model: str, vals: dict[str, Any]) -> int:
        self.aanroepen.append(("create", vals))
        if self.create_fout is not None:
            raise self.create_fout
        self.volgend_id += 1
        rec = {
            "id": self.volgend_id,
            "name": vals["name"],
            "code": vals["code"],
            "active": True,
            "company_id": [self.company_bij_create, "Company"] if self.company_bij_create else False,
        }
        self.bestaand.append(rec)
        return self.volgend_id

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict[str, Any] | None:
        self.aanroepen.append(("read_een", odoo_id))
        return next((dict(r) for r in self.bestaand if r["id"] == odoo_id), None)

    def __getattr__(self, naam: str) -> Any:  # unlink/write/… — mag nooit gebeuren
        raise AssertionError(f"onverwachte Odoo-call {naam}")


def _verzoek(rlz_id: uuid.UUID, naam: str) -> odoo_mapping.RlzProject:
    return _rlz_project(rlz_id, naam)


class TestMaakOdooProjectenAan:
    def test_lookup_voor_create_hergebruikt_actief_account(self) -> None:
        c = FakeOdooClient(
            [{"id": 847, "name": "Tilburg (Heijmans)", "code": "26127", "active": True, "company_id": False}]
        )
        u = odoo_mapping.maak_odoo_projecten_aan(
            c, verzoeken=[_verzoek(RLZ_P_26127, "26127 Tilburg (Heijmans)")], analytic_plan_id=PLAN, company_id=COMPANY
        )
        assert u.gevonden == 1 and u.aangemaakt == 0 and u.overgeslagen == []
        [rij] = u.rijen
        assert rij.soort == "project" and rij.bron == "aangemaakt" and rij.odoo_id == 847 and rij.odoo_code == "26127"
        assert rij.odoo_lokaal_id == odoo_uuid(COMPANY, ANALYTIC, 847)
        assert [a for a, _ in c.aanroepen] == ["search_read"]  # géén create
        domain = c.aanroepen[0][1]
        assert ["plan_id", "=", PLAN] in domain and ["active", "in", [True, False]] in domain

    def test_geen_account_maakt_aan_met_volledige_naam_code_plan_company(self) -> None:
        c = FakeOdooClient()
        u = odoo_mapping.maak_odoo_projecten_aan(
            c, verzoeken=[_verzoek(RLZ_P_26127, "26127 Tilburg (Heijmans)")], analytic_plan_id=PLAN, company_id=COMPANY
        )
        assert u.aangemaakt == 1 and u.gevonden == 0 and u.overgeslagen == []
        vals = next(v for a, v in c.aanroepen if a == "create")
        assert vals == {"name": "26127 Tilburg (Heijmans)", "code": "26127", "plan_id": PLAN, "company_id": COMPANY}
        [account] = u.accounts
        assert account.odoo_id == 901 and account.code == "26127" and account.naam == "26127 Tilburg (Heijmans)"
        assert u.rijen[0].odoo_id == 901 and u.rijen[0].bron == "aangemaakt"
        assert [a for a, _ in c.aanroepen] == ["search_read", "create", "read_een"]  # post-write terug-lezen

    def test_alleen_gearchiveerd_account_is_overgeslagen_nooit_heractiveren(self) -> None:
        c = FakeOdooClient([{"id": 700, "name": "Oud", "code": "26127", "active": False, "company_id": False}])
        u = odoo_mapping.maak_odoo_projecten_aan(
            c, verzoeken=[_verzoek(RLZ_P_26127, "26127 Tilburg (Heijmans)")], analytic_plan_id=PLAN, company_id=COMPANY
        )
        assert u.rijen == [] and u.aangemaakt == 0 and len(u.overgeslagen) == 1
        assert "GEARCHIVEERD" in u.overgeslagen[0] and "26127 Tilburg (Heijmans)" in u.overgeslagen[0]
        assert [a for a, _ in c.aanroepen] == ["search_read"]

    def test_meerdere_actieve_accounts_is_overgeslagen(self) -> None:
        c = FakeOdooClient(
            [
                {"id": 1, "name": "A", "code": "26127", "active": True, "company_id": False},
                {"id": 2, "name": "B", "code": "26127", "active": True, "company_id": False},
            ]
        )
        u = odoo_mapping.maak_odoo_projecten_aan(
            c, verzoeken=[_verzoek(RLZ_P_26127, "26127 Tilburg (Heijmans)")], analytic_plan_id=PLAN, company_id=COMPANY
        )
        assert u.rijen == [] and "2 actieve Odoo-projecten" in u.overgeslagen[0]

    def test_odoo_fout_bij_aanmaken_is_overgeslagen_met_leesbare_reden(self) -> None:
        fout = OdooFout(403, "odoo.exceptions.AccessError", "Geen recht", model=ANALYTIC, methode="create")
        c = FakeOdooClient(create_fout=fout)
        u = odoo_mapping.maak_odoo_projecten_aan(
            c,
            verzoeken=[_verzoek(RLZ_P_26127, "26127 Tilburg (Heijmans)"), _verzoek(RLZ_P_26200, "26200 Eindhoven")],
            analytic_plan_id=PLAN,
            company_id=COMPANY,
        )
        assert u.rijen == [] and len(u.overgeslagen) == 2  # per rij overgeslagen, de rest gaat door
        assert all("Odoo-fout bij aanmaken" in o for o in u.overgeslagen)

    def test_company_mismatch_na_create_is_overgeslagen(self) -> None:
        c = FakeOdooClient(company_bij_create=3)
        u = odoo_mapping.maak_odoo_projecten_aan(
            c, verzoeken=[_verzoek(RLZ_P_26127, "26127 Tilburg (Heijmans)")], analytic_plan_id=PLAN, company_id=COMPANY
        )
        assert u.rijen == [] and u.aangemaakt == 0 and "company 3 i.p.v. 1" in u.overgeslagen[0]

    def test_zonder_nummer_overgeslagen(self) -> None:
        c = FakeOdooClient()
        u = odoo_mapping.maak_odoo_projecten_aan(
            c, verzoeken=[_verzoek(RLZ_P_OVH, "Overhead")], analytic_plan_id=PLAN, company_id=COMPANY
        )
        assert u.rijen == [] and "geen projectnummer" in u.overgeslagen[0] and c.aanroepen == []


class TestVertaalProject:
    def test_project_via_mapping_anders_none(self) -> None:
        gb = uuid.uuid4()
        gb_odoo = odoo_uuid(COMPANY, "account.account", 11)
        mapping = odoo_mapping.RekeningMapping(
            grootboek={gb: gb_odoo}, project={RLZ_P_26127: odoo_uuid(COMPANY, ANALYTIC, 847)}
        )
        assert not mapping.leeg
        met, zonder, geen = odoo_mapping.vertaal_observaties(
            [
                Observatie(None, gb, None, RLZ_P_26127, "app", date(2026, 8, 1)),
                Observatie(None, gb, None, RLZ_P_OVH, "app", date(2026, 8, 1)),
                Observatie(None, gb, None, None, "app", date(2026, 8, 1)),
            ],
            mapping,
        )
        assert met.project_id == odoo_uuid(COMPANY, ANALYTIC, 847) and met.gb_id == gb_odoo
        assert zonder.project_id is None and geen.project_id is None

    def test_alleen_projectmapping_is_niet_leeg(self) -> None:
        assert not odoo_mapping.RekeningMapping(project={RLZ_P_26127: uuid.uuid4()}).leeg


# --------------------------------------------------------------------------- DB + endpoints


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def odoo_live(monkeypatch: pytest.MonkeyPatch, probe_groen) -> None:
    """Live Odoo-lijsten: geen grootboek/btw (de fixture hieronder gebruikt geen GB/btw), wél analytic accounts."""
    monkeypatch.setattr(odoo_mapping, "lees_live_odoo_stamgegevens", lambda **kw: ([], [], list(ODOO_PROJECTEN)))


@pytest.fixture
def fake_client(monkeypatch: pytest.MonkeyPatch) -> FakeOdooClient:
    """De enige Odoo-write van de overstap (aanmaken analytic account) loopt via `service._client`."""
    c = FakeOdooClient()
    monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid: c)
    return c


@pytest.fixture
def rlz_projecten_in_gebruik(administratie_id, gescoopte_gebruiker, tmp_path) -> uuid.UUID:
    """RLZ-verleden: project-cache 26127 (Heijmans), 26200 (BAM) en "Overhead"; een app-observatie op 26127 (geen
    gb-mapping nodig: geen GB in de cache betekent hier dat we de gb-rij ook mappen — zie `_mapping`); een OPEN
    boekvoorstel met regel op Overhead + een open projectverdeling die 26200 noemt; een seed-observatie op een
    project dat niet meer in de cache staat. Retourneert het open document."""
    with scoped_session(administratie_id) as session:
        for pid, naam in (
            (RLZ_P_26127, "26127 Tilburg (Heijmans)"),
            (RLZ_P_26200, "26200 Eindhoven (BAM)"),
            (RLZ_P_OVH, "Overhead"),
        ):
            session.add(
                ProjectCache(
                    id=pid, administratie_id=administratie_id, naam=naam, is_actief=True, brondata={"Name": naam}
                )
            )
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vendor_id=VENDOR,
                regel_sleutel=None,
                gb_id=GB_RLZ,
                btw_id=None,
                project_id=RLZ_P_26127,
                bron="app",
                bron_datum=date(2026, 8, 1),
            )
        )
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vendor_id=VENDOR,
                regel_sleutel=None,
                gb_id=GB_RLZ,
                btw_id=None,
                project_id=RLZ_P_ONBEKEND,
                bron="rlz_seed",
                bron_datum=date(2025, 1, 1),
            )
        )
    opslag = LokaleBestandsopslag(tmp_path / "documenten")
    document_id = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="open.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    ).document_id
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=VENDOR,
        referentie="OPEN-P1",
        factuurdatum=date(2026, 6, 5),
        totaalbedrag=Decimal("100.00"),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=GB_RLZ,
                taxrate_id=None,
                project_id=RLZ_P_OVH,
                netto_bedrag=Decimal("100.00"),
                btw_bedrag=Decimal("0"),
                omschrijving="Kantoor",
            )
        ],
        regels_samenvoegen=False,
    )
    with scoped_session(administratie_id) as session:
        session.add(
            Projectverdeling(
                administratie_id=administratie_id,
                document_id=document_id,
                vaste_regels=[{"project_id": str(RLZ_P_26200), "bedrag": "40.00", "hint": None}],
                verdeling=[{"project_id": str(RLZ_P_26200), "wijze": "vast", "bedrag": "40.00"}],
                status="voorstel",
            )
        )
    return document_id


GB_RLZ = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004000")
GB_ODOO = odoo_mapping.OdooRekening(
    odoo_id=12, lokaal_id=odoo_uuid(COMPANY, "account.account", 12), code="400000", naam="Inkoop", soort=2
)


@pytest.fixture
def odoo_live_met_gb(monkeypatch: pytest.MonkeyPatch, probe_groen) -> None:
    monkeypatch.setattr(odoo_mapping, "lees_live_odoo_stamgegevens", lambda **kw: ([GB_ODOO], [], list(ODOO_PROJECTEN)))


def _mapping(project: list[dict]) -> dict:
    return {"grootboek": [{"rlz_id": str(GB_RLZ), "odoo_id": 12}], "btw": [], "project": project}


class TestInGebruikEnVoorbereiden:
    def test_rlz_in_gebruik_telt_geheugen_open_regels_en_projectverdeling(
        self, administratie_id, rlz_projecten_in_gebruik
    ) -> None:
        with scoped_session(administratie_id) as session:
            _, _, projecten = odoo_mapping.rlz_in_gebruik(session, administratie_id)
        per = {p.rlz_id: p for p in projecten}
        assert set(per) == {RLZ_P_26127, RLZ_P_26200, RLZ_P_OVH, RLZ_P_ONBEKEND}
        assert per[RLZ_P_26127].nummer == "26127" and per[RLZ_P_26127].in_gebruik_observaties == 1
        assert per[RLZ_P_OVH].nummer is None and per[RLZ_P_OVH].in_gebruik_open_regels == 1
        assert per[RLZ_P_26200].in_gebruik_open_regels == 2  # vaste regel + verdeel-deel van de open verdeling
        assert per[RLZ_P_ONBEKEND].naam is None and per[RLZ_P_ONBEKEND].in_gebruik_observaties == 1
        # Volgorde: op nummer, zonder nummer achteraan (naam), onbekende laatst.
        assert [p.rlz_id for p in projecten] == [RLZ_P_26127, RLZ_P_26200, RLZ_P_OVH, RLZ_P_ONBEKEND]

    def test_voorbereiden_projectblok_telling_en_kan_aanmaken(
        self, administratie_id, beheerder_id, odoo_live_met_gb, rlz_projecten_in_gebruik
    ) -> None:
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap/voorbereiden",
            json={"odoo_url": URL, "api_key": KEY, "company_id": COMPANY},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        per = {row["rlz_id"]: row for row in body["project"]}
        assert per[str(RLZ_P_26127)] == {
            "rlz_id": str(RLZ_P_26127),
            "rlz_naam": "26127 Tilburg (Heijmans)",
            "rlz_nummer": "26127",
            "actief": True,
            "in_gebruik_observaties": 1,
            "in_gebruik_open_regels": 0,
            "voorstel_odoo_id": 847,
            "voorstel_odoo_naam": "Tilburg (Heijmans)",
            "reden": "projectnummer",
            "kan_aanmaken": True,
        }
        assert per[str(RLZ_P_26200)]["voorstel_odoo_id"] == 848 and per[str(RLZ_P_26200)]["reden"] == "projectnummer"
        assert per[str(RLZ_P_OVH)]["voorstel_odoo_id"] == 849 and per[str(RLZ_P_OVH)]["reden"] == "projectnaam"
        assert per[str(RLZ_P_OVH)]["kan_aanmaken"] is False  # geen nummer
        assert (
            per[str(RLZ_P_ONBEKEND)]["voorstel_odoo_id"] is None and per[str(RLZ_P_ONBEKEND)]["kan_aanmaken"] is False
        )
        assert [o["odoo_id"] for o in body["odoo_projecten"]] == [847, 848, 849, 850]
        assert body["odoo_projecten"][0] == {
            "odoo_id": 847,
            "lokaal_id": str(odoo_uuid(COMPANY, ANALYTIC, 847)),
            "naam": "Tilburg (Heijmans)",
            "code": "26127",
        }
        assert body["telling"]["project_totaal"] == 4 and body["telling"]["project_met_voorstel"] == 3
        assert body["telling"]["grootboek_totaal"] == 1
        assert _mapping_rijen(administratie_id) == []  # niets persistent


class TestOverstapMetProjectmapping:
    def test_leeg_project_mag_en_vertaalt_naar_none(
        self, administratie_id, beheerder_id, odoo_live_met_gb, rlz_projecten_in_gebruik, sync_gefaked
    ) -> None:
        r = _overstap(administratie_id, beheerder_id, mapping=_mapping([]))
        assert r.status_code == 201, r.text
        assert r.json()["projecten_aangemaakt"] == 0 and r.json()["projecten_overgeslagen"] == []
        assert [x.soort for x in _mapping_rijen(administratie_id)] == ["grootboek"]
        v = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert v.gb.waarde == GB_ODOO.lokaal_id and v.project.waarde is None

    def test_koppelen_en_aanmaken_rijen_cache_idkoppeling_response_en_geheugen(
        self,
        administratie_id,
        beheerder_id,
        odoo_live_met_gb,
        rlz_projecten_in_gebruik,
        sync_gefaked,
        fake_client: FakeOdooClient,
        admin_engine: Engine,
    ) -> None:
        r = _overstap(
            administratie_id,
            beheerder_id,
            mapping=_mapping(
                [
                    {"rlz_id": str(RLZ_P_26127), "odoo_id": 847},  # = voorstel → projectnummer
                    {"rlz_id": str(RLZ_P_26200), "aanmaken": True},  # bestaat niet in Odoo → create
                    {"rlz_id": str(RLZ_P_OVH), "odoo_id": 850},  # anders dan voorstel → handmatig
                    {"rlz_id": str(RLZ_P_ONBEKEND), "odoo_id": None},  # vervalt
                ]
            ),
        )
        assert r.status_code == 201, r.text
        body = r.json()
        assert body["projecten_aangemaakt"] == 1 and body["projecten_overgeslagen"] == []
        assert sync_gefaked == [administratie_id]
        vals = next(v for a, v in fake_client.aanroepen if a == "create")
        assert vals == {"name": "26200 Eindhoven (BAM)", "code": "26200", "plan_id": PLAN, "company_id": COMPANY}

        rijen = {(x.soort, x.rlz_id): x for x in _mapping_rijen(administratie_id)}
        assert len(rijen) == 4 and all(x.versie == 1 for x in rijen.values())
        assert rijen[("project", RLZ_P_26127)].bron == "projectnummer"
        assert rijen[("project", RLZ_P_26127)].rlz_code == "26127" and rijen[("project", RLZ_P_26127)].odoo_id == 847
        assert rijen[("project", RLZ_P_26200)].bron == "aangemaakt" and rijen[("project", RLZ_P_26200)].odoo_id == 901
        assert rijen[("project", RLZ_P_OVH)].bron == "handmatig" and rijen[("project", RLZ_P_OVH)].odoo_id == 850
        assert ("project", RLZ_P_ONBEKEND) not in rijen

        # Het aangemaakte account is direct vertaalbaar + zichtbaar: id-koppeling + project-cache "[code] name".
        lokaal_nieuw = odoo_uuid(COMPANY, ANALYTIC, 901)
        with scoped_session(administratie_id) as session:
            idk = session.get(OdooIdKoppeling, (administratie_id, ANALYTIC, 901))
            assert idk is not None and idk.lokaal_id == lokaal_nieuw
            pc = session.get(ProjectCache, (lokaal_nieuw, administratie_id))
            assert pc is not None and pc.naam == "[26200] 26200 Eindhoven (BAM)" and pc.is_actief is True
            assert (
                pc.brondata["backend"] == "odoo" and pc.brondata["odoo_id"] == 901 and pc.verdwenen_uit_bron_op is None
            )
            geldend = odoo_mapping.geldende_mapping(session, administratie_id)
        assert geldend.project == {
            RLZ_P_26127: odoo_uuid(COMPANY, ANALYTIC, 847),
            RLZ_P_26200: lokaal_nieuw,
            RLZ_P_OVH: odoo_uuid(COMPANY, ANALYTIC, 850),
        }

        audit = _audit(admin_engine, "odoo_rekening_mapping_vastgelegd", administratie_id)
        assert len(audit) == 1 and '"project": 3' in audit[0][1] and '"aangemaakt": 1' in audit[0][1]
        assert "project:26127→26127" in audit[0][1] and KEY not in audit[0][1]
        overstap = _audit(admin_engine, "odoo_overstap", administratie_id)
        assert '"projecten_aangemaakt": 1' in overstap[0][1]

        # Het geheugen vertaalt het project VÓÓR de engine: 26127 → analytic account 847, app-bevestigd blijft.
        v = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert v.project.waarde == odoo_uuid(COMPANY, ANALYTIC, 847) and v.project.app_bevestigd

    def test_aanmaken_mislukt_is_overgeslagen_en_overstap_gaat_door(
        self,
        administratie_id,
        beheerder_id,
        odoo_live_met_gb,
        rlz_projecten_in_gebruik,
        sync_gefaked,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        c = FakeOdooClient(
            [{"id": 700, "name": "Oud", "code": "26200", "active": False, "company_id": False}],
        )
        monkeypatch.setattr(odoo_service, "_client", lambda url, key, cid: c)
        r = _overstap(
            administratie_id, beheerder_id, mapping=_mapping([{"rlz_id": str(RLZ_P_26200), "aanmaken": True}])
        )
        assert r.status_code == 201, r.text
        assert r.json()["projecten_aangemaakt"] == 0
        [reden] = r.json()["projecten_overgeslagen"]
        assert "26200 Eindhoven (BAM)" in reden and "GEARCHIVEERD" in reden
        assert [x.soort for x in _mapping_rijen(administratie_id)] == ["grootboek"]
        assert [a for a, _ in c.aanroepen] == ["search_read"]  # nooit create/write/unlink

    def test_aanmaken_zonder_nummer_422_niets_opgeslagen(
        self, administratie_id, beheerder_id, odoo_live_met_gb, rlz_projecten_in_gebruik, sync_gefaked
    ) -> None:
        r = _overstap(administratie_id, beheerder_id, mapping=_mapping([{"rlz_id": str(RLZ_P_OVH), "aanmaken": True}]))
        assert r.status_code == 422 and "geen projectnummer" in r.text
        assert _mapping_rijen(administratie_id) == [] and sync_gefaked == []

    def test_odoo_id_nul_op_project_is_invoerfout(
        self, administratie_id, beheerder_id, odoo_live_met_gb, rlz_projecten_in_gebruik
    ) -> None:
        r = _overstap(administratie_id, beheerder_id, mapping=_mapping([{"rlz_id": str(RLZ_P_26127), "odoo_id": 0}]))
        assert r.status_code == 422


class TestStandEnCorrectie:
    def _overgestapt(self, aid: uuid.UUID, beheerder: uuid.UUID) -> None:
        r = _overstap(aid, beheerder, mapping=_mapping([{"rlz_id": str(RLZ_P_26127), "odoo_id": 847}]))
        assert r.status_code == 201, r.text
        # De (gefakete) sync zou de Odoo-projecten in de cache zetten; hier handmatig twee analytic accounts.
        with scoped_session(aid) as session:
            for odoo_id, code, naam in ((847, "26127", "Tilburg (Heijmans)"), (850, None, "Test Thomas")):
                lokaal = odoo_uuid(COMPANY, ANALYTIC, odoo_id)
                weergave = f"[{code}] {naam}" if code else naam
                session.add(
                    ProjectCache(
                        id=lokaal,
                        administratie_id=aid,
                        naam=weergave,
                        is_actief=True,
                        brondata={"Name": weergave, "code": code, "odoo_id": odoo_id, "backend": "odoo"},
                    )
                )
                session.add(
                    OdooIdKoppeling(
                        administratie_id=aid, model=ANALYTIC, odoo_id=odoo_id, lokaal_id=lokaal, naam=weergave
                    )
                )

    def test_get_stand_project_en_odoo_projecten(
        self, administratie_id, beheerder_id, odoo_live_met_gb, rlz_projecten_in_gebruik, sync_gefaked
    ) -> None:
        self._overgestapt(administratie_id, beheerder_id)
        r = client.get(f"/administraties/{administratie_id}/odoo/mapping", headers=_bearer(beheerder_id))
        assert r.status_code == 200, r.text
        stand = r.json()
        [rij] = stand["project"]
        assert (
            rij["soort"] == "project" and rij["rlz_code"] == "26127" and rij["rlz_naam"] == "26127 Tilburg (Heijmans)"
        )
        assert rij["odoo_id"] == 847 and rij["odoo_code"] == "26127" and rij["odoo_naam"] == "Tilburg (Heijmans)"
        assert rij["bron"] == "projectnummer" and rij["versie"] == 1
        # Odoo-keuzelijst uit de cache: alleen rijen mét een analytic-id-koppeling (de RLZ-projecten niet).
        assert [(o["odoo_id"], o["code"], o["naam"]) for o in stand["odoo_projecten"]] == [
            (847, "26127", "Tilburg (Heijmans)"),
            (850, None, "Test Thomas"),
        ]

    def test_put_correctie_project_versie_2_en_nieuwe_rij_versie_1(
        self, administratie_id, beheerder_id, odoo_live_met_gb, rlz_projecten_in_gebruik, sync_gefaked, admin_engine
    ) -> None:
        self._overgestapt(administratie_id, beheerder_id)
        h = _bearer(beheerder_id)
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/project/{RLZ_P_26127}", json={"odoo_id": 850}, headers=h
        )
        assert r.status_code == 200, r.text
        rij = next(row for row in r.json()["project"] if row["rlz_id"] == str(RLZ_P_26127))
        assert rij["odoo_id"] == 850 and rij["odoo_naam"] == "Test Thomas" and rij["odoo_code"] is None
        assert rij["versie"] == 2 and rij["bron"] == "handmatig" and rij["rlz_code"] == "26127"
        audit = _audit(admin_engine, "odoo_rekening_mapping_gecorrigeerd", administratie_id)
        assert len(audit) == 1 and '"odoo_id": 847' in audit[0][0] and '"odoo_id": 850' in audit[0][1]
        # Een project dat bij de overstap leeg bleef, alsnog koppelen = versie 1 (additief) mét RLZ-naam/nummer.
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/project/{RLZ_P_OVH}", json={"odoo_id": 847}, headers=h
        )
        assert r.status_code == 200, r.text
        rij = next(row for row in r.json()["project"] if row["rlz_id"] == str(RLZ_P_OVH))
        assert rij["versie"] == 1 and rij["rlz_naam"] == "Overhead" and rij["rlz_code"] is None
        with scoped_session(administratie_id) as session:
            geldend = odoo_mapping.geldende_mapping(session, administratie_id)
        assert geldend.project[RLZ_P_26127] == odoo_uuid(COMPANY, ANALYTIC, 850)
        assert geldend.project[RLZ_P_OVH] == odoo_uuid(COMPANY, ANALYTIC, 847)

    def test_put_project_nul_of_onbekend_422(
        self, administratie_id, beheerder_id, odoo_live_met_gb, rlz_projecten_in_gebruik, sync_gefaked
    ) -> None:
        self._overgestapt(administratie_id, beheerder_id)
        h = _bearer(beheerder_id)
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/project/{RLZ_P_26127}", json={"odoo_id": 0}, headers=h
        )
        assert r.status_code == 422 and "loskoppelen kan niet" in r.text
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/project/{RLZ_P_26127}", json={"odoo_id": 999}, headers=h
        )
        assert r.status_code == 422 and "Odoo-project 999 is niet bekend" in r.text
        assert all(x.versie == 1 for x in _mapping_rijen(administratie_id))

    def test_rolpoort_put_project(self, administratie_id, gescoopte_gebruiker) -> None:
        pad = f"/administraties/{administratie_id}/odoo/mapping/project/{RLZ_P_26127}"
        assert client.put(pad, json={"odoo_id": 847}).status_code == 401
        assert (
            client.put(pad, json={"odoo_id": 847}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code
            == 403
        )


class TestConstraint0113:
    def test_projectrij_en_projectbronnen_passen_in_de_tabel(self, administratie_id, beheerder_id) -> None:
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            for i, bron in enumerate(("projectnummer", "projectnaam", "aangemaakt")):
                session.add(
                    OdooRekeningMapping(
                        administratie_id=administratie_id,
                        soort="project",
                        rlz_id=uuid.uuid4(),
                        rlz_code="2612" + str(i),
                        rlz_naam="x",
                        odoo_lokaal_id=uuid.uuid4(),
                        odoo_id=800 + i,
                        odoo_code=None,
                        odoo_naam="y",
                        bron=bron,
                        versie=1,
                        bevestigd_door=beheerder_id,
                    )
                )
        assert len([x for x in _mapping_rijen(administratie_id) if x.soort == "project"]) == 3
