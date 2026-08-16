"""Btw-aangifte-poort vóór élk storno-pad (besluit Peter 2026-08-15, vervangt de eerder
geparkeerde pre-storno-waarschuwing als hard vangnet).

Waarom: RLZ's API weigert actie 19 níét in een periode waarvan de btw-aangifte al is
ingediend — hij verschuift de terugdraai-btw stil als negatieve TaxSource naar de
eerstvolgende open aangifte-periode (api-verkenning "Actie 19 in een periode met ingediende
btw-aangifte"). Dat is een ongewild suppletie-effect; de RLZ-UI beschermt hier wél, dus onze
app blokkeert de storno en verwijst naar handmatige verwerking (tegenboeking). Het
tegenboek-pad + suppletie-signaal zelf blijven geparkeerd voor een eigen ontwerp-/UX-ronde.

Leesroute (live geverifieerd 2026-08-16, poc_herput_en_aangiftepoort.py `aangifte`):
`GET TaxDeclarations` per administratie; Status 1 = concept, 2 = ingediend, 3 = afgehandeld;
`StartDate`/`Date` = periodegrenzen. Geblokkeerd is een document waarvan de boekdatum
(document-`Date`, dáár hangt RLZ de TaxSource-periode aan) in een Status-2/3-periode valt.

Fail-closed: is de aangifte-status of het document niet leesbaar, dan blokkeert de storno
óók — nooit gokken met een ingediende aangifte. Uitzonderingen die de poort bewust vrijgeeft:
een 404 op het document (niets geboekt = geen btw-effect; het storno-pad zelf behandelt een
404 al als "al weg") en Status 1 (concept — de btw is al teruggedraaid of nooit ontstaan).

BEWUST NIET gepoort: de interne rollback-storno's ín een boek-transactie (omzetmotor,
doorbelastingsmotor: spiegel/memoriaal faalt → storno van de zojuist geboekte verkoop).
Die storno volgt seconden na het boeken; boek- én storno-TaxSource verschuiven dan identiek
(netto nul in dezelfde open periode) en een blokkade zou precies het half-geboekt-scenario
creëren dat de één-transactie-garantie voorkomt."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date

from app.rlz.client import RlzApiError, RlzClient

logger = logging.getLogger(__name__)

STORNO_BLOKKADE_MELDING = (
    "BTW-aangifte over deze periode is definitief ingediend — "
    "wijzigingen handmatig verwerken (tegenboeking)"
)

# RLZ TaxDeclarations-statusmodel (live geverifieerd 2026-08-16): 2 = ingediend, 3 = afgehandeld.
_INGEDIENDE_STATUSSEN = (2, 3)
# Documentstatus 2/3 = geboekt (open/gesloten) — alleen dán heeft een storno btw-effect.
_GEBOEKTE_STATUSSEN = (2, 3)


@dataclass(frozen=True)
class KantToets:
    """Uitkomst per kant (bron-verkoop, doel-spiegel, bankboeking, …) — de UI toont per kant
    zichtbaar waarom een storno geblokkeerd is (opdracht: alles-of-niets, per kant zichtbaar)."""

    kant: str
    toegestaan: bool
    reden: str | None = None
    periode_start: date | None = None
    periode_eind: date | None = None


class StornoGeblokkeerdDoorAangifte(Exception):
    """Minstens één kant valt in een ingediende aangifte-periode (of was niet leesbaar —
    fail-closed). `kanten` draagt álle toetsen zodat de melding per kant kan verklaren."""

    def __init__(self, kanten: list[KantToets]) -> None:
        self.kanten = kanten
        super().__init__(STORNO_BLOKKADE_MELDING)

    def detail_tekst(self) -> str:
        """Mens-leesbare 409-detail: de vaste melding + per geblokkeerde kant waarom."""
        redenen = [f"{t.kant}: {t.reden}" for t in self.kanten if not t.toegestaan and t.reden]
        if not redenen:
            return STORNO_BLOKKADE_MELDING
        return f"{STORNO_BLOKKADE_MELDING}. " + " · ".join(redenen)


def _parse_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


class AangiftePoort:
    """Toetst documenten van één RLZ-administratie tegen haar ingediende btw-aangiften.
    Leest TaxDeclarations lazy en éénmaal per instantie (één poort per administratie per
    request); elke leesfout wordt een fail-closed blokkade, nooit een exception die het
    lees-scherm sloopt."""

    def __init__(self, client: RlzClient) -> None:
        self._client = client
        self._periodes: list[tuple[date, date]] | None = None
        self._leesfout: str | None = None

    def _ingediende_periodes(self) -> list[tuple[date, date]] | None:
        """None = niet leesbaar (fail-closed; reden in self._leesfout)."""
        if self._periodes is not None or self._leesfout is not None:
            return self._periodes
        try:
            rijen = self._client.list_tax_declarations()
        except RlzApiError as exc:
            logger.warning("TaxDeclarations niet leesbaar voor de aangifte-poort: %s", exc)
            self._leesfout = f"btw-aangifte-status niet leesbaar ({exc.status_code})"
            return None
        periodes: list[tuple[date, date]] = []
        for rij in rijen:
            if rij.get("Status") not in _INGEDIENDE_STATUSSEN:
                continue
            start = _parse_datum(rij.get("StartDate"))
            eind = _parse_datum(rij.get("Date"))
            if start is None or eind is None:
                # Een ingediende aangifte zonder leesbare periode kán elke datum dekken.
                self._leesfout = "ingediende btw-aangifte zonder leesbare periode"
                return None
            periodes.append((start, eind))
        self._periodes = periodes
        return periodes

    def toets_boekdatum(self, datum: date, *, kant: str) -> KantToets:
        periodes = self._ingediende_periodes()
        if periodes is None:
            return KantToets(kant=kant, toegestaan=False, reden=f"{self._leesfout} — storno uit voorzorg geblokkeerd")
        for start, eind in periodes:
            if start <= datum <= eind:
                return KantToets(
                    kant=kant,
                    toegestaan=False,
                    reden=(
                        f"boekdatum {datum.isoformat()} valt in de ingediende btw-aangifte "
                        f"{start.isoformat()} t/m {eind.isoformat()}"
                    ),
                    periode_start=start,
                    periode_eind=eind,
                )
        return KantToets(kant=kant, toegestaan=True)

    def toets_document(self, ophalen: Callable[[], dict], *, kant: str) -> KantToets:
        """Haalt het RLZ-document vers op (`ophalen` mag RlzApiError gooien) en toetst de
        boekdatum. 404 en concept (Status 1) zijn vrij; al het onleesbare is fail-closed."""
        try:
            document = ophalen()
        except RlzApiError as exc:
            if exc.status_code == 404:
                return KantToets(kant=kant, toegestaan=True)
            return KantToets(
                kant=kant,
                toegestaan=False,
                reden=f"document niet leesbaar ({exc.status_code}) — storno uit voorzorg geblokkeerd",
            )
        if document.get("Status") not in _GEBOEKTE_STATUSSEN:
            return KantToets(kant=kant, toegestaan=True)
        datum = _parse_datum(document.get("Date"))
        if datum is None:
            return KantToets(
                kant=kant,
                toegestaan=False,
                reden="boekdatum van het document niet leesbaar — storno uit voorzorg geblokkeerd",
            )
        return self.toets_boekdatum(datum, kant=kant)


def blokkeer_bij_ingediende_aangifte(toetsen: list[KantToets]) -> None:
    """Alles-of-niets (opdracht): één geblokkeerde kant blokkeert de hele storno-set — vóór
    de eerste RLZ-write, zodat er nooit half teruggedraaid wordt om aangifte-redenen."""
    if any(not toets.toegestaan for toets in toetsen):
        raise StornoGeblokkeerdDoorAangifte(toetsen)
