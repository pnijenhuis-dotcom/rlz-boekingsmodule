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
