"""PDF-metadata voor de klein-vs-groot-routing (async extractie, 2026-07-10).

pypdf i.p.v. een regex op de ruwe bytes: moderne PDF's (1.5+) verstoppen page-objecten in
gecomprimeerde object streams, waardoor tekstueel zoeken naar "/Type /Page" structureel
ondertelt. Een mislukte telling is géén fout — de routing valt dan terug op bestandsgrootte."""

from __future__ import annotations

import io
import logging

from pypdf import PdfReader

logger = logging.getLogger(__name__)


def tel_paginas(inhoud: bytes) -> int | None:
    """Aantal pagina's van een PDF, of None als het document niet (als PDF) te lezen is."""
    try:
        return len(PdfReader(io.BytesIO(inhoud)).pages)
    except Exception:  # noqa: BLE001 — bewust breed: een corrupte PDF mag de upload niet laten falen
        logger.warning("Kon pagina-aantal niet bepalen — routing valt terug op bestandsgrootte", exc_info=True)
        return None
