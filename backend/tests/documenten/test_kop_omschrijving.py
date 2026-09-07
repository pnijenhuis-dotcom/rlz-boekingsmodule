"""Kop-omschrijving automatisch (blok 9 vervolgrun 07-09, besluit Peter "auto-first"): de document-omschrijving
(RLZ `Description` op de PurchaseInvoice, Odoo `narration`) werd door niemand gezet. Sinds blok 9 deterministisch in
code afgeleid — (i) één échte boekingsregel → die regeltekst, (ii) meerdere regels → de voorgelezen betreft-regel uit
de scan, (iii) terugval "‹leverancier› ‹factuurnummer›" — met herkomst-chip; een door de mens gezette omschrijving
wint altijd (tijdlijn-notitie `kop_omschrijving`, geen kolom). De RLZ-port geeft 'm als `Description` mee in het
boek- én herboekpad; de tegenboeking draagt de bestaande tegenboek-omschrijving óók op documentniveau."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import date
from decimal import Decimal

import pytest
from sqlalchemy import Engine, text

from app.backends.rlz_inkoop import RlzInkoopPort
from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boeken, boekvoorstel, service
from app.documenten.kop_omschrijving import (
    HERKOMST_AFGELEID,
    HERKOMST_FACTUUR,
    HERKOMST_HANDMATIG,
    HERKOMST_REGEL,
    MAX_LENGTE,
    bepaal_kop_omschrijving,
    kap_af,
    normaliseer,
)
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.sync.models import VendorCache
from tests.documenten.fake_rlz_client import FakeBoekClient

VENDOR_ID = uuid.UUID("33333333-0000-0000-0000-0000000000b9")
GB_ID = uuid.UUID("44444444-0000-0000-0000-000000004500")
BTW_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")
BETREFT = "Huur steigermateriaal project 26123 week 34"


# --- puur: de afleidingsregels --------------------------------------------------------------------------------


class TestAfleiding:
    def test_een_regel_geeft_de_regeltekst(self) -> None:
        uitkomst = bepaal_kop_omschrijving(
            regel_omschrijvingen=["Steigerhuur week 34"], betreft=BETREFT, leverancier_naam="Boot", referentie="F-1"
        )
        assert uitkomst.tekst == "Steigerhuur week 34" and uitkomst.herkomst == HERKOMST_REGEL

    def test_meerdere_regels_met_betreft_geeft_betreft(self) -> None:
        uitkomst = bepaal_kop_omschrijving(
            regel_omschrijvingen=["Huur lift", "Transport"], betreft=f"  {BETREFT}  ", leverancier_naam="Boot", referentie="F-1"
        )
        assert uitkomst.tekst == BETREFT and uitkomst.herkomst == HERKOMST_FACTUUR

    def test_zonder_betreft_terugval_leverancier_en_nummer(self) -> None:
        uitkomst = bepaal_kop_omschrijving(
            regel_omschrijvingen=["Huur lift", "Transport"], betreft=None, leverancier_naam="Boot B.V.", referentie="2026-0841"
        )
        assert uitkomst.tekst == "Boot B.V. 2026-0841" and uitkomst.herkomst == HERKOMST_AFGELEID

    def test_sentinel_lege_string_en_witruimte_zijn_onbekend(self) -> None:
        # De AI-sentinel "" (bugfix 31-08) en een witruimte-veld betekenen "geen betreft" → terugval.
        for betreft in ("", "   ", None):
            uitkomst = bepaal_kop_omschrijving(
                regel_omschrijvingen=["a", "b"], betreft=betreft, leverancier_naam="Boot", referentie="F-1"
            )
            assert uitkomst.tekst == "Boot F-1" and uitkomst.herkomst == HERKOMST_AFGELEID
        assert normaliseer("") is None and normaliseer("  \n ") is None and normaliseer(None) is None

    def test_een_regel_zonder_tekst_telt_niet_als_regeltekst(self) -> None:
        uitkomst = bepaal_kop_omschrijving(regel_omschrijvingen=[None], betreft=None, leverancier_naam="Boot", referentie=None)
        assert uitkomst.tekst == "Boot" and uitkomst.herkomst == HERKOMST_AFGELEID

    def test_niets_bruikbaar_is_none(self) -> None:
        uitkomst = bepaal_kop_omschrijving(regel_omschrijvingen=[], betreft="", leverancier_naam=None, referentie="")
        assert uitkomst.tekst is None and uitkomst.herkomst is None

    def test_witruimte_wordt_samengevouwen(self) -> None:
        uitkomst = bepaal_kop_omschrijving(
            regel_omschrijvingen=["Steigerhuur \n  week   34 "], betreft=None, leverancier_naam=None, referentie=None
        )
        assert uitkomst.tekst == "Steigerhuur week 34"

    def test_afkap_op_veilige_rlz_lengte(self) -> None:
        lang = "x" * 300
        assert MAX_LENGTE == 255
        assert len(kap_af(lang)) == 255 and kap_af(lang).endswith("…")
        assert kap_af("kort") == "kort"
        uitkomst = bepaal_kop_omschrijving(regel_omschrijvingen=[lang], betreft=None, leverancier_naam=None, referentie=None)
        assert uitkomst.tekst is not None and len(uitkomst.tekst) == 255


# --- via het boekvoorstel (DB): leesroute, prefill, mens wint ---------------------------------------------------


def _regel(omschrijving: str | None, netto: str = "100.00", btw: str = "21.00") -> boekvoorstel.BoekvoorstelRegelData:
    return boekvoorstel.BoekvoorstelRegelData(
        ledger_id=GB_ID,
        taxrate_id=BTW_ID,
        project_id=None,
        netto_bedrag=Decimal(netto),
        btw_bedrag=Decimal(btw),
        omschrijving=omschrijving,
    )


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=f"factuur-{uuid.uuid4()}.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _sla_op(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    regels: list[boekvoorstel.BoekvoorstelRegelData],
    *,
    referentie: str = "2026-0841",
    omschrijving: str | None = None,
    vendor_id: uuid.UUID | None = VENDOR_ID,
) -> boekvoorstel.BoekvoorstelData:
    totaal = sum((r.netto_bedrag or 0) + (r.btw_bedrag or 0) for r in regels)
    return boekvoorstel.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=actor_id,
        vendor_id=vendor_id,
        referentie=referentie,
        factuurdatum=date(2026, 9, 1),
        totaalbedrag=Decimal(totaal),
        regels=regels,
        regels_samenvoegen=False,
        omschrijving=omschrijving,
    )


def _audit(admin_engine: Engine, document_id: uuid.UUID, actie: str) -> list[dict]:
    with admin_engine.connect() as conn:
        rijen = conn.execute(
            text(
                "SELECT oude_waarde, nieuwe_waarde FROM platform.audit_event "
                "WHERE record_id = :id AND actie = :actie ORDER BY tijdstip"
            ),
            {"id": document_id, "actie": actie},
        ).all()
    return [{"oude_waarde": r[0], "nieuwe_waarde": r[1]} for r in rijen]


@pytest.fixture
def vendor_boot(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        session.add(VendorCache(id=VENDOR_ID, administratie_id=administratie_id, naam="Boot Steigers B.V.", brondata={}))


def _extractie(*, regels: list[AiRegel], betreft: str | None) -> AiFactuurExtractie:
    def veld(waarde: str | None, zekerheid: float = 0.93) -> AiVeld:
        return AiVeld(waarde=waarde, zekerheid=zekerheid)

    return AiFactuurExtractie(
        kop={
            "leverancier_naam": veld("Boot Steigers B.V."),
            "factuurnummer": veld("2026-0841"),
            "factuurdatum": veld("2026-09-01"),
            "valuta": veld("EUR"),
            "totaal_excl": veld(str(sum(Decimal(r.netto_bedrag or "0") for r in regels))),
            "totaal_incl": veld(str(sum(Decimal(r.netto_bedrag or "0") + Decimal(r.btw_bedrag or "0") for r in regels))),
            "btw_bedrag": veld(str(sum(Decimal(r.btw_bedrag or "0") for r in regels))),
            "betreft": veld(betreft, zekerheid=0.9 if betreft else 0.0),
        },
        regels=regels,
        bsn_verwijderd=0,
        volledig=True,
    )


@pytest.fixture
def ai_gate_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    monkeypatch.setattr("app.geheugen.regel_gb._client_voor", lambda *a, **k: None)


def _fake_extractie(monkeypatch: pytest.MonkeyPatch, extractie: AiFactuurExtractie) -> None:
    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None) -> AiFactuurExtractie:
        return extractie

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)


class TestBoekvoorstelLeesroute:
    def test_een_opgeslagen_regel_geeft_de_regeltekst_met_chip_regel(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, vendor_boot: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Steigerhuur week 34")])
        assert data.omschrijving == "Steigerhuur week 34" and data.omschrijving_herkomst == HERKOMST_REGEL
        # De leesroute (GET) geeft exact dezelfde stand — checks, doorbelasten-blok en boekmotor lezen hierdoor.
        gelezen = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert gelezen.omschrijving == "Steigerhuur week 34" and gelezen.omschrijving_herkomst == HERKOMST_REGEL

    def test_meerdere_regels_zonder_betreft_terugval_leverancier_nummer(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, vendor_boot: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _sla_op(
            administratie_id, document_id, gescoopte_gebruiker, [_regel("Huur lift"), _regel("Transport", "50.00", "10.50")]
        )
        assert data.omschrijving == "Boot Steigers B.V. 2026-0841" and data.omschrijving_herkomst == HERKOMST_AFGELEID

    def test_zonder_crediteur_terugval_alleen_nummer(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _sla_op(
            administratie_id, document_id, gescoopte_gebruiker, [_regel("a"), _regel("b")], vendor_id=None, referentie="F-9"
        )
        assert data.omschrijving == "F-9" and data.omschrijving_herkomst == HERKOMST_AFGELEID

    def test_meerdere_regels_met_betreft_uit_de_scan_geeft_chip_factuur(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_boot: None,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _fake_extractie(
            monkeypatch,
            _extractie(
                regels=[
                    AiRegel(omschrijving="Huur lift", netto_bedrag="100.00", btw_bedrag="21.00", hoeveelheid="1", zekerheid=0.9),
                    AiRegel(omschrijving="Transport", netto_bedrag="50.00", btw_bedrag="10.50", hoeveelheid="1", zekerheid=0.9),
                ],
                betreft=BETREFT,
            ),
        )
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        # Het veldvoorstel (controle.bouw_veldvoorstel) draagt de voorgelezen betreft-regel …
        with scoped_session(administratie_id) as session:
            veldvoorstel = boekvoorstel._laatste_veldvoorstel(session, document_id)
        assert veldvoorstel is not None and veldvoorstel["betreft"] == BETREFT
        # … en de PREFILL (niet-opgeslagen, gesplitst: twee regels) gebruikt 'm als kop-omschrijving.
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert prefill.opgeslagen is False
        if prefill.regels_samenvoegen and prefill.samengevoegde_regel is not None:
            # RLZ-default = samengevoegd: de ene synthetische regel is géén regeltekst → betreft.
            assert prefill.omschrijving == BETREFT and prefill.omschrijving_herkomst == HERKOMST_FACTUUR
        data = _sla_op(
            administratie_id, document_id, gescoopte_gebruiker, [_regel("Huur lift"), _regel("Transport", "50.00", "10.50")]
        )
        assert data.omschrijving == BETREFT and data.omschrijving_herkomst == HERKOMST_FACTUUR

    def test_prefill_een_gelezen_regel_samengevoegd_geeft_toch_de_regeltekst(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_boot: None,
        ai_gate_aan: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """De synthetische samengevoegde regel ("Factuur X — samengevoegd (1 regels)") is geen factuurtekst: bij
        precies één gelezen factuurregel is díé tekst de kop-omschrijving."""
        _fake_extractie(
            monkeypatch,
            _extractie(
                regels=[AiRegel(omschrijving="Steigerhuur week 34", netto_bedrag="100.00", btw_bedrag="21.00", hoeveelheid="1", zekerheid=0.9)],
                betreft=None,
            ),
        )
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        prefill = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert prefill.opgeslagen is False
        assert prefill.omschrijving == "Steigerhuur week 34" and prefill.omschrijving_herkomst == HERKOMST_REGEL
        assert "samengevoegd" not in (prefill.omschrijving or "")


class TestMensWint:
    def test_eigen_tekst_wordt_override_met_audit_en_overleeft_herprefill(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_boot: None,
        admin_engine: Engine,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Steigerhuur week 34")])

        data = _sla_op(
            administratie_id, document_id, gescoopte_gebruiker, [_regel("Steigerhuur week 34")], omschrijving="  Eigen  tekst "
        )
        assert data.omschrijving == "Eigen tekst" and data.omschrijving_herkomst == HERKOMST_HANDMATIG
        audit = _audit(admin_engine, document_id, "boekvoorstel_omschrijving_gewijzigd")
        assert len(audit) == 1
        assert audit[0]["oude_waarde"] == {"omschrijving": "Steigerhuur week 34", "handmatig": False}
        assert audit[0]["nieuwe_waarde"] == {"omschrijving": "Eigen tekst", "handmatig": True}

        # Heropenen (GET) én een latere opslag ZONDER omschrijving-veld (oude client, autoboeken) raken 'm niet;
        # ook niet als de regeltekst verandert (de afleiding zou anders worden — de mens wint).
        gelezen = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert gelezen.omschrijving == "Eigen tekst" and gelezen.omschrijving_herkomst == HERKOMST_HANDMATIG
        data = _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Heel andere regel")])
        assert data.omschrijving == "Eigen tekst" and data.omschrijving_herkomst == HERKOMST_HANDMATIG
        # De prefill-autosave bij openen raakt een door een mens opgeslagen voorstel nooit.
        assert (
            boekvoorstel.persisteer_prefill_bij_openen(
                administratie_id=administratie_id, document_id=document_id, geopend_door=gescoopte_gebruiker
            )
            is False
        )
        # Dezelfde waarde nog eens opslaan = geen tweede notitie/audit (geen handeling op de omschrijving).
        _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Heel andere regel")], omschrijving="Eigen tekst")
        assert len(_audit(admin_engine, document_id, "boekvoorstel_omschrijving_gewijzigd")) == 1

    def test_gelijk_aan_de_afleiding_is_geen_override(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, vendor_boot: None, admin_engine: Engine
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _sla_op(
            administratie_id, document_id, gescoopte_gebruiker, [_regel("Steigerhuur week 34")], omschrijving="Steigerhuur week 34"
        )
        assert data.omschrijving_herkomst == HERKOMST_REGEL  # chip blijft: het is nog de automatische waarde
        assert _audit(admin_engine, document_id, "boekvoorstel_omschrijving_gewijzigd") == []
        # … en beweegt dus mee met een nieuwe regeltekst.
        data = _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Transport")], omschrijving="Steigerhuur week 34")
        # De mens liet de oude waarde staan terwijl de afleiding nu "Transport" is → dat ís een bewuste afwijking.
        assert data.omschrijving == "Steigerhuur week 34" and data.omschrijving_herkomst == HERKOMST_HANDMATIG

    def test_leegmaken_zet_terug_naar_automatisch(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, vendor_boot: None, admin_engine: Engine
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Steigerhuur week 34")], omschrijving="Eigen tekst")
        data = _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Steigerhuur week 34")], omschrijving="")
        assert data.omschrijving == "Steigerhuur week 34" and data.omschrijving_herkomst == HERKOMST_REGEL
        audit = _audit(admin_engine, document_id, "boekvoorstel_omschrijving_gewijzigd")
        assert len(audit) == 2 and audit[-1]["nieuwe_waarde"] == {"omschrijving": "Steigerhuur week 34", "handmatig": False}

    def test_override_wordt_afgekapt(
        self, gescoopte_gebruiker: uuid.UUID, administratie_id: uuid.UUID, opslag: LokaleBestandsopslag, vendor_boot: None
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("r")], omschrijving="y" * 400)
        assert data.omschrijving is not None and len(data.omschrijving) == MAX_LENGTE and data.omschrijving.endswith("…")


# --- RLZ-port: Description in de PUT (boeken, herboeken, tegenboeken) --------------------------------------------


def _voorstel(document_id: uuid.UUID, *, boek_cyclus: int = 0, omschrijving: str | None) -> boekvoorstel.BoekvoorstelData:
    return boekvoorstel.BoekvoorstelData(
        document_id=document_id,
        vendor_id=VENDOR_ID,
        referentie="2026-0841",
        factuurdatum=date(2026, 9, 1),
        totaalbedrag=Decimal("121.00"),
        rlz_boekstuknummer=None,
        opgeslagen=True,
        regels=[_regel("Steigerhuur week 34")],
        boek_cyclus=boek_cyclus,
        omschrijving=omschrijving,
        omschrijving_herkomst=HERKOMST_REGEL if omschrijving else None,
    )


class TestRlzPortDescription:
    @pytest.mark.parametrize("boek_cyclus", [0, 1], ids=["boeken", "herboeken (cyclus 1)"])
    def test_put_draagt_description_in_boek_en_herboekpad(self, boek_cyclus: int) -> None:
        fake = FakeBoekClient()
        document_id = uuid.uuid4()
        with RlzInkoopPort(fake) as port:
            port.boek_inkoopfactuur(
                document_id=document_id,
                voorstel=_voorstel(document_id, boek_cyclus=boek_cyclus, omschrijving="Steigerhuur week 34"),
                bestand=b"%PDF",
                bestandsnaam="f.pdf",
            )
        (put,) = fake.puts
        assert put["id"] == rlz_herboeking_id(document_id, boek_cyclus)
        assert put["Description"] == "Steigerhuur week 34"
        # STAP-0 07-09 (herstelrun blok 4a): RLZ negeert de document-Description op PurchaseInvoices en leidt 'm
        # af uit regel 1; `Header` wordt wél bewaard — de kop gaat dus óók als Header mee.
        assert put["Header"] == "Steigerhuur week 34"
        assert put["reference"] == "2026-0841"  # Reference blijft het factuurnummer
        assert put["lines"][0]["Description"] == "Steigerhuur week 34"  # regel-Description ongewijzigd

    def test_zonder_omschrijving_geen_description_veld(self) -> None:
        fake = FakeBoekClient()
        document_id = uuid.uuid4()
        with RlzInkoopPort(fake) as port:
            port.boek_inkoopfactuur(
                document_id=document_id, voorstel=_voorstel(document_id, omschrijving=None), bestand=b"%PDF", bestandsnaam="f.pdf"
            )
        assert "Description" not in fake.puts[0]
        assert "Header" not in fake.puts[0]

    def test_koptekst_afgekapt_op_rlz_200_tekens(self) -> None:
        """RLZ kapt tekstvelden op 200 af (STAP-0 07-09: 250 → 200 in de readback) — zelf netjes afkappen."""
        from app.backends.rlz_inkoop import RLZ_KOPTEKST_MAX, koptekst_velden

        lang = "Steigerhuur " * 30  # 360 tekens
        velden = koptekst_velden(lang)
        assert velden["Header"] == velden["Description"]
        assert len(velden["Header"]) <= RLZ_KOPTEKST_MAX == 200
        assert velden["Header"].endswith("…")
        assert koptekst_velden("kort") == {"Header": "kort", "Description": "kort"}
        assert koptekst_velden(None) == {} and koptekst_velden("") == {}

    def test_tegenboeking_draagt_de_tegenboek_omschrijving_ook_op_documentniveau(self) -> None:
        fake = FakeBoekClient()
        document_id = uuid.uuid4()
        with RlzInkoopPort(fake) as port:
            port.boek_tegenboeking(
                document_id=document_id,
                voorstel=_voorstel(document_id, omschrijving="Steigerhuur week 34"),
                referentie="2026-0841-TB",
                omschrijving="TEGENBOEKING 2026-0841 · Boot Steigers B.V.",
                reden="verkeerde administratie",
                bestand=b"%PDF",
                bestandsnaam="f.pdf",
            )
        (put,) = fake.puts
        assert put["id"] == rlz_tegenboeking_id(document_id, 0)
        assert put["Description"] == "TEGENBOEKING 2026-0841 · Boot Steigers B.V."
        assert put["Header"] == "TEGENBOEKING 2026-0841 · Boot Steigers B.V."
        assert put["lines"][0]["Description"] == "TEGENBOEKING 2026-0841 · Boot Steigers B.V."


class TestBoekpadEndToEnd:
    def test_boek_document_stuurt_de_afgeleide_omschrijving_mee(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        vendor_boot: None,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        beheer_service.zet_boeken_ingeschakeld(actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True)
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        _sla_op(administratie_id, document_id, gescoopte_gebruiker, [_regel("Steigerhuur week 34")])
        fake = FakeBoekClient()
        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: fake)

        resultaat = boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=gescoopte_gebruiker)

        assert resultaat.rlz_boekstuknummer == "RLZ-TEST-00001"
        (put,) = fake.puts
        assert put["Description"] == "Steigerhuur week 34"
        assert put["reference"] == "2026-0841"


def test_dataclass_defaults_blijven_byte_identiek_voor_bestaande_aanroepers() -> None:
    """Additief: bestaande constructies zonder de nieuwe velden krijgen None/None (geen Description, geen narration)."""
    data = replace(_voorstel(uuid.uuid4(), omschrijving="x"), omschrijving=None, omschrijving_herkomst=None)
    assert data.omschrijving is None and data.omschrijving_herkomst is None
