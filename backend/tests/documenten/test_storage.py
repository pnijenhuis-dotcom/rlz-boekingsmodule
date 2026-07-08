from __future__ import annotations

from pathlib import Path

import pytest

from app.documenten.storage import LokaleBestandsopslag


def test_opslaan_en_lezen_roundtrip(tmp_path: Path) -> None:
    opslag = LokaleBestandsopslag(tmp_path / "documenten")
    opslag.opslaan(pad="admin-1/doc-1.pdf", inhoud=b"%PDF-inhoud")
    assert opslag.bestaat(pad="admin-1/doc-1.pdf")
    assert opslag.lezen(pad="admin-1/doc-1.pdf") == b"%PDF-inhoud"


def test_niet_bestaand_pad(tmp_path: Path) -> None:
    opslag = LokaleBestandsopslag(tmp_path / "documenten")
    assert not opslag.bestaat(pad="onbekend.pdf")


def test_pad_buiten_basismap_wordt_geweigerd(tmp_path: Path) -> None:
    opslag = LokaleBestandsopslag(tmp_path / "documenten")
    with pytest.raises(ValueError, match="buiten de opslagmap"):
        opslag.opslaan(pad="../buiten.pdf", inhoud=b"x")
