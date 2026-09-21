# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
""" "Corrigeren…" op een GEBOEKT inkoopdocument (opdracht Peter 21-09, casus BLOW RLZ-04-00000357/358 fout btw-bedrag):
storno (actie 19) + opnieuw klaarzetten vanuit de module, in één handeling mét verplichte reden.

- effect: RLZ-document Status 1 (terug-gelezen), GEBOEKT → KLAAR_OM_TE_BOEKEN, boek_cyclus +1 (vers GUID), boekstuknummer
  leeg, tijdlijnregel `gecorrigeerd` (reden + vorige boeking), audit `document_gecorrigeerd`; daarna boekt het gewone
  boekpad op het NIEUWE GUID en het oude concept is als eigen keten uitgezonderd van het duplicaatsignaal;
- poorten: aangifte → blokkade `aangifte` mét route tegenboeken (niets gewijzigd); (deels) betaald → `afgeletterd` mét
  bank-link; doorbelasting-kant geblokkeerd → `doorbelasting`; verdwenen → `verdwenen` (opnieuw boeken); Odoo →
  `niet_ondersteund` (tegenboeken); reden < 5 tekens → fout;
- idempotentie: tweemaal klikken = één storno (tweede = `AlGecorrigeerd`, 409 `al_gecorrigeerd`);
- doorbelasting-bron: spiegel(s) via de bestaande motor mee, vóór de eigen storno; mislukt = zichtbaar, niets lokaal;
- vastgoed: `factuur_gestorneerd` (bron module_storno) in dezelfde boekstand-reeks als het geboekt-event."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.backends.port import Backend, NietOndersteund, OrigineelStand, ToetsUitkomst
from app.backends.rlz_inkoop import RlzInkoopPort
from app.beheer import service as beheer_service
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, corrigeren, service
from app.documenten.models import DocumentGebeurtenis, DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id
from app.documenten.statusmachine import valideer_overgang
from app.documenten.storage import LokaleBestandsopslag
from app.main import app
from app.odoo.inkoop import OdooInkoopPort
from app.rlz.aangifte import KantToets
from tests.documenten.fake_rlz_client import FakeBoekClient
from tests.documenten.test_duplicaat_afvoer import _bearer

REDEN = "btw-bedrag stond op 48,18 in plaats van 56,93 (Fac-25-023465)"
# Factuurdatum in de fixture = 22-06-2026 → Q2.
AANGIFTE_Q2_INGEDIEND = {"Status": 2, "StartDate": "2026-04-01T00:00:00", "Date": "2026-06-30T00:00:00"}


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
        inhoud=b"%PDF-1.4 corrigeren",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    )
    boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=resultaat.document_id,
        actor_id=gescoopte_gebruiker,
        vendor_id=uuid.uuid4(),
        referentie="Fac-25-023465",
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
        return conn.execute(
            text("SELECT status FROM boekhouding.document WHERE id = :id"), {"id": document_id}
        ).scalar_one()


def _voorstel(admin_engine: Engine, document_id: uuid.UUID) -> tuple[int, str | None]:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT boek_cyclus, rlz_boekstuknummer FROM boekhouding.boekvoorstel WHERE document_id = :id"),
            {"id": document_id},
        ).one()


def _audits(admin_engine: Engine, document_id: uuid.UUID, actie: str) -> list:
    with admin_engine.connect() as conn:
        return conn.execute(
            text("SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event WHERE record_id = :id AND actie = :a"),
            {"id": document_id, "a": actie},
        ).all()


def _corrigeer(administratie_id, document_id, actor_id, fake_client, **kwargs):
    return corrigeren.corrigeer(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        reden=REDEN,
        port=RlzInkoopPort(fake_client),
        doorbelasting_toets=kwargs.pop("doorbelasting_toets", lambda **_: {}),
        **kwargs,
    )


class TestCorrigeerInkoop:
    def test_storno_en_klaar_om_te_boeken(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        oud_guid = rlz_herboeking_id(document_id, 0)
        assert fake._invoices[str(oud_guid)]["Status"] == 2
        assert _voorstel(admin_engine, document_id)[1]  # boekstuknummer vóór

        r = _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)

        assert r.status is DocumentStatus.KLAAR_OM_TE_BOEKEN
        assert r.boek_cyclus == 1
        assert r.gestorneerd == [str(oud_guid)] and r.al_concept == []
        assert r.oud_extern_id == str(oud_guid) and r.oud_boekstuknummer
        assert r.doel_pad == f"/documenten/{administratie_id}/{document_id}"
        # RLZ: hetzelfde document terug naar concept (actie 19), geen delete, geen creditstuk.
        assert fake.correcties == [oud_guid]
        assert fake._invoices[str(oud_guid)]["Status"] == 1
        # Lokaal: statusovergang + vers GUID voor de herboeking + boekstuknummer leeg.
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"
        assert _voorstel(admin_engine, document_id) == (1, None)
        assert rlz_herboeking_id(document_id, 1) != oud_guid
        # Tijdlijnregel `gecorrigeerd` mét reden + vorige boeking (bron van de gele balk).
        with scoped_session(administratie_id) as session:
            laatste = (
                session.query(DocumentGebeurtenis)
                .filter_by(document_id=document_id)
                .order_by(DocumentGebeurtenis.tijdstip.desc())
                .first()
            )
        assert laatste.naar_status is DocumentStatus.KLAAR_OM_TE_BOEKEN
        corr = laatste.detail["gecorrigeerd"]
        assert (
            corr["reden"] == REDEN
            and corr["oud_extern_id"] == str(oud_guid)
            and corr["oud_boekstuknummer"] == r.oud_boekstuknummer
        )
        assert corr["oude_cyclus"] == 0 and corr["nieuwe_cyclus"] == 1
        assert "gecorrigeerd" in laatste.detail["reden"] and REDEN in laatste.detail["reden"]
        # Audit mét reden, oud extern id, oud boekstuknummer.
        [(oud, nieuw)] = _audits(admin_engine, document_id, "document_gecorrigeerd")
        assert (
            oud["status"] == "geboekt"
            and oud["extern_id"] == str(oud_guid)
            and oud["rlz_boekstuknummer"] == r.oud_boekstuknummer
        )
        assert nieuw["reden"] == REDEN and nieuw["status"] == "klaar_om_te_boeken" and nieuw["boek_cyclus"] == 1

    def test_statusmachine_kent_de_uitgang(self) -> None:
        valideer_overgang(DocumentStatus.GEBOEKT, DocumentStatus.KLAAR_OM_TE_BOEKEN)

    def test_daarna_boekt_het_gewone_pad_op_het_nieuwe_guid(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        assert _status(admin_engine, document_id) == "geboekt"
        assert fake._invoices[str(rlz_herboeking_id(document_id, 1))]["Status"] == 2
        assert fake._invoices[str(rlz_herboeking_id(document_id, 0))]["Status"] == 1  # oud concept blijft staan
        assert _voorstel(admin_engine, document_id)[1]  # nieuw boekstuknummer

    def test_toets_beschikbaar(self, geboekt_document, administratie_id, gescoopte_gebruiker) -> None:
        document_id, fake = geboekt_document
        t = corrigeren.toets(
            administratie_id=administratie_id,
            document_id=document_id,
            port=RlzInkoopPort(fake),
            doorbelasting_toets=lambda **_: {},
        )
        assert t.beschikbaar and t.blokkades == [] and t.backend == "rlz"
        assert t.oud_boekstuknummer and t.stukken[0].nog_geboekt and t.stukken[0].bestaat
        assert t.tegenboeken_beschikbaar is False

    def test_reden_verplicht(self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine) -> None:
        document_id, fake = geboekt_document
        with pytest.raises(corrigeren.CorrigerenFout, match="minimaal 5"):
            corrigeren.corrigeer(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden="kort",
                port=RlzInkoopPort(fake),
            )
        assert (
            _status(admin_engine, document_id) == "geboekt" and fake.correcties == []
            if hasattr(fake, "correcties")
            else True
        )

    def test_tweemaal_klikken_is_een_storno(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        with pytest.raises(corrigeren.AlGecorrigeerd) as exc:
            _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        assert exc.value.als_detail()["code"] == "al_gecorrigeerd"
        assert len(fake.correcties) == 1
        assert _voorstel(admin_engine, document_id)[0] == 1
        # De toets op een niet-geboekt document zegt het óók, zonder RLZ-call.
        t = corrigeren.toets(administratie_id=administratie_id, document_id=document_id, port=RlzInkoopPort(fake))
        assert not t.beschikbaar and t.blokkades[0].code == "status"

    def test_al_concept_in_rlz_ui_zet_lokaal_wel_klaar(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        """Iemand deed de storno al rechtstreeks in de RLZ-UI: niets schrijven, wél opnieuw klaarzetten."""
        document_id, fake = geboekt_document
        oud_guid = rlz_herboeking_id(document_id, 0)
        fake._invoices[str(oud_guid)]["Status"] = 1
        r = _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        assert r.gestorneerd == [] and r.al_concept == [str(oud_guid)]
        assert getattr(fake, "correcties", []) == []
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"


class TestPoorten:
    def test_aangifte_blokkeert_en_wijst_naar_tegenboeken(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        fake.aangiften = [AANGIFTE_Q2_INGEDIEND]
        t = corrigeren.toets(
            administratie_id=administratie_id,
            document_id=document_id,
            port=RlzInkoopPort(fake),
            doorbelasting_toets=lambda **_: {},
        )
        assert not t.beschikbaar
        [b] = t.blokkades
        assert b.code == "aangifte" and b.actie == "tegenboeken" and "2026-04-01 t/m 2026-06-30" in b.melding
        assert t.tegenboeken_beschikbaar is True
        with pytest.raises(corrigeren.CorrigerenNietToegestaan) as exc:
            _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        assert exc.value.als_detail()["code"] == "aangifte"
        assert _status(admin_engine, document_id) == "geboekt" and _voorstel(admin_engine, document_id)[0] == 0
        assert getattr(fake, "correcties", []) == []

    def test_aangifte_niet_leesbaar_is_fail_closed(
        self, geboekt_document, administratie_id, gescoopte_gebruiker
    ) -> None:
        document_id, fake = geboekt_document
        fake.faal_op = "aangiften"
        t = corrigeren.toets(
            administratie_id=administratie_id,
            document_id=document_id,
            port=RlzInkoopPort(fake),
            doorbelasting_toets=lambda **_: {},
        )
        assert not t.beschikbaar and t.blokkades[0].code == "niet_leesbaar" and t.blokkades[0].actie == "tegenboeken"

    def test_afgeletterd_blokkeert_met_bank_link(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        fake._invoices[str(rlz_herboeking_id(document_id, 0))]["BasePaidAmount"] = 121.0
        t = corrigeren.toets(
            administratie_id=administratie_id,
            document_id=document_id,
            port=RlzInkoopPort(fake),
            doorbelasting_toets=lambda **_: {},
        )
        [b] = t.blokkades
        assert (
            b.code == "afgeletterd"
            and b.actie == "bank"
            and b.actie_pad == f"/bank/{administratie_id}?zoek=Fac-25-023465"
        )
        assert "bankmodule" in b.melding
        with pytest.raises(corrigeren.CorrigerenNietToegestaan):
            _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        assert _status(admin_engine, document_id) == "geboekt" and getattr(fake, "correcties", []) == []

    def test_verdwenen_is_de_reconciliatie_route(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        del fake._invoices[str(rlz_herboeking_id(document_id, 0))]
        t = corrigeren.toets(
            administratie_id=administratie_id,
            document_id=document_id,
            port=RlzInkoopPort(fake),
            doorbelasting_toets=lambda **_: {},
        )
        [b] = t.blokkades
        assert b.code == "verdwenen" and b.actie == "opnieuw_boeken" and b.actie_pad == "/reconciliatie"
        with pytest.raises(corrigeren.CorrigerenNietToegestaan):
            _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        assert _status(admin_engine, document_id) == "geboekt"

    def test_rlz_storno_fout_laat_alles_staan(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        fake.faal_op = "correct"
        with pytest.raises(corrigeren.CorrigerenMislukt, match="niets lokaal gewijzigd"):
            _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        assert _status(admin_engine, document_id) == "geboekt" and _voorstel(admin_engine, document_id)[0] == 0
        assert fake._invoices[str(rlz_herboeking_id(document_id, 0))]["Status"] == 2
        assert _audits(admin_engine, document_id, "document_correctie_mislukt")


class _OdooAchtigePort:
    """Stub mét de Odoo-capability-set: origineel_stand zegt 'geen storno op hetzelfde document', storneer raise-t."""

    backend = Backend.ODOO

    def __enter__(self):
        return self

    def __exit__(self, *exc_info: object) -> None:
        return None

    def leesclient(self):
        return None

    def origineel_stand(self, *, document_id, boek_cyclus):
        return OrigineelStand(
            kant=KantToets(
                kant="inkoopfactuur",
                toegestaan=False,
                reden="Odoo kent geen storno op hetzelfde document — corrigeren = creditnota (reversal) mét kruisverwijzing",
            ),
            nog_geboekt=True,
            betaald_bedrag=Decimal(0),
            open_bedrag=Decimal("121.00"),
            volledig_afgeletterd=False,
        )

    def toets_geboekt(self, *, document_id, boek_cyclus, boekstuknummer=None):
        return ToetsUitkomst(
            backend=Backend.ODOO, bestaat=True, geboekt=True, boekstuknummer="BILL/2026/0042", extern_id="42"
        )

    def storneer(self, *, document_id, boek_cyclus):
        raise NietOndersteund("Odoo kent geen storno op hetzelfde document")


class TestOdoo:
    def test_odoo_is_zichtbaar_niet_ondersteund_met_tegenboek_route(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, _fake = geboekt_document
        t = corrigeren.toets(
            administratie_id=administratie_id,
            document_id=document_id,
            port=_OdooAchtigePort(),
            doorbelasting_toets=lambda **_: {},
        )
        assert t.backend == "odoo" and not t.beschikbaar
        [b] = t.blokkades
        assert b.code == "niet_ondersteund" and b.actie == "tegenboeken" and "Tegenboeken" in b.melding
        assert t.tegenboeken_beschikbaar is True
        with pytest.raises(corrigeren.CorrigerenNietToegestaan):
            corrigeren.corrigeer(
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=gescoopte_gebruiker,
                reden=REDEN,
                port=_OdooAchtigePort(),
                doorbelasting_toets=lambda **_: {},
            )
        assert _status(admin_engine, document_id) == "geboekt"

    def test_odoo_adapter_storneer_is_niet_ondersteund(self) -> None:
        """Capability-contract 0016 §4: de échte adapter raise-t, zonder Odoo-call (verbinding/client None)."""
        port = OdooInkoopPort(uuid.uuid4(), None, None)  # type: ignore[arg-type]
        with pytest.raises(NietOndersteund, match="Tegenboeken"):
            port.storneer(document_id=uuid.uuid4(), boek_cyclus=0)


class TestDoorbelasting:
    def test_spiegels_gaan_mee_voor_de_eigen_storno(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        boeking_id = uuid.uuid4()
        volgorde: list[str] = []
        aanroepen: list[dict] = []

        def toets_fn(**_):
            return {
                boeking_id: [
                    KantToets(kant="verkoopfactuur (bron-administratie)", toegestaan=True),
                    KantToets(kant="spiegel-inkoopfactuur (Molenhof Beheer)", toegestaan=True),
                ]
            }

        def storno_fn(**kwargs):
            aanroepen.append(kwargs)
            volgorde.append("doorbelasting")

        origineel = fake.correct_purchase_invoice

        def correct(invoice_id):
            volgorde.append("inkoop")
            return origineel(invoice_id)

        fake.correct_purchase_invoice = correct  # type: ignore[method-assign]
        r = _corrigeer(
            administratie_id,
            document_id,
            gescoopte_gebruiker,
            fake,
            doorbelasting_toets=toets_fn,
            doorbelasting_storno=storno_fn,
        )
        assert r.doorbelasting_gestorneerd == 1
        assert volgorde == ["doorbelasting", "inkoop"]  # spiegel eerst, dan het eigen stuk
        [kw] = aanroepen
        assert kw["boeking_id"] == boeking_id and kw["administratie_id"] == administratie_id and REDEN in kw["reden"]
        with scoped_session(administratie_id) as session:
            laatste = (
                session.query(DocumentGebeurtenis)
                .filter_by(document_id=document_id)
                .order_by(DocumentGebeurtenis.tijdstip.desc())
                .first()
            )
        assert laatste.detail["gecorrigeerd"]["doorbelasting_teruggedraaid"] == ["?"]

    def test_geblokkeerde_spiegel_blokkeert_alles(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        boeking_id = uuid.uuid4()

        def toets_fn(**_):
            return {
                boeking_id: [
                    KantToets(kant="verkoopfactuur (bron-administratie)", toegestaan=True),
                    KantToets(
                        kant="spiegel-inkoopfactuur (Molenhof Beheer)",
                        toegestaan=False,
                        reden="boekdatum 2026-06-22 valt in de ingediende btw-aangifte 2026-04-01 t/m 2026-06-30",
                    ),
                ]
            }

        aanroepen: list = []
        t = corrigeren.toets(
            administratie_id=administratie_id,
            document_id=document_id,
            port=RlzInkoopPort(fake),
            doorbelasting_toets=toets_fn,
        )
        [b] = t.blokkades
        assert (
            b.code == "doorbelasting" and "beide kanten of geen" in b.melding and "ingediende btw-aangifte" in b.melding
        )
        with pytest.raises(corrigeren.CorrigerenNietToegestaan):
            _corrigeer(
                administratie_id,
                document_id,
                gescoopte_gebruiker,
                fake,
                doorbelasting_toets=toets_fn,
                doorbelasting_storno=lambda **kw: aanroepen.append(kw),
            )
        assert aanroepen == [] and getattr(fake, "correcties", []) == []
        assert _status(admin_engine, document_id) == "geboekt"

    def test_mislukte_spiegel_storno_is_zichtbaar_en_laat_lokaal_alles_staan(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        boeking_id = uuid.uuid4()

        def toets_fn(**_):
            return {boeking_id: [KantToets(kant="verkoopfactuur (bron-administratie)", toegestaan=True)]}

        def storno_fn(**_):
            raise RuntimeError("Storno spiegel-inkoopfactuur bij Molenhof faalde (500)")

        with pytest.raises(corrigeren.CorrigerenMislukt, match="Molenhof faalde"):
            _corrigeer(
                administratie_id,
                document_id,
                gescoopte_gebruiker,
                fake,
                doorbelasting_toets=toets_fn,
                doorbelasting_storno=storno_fn,
            )
        assert getattr(fake, "correcties", []) == [] and _status(admin_engine, document_id) == "geboekt"
        assert _audits(admin_engine, document_id, "document_correctie_mislukt")


class TestWebhook:
    def test_vastgoed_krijgt_factuur_gestorneerd_in_dezelfde_reeks(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        with admin_engine.begin() as conn:
            conn.execute(
                text("UPDATE platform.administratie SET is_vastgoed = true WHERE id = :id"), {"id": administratie_id}
            )
        # De fixture boekte vóór de vlag → nog geen geboekt-event; boek een tweede keer (herboeken-idioom) om de reeks te starten.
        _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)
        _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT event, payload FROM boekhouding.webhook_uitgaand WHERE document_id = :id ORDER BY aangemaakt_op"
                ),
                {"id": document_id},
            ).all()
        guid1 = str(rlz_herboeking_id(document_id, 1))
        reeks = [r for r in rijen if r.payload["data"]["rlz_document_id"] == guid1]
        assert [r.event for r in reeks] == ["factuur_geboekt", "factuur_gestorneerd"]
        data = reeks[1].payload["data"]
        assert data["volgnummer"] == 2 and data["bron"] == "module_storno" and REDEN in data["reden"]

    def test_niet_vastgoed_geen_event(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine
    ) -> None:
        document_id, fake = geboekt_document
        _corrigeer(administratie_id, document_id, gescoopte_gebruiker, fake)
        with admin_engine.connect() as conn:
            n = conn.execute(
                text("SELECT count(*) FROM boekhouding.webhook_uitgaand WHERE document_id = :id"), {"id": document_id}
            ).scalar_one()
        assert n == 0


class TestHttp:
    def test_toets_en_corrigeren_via_de_route(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, admin_engine, monkeypatch
    ) -> None:
        from fastapi.testclient import TestClient

        document_id, fake = geboekt_document
        monkeypatch.setattr(corrigeren, "_port_voor", lambda administratie_id: RlzInkoopPort(fake))
        monkeypatch.setattr(corrigeren, "_standaard_doorbelasting_toets", lambda **_: {})
        client = TestClient(app)
        kop = _bearer(gescoopte_gebruiker, rol="boekhouding")
        r = client.get(f"/administraties/{administratie_id}/documenten/{document_id}/corrigeer-toets", headers=kop)
        assert r.status_code == 200, r.text
        assert r.json()["beschikbaar"] is True and r.json()["blokkades"] == []

        r = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/corrigeren",
            json={"reden": REDEN},
            headers=kop,
        )
        assert r.status_code == 200, r.text
        body = r.json()
        assert (
            body["status"] == "klaar_om_te_boeken"
            and body["boek_cyclus"] == 1
            and body["doel_pad"].startswith("/documenten/")
        )
        assert _status(admin_engine, document_id) == "klaar_om_te_boeken"

        # Tweede klik: 409 mét herkenbare code, geen tweede storno.
        r = client.post(
            f"/administraties/{administratie_id}/documenten/{document_id}/corrigeren",
            json={"reden": REDEN},
            headers=kop,
        )
        assert r.status_code == 409 and r.json()["detail"]["code"] == "al_gecorrigeerd"
        assert len(fake.correcties) == 1

    def test_blokkade_als_409_met_blokkades(
        self, geboekt_document, administratie_id, gescoopte_gebruiker, monkeypatch
    ) -> None:
        from fastapi.testclient import TestClient

        document_id, fake = geboekt_document
        fake.aangiften = [AANGIFTE_Q2_INGEDIEND]
        monkeypatch.setattr(corrigeren, "_port_voor", lambda administratie_id: RlzInkoopPort(fake))
        monkeypatch.setattr(corrigeren, "_standaard_doorbelasting_toets", lambda **_: {})
        r = TestClient(app).post(
            f"/administraties/{administratie_id}/documenten/{document_id}/corrigeren",
            json={"reden": REDEN},
            headers=_bearer(gescoopte_gebruiker, rol="boekhouding"),
        )
        assert r.status_code == 409, r.text
        detail = r.json()["detail"]
        assert detail["code"] == "aangifte" and detail["blokkades"][0]["actie"] == "tegenboeken"
