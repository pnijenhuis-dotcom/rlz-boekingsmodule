# ruff: noqa: F811 — pytest-fixtures als parameters
"""Instelling activa: defaults zonder rij, Beheerder-PUT mét validatie + audit oud→nieuw, RLZ-grens verversen,
register-probe
(403 = recht ontbreekt, zichtbaar), sync-hook ná de Ledgers-sync."""

from __future__ import annotations

import uuid
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.activa import instelling as instelling_service
from app.activa.models import ActivaInstelling
from app.db.session import scoped_session
from app.rlz.client import RlzApiError
from app.sync import service as sync_service
from tests.activa.conftest import GB_0108, audit_acties
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.sync.conftest import FakeRlzClient


class TestZetten:
    def test_upsert_met_audit_oud_naar_nieuw(
        self, stamgegevens: None, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            stand = instelling_service.zet(
                session,
                administratie_id=administratie_id,
                actor_id=beheerder_id,
                automatisch_aanmaken_ingeschakeld=True,
                activeringsgrens="1000",
                termijnen={"inventaris": 120},
                afschrijving_ledgers={"inventaris": str(GB_0108), "machines": None},
            )
        assert stand.automatisch_aanmaken_ingeschakeld is True and stand.activeringsgrens == Decimal("1000.00")
        assert stand.termijnen == {"inventaris": 120} and stand.afschrijving_ledgers == {"inventaris": GB_0108}
        assert audit_acties(admin_engine, tabel="activa_instelling") == ["activa_instelling_gewijzigd"]
        with admin_engine.connect() as conn:
            oud, nieuw = conn.execute(
                text(
                    "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                    "WHERE actie = 'activa_instelling_gewijzigd'"
                )
            ).one()
        assert oud["automatisch_aanmaken_ingeschakeld"] is False and oud["activeringsgrens"] == "450.00"
        assert nieuw["afschrijving_ledgers"] == {"inventaris": str(GB_0108)} and nieuw["termijnen"] == {
            "inventaris": 120
        }
        # Ongewijzigd opnieuw zetten = geen tweede audit-regel.
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            instelling_service.zet(
                session,
                administratie_id=administratie_id,
                actor_id=beheerder_id,
                automatisch_aanmaken_ingeschakeld=True,
                activeringsgrens="1000.00",
                termijnen={"inventaris": 120},
                afschrijving_ledgers={"inventaris": str(GB_0108)},
            )
        assert audit_acties(admin_engine, tabel="activa_instelling") == ["activa_instelling_gewijzigd"]

    @pytest.mark.parametrize(
        ("velden", "fout"),
        [
            ({"activeringsgrens": "-1"}, "≥ 0"),
            ({"activeringsgrens": "abc"}, "geen bedrag"),
            ({"termijnen": {"inventaris": 13}}, "veelvoud van 12"),
            ({"termijnen": {"inventaris": 612}}, "12..600"),
            ({"termijnen": {"fietsen": 60}}, "onbekende categorie"),
            ({"afschrijving_ledgers": {"fietsen": "00000000-0000-0000-0000-000000000001"}}, "onbekende categorie"),
            (
                {"afschrijving_ledgers": {"inventaris": "00000000-0000-0000-0000-000000000001"}},
                "geen rekening van deze administratie",
            ),
            ({"afschrijving_ledgers": {"inventaris": "geen-uuid"}}, "geen geldig id"),
        ],
    )
    def test_validatie(
        self, stamgegevens: None, administratie_id: uuid.UUID, beheerder_id: uuid.UUID, velden: dict, fout: str
    ) -> None:
        basis = dict(
            automatisch_aanmaken_ingeschakeld=False, activeringsgrens="450", termijnen={}, afschrijving_ledgers={}
        )
        basis.update(velden)
        with (
            scoped_session(administratie_id, actor_id=beheerder_id) as session,
            pytest.raises(instelling_service.OngeldigeInstelling, match=fout),
        ):
            instelling_service.zet(session, administratie_id=administratie_id, actor_id=beheerder_id, **basis)


class TestBronLezers:
    def test_rlz_grens_verversen_en_ontbrekend_veld_is_none(
        self, stamgegevens: None, administratie_id: uuid.UUID
    ) -> None:
        client = FakeBoekClient()
        client.administration_settings = [{"FixedAssetAlertAmount": 450.0}]
        with scoped_session(administratie_id) as session:
            assert instelling_service.ververs_rlz_grens(session, client, administratie_id) == Decimal("450.00")
            stand = instelling_service.lees_stand(session, administratie_id)
            assert (
                stand.grens_rlz == Decimal("450.00")
                and stand.grens_rlz_gelezen_op is not None
                and stand.grens_bron == "rlz"
            )
        client.administration_settings = [{"Name": "zonder veld"}]
        with scoped_session(administratie_id) as session:
            assert instelling_service.ververs_rlz_grens(session, client, administratie_id) is None
            assert instelling_service.lees_stand(session, administratie_id).grens_bron == "instelling"

    def test_probe_register_leesbaar_en_403(self, stamgegevens: None, administratie_id: uuid.UUID) -> None:
        client = FakeBoekClient()
        with scoped_session(administratie_id) as session:
            assert instelling_service.probe_register(session, client, administratie_id) is True
            stand = instelling_service.lees_stand(session, administratie_id)
            assert (
                stand.register_leesbaar is True
                and stand.register_fout is None
                and stand.register_geprobeerd_op is not None
            )
        client.fixed_assets_403 = True
        with scoped_session(administratie_id) as session:
            assert instelling_service.probe_register(session, client, administratie_id) is False
            stand = instelling_service.lees_stand(session, administratie_id)
            assert stand.register_leesbaar is False and "recht ontbreekt (403)" in (stand.register_fout or "")

    def test_probe_andere_fout_laat_stand_onbekend_maar_noteert(
        self, stamgegevens: None, administratie_id: uuid.UUID
    ) -> None:
        client = FakeBoekClient(faal_op="fixed_assets")
        with scoped_session(administratie_id) as session:
            assert instelling_service.probe_register(session, client, administratie_id) is False
            stand = instelling_service.lees_stand(session, administratie_id)
            assert stand.register_leesbaar is None and stand.register_fout == "HTTP 500 bij het lezen van FixedAssets"


class _SyncClientMetActiva(FakeRlzClient):
    """Sync-fake (Ledgers/TaxRates/…) + de activa-routes van de FakeBoekClient-vorm."""

    def __init__(self, data: dict, *, fixed_assets_403: bool = False) -> None:
        super().__init__(data)
        self.fixed_assets_403 = fixed_assets_403
        self.settings_gelezen = 0

    def get_fixed_assets(self, params=None):  # noqa: ANN001, ANN201
        if self.fixed_assets_403:
            raise RlzApiError(403, "GET", "FixedAssets", "Forbidden")
        return []

    def get_administration_settings(self):  # noqa: ANN201
        self.settings_gelezen += 1
        return [{"FixedAssetAlertAmount": 500.0}]

    def for_administration(self, admin_id: str):  # noqa: ANN201
        return self


def _ledger(code: str, naam: str, *, soort: int = 3, vast: bool = True) -> dict:
    return {
        "id": str(uuid.uuid4()),
        "AccountNumber": code,
        "Description": naam,
        "AccountType": soort,
        "IsTotalAccount": False,
        "IsFixedAssetAccount": vast,
    }


class TestSyncHook:
    def test_ledgers_sync_schrijft_is_activa_en_leest_grens_plus_probe(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        client = _SyncClientMetActiva(
            {
                "Ledgers": [
                    _ledger("0107", "Inventaris"),
                    _ledger("3000", "Voorraad", vast=True),  # vlag te breed: geen 0xxx → geen activa (STAP-0 a9)
                    _ledger("4400", "Inhuur", soort=2, vast=False),
                ]
            },
            fixed_assets_403=True,
        )
        sync_service.sync_alles_voor_administratie(administratie_id=administratie_id, client=client)
        with admin_engine.connect() as conn:
            rijen = dict(
                conn.execute(
                    text("SELECT code, is_activa FROM platform.grootboekrekening WHERE administratie_id = :a"),
                    {"a": administratie_id},
                ).all()
            )
        assert rijen == {"0107": True, "3000": False, "4400": False}
        assert client.settings_gelezen == 1
        with scoped_session(administratie_id) as session:
            stand = instelling_service.lees_stand(session, administratie_id)
        assert stand.grens_rlz == Decimal("500.00") and stand.register_leesbaar is False

    def test_zonder_mva_rekeningen_geen_extra_calls(self, administratie_id: uuid.UUID) -> None:
        client = _SyncClientMetActiva({"Ledgers": [_ledger("4400", "Inhuur", soort=2, vast=False)]})
        sync_service.sync_alles_voor_administratie(administratie_id=administratie_id, client=client)
        assert client.settings_gelezen == 0
        with scoped_session(administratie_id) as session:
            assert session.get(ActivaInstelling, administratie_id) is None
