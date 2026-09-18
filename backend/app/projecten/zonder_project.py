"""LEES-ONLY rapport "geboekte inkoopfacturen zonder projectreferentie" (opdracht 18-09 avond; TODO Peter 23-08
"eerst rapport, dan beslissen"). Nameting-instrument (`facturen-zonder-project`, allowlist `scripts/gcp/nameting.sh`).

Twee kanten, twee tellingen:

- **Module-kant** (eigen DB, geen RLZ-call): álle in de module GEBOEKTE inkoopfacturen in administraties met
  `project_verplicht = true` waarvan één of meer `boekvoorstel_regel`-rijen géén `project_id` dragen. Een regel is
  GEDEKT als het document een BEVROREN projectverdeling draagt (status `geboekt`, zelfde `boek_cyclus`): de RLZ-adapter
  splitst zo'n regel bij het boeken in N regels mét Project (`app/backends/rlz_inkoop.py::regels_naar_rlz_lines`), dus
  in RLZ staat er dan wél een project. Gedekt = geen bevinding, wel zichtbaar in de lijst (kolom `dekking`).
- **RLZ-kant** (optioneel, `--rlz`, uitsluitend GET): geboekte `PurchaseInvoices` (Status 2/3) vanaf 1 januari van het
  jaar, per document `/Lines?$expand=Account,Project`; een regel zonder Project op een kostenrekening (Account.Code
  4xxx/7xxx) telt. RLZ-documenten die de module zelf heeft geboekt worden herkend aan het deterministische client-GUID
  (`rlz_ids.rlz_purchase_invoice_id` / `rlz_herboeking_id`) — het verschil tussen de tellingen is daarmee verklaard
  (facturen van vóór de module tellen alleen RLZ-kant).

Herstelroute per rij (VOORSTEL, nooit uitgevoerd): (a) btw-periode open → storno 19 → project op de regels → her-PUT →
17 (idempotent, zelfde client-GUID's); (b) periode ingediend (`app/rlz/aangifte.py`) → tegenboek-pad; zonder RLZ-credential
= "niet toetsbaar" (zichtbaar, nooit stil). Project-VOORSTEL alleen deterministisch: één bevestigde werknummer-mapping
van de leverancier óf één project in ≥ 3 eigen geboekte facturen van die leverancier (recency wint niet — meerduidig =
mens). Geen LLM, geen writes, geen statuswissel.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter, defaultdict
from collections.abc import Callable, Iterator
from dataclasses import dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.models import Administratie, Gebruiker, Grootboekrekening
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
)
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_purchase_invoice_id
from app.projecten.models import LeverancierWerknummer
from app.projectverdeling.data import STATUS_GEBOEKT as VERDELING_GEBOEKT
from app.projectverdeling.models import Projectverdeling
from app.sync.models import ProjectCache, VendorCache

logger = logging.getLogger(__name__)

#: Minimaal aantal eigen geboekte facturen van een leverancier naar hetzelfde (enige) project vóór een voorstel.
GEHEUGEN_MINIMUM = 3
#: Kostenrekeningen (RLZ-kant): regel zonder Project op een 4xxx-/7xxx-rekening telt.
KOSTEN_PREFIXEN = ("4", "7")
_RLZ_GEBOEKT = (2, 3)
_PAGINA = 200

ROUTE_STORNO = "a_storno_herput"
ROUTE_TEGENBOEK = "b_tegenboek"
ROUTE_ONBEKEND = "toets_nodig"
ROUTE_GEEN = "geen_herstel_nodig"


@dataclass(frozen=True)
class ProjectVoorstel:
    project_id: uuid.UUID
    project_naam: str
    herkomst: str  # "werknummer-geheugen (bevestigd)" | "geheugen N× bevestigd"


@dataclass
class Rij:
    administratie_id: uuid.UUID
    administratie: str
    document_id: uuid.UUID
    rlz_document_id: uuid.UUID
    boekstuk: str | None
    referentie: str | None
    leverancier: str | None
    vendor_id: uuid.UUID | None
    factuurdatum: date | None
    boekdatum: date | None  # = factuurdatum (BookDate-regel 28-08); None als de factuurdatum leeg is
    geboekt_op: date | None
    regelnummer: int
    aantal_regels: int
    grootboek: str | None
    netto: Decimal | None
    btw: Decimal | None
    geboekt_door: str  # "automatisch" | naam van de mens | "systeem (achtergrond)"
    boek_cyclus: int
    gedekt_door_verdeling: bool = False
    verdeling_delen: int = 0
    aangifte: str = "niet getoetst"  # "open" | "ingediend (… t/m …)" | "niet toetsbaar (…)"
    route: str = ROUTE_ONBEKEND
    voorstel: ProjectVoorstel | None = None


@dataclass
class RlzRij:
    rlz_document_id: uuid.UUID
    boekstuk: str | None
    referentie: str | None
    datum: date | None
    boekdatum: date | None
    regel_id: uuid.UUID | None
    grootboek: str | None
    omschrijving: str | None
    netto: Decimal | None
    btw: Decimal | None
    van_module: bool


@dataclass
class Uitkomst:
    administratie_id: uuid.UUID
    administratie: str
    jaar: int | None
    geboekt_in_module: int
    rijen: list[Rij] = field(default_factory=list)
    rlz_rijen: list[RlzRij] | None = None  # None = RLZ-kant niet gemeten
    rlz_documenten_gelezen: int = 0
    rlz_leesfouten: int = 0
    rlz_melding: str | None = None

    # -- tellingen -------------------------------------------------------------------------------------------------
    @property
    def bevindingen(self) -> list[Rij]:
        """Module-kant: regels zonder project die NIET door een bevroren verdeling gedekt zijn."""
        return [r for r in self.rijen if not r.gedekt_door_verdeling]

    @property
    def documenten_zonder_project(self) -> int:
        return len({r.document_id for r in self.bevindingen})

    @property
    def documenten_gedekt(self) -> int:
        return len({r.document_id for r in self.rijen if r.gedekt_door_verdeling})

    @property
    def routes(self) -> Counter[str]:
        per_document: dict[uuid.UUID, str] = {}
        for r in self.bevindingen:
            per_document.setdefault(r.document_id, r.route)
        return Counter(per_document.values())

    @property
    def rlz_documenten_zonder_project(self) -> int | None:
        if self.rlz_rijen is None:
            return None
        return len({r.rlz_document_id for r in self.rlz_rijen})

    @property
    def rlz_alleen(self) -> int | None:
        """RLZ-documenten zonder project die NIET door de module geboekt zijn (van vóór de module / buiten de module)."""
        if self.rlz_rijen is None:
            return None
        return len({r.rlz_document_id for r in self.rlz_rijen if not r.van_module})


# --- module-kant -----------------------------------------------------------------------------------------------------


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except (ArithmeticError, ValueError):
        return None


def _als_uuid(waarde: object) -> uuid.UUID | None:
    if isinstance(waarde, uuid.UUID):
        return waarde
    if isinstance(waarde, dict):
        waarde = waarde.get("id")
    if not isinstance(waarde, str):
        return None
    try:
        return uuid.UUID(waarde)
    except ValueError:
        return None


def _als_datum(waarde: object) -> date | None:
    if isinstance(waarde, date):
        return waarde
    if isinstance(waarde, str) and len(waarde) >= 10:
        try:
            return date.fromisoformat(waarde[:10])
        except ValueError:
            return None
    return None


def rlz_document_id_voor(document_id: uuid.UUID, boek_cyclus: int) -> uuid.UUID:
    """Het RLZ-client-GUID van de boeking (cyclus 0 = origineel, anders de herboeking) — zelfde afleiding als de motor."""
    return rlz_purchase_invoice_id(document_id) if boek_cyclus == 0 else rlz_herboeking_id(document_id, boek_cyclus)


def _geboekt_door(session: Session, document_ids: set[uuid.UUID]) -> dict[uuid.UUID, tuple[str, date | None]]:
    """Jongste GEBOEKT-overgang per document → ("automatisch" | naam | "systeem (achtergrond)", datum)."""
    if not document_ids:
        return {}
    rijen = session.execute(
        select(DocumentGebeurtenis, Gebruiker.naam)
        .join(Gebruiker, Gebruiker.id == DocumentGebeurtenis.actor_id, isouter=True)
        .where(
            DocumentGebeurtenis.document_id.in_(document_ids),
            DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
            DocumentGebeurtenis.van_status != DocumentStatus.GEBOEKT,
        )
        .order_by(DocumentGebeurtenis.document_id, DocumentGebeurtenis.tijdstip.desc())
    ).all()
    uit: dict[uuid.UUID, tuple[str, date | None]] = {}
    for gebeurtenis, naam in rijen:
        if gebeurtenis.document_id in uit:
            continue
        detail = gebeurtenis.detail or {}
        if detail.get("automatisch_geboekt"):
            wie = "automatisch"
        elif naam and not naam.lower().startswith("systeem"):
            wie = naam
        else:
            wie = "systeem (achtergrond)"
        uit[gebeurtenis.document_id] = (wie, gebeurtenis.tijdstip.date() if gebeurtenis.tijdstip else None)
    return uit


def _verdelingen(
    session: Session, administratie_id: uuid.UUID, document_ids: set[uuid.UUID]
) -> dict[uuid.UUID, Projectverdeling]:
    if not document_ids:
        return {}
    return {
        v.document_id: v
        for v in session.scalars(
            select(Projectverdeling).where(
                Projectverdeling.administratie_id == administratie_id,
                Projectverdeling.document_id.in_(document_ids),
                Projectverdeling.status == VERDELING_GEBOEKT,
            )
        )
    }


def project_voorstel(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    uitgezonderd: set[uuid.UUID] | None = None,
) -> ProjectVoorstel | None:
    """Deterministisch voorstel (nooit AI): (1) precies één BEVESTIGDE werknummer-mapping-project van de leverancier;
    (2) anders: in de eigen geboekte facturen van de leverancier (buiten `uitgezonderd`) gaat élke projectregel naar
    één en hetzelfde project, in ≥ GEHEUGEN_MINIMUM facturen. Meerdere projecten = None (mens nodig — "nooit raden")."""
    if vendor_id is None:
        return None
    namen = {
        p.id: p.naam or str(p.id)[:8]
        for p in session.scalars(select(ProjectCache).where(ProjectCache.administratie_id == administratie_id))
    }
    bevestigd = {
        w.project_id
        for w in session.scalars(
            select(LeverancierWerknummer).where(
                LeverancierWerknummer.administratie_id == administratie_id,
                LeverancierWerknummer.vendor_id == vendor_id,
                LeverancierWerknummer.bevestigd.is_(True),
            )
        )
    }
    if len(bevestigd) == 1:
        pid = next(iter(bevestigd))
        return ProjectVoorstel(
            project_id=pid, project_naam=namen.get(pid, str(pid)[:8]), herkomst="werknummer-geheugen (bevestigd)"
        )
    if bevestigd:
        return None
    rijen = session.execute(
        select(BoekvoorstelRegel.project_id, Boekvoorstel.document_id)
        .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(
            Document.administratie_id == administratie_id,
            Document.status == DocumentStatus.GEBOEKT,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Boekvoorstel.vendor_id == vendor_id,
            BoekvoorstelRegel.project_id.isnot(None),
        )
    ).all()
    per_project: dict[uuid.UUID, set[uuid.UUID]] = defaultdict(set)
    for pid, did in rijen:
        if uitgezonderd and did in uitgezonderd:
            continue
        per_project[pid].add(did)
    if len(per_project) != 1:
        return None
    pid, docs = next(iter(per_project.items()))
    if len(docs) < GEHEUGEN_MINIMUM:
        return None
    return ProjectVoorstel(
        project_id=pid, project_naam=namen.get(pid, str(pid)[:8]), herkomst=f"geheugen {len(docs)}× bevestigd"
    )


def module_kant(
    session: Session, *, administratie_id: uuid.UUID, administratie_naam: str, jaar: int | None
) -> Uitkomst:
    """Alle geboekte inkoopfacturen van de administratie; rijen = regels zonder project (gedekt of niet)."""
    q = (
        select(Document, Boekvoorstel)
        .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
        .where(
            Document.administratie_id == administratie_id,
            Document.status == DocumentStatus.GEBOEKT,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
        )
    )
    if jaar is not None:
        q = q.where(Boekvoorstel.factuurdatum >= date(jaar, 1, 1), Boekvoorstel.factuurdatum <= date(jaar, 12, 31))
    documenten = session.execute(q.order_by(Boekvoorstel.factuurdatum, Boekvoorstel.referentie)).all()
    uitkomst = Uitkomst(
        administratie_id=administratie_id,
        administratie=administratie_naam,
        jaar=jaar,
        geboekt_in_module=len(documenten),
    )
    if not documenten:
        return uitkomst
    ids = {d.id for d, _ in documenten}
    regels = defaultdict(list)
    for r in session.scalars(
        select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id.in_(ids)).order_by(BoekvoorstelRegel.volgnummer)
    ):
        regels[r.document_id].append(r)
    kandidaten = {d.id for d, _ in documenten if any(r.project_id is None for r in regels.get(d.id, []))}
    if not kandidaten:
        return uitkomst
    wie = _geboekt_door(session, kandidaten)
    verdelingen = _verdelingen(session, administratie_id, kandidaten)
    vendors = {
        v.id: v.naam
        for v in session.scalars(select(VendorCache).where(VendorCache.administratie_id == administratie_id))
    }
    grootboeken = {
        g.ledger_id: f"{g.code} {g.naam}".strip()
        for g in session.scalars(
            select(Grootboekrekening).where(Grootboekrekening.administratie_id == administratie_id)
        )
    }
    voorstellen: dict[uuid.UUID | None, ProjectVoorstel | None] = {}
    for document, voorstel in documenten:
        if document.id not in kandidaten:
            continue
        verdeling = verdelingen.get(document.id)
        gedekt = verdeling is not None and (
            verdeling.boek_cyclus is None or verdeling.boek_cyclus == voorstel.boek_cyclus
        )
        geboekt_door, geboekt_op = wie.get(document.id, ("onbekend", None))
        if voorstel.vendor_id not in voorstellen and not gedekt:
            voorstellen[voorstel.vendor_id] = project_voorstel(
                session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id, uitgezonderd=kandidaten
            )
        alle = regels.get(document.id, [])
        for regel in alle:
            if regel.project_id is not None:
                continue
            uitkomst.rijen.append(
                Rij(
                    administratie_id=administratie_id,
                    administratie=administratie_naam,
                    document_id=document.id,
                    rlz_document_id=rlz_document_id_voor(document.id, voorstel.boek_cyclus),
                    boekstuk=voorstel.rlz_boekstuknummer,
                    referentie=voorstel.referentie,
                    leverancier=vendors.get(voorstel.vendor_id) if voorstel.vendor_id else None,
                    vendor_id=voorstel.vendor_id,
                    factuurdatum=voorstel.factuurdatum,
                    boekdatum=voorstel.factuurdatum,
                    geboekt_op=geboekt_op,
                    regelnummer=regel.volgnummer,
                    aantal_regels=len(alle),
                    grootboek=grootboeken.get(regel.ledger_id) if regel.ledger_id else None,
                    netto=regel.netto_bedrag,
                    btw=regel.btw_bedrag,
                    geboekt_door=geboekt_door,
                    boek_cyclus=voorstel.boek_cyclus,
                    gedekt_door_verdeling=gedekt,
                    verdeling_delen=len(verdeling.verdeling or []) if verdeling is not None else 0,
                    route=ROUTE_GEEN if gedekt else ROUTE_ONBEKEND,
                    voorstel=None if gedekt else voorstellen.get(voorstel.vendor_id),
                )
            )
    return uitkomst


# --- aangifte-toets + route -------------------------------------------------------------------------------------------


def bepaal_routes(
    uitkomst: Uitkomst, toets_boekdatum: Callable[[date], Any] | None, *, reden_niet_toetsbaar: str | None = None
) -> None:
    """Zet per niet-gedekte rij de aangifte-stand en de herstelroute. `toets_boekdatum` = `AangiftePoort.toets_boekdatum`
    (partial mét kant) — None = geen RLZ-credential: zichtbaar "niet toetsbaar", route `toets_nodig`."""
    for rij in uitkomst.rijen:
        if rij.gedekt_door_verdeling:
            rij.aangifte = "n.v.t. (gedekt door projectverdeling)"
            rij.route = ROUTE_GEEN
            continue
        if toets_boekdatum is None:
            rij.aangifte = f"niet toetsbaar ({reden_niet_toetsbaar or 'geen RLZ-credential'})"
            rij.route = ROUTE_ONBEKEND
            continue
        if rij.boekdatum is None:
            rij.aangifte = "niet toetsbaar (geen factuurdatum)"
            rij.route = ROUTE_ONBEKEND
            continue
        toets = toets_boekdatum(rij.boekdatum)
        if toets.toegestaan:
            rij.aangifte = "open"
            rij.route = ROUTE_STORNO
        elif toets.periode_start is not None:
            rij.aangifte = f"ingediend ({toets.periode_start.isoformat()} t/m {toets.periode_eind.isoformat()})"
            rij.route = ROUTE_TEGENBOEK
        else:
            rij.aangifte = f"niet toetsbaar ({toets.reden})"
            rij.route = ROUTE_ONBEKEND


# --- RLZ-kant (uitsluitend GET) ----------------------------------------------------------------------------------------


def _paginas(client: Any, *, vanaf: date) -> Iterator[list[dict]]:
    skip = 0
    while True:
        batch = client.get(
            "PurchaseInvoices",
            params={"$filter": f"Date ge {vanaf.isoformat()}", "$top": str(_PAGINA), "$skip": str(skip)},
        ).get("value", [])
        yield [r for r in batch if r.get("Status") in _RLZ_GEBOEKT]
        if len(batch) < _PAGINA:
            return
        skip += _PAGINA


def _account_code(line: dict) -> str | None:
    account = line.get("Account")
    if isinstance(account, dict):
        code = account.get("Code") or account.get("Number")
        naam = account.get("Name")
        if code is not None:
            return f"{code} {naam or ''}".strip()
        return naam
    return None


def is_kostenregel_zonder_project(line: dict) -> bool:
    """Regel zonder Project-ref op een 4xxx-/7xxx-rekening (Account expanded; zonder Code telt de regel NIET — nooit raden)."""
    if _als_uuid(line.get("Project")) is not None:
        return False
    account = line.get("Account")
    code = str((account or {}).get("Code") or (account or {}).get("Number") or "") if isinstance(account, dict) else ""
    return code.startswith(KOSTEN_PREFIXEN)


def rlz_kant(uitkomst: Uitkomst, client: Any, *, jaar: int) -> None:
    """Leest geboekte PurchaseInvoices vanaf 1-1-`jaar` + hun regels; vult `uitkomst.rlz_*`. Een leesfout op een document
    telt als leesfout (zichtbaar), nooit als 'zonder project'. Documenten van de module worden herkend op client-GUID."""
    from app.rlz.client import RlzApiError

    module_ids = {r.rlz_document_id for r in uitkomst.rijen} | set(_module_rlz_ids(uitkomst.administratie_id))
    uitkomst.rlz_rijen = []
    for pagina in _paginas(client, vanaf=date(jaar, 1, 1)):
        for doc in pagina:
            doc_id = _als_uuid(doc.get("id"))
            if doc_id is None:
                continue
            uitkomst.rlz_documenten_gelezen += 1
            try:
                lines = client.get_lines("PurchaseInvoices", doc_id)
            except RlzApiError as exc:
                uitkomst.rlz_leesfouten += 1
                logger.warning("Lines niet leesbaar voor %s: %s", doc_id, exc)
                continue
            for line in lines:
                if not is_kostenregel_zonder_project(line):
                    continue
                uitkomst.rlz_rijen.append(
                    RlzRij(
                        rlz_document_id=doc_id,
                        boekstuk=doc.get("ReceiptNumber"),
                        referentie=doc.get("Reference"),
                        datum=_als_datum(doc.get("Date")),
                        boekdatum=_als_datum(doc.get("BookDate")),
                        regel_id=_als_uuid(line.get("id")),
                        grootboek=_account_code(line),
                        omschrijving=line.get("Description"),
                        netto=_als_decimal(line.get("NetAmount")),
                        btw=_als_decimal(line.get("TaxAmount")),
                        van_module=doc_id in module_ids,
                    )
                )


def _module_rlz_ids(administratie_id: uuid.UUID) -> Iterator[uuid.UUID]:
    """Client-GUID's van álle module-boekingen van de administratie (ook mét project) — voor het verschil 'van de module'."""
    from app.db.session import scoped_session

    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Document.id, Boekvoorstel.boek_cyclus)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
            .where(
                Document.administratie_id == administratie_id,
                Document.status == DocumentStatus.GEBOEKT,
                Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            )
        ).all()
    for did, cyclus in rijen:
        yield rlz_document_id_voor(did, cyclus or 0)


# --- rapportregels ----------------------------------------------------------------------------------------------------


def _euro(bedrag: Decimal | None) -> str:
    return "—" if bedrag is None else f"{bedrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


ROUTE_TEKST = {
    ROUTE_STORNO: "(a) periode open → storno 19 → project op de regel(s) → her-PUT → 17",
    ROUTE_TEGENBOEK: "(b) periode ingediend → tegenboek-pad",
    ROUTE_ONBEKEND: "toets nodig (aangiftestatus niet toetsbaar)",
    ROUTE_GEEN: "geen herstel nodig (gedekt door bevroren projectverdeling — RLZ draagt het project per deel)",
}


def rapportregels(uitkomst: Uitkomst) -> list[str]:
    regels = [
        f"{uitkomst.administratie} ({uitkomst.administratie_id}) — jaar {uitkomst.jaar or 'alle'}: "
        f"{uitkomst.geboekt_in_module} in de module geboekte inkoopfacturen; "
        f"{uitkomst.documenten_zonder_project} zonder project (bevinding), {uitkomst.documenten_gedekt} gedekt door projectverdeling."
    ]
    for r in uitkomst.rijen:
        regels.append(
            f"  {'GEDEKT   ' if r.gedekt_door_verdeling else 'BEVINDING'} {r.boekstuk or '(geen boekstuk)'} ref {r.referentie!r} "
            f"{r.leverancier or '?'} | factuur {r.factuurdatum} boekdatum {r.boekdatum} geboekt {r.geboekt_op} door {r.geboekt_door} | "
            f"regel {r.regelnummer}/{r.aantal_regels} gb {r.grootboek or '?'} netto {_euro(r.netto)} btw {_euro(r.btw)} | "
            f"aangifte {r.aangifte} | route {r.route}"
            + (f" | verdeling {r.verdeling_delen} delen" if r.gedekt_door_verdeling else "")
            + (
                f" | voorstel {r.voorstel.project_naam} ({r.voorstel.herkomst})"
                if r.voorstel
                else ("" if r.gedekt_door_verdeling else " | project: mens nodig")
            )
            + f" | document {r.document_id} rlz {r.rlz_document_id}"
        )
    routes = uitkomst.routes
    if routes:
        regels.append(
            "  routeverdeling (per document): "
            + ", ".join(f"{ROUTE_TEKST[k]} = {v}" for k, v in sorted(routes.items()))
        )
    if uitkomst.rlz_rijen is None:
        regels.append(
            f"  RLZ-kant: niet gemeten{' — ' + uitkomst.rlz_melding if uitkomst.rlz_melding else ' (zonder --rlz)'}"
        )
    else:
        regels.append(
            f"  RLZ-kant: {uitkomst.rlz_documenten_gelezen} geboekte PurchaseInvoices gelezen ({uitkomst.rlz_leesfouten} leesfouten), "
            f"{uitkomst.rlz_documenten_zonder_project} documenten mét kostenregel zonder Project, waarvan {uitkomst.rlz_alleen} niet door de "
            f"module geboekt (van vóór/buiten de module) — verschil module-kant {uitkomst.documenten_zonder_project} ↔ RLZ-kant verklaard."
        )
        for r in uitkomst.rlz_rijen:
            regels.append(
                f"    RLZ {r.boekstuk or '?'} ref {r.referentie!r} datum {r.datum} boekdatum {r.boekdatum} gb {r.grootboek or '?'} "
                f"netto {_euro(r.netto)} btw {_euro(r.btw)} {'(module)' if r.van_module else '(vóór/buiten module)'} "
                f"rlz {r.rlz_document_id} regel {r.regel_id}"
            )
    return regels


def project_verplichte_administraties(session: Session) -> list[Administratie]:
    return list(
        session.scalars(
            select(Administratie)
            .where(Administratie.project_verplicht.is_(True), Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        )
    )
