"""Administratienaam — bewerkbaar in de module + volgt de bron (opdracht Peter 15-09; migratie 0144).

Casus: Camping "Nieuwenhoven" is in Odoo ná het koppelen hernoemd naar "Strandpark Zilverduynen"; de module bleef de
oude naam tonen en had geen veld om 'm te wijzigen. Twee regels, één schrijver (deze module):

A. **Naam bewerkbaar** — `wijzig_naam` (Beheerder-only via de router): inline op Instellingen › Administraties ›
   ‹administratie› › Algemeen; audit `administratie_naam_gewijzigd` oud→nieuw; zet `naam_bron='mens'`. Een naam die al
   (hoofdletter-ongevoelig) bij een andere administratie staat = `NaamBezet` → 409 mét leesbare reden. Overal waar de
   naam getoond wordt (klantenlijst, tellers-cache, combobox, reconciliatie) wordt `administratie.naam` live gelezen —
   er is geen gedenormaliseerde naam-kolom, dus geen cache-invalidatie nodig (gecontroleerd 15-09: grep
   `administratie_naam` over app/*/models.py = 0).
B. **Naam volgt de bron** — bij élke stamgegevens-sync leest de adapter de bronnaam (Odoo `res.company.name` via
   `app/odoo/probe.py::lees_company_naam`, RLZ `Administrations.Name` via `RlzClient.list_administrations`) en roept
   `volg_bronnaam` aan: `bron_naam`/`bron_naam_gezien_op` worden altijd vastgelegd; staat `naam_bron` ≠ 'mens' dan volgt
   de module de bronnaam (audit `administratie_naam_gevolgd` oud→nieuw, `naam_gevolgd_op`); staat 'mens' dan blijft de
   naam staan en toont de UI de chip "in Odoo/Reeleezee heet deze administratie nu ‹naam›" + "Naam overnemen"
   (`neem_bronnaam_over`: zet de naam, houdt `naam_bron='mens'`). Een bronnaam die bij een ANDERE administratie bezet is
   wordt niet gevolgd (uitkomst `bezet`, zichtbaar in de sync-regel) — nooit twee administraties met dezelfde naam.
C. **Backfill** (data-stap, CLI `administratie-naam-bron-backfill`, dry-run default): per actieve administratie de LIVE
   bronnaam lezen; huidige naam == bronnaam → `naam_bron` = bron (voortaan volgen), anders blijft 'mens' mét de bronnaam
   vastgelegd (chip). Bron niet leesbaar (geen credential, Odoo-fout) = zichtbaar overgeslagen, blijft 'mens'.

Kernprincipes: RLZ/Odoo is de bron van waarheid (KP1) — de naam volgt de bron tenzij een mens bewust anders koos; niets
verdwijnt stil (KP4) — élke naamwissel in het audit_event; leeg = doorlopen (KP7.6) — een onleesbare bron blokkeert de
sync nooit.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from sqlalchemy import func, select

from app.beheer.service import BeheerFout
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

logger = logging.getLogger(__name__)

Bron = Literal["odoo", "rlz"]
NaamBron = Literal["odoo", "rlz", "mens"]
NAAM_MAX_LENGTE = 200
BRON_LABEL: dict[str, str] = {"odoo": "Odoo", "rlz": "Reeleezee"}

#: Uitkomsten van `volg_bronnaam` — leesbaar in de sync-regel en het rapport.
UITKOMST_GEVOLGD = "gevolgd"  # naam_bron ≠ mens, bronnaam ≠ naam → naam overgenomen
UITKOMST_GELIJK = "gelijk"  # bronnaam == naam (niets te doen; bron_naam wél ververst)
UITKOMST_AFWIJKEND_MENS = "afwijkend_mens"  # mens-naam blijft, chip "in <bron> heet deze administratie nu …"
UITKOMST_BEZET = "bezet"  # bronnaam bij een andere administratie in gebruik → niet gevolgd
UITKOMST_ONBEKEND = "onbekend"  # bron gaf geen naam (niet leesbaar) → niets gewijzigd


class NaamFout(BeheerFout):
    """Basis voor de leesbare naam-fouten (router vertaalt naar 409/422)."""


class NaamOngeldig(NaamFout):
    """Leeg of te lang."""


class NaamBezet(NaamFout):
    """Al in gebruik bij een andere administratie (hoofdletter-ongevoelig)."""

    def __init__(self, naam: str, andere: Administratie) -> None:
        self.naam = naam
        self.andere_id = andere.id
        self.andere_naam = andere.naam
        stand = "" if andere.actief else " (gearchiveerd)"
        super().__init__(f'De naam "{naam}" is al in gebruik bij administratie "{andere.naam}"{stand}.')


class GeenBronnaam(NaamFout):
    """Overnemen zonder bekende bronnaam."""


@dataclass(frozen=True)
class NaamStand:
    administratie_id: uuid.UUID
    naam: str
    naam_bron: str
    bron_naam: str | None
    bron_naam_gezien_op: datetime | None
    naam_gevolgd_op: datetime | None

    @property
    def bron_afwijkend(self) -> bool:
        """De bron kent een andere naam dan de module toont (alleen zinvol bij naam_bron == 'mens')."""
        return bool(self.bron_naam) and _vergelijkbaar(self.bron_naam or "") != _vergelijkbaar(self.naam)


def _schoon(naam: str | None) -> str:
    return " ".join((naam or "").split())


def _vergelijkbaar(naam: str) -> str:
    return _schoon(naam).casefold()


def _valideer(naam: str) -> str:
    schoon = _schoon(naam)
    if not schoon:
        raise NaamOngeldig("De naam mag niet leeg zijn.")
    if len(schoon) > NAAM_MAX_LENGTE:
        raise NaamOngeldig(f"De naam mag hoogstens {NAAM_MAX_LENGTE} tekens lang zijn.")
    return schoon


def _andere_met_naam(session, *, naam: str, behalve: uuid.UUID) -> Administratie | None:  # noqa: ANN001
    """Hoofdletter-ongevoelige botsing met élke andere administratie (ook gearchiveerd — die kan terugkomen)."""
    return session.scalars(
        select(Administratie)
        .where(func.lower(Administratie.naam) == naam.casefold(), Administratie.id != behalve)
        .order_by(Administratie.actief.desc(), Administratie.naam)
        .limit(1)
    ).first()


def stand_van(administratie: Administratie) -> NaamStand:
    return NaamStand(
        administratie_id=administratie.id,
        naam=administratie.naam,
        naam_bron=administratie.naam_bron,
        bron_naam=administratie.bron_naam,
        bron_naam_gezien_op=administratie.bron_naam_gezien_op,
        naam_gevolgd_op=administratie.naam_gevolgd_op,
    )


def _naam_waarde(administratie: Administratie) -> dict[str, Any]:
    return {"naam": administratie.naam, "naam_bron": administratie.naam_bron}


def _laad(session, administratie_id: uuid.UUID) -> Administratie:  # noqa: ANN001
    administratie = session.get(Administratie, administratie_id)
    if administratie is None:
        raise BeheerFout(f"Onbekende administratie: {administratie_id}")
    return administratie


# --- A. Naam bewerkbaar (Beheerder) ----------------------------------------------------------------------------------


def haal_stand_op(administratie_id: uuid.UUID) -> NaamStand:
    with scoped_session(None) as session:
        return stand_van(_laad(session, administratie_id))


def wijzig_naam(*, actor_id: uuid.UUID, administratie_id: uuid.UUID, naam: str) -> NaamStand:
    """Naam zetten door een mens: `naam_bron` wordt 'mens' (de bron overschrijft 'm voortaan niet meer), audit
    `administratie_naam_gewijzigd` oud→nieuw. Dezelfde naam opnieuw opslaan = geen wijziging, geen audit."""
    schoon = _valideer(naam)
    # Gescoopt op de administratie: het audit_event draagt administratie_id (tijdlijn per administratie) en de
    # RLS-policy op audit_event eist dan de scope-context; `administratie` zelf kent geen RLS (botsing ziet alles).
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = _laad(session, administratie_id)
        if schoon == administratie.naam and administratie.naam_bron == "mens":
            return stand_van(administratie)
        andere = _andere_met_naam(session, naam=schoon, behalve=administratie_id)
        if andere is not None:
            raise NaamBezet(schoon, andere)
        oud = _naam_waarde(administratie)
        administratie.naam = schoon
        administratie.naam_bron = "mens"
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="administratie_naam_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={**_naam_waarde(administratie), "via": "handmatig"},
            administratie_id=administratie_id,
        )
        session.flush()
        return stand_van(administratie)


def neem_bronnaam_over(*, actor_id: uuid.UUID, administratie_id: uuid.UUID) -> NaamStand:
    """Linkbtn "Naam overnemen" op de chip: de module neemt de laatst gelezen bronnaam over, `naam_bron` BLIJFT 'mens'
    (een bewuste menselijke keuze; de bron krijgt niet stil weer het stuur). Audit `administratie_naam_gewijzigd` mét
    `via: bron_overgenomen`."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = _laad(session, administratie_id)
        bronnaam = _schoon(administratie.bron_naam)
        if not bronnaam:
            raise GeenBronnaam("Er is nog geen naam uit de bron gelezen — de eerstvolgende sync haalt 'm op.")
        if _vergelijkbaar(bronnaam) == _vergelijkbaar(administratie.naam) and administratie.naam == bronnaam:
            return stand_van(administratie)
        andere = _andere_met_naam(session, naam=bronnaam, behalve=administratie_id)
        if andere is not None:
            raise NaamBezet(bronnaam, andere)
        oud = _naam_waarde(administratie)
        administratie.naam = bronnaam
        administratie.naam_bron = "mens"
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="administratie",
            record_id=administratie_id,
            actie="administratie_naam_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={**_naam_waarde(administratie), "via": "bron_overgenomen"},
            administratie_id=administratie_id,
        )
        session.flush()
        return stand_van(administratie)


# --- B. Naam volgt de bron (sync) ------------------------------------------------------------------------------------


def naam_uit_administrations(rijen: list[dict[str, Any]], rlz_admin_id: str) -> str | None:
    """`GET Administrations` → de `Name` van precies onze administratie (id-vergelijking hoofdletter-ongevoelig);
    None als de login 'm niet ziet of de naam leeg is."""
    doel = str(rlz_admin_id).casefold()
    for rij in rijen or []:
        if not isinstance(rij, dict) or rij.get("id") is None:
            continue
        if str(rij["id"]).casefold() != doel:
            continue
        naam = _schoon(str(rij.get("Name") or rij.get("name") or ""))
        return naam or None
    return None


def verwerk_bronnaam(
    session,  # noqa: ANN001
    administratie: Administratie,
    *,
    bron: Bron,
    bronnaam: str | None,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    now: datetime | None = None,
) -> str:
    """Kern van B, binnen een bestaande sessie (de Odoo-sync schrijft 'm in dezelfde transactie als de caches).
    Retourneert één van de UITKOMST_*-constanten."""
    now = now or datetime.now(UTC)
    bronnaam = _schoon(bronnaam) or None
    if bronnaam is None:
        return UITKOMST_ONBEKEND
    administratie.bron_naam = bronnaam
    administratie.bron_naam_gezien_op = now
    if _vergelijkbaar(bronnaam) == _vergelijkbaar(administratie.naam):
        if administratie.naam_bron != "mens" and administratie.naam_bron != bron:
            administratie.naam_bron = bron  # backend gewisseld (RLZ → Odoo): het label volgt de huidige bron
        return UITKOMST_GELIJK
    if administratie.naam_bron == "mens":
        return UITKOMST_AFWIJKEND_MENS
    andere = _andere_met_naam(session, naam=bronnaam, behalve=administratie.id)
    if andere is not None:
        logger.warning(
            "administratienaam %s niet gevolgd: bronnaam %r is bezet door administratie %s",
            administratie.id,
            bronnaam,
            andere.id,
        )
        return UITKOMST_BEZET
    oud = _naam_waarde(administratie)
    administratie.naam = bronnaam
    administratie.naam_bron = bron
    administratie.naam_gevolgd_op = now
    record_audit_event(
        session,
        actor_id=actor_id,
        module="platform",
        tabel="administratie",
        record_id=administratie.id,
        actie="administratie_naam_gevolgd",
        correlatie_id=uuid.uuid4(),
        oude_waarde=oud,
        nieuwe_waarde={**_naam_waarde(administratie), "bron": bron},
        administratie_id=administratie.id,
    )
    return UITKOMST_GEVOLGD


def volg_bronnaam(
    administratie_id: uuid.UUID, *, bron: Bron, bronnaam: str | None, actor_id: uuid.UUID = SYSTEEM_ACTOR_ID
) -> str:
    """B in een eigen transactie (RLZ-sync-pad, backfill). Faalt nooit richting de sync: een onbekende administratie
    geeft `onbekend`."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            return UITKOMST_ONBEKEND
        return verwerk_bronnaam(session, administratie, bron=bron, bronnaam=bronnaam, actor_id=actor_id)


def volg_uit_rlz(administratie_id: uuid.UUID, client, *, actor_id: uuid.UUID = SYSTEEM_ACTOR_ID) -> str:  # noqa: ANN001
    """RLZ-pad: `Administrations` via de gedeelde login (root-vorm), naam van ónze administratie eruit, dan B.
    Een RLZ-fout (403 op Administrations, webfilter) = `onbekend` mét logregel — de stamgegevens-sync blijft groen."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        rlz_admin_id = administratie.rlz_admin_id if administratie is not None else None
    if not rlz_admin_id:
        return UITKOMST_ONBEKEND
    try:
        rijen = client.list_administrations()
    except Exception as exc:  # noqa: BLE001 — bewust breed: de naam mag de sync nooit rood maken
        logger.warning("administratienaam %s: Administrations niet leesbaar (%s)", administratie_id, exc)
        return UITKOMST_ONBEKEND
    return volg_bronnaam(
        administratie_id, bron="rlz", bronnaam=naam_uit_administrations(rijen, rlz_admin_id), actor_id=actor_id
    )


# --- C. Backfill (data-stap ná migratie 0144) ------------------------------------------------------------------------


@dataclass(frozen=True)
class BackfillRegel:
    administratie_id: uuid.UUID
    naam: str
    bron: str  # 'odoo' | 'rlz'
    bronnaam: str | None
    uitkomst: str  # 'bron_gezet' | 'blijft_mens' | 'al_gezet' | 'overgeslagen'
    detail: str = ""


def lees_bronnaam_live(administratie_id: uuid.UUID) -> tuple[Bron, str | None, str]:
    """Live bronlezing voor de backfill: (bron, naam|None, detail). Odoo via `odoo_client_voor(read_only=True)` +
    `lees_company_naam`; RLZ via de root-client. Geen credential/fout = (bron, None, reden) — nooit een exception."""
    from app.backends.registry import Backend, OnbekendeBackend, backend_voor

    try:
        is_odoo = backend_voor(administratie_id) is Backend.ODOO
    except OnbekendeBackend:
        return "rlz", None, "onbekende backend"
    if is_odoo:
        from app.odoo.credentials import odoo_client_voor
        from app.odoo.probe import lees_company_naam

        try:
            client = odoo_client_voor(administratie_id, read_only=True)
        except Exception as exc:  # noqa: BLE001
            return "odoo", None, f"geen Odoo-koppeling/credential ({exc})"
        try:
            naam = lees_company_naam(client)
        finally:
            client.close()
        return "odoo", naam, "" if naam else "company niet leesbaar"
    from app.rlz.credentials import GeenRlzCredentials, open_root_client, rlz_admin_id_voor

    try:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = open_root_client(rlz_admin_id)
    except GeenRlzCredentials as exc:
        return "rlz", None, f"geen RLZ-credential ({exc})"
    try:
        rijen = client.list_administrations()
    except Exception as exc:  # noqa: BLE001
        return "rlz", None, f"Administrations niet leesbaar ({exc})"
    finally:
        client.close()
    naam = naam_uit_administrations(rijen, rlz_admin_id)
    return "rlz", naam, "" if naam else "login ziet deze administratie niet"


def backfill_naam_bron(
    *, dry_run: bool = True, administratie_id: uuid.UUID | None = None, actor_id: uuid.UUID = SYSTEEM_ACTOR_ID
) -> list[BackfillRegel]:
    """Per actieve administratie (of één): huidige naam == live bronnaam → `naam_bron` = bron (audit
    `administratie_naam_bron_backfill`); afwijkend → blijft 'mens', bronnaam vastgelegd (chip); al ≠ 'mens' → al_gezet;
    bron onleesbaar → overgeslagen. Idempotent; dry-run schrijft niets."""
    with scoped_session(None) as session:
        q = select(Administratie).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
        if administratie_id is not None:
            q = select(Administratie).where(Administratie.id == administratie_id)
        kandidaten = [(a.id, a.naam, a.naam_bron) for a in session.scalars(q)]
    regels: list[BackfillRegel] = []
    for aid, naam, naam_bron in kandidaten:
        if naam_bron != "mens":
            regels.append(BackfillRegel(aid, naam, naam_bron, None, "al_gezet", f"naam_bron={naam_bron}"))
            continue
        bron, bronnaam, detail = lees_bronnaam_live(aid)
        if bronnaam is None:
            regels.append(BackfillRegel(aid, naam, bron, None, "overgeslagen", detail))
            continue
        gelijk = _vergelijkbaar(bronnaam) == _vergelijkbaar(naam)
        uitkomst = "bron_gezet" if gelijk else "blijft_mens"
        if not dry_run:
            with scoped_session(aid, actor_id=actor_id) as session:
                administratie = _laad(session, aid)
                now = datetime.now(UTC)
                administratie.bron_naam = bronnaam
                administratie.bron_naam_gezien_op = now
                if gelijk:
                    oud = _naam_waarde(administratie)
                    administratie.naam_bron = bron
                    record_audit_event(
                        session,
                        actor_id=actor_id,
                        module="platform",
                        tabel="administratie",
                        record_id=aid,
                        actie="administratie_naam_bron_backfill",
                        correlatie_id=uuid.uuid4(),
                        oude_waarde=oud,
                        nieuwe_waarde={**_naam_waarde(administratie), "bron_naam": bronnaam},
                        administratie_id=aid,
                    )
        regels.append(BackfillRegel(aid, naam, bron, bronnaam, uitkomst, "" if gelijk else f"bron: {bronnaam}"))
    return regels
