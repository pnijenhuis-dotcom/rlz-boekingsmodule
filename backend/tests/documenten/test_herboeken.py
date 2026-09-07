# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Opnieuw boeken ná een VERDWENEN extern document (A11, fixrun 07-09; casus BOOT/Kempen):

- poort: alleen als de backend het stuk LIVE niet meer kent (404/hol) — bestaat het nog → 409-fout, niets gewijzigd;
- effect: GEBOEKT → KLAAR_OM_TE_BOEKEN, boek_cyclus +1 (vers deterministisch GUID ≠ oud), rlz_boekstuknummer leeg,
  GEEN tegenboeking-rij, tijdlijn-detail + audit_event mét reden en oud extern id;
- daarna boekt het gewone boekpad op het NIEUWE GUID (retry-idempotentie: dezelfde velden, nieuwe cyclus) en de
  reconciliatie is weer schoon;
- verplichte reden; ToetsMislukt → leesbare fout, niets gewijzigd;
- AANGIFTE-POORT (correctie Peter 07-09 op A11 beslispunt 2): boekdatum van de verdwenen boeking in een INGEDIENDE
  btw-periode → `BtwMogelijkAangegeven` (409-code `btw_mogelijk_aangegeven`), niets gewijzigd; alleen een Beheerder
  zet door mét `btw_niet_in_aangifte_bevestigd` + reden (tijdlijn + audit dragen de bevestiging); een andere rol mét
  bevestiging = `GeenToegang`; reden ontbreekt = fout; aangiften niet leesbaar = fail-closed blokkade; open periode =
  gewoon door. Odoo-adapter: lock dates als aangifte-equivalent (fail-closed)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, select, text

from app.backends.port import Backend, ToetsMislukt, ToetsUitkomst
from app.backends.rlz_inkoop import RlzInkoopPort
from app.beheer import service as beheer_service
from app.db.models import AuditEvent, GebruikerRol
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, herboeken, reconciliatie, service
from app.documenten.models import DocumentGebeurtenis, DocumentStatus, Tegenboeking
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.storage import LokaleBestandsopslag
from app.odoo.client import OdooFout
from app.odoo.inkoop import OdooInkoopPort
from tests.documenten.fake_rlz_client import FakeBoekClient

REDEN = "document op 16-08 per abuis in de RLZ-UI verwijderd (kliktest-erfenis)"
BEVESTIGING = "aangifte Q2 is ingediend ZONDER dit document — RLZ-document verwijderd vóór de aangifte (gecontroleerd)"
# Factuurdatum in de fixture = 22-06-2026 → valt in Q2; Q1 raakt 'm niet.
AANGIFTE_Q2_INGEDIEND = {"Status": 2, "StartDate": "2026-04-01T00:00:00", "Date": "2026-06-30T00:00:00"}
AANGIFTE_Q1_INGEDIEND = {"Status": 3, "StartDate": "2026-01-01T00:00:00", "Date": "2026-03-31T00:00:00"}


def _regel() -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=uuid.uuid4(),
        taxrate_id=uuid.uuid4(),
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=Decimal("21.00"),
        omschrijving="Testregel",
    )


@pytest.fixture
def geboekt_document(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    beheerder_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    monkeypatch: pytest.MonkeyPatch,
) -> tuple[uuid.UUID, FakeBoekClient]:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=b"%PDF-1.4 herboeken",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=uuid.uuid4(),
        referentie="202632704",
        factuurdatum=date(2026, 6, 22),
        totaalbedrag=Decimal("121.00"),
        regels=[_regel()],
    )
    fake_client = FakeBoekClient()
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake_client)
    boeken.boek_document(
        administratie_id=administratie_id, document_id=resultaat.document_id, actor_id=gescoopte_gebruiker
    )
    return resultaat.document_id, fake_client


def _status(admin_engine: Engine, document_id: uuid.UUID) -> str:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}).scalar_one()


def _voorstel(admin_engine: Engine, document_id: uuid.UUID) -> tuple[int, str | None]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT boek_cyclus, rlz_boekstuknummer FROM boekhouding.boekvoorstel WHERE document_id = :id"),
            {"id": document_id},
        ).one()


class TestOpnieuwBoekenNaVerdwijnen:
    def test_verdwenen_document_gaat_terug_naar_klaar_om_te_boeken_met_nieuwe_cyclus(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake_client = geboekt_document
        oud_guid = rlz_herboeking_id(document_id, 0)
        assert str(oud_guid) in fake_client._invoices
        # De reconciliatie ziet nu nog niets.
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake_client)
        assert rapport.afwijkingen == ()
        # Een mens verwijdert het document in de RLZ-UI → GET geeft 404 → ontbreekt_in_rlz, mét naam-context.
        del fake_client._invoices[str(oud_guid)]
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake_client)
        [a] = rapport.afwijkingen
        assert a.soort == "ontbreekt_in_rlz" and a.rlz_document_id == oud_guid
        assert a.context["factuurnummer"] == "202632704" and a.context["backend"] == "rlz"
        assert a.context["rlz_boekstuk"] == "RLZ-TEST-00001" and a.context["bedrag_lokaal"] == "121.00"
        assert a.context["extern_id"] == str(oud_guid) and a.context["administratie_naam"]

        r = herboeken.opnieuw_boeken_na_verdwijnen(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden=REDEN,
            port=RlzInkoopPort(fake_client),
        )
        assert r.status == DocumentStatus.KLAAR_OM_TE_BOEKEN and r.boek_cyclus == 1
        assert r.oud_extern_id == str(oud_guid)
        assert r.doel_pad == f"/?administratie={administratie_id}&document={document_id}"
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        assert _voorstel(admin_engine, document_id) == (1, None)
        # Vers GUID, geen tegenboeking, geen extra RLZ-writes door de actie zelf.
        assert rlz_herboeking_id(document_id, 1) != oud_guid
        assert len(fake_client.puts) == 1
        with scoped_session(administratie_id) as session:
            assert session.get(Tegenboeking, (document_id, 0)) is None
            overgang = session.scalars(
                select(DocumentGebeurtenis)
                .where(DocumentGebeurtenis.document_id == document_id)
                .order_by(DocumentGebeurtenis.tijdstip.desc())
            ).first()
            assert overgang is not None
            assert (overgang.van_status, overgang.naar_status) == (DocumentStatus.GEBOEKT, DocumentStatus.KLAAR_OM_TE_BOEKEN)
            ob = overgang.detail["opnieuw_boeken"]
            assert ob["reden"] == REDEN and ob["oud_rlz_document_id"] == str(oud_guid)
            assert ob["oud_boekstuknummer"] == "RLZ-TEST-00001" and ob["nieuwe_cyclus"] == 1
            assert ob["tegenboeking"] is None and ob["aanleiding"] == "ontbreekt_in_rlz"
            assert "extern document verdwenen" in overgang.detail["reden"]
            audit = session.scalars(
                select(AuditEvent).where(
                    AuditEvent.record_id == document_id, AuditEvent.actie == "opnieuw_boeken_na_verdwijnen"
                )
            ).all()
            assert len(audit) == 1
            assert audit[0].oude_waarde["boek_cyclus"] == 0 and audit[0].nieuwe_waarde["nieuwe_cyclus"] == 1
            assert audit[0].actor_id == gescoopte_gebruiker

        # Het gewone boekpad boekt nu op het NIEUWE GUID — zelfde velden, harde checks opnieuw.
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        assert _status(admin_engine, document_id) == "geboekt"
        assert fake_client.puts[-1]["id"] == rlz_herboeking_id(document_id, 1)
        assert fake_client.puts[-1]["reference"] == "202632704"
        assert _voorstel(admin_engine, document_id)[1] == "RLZ-TEST-00002"
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake_client)
        assert rapport.afwijkingen == () and rapport.aantal_gecontroleerd == 1

    def test_bestaat_nog_in_backend_is_409_en_wijzigt_niets(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake_client = geboekt_document
        with pytest.raises(herboeken.NogAanwezigInBackend, match="bestaat nog"):
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                port=RlzInkoopPort(fake_client),
            )
        assert _status(admin_engine, document_id) == "geboekt"
        assert _voorstel(admin_engine, document_id) == (0, "RLZ-TEST-00001")

    def test_hol_antwoord_telt_als_verdwenen(self, geboekt_document, administratie_id, gescoopte_gebruiker) -> None:
        document_id, fake_client = geboekt_document
        fake_client._invoices[str(rlz_herboeking_id(document_id, 0))] = {}  # 200 zonder document
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id, client=fake_client)
        [a] = rapport.afwijkingen
        assert a.soort == "ontbreekt_in_rlz" and "zonder bruikbaar document" in a.detail
        r = herboeken.opnieuw_boeken_na_verdwijnen(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden=REDEN,
            port=RlzInkoopPort(fake_client),
        )
        assert r.boek_cyclus == 1

    def test_reden_verplicht_en_controle_mislukt_wijzigt_niets(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake_client = geboekt_document
        with pytest.raises(herboeken.HerboekenFout, match="Reden is verplicht"):
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden="ok",
                port=RlzInkoopPort(fake_client),
            )

        class KapottePort:
            backend = Backend.RLZ

            def toets_geboekt(self, **_kw) -> ToetsUitkomst:
                raise ToetsMislukt("GET PurchaseInvoices/x -> 500: storing (simulatie)")

            def __exit__(self, *exc) -> None:
                return None

        with pytest.raises(herboeken.HerboekenFout, match="kon niet gecontroleerd worden"):
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                port=KapottePort(),  # type: ignore[arg-type]
            )
        assert _status(admin_engine, document_id) == "geboekt"

    def test_niet_geboekt_document_wordt_geweigerd(
        self, gescoopte_gebruiker, administratie_id, opslag, geboekt_document
    ) -> None:
        _, fake_client = geboekt_document
        ander = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="ander.pdf",
            inhoud=b"%PDF-1.4 ander",
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(herboeken.HerboekenFout, match="alleen een geboekt document"):
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=ander.document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                port=RlzInkoopPort(fake_client),
            )


def _laatste_overgang(administratie_id: uuid.UUID, document_id: uuid.UUID) -> DocumentGebeurtenis:
    with scoped_session(administratie_id) as session:
        overgang = session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == document_id)
            .order_by(DocumentGebeurtenis.tijdstip.desc())
        ).first()
        assert overgang is not None
        session.expunge(overgang)
        return overgang


class TestAangiftePoortHerboeken:
    """Correctie Peter 07-09: herboeken in een ingediende btw-periode is NIET vrij (voorbelasting zit al in de aangifte)."""

    def _verdwenen(self, geboekt_document, aangiften) -> tuple[uuid.UUID, FakeBoekClient]:
        document_id, fake_client = geboekt_document
        del fake_client._invoices[str(rlz_herboeking_id(document_id, 0))]
        fake_client.aangiften = aangiften
        return document_id, fake_client

    def test_boekdatum_in_ingediende_aangifte_blokkeert_zonder_bevestiging(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake_client = self._verdwenen(geboekt_document, [AANGIFTE_Q2_INGEDIEND])
        with pytest.raises(herboeken.BtwMogelijkAangegeven, match="suppletie-pad") as exc_info:
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                rol=GebruikerRol.BOEKHOUDING,
                port=RlzInkoopPort(fake_client),
            )
        exc = exc_info.value
        assert exc.code == "btw_mogelijk_aangegeven" and exc.controleerbaar is True
        detail = exc.als_detail()
        assert detail["code"] == "btw_mogelijk_aangegeven" and detail["soort"] == "ingediende_periode"
        assert detail["boekdatum"] == "2026-06-22" and detail["backend"] == "rlz"
        assert (detail["periode_start"], detail["periode_eind"]) == ("2026-04-01", "2026-06-30")
        assert detail["bevestiging_mogelijk"] is True and detail["bevestiging_rol"] == "beheerder"
        assert "Beheerder" in detail["bericht"] and "2026-06-22" in detail["bericht"]
        # Niets gewijzigd: status, cyclus, boekstuk, geen tijdlijn-overgang, geen audit.
        assert _status(admin_engine, document_id) == "geboekt"
        assert _voorstel(admin_engine, document_id) == (0, "RLZ-TEST-00001")
        assert _laatste_overgang(administratie_id, document_id).naar_status == DocumentStatus.GEBOEKT
        with scoped_session(administratie_id) as session:
            assert (
                session.scalars(
                    select(AuditEvent).where(AuditEvent.record_id == document_id, AuditEvent.actie == "opnieuw_boeken_na_verdwijnen")
                ).all()
                == []
            )

    def test_beheerder_met_bevestiging_zet_door_met_tijdlijn_en_audit(
        self, geboekt_document, administratie_id, beheerder_id, admin_engine
    ) -> None:
        document_id, fake_client = self._verdwenen(geboekt_document, [AANGIFTE_Q2_INGEDIEND])
        r = herboeken.opnieuw_boeken_na_verdwijnen(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            reden=REDEN,
            rol=GebruikerRol.BEHEERDER,
            btw_niet_in_aangifte_bevestigd=True,
            bevestiging_reden=BEVESTIGING,
            port=RlzInkoopPort(fake_client),
        )
        assert r.status == DocumentStatus.KLAAR_OM_TE_BOEKEN and r.boek_cyclus == 1
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        overgang = _laatste_overgang(administratie_id, document_id)
        ob = overgang.detail["opnieuw_boeken"]
        assert ob["btw_poort"]["toegestaan"] is False and ob["btw_poort"]["doorgezet_met_bevestiging"] is True
        assert ob["btw_poort"]["boekdatum"] == "2026-06-22"
        assert (ob["btw_poort"]["periode_start"], ob["btw_poort"]["periode_eind"]) == ("2026-04-01", "2026-06-30")
        assert "ingediende btw-aangifte" in ob["btw_poort"]["reden"]
        assert ob["btw_niet_in_aangifte_bevestigd"] == {"door": str(beheerder_id), "rol": "beheerder", "reden": BEVESTIGING}
        assert "Beheerder-bevestiging" in overgang.detail["reden"] and BEVESTIGING in overgang.detail["reden"]
        with scoped_session(administratie_id) as session:
            [audit] = session.scalars(
                select(AuditEvent).where(AuditEvent.record_id == document_id, AuditEvent.actie == "opnieuw_boeken_na_verdwijnen")
            ).all()
            assert audit.actor_id == beheerder_id
            assert audit.oude_waarde == {"boek_cyclus": 0, "rlz_boekstuknummer": "RLZ-TEST-00001", "status": "geboekt"}
            assert audit.nieuwe_waarde["btw_niet_in_aangifte_bevestigd"]["reden"] == BEVESTIGING
            assert audit.nieuwe_waarde["btw_poort"]["doorgezet_met_bevestiging"] is True
            assert audit.nieuwe_waarde["status"] == "klaar_om_te_boeken"

    def test_niet_beheerder_met_bevestiging_is_geen_toegang(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake_client = self._verdwenen(geboekt_document, [AANGIFTE_Q2_INGEDIEND])
        with pytest.raises(herboeken.GeenToegang, match="Alleen een Beheerder"):
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                rol=GebruikerRol.BOEKHOUDING,
                btw_niet_in_aangifte_bevestigd=True,
                bevestiging_reden=BEVESTIGING,
                port=RlzInkoopPort(fake_client),
            )
        # Ook zonder rol (defensief: geen rol = geen Beheerder).
        with pytest.raises(herboeken.GeenToegang):
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                btw_niet_in_aangifte_bevestigd=True,
                bevestiging_reden=BEVESTIGING,
                port=RlzInkoopPort(fake_client),
            )
        assert _status(admin_engine, document_id) == "geboekt"
        assert _voorstel(admin_engine, document_id) == (0, "RLZ-TEST-00001")

    def test_bevestiging_zonder_reden_geweigerd(self, geboekt_document, administratie_id, beheerder_id, admin_engine) -> None:
        document_id, fake_client = self._verdwenen(geboekt_document, [AANGIFTE_Q2_INGEDIEND])
        for reden in (None, "", "   ", "ok"):
            with pytest.raises(herboeken.HerboekenFout, match="Reden van de bevestiging"):
                herboeken.opnieuw_boeken_na_verdwijnen(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    actor_id=beheerder_id,
                    reden=REDEN,
                    rol=GebruikerRol.BEHEERDER,
                    btw_niet_in_aangifte_bevestigd=True,
                    bevestiging_reden=reden,
                    port=RlzInkoopPort(fake_client),
                )
        assert _status(admin_engine, document_id) == "geboekt"

    def test_aangiften_niet_leesbaar_blokkeert_fail_closed(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, beheerder_id, admin_engine
    ) -> None:
        document_id, fake_client = self._verdwenen(geboekt_document, [])
        fake_client.faal_op = "aangiften"  # GET TaxDeclarations → 500
        with pytest.raises(herboeken.BtwMogelijkAangegeven, match="kon niet gecontroleerd worden") as exc_info:
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                rol=GebruikerRol.BOEKHOUDING,
                port=RlzInkoopPort(fake_client),
            )
        detail = exc_info.value.als_detail()
        assert detail["code"] == "btw_mogelijk_aangegeven" and detail["soort"] == "niet_controleerbaar"
        assert detail["periode_start"] is None and "niet leesbaar" in detail["bericht"]
        assert _status(admin_engine, document_id) == "geboekt"
        # Een Beheerder mág ook hier doorzetten (bewuste keuze: de mens weet wat er is aangegeven) — de tijdlijn
        # legt vast dat de poort niet controleerbaar was.
        r = herboeken.opnieuw_boeken_na_verdwijnen(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            reden=REDEN,
            rol=GebruikerRol.BEHEERDER,
            btw_niet_in_aangifte_bevestigd=True,
            bevestiging_reden=BEVESTIGING,
            port=RlzInkoopPort(fake_client),
        )
        assert r.boek_cyclus == 1
        ob = _laatste_overgang(administratie_id, document_id).detail["opnieuw_boeken"]
        assert ob["btw_poort"]["doorgezet_met_bevestiging"] is True and "niet leesbaar" in ob["btw_poort"]["reden"]

    def test_port_zonder_aangiftepoort_blokkeert_fail_closed(self, geboekt_document, administratie_id, gescoopte_gebruiker) -> None:
        document_id, fake_client = self._verdwenen(geboekt_document, [])

        class PortZonderPoort:
            backend = Backend.RLZ

            def toets_geboekt(self, **_kw) -> ToetsUitkomst:
                return ToetsUitkomst(backend=Backend.RLZ, bestaat=False, reden="404")

            def __exit__(self, *exc) -> None:
                return None

        with pytest.raises(herboeken.BtwMogelijkAangegeven, match="niet controleerbaar"):
            herboeken.opnieuw_boeken_na_verdwijnen(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                rol=GebruikerRol.BOEKHOUDING,
                port=PortZonderPoort(),  # type: ignore[arg-type]
            )

    def test_open_periode_gaat_gewoon_door_en_legt_de_toets_vast(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake_client = self._verdwenen(geboekt_document, [AANGIFTE_Q1_INGEDIEND])  # Q1 raakt 22-06 niet
        r = herboeken.opnieuw_boeken_na_verdwijnen(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            reden=REDEN,
            rol=GebruikerRol.BOEKHOUDING,
            port=RlzInkoopPort(fake_client),
        )
        assert r.boek_cyclus == 1 and _status(admin_engine, document_id) == "klaar_om_te_boeken"
        ob = _laatste_overgang(administratie_id, document_id).detail["opnieuw_boeken"]
        assert ob["btw_poort"] == {
            "boekdatum": "2026-06-22",
            "toegestaan": True,
            "reden": None,
            "periode_start": None,
            "periode_eind": None,
            "doorgezet_met_bevestiging": False,
        }
        assert ob["btw_niet_in_aangifte_bevestigd"] is None
        assert "Beheerder-bevestiging" not in _laatste_overgang(administratie_id, document_id).detail["reden"]


class _FakeOdooClient:
    company_id = 1

    def __init__(self, rij: dict | None, *, faal: bool = False) -> None:
        self._rij = rij
        self._faal = faal

    def read_een(self, model: str, odoo_id: int, fields: list[str]) -> dict | None:
        if self._faal:
            raise OdooFout(500, "InternalError", "storing (simulatie)", model=model, methode="read")
        return self._rij


class TestOdooBtwPeriodePoort:
    """Odoo kent geen TaxDeclarations — de lock dates (tax/fiscalyear/purchase/hard) zijn het aangifte-equivalent."""

    def _port(self, client: _FakeOdooClient) -> OdooInkoopPort:
        return OdooInkoopPort(uuid.uuid4(), None, client)  # type: ignore[arg-type]

    def test_boekdatum_op_of_voor_lock_date_blokkeert(self) -> None:
        port = self._port(_FakeOdooClient({"tax_lock_date": "2026-06-30", "fiscalyear_lock_date": "2025-12-31"}))
        toets = port.toets_btw_periode(boekdatum=date(2026, 6, 22))
        assert toets.toegestaan is False and toets.periode_eind == date(2026, 6, 30)
        assert "btw-lock date t/m 2026-06-30" in (toets.reden or "")
        assert port.toets_btw_periode(boekdatum=date(2026, 6, 30)).toegestaan is False  # grens inclusief
        assert port.toets_btw_periode(boekdatum=date(2026, 7, 1)).toegestaan is True

    def test_geen_lock_dates_is_vrij_en_leesfout_is_fail_closed(self) -> None:
        assert self._port(_FakeOdooClient({})).toets_btw_periode(boekdatum=date(2026, 6, 22)).toegestaan is True
        toets = self._port(_FakeOdooClient(None, faal=True)).toets_btw_periode(boekdatum=date(2026, 6, 22))
        assert toets.toegestaan is False and "niet leesbaar" in (toets.reden or "")
        # company niet leesbaar (None) = OdooFout uit lees_lock_dates → ook fail-closed
        assert self._port(_FakeOdooClient(None)).toets_btw_periode(boekdatum=date(2026, 6, 22)).toegestaan is False
