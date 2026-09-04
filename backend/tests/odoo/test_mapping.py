# ruff: noqa: F811 — pytest-fixtures als parameters (patroon tests/odoo/test_router.py)
"""Boekingsgeheugen-mapping RLZ → Odoo bij een overstap (blok A Odoo-afrondingsrun 04-09, migratie 0111,
`app/odoo/mapping.py`) + C1 "Overgangsdatum wijzigen" geblokkeerd door Odoo-boekingen:

- pure voorstelregels grootboek (zelfde_code / code_verlengd / dubbel = geen voorstel) en btw (percentage /
  verlegd / 0 %-vrijgesteld → synthetisch geen-btw / meerdere = geen gok);
- vertaal_observaties: gb + btw vertaald, project None, bron/datum intact → engine: app_bevestigd blijft, geen
  gesplitste stem tussen oude RLZ- en nieuwe Odoo-observaties op dezelfde rekening;
- valideer_mapping: onvolledig/onbekend = OdooKoppelFout, bron = voorstel-reden of 'handmatig';
- endpoints (Beheerder-only): voorbereiden 200 + 422, overstap zonder mapping bij in-gebruik-rijen 422 (niets
  opgeslagen), overstap mét mapping → rijen + audit + vertaald geheugen, GET mapping, PUT correctie versie 2 +
  audit, overgangsdatum 409.
Probe + stamgegevenssync + live Odoo-lees gemonkeypatcht — geen netwerk, geen Odoo-writes."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import boekvoorstel
from app.documenten import service as documenten_service
from app.documenten.storage import LokaleBestandsopslag
from app.geheugen import service as geheugen_service
from app.geheugen.engine import Observatie, bepaal_voorstel
from app.geheugen.models import BoekingObservatie
from app.geheugen.regel_gb import RegelObservatie
from app.main import app
from app.odoo import mapping as odoo_mapping
from app.odoo import service as odoo_service
from app.odoo.ids import GEEN_BTW_ODOO_ID, odoo_uuid
from app.odoo.models import OdooDocumentKoppeling, OdooIdKoppeling, OdooRekeningMapping
from app.security.tokens import create_access_token
from app.sync.models import TaxRateCache
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401
from tests.odoo.test_router import COMPANY, KEY, OVERGANG, URL, _overstap, probe_groen, sync_gefaked  # noqa: F401

client = TestClient(app)

# RLZ-kant (UUID's zoals ze in het geheugen/de open regels staan).
RLZ_GB_4808 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004808")
RLZ_GB_4000 = uuid.UUID("aaaaaaaa-0000-0000-0000-000000004000")
RLZ_GB_ONBEKEND = uuid.UUID("aaaaaaaa-0000-0000-0000-000000009999")  # niet (meer) in de cache
RLZ_BTW_21 = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000021")
RLZ_BTW_0 = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000000")
RLZ_BTW_VERLEGD = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000099")
VENDOR = uuid.UUID("cccccccc-0000-0000-0000-000000000001")


def _odoo_rek(odoo_id: int, code: str, naam: str = "Rekening") -> odoo_mapping.OdooRekening:
    return odoo_mapping.OdooRekening(
        odoo_id=odoo_id, lokaal_id=odoo_uuid(COMPANY, "account.account", odoo_id), code=code, naam=naam, soort=2
    )


def _odoo_tarief(
    odoo_id: int, naam: str, pct: str, *, verlegd: bool = False, synthetisch: bool = False
) -> odoo_mapping.OdooTarief:
    return odoo_mapping.OdooTarief(
        odoo_id=odoo_id,
        lokaal_id=odoo_uuid(COMPANY, "account.tax", odoo_id),
        naam=naam,
        percentage=Decimal(pct),
        verlegd=verlegd,
        favoriet=naam.endswith("%"),
        synthetisch=synthetisch,
    )


ODOO_GB = [_odoo_rek(10, "4808", "Huur materieel (oud)"), _odoo_rek(11, "480800", "Huur materieel"),
           _odoo_rek(12, "400000", "Inkoop"), _odoo_rek(13, "700100", "Omzet")]  # fmt: skip
ODOO_BTW = [
    _odoo_tarief(21, "21%", "0.21"),
    _odoo_tarief(22, "21% R", "0.21", verlegd=True),
    _odoo_tarief(23, "9%", "0.09"),
    _odoo_tarief(GEEN_BTW_ODOO_ID, "Geen btw (0%)", "0", synthetisch=True),
]


def _rlz_rek(rlz_id: uuid.UUID, code: str | None, naam: str | None = "x") -> odoo_mapping.RlzRekening:
    return odoo_mapping.RlzRekening(
        rlz_id=rlz_id, code=code, naam=naam, in_gebruik_observaties=1, in_gebruik_open_regels=0
    )


def _rlz_tarief(
    rlz_id: uuid.UUID, naam: str, pct: str | None, *, verlegd: bool = False, vrijgesteld: bool = False
) -> odoo_mapping.RlzTarief:
    return odoo_mapping.RlzTarief(
        rlz_id=rlz_id,
        naam=naam,
        percentage=Decimal(pct) if pct is not None else None,
        verlegd=verlegd,
        vrijgesteld=vrijgesteld,
        in_gebruik_observaties=1,
        in_gebruik_open_regels=0,
    )


# --------------------------------------------------------------------------- pure voorstelregels


class TestGrootboekVoorstel:
    def test_exact_gelijke_code_wint_van_verlengd(self) -> None:
        [rij] = odoo_mapping.bepaal_grootboek_voorstel([_rlz_rek(RLZ_GB_4808, "4808")], ODOO_GB)
        assert rij.voorstel is not None and rij.voorstel.odoo_id == 10
        assert rij.reden == "zelfde_code"

    def test_code_plus_00_is_code_verlengd(self) -> None:
        [rij] = odoo_mapping.bepaal_grootboek_voorstel([_rlz_rek(RLZ_GB_4000, "4000")], ODOO_GB)
        assert rij.voorstel is not None and rij.voorstel.odoo_id == 12 and rij.voorstel.code == "400000"
        assert rij.reden == "code_verlengd"

    def test_meerdere_odoo_rekeningen_met_dezelfde_code_geeft_geen_voorstel(self) -> None:
        odoo = [_odoo_rek(1, "4000", "A"), _odoo_rek(2, "4000", "B"), _odoo_rek(3, "400000", "C")]
        [rij] = odoo_mapping.bepaal_grootboek_voorstel([_rlz_rek(RLZ_GB_4000, "4000")], odoo)
        assert rij.voorstel is None and rij.reden is None  # exact dubbel → geen terugval op verlengd
        odoo = [_odoo_rek(2, "400000", "B"), _odoo_rek(3, "400000", "C")]
        [rij] = odoo_mapping.bepaal_grootboek_voorstel([_rlz_rek(RLZ_GB_4000, "4000")], odoo)
        assert rij.voorstel is None

    def test_onbekende_rlz_rekening_zonder_code_geen_voorstel_maar_wel_rij(self) -> None:
        [rij] = odoo_mapping.bepaal_grootboek_voorstel([_rlz_rek(RLZ_GB_ONBEKEND, None, None)], ODOO_GB)
        assert rij.voorstel is None and rij.rlz.rlz_id == RLZ_GB_ONBEKEND

    def test_geen_odoo_lijst_geen_voorstel(self) -> None:
        [rij] = odoo_mapping.bepaal_grootboek_voorstel([_rlz_rek(RLZ_GB_4808, "4808")], [])
        assert rij.voorstel is None


class TestBtwVoorstel:
    def test_gelijk_percentage_precies_een_kandidaat(self) -> None:
        [rij] = odoo_mapping.bepaal_btw_voorstel([_rlz_tarief(RLZ_BTW_21, "NL, Hoog Tarief", "0.2100")], ODOO_BTW)
        assert rij.voorstel is not None and rij.voorstel.odoo_id == 21 and rij.reden == "tarief"

    def test_meerdere_odoo_tarieven_met_zelfde_percentage_geen_gok(self) -> None:
        odoo = [*ODOO_BTW, _odoo_tarief(24, "21% S", "0.21")]
        [rij] = odoo_mapping.bepaal_btw_voorstel([_rlz_tarief(RLZ_BTW_21, "NL, Hoog Tarief", "0.21")], odoo)
        assert rij.voorstel is None and rij.reden is None  # favoriet weegt niet mee

    def test_nul_procent_en_vrijgesteld_naar_synthetisch_geen_btw(self) -> None:
        rijen = odoo_mapping.bepaal_btw_voorstel(
            [
                _rlz_tarief(RLZ_BTW_0, "NL, Nul tarief", "0"),
                _rlz_tarief(uuid.uuid4(), "NL, Geen BTW (Vrijgesteld)", "0", vrijgesteld=True),
            ],
            ODOO_BTW,
        )
        assert all(r.voorstel is not None and r.voorstel.odoo_id == GEEN_BTW_ODOO_ID for r in rijen)
        assert all(r.voorstel.synthetisch for r in rijen)  # type: ignore[union-attr]

    def test_verlegd_naar_odoo_verlegd_tarief(self) -> None:
        [rij] = odoo_mapping.bepaal_btw_voorstel(
            [_rlz_tarief(RLZ_BTW_VERLEGD, "NL, BTW verlegd (hoog)", "0", verlegd=True)], ODOO_BTW
        )
        assert rij.voorstel is not None and rij.voorstel.odoo_id == 22 and rij.voorstel.verlegd

    def test_verlegd_meerdere_kandidaten_beslist_percentage_in_naam(self) -> None:
        odoo = [*ODOO_BTW, _odoo_tarief(25, "9% R", "0.09", verlegd=True)]
        [zonder, met] = odoo_mapping.bepaal_btw_voorstel(
            [
                _rlz_tarief(RLZ_BTW_VERLEGD, "NL, BTW verlegd (hoog)", "0", verlegd=True),
                _rlz_tarief(uuid.uuid4(), "BTW verlegd 21%", "0", verlegd=True),
            ],
            odoo,
        )
        assert zonder.voorstel is None  # twee verlegd-tarieven, geen percentage bekend → mens kiest
        assert met.voorstel is not None and met.voorstel.odoo_id == 22

    def test_onbekend_percentage_geen_voorstel(self) -> None:
        [rij] = odoo_mapping.bepaal_btw_voorstel([_rlz_tarief(uuid.uuid4(), None, None)], ODOO_BTW)  # type: ignore[arg-type]
        assert rij.voorstel is None


# --------------------------------------------------------------------------- vertaling + engine


def _obs(gb: uuid.UUID, *, btw: uuid.UUID | None, bron: str, dag: int, sleutel: str | None = None) -> Observatie:
    return Observatie(
        regel_sleutel=sleutel, gb_id=gb, btw_id=btw, project_id=uuid.uuid4(), bron=bron, bron_datum=date(2026, 8, dag)
    )


ODOO_GB_LOKAAL = odoo_uuid(COMPANY, "account.account", 11)
ODOO_BTW_LOKAAL = odoo_uuid(COMPANY, "account.tax", 21)
MAPPING = odoo_mapping.RekeningMapping(grootboek={RLZ_GB_4808: ODOO_GB_LOKAAL}, btw={RLZ_BTW_21: ODOO_BTW_LOKAAL})


class TestVertaalObservaties:
    def test_vertaalt_gb_en_btw_project_wordt_none_rest_intact(self) -> None:
        o = _obs(RLZ_GB_4808, btw=RLZ_BTW_21, bron="app", dag=3, sleutel="diesel")
        [v] = odoo_mapping.vertaal_observaties([o], MAPPING)
        assert v.gb_id == ODOO_GB_LOKAAL and v.btw_id == ODOO_BTW_LOKAAL and v.project_id is None
        assert (v.bron, v.bron_datum, v.regel_sleutel) == ("app", date(2026, 8, 3), "diesel")

    def test_niet_vertaalbare_btw_wordt_none_en_odoo_era_observatie_blijft(self) -> None:
        rlz = _obs(RLZ_GB_4808, btw=RLZ_BTW_VERLEGD, bron="rlz_seed", dag=1)
        odoo = _obs(ODOO_GB_LOKAAL, btw=ODOO_BTW_LOKAAL, bron="app", dag=20)
        v_rlz, v_odoo = odoo_mapping.vertaal_observaties([rlz, odoo], MAPPING)
        assert v_rlz.gb_id == ODOO_GB_LOKAAL and v_rlz.btw_id is None
        assert v_odoo is odoo  # ongewijzigd, ook het project

    def test_lege_mapping_is_identiteit(self) -> None:
        obs = [_obs(RLZ_GB_4808, btw=RLZ_BTW_21, bron="app", dag=3)]
        assert odoo_mapping.vertaal_observaties(obs, odoo_mapping.RekeningMapping()) is obs

    def test_engine_app_bevestigd_blijft_en_geen_gesplitste_stem(self) -> None:
        """Het contract-hart: een groen app-bevestigd RLZ-geheugen blijft groen op de vertaalde Odoo-rekening,
        en een nieuwe Odoo-observatie op diezelfde rekening telt bij dezelfde stem (geen split → geen oranje)."""
        rlz_app = _obs(RLZ_GB_4808, btw=RLZ_BTW_21, bron="app", dag=1)
        voor = bepaal_voorstel([rlz_app], vandaag=date(2026, 9, 4))
        assert voor.gb.waarde == RLZ_GB_4808 and voor.gb.app_bevestigd and not voor.gb.oranje

        na = bepaal_voorstel(odoo_mapping.vertaal_observaties([rlz_app], MAPPING), vandaag=date(2026, 9, 4))
        assert na.gb.waarde == ODOO_GB_LOKAAL and na.gb.app_bevestigd and not na.gb.oranje
        assert na.gb.confidence == voor.gb.confidence == 1.0
        assert na.btw.waarde == ODOO_BTW_LOKAAL and na.btw.app_bevestigd

        odoo_app = _obs(ODOO_GB_LOKAAL, btw=ODOO_BTW_LOKAAL, bron="app", dag=30)
        samen = bepaal_voorstel(
            odoo_mapping.vertaal_observaties([rlz_app, odoo_app], MAPPING), vandaag=date(2026, 9, 4)
        )
        assert samen.gb.waarde == ODOO_GB_LOKAAL and samen.gb.telling == 2 and samen.gb.confidence == 1.0
        assert "gesplitste stem" not in (samen.gb.reden or "")

    def test_regel_observaties_vertaald(self) -> None:
        r = RegelObservatie(regel_sleutel="diesel", gb_id=RLZ_GB_4808, bron="app", bron_datum=date(2026, 8, 1))
        ander = RegelObservatie(regel_sleutel="huur", gb_id=RLZ_GB_4000, bron="app", bron_datum=date(2026, 8, 1))
        v, w = odoo_mapping.vertaal_regel_observaties([r, ander], MAPPING)
        assert v.gb_id == ODOO_GB_LOKAAL and v.regel_sleutel == "diesel" and v.bron == "app"
        assert w is ander


# --------------------------------------------------------------------------- validatie (puur)


class TestValideerMapping:
    def _voorstel(self):
        gb = odoo_mapping.bepaal_grootboek_voorstel(
            [_rlz_rek(RLZ_GB_4808, "4808"), _rlz_rek(RLZ_GB_4000, "4000")], ODOO_GB
        )
        btw = odoo_mapping.bepaal_btw_voorstel([_rlz_tarief(RLZ_BTW_21, "NL, Hoog Tarief", "0.21")], ODOO_BTW)
        return gb, btw

    def test_ontbrekende_rij_is_onvolledig_en_noemt_aantallen(self) -> None:
        gb, btw = self._voorstel()
        with pytest.raises(odoo_service.OdooKoppelFout, match="onvolledig: 1 grootboekrekening\\(en\\) en 1 btw"):
            odoo_mapping.valideer_mapping(
                grootboek=gb,
                btw=btw,
                odoo_grootboek=ODOO_GB,
                odoo_btw=ODOO_BTW,
                invoer=odoo_mapping.MappingInvoer(grootboek=[odoo_mapping.MappingRijInvoer(RLZ_GB_4808, 10)]),
            )

    def test_onbekend_odoo_id_telt_als_ontbrekend(self) -> None:
        gb, btw = self._voorstel()
        with pytest.raises(odoo_service.OdooKoppelFout, match="onvolledig"):
            odoo_mapping.valideer_mapping(
                grootboek=gb,
                btw=btw,
                odoo_grootboek=ODOO_GB,
                odoo_btw=ODOO_BTW,
                invoer=odoo_mapping.MappingInvoer(
                    grootboek=[
                        odoo_mapping.MappingRijInvoer(RLZ_GB_4808, 10),
                        odoo_mapping.MappingRijInvoer(RLZ_GB_4000, 999),
                    ],
                    btw=[odoo_mapping.MappingRijInvoer(RLZ_BTW_21, 21)],
                ),
            )

    def test_invoer_voor_niet_in_gebruik_rij_geweigerd(self) -> None:
        gb, btw = self._voorstel()
        with pytest.raises(odoo_service.OdooKoppelFout, match="niet in gebruik"):
            odoo_mapping.valideer_mapping(
                grootboek=gb,
                btw=btw,
                odoo_grootboek=ODOO_GB,
                odoo_btw=ODOO_BTW,
                invoer=odoo_mapping.MappingInvoer(grootboek=[odoo_mapping.MappingRijInvoer(uuid.uuid4(), 10)]),
            )

    def test_bron_is_voorstelreden_of_handmatig(self) -> None:
        gb, btw = self._voorstel()
        rijen = odoo_mapping.valideer_mapping(
            grootboek=gb,
            btw=btw,
            odoo_grootboek=ODOO_GB,
            odoo_btw=ODOO_BTW,
            invoer=odoo_mapping.MappingInvoer(
                grootboek=[
                    odoo_mapping.MappingRijInvoer(RLZ_GB_4808, 10),  # = voorstel (zelfde_code)
                    odoo_mapping.MappingRijInvoer(RLZ_GB_4000, 13),  # mens koos anders dan 400000
                ],
                btw=[odoo_mapping.MappingRijInvoer(RLZ_BTW_21, GEEN_BTW_ODOO_ID)],  # mens koos geen-btw
            ),
        )
        per = {(r.soort, r.rlz_id): r for r in rijen}
        assert per[("grootboek", RLZ_GB_4808)].bron == "zelfde_code"
        assert (
            per[("grootboek", RLZ_GB_4000)].bron == "handmatig"
            and per[("grootboek", RLZ_GB_4000)].odoo_code == "700100"
        )
        assert per[("btw", RLZ_BTW_21)].bron == "handmatig" and per[("btw", RLZ_BTW_21)].odoo_id == 0
        assert per[("btw", RLZ_BTW_21)].odoo_lokaal_id == odoo_uuid(COMPANY, "account.tax", 0)

    def test_niets_in_gebruik_lege_mapping_ok(self) -> None:
        assert (
            odoo_mapping.valideer_mapping(grootboek=[], btw=[], odoo_grootboek=ODOO_GB, odoo_btw=ODOO_BTW, invoer=None)
            == []
        )


# --------------------------------------------------------------------------- DB + endpoints


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "beheerder") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


@pytest.fixture
def odoo_live(monkeypatch: pytest.MonkeyPatch, probe_groen) -> None:
    """Live Odoo-lijsten (grootboek + btw) zoals `lees_live_odoo_stamgegevens` ze zou teruggeven."""
    monkeypatch.setattr(odoo_mapping, "lees_live_odoo_stamgegevens", lambda **kw: (list(ODOO_GB), list(ODOO_BTW)))


@pytest.fixture
def rlz_in_gebruik(administratie_id, gescoopte_gebruiker, tmp_path) -> uuid.UUID:
    """RLZ-verleden: cache-rijen 4808/4000 + 21 %/verlegd, twee app-observaties (4808 + 21 %, één mét en één zonder
    regelsleutel), een seed-observatie op een rekening die niet meer in de cache staat, en een OPEN boekvoorstel
    (te_controleren) met regel op 4000 + 21 % én een regel op de verlegd-code. Retourneert het open document."""
    with scoped_session(administratie_id) as session:
        for lid, code, naam in ((RLZ_GB_4808, "4808", "Huur materieel"), (RLZ_GB_4000, "4000", "Inkoop")):
            session.add(
                Grootboekrekening(
                    ledger_id=lid,
                    administratie_id=administratie_id,
                    code=code,
                    naam=naam,
                    soort=2,
                    is_totaalrekening=False,
                )
            )
        session.add(
            TaxRateCache(
                id=RLZ_BTW_21,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={"IsRelayed": False, "IsExcempt": False},
            )
        )
        session.add(
            TaxRateCache(
                id=RLZ_BTW_VERLEGD,
                administratie_id=administratie_id,
                naam="NL, BTW verlegd (hoog)",
                percentage=Decimal("0"),
                brondata={"IsRelayed": True, "IsExcempt": False},
            )
        )
        for i, sleutel in enumerate((None, "diesel nen590")):
            session.add(
                BoekingObservatie(
                    id=uuid.uuid4(),
                    administratie_id=administratie_id,
                    vendor_id=VENDOR,
                    regel_sleutel=sleutel,
                    gb_id=RLZ_GB_4808,
                    btw_id=RLZ_BTW_21,
                    project_id=None,
                    bron="app",
                    bron_datum=date(2026, 8, 1 + i),
                )
            )
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vendor_id=VENDOR,
                regel_sleutel=None,
                gb_id=RLZ_GB_ONBEKEND,
                btw_id=None,
                project_id=None,
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
        referentie="OPEN-1",
        factuurdatum=date(2026, 6, 5),
        totaalbedrag=Decimal("121.00"),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=RLZ_GB_4000,
                taxrate_id=RLZ_BTW_21,
                project_id=None,
                netto_bedrag=Decimal("50.00"),
                btw_bedrag=Decimal("10.50"),
                omschrijving="Inkoop A",
            ),
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=RLZ_GB_4000,
                taxrate_id=RLZ_BTW_VERLEGD,
                project_id=None,
                netto_bedrag=Decimal("50.00"),
                btw_bedrag=Decimal("0"),
                omschrijving="Inkoop B verlegd",
            ),
        ],
        regels_samenvoegen=False,
    )
    return document_id


def _volledige_mapping() -> dict:
    return {
        "grootboek": [
            {"rlz_id": str(RLZ_GB_4808), "odoo_id": 10},
            {"rlz_id": str(RLZ_GB_4000), "odoo_id": 12},
            {"rlz_id": str(RLZ_GB_ONBEKEND), "odoo_id": 13},
        ],
        "btw": [{"rlz_id": str(RLZ_BTW_21), "odoo_id": 21}, {"rlz_id": str(RLZ_BTW_VERLEGD), "odoo_id": 22}],
    }


def _mapping_rijen(aid: uuid.UUID) -> list[OdooRekeningMapping]:
    with scoped_session(aid) as session:
        rijen = session.query(OdooRekeningMapping).order_by(OdooRekeningMapping.soort, OdooRekeningMapping.rlz_id).all()
        session.expunge_all()
        return rijen


def _audit(admin_engine: Engine, actie: str, aid: uuid.UUID) -> list:
    with admin_engine.connect() as conn:
        return list(
            conn.execute(
                text(
                    "SELECT oude_waarde::text, nieuwe_waarde::text FROM platform.audit_event "
                    "WHERE actie = :actie AND record_id = :id ORDER BY tijdstip"
                ),
                {"actie": actie, "id": aid},
            )
        )


class TestVoorbereiden:
    def test_200_in_gebruik_rijen_met_tellingen_voorstel_en_odoo_lijsten(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik
    ) -> None:
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap/voorbereiden",
            json={"odoo_url": URL, "api_key": KEY, "company_id": COMPANY},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert body["company_naam"] == "Universal Steigerbouw" and body["probe"]["verbinding"] == "ok"
        assert KEY not in r.text
        gb = {row["rlz_id"]: row for row in body["grootboek"]}
        assert set(gb) == {str(RLZ_GB_4808), str(RLZ_GB_4000), str(RLZ_GB_ONBEKEND)}
        assert gb[str(RLZ_GB_4808)] == {
            "rlz_id": str(RLZ_GB_4808),
            "rlz_code": "4808",
            "rlz_naam": "Huur materieel",
            "in_gebruik_observaties": 2,
            "in_gebruik_open_regels": 0,
            "voorstel_odoo_id": 10,
            "voorstel_odoo_code": "4808",
            "voorstel_odoo_naam": "Huur materieel (oud)",
            "reden": "zelfde_code",
        }
        assert (
            gb[str(RLZ_GB_4000)]["in_gebruik_open_regels"] == 2 and gb[str(RLZ_GB_4000)]["in_gebruik_observaties"] == 0
        )
        assert gb[str(RLZ_GB_4000)]["voorstel_odoo_id"] == 12 and gb[str(RLZ_GB_4000)]["reden"] == "code_verlengd"
        onbekend = gb[str(RLZ_GB_ONBEKEND)]
        assert onbekend["rlz_code"] is None and onbekend["voorstel_odoo_id"] is None and onbekend["reden"] is None
        assert onbekend["in_gebruik_observaties"] == 1  # tóch te mappen
        # Volgorde: op code, onbekende achteraan.
        assert [row["rlz_code"] for row in body["grootboek"]] == ["4000", "4808", None]

        btw = {row["rlz_id"]: row for row in body["btw"]}
        assert btw[str(RLZ_BTW_21)]["voorstel_odoo_id"] == 21 and btw[str(RLZ_BTW_21)]["reden"] == "tarief"
        assert Decimal(btw[str(RLZ_BTW_21)]["rlz_percentage"]) == Decimal("0.21")  # fractie, zoals de cache
        assert btw[str(RLZ_BTW_21)]["verlegd"] is False
        assert (
            btw[str(RLZ_BTW_21)]["in_gebruik_observaties"] == 2 and btw[str(RLZ_BTW_21)]["in_gebruik_open_regels"] == 1
        )
        assert btw[str(RLZ_BTW_VERLEGD)]["voorstel_odoo_id"] == 22 and btw[str(RLZ_BTW_VERLEGD)]["verlegd"] is True

        assert [o["code"] for o in body["odoo_grootboek"]] == ["4808", "480800", "400000", "700100"]
        synth = next(o for o in body["odoo_btw"] if o["synthetisch"])
        assert synth["odoo_id"] == 0 and synth["percentage"] == "0"
        assert body["telling"] == {
            "grootboek_totaal": 3,
            "grootboek_met_voorstel": 2,
            "btw_totaal": 2,
            "btw_met_voorstel": 2,
        }
        # Niets persistent: geen koppeling, geen mapping-rijen, backend nog rlz.
        assert _mapping_rijen(administratie_id) == []

    def test_lege_administratie_geeft_lege_lijsten(self, administratie_id, beheerder_id, odoo_live) -> None:
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap/voorbereiden",
            json={"odoo_url": URL, "api_key": KEY, "company_id": COMPANY},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
        assert r.json()["grootboek"] == [] and r.json()["btw"] == []
        assert r.json()["telling"]["grootboek_totaal"] == 0

    def test_probe_rood_422_met_rapport(self, administratie_id, beheerder_id, monkeypatch) -> None:
        from tests.odoo.test_router import _rode_probe

        monkeypatch.setattr(odoo_service, "probe_voor", lambda **kw: _rode_probe())
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap/voorbereiden",
            json={"odoo_url": URL, "api_key": KEY, "company_id": COMPANY},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 422, r.text
        assert "niet groen" in r.json()["detail"]["bericht"]
        assert r.json()["detail"]["rapport"]["account.move:write"].startswith("geen schrijfrecht")

    def test_voorvalidatie_al_odoo_422(self, administratie_id, beheerder_id, odoo_live, sync_gefaked) -> None:
        assert _overstap(administratie_id, beheerder_id).status_code == 201
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap/voorbereiden",
            json={"odoo_url": URL, "api_key": KEY, "company_id": COMPANY},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 422 and "boekt al in Odoo" in r.text

    def test_rolpoorten(self, administratie_id, gescoopte_gebruiker) -> None:
        pad = f"/administraties/{administratie_id}/odoo/overstap/voorbereiden"
        body = {"odoo_url": URL, "api_key": KEY, "company_id": COMPANY}
        assert client.post(pad, json=body).status_code == 401
        assert client.post(pad, json=body, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code == 403
        assert client.get(f"/administraties/{administratie_id}/odoo/mapping").status_code == 401
        assert (
            client.get(
                f"/administraties/{administratie_id}/odoo/mapping",
                headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
            ).status_code
            == 403
        )


class TestOverstapMetMapping:
    def test_zonder_mapping_bij_in_gebruik_rijen_422_niets_opgeslagen(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik, sync_gefaked, admin_engine: Engine
    ) -> None:
        r = _overstap(administratie_id, beheerder_id)  # mapping leeg
        assert r.status_code == 422, r.text
        assert "onvolledig: 3 grootboekrekening(en) en 2 btw-tarief(en)" in r.json()["detail"]["bericht"]
        assert "niets opgeslagen" in r.json()["detail"]["bericht"]
        with admin_engine.connect() as conn:
            backend = conn.execute(
                text("SELECT boekhoud_backend FROM platform.administratie WHERE id = :id"), {"id": administratie_id}
            ).scalar_one()
        assert backend == "rlz" and _mapping_rijen(administratie_id) == [] and sync_gefaked == []

    def test_mapping_zonder_veld_is_422(self, administratie_id, beheerder_id, odoo_live) -> None:
        r = client.post(
            f"/administraties/{administratie_id}/odoo/overstap",
            json={"odoo_url": URL, "api_key": KEY, "company_id": COMPANY, "overgangsdatum": OVERGANG.isoformat()},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 422

    def test_met_mapping_201_rijen_bron_audit_en_vertaald_geheugen(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik, sync_gefaked, admin_engine: Engine
    ) -> None:
        # Vóór de overstap: het geheugen wijst naar de RLZ-rekening (leverancier-stem gesplitst door de seed-
        # observatie op de onbekende rekening — dat blijft ná de vertaling exact zo: geen nieuwe split).
        voor = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert voor.gb.waarde == RLZ_GB_4808 and voor.gb.app_bevestigd and voor.gb.telling == 2

        r = _overstap(administratie_id, beheerder_id, mapping=_volledige_mapping())
        assert r.status_code == 201, r.text
        assert sync_gefaked == [administratie_id]

        rijen = _mapping_rijen(administratie_id)
        assert len(rijen) == 5 and all(rij.versie == 1 and rij.bevestigd_door == beheerder_id for rij in rijen)
        per = {(rij.soort, rij.rlz_id): rij for rij in rijen}
        assert (
            per[("grootboek", RLZ_GB_4808)].bron == "zelfde_code"
            and per[("grootboek", RLZ_GB_4808)].odoo_code == "4808"
        )
        assert (
            per[("grootboek", RLZ_GB_4000)].bron == "code_verlengd"
            and per[("grootboek", RLZ_GB_4000)].rlz_naam == "Inkoop"
        )
        assert (
            per[("grootboek", RLZ_GB_ONBEKEND)].bron == "handmatig"
            and per[("grootboek", RLZ_GB_ONBEKEND)].rlz_code is None
        )
        assert per[("btw", RLZ_BTW_21)].bron == "tarief" and per[("btw", RLZ_BTW_21)].odoo_naam == "21%"
        assert per[("btw", RLZ_BTW_VERLEGD)].bron == "tarief" and per[("btw", RLZ_BTW_VERLEGD)].odoo_id == 22
        assert per[("grootboek", RLZ_GB_4808)].odoo_lokaal_id == odoo_uuid(COMPANY, "account.account", 10)

        audit = _audit(admin_engine, "odoo_rekening_mapping_vastgelegd", administratie_id)
        assert len(audit) == 1
        assert '"grootboek": 3' in audit[0][1] and '"btw": 2' in audit[0][1] and "4808→4808" in audit[0][1]
        assert '"handmatig": 1' in audit[0][1] and KEY not in audit[0][1]

        # Ná de overstap: het geheugen vertaalt naar de Odoo-rekening, app-bevestigd blijft, confidence gelijk.
        na = geheugen_service.voorstel_voor(administratie_id=administratie_id, vendor_id=VENDOR)
        assert na.gb.waarde == odoo_uuid(COMPANY, "account.account", 10)
        assert na.gb.app_bevestigd and na.gb.telling == 2 and na.gb.confidence == voor.gb.confidence
        assert na.gb.reden == voor.gb.reden  # zelfde oranje-redenen — de vertaling voegt er nooit een toe
        assert na.btw.waarde == odoo_uuid(COMPANY, "account.tax", 21) and na.btw.app_bevestigd
        assert na.project.waarde is None
        # Regel-niveau: idem via de regel-omschrijving.
        regel = geheugen_service.voorstel_voor(
            administratie_id=administratie_id, vendor_id=VENDOR, regel_omschrijving="Diesel NEN590"
        )
        assert regel.gb.waarde == odoo_uuid(COMPANY, "account.account", 10) and regel.gb.app_bevestigd
        assert not regel.gb.oranje  # regel-niveau verfijnt de leverancier-split: eenduidig groen op de Odoo-rekening

    def test_alles_of_niets_bij_een_onbekende_odoo_id(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik, sync_gefaked
    ) -> None:
        mapping = _volledige_mapping()
        mapping["btw"][0]["odoo_id"] = 999
        r = _overstap(administratie_id, beheerder_id, mapping=mapping)
        assert r.status_code == 422 and "onvolledig: 0 grootboekrekening(en) en 1 btw-tarief(en)" in r.text
        assert _mapping_rijen(administratie_id) == [] and sync_gefaked == []


class TestMappingStandEnCorrectie:
    def _overgestapt(self, aid: uuid.UUID, beheerder: uuid.UUID) -> None:
        assert _overstap(aid, beheerder, mapping=_volledige_mapping()).status_code == 201
        # De (gefakete) sync zou de cache + id-koppelingen vullen; hier handmatig twee Odoo-rijen zodat GET
        # en PUT de keuzelijst/validatie kunnen tonen resp. toetsen.
        with scoped_session(aid) as session:
            for odoo_id, code, naam in ((12, "400000", "Inkoop"), (13, "700100", "Omzet")):
                lokaal = odoo_uuid(COMPANY, "account.account", odoo_id)
                session.add(
                    Grootboekrekening(
                        ledger_id=lokaal, administratie_id=aid, code=code, naam=naam, soort=2, is_totaalrekening=False
                    )
                )
                session.add(
                    OdooIdKoppeling(
                        administratie_id=aid,
                        model="account.account",
                        odoo_id=odoo_id,
                        lokaal_id=lokaal,
                        naam=f"{code} {naam}",
                    )
                )
            lokaal_btw = odoo_uuid(COMPANY, "account.tax", 23)
            session.add(
                TaxRateCache(
                    id=lokaal_btw,
                    administratie_id=aid,
                    naam="9%",
                    percentage=Decimal("0.09"),
                    brondata={"IsRelayed": False, "IsFavorite": True, "backend": "odoo"},
                )
            )
            session.add(
                OdooIdKoppeling(administratie_id=aid, model="account.tax", odoo_id=23, lokaal_id=lokaal_btw, naam="9%")
            )
            # De RLZ-rijen zijn ná de sync 'verdwenen' — horen niet in de Odoo-keuzelijst.
            for g in session.query(Grootboekrekening).filter(
                Grootboekrekening.ledger_id.in_([RLZ_GB_4808, RLZ_GB_4000])
            ):
                g.verdwenen_uit_bron_op = datetime.now(UTC)

    def test_get_zonder_koppeling_404(self, administratie_id, beheerder_id) -> None:
        r = client.get(f"/administraties/{administratie_id}/odoo/mapping", headers=_bearer(beheerder_id))
        assert r.status_code == 404

    def test_get_stand_en_put_correctie_versie_2_met_audit(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik, sync_gefaked, admin_engine: Engine
    ) -> None:
        self._overgestapt(administratie_id, beheerder_id)
        r = client.get(f"/administraties/{administratie_id}/odoo/mapping", headers=_bearer(beheerder_id))
        assert r.status_code == 200, r.text
        stand = r.json()
        assert [row["rlz_code"] for row in stand["grootboek"]] == ["4000", "4808", None]
        rij_4000 = stand["grootboek"][0]
        assert rij_4000["odoo_id"] == 12 and rij_4000["odoo_code"] == "400000" and rij_4000["versie"] == 1
        assert rij_4000["bron"] == "code_verlengd" and rij_4000["bevestigd_door_naam"] == "Test-Beheerder"
        assert rij_4000["soort"] == "grootboek" and rij_4000["bevestigd_op"] is not None
        assert {row["odoo_id"] for row in stand["btw"]} == {21, 22}
        assert [o["code"] for o in stand["odoo_grootboek"]] == ["400000", "700100"]  # alleen Odoo-rijen uit de cache
        assert stand["odoo_btw"] == [
            {
                "odoo_id": 23,
                "lokaal_id": str(odoo_uuid(COMPANY, "account.tax", 23)),
                "naam": "9%",
                "percentage": "0.09",
                "verlegd": False,
                "synthetisch": False,
            }
        ]
        assert stand["laatst_bevestigd_door_naam"] == "Test-Beheerder" and stand["laatst_bevestigd_op"] is not None

        # Correctie: 4000 → 700100 (odoo_id 13) = versie 2, bron handmatig, audit oud→nieuw.
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/grootboek/{RLZ_GB_4000}",
            json={"odoo_id": 13},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
        rij = next(row for row in r.json()["grootboek"] if row["rlz_id"] == str(RLZ_GB_4000))
        assert (
            rij["odoo_id"] == 13 and rij["odoo_code"] == "700100" and rij["versie"] == 2 and rij["bron"] == "handmatig"
        )
        assert rij["rlz_code"] == "4000" and rij["rlz_naam"] == "Inkoop"
        # Beide versies bestaan (append-only); de geldende vertaalt het geheugen.
        alle = [x for x in _mapping_rijen(administratie_id) if x.rlz_id == RLZ_GB_4000]
        assert sorted(x.versie for x in alle) == [1, 2]
        with scoped_session(administratie_id) as session:
            geldend = odoo_mapping.geldende_mapping(session, administratie_id)
        assert geldend.grootboek[RLZ_GB_4000] == odoo_uuid(COMPANY, "account.account", 13)
        audit = _audit(admin_engine, "odoo_rekening_mapping_gecorrigeerd", administratie_id)
        assert len(audit) == 1 and '"odoo_id": 12' in audit[0][0] and '"odoo_id": 13' in audit[0][1]
        assert '"versie": 2' in audit[0][1]

        # Btw-correctie naar synthetisch geen-btw (0) en naar een gesynct tarief.
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/btw/{RLZ_BTW_21}",
            json={"odoo_id": 0},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
        rij = next(row for row in r.json()["btw"] if row["rlz_id"] == str(RLZ_BTW_21))
        assert rij["odoo_id"] == 0 and rij["odoo_naam"] == "Geen btw (0%)" and rij["versie"] == 2
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/btw/{RLZ_BTW_21}",
            json={"odoo_id": 23},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
        rij = next(row for row in r.json()["btw"] if row["rlz_id"] == str(RLZ_BTW_21))
        assert rij["odoo_id"] == 23 and rij["odoo_naam"] == "9%" and rij["versie"] == 3

    def test_put_onbekende_odoo_id_soort_of_nul_op_grootboek_422(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik, sync_gefaked
    ) -> None:
        self._overgestapt(administratie_id, beheerder_id)
        h = _bearer(beheerder_id)
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/grootboek/{RLZ_GB_4000}", json={"odoo_id": 999}, headers=h
        )
        assert r.status_code == 422 and "niet bekend in de gesyncte stamgegevens" in r.text
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/grootboek/{RLZ_GB_4000}", json={"odoo_id": 0}, headers=h
        )
        assert r.status_code == 422 and "alleen voor btw" in r.text
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/project/{RLZ_GB_4000}", json={"odoo_id": 12}, headers=h
        )
        assert r.status_code == 422 and "Onbekende mapping-soort" in r.text
        r = client.put(f"/administraties/{administratie_id}/odoo/mapping/grootboek/{RLZ_GB_4000}", json={}, headers=h)
        assert r.status_code == 422
        # Niets gewijzigd: alle rijen nog versie 1.
        assert all(x.versie == 1 for x in _mapping_rijen(administratie_id))

    def test_put_zonder_koppeling_404(self, administratie_id, beheerder_id) -> None:
        r = client.put(
            f"/administraties/{administratie_id}/odoo/mapping/grootboek/{RLZ_GB_4000}",
            json={"odoo_id": 12},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 404


class TestOvergangsdatumGeblokkeerd:
    """C1: een verschuiving vóórbij al in Odoo geboekte facturen is een 409 mét aantal + oudste boekstuk."""

    def _odoo_boeking(self, aid: uuid.UUID, document_id: uuid.UUID, *, naam: str, state: str = "posted") -> None:
        with scoped_session(aid) as session:
            session.add(
                OdooDocumentKoppeling(
                    administratie_id=aid,
                    document_id=document_id,
                    boek_cyclus=0,
                    soort="boeking",
                    odoo_move_id=3049,
                    odoo_naam=naam,
                    odoo_move_type="in_invoice",
                    company_id=COMPANY,
                    state=state,
                )
            )

    def test_409_noemt_aantal_en_oudste_boekstuk_en_wijzigt_niets(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik, sync_gefaked, admin_engine: Engine
    ) -> None:
        assert _overstap(administratie_id, beheerder_id, mapping=_volledige_mapping()).status_code == 201
        # rlz_in_gebruik = het document mét factuurdatum 05-06-2026; nu "geboekt in Odoo".
        self._odoo_boeking(administratie_id, rlz_in_gebruik, naam="BILL/2026/06/0001")
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum",
            json={"overgangsdatum": "2026-07-01"},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 409, r.text
        bericht = r.json()["detail"]["bericht"]
        assert "1 factuur" in bericht and "BILL/2026/06/0001 op 05-06-2026 is al in Odoo geboekt" in bericht
        assert "kies een datum op of vóór 05-06-2026 of boek die factuur tegen" in bericht
        with scoped_session(None) as session:
            from app.odoo.models import OdooKoppeling

            assert session.get(OdooKoppeling, administratie_id).overgangsdatum == OVERGANG  # ongewijzigd
        assert _audit(admin_engine, "odoo_overgangsdatum_gewijzigd", administratie_id) == []

        # Op de factuurdatum zelf mag (adapter-poort: factuurdatum ≥ overgangsdatum), én eerder.
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum",
            json={"overgangsdatum": "2026-06-05"},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
        assert r.json()["overgangsdatum"] == "2026-06-05"

    def test_gecancelde_odoo_boeking_blokkeert_niet(
        self, administratie_id, beheerder_id, odoo_live, rlz_in_gebruik, sync_gefaked
    ) -> None:
        assert _overstap(administratie_id, beheerder_id, mapping=_volledige_mapping()).status_code == 201
        self._odoo_boeking(administratie_id, rlz_in_gebruik, naam="BILL/2026/06/0002", state="cancel")
        r = client.put(
            f"/administraties/{administratie_id}/odoo/overgangsdatum",
            json={"overgangsdatum": "2026-10-01"},
            headers=_bearer(beheerder_id),
        )
        assert r.status_code == 200, r.text
