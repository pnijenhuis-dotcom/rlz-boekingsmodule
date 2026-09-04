"""Open boekvoorstellen hervertalen bij een overstap RLZ → Odoo (Odoo-slotstuk 04-09, blok C1; besluit Peter 04-09
op beslispunt 3 van "ODOO-AFRONDINGSRUN 04-09 — BLOK A": optie (a), eenmalige expliciete nazorgstap ín de overstap).

De mapping van 0111 vertaalt het GEHEUGEN. Documenten die op het moment van de overstap nog open stonden dragen in
`boekvoorstel_regel` echter nog RLZ-UUID's (ledger_id/taxrate_id/project_id) — de Odoo-adapter zou daar fail-loud op
stranden (`OnbekendeOdooId`). Deze module vertaalt die regels één keer, deterministisch en zichtbaar:

- per regel per veld: waarde None → niets; in de mapping → vertaald mét spoor {van_id, van_code, van_naam, naar_id,
  naar_code, naar_naam}; níét in de mapping → veld LEEG mét spoor {…, naar_id: None, reden} — de controleur kiest
  opnieuw (nooit gokken, nooit stil een RLZ-id laten staan);
- alleen documenten in een niet-terminale status (`mapping.TERMINALE_STATUSSEN`); geboekte/afgewezen/… blijven
  onaangeroerd (historie);
- het spoor staat op `boekvoorstel_regel.overstap_vertaling` (migratie 0112) → chip per veld in het controlescherm; de
  eerstvolgende PUT door de mens schrijft de regels opnieuw zónder spoor (bewust);
- één audit-event `odoo_open_voorstellen_hervertaald` mét tellingen (geen namen-lawine); géén tijdlijn-overgang
  (status wijzigt niet).

Idempotent genoeg voor een herhaalde aanroep: een veld dat al een Odoo-waarde uit de mapping draagt wordt niet
opnieuw aangeraakt. De aanroep zit in `odoo/service.py::koppel_overstap` (zelfde transactie als koppeling + mapping)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document
from app.odoo.mapping import TERMINALE_STATUSSEN, RekeningMapping
from app.odoo.models import OdooRekeningMapping
from app.sync.models import ProjectCache, TaxRateCache

VELD_GROOTBOEK = "grootboek"
VELD_BTW = "btw"
VELD_PROJECT = "project"
VELDEN: tuple[str, ...] = (VELD_GROOTBOEK, VELD_BTW, VELD_PROJECT)
REDEN_GEEN_TEGENHANGER = "geen Odoo-tegenhanger in de mapping bij de overstap"

_KOLOM_PER_VELD = {VELD_GROOTBOEK: "ledger_id", VELD_BTW: "taxrate_id", VELD_PROJECT: "project_id"}


@dataclass(frozen=True)
class HervertaalResultaat:
    """Tellingen van één hervertaling: geraakte documenten/regels en per veld hoeveel vertaald resp. leeggemaakt."""

    documenten: int
    regels: int
    vertaald: dict[str, int] = field(default_factory=dict)
    leeg: dict[str, int] = field(default_factory=dict)


@dataclass(frozen=True)
class _Naam:
    code: str | None
    naam: str | None


class _Namen:
    """Code/naam per UUID voor het spoor: van = RLZ-rij, naar = Odoo-rij. Bronnen: de mapping-rijen zelf (dragen
    rlz_code/rlz_naam/odoo_code/odoo_naam — óók vóór de eerste Odoo-sync) en de caches; ontbrekend = None."""

    def __init__(self, session: Session, administratie_id: uuid.UUID) -> None:
        self._session = session
        self._administratie_id = administratie_id
        self._cache: dict[tuple[str, uuid.UUID], _Naam] = {}
        for rij in session.scalars(
            select(OdooRekeningMapping)
            .where(OdooRekeningMapping.administratie_id == administratie_id)
            .order_by(OdooRekeningMapping.versie)
        ):
            self._cache[(rij.soort, rij.rlz_id)] = _Naam(rij.rlz_code, rij.rlz_naam)
            self._cache[(rij.soort, rij.odoo_lokaal_id)] = _Naam(rij.odoo_code, rij.odoo_naam)

    def voor(self, veld: str, lokaal_id: uuid.UUID) -> _Naam:
        sleutel = (veld, lokaal_id)
        if sleutel in self._cache:
            return self._cache[sleutel]
        naam = self._uit_cache(veld, lokaal_id)
        self._cache[sleutel] = naam
        return naam

    def _uit_cache(self, veld: str, lokaal_id: uuid.UUID) -> _Naam:
        s, aid = self._session, self._administratie_id
        if veld == VELD_GROOTBOEK:
            rij = s.scalars(
                select(Grootboekrekening).where(
                    Grootboekrekening.administratie_id == aid, Grootboekrekening.ledger_id == lokaal_id
                )
            ).first()
            return _Naam(rij.code.strip() if rij and rij.code else None, rij.naam if rij else None)
        if veld == VELD_BTW:
            rij = s.scalars(
                select(TaxRateCache).where(TaxRateCache.administratie_id == aid, TaxRateCache.id == lokaal_id)
            ).first()
            return _Naam(None, rij.naam if rij else None)
        rij = s.scalars(
            select(ProjectCache).where(ProjectCache.administratie_id == aid, ProjectCache.id == lokaal_id)
        ).first()
        return _Naam(None, rij.naam if rij else None)


def _mapping_per_veld(mapping: RekeningMapping) -> dict[str, dict[uuid.UUID, uuid.UUID]]:
    # `project` komt van blok B (parallel gebouwd) — getattr zodat deze module er niet op wacht.
    return {
        VELD_GROOTBOEK: dict(mapping.grootboek),
        VELD_BTW: dict(mapping.btw),
        VELD_PROJECT: dict(getattr(mapping, "project", None) or {}),
    }


def _spoor(veld: str, namen: _Namen, van_id: uuid.UUID, naar_id: uuid.UUID | None) -> dict:
    van = namen.voor(veld, van_id)
    blok: dict = {"van_id": str(van_id), "van_code": van.code, "van_naam": van.naam}
    if naar_id is None:
        blok.update({"naar_id": None, "reden": REDEN_GEEN_TEGENHANGER})
        return blok
    naar = namen.voor(veld, naar_id)
    blok.update({"naar_id": str(naar_id), "naar_code": naar.code, "naar_naam": naar.naam})
    return blok


def hervertaal_open_boekvoorstellen(
    session: Session, *, administratie_id: uuid.UUID, mapping: RekeningMapping, actor_id: uuid.UUID
) -> HervertaalResultaat:
    """Vertaalt de regels van álle open boekvoorstellen van de administratie via `mapping` (zie module-docstring).
    Sessie van de aanroeper, gescoopt op de administratie (RLS op boekvoorstel_regel loopt via document); schrijft
    het spoor per geraakte regel + één audit-event. Geen documenten/regels = tellingen 0, wél een audit-event
    (de stap ís uitgevoerd — herleidbaar)."""
    per_veld = _mapping_per_veld(mapping)
    odoo_waarden = {veld: set(m.values()) for veld, m in per_veld.items()}
    namen = _Namen(session, administratie_id)
    nu = datetime.now(UTC).isoformat()

    regels = session.execute(
        select(BoekvoorstelRegel, Document.id)
        .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(Document.administratie_id == administratie_id, Document.status.not_in(list(TERMINALE_STATUSSEN)))
        .order_by(Document.id, BoekvoorstelRegel.volgnummer)
    ).all()

    vertaald = dict.fromkeys(VELDEN, 0)
    leeg = dict.fromkeys(VELDEN, 0)
    documenten: set[uuid.UUID] = set()
    geraakte_regels = 0
    for regel, document_id in regels:
        spoor: dict = {}
        for veld in VELDEN:
            kolom = _KOLOM_PER_VELD[veld]
            waarde: uuid.UUID | None = getattr(regel, kolom)
            if waarde is None or waarde in odoo_waarden[veld]:
                continue  # leeg, of al een Odoo-waarde (herhaalde aanroep) — niets te doen
            doel = per_veld[veld].get(waarde)
            spoor[veld] = _spoor(veld, namen, waarde, doel)
            setattr(regel, kolom, doel)
            if doel is None:
                leeg[veld] += 1
            else:
                vertaald[veld] += 1
        if not spoor:
            continue
        regel.overstap_vertaling = {"op": nu, **spoor}
        geraakte_regels += 1
        documenten.add(document_id)

    resultaat = HervertaalResultaat(
        documenten=len(documenten),
        regels=geraakte_regels,
        vertaald={k: v for k, v in vertaald.items() if v},
        leeg={k: v for k, v in leeg.items() if v},
    )
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="boekvoorstel_regel",
        record_id=administratie_id,
        actie="odoo_open_voorstellen_hervertaald",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={
            "documenten": resultaat.documenten,
            "regels": resultaat.regels,
            "vertaald": resultaat.vertaald,
            "leeg": resultaat.leeg,
            "mapping": {veld: len(m) for veld, m in per_veld.items()},
        },
        administratie_id=administratie_id,
    )
    return resultaat
