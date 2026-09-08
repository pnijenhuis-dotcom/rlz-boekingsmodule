"""Afwijzen-met-verplichte-reden: reden verplicht (service-laag), afgewezen blokkeert boeken en
blijft zichtbaar in de werkvoorraad (mét reden + wie afwees), heropenen herstelt exact de
herkomst-status, toewijzing default-eigenaar + scope-afdwinging, audit op afwijzen/heropenen —
zelfde patronen (en testopzet) als de vragenworkflow (test_vragen.py)."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app.documenten import afwijzen, boeken, service
from app.documenten.models import AfwijzingStatus, DocumentStatus
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.documenten.storage import LokaleBestandsopslag
from app.documenten.vragen import ToegewezeneBuitenScope
from tests.documenten.test_vragen import _extra_gebruiker, _status, _toegewezen_aan, _zet_document_op

# Zelfde herstelbare herkomsten als bij vragen: heropenen moet er exact naar terugkeren
# (klaar_om_te_boeken mag niet degraderen naar te_controleren, handmatig_afmaken mag zijn
# context niet verliezen).
_HERKOMSTEN = [
    DocumentStatus.TE_CONTROLEREN,
    DocumentStatus.HANDMATIG_AFMAKEN,
    DocumentStatus.KLAAR_OM_TE_BOEKEN,
]


def _afwijzing_audit_acties(admin_engine: Engine, afwijzing_id: uuid.UUID) -> list[str]:
    with admin_engine.connect() as conn:
        return (
            conn.execute(
                text(
                    "SELECT actie FROM platform.audit_event WHERE tabel = 'afwijzing' AND record_id = :id "
                    "ORDER BY tijdstip"
                ),
                {"id": afwijzing_id},
            )
            .scalars()
            .all()
        )


@pytest.fixture
def document_te_controleren(
    gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
) -> uuid.UUID:
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur-af-te-wijzen.pdf",
        inhoud=uuid.uuid4().bytes,
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    assert resultaat.status == DocumentStatus.TE_CONTROLEREN
    return resultaat.document_id


@pytest.fixture
def eigenaar_id(admin_engine: Engine, administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> uuid.UUID:
    from app.beheer import service as beheer_service

    gid = _extra_gebruiker(admin_engine, met_scope_op=administratie_id, beheerder_id=beheerder_id)
    beheer_service.zet_eigenaar(actor_id=beheerder_id, administratie_id=administratie_id, eigenaar_gebruiker_id=gid)
    return gid


class TestAfwijzen:
    @pytest.mark.parametrize("herkomst", _HERKOMSTEN)
    def test_zet_document_op_afgewezen_vanuit_elke_herkomst_en_blokkeert_boeken(
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
        data = afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Niet onze bestelling, navragen bij leverancier",
        )
        assert data.status == AfwijzingStatus.OPEN.value
        assert data.status_voor_afwijzing == herkomst.value
        assert data.reden == "Niet onze bestelling, navragen bij leverancier"
        assert data.afgewezen_door == gescoopte_gebruiker
        assert data.toegewezen_aan == eigenaar_id
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.AFGEWEZEN.value
        # Werkvoorraad-kolom "Toegewezen" volgt de open afwijzing ("ter controle naar").
        assert _toegewezen_aan(admin_engine, document_te_controleren) == eigenaar_id

        with pytest.raises(boeken.OngeldigeBoekpoging):
            boeken.boek_document(
                administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
            )

    @pytest.mark.parametrize("reden", ["", "   ", "\n\t"])
    def test_afwijzen_zonder_reden_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
        reden: str,
    ) -> None:
        """De kern van de domeinbeslissing: een afwijzing zonder reden bestaat niet."""
        with pytest.raises(afwijzen.RedenVerplicht):
            afwijzen.wijs_af(
                administratie_id=administratie_id,
                document_id=document_te_controleren,
                actor_id=gescoopte_gebruiker,
                reden=reden,
            )
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.TE_CONTROLEREN.value
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.afwijzing WHERE document_id = :id"),
                {"id": document_te_controleren},
            ).scalar_one()
        assert aantal == 0

    def test_zonder_eigenaar_loopt_door_zonder_toewijzing_en_blijft_kantoorbreed_zichtbaar(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """Herstelrun 07-09 blok 2 ("leeg = doorlopen", migratie 0121; herziet de weigering `GeenToewijzingMogelijk`):
        zonder eigenaar én zonder expliciete toewijzing wordt het document gewoon afgewezen — toegewezen_aan leeg op
        afwijzing én document, de rij staat in de werkvoorraad "Afgewezen — ter controle", tijdlijn en audit dragen
        `toegewezen_aan: null`. Een ontbrekende instelling houdt de handeling nooit meer tegen."""
        data = afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Niet onze bestelling",
        )
        assert data.toegewezen_aan is None
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.AFGEWEZEN.value
        assert _toegewezen_aan(admin_engine, document_te_controleren) is None
        chip = afwijzen.open_afwijzingen(administratie_id=administratie_id)[document_te_controleren]
        assert chip.toegewezen_aan is None and chip.reden == "Niet onze bestelling"
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT toegewezen_aan FROM boekhouding.afwijzing WHERE id = :id"), {"id": data.id}
            ).one()
            audit = conn.execute(
                text(
                    "SELECT nieuwe_waarde FROM platform.audit_event WHERE tabel = 'afwijzing' AND record_id = :id "
                    "AND actie = 'document_afgewezen'"
                ),
                {"id": data.id},
            ).scalar_one()
            tijdlijn = conn.execute(
                text(
                    "SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :d "
                    "AND naar_status = 'afgewezen'"
                ),
                {"d": document_te_controleren},
            ).scalar_one()
        assert rij.toegewezen_aan is None
        assert "toegewezen_aan" in audit and audit["toegewezen_aan"] is None
        assert "toegewezen_aan" in tijdlijn and tijdlijn["toegewezen_aan"] is None
        # Heropenen werkt zonder toewijzing net zo.
        hersteld = afwijzen.heropen(
            administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
        )
        assert hersteld.document_status == DocumentStatus.TE_CONTROLEREN

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
        with pytest.raises(ToegewezeneBuitenScope):
            afwijzen.wijs_af(
                administratie_id=administratie_id,
                document_id=document_te_controleren,
                actor_id=gescoopte_gebruiker,
                reden="Niet onze bestelling",
                toegewezen_aan=buitenstaander,
            )
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.TE_CONTROLEREN.value
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.afwijzing WHERE document_id = :id"),
                {"id": document_te_controleren},
            ).scalar_one()
        assert aantal == 0

    def test_dubbel_afwijzen_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Niet onze bestelling",
        )
        with pytest.raises(OngeldigeStatusovergang):
            afwijzen.wijs_af(
                administratie_id=administratie_id,
                document_id=document_te_controleren,
                actor_id=gescoopte_gebruiker,
                reden="Nogmaals afwijzen",
            )
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.AFGEWEZEN.value

    def test_blijft_zichtbaar_in_werkvoorraad_met_reden_en_wie(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """CLAUDE.md: "Afwijzen = verplichte reden, blijft zichtbaar" — het afgewezen document
        staat gewoon in de (niet-verwijderd-)lijst en de chip-data (reden + wie afwees) is per
        document beschikbaar."""
        afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Niet onze bestelling, navragen bij leverancier",
        )
        # Aanvulling blok 3 (Peter 08-09): afgewezen is een eindstatus — standaard verborgen in de lijst, het
        # aantal reist mee (tel_afgehandeld) en de rij komt mét reden/wie terug via "Toon afgehandelde documenten".
        assert document_te_controleren not in {i.document.id for i in service.lijst_documenten(administratie_id=administratie_id)}
        assert service.tel_afgehandeld(administratie_id=administratie_id)[DocumentStatus.AFGEWEZEN] == 1
        items = service.lijst_documenten(administratie_id=administratie_id, toon_afgehandeld=True)
        assert any(
            item.document.id == document_te_controleren
            and item.document.status == DocumentStatus.AFGEWEZEN
            for item in items
        )
        open_per_document = afwijzen.open_afwijzingen(administratie_id=administratie_id)
        chip = open_per_document[document_te_controleren]
        assert chip.reden == "Niet onze bestelling, navragen bij leverancier"
        assert chip.afgewezen_door == gescoopte_gebruiker


class TestHeropenen:
    @pytest.mark.parametrize("herkomst", _HERKOMSTEN)
    def test_heropenen_herstelt_exact_de_herkomst(
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
        afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Niet onze bestelling",
        )
        data = afwijzen.heropen(
            administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
        )
        assert data.status == AfwijzingStatus.HEROPEND.value
        assert data.heropend_door == gescoopte_gebruiker
        assert data.document_status == herkomst
        assert _status(admin_engine, document_te_controleren) == herkomst.value
        # De toewijzing hoorde bij de open afwijzing — na heropenen weer leeg.
        assert _toegewezen_aan(admin_engine, document_te_controleren) is None
        # Historie blijft: de heropende afwijzing staat nog in de tabel.
        with admin_engine.connect() as conn:
            statussen = (
                conn.execute(
                    text("SELECT status FROM boekhouding.afwijzing WHERE document_id = :id"),
                    {"id": document_te_controleren},
                )
                .scalars()
                .all()
            )
        assert statussen == [AfwijzingStatus.HEROPEND.value]

    def test_heropenen_zonder_open_afwijzing_geweigerd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        with pytest.raises(afwijzen.GeenOpenAfwijzing):
            afwijzen.heropen(
                administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
            )
        assert _status(admin_engine, document_te_controleren) == DocumentStatus.TE_CONTROLEREN.value

    def test_na_heropenen_kan_opnieuw_afgewezen_worden(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        """De één-open-afwijzing-regel geldt per moment, niet voor altijd — na heropenen is een
        nieuwe afwijzing (nieuwe rij, historie compleet) gewoon mogelijk."""
        afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Eerste afwijzing",
        )
        afwijzen.heropen(
            administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
        )
        tweede = afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Tweede afwijzing",
        )
        assert tweede.reden == "Tweede afwijzing"
        with admin_engine.connect() as conn:
            aantal = conn.execute(
                text("SELECT count(*) FROM boekhouding.afwijzing WHERE document_id = :id"),
                {"id": document_te_controleren},
            ).scalar_one()
        assert aantal == 2


class TestAudit:
    def test_audit_op_afwijzen_en_heropenen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        document_te_controleren: uuid.UUID,
        eigenaar_id: uuid.UUID,
        admin_engine: Engine,
    ) -> None:
        data = afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_te_controleren,
            actor_id=gescoopte_gebruiker,
            reden="Niet onze bestelling",
        )
        afwijzen.heropen(
            administratie_id=administratie_id, document_id=document_te_controleren, actor_id=gescoopte_gebruiker
        )
        assert _afwijzing_audit_acties(admin_engine, data.id) == ["document_afgewezen", "document_heropend"]
