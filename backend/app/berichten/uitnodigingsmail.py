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


def _versie_tuple(versie: str) -> tuple[int, ...]:
    delen: list[int] = []
    for deel in versie.strip().split("."):
        cijfers = "".join(ch for ch in deel if ch.isdigit())
        delen.append(int(cijfers) if cijfers else 0)
    return tuple(delen) or (0,)


def store_versie_geschikt(platform: str) -> bool:
    """Peter 16-09 (web vs app, blok C): de store-link hoort alleen in de mail als de GEPUBLICEERDE store-versie de
    app-auth zonder passkey draagt (≥ `store_min_appauth_versie`). iOS staat op 1.0 (goedgekeurd 09-09, 1.1 nog niet
    ingediend) → géén App Store-link maar de TestFlight-instructie; leeg = geen listing = niet geschikt."""
    versie = (settings.store_app_versie_ios if platform == "ios" else settings.store_app_versie_android).strip()
    if not versie:
        return False
    return _versie_tuple(versie) >= _versie_tuple(settings.store_min_appauth_versie)


def store_links(*, alleen_geschikt: bool = False) -> list[tuple[str, str]]:
    """(label, url) per platform, alleen gevulde links (blok F: leeg = niets tonen). `alleen_geschikt` (16-09): ook
    alleen de platformen waarvan de store-versie de app-auth draagt."""
    uit: list[tuple[str, str]] = []
    if settings.store_link_ios.strip() and (not alleen_geschikt or store_versie_geschikt("ios")):
        uit.append(("iPhone/iPad (App Store)", settings.store_link_ios.strip()))
    if settings.store_link_android.strip() and (not alleen_geschikt or store_versie_geschikt("android")):
        uit.append(("Android (Google Play)", settings.store_link_android.strip()))
    return uit


#: Terugval-instructie als er wél een store-listing is maar de store-versie de app-auth nog niet draagt (16-09).
TESTFLIGHT_INSTRUCTIE = (
    "De versie in de App Store / Google Play werkt nog met een wachtwoord en past niet bij deze uitnodiging. "
    "Installeer de app via TestFlight (iPhone/iPad) of de interne testversie in Google Play (Android) — vraag het "
    "kantoor om die uitnodiging als je 'm niet hebt."
)


def versie_eis() -> str:
    """Casus Romy 17-09 (herstel-link "landt op web"): de 1.0-app kent de app-auth niet en kan met deze link nooit
    inloggen — de mail zegt de versie-eis daarom letterlijk, mét de weg (updaten via de store)."""
    winkels = [label.split("(", 1)[1].rstrip(")") for label, _url in store_links(alleen_geschikt=True)]
    via = " of ".join(("de App Store" if w == "App Store" else w) for w in winkels) or "de app-winkel"
    return (
        f"Heb je de app al? Update 'm dan eerst via {via} — je hebt versie "
        f"{settings.store_min_appauth_versie} of hoger nodig; een oudere versie kent deze link niet."
    )


#: Android zonder geschikte Play-versie (SPOED 18-09, casus Edge-tablet): de web-versie op het beginscherm start
#: als een echte app, houdt de sessie vast en heeft geen browser-terugknop die de app verlaat.
ANDROID_WEB_INSTRUCTIE = (
    "Android zonder app in Google Play? Open de link in Chrome of Edge en zet de web-versie op je beginscherm "
    "(Chrome: menu ⋮ → 'Toevoegen aan startscherm'; Edge: menu ⋯ → 'Toevoegen aan telefoon') — dan blijft de app "
    "ingelogd en start hij als een echte app."
)


def _android_geschikt() -> bool:
    return any(label.startswith("Android") for label, _url in store_links(alleen_geschikt=True))


def android_web_regel() -> str:
    """Eén zin voor Android-gebruikers zolang er géén geschikte Play-versie is (18-09); lege string zodra die er is."""
    return "" if _android_geschikt() else ANDROID_WEB_INSTRUCTIE


def installatie_regels() -> str:
    """Stap 1 van de app-mail (16-09): geschikte store-links, anders de TestFlight-/interne-track-instructie, anders
    (geen enkele listing) de neutrale regel. Sinds 17-09 altijd mét de versie-eis (casus Romy); sinds 18-09 mét
    de Android-web-regel zolang er geen geschikte Play-versie is."""
    geschikt = store_links(alleen_geschikt=True)
    android = android_web_regel()
    if geschikt:
        return (
            "Download eerst de app op je telefoon — of update 'm als je 'm al hebt:\n"
            + "\n".join(f"   - {label}: {url}" for label, url in geschikt)
            + f"\n   {versie_eis()}"
            + (f"\n   {android}" if android else "")
        )
    if store_links():
        return f"Installeer de app op je telefoon. {TESTFLIGHT_INSTRUCTIE}" + (f" {android}" if android else "")
    basis = "Installeer de app op je telefoon (het kantoor stuurt je de installatielink)."
    return basis + (f" {android}" if android else "")


def download_blok() -> str:
    """Blok "Download eerst de app" (herstelmail) — lege string zolang er geen GESCHIKTE store-link is (16-09: een
    store-versie die de app-auth nog niet draagt krijgt de TestFlight-instructie in plaats van een misleidende link)."""
    links = store_links(alleen_geschikt=True)
    android = android_web_regel()
    if not links:
        if store_links():
            return f"{TESTFLIGHT_INSTRUCTIE}" + (f" {android}" if android else "") + "\n\n"
        return f"{android}\n\n" if android else ""
    regels = "\n".join(f"- {label}: {url}" for label, url in links)
    return (
        f"Download eerst de app op je telefoon en open daarna de link hieronder:\n{regels}\n"
        + (f"{android}\n" if android else "")
        + "\n"
    )


def app_activatie_stappen(*, link: str, verloopt_op: datetime, activatiecode: str | None, herstel: bool = False) -> str:
    """Uitnodigingsmail voor app-rollen (Peter 16-09, blok C): ÉÉN genummerde volgorde — 1 installeer/update de app (alleen
    een store-link als die versie geschikt is; versie-eis letterlijk), 2 open déze link op je telefoon, 3 kies een
    toegangscode; activatiecode als terugval eronder; plus wat te doen als de link tóch op een computer opende (er wordt
    niets vastgelegd tot een keuze) en hoe je later een tweede toestel koppelt (zelfservice, blok B). `herstel` (17-09,
    casus Romy): de herstel-link volgt exact dezelfde volgorde — stap 2 koppelt het toestel opnieuw, stap 3 is een
    nieuwe toegangscode."""
    geldig = verloopt_op.astimezone().strftime("%d-%m-%Y %H:%M")
    kop = "Zo koppel je de app opnieuw, in deze volgorde:" if herstel else "Zo activeer je de app, in deze volgorde:"
    stap2 = (
        "2. Open déze link op je telefoon — niet op een computer en niet in een browser als je de app hebt; de link "
        f"koppelt {'opnieuw ' if herstel else ''}het toestel waarop je hem opent (eenmalig, geldig tot {geldig}):\n   {link}\n"
    )
    stap3 = "3. Kies in de app een nieuwe toegangscode van 5 cijfers.\n\n" if herstel else "3. Kies in de app een toegangscode van 5 cijfers.\n\n"
    return (
        f"{kop}\n\n"
        f"1. {installatie_regels()}\n"
        f"{stap2}"
        f"{stap3}"
        f"{activatiecode_blok(activatiecode, app_rol=True)}"
        "Opende je de link per ongeluk op een computer of in een browser? Kies daar 'In de app op deze telefoon' of 'Open "
        "op je telefoon' — er wordt niets vastgelegd tot je een keuze maakt. Wil je de app later óók op een ander toestel "
        "gebruiken: in de app onder Toegang › 'Telefoon/app koppelen'.\n\n"
    )


def activatiecode_blok(activatiecode: str | None, *, app_rol: bool) -> str:
    """App-auth zonder passkey (besluit Peter 08-09): het codeblok voor externe app-rollen — voor wie de
    link niet kan openen of op een ander toestel activeert. Zelfde geldigheid als de link. Kantoor-rollen
    (geen code) en ontbrekende code = lege string, de mail is dan exact zoals voorheen."""
    if not app_rol or not activatiecode:
        return ""
    return (
        f"Kun je de link niet openen (of activeer je op een ander toestel)? Voer dan in de app deze "
        f"activatiecode in: {activatiecode} (zelfde geldigheid).\n\n"
    )


def verstuur_uitnodigingsmail(
    *,
    naam: str,
    e_mail: str,
    token: str,
    verloopt_op: datetime,
    app_rol: bool = False,
    activatiecode: str | None = None,
) -> None:
    """Raise-t mail.MailFout bij niet-geconfigureerd/mislukt — de aanroeper maakt dat zichtbaar.
    `app_rol` (accordeur/veldrollen, blok F): mét gevulde store-links krijgt de mail het blok
    "Download eerst de app"; zonder links is de mail exact zoals voorheen. `activatiecode` (08-09): het
    codeblok "Activatiecode: XXXX-XXXX" voor app-rollen."""
    link = activeerlink(token)
    if app_rol:
        # 16-09: app-rollen krijgen de genummerde volgorde (installeren → link op je telefoon → toegangscode).
        kern = app_activatie_stappen(link=link, verloopt_op=verloopt_op, activatiecode=activatiecode)
    else:
        kern = (
            f"Activeer je account via deze link (eenmalig, geldig tot "
            f"{verloopt_op.astimezone().strftime('%d-%m-%Y %H:%M')}):\n{link}\n\n"
        )
    tekst = (
        f"Beste {naam},\n\n"
        f"Er staat een account voor je klaar bij Administratiekantoor Nijenhuis.\n\n"
        f"{kern}"
        f"Werkt de link niet meer? Vraag dan een nieuwe uitnodiging aan bij het kantoor.\n\n"
        f"Administratiekantoor Nijenhuis"
    )
    mail.verzend_mail(naar=e_mail, onderwerp="Je account bij Administratiekantoor Nijenhuis", tekst=tekst)


def herstellink(token: str) -> str:
    """Zelfde /activeren-route als de uitnodiging (het token bepaalt server-side de soort);
    `herstel=1` is uitsluitend presentatie — het scherm zegt dan 'Toestel opnieuw koppelen'
    i.p.v. 'Account activeren'."""
    return f"{activeerlink(token)}&herstel=1"


def verstuur_herstelmail(
    *, naam: str, e_mail: str, token: str, verloopt_op: datetime, activatiecode: str | None = None
) -> None:
    """Herstel-link voor een actieve externe app-gebruiker (feedbackronde 25-08 punt 7; herzien 08-09 naar het
    toestel-model: geen wachtwoord meer — de link/code koppelt een (nieuw) toestel, de gebruiker kiest daarna
    opnieuw een toegangscode; alle oude sessies vervallen). Herstel-links bestaan alleen voor app-rollen, dus
    het codeblok staat er altijd zodra er een code is. Raise-t mail.MailFout bij niet-geconfigureerd/mislukt."""
    link = herstellink(token)
    # 17-09 (casus Romy): dezelfde genummerde volgorde als de uitnodiging — installeer/update (versie-eis) → link op je
    # telefoon → nieuwe toegangscode — i.p.v. een los downloadblok boven een kale link.
    tekst = (
        f"Beste {naam},\n\n"
        f"Het kantoor heeft een herstel-link voor je aangemaakt zodat je de app opnieuw kunt koppelen aan je "
        f"account bij Administratiekantoor Nijenhuis.\n\n"
        f"{app_activatie_stappen(link=link, verloopt_op=verloopt_op, activatiecode=activatiecode, herstel=True)}"
        f"Je bestaande instellingen blijven bewaard; eerdere toestellen worden uitgelogd.\n\n"
        f"Heb je hier niet om gevraagd? Neem dan contact op met het kantoor — de link vervalt "
        f"vanzelf.\n\n"
        f"Administratiekantoor Nijenhuis"
    )
    mail.verzend_mail(naar=e_mail, onderwerp="App opnieuw koppelen — Administratiekantoor Nijenhuis", tekst=tekst)


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
        f"{naam} ({e_mail}) meldt vanuit de activatieflow van de app dat de activatie niet lukt.\n\n"
        f"Er is niets half geregistreerd: het account staat nog op 'uitgenodigd' en de activatielink/"
        f"activatiecode blijft geldig tot de vervaldatum. Neem contact op met de gebruiker; lukt het "
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
        f"De gebruiker vraagt om een nieuwe uitnodiging. Stuur die vanuit Gebruikers & toegang "
        f"(Herstel-link of nieuwe uitnodiging; de mail bevat link én activatiecode) — daarna activeert de "
        f"gebruiker het toestel opnieuw, kiest een nieuwe toegangscode en werkt alles zoals voorheen.\n\n"
        f"Administratiekantoor Nijenhuis — automatisch bericht"
    )
    try:
        mail.verzend_mail(naar=ontvanger, onderwerp=f"Nieuwe activatielink gevraagd — {naam}", tekst=tekst)
    except mail.MailFout:
        logger.exception("App-lock-hulpmail aan het kantoor mislukt (%s)", e_mail)
