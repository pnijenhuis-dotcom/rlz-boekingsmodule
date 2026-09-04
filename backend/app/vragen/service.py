"""Open vragen KANTOORBREED (design-ronde 03-09 blok B2; mockup `inzicht-kantoorbreed.html` paneel 2
"Inzicht › Open vragen" + ontwerpnotities ①④⑨; principe minimale mens, maximale autonomie — besluit
Peter 02-09, regel 1 "administratie is een filter, nooit een poort").

Vervangt de client-side N+1-fan-out van de werkvoorraad-dwarsdoorsnede (één `GET
/administraties/{id}/vragen` per klant mét teller > 0) door één server-side lijst over álle
administraties in de scope van de actor: oudste eerst, paginering 25, facet-filters (administratie /
"aan mij" / ouderdom), zoekterm, tellers. De per-administratie-routes in `app/documenten/vragen.py`
blijven bestaan als deeplink-doel (klantpagina `sectie=vragen`) en als schrijfkant (bericht plaatsen,
afhandelen, intrekken) — hier wordt uitsluitend GELEZEN, niets gemuteerd, geen RLZ-calls.

Scope-patroon (Platform conventies §RLS + autoboek-kandidaten-referentie): itereer over
`mijn_administraties(actor)` en lees per administratie in `scoped_session(aid, actor_id=actor)` — nooit
`scoped_session(None)` voor administratie-gebonden rijen. RLS blijft de scope-waarheid; de iteratie is de
tweede laag. Aggregeren/filteren/sorteren/pagineren in Python (de aantallen zijn klein: open vragen zijn
per definitie een werkvoorraad, geen archief).

ÉÉN definitie "open vraag" (B2.3): een `vraag`-rij met status 'open' op een document dat nog bestaat als
werkstuk — niet verwijderd, gesplitst of samengevoegd (`_DOCUMENT_WEG`). GEBOEKT telt hier — anders dan bij
de werkvoorraad-tellers — bewust NIET als terminaal: sinds blok B5 (26-08) laat een vraag aan de
klant-accordeur op een document dat bij de klant ligt of al geboekt is de documentstatus staan, en die vraag
wacht wél op antwoord. Sinds G1 (03-09) telt de klantenlijst-kolom "Vragen" (`WerkvoorraadKlant.vragen`,
`app/documenten/service.py`) DEZELFDE definitie via `tel_open_vragen` — één bron (`_open_vraag_voorwaarden`),
KPI-kaart en kolom kunnen niet meer uiteenlopen; `blokkeert_boeken` (document in `vraag_open`) blijft als
aparte teller zichtbaar.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import and_, func, select
from sqlalchemy.orm import Session

from app.auth import service as auth_service
from app.db.models import Gebruiker, GebruikerRol
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document, DocumentStatus, Vraag, VraagBericht, VraagStatus
from app.sync.models import VendorCache

PER_PAGINA = 25
TOEGEWEZEN_OPTIES = ("alle", "mij")
#: Vanaf hoeveel dagen wachten de chip oranje wordt (mockup: 8 dagen oranje, 2 dagen grijs).
WACHT_ORANJE_VANAF_DAGEN = 7
#: Documenten die als werkstuk verdwenen zijn — een open vraag daarop is geen werk meer. Geboekt
#: hoort hier bewust NIET bij (zie moduledocstring, blok B5).
_DOCUMENT_WEG = (DocumentStatus.VERWIJDERD, DocumentStatus.GESPLITST, DocumentStatus.SAMENGEVOEGD)


def _open_vraag_voorwaarden(administratie_id: uuid.UUID) -> tuple:
    """DE definitie "open vraag" als where-voorwaarden (B2.3/G1): `vraag`-rij met status open op een document
    van deze administratie dat nog bestaat als werkstuk. Vereist een join Vraag → Document. Zowel de
    kantoorbrede lijst/KPI als de klantenlijst-kolom "Vragen" lezen hier — nooit een tweede formulering."""
    return (
        Vraag.administratie_id == administratie_id,
        Vraag.status == VraagStatus.OPEN.value,
        Document.status.notin_(_DOCUMENT_WEG),
    )


def tel_open_vragen(session: Session, administratie_id: uuid.UUID) -> int:
    """Aantal open vragen van één administratie volgens de KPI-definitie (G1, 03-09) — pure leesquery in de
    door de aanroeper geopende `scoped_session(administratie_id, …)` (RLS op `vraag` toetst uitsluitend de
    administratie, geen actor nodig). Gebruikt door `werkvoorraad_overzicht` voor `WerkvoorraadKlant.vragen`,
    zodat de klantenlijst-kolom hetzelfde telt als de kaart "Open vragen"."""
    return (
        session.scalar(
            select(func.count())
            .select_from(Vraag)
            .join(Document, Vraag.document_id == Document.id)
            .where(*_open_vraag_voorwaarden(administratie_id))
        )
        or 0
    )


class OpenVragenFout(Exception):
    """Ongeldige filterwaarde (leesbare 422 in de router)."""


@dataclass(frozen=True)
class OpenVraagRij:
    vraag_id: uuid.UUID
    document_id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    vraag_tekst: str
    #: Laatste bijdrage in de thread (None = alleen de openingsvraag), mét auteur en tijdstip.
    laatste_bericht: str | None
    laatste_bericht_door: str | None
    laatste_bericht_op: datetime | None
    gesteld_door_id: uuid.UUID
    gesteld_door_naam: str | None
    gesteld_op: datetime
    aan_de_beurt_id: uuid.UUID
    aan_de_beurt_naam: str | None
    #: True als de actor zelf aan zet is ("aan u" in de mockup).
    aan_mij: bool
    wacht_dagen: int
    document_bestandsnaam: str
    document_status: str
    leverancier_naam: str | None
    referentie: str | None
    totaalbedrag: Decimal | None
    #: Document staat in `vraag_open` — de vraag houdt de boekknop dicht.
    blokkeert_boeken: bool


@dataclass(frozen=True)
class Tellers:
    open: int
    aan_mij: int
    blokkeert_boeken: int
    administraties: int


@dataclass(frozen=True)
class AdministratieFacet:
    administratie_id: uuid.UUID
    administratie_naam: str
    aantal: int


@dataclass(frozen=True)
class Lijst:
    rijen: list[OpenVraagRij]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: Tellers
    administraties: list[AdministratieFacet]


def _wacht_dagen(gesteld_op: datetime, nu: datetime) -> int:
    """Hele dagen sinds het stellen (kolom "Wacht sinds"); nooit negatief. Een naïeve timestamp
    (SQLite-achtige testdubbels) geldt als UTC — de kolom zelf is timestamptz (migratie 0022)."""
    if gesteld_op.tzinfo is None:
        gesteld_op = gesteld_op.replace(tzinfo=UTC)
    return max(0, (nu - gesteld_op).days)


def _alle_open_vragen(*, actor_id: uuid.UUID, rol: GebruikerRol, nu: datetime) -> list[OpenVraagRij]:
    administraties = auth_service.mijn_administraties(actor_id=actor_id, rol=rol)
    uit: list[OpenVraagRij] = []
    for administratie in administraties:
        aid = administratie.id
        with scoped_session(aid, actor_id=actor_id) as session:
            rijen = list(
                session.execute(
                    select(Vraag, Document, Boekvoorstel, VendorCache.naam)
                    .join(Document, Vraag.document_id == Document.id)
                    .outerjoin(Boekvoorstel, Boekvoorstel.document_id == Document.id)
                    .outerjoin(
                        VendorCache,
                        and_(VendorCache.id == Boekvoorstel.vendor_id, VendorCache.administratie_id == aid),
                    )
                    .where(*_open_vraag_voorwaarden(aid))
                    .order_by(Vraag.gesteld_op, Vraag.id)
                ).all()
            )
            if not rijen:
                continue
            vraag_ids = [vraag.id for vraag, _d, _b, _n in rijen]
            # Laatste bericht per vraag: nieuwste eerst ophalen, eerste treffer per vraag wint.
            laatste: dict[uuid.UUID, VraagBericht] = {}
            for bericht in session.scalars(
                select(VraagBericht)
                .where(VraagBericht.vraag_id.in_(vraag_ids))
                .order_by(VraagBericht.geplaatst_op.desc(), VraagBericht.id)
            ):
                laatste.setdefault(bericht.vraag_id, bericht)
            gebruiker_ids = {vraag.gesteld_door for vraag, _d, _b, _n in rijen}
            gebruiker_ids |= {vraag.aan_de_beurt or vraag.toegewezen_aan for vraag, _d, _b, _n in rijen}
            gebruiker_ids |= {b.auteur_id for b in laatste.values()}
            namen = dict(
                session.execute(select(Gebruiker.id, Gebruiker.naam).where(Gebruiker.id.in_(list(gebruiker_ids)))).all()
            )
            for vraag, document, voorstel, leverancier in rijen:
                aan_de_beurt = vraag.aan_de_beurt or vraag.toegewezen_aan
                bericht = laatste.get(vraag.id)
                uit.append(
                    OpenVraagRij(
                        vraag_id=vraag.id,
                        document_id=document.id,
                        administratie_id=aid,
                        administratie_naam=administratie.naam,
                        vraag_tekst=vraag.vraag_tekst,
                        laatste_bericht=bericht.tekst if bericht else None,
                        laatste_bericht_door=namen.get(bericht.auteur_id) if bericht else None,
                        laatste_bericht_op=bericht.geplaatst_op if bericht else None,
                        gesteld_door_id=vraag.gesteld_door,
                        gesteld_door_naam=namen.get(vraag.gesteld_door),
                        gesteld_op=vraag.gesteld_op,
                        aan_de_beurt_id=aan_de_beurt,
                        aan_de_beurt_naam=namen.get(aan_de_beurt),
                        aan_mij=aan_de_beurt == actor_id,
                        wacht_dagen=_wacht_dagen(vraag.gesteld_op, nu),
                        document_bestandsnaam=document.bestandsnaam,
                        document_status=document.status.value,
                        leverancier_naam=leverancier,
                        referentie=voorstel.referentie if voorstel else None,
                        totaalbedrag=voorstel.totaalbedrag if voorstel else None,
                        blokkeert_boeken=document.status == DocumentStatus.VRAAG_OPEN,
                    )
                )
    # Oudste eerst (urgentste bovenaan, mockup "oudste eerst"); id als stabiele tiebreaker.
    uit.sort(key=lambda r: (r.gesteld_op, r.vraag_id.hex))
    return uit


def _tellers(rijen: list[OpenVraagRij]) -> Tellers:
    return Tellers(
        open=len(rijen),
        aan_mij=sum(1 for r in rijen if r.aan_mij),
        blokkeert_boeken=sum(1 for r in rijen if r.blokkeert_boeken),
        administraties=len({r.administratie_id for r in rijen}),
    )


def _facet(rijen: list[OpenVraagRij]) -> list[AdministratieFacet]:
    per: dict[uuid.UUID, AdministratieFacet] = {}
    for r in rijen:
        bestaand = per.get(r.administratie_id)
        per[r.administratie_id] = AdministratieFacet(
            administratie_id=r.administratie_id,
            administratie_naam=r.administratie_naam,
            aantal=(bestaand.aantal if bestaand else 0) + 1,
        )
    return sorted(per.values(), key=lambda f: f.administratie_naam.lower())


def tellers(*, actor_id: uuid.UUID, rol: GebruikerRol, nu: datetime | None = None) -> Tellers:
    """Stand voor de KPI-kaart "Open vragen" (B2.3) — zelfde bron en definitie als de lijst."""
    return _tellers(_alle_open_vragen(actor_id=actor_id, rol=rol, nu=nu or datetime.now(UTC)))


def lijst(
    *,
    actor_id: uuid.UUID,
    rol: GebruikerRol,
    pagina: int = 1,
    per_pagina: int = PER_PAGINA,
    administratie_id: uuid.UUID | None = None,
    toegewezen: str = "alle",
    ouder_dan_dagen: int | None = None,
    q: str = "",
    nu: datetime | None = None,
) -> Lijst:
    """Kantoorbrede lijst: filters zijn FILTERS op de scope-set (een administratie buiten de scope
    levert gewoon nul rijen — geen poort, geen 403), tellers en facet gaan over de ongefilterde
    scope-set (chips "N open" / "M aan mij" in de paneelkop), `totaal` over de selectie (paginering).
    `ouder_dan_dagen` = wacht minstens N hele dagen (≥, zodat "7 dagen" en de oranje chip samenvallen)."""
    if toegewezen not in TOEGEWEZEN_OPTIES:
        raise OpenVragenFout(f"Onbekende waarde voor toegewezen: {toegewezen!r} (alle | mij)")
    if ouder_dan_dagen is not None and ouder_dan_dagen < 0:
        raise OpenVragenFout("ouder_dan_dagen kan niet negatief zijn")
    if pagina < 1:
        raise OpenVragenFout("pagina begint bij 1")
    alle = _alle_open_vragen(actor_id=actor_id, rol=rol, nu=nu or datetime.now(UTC))
    selectie = alle
    if administratie_id is not None:
        selectie = [r for r in selectie if r.administratie_id == administratie_id]
    if toegewezen == "mij":
        selectie = [r for r in selectie if r.aan_mij]
    if ouder_dan_dagen is not None:
        selectie = [r for r in selectie if r.wacht_dagen >= ouder_dan_dagen]
    zoek = q.strip().lower()
    if zoek:
        selectie = [
            r
            for r in selectie
            if zoek in r.vraag_tekst.lower()
            or zoek in (r.leverancier_naam or "").lower()
            or zoek in (r.referentie or "").lower()
            or zoek in r.administratie_naam.lower()
            or zoek in r.document_bestandsnaam.lower()
            or zoek in (r.laatste_bericht or "").lower()
        ]
    start = (pagina - 1) * per_pagina
    return Lijst(
        rijen=selectie[start : start + per_pagina],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=per_pagina,
        tellers=_tellers(alle),
        administraties=_facet(alle),
    )
