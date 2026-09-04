"""Servicelaag + router verplichtingen (04-09): voorstel opslaan/lezen, de harde checks, vervallen
(⑥), de RLS-scope en de router-statuscodes."""

from __future__ import annotations

import uuid
from datetime import date, timedelta
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten.models import DocumentSoort, DocumentStatus
from app.main import app
from app.security.tokens import create_access_token
from app.verplichting import service
from app.verplichting.models import Verplichting
from tests.verplichting.conftest import (
    OFFERTEBEDRAG,
    VENDOR_ID,
    document_status,
    sla_offerte_op,
    upload_verplichting,
)

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str = "boekhouding") -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _check(voorstel: service.VerplichtingVoorstel, naam: str):
    return next(c for c in voorstel.checks if c.naam == naam)


class TestVoorstel:
    def test_upload_landt_op_te_controleren_met_zichtbare_overgeslagen_extractie(
        self, admin_engine: Engine, administratie_id, gescoopte_gebruiker, opslag
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        assert document_status(admin_engine, document_id) == DocumentStatus.TE_CONTROLEREN.value
        voorstel = service.haal_voorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert voorstel.opgeslagen is False
        # AI staat in de tests uit → zichtbare reden, nooit stil (CLAUDE.md).
        assert voorstel.ai_overgeslagen_reden == "ai_extractie_uitgeschakeld"

    def test_opslaan_zet_de_velden_en_de_herkomst_op_mens(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors, project_id
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        voorstel = sla_offerte_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            project_id=project_id,
        )
        assert voorstel.opgeslagen is True
        assert voorstel.soort_label == "offerte"
        assert voorstel.vendor_naam == "Confide Bouw B.V."
        assert voorstel.project_naam == "26140 Koningstraat (Confide)"
        assert voorstel.totaalbedrag_excl == OFFERTEBEDRAG
        assert voorstel.herkomst["leverancier"] == "mens"
        assert voorstel.herkomst["totaalbedrag_excl"] == "mens"
        assert voorstel.goedgekeurd is None and voorstel.verbruik is None

    def test_onbekend_soort_label_is_ongeldige_invoer(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        with pytest.raises(service.OngeldigeInvoer):
            sla_offerte_op(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                soort_label="aanbieding",
            )

    def test_een_inkoopfactuur_is_geen_verplichting(self, administratie_id, gescoopte_gebruiker, opslag):
        from app.documenten import service as documenten_service

        resultaat = documenten_service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.pdf",
            inhoud=b"%PDF-1.4 factuur",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            soort=DocumentSoort.INKOOPFACTUUR,
        )
        with pytest.raises(service.GeenVerplichtingDocument):
            service.haal_voorstel_op(
                administratie_id=administratie_id, document_id=resultaat.document_id
            )


class TestChecks:
    def test_verplichte_velden_blokkeren_zolang_er_niets_staat(
        self, administratie_id, gescoopte_gebruiker, opslag
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        rapport = service.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
        assert rapport.geblokkeerd
        velden = next(r for r in rapport.resultaten if r.naam == "Verplichte velden")
        assert "leverancier" in velden.melding and "soort" in velden.melding

    def test_alles_groen_bij_een_volledig_voorstel(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors, project_id
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        sla_offerte_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            project_id=project_id,
        )
        rapport = service.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
        assert not rapport.geblokkeerd

    def test_bedrag_nul_blokkeert(self, administratie_id, gescoopte_gebruiker, opslag, vendors):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        sla_offerte_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            totaalbedrag_excl=Decimal("0.00"),
        )
        rapport = service.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
        assert rapport.geblokkeerd

    def test_geldigheid_voor_de_documentdatum_blokkeert(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        voorstel = sla_offerte_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            datum=date(2026, 9, 1),
            geldig_tot=date(2026, 8, 1),
        )
        geldigheid = _check(voorstel, "Geldigheid")
        assert geldigheid.ok is False

    def test_verstreken_geldigheid_is_een_signaal_geen_blokkade(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        gisteren = date.today() - timedelta(days=1)
        voorstel = sla_offerte_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            datum=gisteren - timedelta(days=30),
            geldig_tot=gisteren,
        )
        geldigheid = _check(voorstel, "Geldigheid")
        assert geldigheid.ok is True and geldigheid.signaal is True
        rapport = service.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
        assert not rapport.geblokkeerd

    def test_projectplicht_maakt_project_verplicht(
        self, admin_engine: Engine, administratie_id, gescoopte_gebruiker, opslag, vendors
    ):
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET project_verplicht = true WHERE id = :id"),
                {"id": administratie_id},
            )
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        voorstel = sla_offerte_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            project_id=None,
        )
        velden = _check(voorstel, "Verplichte velden")
        assert velden.ok is False and "project" in velden.melding

    def test_duplicaat_offerte_blokkeert(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors, geaccordeerde_offerte
    ):
        tweede = upload_verplichting(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            bestandsnaam="offerte-26140-kopie.pdf",
        )
        voorstel = sla_offerte_op(
            administratie_id=administratie_id, document_id=tweede, actor_id=gescoopte_gebruiker
        )
        duplicaat = _check(voorstel, "Duplicaat offerte")
        assert duplicaat.ok is False and "26140-OFF-01" in duplicaat.melding

    def test_ander_offertenummer_is_geen_duplicaat(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors, geaccordeerde_offerte
    ):
        tweede = upload_verplichting(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            bestandsnaam="offerte-26140-02.pdf",
        )
        voorstel = sla_offerte_op(
            administratie_id=administratie_id,
            document_id=tweede,
            actor_id=gescoopte_gebruiker,
            offertenummer="26140-OFF-02",
        )
        assert _check(voorstel, "Duplicaat offerte").ok is True


class TestVervallen:
    def test_alleen_een_geaccordeerde_verplichting_kan_vervallen(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        with pytest.raises(service.OngeldigeVerplichtingActie):
            service.laat_vervallen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden="niet meer nodig",
            )

    def test_vervallen_laat_de_status_staan_en_legt_reden_vast(
        self, admin_engine: Engine, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte
    ):
        voorstel = service.laat_vervallen(
            administratie_id=administratie_id,
            document_id=geaccordeerde_offerte,
            actor_id=gescoopte_gebruiker,
            reden="opdracht ingetrokken door de klant",
        )
        assert voorstel.vervallen is not None
        assert voorstel.vervallen.reden == "opdracht ingetrokken door de klant"
        # ⑥: het document blijft geaccordeerd (bewaarplicht/herleidbaarheid).
        assert document_status(admin_engine, geaccordeerde_offerte) == DocumentStatus.GEACCORDEERD.value

    def test_reden_is_verplicht(self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte):
        with pytest.raises(service.OngeldigeInvoer):
            service.laat_vervallen(
                administratie_id=administratie_id,
                document_id=geaccordeerde_offerte,
                actor_id=gescoopte_gebruiker,
                reden="  ",
            )

    def test_tweede_keer_vervallen_is_een_conflict(
        self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte
    ):
        service.laat_vervallen(
            administratie_id=administratie_id,
            document_id=geaccordeerde_offerte,
            actor_id=gescoopte_gebruiker,
            reden="ingetrokken",
        )
        with pytest.raises(service.OngeldigeVerplichtingActie):
            service.laat_vervallen(
                administratie_id=administratie_id,
                document_id=geaccordeerde_offerte,
                actor_id=gescoopte_gebruiker,
                reden="nogmaals",
            )


class TestGoedkeuring:
    def test_laatste_akkoord_legt_bedrag_en_actor_vast(self, administratie_id, geaccordeerde_offerte):
        voorstel = service.haal_voorstel_op(
            administratie_id=administratie_id, document_id=geaccordeerde_offerte
        )
        assert voorstel.status == DocumentStatus.GEACCORDEERD.value
        assert voorstel.goedgekeurd is not None
        assert voorstel.goedgekeurd.bedrag_excl == OFFERTEBEDRAG
        assert voorstel.verbruik is not None
        assert voorstel.verbruik.verbruikt_excl == Decimal("0.00")
        assert voorstel.verbruik.percentage == 0

    def test_bevroren_zodra_geaccordeerd(self, administratie_id, gescoopte_gebruiker, geaccordeerde_offerte):
        with pytest.raises(service.OngeldigeVerplichtingActie):
            sla_offerte_op(
                administratie_id=administratie_id,
                document_id=geaccordeerde_offerte,
                actor_id=gescoopte_gebruiker,
                totaalbedrag_excl=Decimal("99999.00"),
            )


class TestRls:
    def test_verplichting_rij_is_niet_zichtbaar_buiten_de_administratie(
        self, admin_engine: Engine, administratie_id, geaccordeerde_offerte
    ):
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text(
                    "INSERT INTO platform.administratie (id, naam, rlz_admin_id) "
                    "VALUES (:id, 'Andere BV (test)', :rlz)"
                ),
                {"id": andere, "rlz": f"rlz-{andere}"},
            )
        with scoped_session(andere) as session:
            assert session.get(Verplichting, geaccordeerde_offerte) is None
        with scoped_session(administratie_id) as session:
            assert session.get(Verplichting, geaccordeerde_offerte) is not None


class TestRouter:
    def test_voorstel_ophalen_en_opslaan(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors, project_id
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        basis = f"/administraties/{administratie_id}/verplichtingen/documenten/{document_id}"
        resp = client.get(f"{basis}/voorstel", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200
        assert resp.json()["opgeslagen"] is False

        resp = client.put(
            f"{basis}/voorstel",
            json={
                "soort_label": "prijsopgave",
                "vendor_id": str(VENDOR_ID),
                "project_id": str(project_id),
                "offertenummer": "26140-OFF-07",
                "datum": "2026-09-01",
                "totaalbedrag_excl": "12500.00",
                "geldig_tot": "2026-12-31",
                "omschrijving": "Dakwerk",
            },
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 200, resp.text
        body = resp.json()
        assert body["soort_label"] == "prijsopgave"
        assert body["totaalbedrag_excl"] == "12500.00"
        assert [c["status"] for c in body["checks"] if c["naam"] == "Verplichte velden"] == ["ok"]

        resp = client.post(f"{basis}/checks", headers=_bearer(gescoopte_gebruiker))
        assert resp.status_code == 200 and resp.json()["geblokkeerd"] is False

    def test_onbekend_soort_label_is_422(self, administratie_id, gescoopte_gebruiker, opslag, vendors):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        resp = client.put(
            f"/administraties/{administratie_id}/verplichtingen/documenten/{document_id}/voorstel",
            json={"soort_label": "aanbieding"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 422

    def test_onbekend_document_is_404(self, administratie_id, gescoopte_gebruiker):
        resp = client.get(
            f"/administraties/{administratie_id}/verplichtingen/documenten/{uuid.uuid4()}/voorstel",
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 404

    def test_vervallen_op_niet_geaccordeerd_is_409(
        self, administratie_id, gescoopte_gebruiker, opslag, vendors
    ):
        document_id = upload_verplichting(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        resp = client.post(
            f"/administraties/{administratie_id}/verplichtingen/documenten/{document_id}/vervallen",
            json={"reden": "niet meer nodig"},
            headers=_bearer(gescoopte_gebruiker),
        )
        assert resp.status_code == 409
