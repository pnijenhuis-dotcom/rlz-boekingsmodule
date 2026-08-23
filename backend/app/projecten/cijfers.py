"""Resultaat per project + cumulatief overzicht (mockup projecten-invoer.html views 3/4,
akkoord Peter 22-08) — de ANALYTISCHE laag: volledig deterministisch, wordt nooit in RLZ
geboekt, excl. AK-opslag (CLAUDE.md "Integrale marge").

Bronnen:
- baten gefactureerd / kosten geboekt: `project_regel_cache` — RLZ-documentregels mét
  projectreferentie (sync hieronder: PurchaseInvoices + SalesInvoices → /Lines?$expand=
  Account,Project; api-verkenning "factuurregels dragen Project + GB aan béíde kanten").
  ⚠️ De SalesInvoices-collectie ziet API-aangemaakte facturen niet (STAP 0 omzetmodule) —
  voor de steigerbouw-tak is dat de juiste bron (verkoop gaat daar via de RLZ-UI); een
  Receipts-bron voor API-verkoop is een bewuste parkeerpost.
- kosten onderweg: GOEDGEKEURDE, nog niet verrekende weekstaten × ZZP-tarief (uren zonder
  tarief = post "onbepaalbaar", oranje — nooit gokken, mockup);
- baten onderweg: goedgekeurd meerwerk dat nog niet doorbelast is (bedrag verplicht gevuld
  door de status-CHECK).

Week-toewijzing (mockup-notitie): kosten op WERKWEEK waar herleidbaar — een geboekte
factuur waarvan weekstaten van dit project verrekend zijn, wordt over die staat-weken
verdeeld naar rato van de goedgekeurde uren; al het overige op factuurdatum-week. Het
cumulatieve overzicht gebruikt exact dezelfde rekenfunctie als het projectdetail — de
cijfers sluiten per definitie op elkaar (test hierop in tests/projecten)."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.db.models import DetacheerderKoppeling
from app.db.session import scoped_session
from app.projecten.models import ProjectRegelCache, ProjectRegelSoort
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import ProjectCache
from app.uren.models import (
    Meerwerk,
    MeerwerkStatus,
    ProjectSpecificatie,
    VeldwerkerCrediteur,
    Weekstaat,
    WeekstaatDag,
    WeekstaatStatus,
)

logger = logging.getLogger(__name__)

_PAGINA_GROOTTE = 100
# Sync-ondergrens: het huidige + vorige boekjaar dekt de lopende projecten; historie = archief.
CIJFERS_VANAF = date(2025, 1, 1)
# RLZ-documentstatussen: geboekt = 2 óf 3 (nooit alleen op 2 toetsen — CLAUDE.md).
_RLZ_GEBOEKT = (2, 3)

_COLLECTIES = (("PurchaseInvoices", ProjectRegelSoort.INKOOP.value), ("SalesInvoices", ProjectRegelSoort.VERKOOP.value))

# Signaaldrempel: vanaf zoveel opeenvolgende recente weken kosten-zonder-baten kleurt het.
KOSTEN_ZONDER_OMZET_DREMPEL_WEKEN = 2


# --- sync --------------------------------------------------------------------------------------


def _als_uuid(waarde: object) -> uuid.UUID | None:
    if isinstance(waarde, dict):
        waarde = waarde.get("id")
    if not waarde:
        return None
    try:
        return uuid.UUID(str(waarde))
    except ValueError:
        return None


def _als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except Exception:  # noqa: BLE001 — RLZ-velden zijn niet ons schema
        return None


def _documenten_paginas(client: RlzClient, collectie: str, *, vanaf: date) -> Iterator[list[dict]]:
    """Geboekte documenten vanaf de ondergrens, per RLZ-serverpagina (patroon
    app/geheugen/seed.py; Status-filter kan niet server-side — OData geeft daar een 400 op,
    lokaal filteren). Bewust een generator: de 504-crash van 23-08 kwam uit één synchrone
    request over de volledige collecties — de aanvoer is nu per pagina begrensd, er staat
    nooit méér dan één pagina documenten tegelijk in het geheugen."""
    skip = 0
    while True:
        batch = client.get(
            collectie,
            params={"$filter": f"Date ge {vanaf.isoformat()}", "$top": str(_PAGINA_GROOTTE), "$skip": str(skip)},
        ).get("value", [])
        yield [r for r in batch if r.get("Status") in _RLZ_GEBOEKT]
        if len(batch) < _PAGINA_GROOTTE:
            return
        skip += _PAGINA_GROOTTE


@dataclass(frozen=True)
class _DocumentKop:
    """Minimale documentkop voor de verwerking + de herkansing van leesfouten — bewust geen
    volledige RLZ-dicts vasthouden (geheugen-begrensd)."""

    collectie: str
    soort: str
    doc_id: uuid.UUID
    datum: date | None
    referentie: str | None


def _verwerk_document(
    session: Session, *, administratie_id: uuid.UUID, kop: _DocumentKop, lines: list[dict],
    gezien: set[uuid.UUID], nu: datetime, teller: dict[str, int],
) -> None:
    project_lines = [line for line in lines if _als_uuid(line.get("Project")) is not None]
    if not project_lines:
        return
    teller["documenten"] += 1
    for line in project_lines:
        line_id = _als_uuid(line.get("id"))
        netto = _als_decimal(line.get("NetAmount"))
        if line_id is None or netto is None:
            continue
        gezien.add(line_id)
        rij = session.get(ProjectRegelCache, (line_id, administratie_id))
        if rij is None:
            rij = ProjectRegelCache(
                id=line_id,
                administratie_id=administratie_id,
                rlz_document_id=kop.doc_id,
                soort=kop.soort,
                project_id=_als_uuid(line.get("Project")),
                netto_bedrag=netto,
            )
            session.add(rij)
        rij.rlz_document_id = kop.doc_id
        rij.soort = kop.soort
        rij.project_id = _als_uuid(line.get("Project"))
        rij.ledger_id = _als_uuid(line.get("Account"))
        rij.netto_bedrag = netto
        rij.btw_bedrag = _als_decimal(line.get("TaxAmount"))
        rij.datum = kop.datum
        rij.referentie = kop.referentie
        rij.omschrijving = line.get("Description")
        rij.laatst_gesynchroniseerd = nu
        rij.verdwenen_uit_bron_op = None
        teller["regels"] += 1


def sync_project_regels(
    *,
    administratie_id: uuid.UUID,
    client: RlzClient | None = None,
    vanaf: date | None = None,
    voortgang: Callable[[dict[str, int]], None] | None = None,
) -> dict[str, int]:
    """Ververst de project_regel_cache voor één administratie. Idempotent (upsert op het
    RLZ-Line-GUID); regels die uit de bron verdwenen zijn (storno, regelvervanging) krijgen
    `verdwenen_uit_bron_op` en tellen niet meer mee — nooit hard verwijderen zolang de sync
    loopt, de reconciliatie-sweep ruimt cache-rijen niet op (leescache).

    Geheugen-begrensd (fix 23-08): per documenttype en per RLZ-pagina, één DB-transactie per
    pagina; `voortgang` (heartbeat achtergrondrun) wordt per pagina aangeroepen. Documenten
    waarvan RLZ de regels niet gaf (bv. de 403-storm van 23-08) krijgen één herkansing aan
    het einde van de run en tellen daarna als `leesfouten` — hun bestaande cache-rijen worden
    dan bewust NIET als verdwenen gemarkeerd (de bron was onleesbaar, niet leeg)."""
    vanaf = vanaf or CIJFERS_VANAF
    eigen_client = client is None
    if client is None:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)

    nu = datetime.now(UTC)
    teller = {"documenten": 0, "regels": 0, "verdwenen": 0, "leesfouten": 0}
    gezien: set[uuid.UUID] = set()
    mislukt: list[_DocumentKop] = []

    def _lees_en_verwerk(session: Session, kop: _DocumentKop) -> bool:
        try:
            lines = client.get_lines(kop.collectie, kop.doc_id, expand="Account,Project")
        except RlzApiError as exc:
            logger.warning(
                "Projectcijfers-sync: regels van %s/%s niet leesbaar: %s", kop.collectie, kop.doc_id, exc
            )
            return False
        _verwerk_document(
            session, administratie_id=administratie_id, kop=kop, lines=lines,
            gezien=gezien, nu=nu, teller=teller,
        )
        return True

    try:
        for collectie, soort in _COLLECTIES:
            for pagina in _documenten_paginas(client, collectie, vanaf=vanaf):
                if not pagina:
                    continue
                with scoped_session(administratie_id) as session:
                    for document in pagina:
                        doc_id = _als_uuid(document.get("id"))
                        if doc_id is None:
                            continue
                        kop = _DocumentKop(
                            collectie=collectie,
                            soort=soort,
                            doc_id=doc_id,
                            datum=_als_datum(document.get("Date")),
                            referentie=document.get("Reference") or document.get("ReceiptNumber"),
                        )
                        if not _lees_en_verwerk(session, kop):
                            mislukt.append(kop)
                if voortgang is not None:
                    voortgang(dict(teller))

        # Herkansing: één rustige tweede poging per gefaald document (de 403-storm van 23-08
        # was een tijdelijke blokkade). Wat dan nóg faalt telt als leesfout — zichtbaar in de
        # runstatus, nooit stil.
        if mislukt:
            nog_mislukt: set[uuid.UUID] = set()
            with scoped_session(administratie_id) as session:
                for kop in mislukt:
                    if not _lees_en_verwerk(session, kop):
                        nog_mislukt.add(kop.doc_id)
            teller["leesfouten"] = len(nog_mislukt)
            if voortgang is not None:
                voortgang(dict(teller))
        else:
            nog_mislukt = set()
    finally:
        if eigen_client:
            client.close()

    with scoped_session(administratie_id) as session:
        for rij in session.scalars(
            select(ProjectRegelCache).where(
                ProjectRegelCache.administratie_id == administratie_id,
                ProjectRegelCache.verdwenen_uit_bron_op.is_(None),
            )
        ):
            if (
                rij.id not in gezien
                and rij.rlz_document_id not in nog_mislukt
                and (rij.datum is None or rij.datum >= vanaf)
            ):
                rij.verdwenen_uit_bron_op = nu
                teller["verdwenen"] += 1
    return teller


# --- rekenlaag ---------------------------------------------------------------------------------


@dataclass(frozen=True)
class ProjectWeek:
    jaar: int
    weeknummer: int
    baten: Decimal
    kosten_geboekt: Decimal
    kosten_onderweg: Decimal
    onderweg_onbepaalbaar_uren: Decimal  # uren zonder tarief in deze week (oranje, nooit gokken)
    saldo: Decimal
    cumulatief: Decimal
    baten_detail: list[str] = field(default_factory=list)
    kosten_detail: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class ProjectCijfers:
    project_id: uuid.UUID
    project_naam: str | None
    opdrachtgever: str | None
    baten_geboekt: Decimal
    kosten_geboekt: Decimal
    uren_onderweg_bedrag: Decimal
    uren_onderweg_uren: Decimal
    onbepaalbaar_uren: Decimal  # goedgekeurde onverrekende uren zónder tarief (post "onbepaalbaar")
    meerwerk_onderweg_bedrag: Decimal
    onderweg_saldo: Decimal  # meerwerk-onderweg − uren-onderweg (mockup-tegel "Onderweg")
    verwachte_marge: Decimal
    marge_pct: Decimal | None  # None als er (nog) geen baten zijn
    weken: list[ProjectWeek]
    heeft_activiteit: bool


def _iso_week(datum: date) -> tuple[int, int]:
    iso = datum.isocalendar()
    return iso[0], iso[1]


def _tarief_voor(session: Session, *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID) -> Decimal | None:
    """ZZP-tarief voor de onderweg-verrijking: eerst het eigen koppeling-tarief
    (veldwerker_crediteur), anders het bureau-tarief (detacheerder↔zzp'er) als dat
    ondubbelzinnig is (precies één tarief) — anders None = onbepaalbaar, nooit gokken."""
    eigen = session.get(VeldwerkerCrediteur, (administratie_id, gebruiker_id))
    if eigen is not None and eigen.uurtarief is not None:
        return eigen.uurtarief
    bureau_tarieven = {
        k.uurtarief
        for k in session.scalars(
            select(DetacheerderKoppeling).where(DetacheerderKoppeling.zzper_gebruiker_id == gebruiker_id)
        )
        if k.uurtarief is not None
    }
    if len(bureau_tarieven) == 1:
        return next(iter(bureau_tarieven))
    return None


def bereken_project_cijfers(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID
) -> ProjectCijfers:
    """Eén rekenfunctie voor detail én overzicht — de cijfers sluiten per definitie."""
    project = session.get(ProjectCache, (project_id, administratie_id))
    spec = session.get(ProjectSpecificatie, (project_id, administratie_id))

    regels = list(
        session.scalars(
            select(ProjectRegelCache).where(
                ProjectRegelCache.administratie_id == administratie_id,
                ProjectRegelCache.project_id == project_id,
                ProjectRegelCache.verdwenen_uit_bron_op.is_(None),
            )
        )
    )

    # Werkweek-herleiding: geboekte documenten waarvan weekstaten van dít project verrekend
    # zijn → hun kosten verdeeld over de staat-weken naar rato van de goedgekeurde uren.
    verrekende_staten = list(
        session.execute(
            select(
                Weekstaat.verrekend_met_document_id,
                Weekstaat.jaar,
                Weekstaat.weeknummer,
                func.coalesce(func.sum(WeekstaatDag.uren), 0).label("uren"),
            )
            .join(WeekstaatDag, WeekstaatDag.weekstaat_id == Weekstaat.id)
            .where(
                Weekstaat.administratie_id == administratie_id,
                Weekstaat.project_id == project_id,
                Weekstaat.status == WeekstaatStatus.GOEDGEKEURD.value,
                Weekstaat.verrekend_met_document_id.is_not(None),
            )
            .group_by(Weekstaat.verrekend_met_document_id, Weekstaat.jaar, Weekstaat.weeknummer)
        )
    )
    herleidbare_rlz_ids: dict[uuid.UUID, list[tuple[int, int, Decimal]]] = {}
    if verrekende_staten:
        # Lokaal document → actueel RLZ-GUID (boek_cyclus-bewust, tegenboek-pad).
        from app.documenten.models import Boekvoorstel
        from app.documenten.rlz_ids import rlz_herboeking_id

        per_document: dict[uuid.UUID, list[tuple[int, int, Decimal]]] = {}
        for rij in verrekende_staten:
            per_document.setdefault(rij.verrekend_met_document_id, []).append(
                (rij.jaar, rij.weeknummer, Decimal(rij.uren))
            )
        for document_id, weken in per_document.items():
            voorstel = session.get(Boekvoorstel, document_id)
            cyclus = voorstel.boek_cyclus if voorstel else 0
            herleidbare_rlz_ids[rlz_herboeking_id(document_id, cyclus)] = weken

    baten_per_week: dict[tuple[int, int], Decimal] = {}
    kosten_per_week: dict[tuple[int, int], Decimal] = {}
    baten_detail: dict[tuple[int, int], list[str]] = {}
    kosten_detail: dict[tuple[int, int], list[str]] = {}
    baten_geboekt = Decimal("0")
    kosten_geboekt = Decimal("0")

    herleidbaar_per_doc: dict[uuid.UUID, Decimal] = {}
    for regel in regels:
        if regel.soort == ProjectRegelSoort.VERKOOP.value:
            baten_geboekt += regel.netto_bedrag
            if regel.datum is not None:
                sleutel = _iso_week(regel.datum)
                baten_per_week[sleutel] = baten_per_week.get(sleutel, Decimal("0")) + regel.netto_bedrag
                if regel.referentie:
                    baten_detail.setdefault(sleutel, [])
                    if regel.referentie not in baten_detail[sleutel]:
                        baten_detail[sleutel].append(regel.referentie)
        else:
            kosten_geboekt += regel.netto_bedrag
            if regel.rlz_document_id in herleidbare_rlz_ids:
                herleidbaar_per_doc[regel.rlz_document_id] = (
                    herleidbaar_per_doc.get(regel.rlz_document_id, Decimal("0")) + regel.netto_bedrag
                )
            elif regel.datum is not None:
                sleutel = _iso_week(regel.datum)
                kosten_per_week[sleutel] = kosten_per_week.get(sleutel, Decimal("0")) + regel.netto_bedrag

    # Herleidbare kosten naar rato van de goedgekeurde uren per staat-week (grootste-rest is
    # hier niet nodig: dit is een analytische weergave, geen boeking — 2 decimalen per week,
    # het restant landt op de laatste week zodat de som exact klopt).
    for rlz_doc_id, bedrag in herleidbaar_per_doc.items():
        weken = herleidbare_rlz_ids[rlz_doc_id]
        totaal_uren = sum((u for _, _, u in weken), Decimal("0"))
        if totaal_uren == 0:
            continue
        toegewezen = Decimal("0")
        for i, (jaar, weeknummer, uren) in enumerate(weken):
            if i == len(weken) - 1:
                deel = bedrag - toegewezen
            else:
                deel = (bedrag * uren / totaal_uren).quantize(Decimal("0.01"))
                toegewezen += deel
            sleutel = (jaar, weeknummer)
            kosten_per_week[sleutel] = kosten_per_week.get(sleutel, Decimal("0")) + deel
            kosten_detail.setdefault(sleutel, [])
            if "uit weekstaten" not in kosten_detail[sleutel]:
                kosten_detail[sleutel].append("uit weekstaten")

    # Kosten onderweg: goedgekeurde, nog niet verrekende weekstaten × tarief per gebruiker.
    onverrekend = list(
        session.execute(
            select(
                Weekstaat.gebruiker_id,
                Weekstaat.jaar,
                Weekstaat.weeknummer,
                func.coalesce(func.sum(WeekstaatDag.uren), 0).label("uren"),
            )
            .join(WeekstaatDag, WeekstaatDag.weekstaat_id == Weekstaat.id)
            .where(
                Weekstaat.administratie_id == administratie_id,
                Weekstaat.project_id == project_id,
                Weekstaat.status == WeekstaatStatus.GOEDGEKEURD.value,
                Weekstaat.verrekend_met_document_id.is_(None),
            )
            .group_by(Weekstaat.gebruiker_id, Weekstaat.jaar, Weekstaat.weeknummer)
        )
    )
    onderweg_per_week: dict[tuple[int, int], Decimal] = {}
    onbepaalbaar_per_week: dict[tuple[int, int], Decimal] = {}
    uren_onderweg_bedrag = Decimal("0")
    uren_onderweg_uren = Decimal("0")
    onbepaalbaar_uren = Decimal("0")
    tarief_cache: dict[uuid.UUID, Decimal | None] = {}
    for rij in onverrekend:
        uren = Decimal(rij.uren)
        if uren == 0:
            continue
        if rij.gebruiker_id not in tarief_cache:
            tarief_cache[rij.gebruiker_id] = _tarief_voor(
                session, administratie_id=administratie_id, gebruiker_id=rij.gebruiker_id
            )
        tarief = tarief_cache[rij.gebruiker_id]
        sleutel = (rij.jaar, rij.weeknummer)
        uren_onderweg_uren += uren
        if tarief is None:
            onbepaalbaar_uren += uren
            onbepaalbaar_per_week[sleutel] = onbepaalbaar_per_week.get(sleutel, Decimal("0")) + uren
        else:
            bedrag = (uren * tarief).quantize(Decimal("0.01"))
            uren_onderweg_bedrag += bedrag
            onderweg_per_week[sleutel] = onderweg_per_week.get(sleutel, Decimal("0")) + bedrag

    # Baten onderweg: goedgekeurd meerwerk dat nog niet doorbelast is (bedrag verplicht).
    meerwerk_onderweg = Decimal(
        session.execute(
            select(func.coalesce(func.sum(Meerwerk.bedrag), 0)).where(
                Meerwerk.administratie_id == administratie_id,
                Meerwerk.project_id == project_id,
                Meerwerk.status == MeerwerkStatus.GOEDGEKEURD.value,
            )
        ).scalar_one()
    )

    week_sleutels = sorted(
        set(baten_per_week) | set(kosten_per_week) | set(onderweg_per_week) | set(onbepaalbaar_per_week)
    )
    weken: list[ProjectWeek] = []
    cumulatief = Decimal("0")
    for sleutel in week_sleutels:
        baten = baten_per_week.get(sleutel, Decimal("0"))
        kosten = kosten_per_week.get(sleutel, Decimal("0"))
        onderweg = onderweg_per_week.get(sleutel, Decimal("0"))
        saldo = baten - kosten - onderweg
        cumulatief += saldo
        weken.append(
            ProjectWeek(
                jaar=sleutel[0],
                weeknummer=sleutel[1],
                baten=baten,
                kosten_geboekt=kosten,
                kosten_onderweg=onderweg,
                onderweg_onbepaalbaar_uren=onbepaalbaar_per_week.get(sleutel, Decimal("0")),
                saldo=saldo,
                cumulatief=cumulatief,
                baten_detail=baten_detail.get(sleutel, []),
                kosten_detail=kosten_detail.get(sleutel, []),
            )
        )

    baten_totaal = baten_geboekt + meerwerk_onderweg
    verwachte_marge = baten_totaal - kosten_geboekt - uren_onderweg_bedrag
    marge_pct: Decimal | None = None
    if baten_totaal != 0:
        marge_pct = (verwachte_marge / baten_totaal * 100).quantize(Decimal("0.1"))

    return ProjectCijfers(
        project_id=project_id,
        project_naam=project.naam if project else None,
        opdrachtgever=spec.opdrachtgever if spec else None,
        baten_geboekt=baten_geboekt,
        kosten_geboekt=kosten_geboekt,
        uren_onderweg_bedrag=uren_onderweg_bedrag,
        uren_onderweg_uren=uren_onderweg_uren,
        onbepaalbaar_uren=onbepaalbaar_uren,
        meerwerk_onderweg_bedrag=meerwerk_onderweg,
        onderweg_saldo=meerwerk_onderweg - uren_onderweg_bedrag,
        verwachte_marge=verwachte_marge,
        marge_pct=marge_pct,
        weken=weken,
        heeft_activiteit=bool(weken) or meerwerk_onderweg != 0,
    )


def trend_over_vier_weken(cijfers: ProjectCijfers, *, vandaag: date | None = None) -> str:
    """4-weken-trend (mockup-kolom): het weeksaldo-totaal van de laatste 4 ISO-weken t.o.v. de
    4 weken ervoor — 'stijgend' | 'dalend' | 'stabiel'. Deterministisch; `vandaag` injecteerbaar."""
    vandaag = vandaag or date.today()
    huidige = _iso_week(vandaag)

    def week_index(jaar: int, week: int) -> int:
        # Monotone index over jaargrenzen heen (ISO-jaren hebben 52/53 weken; 53 is veilig
        # als vaste factor voor een ordinale vergelijking).
        return jaar * 53 + week

    grens = week_index(*huidige)
    recent = Decimal("0")
    ervoor = Decimal("0")
    for week in cijfers.weken:
        idx = week_index(week.jaar, week.weeknummer)
        if grens - 3 <= idx <= grens:
            recent += week.saldo
        elif grens - 7 <= idx < grens - 3:
            ervoor += week.saldo
    if recent > ervoor:
        return "stijgend"
    if recent < ervoor:
        return "dalend"
    return "stabiel"


def kosten_zonder_omzet_weken(cijfers: ProjectCijfers) -> int:
    """Signaal "kosten zonder omzet": het aantal opeenvolgende meest recente activiteit-weken
    met kosten (geboekt of onderweg) maar zonder baten — teruggeteld vanaf de laatste week."""
    teller = 0
    for week in reversed(cijfers.weken):
        heeft_kosten = week.kosten_geboekt != 0 or week.kosten_onderweg != 0 or week.onderweg_onbepaalbaar_uren != 0
        if week.baten != 0 or not heeft_kosten:
            break
        teller += 1
    return teller


# --- cumulatief overzicht alle projecten (mockup view 4) ------------------------------------------


@dataclass(frozen=True)
class OverzichtRij:
    cijfers: ProjectCijfers
    trend: str
    kosten_zonder_omzet_weken: int
    meerwerk_te_lang_niet_doorbelast: int
    doorlopende_huur: bool


@dataclass(frozen=True)
class ProjectenOverzicht:
    baten_totaal: Decimal
    kosten_totaal_incl_onderweg: Decimal
    uren_onderweg_totaal: Decimal
    onbepaalbaar_uren_totaal: Decimal
    meerwerk_onderweg_totaal: Decimal
    marge_totaal: Decimal
    marge_pct: Decimal | None
    aandacht: int  # projecten met negatieve óf dalende marge (mockup-tegel)
    rijen: list[OverzichtRij]  # gesorteerd: laagste marge eerst — aandachtswerk bovenaan


def overzicht_alle_projecten(*, administratie_id: uuid.UUID, vandaag: date | None = None) -> ProjectenOverzicht:
    """Zelfde rekenfunctie als het projectdetail (bereken_project_cijfers) over alle actieve
    projecten mét activiteit — de cijfers sluiten per definitie op elkaar. Signalen: kosten
    zonder omzet (trailing weken), meerwerk > 2 weken niet doorbelast (bestaand
    BEWAKING_DAGEN-signaal), doorlopende huur (specificatie-veld)."""
    from datetime import timedelta

    from app.uren.service import BEWAKING_DAGEN

    vandaag = vandaag or date.today()
    with scoped_session(administratie_id) as session:
        projecten = list(
            session.scalars(
                select(ProjectCache).where(
                    ProjectCache.administratie_id == administratie_id,
                    ProjectCache.is_actief.is_(True),
                    ProjectCache.verdwenen_uit_bron_op.is_(None),
                )
            )
        )
        grens = datetime.now(UTC) - timedelta(days=BEWAKING_DAGEN)
        te_lang_per_project = dict(
            session.execute(
                select(Meerwerk.project_id, func.count())
                .where(
                    Meerwerk.administratie_id == administratie_id,
                    Meerwerk.status == MeerwerkStatus.GOEDGEKEURD.value,
                    Meerwerk.beoordeeld_op < grens,
                )
                .group_by(Meerwerk.project_id)
            ).all()
        )
        specs = {
            s.project_id: s
            for s in session.scalars(
                select(ProjectSpecificatie).where(ProjectSpecificatie.administratie_id == administratie_id)
            )
        }

        rijen: list[OverzichtRij] = []
        for project in projecten:
            cijfers = bereken_project_cijfers(session, administratie_id=administratie_id, project_id=project.id)
            if not cijfers.heeft_activiteit:
                continue
            spec = specs.get(project.id)
            rijen.append(
                OverzichtRij(
                    cijfers=cijfers,
                    trend=trend_over_vier_weken(cijfers, vandaag=vandaag),
                    kosten_zonder_omzet_weken=kosten_zonder_omzet_weken(cijfers),
                    meerwerk_te_lang_niet_doorbelast=te_lang_per_project.get(project.id, 0),
                    doorlopende_huur=bool(spec and spec.doorlopende_huur_omschrijving),
                )
            )

    rijen.sort(key=lambda r: (r.cijfers.verwachte_marge, r.cijfers.project_naam or ""))
    baten_totaal = sum((r.cijfers.baten_geboekt + r.cijfers.meerwerk_onderweg_bedrag for r in rijen), Decimal("0"))
    uren_onderweg = sum((r.cijfers.uren_onderweg_bedrag for r in rijen), Decimal("0"))
    kosten_totaal = sum((r.cijfers.kosten_geboekt for r in rijen), Decimal("0")) + uren_onderweg
    marge_totaal = baten_totaal - kosten_totaal
    marge_pct = (marge_totaal / baten_totaal * 100).quantize(Decimal("0.1")) if baten_totaal != 0 else None
    aandacht = sum(1 for r in rijen if r.cijfers.verwachte_marge < 0 or r.trend == "dalend")
    return ProjectenOverzicht(
        baten_totaal=baten_totaal,
        kosten_totaal_incl_onderweg=kosten_totaal,
        uren_onderweg_totaal=uren_onderweg,
        onbepaalbaar_uren_totaal=sum((r.cijfers.onbepaalbaar_uren for r in rijen), Decimal("0")),
        meerwerk_onderweg_totaal=sum((r.cijfers.meerwerk_onderweg_bedrag for r in rijen), Decimal("0")),
        marge_totaal=marge_totaal,
        marge_pct=marge_pct,
        aandacht=aandacht,
        rijen=rijen,
    )
