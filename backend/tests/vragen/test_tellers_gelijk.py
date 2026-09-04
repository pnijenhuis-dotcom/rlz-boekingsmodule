# ruff: noqa: F811 — pytest-fixtures als parameters
"""G1 (mee-lift-fix 03-09, akkoord Peter): de KPI-kaart "Open vragen" (`app.vragen.service.tellers().open`)
en de klantenlijst-kolom "Vragen" (`WerkvoorraadKlant.vragen` uit `werkvoorraad_overzicht`) tellen DEZELFDE
definitie — open `vraag`-rijen op documenten die nog bestaan als werkstuk (`_DOCUMENT_WEG`), GEBOEKT telt mee
(blok B5). Vóór G1 telde de kolom documenten in status `vraag_open`, waardoor een vraag op een geboekt document
wél op de kaart maar niet in de kolom stond. Toets met een echte niet-Beheerder MÉT scope (conventies §RLS)."""

from __future__ import annotations

import uuid

from sqlalchemy import Engine

from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten import vragen as vragen_service
from app.documenten.models import Document, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.vragen import service
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.vragen.test_open_vragen import _document, _vraag


def _naar_geboekt(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Testhulp: via de statusmachine-schrijver naar geboekt (klaar → geboekt), zonder RLZ."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        documenten_service._schrijf_overgang(
            session, document=document, naar=DocumentStatus.KLAAR_OM_TE_BOEKEN, actor_id=actor_id
        )
        documenten_service._schrijf_overgang(session, document=document, naar=DocumentStatus.GEBOEKT, actor_id=actor_id)


def _status(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> DocumentStatus:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        assert document is not None
        return document.status


def _klantrij(administratie_id: uuid.UUID) -> documenten_service.WerkvoorraadKlant:
    overzicht = documenten_service.werkvoorraad_overzicht(administratie_ids_met_naam=[(administratie_id, "Scope-test")])
    assert len(overzicht) == 1
    return overzicht[0]


class TestTellersGelijk:
    def test_kolom_vragen_telt_open_vraag_rijen_zoals_de_kpi(
        self,
        admin_engine: Engine,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        """Seed: (a) document in vraag_open mét één open vraag; (b) GEBOEKT document mét een open vraag
        (dialoogmodel B5: status blijft geboekt); (c) document mét één AFGEHANDELDE en daarna één nieuwe open
        vraag (de partiële unique-index `vraag_een_open_per_document` staat maar één open vraag per document
        toe); (d) verwijderd document mét een nog-open vraag. Verwacht: 3 open vraag-rijen (a, b, c) — en
        exact dat getal op zowel de KPI als de kolom."""
        # (a) één open vraag op een te_controleren-document → document naar vraag_open
        doc_a = _document(administratie_id, gescoopte_gebruiker, opslag, "a-vraag-open.pdf")
        _vraag(administratie_id, doc_a, actor_id=gescoopte_gebruiker, toegewezen_aan=beheerder_id, tekst="Welke GB?")
        assert _status(administratie_id, doc_a, gescoopte_gebruiker) == DocumentStatus.VRAAG_OPEN

        # (b) vraag op een geboekt document — status blijft geboekt (blok B5), de vraag wacht wél
        doc_b = _document(administratie_id, gescoopte_gebruiker, opslag, "b-geboekt.pdf")
        _naar_geboekt(administratie_id, doc_b, gescoopte_gebruiker)
        _vraag(administratie_id, doc_b, actor_id=gescoopte_gebruiker, toegewezen_aan=beheerder_id, tekst="Nog een bon?")
        assert _status(administratie_id, doc_b, gescoopte_gebruiker) == DocumentStatus.GEBOEKT

        # (c) één afgehandelde + één nieuwe open vraag op hetzelfde document → telt als 1
        doc_c = _document(administratie_id, gescoopte_gebruiker, opslag, "c-twee-vragen.pdf")
        v_c1 = _vraag(
            administratie_id, doc_c, actor_id=gescoopte_gebruiker, toegewezen_aan=beheerder_id, tekst="Eerste?"
        )
        vragen_service.handel_vraag_af(
            administratie_id=administratie_id, vraag_id=v_c1, actor_id=gescoopte_gebruiker, slotbericht=None
        )
        assert _status(administratie_id, doc_c, gescoopte_gebruiker) == DocumentStatus.TE_CONTROLEREN
        _vraag(administratie_id, doc_c, actor_id=gescoopte_gebruiker, toegewezen_aan=beheerder_id, tekst="Tweede?")
        assert _status(administratie_id, doc_c, gescoopte_gebruiker) == DocumentStatus.VRAAG_OPEN

        # (d) verwijderd document mét open vraag — geen werk meer, telt nergens
        doc_d = _document(administratie_id, gescoopte_gebruiker, opslag, "d-verwijderd.pdf")
        _vraag(administratie_id, doc_d, actor_id=gescoopte_gebruiker, toegewezen_aan=beheerder_id, tekst="Dubbel?")
        documenten_service.verwijder_document(
            administratie_id=administratie_id,
            document_id=doc_d,
            actor_id=gescoopte_gebruiker,
            reden="test: dubbel geüpload",
        )
        assert _status(administratie_id, doc_d, gescoopte_gebruiker) == DocumentStatus.VERWIJDERD

        kpi = service.tellers(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING)
        rij = _klantrij(administratie_id)
        assert kpi.open == 3
        assert rij.vragen == kpi.open == 3
        # De oude document-telling zou 2 geven (alleen a en c staan in vraag_open) — dat is nu de
        # blokkeert-boeken-teller van de KPI, niet meer de kolom.
        assert kpi.blokkeert_boeken == 2
        assert rij.heeft_openstaand_werk is True

    def test_open_vraag_op_geboekt_document_is_werk_voor_de_klantrij(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        opslag: LokaleBestandsopslag,
    ) -> None:
        """Alleen een geboekt document mét open vraag: vóór G1 stond de klant met nul werk in de lijst terwijl de
        kaart "Open vragen" 1 toonde. Nu: kolom 1, klant heeft openstaand werk; afhandelen zet beide op 0."""
        doc = _document(administratie_id, gescoopte_gebruiker, opslag, "alleen-geboekt.pdf")
        _naar_geboekt(administratie_id, doc, gescoopte_gebruiker)
        vraag_id = _vraag(
            administratie_id, doc, actor_id=beheerder_id, toegewezen_aan=gescoopte_gebruiker, tekst="Bon?"
        )

        rij = _klantrij(administratie_id)
        assert rij.vragen == 1 and rij.te_controleren == 0 and rij.heeft_openstaand_werk is True
        assert service.tellers(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING).open == 1

        vragen_service.handel_vraag_af(
            administratie_id=administratie_id, vraag_id=vraag_id, actor_id=beheerder_id, slotbericht="Gevonden."
        )
        rij_na = _klantrij(administratie_id)
        assert rij_na.vragen == 0 and rij_na.heeft_openstaand_werk is False
        assert service.tellers(actor_id=gescoopte_gebruiker, rol=GebruikerRol.BOEKHOUDING).open == 0
