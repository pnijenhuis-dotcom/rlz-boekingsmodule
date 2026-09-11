"""Mini-voorraad — lezen + de vier toegestane handelingen (mockup mini-voorraad.html, ⑧ = kernbesluit Peter 05-09):

* LEZEN: productenlijst (zoek, filter alle/nieuw/gearchiveerd, 25/pagina), voorraadlog per product, stand-tellers,
  materiaallijst (F5) en de virtuele artikelgroep voor de voorraad-aansluiting (F5).
* HANDELINGEN zónder standmutatie: "Naam bevestigen" (alleen weergavenaam + vlag uit), archiveren/dearchiveren
  (kolom, stand blijft), en de BESCHADIGINGSMELDING — een gebeurtenis-registratie (wie/waar/wanneer) die als
  append-only mutatie −aantal telt, VERPLICHT gekoppeld aan een actief project van de administratie.
* Er bestaat GEEN functie die een stand, aantal of mutatie wijzigt/verwijdert (de DB-grant dwingt dat mee af).

De stand per product = SUM(aantal) over de mutaties — één query, nooit een kolom. Instroom/storno leven in
`instroom.py` (ín de boek-/tegenboek-transactie). Alles geauditeerd (`record_audit_event`)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import Select, case, func, or_, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel
from app.mini_voorraad.models import (
    SOORT_BESCHADIGING,
    SOORT_INSTROOM,
    SOORT_STORNO,
    SOORT_UITSTROOM,
    MiniProduct,
    MiniVoorraadMutatie,
)
from app.sync.models import ProjectCache, VendorCache
from app.tijd import vandaag_nl
from app.voorraad.models import ONBEKENDE_LEVERANCIER
from app.voorraad.normalisatie import normaliseer_code, normaliseer_tekst

PER_PAGINA = 25
MAX_PER_PAGINA = 200
MIN_REDEN_LENGTE = 5
_DUIZENDSTE = Decimal("0.001")

#: Naam van de virtuele artikelgroep in de voorraad-aansluiting én de categorie in de materiaallijst (F5).
VIRTUELE_GROEP_NAAM = "Speciale producten (mini-voorraad)"
_VIRTUELE_GROEP_NAMESPACE = uuid.UUID("6d1e6f1a-9c3b-4b5e-8f0a-2d4c7e9b1a55")

UITGESCHAKELD_TEKST = "Mini-voorraad staat uit voor deze administratie — Beheerder: Instellingen › Administraties"


class MiniVoorraadFout(Exception):
    """Basis voor alle domeinfouten van de mini-voorraad."""


class MiniVoorraadUitgeschakeld(MiniVoorraadFout):
    """Opt-in staat uit (409)."""


class ProductNietGevonden(MiniVoorraadFout):
    """Onbekend product binnen deze administratie (404)."""


class OngeldigeInvoer(MiniVoorraadFout):
    """Onbruikbare invoer (422) — leesbare reden."""


class GeenActiefProject(OngeldigeInvoer):
    """Beschadiging zonder actief project van deze administratie (422)."""


# --- basis -----------------------------------------------------------------------------------------------


def is_ingeschakeld(session: Session, administratie_id: uuid.UUID) -> bool:
    administratie = session.get(Administratie, administratie_id)
    return administratie is not None and administratie.mini_voorraad_ingeschakeld


def _vereis_ingeschakeld(session: Session, administratie_id: uuid.UUID) -> None:
    if not is_ingeschakeld(session, administratie_id):
        raise MiniVoorraadUitgeschakeld(UITGESCHAKELD_TEKST)


def virtuele_groep_id(administratie_id: uuid.UUID) -> uuid.UUID:
    """Deterministisch id van de virtuele artikelgroep in de voorraad-aansluiting (geen DB-rij)."""
    return uuid.uuid5(_VIRTUELE_GROEP_NAMESPACE, f"mini-voorraad:{administratie_id}")


def _als_str(waarde: Decimal | None) -> str | None:
    if waarde is None:
        return None
    q = waarde.quantize(_DUIZENDSTE)
    tekst = f"{q.normalize():f}" if q != 0 else "0"
    return tekst


def als_aantal_str(waarde: Decimal) -> str:
    """Decimal → string zonder wetenschappelijke notatie en zonder overbodige nullen ("96", "12.5", "-4")."""
    return _als_str(waarde) or "0"


def parse_aantal(waarde: str) -> Decimal:
    """Beschadigingsaantal uit de invoer: strikt positief, max 3 decimalen; komma als decimaalteken mag."""
    schoon = (waarde or "").strip().replace(" ", "").replace(",", ".")
    try:
        aantal = Decimal(schoon)
    except InvalidOperation as exc:
        raise OngeldigeInvoer(f"Aantal '{waarde}' is geen getal") from exc
    if not aantal.is_finite() or aantal <= 0:
        raise OngeldigeInvoer("Aantal moet groter dan 0 zijn")
    if aantal != aantal.quantize(_DUIZENDSTE):
        raise OngeldigeInvoer("Aantal mag maximaal 3 decimalen hebben")
    return aantal.quantize(_DUIZENDSTE)


def standen_per_product(
    session: Session, product_ids: list[uuid.UUID]
) -> dict[uuid.UUID, tuple[Decimal, datetime | None]]:
    """SUM(aantal) + laatste mutatiemoment per product — één query."""
    if not product_ids:
        return {}
    rijen = session.execute(
        select(
            MiniVoorraadMutatie.product_id,
            func.coalesce(func.sum(MiniVoorraadMutatie.aantal), 0),
            func.max(MiniVoorraadMutatie.aangemaakt_op),
        )
        .where(MiniVoorraadMutatie.product_id.in_(product_ids))
        .group_by(MiniVoorraadMutatie.product_id)
    ).all()
    uit = {pid: (Decimal(0), None) for pid in product_ids}
    for pid, som, laatste in rijen:
        uit[pid] = (Decimal(som).quantize(_DUIZENDSTE), laatste)
    return uit


def _product(session: Session, administratie_id: uuid.UUID, product_id: uuid.UUID) -> MiniProduct:
    product = session.get(MiniProduct, product_id)
    if product is None or product.administratie_id != administratie_id:
        raise ProductNietGevonden("Onbekend product in de mini-voorraad van deze administratie")
    return product


def vind_of_maak_product(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    leverancier_naam: str | None,
    omschrijving: str,
    artikelcode: str | None,
    eenheid: str | None,
    bron_document_id: uuid.UUID | None,
    actor_id: uuid.UUID,
) -> tuple[MiniProduct, bool]:
    """Deterministische matchvolgorde (①): artikelcode per leverancier → exacte genormaliseerde omschrijving per
    leverancier → NIEUW product (vlag `nieuw_controleren`). Geeft (product, is_nieuw). Een gearchiveerd product dat
    opnieuw voorkomt herleeft mét audit — nooit een tweede rij met dezelfde sleutel. Een gevonden product zonder
    code leert de code van de regel (deterministisch, geen AI)."""
    vendor = vendor_id or ONBEKENDE_LEVERANCIER
    norm = normaliseer_tekst(omschrijving)
    if not norm:
        raise OngeldigeInvoer("Lege omschrijving")
    code = normaliseer_code(artikelcode) if artikelcode else None
    product: MiniProduct | None = None
    if code:
        product = session.scalars(
            select(MiniProduct)
            .where(
                MiniProduct.administratie_id == administratie_id,
                MiniProduct.vendor_id == vendor,
                MiniProduct.artikelcode == code,
            )
            .order_by(MiniProduct.gearchiveerd, MiniProduct.aangemaakt_op)
        ).first()
    if product is None:
        product = session.scalars(
            select(MiniProduct).where(
                MiniProduct.administratie_id == administratie_id,
                MiniProduct.vendor_id == vendor,
                MiniProduct.omschrijving_norm == norm,
            )
        ).first()
    if product is None:
        product = MiniProduct(
            administratie_id=administratie_id,
            vendor_id=vendor,
            leverancier_naam=(leverancier_naam or None) and leverancier_naam[:200],
            artikelcode=code,
            omschrijving=omschrijving.strip()[:500],
            omschrijving_norm=norm,
            eenheid=(eenheid or None) and str(eenheid)[:16],
            nieuw_controleren=True,
            bron_document_id=bron_document_id,
        )
        session.add(product)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="mini_product",
            record_id=product.id,
            actie="mini_product_aangemaakt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "omschrijving": product.omschrijving,
                "artikelcode": code,
                "vendor_id": str(vendor),
                "bron_document_id": str(bron_document_id) if bron_document_id else None,
            },
            administratie_id=administratie_id,
        )
        return product, True
    if product.gearchiveerd:
        _dearchiveer(session, product, actor_id=actor_id, reden="opnieuw aangetroffen op een geboekte inkoopfactuur")
    if code and product.artikelcode is None:
        product.artikelcode = code
    if product.leverancier_naam is None and leverancier_naam:
        product.leverancier_naam = leverancier_naam[:200]
    if product.eenheid is None and eenheid:
        product.eenheid = str(eenheid)[:16]
    return product, False


def _dearchiveer(session: Session, product: MiniProduct, *, actor_id: uuid.UUID, reden: str) -> None:
    product.gearchiveerd = False
    product.gearchiveerd_op = None
    product.gearchiveerd_door = None
    record_audit_event(
        session,
        actor_id=actor_id,
        module="mi",
        tabel="mini_product",
        record_id=product.id,
        actie="mini_product_gedearchiveerd",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"gearchiveerd": True},
        nieuwe_waarde={"gearchiveerd": False, "reden": reden},
        administratie_id=product.administratie_id,
    )


# --- lezen ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProductData:
    id: uuid.UUID
    administratie_id: uuid.UUID
    vendor_id: uuid.UUID
    leverancier_naam: str | None
    artikelcode: str | None
    omschrijving: str
    weergavenaam: str | None
    eenheid: str | None
    nieuw_controleren: bool
    gearchiveerd: bool
    stand: str
    laatste_mutatie_op: str | None
    aangemaakt_op: str


@dataclass(frozen=True)
class ProductLijst:
    items: list[ProductData]
    totaal: int
    pagina: int
    per_pagina: int
    nieuw_controleren: int
    ingeschakeld: bool


def _product_data(p: MiniProduct, stand: Decimal, laatste: datetime | None) -> ProductData:
    return ProductData(
        id=p.id,
        administratie_id=p.administratie_id,
        vendor_id=p.vendor_id,
        leverancier_naam=p.leverancier_naam,
        artikelcode=p.artikelcode,
        omschrijving=p.omschrijving,
        weergavenaam=p.weergavenaam,
        eenheid=p.eenheid,
        nieuw_controleren=p.nieuw_controleren,
        gearchiveerd=p.gearchiveerd,
        stand=als_aantal_str(stand),
        laatste_mutatie_op=laatste.isoformat() if laatste else None,
        aangemaakt_op=p.aangemaakt_op.isoformat(),
    )


def _tel_nieuw(session: Session, administratie_id: uuid.UUID) -> int:
    return int(
        session.scalar(
            select(func.count()).where(
                MiniProduct.administratie_id == administratie_id,
                MiniProduct.nieuw_controleren.is_(True),
                MiniProduct.gearchiveerd.is_(False),
            )
        )
        or 0
    )


def producten(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    q: str = "",
    pagina: int = 1,
    per_pagina: int = PER_PAGINA,
    filter: str = "alle",
) -> ProductLijst:
    """Lijst per administratie (RLS-scope), server-side gezocht/gepagineerd. Filter `alle` = actieve producten,
    `nieuw` = alleen de vlag, `gearchiveerd` = alleen gearchiveerd. Sortering: nieuw eerst, dan omschrijving."""
    if filter not in ("alle", "nieuw", "gearchiveerd"):
        raise OngeldigeInvoer("Onbekend filter — kies alle, nieuw of gearchiveerd")
    per_pagina = max(1, min(per_pagina, MAX_PER_PAGINA))
    pagina = max(1, pagina)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        ingeschakeld = is_ingeschakeld(session, administratie_id)
        query: Select = select(MiniProduct).where(MiniProduct.administratie_id == administratie_id)
        if filter == "gearchiveerd":
            query = query.where(MiniProduct.gearchiveerd.is_(True))
        else:
            query = query.where(MiniProduct.gearchiveerd.is_(False))
            if filter == "nieuw":
                query = query.where(MiniProduct.nieuw_controleren.is_(True))
        if q.strip():
            term = f"%{q.strip()}%"
            query = query.where(
                or_(
                    MiniProduct.omschrijving.ilike(term),
                    MiniProduct.weergavenaam.ilike(term),
                    MiniProduct.leverancier_naam.ilike(term),
                    MiniProduct.artikelcode.ilike(term),
                )
            )
        totaal = int(session.scalar(select(func.count()).select_from(query.subquery())) or 0)
        rijen = session.scalars(
            query.order_by(
                MiniProduct.nieuw_controleren.desc(),
                func.lower(func.coalesce(MiniProduct.weergavenaam, MiniProduct.omschrijving)),
            )
            .offset((pagina - 1) * per_pagina)
            .limit(per_pagina)
        ).all()
        standen = standen_per_product(session, [r.id for r in rijen])
        items = [_product_data(r, *standen[r.id]) for r in rijen]
        nieuw = _tel_nieuw(session, administratie_id)
    return ProductLijst(
        items=items,
        totaal=totaal,
        pagina=pagina,
        per_pagina=per_pagina,
        nieuw_controleren=nieuw,
        ingeschakeld=ingeschakeld,
    )


def product(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, product_id: uuid.UUID) -> ProductData:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        p = _product(session, administratie_id, product_id)
        stand, laatste = standen_per_product(session, [p.id])[p.id]
        return _product_data(p, stand, laatste)


@dataclass(frozen=True)
class MutatieData:
    id: uuid.UUID
    soort: str
    aantal: str
    datum: str
    document_id: str | None
    document_referentie: str | None
    document_leverancier: str | None
    boek_cyclus: int | None
    project_id: str | None
    project_naam: str | None
    gemeld_door_naam: str | None
    toelichting: str | None
    aangemaakt_op: str


@dataclass(frozen=True)
class LogLijst:
    items: list[MutatieData]
    totaal: int
    pagina: int
    per_pagina: int


def _mutatie_data(session: Session, administratie_id: uuid.UUID, rijen: list[MiniVoorraadMutatie]) -> list[MutatieData]:
    """Verrijking in drie gebatchte lookups (geen N+1): boekvoorstel (referentie + vendor), projectnaam, melder."""
    document_ids = {m.document_id for m in rijen if m.document_id}
    voorstellen: dict[uuid.UUID, Boekvoorstel] = {}
    vendor_namen: dict[uuid.UUID, str | None] = {}
    if document_ids:
        for bv in session.scalars(select(Boekvoorstel).where(Boekvoorstel.document_id.in_(document_ids))):
            voorstellen[bv.document_id] = bv
        vendor_ids = {bv.vendor_id for bv in voorstellen.values() if bv.vendor_id}
        if vendor_ids:
            for v in session.scalars(
                select(VendorCache).where(
                    VendorCache.administratie_id == administratie_id, VendorCache.id.in_(vendor_ids)
                )
            ):
                vendor_namen[v.id] = v.naam
    project_ids = {m.project_id for m in rijen if m.project_id}
    project_namen: dict[uuid.UUID, str | None] = {}
    if project_ids:
        for p in session.scalars(
            select(ProjectCache).where(
                ProjectCache.administratie_id == administratie_id, ProjectCache.id.in_(project_ids)
            )
        ):
            project_namen[p.id] = p.naam
    melder_ids = {m.gemeld_door for m in rijen if m.gemeld_door}
    melder_namen: dict[uuid.UUID, str] = {}
    if melder_ids:
        for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_(melder_ids))):
            melder_namen[g.id] = g.naam
    uit: list[MutatieData] = []
    for m in rijen:
        bv = voorstellen.get(m.document_id) if m.document_id else None
        uit.append(
            MutatieData(
                id=m.id,
                soort=m.soort,
                aantal=als_aantal_str(m.aantal),
                datum=m.datum.isoformat(),
                document_id=str(m.document_id) if m.document_id else None,
                document_referentie=bv.referentie if bv else None,
                document_leverancier=(vendor_namen.get(bv.vendor_id) if bv and bv.vendor_id else None),
                boek_cyclus=m.boek_cyclus,
                project_id=str(m.project_id) if m.project_id else None,
                project_naam=project_namen.get(m.project_id) if m.project_id else None,
                gemeld_door_naam=melder_namen.get(m.gemeld_door) if m.gemeld_door else None,
                toelichting=m.toelichting,
                aangemaakt_op=m.aangemaakt_op.isoformat(),
            )
        )
    return uit


def log(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    product_id: uuid.UUID,
    pagina: int = 1,
    per_pagina: int = PER_PAGINA,
) -> LogLijst:
    """Voorraadlog per product: append-only, nieuwste eerst, 25/pagina."""
    per_pagina = max(1, min(per_pagina, MAX_PER_PAGINA))
    pagina = max(1, pagina)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        p = _product(session, administratie_id, product_id)
        basis = select(MiniVoorraadMutatie).where(MiniVoorraadMutatie.product_id == p.id)
        totaal = int(session.scalar(select(func.count()).select_from(basis.subquery())) or 0)
        rijen = session.scalars(
            basis.order_by(MiniVoorraadMutatie.aangemaakt_op.desc(), MiniVoorraadMutatie.id.desc())
            .offset((pagina - 1) * per_pagina)
            .limit(per_pagina)
        ).all()
        items = _mutatie_data(session, administratie_id, list(rijen))
    return LogLijst(items=items, totaal=totaal, pagina=pagina, per_pagina=per_pagina)


@dataclass(frozen=True)
class StandData:
    ingeschakeld: bool
    producten: int
    nieuw_controleren: int


def stand(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> StandData:
    """Tellers voor tab/badge: actieve producten + vlag-teller. Uit = alles 0 (geen 409 — de UI toont dan niets)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        ingeschakeld = is_ingeschakeld(session, administratie_id)
        if not ingeschakeld:
            return StandData(ingeschakeld=False, producten=0, nieuw_controleren=0)
        n = int(
            session.scalar(
                select(func.count()).where(
                    MiniProduct.administratie_id == administratie_id, MiniProduct.gearchiveerd.is_(False)
                )
            )
            or 0
        )
        return StandData(ingeschakeld=True, producten=n, nieuw_controleren=_tel_nieuw(session, administratie_id))


# --- handelingen zónder standmutatie ------------------------------------------------------------------------


def bevestig_naam(
    *, administratie_id: uuid.UUID, actor_id: uuid.UUID, product_id: uuid.UUID, weergavenaam: str
) -> ProductData:
    """ "Naam bevestigen" (⑦): wijzigt UITSLUITEND de weergavenaam en zet de vlag uit; de factuurtekst blijft de
    sleutel. Mag gelijk zijn aan de omschrijving (= "de factuurtekst klopt")."""
    naam = " ".join(weergavenaam.split()).strip()
    if not naam:
        raise OngeldigeInvoer("Weergavenaam mag niet leeg zijn")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_ingeschakeld(session, administratie_id)
        p = _product(session, administratie_id, product_id)
        oud = {"weergavenaam": p.weergavenaam, "nieuw_controleren": p.nieuw_controleren}
        p.weergavenaam = naam[:200]
        p.nieuw_controleren = False
        p.naam_bevestigd_op = datetime.now(UTC)
        p.naam_bevestigd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="mini_product",
            record_id=p.id,
            actie="mini_product_naam_bevestigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"weergavenaam": p.weergavenaam, "nieuw_controleren": False, "omschrijving": p.omschrijving},
            administratie_id=administratie_id,
        )
        session.flush()
        s, laatste = standen_per_product(session, [p.id])[p.id]
        return _product_data(p, s, laatste)


def archiveer(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, product_id: uuid.UUID, reden: str) -> ProductData:
    """Archiveren (⑥, Beheerder in de router): kolom + reden in de audit; de stand en het log blijven staan.
    Verschijnt het product later opnieuw op een factuur, dan herleeft het (instroom.py)."""
    if len(reden.strip()) < MIN_REDEN_LENGTE:
        raise OngeldigeInvoer(f"Reden is verplicht (minimaal {MIN_REDEN_LENGTE} tekens)")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_ingeschakeld(session, administratie_id)
        p = _product(session, administratie_id, product_id)
        if p.gearchiveerd:
            raise OngeldigeInvoer("Dit product is al gearchiveerd")
        p.gearchiveerd = True
        p.gearchiveerd_op = datetime.now(UTC)
        p.gearchiveerd_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="mini_product",
            record_id=p.id,
            actie="mini_product_gearchiveerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"gearchiveerd": False},
            nieuwe_waarde={"gearchiveerd": True, "reden": reden.strip()},
            administratie_id=administratie_id,
        )
        session.flush()
        s, laatste = standen_per_product(session, [p.id])[p.id]
        return _product_data(p, s, laatste)


def dearchiveer(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, product_id: uuid.UUID) -> ProductData:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_ingeschakeld(session, administratie_id)
        p = _product(session, administratie_id, product_id)
        if not p.gearchiveerd:
            raise OngeldigeInvoer("Dit product is niet gearchiveerd")
        _dearchiveer(session, p, actor_id=actor_id, reden="gedearchiveerd door Beheerder")
        session.flush()
        s, laatste = standen_per_product(session, [p.id])[p.id]
        return _product_data(p, s, laatste)


def meld_beschadiging(
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    product_id: uuid.UUID,
    aantal: str,
    project_id: uuid.UUID,
    datum: date,
    toelichting: str | None,
) -> MutatieData:
    """Beschadigingsmelding (⑧): een GEBEURTENIS — wie (actor = gemeld_door), waar (project, verplicht en actief in
    `project_cache` van deze administratie), wanneer (datum) — vastgelegd als append-only mutatie −aantal. Nooit een
    getal-correctie: er is geen route om een stand te zetten, alleen deze registratie."""
    hoeveel = parse_aantal(aantal)
    if datum > vandaag_nl():
        raise OngeldigeInvoer("De datum van een beschadiging kan niet in de toekomst liggen")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_ingeschakeld(session, administratie_id)
        p = _product(session, administratie_id, product_id)
        if p.gearchiveerd:
            raise OngeldigeInvoer("Dit product is gearchiveerd — dearchiveer het eerst (Beheerder)")
        project = session.get(ProjectCache, (project_id, administratie_id))  # samengestelde PK (id, administratie)
        if (
            project is None
            or project.administratie_id != administratie_id
            or project.verdwenen_uit_bron_op is not None
            or project.is_actief is False
        ):
            raise GeenActiefProject(
                "Kies een actief project van deze administratie — een beschadiging hangt altijd aan een project"
            )
        m = MiniVoorraadMutatie(
            administratie_id=administratie_id,
            product_id=p.id,
            soort=SOORT_BESCHADIGING,
            aantal=-hoeveel,
            datum=datum,
            project_id=project.id,
            gemeld_door=actor_id,
            toelichting=(toelichting or "").strip()[:1000] or None,
            aangemaakt_door=actor_id,
        )
        session.add(m)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="mi",
            tabel="mini_voorraad_mutatie",
            record_id=m.id,
            actie="mini_voorraad_beschadiging_gemeld",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "product_id": str(p.id),
                "omschrijving": p.omschrijving,
                "aantal": als_aantal_str(m.aantal),
                "project_id": str(project.id),
                "project_naam": project.naam,
                "datum": datum.isoformat(),
                "toelichting": m.toelichting,
            },
            administratie_id=administratie_id,
        )
        return _mutatie_data(session, administratie_id, [m])[0]


# --- F5: materiaallijst (planning/transport) + virtuele artikelgroep (voorraad-aansluiting) ------------------


@dataclass(frozen=True)
class MateriaallijstItem:
    id: uuid.UUID
    naam: str
    eenheid: str | None
    mini_voorraad_stand: str
    leverancier_naam: str | None
    artikelcode: str | None


def materiaallijst(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> list[MateriaallijstItem]:
    """Read-only items voor de materiaallijst-dialoog: actieve mini-producten mét stand > 0. Eigen leesroute (geen
    injectie in de per-leverancier-catalogus van `materiaal` — die is gekoppeld aan een materiaal-leverancier en
    zijn product-ids zijn FK-doelen van bestellingen/transport; zie contract_afwijkingen_F)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _vereis_ingeschakeld(session, administratie_id)
        rijen = session.scalars(
            select(MiniProduct).where(
                MiniProduct.administratie_id == administratie_id, MiniProduct.gearchiveerd.is_(False)
            )
        ).all()
        standen = standen_per_product(session, [r.id for r in rijen])
        items = [
            MateriaallijstItem(
                id=r.id,
                naam=r.weergavenaam or r.omschrijving,
                eenheid=r.eenheid,
                mini_voorraad_stand=als_aantal_str(standen[r.id][0]),
                leverancier_naam=r.leverancier_naam,
                artikelcode=r.artikelcode,
            )
            for r in rijen
            if standen[r.id][0] > 0
        ]
    items.sort(key=lambda i: i.naam.lower())
    return items


@dataclass(frozen=True)
class VirtueleGroep:
    """Aggregaat voor de voorraad-aansluiting (F5): begin (Σ vóór `van`), in (instroom in de periode), uit
    (uitstroom + beschadiging + storno in de periode, als positief getal), theoretisch = begin + in − uit."""

    artikelgroep_id: uuid.UUID
    naam: str
    begin: Decimal
    inkoop: Decimal
    verkoop: Decimal
    theoretisch: Decimal
    regels_in: int
    regels_uit: int
    producten: int = 0
    bron: str = field(default="mini_voorraad")


def virtuele_groep(session: Session, *, administratie_id: uuid.UUID, van: date, tot: date) -> VirtueleGroep | None:
    """None als de opt-in uit staat. Twee aggregaatqueries — nooit alle mutaties in Python."""
    if not is_ingeschakeld(session, administratie_id):
        return None
    m = MiniVoorraadMutatie
    in_periode = m.datum.between(van, tot)
    positief = m.soort == SOORT_INSTROOM
    negatief = m.soort.in_([SOORT_STORNO, SOORT_UITSTROOM, SOORT_BESCHADIGING])
    rij = session.execute(
        select(
            func.coalesce(func.sum(case((m.datum < van, m.aantal), else_=0)), 0),
            func.coalesce(func.sum(case((in_periode & positief, m.aantal), else_=0)), 0),
            func.coalesce(func.sum(case((in_periode & negatief, -m.aantal), else_=0)), 0),
            func.coalesce(func.sum(case((in_periode & positief, 1), else_=0)), 0),
            func.coalesce(func.sum(case((in_periode & negatief, 1), else_=0)), 0),
        ).where(m.administratie_id == administratie_id, m.datum <= tot)
    ).one()
    producten_n = int(
        session.scalar(
            select(func.count()).where(
                MiniProduct.administratie_id == administratie_id, MiniProduct.gearchiveerd.is_(False)
            )
        )
        or 0
    )
    begin = Decimal(rij[0]).quantize(_DUIZENDSTE)
    inkoop = Decimal(rij[1]).quantize(_DUIZENDSTE)
    verkoop = Decimal(rij[2]).quantize(_DUIZENDSTE)
    return VirtueleGroep(
        artikelgroep_id=virtuele_groep_id(administratie_id),
        naam=VIRTUELE_GROEP_NAAM,
        begin=begin,
        inkoop=inkoop,
        verkoop=verkoop,
        theoretisch=(begin + inkoop - verkoop).quantize(_DUIZENDSTE),
        regels_in=int(rij[3]),
        regels_uit=int(rij[4]),
        producten=producten_n,
    )
