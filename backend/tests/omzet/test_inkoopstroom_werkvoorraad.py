# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Blok C (Peter 16-09 avond): de dagelijkse toets "kassarapport in de inkoopstroom" óók op ONGEBOEKTE documenten in de
werkvoorraad — herkende bron op de PDF-tekstlaag (ProfX, begrensd tot de werkvoorraad) of alle regels op een omzetrekening →
bevinding `kassarapport_in_werkvoorraad` mét de actie "Type wijzigen → kassarapport" (bestaande soort-wissel) vanuit
Inzicht › Reconciliatie; leesbare teksten; audit-teller `kassarapport_inkoopstroom_run` alleen in de echte run (nooit lees-only);
de lokale toets draait ook voor Odoo-administraties."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten import soort as soort_service
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
from app.main import app
from app.omzet import inkoopstroom
from app.omzet import reconciliatie as omzet_reconciliatie
from app.reconciliatie import run as run_service
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie import teksten
from app.security.tokens import create_access_token
from tests.keten import casussen
from tests.keten import pdf as keten_pdf
from tests.omzet.test_categorie_binder import omzet_ledgers  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _profx_pdf() -> bytes:
    paginas = json.loads((casussen.FIXTURES / casussen.AD_OMZET_PROFX / "pdf_tekst.json").read_text(encoding="utf-8"))
    return keten_pdf.maak_pdf(paginas)


def _inkoopfactuur_in_werkvoorraad(administratie_id, actor, opslag, *, naam: str, inhoud: bytes, ledgers=(), admin_engine=None) -> uuid.UUID:  # noqa: ANN001
    doc_id = documenten_service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=inhoud, actor_id=actor, opslag=opslag
    ).document_id
    # Peter 19-09: een parser-treffer wordt bij upload DIRECT kassarapport (autotype). Deze tests toetsen de dagelijkse
    # toets op documenten van vóór die regel — zet de soort terug zoals ze toen in de werkvoorraad stonden (admin-engine:
    # de tijdlijn is append-only voor de app-rol).
    with scoped_session(administratie_id, actor_id=actor) as session:
        soort_nu = session.get(Document, doc_id).soort
    if soort_nu == DocumentSoort.KASSARAPPORT.value:
        assert admin_engine is not None, "ProfX-upload vraagt admin_engine om de pre-19-09-stand te simuleren"
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET soort = 'inkoopfactuur', status = 'te_controleren' WHERE id = :id"), {"id": doc_id})
            conn.execute(text("DELETE FROM boekhouding.document_gebeurtenis WHERE document_id = :id"), {"id": doc_id})
            conn.execute(text("DELETE FROM platform.audit_event WHERE record_id = :id AND actie = 'soort_automatisch_gewijzigd'"), {"id": doc_id})
    with scoped_session(administratie_id, actor_id=actor) as session:
        doc = session.get(Document, doc_id)
        assert doc.status in inkoopstroom.WERKVOORRAAD_STATUSSEN, doc.status
        if ledgers:
            session.add(Boekvoorstel(document_id=doc_id, referentie="11-09", factuurdatum=date(2026, 9, 11), totaalbedrag=Decimal("100"), boek_cyclus=0))
            for i, ledger in enumerate(ledgers, start=1):
                session.add(BoekvoorstelRegel(document_id=doc_id, volgnummer=i, ledger_id=ledger, netto_bedrag=Decimal("100"), btw_bedrag=Decimal("0"), omschrijving=f"regel {i}"))
    return doc_id


def _audit(admin_engine: Engine, actie: str) -> list:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT nieuwe_waarde, administratie_id FROM platform.audit_event WHERE actie = :a"), {"a": actie}).all()


class TestDetectieWerkvoorraad:
    def test_profx_pdf_en_omzetrekeningen_worden_gevonden_niet_gewone_facturen(
        self, administratie_id, gescoopte_gebruiker, opslag, omzet_ledgers, admin_engine
    ) -> None:
        profx = _inkoopfactuur_in_werkvoorraad(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 11-9.pdf", inhoud=_profx_pdf(), admin_engine=admin_engine)
        omzet = _inkoopfactuur_in_werkvoorraad(
            administratie_id, gescoopte_gebruiker, opslag, naam="rapport.pdf", inhoud=b"%PDF-1.4 x",
            ledgers=[omzet_ledgers["omzet_hoog"], omzet_ledgers["omzet_laag"]],
        )
        _inkoopfactuur_in_werkvoorraad(
            administratie_id, gescoopte_gebruiker, opslag, naam="huur.pdf", inhoud=b"%PDF-1.4 y",
            ledgers=[omzet_ledgers["omzet_hoog"], omzet_ledgers["kosten"]],
        )
        _inkoopfactuur_in_werkvoorraad(administratie_id, gescoopte_gebruiker, opslag, naam="leeg.pdf", inhoud=b"%PDF-1.4 z")
        with scoped_session(administratie_id) as session:
            treffers = inkoopstroom.ongeboekte_kassarapporten_in_inkoopstroom(session, administratie_id=administratie_id, opslag=opslag)
        assert {(t.document_id, t.signaal) for t in treffers} == {(profx, "profx_journaal"), (omzet, "omzetrekeningen")}
        # Lees-only: geen audit-rij; de echte run (registreer) schrijft er precies één per administratie mét tellers.
        afw = omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id)
        assert sorted(a.soort for a in afw) == [inkoopstroom.SOORT_WERKVOORRAAD, inkoopstroom.SOORT_WERKVOORRAAD]
        assert _audit(admin_engine, "kassarapport_inkoopstroom_run") == []
        # Echte run (Peter 19-09): de parser-treffer wordt eerst automatisch omgezet (autotype); alleen het zachte
        # signaal 'omzetrekeningen' blijft over als melding mét knop.
        afw_echt = omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id, registreer=True)
        assert [x.document_id for x in afw_echt] == [omzet]
        [(nw, aid)] = _audit(admin_engine, "kassarapport_inkoopstroom_run")
        assert (nw["geboekt"], nw["ongeboekt"], aid) == (0, 1, administratie_id)
        assert set(nw["signalen"]) == {"omzetrekeningen"}
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT soort FROM boekhouding.document WHERE id = :id"), {"id": profx}).scalar_one() == "kassarapport"
        # Leesbare tekst (titel / wat / doe) — geen GUID's, wél de handeling.
        a = next(x for x in afw if x.document_id == profx)
        lb = teksten.leesbaar(
            SimpleNamespace(blok="omzet", soort="afwijking", tekst=a.detail, detail={"afwijking_soort": a.soort, "detail": a.detail, "document_id": str(profx)})
        )
        assert lb.titel.startswith("Kassarapport in de werkvoorraad") and "Journaal 11-9" in lb.titel
        assert "herkend kassarapport" in lb.wat and "Type wijzigen" in lb.doe and not teksten.bevat_technische_sleutel(lb.wat)

    def test_pdf_lezing_is_begrensd_en_reconcilieer_alle_omzet_neemt_odoo_mee(
        self, administratie_id, gescoopte_gebruiker, opslag, monkeypatch, admin_engine
    ) -> None:
        _inkoopfactuur_in_werkvoorraad(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 12-9.pdf", inhoud=_profx_pdf(), admin_engine=admin_engine)
        with scoped_session(administratie_id) as session:
            assert inkoopstroom.ongeboekte_kassarapporten_in_inkoopstroom(session, administratie_id=administratie_id, opslag=opslag, max_pdf_lezingen=0) == []
        # Odoo-administratie: het RLZ-blok wordt overgeslagen, de lokale toets loopt wél (A12 + blok C).
        from app.backends import registry

        monkeypatch.setattr(registry, "actieve_administraties_per_backend", lambda: ([], [administratie_id]))
        monkeypatch.setattr(omzet_reconciliatie, "reconcilieer_omzet", lambda *a, **k: pytest.fail("RLZ-blok mag niet draaien voor Odoo"))
        resultaat = omzet_reconciliatie.reconcilieer_alle_omzet()
        assert administratie_id in resultaat.overgeslagen
        assert [a.soort for a in resultaat.afwijkingen] == [inkoopstroom.SOORT_WERKVOORRAAD]


def _run_met(aid: uuid.UUID, document_id: uuid.UUID, soort: str, detail: str) -> None:
    def blok(args, verzamelaar=None) -> int:  # noqa: ANN001
        [b] = acceptatie_service.beoordeel(bron="omzet", administratie_id=aid, afwijkingen=[(document_id, soort, detail)])
        verzamelaar.bevinding(
            soort="afwijking",
            administratie_id=aid,
            vingerafdruk=b.vingerafdruk,
            tekst=f"boeking={document_id} soort={soort}: {detail}",
            detail={"bron": "omzet", "record_id": str(document_id), "afwijking_soort": soort, "detail": detail, "geaccepteerd": False, "document_id": str(document_id)},
        )
        return 1

    run_service.voer_uit(blokken=[("omzet", blok)], args=argparse.Namespace(), bron="cli", stdout=lambda t: None)


class TestTypeWijzigenVanuitBevinding:
    def test_kantoorrol_wisselt_type_en_de_bevinding_verdwijnt_bij_de_volgende_toets(
        self, administratie_id, gescoopte_gebruiker, beheerder_id, opslag, monkeypatch, admin_engine
    ) -> None:
        doc = _inkoopfactuur_in_werkvoorraad(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 13-9.pdf", inhoud=_profx_pdf(), admin_engine=admin_engine)
        # Geen echte extractie ná de wissel (geen AI in de suite) — de statuswissel zelf is wat we toetsen.
        monkeypatch.setattr(soort_service, "start_extractie_na_toewijzing", lambda **kw: DocumentStatus.ONTVANGEN, raising=False)
        [a] = omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id)
        _run_met(administratie_id, doc, a.soort, a.detail)
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        [rij] = client.get("/reconciliatie/bevindingen", headers=kop).json()["rijen"]
        assert rij["detail"]["afwijking_soort"] == "kassarapport_in_werkvoorraad" and rij["titel"].startswith("Kassarapport in de werkvoorraad")
        r = client.post(f"/reconciliatie/bevindingen/{rij['id']}/type-wijzigen-kassarapport", headers=kop, json={"administratie_id": str(administratie_id)})
        assert r.status_code == 200, r.text
        assert (r.json()["van_soort"], r.json()["naar_soort"], r.json()["document_id"]) == ("inkoopfactuur", "kassarapport", str(doc))
        with admin_engine.connect() as conn:
            soort, status = conn.execute(text("SELECT soort, status FROM boekhouding.document WHERE id = :id"), {"id": doc}).one()
        assert (soort, status) == ("kassarapport", "ontvangen")
        assert omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id) == []
        # Nog eens = 409/422 (is al een kassarapport → ongewijzigd telt als 'geen soort-wissel mogelijk' → 200 idempotent)
        r2 = client.post(f"/reconciliatie/bevindingen/{rij['id']}/type-wijzigen-kassarapport", headers=kop, json={"administratie_id": str(administratie_id)})
        assert r2.status_code == 200 and r2.json()["naar_soort"] == "kassarapport"
        # Verkeerde soort → 422; onbekende bevinding → 404; buiten scope → 403.
        assert client.post(f"/reconciliatie/bevindingen/{uuid.uuid4()}/type-wijzigen-kassarapport", headers=kop, json={"administratie_id": str(administratie_id)}).status_code == 404
        andere = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'Andere BV', :rlz)"), {"id": andere, "rlz": f"rlz-{andere}"})
        assert client.post(f"/reconciliatie/bevindingen/{rij['id']}/type-wijzigen-kassarapport", headers=kop, json={"administratie_id": str(andere)}).status_code == 403
