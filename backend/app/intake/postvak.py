"""Intake-bron: "haal nieuwe berichten uit het centrale postvak".

Het contract is bewust minimaal en payload-gedreven (zelfde ontwerplijn als de
extractie-wachtrij): een bron levert ruwe .eml-bytes, de verwerking (app/intake/verwerking.py)
doet al het domeinwerk — de .eml-upload (POST /intake/eml) en de live IMAP-fetch zijn exact
hetzelfde codepad.

LIVE IMAP-FETCH (F3.4, geactiveerd 2026-08-15): `ImapPostvakBron` leest het centrale
intake-adres (facturen@ak-nijenhuis.nl, Google Workspace — IMAP SSL 993, app-wachtwoord via
Secret Manager `INTAKE_IMAP_WACHTWOORD`). Ongelezen berichten zijn de werkvoorraad van het
postvak; een bericht wordt pas als gelezen gemarkeerd NADAT de aanroeper het verwerkt heeft
(generator hervat) — crasht de verwerking, dan blijft het bericht ongelezen en pakt de
volgende run het opnieuw op (verwerk_eml is idempotent op Message-ID, dus nooit dubbel).
Zolang de settings leeg zijn (lokale dev) meldt het CLI-commando `intake-postvak-verwerken`
expliciet dat de bron niet geconfigureerd is — geen stille no-op."""

from __future__ import annotations

import imaplib
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import dataclass
from typing import Protocol

from app.config import settings

# Intake-kanalen (blok 3 bundel 08-09): 'facturen' = het bestaande postvak (settings.intake_imap_*), 'declaraties' = het
# tweede postvak (settings.intake_declaraties_imap_*). Bron van de kanaalnamen: app/documenten/betaalstatus.py::KANALEN.
KANAAL_FACTUREN = "facturen"
KANAAL_DECLARATIES = "declaraties"
_SETTINGS_PREFIX_PER_KANAAL = {KANAAL_FACTUREN: "intake_imap", KANAAL_DECLARATIES: "intake_declaraties_imap"}


@dataclass(frozen=True)
class ImapInstellingen:
    kanaal: str
    host: str | None
    poort: int
    gebruiker: str | None
    wachtwoord: str | None
    env_prefix: str  # voor de foutmelding: welke envs/secret op de job horen te staan

    @classmethod
    def voor_kanaal(cls, kanaal: str) -> ImapInstellingen:
        if kanaal not in _SETTINGS_PREFIX_PER_KANAAL:
            raise ValueError(f"Onbekend intake-kanaal {kanaal!r} — kies {' of '.join(_SETTINGS_PREFIX_PER_KANAAL)}")
        prefix = _SETTINGS_PREFIX_PER_KANAAL[kanaal]
        return cls(
            kanaal=kanaal,
            host=getattr(settings, f"{prefix}_host"),
            poort=getattr(settings, f"{prefix}_poort"),
            gebruiker=getattr(settings, f"{prefix}_gebruiker"),
            wachtwoord=getattr(settings, f"{prefix}_wachtwoord"),
            env_prefix=prefix.upper(),
        )

    def ontbrekend(self) -> list[str]:
        return [
            f"{self.env_prefix.lower()}_{naam}"
            for naam, waarde in (("host", self.host), ("gebruiker", self.gebruiker), ("wachtwoord", self.wachtwoord))
            if not waarde
        ]


class PostvakBron(Protocol):
    """Levert ruwe .eml-berichten (bytes) op; de aanroeper parseert en verwerkt ze."""

    def nieuwe_berichten(self) -> Iterator[bytes]: ...


class PostvakNietGeconfigureerd(Exception):
    """De IMAP-bron mist configuratie (intake_imap_*-settings) — lokale dev of een
    onvolledige activatie; de .eml-upload (POST /intake/eml) blijft dan het kanaal."""


class PostvakFout(Exception):
    """Verbinding/login/protocol-fout tegen de IMAP-server — zichtbare fout (exit 1 in de
    job → Cloud Monitoring-alert), nooit stil."""


def _fetch_inhoud(delen: list) -> bytes | None:
    """imaplib geeft een FETCH-respons als mix van tuples en losse bytes terug; de ruwe
    berichtinhoud is het tweede element van de tuple-delen."""
    for deel in delen:
        if isinstance(deel, tuple) and len(deel) >= 2 and isinstance(deel[1], (bytes, bytearray)):
            return bytes(deel[1])
    return None


class ImapPostvakBron:
    """Live IMAP-koppeling op het centrale intake-adres (mockup Instellingen → E-mail intake).

    Leesvolgorde per run: SELECT INBOX → UID SEARCH UNSEEN → per bericht BODY.PEEK[] (peek:
    het ophalen zelf zet géén gelezen-vlag) → yield → ná verwerking door de aanroeper
    (generator hervat) UID STORE +FLAGS \\Seen. Het postvak is een dedicated app-mailbox;
    de gelezen-vlag is dáár de "verwerkt door de intake"-administratie."""

    def __init__(self, kanaal: str = KANAAL_FACTUREN) -> None:
        # Blok 3 bundel 08-09: één bron-klasse voor beide postvakken; de instellingen worden pas bij het lezen opgehaald
        # (tests monkeypatchen `settings` ná constructie — zelfde gedrag als vóór de kanaal-parameter).
        self.kanaal = kanaal

    def nieuwe_berichten(self) -> Iterator[bytes]:
        instellingen = ImapInstellingen.voor_kanaal(self.kanaal)
        ontbrekend = instellingen.ontbrekend()
        if ontbrekend:
            raise PostvakNietGeconfigureerd(
                f"Live postvak-fetch ({self.kanaal}) is niet geconfigureerd ({', '.join(ontbrekend)} ontbreekt) — "
                "lokaal is de .eml-upload (POST /intake/eml) het kanaal; in de cloud horen de "
                f"{instellingen.env_prefix}_*-envs + het secret {instellingen.env_prefix}_WACHTWOORD "
                "op de job te staan."
            )
        try:
            verbinding = imaplib.IMAP4_SSL(instellingen.host, instellingen.poort)
        except OSError as exc:
            raise PostvakFout(
                f"Geen verbinding met IMAP-server {instellingen.host}:{instellingen.poort}: {exc}"
            ) from exc
        try:
            try:
                verbinding.login(instellingen.gebruiker, instellingen.wachtwoord)
            except imaplib.IMAP4.error as exc:
                raise PostvakFout(
                    f"IMAP-login geweigerd voor {instellingen.gebruiker} — controleer het "
                    f"app-wachtwoord (secret {instellingen.env_prefix}_WACHTWOORD): {exc}"
                ) from exc
            status, _ = verbinding.select("INBOX")
            if status != "OK":
                raise PostvakFout("IMAP SELECT INBOX mislukt")
            status, zoekresultaat = verbinding.uid("SEARCH", None, "UNSEEN")
            if status != "OK":
                raise PostvakFout("IMAP SEARCH UNSEEN mislukt")
            uids = zoekresultaat[0].split() if zoekresultaat and zoekresultaat[0] else []
            for uid in uids:
                status, delen = verbinding.uid("FETCH", uid, "(BODY.PEEK[])")
                if status != "OK":
                    raise PostvakFout(f"IMAP FETCH van bericht uid={uid.decode()} mislukt")
                inhoud = _fetch_inhoud(delen)
                if inhoud is None:
                    raise PostvakFout(f"IMAP FETCH uid={uid.decode()} leverde geen berichtinhoud")
                yield inhoud
                # De aanroeper is klaar met dit bericht (zonder exception hervat) — nu pas de
                # gelezen-vlag; bij een crash blijft het bericht UNSEEN en is de volgende run
                # de retry (verwerk_eml is idempotent op Message-ID).
                verbinding.uid("STORE", uid, "+FLAGS", "(\\Seen)")
        finally:
            with suppress(Exception):
                verbinding.logout()
