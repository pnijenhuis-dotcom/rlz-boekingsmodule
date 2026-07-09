from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import service
from app.documenten.models import Document, DocumentStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _laatste_gebeurtenis_detail(admin_engine: Engine, document_id: uuid.UUID, naar_status: str) -> dict:
    with admin_engine.connect() as conn:
        return conn.execute(
            text(
                "SELECT detail FROM boekhouding.document_gebeurtenis "
                "WHERE document_id = :id AND naar_status = :naar ORDER BY tijdstip DESC LIMIT 1"
            ),
            {"id": document_id, "naar": naar_status},
        ).scalar_one()


def _audit_acties(admin_engine: Engine, document_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'document' AND record_id = :id "
                    "ORDER BY tijdstip"
                ),
                {"id": document_id},
            )
            .scalars()
            .all()
        )


def _geboekt_document(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> uuid.UUID:
    """Fabriceert cheap een document op status geboekt (via de statusmachine, geen echte RLZ-
    aanroepen) — voor deze tests gaat het alleen om het verwijder-verbod, niet om de boekmechanica
    zelf (die heeft zijn eigen tests in test_boeken.py)."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="al-geboekt.pdf",
        inhoud=uuid.uuid4().bytes,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        document = session.get(Document, resultaat.document_id)
        assert document is not None
        _schrijf_overgang(
            session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
        )
        _schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=gescoopte_gebruiker)
    return resultaat.document_id


class TestVerwijderDocument:
    def test_zet_status_op_verwijderd_met_reden_en_vorige_status_in_de_tijdlijn(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="dubbele-upload.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )

        nieuwe_status = service.verwijder_document(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            reden="Per abuis twee keer geüpload",
        )

        assert nieuwe_status == DocumentStatus.VERWIJDERD
        assert _status(admin_engine, resultaat.document_id) == "verwijderd"
        detail = _laatste_gebeurtenis_detail(admin_engine, resultaat.document_id, "verwijderd")
        assert detail == {"reden": "Per abuis twee keer geüpload", "vorige_status": "te_controleren"}
        assert _audit_acties(admin_engine, resultaat.document_id)[-1] == "status_verwijderd"

    def test_reden_is_optioneel(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="zonder-reden.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        nieuwe_status = service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )
        assert nieuwe_status == DocumentStatus.VERWIJDERD

    def test_bestand_blijft_bestaan_na_verwijderen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        """Soft-delete, "niets verdwijnt stil": het bestand op de opslag wordt nooit weggegooid."""
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="blijft-bestaan.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        opslag_pad = f"{administratie_id}/{resultaat.document_id}.pdf"
        assert opslag.bestaat(pad=opslag_pad)

        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        assert opslag.bestaat(pad=opslag_pad)

    def test_geboekt_document_kan_niet_verwijderd_worden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        """De hard-geëiste regel (design-pass taak 4, bewaarplicht): een geboekt document mag
        onder geen omstandigheid verwijderd worden, ook niet zachtjes."""
        document_id = _geboekt_document(gescoopte_gebruiker, administratie_id, opslag)

        with pytest.raises(service.VerwijderenNietToegestaan):
            service.verwijder_document(
                administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker
            )

        assert _status(admin_engine, document_id) == "geboekt"

    def test_onbekend_document_geeft_documentnietgevonden(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        with pytest.raises(service.DocumentNietGevonden):
            service.verwijder_document(
                administratie_id=administratie_id, document_id=uuid.uuid4(), actor_id=gescoopte_gebruiker
            )

    def test_afgewezen_document_kan_ook_verwijderd_worden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        """'Niet-geboekt' is de enige harde grens — een afgewezen document is niet geboekt, dus
        ook verwijderbaar (bv. definitief foutieve/ongewenste upload opruimen)."""
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="afgewezen.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, resultaat.document_id)
            assert document is not None
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.AFGEWEZEN, actor_id=gescoopte_gebruiker
            )

        nieuwe_status = service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )
        assert nieuwe_status == DocumentStatus.VERWIJDERD
        assert _status(admin_engine, resultaat.document_id) == "verwijderd"


class TestHerstelDocument:
    def test_herstelt_naar_de_status_van_voor_de_verwijdering(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="te-herstellen.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        nieuwe_status = service.herstel_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        assert nieuwe_status == DocumentStatus.TE_CONTROLEREN
        assert _status(admin_engine, resultaat.document_id) == "te_controleren"

    def test_herstelt_ook_vanuit_boeken_mislukt_niet_naar_een_vast_default(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="boeken-mislukt.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, resultaat.document_id)
            assert document is not None
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=gescoopte_gebruiker
            )
            _schrijf_overgang(
                session, document=document, naar=DocumentStatus.BOEKEN_MISLUKT, actor_id=gescoopte_gebruiker
            )
        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        nieuwe_status = service.herstel_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        assert nieuwe_status == DocumentStatus.BOEKEN_MISLUKT

    def test_niet_verwijderd_document_kan_niet_herstellen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="niet-verwijderd.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(service.DocumentNietVerwijderd):
            service.herstel_document(
                administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
            )

    def test_onbekend_document_geeft_documentnietgevonden(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID
    ) -> None:
        with pytest.raises(service.DocumentNietGevonden):
            service.herstel_document(
                administratie_id=administratie_id, document_id=uuid.uuid4(), actor_id=gescoopte_gebruiker
            )


class TestLijstDocumentenToonVerwijderd:
    def test_verwijderde_documenten_zijn_standaard_verborgen(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="verborgen.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        lijst = service.lijst_documenten(administratie_id=administratie_id)
        assert resultaat.document_id not in {item.document.id for item in lijst}

    def test_toon_verwijderd_zet_ze_er_weer_bij(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        resultaat = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="weer-zichtbaar.pdf",
            inhoud=uuid.uuid4().bytes,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        service.verwijder_document(
            administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
        )

        lijst = service.lijst_documenten(administratie_id=administratie_id, toon_verwijderd=True)
        assert resultaat.document_id in {item.document.id for item in lijst}
