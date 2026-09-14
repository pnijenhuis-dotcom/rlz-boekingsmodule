"""Stap 5b van de winnaarsvolgorde (regel_prefill.py; migratie 0143): de uit de historie afgeleide grootboek-default —
ná de RLZ-default (die wint), vóór de administratie-default (die verliest); alleen op een regel mét grootboek, tarief in
de actuele cache, geheugen wint, `btw_bewust_leeg` remt WÉL; `btw_bron_detail` = "meestal op deze rekening (n×)"."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime
from decimal import Decimal

import pytest
from sqlalchemy import update

from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.documenten import regel_prefill
from app.documenten.boekvoorstel import _AUTOSAVE_HERKOMSTEN, BoekvoorstelRegelData
from app.documenten.regel_prefill import (
    BTW_BRON_GROOTBOEK,
    BTW_BRON_GROOTBOEK_HISTORIE,
    BTW_BRON_STANDAARD,
    grootboek_historie_defaults_voor,
)
from app.geheugen.engine import Observatie
from app.sync.models import TaxRateCache

GB_HISTORIE = uuid.UUID("44444444-0000-0000-0000-000000004404")  # alleen historie-default
GB_BEIDE = uuid.UUID("44444444-0000-0000-0000-000000004406")  # RLZ-default laag + historie hoog → RLZ wint
GB_ZONDER = uuid.UUID("44444444-0000-0000-0000-000000004403")
GB_VERDWENEN = uuid.UUID("44444444-0000-0000-0000-000000004405")
HOOG_ID = uuid.UUID("55555555-0000-0000-0000-000000000021")
LAAG_ID = uuid.UUID("55555555-0000-0000-0000-000000000009")
VERDWENEN_ID = uuid.UUID("55555555-0000-0000-0000-000000000099")
DOCUMENT_ID = uuid.UUID("bbbbbbbb-0000-0000-0000-000000000002")


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
        for ledger_id, code, rlz_default, historie, n in (
            (GB_HISTORIE, "4404", None, HOOG_ID, 12),
            (GB_BEIDE, "4406", LAAG_ID, HOOG_ID, 30),
            (GB_ZONDER, "4403", None, None, None),
            (GB_VERDWENEN, "4405", None, VERDWENEN_ID, 8),
        ):
            session.add(
                Grootboekrekening(
                    ledger_id=ledger_id,
                    administratie_id=administratie_id,
                    code=code,
                    naam=f"Rekening {code}",
                    soort=2,
                    is_totaalrekening=False,
                    standaard_taxrate_id=rlz_default,
                    historie_taxrate_id=historie,
                    historie_taxrate_n=n,
                    historie_taxrate_aandeel=Decimal("0.95") if historie else None,
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
        return regel_prefill.verrijk_prefill(
            session,
            administratie_id=administratie_id,
            document_id=DOCUMENT_ID,
            vendor_id=None,
            regels=regels,
            samengevoegde_regel=None,
            **kw,
        )


def test_historie_defaults_voor_filtert_op_actieve_tarieven(administratie_id: uuid.UUID, stam: None) -> None:
    with scoped_session(administratie_id) as session:
        assert grootboek_historie_defaults_voor(session, administratie_id=administratie_id) == {
            GB_HISTORIE: (HOOG_ID, 12),
            GB_BEIDE: (HOOG_ID, 30),
        }


def test_historie_default_vult_leeg_veld_met_oranje_herkomst_en_detail(administratie_id: uuid.UUID, stam: None) -> None:
    (historie, beide, zonder, verdwenen, zonder_gb), _ = _verrijk(
        administratie_id,
        [
            _regel(ledger_id=GB_HISTORIE),
            _regel(ledger_id=GB_BEIDE),
            _regel(ledger_id=GB_ZONDER),
            _regel(ledger_id=GB_VERDWENEN),
            _regel(),
        ],
    )
    assert (historie.taxrate_id, historie.btw_bron) == (HOOG_ID, BTW_BRON_GROOTBOEK_HISTORIE)
    assert historie.btw_bron_detail == "meestal op deze rekening (12×)"
    assert historie.prefill_herkomst == {"btw": BTW_BRON_GROOTBOEK_HISTORIE}
    # De échte RLZ-default (stap 5) wint van de historie (stap 5b).
    assert (beide.taxrate_id, beide.btw_bron) == (LAAG_ID, BTW_BRON_GROOTBOEK)
    assert zonder.taxrate_id is None and verdwenen.taxrate_id is None and zonder_gb.taxrate_id is None


def test_historie_default_wint_van_administratie_default_maar_respecteert_bewust_leeg(
    administratie_id: uuid.UUID, stam: None
) -> None:
    with scoped_session(administratie_id) as session:
        session.execute(
            update(Administratie).where(Administratie.id == administratie_id).values(standaard_taxrate_id=LAAG_ID)
        )
    (historie, zonder, bewust_leeg), _ = _verrijk(
        administratie_id,
        [_regel(ledger_id=GB_HISTORIE), _regel(ledger_id=GB_ZONDER), _regel(ledger_id=GB_HISTORIE, btw_bewust_leeg=True)],
    )
    assert (historie.taxrate_id, historie.btw_bron) == (HOOG_ID, BTW_BRON_GROOTBOEK_HISTORIE)
    assert (zonder.taxrate_id, zonder.btw_bron) == (LAAG_ID, BTW_BRON_STANDAARD)
    # A3: de scan liet de btw bewust leeg (0 %/ambigu) — een afgeleide default zwijgt, net als de administratie-default.
    assert bewust_leeg.taxrate_id is None and bewust_leeg.btw_bron is None


def test_factuur_en_geheugen_winnen_van_de_historie_default(administratie_id: uuid.UUID, stam: None, monkeypatch) -> None:
    (factuur,), _ = _verrijk(administratie_id, [_regel(ledger_id=GB_HISTORIE, taxrate_id=LAAG_ID, btw_bron="factuur")])
    assert (factuur.taxrate_id, factuur.btw_bron) == (LAAG_ID, "factuur")

    def _engine_met_btw(*_a, **_k) -> list[Observatie]:
        return [
            Observatie(
                regel_sleutel=None,
                gb_id=GB_HISTORIE,
                btw_id=LAAG_ID,
                project_id=None,
                bron="app_bevestigd",
                bron_datum=datetime(2026, 9, 1, tzinfo=UTC).date(),
            )
        ]

    monkeypatch.setattr(regel_prefill, "_engine_observaties", _engine_met_btw)
    with scoped_session(administratie_id) as session:
        (regel,), _ = regel_prefill.verrijk_prefill(
            session,
            administratie_id=administratie_id,
            document_id=DOCUMENT_ID,
            vendor_id=uuid.uuid4(),
            regels=[_regel(ledger_id=GB_HISTORIE, omschrijving="Iets nieuws")],
            samengevoegde_regel=None,
        )
    assert regel.taxrate_id == LAAG_ID and regel.prefill_herkomst == {"btw": "leverancier_geheugen"}


def test_samengevoegde_regel_en_autosave_trigger(administratie_id: uuid.UUID, stam: None) -> None:
    with scoped_session(administratie_id) as session:
        _, samengevoegd = regel_prefill.verrijk_prefill(
            session,
            administratie_id=administratie_id,
            document_id=DOCUMENT_ID,
            vendor_id=None,
            regels=[],
            samengevoegde_regel=_regel(ledger_id=GB_HISTORIE),
        )
    assert samengevoegd is not None
    assert (samengevoegd.taxrate_id, samengevoegd.btw_bron) == (HOOG_ID, BTW_BRON_GROOTBOEK_HISTORIE)
    assert BTW_BRON_GROOTBOEK_HISTORIE in _AUTOSAVE_HERKOMSTEN, "checks moeten dezelfde btw zien als de mens (A10)"
