"""Intercompany-relaties — afleiding, leesbron en Beheerder-mutaties (blok A opdracht 16-09).

Afleiding (`leid_relaties_af`): per actieve administratie A worden crediteuren (vendor_cache + `crediteur_kenmerk`
incl. RLZ-KvK-fallback) en debiteuren (RLZ `Customers` live, één gepagineerde leesroute per administratie; Odoo
`res.partner` mét `customer_rank > 0`) gematcht tegen `administratie_identiteit` van ÁNDERE administraties, in de
volgorde kvk > btw > naam_norm (exact gelijk). Een treffer wordt een `intercompany_relatie`-rij (A, entity_in_a, B) mét
`richting` vanuit A ('crediteur' = B levert aan A; 'debiteur' = A verkoopt aan B), status 'afgeleid', bron 'afgeleid'.
Bestaande actieve `intercompany_tegenpartij`-rijen van de doorbelasting (bron-kant = doel_customer_guid → 'debiteur',
B = mapping.doel_administratie; doel-kant = crediteur in de doeladministratie → 'crediteur', B = mapping.administratie)
worden overgenomen als basis 'doorbelasting', status 'bevestigd'. Rijen met bron 'mens' worden NOOIT aangeraakt.

Actief voor de factuurmatch (`actieve_paren`): status 'bevestigd' óf (status 'afgeleid' én basis ≠ 'naam') — een
naam-only-treffer is "vermoedelijk IC, bevestigen" en telt pas mee ná een Beheerder-bevestiging (beslispunt 3, default).

De doorbelasting-IC-vlag (`intercompany_entity_guids` / `intercompany_tegenpartij` / `is_intercompany_leverancier`)
leeft sinds 16-09 hier met EXACT de oude semantiek (actieve `intercompany_tegenpartij`-rijen in de administratie van het
document); `app/doorbelasting/intercompany.py` her-exporteert ze — gedrag identiek, afnemers ongewijzigd."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.backends.registry import Backend, backend_voor
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.documenten import crediteur_kenmerk
from app.doorbelasting.models import DoorbelastingMapping, IntercompanyTegenpartij
from app.extractie.btw_nummer import normaliseer_kvk_nummer
from app.intercompany import identiteit as identiteit_module
from app.intercompany.models import BASES, STATUSSEN, AdministratieIdentiteit, IntercompanyRelatie
from app.rlz.credentials import GeenRlzCredentials
from app.sync.models import VendorCache

AUDIT_ACTIE = "intercompany_relatie_gewijzigd"
_MODULE = "boekhouding"
# Rangorde van de basis: een sterkere basis wint bij herafleiding, nooit een zwakkere over een sterkere.
_BASIS_RANG = {"doorbelasting": 0, "kvk": 1, "btw": 2, "naam": 3}


class IntercompanyFout(Exception):
    """Basisfout — de router vertaalt naar 404/409/403."""


class RelatieOnbekend(IntercompanyFout):
    pass


class GeenBeheerder(IntercompanyFout):
    """Mens-mutaties op intercompany-relaties zijn Beheerder-only (server-side poort, los van de router)."""


# --- oude semantiek doorbelasting-IC-vlag (verplaatst uit doorbelasting/intercompany.py, gedrag identiek) ----------

OVERGESLAGEN_REDEN_INTERCOMPANY = "intercompany"


def intercompany_entity_guids(session: Session, *, administratie_id: uuid.UUID) -> set[uuid.UUID]:
    """De entity-GUID's die in deze administratie als intercompany gelden (alleen actieve rijen)."""
    return {
        rij.entity_guid
        for rij in session.scalars(
            select(IntercompanyTegenpartij).where(
                IntercompanyTegenpartij.administratie_id == administratie_id,
                IntercompanyTegenpartij.actief.is_(True),
            )
        )
    }


def intercompany_tegenpartij(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None
) -> IntercompanyTegenpartij | None:
    """De actieve IC-rij voor deze crediteur in deze administratie, of None. `vendor_id` None = None (geen
    leverancier herkend → nooit intercompany)."""
    if vendor_id is None:
        return None
    return session.scalars(
        select(IntercompanyTegenpartij).where(
            IntercompanyTegenpartij.administratie_id == administratie_id,
            IntercompanyTegenpartij.entity_guid == vendor_id,
            IntercompanyTegenpartij.actief.is_(True),
        )
    ).first()


def is_intercompany_leverancier(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> bool:
    """True als deze crediteur in déze administratie een actieve IC-rij heeft — dé definitie van
    "leverancier met IC-vlag" voor alle afnemers."""
    return intercompany_tegenpartij(session, administratie_id=administratie_id, vendor_id=vendor_id) is not None


# --- datastructuren ------------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Paar:
    """Eén actieve IC-relatie zoals de factuurmatch 'm nodig heeft. `entity_in_b` = de spiegel-entity in B (de rij
    (B, entity, A) met tegengestelde richting) als die bestaat, anders None."""

    administratie_a_id: uuid.UUID
    entity_in_a: uuid.UUID
    administratie_b_id: uuid.UUID
    richting: str
    basis: str
    status: str
    entity_in_b: uuid.UUID | None = None


@dataclass(frozen=True)
class RelatieInfo:
    id: uuid.UUID
    administratie_a_id: uuid.UUID
    administratie_a_naam: str
    entity_in_a: uuid.UUID
    entity_naam: str | None
    administratie_b_id: uuid.UUID
    administratie_b_naam: str
    richting: str
    basis: str
    status: str
    bron: str
    reden: str | None
    gewijzigd_op: datetime | None
    actief: bool


@dataclass
class AfleidUitkomst:
    administraties: int = 0
    crediteuren_bekeken: int = 0
    debiteuren_bekeken: int = 0
    relaties_nieuw: int = 0
    relaties_bijgewerkt: int = 0
    relaties_ongewijzigd: int = 0
    mens_rijen_overgeslagen: int = 0
    doorbelasting_overgenomen: int = 0
    per_basis: dict[str, int] = field(default_factory=dict)
    overgeslagen: list[tuple[uuid.UUID, str]] = field(default_factory=list)
    fouten: list[tuple[uuid.UUID, str]] = field(default_factory=list)

    def as_dict(self) -> dict[str, Any]:
        return {
            "administraties": self.administraties,
            "crediteuren_bekeken": self.crediteuren_bekeken,
            "debiteuren_bekeken": self.debiteuren_bekeken,
            "relaties_nieuw": self.relaties_nieuw,
            "relaties_bijgewerkt": self.relaties_bijgewerkt,
            "relaties_ongewijzigd": self.relaties_ongewijzigd,
            "mens_rijen_overgeslagen": self.mens_rijen_overgeslagen,
            "doorbelasting_overgenomen": self.doorbelasting_overgenomen,
            "per_basis": dict(self.per_basis),
            "overgeslagen": [f"{aid}: {m}" for aid, m in self.overgeslagen],
            "fouten": [f"{aid}: {m}" for aid, m in self.fouten],
        }


@dataclass(frozen=True)
class _Kandidaat:
    administratie_a_id: uuid.UUID
    entity_in_a: uuid.UUID
    entity_naam: str | None
    administratie_b_id: uuid.UUID
    richting: str
    basis: str


@dataclass(frozen=True)
class _Relatiepartij:
    """Eén crediteur of debiteur in A zoals de matcher 'm ziet."""

    entity_id: uuid.UUID
    naam: str | None
    kvk: str | None
    btw: str | None


# --- identiteiten-index -------------------------------------------------------------------------------------------


class _Index:
    def __init__(self, identiteiten: Iterable[AdministratieIdentiteit]) -> None:
        self.kvk: dict[str, set[uuid.UUID]] = {}
        self.btw: dict[str, set[uuid.UUID]] = {}
        self.naam: dict[str, set[uuid.UUID]] = {}
        for i in identiteiten:
            if i.kvk:
                self.kvk.setdefault(i.kvk, set()).add(i.administratie_id)
            if i.btw:
                self.btw.setdefault(i.btw.upper(), set()).add(i.administratie_id)
            if i.naam_norm:
                self.naam.setdefault(i.naam_norm, set()).add(i.administratie_id)

    def match(self, partij: _Relatiepartij, *, eigen: uuid.UUID) -> tuple[str, set[uuid.UUID]] | None:
        """kvk > btw > naam — de eerste basis mét een treffer bij een ANDERE administratie wint."""
        if partij.kvk:
            treffers = self.kvk.get(partij.kvk, set()) - {eigen}
            if treffers:
                return "kvk", treffers
        if partij.btw:
            treffers = self.btw.get(partij.btw.upper(), set()) - {eigen}
            if treffers:
                return "btw", treffers
        norm = identiteit_module.naam_norm(partij.naam)
        if norm:
            treffers = self.naam.get(norm, set()) - {eigen}
            if treffers:
                return "naam", treffers
        return None


# --- lezers per administratie --------------------------------------------------------------------------------------


def _crediteuren(administratie_id: uuid.UUID) -> list[_Relatiepartij]:
    with scoped_session(administratie_id) as session:
        kenmerken = crediteur_kenmerk.kenmerken_per_vendor(session, administratie_id=administratie_id)
        rijen = list(
            session.scalars(
                select(VendorCache).where(
                    VendorCache.administratie_id == administratie_id, VendorCache.verdwenen_uit_bron_op.is_(None)
                )
            )
        )
        uit: list[_Relatiepartij] = []
        for rij in rijen:
            k = kenmerken.get(rij.id)
            uit.append(
                _Relatiepartij(
                    entity_id=rij.id,
                    naam=rij.naam,
                    kvk=k.kvk_nummer if k else None,
                    btw=(k.btw_nummer.upper() if k and k.btw_nummer else None),
                )
            )
        return uit


def _debiteuren_rlz(client: Any, *, per_pagina: int = 500, max_paginas: int = 20) -> list[_Relatiepartij]:
    """`Customers` gepagineerd ($top/$skip) — begrensd zodat een webfilter-blokkering nooit uit een runaway-lus komt."""
    uit: list[_Relatiepartij] = []
    for pagina in range(max_paginas):
        antwoord = client.get(
            "Customers", params={"$top": str(per_pagina), "$skip": str(pagina * per_pagina), "$orderby": "id asc"}
        )
        deel = antwoord.get("value", []) if isinstance(antwoord, dict) else list(antwoord or [])
        for rij in deel:
            try:
                entity_id = uuid.UUID(str(rij.get("id")))
            except (ValueError, TypeError, AttributeError):
                continue
            uit.append(
                _Relatiepartij(
                    entity_id=entity_id,
                    naam=rij.get("Name") or rij.get("SearchName"),
                    kvk=normaliseer_kvk_nummer(str(rij.get("ChamberOfCommerceNumber") or "")),
                    btw=None,
                )
            )
        if len(deel) < per_pagina:
            break
    return uit


def _debiteuren_odoo(client: Any) -> list[_Relatiepartij]:
    from app.odoo.ids import odoo_uuid

    rijen = client.search_read_alles(
        "res.partner", [["customer_rank", ">", 0]], ["id", "name", "vat", "company_registry"]
    )
    uit: list[_Relatiepartij] = []
    for rij in rijen:
        uit.append(
            _Relatiepartij(
                entity_id=odoo_uuid(client.company_id, "res.partner", int(rij["id"])),
                naam=rij.get("name"),
                kvk=normaliseer_kvk_nummer(str(rij.get("company_registry") or "")),
                btw=identiteit_module.btw_norm(str(rij.get("vat") or "") or None),
            )
        )
    return uit


def _debiteuren(administratie_id: uuid.UUID) -> list[_Relatiepartij]:
    if backend_voor(administratie_id) is Backend.ODOO:
        client = identiteit_module.odoo_client_voor_lezen(administratie_id)
        try:
            return _debiteuren_odoo(client)
        finally:
            client.close()
    client = identiteit_module.rlz_client_voor(administratie_id)
    try:
        return _debiteuren_rlz(client)
    finally:
        client.close()


# --- doorbelasting-overname ----------------------------------------------------------------------------------------


def _doorbelasting_kandidaten(administratie_ids: list[uuid.UUID], uitkomst: AfleidUitkomst) -> list[_Kandidaat]:
    """Actieve `intercompany_tegenpartij`-rijen → kandidaten mét basis 'doorbelasting'. De mapping-rijen leven in de
    scope van de BRON-administratie (RLS), dus eerst alle mappings verzamelen, dan per administratie de IC-rijen
    koppelen (mapping_id eerst, anders (bron, doel_customer_guid))."""
    mappings: dict[uuid.UUID, DoorbelastingMapping] = {}
    for aid in administratie_ids:
        with scoped_session(aid) as session:
            for m in session.scalars(select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == aid)):
                session.expunge(m)
                mappings[m.id] = m
    per_bron_customer = {(m.administratie_id, m.doel_customer_guid): m for m in mappings.values()}
    kandidaten: list[_Kandidaat] = []
    for aid in administratie_ids:
        with scoped_session(aid) as session:
            rijen = list(
                session.scalars(
                    select(IntercompanyTegenpartij).where(
                        IntercompanyTegenpartij.administratie_id == aid, IntercompanyTegenpartij.actief.is_(True)
                    )
                )
            )
            session.expunge_all()
        for rij in rijen:
            m = mappings.get(rij.mapping_id) if rij.mapping_id else None
            if m is None:
                m = per_bron_customer.get((aid, rij.entity_guid))
            if m is None or not m.actief or not m.intercompany:
                continue
            if m.administratie_id == aid and m.doel_customer_guid == rij.entity_guid:
                if m.doel_administratie_id is None or m.doel_administratie_id == aid:
                    continue
                kandidaten.append(
                    _Kandidaat(aid, rij.entity_guid, rij.naam, m.doel_administratie_id, "debiteur", "doorbelasting")
                )
            elif m.doel_administratie_id == aid and m.administratie_id != aid:
                kandidaten.append(
                    _Kandidaat(aid, rij.entity_guid, rij.naam, m.administratie_id, "crediteur", "doorbelasting")
                )
    uitkomst.doorbelasting_overgenomen = len(kandidaten)
    return kandidaten


# --- afleiding -----------------------------------------------------------------------------------------------------


def leid_relaties_af(administratie_ids: Iterable[uuid.UUID] | None = None) -> AfleidUitkomst:
    """Herafleiding voor de gegeven (default: alle actieve) administraties. Matcht ALTIJD tegen álle opgeslagen
    identiteiten; schrijft alleen rijen waarvan A in de selectie zit. Mens-rijen blijven ongemoeid; een afgeleide rij
    die niet meer afgeleid wordt blijft staan (niets verdwijnt stil — de Beheerder kan 'm uitsluiten)."""
    uitkomst = AfleidUitkomst()
    administraties = identiteit_module.actieve_administraties(administratie_ids)
    uitkomst.administraties = len(administraties)
    index = _Index(identiteit_module.alle_identiteiten().values())
    kandidaten: list[_Kandidaat] = []

    for aid, _naam in administraties:
        try:
            crediteuren = _crediteuren(aid)
        except Exception as exc:  # noqa: BLE001
            uitkomst.fouten.append((aid, f"crediteuren: {type(exc).__name__}: {exc}"))
            crediteuren = []
        uitkomst.crediteuren_bekeken += len(crediteuren)
        for partij in crediteuren:
            treffer = index.match(partij, eigen=aid)
            if treffer is None:
                continue
            basis, b_ids = treffer
            for b in b_ids:
                kandidaten.append(_Kandidaat(aid, partij.entity_id, partij.naam, b, "crediteur", basis))
        try:
            debiteuren = _debiteuren(aid)
        except GeenRlzCredentials as exc:
            uitkomst.overgeslagen.append((aid, f"debiteuren niet gelezen — geen credential: {exc}"))
            debiteuren = []
        except Exception as exc:  # noqa: BLE001
            uitkomst.fouten.append((aid, f"debiteuren: {type(exc).__name__}: {exc}"))
            debiteuren = []
        uitkomst.debiteuren_bekeken += len(debiteuren)
        for partij in debiteuren:
            treffer = index.match(partij, eigen=aid)
            if treffer is None:
                continue
            basis, b_ids = treffer
            for b in b_ids:
                kandidaten.append(_Kandidaat(aid, partij.entity_id, partij.naam, b, "debiteur", basis))

    kandidaten.extend(_doorbelasting_kandidaten([aid for aid, _ in administraties], uitkomst))

    # Per (A, entity, B) de sterkste basis; doorbelasting > kvk > btw > naam.
    beste: dict[tuple[uuid.UUID, uuid.UUID, uuid.UUID], _Kandidaat] = {}
    for k in kandidaten:
        sleutel = (k.administratie_a_id, k.entity_in_a, k.administratie_b_id)
        huidig = beste.get(sleutel)
        if huidig is None or _BASIS_RANG[k.basis] < _BASIS_RANG[huidig.basis]:
            beste[sleutel] = k

    with scoped_session(None) as session:
        for sleutel, k in beste.items():
            rij = session.scalars(
                select(IntercompanyRelatie).where(
                    IntercompanyRelatie.administratie_a_id == sleutel[0],
                    IntercompanyRelatie.entity_in_a == sleutel[1],
                    IntercompanyRelatie.administratie_b_id == sleutel[2],
                )
            ).one_or_none()
            status = "bevestigd" if k.basis == "doorbelasting" else "afgeleid"
            uitkomst.per_basis[k.basis] = uitkomst.per_basis.get(k.basis, 0) + 1
            if rij is None:
                session.add(
                    IntercompanyRelatie(
                        administratie_a_id=k.administratie_a_id,
                        entity_in_a=k.entity_in_a,
                        entity_naam=k.entity_naam,
                        administratie_b_id=k.administratie_b_id,
                        richting=k.richting,
                        basis=k.basis,
                        status=status,
                        bron="afgeleid",
                    )
                )
                uitkomst.relaties_nieuw += 1
                continue
            if rij.bron == "mens":
                uitkomst.mens_rijen_overgeslagen += 1
                continue
            # Afgeleide rij: nooit een zwakkere basis over een sterkere; naam volgt de bron.
            nieuwe_basis = k.basis if _BASIS_RANG[k.basis] <= _BASIS_RANG[rij.basis] else rij.basis
            nieuwe_status = "bevestigd" if nieuwe_basis == "doorbelasting" else rij.status
            if (rij.basis, rij.status, rij.richting, rij.entity_naam) == (
                nieuwe_basis,
                nieuwe_status,
                k.richting,
                k.entity_naam,
            ):
                uitkomst.relaties_ongewijzigd += 1
                continue
            rij.basis = nieuwe_basis
            rij.status = nieuwe_status
            rij.richting = k.richting
            rij.entity_naam = k.entity_naam
            uitkomst.relaties_bijgewerkt += 1
    return uitkomst


# --- lezen ---------------------------------------------------------------------------------------------------------


def is_actief(status: str, basis: str) -> bool:
    return status == "bevestigd" or (status == "afgeleid" and basis != "naam")


def actieve_paren() -> list[Paar]:
    """Alle actieve relaties als `Paar`, mét de spiegel-entity in B als die bekend is."""
    with scoped_session(None) as session:
        rijen = list(session.scalars(select(IntercompanyRelatie)))
        session.expunge_all()
    spiegel: dict[tuple[uuid.UUID, uuid.UUID, str], uuid.UUID] = {}
    for r in rijen:
        spiegel[(r.administratie_a_id, r.administratie_b_id, r.richting)] = r.entity_in_a
    paren: list[Paar] = []
    for r in rijen:
        if not is_actief(r.status, r.basis):
            continue
        tegengesteld = "crediteur" if r.richting == "debiteur" else "debiteur"
        paren.append(
            Paar(
                administratie_a_id=r.administratie_a_id,
                entity_in_a=r.entity_in_a,
                administratie_b_id=r.administratie_b_id,
                richting=r.richting,
                basis=r.basis,
                status=r.status,
                entity_in_b=spiegel.get((r.administratie_b_id, r.administratie_a_id, tegengesteld)),
            )
        )
    return paren


def _namen(session: Session) -> dict[uuid.UUID, str]:
    return {r[0]: r[1] for r in session.execute(select(Administratie.id, Administratie.naam)).all()}


def _info(r: IntercompanyRelatie, namen: dict[uuid.UUID, str]) -> RelatieInfo:
    return RelatieInfo(
        id=r.id,
        administratie_a_id=r.administratie_a_id,
        administratie_a_naam=namen.get(r.administratie_a_id, str(r.administratie_a_id)),
        entity_in_a=r.entity_in_a,
        entity_naam=r.entity_naam,
        administratie_b_id=r.administratie_b_id,
        administratie_b_naam=namen.get(r.administratie_b_id, str(r.administratie_b_id)),
        richting=r.richting,
        basis=r.basis,
        status=r.status,
        bron=r.bron,
        reden=r.reden,
        gewijzigd_op=r.gewijzigd_op,
        actief=is_actief(r.status, r.basis),
    )


def relaties_voor_administratie(administratie_id: uuid.UUID | None = None) -> list[RelatieInfo]:
    """Alle relaties (kantoorbreed) of alleen die waarin de administratie als A óf B voorkomt."""
    with scoped_session(None) as session:
        q = select(IntercompanyRelatie)
        if administratie_id is not None:
            q = q.where(
                (IntercompanyRelatie.administratie_a_id == administratie_id)
                | (IntercompanyRelatie.administratie_b_id == administratie_id)
            )
        namen = _namen(session)
        rijen = list(session.scalars(q))
        infos = [_info(r, namen) for r in rijen]
    infos.sort(
        key=lambda i: (i.administratie_a_naam.lower(), i.administratie_b_naam.lower(), (i.entity_naam or "").lower())
    )
    return infos


# --- Beheerder-mutaties ----------------------------------------------------------------------------------------------


def vereis_beheerder(session: Session, actor_id: uuid.UUID) -> None:
    """Server-side poort los van de router (CLI's en services gebruiken dezelfde)."""
    gebruiker = session.get(Gebruiker, actor_id)
    if gebruiker is None or gebruiker.rol != GebruikerRol.BEHEERDER:
        raise GeenBeheerder("Alleen een Beheerder mag intercompany-relaties bevestigen of uitsluiten.")


def zet_status(relatie_id: uuid.UUID, *, status: str, reden: str | None, actor_id: uuid.UUID) -> RelatieInfo:
    """'bevestigd' / 'uitgesloten' = mens-besluit (bron 'mens', reden verplicht bij uitsluiten); 'afgeleid' = terug
    naar het systeem (bron 'afgeleid', de volgende afleiding beheert de rij weer). Audit oud→nieuw op administratie A.
    """
    if status not in STATUSSEN:
        raise IntercompanyFout(f"Onbekende status: {status}")
    reden_schoon = " ".join((reden or "").split()) or None
    if status == "uitgesloten" and not reden_schoon:
        raise IntercompanyFout("Uitsluiten vereist een reden.")
    with scoped_session(None) as session:
        vereis_beheerder(session, actor_id)
        rij = session.get(IntercompanyRelatie, relatie_id)
        if rij is None:
            raise RelatieOnbekend(f"Onbekende intercompany-relatie: {relatie_id}")
        administratie_a_id = rij.administratie_a_id
    with scoped_session(administratie_a_id, actor_id=actor_id) as session:
        rij = session.get(IntercompanyRelatie, relatie_id)
        assert rij is not None
        oud = {"status": rij.status, "bron": rij.bron, "reden": rij.reden, "basis": rij.basis}
        rij.status = status
        rij.bron = "afgeleid" if status == "afgeleid" else "mens"
        rij.reden = reden_schoon
        rij.gewijzigd_door = actor_id
        rij.gewijzigd_op = datetime.now(UTC)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="intercompany_relatie",
            record_id=rij.id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"status": rij.status, "bron": rij.bron, "reden": rij.reden, "basis": rij.basis},
            administratie_id=administratie_a_id,
        )
        namen = _namen(session)
        return _info(rij, namen)


__all__ = [
    "AUDIT_ACTIE",
    "BASES",
    "AfleidUitkomst",
    "GeenBeheerder",
    "IntercompanyFout",
    "OVERGESLAGEN_REDEN_INTERCOMPANY",
    "Paar",
    "RelatieInfo",
    "RelatieOnbekend",
    "actieve_paren",
    "intercompany_entity_guids",
    "intercompany_tegenpartij",
    "is_actief",
    "is_intercompany_leverancier",
    "leid_relaties_af",
    "relaties_voor_administratie",
    "vereis_beheerder",
    "zet_status",
]
