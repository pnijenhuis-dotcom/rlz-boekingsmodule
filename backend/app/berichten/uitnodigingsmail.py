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


def store_links() -> list[tuple[str, str]]:
    """(label, url) per platform, alleen gevulde links (blok F: leeg = niets tonen)."""
    uit: list[tuple[str, str]] = []
    if settings.store_link_ios.strip():
        uit.append(("iPhone/iPad (App Store)", settings.store_link_ios.strip()))
    if settings.store_link_android.strip():
        uit.append(("Android (Google Play)", settings.store_link_android.strip()))
    return uit


def download_blok() -> str:
    """Blok "Download eerst de app" voor app-rollen — lege string zolang er geen store-link gevuld is."""
    links = store_links()
    if not links:
        return ""
    regels = "\n".join(f"- {label}: {url}" for label, url in links)
    return f"Download eerst de app op je telefoon en open daarna de link hieronder:\n{regels}\n\n"


def verstuur_uitnodigingsmail(
    *, naam: str, e_mail: str, token: str, verloopt_op: datetime, app_rol: bool = False
) -> None:
    """Raise-t mail.MailFout bij niet-geconfigureerd/mislukt — de aanroeper maakt dat zichtbaar.
    `app_rol` (accordeur/veldrollen, blok F): mét gevulde store-links krijgt de mail het blok
    "Download eerst de app"; zonder links is de mail exact zoals voorheen."""
    link = activeerlink(token)
    tekst = (
        f"Beste {naam},\n\n"
        f"Er staat een account voor je klaar bij Administratiekantoor Nijenhuis.\n\n"
        f"{download_blok() if app_rol else ''}"
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


def verstuur_activatieprobleem_aan_kantoor(*, naam: str, e_mail: str) -> None:
    """Knop "Ik kom er niet uit — meld het kantoor" uit de mobiele activatieflow (28-08). Gaat
    naar het kantoor-antwoordadres (berichten_reply_to — de mens, niet het intake-postvak);
    ontbreekt dat of faalt de mail, dan blijft het audit-event op de gebruiker het spoor — de
    fout wordt gelogd, nooit aan de gebruiker getoond (die kan er niets aan doen)."""
    import logging

    logger = logging.getLogger(__name__)
    ontvanger = settings.berichten_reply_to
    if not ontvanger:
        logger.warning("Activatieprobleem gemeld door %s (%s) — geen kantoor-adres (BERICHTEN_REPLY_TO)", naam, e_mail)
        return
    tekst = (
        f"{naam} ({e_mail}) meldt vanuit de activatieflow van de app dat de passkey-registratie niet "
        f"lukt.\n\nEr is niets half geregistreerd: het account staat nog op 'uitgenodigd' en de "
        f"activatielink blijft geldig tot de vervaldatum. Neem contact op met de gebruiker; lukt het "
        f"daarna nog niet, stuur dan een nieuwe uitnodiging of herstel-link vanuit Gebruikers & toegang.\n\n"
        f"Administratiekantoor Nijenhuis — automatisch bericht"
    )
    try:
        mail.verzend_mail(naar=ontvanger, onderwerp=f"Activatie lukt niet — {naam}", tekst=tekst)
    except mail.MailFout:
        logger.exception("Activatieprobleem-mail aan het kantoor mislukt (%s)", e_mail)


def verstuur_app_lock_hulp_aan_kantoor(*, naam: str, e_mail: str) -> None:
    """Knop "Kantoor vragen om nieuwe link" ná de app-lock-uitsluiting (5× foute code, mockup
    app-lock-pincode.html scherm 6). Zelfde kanaal- en faalgedrag als het activatieprobleem:
    naar het kantoor-antwoordadres, fout gelogd, nooit aan de gebruiker getoond."""
    import logging

    logger = logging.getLogger(__name__)
    ontvanger = settings.berichten_reply_to
    if not ontvanger:
        logger.warning("App-lock-hulp gevraagd door %s (%s) — geen kantoor-adres (BERICHTEN_REPLY_TO)", naam, e_mail)
        return
    tekst = (
        f"{naam} ({e_mail}) heeft de toegangscode van de app 5 keer onjuist ingevoerd. Het toestel "
        f"is uit voorzorg uitgelogd en de toegang van dat apparaat is ingetrokken.\n\n"
        f"De gebruiker vraagt om een nieuwe activatielink. Stuur die vanuit Gebruikers & toegang "
        f"(Herstel-link of nieuwe uitnodiging) — daarna kiest de gebruiker opnieuw een code en "
        f"werkt alles zoals voorheen.\n\n"
        f"Administratiekantoor Nijenhuis — automatisch bericht"
    )
    try:
        mail.verzend_mail(naar=ontvanger, onderwerp=f"Nieuwe activatielink gevraagd — {naam}", tekst=tekst)
    except mail.MailFout:
        logger.exception("App-lock-hulpmail aan het kantoor mislukt (%s)", e_mail)
