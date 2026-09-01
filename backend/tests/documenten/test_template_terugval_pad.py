"""Deterministische extractie-terugval in de échte keten (best-practice-besluit 2, 31-08): drie
menselijke boekingen leren een template, het vierde document van dezelfde crediteur wordt zónder AI
geëxtraheerd (óók met de AI-gate uit), een layoutwijziging verwerpt volledig + markeert het template
ongeldig mét audit, een correctie door de controleur idem, automatisch geboekte documenten tellen niet
als leerbron, de kenmerk-sleutel werkt over administraties heen en de Instellingen-teller telt."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.auth import service as auth_service
from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, service
from app.documenten.models import CrediteurKenmerk, DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.extractie import template_service
from app.extractie.service import AiFactuurExtractie, AiVeld
from app.sync.models import VendorCache
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.extractie.pdf_helper import maak_tekst_pdf

VENDOR_ID = uuid.UUID("77777777-7777-7777-7777-777777777771")
BTW_NUMMER = "NL001234567B01"

_FACTUREN = [
    ("F-2026-042", date(2026, 6, 1), date(2026, 6, 30), "1.000,00", "210,00", "1.210,00"),
    ("F-2026-051", date(2026, 7, 1), date(2026, 7, 31), "1.000,00", "210,00", "1.210,00"),
    ("F-2026-063", date(2026, 8, 1), date(2026, 8, 31), "1.050,00", "220,50", "1.270,50"),
]
_VIERDE = ("F-2026-071", date(2026, 9, 1), date(2026, 9, 30), "1.050,00", "220,50", "1.270,50")


def _nl(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _pdf(
    nr: str, dat: date, verval: date, excl: str, btw: str, incl: str, *, incl_label: str = "Totaal incl. btw"
) -> bytes:
    return maak_tekst_pdf(
        [
            "Bouwmaat Nederland B.V.",
            f"Btw-nummer: {BTW_NUMMER}",
            [(50, "Factuurnummer"), (200, "Factuurdatum"), (350, "Vervaldatum")],
            [(50, nr), (200, _nl(dat)), (350, _nl(verval))],
            f"Totaal excl. btw   € {excl}",
            f"BTW 21%           € {btw}",
            f"{incl_label}   € {incl}",
        ]
    )


def _bedrag(tekst: str) -> Decimal:
    return Decimal(tekst.replace(".", "").replace(",", "."))


@pytest.fixture
def vendor_met_kenmerk(administratie_id: uuid.UUID) -> uuid.UUID:
    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(id=VENDOR_ID, administratie_id=administratie_id, naam="Bouwmaat Nederland B.V.", brondata={})
        )
        session.add(
            CrediteurKenmerk(
                administratie_id=administratie_id,
                vendor_id=VENDOR_ID,
                btw_nummer=BTW_NUMMER,
                btw_nummer_geverifieerd=True,
                btw_nummer_bron="handmatig",
            )
        )
    return VENDOR_ID


@pytest.fixture
def boeken_aan(beheerder_id: uuid.UUID, administratie_id: uuid.UUID) -> None:
    beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)


@pytest.fixture
def fake_ai(monkeypatch: pytest.MonkeyPatch) -> list[bytes]:
    """AI-gate aan + key aanwezig, maar de Claude-aanroep is een teller: zo bewijst een test dat het
    template-pad de AI niet raakte — en dat het AI-pad wél draait als het template wegvalt."""
    aanroepen: list[bytes] = []

    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None) -> AiFactuurExtractie:
        aanroepen.append(pdf_bytes)
        kop = {
            "leverancier_naam": AiVeld("Bouwmaat Nederland B.V.", 0.9),
            "factuurnummer": AiVeld("AI-REF", 0.9),
            "factuurdatum": AiVeld("2026-09-01", 0.9),
            "totaal_excl": AiVeld("1050.00", 0.9),
            "totaal_incl": AiVeld("1270.50", 0.9),
            "btw_bedrag": AiVeld("220.50", 0.9),
        }
        return AiFactuurExtractie(kop=kop, regels=[], bsn_verwijderd=0, volledig=True)

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    return aanroepen


@pytest.fixture
def ai_gate_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )


def _upload(
    administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag, inhoud: bytes, naam: str
) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id, bestandsnaam=naam, inhoud=inhoud, actor_id=actor_id, opslag=opslag
    ).document_id


def _boek(
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    document_id: uuid.UUID,
    factuur: tuple,
    monkeypatch: pytest.MonkeyPatch,
    *,
    referentie: str | None = None,
    extra_overgang_detail: dict | None = None,
) -> None:
    nr, dat, verval, excl, btw, incl = factuur
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=VENDOR_ID,
        referentie=referentie or nr,
        factuurdatum=dat,
        vervaldatum=verval,
        totaalbedrag=_bedrag(incl),
        regels=[
            boekvoorstel.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=uuid.uuid4(),
                project_id=None,
                netto_bedrag=_bedrag(excl),
                btw_bedrag=_bedrag(btw),
                omschrijving="Huur",
            )
        ],
    )
    monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
    resultaat = boeken.boek_document(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        extra_overgang_detail=extra_overgang_detail,
    )
    assert resultaat.status == DocumentStatus.GEBOEKT


def _leer_drie(administratie_id, actor_id, opslag, monkeypatch) -> list[uuid.UUID]:
    ids = []
    for i, factuur in enumerate(_FACTUREN):
        document_id = _upload(administratie_id, actor_id, opslag, _pdf(*factuur), f"factuur-{i}.pdf")
        _boek(administratie_id, actor_id, document_id, factuur, monkeypatch)
        ids.append(document_id)
    return ids


def _templates(admin_engine: Engine) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT sleutel, sleutel_soort, geldig, ongeldig_reden, versie, gebruikt_aantal, definitie "
                "FROM boekhouding.extractie_template ORDER BY sleutel"
            )
        ).mappings()
        return [dict(r) for r in rijen]


def _audit_acties(admin_engine: Engine, actie: str) -> int:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT count(*) FROM platform.audit_event WHERE actie = :a"), {"a": actie}
        ).scalar_one()


def _laatste_uitkomst(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict:
    detail = service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
    for g in reversed(detail.gebeurtenissen):
        if g.naar_status in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN) and g.detail:
            return g.detail
    raise AssertionError("geen extractie-uitkomst in de tijdlijn")


class TestLerenEnToepassen:
    def test_drie_boekingen_leren_template_vierde_zonder_ai(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
        ai_gate_aan: None,
        fake_ai: list[bytes],
    ) -> None:
        # Vóór het template: de eerste drie gaan gewoon door de (fake) AI.
        _leer_drie(administratie_id, gescoopte_gebruiker, opslag, monkeypatch)
        assert len(fake_ai) == 3
        [template] = _templates(admin_engine)
        assert template["sleutel"] == f"btw:{BTW_NUMMER}" and template["sleutel_soort"] == "btw_nummer"
        assert template["geldig"] is True and template["versie"] == 1
        assert template["definitie"]["regels_modus"] == "enkel"
        assert _audit_acties(admin_engine, "extractie_template_geleerd") == 1

        vierde = _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE), "factuur-4.pdf")
        assert len(fake_ai) == 3, "het template-pad mag de AI niet raken"
        uitkomst = _laatste_uitkomst(administratie_id, vierde)
        assert uitkomst["extractie_bron"] == "template"
        # Een menselijke upload draagt geen systeem-reden; de worker/systeem-variant benoemt de bron.
        assert "reden" not in uitkomst or uitkomst["reden"].startswith("extractie afgerond via template")
        voorstel = uitkomst["veldvoorstel"]
        assert voorstel["bron"] == "template"
        assert voorstel["factuurnummer"] == "F-2026-071"
        assert voorstel["factuurdatum"] == "2026-09-01" and voorstel["vervaldatum"] == "2026-09-30"
        assert (voorstel["totaal_excl"], voorstel["btw_bedrag"], voorstel["totaal_incl"]) == (
            "1050.00",
            "220.50",
            "1270.50",
        )
        assert voorstel["vendor_suggestie"] == {"vendor_id": str(VENDOR_ID), "match": "btw_nummer"}
        assert voorstel["template"]["herkend_op"] == "btw_nummer"
        assert voorstel["zekerheid"]["factuurnummer"] == 1.0
        assert voorstel["controle"]["regelsom_wijkt_af"] is False
        assert voorstel["regels"][0]["netto_bedrag"] == "1050.00"
        # Downstream ongewijzigd: het boekvoorstel-prefill leest hetzelfde veldvoorstel.
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=vierde)
        assert prefill.referentie == "F-2026-071" and prefill.totaalbedrag == Decimal("1270.50")
        [template] = _templates(admin_engine)
        assert template["gebruikt_aantal"] == 1

    def test_werkt_ook_met_ai_gate_uit_en_zonder_key(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
    ) -> None:
        """Het template-pad staat NIET achter de AVG-gate: lokale code, geen data naar buiten."""
        _leer_drie(administratie_id, gescoopte_gebruiker, opslag, monkeypatch)
        vierde = _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE), "factuur-4.pdf")
        uitkomst = _laatste_uitkomst(administratie_id, vierde)
        assert uitkomst["veldvoorstel"]["bron"] == "template"
        assert "ai_extractie_overgeslagen" not in uitkomst

    def test_layoutwijziging_verwerpt_volledig_en_markeert_ongeldig(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
        ai_gate_aan: None,
        fake_ai: list[bytes],
    ) -> None:
        _leer_drie(administratie_id, gescoopte_gebruiker, opslag, monkeypatch)
        nieuw = _upload(
            administratie_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE, incl_label="Te betalen"), "factuur-nieuw.pdf"
        )
        assert len(fake_ai) == 4, "verworpen template → het AI-pad neemt het over"
        uitkomst = _laatste_uitkomst(administratie_id, nieuw)
        assert uitkomst["veldvoorstel"]["bron"] == "ai"  # géén half template-voorstel
        assert uitkomst["veldvoorstel"]["factuurnummer"] == "AI-REF"
        assert "template verworpen" in uitkomst["template_terugval"]
        [template] = _templates(admin_engine)
        assert template["geldig"] is False
        assert "totaal_incl niet gevonden" in template["ongeldig_reden"]
        assert _audit_acties(admin_engine, "extractie_template_ongeldig") == 1
        # Ongeldig template = niet meer toegepast, ook niet op een document dat wél zou passen.
        weer = _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE), "factuur-5.pdf")
        assert len(fake_ai) == 5
        assert _laatste_uitkomst(administratie_id, weer)["veldvoorstel"]["bron"] == "ai"

    def test_correctie_door_controleur_maakt_template_ongeldig(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
    ) -> None:
        _leer_drie(administratie_id, gescoopte_gebruiker, opslag, monkeypatch)
        vierde = _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE), "factuur-4.pdf")
        assert _laatste_uitkomst(administratie_id, vierde)["veldvoorstel"]["bron"] == "template"
        # De controleur corrigeert de referentie vóór het boeken: het template las 'm dus verkeerd.
        _boek(administratie_id, gescoopte_gebruiker, vierde, _VIERDE, monkeypatch, referentie="F-2026-071-A")
        [template] = _templates(admin_engine)
        assert template["geldig"] is False
        assert "bevestigde waarden" in template["ongeldig_reden"]
        assert _audit_acties(admin_engine, "extractie_template_ongeldig") == 1
        # Opnieuw leren uit de laatste drie (incl. de correctie) kán niet: de tekst zegt iets anders.
        assert _audit_acties(admin_engine, "extractie_template_geleerd") == 1

    def test_bevestiging_die_klopt_laat_template_staan_en_leert_niet_opnieuw(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
    ) -> None:
        _leer_drie(administratie_id, gescoopte_gebruiker, opslag, monkeypatch)
        vierde = _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE), "factuur-4.pdf")
        _boek(administratie_id, gescoopte_gebruiker, vierde, _VIERDE, monkeypatch)
        [template] = _templates(admin_engine)
        assert template["geldig"] is True and template["versie"] == 1
        assert _audit_acties(admin_engine, "extractie_template_geleerd") == 1

    def test_automatisch_geboekte_documenten_zijn_geen_leerbron(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
    ) -> None:
        for i, factuur in enumerate(_FACTUREN):
            document_id = _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*factuur), f"auto-{i}.pdf")
            _boek(
                administratie_id,
                gescoopte_gebruiker,
                document_id,
                factuur,
                monkeypatch,
                extra_overgang_detail={"automatisch_geboekt": True, "bron": "leverancier_opt_in"},
            )
        assert _templates(admin_engine) == []

    def test_twee_boekingen_leren_nog_niets(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
    ) -> None:
        for i, factuur in enumerate(_FACTUREN[:2]):
            document_id = _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*factuur), f"factuur-{i}.pdf")
            _boek(administratie_id, gescoopte_gebruiker, document_id, factuur, monkeypatch)
        assert _templates(admin_engine) == []


class TestKenmerkSleutelOverAdministratiesHeen:
    def test_template_uit_administratie_a_werkt_in_administratie_b(
        self,
        gescoopte_gebruiker: uuid.UUID,
        beheerder_id: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
    ) -> None:
        _leer_drie(administratie_id, gescoopte_gebruiker, opslag, monkeypatch)
        # Administratie B: eigen vendor-GUID, zelfde btw-nummer op de crediteurkaart.
        b_id = uuid.uuid4()
        b_vendor = uuid.uuid4()
        with admin_engine.begin() as conn:
            conn.execute(
                text("INSERT INTO platform.administratie (id, naam, rlz_admin_id) VALUES (:id, 'B', :rlz)"),
                {"id": b_id, "rlz": f"rlz-{b_id}"},
            )
        auth_service.voeg_scope_toe(actor_id=beheerder_id, doel_gebruiker_id=gescoopte_gebruiker, administratie_id=b_id)
        with scoped_session(b_id) as session:
            session.add(VendorCache(id=b_vendor, administratie_id=b_id, naam="Bouwmaat Nederland B.V.", brondata={}))
            session.add(
                CrediteurKenmerk(
                    administratie_id=b_id, vendor_id=b_vendor, btw_nummer=BTW_NUMMER, btw_nummer_bron="handmatig"
                )
            )
        document_id = _upload(b_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE), "factuur-b.pdf")
        voorstel = _laatste_uitkomst(b_id, document_id)["veldvoorstel"]
        assert voorstel["bron"] == "template"
        assert voorstel["vendor_suggestie"]["vendor_id"] == str(b_vendor)


class TestMaandStatistiek:
    def test_telt_template_en_ai_en_actieve_templates(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        monkeypatch: pytest.MonkeyPatch,
        vendor_met_kenmerk: uuid.UUID,
        boeken_aan: None,
        ai_gate_aan: None,
        fake_ai: list[bytes],
    ) -> None:
        _leer_drie(administratie_id, gescoopte_gebruiker, opslag, monkeypatch)
        _upload(administratie_id, gescoopte_gebruiker, opslag, _pdf(*_VIERDE), "factuur-4.pdf")
        stat = template_service.maand_statistiek()
        assert (stat.via_template, stat.via_ai, stat.templates_actief) == (1, 3, 1)
