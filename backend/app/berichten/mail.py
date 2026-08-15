"""Gedeeld uitgaand mailkanaal (berichten-bouwsteen, 2026-08-15).

Eén verzendpad voor álle app-mail (uitnodigingen, accordeur-herinneringen, latere afnemers) via
de bestaande Google Workspace: SMTP over SSL met een app-wachtwoord (zelfde provider-lijn als de
IMAP-intake — DPA rond 2026-08-15). Bewust géén externe maildienst: geen extra verwerker.

Fail-zichtbaar (opdracht-eis): niet geconfigureerd of verzending mislukt = een expliciete
exception die de aanroeper toont/logt — mail verdwijnt nooit stil. Geen retry-lus hier; de
aanroeper bepaalt wat falen betekent (uitnodiging: link blijft handmatig deelbaar; herinnering:
rij op 'mislukt', volgende job-run probeert opnieuw, F3.2-alert bijt via exit 1)."""

from __future__ import annotations

import smtplib
from email.message import EmailMessage
from email.utils import formataddr

from app.config import settings


class MailFout(Exception):
    """Basisfout van het mailkanaal."""


class MailNietGeconfigureerd(MailFout):
    """SMTP-instellingen ontbreken (lokale dev of nog geen secret) — zichtbaar melden."""


class MailVerzendFout(MailFout):
    """De SMTP-verzending zelf faalde (verbinding, auth, geweigerde ontvanger)."""


def is_geconfigureerd() -> bool:
    return bool(
        settings.berichten_smtp_host
        and settings.berichten_smtp_gebruiker
        and settings.berichten_smtp_wachtwoord
    )


def _afzender() -> str:
    adres = settings.berichten_afzender or settings.berichten_smtp_gebruiker or ""
    return formataddr((settings.berichten_afzender_naam, adres))


def bouw_bericht(*, naar: str, onderwerp: str, tekst: str) -> EmailMessage:
    """Plain-text mail (bewust: geen HTML-sjablonen — de inhoud is kort en functioneel, en
    plain text rendert overal, incl. strenge zakelijke mailclients)."""
    bericht = EmailMessage()
    bericht["From"] = _afzender()
    bericht["To"] = naar
    bericht["Subject"] = onderwerp
    bericht.set_content(tekst)
    return bericht


def verzend_mail(*, naar: str, onderwerp: str, tekst: str) -> None:
    """Verzend één mail, synchroon. Raise-t altijd expliciet bij falen — nooit stil."""
    if not is_geconfigureerd():
        raise MailNietGeconfigureerd(
            "Mailkanaal niet geconfigureerd (BERICHTEN_SMTP_HOST/-GEBRUIKER/-WACHTWOORD ontbreekt)."
        )
    bericht = bouw_bericht(naar=naar, onderwerp=onderwerp, tekst=tekst)
    try:
        with smtplib.SMTP_SSL(settings.berichten_smtp_host, settings.berichten_smtp_poort, timeout=30) as smtp:
            smtp.login(settings.berichten_smtp_gebruiker, settings.berichten_smtp_wachtwoord)
            smtp.send_message(bericht)
    except (OSError, smtplib.SMTPException) as exc:
        raise MailVerzendFout(f"Mail aan {naar} niet verzonden: {exc}") from exc
