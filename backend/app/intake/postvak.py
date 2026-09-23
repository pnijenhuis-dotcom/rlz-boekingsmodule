"""Intake-bron: "haal berichten uit een intake-postvak".

Het contract is bewust minimaal en payload-gedreven (zelfde ontwerplijn als de extractie-wachtrij): een bron levert
ruwe .eml-bytes, de verwerking (app/intake/verwerking.py) doet al het domeinwerk — de .eml-upload (POST /intake/eml)
en de live IMAP-fetch zijn exact hetzelfde codepad.

LIVE IMAP-FETCH (F3.4, geactiveerd 2026-08-15) — HERZIEN 23-09 (Peter 22-09 "er zijn facturen gemaild die niet in
onze module staan"; BESLISSINGEN "INTAKE — TWEEDE POSTVAK KEMPENGROEP DIRECT + MESSAGE-ID-ADMINISTRATIE +
POSTVAKBEWAKING (Peter 22-09)"):
- tot 23-09 was de werkvoorraad `UID SEARCH UNSEEN` in INBOX en de gelezen-vlag de verwerkt-administratie. Dat verloor
  drie klassen berichten: wat een mens al gelezen had vóór de intake liep, wat in Spam landde (SPF-breuk door de
  Gmail-forward vanaf facturen@kempengroep.nl) en wat Gmail zelf niet doorstuurde.
- sinds 23-09 leest `ImapPostvakBron` ALLE berichten (gelezen én ongelezen) van de laatste
  `settings.intake_postvak_venster_dagen` dagen in INBOX én de spam-map, haalt eerst alleen de kop (Message-ID) op en
  verwerkt wat nog niet in `intake_bericht_verwerkt`/`intake_bericht` staat (`app/intake/verwerkt.py`). De gelezen-vlag
  wordt ná verwerking nog wél gezet, maar alleen als bijproduct (mensen in de mailbox zien dan wat de module had).
- kanalen: 'facturen' (facturen@ak-nijenhuis.nl), 'declaraties' (declaraties@) en 'facturen_kempengroep'
  (facturen@kempengroep.nl DIRECT, geen forward meer — settings `intake_kempengroep_imap_*`).
Zolang de settings leeg zijn (lokale dev) meldt het CLI-commando `intake-postvak-verwerken` expliciet dat de bron
niet geconfigureerd is — geen stille no-op."""

from __future__ import annotations

import email
import email.policy
import email.utils
import imaplib
import re
from collections.abc import Callable, Iterator
from contextlib import suppress
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Protocol

from app.config import settings
from app.tijd import vandaag_nl
from app.documenten.betaalstatus import (
    KANAAL_DECLARATIES,
    KANAAL_FACTUREN,
    KANAAL_FACTUREN_KEMPENGROEP,
    KANALEN,
    POSTVAK_ADRES_PER_KANAAL,
)

__all__ = [
    "KANAAL_DECLARATIES",
    "KANAAL_FACTUREN",
    "KANAAL_FACTUREN_KEMPENGROEP",
    "KANALEN",
    "KANALEN_MET_JOB",
    "POSTVAK_ADRES_PER_KANAAL",
    "ImapInstellingen",
    "ImapPostvakBron",
    "PostvakBericht",
    "PostvakBron",
    "PostvakFout",
    "PostvakKop",
    "PostvakNietGeconfigureerd",
    "PostvakVerbinding",
    "sleutel_voor",
]

# Bron van de kanaalnamen: app/documenten/betaalstatus.py::KANALEN. Settings-prefix per kanaal.
_SETTINGS_PREFIX_PER_KANAAL = {
    KANAAL_FACTUREN: "intake_imap",
    KANAAL_DECLARATIES: "intake_declaraties_imap",
    KANAAL_FACTUREN_KEMPENGROEP: "intake_kempengroep_imap",
}
#: Kanalen mét een Cloud Run-job in deploy.yml (rlz-intake-imap, rlz-intake-imap-kempengroep). Voor déze kanalen is
#: "niet geconfigureerd" op de reconciliatie-job een FOUT (nooit stil); declaraties@ heeft (nog) geen job en wordt
#: zichtbaar overgeslagen.
KANALEN_MET_JOB: tuple[str, ...] = (KANAAL_FACTUREN, KANAAL_FACTUREN_KEMPENGROEP)
INBOX = "INBOX"
_HEADER_VELDEN = "(FLAGS BODY.PEEK[HEADER.FIELDS (MESSAGE-ID FROM SUBJECT DATE REFERENCES IN-REPLY-TO)])"
_FLAGS = re.compile(rb"FLAGS \(([^)]*)\)")
_UID = re.compile(rb"UID (\d+)")
_MAANDEN = ("Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec")


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

    @property
    def geconfigureerd(self) -> bool:
        return not self.ontbrekend()


@dataclass(frozen=True)
class PostvakKop:
    """Kop van één bericht in het postvak (zonder body): genoeg voor de verwerkt-toets en de bewaking."""

    uid: str
    map: str
    message_id: str | None
    afzender: str | None
    onderwerp: str | None
    datum: datetime | None
    gelezen: bool
    references: tuple[str, ...] = ()

    @property
    def sleutel(self) -> str:
        return sleutel_voor(self.message_id, map=self.map, uid=self.uid)

    @property
    def uit_spam(self) -> bool:
        return self.map != INBOX


@dataclass(frozen=True)
class PostvakBericht:
    """Eén opgehaald bericht: kop + ruwe .eml-bytes. `sleutel` = Message-ID, anders `uid:<map>:<uid>`."""

    kop: PostvakKop
    inhoud: bytes

    @property
    def sleutel(self) -> str:
        return self.kop.sleutel

    @property
    def uit_spam(self) -> bool:
        return self.kop.uit_spam


def sleutel_voor(message_id: str | None, *, map: str, uid: str) -> str:
    """Verwerkt-sleutel: de Message-ID (RFC 5322) als die er is; anders een surrogaat op map + uid (stabiel binnen
    één mailbox — UIDVALIDITY-wissels zijn zeldzaam en leiden hoogstens tot één AL-VERWERKT via verwerk_eml)."""
    mid = (message_id or "").strip()
    return mid if mid else f"uid:{map}:{uid}"


class PostvakBron(Protocol):
    """Levert berichten op; de aanroeper parseert en verwerkt ze."""

    def nieuwe_berichten(self) -> Iterator[PostvakBericht]: ...


class PostvakNietGeconfigureerd(Exception):
    """De IMAP-bron mist configuratie (intake_*_imap-settings) — lokale dev of een onvolledige activatie; de .eml-upload
    (POST /intake/eml) blijft dan het kanaal."""


class PostvakFout(Exception):
    """Verbinding/login/protocol-fout tegen de IMAP-server — zichtbare fout (exit 1 in de job → Cloud Monitoring-alert;
    FOUT-bevinding in het reconciliatieblok `intake`), nooit stil."""


def _fetch_delen(delen: list) -> list[tuple[bytes, bytes]]:
    """imaplib geeft een FETCH-respons als mix van tuples en losse bytes terug; de tuple-delen dragen
    (kopregel, inhoud) — bij een multi-uid FETCH één tuple per bericht."""
    uit: list[tuple[bytes, bytes]] = []
    for deel in delen:
        if isinstance(deel, tuple) and len(deel) >= 2 and isinstance(deel[1], (bytes, bytearray)):
            uit.append((bytes(deel[0]), bytes(deel[1])))
    return uit


def _fetch_inhoud(delen: list) -> bytes | None:
    paren = _fetch_delen(delen)
    return paren[0][1] if paren else None


def imap_datum(d: date) -> str:
    """IMAP SEARCH SINCE-notatie (RFC 3501): dd-Mon-yyyy, Engelse maandafkorting, locale-onafhankelijk."""
    return f"{d.day:02d}-{_MAANDEN[d.month - 1]}-{d.year}"


def _kop_uit_header(uid: str, map: str, kopregel: bytes, header: bytes) -> PostvakKop:
    bericht = email.message_from_bytes(header, policy=email.policy.default)
    flags = _FLAGS.search(kopregel)
    gelezen = b"\\Seen" in (flags.group(1) if flags else b"")
    datum: datetime | None = None
    if bericht.get("Date"):
        with suppress(TypeError, ValueError):
            datum = email.utils.parsedate_to_datetime(str(bericht.get("Date")))
    _, adres = email.utils.parseaddr(str(bericht.get("From", "")))
    refs = " ".join(str(bericht.get(h) or "") for h in ("References", "In-Reply-To"))
    references = tuple(dict.fromkeys(r.strip() for r in refs.split() if r.strip()))
    mid = bericht.get("Message-ID")
    return PostvakKop(
        uid=uid,
        map=map,
        message_id=str(mid).strip() if mid else None,
        afzender=adres or None,
        onderwerp=str(bericht.get("Subject")) if bericht.get("Subject") else None,
        datum=datum,
        gelezen=gelezen,
        references=references,
    )


class PostvakVerbinding:
    """Dunne, expliciete laag om imaplib voor één kanaal: verbinden/inloggen (fouten leesbaar), mappen kiezen, koppen
    lezen (BODY.PEEK — zet nooit een vlag), één bericht ophalen, gelezen-vlag zetten. Gedeeld door de fetch, het
    reconciliatieblok `intake` (telling) en de lees-only audit-CLI (`intake-postvak-audit`)."""

    def __init__(self, instellingen: ImapInstellingen) -> None:
        self.instellingen = instellingen
        self._imap: imaplib.IMAP4_SSL | None = None
        self._map: str | None = None

    # -- levenscyclus ------------------------------------------------------------------------------------------------
    def __enter__(self) -> PostvakVerbinding:
        self.verbind()
        return self

    def __exit__(self, *exc: object) -> None:
        self.sluit()

    def verbind(self) -> None:
        i = self.instellingen
        ontbrekend = i.ontbrekend()
        if ontbrekend:
            raise PostvakNietGeconfigureerd(
                f"Live postvak-fetch ({i.kanaal}) is niet geconfigureerd ({', '.join(ontbrekend)} ontbreekt) — "
                "lokaal is de .eml-upload (POST /intake/eml) het kanaal; in de cloud horen de "
                f"{i.env_prefix}_*-envs + het secret {i.env_prefix}_WACHTWOORD op de job te staan."
            )
        try:
            self._imap = imaplib.IMAP4_SSL(i.host, i.poort)
        except OSError as exc:
            raise PostvakFout(f"Geen verbinding met IMAP-server {i.host}:{i.poort}: {exc}") from exc
        try:
            self._imap.login(i.gebruiker, i.wachtwoord)
        except imaplib.IMAP4.error as exc:
            self.sluit()
            raise PostvakFout(
                f"IMAP-login geweigerd voor {i.gebruiker} — controleer het app-wachtwoord "
                f"(secret {i.env_prefix}_WACHTWOORD): {exc}"
            ) from exc

    def sluit(self) -> None:
        if self._imap is not None:
            with suppress(Exception):
                self._imap.logout()
            self._imap = None
            self._map = None

    @property
    def _verbinding(self) -> imaplib.IMAP4_SSL:
        if self._imap is None:
            raise PostvakFout("IMAP-verbinding is niet geopend")
        return self._imap

    # -- mappen ------------------------------------------------------------------------------------------------------
    @staticmethod
    def standaard_mappen() -> tuple[str, ...]:
        """INBOX + de spam-map (Gmail: `[Gmail]/Spam`). De audit leest daarnaast `[Gmail]/All Mail`."""
        return (INBOX, settings.intake_imap_spam_map)

    def kies_map(self, map: str) -> int:
        """SELECT (schrijfbaar, voor de gelezen-vlag); geeft het aantal berichten terug. Een map die niet bestaat is
        een PostvakFout — een spam-map die stil ontbreekt zou precies het gat van vóór 23-09 terugbrengen."""
        if self._map == map:
            return -1
        status, data = self._verbinding.select(self._quote(map))
        if status != "OK":
            raise PostvakFout(f"IMAP SELECT {map} mislukt ({(data or [b''])[0]!r})")
        self._map = map
        with suppress(Exception):
            return int(data[0])
        return -1

    @staticmethod
    def _quote(map: str) -> str:
        return f'"{map}"' if " " in map or "[" in map else map

    # -- lezen -------------------------------------------------------------------------------------------------------
    def koppen(self, map: str, *, sinds: date | None, alleen_ongelezen: bool = False) -> list[PostvakKop]:
        """Koppen van alle berichten in `map` vanaf `sinds` (IMAP SINCE = interne datum, dag-granulariteit), gelezen én
        ongelezen. BODY.PEEK: het lezen zelf zet géén vlag."""
        self.kies_map(map)
        criteria: list[str] = []
        if sinds is not None:
            criteria += ["SINCE", imap_datum(sinds)]
        if alleen_ongelezen:
            criteria.append("UNSEEN")
        if not criteria:
            criteria = ["ALL"]
        status, zoekresultaat = self._verbinding.uid("SEARCH", None, *criteria)
        if status != "OK":
            raise PostvakFout(f"IMAP SEARCH {' '.join(criteria)} in {map} mislukt")
        uids = zoekresultaat[0].split() if zoekresultaat and zoekresultaat[0] else []
        koppen: list[PostvakKop] = []
        for uid in uids:
            status, delen = self._verbinding.uid("FETCH", uid, _HEADER_VELDEN)
            if status != "OK":
                raise PostvakFout(f"IMAP FETCH kop van bericht uid={uid.decode()} in {map} mislukt")
            paren = _fetch_delen(delen)
            if not paren:
                raise PostvakFout(f"IMAP FETCH kop uid={uid.decode()} in {map} leverde geen header")
            koppen.append(_kop_uit_header(uid.decode(), map, paren[0][0], paren[0][1]))
        return koppen

    def bericht(self, kop: PostvakKop) -> bytes:
        self.kies_map(kop.map)
        status, delen = self._verbinding.uid("FETCH", kop.uid.encode(), "(BODY.PEEK[])")
        if status != "OK":
            raise PostvakFout(f"IMAP FETCH van bericht uid={kop.uid} in {kop.map} mislukt")
        inhoud = _fetch_inhoud(delen)
        if inhoud is None:
            raise PostvakFout(f"IMAP FETCH uid={kop.uid} in {kop.map} leverde geen berichtinhoud")
        return inhoud

    def markeer_gelezen(self, kop: PostvakKop) -> None:
        """Bijproduct sinds 23-09: de gelezen-vlag is geen administratie meer, wél handig voor wie de mailbox opent.
        Een STORE-fout is geen reden om de verwerking te laten falen (het bericht staat al in de verwerkt-tabel)."""
        with suppress(Exception):
            self.kies_map(kop.map)
            self._verbinding.uid("STORE", kop.uid.encode(), "+FLAGS", "(\\Seen)")


@dataclass
class FetchTelling:
    """Wat de bron in één run zag — voedt het audit `intake_postvak_run` (dagtellers in de reconciliatiemail)."""

    gezien: int = 0
    gezien_spam: int = 0
    overgeslagen_bekend: int = 0
    opgehaald: int = 0
    per_map: dict[str, int] = field(default_factory=dict)


class ImapPostvakBron:
    """Live IMAP-koppeling op een intake-postvak (mockup Instellingen → E-mail intake).

    Leesvolgorde per run (sinds 23-09): per map (INBOX, spam-map) → UID SEARCH SINCE <venster> (ALL, dus óók gelezen)
    → per bericht de KOP (Message-ID) via BODY.PEEK → staat de sleutel al in de verwerkt-administratie (`bekend`)?
    dan overslaan → anders BODY.PEEK[] → yield → ná verwerking door de aanroeper (generator hervat) de gelezen-vlag als
    bijproduct. Crasht de verwerking, dan staat het bericht niet in de verwerkt-tabel en pakt de volgende run het
    opnieuw op (verwerk_eml is idempotent op Message-ID, dus nooit dubbel)."""

    def __init__(
        self,
        kanaal: str = KANAAL_FACTUREN,
        *,
        bekend: Callable[[str], bool] | None = None,
        sinds: date | None = None,
    ) -> None:
        # Eén bron-klasse voor alle postvakken; de instellingen worden pas bij het lezen opgehaald (tests
        # monkeypatchen `settings` ná constructie). `bekend(sleutel)` = staat dit bericht al in de
        # verwerkt-administratie (default: app/intake/verwerkt.py); `sinds` = begin van het leesvenster
        # (default: vandaag − intake_postvak_venster_dagen).
        self.kanaal = kanaal
        self._bekend = bekend
        self._sinds = sinds
        self.telling = FetchTelling()

    def venster_vanaf(self) -> date:
        if self._sinds is not None:
            return self._sinds
        # NL-kalenderdag (app/tijd.py, guard test_kalenderdag_guard) — een UTC-datum verschuift ná 22:00 naar gisteren.
        return vandaag_nl() - timedelta(days=max(0, int(settings.intake_postvak_venster_dagen)))

    def _is_bekend(self) -> Callable[[str], bool]:
        if self._bekend is not None:
            return self._bekend
        from app.intake import verwerkt

        return verwerkt.bekend_toets(self.kanaal)

    def nieuwe_berichten(self) -> Iterator[PostvakBericht]:
        instellingen = ImapInstellingen.voor_kanaal(self.kanaal)
        verbinding = PostvakVerbinding(instellingen)
        verbinding.verbind()  # PostvakNietGeconfigureerd / PostvakFout — vóór de eerste yield, dus zichtbaar in de CLI
        bekend = self._is_bekend()
        sinds = self.venster_vanaf()
        try:
            for map in PostvakVerbinding.standaard_mappen():
                koppen = verbinding.koppen(map, sinds=sinds)
                self.telling.per_map[map] = len(koppen)
                self.telling.gezien += len(koppen)
                if map != INBOX:
                    self.telling.gezien_spam += len(koppen)
                for kop in koppen:
                    if bekend(kop.sleutel):
                        self.telling.overgeslagen_bekend += 1
                        continue
                    inhoud = verbinding.bericht(kop)
                    self.telling.opgehaald += 1
                    yield PostvakBericht(kop=kop, inhoud=inhoud)
                    # De aanroeper is klaar met dit bericht (zonder exception hervat): gelezen-vlag als bijproduct.
                    verbinding.markeer_gelezen(kop)
        finally:
            verbinding.sluit()
