"""Deterministische .eml-parsing (stdlib `email`) — de fixture-/upload-variant van de
intake-seam: een doorgestuurde of geëxporteerde mail (.eml) wordt exact zo verwerkt als de
latere live IMAP-fetch (app/intake/postvak.py) berichten zal aanleveren."""

from __future__ import annotations

import email
import email.policy
import email.utils
from dataclasses import dataclass, field
from datetime import datetime

# Bijlage-typen die de intake verwerkt; al het andere wordt zichtbaar geregistreerd als
# "niet verwerkbaar" in het intake-bericht (nooit stil genegeerd).
_PDF_TYPES = {"application/pdf"}
_XML_TYPES = {"application/xml", "text/xml"}


@dataclass(frozen=True)
class IntakeBijlage:
    bestandsnaam: str
    inhoud: bytes
    content_type: str

    @property
    def is_pdf(self) -> bool:
        return self.content_type in _PDF_TYPES or self.bestandsnaam.lower().endswith(".pdf")

    @property
    def is_xml(self) -> bool:
        return self.content_type in _XML_TYPES or self.bestandsnaam.lower().endswith(".xml")


@dataclass(frozen=True)
class IntakeMail:
    message_id: str | None
    afzender: str | None
    onderwerp: str | None
    ontvangen_op: datetime | None
    bijlagen: list[IntakeBijlage] = field(default_factory=list)


class GeenGeldigeEml(Exception):
    """De inhoud is geen parsebaar e-mailbericht."""


def parse_eml(inhoud: bytes) -> IntakeMail:
    try:
        bericht = email.message_from_bytes(inhoud, policy=email.policy.default)
    except Exception as exc:  # noqa: BLE001 — stdlib gooit uiteenlopende parse-fouten
        raise GeenGeldigeEml(f"Kan e-mailbericht niet parsen: {exc}") from exc
    if not bericht.keys():
        raise GeenGeldigeEml("Geen e-mailheaders gevonden — is dit wel een .eml-bestand?")

    afzender_naam, afzender_adres = email.utils.parseaddr(str(bericht.get("From", "")))
    ontvangen_op: datetime | None = None
    datum_header = bericht.get("Date")
    if datum_header:
        try:
            ontvangen_op = email.utils.parsedate_to_datetime(str(datum_header))
        except (TypeError, ValueError):
            ontvangen_op = None

    bijlagen: list[IntakeBijlage] = []
    for deel in bericht.walk():
        if deel.get_content_maintype() == "multipart":
            continue
        bestandsnaam = deel.get_filename()
        if not bestandsnaam:
            continue  # body-tekst; alleen benoemde bijlagen zijn documenten
        payload = deel.get_payload(decode=True)
        if not payload:
            continue
        bijlagen.append(
            IntakeBijlage(
                bestandsnaam=bestandsnaam,
                inhoud=payload,
                content_type=deel.get_content_type(),
            )
        )

    message_id = bericht.get("Message-ID")
    return IntakeMail(
        message_id=str(message_id).strip() if message_id else None,
        afzender=afzender_adres or afzender_naam or None,
        onderwerp=str(bericht.get("Subject")) if bericht.get("Subject") else None,
        ontvangen_op=ontvangen_op,
        bijlagen=bijlagen,
    )
