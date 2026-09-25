"""Blok 4 feedbackrun A 25-09 (FV-16, aangepaste vorm): factuurdatum in een INGEDIENDE btw-aangifteperiode = ORANJE
check mét de bewuste keuze "Boeken (btw in volgend tijdvak)" — nooit een blokkade (nagekomen facturen zijn legitiem).

- open periode → groen; ingediend → oranje mét actie `aangifte_bevestigen`;
- bevestigen → tijdlijn-notitie + audit `aangifteperiode_bevestigd`, de rij blijft oranje "bevestigd door …" zonder actie;
- boeken zonder bevestiging mag (oranje is geen poort) en schrijft de tijdlijnregel "niet vooraf bevestigd";
- het AUTOMATISCHE pad boekt nooit op de oranje rij (AutoboekGeweigerdDoorSignaal);
- RLZ-fout op TaxDeclarations = oranje "niet leesbaar" (nooit stil), Odoo = n.v.t. (groen mét tekst);
- de toets zit in het externe deel: tweede run mét dezelfde vingerafdruk komt uit de cache.
"""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.documenten import aangifteperiode, boeken, boekvoorstel, service, volumerem
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.security.tokens import create_access_token
from tests.documenten.fake_rlz_client import FakeBoekClient

FACTUURDATUM = date(2026, 7, 1)
#: RLZ-vorm van `GET TaxDeclarations` (api-verkenning "Actie 19 in een periode met ingediende btw-aangifte").
INGEDIEND_Q3 = {"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}
AFGEHANDELD_Q2 = {"Status": 3, "StartDate": "2026-04-01T00:00:00", "Date": "2026-06-30T00:00:00"}
CONCEPT_Q3 = {"Status": 1, "StartDate": "2026-07-01T00:00:00", "Date": "2026-09-30T00:00:00"}


def _regel() -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Testregel",
    )


def _document(administratie_id: uuid.UUID, actor: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"{uuid.uuid4()}.pdf",
        inhoud=b"%PDF-1.4 " + uuid.uuid4().bytes,
        actor_id=actor,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor,
        vendor_id=uuid.uuid4(),
        referentie=f"F-{uuid.uuid4().hex[:8]}",
        factuurdatum=FACTUURDATUM,
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    return resultaat.document_id


def _rij(rapport) -> aangifteperiode.CheckResultaat:  # noqa: ANN001
    rij = aangifteperiode.rij_uit(rapport.resultaten)
    assert rij is not None, [r.naam for r in rapport.resultaten]
    return rij


def _tijdlijn_details(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r.detail
            for r in conn.execute(
                text("SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :d ORDER BY tijdstip"),
                {"d": document_id},
            )
        ]


def _audits(admin_engine: Engine, document_id: uuid.UUID, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r.nieuwe_waarde
            for r in conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE record_id = :d AND actie = :a"),
                {"d": document_id, "a": actie},
            )
        ]


class TestCheckRij:
    def test_open_periode_is_groen_zonder_actie(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        fake = FakeBoekClient(aangiften=[AFGEHANDELD_Q2, CONCEPT_Q3])
        rij = _rij(boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake))
        assert rij.ok and not rij.signaal and rij.acties == ()
        assert "open aangifteperiode" in rij.melding

    def test_ingediende_periode_is_oranje_met_bevestig_actie_nooit_blokkerend(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        rij = _rij(rapport)
        assert rij.ok and rij.signaal, rij
        assert rapport.geblokkeerd is False
        assert "2026-07-01 t/m 2026-09-30" in rij.melding and "eerstvolgende open tijdvak" in rij.melding
        assert [a.code for a in rij.acties] == [aangifteperiode.ACTIE_CODE]
        assert rij.acties[0].label == "Boeken (btw in volgend tijdvak)"

    def test_status_3_afgehandeld_telt_ook_als_ingediend(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        fake = FakeBoekClient(aangiften=[{**INGEDIEND_Q3, "Status": 3}])
        rij = _rij(boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake))
        assert rij.signaal and rij.acties

    def test_rlz_fout_op_aangiften_is_oranje_niet_leesbaar_zonder_actie(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        fake = FakeBoekClient(faal_op="aangiften")
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        rij = _rij(rapport)
        assert rij.ok and rij.signaal and rij.acties == ()
        assert "niet leesbaar" in rij.melding
        # De andere externe rijen zijn gewoon gedraaid — één kapotte collectie sloopt de rest niet.
        assert rapport.geblokkeerd is False

    def test_odoo_administratie_is_nvt(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.backends import registry

        monkeypatch.setattr(registry, "backend_voor", lambda _aid: SimpleNamespace(value="odoo"))
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        rij = _rij(boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake))
        assert rij.ok and not rij.signaal and "Odoo" in rij.melding

    def test_tweede_run_zelfde_vingerafdruk_komt_uit_de_cache(
        self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        eerste = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        assert eerste.extern_uit_cache is False
        # RLZ zegt nu iets anders — de cache (zelfde vingerafdruk, < 15 min) wint tot "Opnieuw controleren"/VERS.
        fake.aangiften = []
        tweede = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id, client=fake)
        assert tweede.extern_uit_cache is True and _rij(tweede).signaal
        vers = boekvoorstel.voer_checks_uit(
            administratie_id=administratie_id, document_id=document_id, client=fake, extern="vers"
        )
        assert not _rij(vers).signaal

    def test_storings_tak_zonder_verbinding_is_oranje_niet_getoetst(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        def kapot(_rlz_admin_id):  # noqa: ANN001, ANN202
            raise RuntimeError("geen verbinding (simulatie)")

        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", kapot)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
        rij = _rij(rapport)
        assert rij.ok and rij.signaal and "niet getoetst" in rij.melding and rij.acties == ()


class TestBewusteKeuze:
    def test_bevestigen_schrijft_tijdlijn_en_audit_en_de_rij_verliest_de_actie(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        rapport = boekvoorstel.bevestig_aangifteperiode(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        rij = _rij(rapport)
        assert rij.ok and rij.signaal and rij.acties == ()
        assert "bevestigd" in rij.melding and "btw in volgend tijdvak" in rij.melding
        notities = [d for d in _tijdlijn_details(admin_engine, document_id) if aangifteperiode.SLEUTEL in (d or {})]
        assert len(notities) == 1
        assert notities[0][aangifteperiode.SLEUTEL]["periode_start"] == "2026-07-01"
        assert "bewust geboekt" in notities[0]["reden"]
        audits = _audits(admin_engine, document_id, aangifteperiode.AUDIT_BEVESTIGD)
        assert len(audits) == 1 and audits[0]["bevestigd"] is True
        # Idempotent: tweede klik schrijft niets.
        boekvoorstel.bevestig_aangifteperiode(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert len(_audits(admin_engine, document_id, aangifteperiode.AUDIT_BEVESTIGD)) == 1

    def test_bevestigen_zonder_ingediende_periode_is_409_in_de_service(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient(aangiften=[CONCEPT_Q3])
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        with pytest.raises(boekvoorstel.NietsTeBevestigen):
            boekvoorstel.bevestig_aangifteperiode(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
            )


class TestBoeken:
    @pytest.fixture
    def boeken_aan(self, beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)

    def test_mens_boekt_zonder_bevestiging_met_tijdlijnregel(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        resultaat = boeken.boek_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        assert resultaat.status.value == "geboekt" and len(fake.puts) == 1
        regels = [
            d for d in _tijdlijn_details(admin_engine, document_id) if aangifteperiode.SLEUTEL_GEBOEKT_ONBEVESTIGD in (d or {})
        ]
        assert len(regels) == 1 and "niet vooraf bevestigd" in regels[0]["reden"]
        assert regels[0][aangifteperiode.SLEUTEL_GEBOEKT_ONBEVESTIGD]["periode_start"] == "2026-07-01"

    def test_mens_boekt_na_bevestiging_zonder_extra_regel(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        boekvoorstel.bevestig_aangifteperiode(
            administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
        )
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        assert not [
            d for d in _tijdlijn_details(admin_engine, document_id) if aangifteperiode.SLEUTEL_GEBOEKT_ONBEVESTIGD in (d or {})
        ]

    def test_autoboek_pad_boekt_nooit_op_de_oranje_rij(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        with pytest.raises(boeken.AutoboekGeweigerdDoorSignaal, match="bewuste keuze vereist"):
            boeken.boek_document(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                extra_overgang_detail={volumerem.AUTOMATISCH_MARKERING: True},
            )
        assert fake.puts == []
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status::text FROM boekhouding.document WHERE id = :d"), {"d": document_id}
            ).scalar_one()
        assert status != "geboekt"

    def test_autoboeken_vangt_de_weigering_als_zichtbare_reden(self) -> None:
        """De autoboek-motor vertaalt de weigering in een zichtbare audit-reden (`_weiger`) — de except-tuple in
        `autoboeken.py` draagt de klasse; het gedrag zelf zit in `boek_document` (test hierboven)."""
        import inspect

        from app.documenten import autoboeken

        assert autoboeken.boeken_service.AutoboekGeweigerdDoorSignaal is boeken.AutoboekGeweigerdDoorSignaal
        bron = inspect.getsource(autoboeken)
        assert "boeken_service.AutoboekGeweigerdDoorSignaal" in bron


class TestRoute:
    client = TestClient(app)

    def _bearer(self, gebruiker_id: uuid.UUID) -> dict[str, str]:
        return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol='boekhouding')}"}

    def test_post_bevestigen_geeft_200_met_rapport_en_409_zonder_ingediende_periode(
        self,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        fake = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake)
        document_id = _document(administratie_id, gescoopte_gebruiker, opslag)
        pad = f"/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/aangifte-periode-bevestigen"
        resp = self.client.post(pad, headers=self._bearer(gescoopte_gebruiker))
        assert resp.status_code == 200, resp.text
        rij = next(r for r in resp.json()["resultaten"] if r["naam"] == aangifteperiode.NAAM)
        assert rij["ok"] and rij["signaal"] and rij["acties"] == [] and "bevestigd" in rij["melding"]
        # Vóór de bevestiging droeg de rij de actie (DTO-vorm, oranje mét handeling).
        fake2 = FakeBoekClient(aangiften=[INGEDIEND_Q3])
        monkeypatch.setattr(boekvoorstel, "client_voor_rlz_admin_id", lambda _rlz_admin_id: fake2)
        ander = _document(administratie_id, gescoopte_gebruiker, opslag)
        checks = self.client.post(
            f"/administraties/{administratie_id}/documenten/{ander}/boekvoorstel/checks",
            headers=self._bearer(gescoopte_gebruiker),
        )
        rij2 = next(r for r in checks.json()["resultaten"] if r["naam"] == aangifteperiode.NAAM)
        assert rij2["signaal"] and [a["code"] for a in rij2["acties"]] == [aangifteperiode.ACTIE_CODE]
        # Open periode → 409 (de actieve fake is fake2).
        fake2.aangiften = [CONCEPT_Q3]
        open_doc = _document(administratie_id, gescoopte_gebruiker, opslag)
        resp = self.client.post(
            f"/administraties/{administratie_id}/documenten/{open_doc}/boekvoorstel/aangifte-periode-bevestigen",
            headers=self._bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 409, resp.text

    def test_route_zonder_scope_is_403(
        self, administratie_id: uuid.UUID, admin_engine: Engine, beheerder_id: uuid.UUID
    ) -> None:
        from tests.documenten.test_vragen import _extra_gebruiker

        vreemde = _extra_gebruiker(admin_engine, met_scope_op=None, beheerder_id=beheerder_id)
        resp = self.client.post(
            f"/administraties/{administratie_id}/documenten/{uuid.uuid4()}/boekvoorstel/aangifte-periode-bevestigen",
            headers=self._bearer(vreemde),
        )
        assert resp.status_code in (403, 404)
