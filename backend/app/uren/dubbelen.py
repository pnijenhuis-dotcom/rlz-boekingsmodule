"""Dubbele veldwerkers — LEES-ONLY detector op HARDE sleutels alleen (opdracht Peter 21-09, correctie Peter 21-09).

Aanleiding: Cowork las "V. Ponchev"/"Z.V. Panchev" en "M. Demir"/"R. Demir" (zelfde projecten, zelfde dagen) als dubbele
records — het zijn broers die als ploeg samen gepland staan. Les: planningspatroon ≠ identiteit, naamgelijkenis ≠
identiteit.
Deze detector kijkt daarom UITSLUITEND naar harde sleutels binnen één administratie:

- **KvK-nummer** — `veldwerker_dossier.kvk_nummer` (per administratie × veldwerker);
- **IBAN** — via de crediteur-koppeling `veldwerker_crediteur.vendor_id` → `leverancier_iban` (alle rekeningen van
die crediteur);
- **e-mail** — `platform.gebruiker.e_mail` (genormaliseerd: lower + trim; de kolom is UNIEK, dus in de praktijk 0 —
de toets
  staat er zodat een pseudonimisering of import die dat ooit doorbreekt zichtbaar wordt);
- **telefoon** — géén veld op `platform.gebruiker` (alleen `materiaal.leverancier` kent er een) → "niet toetsbaar",
nooit stil.

Naam-afstand, initialen, achternaam, planningspatroon: NOOIT een signaal (guard-test). Geen UI-chip, geen samenvoegen
— alleen het
rapport (CLI `veldwerkers-dubbelen`). Set-based: vaste statements per administratie."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field

from sqlalchemy import select

from app.db.models import Gebruiker, GebruikerAdministratie, GebruikerRol
from app.documenten.models import LeverancierIban
from app.uren.models import VeldwerkerCrediteur, VeldwerkerDossier

#: Veldwerker-rollen die het rapport toetst (planbaar + detacheerder — allemaal "veldwerkers" in Beheer › Veldwerkers).
VELDWERKER_ROLLEN = (GebruikerRol.ZZPER, GebruikerRol.UITVOERDER, GebruikerRol.DETACHEERDER)
HARDE_SLEUTELS = ("kvk", "iban", "e_mail")
NIET_TOETSBAAR = {"telefoon": "geen telefoonveld op platform.gebruiker — niet toetsbaar (geen bron, geen signaal)"}


@dataclass(frozen=True)
class VeldwerkerSleutels:
    gebruiker_id: uuid.UUID
    naam: str
    rol: str
    e_mail: str | None
    kvk: str | None
    ibans: tuple[str, ...] = ()


@dataclass(frozen=True)
class Kandidaat:
    """Twee of meer veldwerkers in één administratie mét dezelfde harde sleutel."""

    sleutel: str  # 'kvk' | 'iban' | 'e_mail'
    waarde: str
    gebruiker_ids: tuple[uuid.UUID, ...]
    namen: tuple[str, ...]


@dataclass(frozen=True)
class DubbelenRapport:
    administratie_id: uuid.UUID
    administratie_naam: str
    aantal_veldwerkers: int
    aantal_met_kvk: int
    aantal_met_iban: int
    kandidaten: list[Kandidaat] = field(default_factory=list)
    niet_toetsbaar: dict[str, str] = field(default_factory=lambda: dict(NIET_TOETSBAAR))


def normaliseer_kvk(waarde: str | None) -> str | None:
    cijfers = "".join(ch for ch in (waarde or "") if ch.isdigit())
    return cijfers or None


def normaliseer_iban(waarde: str | None) -> str | None:
    kaal = "".join((waarde or "").split()).upper()
    return kaal or None


def normaliseer_e_mail(waarde: str | None) -> str | None:
    kaal = (waarde or "").strip().lower()
    return kaal or None


def kandidaten_uit_sleutels(veldwerkers: list[VeldwerkerSleutels]) -> list[Kandidaat]:
    """Puur: groepeer op harde sleutel; ≥ 2 verschillende personen mét dezelfde waarde = kandidaat. Namen spelen geen
    rol."""
    groepen: dict[tuple[str, str], dict[uuid.UUID, str]] = {}
    for v in veldwerkers:
        if v.kvk:
            groepen.setdefault(("kvk", v.kvk), {})[v.gebruiker_id] = v.naam
        if v.e_mail:
            groepen.setdefault(("e_mail", v.e_mail), {})[v.gebruiker_id] = v.naam
        for iban in v.ibans:
            groepen.setdefault(("iban", iban), {})[v.gebruiker_id] = v.naam
    uit: list[Kandidaat] = []
    for (sleutel, waarde), leden in sorted(groepen.items()):
        if len(leden) < 2:
            continue
        ids = tuple(sorted(leden, key=lambda g: (leden[g], str(g))))
        uit.append(Kandidaat(sleutel=sleutel, waarde=waarde, gebruiker_ids=ids, namen=tuple(leden[g] for g in ids)))
    return uit


def sleutels_voor_administratie(session, *, administratie_id: uuid.UUID) -> list[VeldwerkerSleutels]:  # noqa: ANN001
    """Set-based: veldwerkers mét scope op deze administratie (één statement), dossiers (één), crediteur-koppelingen
    (één),
    IBAN's van die crediteuren (één)."""
    gebruikers = list(
        session.scalars(
            select(Gebruiker)
            .join(GebruikerAdministratie, GebruikerAdministratie.gebruiker_id == Gebruiker.id)
            .where(GebruikerAdministratie.administratie_id == administratie_id, Gebruiker.rol.in_(VELDWERKER_ROLLEN))
            .order_by(Gebruiker.naam)
        )
    )
    if not gebruikers:
        return []
    ids = {g.id for g in gebruikers}
    kvk_per_gebruiker = {
        d.gebruiker_id: normaliseer_kvk(d.kvk_nummer)
        for d in session.scalars(
            select(VeldwerkerDossier).where(
                VeldwerkerDossier.administratie_id == administratie_id, VeldwerkerDossier.gebruiker_id.in_(ids)
            )
        )
    }
    vendor_per_gebruiker = {
        k.gebruiker_id: k.vendor_id
        for k in session.scalars(
            select(VeldwerkerCrediteur).where(
                VeldwerkerCrediteur.administratie_id == administratie_id, VeldwerkerCrediteur.gebruiker_id.in_(ids)
            )
        )
    }
    ibans_per_vendor: dict[uuid.UUID, set[str]] = {}
    if vendor_per_gebruiker:
        for rij in session.scalars(
            select(LeverancierIban).where(
                LeverancierIban.administratie_id == administratie_id,
                LeverancierIban.vendor_id.in_(set(vendor_per_gebruiker.values())),
            )
        ):
            iban = normaliseer_iban(rij.iban)
            if iban:
                ibans_per_vendor.setdefault(rij.vendor_id, set()).add(iban)
    uit: list[VeldwerkerSleutels] = []
    for g in gebruikers:
        vendor = vendor_per_gebruiker.get(g.id)
        uit.append(
            VeldwerkerSleutels(
                gebruiker_id=g.id,
                naam=g.naam,
                rol=g.rol.value,
                e_mail=normaliseer_e_mail(g.e_mail),
                kvk=kvk_per_gebruiker.get(g.id),
                ibans=tuple(sorted(ibans_per_vendor.get(vendor, set()))) if vendor else (),
            )
        )
    return uit


def rapport_voor_administratie(session, *, administratie_id: uuid.UUID, administratie_naam: str) -> DubbelenRapport:  # noqa: ANN001
    sleutels = sleutels_voor_administratie(session, administratie_id=administratie_id)
    return DubbelenRapport(
        administratie_id=administratie_id,
        administratie_naam=administratie_naam,
        aantal_veldwerkers=len(sleutels),
        aantal_met_kvk=sum(1 for v in sleutels if v.kvk),
        aantal_met_iban=sum(1 for v in sleutels if v.ibans),
        kandidaten=kandidaten_uit_sleutels(sleutels),
    )


def rapportregels(r: DubbelenRapport) -> list[str]:
    regels = [
        f"== {r.administratie_naam} ({r.administratie_id}) — {r.aantal_veldwerkers} veldwerker(s) in scope · "
        f"{r.aantal_met_kvk} mét KvK · {r.aantal_met_iban} mét IBAN via crediteur · "
        f"{len(r.kandidaten)} kandidaat-cluster(s)"
    ]
    for k in r.kandidaten:
        namen = " · ".join(f"{n} ({g})" for n, g in zip(k.namen, k.gebruiker_ids, strict=True))
        regels.append(f"  KANDIDAAT {k.sleutel}={k.waarde}: {namen} — beoordelen (geen samenvoegen, geen UI-chip)")
    if not r.kandidaten:
        regels.append("  geen kandidaten op harde sleutels (KvK, IBAN, e-mail)")
    for veld, reden in r.niet_toetsbaar.items():
        regels.append(f"  niet toetsbaar: {veld} — {reden}")
    return regels
