# ruff: noqa: F811 — pytest-fixtures als parameters
"""Gouden set — casus q: autoboeken per administratie, "leren en boeken" (blok A bundel 10-09; besluit Peter 10-09;
migratie 0128). Basis = casus h (BDO-UBL) met per exemplaar een ander factuurnummer (fixtures/q_autoboek_leren/bron.json).

Doelgedrag: schakelaar aan → vier mens-boekingen met dezelfde GB/btw/project (reeks 3 = drempel 3) → het systeem
activeert de leverancier zelf (bron systeem, audit + tijdlijnregel) → het vijfde exemplaar boekt bij intake automatisch
(chip automatisch, alle poorten onverkort) → een tegenboeking van die automatische boeking zet de leverancier terug op
"leert 0/3". Zonder schakelaar: dezelfde vier boekingen leveren alleen een nominatie (gedrag 01-09). Kempen-regel:
een doorbelastende administratie krijgt 409 mét uitleg."""

from __future__ import annotations

import json
import uuid

import pytest
from sqlalchemy import Engine, text

from app.autoboek_kandidaten import service as kandidaten_service
from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, tegenboeken
from app.documenten.models import DocumentStatus, LeverancierVoorkeur
from app.security.tokens import create_access_token
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import GB_ADVIES, PROJECT_26049, TAXRATE_HOOG, Keten
from tests.keten.pdf import maak_pdf

BASIS = Casus(casussen.H_BDO)
BASIS_NUMMER = "6088744"
KEMPEN_TEKST = beheer_service.AUTOBOEKEN_LEREN_NIET_TOEGESTAAN_TEKST
AANGIFTE_Q3_INGEDIEND = {"Status": 2, "StartDate": "2026-07-01T00:00:00", "Date": "2026-12-31T00:00:00"}


def _exemplaar(n: int) -> tuple[str, bytes, str, bytes]:
    """(xml-naam, xml, pdf-naam, pdf) van het n-de BDO-exemplaar: factuurnummer 60887{50+n} in UBL én PDF-tekst."""
    nummer = f"60887{50 + n}"
    paginas = json.loads(
        json.dumps(json.loads((BASIS.map / "pdf_tekst.json").read_text())).replace(BASIS_NUMMER, nummer)
    )
    pdf = maak_pdf(paginas)
    xml = BASIS.xml(ingesloten_pdf=pdf).replace(BASIS_NUMMER.encode(), nummer.encode())
    return (f"BDO - {nummer}.xml", xml, f"BDO - {nummer}.pdf", pdf)


def _intake(keten: Keten, n: int) -> uuid.UUID:
    xml_naam, xml, pdf_naam, pdf = _exemplaar(n)
    resultaat = keten.mail([(xml_naam, xml), (pdf_naam, pdf)], message_id=f"<q-bdo-{n}@test>")
    return {r.bestandsnaam: r for r in resultaat.bijlagen}[xml_naam].document_id


def _boek_als_mens(keten: Keten, document_id: uuid.UUID) -> None:
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
                ledger_id=GB_ADVIES,
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


def _voorkeur(keten: Keten) -> LeverancierVoorkeur | None:
    with scoped_session(keten.administratie_id) as session:
        rij = session.get(LeverancierVoorkeur, (keten.administratie_id, keten.vendors["bdo"]))
        if rij is not None:
            session.expunge(rij)
        return rij


def _audit(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return int(
            conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}).scalar() or 0
        )


@pytest.fixture
def drempel_3(beheerder_id: uuid.UUID) -> int:
    return kandidaten_service.zet_drempel(actor_id=beheerder_id, drempel=3)


@pytest.fixture
def beheer_headers(beheerder_id: uuid.UUID) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(beheerder_id, rol='beheerder')}"}


@pytest.fixture
def leren_aan(keten: Keten, beheer_headers: dict[str, str], drempel_3: int) -> None:
    r = keten.api.put(
        f"/administraties/{keten.administratie_id}/autoboeken-leren-instelling",
        headers=beheer_headers,
        json={"ingeschakeld": True},
    )
    assert r.status_code == 200, r.text
    assert r.json() == {"ingeschakeld": True, "toegestaan": True, "reden_niet_toegestaan": None}


class TestLerenEnBoeken:
    def test_vier_mens_boekingen_activeren_en_het_vijfde_exemplaar_boekt_automatisch(
        self, keten: Keten, leren_aan: None, beheer_headers: dict[str, str], admin_engine: Engine
    ) -> None:
        docs = [_intake(keten, n) for n in range(4)]
        assert {keten.status(d) for d in docs} == {DocumentStatus.TE_CONTROLEREN}
        for d in docs[:3]:
            _boek_als_mens(keten, d)
        assert _voorkeur(keten) is None, "drie boekingen = reeks 2: nog niet actief"
        _boek_als_mens(keten, docs[3])
        voorkeur = _voorkeur(keten)
        assert (
            voorkeur is not None and voorkeur.autoboeken_ingeschakeld is True and voorkeur.autoboeken_bron == "systeem"
        )
        assert _audit(admin_engine, "autoboek_leverancier_geactiveerd") == 1
        assert any("autoboek_geactiveerd" in (regel or {}) for regel in keten.tijdlijn(docs[3]))
        lijst = keten.api.get(
            f"/administraties/{keten.administratie_id}/leveranciers-autoboeken", headers=beheer_headers
        ).json()
        bdo = next(r for r in lijst["leveranciers"] if r["vendor_id"] == str(keten.vendors["bdo"]))
        assert (bdo["stand"], bdo["reeks"], bdo["drempel"], bdo["bron"]) == ("boekt_automatisch", 3, 3, "systeem")

        # Vijfde exemplaar: intake → autoboekpad (harde checks, geheugen app-bevestigd incl. project, geen signaal) → geboekt.
        vijfde = _intake(keten, 4)
        assert keten.status(vijfde) == DocumentStatus.GEBOEKT
        geboekt = next(r for r in keten.tijdlijn(vijfde) if "rlz_boekstuknummer" in (r or {}))
        assert geboekt["automatisch_geboekt"] is True and geboekt["bron"] == "leverancier_opt_in"
        assert _audit(admin_engine, "automatisch_geboekt") == 1
        rij = keten.lijst_rij(vijfde, toon_afgehandeld="true")
        assert rij is not None and rij["status"] == "geboekt" and rij["automatisch_geboekt"] is True
        assert len(keten.rlz.puts) == 5

        # Tegenboeking van de automatische boeking (storno geblokkeerd door een ingediende aangifte) → leert 0/3.
        keten.rlz.aangiften = [AANGIFTE_Q3_INGEDIEND]
        tegenboeken.voer_tegenboeking_uit(
            administratie_id=keten.administratie_id,
            document_id=vijfde,
            actor_id=keten.actor,
            soort="volledig",
            reden="automatisch op 4700 geboekt, hoort op 4400 — na aangifte, dus tegenboeken",
        )
        voorkeur = _voorkeur(keten)
        assert voorkeur.autoboeken_ingeschakeld is False and voorkeur.autoboeken_bron is None
        assert voorkeur.autoboeken_gereset_op is not None
        assert _audit(admin_engine, "autoboek_leverancier_gereset") == 1
        reset_regel = next(r for r in keten.tijdlijn(vijfde) if "autoboek_reset" in (r or {}))
        assert (
            reset_regel["reden"]
            == "Autoboeken voor BDO Accountancy, Tax & Legal B.V. teruggezet naar leren (0/3) — storno"
        )
        lijst = keten.api.get(
            f"/administraties/{keten.administratie_id}/leveranciers-autoboeken", headers=beheer_headers
        ).json()
        bdo = next(r for r in lijst["leveranciers"] if r["vendor_id"] == str(keten.vendors["bdo"]))
        assert (bdo["stand"], bdo["reeks"], bdo["gereset_op"] is not None) == ("leert", 0, True)
        # Een zesde exemplaar blijft nu mensenwerk (weigering geauditeerd — de opt-in staat uit, dus geen audit-ruis).
        zesde = _intake(keten, 5)
        assert keten.status(zesde) == DocumentStatus.TE_CONTROLEREN

    def test_zonder_schakelaar_alleen_nominatie(self, keten: Keten, drempel_3: int, admin_engine: Engine) -> None:
        docs = [_intake(keten, n) for n in range(4)]
        for d in docs:
            _boek_als_mens(keten, d)
        assert _voorkeur(keten) is None
        assert _audit(admin_engine, "autoboek_leverancier_geactiveerd") == 0
        stand = kandidaten_service.hertoets_vendor(
            administratie_id=keten.administratie_id, vendor_id=keten.vendors["bdo"]
        )
        assert stand.kwalificeert is True and stand.reeks_ongewijzigd == 3 and stand.actief is False
        vijfde = _intake(keten, 4)
        assert keten.status(vijfde) == DocumentStatus.TE_CONTROLEREN

    def test_doorbelasting_administratie_krijgt_409_met_uitleg(
        self, keten: Keten, beheer_headers: dict[str, str], admin_engine: Engine
    ) -> None:
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET doorbelasting_ingeschakeld = true WHERE id = :id"),
                {"id": keten.administratie_id},
            )
        r = keten.api.put(
            f"/administraties/{keten.administratie_id}/autoboeken-leren-instelling",
            headers=beheer_headers,
            json={"ingeschakeld": True},
        )
        assert r.status_code == 409 and r.json()["detail"] == KEMPEN_TEKST
        lijst = keten.api.get("/instellingen/administraties", headers=beheer_headers).json()["administraties"]
        rij = next(a for a in lijst if a["id"] == str(keten.administratie_id))
        assert rij["autoboeken_leren_toegestaan"] is False and rij["autoboeken_leren_ingeschakeld"] is False
