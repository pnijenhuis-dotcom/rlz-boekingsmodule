"""Content-type uit de bestandsnaam — één plek (feedbackronde 25-08 deel 3 punt 2). Tot dan
gold overal "pdf, anders xml"; sinds afbeeldingen als brondocument bewaard kunnen worden
(onbruikbare afbeelding in de verzamelbak, origineel naast de omgezette PDF) moet een
opgeslagen .jpg/.png/.heic óók als zodanig geserveerd worden."""

from __future__ import annotations

from pathlib import Path

_CONTENT_TYPES = {
    ".pdf": "application/pdf",
    ".xml": "application/xml",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".png": "image/png",
    ".heic": "image/heic",
    ".heif": "image/heif",
    ".eml": "message/rfc822",
}


def content_type_voor(bestandsnaam: str) -> str:
    return _CONTENT_TYPES.get(Path(bestandsnaam).suffix.lower(), "application/octet-stream")
