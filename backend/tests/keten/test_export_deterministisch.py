"""Guard gouden set — de frontend-fixture-export is deterministisch (blok 5 vervolgrun 10-09 avond).

Aanleiding: `frontend/src/dev/keten/b_floor.json` veranderde bij élke keten-run in één veld — de afwijsreden van het
auto-afgevoerde module-duplicaat ("Duplicaat van 26219 (document … van <ONTVANGSTDATUM> in de werkvoorraad)",
`app/documenten/duplicaat_afvoer.py::Origineel.reden`) draagt de datum van `document.aangemaakt_op`, een DB-`now()`.
Tijdstippen normaliseert de export al (casussen.EXPORT_TIJDSTIP); een afgeleide DATUM glipt daar doorheen. Sinds blok 5
bevriest `Keten` het ontvangstmoment ná elke intake-stap op conftest.REFERENTIE_TIJDSTIP.

Deze tests bewaken (1) de bevriezing zelf, (2) dat casus b's reden de referentiedatum draagt, (3) dat de export bij
de eerste opening exact de gecommitte fixture is en herhaalde exports daarna byte-gelijk zijn, en (4) — sweep — dat
géén enkele geëxporteerde JSON de datum van vandaag bevat. Die sweep is eerlijk over zijn blinde vlek: valt vandaag op
de referentiedatum, dan kan hij drift niet van bevroren waarden onderscheiden en slaat hij over met die melding."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.documenten.models import DocumentStatus
from tests.keten import casussen
from tests.keten.casussen import Casus
from tests.keten.conftest import FRONTEND_KETEN_DIR, REFERENTIE_DATUM, REFERENTIE_TIJDSTIP, Keten, echte_vandaag_nl

CASUS = Casus(casussen.B_FLOOR)
XML, PDF = CASUS.xml_bestandsnaam(), CASUS.pdf_bestandsnaam()


def _mail_floor(keten: Keten, deel: str):
    pdf = CASUS.pdf()
    return keten.mail(
        [(XML, CASUS.xml(ingesloten_pdf=pdf)), (PDF, pdf)], onderwerp=f"Facturen universal steigerbouw {deel}"
    )


@pytest.fixture
def floor_twee_keer(keten: Keten) -> tuple:
    """Casus b/g zoals test_b: deel 5 = het werkstuk, deel 9 = byte-identiek exemplaar → afgevoerd als
    module-duplicaat."""
    eerste = _mail_floor(keten, "deel 5").bijlagen[0].document_id
    tweede = _mail_floor(keten, "deel 9").bijlagen[0].document_id
    return eerste, tweede


class TestOntvangstBevroren:
    def test_vers_document_landt_op_de_referentiedag(self, keten: Keten) -> None:
        document_id = _mail_floor(keten, "deel 5").bijlagen[0].document_id
        aangemaakt_op = keten.rij(document_id)["aangemaakt_op"]
        assert aangemaakt_op.date() == REFERENTIE_DATUM
        assert aangemaakt_op > REFERENTIE_TIJDSTIP  # + n seconden, nooit exact het referentietijdstip zelf

    def test_volgorde_en_ties_blijven(self, keten: Keten, floor_twee_keer: tuple) -> None:
        """Een latere intake-stap landt ná de eerdere (de duplicaat-motor kiest het OUDSTE als origineel), en beide
        exemplaren staan op de referentiedag."""
        eerste, tweede = floor_twee_keer
        a, b = keten.rij(eerste)["aangemaakt_op"], keten.rij(tweede)["aangemaakt_op"]
        assert a < b and a.date() == b.date() == REFERENTIE_DATUM

    def test_afwijsreden_draagt_de_referentiedatum(self, keten: Keten, floor_twee_keer: tuple) -> None:
        eerste, tweede = floor_twee_keer
        assert keten.status(tweede) == DocumentStatus.AFGEVOERD_DUPLICAAT
        reden = keten.afwijzing(tweede)["reden"]
        assert f"van {REFERENTIE_DATUM.isoformat()} in de werkvoorraad" in reden, reden
        if echte_vandaag_nl() != REFERENTIE_DATUM:
            assert echte_vandaag_nl().isoformat() not in reden, reden


class TestExportDeterministisch:
    def test_export_bij_eerste_opening_is_de_gecommitte_fixture_en_daarna_byte_stabiel(
        self, keten: Keten, floor_twee_keer: tuple, tmp_path: Path
    ) -> None:
        """Twee lagen determinisme, eerlijk uit elkaar gehouden:
        (1) cross-run/cross-dag: de export bij de EERSTE opening van het controlescherm (zoals test_b exporteert) is
            exact de gecommitte fixture — niet alleen qua tijdstippen/UUID's (die normaliseert de export) maar ook qua
            afgeleide datums (die bevriest `Keten`). Rood = de fixture is verouderd (draai tests/keten en commit de
            export) óf er drijft weer een veld met de kalender mee (zie de diff).
        (2) binnen één stand: ná die eerste opening zijn herhaalde exports byte-gelijk. De eerste opening zelf is
            bewust NIET gelijk aan de tweede — dat is leergedrag, geen klok: de IBAN-check legt bij het eerste openen de
            baseline vast ("Eerste IBAN … vastgelegd als baseline") en de prefill wordt gepersisteerd (A10 07-09)."""
        eerste, _ = floor_twee_keer
        eerste_opening = keten.exporteer("b_floor", eerste, doel=tmp_path / "1")
        herhaling_a = keten.exporteer("b_floor", eerste, doel=tmp_path / "2")
        herhaling_b = keten.exporteer("b_floor", eerste, doel=tmp_path / "3")
        assert eerste_opening is not None and herhaling_a is not None and herhaling_b is not None
        assert herhaling_a.read_bytes() == herhaling_b.read_bytes()
        gecommit = FRONTEND_KETEN_DIR / "b_floor.json"
        if not gecommit.exists():
            pytest.skip("geen frontend-map in deze checkout (CI-artefact) — laag (1) overgeslagen")
        vers = json.loads(eerste_opening.read_text(encoding="utf-8"))
        assert vers == json.loads(gecommit.read_text(encoding="utf-8")), (
            "export ≠ gecommitte b_floor.json — verouderde fixture (draai tests/keten, commit) of drift met de kalender"
        )


def test_sweep_geen_export_draagt_de_datum_van_vandaag() -> None:
    """Over álle geëxporteerde casus-JSON's: de datum van vandaag komt nergens voor. Fixture-datums (factuur-,
    verval-, periode-datums) liggen vast in de casusmappen; een waarde gelijk aan vandaag kan alleen uit de klok komen.
    Eerlijk over de blinde vlek: op de referentiedag zelf is 'vandaag' ook de bevroren waarde → overslaan mét
    melding."""
    if not FRONTEND_KETEN_DIR.exists():
        pytest.skip("geen frontend-map in deze checkout (CI-artefact)")
    vandaag = echte_vandaag_nl()
    if vandaag == REFERENTIE_DATUM:
        pytest.skip(
            f"vandaag ({vandaag.isoformat()}) is de referentiedatum van de gouden set — de sweep kan drift niet van "
            "bevroren waarden onderscheiden; morgen is hij weer scherp"
        )
    exports = sorted(FRONTEND_KETEN_DIR.glob("*.json"))
    assert exports, f"geen exports in {FRONTEND_KETEN_DIR} — draai eerst tests/keten"
    treffers = []
    for pad in exports:
        for nr, regel in enumerate(pad.read_text(encoding="utf-8").splitlines(), start=1):
            if vandaag.isoformat() in regel:
                treffers.append(f"{pad.name}:{nr}: {regel.strip()}")
    assert not treffers, (
        "Een export draagt de datum van vandaag — er drijft een veld met de kalender mee (of een fixture-datum valt "
        "toevallig op vandaag; dan is dit morgen groen). Bevries de bron in tests/keten/conftest.py "
        "(_bevries_ontvangst / normaliseer_voor_export), nooit door de assert te verzachten:\n  - "
        + "\n  - ".join(treffers)
    )
