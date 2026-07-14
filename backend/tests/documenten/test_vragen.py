"""Vragenworkflow (PART A): stellen blokkeert boeken (vanuit élke herstelbare herkomst),
beantwoorden/intrekken herstellen exact de herkomst-status, toewijzing default-eigenaar +
scope-afdwinging, één open vraag tegelijk, audit op stellen/beantwoorden/intrekken."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, service, vragen
from app.documenten.models import Document, DocumentStatus, VraagStatus
from app.documenten.service import _schrijf_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.rlz.credentials import GeenRlzCredentials

# Elke herkomst waaruit een vraag gesteld kan worden — beantwoorden/intrekken moet er exact
# naar terugkeren (money-path statuslogica: klaar_om_te_boeken mag niet degraderen naar
# te_controleren, handmatig_afmaken mag zijn context niet verliezen).
_HERKOMSTEN = [
    DocumentStatus.TE_CONTROLEREN,
    DocumentStatus.HANDMATIG_AFMAKEN,
    DocumentStatus.KLAAR_OM_TE_BOEKEN,
]


def _zet_document_op(
    admin_engine: Engine,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    herkomst: DocumentStatus,
) -> None:
    """Brengt een vers geüpload document (te_controleren) via geldige statusmachine-overgangen
    naar de gewenste herkomst-status."""
    paden = {
        DocumentStatus.TE_CONTROLEREN: [],
        DocumentStatus.KLAAR_OM_TE_BOEKEN: [DocumentStatus.KLAAR_OM_TE_BOEKEN],
        DocumentStatus.HANDMATIG_AFMAKEN: [DocumentStatus.EXTRACTIE_BEZIG, DocumentStatus.HANDMATIG_AFMAKEN],
    }
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        for stap in paden[herkomst]:
            _schrijf_overgang(session, document=document, naar=stap, actor_id=actor_id)


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _toegewezen_aan(admin_engine: Engine, document_id: uuid.UUID) -> uuid.UUID | None:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT toegewezen_aan FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _vraag_audit_acties(admin_engine: Engine, vraag_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'vraag' AND record_id = :id "
                    "ORDER BY tijdstip"
                ),
                {"id": vraag_id},
            )
            .scalars()
            .all()
        )


def _extra_gebruiker(admin_engine: Engine, *, met_scope_op: uuid.UUID | None, beheerder_id: uuid.UUID) -> uuid.UUID:
    """Tweede actieve boekhouding-gebruiker, optioneel mét scope — voor toewijzings-tests."""
    gid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text(
                "INSERT INTO platform.gebruiker (id, naam, e_mail, rol, status) "
                "VALUES (:id, 'Collega', :mail, 'boekhouding', 'actief')"
            ),
            {"id": gid, "mail": f"{gid}@test.local"},
        )
    if met_scope_op is not None:
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gid, administratie_id=met_scope_op)
    return gid


@pytest.fixture
def document_te_controleren(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> uuid.UUID:
    """Upload zonder AI-gate: een PDF landt direct op te_controleren — de status waaruit een
    vraag gesteld kan worden."""
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur-met-vraag.pdf",
        inhoud=uuid.uuid4().bytes,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    return resultaat.document_id


@pytest.fixture
def eigenaar_id(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    """Actieve gebruiker mét scope, als eigenaar van de administratie ingesteld (mockup
    Instellingen "Eigenaar (krijgt vragen)")."""
    gid = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
    beheer_service.zet_eigenaar(actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=gid)
    return gid


class TestVraagStellen:
    @pytest.mark.parametrize("herkomst", _HERKOMSTEN)
    def test_zet_document_op_vraag_open_vanuit_elke_herkomst_en_blokkeert_boeken(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        herkomst: DocumentStatus,
    ) -> None:
        _zet_document_op(
            admin_engine,
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            herkomst=herkomst,
        )
        data = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Op welke kostenpost moet dit geboekt worden?",
        )
        assert data.status == VraagStatus.OPEN.value
        assert data.status_voor_vraag == herkomst.value
        assert data.toegewezen_aan == eigenaar_id
        assert data.gesteld_door == gescoopte_gebruiker
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.VRAAG_OPEN.value
        # Werkvoorraad-kolom "Toegewezen" volgt de open vraag.
        assert _toegewezen_aan(admin_engine, document_te_controleren) == eigenaar_id

        with pytest.raises(boeken.OngeldigeBoekpoging):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
            )

    @pytest.mark.parametrize("tekst", ["", "   ", "\n\t"])
    def test_vraag_zonder_tekst_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        tekst: str,
    ) -> None:
        with pytest.raises(vragen.VraagTekstVerplicht):
            vragen.stel_vraag(
                administratie_id=administratie_id,
                document_id=document_te_controleren,
                actor_id=gescoopte_gebruiker,
                vraag_tekst=tekst,
            )
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.TE_CONTROLEREN.value

    def test_zonder_eigenaar_en_zonder_toewijzing_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Geen stille default en geen onbeheerde vraag: zonder eigenaar is een expliciete
        toewijzing verplicht."""
        with pytest.raises(vragen.GeenToewijzingMogelijk):
            vragen.stel_vraag(
                administratie_id=administratie_id,
                document_id=document_te_controleren,
                actor_id=gescoopte_gebruiker,
                vraag_tekst="Wie moet dit oppakken?",
            )
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.TE_CONTROLEREN.value

    def test_toewijzing_override_binnen_scope(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        collega = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
        data = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Kun jij hiernaar kijken?",
            toegewezen_aan=collega,
        )
        assert data.toegewezen_aan == collega
        assert _toegewezen_aan(admin_engine, document_te_controleren) == collega

    def test_toewijzing_buiten_scope_geweigerd_en_laat_niets_achter(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        buitenstaander = _extra_gebruiker(admin_engine, met_scope_op=None, beheerder_id=beheerder_id)
        with pytest.raises(vragen.ToegewezeneBuitenScope):
            vragen.stel_vraag(
                administratie_id=administratie_id,
                document_id=document_te_controleren,
                actor_id=gescoopte_gebruiker,
                vraag_tekst="Kun jij hiernaar kijken?",
                toegewezen_aan=buitenstaander,
            )
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.TE_CONTROLEREN.value
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.vraag WHERE document_id = :id"),
                {"id": document_te_controleren},
            ).scalar_one()
        assert aantal == 0

    def test_een_open_vraag_per_document_tegelijk(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
    ) -> None:
        vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Eerste vraag",
        )
        with pytest.raises(vragen.ErIsAlEenOpenVraag):
            vragen.stel_vraag(
                administratie_id=administratie_id,
                document_id=document_te_controleren,
                actor_id=gescoopte_gebruiker,
                vraag_tekst="Tweede vraag terwijl de eerste nog open staat",
            )

    def test_audit_event_bij_stellen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        data = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Audit-check",
        )
        assert _vraag_audit_acties(admin_engine, data.id) == ["vraag_gesteld"]


class TestVraagBeantwoorden:
    @pytest.fixture
    def open_vraag(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
    ) -> vragen.VraagData:
        return vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Zakelijk of doorbelasten aan huurder?",
        )

    @pytest.mark.parametrize("herkomst", _HERKOMSTEN)
    def test_herstelt_exact_de_herkomst_status_en_deblokkeert_boeken(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        herkomst: DocumentStatus,
    ) -> None:
        """Nooit hardgecodeerd naar te_controleren: klaar_om_te_boeken blijft klaar_om_te_boeken,
        handmatig_afmaken houdt zijn context."""
        _zet_document_op(
            admin_engine,
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            herkomst=herkomst,
        )
        gesteld = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Zakelijk of doorbelasten?",
        )
        data = vragen.beantwoord_vraag(
            administratie_id=administratie_id,
            vraag_id=gesteld.id,
            actor_id=eigenaar_id,
            antwoord_tekst="Zakelijk, boeken op 4560.",
        )
        assert data.status == VraagStatus.BEANTWOORD.value
        assert data.antwoord_tekst == "Zakelijk, boeken op 4560."
        assert data.beantwoord_door == eigenaar_id
        assert data.beantwoord_op is not None
        assert _status(admin_engine, document_te_controleren) == herkomst.value
        assert _toegewezen_aan(admin_engine, document_te_controleren) is None

        # De statuspoort van boeken is weer open (elke herkomst is een geldige boek-startstatus):
        # de poging strandt nu pas op de ontbrekende RLZ-credentials van de testadministratie,
        # niet meer op OngeldigeBoekpoging.
        with pytest.raises(GeenRlzCredentials):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
            )

    @pytest.mark.parametrize("tekst", ["", "   "])
    def test_antwoord_zonder_tekst_geweigerd(
        self,
        administratie_id: uuid.UUID,
        eigenaar_id: uuid.UUID,
        open_vraag: vragen.VraagData,
        admin_engine: Engine,
        tekst: str,
    ) -> None:
        with pytest.raises(vragen.AntwoordTekstVerplicht):
            vragen.beantwoord_vraag(
                administratie_id=administratie_id, vraag_id=open_vraag.id, actor_id=eigenaar_id, antwoord_tekst=tekst
            )
        assert _status(admin_engine, open_vraag.document_id) == DocumentStatus.VRAAG_OPEN.value

    def test_al_beantwoorde_vraag_geweigerd(
        self, administratie_id: uuid.UUID, eigenaar_id: uuid.UUID, open_vraag: vragen.VraagData
    ) -> None:
        vragen.beantwoord_vraag(
            administratie_id=administratie_id, vraag_id=open_vraag.id, actor_id=eigenaar_id, antwoord_tekst="Antwoord"
        )
        with pytest.raises(vragen.VraagNietOpen):
            vragen.beantwoord_vraag(
                administratie_id=administratie_id,
                vraag_id=open_vraag.id,
                actor_id=eigenaar_id,
                antwoord_tekst="Nog een keer",
            )

    def test_audit_event_bij_beantwoorden(
        self,
        administratie_id: uuid.UUID,
        eigenaar_id: uuid.UUID,
        open_vraag: vragen.VraagData,
        admin_engine: Engine,
    ) -> None:
        vragen.beantwoord_vraag(
            administratie_id=administratie_id, vraag_id=open_vraag.id, actor_id=eigenaar_id, antwoord_tekst="Antwoord"
        )
        assert _vraag_audit_acties(admin_engine, open_vraag.id) == ["vraag_gesteld", "vraag_beantwoord"]

    def test_historie_blijft_en_nieuwe_vraag_kan_daarna(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        open_vraag: vragen.VraagData,
    ) -> None:
        vragen.beantwoord_vraag(
            administratie_id=administratie_id, vraag_id=open_vraag.id, actor_id=eigenaar_id, antwoord_tekst="Antwoord"
        )
        tweede = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Vervolgvraag",
        )
        alle = vragen.lijst_vragen(administratie_id=administratie_id, document_id=document_te_controleren)
        assert {v.id for v in alle} == {open_vraag.id, tweede.id}
        open_alleen = vragen.lijst_vragen(
            administratie_id=administratie_id, status=VraagStatus.OPEN, document_id=document_te_controleren
        )
        assert [v.id for v in open_alleen] == [tweede.id]


class TestVraagIntrekken:
    @pytest.mark.parametrize("herkomst", _HERKOMSTEN)
    def test_herstelt_exact_de_herkomst_status(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        herkomst: DocumentStatus,
    ) -> None:
        _zet_document_op(
            admin_engine,
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            herkomst=herkomst,
        )
        gesteld = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Per ongeluk gesteld",
        )
        data = vragen.trek_vraag_in(
            administratie_id=administratie_id,
            vraag_id=gesteld.id,
            actor_id=gescoopte_gebruiker,
            reden="Verkeerd document",
        )
        assert data.status == VraagStatus.INGETROKKEN.value
        assert data.ingetrokken_door == gescoopte_gebruiker
        assert data.ingetrokken_op is not None
        assert data.ingetrokken_reden == "Verkeerd document"
        assert data.antwoord_tekst is None
        assert _status(admin_engine, document_te_controleren) == herkomst.value
        assert _toegewezen_aan(admin_engine, document_te_controleren) is None

    def test_reden_is_optioneel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
    ) -> None:
        gesteld = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Per ongeluk gesteld",
        )
        data = vragen.trek_vraag_in(
            administratie_id=administratie_id, vraag_id=gesteld.id, actor_id=gescoopte_gebruiker
        )
        assert data.status == VraagStatus.INGETROKKEN.value
        assert data.ingetrokken_reden is None

    def test_na_intrekken_kan_een_nieuwe_vraag_gesteld_worden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
    ) -> None:
        eerste = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Per ongeluk gesteld",
        )
        vragen.trek_vraag_in(administratie_id=administratie_id, vraag_id=eerste.id, actor_id=gescoopte_gebruiker)
        tweede = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="De echte vraag",
        )
        alle = vragen.lijst_vragen(administratie_id=administratie_id, document_id=document_te_controleren)
        assert {(v.id, v.status) for v in alle} == {
            (eerste.id, VraagStatus.INGETROKKEN.value),
            (tweede.id, VraagStatus.OPEN.value),
        }

    def test_ingetrokken_vraag_kan_niet_beantwoord_of_opnieuw_ingetrokken_worden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
    ) -> None:
        gesteld = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Per ongeluk gesteld",
        )
        vragen.trek_vraag_in(administratie_id=administratie_id, vraag_id=gesteld.id, actor_id=gescoopte_gebruiker)
        with pytest.raises(vragen.VraagNietOpen):
            vragen.beantwoord_vraag(
                administratie_id=administratie_id,
                vraag_id=gesteld.id,
                actor_id=eigenaar_id,
                antwoord_tekst="Te laat",
            )
        with pytest.raises(vragen.VraagNietOpen):
            vragen.trek_vraag_in(administratie_id=administratie_id, vraag_id=gesteld.id, actor_id=gescoopte_gebruiker)

    def test_audit_event_bij_intrekken(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        gesteld = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Per ongeluk gesteld",
        )
        vragen.trek_vraag_in(administratie_id=administratie_id, vraag_id=gesteld.id, actor_id=gescoopte_gebruiker)
        assert _vraag_audit_acties(admin_engine, gesteld.id) == ["vraag_gesteld", "vraag_ingetrokken"]
