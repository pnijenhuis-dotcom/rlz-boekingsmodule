"""Globaal zoeken + archief (blok 4): treffer-typen, inline vraag-/accorderingshistorie en —
kern — scope-veiligheid: geen scope = geen data, ook cross-administratie."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import boekvoorstel, vragen
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.sync.models import VendorCache
from app.zoeken import service as zoeken_service
from tests.auth.conftest import actieve_gebruiker, administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401


@pytest.fixture
def andere_administratie(admin_engine: Engine) -> uuid.UUID:
    aid = uuid.uuid4()
    with admin_engine.begin() as conn:
        conn.execute(
            text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere klant', :rlz)"),
            {"id": aid, "rlz": f"rlz-{aid}"},
        )
    return aid


def _maak_document(
    *,
    administratie_id: uuid.UUID,  # noqa: F811
    actor_id: uuid.UUID,
    opslag: LokaleBestandsopslag,  # noqa: F811
    referentie: str = "F-2026-0642",
    boekstuknummer: str | None = "IF-2026-0219",
    vendor_naam: str = "Bouwmaat Nederland B.V.",
) -> uuid.UUID:
    vendor_id = uuid.uuid4()
    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(id=vendor_id, administratie_id=administratie_id, naam=vendor_naam, brondata={})
        )
    resultaat = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{referentie}.pdf",
        inhoud=f"%PDF-1.4 {referentie}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 7, 1),
        totaalbedrag=Decimal("922.04"),
        regels=[],
    )
    if boekstuknummer is not None:
        with scoped_session(administratie_id) as session:
            from app.documenten.models import Boekvoorstel

            voorstel = session.get(Boekvoorstel, resultaat.document_id)
            voorstel.rlz_boekstuknummer = boekstuknummer
    return resultaat.document_id


class TestZoeken:
    @pytest.mark.parametrize("term", ["2026-0642", "IF-2026-0219", "Bouwmaat", "922.04"])
    def test_vindt_document_op_referentie_boekstuk_leverancier_en_bedrag(
        self,
        term: str,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        document_id = _maak_document(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        resultaat = zoeken_service.zoek(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, term=term
        )
        assert [h.document_id for h in resultaat.documenten] == [document_id]
        hit = resultaat.documenten[0]
        assert hit.leverancier == "Bouwmaat Nederland B.V."
        assert hit.rlz_boekstuknummer == "IF-2026-0219"

    def test_vraagtekst_treffer_komt_met_vraag_inline(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            from app.db.models import Administratie

            session.get(Administratie, administratie_id).eigenaar_gebruiker_id = beheerder_id
        document_id = _maak_document(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Is dit de kwartaalafrekening zonnepanelen?",
        )
        resultaat = zoeken_service.zoek(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, term="zonnepanelen"
        )
        assert [h.document_id for h in resultaat.documenten] == [document_id]
        assert "zonnepanelen" in resultaat.documenten[0].vragen[0].vraag_tekst

    def test_scope_veilig_geen_treffers_buiten_eigen_administraties(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        andere_administratie: uuid.UUID,
        administratie_id: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        _maak_document(
            administratie_id=andere_administratie,
            actor_id=beheerder_id,
            opslag=opslag,
            referentie="GEHEIM-999",
            vendor_naam="Verborgen Leverancier B.V.",
        )
        resultaat = zoeken_service.zoek(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, term="GEHEIM-999"
        )
        assert resultaat.documenten == []
        assert resultaat.audit == []
        # Een Beheerder ziet 'm wél (platform-brede scope).
        beheerder_resultaat = zoeken_service.zoek(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, term="GEHEIM-999"
        )
        assert len(beheerder_resultaat.documenten) == 1

    def test_audit_treffers(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        _maak_document(administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag)
        resultaat = zoeken_service.zoek(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, term="boekvoorstel_opgeslagen"
        )
        assert resultaat.audit
        assert resultaat.audit[0].actie == "boekvoorstel_opgeslagen"

    def test_te_korte_term_geeft_leeg_resultaat(self, gescoopte_gebruiker: uuid.UUID) -> None:  # noqa: F811
        resultaat = zoeken_service.zoek(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, term="x")
        assert resultaat.documenten == [] and resultaat.audit == [] and resultaat.administraties == []

    def test_administratienaam_treffer_case_insensitief(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
    ) -> None:
        resultaat = zoeken_service.zoek(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, term="scope-TEST"
        )
        assert [(h.administratie_id, h.naam) for h in resultaat.administraties] == [
            (administratie_id, "Scope-test")
        ]

    def test_administratienaam_scope_veilig(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        beheerder_id: uuid.UUID,  # noqa: F811
        andere_administratie: uuid.UUID,
        administratie_id: uuid.UUID,  # noqa: F811
    ) -> None:
        # 'Andere klant' bestaat maar zit niet in de scope van de gebruiker — géén naam-hit.
        resultaat = zoeken_service.zoek(
            actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING, term="Andere klant"
        )
        assert resultaat.administraties == []
        # Een Beheerder ziet 'm wél (platform-brede scope).
        beheerder_resultaat = zoeken_service.zoek(
            actor_id=beheerder_id, rol=GebruikerRol.BEHEERDER, term="Andere klant"
        )
        assert [h.administratie_id for h in beheerder_resultaat.administraties] == [andere_administratie]


class TestArchief:
    def test_archief_toont_alleen_geboekte_documenten_met_boekstuk(
        self,
        gescoopte_gebruiker: uuid.UUID,  # noqa: F811
        administratie_id: uuid.UUID,  # noqa: F811
        admin_engine: Engine,
        opslag: LokaleBestandsopslag,  # noqa: F811
    ) -> None:
        geboekt = _maak_document(
            administratie_id=administratie_id, actor_id=gescoopte_gebruiker, opslag=opslag
        )
        _maak_document(
            administratie_id=administratie_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
            referentie="F-OPEN-1",
            boekstuknummer=None,
        )
        # Zet het eerste document op geboekt via de statusmachine-route (tijdlijn incluis).
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            document = session.get(Document, geboekt)
            documenten_service._schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                actor_id=gescoopte_gebruiker,
            )
            documenten_service._schrijf_overgang(
                session,
                document=document,
                naar=DocumentStatus.GEBOEKT,
                actor_id=gescoopte_gebruiker,
                detail={"rlz_boekstuknummer": "IF-2026-0219"},
            )
        rijen = zoeken_service.archief(administratie_id=administratie_id)
        assert [r.document_id for r in rijen] == [geboekt]
        assert rijen[0].rlz_boekstuknummer == "IF-2026-0219"
        assert rijen[0].geboekt_op is not None
        assert rijen[0].leverancier == "Bouwmaat Nederland B.V."
