# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Bijlage volgt het duplicaat naar het origineel (BUG 03-10, Peter "werkdetails zonder factuur kan niet";
`app/documenten/bijlage_doel.py`). Unit op de drie bronnen (afwijzing-link, vlag, factuurnummer), de keten, het
afgewezen-pad zonder tegenhanger, het verhuizen van al gekoppelde bijlagen en de idempotente notitie/chip."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import afwijzen, bijlage_doel, boekvoorstel
from app.documenten import bijlagen as bijlagen_module
from app.documenten import service as documenten_service
from app.documenten.models import Document, DocumentBron, DocumentStatus
from tests.auth.conftest import administratie_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.extractie.pdf_helper import maak_tekst_pdf
from tests.intake.conftest import bouw_ubl

NUMMER = "RLZ-2080143088"


def _doc(aid: uuid.UUID, actor: uuid.UUID, naam: str, inhoud: bytes) -> uuid.UUID:
    return documenten_service.upload_document(
        administratie_id=aid, bestandsnaam=naam, inhoud=inhoud, actor_id=actor, bron=DocumentBron.EMAIL
    ).document_id


def _voorstel(aid: uuid.UUID, actor: uuid.UUID, document_id: uuid.UUID, referentie: str, totaal: str = "121.00") -> None:
    """Zelfde factuurnummer, ánder totaal: geen harde duplicaat-match (anders voert de motor het document zelf af)."""
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=aid,
        document_id=document_id,
        actor_id=actor,
        vendor_id=uuid.uuid4(),
        referentie=referentie,
        factuurdatum=date(2026, 8, 19),
        totaalbedrag=Decimal(totaal),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), project_id=None, netto_bedrag=Decimal("100.00"),
                btw_bedrag=Decimal("21.00"), omschrijving="Huur",
            )
        ],
    )


def _zet_status(admin_engine: Engine, document_id: uuid.UUID, status: str, *, vlag: uuid.UUID | None = None) -> None:
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document SET status = :s, mogelijk_duplicaat_van_id = :v WHERE id = :id"),
            {"s": status, "v": vlag, "id": document_id},
        )


def _volg(aid: uuid.UUID, document_id: uuid.UUID):
    with scoped_session(aid) as session:
        d = session.get(Document, document_id)
        uitkomst = bijlage_doel.volg_naar_origineel(session, d)
        if isinstance(uitkomst, bijlage_doel.Doel):
            return ("doel", uitkomst.document.id, uitkomst.bron, uitkomst.label)
        if isinstance(uitkomst, bijlage_doel.GeenDoel):
            return ("geen", uitkomst.reden, uitkomst.afwijs_reden)
        return None


class TestVolgNaarOrigineel:
    def test_niet_volgbaar_is_none(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
        d = _doc(administratie_id, gescoopte_gebruiker, "a.xml", bouw_ubl(factuurnummer=NUMMER))
        assert _volg(administratie_id, d) is None

    def test_bron_1_afwijzing_link(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
        origineel = _doc(administratie_id, gescoopte_gebruiker, "orig.xml", bouw_ubl(factuurnummer=NUMMER))
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER, klant="Ander", totaal="242.00"))
        afwijzen.wijs_af(
            administratie_id=administratie_id, document_id=dup, actor_id=gescoopte_gebruiker, reden="Duplicaat van orig",
            duplicaat_van_document_id=origineel, naar_status=DocumentStatus.AFGEVOERD_DUPLICAAT,
        )
        uit = _volg(administratie_id, dup)
        assert uit == ("doel", origineel, bijlage_doel.BRON_AFWIJZING, "via duplicaat → orig.xml")

    def test_bron_2_vlag_mogelijk_duplicaat(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        origineel = _doc(administratie_id, gescoopte_gebruiker, "orig.xml", bouw_ubl(factuurnummer=NUMMER))
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER, klant="Ander", totaal="242.00"))
        _zet_status(admin_engine, dup, "afgevoerd_duplicaat", vlag=origineel)  # legacy-stand zonder afwijzing-rij
        uit = _volg(administratie_id, dup)
        assert uit == ("doel", origineel, bijlage_doel.BRON_VLAG, "via duplicaat → orig.xml")

    def test_bron_3_zelfde_factuurnummer_ook_geboekt(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        origineel = _doc(administratie_id, gescoopte_gebruiker, "orig.xml", bouw_ubl(factuurnummer=NUMMER))
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER, klant="Ander", totaal="242.00"))
        _voorstel(administratie_id, gescoopte_gebruiker, origineel, "RLZ 2080143088")  # andere schrijfwijze, zelfde norm
        _voorstel(administratie_id, gescoopte_gebruiker, dup, NUMMER, totaal="242.00")
        afwijzen.wijs_af(administratie_id=administratie_id, document_id=dup, actor_id=gescoopte_gebruiker, reden="dubbel")
        _zet_status(admin_engine, origineel, "geboekt")
        uit = _volg(administratie_id, dup)
        assert uit == ("doel", origineel, bijlage_doel.BRON_FACTUURNUMMER, "via afgewezen factuur → orig.xml")

    def test_factuurnummer_meerdere_treffers_is_nooit_raden(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
        a = _doc(administratie_id, gescoopte_gebruiker, "a.xml", bouw_ubl(factuurnummer=NUMMER))
        b = _doc(administratie_id, gescoopte_gebruiker, "b.xml", bouw_ubl(factuurnummer=NUMMER, klant="B", totaal="242.00"))
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER, klant="C", totaal="363.00"))
        for d, totaal in ((a, "121.00"), (b, "242.00"), (dup, "363.00")):
            _voorstel(administratie_id, gescoopte_gebruiker, d, NUMMER, totaal=totaal)
        afwijzen.wijs_af(administratie_id=administratie_id, document_id=dup, actor_id=gescoopte_gebruiker, reden="dubbel")
        uit = _volg(administratie_id, dup)
        assert uit is not None and uit[0] == "geen" and "niet eenduidig" in uit[1] and uit[2] == "dubbel"

    def test_afgewezen_zonder_tegenhanger_geeft_reden_en_afwijsreden(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER))
        afwijzen.wijs_af(administratie_id=administratie_id, document_id=dup, actor_id=gescoopte_gebruiker, reden="geen factuur maar werkdetails")
        uit = _volg(administratie_id, dup)
        assert uit == ("geen", f"geen ander document mét factuurnummer {NUMMER} in deze administratie", "geen factuur maar werkdetails")

    def test_keten_origineel_zelf_afgevoerd_wordt_doorgevolgd(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
        echt = _doc(administratie_id, gescoopte_gebruiker, "echt.xml", bouw_ubl(factuurnummer=NUMMER))
        midden = _doc(administratie_id, gescoopte_gebruiker, "midden.xml", bouw_ubl(factuurnummer=NUMMER, klant="M", totaal="363.00"))
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER, klant="D", totaal="242.00"))
        afwijzen.wijs_af(administratie_id=administratie_id, document_id=midden, actor_id=gescoopte_gebruiker, reden="dup", duplicaat_van_document_id=echt, naar_status=DocumentStatus.AFGEVOERD_DUPLICAAT)
        afwijzen.wijs_af(administratie_id=administratie_id, document_id=dup, actor_id=gescoopte_gebruiker, reden="dup", duplicaat_van_document_id=midden, naar_status=DocumentStatus.AFGEVOERD_DUPLICAAT)
        uit = _volg(administratie_id, dup)
        assert uit == ("doel", echt, bijlage_doel.BRON_AFWIJZING, "via duplicaat → echt.xml")

    def test_origineel_verwijderd_is_geen_doel(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        origineel = _doc(administratie_id, gescoopte_gebruiker, "orig.xml", bouw_ubl(factuurnummer=NUMMER))
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER, klant="D", totaal="242.00"))
        afwijzen.wijs_af(administratie_id=administratie_id, document_id=dup, actor_id=gescoopte_gebruiker, reden="dup", duplicaat_van_document_id=origineel, naar_status=DocumentStatus.AFGEVOERD_DUPLICAAT)
        _zet_status(admin_engine, origineel, "verwijderd")
        uit = _volg(administratie_id, dup)
        assert uit is not None and uit[0] == "geen" and "is zelf verwijderd" in uit[1]


class TestVerhuizenEnNotitie:
    def test_bijlagen_van_duplicaat_verhuizen_naar_origineel_idempotent(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, admin_engine: Engine) -> None:
        origineel = _doc(administratie_id, gescoopte_gebruiker, "orig.xml", bouw_ubl(factuurnummer=NUMMER))
        dup = _doc(administratie_id, gescoopte_gebruiker, "dup.xml", bouw_ubl(factuurnummer=NUMMER, klant="D", totaal="242.00"))
        bijlage_id = bijlagen_module.registreer_bijlage(
            factuur_document_id=dup, administratie_id=administratie_id, bestandsnaam="werkdetails.pdf",
            inhoud=maak_tekst_pdf(["Werkdetails week 33"]), content_type="application/pdf", actor_id=gescoopte_gebruiker,
            intake_bericht_id=None,
        )
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            n = bijlage_doel.verhuis_bijlagen_naar_origineel(
                session, duplicaat=session.get(Document, dup), origineel=session.get(Document, origineel),
                actor_id=gescoopte_gebruiker, herkomst="test",
            )
        assert n == [bijlage_id]
        with admin_engine.connect() as conn:
            rij = conn.execute(text("SELECT samengevoegd_in_id, samenvoeg_rol, status FROM boekhouding.document WHERE id = :id"), {"id": bijlage_id}).one()
            audits = conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": bijlage_doel.AUDIT_BIJLAGE_NAAR_ORIGINEEL}).scalar_one()
        assert (rij.samengevoegd_in_id, rij.samenvoeg_rol, rij.status) == (origineel, "bijlage", "samengevoegd")
        assert audits == 1
        # Tweede keer: niets meer te verhuizen (het duplicaat heeft geen bijlagen meer).
        with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
            assert bijlage_doel.verhuis_bijlagen_naar_origineel(session, duplicaat=session.get(Document, dup), origineel=session.get(Document, origineel), actor_id=gescoopte_gebruiker, herkomst="test") == []
        assert [b.bestandsnaam for b in bijlagen_module.bijlagen_voor(administratie_id=administratie_id, document_id=origineel)] == ["werkdetails.pdf"]

    def test_notitie_factuur_afgewezen_is_idempotent_en_leesbaar_voor_de_dto(self, administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID) -> None:
        factuur = _doc(administratie_id, gescoopte_gebruiker, "factuur.xml", bouw_ubl(factuurnummer=NUMMER))
        bijlage = _doc(administratie_id, gescoopte_gebruiker, "werkdetails.pdf", maak_tekst_pdf(["Werkdetails"]))
        afwijzen.wijs_af(administratie_id=administratie_id, document_id=factuur, actor_id=gescoopte_gebruiker, reden="dubbel met eerdere factuur")
        for verwacht in (True, False):
            with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
                geschreven = bijlage_doel.noteer_factuur_afgewezen(
                    session, bijlage=session.get(Document, bijlage), factuur=session.get(Document, factuur),
                    afwijs_reden="dubbel met eerdere factuur", actor_id=gescoopte_gebruiker,
                )
            assert geschreven is verwacht
        detail = documenten_service.haal_document_op(administratie_id=administratie_id, document_id=bijlage)
        dto = bijlage_doel.factuur_afgewezen_uit_tijdlijn(detail.gebeurtenissen)
        assert dto is not None and dto["document_id"] == factuur and dto["bestandsnaam"] == "factuur.xml" and dto["afwijs_reden"] == "dubbel met eerdere factuur"
        # De bijlage staat nog gewoon open — niets automatisch afgewezen.
        assert detail.document.status not in (DocumentStatus.AFGEWEZEN, DocumentStatus.SAMENGEVOEGD)
