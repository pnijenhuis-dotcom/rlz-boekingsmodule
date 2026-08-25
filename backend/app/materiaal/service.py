"""Transportplanning + bestellingen + materiaalstand — motor (steigerbouw-run blok D1–D5).

Seam-eis: deze module raakt de boekhouding NIET (geen RlzClient); de enige greep is de
crediteur-koppeling `MateriaalLeverancier.vendor_id` (D6, app/materiaal/match.py) via de
bestaande vendor-cache. Audit-eis: élke mutatie append-only geauditeerd (actor + oud→nieuw):
catalogus, bestelling (concept, revisie, verzending, annulering), transport (plannen, wijzigen,
statusovergang mét bron — de seam voor het verhuursysteem).

Statusmodel transport: gepland → bevestigd → geleverd (kantoor-klikwerk; ook gepland → geleverd
mag); alles behalve geleverd → geannuleerd mét reden; geleverd is terminaal (correctie = nieuw
retour/levering — parkeerpost veld-app-aftekening). Materiaalstand = uitsluitend status
'geleverd' telt (Σ leveringen − Σ retouren per product), huurperiode per item uit de tijdlijn."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, time
from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import Text, func, or_, select

from app.berichten import mail
from app.db.audit import record_audit_event
from app.db.models import Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.materiaal.models import (
    M2_DELER,
    BestellingStatus,
    MateriaalBestelling,
    MateriaalBestellingRevisie,
    MateriaalCategorie,
    MateriaalLeverancier,
    MateriaalProduct,
    MateriaalTransport,
    TransportSoort,
    TransportStatus,
)
from app.materiaal.pdf import TekstRegel, bouw_pdf, paginering
from app.materiaal.seed import UNIVERSAL_CATALOGUS, UNIVERSAL_LEVERANCIER
from app.sync.models import ProjectCache
from app.uren.models import ProjectSpecificatie
from app.uren.service import (
    MODULE,
    GeenToegang,
    NietGevonden,
    OngeldigeInvoer,
    OngeldigeOvergang,
    UrenFout,
    _administratie_met_opt_in,
    _vereis_meerwerk_recht,
    week_grenzen,
)

_CENT = Decimal("0.01")
MAX_PER_PAGINA = 100


class VerzendenMislukt(UrenFout):
    """Bestelbon niet bezorgd (mail) — niets vastgelegd als revisie, opnieuw proberen mag."""


def _vereis_beheerder(session, actor_id: uuid.UUID) -> None:
    actor = session.get(Gebruiker, actor_id)
    if actor is None or actor.rol != GebruikerRol.BEHEERDER:
        raise GeenToegang("Catalogusbeheer is voorbehouden aan de Beheerder")


def _leverancier(session, administratie_id: uuid.UUID, leverancier_id: uuid.UUID) -> MateriaalLeverancier:
    lev = session.get(MateriaalLeverancier, leverancier_id)
    if lev is None or lev.administratie_id != administratie_id:
        raise NietGevonden("Onbekende leverancier")
    return lev


def _project(session, administratie_id: uuid.UUID, project_id: uuid.UUID) -> ProjectCache:
    project = session.get(ProjectCache, (project_id, administratie_id))
    if project is None:
        raise NietGevonden("Onbekend project voor deze administratie")
    return project


def _rond(waarde: Decimal) -> Decimal:
    return waarde.quantize(_CENT, rounding=ROUND_HALF_UP)


# --- catalogus ------------------------------------------------------------------------------------


@dataclass(frozen=True)
class LeverancierData:
    id: uuid.UUID
    naam: str
    bestel_email: str | None
    telefoon: str | None
    adres: str | None
    vendor_id: uuid.UUID | None
    actief: bool
    aantal_producten: int


@dataclass(frozen=True)
class ProductData:
    id: uuid.UUID
    leverancier_id: uuid.UUID
    categorie_id: uuid.UUID
    categorie_naam: str
    bundel: str
    naam: str
    verpakking: str | None
    eenheid: str
    m2_lengte: Decimal | None
    volgorde: int
    actief: bool
    nummer: str = ""  # "1.3" — bundelnummer.volgnummer in de vaste catalogusvolgorde


@dataclass(frozen=True)
class CategorieData:
    id: uuid.UUID
    naam: str
    bundel: str
    volgorde: int
    actief: bool
    producten: list[ProductData]


def leveranciers_overzicht(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, zoek: str = "", alleen_actief: bool = True
) -> list[LeverancierData]:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        query = select(MateriaalLeverancier).where(MateriaalLeverancier.administratie_id == administratie_id)
        if alleen_actief:
            query = query.where(MateriaalLeverancier.actief.is_(True))
        if zoek.strip():
            query = query.where(MateriaalLeverancier.naam.ilike(f"%{zoek.strip()}%"))
        rijen = session.scalars(query.order_by(MateriaalLeverancier.naam)).all()
        tellingen = dict(
            session.execute(
                select(MateriaalProduct.leverancier_id, func.count())
                .where(MateriaalProduct.administratie_id == administratie_id, MateriaalProduct.actief.is_(True))
                .group_by(MateriaalProduct.leverancier_id)
            ).all()
        )
        return [
            LeverancierData(
                id=r.id,
                naam=r.naam,
                bestel_email=r.bestel_email,
                telefoon=r.telefoon,
                adres=r.adres,
                vendor_id=r.vendor_id,
                actief=r.actief,
                aantal_producten=tellingen.get(r.id, 0),
            )
            for r in rijen
        ]


def zet_leverancier(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    leverancier_id: uuid.UUID | None,
    naam: str,
    bestel_email: str | None,
    telefoon: str | None,
    adres: str | None,
    vendor_id: uuid.UUID | None,
    actief: bool = True,
) -> uuid.UUID:
    naam = naam.strip()
    if not naam:
        raise OngeldigeInvoer("Naam is verplicht")
    if bestel_email is not None and bestel_email.strip() and "@" not in bestel_email:
        raise OngeldigeInvoer("Ongeldig bestel-mailadres")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_beheerder(session, actor_id)
        nieuw = {
            "naam": naam,
            "bestel_email": (bestel_email or "").strip().lower() or None,
            "telefoon": (telefoon or "").strip() or None,
            "adres": (adres or "").strip() or None,
            "vendor_id": str(vendor_id) if vendor_id else None,
            "actief": actief,
        }
        if leverancier_id is None:
            lev = MateriaalLeverancier(
                administratie_id=administratie_id, bijgewerkt_door=actor_id, **{**nieuw, "vendor_id": vendor_id}
            )
            session.add(lev)
            session.flush()
            oud = None
        else:
            lev = _leverancier(session, administratie_id, leverancier_id)
            oud = {
                k: (str(getattr(lev, k)) if k == "vendor_id" and getattr(lev, k) else getattr(lev, k)) for k in nieuw
            }
            for k, v in nieuw.items():
                setattr(lev, k, vendor_id if k == "vendor_id" else v)
            lev.bijgewerkt_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_leverancier",
            record_id=lev.id,
            actie="materiaal_leverancier_gezet",
            correlatie_id=lev.id,
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
            administratie_id=administratie_id,
        )
        return lev.id


def _catalogus_in_sessie(
    session, administratie_id: uuid.UUID, leverancier_id: uuid.UUID, *, alleen_actief: bool
) -> list[CategorieData]:
    cats = session.scalars(
        select(MateriaalCategorie)
        .where(MateriaalCategorie.leverancier_id == leverancier_id)
        .order_by(MateriaalCategorie.bundel, MateriaalCategorie.volgorde, MateriaalCategorie.naam)
    ).all()
    prods = session.scalars(
        select(MateriaalProduct)
        .where(MateriaalProduct.leverancier_id == leverancier_id)
        .order_by(MateriaalProduct.volgorde, MateriaalProduct.naam)
    ).all()
    per_cat: dict[uuid.UUID, list[MateriaalProduct]] = {}
    for p in prods:
        if alleen_actief and not p.actief:
            continue
        per_cat.setdefault(p.categorie_id, []).append(p)
    bundel_nr: dict[str, int] = {}
    teller_per_bundel: dict[str, int] = {}
    resultaat: list[CategorieData] = []
    for c in cats:
        if alleen_actief and not c.actief:
            continue
        if c.bundel not in bundel_nr:
            bundel_nr[c.bundel] = len(bundel_nr) + 1
        producten = []
        for p in per_cat.get(c.id, []):
            teller_per_bundel[c.bundel] = teller_per_bundel.get(c.bundel, 0) + 1
            producten.append(
                ProductData(
                    id=p.id,
                    leverancier_id=p.leverancier_id,
                    categorie_id=c.id,
                    categorie_naam=c.naam,
                    bundel=c.bundel,
                    naam=p.naam,
                    verpakking=p.verpakking,
                    eenheid=p.eenheid,
                    m2_lengte=p.m2_lengte,
                    volgorde=p.volgorde,
                    actief=p.actief,
                    nummer=f"{bundel_nr[c.bundel]}.{teller_per_bundel[c.bundel]}",
                )
            )
        resultaat.append(
            CategorieData(
                id=c.id, naam=c.naam, bundel=c.bundel, volgorde=c.volgorde, actief=c.actief, producten=producten
            )
        )
    return resultaat


def catalogus(
    *, administratie_id: uuid.UUID, leverancier_id: uuid.UUID, actor_id: uuid.UUID, alleen_actief: bool = True
) -> list[CategorieData]:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        _leverancier(session, administratie_id, leverancier_id)
        return _catalogus_in_sessie(session, administratie_id, leverancier_id, alleen_actief=alleen_actief)


def producten_overzicht(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    leverancier_id: uuid.UUID | None,
    zoek: str = "",
    pagina: int = 1,
    per_pagina: int = 25,
) -> tuple[list[ProductData], int]:
    """Schaalbare catalogus-lijst (C4): zoeken + paginering server-side."""
    per_pagina = max(1, min(per_pagina, MAX_PER_PAGINA))
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        query = (
            select(MateriaalProduct, MateriaalCategorie)
            .join(MateriaalCategorie, MateriaalCategorie.id == MateriaalProduct.categorie_id)
            .where(MateriaalProduct.administratie_id == administratie_id)
        )
        if leverancier_id is not None:
            query = query.where(MateriaalProduct.leverancier_id == leverancier_id)
        if zoek.strip():
            term = f"%{zoek.strip()}%"
            query = query.where(or_(MateriaalProduct.naam.ilike(term), MateriaalCategorie.naam.ilike(term)))
        totaal = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rijen = session.execute(
            query.order_by(
                MateriaalCategorie.bundel, MateriaalCategorie.volgorde, MateriaalProduct.volgorde, MateriaalProduct.naam
            )
            .offset((max(pagina, 1) - 1) * per_pagina)
            .limit(per_pagina)
        ).all()
        return [
            ProductData(
                id=p.id,
                leverancier_id=p.leverancier_id,
                categorie_id=c.id,
                categorie_naam=c.naam,
                bundel=c.bundel,
                naam=p.naam,
                verpakking=p.verpakking,
                eenheid=p.eenheid,
                m2_lengte=p.m2_lengte,
                volgorde=p.volgorde,
                actief=p.actief,
            )
            for p, c in rijen
        ], int(totaal)


def zet_categorie(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    leverancier_id: uuid.UUID,
    categorie_id: uuid.UUID | None,
    naam: str,
    bundel: str,
    volgorde: int,
    actief: bool = True,
) -> uuid.UUID:
    naam = naam.strip()
    if not naam:
        raise OngeldigeInvoer("Naam is verplicht")
    if bundel not in ("steiger", "trappentoren", "overig"):
        raise OngeldigeInvoer("Bundel moet steiger, trappentoren of overig zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_beheerder(session, actor_id)
        _leverancier(session, administratie_id, leverancier_id)
        nieuw = {"naam": naam, "bundel": bundel, "volgorde": volgorde, "actief": actief}
        if categorie_id is None:
            cat = MateriaalCategorie(administratie_id=administratie_id, leverancier_id=leverancier_id, **nieuw)
            session.add(cat)
            session.flush()
            oud = None
        else:
            cat = session.get(MateriaalCategorie, categorie_id)
            if cat is None or cat.administratie_id != administratie_id:
                raise NietGevonden("Onbekende categorie")
            oud = {k: getattr(cat, k) for k in nieuw}
            for k, v in nieuw.items():
                setattr(cat, k, v)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_categorie",
            record_id=cat.id,
            actie="materiaal_categorie_gezet",
            correlatie_id=leverancier_id,
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
            administratie_id=administratie_id,
        )
        return cat.id


def zet_product(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    leverancier_id: uuid.UUID,
    product_id: uuid.UUID | None,
    categorie_id: uuid.UUID,
    naam: str,
    verpakking: str | None,
    eenheid: str,
    m2_lengte: Decimal | None,
    volgorde: int,
    actief: bool = True,
) -> uuid.UUID:
    naam = naam.strip()
    if not naam:
        raise OngeldigeInvoer("Productnaam is verplicht")
    if eenheid not in ("stuks", "rol", "m1", "m2", "set"):
        raise OngeldigeInvoer("Eenheid moet stuks, rol, m1, m2 of set zijn")
    if m2_lengte is not None and m2_lengte < 0:
        raise OngeldigeInvoer("m²-lengte kan niet negatief zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_beheerder(session, actor_id)
        _leverancier(session, administratie_id, leverancier_id)
        cat = session.get(MateriaalCategorie, categorie_id)
        if cat is None or cat.leverancier_id != leverancier_id:
            raise NietGevonden("Onbekende categorie voor deze leverancier")
        nieuw = {
            "categorie_id": str(categorie_id),
            "naam": naam,
            "verpakking": (verpakking or "").strip() or None,
            "eenheid": eenheid,
            "m2_lengte": str(m2_lengte) if m2_lengte is not None else None,
            "volgorde": volgorde,
            "actief": actief,
        }
        if product_id is None:
            prod = MateriaalProduct(
                administratie_id=administratie_id,
                leverancier_id=leverancier_id,
                categorie_id=categorie_id,
                naam=naam,
                verpakking=nieuw["verpakking"],
                eenheid=eenheid,
                m2_lengte=m2_lengte,
                volgorde=volgorde,
                actief=actief,
            )
            session.add(prod)
            session.flush()
            oud = None
        else:
            prod = session.get(MateriaalProduct, product_id)
            if prod is None or prod.administratie_id != administratie_id:
                raise NietGevonden("Onbekend product")
            oud = {
                "categorie_id": str(prod.categorie_id),
                "naam": prod.naam,
                "verpakking": prod.verpakking,
                "eenheid": prod.eenheid,
                "m2_lengte": str(prod.m2_lengte) if prod.m2_lengte is not None else None,
                "volgorde": prod.volgorde,
                "actief": prod.actief,
            }
            prod.categorie_id, prod.naam, prod.verpakking, prod.eenheid = (
                categorie_id,
                naam,
                nieuw["verpakking"],
                eenheid,
            )
            prod.m2_lengte, prod.volgorde, prod.actief = m2_lengte, volgorde, actief
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_product",
            record_id=prod.id,
            actie="materiaal_product_gezet",
            correlatie_id=leverancier_id,
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
            administratie_id=administratie_id,
        )
        return prod.id


@dataclass(frozen=True)
class SeedResultaat:
    leverancier_id: uuid.UUID
    categorieen_nieuw: int
    producten_nieuw: int
    producten_bestaand: int


def seed_universal(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> SeedResultaat:
    """Idempotente seed uit de bestellijst (app/materiaal/seed.py): upsert op naam, nooit
    verwijderen; bestaande producten blijven ongemoeid (ook hun m²-lengte)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_beheerder(session, actor_id)
        lev = session.scalars(
            select(MateriaalLeverancier).where(
                MateriaalLeverancier.administratie_id == administratie_id,
                MateriaalLeverancier.naam == UNIVERSAL_LEVERANCIER["naam"],
            )
        ).first()
        if lev is None:
            lev = MateriaalLeverancier(
                administratie_id=administratie_id, bijgewerkt_door=actor_id, actief=True, **UNIVERSAL_LEVERANCIER
            )
            session.add(lev)
            session.flush()
        cats_nieuw = prod_nieuw = prod_bestaand = 0
        bestaande_cats = {
            c.naam: c
            for c in session.scalars(select(MateriaalCategorie).where(MateriaalCategorie.leverancier_id == lev.id))
        }
        bestaande_prods = {
            p.naam: p
            for p in session.scalars(select(MateriaalProduct).where(MateriaalProduct.leverancier_id == lev.id))
        }
        for ci, sc in enumerate(UNIVERSAL_CATALOGUS, start=1):
            cat = bestaande_cats.get(sc.naam)
            if cat is None:
                cat = MateriaalCategorie(
                    administratie_id=administratie_id,
                    leverancier_id=lev.id,
                    naam=sc.naam,
                    bundel=sc.bundel,
                    volgorde=ci,
                    actief=True,
                )
                session.add(cat)
                session.flush()
                bestaande_cats[sc.naam] = cat
                cats_nieuw += 1
            for pi, sp in enumerate(sc.producten, start=1):
                if sp.naam in bestaande_prods:
                    prod_bestaand += 1
                    continue
                session.add(
                    MateriaalProduct(
                        administratie_id=administratie_id,
                        leverancier_id=lev.id,
                        categorie_id=cat.id,
                        naam=sp.naam,
                        verpakking=sp.verpakking,
                        eenheid=sp.eenheid,
                        m2_lengte=sp.m2_lengte,
                        volgorde=ci * 100 + pi,
                        actief=True,
                    )
                )
                prod_nieuw += 1
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_leverancier",
            record_id=lev.id,
            actie="materiaal_catalogus_geseed",
            correlatie_id=lev.id,
            nieuwe_waarde={
                "bron": "bestellijst-universal-voorbeeld.xlsx",
                "categorieen_nieuw": cats_nieuw,
                "producten_nieuw": prod_nieuw,
                "producten_bestaand": prod_bestaand,
            },
            administratie_id=administratie_id,
        )
        return SeedResultaat(lev.id, cats_nieuw, prod_nieuw, prod_bestaand)


# --- m²-formule ---------------------------------------------------------------------------------------


def bereken_m2(regels: dict[str, int], producten: dict[uuid.UUID, MateriaalProduct | ProductData]) -> Decimal:
    """Bundel-m² uit de bestellijst: Σ(aantal × m2_lengte) / 4,6 over producten mét lengte."""
    som = Decimal("0")
    for pid, aantal in regels.items():
        p = producten.get(uuid.UUID(str(pid)))
        if p is None or p.m2_lengte is None or not aantal:
            continue
        som += Decimal(int(aantal)) * p.m2_lengte
    return _rond(som / M2_DELER) if som else Decimal("0.00")


def _normaliseer_regels(regels: dict, producten: dict[uuid.UUID, MateriaalProduct]) -> dict[str, int]:
    schoon: dict[str, int] = {}
    for pid, aantal in (regels or {}).items():
        try:
            key = uuid.UUID(str(pid))
            n = int(aantal)
        except (ValueError, TypeError) as exc:
            raise OngeldigeInvoer("Ongeldige bestelregel") from exc
        if key not in producten:
            raise OngeldigeInvoer("Bestelregel verwijst naar een product buiten de catalogus van deze leverancier")
        if n < 0:
            raise OngeldigeInvoer("Aantal kan niet negatief zijn")
        if n > 0:
            schoon[str(key)] = n
    return schoon


# --- bestellingen ----------------------------------------------------------------------------------------


def nummer_label(volgnummer: int, aangemaakt_op: datetime) -> str:
    return f"B-{aangemaakt_op.year}-{volgnummer:04d}"


@dataclass(frozen=True)
class BestelRegelData:
    product: ProductData
    aantal: int
    was: int | None  # aantal in de laatst verstuurde revisie (None = nog nooit verstuurd)
    geleverd: int  # via gekoppelde transporten met status geleverd


@dataclass(frozen=True)
class RevisieData:
    revisie: int
    verstuurd_op: datetime
    verstuurd_door_naam: str | None
    verzonden_naar: str
    mail_status: str
    mail_fout: str | None
    m2_totaal: Decimal
    delta: list | None
    aantal_regels: int


@dataclass(frozen=True)
class BestellingData:
    id: uuid.UUID
    nummer: str
    project_id: uuid.UUID
    project_naam: str | None
    leverancier_id: uuid.UUID
    leverancier_naam: str
    leverancier_email: str | None
    status: str
    revisie: int
    heeft_concept_wijzigingen: bool
    gewenste_leverdatum: date | None
    gewenste_levertijd: time | None
    leveradres: str | None
    contactpersoon: str | None
    opmerking: str | None
    annulering_reden: str | None
    m2_totaal: Decimal
    aantal_regels: int
    aangemaakt_op: datetime
    bijgewerkt_op: datetime
    regels: list[BestelRegelData] = field(default_factory=list)
    revisies: list[RevisieData] = field(default_factory=list)
    transport_ids: list[uuid.UUID] = field(default_factory=list)


def _laatste_revisie(session, bestelling_id: uuid.UUID) -> MateriaalBestellingRevisie | None:
    return session.scalars(
        select(MateriaalBestellingRevisie)
        .where(MateriaalBestellingRevisie.bestelling_id == bestelling_id)
        .order_by(MateriaalBestellingRevisie.revisie.desc())
    ).first()


def _producten_van(session, leverancier_id: uuid.UUID) -> dict[uuid.UUID, MateriaalProduct]:
    return {
        p.id: p
        for p in session.scalars(select(MateriaalProduct).where(MateriaalProduct.leverancier_id == leverancier_id))
    }


def _bestelling_data(session, b: MateriaalBestelling, *, volledig: bool) -> BestellingData:
    lev = session.get(MateriaalLeverancier, b.leverancier_id)
    project = session.get(ProjectCache, (b.project_id, b.administratie_id))
    producten = _producten_van(session, b.leverancier_id)
    laatste = _laatste_revisie(session, b.id)
    was = {str(k): int(v) for k, v in (laatste.regels if laatste else {}).items()}
    huidig = {str(k): int(v) for k, v in (b.regels or {}).items()}
    regels: list[BestelRegelData] = []
    transport_ids: list[uuid.UUID] = []
    revisies: list[RevisieData] = []
    if volledig:
        geleverd: dict[str, int] = {}
        transporten = session.scalars(select(MateriaalTransport).where(MateriaalTransport.bestelling_id == b.id)).all()
        for t in transporten:
            transport_ids.append(t.id)
            if t.status == TransportStatus.GELEVERD.value and t.soort == TransportSoort.LEVERING.value:
                for pid, n in (t.regels or {}).items():
                    geleverd[str(pid)] = geleverd.get(str(pid), 0) + int(n)
        for cat in _catalogus_in_sessie(session, b.administratie_id, b.leverancier_id, alleen_actief=True):
            for p in cat.producten:
                regels.append(
                    BestelRegelData(
                        product=p,
                        aantal=huidig.get(str(p.id), 0),
                        was=(was.get(str(p.id), 0) if laatste is not None else None),
                        geleverd=geleverd.get(str(p.id), 0),
                    )
                )
        namen = {
            g.id: g.naam
            for g in session.scalars(
                select(Gebruiker).where(
                    Gebruiker.id.in_(
                        [
                            r.verstuurd_door
                            for r in session.scalars(
                                select(MateriaalBestellingRevisie).where(
                                    MateriaalBestellingRevisie.bestelling_id == b.id
                                )
                            )
                        ]
                    )
                )
            )
        }
        revisies = [
            RevisieData(
                revisie=r.revisie,
                verstuurd_op=r.verstuurd_op,
                verstuurd_door_naam=namen.get(r.verstuurd_door),
                verzonden_naar=r.verzonden_naar,
                mail_status=r.mail_status,
                mail_fout=r.mail_fout,
                m2_totaal=r.m2_totaal,
                delta=r.delta,
                aantal_regels=len(r.regels or {}),
            )
            for r in session.scalars(
                select(MateriaalBestellingRevisie)
                .where(MateriaalBestellingRevisie.bestelling_id == b.id)
                .order_by(MateriaalBestellingRevisie.revisie)
            )
        ]
    return BestellingData(
        id=b.id,
        nummer=nummer_label(b.volgnummer, b.aangemaakt_op),
        project_id=b.project_id,
        project_naam=project.naam if project else None,
        leverancier_id=b.leverancier_id,
        leverancier_naam=lev.naam if lev else "?",
        leverancier_email=lev.bestel_email if lev else None,
        status=b.status,
        revisie=b.revisie,
        heeft_concept_wijzigingen=(laatste is not None and huidig != was),
        gewenste_leverdatum=b.gewenste_leverdatum,
        gewenste_levertijd=b.gewenste_levertijd,
        leveradres=b.leveradres,
        contactpersoon=b.contactpersoon,
        opmerking=b.opmerking,
        annulering_reden=b.annulering_reden,
        m2_totaal=bereken_m2(huidig, producten),
        aantal_regels=len(huidig),
        aangemaakt_op=b.aangemaakt_op,
        bijgewerkt_op=b.bijgewerkt_op,
        regels=regels,
        revisies=revisies,
        transport_ids=transport_ids,
    )


def bestellingen_overzicht(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    project_id: uuid.UUID | None = None,
    zoek: str = "",
    status: str | None = None,
    pagina: int = 1,
    per_pagina: int = 25,
) -> tuple[list[BestellingData], int]:
    per_pagina = max(1, min(per_pagina, MAX_PER_PAGINA))
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        query = (
            select(MateriaalBestelling)
            .join(MateriaalLeverancier, MateriaalLeverancier.id == MateriaalBestelling.leverancier_id)
            .join(
                ProjectCache,
                (ProjectCache.id == MateriaalBestelling.project_id)
                & (ProjectCache.administratie_id == MateriaalBestelling.administratie_id),
            )
            .where(MateriaalBestelling.administratie_id == administratie_id)
        )
        if project_id is not None:
            query = query.where(MateriaalBestelling.project_id == project_id)
        if status:
            query = query.where(MateriaalBestelling.status == status)
        if zoek.strip():
            term = f"%{zoek.strip()}%"
            query = query.where(
                or_(
                    MateriaalLeverancier.naam.ilike(term),
                    ProjectCache.naam.ilike(term),
                    func.cast(MateriaalBestelling.volgnummer, Text).ilike(term),
                )
            )
        totaal = session.scalar(select(func.count()).select_from(query.subquery())) or 0
        rijen = session.scalars(
            query.order_by(MateriaalBestelling.bijgewerkt_op.desc())
            .offset((max(pagina, 1) - 1) * per_pagina)
            .limit(per_pagina)
        ).all()
        return [_bestelling_data(session, b, volledig=False) for b in rijen], int(totaal)


def bestelling_detail(*, administratie_id: uuid.UUID, bestelling_id: uuid.UUID, actor_id: uuid.UUID) -> BestellingData:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        b = _bestelling(session, administratie_id, bestelling_id)
        return _bestelling_data(session, b, volledig=True)


def _bestelling(session, administratie_id: uuid.UUID, bestelling_id: uuid.UUID) -> MateriaalBestelling:
    b = session.get(MateriaalBestelling, bestelling_id)
    if b is None or b.administratie_id != administratie_id:
        raise NietGevonden("Onbekende bestelling")
    return b


def maak_bestelling(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    project_id: uuid.UUID,
    leverancier_id: uuid.UUID,
    gewenste_leverdatum: date | None = None,
    gewenste_levertijd: time | None = None,
) -> uuid.UUID:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        project = _project(session, administratie_id, project_id)
        lev = _leverancier(session, administratie_id, leverancier_id)
        if not lev.actief:
            raise OngeldigeInvoer("Deze leverancier is inactief")
        volgnummer = (
            session.scalar(
                select(func.max(MateriaalBestelling.volgnummer)).where(
                    MateriaalBestelling.administratie_id == administratie_id
                )
            )
            or 0
        ) + 1
        spec = session.get(ProjectSpecificatie, (project_id, administratie_id))
        leveradres = f"Projectadres {project.naam or ''}".strip()
        if spec is not None and spec.opdrachtgever:
            leveradres += f" ({spec.opdrachtgever})"
        b = MateriaalBestelling(
            administratie_id=administratie_id,
            project_id=project_id,
            leverancier_id=leverancier_id,
            volgnummer=volgnummer,
            status=BestellingStatus.CONCEPT.value,
            revisie=0,
            regels={},
            gewenste_leverdatum=gewenste_leverdatum,
            gewenste_levertijd=gewenste_levertijd,
            leveradres=leveradres,
            aangemaakt_door=actor_id,
            bijgewerkt_door=actor_id,
        )
        session.add(b)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_bestelling",
            record_id=b.id,
            actie="bestelling_aangemaakt",
            correlatie_id=b.id,
            nieuwe_waarde={
                "nummer": nummer_label(volgnummer, datetime.now(UTC)),
                "project_id": str(project_id),
                "leverancier_id": str(leverancier_id),
            },
            administratie_id=administratie_id,
        )
        return b.id


def werk_concept_bij(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    bestelling_id: uuid.UUID,
    regels: dict,
    gewenste_leverdatum: date | None,
    gewenste_levertijd: time | None,
    leveradres: str | None,
    contactpersoon: str | None,
    opmerking: str | None,
) -> BestellingData:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        b = _bestelling(session, administratie_id, bestelling_id)
        if b.status == BestellingStatus.GEANNULEERD.value:
            raise OngeldigeOvergang("Een geannuleerde bestelling kan niet meer gewijzigd worden")
        producten = _producten_van(session, b.leverancier_id)
        schoon = _normaliseer_regels(regels, producten)
        oud = {
            "regels": b.regels,
            "gewenste_leverdatum": b.gewenste_leverdatum.isoformat() if b.gewenste_leverdatum else None,
            "gewenste_levertijd": b.gewenste_levertijd.isoformat() if b.gewenste_levertijd else None,
            "leveradres": b.leveradres,
            "contactpersoon": b.contactpersoon,
            "opmerking": b.opmerking,
        }
        b.regels = schoon
        b.gewenste_leverdatum = gewenste_leverdatum
        b.gewenste_levertijd = gewenste_levertijd
        b.leveradres = (leveradres or "").strip() or None
        b.contactpersoon = (contactpersoon or "").strip() or None
        b.opmerking = (opmerking or "").strip() or None
        b.bijgewerkt_door = actor_id
        nieuw = {
            "regels": schoon,
            "gewenste_leverdatum": gewenste_leverdatum.isoformat() if gewenste_leverdatum else None,
            "gewenste_levertijd": gewenste_levertijd.isoformat() if gewenste_levertijd else None,
            "leveradres": b.leveradres,
            "contactpersoon": b.contactpersoon,
            "opmerking": b.opmerking,
            "m2_totaal": str(bereken_m2(schoon, producten)),
        }
        if {k: v for k, v in oud.items()} != {k: v for k, v in nieuw.items() if k != "m2_totaal"}:
            record_audit_event(
                session,
                actor_id=actor_id,
                module=MODULE,
                tabel="materiaal_bestelling",
                record_id=b.id,
                actie="bestelling_concept_gewijzigd",
                correlatie_id=b.id,
                oude_waarde=oud,
                nieuwe_waarde=nieuw,
                administratie_id=administratie_id,
            )
        session.flush()
        return _bestelling_data(session, b, volledig=True)


def bereken_delta(oud: dict, nieuw: dict, producten: dict[uuid.UUID, MateriaalProduct]) -> list[dict]:
    """Alleen gewijzigde regels oud → nieuw (mockup: 'was …'-markering; update-mail toont
    uitsluitend deze regels)."""
    delta: list[dict] = []
    for pid in sorted(
        set(oud) | set(nieuw), key=lambda k: (producten[uuid.UUID(k)].volgorde if uuid.UUID(k) in producten else 0, k)
    ):
        o, n = int(oud.get(pid, 0)), int(nieuw.get(pid, 0))
        if o != n:
            p = producten.get(uuid.UUID(pid))
            delta.append({"product_id": pid, "naam": p.naam if p else "?", "oud": o, "nieuw": n})
    return delta


def _tijd_label(t: time | None) -> str:
    return t.strftime("%H:%M") if t else ""


def _datum_met_week(d: date | None) -> str:
    if d is None:
        return "—"
    iso = d.isocalendar()
    return f"{d.strftime('%d-%m-%Y')} (wk {iso.week})"


def _bon_regels(
    b: MateriaalBestelling,
    lev: MateriaalLeverancier,
    project: ProjectCache | None,
    catalogus: list[CategorieData],
    regels: dict[str, int],
    delta: list[dict],
    m2: Decimal,
    revisie: int,
    afzender: str,
) -> list[TekstRegel]:
    nummer = nummer_label(b.volgnummer, b.aangemaakt_op)
    r: list[TekstRegel] = [
        TekstRegel(f"Bestelling {nummer} · revisie r{revisie}", grootte=15, vet=True),
        TekstRegel(f"Aan: {lev.naam}" + (f" · {lev.bestel_email}" if lev.bestel_email else ""), grootte=10),
        TekstRegel(f"Van: {afzender}", grootte=10),
        TekstRegel(""),
        TekstRegel("Project:", vet=True),
        TekstRegel(project.naam if project else str(b.project_id), x=170),
        TekstRegel("Leveradres:", vet=True),
        TekstRegel(b.leveradres or "—", x=170),
        TekstRegel("Gewenste levering:", vet=True),
        TekstRegel(f"{_datum_met_week(b.gewenste_leverdatum)} {_tijd_label(b.gewenste_levertijd)}".strip(), x=170),
    ]
    if b.contactpersoon:
        r += [TekstRegel("Contactpersoon:", vet=True), TekstRegel(b.contactpersoon, x=170)]
    if b.opmerking:
        r += [TekstRegel("Opmerking:", vet=True), TekstRegel(b.opmerking[:110], x=170)]
    r.append(TekstRegel(""))
    if revisie > 1 and delta:
        r.append(TekstRegel(f"WIJZIGINGEN t.o.v. revisie r{revisie - 1} (oud → nieuw):", vet=True))
        for d in delta:
            r += [TekstRegel(d["naam"]), TekstRegel(f"{d['oud']} → {d['nieuw']}", x=400, vet=True)]
        r.append(TekstRegel(""))
    r += [
        TekstRegel("Nr.", vet=True),
        TekstRegel("Product", x=90, vet=True),
        TekstRegel("Verpakking", x=360, vet=True),
        TekstRegel("Aantal", x=470, vet=True),
    ]
    was_map = {d["product_id"]: d["oud"] for d in delta}
    for cat in catalogus:
        cat_regels = [p for p in cat.producten if regels.get(str(p.id), 0) > 0 or str(p.id) in was_map]
        if not cat_regels:
            continue
        r.append(TekstRegel(f"{cat.naam}", vet=True, grootte=9))
        for p in cat_regels:
            n = regels.get(str(p.id), 0)
            aantal = f"{n}" + (f"  (was {was_map[str(p.id)]})" if str(p.id) in was_map else "")
            r += [
                TekstRegel(p.nummer, grootte=9),
                TekstRegel(p.naam[:52], x=90),
                TekstRegel(p.verpakking or "", x=360, grootte=9),
                TekstRegel(aantal, x=470, vet=str(p.id) in was_map),
            ]
    r += [
        TekstRegel(""),
        TekstRegel(f"Totaal steigermateriaal (bundel): {m2} m²  —  formule Σ(aantal × lengte) / 4,6", vet=True),
    ]
    r += [
        TekstRegel(""),
        TekstRegel(
            "0 = niet bestellen. Deze bon is gegenereerd door de Nijenhuis Boekingsmodule; "
            "wijzigingen ná verzending volgen als nieuwe revisie.",
            grootte=8,
        ),
    ]
    return r


def verstuur_bestelling(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, bestelling_id: uuid.UUID, koppel_levering: bool = True
) -> BestellingData:
    """Versturen = REVISIE r{n+1}: snapshot + delta + PDF-bon (DocumentOpslag) + mail (bestaand
    SMTP-kanaal, mens klikt expliciet). Mailfout = niets vastgelegd als revisie (geen halve stand),
    zichtbare fout + audit; opnieuw proberen mag. Koppelt/actualiseert de geplande levering."""
    from app.documenten.storage import standaard_opslag

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        actor = _vereis_meerwerk_recht(session, actor_id)
        b = _bestelling(session, administratie_id, bestelling_id)
        if b.status == BestellingStatus.GEANNULEERD.value:
            raise OngeldigeOvergang("Een geannuleerde bestelling kan niet verstuurd worden")
        lev = _leverancier(session, administratie_id, b.leverancier_id)
        if not lev.bestel_email:
            raise OngeldigeInvoer("De leverancier heeft geen bestel-mailadres — vul dat eerst in bij de catalogus")
        regels = {str(k): int(v) for k, v in (b.regels or {}).items() if int(v) > 0}
        if not regels:
            raise OngeldigeInvoer("Een bestelling zonder regels kan niet verstuurd worden")
        laatste = _laatste_revisie(session, b.id)
        vorige = {str(k): int(v) for k, v in (laatste.regels if laatste else {}).items()}
        if (
            laatste is not None
            and vorige == regels
            and laatste.gewenste_leverdatum == b.gewenste_leverdatum
            and laatste.leveradres == b.leveradres
        ):
            raise OngeldigeOvergang("Geen wijzigingen sinds de laatste verzending — er is niets te versturen")
        producten = _producten_van(session, b.leverancier_id)
        delta = bereken_delta(vorige, regels, producten) if laatste is not None else []
        m2 = bereken_m2(regels, producten)
        nieuwe_revisie = b.revisie + 1
        project = session.get(ProjectCache, (b.project_id, administratie_id))
        catalogus_lijst = _catalogus_in_sessie(session, administratie_id, b.leverancier_id, alleen_actief=False)
        afzender = f"{actor.naam} — Administratiekantoor Nijenhuis"
        pdf = bouw_pdf(
            paginering(_bon_regels(b, lev, project, catalogus_lijst, regels, delta, m2, nieuwe_revisie, afzender))
        )
        nummer = nummer_label(b.volgnummer, b.aangemaakt_op)
        pad = f"materiaal/bestelling/{administratie_id}/{b.id}/{nummer}-r{nieuwe_revisie}.pdf"
        soort_label = "Bestelling" if nieuwe_revisie == 1 else "Gewijzigde bestelling"
        onderwerp = f"{soort_label} {nummer} r{nieuwe_revisie} — {project.naam if project else 'project'}"
        if nieuwe_revisie == 1 or not delta:
            regeltekst = "\n".join(
                f"- {producten[uuid.UUID(pid)].naam}: {n}" for pid, n in regels.items() if uuid.UUID(pid) in producten
            )
            kern = f"Hierbij onze bestelling {nummer} voor project {project.naam if project else ''}:\n{regeltekst}"
        else:
            regeltekst = "\n".join(f"- {d['naam']}: {d['oud']} → {d['nieuw']}" for d in delta)
            kern = (
                f"Wijziging op bestelling {nummer} (revisie r{nieuwe_revisie}) — uitsluitend de gewijzigde regels "
                f"(oud → nieuw):\n{regeltekst}"
            )
        tekst = (
            f"Beste {lev.naam},\n\n{kern}\n\n"
            f"Gewenste levering: {_datum_met_week(b.gewenste_leverdatum)} {_tijd_label(b.gewenste_levertijd)}\n"
            f"Leveradres: {b.leveradres or '—'}\n"
            f"Totaal steigermateriaal (bundel): {m2} m²\n\n"
            f"De volledige bon staat in de bijlage (PDF).\n\nMet vriendelijke groet,\n{afzender}"
        )
        session.expunge(actor)

    # Mail buiten de transactie (extern effect); fail-zichtbaar.
    try:
        mail.verzend_mail(
            naar=lev.bestel_email,
            onderwerp=onderwerp,
            tekst=tekst,
            bijlagen=[(f"{nummer}-r{nieuwe_revisie}.pdf", pdf, "application/pdf")],
        )
    except Exception as exc:  # noqa: BLE001 — MailFout én onverwachte crash: zichtbaar, nooit stil
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            record_audit_event(
                session,
                actor_id=actor_id,
                module=MODULE,
                tabel="materiaal_bestelling",
                record_id=bestelling_id,
                actie="bestelling_verzending_mislukt",
                correlatie_id=bestelling_id,
                nieuwe_waarde={"revisie": nieuwe_revisie, "naar": lev.bestel_email, "fout": str(exc)},
                administratie_id=administratie_id,
            )
        raise VerzendenMislukt(f"Bestelbon niet verzonden aan {lev.bestel_email}: {exc}") from exc

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        b = _bestelling(session, administratie_id, bestelling_id)
        standaard_opslag().opslaan(pad=pad, inhoud=pdf)
        session.add(
            MateriaalBestellingRevisie(
                administratie_id=administratie_id,
                bestelling_id=b.id,
                revisie=nieuwe_revisie,
                regels=regels,
                m2_totaal=m2,
                delta=delta or None,
                gewenste_leverdatum=b.gewenste_leverdatum,
                gewenste_levertijd=b.gewenste_levertijd,
                leveradres=b.leveradres,
                pdf_opslag_pad=pad,
                verzonden_naar=lev.bestel_email,
                mail_status="verzonden",
                verstuurd_door=actor_id,
            )
        )
        oud_status, b.status, b.revisie = b.status, BestellingStatus.VERSTUURD.value, nieuwe_revisie
        b.bijgewerkt_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_bestelling",
            record_id=b.id,
            actie="bestelling_verstuurd",
            correlatie_id=b.id,
            oude_waarde={"status": oud_status, "revisie": nieuwe_revisie - 1},
            nieuwe_waarde={
                "status": b.status,
                "revisie": nieuwe_revisie,
                "naar": lev.bestel_email,
                "m2_totaal": str(m2),
                "delta": delta,
                "pdf": pad,
            },
            administratie_id=administratie_id,
        )
        if koppel_levering and b.gewenste_leverdatum is not None:
            _koppel_levering_aan_bestelling(session, b, regels, actor_id)
        session.flush()
        return _bestelling_data(session, b, volledig=True)


def _koppel_levering_aan_bestelling(
    session, b: MateriaalBestelling, regels: dict[str, int], actor_id: uuid.UUID
) -> None:
    """De bestelling koppelt aan de transport-levering (D3): bestaat er al een GEPLANDE levering
    voor deze bestelling, dan volgt die de nieuwe regels/datum; anders wordt er één geplant."""
    levering = session.scalars(
        select(MateriaalTransport).where(
            MateriaalTransport.bestelling_id == b.id,
            MateriaalTransport.soort == TransportSoort.LEVERING.value,
            MateriaalTransport.status.in_([TransportStatus.GEPLAND.value, TransportStatus.BEVESTIGD.value]),
        )
    ).first()
    if levering is None:
        levering = MateriaalTransport(
            administratie_id=b.administratie_id,
            project_id=b.project_id,
            leverancier_id=b.leverancier_id,
            bestelling_id=b.id,
            soort=TransportSoort.LEVERING.value,
            datum=b.gewenste_leverdatum,
            tijdstip=b.gewenste_levertijd,
            status=TransportStatus.GEPLAND.value,
            status_bron="kantoor",
            regels=regels,
            omschrijving=f"Levering bestelling {nummer_label(b.volgnummer, b.aangemaakt_op)}",
            aangemaakt_door=actor_id,
        )
        session.add(levering)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_transport",
            record_id=levering.id,
            actie="transport_gepland",
            correlatie_id=b.id,
            nieuwe_waarde={
                "soort": "levering",
                "datum": b.gewenste_leverdatum.isoformat(),
                "bestelling_id": str(b.id),
                "regels": regels,
                "bron": "bestelling",
            },
            administratie_id=b.administratie_id,
        )
        return
    oud = {"datum": levering.datum.isoformat(), "regels": levering.regels}
    levering.datum, levering.tijdstip, levering.regels = b.gewenste_leverdatum, b.gewenste_levertijd, regels
    record_audit_event(
        session,
        actor_id=actor_id,
        module=MODULE,
        tabel="materiaal_transport",
        record_id=levering.id,
        actie="transport_gewijzigd",
        correlatie_id=b.id,
        oude_waarde=oud,
        nieuwe_waarde={"datum": b.gewenste_leverdatum.isoformat(), "regels": regels, "bron": "bestelling-revisie"},
        administratie_id=b.administratie_id,
    )


def annuleer_bestelling(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, bestelling_id: uuid.UUID, reden: str
) -> BestellingData:
    reden = (reden or "").strip()
    if not reden:
        raise OngeldigeInvoer("Annuleren vereist een reden")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        b = _bestelling(session, administratie_id, bestelling_id)
        if b.status == BestellingStatus.GEANNULEERD.value:
            return _bestelling_data(session, b, volledig=True)
        oud = b.status
        b.status, b.annulering_reden, b.bijgewerkt_door = BestellingStatus.GEANNULEERD.value, reden, actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_bestelling",
            record_id=b.id,
            actie="bestelling_geannuleerd",
            correlatie_id=b.id,
            oude_waarde={"status": oud},
            nieuwe_waarde={"status": b.status, "reden": reden},
            administratie_id=administratie_id,
        )
        return _bestelling_data(session, b, volledig=True)


def revisie_pdf(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, bestelling_id: uuid.UUID, revisie: int
) -> tuple[str, bytes]:
    from app.documenten.storage import standaard_opslag

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        b = _bestelling(session, administratie_id, bestelling_id)
        rij = session.scalars(
            select(MateriaalBestellingRevisie).where(
                MateriaalBestellingRevisie.bestelling_id == b.id, MateriaalBestellingRevisie.revisie == revisie
            )
        ).first()
        if rij is None:
            raise NietGevonden("Onbekende revisie")
        pad, naam = rij.pdf_opslag_pad, f"{nummer_label(b.volgnummer, b.aangemaakt_op)}-r{revisie}.pdf"
    return naam, standaard_opslag().lezen(pad=pad)


# --- transport ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportData:
    id: uuid.UUID
    project_id: uuid.UUID
    project_naam: str | None
    leverancier_id: uuid.UUID
    leverancier_naam: str
    bestelling_id: uuid.UUID | None
    bestelling_nummer: str | None
    soort: str
    datum: date
    tijdstip: time | None
    status: str
    status_bron: str
    status_reden: str | None
    regels: list[dict]  # [{product_id, naam, aantal, eenheid}]
    samenvatting: str  # "Steiger 600 m²" / "Lift 1×"
    m2: Decimal
    omschrijving: str | None


def _transport_data(
    session,
    t: MateriaalTransport,
    producten: dict[uuid.UUID, MateriaalProduct],
    leveranciers: dict[uuid.UUID, MateriaalLeverancier],
    projecten: dict[uuid.UUID, ProjectCache],
    bestellingen: dict[uuid.UUID, MateriaalBestelling],
) -> TransportData:
    regels = []
    for pid, n in (t.regels or {}).items():
        p = producten.get(uuid.UUID(str(pid)))
        regels.append(
            {
                "product_id": str(pid),
                "naam": p.naam if p else "?",
                "aantal": int(n),
                "eenheid": p.eenheid if p else "stuks",
            }
        )
    m2 = bereken_m2({str(k): int(v) for k, v in (t.regels or {}).items()}, producten)
    if m2 > 0:
        samenvatting = f"{'Levering' if t.soort == 'levering' else 'Retour'} steiger {m2} m²"
    elif regels:
        eerste = regels[0]
        extra = f" +{len(regels) - 1}" if len(regels) > 1 else ""
        samenvatting = (
            f"{'Levering' if t.soort == 'levering' else 'Retour'} {eerste['naam']} ({eerste['aantal']}×){extra}"
        )
    else:
        samenvatting = t.omschrijving or ("Levering" if t.soort == "levering" else "Retour")
    lev = leveranciers.get(t.leverancier_id)
    proj = projecten.get(t.project_id)
    best = bestellingen.get(t.bestelling_id) if t.bestelling_id else None
    return TransportData(
        id=t.id,
        project_id=t.project_id,
        project_naam=proj.naam if proj else None,
        leverancier_id=t.leverancier_id,
        leverancier_naam=lev.naam if lev else "?",
        bestelling_id=t.bestelling_id,
        bestelling_nummer=nummer_label(best.volgnummer, best.aangemaakt_op) if best else None,
        soort=t.soort,
        datum=t.datum,
        tijdstip=t.tijdstip,
        status=t.status,
        status_bron=t.status_bron,
        status_reden=t.status_reden,
        regels=regels,
        samenvatting=samenvatting,
        m2=m2,
        omschrijving=t.omschrijving,
    )


def _transport_context(session, administratie_id: uuid.UUID, transporten: list[MateriaalTransport]):
    producten = {
        p.id: p
        for p in session.scalars(select(MateriaalProduct).where(MateriaalProduct.administratie_id == administratie_id))
    }
    leveranciers = {
        lv.id: lv
        for lv in session.scalars(
            select(MateriaalLeverancier).where(MateriaalLeverancier.administratie_id == administratie_id)
        )
    }
    project_ids = {t.project_id for t in transporten}
    projecten = (
        {
            p.id: p
            for p in session.scalars(
                select(ProjectCache).where(
                    ProjectCache.administratie_id == administratie_id, ProjectCache.id.in_(project_ids)
                )
            )
        }
        if project_ids
        else {}
    )
    best_ids = {t.bestelling_id for t in transporten if t.bestelling_id}
    bestellingen = (
        {b.id: b for b in session.scalars(select(MateriaalBestelling).where(MateriaalBestelling.id.in_(best_ids)))}
        if best_ids
        else {}
    )
    return producten, leveranciers, projecten, bestellingen


def _transport(session, administratie_id: uuid.UUID, transport_id: uuid.UUID) -> MateriaalTransport:
    t = session.get(MateriaalTransport, transport_id)
    if t is None or t.administratie_id != administratie_id:
        raise NietGevonden("Onbekend transport")
    return t


def plan_transport(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    project_id: uuid.UUID,
    leverancier_id: uuid.UUID,
    soort: str,
    datum: date,
    tijdstip: time | None,
    regels: dict,
    omschrijving: str | None,
    bestelling_id: uuid.UUID | None = None,
) -> TransportData:
    if soort not in {s.value for s in TransportSoort}:
        raise OngeldigeInvoer("Soort moet levering of retour zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        project = _project(session, administratie_id, project_id)
        if project.is_actief is not True:
            raise OngeldigeInvoer("Alleen actieve projecten staan in de transportplanning")
        _leverancier(session, administratie_id, leverancier_id)
        producten = _producten_van(session, leverancier_id)
        schoon = _normaliseer_regels(regels, producten)
        if not schoon and not (omschrijving or "").strip():
            raise OngeldigeInvoer("Kies minstens één materiaalregel of geef een omschrijving")
        if bestelling_id is not None:
            b = _bestelling(session, administratie_id, bestelling_id)
            if b.leverancier_id != leverancier_id or b.project_id != project_id:
                raise OngeldigeInvoer("De bestelling hoort bij een andere leverancier of een ander project")
        t = MateriaalTransport(
            administratie_id=administratie_id,
            project_id=project_id,
            leverancier_id=leverancier_id,
            bestelling_id=bestelling_id,
            soort=soort,
            datum=datum,
            tijdstip=tijdstip,
            status=TransportStatus.GEPLAND.value,
            status_bron="kantoor",
            regels=schoon,
            omschrijving=(omschrijving or "").strip() or None,
            aangemaakt_door=actor_id,
        )
        session.add(t)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_transport",
            record_id=t.id,
            actie="transport_gepland",
            correlatie_id=t.id,
            nieuwe_waarde={
                "soort": soort,
                "datum": datum.isoformat(),
                "tijdstip": tijdstip.isoformat() if tijdstip else None,
                "regels": schoon,
                "leverancier_id": str(leverancier_id),
                "project_id": str(project_id),
                "bestelling_id": str(bestelling_id) if bestelling_id else None,
            },
            administratie_id=administratie_id,
        )
        return _transport_data(session, t, *_transport_context(session, administratie_id, [t]))


def wijzig_transport(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    transport_id: uuid.UUID,
    datum: date | None = None,
    tijdstip: time | None = None,
    regels: dict | None = None,
    omschrijving: str | None = None,
    project_id: uuid.UUID | None = None,
) -> TransportData:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        t = _transport(session, administratie_id, transport_id)
        if t.status in (TransportStatus.GELEVERD.value, TransportStatus.GEANNULEERD.value):
            raise OngeldigeOvergang(
                "Een geleverd of geannuleerd transport wijzigt niet meer — plan een nieuw transport"
            )
        oud = {
            "datum": t.datum.isoformat(),
            "tijdstip": t.tijdstip.isoformat() if t.tijdstip else None,
            "regels": t.regels,
            "omschrijving": t.omschrijving,
            "project_id": str(t.project_id),
        }
        if datum is not None:
            t.datum = datum
        if tijdstip is not None:
            t.tijdstip = tijdstip
        if regels is not None:
            t.regels = _normaliseer_regels(regels, _producten_van(session, t.leverancier_id))
        if omschrijving is not None:
            t.omschrijving = omschrijving.strip() or None
        if project_id is not None and project_id != t.project_id:
            project = _project(session, administratie_id, project_id)
            if project.is_actief is not True:
                raise OngeldigeInvoer("Alleen actieve projecten staan in de transportplanning")
            t.project_id = project_id
        nieuw = {
            "datum": t.datum.isoformat(),
            "tijdstip": t.tijdstip.isoformat() if t.tijdstip else None,
            "regels": t.regels,
            "omschrijving": t.omschrijving,
            "project_id": str(t.project_id),
        }
        if oud != nieuw:
            record_audit_event(
                session,
                actor_id=actor_id,
                module=MODULE,
                tabel="materiaal_transport",
                record_id=t.id,
                actie="transport_gewijzigd",
                correlatie_id=t.id,
                oude_waarde=oud,
                nieuwe_waarde=nieuw,
                administratie_id=administratie_id,
            )
        return _transport_data(session, t, *_transport_context(session, administratie_id, [t]))


_OVERGANGEN = {
    TransportStatus.GEPLAND.value: {
        TransportStatus.BEVESTIGD.value,
        TransportStatus.GELEVERD.value,
        TransportStatus.GEANNULEERD.value,
    },
    TransportStatus.BEVESTIGD.value: {
        TransportStatus.GELEVERD.value,
        TransportStatus.GEANNULEERD.value,
        TransportStatus.GEPLAND.value,
    },
    TransportStatus.GELEVERD.value: set(),
    TransportStatus.GEANNULEERD.value: set(),
}


def zet_transport_status(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    transport_id: uuid.UUID,
    nieuwe_status: str,
    reden: str | None = None,
    bron: str = "kantoor",
) -> TransportData:
    """DE SEAM voor de latere verhuursysteem-koppeling: dezelfde functie met bron='verhuursysteem'
    (parkeerpost; veld-app-aftekening idem). Nu kantoor-klikwerk. Overgangen: gepland → bevestigd
    → geleverd (ook gepland → geleverd), bevestigd → gepland (terug), alles behalve geleverd →
    geannuleerd mét reden. Geleverd is terminaal. Idempotent op dezelfde status."""
    if nieuwe_status not in {s.value for s in TransportStatus}:
        raise OngeldigeInvoer("Onbekende transportstatus")
    if bron not in ("kantoor", "verhuursysteem", "veld"):
        raise OngeldigeInvoer("Onbekende statusbron")
    reden = (reden or "").strip() or None
    if nieuwe_status == TransportStatus.GEANNULEERD.value and not reden:
        raise OngeldigeInvoer("Annuleren vereist een reden")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        t = _transport(session, administratie_id, transport_id)
        if t.status == nieuwe_status:
            return _transport_data(session, t, *_transport_context(session, administratie_id, [t]))
        if nieuwe_status not in _OVERGANGEN[t.status]:
            raise OngeldigeOvergang(f"Overgang {t.status} → {nieuwe_status} is niet toegestaan")
        oud = t.status
        t.status, t.status_bron, t.status_reden = nieuwe_status, bron, reden
        t.status_gewijzigd_door, t.status_gewijzigd_op = actor_id, datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="materiaal_transport",
            record_id=t.id,
            actie="transport_status_gewijzigd",
            correlatie_id=t.id,
            oude_waarde={"status": oud},
            nieuwe_waarde={"status": nieuwe_status, "bron": bron, "reden": reden},
            administratie_id=administratie_id,
        )
        return _transport_data(session, t, *_transport_context(session, administratie_id, [t]))


# --- materiaalstand + huurperiode ------------------------------------------------------------------------------


@dataclass(frozen=True)
class StandRegel:
    product_id: uuid.UUID
    naam: str
    categorie: str
    eenheid: str
    geleverd: int
    retour: int
    op_locatie: int
    eerste_levering: date | None
    laatste_retour: date | None
    huurdagen_tot_vandaag: int  # Σ over de tijdlijn van (op_locatie > 0)-dagen — de huurperiode per item
    huur_eenheden: Decimal  # Σ aantal × dagen / 7 (item-weken) — basis factuurcontrole (aantal × huurperiode)
    leveranciers: list[str]
    m2: Decimal


@dataclass(frozen=True)
class MateriaalStand:
    project_id: uuid.UUID
    project_naam: str | None
    tot_en_met: date
    regels: list[StandRegel]
    m2_op_locatie: Decimal
    totaal_items: int
    leveranciers: list[str]


def _tijdlijn(events: list[tuple[date, int]], tot_en_met: date) -> tuple[int, Decimal, date | None, date | None]:
    """events = [(datum, +aantal | −aantal)] → (huurdagen, item-weken, eerste_levering, laatste_retour_naar_0)."""
    stock = 0
    huurdagen = 0
    item_dagen = 0
    eerste: date | None = None
    laatste_nul: date | None = None
    vorige: date | None = None
    for d, delta in sorted(events, key=lambda e: (e[0], -e[1])):
        if d > tot_en_met:
            break
        if vorige is not None and stock > 0:
            dagen = (d - vorige).days
            huurdagen += dagen
            item_dagen += dagen * stock
        stock += delta
        if delta > 0 and eerste is None:
            eerste = d
        if stock <= 0 and delta < 0:
            laatste_nul = d
        vorige = d
    if vorige is not None and stock > 0:
        dagen = (tot_en_met - vorige).days + 1
        huurdagen += dagen
        item_dagen += dagen * stock
    return huurdagen, _rond(Decimal(item_dagen) / Decimal(7)), eerste, (laatste_nul if stock <= 0 else None)


def materiaalstand_in_sessie(
    session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, tot_en_met: date | None = None
) -> MateriaalStand:
    tot_en_met = tot_en_met or date.today()
    project = session.get(ProjectCache, (project_id, administratie_id))
    transporten = session.scalars(
        select(MateriaalTransport).where(
            MateriaalTransport.administratie_id == administratie_id,
            MateriaalTransport.project_id == project_id,
            MateriaalTransport.status == TransportStatus.GELEVERD.value,
            MateriaalTransport.datum <= tot_en_met,
        )
    ).all()
    producten, leveranciers, _, _ = _transport_context(session, administratie_id, transporten)
    categorieen = {
        c.id: c
        for c in session.scalars(
            select(MateriaalCategorie).where(MateriaalCategorie.administratie_id == administratie_id)
        )
    }
    events: dict[uuid.UUID, list[tuple[date, int]]] = {}
    levs: dict[uuid.UUID, set[str]] = {}
    for t in transporten:
        teken = 1 if t.soort == TransportSoort.LEVERING.value else -1
        for pid, n in (t.regels or {}).items():
            key = uuid.UUID(str(pid))
            events.setdefault(key, []).append((t.datum, teken * int(n)))
            lev = leveranciers.get(t.leverancier_id)
            if lev:
                levs.setdefault(key, set()).add(lev.naam)
    regels: list[StandRegel] = []
    for pid, evs in events.items():
        p = producten.get(pid)
        geleverd = sum(n for _, n in evs if n > 0)
        retour = -sum(n for _, n in evs if n < 0)
        huurdagen, eenheden, eerste, laatste = _tijdlijn(evs, tot_en_met)
        op_locatie = max(geleverd - retour, 0)
        m2 = _rond(Decimal(op_locatie) * p.m2_lengte / M2_DELER) if p and p.m2_lengte else Decimal("0.00")
        regels.append(
            StandRegel(
                product_id=pid,
                naam=p.naam if p else "?",
                categorie=categorieen[p.categorie_id].naam if p and p.categorie_id in categorieen else "?",
                eenheid=p.eenheid if p else "stuks",
                geleverd=geleverd,
                retour=retour,
                op_locatie=op_locatie,
                eerste_levering=eerste,
                laatste_retour=laatste,
                huurdagen_tot_vandaag=huurdagen,
                huur_eenheden=eenheden,
                leveranciers=sorted(levs.get(pid, set())),
                m2=m2,
            )
        )
    regels.sort(key=lambda r: (r.categorie, r.naam))
    return MateriaalStand(
        project_id=project_id,
        project_naam=project.naam if project else None,
        tot_en_met=tot_en_met,
        regels=regels,
        m2_op_locatie=_rond(sum((r.m2 for r in regels), Decimal("0"))),
        totaal_items=sum(r.op_locatie for r in regels),
        leveranciers=sorted({n for r in regels for n in r.leveranciers}),
    )


def materiaalstand(*, administratie_id: uuid.UUID, project_id: uuid.UUID, actor_id: uuid.UUID) -> MateriaalStand:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        _project(session, administratie_id, project_id)
        return materiaalstand_in_sessie(session, administratie_id=administratie_id, project_id=project_id)


def m2_geleverd_in_sessie(session, *, administratie_id: uuid.UUID, project_id: uuid.UUID) -> Decimal | None:
    """Toetsbron voor de keuring (D6): geleverde m² op het project; None = geen leveringen
    geregistreerd (dan géén signaal — er is niets om tegen te toetsen)."""
    stand = materiaalstand_in_sessie(session, administratie_id=administratie_id, project_id=project_id)
    if not stand.regels:
        return None
    return stand.m2_op_locatie


# --- wachtrisico (kruissignaal personeel × transport, D5) ---------------------------------------------------------


@dataclass(frozen=True)
class WachtrisicoMelding:
    project_id: uuid.UUID
    project_naam: str | None
    datum: date
    aantal_personen: int
    transport_id: uuid.UUID | None
    leverancier_naam: str | None
    samenvatting: str


def wachtrisico_in_sessie(
    session, *, administratie_id: uuid.UUID, personeel: dict[tuple[uuid.UUID, date], int]
) -> list[WachtrisicoMelding]:
    """Rood signaal (D5): personeel gepland op (project, dag) terwijl er voor dat project een
    levering gepland/onbevestigd staat (datum ≤ dag) én er nog niets als 'geleverd' op locatie
    staat vóór die dag — de ploeg wacht op materiaal. Zonder pending levering geen signaal (het
    project kan al lopen op eerder geleverd materiaal)."""
    if not personeel:
        return []
    project_ids = {p for p, _ in personeel}
    transporten = session.scalars(
        select(MateriaalTransport).where(
            MateriaalTransport.administratie_id == administratie_id,
            MateriaalTransport.project_id.in_(project_ids),
            MateriaalTransport.soort == TransportSoort.LEVERING.value,
            MateriaalTransport.status != TransportStatus.GEANNULEERD.value,
        )
    ).all()
    if not transporten:
        return []
    producten, leveranciers, projecten, bestellingen = _transport_context(session, administratie_id, transporten)
    meldingen: list[WachtrisicoMelding] = []
    for (project_id, dag), aantal in sorted(personeel.items(), key=lambda kv: (kv[0][1], str(kv[0][0]))):
        eigen = [t for t in transporten if t.project_id == project_id]
        geleverd_voor_dag = any(t.status == TransportStatus.GELEVERD.value and t.datum <= dag for t in eigen)
        if geleverd_voor_dag:
            continue
        pending = [t for t in eigen if t.status == TransportStatus.GEPLAND.value and t.datum <= dag]
        if not pending:
            continue
        t = sorted(pending, key=lambda x: x.datum)[-1]
        data = _transport_data(session, t, producten, leveranciers, projecten, bestellingen)
        meldingen.append(
            WachtrisicoMelding(
                project_id=project_id,
                project_naam=data.project_naam,
                datum=dag,
                aantal_personen=aantal,
                transport_id=t.id,
                leverancier_naam=data.leverancier_naam,
                samenvatting=data.samenvatting,
            )
        )
    return meldingen


# --- transport-weekgrid ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class TransportProjectRij:
    project_id: uuid.UUID
    project_naam: str | None
    opdrachtgever: str | None
    is_actief: bool
    per_datum: dict[str, list[TransportData]]
    week_transporten: int
    ploeg_label: str | None  # "ploeg ma–vr (3 man)" uit de personeelsplanning


@dataclass(frozen=True)
class TransportWeek:
    jaar: int
    weeknummer: int
    maandag: date
    zondag: date
    projecten: list[TransportProjectRij]
    wachtrisico: list[WachtrisicoMelding]
    aantal_transporten: int
    bestellingen_concept: int
    bestellingen_met_wijzigingen: int
    materiaalmatch_open: int


def transport_week(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, jaar: int, weeknummer: int) -> TransportWeek:
    from app.materiaal.match import open_materiaalmatches_in_sessie
    from app.uren.models import PlanningToewijzing

    maandag, zondag = week_grenzen(jaar, weeknummer)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_meerwerk_recht(session, actor_id)
        transporten = session.scalars(
            select(MateriaalTransport).where(
                MateriaalTransport.administratie_id == administratie_id,
                MateriaalTransport.datum >= maandag,
                MateriaalTransport.datum <= zondag,
                MateriaalTransport.status != TransportStatus.GEANNULEERD.value,
            )
        ).all()
        producten, leveranciers, _, bestellingen = _transport_context(session, administratie_id, transporten)
        projecten = session.scalars(
            select(ProjectCache).where(
                ProjectCache.administratie_id == administratie_id,
                ProjectCache.verdwenen_uit_bron_op.is_(None),
                or_(
                    ProjectCache.is_actief.is_(True),
                    ProjectCache.id.in_({t.project_id for t in transporten} or {uuid.uuid4()}),
                ),
            )
        ).all()
        proj_map = {p.id: p for p in projecten}
        specs = (
            {
                s.project_id: s
                for s in session.scalars(
                    select(ProjectSpecificatie).where(
                        ProjectSpecificatie.administratie_id == administratie_id,
                        ProjectSpecificatie.project_id.in_(list(proj_map)),
                    )
                )
            }
            if proj_map
            else {}
        )
        toewijzingen = session.scalars(
            select(PlanningToewijzing).where(
                PlanningToewijzing.administratie_id == administratie_id,
                PlanningToewijzing.datum >= maandag,
                PlanningToewijzing.datum <= zondag,
            )
        ).all()
        personeel: dict[tuple[uuid.UUID, date], int] = {}
        for tw in toewijzingen:
            personeel[(tw.project_id, tw.datum)] = personeel.get((tw.project_id, tw.datum), 0) + 1
        rijen: list[TransportProjectRij] = []
        for p in sorted(projecten, key=lambda x: x.naam or ""):
            eigen = [t for t in transporten if t.project_id == p.id]
            per_datum: dict[str, list[TransportData]] = {}
            for t in sorted(eigen, key=lambda x: (x.datum, x.tijdstip or time.min)):
                per_datum.setdefault(t.datum.isoformat(), []).append(
                    _transport_data(session, t, producten, leveranciers, proj_map, bestellingen)
                )
            dagen_met_ploeg = sorted({d for (pid, d), _ in personeel.items() if pid == p.id})
            ploeg_label = None
            if dagen_met_ploeg:
                maxman = max(n for (pid, _), n in personeel.items() if pid == p.id)
                namen = ["ma", "di", "wo", "do", "vr", "za", "zo"]
                ploeg_label = (
                    f"ploeg {namen[dagen_met_ploeg[0].weekday()]}–{namen[dagen_met_ploeg[-1].weekday()]} ({maxman} man)"
                    if len(dagen_met_ploeg) > 1
                    else f"ploeg {namen[dagen_met_ploeg[0].weekday()]} ({maxman} man)"
                )
            rijen.append(
                TransportProjectRij(
                    project_id=p.id,
                    project_naam=p.naam,
                    opdrachtgever=specs[p.id].opdrachtgever if p.id in specs else None,
                    is_actief=p.is_actief is True,
                    per_datum=per_datum,
                    week_transporten=len(eigen),
                    ploeg_label=ploeg_label,
                )
            )
        wachtrisico = wachtrisico_in_sessie(session, administratie_id=administratie_id, personeel=personeel)
        bestellingen_alle = session.scalars(
            select(MateriaalBestelling).where(
                MateriaalBestelling.administratie_id == administratie_id,
                MateriaalBestelling.status != BestellingStatus.GEANNULEERD.value,
            )
        ).all()
        concept = sum(1 for b in bestellingen_alle if b.status == BestellingStatus.CONCEPT.value)
        met_wijz = 0
        for b in bestellingen_alle:
            if b.status == BestellingStatus.VERSTUURD.value:
                laatste = _laatste_revisie(session, b.id)
                if laatste is not None and {str(k): int(v) for k, v in (b.regels or {}).items()} != {
                    str(k): int(v) for k, v in laatste.regels.items()
                }:
                    met_wijz += 1
        return TransportWeek(
            jaar=jaar,
            weeknummer=weeknummer,
            maandag=maandag,
            zondag=zondag,
            projecten=rijen,
            wachtrisico=wachtrisico,
            aantal_transporten=len(transporten),
            bestellingen_concept=concept,
            bestellingen_met_wijzigingen=met_wijz,
            materiaalmatch_open=open_materiaalmatches_in_sessie(session, administratie_id=administratie_id),
        )
