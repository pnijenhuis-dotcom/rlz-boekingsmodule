"""Intake-seam: "haal nieuwe berichten uit het centrale postvak".

Het contract is bewust minimaal en payload-gedreven (zelfde ontwerplijn als de
extractie-wachtrij): een bron levert ruwe .eml-bytes, de verwerking (app/intake/verwerking.py)
doet al het domeinwerk — zo is de fixture-/uploadvariant vandaag exact dezelfde codepad als de
live IMAP-fetch straks.

LIVE-FETCH-SEAM (gemarkeerd, wacht op de GCP-uitrol): `ImapPostvakBron` is een stub die pas
werkt zodra de intake_imap_*-settings gevuld zijn én de implementatie bij de Cloud
Scheduler-koppeling geactiveerd wordt. Tot die tijd is de .eml-upload (endpoint
POST /intake/eml — een doorgestuurde mail als bestand) het intake-kanaal; het CLI-commando
`intake-postvak-verwerken` meldt dan expliciet dat de seam nog niet actief is — geen stille
no-op."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Protocol

from app.config import settings


class PostvakBron(Protocol):
    """Levert ruwe .eml-berichten (bytes) op; de aanroeper parseert en verwerkt ze."""

    def nieuwe_berichten(self) -> Iterator[bytes]: ...


class PostvakNietGeconfigureerd(Exception):
    """De live-fetch-seam is nog niet geactiveerd (GCP-uitrol) of niet geconfigureerd."""


class ImapPostvakBron:
    """SEAM-STUB: de live IMAP-koppeling op het centrale adres (mockup Instellingen →
    E-mail intake). Wordt geactiveerd bij de GCP-uitrol (Cloud Scheduler-job → dit commando);
    de settings bestaan al zodat de configuratie-vorm vastligt."""

    def nieuwe_berichten(self) -> Iterator[bytes]:
        if not settings.intake_imap_host:
            raise PostvakNietGeconfigureerd(
                "Live postvak-fetch is nog niet geconfigureerd (intake_imap_host ontbreekt) — "
                "gebruik tot de GCP-uitrol de .eml-upload (POST /intake/eml)."
            )
        raise PostvakNietGeconfigureerd(
            "Live IMAP-fetch is een bewuste seam die bij de GCP-uitrol wordt geactiveerd "
            "(Cloud Scheduler + mail-infra) — zie docs/BESLISSINGEN.md e-mail-intake."
        )
