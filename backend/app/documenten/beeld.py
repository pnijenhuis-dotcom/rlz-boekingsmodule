"""Het BEELD van een document — wat een mens moet zien en wat als PDF-bijlage naar RLZ gaat (blok A2
02-09, casus RLZ-export-UBL's: de factuur-PDF zit ín de UBL als EmbeddedDocumentBinaryObject).

Eén bron voor drie afnemers (verzamelbak-preview, controlescherm-bijlage, `zorg_voor_bijlage` bij het
boeken), in deze volgorde:
1. bron-kolommen (`document.bron_*`) mét PDF naast een UBL-hoofdbestand → die PDF (bundeling/samenvoegen
   02-09, `beeld_is_bron`);
2. UBL-hoofdbestand zonder bron-PDF maar mét ingesloten PDF → de ingesloten PDF
   (`documenten/ubl.py::lees_ingesloten_pdf`; rijen van vóór migratie 0098 of andere ingangen);
3. anders het hoofdbestand zelf (PDF, of een UBL zonder beeld — bestaand gedrag: samenvatting/paar).

Puur en deterministisch: geen DB-schrijfactie, geen AI. Wie het beeld wil PERSISTEREN (bron-kolommen
vullen) doet dat expliciet — zie `intake/herlezen.py` (nazorg) en de bundeling bij de intake."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol

from app.documenten.mime import content_type_voor
from app.documenten.storage import DocumentOpslag
from app.documenten.ubl import lees_ingesloten_pdf


class DocumentBestanden(Protocol):
    """De vijf bestandskolommen van `Document` — een ORM-object óf een losse snapshot
    (`BestandenSnapshot`) voor aanroepers die het beeld buiten de DB-transactie bepalen."""

    bestandsnaam: str
    opslag_pad: str
    bron_opslag_pad: str | None
    bron_bestandsnaam: str | None
    bron_content_type: str | None


@dataclass(frozen=True)
class BestandenSnapshot:
    bestandsnaam: str
    opslag_pad: str
    bron_opslag_pad: str | None = None
    bron_bestandsnaam: str | None = None
    bron_content_type: str | None = None

    @classmethod
    def van(cls, document: DocumentBestanden) -> BestandenSnapshot:
        return cls(
            bestandsnaam=document.bestandsnaam,
            opslag_pad=document.opslag_pad,
            bron_opslag_pad=document.bron_opslag_pad,
            bron_bestandsnaam=document.bron_bestandsnaam,
            bron_content_type=document.bron_content_type,
        )


_UBL_SUFFIX = ".xml"

HERKOMST_BRON = "bron"
HERKOMST_INGESLOTEN = "ingesloten_pdf"
HERKOMST_HOOFDBESTAND = "hoofdbestand"


@dataclass(frozen=True)
class Beeld:
    inhoud: bytes
    bestandsnaam: str
    content_type: str
    #: HERKOMST_BRON | HERKOMST_INGESLOTEN | HERKOMST_HOOFDBESTAND
    herkomst: str

    @property
    def is_pdf(self) -> bool:
        return self.content_type.lower() == "application/pdf"


def beeld_is_bron(document: DocumentBestanden) -> bool:
    """Gebundeld UBL+PDF-document (bundeling/samenvoegen 02-09): het opgeslagen bestand is de UBL
    (data), het beeld is de PDF in de bron-kolommen."""
    return (
        document.bron_opslag_pad is not None
        and (document.bron_content_type or "").lower() == "application/pdf"
        and document.bestandsnaam.lower().endswith(_UBL_SUFFIX)
    )


def bepaal_beeld(document: DocumentBestanden, *, opslag: DocumentOpslag, hoofdinhoud: bytes | None = None) -> Beeld:
    """Zie module-docstring. `hoofdinhoud` mag worden meegegeven als de aanroeper het hoofdbestand al
    gelezen heeft (voorkomt een tweede opslag-lees)."""
    if beeld_is_bron(document):
        assert document.bron_opslag_pad is not None
        return Beeld(
            inhoud=opslag.lezen(pad=document.bron_opslag_pad),
            bestandsnaam=document.bron_bestandsnaam or "beeld.pdf",
            content_type=document.bron_content_type or "application/pdf",
            herkomst=HERKOMST_BRON,
        )
    inhoud = hoofdinhoud if hoofdinhoud is not None else opslag.lezen(pad=document.opslag_pad)
    if document.bestandsnaam.lower().endswith(_UBL_SUFFIX):
        ingesloten = lees_ingesloten_pdf(inhoud)
        if ingesloten is not None:
            return Beeld(
                inhoud=ingesloten.inhoud,
                bestandsnaam=ingesloten.bestandsnaam,
                content_type="application/pdf",
                herkomst=HERKOMST_INGESLOTEN,
            )
    return Beeld(
        inhoud=inhoud,
        bestandsnaam=document.bestandsnaam,
        content_type=content_type_voor(document.bestandsnaam),
        herkomst=HERKOMST_HOOFDBESTAND,
    )
