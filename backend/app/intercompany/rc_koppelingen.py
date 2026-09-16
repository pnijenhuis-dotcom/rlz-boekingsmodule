"""Rekening-courant-koppelingen afleiden en beheren (blok A opdracht 16-09; de dagelijkse toets zelf is blok C,
`rekening_courant.py`).

Afleiding (`leid_rc_koppelingen_af`): per administratie A de balansrekeningen (`platform.grootboekrekening`, soort 3
activa / 4 passiva, geen totaalrekening, niet verdwenen) waarvan `naam_norm(naam)` de `naam_norm` van een ANDERE
administratie B bevat (als aaneengesloten hele woorden) óf één van B's Beheerder-afkortingen (heel woord, bv. "KF") →
kandidaat (A, rekening_a, B). Meerdere identiteiten in één rekeningnaam: de LANGSTE naam wint ("kempen facilities"
boven "kempen"); blijven er twee niet-geneste treffers over, dan is de rekening meerduidig en wordt NIET ingevuld
(nooit raden). De tegenrekening (`rekening_b`) is de ene rekening in B die naar A verwijst; zijn dat er 0 of ≥ 2, dan
blijft rekening_b NULL ("RC zonder tegenrekening" — oranje in blok C; bij ≥ 2 noemt de reden dat).

Upsert op (A, rekening_a, B) mét status 'afgeleid', bron 'afgeleid'; rijen met bron 'mens' worden nooit aangeraakt; een
rij die niet meer afgeleid wordt blijft staan (niets verdwijnt stil). `zet_rc_status` en `zet_afkortingen` zijn
Beheerder-only mét audit oud→nieuw."""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.intercompany import identiteit as identiteit_module
from app.intercompany.models import STATUSSEN, AdministratieIdentiteit, RcKoppeling
from app.intercompany.relaties import GeenBeheerder, IntercompanyFout, vereis_beheerder

AUDIT_ACTIE_RC = "rc_koppeling_gewijzigd"
AUDIT_ACTIE_AFKORTINGEN = "administratie_identiteit_afkortingen_gewijzigd"
_MODULE = "boekhouding"
BALANS_SOORTEN = (3, 4)


class RcKoppelingOnbekend(IntercompanyFout):
    pass


@dataclass(frozen=True)
class Rekening:
    administratie_id: uuid.UUID
    ledger_id: uuid.UUID
    code: str
    naam: str


@dataclass(frozen=True)
class RcKoppelingInfo:
    id: uuid.UUID
    administratie_a_id: uuid.UUID
    administratie_a_naam: str
    rekening_a: uuid.UUID
    rekening_a_code: str | None
    rekening_a_naam: str | None
    administratie_b_id: uuid.UUID
    administratie_b_naam: str
    rekening_b: uuid.UUID | None
    rekening_b_code: str | None
    rekening_b_naam: str | None
    basis: str
    status: str
    bron: str
    reden: str | None
    gewijzigd_op: datetime | None
    actief: bool


@dataclass(frozen=True)
class IdentiteitInfo:
    administratie_id: uuid.UUID
    administratie_naam: str
    naam: str | None
    naam_norm: str | None
    kvk: str | None
    btw: str | None
    bron: str
    afkortingen: list[str]
    gelezen_op: datetime | None


@dataclass
class RcAfleidUitkomst:
    administraties: int = 0
    rekeningen_bekeken: int = 0
    kandidaten: int = 0
    meerduidig: int = 0
    koppelingen_nieuw: int = 0
    koppelingen_bijgewerkt: int = 0
    koppelingen_ongewijzigd: int = 0
    mens_rijen_overgeslagen: int = 0
    zonder_tegenrekening: int = 0
    per_basis: dict[str, int] = field(default_factory=dict)

    def as_dict(self) -> dict[str, Any]:
        return {
            "administraties": self.administraties,
            "rekeningen_bekeken": self.rekeningen_bekeken,
            "kandidaten": self.kandidaten,
            "meerduidig": self.meerduidig,
            "koppelingen_nieuw": self.koppelingen_nieuw,
            "koppelingen_bijgewerkt": self.koppelingen_bijgewerkt,
            "koppelingen_ongewijzigd": self.koppelingen_ongewijzigd,
            "mens_rijen_overgeslagen": self.mens_rijen_overgeslagen,
            "zonder_tegenrekening": self.zonder_tegenrekening,
            "per_basis": dict(self.per_basis),
        }


# --- herkenning ------------------------------------------------------------------------------------------------------


def _bevat_heel(tekst_norm: str, deel_norm: str) -> bool:
    """`deel_norm` komt als aaneengesloten hele woorden voor in `tekst_norm` (beide al genormaliseerd)."""
    if not deel_norm or not tekst_norm:
        return False
    return re.search(rf"(?<![a-z0-9]){re.escape(deel_norm)}(?![a-z0-9])", tekst_norm) is not None


def herken_verwijzing(
    rekeningnaam: str, *, eigen: uuid.UUID, identiteiten: Iterable[AdministratieIdentiteit]
) -> tuple[uuid.UUID, str] | None | str:
    """Naar welke ANDERE administratie verwijst deze rekeningnaam? → (administratie_id, basis 'naam'|'afkorting'),
    None (geen) of de string 'meerduidig' (twee niet-geneste treffers — nooit raden)."""
    norm = identiteit_module.naam_norm(rekeningnaam)
    if not norm:
        return None
    treffers: list[tuple[str, uuid.UUID, str]] = []  # (gematchte tekst, administratie, basis)
    for i in identiteiten:
        if i.administratie_id == eigen:
            continue
        if i.naam_norm and _bevat_heel(norm, i.naam_norm):
            treffers.append((i.naam_norm, i.administratie_id, "naam"))
            continue
        for afk in i.afkortingen or []:
            afk_norm = identiteit_module.naam_norm(str(afk))
            if afk_norm and _bevat_heel(norm, afk_norm):
                treffers.append((afk_norm, i.administratie_id, "afkorting"))
                break
    if not treffers:
        return None
    treffers.sort(key=lambda t: -len(t[0]))
    langste = treffers[0]
    # Alle overige treffers moeten binnen de langste vallen (genest: "kempen" ⊂ "kempen facilities"); anders meerduidig.
    for tekst, adm, _basis in treffers[1:]:
        if adm == langste[1]:
            continue
        if not _bevat_heel(langste[0], tekst):
            return "meerduidig"
    return langste[1], langste[2]


def _balansrekeningen(administratie_id: uuid.UUID) -> list[Rekening]:
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Grootboekrekening.ledger_id, Grootboekrekening.code, Grootboekrekening.naam).where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.soort.in_(BALANS_SOORTEN),
                Grootboekrekening.is_totaalrekening.is_(False),
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            )
        ).all()
    return [Rekening(administratie_id, r[0], r[1], r[2]) for r in rijen]


# --- afleiding -----------------------------------------------------------------------------------------------------


def leid_rc_koppelingen_af(administratie_ids: Iterable[uuid.UUID] | None = None) -> RcAfleidUitkomst:
    uitkomst = RcAfleidUitkomst()
    administraties = identiteit_module.actieve_administraties(administratie_ids)
    alle_actief = identiteit_module.actieve_administraties(None)
    uitkomst.administraties = len(administraties)
    identiteiten = list(identiteit_module.alle_identiteiten().values())
    selectie = {aid for aid, _ in administraties}

    # Stap 1: per rekening (over ÁLLE actieve administraties, want de tegenrekening kan buiten de selectie liggen) de
    # verwijzing herkennen.
    verwijzing: dict[tuple[uuid.UUID, uuid.UUID], tuple[Rekening, uuid.UUID, str]] = {}
    for aid, _naam in alle_actief:
        rekeningen = _balansrekeningen(aid)
        if aid in selectie:
            uitkomst.rekeningen_bekeken += len(rekeningen)
        for rek in rekeningen:
            uitkomst_herk = herken_verwijzing(rek.naam, eigen=aid, identiteiten=identiteiten)
            if uitkomst_herk is None:
                continue
            if uitkomst_herk == "meerduidig":
                if aid in selectie:
                    uitkomst.meerduidig += 1
                continue
            b, basis = uitkomst_herk
            verwijzing[(aid, rek.ledger_id)] = (rek, b, basis)

    # Stap 2: per (A, B) de rekeningen in B die naar A verwijzen → tegenrekening als het er precies één is.
    naar: dict[tuple[uuid.UUID, uuid.UUID], list[Rekening]] = {}
    for (aid, _lid), (rek, b, _basis) in verwijzing.items():
        naar.setdefault((aid, b), []).append(rek)

    with scoped_session(None) as session:
        for (aid, _lid), (rek, b, basis) in verwijzing.items():
            if aid not in selectie:
                continue
            uitkomst.kandidaten += 1
            uitkomst.per_basis[basis] = uitkomst.per_basis.get(basis, 0) + 1
            tegen = naar.get((b, aid), [])
            rekening_b = tegen[0] if len(tegen) == 1 else None
            reden_afgeleid = None
            if len(tegen) > 1:
                reden_afgeleid = (
                    f"{len(tegen)} rekeningen in de tegenpartij verwijzen hierheen — tegenrekening niet eenduidig"
                )
            if rekening_b is None:
                uitkomst.zonder_tegenrekening += 1
            rij = session.scalars(
                select(RcKoppeling).where(
                    RcKoppeling.administratie_a_id == aid,
                    RcKoppeling.rekening_a == rek.ledger_id,
                    RcKoppeling.administratie_b_id == b,
                )
            ).one_or_none()
            if rij is None:
                session.add(
                    RcKoppeling(
                        administratie_a_id=aid,
                        rekening_a=rek.ledger_id,
                        rekening_a_code=rek.code,
                        rekening_a_naam=rek.naam,
                        administratie_b_id=b,
                        rekening_b=rekening_b.ledger_id if rekening_b else None,
                        rekening_b_code=rekening_b.code if rekening_b else None,
                        rekening_b_naam=rekening_b.naam if rekening_b else None,
                        basis=basis,
                        status="afgeleid",
                        bron="afgeleid",
                        reden=reden_afgeleid,
                    )
                )
                uitkomst.koppelingen_nieuw += 1
                continue
            if rij.bron == "mens":
                uitkomst.mens_rijen_overgeslagen += 1
                continue
            nieuw = (
                rek.code,
                rek.naam,
                rekening_b.ledger_id if rekening_b else None,
                rekening_b.code if rekening_b else None,
                rekening_b.naam if rekening_b else None,
                basis,
                reden_afgeleid,
            )
            oud = (
                rij.rekening_a_code,
                rij.rekening_a_naam,
                rij.rekening_b,
                rij.rekening_b_code,
                rij.rekening_b_naam,
                rij.basis,
                rij.reden,
            )
            if oud == nieuw:
                uitkomst.koppelingen_ongewijzigd += 1
                continue
            (
                rij.rekening_a_code,
                rij.rekening_a_naam,
                rij.rekening_b,
                rij.rekening_b_code,
                rij.rekening_b_naam,
                rij.basis,
                rij.reden,
            ) = nieuw
            uitkomst.koppelingen_bijgewerkt += 1
    return uitkomst


# --- lezen ---------------------------------------------------------------------------------------------------------


def is_actief(status: str) -> bool:
    return status in ("afgeleid", "bevestigd")


def _namen(session: Session) -> dict[uuid.UUID, str]:
    return {r[0]: r[1] for r in session.execute(select(Administratie.id, Administratie.naam)).all()}


def _info(r: RcKoppeling, namen: dict[uuid.UUID, str]) -> RcKoppelingInfo:
    return RcKoppelingInfo(
        id=r.id,
        administratie_a_id=r.administratie_a_id,
        administratie_a_naam=namen.get(r.administratie_a_id, str(r.administratie_a_id)),
        rekening_a=r.rekening_a,
        rekening_a_code=r.rekening_a_code,
        rekening_a_naam=r.rekening_a_naam,
        administratie_b_id=r.administratie_b_id,
        administratie_b_naam=namen.get(r.administratie_b_id, str(r.administratie_b_id)),
        rekening_b=r.rekening_b,
        rekening_b_code=r.rekening_b_code,
        rekening_b_naam=r.rekening_b_naam,
        basis=r.basis,
        status=r.status,
        bron=r.bron,
        reden=r.reden,
        gewijzigd_op=r.gewijzigd_op,
        actief=is_actief(r.status),
    )


def alle_rc_koppelingen() -> list[RcKoppelingInfo]:
    with scoped_session(None) as session:
        namen = _namen(session)
        infos = [_info(r, namen) for r in session.scalars(select(RcKoppeling))]
    infos.sort(key=lambda i: (i.administratie_a_naam.lower(), i.rekening_a_code or "", i.administratie_b_naam.lower()))
    return infos


def actieve_rc_koppelingen() -> list[RcKoppelingInfo]:
    """Status 'afgeleid' óf 'bevestigd' — de dagelijkse toets (blok C) leest deze; 'uitgesloten' telt nooit mee."""
    return [k for k in alle_rc_koppelingen() if k.actief]


def identiteiten_overzicht() -> list[IdentiteitInfo]:
    """Alle actieve administraties mét hun identiteit (of lege velden als die nog niet gelezen is) — voor de
    Beheerder-UI (afkortingen per administratie)."""
    with scoped_session(None) as session:
        administraties = session.execute(
            select(Administratie.id, Administratie.naam)
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
        rijen = {r.administratie_id: r for r in session.scalars(select(AdministratieIdentiteit))}
        uit: list[IdentiteitInfo] = []
        for aid, naam in administraties:
            r = rijen.get(aid)
            uit.append(
                IdentiteitInfo(
                    administratie_id=aid,
                    administratie_naam=naam,
                    naam=r.naam if r else None,
                    naam_norm=r.naam_norm if r else None,
                    kvk=r.kvk if r else None,
                    btw=r.btw if r else None,
                    bron=r.bron if r else "rlz",
                    afkortingen=[str(a) for a in (r.afkortingen or [])] if r else [],
                    gelezen_op=r.gelezen_op if r else None,
                )
            )
        return uit


# --- Beheerder-mutaties ----------------------------------------------------------------------------------------------


def zet_rc_status(koppeling_id: uuid.UUID, *, status: str, reden: str | None, actor_id: uuid.UUID) -> RcKoppelingInfo:
    if status not in STATUSSEN:
        raise IntercompanyFout(f"Onbekende status: {status}")
    reden_schoon = " ".join((reden or "").split()) or None
    if status == "uitgesloten" and not reden_schoon:
        raise IntercompanyFout("Uitsluiten vereist een reden.")
    with scoped_session(None) as session:
        vereis_beheerder(session, actor_id)
        rij = session.get(RcKoppeling, koppeling_id)
        if rij is None:
            raise RcKoppelingOnbekend(f"Onbekende rekening-courant-koppeling: {koppeling_id}")
        administratie_a_id = rij.administratie_a_id
    with scoped_session(administratie_a_id, actor_id=actor_id) as session:
        rij = session.get(RcKoppeling, koppeling_id)
        assert rij is not None
        oud = {"status": rij.status, "bron": rij.bron, "reden": rij.reden}
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
            tabel="rc_koppeling",
            record_id=rij.id,
            actie=AUDIT_ACTIE_RC,
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"status": rij.status, "bron": rij.bron, "reden": rij.reden},
            administratie_id=administratie_a_id,
        )
        return _info(rij, _namen(session))


def normaliseer_afkortingen(afkortingen: Iterable[str]) -> list[str]:
    """Trim, leeg weg, dubbelen (hoofdletterongevoelig) weg, volgorde behouden; hoogstens 20 tekens per afkorting."""
    uit: list[str] = []
    gezien: set[str] = set()
    for a in afkortingen:
        schoon = " ".join(str(a).split())[:20]
        if not schoon or schoon.lower() in gezien:
            continue
        gezien.add(schoon.lower())
        uit.append(schoon)
    return uit


def zet_afkortingen(administratie_id: uuid.UUID, afkortingen: Iterable[str], *, actor_id: uuid.UUID) -> IdentiteitInfo:
    """Beheerder-afkortingen voor déze administratie ("KF" → Kempen Facilities). De identiteit-rij ontstaat hier als
    'ie er nog niet is (bron blijft die van de sync; kvk/naam volgen bij de volgende sync). Audit oud→nieuw."""
    nieuw = normaliseer_afkortingen(afkortingen)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        vereis_beheerder(session, actor_id)
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise IntercompanyFout(f"Onbekende administratie: {administratie_id}")
        rij = session.get(AdministratieIdentiteit, administratie_id)
        if rij is None:
            rij = AdministratieIdentiteit(administratie_id=administratie_id, bron="rlz")
            session.add(rij)
        oud = list(rij.afkortingen or [])
        rij.afkortingen = nieuw or None
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module=_MODULE,
            tabel="administratie_identiteit",
            record_id=administratie_id,
            actie=AUDIT_ACTIE_AFKORTINGEN,
            correlatie_id=uuid.uuid4(),
            oude_waarde={"afkortingen": oud},
            nieuwe_waarde={"afkortingen": nieuw},
            administratie_id=administratie_id,
        )
        return IdentiteitInfo(
            administratie_id=administratie_id,
            administratie_naam=administratie.naam,
            naam=rij.naam,
            naam_norm=rij.naam_norm,
            kvk=rij.kvk,
            btw=rij.btw,
            bron=rij.bron,
            afkortingen=nieuw,
            gelezen_op=rij.gelezen_op,
        )


__all__ = [
    "AUDIT_ACTIE_AFKORTINGEN",
    "AUDIT_ACTIE_RC",
    "GeenBeheerder",
    "IdentiteitInfo",
    "RcAfleidUitkomst",
    "RcKoppelingInfo",
    "RcKoppelingOnbekend",
    "actieve_rc_koppelingen",
    "alle_rc_koppelingen",
    "herken_verwijzing",
    "identiteiten_overzicht",
    "leid_rc_koppelingen_af",
    "zet_afkortingen",
    "zet_rc_status",
]
