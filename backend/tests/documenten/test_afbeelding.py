"""Afbeelding → PDF (feedbackronde 25-08 deel 3 punt 2): deterministisch, verliesvrij voor JPEG,
HEIC via JPEG, onbruikbaar = expliciete fout; de PDF is leesbaar voor pypdf (rest van de keten)."""

from __future__ import annotations

import io

import pytest
from PIL import Image
from pypdf import PdfReader

from app.documenten.afbeelding import (
    AfbeeldingOnbruikbaar,
    afbeelding_naar_pdf,
    is_afbeelding,
    pdf_bestandsnaam,
)
from app.documenten.mime import content_type_voor
from app.documenten.pdf import tel_paginas


def _jpeg(breedte: int = 40, hoogte: int = 30, *, orientatie: int | None = None, mode: str = "RGB") -> bytes:
    beeld = Image.new(mode, (breedte, hoogte), 128 if mode == "L" else (200, 30, 30))
    buffer = io.BytesIO()
    exif = None
    if orientatie is not None:
        exif = Image.Exif()
        exif[0x0112] = orientatie
    beeld.save(buffer, format="JPEG", quality=90, **({"exif": exif} if exif is not None else {}))
    return buffer.getvalue()


def _png(breedte: int = 20, hoogte: int = 10, *, mode: str = "RGB") -> bytes:
    kleur = (10, 200, 10, 128) if mode == "RGBA" else (10, 200, 10)
    beeld = Image.new(mode, (breedte, hoogte), kleur)
    buffer = io.BytesIO()
    beeld.save(buffer, format="PNG")
    return buffer.getvalue()


def _heic() -> bytes:
    import pillow_heif

    pillow_heif.register_heif_opener()
    beeld = Image.new("RGB", (64, 48), (30, 60, 200))
    buffer = io.BytesIO()
    beeld.save(buffer, format="HEIF", quality=90)
    return buffer.getvalue()


class TestHerkenning:
    def test_suffix_of_content_type(self) -> None:
        assert is_afbeelding("foto.JPG")
        assert is_afbeelding("scan.heic")
        assert is_afbeelding("x.bin", "image/png")
        assert is_afbeelding("x.bin", "image/jpeg; name=foto")
        assert not is_afbeelding("factuur.pdf", "application/pdf")
        assert not is_afbeelding("logo.gif", "image/gif")  # bewust niet: geen standaard-documentformaat
        assert not is_afbeelding(None, None)

    def test_pdf_bestandsnaam(self) -> None:
        assert pdf_bestandsnaam("Factuur bouwmaat.jpeg") == "Factuur bouwmaat.pdf"
        assert pdf_bestandsnaam(".heic") == "afbeelding.pdf"

    def test_content_type_map(self) -> None:
        assert content_type_voor("a.pdf") == "application/pdf"
        assert content_type_voor("a.XML") == "application/xml"
        assert content_type_voor("a.jpg") == "image/jpeg"
        assert content_type_voor("a.heic") == "image/heic"
        assert content_type_voor("a.docx") == "application/octet-stream"


class TestOmzetting:
    def test_jpeg_wordt_verliesvrij_ingebed_en_is_deterministisch(self) -> None:
        jpeg = _jpeg()
        a = afbeelding_naar_pdf(jpeg, bestandsnaam="foto.jpg")
        b = afbeelding_naar_pdf(jpeg, bestandsnaam="foto.jpg")
        assert a.pdf == b.pdf  # zelfde bytes in = zelfde bytes uit (sha256-duplicaatcheck)
        assert a.pdf_bestandsnaam == "foto.pdf"
        assert jpeg in a.pdf  # originele JPEG-bytes zitten letterlijk in de PDF (DCTDecode)
        assert b"/DCTDecode" in a.pdf and b"/DeviceRGB" in a.pdf
        assert (a.breedte, a.hoogte, a.bron_formaat) == (40, 30, "JPEG")
        # Geen datums/ID's → niets tijdafhankelijks in het bestand.
        assert b"/CreationDate" not in a.pdf and b"/ID" not in a.pdf

    def test_pdf_is_leesbaar_voor_de_rest_van_de_keten(self) -> None:
        pdf = afbeelding_naar_pdf(_jpeg(), bestandsnaam="foto.jpg").pdf
        assert tel_paginas(pdf) == 1
        lezer = PdfReader(io.BytesIO(pdf))
        pagina = lezer.pages[0]
        assert len(pagina.images) == 1
        assert pagina.images[0].image.size == (40, 30)
        # Liggend beeld → liggende A4.
        assert float(pagina.mediabox.width) > float(pagina.mediabox.height)

    def test_staand_beeld_geeft_staande_pagina(self) -> None:
        pdf = afbeelding_naar_pdf(_jpeg(30, 40), bestandsnaam="f.jpg").pdf
        pagina = PdfReader(io.BytesIO(pdf)).pages[0]
        assert float(pagina.mediabox.height) > float(pagina.mediabox.width)

    def test_exif_rotatie_via_pagina_rotate_niet_via_hercodering(self) -> None:
        jpeg = _jpeg(40, 30, orientatie=6)
        uit = afbeelding_naar_pdf(jpeg, bestandsnaam="f.jpg")
        assert jpeg in uit.pdf  # nog steeds verliesvrij
        pagina = PdfReader(io.BytesIO(uit.pdf)).pages[0]
        assert pagina.get("/Rotate") == 90
        # Gedraaid beeld (40×30 → 30×40 voor de kijker) = staand → pagina vóór rotatie liggend.
        assert float(pagina.mediabox.width) > float(pagina.mediabox.height)

    def test_grijswaarden_jpeg(self) -> None:
        pdf = afbeelding_naar_pdf(_jpeg(mode="L"), bestandsnaam="f.jpg").pdf
        assert b"/DeviceGray" in pdf and b"/DCTDecode" in pdf

    def test_png_lossless_via_flate_en_alfa_op_wit(self) -> None:
        uit = afbeelding_naar_pdf(_png(mode="RGBA"), bestandsnaam="scan.png")
        assert b"/FlateDecode" in uit.pdf and uit.bron_formaat == "PNG"
        pagina = PdfReader(io.BytesIO(uit.pdf)).pages[0]
        beeld = pagina.images[0].image
        assert beeld.size == (20, 10)
        # Half-transparant groen op wit → lichter groen, exact reproduceerbaar (lossless).
        assert beeld.getpixel((0, 0)) == (132, 227, 132)
        assert afbeelding_naar_pdf(_png(mode="RGBA"), bestandsnaam="scan.png").pdf == uit.pdf

    def test_heic_gaat_via_jpeg(self) -> None:
        uit = afbeelding_naar_pdf(_heic(), bestandsnaam="IMG_0001.HEIC")
        assert uit.bron_formaat in ("HEIF", "HEIC")
        assert b"/DCTDecode" in uit.pdf and uit.pdf_bestandsnaam == "IMG_0001.pdf"
        assert afbeelding_naar_pdf(_heic(), bestandsnaam="IMG_0001.HEIC").pdf == uit.pdf
        assert PdfReader(io.BytesIO(uit.pdf)).pages[0].images[0].image.size == (64, 48)


class TestOnbruikbaar:
    def test_leeg(self) -> None:
        with pytest.raises(AfbeeldingOnbruikbaar, match="0 bytes"):
            afbeelding_naar_pdf(b"", bestandsnaam="f.jpg")

    def test_geen_afbeelding(self) -> None:
        with pytest.raises(AfbeeldingOnbruikbaar, match="geen herkenbare afbeelding"):
            afbeelding_naar_pdf(b"%PDF-1.4 dit is geen foto", bestandsnaam="f.jpg")

    def test_afgekapte_jpeg(self) -> None:
        jpeg = _jpeg(200, 200)
        with pytest.raises(AfbeeldingOnbruikbaar, match="niet te decoderen"):
            afbeelding_naar_pdf(jpeg[: len(jpeg) // 3], bestandsnaam="f.jpg")
