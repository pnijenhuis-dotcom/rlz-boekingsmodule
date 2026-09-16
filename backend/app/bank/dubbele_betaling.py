"""Dubbele betaling signaleren (blok C, opdracht Peter 16-09; casus Kempen Facilities → Hello Kitchen Duiven:
€ 12.600,00 én € 16.250,00 elk tweemaal betaald omdat twee facturen dubbel geboekt stonden — Zenvoices + module).

Pure, deterministische motor over de eigen bankmutatie-cache — géén RLZ-call, géén AI. Regel: twee (of meer) UITGAANDE
mutaties aan dezelfde tegenrekening-IBAN, cent-exact hetzelfde bedrag, binnen `venster_dagen` van elkaar → vermoeden
`dubbele_betaling_vermoed`, TENZIJ
  (a) de reeks van álle mutaties met die IBAN+bedrag PERIODIEK is (huur/abonnement — `classificeer_reeks`; bij twee
      datums geeft die ONBEPAALD en dan signaleren we wél: twee gelijke betalingen zonder patroon);
  (b) de RLZ-koppelingen van de mutaties naar VERSCHILLENDE documenten mét verschillende genormaliseerde referentie
      wijzen (dan zijn het gewoon twee facturen; RLZ-systeemhulzen — document_type 19 / referentie None — tellen niet);
  (c) de aanroeper weet dat er ≥ N identieke facturen van dat bedrag bij de crediteur staan (`facturen_per_sleutel`).
Signaleren, nooit handelen: een mens beoordeelt (terugvordering) — de bevinding is oranje, nooit blokkerend."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

VENSTER_DAGEN_DEFAULT = 60
#: Leeshorizon van de per-administratie-variant (zelfde 400 dagen als de rlz_dubbel-toets).
LEESHORIZON_DAGEN = 400
#: RLZ-systeemhulzen (bank-plumbing) — een koppeling dáárnaar zegt niets over "welke factuur".
_SYSTEEMHULS_DOCUMENT_TYPE = 19

_CENT = Decimal("0.01")
_TELWOORDEN = {2: "twee", 3: "drie", 4: "vier", 5: "vijf", 6: "zes", 7: "zeven", 8: "acht", 9: "negen", 10: "tien"}


@dataclass(frozen=True)
class DubbeleBetaling:
    """Eén vermoeden: dezelfde tegenrekening, hetzelfde bedrag, `datums` chronologisch (== volgorde `mutatie_ids`)."""

    mutatie_ids: tuple[uuid.UUID, ...]
    tegenrekening_iban: str
    tegenpartij_naam: str | None
    bedrag: Decimal  # positief, cent-exact
    datums: tuple[date, ...]

    @property
    def jongste_mutatie_id(self) -> uuid.UUID:
        return self.mutatie_ids[-1]

    @property
    def aantal(self) -> int:
        return len(self.mutatie_ids)


@dataclass(frozen=True)
class DubbeleBetalingAnalyse:
    signalen: tuple[DubbeleBetaling, ...]
    #: Aantal sleutels (IBAN + bedrag) mét ≥ 2 uitgaande mutaties die getoetst zijn — de teller voor de reconciliatie.
    sleutels_getoetst: int


def euro_nl(bedrag: Decimal) -> str:
    """Decimal → '€ 12.600,00' (NL-notatie, altijd twee decimalen)."""
    q = abs(Decimal(bedrag)).quantize(_CENT)
    geheel, cent = f"{q:.2f}".split(".")
    groepen = []
    while len(geheel) > 3:
        groepen.insert(0, geheel[-3:])
        geheel = geheel[:-3]
    groepen.insert(0, geheel)
    return f"€ {'.'.join(groepen)},{cent}"


def _dd_mm(d: date) -> str:
    return d.strftime("%d-%m")


def _opsomming(delen: list[str]) -> str:
    if len(delen) <= 1:
        return "".join(delen)
    return ", ".join(delen[:-1]) + " en " + delen[-1]


def tekst_uit_delen(naam: str | None, bedrag: Decimal, datums: Iterable[date], *, iban: str | None = None) -> str:
    """De ene zin voor bevinding, chip-tooltip en mail — mensentaal, geen id's.
    "Aan Hello Kitchen Duiven is € 12.600,00 twee keer betaald (18-08 en 03-09) voor wat één factuur lijkt —
    controleer of terugvordering nodig is." """
    datums = sorted(datums)
    n = len(datums)
    keer = f"{_TELWOORDEN.get(n, str(n))} keer"
    wie = naam or (f"tegenrekening …{iban[-4:]}" if iban and len(iban) >= 4 else "dezelfde tegenrekening")
    return (
        f"Aan {wie} is {euro_nl(bedrag)} {keer} betaald ({_opsomming([_dd_mm(d) for d in datums])}) "
        "voor wat één factuur lijkt — controleer of terugvordering nodig is."
    )


def tekst(d: DubbeleBetaling) -> str:
    return tekst_uit_delen(d.tegenpartij_naam, d.bedrag, d.datums, iban=d.tegenrekening_iban)


# -- motor -------------------------------------------------------------------------------------------------------------


def _bedrag(m: Any) -> Decimal | None:
    b = getattr(m, "bedrag", None)
    if b is None:
        return None
    try:
        return Decimal(str(b)).quantize(_CENT)
    except Exception:  # noqa: BLE001 — een onleesbaar bedrag is geen kandidaat
        return None


def _referenties(m: Any) -> set[str]:
    """Genormaliseerde referenties van de ECHTE documenten waaraan de mutatie in RLZ hangt (hulzen tellen niet)."""
    from app.documenten.duplicaat_afvoer import normaliseer_referentie

    uit: set[str] = set()
    for k in getattr(m, "rlz_koppelingen", None) or []:
        if not isinstance(k, Mapping):
            continue
        if k.get("document_type") == _SYSTEEMHULS_DOCUMENT_TYPE:
            continue
        ref = normaliseer_referentie(k.get("referentie"))
        if ref:
            uit.add(ref)
    return uit


def _wijzen_naar_verschillende_facturen(cluster: list[Any]) -> bool:
    """Elke mutatie hangt aan minstens één echt document én geen referentie komt bij twee mutaties voor."""
    gezien: set[str] = set()
    for m in cluster:
        refs = _referenties(m)
        if not refs or refs & gezien:
            return False
        gezien |= refs
    return True


def _clusters_binnen_venster(gesorteerd: list[Any], venster_dagen: int) -> list[list[Any]]:
    """Ketens van opeenvolgende mutaties waarin élke volgende binnen `venster_dagen` van de vorige valt."""
    clusters: list[list[Any]] = []
    huidig: list[Any] = []
    for m in gesorteerd:
        if huidig and (m.boekdatum - huidig[-1].boekdatum).days > venster_dagen:
            clusters.append(huidig)
            huidig = []
        huidig.append(m)
    if huidig:
        clusters.append(huidig)
    return [c for c in clusters if len(c) >= 2]


def analyseer_dubbele_betalingen(
    mutaties: Iterable[Any],
    *,
    venster_dagen: int = VENSTER_DAGEN_DEFAULT,
    facturen_per_sleutel: Mapping[tuple[str, Decimal], int] | None = None,
) -> DubbeleBetalingAnalyse:
    """Pure motor over `BankMutatie`-achtige records (duck-typed: id, boekdatum, bedrag, tegenrekening_iban,
    tegenpartij_naam, omschrijving, rlz_koppelingen). Zie de module-docstring voor de regel."""
    from app.bank.matchmotor import normaliseer_iban
    from app.terugkerend.service import ReeksClassificatie, classificeer_reeks

    per_sleutel: dict[tuple[str, Decimal], list[Any]] = defaultdict(list)
    for m in mutaties:
        bedrag = _bedrag(m)
        if bedrag is None or bedrag >= 0 or getattr(m, "boekdatum", None) is None:
            continue
        iban = normaliseer_iban(getattr(m, "tegenrekening_iban", None))
        if not iban:
            continue
        per_sleutel[(iban, abs(bedrag))].append(m)

    signalen: list[DubbeleBetaling] = []
    sleutels_getoetst = 0
    for (iban, bedrag), groep in sorted(per_sleutel.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if len(groep) < 2:
            continue
        sleutels_getoetst += 1
        gesorteerd = sorted(groep, key=lambda m: (m.boekdatum, str(m.id)))
        # (a) periodiek patroon over de hele reeks (huur, abonnement) = geen signaal.
        if classificeer_reeks([m.boekdatum for m in gesorteerd]).classificatie is ReeksClassificatie.PERIODIEK:
            continue
        # (c) de aanroeper kent evenveel (of meer) identieke facturen als betalingen.
        if facturen_per_sleutel is not None and facturen_per_sleutel.get((iban, bedrag), 0) >= len(gesorteerd):
            continue
        for cluster in _clusters_binnen_venster(gesorteerd, venster_dagen):
            # (b) aantoonbaar twee verschillende facturen in RLZ = geen signaal.
            if _wijzen_naar_verschillende_facturen(cluster):
                continue
            naam = next((m.tegenpartij_naam for m in reversed(cluster) if getattr(m, "tegenpartij_naam", None)), None)
            signalen.append(
                DubbeleBetaling(
                    mutatie_ids=tuple(m.id for m in cluster),
                    tegenrekening_iban=iban,
                    tegenpartij_naam=naam,
                    bedrag=bedrag,
                    datums=tuple(m.boekdatum for m in cluster),
                )
            )
    return DubbeleBetalingAnalyse(signalen=tuple(signalen), sleutels_getoetst=sleutels_getoetst)


def vind_dubbele_betalingen(
    mutaties: Iterable[Any],
    *,
    venster_dagen: int = VENSTER_DAGEN_DEFAULT,
    facturen_per_sleutel: Mapping[tuple[str, Decimal], int] | None = None,
) -> list[DubbeleBetaling]:
    return list(
        analyseer_dubbele_betalingen(
            mutaties, venster_dagen=venster_dagen, facturen_per_sleutel=facturen_per_sleutel
        ).signalen
    )


# -- per administratie (één query, eigen DB) ---------------------------------------------------------------------------


def analyseer_voor_administratie(administratie_id: uuid.UUID, *, session: Any = None) -> DubbeleBetalingAnalyse:
    """Uitgaande, niet-verdwenen mutaties van de laatste `LEESHORIZON_DAGEN` in één set-based query, daarna de motor.
    Zonder `session` opent de functie zelf een `scoped_session(administratie_id)`."""
    from sqlalchemy import select

    from app.bank.models import BankMutatie
    from app.db.session import scoped_session
    from app.tijd import vandaag_nl

    vanaf = vandaag_nl() - timedelta(days=LEESHORIZON_DAGEN)
    stmt = select(
        BankMutatie.id,
        BankMutatie.boekdatum,
        BankMutatie.bedrag,
        BankMutatie.tegenrekening_iban,
        BankMutatie.tegenpartij_naam,
        BankMutatie.omschrijving,
        BankMutatie.rlz_koppelingen,
    ).where(
        BankMutatie.administratie_id == administratie_id,
        BankMutatie.bedrag < 0,
        BankMutatie.boekdatum >= vanaf,
        BankMutatie.verdwenen_uit_bron_op.is_(None),
    )
    if session is not None:
        rijen = list(session.execute(stmt))
    else:
        with scoped_session(administratie_id) as s:
            rijen = list(s.execute(stmt))
    return analyseer_dubbele_betalingen(rijen)


def vind_dubbele_betalingen_voor_administratie(
    administratie_id: uuid.UUID, *, session: Any = None
) -> list[DubbeleBetaling]:
    return list(analyseer_voor_administratie(administratie_id, session=session).signalen)
