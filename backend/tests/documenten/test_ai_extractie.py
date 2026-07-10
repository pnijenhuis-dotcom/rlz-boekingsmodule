from __future__ import annotations

import uuid

import pytest

from app.beheer import service as beheer_service
from app.config import settings
from app.documenten import boekvoorstel, service
from app.documenten.models import DocumentStatus
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.sync import service as sync_service
from tests.sync.conftest import FakeRlzClient

_PDF = b"%PDF-1.4 ai-extractie-test"


def _veld(waarde: str | None, zekerheid: float = 0.95) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _fake_extractie(volledig: bool = True) -> AiFactuurExtractie:
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("Bouwmaat Nederland BV"),  # fuzzy t.o.v. cache ("B.V.")
            "factuurnummer": _veld("F-2026-042"),
            "factuurdatum": _veld("2026-07-01"),
            "vervaldatum": _veld("2026-07-31", zekerheid=0.5),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld("150.00"),
            "totaal_incl": _veld("178.50"),
            "btw_bedrag": _veld("28.50"),
        },
        regels=[
            AiRegel(
                omschrijving="Steigerhout", netto_bedrag="100.00", btw_bedrag="21.00", hoeveelheid="4", zekerheid=0.95
            ),
            AiRegel(
                omschrijving="Bezorging", netto_bedrag="50.00", btw_bedrag="7.50", hoeveelheid=None, zekerheid=0.9
            ),
        ],
        bsn_verwijderd=0,
        volledig=volledig,
    )


@pytest.fixture
def ai_gate_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )


@pytest.fixture
def fake_extraheer(monkeypatch: pytest.MonkeyPatch):
    """Vervangt de echte Claude-aanroep — de kale suite doet nooit echte API-calls. De fixture
    registreert hoe vaak hij is aangeroepen zodat gate-tests kunnen bewijzen dat er níks naar de
    AI ging."""
    aanroepen: list[bytes] = []

    def _fake(pdf_bytes: bytes, *, client=None) -> AiFactuurExtractie:
        aanroepen.append(pdf_bytes)
        return _fake_extractie()

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)
    return aanroepen


def _upload_pdf(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag):
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="factuur.pdf",
        inhoud=_PDF,
        actor_id=actor_id,
        opslag=opslag,
    )


def _extractie_detail(administratie_id: uuid.UUID, document_id: uuid.UUID) -> dict | None:
    detail = service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
    for gebeurtenis in detail.gebeurtenissen:
        if gebeurtenis.naar_status in (DocumentStatus.TE_CONTROLEREN, DocumentStatus.HANDMATIG_AFMAKEN):
            return gebeurtenis.detail
    return None


class TestAvgGate:
    def test_gate_uit_default_stuurt_niets_naar_de_ai(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)

        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        assert fake_extraheer == []  # niets naar de Claude API zonder expliciete opt-in
        detail = _extractie_detail(administratie_id, resultaat.document_id)
        assert detail == {"ai_extractie_overgeslagen": "ai_extractie_uitgeschakeld"}

    def test_gate_aan_zonder_api_key_slaat_zichtbaar_over(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)

        assert fake_extraheer == []
        detail = _extractie_detail(administratie_id, resultaat.document_id)
        assert detail == {"ai_extractie_overgeslagen": "geen_api_key"}

    def test_ubl_gaat_nooit_via_de_ai_route(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.documenten.test_ubl import _VOORBEELD_UBL

        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        assert fake_extraheer == []  # UBL blijft de deterministische bron


class TestAiVoorstel:
    def test_voorstel_belandt_in_tijdlijn_en_prefillt_boekvoorstel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        vendor_id, taxrate_hoog = uuid.uuid4(), uuid.uuid4()
        sync_service.sync_vendors(
            administratie_id=administratie_id,
            client=FakeRlzClient(
                {"Vendors": [{"id": str(vendor_id), "Name": "Bouwmaat Nederland B.V.", "IsArchived": False}]}
            ),
        )
        sync_service.sync_taxrates(
            administratie_id=administratie_id,
            client=FakeRlzClient(
                {
                    "TaxRates": [
                        {"id": str(taxrate_hoog), "Name": "21% inkoop", "Percentage": 0.21},
                        {"id": str(uuid.uuid4()), "Name": "9% inkoop", "Percentage": 0.09},
                    ]
                }
            ),
        )

        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)
        assert fake_extraheer == [_PDF]

        detail = _extractie_detail(administratie_id, resultaat.document_id)
        assert detail is not None and "veldvoorstel" in detail
        voorstel = detail["veldvoorstel"]
        assert voorstel["bron"] == "ai"
        assert voorstel["vendor_suggestie"] == {"vendor_id": str(vendor_id), "match": "fuzzy"}
        assert voorstel["zekerheid"]["factuurnummer"] == 0.95
        assert "vervaldatum" in voorstel["controle"]["lage_zekerheid"]
        # 100+21+50+7.50 = 178.50 — regelsom sluit aan op het gelezen totaal.
        assert voorstel["controle"]["regelsom_wijkt_af"] is False

        data = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=resultaat.document_id
        )
        assert data.opgeslagen is False
        assert data.vendor_id == vendor_id
        assert data.referentie == "F-2026-042"
        assert str(data.totaalbedrag) == "178.50"
        assert len(data.regels) == 2
        assert data.regels[0].taxrate_id == taxrate_hoog  # 21% uniek uit de cache
        assert data.regels[1].taxrate_id is None  # 15% bestaat niet in de cache — geen gok
        assert all(regel.ledger_id is None for regel in data.regels)  # GB pas met boekingsgeheugen

    def test_voorstel_boekt_nooit_automatisch(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)

        # Eindstatus is en blijft te_controleren: de mens drukt, nooit de AI.
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        doorlopen = {g.naar_status for g in detail.gebeurtenissen}
        assert DocumentStatus.KLAAR_OM_TE_BOEKEN not in doorlopen
        assert DocumentStatus.GEBOEKT not in doorlopen

    def test_opnieuw_extraheren_na_transiente_fout(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Timeout-fix 2026-07-10: eerste extractie faalt transiënt → "opnieuw extraheren"
        draait de route opnieuw zonder her-upload, en het nieuwste voorstel wint overal."""
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

        def _timeout(pdf_bytes: bytes, *, client=None) -> AiFactuurExtractie:
            raise RuntimeError("Claude API-timeout na 120s")

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _timeout)
        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)
        assert "timeout" in (_extractie_detail(administratie_id, resultaat.document_id) or {}).get(
            "ai_extractie_fout", ""
        )

        aanroepen: list[bytes] = []

        def _werkt(pdf_bytes: bytes, *, client=None) -> AiFactuurExtractie:
            aanroepen.append(pdf_bytes)
            return _fake_extractie()

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _werkt)
        status = service.herextraheer_document(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )

        assert status == DocumentStatus.TE_CONTROLEREN
        assert aanroepen == [_PDF]
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        # Nieuwste extractie wint: het voorstel is nu aanwezig, en de tijdlijn toont beide pogingen.
        assert detail.veldvoorstel is not None and detail.veldvoorstel["bron"] == "ai"
        extractie_rondes = [g for g in detail.gebeurtenissen if g.naar_status == DocumentStatus.EXTRACTIE_BEZIG]
        assert len(extractie_rondes) == 2
        data = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=resultaat.document_id
        )
        assert data.referentie == "F-2026-042"

    def test_opnieuw_extraheren_alleen_voor_pdf_vanaf_te_controleren(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: list[bytes],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from tests.documenten.test_ubl import _VOORBEELD_UBL

        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

        # UBL: deterministisch — opnieuw extraheren is zinloos en wordt geweigerd.
        ubl = service.upload_document(
            administratie_id=administratie_id,
            bestandsnaam="factuur.xml",
            inhoud=_VOORBEELD_UBL,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )
        with pytest.raises(service.HerextractieNietToegestaan, match="PDF"):
            service.herextraheer_document(
                administratie_id=administratie_id,
                document_id=ubl.document_id,
                actor_id=gescoopte_gebruiker,
                opslag=opslag,
            )

        # Verkeerde status: na verwijderen staat het document niet meer op te_controleren.
        pdf = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)
        service.verwijder_document(
            administratie_id=administratie_id, document_id=pdf.document_id, actor_id=gescoopte_gebruiker
        )
        with pytest.raises(service.HerextractieNietToegestaan, match="te_controleren"):
            service.herextraheer_document(
                administratie_id=administratie_id,
                document_id=pdf.document_id,
                actor_id=gescoopte_gebruiker,
                opslag=opslag,
            )

    def test_metriek_in_tijdlijn(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from app.extractie.service import ExtractieMetriek

        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

        def _met_metriek(pdf_bytes: bytes, *, client=None) -> AiFactuurExtractie:
            basis = _fake_extractie()
            return AiFactuurExtractie(
                kop=basis.kop,
                regels=basis.regels,
                bsn_verwijderd=0,
                volledig=True,
                metriek=ExtractieMetriek(aanroepen=1, input_tokens=1234, output_tokens=567, chunked=False),
            )

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _met_metriek)
        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)
        detail = _extractie_detail(administratie_id, resultaat.document_id)
        assert detail is not None
        assert detail["ai_metriek"] == {
            "aanroepen": 1,
            "input_tokens": 1234,
            "output_tokens": 567,
            "chunked": False,
            "regels": 2,
        }


class TestWaarborgProjectadministratie:
    def test_onvolledige_regelset_blokkeert_bij_projectplicht(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De harde waarborg: projectplicht + niet-aantoonbaar-complete regelset → blokkerende
        status handmatig_afmaken, NOOIT een totalen-only voorstel dat projecttoerekening laat
        wegvallen."""
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        beheer_service.zet_project_verplicht(
            actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True
        )
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None: _fake_extractie(volledig=False),
        )

        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)

        assert resultaat.status == DocumentStatus.HANDMATIG_AFMAKEN
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        # Bewust géén voorstel — ook niet gedeeltelijk.
        assert detail.veldvoorstel is None
        blokkade = _extractie_detail(administratie_id, resultaat.document_id)
        assert blokkade is not None
        assert "niet aantoonbaar compleet" in blokkade["ai_extractie_onvolledig"]
        assert blokkade["ai_metriek"]["regels"] == 2
        data = boekvoorstel.haal_boekvoorstel_op(
            administratie_id=administratie_id, document_id=resultaat.document_id
        )
        assert data.regels == [] and data.vendor_id is None and data.totaalbedrag is None

    def test_onvolledig_zonder_projectplicht_geeft_voorstel_met_signaal(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None: _fake_extractie(volledig=False),
        )

        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)

        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert detail.veldvoorstel is not None
        assert detail.veldvoorstel["controle"]["onvolledig"] is True

    def test_opnieuw_extraheren_vanaf_handmatig_afmaken(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        beheer_service.zet_project_verplicht(
            actor_id=beheerder_id, administratie_id=administratie_id, verplicht=True
        )
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None: _fake_extractie(volledig=False),
        )
        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)
        assert resultaat.status == DocumentStatus.HANDMATIG_AFMAKEN

        # Tweede poging krijgt de regelset wél compleet → normaal voorstel, te_controleren.
        monkeypatch.setattr(
            "app.extractie.service.extraheer_inkoopfactuur",
            lambda pdf_bytes, *, client=None: _fake_extractie(volledig=True),
        )
        status = service.herextraheer_document(
            administratie_id=administratie_id,
            document_id=resultaat.document_id,
            actor_id=gescoopte_gebruiker,
            opslag=opslag,
        )

        assert status == DocumentStatus.TE_CONTROLEREN
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=resultaat.document_id)
        assert detail.veldvoorstel is not None
        assert detail.veldvoorstel["controle"]["onvolledig"] is False

    def test_ai_fout_is_zichtbaar_en_laat_upload_slagen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")

        def _kapot(pdf_bytes: bytes, *, client=None) -> AiFactuurExtractie:
            raise RuntimeError("Claude API-fout: 529 overloaded")

        monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _kapot)
        resultaat = _upload_pdf(administratie_id, gescoopte_gebruiker, opslag)

        # De upload faalt niet en het document verdwijnt niet stil: fout herkenbaar in de tijdlijn,
        # controleur kan handmatig verder.
        assert resultaat.status == DocumentStatus.TE_CONTROLEREN
        detail = _extractie_detail(administratie_id, resultaat.document_id)
        assert detail is not None
        assert "529 overloaded" in detail["ai_extractie_fout"]
