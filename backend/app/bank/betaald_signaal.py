"""Al-betaald-signaal bij boeken (besluit Peter 25-08, RLZ-feedbackronde deel 2 punt 1).

Zodra crediteur + totaalbedrag van een inkoopfactuur bekend zijn toetst het controlescherm de
ONafgeletterde bankmutaties van de administratie uit de LOKALE bank-cache (`bank_mutatie`,
geen live RLZ-call): bedrag incl. btw exact gelijk (afschrijving = −totaal) is de basis;
factuurnummer in omschrijving/naam en de crediteurnaam versterken de match. Uitkomst =
zichtbaar SIGNAAL "Waarschijnlijk al betaald — datum, rekening, bedrag" mét matchreden;
nooit blokkerend. Ná het boeken pakt de bestaande afletter-matching (app/bank/matchmotor.py,
zelfde normalisatie) de mutatie op zoals nu.

Bewust buiten scope (parkeerpost, BESLISSINGEN deel 2 punt 1): G-rekening-/deelbetaling-
combinaties waarbij de SOM van meerdere mutaties het factuurbedrag vormt.
"""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal

from sqlalchemy import select

from app.bank.matchmotor import referentie_komt_voor
from app.bank.models import BankMutatie, PaymentAccountCache
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentSoort
from app.sync.models import VendorCache

_MAX_TREFFERS = 5
_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-zà-ÿ]+")
# Rechtsvorm-/vulwoorden tellen niet als naamherkenning ("B.V." staat op elke tweede mutatie).
_RUIS_TOKENS = frozenset({"bv", "b", "v", "nv", "vof", "cv", "de", "het", "en", "van", "der", "den", "the"})


@dataclass(frozen=True)
class AlBetaaldTreffer:
    mutatie_id: uuid.UUID
    boekdatum: date
    bedrag: Decimal
    rekening_naam: str | None
    rekening_iban: str | None
    tegenpartij_naam: str | None
    omschrijving: str | None
    redenen: tuple[str, ...]

    @property
    def sterkte(self) -> int:
        return len(self.redenen)


def _naam_tokens(naam: str | None) -> set[str]:
    if not naam:
        return set()
    return {t for t in _NIET_ALFANUMERIEK.split(naam.lower()) if len(t) >= 3 and t not in _RUIS_TOKENS}


def naam_herkend(vendor_naam: str | None, *teksten: str | None) -> bool:
    """Crediteurnaam-herkenning: minimaal één betekenisvol token (≥ 3 tekens, geen rechtsvorm/
    vulwoord) van de crediteurnaam komt voor in de tegenpartijnaam of omschrijving."""
    tokens = _naam_tokens(vendor_naam)
    if not tokens:
        return False
    doel = " ".join(_NIET_ALFANUMERIEK.sub(" ", (t or "").lower()) for t in teksten)
    doel_tokens = set(doel.split())
    return any(t in doel_tokens for t in tokens)


def zoek_al_betaald(
    *,
    administratie_id: uuid.UUID,
    totaalbedrag: Decimal,
    referentie: str | None,
    vendor_naam: str | None,
) -> list[AlBetaaldTreffer]:
    """Onafgeletterde mutaties (open_bedrag ≠ 0 — nooit op IsComplete toetsen, die is stale na
    storno) met bedrag exact −totaal; gesorteerd op matchsterkte (meer redenen eerst), dan
    nieuwste eerst. Puur lezen uit de lokale cache."""
    with scoped_session(administratie_id) as session:
        mutaties = session.scalars(
            select(BankMutatie).where(
                BankMutatie.administratie_id == administratie_id,
                BankMutatie.open_bedrag.is_not(None),
                BankMutatie.open_bedrag != 0,
                BankMutatie.bedrag == -totaalbedrag,
                BankMutatie.verdwenen_uit_bron_op.is_(None),
            )
        ).all()
        rekeningen = {
            r.id: r
            for r in session.scalars(
                select(PaymentAccountCache).where(PaymentAccountCache.administratie_id == administratie_id)
            )
        }
        treffers: list[AlBetaaldTreffer] = []
        for m in mutaties:
            redenen = ["bedrag incl. btw exact gelijk"]
            if referentie and referentie_komt_voor(referentie, m.tegenpartij_naam, m.omschrijving):
                redenen.append("factuurnummer in omschrijving")
            if naam_herkend(vendor_naam, m.tegenpartij_naam, m.omschrijving):
                redenen.append("crediteurnaam herkend")
            rekening = rekeningen.get(m.payment_account_id)
            treffers.append(
                AlBetaaldTreffer(
                    mutatie_id=m.id,
                    boekdatum=m.boekdatum,
                    bedrag=m.bedrag,
                    rekening_naam=rekening.naam if rekening else None,
                    rekening_iban=rekening.iban if rekening else None,
                    tegenpartij_naam=m.tegenpartij_naam,
                    omschrijving=m.omschrijving,
                    redenen=tuple(redenen),
                )
            )
    treffers.sort(key=lambda t: (-t.sterkte, t.boekdatum), reverse=False)
    # Zelfde sterkte: nieuwste eerst.
    treffers.sort(key=lambda t: (-t.sterkte, -t.boekdatum.toordinal()))
    return treffers[:_MAX_TREFFERS]


@dataclass(frozen=True)
class AlBetaaldSignaal:
    toetsbaar: bool
    treffers: list[AlBetaaldTreffer]


def signaal_voor_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> AlBetaaldSignaal:
    """Glue voor het controlescherm: leest crediteur/referentie/totaal uit het (opgeslagen of
    geëxtraheerde) boekvoorstel; niet toetsbaar zolang crediteur of totaal ontbreekt of het
    geen inkoopfactuur is. Read-only — geen audit, geen status."""
    from app.documenten.boekvoorstel import haal_boekvoorstel_op  # lokaal: boekvoorstel is zwaar

    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return AlBetaaldSignaal(toetsbaar=False, treffers=[])
    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    if voorstel.vendor_id is None or voorstel.totaalbedrag is None or voorstel.totaalbedrag == 0:
        return AlBetaaldSignaal(toetsbaar=False, treffers=[])
    with scoped_session(administratie_id) as session:
        vendor = session.get(VendorCache, (voorstel.vendor_id, administratie_id))
        vendor_naam = vendor.naam if vendor else None
    return AlBetaaldSignaal(
        toetsbaar=True,
        treffers=zoek_al_betaald(
            administratie_id=administratie_id,
            totaalbedrag=voorstel.totaalbedrag,
            referentie=voorstel.referentie,
            vendor_naam=vendor_naam,
        ),
    )
