"""Uitnodigingsmail (eerste kantoor-afnemer van het gedeelde mailkanaal, BOUWPLAN-punt
"E-mailverzending van uitnodigingen").

De activeerlink is exact de bestaande linkvorm ({app_basis_url}/activeren?token=...) — het
plaintext-token verlaat de server alleen via deze mail en de API-respons aan de Beheerder
(de handmatig-delen-terugval blijft bestaan: mail niet geconfigureerd of mislukt = zichtbare
fout in de respons, de Beheerder deelt de link dan zelf — nooit een stil verdwenen uitnodiging)."""

from __future__ import annotations

from datetime import datetime

from app.berichten import mail
from app.config import settings


def activeerlink(token: str) -> str:
    return f"{settings.app_basis_url.rstrip('/')}/activeren?token={token}"


def verstuur_uitnodigingsmail(*, naam: str, e_mail: str, token: str, verloopt_op: datetime) -> None:
    """Raise-t mail.MailFout bij niet-geconfigureerd/mislukt — de aanroeper maakt dat zichtbaar."""
    link = activeerlink(token)
    tekst = (
        f"Beste {naam},\n\n"
        f"Er staat een account voor je klaar bij Administratiekantoor Nijenhuis.\n\n"
        f"Activeer je account via deze link (eenmalig, geldig tot "
        f"{verloopt_op.astimezone().strftime('%d-%m-%Y %H:%M')}):\n{link}\n\n"
        f"Werkt de link niet meer? Vraag dan een nieuwe uitnodiging aan bij het kantoor.\n\n"
        f"Administratiekantoor Nijenhuis"
    )
    mail.verzend_mail(naar=e_mail, onderwerp="Je account bij Administratiekantoor Nijenhuis", tekst=tekst)


def herstellink(token: str) -> str:
    """Zelfde /activeren-route als de uitnodiging (het token bepaalt server-side de soort);
    `herstel=1` is uitsluitend presentatie — het scherm zegt dan 'Nieuw wachtwoord instellen'
    i.p.v. 'Account activeren'."""
    return f"{activeerlink(token)}&herstel=1"


def verstuur_herstelmail(*, naam: str, e_mail: str, token: str, verloopt_op: datetime) -> None:
    """Wachtwoord-herstel voor een actieve externe gebruiker (feedbackronde 25-08 punt 7).
    Raise-t mail.MailFout bij niet-geconfigureerd/mislukt — de aanroeper maakt dat zichtbaar."""
    link = herstellink(token)
    tekst = (
        f"Beste {naam},\n\n"
        f"Het kantoor heeft een herstel-link voor je aangemaakt zodat je een nieuw wachtwoord kunt "
        f"instellen voor je account bij Administratiekantoor Nijenhuis.\n\n"
        f"Stel je nieuwe wachtwoord in via deze link (eenmalig, geldig tot "
        f"{verloopt_op.astimezone().strftime('%d-%m-%Y %H:%M')}):\n{link}\n\n"
        f"Daarna registreer je je apparaat opnieuw. Je bestaande instellingen blijven bewaard.\n\n"
        f"Heb je hier niet om gevraagd? Neem dan contact op met het kantoor — de link vervalt "
        f"vanzelf.\n\n"
        f"Administratiekantoor Nijenhuis"
    )
    mail.verzend_mail(naar=e_mail, onderwerp="Nieuw wachtwoord instellen — Administratiekantoor Nijenhuis", tekst=tekst)
