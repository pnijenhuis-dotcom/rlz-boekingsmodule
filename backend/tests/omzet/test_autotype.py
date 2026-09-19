# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Kassarapport automatisch typeren (Peter 19-09, screenshot Reconciliatie Van Boxtel "dit zijn meldingen waar ik dus niks mee
doe"): parser-eenduidig (ProfX/dagstaat/kascheck/pilates) → soort kassarapport bij upload/intake mét tijdlijn + audit
`soort_automatisch_gewijzigd`; niet-eenduidig (alleen omzetrekeningen) → bevinding zoals voorheen; "Tóch inkoopfactuur" →
terug + observatie `typering_correctie`; ná 2 correcties → melden i.p.v. doen (bij intake én in de dagelijkse run, mét
leesbare reden); nazorg-CLI idempotent (dry-run = 0 writes); dagteller `kassarapport_autotype` in de reconciliatie."""

from __future__ import annotations

import argparse
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.db.session import scoped_session
from app.documenten import service as documenten_service
from app.documenten import soort as soort_service
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.main import app
from app.omzet import autotype, inkoopstroom
from app.omzet import reconciliatie as omzet_reconciliatie
from app.reconciliatie import automatiseringen as auto
from app.reconciliatie import teksten
from app.security.tokens import create_access_token
from tests.keten import casussen
from tests.keten import pdf as keten_pdf
from tests.omzet.test_categorie_binder import omzet_ledgers  # noqa: F401
from tests.omzet.test_inkoopstroom_werkvoorraad import _inkoopfactuur_in_werkvoorraad

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _profx_pdf() -> bytes:
    paginas = json.loads((casussen.FIXTURES / casussen.AD_OMZET_PROFX / "pdf_tekst.json").read_text(encoding="utf-8"))
    return keten_pdf.maak_pdf(paginas)


def _gewone_pdf() -> bytes:
    return keten_pdf.maak_pdf([["Factuur 123", "Totaal 10,00"]])


def _rij(admin_engine: Engine, document_id: uuid.UUID) -> tuple[str, str]:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT soort, status FROM boekhouding.document WHERE id = :id"), {"id": document_id}).one()


def _audit(admin_engine: Engine, actie: str, document_id: uuid.UUID | None = None) -> list:
    with admin_engine.connect() as conn:
        sql = "SELECT nieuwe_waarde, administratie_id, record_id FROM platform.audit_event WHERE actie = :a"
        params: dict = {"a": actie}
        if document_id is not None:
            sql += " AND record_id = :r"
            params["r"] = document_id
        return conn.execute(text(sql + " ORDER BY tijdstip"), params).all()


def _tijdlijn(admin_engine: Engine, document_id: uuid.UUID) -> list[dict]:
    with admin_engine.connect() as conn:
        return [
            r[0] or {}
            for r in conn.execute(
                text("SELECT detail FROM boekhouding.document_gebeurtenis WHERE document_id = :id ORDER BY tijdstip, id"),
                {"id": document_id},
            ).all()
        ]


def _upload(administratie_id, actor, opslag, *, naam: str, inhoud: bytes, soort=DocumentSoort.INKOOPFACTUUR, **kw):  # noqa: ANN001
    return documenten_service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=inhoud, actor_id=actor, opslag=opslag, soort=soort, **kw
    ).document_id


def _zet_terug_naar_inkoopfactuur(admin_engine: Engine, document_id: uuid.UUID) -> None:
    """Simuleert een document van vóór deze feature (werkvoorraad, soort inkoopfactuur, parser-treffer op de PDF)."""
    with admin_engine.begin() as conn:
        conn.execute(
            text("UPDATE boekhouding.document SET soort = 'inkoopfactuur', status = 'te_controleren' WHERE id = :id"),
            {"id": document_id},
        )
        conn.execute(text("DELETE FROM boekhouding.document_gebeurtenis WHERE document_id = :id"), {"id": document_id})
        conn.execute(
            text(
                "DELETE FROM platform.audit_event WHERE record_id = :id AND actie IN "
                "('soort_automatisch_gewijzigd', 'documentsoort_gewijzigd')"
            ),
            {"id": document_id},
        )


def _schrijf_correctie(admin_engine: Engine, administratie_id: uuid.UUID, *, bron: str, afzender: str | None, n: int, dagen_oud: int = 0) -> None:
    """Rechtstreeks n observaties `typering_correctie` op de sleutel (de route zelf wordt apart getoetst)."""
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    tijdstip = datetime.now(UTC) - timedelta(days=dagen_oud)
    with admin_engine.begin() as conn:
        for _ in range(n):
            conn.execute(
                text(
                    "INSERT INTO platform.audit_event (id, tijdstip, actor_id, module, tabel, record_id, actie, nieuwe_waarde, correlatie_id, administratie_id) "
                    "VALUES (:id, :t, :actor, 'boekhouding', 'document', :rec, 'typering_correctie', CAST(:nw AS jsonb), :corr, :adm)"
                ),
                {
                    "id": uuid.uuid4(), "t": tijdstip, "actor": SYSTEEM_ACTOR_ID, "rec": uuid.uuid4(), "corr": uuid.uuid4(),
                    "adm": administratie_id, "nw": json.dumps({"bron": bron, "afzender": autotype.normaliseer_afzender(afzender) or None}),
                },
            )


class TestHerkenning:
    def test_herken_pdf_en_spreadsheet_en_gewone_factuur(self) -> None:
        assert autotype.herken("Journaal 1-9.pdf", _profx_pdf()) == "profx_journaal"
        assert autotype.herken("factuur.pdf", _gewone_pdf()) is None
        assert autotype.herken("kapot.pdf", b"%PDF-1.4 x") is None
        assert autotype.herken("rommel.xlsx", b"geen spreadsheet") is None
        assert autotype.bron_leesbaar("profx_journaal") == "ProfX-journaal"
        assert autotype.normaliseer_afzender("  Kassa@Coffeeshop.EXAMPLE ") == "kassa@coffeeshop.example"
        assert autotype.normaliseer_afzender(None) == ""


class TestUploadAutomatischTyperen:
    def test_profx_upload_als_inkoopfactuur_wordt_direct_kassarapport_met_tijdlijn_en_audit(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine
    ) -> None:
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 1-9.pdf", inhoud=_profx_pdf())
        soort, status = _rij(admin_engine, doc)
        assert soort == "kassarapport" and status in ("te_controleren", "vraag_open", "handmatig_afmaken")
        regels = [g for g in _tijdlijn(admin_engine, doc) if autotype.TIJDLIJN_SLEUTEL in g]
        assert len(regels) == 1 and regels[0]["reden"] == "type automatisch gewijzigd: inkoopfactuur → kassarapport (ProfX-journaal herkend)"
        assert regels[0][autotype.TIJDLIJN_SLEUTEL] == {"van": "inkoopfactuur", "naar": "kassarapport", "bron": "profx_journaal"}
        [(nw, aid, rec)] = _audit(admin_engine, autotype.AUDIT_GEWIJZIGD, doc)
        assert (aid, rec, nw["bron"], nw["ingang"], nw["afzender"]) == (administratie_id, doc, "profx_journaal", "upload", None)
        # De chip-bron voor het omzet-controlescherm.
        with scoped_session(administratie_id) as session:
            assert autotype.is_automatisch_getypeerd(session, document_id=doc) == {"van": "inkoopfactuur", "naar": "kassarapport", "bron": "profx_journaal"}
        # Geen bevinding meer: het document staat niet als inkoopfactuur in de werkvoorraad.
        assert omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id) == []

    def test_gewone_factuur_en_mens_gekozen_kassarapport_blijven_ongemoeid(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine
    ) -> None:
        gewoon = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="factuur.pdf", inhoud=_gewone_pdf())
        assert _rij(admin_engine, gewoon)[0] == "inkoopfactuur"
        assert _audit(admin_engine, autotype.AUDIT_GEWIJZIGD, gewoon) == [] and _audit(admin_engine, autotype.AUDIT_OVERGESLAGEN, gewoon) == []
        # Een mens die bewust "kassarapport" kiest voor een gewone PDF: geen parser-treffer, geen overrule.
        _schrijf_correctie(admin_engine, administratie_id, bron="profx_journaal", afzender=None, n=2)
        mens = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 2-9.pdf", inhoud=_profx_pdf(), soort=DocumentSoort.KASSARAPPORT)
        assert _rij(admin_engine, mens)[0] == "kassarapport" and _audit(admin_engine, autotype.AUDIT_OVERGESLAGEN, mens) == []

    def test_na_twee_correcties_blijft_de_upload_inkoopfactuur_met_reden_en_de_intake_valt_terug(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine
    ) -> None:
        _schrijf_correctie(admin_engine, administratie_id, bron="profx_journaal", afzender=None, n=2)
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 3-9.pdf", inhoud=_profx_pdf())
        assert _rij(admin_engine, doc)[0] == "inkoopfactuur"
        [(nw, _, _)] = _audit(admin_engine, autotype.AUDIT_OVERGESLAGEN, doc)
        assert (nw["reden"], nw["correcties"], nw["bron"], nw["ingang"]) == ("correcties", 2, "profx_journaal", "upload")
        [regel] = [g for g in _tijdlijn(admin_engine, doc) if "kassarapport_autotype_overgeslagen" in g]
        assert "2× eerder teruggezet" in regel["reden"]
        # Een andere afzender (mail) leert apart: correcties zonder afzender tellen niet voor kassa@x.
        via_mail = _upload(
            administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 4-9.pdf", inhoud=_profx_pdf(),
            soort=DocumentSoort.KASSARAPPORT, soort_door_systeem=True, afzender_hint="kassa@coffeeshop.example",
        )
        assert _rij(admin_engine, via_mail)[0] == "kassarapport"
        # Dezelfde afzender mét twee correcties: de intake-herkenning valt terug op inkoopfactuur (melden i.p.v. doen).
        _schrijf_correctie(admin_engine, administratie_id, bron="profx_journaal", afzender="kassa@coffeeshop.example", n=2)
        terug = _upload(
            administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 5-9.pdf", inhoud=_profx_pdf(),
            soort=DocumentSoort.KASSARAPPORT, soort_door_systeem=True, afzender_hint="Kassa@Coffeeshop.example",
        )
        assert _rij(admin_engine, terug)[0] == "inkoopfactuur"
        assert _audit(admin_engine, autotype.AUDIT_OVERGESLAGEN, terug)[0][0]["ingang"] == "upload"
        # Correcties buiten het venster tellen niet meer (recency).
        with scoped_session(administratie_id) as session:
            assert autotype.tel_correcties(session, administratie_id=administratie_id, bron="profx_journaal", afzender=None) == 2
            assert autotype.tel_correcties(session, administratie_id=administratie_id, bron="profx_journaal", afzender=None, nu=datetime.now(UTC) + timedelta(days=autotype.CORRECTIE_VENSTER_DAGEN + 1)) == 0


class TestWerkvoorraadMotorEnReconciliatie:
    def test_dagelijkse_run_zet_parser_treffers_om_en_laat_omzetrekeningen_signaal_als_melding(
        self, administratie_id, gescoopte_gebruiker, opslag, omzet_ledgers, admin_engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(soort_service, "start_extractie_na_toewijzing", lambda **kw: DocumentStatus.ONTVANGEN, raising=False)
        profx = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 6-9.pdf", inhoud=_profx_pdf())
        _zet_terug_naar_inkoopfactuur(admin_engine, profx)
        zacht = _inkoopfactuur_in_werkvoorraad(
            administratie_id, gescoopte_gebruiker, opslag, naam="rapport.pdf", inhoud=b"%PDF-1.4 x",
            ledgers=[omzet_ledgers["omzet_hoog"], omzet_ledgers["omzet_laag"]],
        )
        # Lees-only: niets geschreven, beide gemeld — de parser-treffer mét "automatisch bij de dagelijkse run".
        afw = omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id)
        assert {a.document_id for a in afw} == {profx, zacht}
        a = next(x for x in afw if x.document_id == profx)
        assert "automatisch bij de dagelijkse run" in a.detail and _rij(admin_engine, profx)[0] == "inkoopfactuur"
        lb = teksten.leesbaar(argparse.Namespace(blok="omzet", soort="afwijking", tekst=a.detail, detail={"afwijking_soort": a.soort, "detail": a.detail, "document_id": str(profx)}))
        assert "lees-only meting" in lb.wat and "herkend kassarapport" in lb.wat
        # Echte run (registreer): de motor zet het ProfX-document om; alleen het zachte signaal blijft een melding.
        afw2 = omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id, registreer=True)
        assert [x.document_id for x in afw2] == [zacht] and "automatisch" not in afw2[0].detail
        soort, status = _rij(admin_engine, profx)
        assert (soort, status) == ("kassarapport", "ontvangen")
        [(nw, _, _)] = _audit(admin_engine, autotype.AUDIT_GEWIJZIGD, profx)
        assert nw["ingang"] == "werkvoorraad"
        [(run, aid, rec)] = _audit(admin_engine, autotype.AUDIT_RUN)
        assert (run["verwacht"], run["gedaan"], run["overgeslagen"], aid, rec) == (1, 1, {}, administratie_id, administratie_id)
        regels = [g for g in _tijdlijn(admin_engine, profx) if autotype.TIJDLIJN_SLEUTEL in g]
        assert len(regels) == 1 and regels[0]["reden"].startswith("type automatisch gewijzigd: inkoopfactuur → kassarapport")
        # Idempotent: een tweede echte run vindt niets meer (geen extra run-rij, geen dubbele wissel).
        omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id, registreer=True)
        assert len(_audit(admin_engine, autotype.AUDIT_RUN)) == 1 and len(_audit(admin_engine, autotype.AUDIT_GEWIJZIGD, profx)) == 1

    def test_na_twee_correcties_blijft_de_parser_treffer_een_melding_met_leesbare_reden(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(soort_service, "start_extractie_na_toewijzing", lambda **kw: DocumentStatus.ONTVANGEN, raising=False)
        profx = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 7-9.pdf", inhoud=_profx_pdf())
        _zet_terug_naar_inkoopfactuur(admin_engine, profx)
        _schrijf_correctie(admin_engine, administratie_id, bron="profx_journaal", afzender=None, n=2)
        [a] = omzet_reconciliatie.omzet_in_inkoopstroom_afwijkingen(administratie_id, registreer=True)
        assert a.document_id == profx and "automatisch overgeslagen: correcties 2×" in a.detail
        assert _rij(admin_engine, profx)[0] == "inkoopfactuur"
        [(run, _, _)] = _audit(admin_engine, autotype.AUDIT_RUN)
        assert (run["verwacht"], run["gedaan"], run["overgeslagen"]) == (1, 0, {"correcties": 1})
        [(over, _, _)] = _audit(admin_engine, autotype.AUDIT_OVERGESLAGEN, profx)
        assert (over["reden"], over["correcties"], over["ingang"]) == ("correcties", 2, "werkvoorraad")
        lb = teksten.leesbaar(argparse.Namespace(blok="omzet", soort="afwijking", tekst=a.detail, detail={"afwijking_soort": a.soort, "detail": a.detail, "document_id": str(profx)}))
        assert "al eerder teruggezet naar inkoopfactuur" in lb.wat and "Type wijzigen" in lb.doe and not teksten.bevat_technische_sleutel(lb.wat)
        # De knop uit de bevinding werkt nog steeds (mens beslist).
        with scoped_session(administratie_id) as session:
            assert [t.document_id for t in inkoopstroom.ongeboekte_kassarapporten_in_inkoopstroom(session, administratie_id=administratie_id, opslag=opslag)] == [profx]

    def test_status_die_de_wissel_niet_toelaat_is_overgeslagen_status_nooit_stil(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, monkeypatch
    ) -> None:
        profx = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 8-9.pdf", inhoud=_profx_pdf())
        _zet_terug_naar_inkoopfactuur(admin_engine, profx)
        # De werkvoorraad-toets ziet 'm (te_controleren); de wissel zelf weigert (gesimuleerd).
        def weiger(**kw):  # noqa: ANN003
            raise soort_service.SoortWisselNietToegestaan("Type wijzigen kan niet vanuit deze stand — ter accordering")

        monkeypatch.setattr(soort_service, "wijzig_documentsoort", weiger)
        uit = autotype.verwerk_werkvoorraad(administratie_id, opslag=opslag)
        assert (uit.verwacht, uit.gedaan, uit.overgeslagen) == (1, 0, {"status": 1})
        [(over, _, _)] = _audit(admin_engine, autotype.AUDIT_OVERGESLAGEN, profx)
        assert over["reden"] == "status" and "ter accordering" in over["detail"]

    def test_nazorg_cli_dry_run_schrijft_niets_en_de_echte_run_is_idempotent(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, monkeypatch, capsys
    ) -> None:
        from app import cli

        monkeypatch.setattr(soort_service, "start_extractie_na_toewijzing", lambda **kw: DocumentStatus.ONTVANGEN, raising=False)
        profx = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 9-9.pdf", inhoud=_profx_pdf())
        _zet_terug_naar_inkoopfactuur(admin_engine, profx)
        with admin_engine.connect() as conn:
            audit_voor = conn.execute(text("SELECT count(*) FROM platform.audit_event")).scalar_one()
        assert cli.main(["kassarapport-autotype-nazorg", "--dry-run", "--administratie", str(administratie_id)]) == 0
        uit = capsys.readouterr().out
        assert "dry-run — 0 writes" in uit and "zou omzetten 1" in uit and "Journaal 9-9.pdf" in uit
        with admin_engine.connect() as conn:
            assert conn.execute(text("SELECT count(*) FROM platform.audit_event")).scalar_one() == audit_voor
        assert _rij(admin_engine, profx)[0] == "inkoopfactuur"
        assert cli.main(["kassarapport-autotype-nazorg", "--administratie", str(administratie_id)]) == 0
        assert "omgezet 1" in capsys.readouterr().out and _rij(admin_engine, profx)[0] == "kassarapport"
        assert cli.main(["kassarapport-autotype-nazorg", "--administratie", str(administratie_id)]) == 0
        assert "0 kandidaat/kandidaten" in capsys.readouterr().out
        assert len(_audit(admin_engine, autotype.AUDIT_RUN)) == 1
        assert cli.main(["kassarapport-autotype-nazorg", "--administratie", "bestaat-niet-xyz"]) == 2


class TestTochInkoopfactuur:
    def test_route_zet_terug_schrijft_observatie_en_meldt_de_drempel(
        self, administratie_id, gescoopte_gebruiker, opslag, admin_engine, monkeypatch
    ) -> None:
        monkeypatch.setattr(soort_service, "start_extractie_na_toewijzing", lambda **kw: DocumentStatus.ONTVANGEN, raising=False)
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 10-9.pdf", inhoud=_profx_pdf())
        assert _rij(admin_engine, doc)[0] == "kassarapport"
        # Het omzetvoorstel draagt de chip-bron.
        vs = client.get(f"/administraties/{administratie_id}/omzet/documenten/{doc}/voorstel", headers=kop)
        assert vs.status_code == 200 and (vs.json()["automatisch_getypeerd"], vs.json()["automatisch_getypeerd_bron"]) == (True, "profx_journaal")
        pad = f"/administraties/{administratie_id}/omzet/documenten/{doc}/toch-inkoopfactuur"
        assert client.post(pad, headers=kop, json={"reden": "kort"}).status_code == 422
        r = client.post(pad, headers=kop, json={"reden": "Dit is een inkoopfactuur van de kassaleverancier"})
        assert r.status_code == 200, r.text
        assert (r.json()["status"], r.json()["correcties"], r.json()["bron"], r.json()["valt_terug_op_melden"]) == ("ontvangen", 1, "profx_journaal", False)
        assert _rij(admin_engine, doc) == ("inkoopfactuur", "ontvangen")
        [(nw, aid, rec)] = _audit(admin_engine, autotype.AUDIT_CORRECTIE, doc)
        assert (aid, rec, nw["bron"], nw["afzender"]) == (administratie_id, doc, "profx_journaal", None) and "kassaleverancier" in nw["reden"]
        assert any("reden: Dit is een inkoopfactuur" in (g.get("reden") or "") for g in _tijdlijn(admin_engine, doc))
        with scoped_session(administratie_id) as session:
            assert autotype.is_automatisch_getypeerd(session, document_id=doc) is None
        # Nog eens op hetzelfde document: geen kassarapport meer → 422.
        assert client.post(pad, headers=kop, json={"reden": "nog een keer proberen"}).status_code == 422
        # Tweede correctie (ander document, zelfde sleutel) raakt de drempel: vanaf nu melden i.p.v. doen.
        doc2 = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 11-9.pdf", inhoud=_profx_pdf())
        assert _rij(admin_engine, doc2)[0] == "kassarapport"
        r2 = client.post(f"/administraties/{administratie_id}/omzet/documenten/{doc2}/toch-inkoopfactuur", headers=kop, json={"reden": "ook een inkoopfactuur"})
        assert r2.status_code == 200 and (r2.json()["correcties"], r2.json()["valt_terug_op_melden"]) == (2, True)
        doc3 = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 12-9.pdf", inhoud=_profx_pdf())
        assert _rij(admin_engine, doc3)[0] == "inkoopfactuur"
        # Buiten scope → 403; onbekend document → 422.
        andere = uuid.uuid4()
        assert client.post(f"/administraties/{andere}/omzet/documenten/{doc3}/toch-inkoopfactuur", headers=kop, json={"reden": "buiten scope"}).status_code == 403
        assert client.post(f"/administraties/{administratie_id}/omzet/documenten/{uuid.uuid4()}/toch-inkoopfactuur", headers=kop, json={"reden": "onbekend document"}).status_code == 422

    def test_geboekt_kassarapport_kan_niet_terug(self, administratie_id, gescoopte_gebruiker, opslag, admin_engine) -> None:
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        doc = _upload(administratie_id, gescoopte_gebruiker, opslag, naam="Journaal 13-9.pdf", inhoud=_profx_pdf())
        with admin_engine.begin() as conn:
            conn.execute(text("UPDATE boekhouding.document SET status = 'geboekt' WHERE id = :id"), {"id": doc})
        r = client.post(f"/administraties/{administratie_id}/omzet/documenten/{doc}/toch-inkoopfactuur", headers=kop, json={"reden": "toch inkoop"})
        assert r.status_code == 409 and _audit(admin_engine, autotype.AUDIT_CORRECTIE, doc) == []


class TestDagteller:
    def test_kassarapport_autotype_telt_intake_run_en_overgeslagen(self) -> None:
        from tests.reconciliatie.test_automatiseringen import NU, _feiten, _teller, _uur

        aid = uuid.uuid4()
        f = _feiten(
            aid,
            audit=[
                auto.AuditFeit("soort_automatisch_gewijzigd", _uur(2), aid, {"bron": "profx_journaal", "ingang": "upload"}),
                auto.AuditFeit("soort_automatisch_gewijzigd", _uur(3), aid, {"bron": "profx_journaal", "ingang": "intake"}),
                # De werkvoorraad-wissel telt via de run-rij, niet dubbel via de document-rij.
                auto.AuditFeit("soort_automatisch_gewijzigd", _uur(4), aid, {"bron": "profx_journaal", "ingang": "werkvoorraad"}),
                auto.AuditFeit("kassarapport_autotype_overgeslagen", _uur(5), aid, {"bron": "profx_journaal", "ingang": "upload", "reden": "correcties", "bestandsnaam": "Journaal 3-9.pdf"}),
                auto.AuditFeit("kassarapport_autotype_run", _uur(6), aid, {"verwacht": 4, "gedaan": 3, "overgeslagen": {"correcties": 1}}),
                auto.AuditFeit("kassarapport_autotype_run", _uur(24 * 3), aid, {"verwacht": 1, "gedaan": 1, "overgeslagen": {}}),
            ],
        )
        t = _teller(auto.bereken(f, nu=NU), auto.KASSARAPPORT_AUTOTYPE)
        assert t.stand == "altijd" and t.label.startswith("Kassarapport automatisch getypeerd")
        assert (t.dag.verwacht, t.dag.gedaan, t.dag.overgeslagen) == (7, 5, {"autotype_correcties": 2})
        assert (t.week.verwacht, t.week.gedaan) == (8, 6)
        assert t.harde_voorwaarden == [] and auto.KASSARAPPORT_AUTOTYPE in auto.VOLGORDE
        leeg = _teller(auto.bereken(_feiten(aid), nu=NU), auto.KASSARAPPORT_AUTOTYPE)
        assert leeg.stil is False and leeg.week.verwacht == 0
