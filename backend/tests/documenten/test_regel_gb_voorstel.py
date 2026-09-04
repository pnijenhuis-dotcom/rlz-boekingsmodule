"""Regel-niveau GB-voorstel in de boekvoorstel-prefill (blok D medewerker-wensen 04-09): volgorde
regel-geheugen > AI-classificatie > leeg, AI alleen achter de gate én bij ≥ 2 historische grootboeken,
persistentie (herladen = geen tweede call), de opgeslagen keuze van de mens wint, en het autoboek-slot
wordt nooit groen op een AI-voorstel."""

from __future__ import annotations

import uuid
from datetime import UTC, date, datetime

import pytest
from sqlalchemy import Engine, text

from app.beheer import service as beheer_service
from app.config import settings
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.documenten import autoboeken, boekvoorstel, service
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.client import ClaudeAntwoord
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.geheugen import regel_gb
from app.geheugen.models import BoekingObservatie, RegelGbClassificatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.sync.models import VendorCache

VENDOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333331")
GB_4110 = uuid.UUID("44444444-0000-0000-0000-000000004110")
GB_4112 = uuid.UUID("44444444-0000-0000-0000-000000004112")
BTW_ID = uuid.UUID("55555555-5555-5555-5555-555555555551")

OMSCHRIJVING_BEKEND = "Microsoft 365 Business Premium (YR-MTH)"
OMSCHRIJVING_NIEUW = "Copilot Business Premium (YR-MTH)"


def _veld(waarde: str | None, zekerheid: float = 0.95) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _fake_extractie() -> AiFactuurExtractie:
    """Derks-casus: twee regels van dezelfde leverancier, één bekend in het regel-geheugen, één nieuw."""
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("Derks Automatisering B.V."),
            "factuurnummer": _veld("D-2026-0901"),
            "factuurdatum": _veld("2026-09-01"),
            "vervaldatum": _veld("2026-09-30", zekerheid=0.5),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld("111.91"),
            "totaal_incl": _veld("135.41"),
            "btw_bedrag": _veld("23.50"),
        },
        regels=[
            AiRegel(
                omschrijving=OMSCHRIJVING_BEKEND,
                netto_bedrag="82.40",
                btw_bedrag="17.30",
                hoeveelheid="1",
                zekerheid=0.95,
            ),
            AiRegel(
                omschrijving=OMSCHRIJVING_NIEUW, netto_bedrag="29.51", btw_bedrag="6.20", hoeveelheid="1", zekerheid=0.9
            ),
        ],
        bsn_verwijderd=0,
        volledig=True,
    )


class FakeClaudeClient:
    """Test-seam voor de classificatie-call: registreert elke aanroep en kiest deterministisch."""

    aanroepen: list[dict] = []
    keuze_k = 2  # kandidaat-index die de "AI" per regel kiest

    def __init__(self, **kwargs) -> None:
        self._model = "fake-model"

    def vraag_json(self, *, system: str, opdracht: str, json_schema: dict) -> ClaudeAntwoord:
        FakeClaudeClient.aanroepen.append({"system": system, "opdracht": opdracht, "schema": json_schema})
        # Regelnummers uit de opdracht: elke regel krijgt dezelfde kandidaat-index.
        keuzes = []
        in_regels = False
        for regel in opdracht.splitlines():
            if regel.startswith("Factuurregels:"):
                in_regels = True
                continue
            if in_regels and regel[:1].isdigit():
                keuzes.append({"i": int(regel.split(".", 1)[0]), "k": FakeClaudeClient.keuze_k})
        return ClaudeAntwoord(data={"keuzes": keuzes}, afgekapt=False, input_tokens=10, output_tokens=5)


@pytest.fixture(autouse=True)
def _reset_fake_client() -> None:
    FakeClaudeClient.aanroepen = []
    FakeClaudeClient.keuze_k = 2


@pytest.fixture
def ai_gate_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")


@pytest.fixture
def fake_extraheer(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None) -> AiFactuurExtractie:
        return _fake_extractie()

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)


@pytest.fixture
def fake_claude(monkeypatch: pytest.MonkeyPatch) -> type[FakeClaudeClient]:
    """De classificatie construeert zijn client via `_client_voor` (gate + key) — de klasse zelf is de seam,
    zodat de gate-toets écht loopt."""
    monkeypatch.setattr("app.extractie.client.ClaudeExtractieClient", FakeClaudeClient)
    return FakeClaudeClient


@pytest.fixture
def vendor_derks(administratie_id: uuid.UUID) -> uuid.UUID:
    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(id=VENDOR_ID, administratie_id=administratie_id, naam="Derks Automatisering B.V.", brondata={})
        )
        for ledger_id, code, naam in ((GB_4110, "4110", "Automatisering"), (GB_4112, "4112", "Software-abonnementen")):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=administratie_id,
                    code=code,
                    naam=naam,
                    soort=2,
                    is_totaalrekening=False,
                )
            )
    return VENDOR_ID


def _observatie(
    administratie_id: uuid.UUID, *, gb: uuid.UUID, bron: str, omschrijving: str | None
) -> BoekingObservatie:
    return BoekingObservatie(
        id=uuid.uuid4(),
        administratie_id=administratie_id,
        vendor_id=VENDOR_ID,
        regel_sleutel=normaliseer_regel_sleutel(omschrijving),
        regel_omschrijving_raw=omschrijving,
        gb_id=gb,
        btw_id=BTW_ID,
        project_id=None,
        bron=bron,
        bron_datum=datetime.now(UTC).date(),
    )


@pytest.fixture
def geheugen_twee_gbs(administratie_id: uuid.UUID, vendor_derks: uuid.UUID) -> None:
    """Bekende regel = app-bevestigd op 4110; 4112 komt alleen uit de RLZ-historie op een ándere regel."""
    with scoped_session(administratie_id) as session:
        session.add(_observatie(administratie_id, gb=GB_4110, bron="app", omschrijving=OMSCHRIJVING_BEKEND))
        session.add(_observatie(administratie_id, gb=GB_4110, bron="app", omschrijving=OMSCHRIJVING_BEKEND))
        session.add(_observatie(administratie_id, gb=GB_4112, bron="rlz_seed", omschrijving="Exchange Online Plan 2"))


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="derks.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def _classificaties(admin_engine: Engine, document_id: uuid.UUID) -> list[tuple[int, uuid.UUID | None]]:
    with admin_engine.connect() as conn:
        return [
            (r[0], r[1])
            for r in conn.execute(
                text(
                    "SELECT regel_volgnummer, ledger_id FROM boekhouding.regel_gb_classificatie "
                    "WHERE document_id = :d ORDER BY regel_volgnummer"
                ),
                {"d": document_id},
            ).all()
        ]


class TestPrefillVolgorde:
    def test_geheugen_groen_dan_ai_oranje_dan_leeg(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
        geheugen_twee_gbs: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)

        # De post-extractie-hook deed precies één classificatie-call, alleen voor de open regel.
        assert len(fake_claude.aanroepen) == 1
        opdracht = fake_claude.aanroepen[0]["opdracht"]
        assert OMSCHRIJVING_NIEUW in opdracht and OMSCHRIJVING_BEKEND not in opdracht
        assert "4110 Automatisering" in opdracht and "4112 Software-abonnementen" in opdracht
        assert fake_claude.aanroepen[0]["schema"] is regel_gb.CLASSIFICATIE_SCHEMA
        assert _classificaties(admin_engine, document_id) == [(2, GB_4112)]

        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.opgeslagen is False and data.vendor_id == VENDOR_ID
        bekend, nieuw = data.regels
        assert bekend.ledger_id == GB_4110 and bekend.gb_bron == "geheugen"
        assert bekend.gb_voorstel_detail == f"2× bevestigd, laatst {date.today():%d-%m-%Y}"
        assert nieuw.ledger_id == GB_4112 and nieuw.gb_bron == "ai"
        assert nieuw.gb_voorstel_detail == "AI koos uit 2 grootboeken van deze leverancier — bevestig of corrigeer"
        # De samengevoegde regel krijgt nooit een regel-GB (synthetische omschrijving).
        assert data.samengevoegde_regel is not None and data.samengevoegde_regel.ledger_id is None

    def test_herladen_doet_geen_tweede_call(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
        geheugen_twee_gbs: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert len(fake_claude.aanroepen) == 1
        for _ in range(3):
            boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        # Ook een expliciete her-run van de classificatie (bv. tweede hook-aanroep) is idempotent.
        assert regel_gb.classificeer_document(administratie_id=administratie_id, document_id=document_id) == 0
        assert len(fake_claude.aanroepen) == 1

    def test_ai_keuze_geen_blijft_leeg_en_wordt_niet_opnieuw_gevraagd(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
        geheugen_twee_gbs: None,
    ) -> None:
        fake_claude.keuze_k = 0
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _classificaties(admin_engine, document_id) == [(2, None)]
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.regels[1].ledger_id is None and data.regels[1].gb_bron is None
        assert regel_gb.classificeer_document(administratie_id=administratie_id, document_id=document_id) == 0
        assert len(fake_claude.aanroepen) == 1

    def test_ai_kiest_buiten_de_kandidatenlijst_wordt_geen(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
        geheugen_twee_gbs: None,
    ) -> None:
        fake_claude.keuze_k = 7  # bestaat niet — het model verzint nooit een grootboek
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert _classificaties(admin_engine, document_id) == [(2, None)]


class TestAiPoorten:
    def test_gate_uit_geen_call_en_geheugen_werkt_wel(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        monkeypatch: pytest.MonkeyPatch,
        fake_claude: type[FakeClaudeClient],
        geheugen_twee_gbs: None,
    ) -> None:
        """Zonder de AVG-gate loopt ook de extractie niet — dan is er geen veldvoorstel; simuleer het
        veldvoorstel via een directe her-run van de classificatie op een gate-loze administratie."""
        monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
        assert regel_gb._client_voor(administratie_id, uuid.uuid4()) is None  # gate default UIT
        assert fake_claude.aanroepen == []

    def test_zonder_api_key_geen_call(
        self,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
        fake_claude: type[FakeClaudeClient],
    ) -> None:
        beheer_service.zet_ai_extractie_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        monkeypatch.setattr(settings, "anthropic_api_key", None)
        assert regel_gb._client_voor(administratie_id, uuid.uuid4()) is None

    def test_minder_dan_twee_kandidaten_geen_call(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
        vendor_derks: uuid.UUID,
    ) -> None:
        with scoped_session(administratie_id) as session:
            session.add(_observatie(administratie_id, gb=GB_4110, bron="app", omschrijving=OMSCHRIJVING_BEKEND))
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        assert fake_claude.aanroepen == []  # één historisch grootboek: de engine kiest die al
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.regels[0].gb_bron == "geheugen"
        assert data.regels[1].ledger_id is None and data.regels[1].gb_bron is None  # leeg = mens (of engine-prefill UI)

    def test_zonder_leverancier_geen_call(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
    ) -> None:
        _upload(administratie_id, gescoopte_gebruiker, opslag)  # geen vendor in de cache → geen suggestie
        assert fake_claude.aanroepen == []


class TestMensWint:
    def test_opgeslagen_keuze_wint_van_geheugen_en_ai(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
        geheugen_twee_gbs: None,
    ) -> None:
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        eigen_gb = uuid.uuid4()
        boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=gescoopte_gebruiker,
            vendor_id=VENDOR_ID,
            referentie=data.referentie,
            factuurdatum=data.factuurdatum,
            totaalbedrag=data.totaalbedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=eigen_gb,
                    taxrate_id=BTW_ID,
                    project_id=None,
                    netto_bedrag=r.netto_bedrag,
                    btw_bedrag=r.btw_bedrag,
                    omschrijving=r.omschrijving,
                )
                for r in data.regels
            ],
            regels_samenvoegen=False,
        )
        opnieuw = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert opnieuw.opgeslagen is True
        assert all(
            r.ledger_id == eigen_gb and r.gb_bron is None and r.gb_voorstel_detail is None for r in opnieuw.regels
        )
        # Een opgeslagen voorstel wordt nooit meer geclassificeerd.
        assert regel_gb.classificeer_document(administratie_id=administratie_id, document_id=document_id) == 0
        assert len(fake_claude.aanroepen) == 1

    def test_herextractie_met_andere_omschrijving_maakt_uitkomst_ongeldig(self, administratie_id: uuid.UUID) -> None:
        rij = RegelGbClassificatie(
            administratie_id=administratie_id,
            document_id=uuid.uuid4(),
            regel_volgnummer=2,
            regel_sleutel=normaliseer_regel_sleutel(OMSCHRIJVING_NIEUW),
            ledger_id=GB_4112,
            kandidaten_n=2,
            model="fake",
        )
        assert regel_gb.geldige_classificatie({2: rij}, volgnummer=2, omschrijving=OMSCHRIJVING_NIEUW) is rij
        assert regel_gb.geldige_classificatie({2: rij}, volgnummer=2, omschrijving="Iets heel anders") is None
        assert regel_gb.geldige_classificatie({2: rij}, volgnummer=1, omschrijving=OMSCHRIJVING_NIEUW) is None


class TestAutoboekSlotNietGroenOpAi:
    def test_autoboeken_weigert_ondanks_ai_prefill(
        self,
        gescoopte_gebruiker: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        opslag: LokaleBestandsopslag,
        admin_engine: Engine,
        ai_gate_aan: None,
        fake_extraheer: None,
        fake_claude: type[FakeClaudeClient],
        geheugen_twee_gbs: None,
    ) -> None:
        """Het autoboek-pad leest uitsluitend de engine (kop-niveau-geheugen); een regel mét AI-voorstel
        telt nooit als app-bevestigd — de leverancier-stem is hier gesplitst (4110 app + 4112 seed), dus
        oranje → geweigerd, ondanks dat de prefill beide regels een grootboek geeft."""
        beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
        )
        autoboeken.zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=VENDOR_ID, actor_id=beheerder_id, ingeschakeld=True
        )
        document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
        assert data.regels[1].gb_bron == "ai"
        besluit = autoboeken.probeer_autoboeken_na_extractie(administratie_id=administratie_id, document_id=document_id)
        assert besluit is not None and besluit.geboekt is False
        assert "geheugen" in besluit.reden
        with admin_engine.connect() as conn:
            status = conn.execute(
                text("SELECT status FROM boekhouding.document WHERE id = :d"), {"d": document_id}
            ).scalar_one()
        assert status == "te_controleren"
