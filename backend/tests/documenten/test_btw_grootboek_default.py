"""Btw-default uit de grootboekrekening (opdracht Peter 14-09, casus L.H.G. Holding "Kosten mobiele telefonie"):
stap 5 van de winnaarsvolgorde in regel_prefill.py — factuur (berekend/verlegd) en leverancier-geheugen winnen, de
grootboek-default wint van de administratie-default, vult alleen een leeg btw-veld op een regel MÉT grootboek, negeert
`btw_bewust_leeg` (expliciete RLZ-keuze) en een tarief dat niet (meer) in de cache staat."""

from __future__ import annotations

import uuid
from dataclasses import replace
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.documenten import regel_prefill
from app.documenten.boekvoorstel import BoekvoorstelRegelData
from app.documenten.regel_prefill import BTW_BRON_GROOTBOEK, BTW_BRON_STANDAARD, grootboek_defaults_voor
from app.geheugen.engine import Observatie
from app.sync.models import TaxRateCache

GB_MOBIEL = uuid.UUID("44444444-0000-0000-0000-000000004404")
GB_ZONDER = uuid.UUID("44444444-0000-0000-0000-000000004403")
GB_VERDWENEN_TARIEF = uuid.UUID("44444444-0000-0000-0000-000000004405")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")
LAAG_ID = uuid.UUID("55555555-0000-0000-0000-000000000009")
VERDWENEN_ID = uuid.UUID("55555555-0000-0000-0000-000000000099")
DOCUMENT_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000001")


@pytest.fixture
def stam(administratie_id: uuid.UUID) -> None:
    with scoped_session(administratie_id) as session:
        for id_, naam, pct in ((HOOG_ID, "NL, Hoog Tarief", "0.2100"), (LAAG_ID, "NL, Laag Tarief", "0.0900")):
            session.add(
                TaxRateCache(id=id_, administratie_id=administratie_id, naam=naam, percentage=Decimal(pct), brondata={})
            )
        session.add(
            TaxRateCache(
                id=VERDWENEN_ID,
                administratie_id=administratie_id,
                naam="Oud tarief",
                percentage=Decimal("0"),
                brondata={},
                verdwenen_uit_bron_op=datetime(2026, 9, 1, tzinfo=UTC),
            )
        )
        for ledger_id, code, default in (
            (GB_MOBIEL, "4404", HOOG_ID),
            (GB_ZONDER, "4403", None),
            (GB_VERDWENEN_TARIEF, "4405", VERDWENEN_ID),
        ):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=administratie_id,
                    code=code,
                    naam=f"Rekening {code}",
                    soort=2,
                    is_totaalrekening=False,
                    standaard_taxrate_id=default,
                )
            )


def _regel(**kw) -> BoekvoorstelRegelData:
    basis = dict(
        ledger_id=None,
        taxrate_id=None,
        project_id=None,
        netto_bedrag=Decimal("100.00"),
        btw_bedrag=None,
        omschrijving="Abonnement mobiel",
    )
    return BoekvoorstelRegelData(**{**basis, **kw})


def _verrijk(administratie_id: uuid.UUID, regels: list[BoekvoorstelRegelData], **kw):
    with scoped_session(administratie_id) as session:
        verrijkt, samengevoegd = regel_prefill.verrijk_prefill(
            session,
            administratie_id=administratie_id,
            document_id=DOCUMENT_ID,
            vendor_id=None,
            regels=regels,
            samengevoegde_regel=None,
            **kw,
        )
    return verrijkt, samengevoegd


def test_grootboek_defaults_voor_filtert_op_actieve_tarieven_en_rekeningen(
    administratie_id: uuid.UUID, stam: None
) -> None:
    with scoped_session(administratie_id) as session:
        assert grootboek_defaults_voor(session, administratie_id=administratie_id) == {GB_MOBIEL: HOOG_ID}
        # rekening verdwenen uit de bron → geen default meer
        session.execute(
            update(Grootboekrekening)
            .where(Grootboekrekening.ledger_id == GB_MOBIEL)
            .values(verdwenen_uit_bron_op=datetime(2026, 9, 10, tzinfo=UTC))
        )
        session.flush()
        assert grootboek_defaults_voor(session, administratie_id=administratie_id) == {}


def test_grootboek_default_vult_leeg_btw_veld_van_regel_met_grootboek(administratie_id: uuid.UUID, stam: None) -> None:
    (mobiel, zonder_gb, zonder_default, verdwenen), _ = _verrijk(
        administratie_id,
        [
            _regel(ledger_id=GB_MOBIEL),
            _regel(),  # geen grootboek → geen default (de mens kiest eerst de rekening)
            _regel(ledger_id=GB_ZONDER),
            _regel(ledger_id=GB_VERDWENEN_TARIEF),
        ],
    )
    assert (mobiel.taxrate_id, mobiel.btw_bron) == (HOOG_ID, BTW_BRON_GROOTBOEK)
    assert mobiel.prefill_herkomst == {"btw": BTW_BRON_GROOTBOEK}
    assert zonder_gb.taxrate_id is None and zonder_gb.btw_bron is None
    assert zonder_default.taxrate_id is None and zonder_default.btw_bron is None
    assert verdwenen.taxrate_id is None, "een tarief dat niet (meer) in de cache staat vult nooit"


def test_grootboek_default_negeert_bewust_leeg_maar_admin_default_niet(administratie_id: uuid.UUID, stam: None) -> None:
    """A3-regel (0 %/ambigu bewust leeg → administratie-default zwijgt) geldt niet voor de grootboek-default: die is een
    expliciete keuze in RLZ, geen scan-afleiding."""
    with scoped_session(administratie_id) as session:
        session.execute(
            update(Administratie).where(Administratie.id == administratie_id).values(standaard_taxrate_id=LAAG_ID)
        )
    (mobiel, zonder_default), _ = _verrijk(
        administratie_id,
        [_regel(ledger_id=GB_MOBIEL, btw_bewust_leeg=True), _regel(ledger_id=GB_ZONDER, btw_bewust_leeg=True)],
    )
    assert (mobiel.taxrate_id, mobiel.btw_bron) == (HOOG_ID, BTW_BRON_GROOTBOEK)
    assert zonder_default.taxrate_id is None and zonder_default.btw_bron is None


def test_grootboek_default_wint_van_administratie_default(administratie_id: uuid.UUID, stam: None) -> None:
    with scoped_session(administratie_id) as session:
        session.execute(
            update(Administratie).where(Administratie.id == administratie_id).values(standaard_taxrate_id=LAAG_ID)
        )
    (mobiel, zonder_default), _ = _verrijk(administratie_id, [_regel(ledger_id=GB_MOBIEL), _regel(ledger_id=GB_ZONDER)])
    assert (mobiel.taxrate_id, mobiel.btw_bron) == (HOOG_ID, BTW_BRON_GROOTBOEK)
    assert (zonder_default.taxrate_id, zonder_default.btw_bron) == (LAAG_ID, BTW_BRON_STANDAARD)


def test_factuur_en_geheugen_winnen_van_de_grootboek_default(
    administratie_id: uuid.UUID, stam: None, monkeypatch
) -> None:
    # Factuur berekend: het veld staat al gevuld mét btw_bron='factuur' — de default raakt 'm niet.
    (factuur,), _ = _verrijk(administratie_id, [_regel(ledger_id=GB_MOBIEL, taxrate_id=LAAG_ID, btw_bron="factuur")])
    assert (factuur.taxrate_id, factuur.btw_bron) == (LAAG_ID, "factuur")

    # Leverancier-geheugen mét btw: de engine wint (de UI vult 'm mét geheugen-chip) — geen grootboek-default.
    def _engine_met_btw(*_a, **_k) -> list[Observatie]:
        return [
            Observatie(
                regel_sleutel=None,
                gb_id=GB_MOBIEL,
                btw_id=LAAG_ID,
                project_id=None,
                bron="app_bevestigd",
                bron_datum=datetime(2026, 9, 1, tzinfo=UTC).date(),
            )
        ]

    monkeypatch.setattr(regel_prefill, "_engine_observaties", _engine_met_btw)
    with scoped_session(administratie_id) as session:
        verrijkt, _ = regel_prefill.verrijk_prefill(
            session,
            administratie_id=administratie_id,
            document_id=DOCUMENT_ID,
            vendor_id=uuid.uuid4(),
            regels=[replace(_regel(ledger_id=GB_MOBIEL), omschrijving="Iets nieuws")],
            samengevoegde_regel=None,
        )
    (regel,) = verrijkt
    assert regel.taxrate_id == LAAG_ID and regel.prefill_herkomst == {"btw": "leverancier_geheugen"}


def test_samengevoegde_regel_volgt_dezelfde_regel(administratie_id: uuid.UUID, stam: None) -> None:
    with scoped_session(administratie_id) as session:
        _, samengevoegd = regel_prefill.verrijk_prefill(
            session,
            administratie_id=administratie_id,
            document_id=DOCUMENT_ID,
            vendor_id=None,
            regels=[],
            samengevoegde_regel=_regel(ledger_id=GB_MOBIEL),
        )
    assert samengevoegd is not None
    assert (samengevoegd.taxrate_id, samengevoegd.btw_bron) == (HOOG_ID, BTW_BRON_GROOTBOEK)
