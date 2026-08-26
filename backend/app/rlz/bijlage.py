"""Herstart-veilige PDF-bijlage-upload voor álle boekmotoren (inkoop, verkoop/omzet,
memoriaal, doorbelasting-spiegel).

Geverifieerde RLZ-semantiek (STAP-0 "Uploads bij een herstart-boekcyclus", 2026-08-16,
verkenning/api-verkenning.md — aanleiding: kliktest 2 van TEST-ONB-KLIKTEST-01 faalde per
doelentiteit op de bijlage-upload):

- `/Uploads` kent GÉÉN overschrijven: een her-PUT op een bestaand upload-GUID geeft
  `400 _InvalidData`, en een GUID dat in een eerdere boekcyclus verbruikt is op een intussen
  (in de RLZ-UI) verwijderd document geeft `404 _NotFound`. De oude aanname "een retry
  overschrijft (PUT) dezelfde bijlage" was fout.
- Bijlagen overleven boeken (17), storno (19) én een her-PUT van het document zelf
  (die vervangt alleen de DocumentLineList).
- De leesroute `GET .../Uploads` werkt op PurchaseInvoices, SalesInvoices en ManualJournals,
  in concept- én geboekte staat, en is dus bruikbaar als aanwezigheids-check.

Idempotentie komt hier daarom uit de LEESROUTE (bijlage al aanwezig = klaar — dekt zowel de
crash-retry ná een geslaagde upload als de herstart op een storno-concept), niet uit
PUT-overschrijven. Het deterministische upload-GUID uit rlz_ids blijft de eerste kandidaat;
is dat GUID verbruikt (document van een eerdere cyclus verwijderd), dan volgt een
deterministisch cyclus-GUID (uuid5 op het basis-GUID) — begrensd, nooit een stil verlies
van de bijlage."""

from __future__ import annotations

import logging
import uuid

from app.rlz.client import RlzApiError, RlzClient

logger = logging.getLogger(__name__)

# Eén cyclus-GUID per herstart waarin het document opnieuw is aangemaakt — meer dan een
# paar cycli betekent iets structureels; dan hoort de laatste RLZ-fout zichtbaar te worden.
MAX_UPLOAD_CYCLI = 5


def cyclus_upload_id(basis: uuid.UUID, cyclus: int) -> uuid.UUID:
    """Deterministische opvolger van een verbruikt upload-GUID: cyclus 0 = het basis-GUID
    zelf (rlz_ids), elke volgende herstart-cyclus een uuid5 óver dat basis-GUID — dezelfde
    herstart raakt dus altijd dezelfde kandidatenreeks (retry-idempotent)."""
    if cyclus == 0:
        return basis
    return uuid.uuid5(basis, f"upload-cyclus:{cyclus}")


def zorg_voor_bijlage(
    client: RlzClient,
    entity_path: str,
    entity_id: uuid.UUID,
    *,
    upload_id: uuid.UUID,
    filename: str,
    content_base64: str,
    op_bestandsnaam: bool = False,
) -> bool:
    """Zorgt dat het document deze bijlage draagt. Retourneert True als er geüpload is, False
    als de bijlage er al stond (herstart op een storno-concept / crash-retry).

    Default (`op_bestandsnaam=False`, alle enkel-bijlage-motoren): "er staat al íets" = klaar.
    `op_bestandsnaam=True` (doorbelasting sinds blok A 26-08: factuur-PDF náást de originele
    bon, meerdere bijlagen per document — RLZ staat dat toe, STAP-0 16-08 punt 4): alleen een
    bestaande upload met dezelfde `FileName` telt als aanwezig, andere bijlagen blokkeren niet.

    Is de Uploads-lijst onverhoopt onleesbaar, dan valt de check open naar het oude gedrag
    (gewoon uploaden) — een dubbele bijlage is cosmetisch, een boeking die strandt op een
    leesprobleem niet. Een verbruikt GUID (400/404) schuift door naar het volgende
    cyclus-GUID; elke andere fout blijft gewoon zichtbaar falen."""
    try:
        respons = client.get(f"{entity_path}/{entity_id}/Uploads")
        bestaande = respons.get("value", []) if isinstance(respons, dict) else respons
        if op_bestandsnaam:
            if any((u or {}).get("FileName") == filename for u in bestaande):
                return False
        elif bestaande:
            return False
    except RlzApiError as exc:
        logger.warning(
            "Uploads-lijst van %s/%s onleesbaar (%s) — upload zonder aanwezigheids-check",
            entity_path,
            entity_id,
            exc.status_code,
        )

    laatste: RlzApiError | None = None
    for cyclus in range(MAX_UPLOAD_CYCLI):
        kandidaat = cyclus_upload_id(upload_id, cyclus)
        try:
            client.upload_bijlage(
                entity_path, entity_id, upload_id=kandidaat, filename=filename, content_base64=content_base64
            )
            return True
        except RlzApiError as exc:
            if exc.status_code not in (400, 404):
                raise
            laatste = exc
            logger.warning(
                "Upload-GUID %s (cyclus %s) onbruikbaar op %s/%s (%s) — volgende cyclus-GUID",
                kandidaat,
                cyclus,
                entity_path,
                entity_id,
                exc.status_code,
            )
    assert laatste is not None
    raise laatste
