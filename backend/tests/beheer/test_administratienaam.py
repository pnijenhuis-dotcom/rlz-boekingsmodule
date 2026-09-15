# ruff: noqa: F811 — pytest-fixtures als parameters
"""Administratienaam — bewerkbaar in de module + volgt de bron (opdracht Peter 15-09; migratie 0144; casus Camping
"Nieuwenhoven" → in Odoo hernoemd naar "Strandpark Zilverduynen" ná het koppelen).

A. `wijzig_naam`: audit oud→nieuw, `naam_bron='mens'`, bezet (hoofdletter-ongevoelig, ook gearchiveerd) = NaamBezet →
   409, leeg = 422, zelfde naam = geen audit.
B. `verwerk_bronnaam`/`volg_bronnaam`: bron ≠ mens → naam volgt mét audit `administratie_naam_gevolgd`; mens → niet
   overschrijven, bronnaam vastgelegd (chip-data); bronnaam bezet → niet gevolgd; onleesbare bron = niets gewijzigd.
   RLZ-pad (`volg_uit_rlz`) leest `Administrations` via de ROOT-vorm; Odoo-pad (`sync_alles_voor_odoo_administratie`)
   leest `res.company.name` via `probe.lees_company_naam` en ververst óók `odoo_koppeling.company_naam`.
C. Backfill: naam == bron → bron gezet; afwijkend → blijft mens; onleesbaar → overgeslagen; dry-run schrijft niets.
D. Router + rol-matrix: naam wijzigen/overnemen = Beheerder-only (boekhouder mét scope 403), DTO-velden in de lijst.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import administratienaam as an
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import gescoopte_gebruiker  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _audit(admin_engine: Engine, actie: str, record_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE actie = :a AND record_id = :r ORDER BY tijdstip"
            ),
            {"a": actie, "r": record_id},
        ).mappings()
        return [dict(r) for r in rijen]


def _rij(admin_engine: Engine, aid: uuid.UUID) -> dict:
    with admin_engine.connect() as conn:
        return dict(
            conn.execute(
                text(
                    "SELECT naam, naam_bron, bron_naam, bron_naam_gezien_op, naam_gevolgd_op, boekhoud_backend "
                    "FROM platform.administratie WHERE id = :id"
                ),
                {"id": aid},
            )
            .mappings()
            .one()
        )


def _tweede_administratie(admin_engine: Engine, naam: str, *, actief: bool = True) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.administratie (id, naam, rlz_admin_id, actief) VALUES (:id, :naam, :rlz, :actief)"
            ),
            {"id": aid, "naam": naam, "rlz": f"rlz-{aid}", "actief": actief},
        )
    return aid


def _zet_bron(admin_engine: Engine, aid: uuid.UUID, bron: str) -> None:
    with admin_engine.begin() as conn:
        conn.execute(text("UPDATE platform.administratie SET naam_bron = :b WHERE id = :id"), {"b": bron, "id": aid})


class TestNaamWijzigen:
    def test_default_is_mens_en_wijzigen_geeft_audit_oud_nieuw(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        assert _rij(admin_engine, administratie_id)["naam_bron"] == "mens"  # DB-default = fail-closed
        _zet_bron(admin_engine, administratie_id, "odoo")
        stand = an.wijzig_naam(
            actor_id=beheerder_id, administratie_id=administratie_id, naam="  Strandpark   Zilverduynen "
        )
        assert (stand.naam, stand.naam_bron) == ("Strandpark Zilverduynen", "mens")
        rij = _rij(admin_engine, administratie_id)
        assert (rij["naam"], rij["naam_bron"]) == ("Strandpark Zilverduynen", "mens")
        audit = _audit(admin_engine, "administratie_naam_gewijzigd", administratie_id)
        assert len(audit) == 1
        assert audit[0]["oude_waarde"] == {"naam": "Scope-test", "naam_bron": "odoo"}
        assert audit[0]["nieuwe_waarde"] == {"naam": "Strandpark Zilverduynen", "naam_bron": "mens", "via": "handmatig"}

    def test_zelfde_naam_opnieuw_is_geen_wijziging(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        an.wijzig_naam(actor_id=beheerder_id, administratie_id=administratie_id, naam="Scope-test")
        assert _audit(admin_engine, "administratie_naam_gewijzigd", administratie_id) == []

    def test_leeg_en_te_lang_zijn_ongeldig(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        with pytest.raises(an.NaamOngeldig):
            an.wijzig_naam(actor_id=beheerder_id, administratie_id=administratie_id, naam="   ")
        with pytest.raises(an.NaamOngeldig):
            an.wijzig_naam(actor_id=beheerder_id, administratie_id=administratie_id, naam="x" * 201)

    def test_bezet_hoofdletter_ongevoelig_ook_bij_gearchiveerde(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _tweede_administratie(admin_engine, "Kempen Facilities", actief=False)
        with pytest.raises(an.NaamBezet) as exc:
            an.wijzig_naam(actor_id=beheerder_id, administratie_id=administratie_id, naam="kempen facilities")
        assert "gearchiveerd" in str(exc.value) and "Kempen Facilities" in str(exc.value)
        assert _rij(admin_engine, administratie_id)["naam"] == "Scope-test"


class TestNaamVolgtDeBron:
    def test_bron_odoo_volgt_met_audit(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        _zet_bron(admin_engine, administratie_id, "odoo")
        uitkomst = an.volg_bronnaam(administratie_id, bron="odoo", bronnaam="Strandpark Zilverduynen")
        assert uitkomst == an.UITKOMST_GEVOLGD
        rij = _rij(admin_engine, administratie_id)
        assert (rij["naam"], rij["naam_bron"], rij["bron_naam"]) == (
            "Strandpark Zilverduynen",
            "odoo",
            "Strandpark Zilverduynen",
        )
        assert rij["naam_gevolgd_op"] is not None and rij["bron_naam_gezien_op"] is not None
        audit = _audit(admin_engine, "administratie_naam_gevolgd", administratie_id)
        assert audit == [
            {
                "oude_waarde": {"naam": "Scope-test", "naam_bron": "odoo"},
                "nieuwe_waarde": {"naam": "Strandpark Zilverduynen", "naam_bron": "odoo", "bron": "odoo"},
            }
        ]
        # Tweede sync met dezelfde naam: gelijk, geen tweede audit.
        assert an.volg_bronnaam(administratie_id, bron="odoo", bronnaam="Strandpark Zilverduynen") == an.UITKOMST_GELIJK
        assert len(_audit(admin_engine, "administratie_naam_gevolgd", administratie_id)) == 1

    def test_mens_naam_wordt_niet_overschreven_maar_bronnaam_vastgelegd(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        uitkomst = an.volg_bronnaam(administratie_id, bron="rlz", bronnaam="Scope-test B.V.")
        assert uitkomst == an.UITKOMST_AFWIJKEND_MENS
        rij = _rij(admin_engine, administratie_id)
        assert (rij["naam"], rij["naam_bron"], rij["bron_naam"]) == ("Scope-test", "mens", "Scope-test B.V.")
        assert _audit(admin_engine, "administratie_naam_gevolgd", administratie_id) == []
        assert an.haal_stand_op(administratie_id).bron_afwijkend is True

    def test_bezette_bronnaam_wordt_niet_gevolgd(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        _zet_bron(admin_engine, administratie_id, "rlz")
        _tweede_administratie(admin_engine, "Universal Verkoop")
        assert an.volg_bronnaam(administratie_id, bron="rlz", bronnaam="universal verkoop") == an.UITKOMST_BEZET
        rij = _rij(admin_engine, administratie_id)
        assert rij["naam"] == "Scope-test" and rij["bron_naam"] == "universal verkoop"

    def test_onleesbare_bron_wijzigt_niets(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        _zet_bron(admin_engine, administratie_id, "rlz")
        assert an.volg_bronnaam(administratie_id, bron="rlz", bronnaam=None) == an.UITKOMST_ONBEKEND
        assert an.volg_bronnaam(administratie_id, bron="rlz", bronnaam="   ") == an.UITKOMST_ONBEKEND
        rij = _rij(admin_engine, administratie_id)
        assert rij["bron_naam"] is None and rij["naam"] == "Scope-test"

    def test_backend_wissel_laat_het_bronlabel_volgen(self, administratie_id: uuid.UUID, admin_engine: Engine) -> None:
        _zet_bron(admin_engine, administratie_id, "rlz")
        assert an.volg_bronnaam(administratie_id, bron="odoo", bronnaam="Scope-test") == an.UITKOMST_GELIJK
        assert _rij(admin_engine, administratie_id)["naam_bron"] == "odoo"

    def test_naam_uit_administrations(self) -> None:
        rijen = [
            {"id": "AbC", "Name": "  Camping   Nieuwenhoven "},
            {"id": "x", "Name": "Andere"},
            {"id": None},
            "rommel",
        ]
        assert an.naam_uit_administrations(rijen, "abc") == "Camping Nieuwenhoven"
        assert an.naam_uit_administrations(rijen, "zzz") is None
        assert an.naam_uit_administrations([{"id": "q", "Name": ""}], "q") is None

    def test_volg_uit_rlz_leest_administrations_via_root_en_faalt_nooit(
        self, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        _zet_bron(admin_engine, administratie_id, "rlz")
        rlz_admin_id = f"rlz-{administratie_id}"

        class _Client:
            def __init__(self) -> None:
                self.paden: list[str] = []

            def root(self):
                return self

            def get(self, pad, params=None):
                self.paden.append(pad)
                return {"value": [{"id": rlz_admin_id, "Name": "Scope-test hernoemd"}]}

            def list_administrations(self):
                return self.get("Administrations").get("value", [])

        c = _Client()
        assert an.volg_uit_rlz(administratie_id, c) == an.UITKOMST_GEVOLGD
        assert c.paden == ["Administrations"]
        assert _rij(admin_engine, administratie_id)["naam"] == "Scope-test hernoemd"

        class _Kapot:
            def list_administrations(self):
                raise RuntimeError("403 Administrations")

        assert an.volg_uit_rlz(administratie_id, _Kapot()) == an.UITKOMST_ONBEKEND

    def test_rlz_client_list_administrations_gaat_altijd_via_root(self) -> None:
        from app.rlz.client import RlzClient

        gezien: list[str] = []

        class _Http:
            def request(self, method, url, **kw):
                gezien.append(url)
                return SimpleNamespace(
                    status_code=200, headers={}, text="{}", json=lambda: {"value": [{"id": "a", "Name": "A"}]}
                )

        gescoped = RlzClient(username="", password="", admin_id="ADMIN-1", client=_Http())  # type: ignore[arg-type]
        assert gescoped.list_administrations() == [{"id": "a", "Name": "A"}]
        assert gezien == ["/Administrations"]  # géén /ADMIN-1/-prefix
        assert gescoped.get("Ledgers") is not None and gezien[-1] == "/ADMIN-1/Ledgers"

    def test_rlz_sync_alles_geeft_naam_uitkomst_mee(
        self, administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from app.sync import service as sync_service

        _zet_bron(admin_engine, administratie_id, "rlz")
        rlz_admin_id = f"rlz-{administratie_id}"

        class _Client:
            def get(self, pad, params=None):
                return {"value": []}

            def list_administrations(self):
                return [{"id": rlz_admin_id, "Name": "Scope-test nieuw"}]

            def close(self) -> None:
                pass

        r = sync_service.sync_alles_voor_administratie(administratie_id=administratie_id, client=_Client())
        assert r.naam == an.UITKOMST_GEVOLGD
        assert _rij(admin_engine, administratie_id)["naam"] == "Scope-test nieuw"

    def test_odoo_sync_volgt_companynaam_en_ververst_koppeling(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.db.session import scoped_session
        from app.odoo import sync as odoo_sync
        from app.odoo.models import OdooKoppeling
        from app.security.envelope import wrap_secret

        ciphertext, wrapped = wrap_secret(b"key")
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "UPDATE platform.administratie SET boekhoud_backend = 'odoo', naam_bron = 'odoo', "
                    "naam = 'Camping Nieuwenhoven' WHERE id = :id"
                ),
                {"id": administratie_id},
            )
        with scoped_session(None, actor_id=beheerder_id) as session:
            session.add(
                OdooKoppeling(
                    administratie_id=administratie_id,
                    odoo_url="https://test.odoo.com",
                    company_id=6,
                    company_naam="Camping Nieuwenhoven",
                    api_key_ciphertext=ciphertext,
                    wrapped_data_key=wrapped,
                    aangemaakt_door=beheerder_id,
                )
            )
        monkeypatch.setattr(
            odoo_sync, "koppeling_voor", lambda aid: SimpleNamespace(company_id=6, analytic_plan_id=None)
        )
        monkeypatch.setattr(odoo_sync, "lees_grootboek", lambda c, v: [])
        monkeypatch.setattr(odoo_sync, "lees_btw", lambda c, v: [])
        monkeypatch.setattr(odoo_sync, "lees_crediteuren", lambda c, v: [])
        monkeypatch.setattr(odoo_sync, "lees_projecten", lambda c, v, plan_id: [])
        monkeypatch.setattr(odoo_sync, "lees_company_naam", lambda c: "Strandpark Zilverduynen")

        r = odoo_sync.sync_alles_voor_odoo_administratie(administratie_id=administratie_id, client=SimpleNamespace())
        assert r.naam == an.UITKOMST_GEVOLGD
        rij = _rij(admin_engine, administratie_id)
        assert (rij["naam"], rij["naam_bron"], rij["bron_naam"]) == (
            "Strandpark Zilverduynen",
            "odoo",
            "Strandpark Zilverduynen",
        )
        with admin_engine.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT company_naam FROM platform.odoo_koppeling WHERE administratie_id = :id"),
                    {"id": administratie_id},
                ).scalar()
                == "Strandpark Zilverduynen"
            )
        assert len(_audit(admin_engine, "administratie_naam_gevolgd", administratie_id)) == 1

    def test_lees_company_naam_is_de_ene_leesbron(self) -> None:
        from app.odoo.client import OdooFout
        from app.odoo.probe import lees_company_naam

        class _Ok:
            company_id = 6

            def read_een(self, model, odoo_id, fields):
                assert (model, odoo_id, fields) == ("res.company", 6, ["name"])
                return {"id": 6, "name": "  Strandpark  Zilverduynen "}

        class _Weg:
            company_id = 6

            def read_een(self, model, odoo_id, fields):
                raise OdooFout(403, "AccessError", "nee", model=model, methode="read")

        assert lees_company_naam(_Ok()) == "Strandpark Zilverduynen"  # type: ignore[arg-type]
        assert lees_company_naam(_Weg()) is None  # type: ignore[arg-type]


class TestOvernemen:
    def test_overnemen_zet_naam_en_houdt_mens(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        with pytest.raises(an.GeenBronnaam):
            an.neem_bronnaam_over(actor_id=beheerder_id, administratie_id=administratie_id)
        an.volg_bronnaam(administratie_id, bron="odoo", bronnaam="Strandpark Zilverduynen")
        stand = an.neem_bronnaam_over(actor_id=beheerder_id, administratie_id=administratie_id)
        assert (stand.naam, stand.naam_bron, stand.bron_afwijkend) == ("Strandpark Zilverduynen", "mens", False)
        audit = _audit(admin_engine, "administratie_naam_gewijzigd", administratie_id)
        assert audit[-1]["nieuwe_waarde"]["via"] == "bron_overgenomen"
        # Een latere sync met dezelfde bronnaam: gelijk, en de bron krijgt NIET stil het stuur terug.
        assert an.volg_bronnaam(administratie_id, bron="odoo", bronnaam="Strandpark Zilverduynen") == an.UITKOMST_GELIJK
        assert _rij(admin_engine, administratie_id)["naam_bron"] == "mens"


class TestBackfill:
    def test_backfill_bron_gezet_blijft_mens_en_overgeslagen(
        self, administratie_id: uuid.UUID, admin_engine: Engine, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        gelijk = administratie_id  # naam Scope-test == bronnaam
        anders = _tweede_administratie(admin_engine, "Camping Nieuwenhoven")
        weg = _tweede_administratie(admin_engine, "Zonder credential")
        al = _tweede_administratie(admin_engine, "Al gezet")
        _zet_bron(admin_engine, al, "rlz")
        bron_per_id = {
            gelijk: ("rlz", "scope-test", ""),
            anders: ("odoo", "Strandpark Zilverduynen", ""),
            weg: ("rlz", None, "geen RLZ-credential"),
        }
        monkeypatch.setattr(an, "lees_bronnaam_live", lambda aid: bron_per_id[aid])

        dry = {
            r.administratie_id: r
            for r in an.backfill_naam_bron(dry_run=True)
            if r.administratie_id in {*bron_per_id, al}
        }
        assert {k: v.uitkomst for k, v in dry.items()} == {
            gelijk: "bron_gezet",
            anders: "blijft_mens",
            weg: "overgeslagen",
            al: "al_gezet",
        }
        assert _rij(admin_engine, gelijk)["naam_bron"] == "mens" and _rij(admin_engine, anders)["bron_naam"] is None

        an.backfill_naam_bron(dry_run=False)
        assert _rij(admin_engine, gelijk)["naam_bron"] == "rlz"
        assert _rij(admin_engine, gelijk)["bron_naam"] == "scope-test"
        rij_anders = _rij(admin_engine, anders)
        assert (rij_anders["naam"], rij_anders["naam_bron"], rij_anders["bron_naam"]) == (
            "Camping Nieuwenhoven",
            "mens",
            "Strandpark Zilverduynen",
        )
        assert _rij(admin_engine, weg)["bron_naam"] is None
        assert len(_audit(admin_engine, "administratie_naam_bron_backfill", gelijk)) == 1
        assert _audit(admin_engine, "administratie_naam_bron_backfill", anders) == []
        # Idempotent: tweede schrijfrun raakt niets meer.
        tweede = {r.administratie_id: r.uitkomst for r in an.backfill_naam_bron(dry_run=False)}
        assert tweede[gelijk] == "al_gezet" and tweede[anders] == "blijft_mens"
        assert len(_audit(admin_engine, "administratie_naam_bron_backfill", gelijk)) == 1

    def test_cli_dry_run_default(
        self, administratie_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from app import cli

        monkeypatch.setattr(an, "lees_bronnaam_live", lambda aid: ("rlz", "Scope-test", ""))
        assert cli.main(["administratie-naam-bron-backfill", "--administratie", str(administratie_id)]) == 0
        uit = capsys.readouterr().out
        assert "DRY-RUN" in uit and "BRON   rlz" in uit
        assert an.haal_stand_op(administratie_id).naam_bron == "mens"


class TestRouter:
    def test_beheerder_wijzigt_en_neemt_over_boekhouder_403(
        self,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        pad = f"/administraties/{administratie_id}/naam"
        assert (
            client.put(pad, json={"naam": "X"}, headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code
            == 403
        )
        assert (
            client.post(f"{pad}-overnemen", headers=_bearer(gescoopte_gebruiker, rol="boekhouding")).status_code == 403
        )
        resp = client.put(pad, json={"naam": "Strandpark Zilverduynen"}, headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200, resp.text
        assert resp.json()["naam"] == "Strandpark Zilverduynen" and resp.json()["naam_bron"] == "mens"
        assert client.put(pad, json={"naam": " "}, headers=_bearer(beheerder_id, rol="beheerder")).status_code == 422
        _tweede_administratie(admin_engine, "Kempen Facilities")
        bezet = client.put(pad, json={"naam": "KEMPEN FACILITIES"}, headers=_bearer(beheerder_id, rol="beheerder"))
        assert bezet.status_code == 409 and "Kempen Facilities" in bezet.json()["detail"]
        geen = client.post(f"{pad}-overnemen", headers=_bearer(beheerder_id, rol="beheerder"))
        assert geen.status_code == 409
        an.volg_bronnaam(administratie_id, bron="odoo", bronnaam="Zilverduynen Strandpark")
        over = client.post(f"{pad}-overnemen", headers=_bearer(beheerder_id, rol="beheerder"))
        assert over.status_code == 200 and over.json()["naam"] == "Zilverduynen Strandpark"
        assert over.json()["bron_afwijkend"] is False

    def test_lijst_dto_draagt_de_naamvelden(
        self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID, admin_engine: Engine
    ) -> None:
        an.volg_bronnaam(administratie_id, bron="rlz", bronnaam="Scope-test B.V.")
        resp = client.get("/instellingen/administraties", headers=_bearer(beheerder_id, rol="beheerder"))
        assert resp.status_code == 200
        rij = next(r for r in resp.json()["administraties"] if r["id"] == str(administratie_id))
        assert (rij["naam"], rij["naam_bron"], rij["bron_naam"]) == ("Scope-test", "mens", "Scope-test B.V.")
        assert rij["bron_naam_gezien_op"] is not None and rij["naam_gevolgd_op"] is None
