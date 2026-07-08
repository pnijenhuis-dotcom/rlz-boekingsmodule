from __future__ import annotations

import itertools

import pytest

from app.documenten.models import DocumentStatus
from app.documenten.statusmachine import _TOEGESTANE_OVERGANGEN, OngeldigeStatusovergang, valideer_overgang

_ALLE_GELDIGE_PAREN = {(van, naar) for van, toegestaan in _TOEGESTANE_OVERGANGEN.items() for naar in toegestaan}


@pytest.mark.parametrize(("van", "naar"), sorted(_ALLE_GELDIGE_PAREN, key=lambda p: (p[0].value, p[1].value)))
def test_geldige_overgang_slaagt(van: DocumentStatus, naar: DocumentStatus) -> None:
    valideer_overgang(van, naar)  # geen exception


_ALLE_PAREN = set(itertools.product(DocumentStatus, DocumentStatus))
_ONGELDIGE_PAREN = _ALLE_PAREN - _ALLE_GELDIGE_PAREN


@pytest.mark.parametrize(("van", "naar"), sorted(_ONGELDIGE_PAREN, key=lambda p: (p[0].value, p[1].value)))
def test_ongeldige_overgang_faalt(van: DocumentStatus, naar: DocumentStatus) -> None:
    with pytest.raises(OngeldigeStatusovergang):
        valideer_overgang(van, naar)


def test_terminale_statussen_hebben_geen_uitgaande_overgangen() -> None:
    assert _TOEGESTANE_OVERGANGEN[DocumentStatus.AFGEWEZEN] == frozenset()
    assert _TOEGESTANE_OVERGANGEN[DocumentStatus.GEBOEKT] == frozenset()


def test_elke_status_staat_in_de_overgangstabel() -> None:
    """Voorkomt een stil gat: een nieuwe DocumentStatus-waarde die vergeten wordt toe te voegen
    aan _TOEGESTANE_OVERGANGEN zou anders geruisloos overal als 'geen overgangen toegestaan'
    behandeld worden."""
    assert set(_TOEGESTANE_OVERGANGEN.keys()) == set(DocumentStatus)
