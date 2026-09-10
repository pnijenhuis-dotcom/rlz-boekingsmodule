# ruff: noqa: F811 — pytest-fixtures als parameters
"""Gouden set — casus s: boekingsgeheugen "recency wint" (blok 3.1 vervolgrun 10-09 avond; besluit Peter 10-09 avond op
beslispunt 1 van "AUTOBOEKEN — DREMPEL TELT DRIE IDENTIEKE MENS-BOEKINGEN"). Basis = casus h (BDO-UBL), zelfde
exemplaar-motor als casus q.

Doelgedrag: een leverancier met historisch één afwijkende mens-boeking (B, A, A, A) is niet meer blijvend "gesplitst"/
oranje — de laatste drie identieke mens-boekingen maken A groen en app-bevestigd (prefill + geheugen-route), de oude B
blijft zichtbaar als "eerder ook"; mét de administratie-schakelaar aan activeert de bestaande motor de leverancier ná de
vierde boeking (de motor is ongewijzigd — de engine levert het). A, A, B blijft oranje."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.autoboek_kandidaten import service as kandidaten_service
from app.documenten.models import LeverancierVoorkeur
from app.geheugen import service as geheugen_service
from app.security.tokens import create_access_token
from tests.keten.conftest import GB_ADVIES, GB_INHUUR, Keten
from tests.keten.test_q_autoboek_leren import _boek_als_mens, _intake


def _boek_met_gb(keten: Keten, document_id: uuid.UUID, gb: uuid.UUID) -> None:
    from app.documenten import boeken, boekvoorstel
    from tests.keten.conftest import PROJECT_26049, TAXRATE_HOOG

    voorstel = keten.prefill(document_id)
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=keten.administratie_id,
        document_id=document_id,
        actor_id=keten.actor,
        vendor_id=voorstel.vendor_id,
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        vervaldatum=voorstel.vervaldatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=gb,
                taxrate_id=r.taxrate_id or TAXRATE_HOOG,
                project_id=PROJECT_26049,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
                omschrijving=r.omschrijving or "regel",
            )
            for r in voorstel.regels
        ],
    )
    boeken.boek_document(administratie_id=keten.administratie_id, document_id=document_id, actor_id=keten.actor)


@pytest.fixture
def gb_anders() -> uuid.UUID:
    """De afwijkende rekening B: een tweede grootboekrekening uit de keten-cache (GB_INHUUR)."""
    return GB_INHUUR


@pytest.fixture
def beheer_headers(beheerder_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}


def _geheugen(keten: Keten):  # noqa: ANN202
    return geheugen_service.voorstel_voor(administratie_id=keten.administratie_id, vendor_id=keten.vendors["bdo"])


class TestRecencyWint:
    def test_B_A_A_A_maakt_A_groen_met_eerder_ook_B(
        self, keten: Keten, gb_anders: uuid.UUID, beheer_headers: dict[str, str]
    ) -> None:
        docs = [_intake(keten, n) for n in range(4)]
        _boek_met_gb(keten, docs[0], gb_anders)  # B
        for d in docs[1:3]:
            _boek_als_mens(keten, d)  # A, A
        # Ná B, A, A: gesplitste stem → oranje (de laatste drie zijn niet identiek).
        v = _geheugen(keten).gb
        assert v.waarde == GB_ADVIES and v.oranje and not v.recent_consensus
        assert "gesplitste stem" in (v.reden or "")
        _boek_als_mens(keten, docs[3])  # A
        # Ná B, A, A, A: recency wint — groen, app-bevestigd, B zichtbaar als "eerder ook".
        v = _geheugen(keten).gb
        assert v.waarde == GB_ADVIES and not v.oranje and v.app_bevestigd and v.recent_consensus
        assert v.eerder_ook == (gb_anders,)
        # Dezelfde stand via de kantoor-route (controlescherm-chip) — DTO draagt recent_consensus + eerder_ook.
        r = keten.api.post(
            f"/administraties/{keten.administratie_id}/boekingsgeheugen/voorstel",
            headers=beheer_headers,
            json={"vendor_id": str(keten.vendors["bdo"]), "regel_omschrijving": None},
        )
        assert r.status_code == 200, r.text
        assert r.json()["gb"]["oranje"] is False and r.json()["gb"]["recent_consensus"] is True
        assert r.json()["gb"]["eerder_ook"] == [str(gb_anders)]
        # Het vijfde exemplaar prefillt A zonder oranje geheugen-reden.
        vijfde = _intake(keten, 4)
        prefill = keten.prefill(vijfde)
        assert all(r.ledger_id == GB_ADVIES for r in prefill.regels)

    def test_A_A_B_blijft_oranje(self, keten: Keten, gb_anders: uuid.UUID) -> None:
        docs = [_intake(keten, n) for n in range(3)]
        for d in docs[:2]:
            _boek_als_mens(keten, d)
        _boek_met_gb(keten, docs[2], gb_anders)
        v = _geheugen(keten).gb
        assert v.oranje and not v.recent_consensus and "gesplitste stem" in (v.reden or "")

    def test_activatie_motor_ongewijzigd_B_A_A_A_activeert_met_schakelaar_aan(
        self,
        keten: Keten,
        gb_anders: uuid.UUID,
        beheer_headers: dict[str, str],
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        kandidaten_service.zet_drempel(actor_id=beheerder_id, drempel=3)
        r = keten.api.put(
            f"/administraties/{keten.administratie_id}/autoboeken-leren-instelling",
            headers=beheer_headers,
            json={"ingeschakeld": True},
        )
        assert r.status_code == 200, r.text
        docs = [_intake(keten, n) for n in range(4)]
        _boek_met_gb(keten, docs[0], gb_anders)
        for d in docs[1:3]:
            _boek_als_mens(keten, d)
        with admin_engine.connect() as conn:  # geen activatie ná B, A, A
            assert (
                conn.execute(
                    text("SELECT count(*) FROM platform.audit_event WHERE actie = 'autoboek_leverancier_geactiveerd'")
                ).scalar()
                == 0
            )
        _boek_als_mens(keten, docs[3])
        from app.db.session import scoped_session

        with scoped_session(keten.administratie_id) as session:
            voorkeur = session.get(LeverancierVoorkeur, (keten.administratie_id, keten.vendors["bdo"]))
            assert (
                voorkeur is not None
                and voorkeur.autoboeken_ingeschakeld is True
                and voorkeur.autoboeken_bron == "systeem"
            )
        stand = next(
            s
            for s in kandidaten_service.bereken_standen(administratie_id=keten.administratie_id)
            if s.vendor_id == keten.vendors["bdo"]
        )
        assert stand.eerder_afwijkend is True and stand.reeks_ongewijzigd == 3
