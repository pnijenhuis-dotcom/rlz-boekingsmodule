# ruff: noqa: F811 — pytest-fixtures als parameters
"""Herkoppeling doelentiteit (Peter 12-09/16-09, blok 1): een whitelist-rij zonder `doel_administratie_id` wordt op de
genormaliseerde naam gekoppeld zodra het doel onboarded is (exact = koppelen + audit), een bijna-match (enkelvoud/
meervoud, casus Mantelzorgwoning) of meerdere kandidaten = NIET koppelen maar zichtbaar (audit niet_gekoppeld → LET-OP),
geen kandidaat = geteld, geen LET-OP. Afwezig-pad: geen actor/eigenaar nodig (systeem-actor), lege kandidatenlijst =
gewoon doorlopen. Idempotent: een tweede run vindt geen open rij meer."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import select, text

from app.db.models import AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.doorbelasting import herkoppeling as hk
from app.doorbelasting.models import DoorbelastingMapping
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.doorbelasting.conftest import maak_administratie


def _mapping(admin_engine, bron: uuid.UUID, beheerder: uuid.UUID, naam: str) -> uuid.UUID:  # noqa: ANN001
    mid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO boekhouding.doorbelasting_mapping (id, administratie_id, doelentiteit_naam, doel_customer_guid, "
                "doel_administratie_id, intercompany, actief, aangemaakt_door) "
                "VALUES (:id, :adm, :naam, :guid, NULL, true, true, :door)"
            ),
            {"id": mid, "adm": bron, "naam": naam, "guid": uuid.uuid4(), "door": beheerder},
        )
    return mid


def _doel_van(admin_engine, mid: uuid.UUID) -> uuid.UUID | None:  # noqa: ANN001
    with admin_engine.begin() as conn:
        return conn.execute(
            text("SELECT doel_administratie_id FROM boekhouding.doorbelasting_mapping WHERE id = :id"), {"id": mid}
        ).scalar_one()


def _audits(bron: uuid.UUID, actie: str) -> list[AuditEvent]:
    with scoped_session(bron, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.scalars(
            select(AuditEvent).where(AuditEvent.administratie_id == bron, AuditEvent.actie == actie)
        ).all()
        for r in rijen:
            session.expunge(r)
        return list(rijen)


class TestBeoordeelPuur:
    def test_exact_op_genormaliseerde_naam_wint(self) -> None:
        k = [hk.Kandidaat(uuid.uuid4(), "Kempen Chalets B.V."), hk.Kandidaat(uuid.uuid4(), "Kempen Facilities B.V.")]
        soort, treffers = hk.beoordeel("Kempen Chalets B.V.", k)
        assert soort == hk.UITKOMST_GEKOPPELD and treffers == (k[0],)
        soort, treffers = hk.beoordeel("kempen chalets bv", k)  # zelfde genormaliseerde naam
        assert soort == hk.UITKOMST_GEKOPPELD and treffers == (k[0],)

    def test_identiteitsnaam_telt_als_exact(self) -> None:
        k = [hk.Kandidaat(uuid.uuid4(), "Mantelzorgwoningen Midden Nederland", identiteit_naam="Mantelzorgwoning Midden Nederland B.V.")]
        soort, treffers = hk.beoordeel("Mantelzorgwoning Midden Nederland B.V.", k)
        assert soort == hk.UITKOMST_GEKOPPELD and treffers == (k[0],)

    def test_bijna_match_koppelt_niet(self) -> None:
        k = [hk.Kandidaat(uuid.uuid4(), "Mantelzorgwoningen Midden Nederland")]
        soort, treffers = hk.beoordeel("Mantelzorgwoning Midden Nederland B.V.", k)
        assert soort == hk.UITKOMST_BIJNA_MATCH and treffers == (k[0],)

    def test_meerdere_exact_of_bijna_koppelt_niet(self) -> None:
        k = [hk.Kandidaat(uuid.uuid4(), "Molenhof Beheer B.V."), hk.Kandidaat(uuid.uuid4(), "Molenhof Beheer BV")]
        assert hk.beoordeel("Molenhof Beheer B.V.", k)[0] == hk.UITKOMST_MEERDERE

    def test_geen_kandidaat(self) -> None:
        assert hk.beoordeel("Rubicon Investments B.V.", [hk.Kandidaat(uuid.uuid4(), "Kempen Chalets B.V.")]) == (hk.UITKOMST_GEEN, ())
        assert hk.beoordeel("X", []) == (hk.UITKOMST_GEEN, ())


class TestHerkoppelDoelen:
    def test_exact_koppelt_met_audit_en_is_idempotent(self, admin_engine, administratie_id, beheerder_id) -> None:  # noqa: ANN001
        bron = administratie_id
        chalets = maak_administratie(admin_engine, "Kempen Chalets B.V.")
        maak_administratie(admin_engine, "Kempen Facilities B.V.")
        mid = _mapping(admin_engine, bron, beheerder_id, "Kempen Chalets B.V.")
        u = hk.herkoppel_doelen(administratie_ids=[bron])
        assert u.fouten == []
        assert [r.uitkomst for r in u.rijen] == [hk.UITKOMST_GEKOPPELD]
        assert _doel_van(admin_engine, mid) == chalets
        gekoppeld = _audits(bron, hk.AUDIT_GEKOPPELD)
        assert len(gekoppeld) == 1 and gekoppeld[0].nieuwe_waarde["doel_administratie_id"] == str(chalets)
        assert gekoppeld[0].nieuwe_waarde["basis"] == "naam_exact" and gekoppeld[0].actor_id == SYSTEEM_ACTOR_ID
        assert len(_audits(bron, "doorbelasting_mapping_gewijzigd")) == 1
        run = _audits(bron, hk.AUDIT_RUN)
        assert len(run) == 1 and run[0].nieuwe_waarde["open"] == 1 and run[0].nieuwe_waarde["gekoppeld"] == 1
        # tweede run: geen open rij meer → geen nieuwe koppeling, geen tweede run-audit voor deze bron
        u2 = hk.herkoppel_doelen(administratie_ids=[bron])
        assert u2.rijen == [] and len(_audits(bron, hk.AUDIT_RUN)) == 1

    def test_bijna_match_en_meerdere_koppelen_niet_maar_zijn_zichtbaar(self, admin_engine, administratie_id, beheerder_id) -> None:  # noqa: ANN001
        bron = administratie_id
        maak_administratie(admin_engine, "Mantelzorgwoningen Midden Nederland")
        maak_administratie(admin_engine, "Molenhof Beheer B.V.")
        maak_administratie(admin_engine, "Molenhof Beheer BV")
        m1 = _mapping(admin_engine, bron, beheerder_id, "Mantelzorgwoning Midden Nederland B.V.")
        m2 = _mapping(admin_engine, bron, beheerder_id, "Molenhof Beheer B.V.")
        m3 = _mapping(admin_engine, bron, beheerder_id, "Rubicon Investments B.V.")
        u = hk.herkoppel_doelen(administratie_ids=[bron])
        per = {r.mapping_id: r.uitkomst for r in u.rijen}
        assert per == {m1: hk.UITKOMST_BIJNA_MATCH, m2: hk.UITKOMST_MEERDERE, m3: hk.UITKOMST_GEEN}
        assert _doel_van(admin_engine, m1) is None and _doel_van(admin_engine, m2) is None
        niet = _audits(bron, hk.AUDIT_NIET_GEKOPPELD)
        assert {a.nieuwe_waarde["reden"] for a in niet} == {"bijna_match", "meerdere"}
        assert all(a.nieuwe_waarde["kandidaten"] for a in niet)
        run = _audits(bron, hk.AUDIT_RUN)[0].nieuwe_waarde
        assert (run["open"], run["gekoppeld"], run["bijna_match"], run["meerdere"], run["geen"]) == (3, 0, 1, 1, 1)
        assert len(run["niet_gekoppeld"]) == 2
        regels = "\n".join(u.regels())
        assert "LET-OP" in regels and "Mantelzorgwoningen Midden Nederland" in regels

    def test_afwezig_pad_geen_kandidaten_en_geen_actor_loopt_door(self, admin_engine, administratie_id, beheerder_id) -> None:  # noqa: ANN001
        """Geen eigenaar/actor-instelling nodig (systeem-actor) en zonder enige kandidaat blijft de rij zichtbaar 'geen'."""
        bron = administratie_id
        mid = _mapping(admin_engine, bron, beheerder_id, "Kempen Chalets B.V.")
        u = hk.herkoppel_doelen(administratie_ids=[bron], kandidaten=[])
        assert [r.uitkomst for r in u.rijen] == [hk.UITKOMST_GEEN] and u.fouten == []
        assert _doel_van(admin_engine, mid) is None
        assert _audits(bron, hk.AUDIT_RUN)[0].nieuwe_waarde["geen"] == 1
        assert hk.rapporteer_herkoppeling([bron]) == 0

    def test_bron_zelf_is_nooit_kandidaat(self, admin_engine, administratie_id, beheerder_id) -> None:  # noqa: ANN001
        bron = administratie_id
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE platform.administratie SET naam = 'Kempen Facilities B.V.' WHERE id = :id"), {"id": bron})
        mid = _mapping(admin_engine, bron, beheerder_id, "Kempen Facilities B.V.")
        u = hk.herkoppel_doelen(administratie_ids=[bron])
        assert [r.uitkomst for r in u.rijen] == [hk.UITKOMST_GEEN]
        assert _doel_van(admin_engine, mid) is None

    def test_gekoppelde_rij_wordt_niet_opnieuw_beoordeeld(self, admin_engine, administratie_id, beheerder_id) -> None:  # noqa: ANN001
        bron = administratie_id
        doel = maak_administratie(admin_engine, "Kempen Chalets B.V.")
        mid = _mapping(admin_engine, bron, beheerder_id, "Kempen Chalets B.V.")
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.doorbelasting_mapping SET doel_administratie_id = :d WHERE id = :id"), {"d": doel, "id": mid})
        assert hk.herkoppel_doelen(administratie_ids=[bron]).rijen == []


@pytest.mark.parametrize("veld", ["actief"])
def test_inactieve_rij_telt_niet(admin_engine, administratie_id, beheerder_id, veld: str) -> None:  # noqa: ANN001
    mid = _mapping(admin_engine, administratie_id, beheerder_id, "Kempen Chalets B.V.")
    maak_administratie(admin_engine, "Kempen Chalets B.V.")
    with admin_engine.begin() as conn:
        conn.execute(text(f"UPDATE boekhouding.doorbelasting_mapping SET {veld} = false WHERE id = :id"), {"id": mid})
    assert hk.herkoppel_doelen(administratie_ids=[administratie_id]).rijen == []
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        assert session.get(DoorbelastingMapping, mid).doel_administratie_id is None
