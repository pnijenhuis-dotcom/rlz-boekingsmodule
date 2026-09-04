"""Btw-default in de boekvoorstel-prefill (blok E medewerker-wensen 04-09): invulvolgorde factuur >
leverancier-geheugen > administratie-default > leeg, chip-bron `btw_bron='standaard'`, default UIT = niets,
samengevoegde regel volgt dezelfde regel, opgeslagen voorstel wordt nooit geraakt."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest

from app.beheer import btw_default
from app.beheer import service as beheer_service
from app.config import settings
from app.db.session import scoped_session
from app.documenten import boekvoorstel, service
from app.documenten.storage import LokaleBestandsopslag
from app.extractie.service import AiFactuurExtractie, AiRegel, AiVeld
from app.geheugen.models import BoekingObservatie
from app.sync.models import VendorCache

VENDOR_ID = uuid.UUID("33333333-3333-3333-3333-333333333332")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")
VERLEGD_ID = uuid.UUID("55555555-0000-0000-0000-000000000009")
GEHEUGEN_BTW_ID = uuid.UUID("55555555-0000-0000-0000-000000000077")
GB_ID = uuid.UUID("44444444-0000-0000-0000-000000004000")


def _veld(waarde: str | None, zekerheid: float = 0.95) -> AiVeld:
    return AiVeld(waarde=waarde, zekerheid=zekerheid)


def _fake_extractie() -> AiFactuurExtractie:
    """Steigerbouw-casus: één regel mét 21 % (factuur leidt de code af), één regel zonder btw (0 % is
    ambigu — de scan laat 'm bewust leeg)."""
    return AiFactuurExtractie(
        kop={
            "leverancier_naam": _veld("Steigerverhuur Zuid B.V."),
            "factuurnummer": _veld("SZ-2026-77"),
            "factuurdatum": _veld("2026-09-01"),
            "vervaldatum": _veld("2026-10-01", zekerheid=0.5),
            "valuta": _veld("EUR"),
            "totaal_excl": _veld("1100.00"),
            "totaal_incl": _veld("1121.00"),
            "btw_bedrag": _veld("21.00"),
        },
        regels=[
            AiRegel(
                omschrijving="Diesel heftruck",
                netto_bedrag="100.00",
                btw_bedrag="21.00",
                hoeveelheid="1",
                zekerheid=0.95,
            ),
            AiRegel(
                omschrijving="AR-40 staander 2,0m m.p. (huur)",
                netto_bedrag="1000.00",
                btw_bedrag="0.00",
                hoeveelheid="40",
                zekerheid=0.9,
            ),
        ],
        bsn_verwijderd=0,
        volledig=True,
    )


@pytest.fixture
def ai_gate_aan(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
    beheer_service.zet_ai_extractie_ingeschakeld(
        actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=True
    )
    monkeypatch.setattr(settings, "anthropic_api_key", "test-key")
    # Geen echte AI-classificatie-client in deze suite (er zijn hier sowieso < 2 kandidaten).
    monkeypatch.setattr("app.geheugen.regel_gb._client_voor", lambda *a, **k: None)


@pytest.fixture
def fake_extraheer(monkeypatch: pytest.MonkeyPatch) -> None:
    def _fake(pdf_bytes: bytes, *, client=None, verbruik_referentie=None, mail_context=None) -> AiFactuurExtractie:
        return _fake_extractie()

    monkeypatch.setattr("app.extractie.service.extraheer_inkoopfactuur", _fake)


@pytest.fixture
def stamgegevens(administratie_id: uuid.UUID) -> None:
    from app.sync.models import TaxRateCache

    with scoped_session(administratie_id) as session:
        session.add(
            VendorCache(id=VENDOR_ID, administratie_id=administratie_id, naam="Steigerverhuur Zuid B.V.", brondata={})
        )
        session.add(
            TaxRateCache(
                id=HOOG_ID,
                administratie_id=administratie_id,
                naam="NL, Hoog Tarief",
                percentage=Decimal("0.2100"),
                brondata={},
            )
        )
        session.add(
            TaxRateCache(
                id=VERLEGD_ID,
                administratie_id=administratie_id,
                naam="NL, BTW verlegd (hoog)",
                percentage=Decimal("0"),
                brondata={},
            )
        )
        session.add(
            TaxRateCache(
                id=GEHEUGEN_BTW_ID,
                administratie_id=administratie_id,
                naam="NL, Vrijgesteld",
                percentage=Decimal("0"),
                brondata={},
            )
        )


@pytest.fixture
def default_verlegd(administratie_id: uuid.UUID, beheerder_id: uuid.UUID, stamgegevens: None) -> None:
    btw_default.zet_btw_default(actor_id=beheerder_id, administratie_id=administratie_id, taxrate_id=VERLEGD_ID)


def _upload(administratie_id: uuid.UUID, actor_id: uuid.UUID, opslag: LokaleBestandsopslag) -> uuid.UUID:
    return service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="steigers.pdf",
        inhoud=f"%PDF-1.4 {uuid.uuid4()}".encode(),
        actor_id=actor_id,
        opslag=opslag,
    ).document_id


def test_factuur_wint_default_vult_alleen_wat_leeg_bleef(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    ai_gate_aan: None,
    fake_extraheer: None,
    default_verlegd: None,
) -> None:
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    diesel, huur = data.regels
    assert diesel.taxrate_id == HOOG_ID and diesel.btw_bron == "factuur"
    # De scan liet 0 % bewust leeg (ambigu) — zonder leverancier-geheugen vult de administratie-default 'm,
    # mét chip; de harde checks blijven de poort (beslispunt Peter, BESLISSINGEN blok E).
    assert huur.taxrate_id == VERLEGD_ID and huur.btw_bron == "standaard"
    # Samengevoegde regel: btw-codes verschillen per regel → geen factuur-code → default.
    assert data.samengevoegde_regel is not None
    assert data.samengevoegde_regel.taxrate_id == VERLEGD_ID and data.samengevoegde_regel.btw_bron == "standaard"


def test_leverancier_geheugen_wint_van_default(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    ai_gate_aan: None,
    fake_extraheer: None,
    default_verlegd: None,
) -> None:
    """Heeft de engine een btw-voorstel (hier op leverancier-niveau), dan blijft het veld leeg voor de UI —
    die vult 'm via /boekingsgeheugen/voorstel mét geheugen-chip. De default overrulet het geheugen nooit."""
    with scoped_session(administratie_id) as session:
        session.add(
            BoekingObservatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                vendor_id=VENDOR_ID,
                regel_sleutel=None,
                gb_id=GB_ID,
                btw_id=GEHEUGEN_BTW_ID,
                project_id=None,
                bron="app",
                bron_datum=datetime.now(UTC).date(),
            )
        )
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    diesel, huur = data.regels
    assert diesel.taxrate_id == HOOG_ID and diesel.btw_bron == "factuur"  # factuur blijft eerst
    assert huur.taxrate_id is None and huur.btw_bron is None
    assert data.samengevoegde_regel is not None and data.samengevoegde_regel.taxrate_id is None


def test_default_uit_vult_niets(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    ai_gate_aan: None,
    fake_extraheer: None,
    stamgegevens: None,
) -> None:
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    assert data.regels[1].taxrate_id is None and data.regels[1].btw_bron is None


def test_opgeslagen_voorstel_wordt_niet_geraakt(
    gescoopte_gebruiker: uuid.UUID,
    administratie_id: uuid.UUID,
    opslag: LokaleBestandsopslag,
    ai_gate_aan: None,
    fake_extraheer: None,
    default_verlegd: None,
) -> None:
    document_id = _upload(administratie_id, gescoopte_gebruiker, opslag)
    data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
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
                ledger_id=GB_ID,
                taxrate_id=None,
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
    assert all(r.taxrate_id is None and r.btw_bron is None for r in opnieuw.regels)  # expres leeg gelaten = leeg
