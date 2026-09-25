"""FV-09 (feedbackrun A 25-09, blok 6): de tijdlijn-notitie `btw_herrekend` kent sinds 25-09 twee aanleidingen —
`tarief` (18-09: tarief én btw-bedrag gewisseld) en `netto` (zelfde tarief, netto gewijzigd én btw-bedrag mee) — zodat
de tijdlijn zegt "Btw herrekend — regel n: netto € a → € b, btw € c → € d (netto gewijzigd)". Een btw-wijziging zónder
netto- of tariefwijziging is een mens-invoer en geen notitie. Puur (geen DB): ORM-objecten als snapshot."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.documenten.boekvoorstel import (
    BTW_HERREKEND_AANLEIDING_NETTO,
    BTW_HERREKEND_AANLEIDING_TARIEF,
    _btw_herrekend_notities,
)
from app.documenten.models import BoekvoorstelRegel

HOOG = uuid.uuid4()
NUL = uuid.uuid4()


def _regel(taxrate_id: uuid.UUID | None, netto: str | None, btw: str | None) -> BoekvoorstelRegel:
    return BoekvoorstelRegel(
        document_id=uuid.uuid4(),
        volgnummer=1,
        ledger_id=None,
        taxrate_id=taxrate_id,
        netto_bedrag=Decimal(netto) if netto is not None else None,
        btw_bedrag=Decimal(btw) if btw is not None else None,
    )


class TestBtwHerrekendNotities:
    def test_netto_gewijzigd_zelfde_tarief_btw_mee_is_aanleiding_netto(self) -> None:
        uit = _btw_herrekend_notities([_regel(HOOG, "96.36", "20.24")], [_regel(HOOG, "100.00", "21.00")])
        assert len(uit) == 1
        n = uit[0]
        assert n["aanleiding"] == BTW_HERREKEND_AANLEIDING_NETTO
        assert (n["regel"], n["netto_van"], n["netto_naar"], n["btw_van"], n["btw_naar"]) == (
            1,
            "96.36",
            "100.00",
            "20.24",
            "21.00",
        )
        assert n["in_kosten"] is False

    def test_tariefwissel_blijft_aanleiding_tarief_ook_met_nettowijziging_in_kosten(self) -> None:
        uit = _btw_herrekend_notities([_regel(HOOG, "96.36", "20.24")], [_regel(NUL, "116.60", "0.00")])
        assert len(uit) == 1
        assert uit[0]["aanleiding"] == BTW_HERREKEND_AANLEIDING_TARIEF
        assert uit[0]["in_kosten"] is True

    def test_alleen_btw_gewijzigd_is_mens_invoer_geen_notitie(self) -> None:
        assert _btw_herrekend_notities([_regel(HOOG, "96.36", "20.24")], [_regel(HOOG, "96.36", "20.20")]) == []

    def test_netto_gewijzigd_zonder_btw_wijziging_geen_notitie(self) -> None:
        # Bijvoorbeeld tarief onbekend: het scherm laat de btw staan — er is niets herrekend.
        assert _btw_herrekend_notities([_regel(None, "96.36", "20.24")], [_regel(None, "100.00", "20.24")]) == []

    def test_netto_gewijzigd_zonder_tarief_maar_btw_mee_is_geen_notitie(self) -> None:
        # Zonder tarief kán er niet uit het tarief herrekend zijn (de mens typte het) — geen notitie.
        assert _btw_herrekend_notities([_regel(None, "96.36", "20.24")], [_regel(None, "100.00", "21.00")]) == []

    def test_nieuwe_of_verwijderde_regel_telt_niet(self) -> None:
        assert _btw_herrekend_notities([], [_regel(HOOG, "100.00", "21.00")]) == []
        assert _btw_herrekend_notities([_regel(HOOG, "96.36", "20.24")], []) == []
