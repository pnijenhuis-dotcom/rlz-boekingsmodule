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


def test_geboekt_en_gesplitst_zijn_de_terminale_statussen() -> None:
    """Bewaarplicht (design-pass taak 4): een geboekt document kan naar geen andere status meer,
    óók niet naar verwijderd. Sinds de e-mail-intake (migratie 0028) geldt hetzelfde voor een
    gesplitst bron-document: de kind-documenten verwijzen ernaar (gesplitst_uit_id) — het
    origineel verwijderen zou hun herkomst breken. Elke andere status (zelfs afgewezen) heeft
    nog altijd minstens verwijderd als uitgang. Uitzondering sinds het tegenboek-pad (migratie
    0061, mockup 22-08): GEBOEKT heeft precies één uitgang — terug naar te_controleren bij
    "tegenboeken én opnieuw boeken" (alleen ná een geslaagde tegenboeking in RLZ); nooit naar
    verwijderd."""
    assert _TOEGESTANE_OVERGANGEN[DocumentStatus.GEBOEKT] == frozenset({DocumentStatus.TE_CONTROLEREN})
    assert DocumentStatus.VERWIJDERD not in _TOEGESTANE_OVERGANGEN[DocumentStatus.GEBOEKT]
    assert _TOEGESTANE_OVERGANGEN[DocumentStatus.GESPLITST] == frozenset()
    assert _TOEGESTANE_OVERGANGEN[DocumentStatus.SAMENGEVOEGD] == frozenset({DocumentStatus.NIET_TOEGEWEZEN})
    for van in DocumentStatus:
        if van in (
            DocumentStatus.GEBOEKT,
            DocumentStatus.GESPLITST,
            DocumentStatus.VERWIJDERD,
            # Klant-accordering (migratie 0033): een document dat bij de klant ligt is bewust
            # niet direct verwijderbaar — eerst intrekken (→ klaar_om_te_boeken), dan pas.
            DocumentStatus.TER_ACCORDERING,
            # Samengevoegd (migratie 0098, blok B4 02-09): de rij is het beeld/de bron van het
            # leidende document — enige uitgang is "samenvoegen ongedaan" (→ niet_toegewezen),
            # nooit verwijderd (het bestand blijft terugvindbaar op sha256).
            DocumentStatus.SAMENGEVOEGD,
        ):
            continue
        assert DocumentStatus.VERWIJDERD in _TOEGESTANE_OVERGANGEN[van], f"{van} kan niet verwijderd worden"


def test_ter_accordering_kan_alleen_terug_naar_de_kantoorbak() -> None:
    """Klant-accordering (migratie 0033): de enige uitgang is klaar_om_te_boeken — het laatste
    akkoord (waarna de boekmotor zelf boekt), intrekken door het kantoor én de afwijs-route
    (die eerst terugzet en dan het bestaande afwijzen-patroon volgt) lopen daar allemaal
    doorheen; nooit rechtstreeks naar geboekt of verwijderd."""
    assert _TOEGESTANE_OVERGANGEN[DocumentStatus.TER_ACCORDERING] == frozenset(
        {DocumentStatus.KLAAR_OM_TE_BOEKEN}
    )
    assert DocumentStatus.TER_ACCORDERING in _TOEGESTANE_OVERGANGEN[DocumentStatus.KLAAR_OM_TE_BOEKEN]


def test_verwijderd_kan_terug_naar_elke_status_die_er_ook_naartoe_mag() -> None:
    """herstel_document() zet een document terug op zijn status van vóór de verwijdering — dat
    moet voor elke mogelijke 'vorige status' een toegestane overgang zijn, anders faalt een
    geldig herstel op de statusmachine zelf."""
    bronnen_van_verwijderd = {
        van for van, toegestaan in _TOEGESTANE_OVERGANGEN.items() if DocumentStatus.VERWIJDERD in toegestaan
    }
    assert bronnen_van_verwijderd <= _TOEGESTANE_OVERGANGEN[DocumentStatus.VERWIJDERD]


def test_elke_status_staat_in_de_overgangstabel() -> None:
    """Voorkomt een stil gat: een nieuwe DocumentStatus-waarde die vergeten wordt toe te voegen
    aan _TOEGESTANE_OVERGANGEN zou anders geruisloos overal als 'geen overgangen toegestaan'
    behandeld worden."""
    assert set(_TOEGESTANE_OVERGANGEN.keys()) == set(DocumentStatus)
