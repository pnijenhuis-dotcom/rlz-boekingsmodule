"""Guard (nameting 19-09 ic_spiegel_rood): de `--alleen`-keuzelijst van `reconciliatie-alles` is exact `run.BLOKKEN`.

Aanleiding: de meetlat uit docs/regels (`reconciliatie-alles --alleen doorbelasting_aansluiting --lees-only`) gaf op de
job-image argparse-exit 2 ("invalid choice") omdat het blok wél in `run.BLOKKEN` en in de blokkenlijst van de CLI stond,
maar niet in de hard gecodeerde `choices=`. Eén bron voorkomt dat een nieuw blok wél draait maar niet los meetbaar is.
Onderscheid: een geldige keuze zónder --lees-only eindigt in de eigen FOUT-regel (return 2), een ongeldige keuze laat
argparse `SystemExit` gooien — dáárop toetst deze test, zonder RLZ of database te raken."""

from __future__ import annotations

import pytest

from app import cli
from app.reconciliatie import run as reconciliatie_run


@pytest.mark.parametrize("blok", reconciliatie_run.BLOKKEN)
def test_elk_run_blok_is_een_geldige_alleen_keuze(blok: str, capsys: pytest.CaptureFixture[str]) -> None:
    # Zonder --lees-only stopt de CLI vóór enig blok draait: return 2 mét de eigen melding, géén argparse-SystemExit.
    assert cli.main(["reconciliatie-alles", "--alleen", blok]) == 2
    assert "--alleen werkt uitsluitend samen met --lees-only" in capsys.readouterr().err


def test_keuzelijst_is_run_blokken() -> None:
    assert cli._reconciliatie_run_blokken() == tuple(reconciliatie_run.BLOKKEN)
    assert "doorbelasting_aansluiting" in cli._reconciliatie_run_blokken()


def test_onbekend_blok_blijft_argparse_fout() -> None:
    with pytest.raises(SystemExit) as exc:
        cli.main(["reconciliatie-alles", "--alleen", "bestaat_niet", "--lees-only"])
    assert exc.value.code == 2
