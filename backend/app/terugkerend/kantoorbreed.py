"""Inzicht › Terugkerende facturen KANTOORBREED (design-ronde 03-09 blok B1; mockup
`inzicht-kantoorbreed.html` paneel 1 + ontwerpnotities ①②⑨ = bouwnorm; principe "minimale mens,
maximale autonomie", besluit Peter 02-09).

Het autoboek-kandidaten-patroon: één endpoint zónder administratie in het pad, scope = de
administraties van de actor (`mijn_administraties`, Beheerder = alle actieve), per administratie
gelezen in `scoped_session(aid, actor_id=…)` — RLS blijft de scope-waarheid, nooit
`scoped_session(None)` voor administratie-gebonden rijen. Aggregeren/sorteren/pagineren in Python.

Eén RIJ = één SIGNAAL (ontbreekt óf prijsstijging) — een leverancier met beide krijgt twee rijen,
omdat elke rij precies één handeling draagt (②): ontbreekt → "Navragen bij leverancier…"
(concept-mail, de MENS bewerkt en verstuurt), prijsstijging → "Naar de boeking →". Urgentste bovenaan:
ontbreekt op meeste dagen te laat, daarna prijsstijging op hoogste %. Status-facet = filter, nooit
poort. Alleen lezen + één mail op mensklik; geen RLZ-writes, geen AI."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import select

from app.auth import service as auth_service
from app.berichten import mail
from app.db.audit import record_audit_event
from app.db.models import Administratie, GebruikerRol
from app.db.session import scoped_session
from app.sync.models import VendorCache
from app.terugkerend.models import TerugkerendSignaal
from app.terugkerend.service import TerugkerendFout

PER_PAGINA = 25
STATUSSEN = ("aandacht", "gesnoozed", "afgemeld", "alle")
SOORTEN = ("ontbreekt", "prijsstijging")
_E_MAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


@dataclass(frozen=True)
class KantoorRij:
    administratie_id: uuid.UUID
    administratie_naam: str
    vendor_id: uuid.UUID
    leverancier: str | None
    soort: str  # ontbreekt | prijsstijging
    status: str  # aandacht | gesnoozed | afgemeld
    patroon: str
    interval_dagen: int
    aantal_facturen: int
    laatste_datum: date
    laatste_bedrag: Decimal | None
    laatste_document_id: uuid.UUID | None
    vorige_datum: date | None
    vorige_bedrag: Decimal | None
    verwacht_op: date
    uiterlijk_op: date
    dagen_te_laat: int | None
    prijsstijging_pct: Decimal | None
    snooze_tot: date | None
    afgemeld_op: datetime | None
    berekend_op: datetime


@dataclass(frozen=True)
class AdministratieFacet:
    administratie_id: uuid.UUID
    naam: str
    aantal: int


@dataclass(frozen=True)
class Tellers:
    ontbrekend: int  # aandacht nodig, kantoorbreed binnen de scope
    prijsstijging: int
    administraties: int  # administraties mét ≥ 1 signaal dat aandacht nodig heeft


@dataclass(frozen=True)
class Facetten:
    status: dict[str, int]  # aandacht | gesnoozed | afgemeld | alle → aantal (binnen administratie + q)
    administraties: list[AdministratieFacet]


@dataclass(frozen=True)
class KantoorLijst:
    rijen: list[KantoorRij]
    totaal: int
    pagina: int
    per_pagina: int
    administraties_in_selectie: int
    tellers: Tellers
    facetten: Facetten


def _rij_status(rij: TerugkerendSignaal, soort: str, vandaag: date) -> str:
    """Afgemeld = per leverancier, dus beide soorten; snooze gaat over de ontbrekende factuur en
    raakt een prijsstijging-rij niet (die is een feit op een bestaande boeking)."""
    if rij.afgemeld_op is not None:
        return "afgemeld"
    if soort == "ontbreekt" and rij.snooze_tot is not None and rij.snooze_tot > vandaag:
        return "gesnoozed"
    return "aandacht"


def _rijen_voor(
    rij: TerugkerendSignaal, *, aid: uuid.UUID, naam: str, leverancier: str | None, vandaag: date
) -> list[KantoorRij]:
    uit: list[KantoorRij] = []
    soorten: list[str] = []
    if rij.ontbreekt_sinds is not None:
        soorten.append("ontbreekt")
    if rij.prijsstijging_pct is not None:
        soorten.append("prijsstijging")
    for soort in soorten:
        uit.append(
            KantoorRij(
                administratie_id=aid,
                administratie_naam=naam,
                vendor_id=rij.vendor_id,
                leverancier=leverancier,
                soort=soort,
                status=_rij_status(rij, soort, vandaag),
                patroon=rij.patroon,
                interval_dagen=rij.interval_dagen,
                aantal_facturen=rij.aantal_facturen,
                laatste_datum=rij.laatste_datum,
                laatste_bedrag=rij.laatste_bedrag,
                laatste_document_id=rij.laatste_document_id,
                vorige_datum=rij.vorige_datum,
                vorige_bedrag=rij.vorige_bedrag,
                verwacht_op=rij.verwacht_op,
                uiterlijk_op=rij.uiterlijk_op,
                dagen_te_laat=(vandaag - rij.uiterlijk_op).days if soort == "ontbreekt" else None,
                prijsstijging_pct=rij.prijsstijging_pct if soort == "prijsstijging" else None,
                snooze_tot=rij.snooze_tot,
                afgemeld_op=rij.afgemeld_op,
                berekend_op=rij.berekend_op,
            )
        )
    return uit


def _alle_rijen(*, actor_id: uuid.UUID, rol: GebruikerRol, vandaag: date) -> list[KantoorRij]:
    """Scope = mijn_administraties; per administratie in een gescoopte sessie mét actor (RLS-les 25-08)."""
    administraties = [(a.id, a.naam) for a in auth_service.mijn_administraties(actor_id=actor_id, rol=rol)]
    uit: list[KantoorRij] = []
    for aid, naam in administraties:
        with scoped_session(aid, actor_id=actor_id) as session:
            rijen = session.scalars(select(TerugkerendSignaal).where(TerugkerendSignaal.administratie_id == aid)).all()
            if not rijen:
                continue
            namen = dict(
                session.execute(
                    select(VendorCache.id, VendorCache.naam).where(
                        VendorCache.administratie_id == aid, VendorCache.id.in_([r.vendor_id for r in rijen])
                    )
                ).all()
            )
            for r in rijen:
                uit.extend(_rijen_voor(r, aid=aid, naam=naam, leverancier=namen.get(r.vendor_id), vandaag=vandaag))
    return uit


def _urgentie(r: KantoorRij) -> tuple:
    """Ontbreekt vóór prijsstijging; binnen ontbreekt de meeste dagen te laat eerst, binnen
    prijsstijging het hoogste % eerst; daarna alfabetisch (stabiel, deterministisch)."""
    return (
        0 if r.soort == "ontbreekt" else 1,
        -(r.dagen_te_laat or 0),
        -(r.prijsstijging_pct or Decimal(0)),
        (r.leverancier or "").lower(),
        r.administratie_naam.lower(),
    )


def lijst(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    pagina: int = 1,
    q: str = "",
    administratie_id: uuid.UUID | None = None,
    status: str = "aandacht",
    per_pagina: int = PER_PAGINA,
    vandaag: date | None = None,
) -> KantoorLijst:
    if status not in STATUSSEN:
        raise TerugkerendFout(f"Onbekende status: {status}")
    vandaag = vandaag or datetime.now(UTC).date()
    alles = _alle_rijen(actor_id=actor_id, rol=rol, vandaag=vandaag)
    aandacht = [r for r in alles if r.status == "aandacht"]
    tellers = Tellers(
        ontbrekend=sum(1 for r in aandacht if r.soort == "ontbreekt"),
        prijsstijging=sum(1 for r in aandacht if r.soort == "prijsstijging"),
        administraties=len({r.administratie_id for r in aandacht}),
    )
    # Facet-waarden: administraties tellen binnen de zoekterm + status, status telt binnen administratie + zoekterm.
    zoek = q.strip().lower()
    na_q = [r for r in alles if not zoek or zoek in (r.leverancier or "").lower()]
    na_admin = [r for r in na_q if administratie_id is None or r.administratie_id == administratie_id]
    status_facet = {s: len([r for r in na_admin if s == "alle" or r.status == s]) for s in STATUSSEN}
    na_status = [r for r in na_q if status == "alle" or r.status == status]
    per_admin: dict[uuid.UUID, AdministratieFacet] = {}
    for r in na_status:
        f = per_admin.get(r.administratie_id)
        per_admin[r.administratie_id] = AdministratieFacet(
            administratie_id=r.administratie_id, naam=r.administratie_naam, aantal=(f.aantal if f else 0) + 1
        )
    selectie = [r for r in na_admin if status == "alle" or r.status == status]
    selectie.sort(key=_urgentie)
    start = max(pagina - 1, 0) * per_pagina
    return KantoorLijst(
        rijen=selectie[start : start + per_pagina],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=per_pagina,
        administraties_in_selectie=len({r.administratie_id for r in selectie}),
        tellers=tellers,
        facetten=Facetten(
            status=status_facet,
            administraties=sorted(per_admin.values(), key=lambda f: f.naam.lower()),
        ),
    )


# --- concept-mail "Navragen bij leverancier…" (②) ------------------------------------------------


@dataclass(frozen=True)
class ConceptMail:
    ontvanger_e_mail: str | None  # uit de vendor-cache (RLZ-veld Email) als bekend, anders leeg → mens vult in
    leverancier: str | None
    administratie_naam: str
    onderwerp: str
    tekst: str


def _bedrag(waarde: Decimal | None) -> str:
    return (
        f"€ {waarde:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".") if waarde is not None else "onbekend"
    )


def _datum(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def _maand_nl(d: date) -> str:
    maanden = (
        "januari",
        "februari",
        "maart",
        "april",
        "mei",
        "juni",
        "juli",
        "augustus",
        "september",
        "oktober",
        "november",
        "december",
    )
    return f"{maanden[d.month - 1]} {d.year}"


def _signaal_en_context(
    session, administratie_id: uuid.UUID, vendor_id: uuid.UUID
) -> tuple[TerugkerendSignaal, str | None, str | None, str]:
    rij = session.scalars(
        select(TerugkerendSignaal).where(
            TerugkerendSignaal.administratie_id == administratie_id, TerugkerendSignaal.vendor_id == vendor_id
        )
    ).first()
    if rij is None:
        raise TerugkerendFout("Geen terugkerend patroon bekend voor deze leverancier")
    vendor = session.get(VendorCache, (vendor_id, administratie_id))
    administratie = session.get(Administratie, administratie_id)
    if administratie is None:
        raise TerugkerendFout(f"Onbekende administratie: {administratie_id}")
    e_mail = None
    if vendor is not None and isinstance(vendor.brondata, dict):
        kandidaat = vendor.brondata.get("Email")
        if isinstance(kandidaat, str) and _E_MAIL.match(kandidaat.strip()):
            e_mail = kandidaat.strip()
    return rij, (vendor.naam if vendor else None), e_mail, administratie.naam


def bouw_conceptmail(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID) -> ConceptMail:
    """Deterministische concepttekst (geen AI): leverancier, administratienaam, verwachte periode
    (maand/kwartaal van `verwacht_op`), laatste factuur (datum + bedrag). Genereren is lezen — er
    wordt niets verzonden of vastgelegd; de mens bewerkt en verstuurt expliciet."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij, leverancier, e_mail, administratie_naam = _signaal_en_context(session, administratie_id, vendor_id)
        laatste_datum, laatste_bedrag, verwacht_op, patroon = (
            rij.laatste_datum,
            rij.laatste_bedrag,
            rij.verwacht_op,
            rij.patroon,
        )
    aanhef = f"Beste {leverancier}," if leverancier else "Geachte heer/mevrouw,"
    periode = _maand_nl(verwacht_op) if patroon == "maand" else f"het kwartaal rond {_maand_nl(verwacht_op)}"
    ritme = "maandelijks" if patroon == "maand" else "per kwartaal"
    regels = [
        aanhef,
        "",
        f"Wij verzorgen de administratie van {administratie_naam}. Van u ontvangen wij {ritme} een factuur; "
        f"de laatste die wij hebben is die van {_datum(laatste_datum)} ({_bedrag(laatste_bedrag)}).",
        "",
        f"De factuur voor {periode} hebben wij nog niet ontvangen. Kunt u nagaan of deze al verstuurd is, "
        "en hem anders (opnieuw) sturen naar facturen@ak-nijenhuis.nl?",
        "",
        "Is er geen factuur meer te verwachten, bijvoorbeeld omdat het contract is beëindigd, dan horen wij dat "
        "ook graag.",
        "",
        "Met vriendelijke groet,",
        "Administratiekantoor Nijenhuis",
    ]
    return ConceptMail(
        ontvanger_e_mail=e_mail,
        leverancier=leverancier,
        administratie_naam=administratie_naam,
        onderwerp=f"Vraag over de factuur voor {periode} — {administratie_naam}",
        tekst="\n".join(regels),
    )


def verstuur_conceptmail(
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    actor_id: uuid.UUID,
    naar: str,
    onderwerp: str,
    tekst: str,
) -> str:
    """Verzend de door de MENS gereviewde navraag via het gedeelde SMTP-kanaal (fail-zichtbaar:
    MailNietGeconfigureerd/MailVerzendFout raise-n door naar de router) en leg de verzending vast in
    audit_event (patroon factuurmatch_mail). Nooit automatisch. Retourneert het ontvangeradres."""
    naar = naar.strip()
    onderwerp = onderwerp.strip()
    tekst = tekst.strip()
    if not _E_MAIL.match(naar):
        raise TerugkerendFout("Vul een geldig e-mailadres van de leverancier in")
    if not onderwerp or not tekst:
        raise TerugkerendFout("Onderwerp en tekst zijn verplicht — een lege mail versturen kan niet")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij, leverancier, _, _ = _signaal_en_context(session, administratie_id, vendor_id)
        signaal_id = rij.id
    # Verzenden buiten de DB-transactie: een SMTP-fout raise-t hier en er wordt dan niets vastgelegd.
    mail.verzend_mail(naar=naar, onderwerp=onderwerp, tekst=tekst)
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="terugkerend_signaal",
            record_id=signaal_id,
            actie="terugkerend_navraag_verzonden",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "aan": naar,
                "onderwerp": onderwerp,
                "vendor_id": str(vendor_id),
                "leverancier": leverancier,
                "verzonden_op": datetime.now(UTC).isoformat(),
            },
            administratie_id=administratie_id,
        )
    return naar


__all__ = [
    "PER_PAGINA",
    "STATUSSEN",
    "ConceptMail",
    "KantoorLijst",
    "KantoorRij",
    "bouw_conceptmail",
    "lijst",
    "verstuur_conceptmail",
]
