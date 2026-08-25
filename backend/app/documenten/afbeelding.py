"""Afbeeldingen (JPEG/PNG/HEIC) → PDF bij binnenkomst (besluit Peter, feedbackronde 25-08 deel 3
punt 2): de hele keten — preview, AI-extractie, splitsing, RLZ-bijlage-upload, 7-jaar-archief —
blijft uniform PDF; het origineel blijft als brondocument bewaard (Document.bron_*-kolommen).

Eisen en hoe ze hier afgedwongen worden:
- DETERMINISTISCH: eigen minimale PDF-writer zonder /Info, datums of /ID; de xref wordt exact
  berekend. Dezelfde bytes in = dezelfde bytes uit — dus de sha256-duplicaatcheck bij binnenkomst
  blijft werken en een her-upload van dezelfde foto is idempotent.
- VERLIESVRIJ: een JPEG (RGB/grijs) wordt byte-voor-byte ingebed (/DCTDecode, geen hercodering);
  EXIF-rotatie wordt als pagina-/Rotate meegegeven i.p.v. de pixels te herschrijven. PNG (en
  andere niet-JPEG-bronnen) gaan als ruwe pixels met /FlateDecode — lossless; transparantie
  wordt op wit geplat (een factuur-PDF heeft geen alfakanaal).
- HEIC EERST NAAR JPEG (spec): HEIC is een gecomprimeerd fotoformaat; decoderen + verliesvrij
  opslaan zou 30+ MB per iPhone-foto geven. Eén deterministische JPEG-hercodering (kwaliteit 95,
  geen EXIF-herschrijving, oriëntatie via /Rotate) en daarna dezelfde DCT-inbedding.
- ONBRUIKBAAR = expliciete fout (AfbeeldingOnbruikbaar met reden: leeg, niet te decoderen,
  afgekapt, decompressiebom) — de aanroeper zet 'm zichtbaar in de verzamelbak, nooit stil.

Paginaformaat: A4 (staand of liggend naar de beeldverhouding), afbeelding schaalt passend zonder
marge — de pixels zelf blijven onaangeraakt, alleen de weergavematrix schaalt."""

from __future__ import annotations

import io
import zlib
from dataclasses import dataclass
from pathlib import Path

from PIL import Image, ImageOps, UnidentifiedImageError

AFBEELDING_SUFFIXEN = frozenset({".jpg", ".jpeg", ".png", ".heic", ".heif"})
AFBEELDING_CONTENT_TYPES = frozenset({"image/jpeg", "image/png", "image/heic", "image/heif", "image/heic-sequence"})
_HEIC_SUFFIXEN = frozenset({".heic", ".heif"})

# A4 in PDF-punten.
_A4_STAAND = (595.276, 841.890)
_HEIC_JPEG_KWALITEIT = 95
# EXIF-oriëntatie → PDF-/Rotate (kloksgewijs bij weergave). Gespiegelde varianten (2/4/5/7)
# komen bij camera's niet voor en gaan via de pixel-route (exif_transpose).
_ROTATIE = {1: 0, 3: 180, 6: 90, 8: 270}

_heif_geregistreerd = False


def _registreer_heif() -> None:
    global _heif_geregistreerd
    if not _heif_geregistreerd:
        import pillow_heif

        pillow_heif.register_heif_opener()
        _heif_geregistreerd = True


class AfbeeldingOnbruikbaar(Exception):
    """De afbeelding is geen bruikbaar document (leeg, corrupt, onleesbaar) — reden in str()."""


def is_afbeelding(bestandsnaam: str | None, content_type: str | None = None) -> bool:
    if bestandsnaam and Path(bestandsnaam).suffix.lower() in AFBEELDING_SUFFIXEN:
        return True
    return bool(content_type) and content_type.split(";")[0].strip().lower() in AFBEELDING_CONTENT_TYPES


def pdf_bestandsnaam(bestandsnaam: str) -> str:
    """foto.jpg → foto.pdf (de stam blijft herkenbaar; het origineel heet nog steeds foto.jpg)."""
    naam = Path(bestandsnaam).name
    laag = naam.lower()
    suffix = next((s for s in AFBEELDING_SUFFIXEN if laag.endswith(s)), "")
    stam = naam[: len(naam) - len(suffix)] if suffix else naam
    return f"{stam or 'afbeelding'}.pdf"


@dataclass(frozen=True)
class OmgezetteAfbeelding:
    pdf: bytes
    pdf_bestandsnaam: str
    breedte: int  # pixels van de bron (vóór rotatie)
    hoogte: int
    bron_formaat: str  # "JPEG" / "PNG" / "HEIF" — zoals Pillow 'm herkende


def afbeelding_naar_pdf(inhoud: bytes, *, bestandsnaam: str) -> OmgezetteAfbeelding:
    if not inhoud:
        raise AfbeeldingOnbruikbaar("leeg bestand (0 bytes)")
    if Path(bestandsnaam).suffix.lower() in _HEIC_SUFFIXEN or inhoud[4:12] in (b"ftypheic", b"ftypheix", b"ftypmif1"):
        _registreer_heif()
    try:
        beeld = Image.open(io.BytesIO(inhoud))
        beeld.load()  # dwingt volledige decodering af: afgekapte/corrupte data faalt hier
    except UnidentifiedImageError as exc:
        raise AfbeeldingOnbruikbaar("geen herkenbare afbeelding (JPEG/PNG/HEIC)") from exc
    except Image.DecompressionBombError as exc:
        raise AfbeeldingOnbruikbaar("afbeelding is onrealistisch groot (decompressiebom-grens)") from exc
    except Exception as exc:  # noqa: BLE001 — Pillow gooit per formaat andere fouten; alle = corrupt
        raise AfbeeldingOnbruikbaar(f"afbeelding niet te decoderen: {exc}") from exc

    breedte, hoogte = beeld.size
    if breedte < 1 or hoogte < 1:
        raise AfbeeldingOnbruikbaar("afbeelding zonder pixels")
    formaat = beeld.format or "ONBEKEND"
    orientatie = _exif_orientatie(beeld)

    if formaat == "JPEG" and beeld.mode in ("RGB", "L") and orientatie in _ROTATIE:
        # Verliesvrij: de originele JPEG-bytes zelf in het XObject.
        pdf = _bouw_pdf(
            beelddata=inhoud,
            filter_naam="DCTDecode",
            kleurruimte="DeviceRGB" if beeld.mode == "RGB" else "DeviceGray",
            breedte=breedte,
            hoogte=hoogte,
            rotatie=_ROTATIE[orientatie],
        )
    elif formaat in ("HEIF", "HEIC", "AVIF") and orientatie in _ROTATIE:
        # HEIC eerst naar JPEG (spec): één deterministische hercodering, oriëntatie via /Rotate.
        rgb = beeld.convert("RGB")
        buffer = io.BytesIO()
        rgb.save(buffer, format="JPEG", quality=_HEIC_JPEG_KWALITEIT, optimize=False, progressive=False)
        pdf = _bouw_pdf(
            beelddata=buffer.getvalue(),
            filter_naam="DCTDecode",
            kleurruimte="DeviceRGB",
            breedte=rgb.width,
            hoogte=rgb.height,
            rotatie=_ROTATIE[orientatie],
        )
    else:
        # Pixel-route (PNG, CMYK-JPEG, gespiegelde EXIF, palet/alfa): lossless Flate over RGB/grijs.
        recht = ImageOps.exif_transpose(beeld) or beeld
        vlak = _plat_op_wit(recht)
        kleurruimte = "DeviceGray" if vlak.mode == "L" else "DeviceRGB"
        pdf = _bouw_pdf(
            beelddata=zlib.compress(vlak.tobytes(), 9),
            filter_naam="FlateDecode",
            kleurruimte=kleurruimte,
            breedte=vlak.width,
            hoogte=vlak.height,
            rotatie=0,
        )
    return OmgezetteAfbeelding(
        pdf=pdf, pdf_bestandsnaam=pdf_bestandsnaam(bestandsnaam), breedte=breedte, hoogte=hoogte, bron_formaat=formaat
    )


def _exif_orientatie(beeld: Image.Image) -> int:
    try:
        waarde = beeld.getexif().get(0x0112)
    except Exception:  # noqa: BLE001 — kapotte EXIF is geen reden om de foto te weigeren
        return 1
    return int(waarde) if isinstance(waarde, int) and 1 <= waarde <= 8 else 1


def _plat_op_wit(beeld: Image.Image) -> Image.Image:
    if beeld.mode == "L":
        return beeld
    if beeld.mode in ("RGBA", "LA", "PA") or (beeld.mode == "P" and "transparency" in beeld.info):
        rgba = beeld.convert("RGBA")
        wit = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        return Image.alpha_composite(wit, rgba).convert("RGB")
    if beeld.mode == "1":
        return beeld.convert("L")
    return beeld.convert("RGB")


def _paginaformaat(breedte: int, hoogte: int, rotatie: int) -> tuple[float, float, float, float]:
    """(pagina_b, pagina_h, beeld_b, beeld_h) in punten: A4 in de stand van het (gedraaide)
    beeld, beeld passend geschaald zonder marge."""
    # De effectieve beeldverhouding zoals de kijker 'm ziet (na /Rotate).
    eff_b, eff_h = (hoogte, breedte) if rotatie in (90, 270) else (breedte, hoogte)
    liggend = eff_b > eff_h
    pagina_b, pagina_h = (_A4_STAAND[1], _A4_STAAND[0]) if liggend else _A4_STAAND
    # Op de (ongedraaide) pagina staat het beeld in zijn eigen pixelverhouding; de pagina zelf
    # wordt door /Rotate gedraaid — dus voor de schaal werken we in de ongedraaide ruimte.
    if rotatie in (90, 270):
        pagina_b, pagina_h = pagina_h, pagina_b
    schaal = min(pagina_b / breedte, pagina_h / hoogte)
    beeld_b, beeld_h = breedte * schaal, hoogte * schaal
    return pagina_b, pagina_h, beeld_b, beeld_h


def _bouw_pdf(
    *, beelddata: bytes, filter_naam: str, kleurruimte: str, breedte: int, hoogte: int, rotatie: int
) -> bytes:
    pagina_b, pagina_h, beeld_b, beeld_h = _paginaformaat(breedte, hoogte, rotatie)
    x = (pagina_b - beeld_b) / 2
    y = (pagina_h - beeld_h) / 2
    inhoud = f"q {beeld_b:.4f} 0 0 {beeld_h:.4f} {x:.4f} {y:.4f} cm /Im0 Do Q".encode("ascii")

    objecten = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        (
            f"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 {pagina_b:.3f} {pagina_h:.3f}] "
            f"/Rotate {rotatie} /Resources << /XObject << /Im0 4 0 R >> >> /Contents 5 0 R >>"
        ).encode("ascii"),
        (
            f"<< /Type /XObject /Subtype /Image /Width {breedte} /Height {hoogte} /ColorSpace /{kleurruimte} "
            f"/BitsPerComponent 8 /Filter /{filter_naam} /Length {len(beelddata)} >>"
        ).encode("ascii")
        + b"\nstream\n"
        + beelddata
        + b"\nendstream",
        f"<< /Length {len(inhoud)} >>".encode("ascii") + b"\nstream\n" + inhoud + b"\nendstream",
    ]

    uit = io.BytesIO()
    uit.write(b"%PDF-1.4\n%\xe2\xe3\xcf\xd3\n")
    offsets: list[int] = []
    for nummer, obj in enumerate(objecten, start=1):
        offsets.append(uit.tell())
        uit.write(f"{nummer} 0 obj\n".encode("ascii") + obj + b"\nendobj\n")
    xref_start = uit.tell()
    uit.write(f"xref\n0 {len(objecten) + 1}\n".encode("ascii"))
    uit.write(b"0000000000 65535 f \n")
    for offset in offsets:
        uit.write(f"{offset:010d} 00000 n \n".encode("ascii"))
    uit.write(f"trailer\n<< /Size {len(objecten) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n".encode("ascii"))
    return uit.getvalue()
