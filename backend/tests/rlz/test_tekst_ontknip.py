"""Blok 0 run 2 VGG (12-09): ontknippen van RLZ's 32-tekens-regelknip — parametrisch op de letterlijke
omschrijvingen uit de STAP-0 (rlz-lezen, 120 records) en de nameting 11-09."""

from __future__ import annotations

import pytest

from app.rlz.tekst import ontknip, ontknip_velden


@pytest.mark.parametrize(
    ("ruw", "verwacht"),
    [
        (
            "betreft: Gustaaf Gelderstraat 60\nte Almere, ons dossier: 2025.07\n8957.01",
            "betreft: Gustaaf Gelderstraat 60 te Almere, ons dossier: 2025.078957.01",
        ),
        (
            "betreft: Kruidenlaan 72 te Venra\ny, ons dossier: 2026.080367.01",
            "betreft: Kruidenlaan 72 te Venray, ons dossier: 2026.080367.01",
        ),
        (
            "betreft: Vondelstraat 14 te Roer\nmond, ons dossier: 2026.079949.0\n1",
            "betreft: Vondelstraat 14 te Roermond, ons dossier: 2026.079949.01",
        ),
        (
            "betreft: Bleijerheiderstraat 123\nB te Kerkrade, ons dossier:2025.\n079527.01",
            "betreft: Bleijerheiderstraat 123B te Kerkrade, ons dossier:2025.079527.01",
        ),
        (
            "Overdracht Heelsumstraat 75 te '\ns-Gravenhage, ons dossier:2026.0\n80234.01",
            "Overdracht Heelsumstraat 75 te 's-Gravenhage, ons dossier:2026.080234.01",
        ),
        (
            "Aanbetaling volgens afspraak: Oo\nsterdiepswal 7 te Kollum",
            "Aanbetaling volgens afspraak: Oosterdiepswal 7 te Kollum",
        ),
        ("2/2 aanbetaling Bornholmstraat 4\n9, Almere", "2/2 aanbetaling Bornholmstraat 49, Almere"),
        (
            "Aanbetaling volgens afspraak: St\nadhoudersring 374, Zoetermeer",
            "Aanbetaling volgens afspraak: Stadhoudersring 374, Zoetermeer",
        ),
        (
            "Aanbetaling volgens afspraak All\nard Piersonlaan 20, Den Haag",
            "Aanbetaling volgens afspraak Allard Piersonlaan 20, Den Haag",
        ),
        ("Haringvlietstraat 44 Dordrecht R\nente", "Haringvlietstraat 44 Dordrecht Rente"),
        (
            "Overdracht Sportlaan 180 te Purm\nerend, ons dossier: 2026.080301.\n01",
            "Overdracht Sportlaan 180 te Purmerend, ons dossier: 2026.080301.01",
        ),
        ("Laatste vaste lasten: Duifhuis 1\n1, Berlicum", "Laatste vaste lasten: Duifhuis 11, Berlicum"),
        # géén 32-grens = echte regelovergang → spatie (betaalkenmerk + documentregel)
        ("2026-0731\nRLZ-04-00000856 1-9-2026", "2026-0731 RLZ-04-00000856 1-9-2026"),
        # 31 tekens (RLZ stripte een slotspatie) → spatie
        (
            "Cafe Restaurant Meyer Amsterdam\n04-09-2026 18:03TERMINALID: 4746\n4443 PASVOLGNR: 001",
            "Cafe Restaurant Meyer Amsterdam 04-09-2026 18:03TERMINALID: 47464443 PASVOLGNR: 001",
        ),
        ("Vaste lasten: Dwartsweg 22, Zeis\nt maand mei", "Vaste lasten: Dwartsweg 22, Zeist maand mei"),
        ("Kerkstraat 44", "Kerkstraat 44"),
        ("  dubbele   spaties \n regel ", "dubbele spaties regel"),
        ("", None),
        (None, None),
    ],
)
def test_ontknip(ruw: str | None, verwacht: str | None) -> None:
    assert ontknip(ruw) == verwacht


def test_ontknip_is_idempotent() -> None:
    eenmaal = ontknip("Aanbetaling volgens afspraak: Oo\nsterdiepswal 7 te Kollum")
    assert ontknip(eenmaal) == eenmaal


def test_ontknip_velden_eerste_gevulde() -> None:
    rij = {"Description": "", "Header": "Betreft: Oo\nster", "Reference": "x"}
    assert ontknip_velden(rij, "Description", "Header", "Reference") == "Betreft: Oo ster"  # 11 tekens ≠ 32 → spatie
    assert ontknip_velden({"Description": None}, "Description") is None
