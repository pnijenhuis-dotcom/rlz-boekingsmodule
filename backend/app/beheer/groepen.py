"""Groepskenmerk op administratie (blok 8 run 11-09 middag, opdracht Peter 11-09; migratie 0135).

Datalaag, schaalbaar — geen lijstonderhoud in code: `platform.groep` (naam, korte unieke code, actief) +
`platform.administratie.groep_id` (hoogstens één groep). De groep is een FILTER op de kantoorbrede overzichten
(klantenlijst `GET /werkvoorraad/overzicht?groep_id=`, Inzicht › Reconciliatie, Instellingen › Administraties) —
nooit een poort (Kernprincipe 7). Leeg = geen groep en dat blokkeert niets (wizard-veld optioneel).

Regels:
- Groepen worden nooit verwijderd — archiveren = `actief=False`; een gearchiveerde groep kan niet meer aan een
  administratie worden toegekend, bestaande leden houden hun groep (zichtbaar als "(gearchiveerd)").
- Muteren = Beheerder-only (router `require_beheerder` én RLS `platform.current_actor_is_beheerder()` — de sessie
  draagt daarom altijd `actor_id`); lezen mag elke kantoorrol (filter-keuzelijst).
- Élke mutatie in het append-only audit_event, oud→nieuw: `groep_aangemaakt`, `groep_gewijzigd` (tabel groep) en
  `administratie_groep_gewijzigd` (tabel administratie).
- De eerste groep "Kempen groep" wordt bewust NIET in code gevuld — Peter maakt 'm via de UI en kent de leden toe.
"""

from __future__ import annotations

import re
import unicodedata
import uuid
from dataclasses import dataclass

from sqlalchemy import func, select

from app.beheer.service import BeheerFout
from app.db.audit import record_audit_event
from app.db.models import Administratie, Groep
from app.db.session import scoped_session

CODE_PATROON = re.compile(r"^[A-Z0-9]{2,12}$")
CODE_MAX_LENGTE = 12


class GroepFout(BeheerFout):
    """Domeinfout rond groepen (onbekend, ongeldige code, code bezet, gearchiveerd)."""


class GroepOnbekend(GroepFout):
    pass


class GroepOngeldig(GroepFout):
    """Ongeldige invoer (lege naam, code buiten het patroon) → 422."""


class GroepCodeBezet(GroepFout):
    """Code bestaat al (uniek, ook over gearchiveerde groepen heen) → 409."""


class GroepGearchiveerd(GroepFout):
    """Toekennen aan een gearchiveerde groep → 409."""


@dataclass(frozen=True)
class GroepInfo:
    id: uuid.UUID
    naam: str
    code: str
    actief: bool
    aantal_administraties: int


def code_voorstel(naam: str) -> str:
    """Deterministisch code-voorstel uit de naam: accenten weg, alleen letters/cijfers, hoofdletters, max 12 tekens
    ("Kempen groep" → "KEMPENGROEP", "Jansen & Zn." → "JANSENZN"). De Beheerder kan 'm in de UI aanpassen; te kort
    (< 2) = leeg voorstel, de UI vraagt dan zelf om een code. De frontend spiegelt deze regel (groepen.ts)."""
    zonder_accenten = unicodedata.normalize("NFKD", naam).encode("ascii", "ignore").decode("ascii")
    kaal = re.sub(r"[^A-Za-z0-9]", "", zonder_accenten).upper()[:CODE_MAX_LENGTE]
    return kaal if len(kaal) >= 2 else ""


def normaliseer_code(code: str | None, *, naam: str) -> str:
    """Code uit de invoer (getrimd, hoofdletters) of het voorstel uit de naam; buiten het patroon = GroepOngeldig."""
    kandidaat = (code or "").strip().upper() or code_voorstel(naam)
    if not CODE_PATROON.match(kandidaat):
        raise GroepOngeldig("Code moet 2–12 tekens zijn en alleen hoofdletters en cijfers bevatten (bv. KEMPEN).")
    return kandidaat


def _naam_schoon(naam: str) -> str:
    schoon = " ".join(naam.split())
    if not schoon:
        raise GroepOngeldig("Naam van de groep mag niet leeg zijn.")
    if len(schoon) > 80:
        raise GroepOngeldig("Naam van de groep is te lang (max. 80 tekens).")
    return schoon


def _info(groep: Groep, aantal: int) -> GroepInfo:
    return GroepInfo(id=groep.id, naam=groep.naam, code=groep.code, actief=groep.actief, aantal_administraties=aantal)


def lijst_groepen(*, inclusief_gearchiveerd: bool = True) -> list[GroepInfo]:
    """Alle groepen (alfabetisch; actieve eerst) mét het aantal niet-gearchiveerde lid-administraties. Platformbrede
    referentietabel: `scoped_session(None)` zonder actor — de SELECT-policy is open voor elke ingelogde."""
    with scoped_session(None) as session:
        q = select(Groep).order_by(Groep.actief.desc(), Groep.naam)
        if not inclusief_gearchiveerd:
            q = q.where(Groep.actief.is_(True))
        groepen = list(session.scalars(q))
        tellingen = dict(
            session.execute(
                select(Administratie.groep_id, func.count())
                .where(Administratie.groep_id.is_not(None), Administratie.actief.is_(True))
                .group_by(Administratie.groep_id)
            ).all()
        )
        return [_info(g, int(tellingen.get(g.id, 0))) for g in groepen]


def haal_groep_op(groep_id: uuid.UUID) -> GroepInfo:
    with scoped_session(None) as session:
        groep = session.get(Groep, groep_id)
        if groep is None:
            raise GroepOnbekend(f"Onbekende groep: {groep_id}")
        aantal = session.scalar(
            select(func.count())
            .select_from(Administratie)
            .where(Administratie.groep_id == groep_id, Administratie.actief.is_(True))
        )
        return _info(groep, int(aantal or 0))


def maak_groep(*, actor_id: uuid.UUID, naam: str, code: str | None = None) -> GroepInfo:
    """Nieuwe groep — Beheerder-only (router + RLS). Code leeg = voorstel uit de naam. Audit `groep_aangemaakt`."""
    schoon = _naam_schoon(naam)
    code_def = normaliseer_code(code, naam=schoon)
    with scoped_session(None, actor_id=actor_id) as session:
        bezet = session.scalar(select(Groep.id).where(Groep.code == code_def))
        if bezet is not None:
            raise GroepCodeBezet(f"Code {code_def} is al in gebruik door een andere groep.")
        groep = Groep(id=uuid.uuid4(), naam=schoon, code=code_def, actief=True)
        session.add(groep)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="groep",
            record_id=groep.id,
            actie="groep_aangemaakt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"naam": schoon, "code": code_def, "actief": True},
        )
        return _info(groep, 0)


def wijzig_groep(
    *, actor_id: uuid.UUID, groep_id: uuid.UUID, naam: str | None = None, actief: bool | None = None
) -> GroepInfo:
    """Hernoemen en/of archiveren/heractiveren — nooit verwijderen; de code is onveranderlijk (filter-deeplinks en
    audit-sporen verwijzen ernaar). Audit `groep_gewijzigd` oud→nieuw, ook bij een no-op (bewuste herbevestiging)."""
    with scoped_session(None, actor_id=actor_id) as session:
        groep = session.get(Groep, groep_id)
        if groep is None:
            raise GroepOnbekend(f"Onbekende groep: {groep_id}")
        oud = {"naam": groep.naam, "actief": groep.actief}
        if naam is not None:
            groep.naam = _naam_schoon(naam)
        if actief is not None:
            groep.actief = actief
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="groep",
            record_id=groep.id,
            actie="groep_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={"naam": groep.naam, "actief": groep.actief},
        )
        aantal = session.scalar(
            select(func.count())
            .select_from(Administratie)
            .where(Administratie.groep_id == groep_id, Administratie.actief.is_(True))
        )
        return _info(groep, int(aantal or 0))


def zet_administratie_groep(
    *, actor_id: uuid.UUID, administratie_id: uuid.UUID, groep_id: uuid.UUID | None
) -> GroepInfo | None:
    """Groep van een administratie zetten of wissen (None). Alleen een ACTIEVE groep is toekenbaar; de administratie-
    rij zelf kent geen RLS, de Beheerder-poort is de router. Audit `administratie_groep_gewijzigd` oud→nieuw mét
    code én naam (leesbaar in de tijdlijn zonder GUID-lookup). Geen stille no-op-detectie (patroon toggles)."""
    with scoped_session(None, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise BeheerFout(f"Onbekende administratie: {administratie_id}")
        nieuw: Groep | None = None
        if groep_id is not None:
            nieuw = session.get(Groep, groep_id)
            if nieuw is None:
                raise GroepOnbekend(f"Onbekende groep: {groep_id}")
            if not nieuw.actief:
                raise GroepGearchiveerd(
                    f"Groep {nieuw.naam} is gearchiveerd — heractiveer 'm eerst of kies een andere."
                )
        oud = session.get(Groep, administratie.groep_id) if administratie.groep_id else None
        administratie.groep_id = groep_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="administratie_groep_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=_groep_waarde(oud),
            nieuwe_waarde=_groep_waarde(nieuw),
        )
        if nieuw is None:
            return None
        aantal = session.scalar(
            select(func.count())
            .select_from(Administratie)
            .where(Administratie.groep_id == nieuw.id, Administratie.actief.is_(True))
        )
        return _info(nieuw, int(aantal or 0))


@dataclass(frozen=True)
class BulkRij:
    administratie_id: uuid.UUID
    naam: str
    #: "toegevoegd" | "verhuisd" | "verwijderd" | "overgeslagen"
    uitkomst: str
    #: Bij "verhuisd": de naam van de groep waar de administratie vandaan kwam; bij "overgeslagen": de reden.
    detail: str | None = None


@dataclass(frozen=True)
class BulkUitkomst:
    groep: GroepInfo
    rijen: list[BulkRij]

    @property
    def toegevoegd(self) -> int:
        return sum(1 for r in self.rijen if r.uitkomst in ("toegevoegd", "verhuisd"))

    @property
    def verwijderd(self) -> int:
        return sum(1 for r in self.rijen if r.uitkomst == "verwijderd")


def zet_groep_bulk(
    *,
    actor_id: uuid.UUID,
    groep_id: uuid.UUID,
    toevoegen: list[uuid.UUID],
    verwijderen: list[uuid.UUID],
) -> BulkUitkomst:
    """Bulk-toewijzing 16-09 (Peter: "nu moet ik 1 voor 1 doen"): meerdere administraties in ÉÉN transactie aan een
    groep toevoegen en/of eruit halen — per administratie dezelfde audit `administratie_groep_gewijzigd` oud→nieuw
    als de enkelvoudige route. Regels: gearchiveerde groep = GroepGearchiveerd (409, niets gewijzigd); onbekende
    groep = GroepOnbekend (404); onbekende administratie = BeheerFout (404, hele transactie terug — geen half werk);
    een administratie die al lid is = "overgeslagen: al lid" (geen audit, idempotent); lid van een ANDERE groep =
    "verhuisd" mét de oude groepsnaam (de UI vraagt daar vooraf bevestiging voor); `verwijderen` haalt alleen leden
    van DEZE groep eruit — een administratie in een andere groep wordt niet stil losgemaakt ("overgeslagen: zit in
    groep X")."""
    with scoped_session(None, actor_id=actor_id) as session:
        groep = session.get(Groep, groep_id)
        if groep is None:
            raise GroepOnbekend(f"Onbekende groep: {groep_id}")
        if not groep.actief and toevoegen:
            raise GroepGearchiveerd(f"Groep {groep.naam} is gearchiveerd — heractiveer 'm eerst of kies een andere.")
        rijen: list[BulkRij] = []
        gezien: set[uuid.UUID] = set()

        def _administratie(aid: uuid.UUID) -> Administratie:
            administratie = session.get(Administratie, aid)
            if administratie is None:
                raise BeheerFout(f"Onbekende administratie: {aid}")
            return administratie

        def _audit(administratie: Administratie, oud: Groep | None, nieuw: Groep | None) -> None:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="platform",
                tabel="administratie",
                record_id=administratie.id,
                actie="administratie_groep_gewijzigd",
                correlatie_id=correlatie,
                oude_waarde=_groep_waarde(oud),
                nieuwe_waarde=_groep_waarde(nieuw),
            )

        correlatie = uuid.uuid4()
        for aid in toevoegen:
            if aid in gezien:
                continue
            gezien.add(aid)
            administratie = _administratie(aid)
            if administratie.groep_id == groep.id:
                rijen.append(BulkRij(aid, administratie.naam, "overgeslagen", "al lid van deze groep"))
                continue
            oud = session.get(Groep, administratie.groep_id) if administratie.groep_id else None
            administratie.groep_id = groep.id
            _audit(administratie, oud, groep)
            if oud is None:
                rijen.append(BulkRij(aid, administratie.naam, "toegevoegd"))
            else:
                rijen.append(BulkRij(aid, administratie.naam, "verhuisd", oud.naam))
        for aid in verwijderen:
            if aid in gezien:
                continue
            gezien.add(aid)
            administratie = _administratie(aid)
            if administratie.groep_id != groep.id:
                andere = session.get(Groep, administratie.groep_id) if administratie.groep_id else None
                reden = f"zit in groep {andere.naam}" if andere else "zit niet in een groep"
                rijen.append(BulkRij(aid, administratie.naam, "overgeslagen", reden))
                continue
            administratie.groep_id = None
            _audit(administratie, groep, None)
            rijen.append(BulkRij(aid, administratie.naam, "verwijderd"))
        session.flush()
        aantal = session.scalar(
            select(func.count())
            .select_from(Administratie)
            .where(Administratie.groep_id == groep.id, Administratie.actief.is_(True))
        )
        return BulkUitkomst(groep=_info(groep, int(aantal or 0)), rijen=rijen)


def _groep_waarde(groep: Groep | None) -> dict:
    if groep is None:
        return {"groep_id": None, "groep_code": None, "groep_naam": None}
    return {"groep_id": str(groep.id), "groep_code": groep.code, "groep_naam": groep.naam}


def administratie_ids_in_groep(groep_id: uuid.UUID) -> set[uuid.UUID]:
    """Filterbron voor de kantoorbrede overzichten: id's van álle administraties (ook gearchiveerde — de aanroeper
    filtert al op actief/scope) in deze groep. Onbekende groep = lege set (filter levert niets, geen fout)."""
    with scoped_session(None) as session:
        return set(session.scalars(select(Administratie.id).where(Administratie.groep_id == groep_id)))


def groep_per_administratie(administratie_ids: list[uuid.UUID]) -> dict[uuid.UUID, GroepInfo]:
    """Verrijking van administratie-DTO's: {administratie_id: groep} voor de gegeven administraties (alleen die mét
    groep). Eén query, geen N+1."""
    if not administratie_ids:
        return {}
    with scoped_session(None) as session:
        rijen = session.execute(
            select(Administratie.id, Groep)
            .join(Groep, Groep.id == Administratie.groep_id)
            .where(Administratie.id.in_(administratie_ids))
        ).all()
        tellingen = dict(
            session.execute(
                select(Administratie.groep_id, func.count())
                .where(Administratie.groep_id.is_not(None), Administratie.actief.is_(True))
                .group_by(Administratie.groep_id)
            ).all()
        )
        return {aid: _info(g, int(tellingen.get(g.id, 0))) for aid, g in rijen}
