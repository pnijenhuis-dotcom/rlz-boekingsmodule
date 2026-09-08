"""Inzicht › Reconciliatie KANTOORBREED (opdracht 06-09 blok C; mockup `inzicht-kantoorbreed.html`
ontwerpnotities ①②⑨ = bouwnorm, kernprincipe 7 "signalering zonder handeling is niet af").

Bron = de bevindingen van de LAATSTE AFGERONDE reconciliatie-run (app/reconciliatie/run.py). Scope =
`mijn_administraties` (Beheerder = alle actieve), per administratie gelezen in
`scoped_session(aid, actor_id=…)` — RLS blijft de waarheid (RLS-les 25-08); administratie-loze
bevindingen (blokcrash) staan in de scope-loze sessie en zijn kantoorbreed zichtbaar. Aggregeren,
sorteren en pagineren in Python (25 per pagina). Soort en administratie zijn FACET-filters, nooit
een poort.

Handeling per rij (hergebruik bestaande schrijvers — géén tweede schrijver):
- afwijking       → "Accepteren…" (verplichte reden, `reconciliatie.service.accepteer`, Beheerder) en
                    op een geaccepteerde rij "Intrekken" (`trek_in`);
- let_op          → "Gezien" (snooze mét reden, `reconciliatie_gezien`; vervalt ná `gezien_dagen`,
                    komt terug zodra de kandidaat een andere reden krijgt) + deeplink naar het
                    doorbelasting-run-detail;
- uitgesloten     → alleen zichtbaar onder het facet, geen actie (besluit 0043).
Elke handeling geauditeerd (audit_event oud→nieuw). Geen AI, geen RLZ-calls."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.auth import service as auth_service
from app.db.audit import record_audit_event
from app.db.models import Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.reconciliatie import run as run_service
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie import teksten
from app.reconciliatie.models import (
    BevindingSoort,
    ReconciliatieBevinding,
    ReconciliatieGezien,
    ReconciliatieInstelling,
    ReconciliatieRun,
)

PER_PAGINA = 25
SOORT_FACETTEN = ("aandacht", "afwijking", "let_op", "fout", "geaccepteerd", "uitgesloten", "gezien", "alle")
AANDACHT = (BevindingSoort.AFWIJKING.value, BevindingSoort.FOUT.value, BevindingSoort.LET_OP.value)
_URGENTIE = {"afwijking": 0, "fout": 1, "let_op": 2, "geaccepteerd": 3, "uitgesloten": 4, "gezien": 5}
#: Binnen soort=afwijking bovenaan (contract A↔A8 punt 5): een verdwenen of teruggedraaid extern document
#: is de zwaarste categorie — daar is boekhoudkundig werk, niet alleen beoordelen.
_URGENTIE_AFWIJKING_SOORT = {
    "ontbreekt_in_rlz": 0,
    "ontbreekt_in_odoo": 0,
    "document_ontbreekt_in_rlz": 0,
    "mutatie_ontbreekt_in_rlz": 0,
    "teruggedraaid_in_odoo": 1,
    "boeking_teruggedraaid_in_rlz": 1,
    "aflettering_teruggedraaid_in_rlz": 1,
    "half_geboekt": 2,
    # Blok 6 (08-09): mogelijk dubbel in RLZ — beoordelen in Reeleezee, geen boekhoudkundig werk in de app.
    "dubbel_in_rlz": 3,
}
_MINIMALE_REDEN = 5


class ReconciliatieFout(Exception):
    """Fail-loud richting de router (404/403/422 — de router vertaalt op de tekst)."""


@dataclass(frozen=True)
class AcceptatieWeergave:
    reden: str
    geaccepteerd_op: datetime
    geaccepteerd_door_naam: str | None


@dataclass(frozen=True)
class GezienWeergave:
    reden: str
    gezien_op: datetime
    vervalt_op: datetime
    gezien_door_naam: str | None


@dataclass(frozen=True)
class Rij:
    id: uuid.UUID
    run_id: uuid.UUID
    blok: str
    soort: str  # afwijking | let_op | fout | geaccepteerd | uitgesloten | gezien (= gesnoozede let_op)
    administratie_id: uuid.UUID | None
    administratie_naam: str | None
    vingerafdruk: str
    tekst: str
    sinds: datetime
    nieuw: bool
    acceptatie: AcceptatieWeergave | None
    gezien: GezienWeergave | None
    detail: dict | None
    doel_pad: str | None
    # Leesbare laag (fixrun 07-09 blok A8, app/reconciliatie/teksten.py): titel + "wat is er" + "wat doe je"
    # met namen; technische sleutels in `details` (label, waarde) voor de uitklap. `tekst` blijft de CLI-regel.
    titel: str = ""
    wat: str = ""
    doe: str = ""
    details: tuple[tuple[str, str], ...] = ()

    @property
    def zoektekst(self) -> str:
        return " ".join((self.tekst, self.titel, self.wat, self.administratie_naam or "")).lower()


@dataclass(frozen=True)
class AdministratieFacet:
    administratie_id: uuid.UUID
    naam: str
    aantal: int


@dataclass(frozen=True)
class Tellers:
    afwijkingen: int
    let_op: int  # open (niet gezien)
    fouten: int
    geaccepteerd: int
    uitgesloten: int
    gezien: int
    administraties: int  # administraties mét ≥ 1 aandacht-rij


@dataclass(frozen=True)
class Lijst:
    rijen: list[Rij]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: Tellers
    facetten_soort: dict[str, int]
    facetten_administraties: list[AdministratieFacet]
    laatste_run: run_service.RunInfo | None


@dataclass(frozen=True)
class Stand:
    teller: int  # open afwijkingen + fouten + open let_op — de KPI-kaart
    afwijkingen: int
    let_op: int
    fouten: int
    laatste_run: run_service.RunInfo | None


def _doel_pad(b: ReconciliatieBevinding) -> str | None:
    d = b.detail or {}
    aid = b.administratie_id
    if aid is None:
        return None
    if b.blok == "doorbelasting" and d.get("document_id"):
        return f"/doorbelasting/{aid}/{d['document_id']}"
    if b.blok in ("documenten", "omzet") and d.get("document_id"):
        return f"/?administratie={aid}&document={d['document_id']}"
    return None


def _doel_pad_of_instelling(b: ReconciliatieBevinding) -> str | None:
    """Automatiserings-LET-OP (herstelrun 07-09 blok C): de handeling is de instelling herstellen — de
    deeplink staat in `detail.doel_pad`, ook zonder administratie (platformbrede voorwaarde)."""
    if b.blok == "automatisering":
        return str((b.detail or {}).get("doel_pad") or "/instellingen")
    return _doel_pad(b)


def _scope(actor_id: uuid.UUID, rol: GebruikerRol) -> list[tuple[uuid.UUID, str]]:
    return [(a.id, a.naam) for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)]


def _namen(session, ids: set[uuid.UUID]) -> dict[uuid.UUID, str]:
    if not ids:
        return {}
    return {
        rij.id: rij.naam for rij in session.execute(select(Gebruiker.id, Gebruiker.naam).where(Gebruiker.id.in_(ids)))
    }


def _rijen_voor_administratie(
    *,
    aid: uuid.UUID | None,
    naam: str | None,
    actor_id: uuid.UUID,
    run: run_service.RunInfo,
    nu: datetime,
    dagen: int,
) -> list[Rij]:
    with scoped_session(aid, actor_id=actor_id) as session:
        q = select(ReconciliatieBevinding).where(ReconciliatieBevinding.run_id == run.run_id)
        q = (
            q.where(ReconciliatieBevinding.administratie_id.is_(None))
            if aid is None
            else q.where(ReconciliatieBevinding.administratie_id == aid)
        )
        bevindingen = list(session.scalars(q.order_by(ReconciliatieBevinding.aangemaakt_op)))
        if not bevindingen:
            return []
        vafs = {b.vingerafdruk for b in bevindingen}
        # "sinds" = de eerste afgeronde run waarin deze vingerafdruk (voor deze administratie) voorkwam.
        sinds_q = (
            select(ReconciliatieBevinding.vingerafdruk, func.min(ReconciliatieRun.afgerond_op))
            .join(ReconciliatieRun, ReconciliatieRun.id == ReconciliatieBevinding.run_id)
            .where(ReconciliatieBevinding.vingerafdruk.in_(vafs), ReconciliatieRun.afgerond_op.is_not(None))
            .group_by(ReconciliatieBevinding.vingerafdruk)
        )
        sinds_q = (
            sinds_q.where(ReconciliatieBevinding.administratie_id.is_(None))
            if aid is None
            else sinds_q.where(ReconciliatieBevinding.administratie_id == aid)
        )
        sinds = dict(session.execute(sinds_q).all())
        gezien: dict[str, ReconciliatieGezien] = {}
        acceptaties: dict[str, acceptatie_service.AcceptatieInfo] = {}
        if aid is not None:
            for g in session.scalars(
                select(ReconciliatieGezien).where(
                    ReconciliatieGezien.administratie_id == aid,
                    ReconciliatieGezien.ingetrokken_op.is_(None),
                    ReconciliatieGezien.gezien_op > nu - timedelta(days=dagen),
                )
            ):
                gezien[g.vingerafdruk] = g
            for bron in {(b.detail or {}).get("bron") for b in bevindingen} - {None}:
                acceptaties.update(acceptatie_service._actieve_acceptaties(administratie_id=aid, bron=bron))
        namen = _namen(
            session,
            {g.gezien_door for g in gezien.values()} | {a.geaccepteerd_door for a in acceptaties.values()},
        )
        run_afgerond = run.afgerond_op
        uit: list[Rij] = []
        for b in bevindingen:
            soort = b.soort
            gezien_rij = gezien.get(b.vingerafdruk) if soort == BevindingSoort.LET_OP.value else None
            if gezien_rij is not None:
                reden_nu = (b.detail or {}).get("reden")
                if gezien_rij.reden_snapshot is not None and reden_nu not in (None, gezien_rij.reden_snapshot):
                    gezien_rij = None  # kandidaat kwam met een andere reden terug → telt weer
            if gezien_rij is not None:
                soort = "gezien"
            acc = acceptaties.get(b.vingerafdruk)
            # BUGFIX 07-09 (blok A8): de opgeslagen bevinding zegt 'afwijking' tot de VOLGENDE run; de
            # acceptatie is echter al live (reconciliatie_acceptatie). De lijst en de KPI volgen daarom de
            # actuele acceptatie-stand: geaccepteerd → direct uit "aandacht nodig"; ingetrokken → direct terug.
            # Uitgesloten blijft uitgesloten (besluit 0043), gezien/let_op/fout raakt dit niet.
            if soort == BevindingSoort.AFWIJKING.value and acc is not None:
                soort = BevindingSoort.GEACCEPTEERD.value
            elif soort == BevindingSoort.GEACCEPTEERD.value and acc is None and (b.detail or {}).get("bron"):
                soort = BevindingSoort.AFWIJKING.value
            eerste = sinds.get(b.vingerafdruk) or run_afgerond or b.aangemaakt_op
            lees = teksten.leesbaar(b, administratie_naam=naam, soort=soort)
            uit.append(
                Rij(
                    id=b.id,
                    run_id=b.run_id,
                    blok=b.blok,
                    soort=soort,
                    administratie_id=aid,
                    administratie_naam=naam,
                    vingerafdruk=b.vingerafdruk,
                    tekst=b.tekst,
                    sinds=eerste,
                    nieuw=run_afgerond is not None and eerste >= run_afgerond,
                    acceptatie=(
                        AcceptatieWeergave(
                            reden=acc.reden,
                            geaccepteerd_op=acc.geaccepteerd_op,
                            geaccepteerd_door_naam=namen.get(acc.geaccepteerd_door),
                        )
                        if acc is not None and soort in ("geaccepteerd", "uitgesloten")
                        else None
                    ),
                    gezien=(
                        GezienWeergave(
                            reden=gezien_rij.reden,
                            gezien_op=gezien_rij.gezien_op,
                            vervalt_op=run_service.gezien_vervalt_op(gezien_rij, dagen),
                            gezien_door_naam=namen.get(gezien_rij.gezien_door),
                        )
                        if gezien_rij is not None
                        else None
                    ),
                    detail=b.detail,
                    doel_pad=_doel_pad_of_instelling(b),
                    titel=lees.titel,
                    wat=lees.wat,
                    doe=lees.doe,
                    details=tuple(lees.details),
                )
            )
        return uit


def _alle_rijen(
    *, actor_id: uuid.UUID, rol: GebruikerRol, nu: datetime
) -> tuple[list[Rij], run_service.RunInfo | None]:
    run = run_service.laatste_afgeronde_run()
    if run is None:
        return [], None
    dagen = run_service.gezien_dagen()
    uit = _rijen_voor_administratie(aid=None, naam=None, actor_id=actor_id, run=run, nu=nu, dagen=dagen)
    for aid, naam in _scope(actor_id, rol):
        uit.extend(_rijen_voor_administratie(aid=aid, naam=naam, actor_id=actor_id, run=run, nu=nu, dagen=dagen))
    return uit, run


def _in_facet(rij: Rij, soort: str) -> bool:
    if soort == "alle":
        return True
    if soort == "aandacht":
        return rij.soort in AANDACHT
    return rij.soort == soort


def _urgentie_binnen_soort(r: Rij) -> int:
    if r.soort != BevindingSoort.AFWIJKING.value:
        return 9
    return _URGENTIE_AFWIJKING_SOORT.get(str((r.detail or {}).get("afwijking_soort") or ""), 5)


def _sorteer(rijen: list[Rij]) -> list[Rij]:
    return sorted(
        rijen,
        key=lambda r: (
            _URGENTIE.get(r.soort, 9),
            _urgentie_binnen_soort(r),
            r.sinds,
            r.administratie_naam or "",
            r.titel,
            r.tekst,
        ),
    )


def lijst(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    pagina: int = 1,
    q: str = "",
    administratie_id: uuid.UUID | None = None,
    soort: str = "aandacht",
    nu: datetime | None = None,
) -> Lijst:
    if soort not in SOORT_FACETTEN:
        raise ReconciliatieFout(f"Onbekend soort-facet: {soort}")
    nu = nu or datetime.now(UTC)
    alle, run = _alle_rijen(actor_id=actor_id, rol=rol, nu=nu)

    tellers = Tellers(
        afwijkingen=sum(1 for r in alle if r.soort == "afwijking"),
        let_op=sum(1 for r in alle if r.soort == "let_op"),
        fouten=sum(1 for r in alle if r.soort == "fout"),
        geaccepteerd=sum(1 for r in alle if r.soort == "geaccepteerd"),
        uitgesloten=sum(1 for r in alle if r.soort == "uitgesloten"),
        gezien=sum(1 for r in alle if r.soort == "gezien"),
        administraties=len({r.administratie_id for r in alle if r.soort in AANDACHT and r.administratie_id}),
    )

    term = q.strip().lower()
    binnen_admin_q = [
        r
        for r in alle
        if (administratie_id is None or r.administratie_id == administratie_id) and (not term or term in r.zoektekst)
    ]
    facetten_soort = {s: sum(1 for r in binnen_admin_q if _in_facet(r, s)) for s in SOORT_FACETTEN}
    binnen_soort_q = [r for r in alle if _in_facet(r, soort) and (not term or term in r.zoektekst)]
    per_admin: dict[uuid.UUID, tuple[str, int]] = {}
    for r in binnen_soort_q:
        if r.administratie_id is None:
            continue
        naam, n = per_admin.get(r.administratie_id, (r.administratie_naam or "", 0))
        per_admin[r.administratie_id] = (naam, n + 1)
    facetten_administraties = sorted(
        (AdministratieFacet(administratie_id=aid, naam=naam, aantal=n) for aid, (naam, n) in per_admin.items()),
        key=lambda f: (-f.aantal, f.naam),
    )

    selectie = _sorteer([r for r in binnen_admin_q if _in_facet(r, soort)])
    start = (pagina - 1) * PER_PAGINA
    return Lijst(
        rijen=selectie[start : start + PER_PAGINA],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=PER_PAGINA,
        administraties_in_selectie=len({r.administratie_id for r in selectie if r.administratie_id}),
        tellers=tellers,
        facetten_soort=facetten_soort,
        facetten_administraties=facetten_administraties,
        laatste_run=run,
    )


def stand(*, actor_id: uuid.UUID, rol: GebruikerRol, nu: datetime | None = None) -> Stand:
    """KPI-kaart werkvoorraad: teller = open afwijkingen + fouten + open LET-OP's (niet gezien) van de
    laatste afgeronde run, binnen de scope; subregel = laatste run."""
    nu = nu or datetime.now(UTC)
    alle, run = _alle_rijen(actor_id=actor_id, rol=rol, nu=nu)
    afwijkingen = sum(1 for r in alle if r.soort == "afwijking")
    let_op = sum(1 for r in alle if r.soort == "let_op")
    fouten = sum(1 for r in alle if r.soort == "fout")
    return Stand(
        teller=afwijkingen + let_op + fouten, afwijkingen=afwijkingen, let_op=let_op, fouten=fouten, laatste_run=run
    )


# ---- handelingen -------------------------------------------------------------------------------


def _vereis_scope(actor_id: uuid.UUID, rol: GebruikerRol, administratie_id: uuid.UUID) -> None:
    if administratie_id not in {aid for aid, _ in _scope(actor_id, rol)}:
        raise ReconciliatieFout("Geen toegang tot deze administratie")


def _laad_bevinding(
    *, bevinding_id: uuid.UUID, administratie_id: uuid.UUID, actor_id: uuid.UUID
) -> ReconciliatieBevinding:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(ReconciliatieBevinding, bevinding_id)
        if rij is None or rij.administratie_id != administratie_id:
            raise ReconciliatieFout("Bevinding niet gevonden")
        session.expunge(rij)
        return rij


def accepteer(
    *, bevinding_id: uuid.UUID, administratie_id: uuid.UUID, reden: str, actor_id: uuid.UUID, rol: GebruikerRol
) -> uuid.UUID:
    """ "Accepteren…" op een afwijking = exact de CLI-route `reconciliatie-accepteer`: dezelfde schrijver,
    dezelfde vingerafdruk (bron|soort|detail uit de bevinding), Beheerder-check in de service."""
    _vereis_scope(actor_id, rol, administratie_id)
    b = _laad_bevinding(bevinding_id=bevinding_id, administratie_id=administratie_id, actor_id=actor_id)
    d = b.detail or {}
    if b.soort not in (
        BevindingSoort.AFWIJKING.value,
        BevindingSoort.UITGESLOTEN.value,
        BevindingSoort.GEACCEPTEERD.value,  # opgeslagen als geaccepteerd, maar intussen ingetrokken (live-stand)
    ) or not d.get("bron"):
        raise ReconciliatieFout("Alleen een afwijking kan geaccepteerd worden")
    # "Al geaccepteerd" toetsen op de LIVE acceptatie-stand, niet op de snapshot in de bevinding (bugfix 07-09):
    # ná intrekken moet dezelfde rij opnieuw te accepteren zijn zonder een nieuwe run.
    if b.vingerafdruk in acceptatie_service._actieve_acceptaties(administratie_id=administratie_id, bron=d["bron"]):
        raise ReconciliatieFout("Deze afwijking is al geaccepteerd")
    try:
        return acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=d["bron"],
            record_id=uuid.UUID(d["record_id"]),
            soort=d["afwijking_soort"],
            detail=d["detail"],
            reden=reden,
            beheerder_id=actor_id,
        )
    except acceptatie_service.AcceptatieFout as exc:
        raise ReconciliatieFout(str(exc)) from exc


def trek_acceptatie_in(
    *, bevinding_id: uuid.UUID, administratie_id: uuid.UUID, reden: str, actor_id: uuid.UUID, rol: GebruikerRol
) -> uuid.UUID:
    _vereis_scope(actor_id, rol, administratie_id)
    b = _laad_bevinding(bevinding_id=bevinding_id, administratie_id=administratie_id, actor_id=actor_id)
    d = b.detail or {}
    if not d.get("bron"):
        raise ReconciliatieFout("Deze bevinding draagt geen acceptatie")
    try:
        return acceptatie_service.trek_in(
            administratie_id=administratie_id,
            bron=d["bron"],
            vingerafdruk_waarde=b.vingerafdruk,
            reden=reden,
            beheerder_id=actor_id,
        )
    except acceptatie_service.AcceptatieFout as exc:
        raise ReconciliatieFout(str(exc)) from exc


def gezien_dagen() -> int:
    return run_service.gezien_dagen()


def zet_gezien_dagen(*, dagen: int, actor_id: uuid.UUID) -> int:
    if not 1 <= dagen <= 3650:
        raise ReconciliatieFout("Aantal dagen moet tussen 1 en 3650 liggen")
    with scoped_session(None, actor_id=actor_id) as session:
        rij = session.get(ReconciliatieInstelling, True)
        if rij is None:
            raise ReconciliatieFout(
                "boekhouding.reconciliatie_instelling heeft geen rij — migratie 0114 niet toegepast?"
            )
        oud = rij.gezien_dagen
        rij.gezien_dagen = dagen
        rij.gewijzigd_door = actor_id
        rij.gewijzigd_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="reconciliatie_instelling",
            record_id=uuid.UUID(int=0),
            actie="reconciliatie_gezien_dagen_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"gezien_dagen": oud},
            nieuwe_waarde={"gezien_dagen": dagen},
        )
        return dagen


def markeer_gezien(
    *, bevinding_id: uuid.UUID, administratie_id: uuid.UUID, reden: str, actor_id: uuid.UUID, rol: GebruikerRol
) -> uuid.UUID:
    """ "Gezien" op een LET-OP-rij (opruim-kandidaat): snooze mét verplichte reden, élke kantoorrol
    binnen scope. Idempotent op een al actieve snooze (zelfde rij terug)."""
    if len((reden or "").strip()) < _MINIMALE_REDEN:
        raise ReconciliatieFout("'Gezien' vereist een inhoudelijke reden")
    _vereis_scope(actor_id, rol, administratie_id)
    b = _laad_bevinding(bevinding_id=bevinding_id, administratie_id=administratie_id, actor_id=actor_id)
    if b.soort != BevindingSoort.LET_OP.value:
        raise ReconciliatieFout("'Gezien' geldt alleen voor een LET-OP-bevinding")
    nu = datetime.now(UTC)
    dagen = gezien_dagen()
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        bestaand = session.scalars(
            select(ReconciliatieGezien).where(
                ReconciliatieGezien.administratie_id == administratie_id,
                ReconciliatieGezien.vingerafdruk == b.vingerafdruk,
                ReconciliatieGezien.ingetrokken_op.is_(None),
            )
        ).one_or_none()
        if bestaand is not None:
            if run_service.gezien_vervalt_op(bestaand, dagen) > nu:
                return bestaand.id
            # vervallen snooze: intrekken (nooit delete) en een nieuwe zetten
            bestaand.ingetrokken_op = nu
            bestaand.ingetrokken_door = actor_id
        rij = ReconciliatieGezien(
            administratie_id=administratie_id,
            blok=b.blok,
            vingerafdruk=b.vingerafdruk,
            reden_snapshot=(b.detail or {}).get("reden"),
            reden=reden.strip(),
            gezien_door=actor_id,
            vervalt_op=nu + timedelta(days=dagen),
        )
        session.add(rij)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="reconciliatie_gezien",
            record_id=rij.id,
            actie="reconciliatie_bevinding_gezien",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"soort": "let_op"},
            nieuwe_waarde={
                "vingerafdruk": b.vingerafdruk,
                "blok": b.blok,
                "reden": reden.strip(),
                "vervalt_op": rij.vervalt_op.isoformat(),
                "tekst": b.tekst,
            },
            administratie_id=administratie_id,
        )
        return rij.id


def gezien_intrekken(
    *, bevinding_id: uuid.UUID, administratie_id: uuid.UUID, reden: str, actor_id: uuid.UUID, rol: GebruikerRol
) -> uuid.UUID:
    if len((reden or "").strip()) < _MINIMALE_REDEN:
        raise ReconciliatieFout("Intrekken vereist een inhoudelijke reden")
    _vereis_scope(actor_id, rol, administratie_id)
    b = _laad_bevinding(bevinding_id=bevinding_id, administratie_id=administratie_id, actor_id=actor_id)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.scalars(
            select(ReconciliatieGezien).where(
                ReconciliatieGezien.administratie_id == administratie_id,
                ReconciliatieGezien.vingerafdruk == b.vingerafdruk,
                ReconciliatieGezien.ingetrokken_op.is_(None),
            )
        ).one_or_none()
        if rij is None:
            raise ReconciliatieFout("Geen actieve 'Gezien'-markering op deze bevinding")
        rij.ingetrokken_op = datetime.now(UTC)
        rij.ingetrokken_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="reconciliatie_gezien",
            record_id=rij.id,
            actie="reconciliatie_gezien_ingetrokken",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"reden": rij.reden, "vervalt_op": rij.vervalt_op.isoformat()},
            nieuwe_waarde={"ingetrokken_reden": reden.strip()},
            administratie_id=administratie_id,
        )
        return rij.id
