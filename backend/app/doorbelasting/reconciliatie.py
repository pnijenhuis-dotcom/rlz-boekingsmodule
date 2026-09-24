"""Doorbelasting-reconciliatie (failsafe, zelfde patroon als de omzet-reconciliatie):
vergelijkt elke lokale doorbelastings-boeking met de werkelijke RLZ-staat van BEIDE kanten —
de verkoopfactuur in de bron-administratie én de spiegel-inkoopfactuur in de
doel-administratie — en rapporteert afwijkingen: in de RLZ-UI teruggedraaide documenten
(Status 1), verdwenen documenten, alle half_geboekt-rijen (die zíjn de afwijking) en
spiegel_open-taken ouder dan een week (open werk mag niet stilletjes verstoffen).

Sinds 24-09 (opdracht "doorbelasting btw per tarief over subtotaal — RLZ-vorm") óók:
- **bedrag** — RLZ's `TotalPayableAmount`/`TotalTaxAmount` van verkoop én spiegel naast onze registratie
  (netto + provisie + btw): méér dan `BEDRAG_TOLERANTIE` (€ 0,05) verschil, óf verkoop ≠ spiegel in RLZ =
  `doorbelasting_bedrag_afwijking` (actie, besluit Peter in de opdracht); ≤ € 0,05 is géén bevinding maar het
  cent-verschil van de oude per-regel-afronding — dat herstelt de data-stap `doorbelasting-bedragen-gelijktrekken`
  (hier alleen geteld in `centverschillen`, zichtbaar in de CLI-regel);
- **factuur-PDF** — een geboekte doorbelasting zonder `factuur_pdf_status = aanwezig` ouder dan
  `FACTUUR_PDF_SIGNALEER_NA` (1 dag) = `doorbelasting_factuur_pdf_ontbreekt` (meten) mét de handeling
  "Factuur-PDF herstellen" op de rij (art. 35a: de spiegel moet een factuur op naam dragen).
Rapporteert alleen; herstellen is mensenwerk (of de expliciete nazorg-CLI)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session
from app.doorbelasting.factuur import FACTUUR_STATUS_AANWEZIG
from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

_GEBOEKTE_STATUSSEN = {2, 3}
_SPIEGEL_OPEN_SIGNALEER_NA = timedelta(days=7)
#: 24-09: een geboekte doorbelasting zonder factuur-PDF ouder dan een dag is een bevinding mét handeling.
FACTUUR_PDF_SIGNALEER_NA = timedelta(days=1)
#: 24-09: zelfde grens als de automatische acceptatie in de documenten-reconciliatie (reconciliatie-nazorg 15-09) en de
#: data-stap `doorbelasting-bedragen-gelijktrekken` — tot hier is het een cent-verschil van de oude per-regel-afronding.
BEDRAG_TOLERANTIE = Decimal("0.05")
SOORT_BEDRAG_AFWIJKING = "doorbelasting_bedrag_afwijking"
SOORT_FACTUUR_PDF_ONTBREEKT = "doorbelasting_factuur_pdf_ontbreekt"


@dataclass(frozen=True)
class DoorbelastingAfwijking:
    administratie_id: uuid.UUID
    boeking_id: uuid.UUID
    document_id: uuid.UUID
    soort: str
    detail: str
    #: 24-09: extra sleutels voor de leesbare tekst/handeling (rlz_verkoop_incl, rlz_spiegel_incl, factuur_pdf_reden).
    extra: dict[str, str] = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class DoorbelastingReconciliatieResultaat:
    afwijkingen: list[DoorbelastingAfwijking]
    fouten: dict[uuid.UUID, str]
    #: A12 (07-09): Odoo-administraties mét doorbelasting aan — RLZ-only blok, zichtbaar overgeslagen (geen fout).
    overgeslagen: dict[uuid.UUID, str] = field(default_factory=dict)
    #: 24-09: per administratie het aantal boekingen mét een cent-verschil ≤ € 0,05 (geen bevinding — data-stap).
    centverschillen: dict[uuid.UUID, int] = field(default_factory=dict)


@dataclass(frozen=True)
class RlzBedragen:
    """De totalen die RLZ op een document vastlegt (record-vorm; STAP-0 24-09)."""

    incl: Decimal | None
    btw: Decimal | None
    netto: Decimal | None


def _bedrag(doc: dict, *sleutels: str) -> Decimal | None:
    for s in sleutels:
        if doc.get(s) is not None:
            return Decimal(str(doc[s])).quantize(Decimal("0.01"))
    return None


def _rlz_bedragen(doc: dict) -> RlzBedragen:
    return RlzBedragen(
        incl=_bedrag(doc, "TotalPayableAmount", "BaseInvoiceAmount"),
        btw=_bedrag(doc, "TotalTaxAmount", "BaseTaxAmount"),
        netto=_bedrag(doc, "TotalNetAmount", "BaseNetAmount"),
    )


def _controleer(client: RlzClient, pad: str, rlz_id: uuid.UUID, label: str) -> tuple[str, str] | None:
    fout, _ = _controleer_met_bedragen(client, pad, rlz_id, label)
    return fout


def _controleer_met_bedragen(
    client: RlzClient, pad: str, rlz_id: uuid.UUID, label: str
) -> tuple[tuple[str, str] | None, RlzBedragen | None]:
    """Eén GET: statusafwijking (zoals altijd) én de RLZ-bedragen (24-09) uit hetzelfde record."""
    try:
        doc = client.get(f"{pad}/{rlz_id}")
    except RlzApiError as exc:
        if exc.status_code == 404:
            return ("ontbreekt_in_rlz", f"{label} {rlz_id} bestaat niet (meer) in RLZ"), None
        return ("controle_mislukt", f"{label} {rlz_id} kon niet opgehaald worden: {exc}"), None
    status = doc.get("Status")
    bedragen = _rlz_bedragen(doc)
    if status not in _GEBOEKTE_STATUSSEN:
        return ("status_niet_definitief", f"{label} {rlz_id} staat in RLZ op Status {status}"), bedragen
    return None, bedragen


def toets_bedragen(
    *,
    ons_incl: Decimal,
    ons_btw: Decimal,
    verkoop: RlzBedragen | None,
    spiegel: RlzBedragen | None,
    tolerantie: Decimal = BEDRAG_TOLERANTIE,
) -> tuple[str | None, str]:
    """Pure toets (24-09): ("afwijking" | "centverschil" | None, detail). Afwijking = |RLZ − module| > tolerantie op
    een van beide kanten óf verkoop ≠ spiegel in RLZ; centverschil = ≠ 0 maar ≤ tolerantie (data-stap); None = gelijk
    of niet toetsbaar (geen RLZ-bedrag gelezen)."""
    kanten = [(k, b) for k, b in (("verkoop", verkoop), ("spiegel", spiegel)) if b is not None and b.incl is not None]
    if not kanten:
        return None, "geen RLZ-bedragen gelezen"
    beide = verkoop is not None and spiegel is not None and verkoop.incl is not None and spiegel.incl is not None
    if beide and (
        verkoop.incl != spiegel.incl or (verkoop.btw is not None and spiegel.btw is not None and verkoop.btw != spiegel.btw)
    ):
        return "afwijking", (
                f"verkoop en spiegel verschillen in RLZ: verkoop {verkoop.incl} (btw {verkoop.btw}) ≠ spiegel "
                f"{spiegel.incl} (btw {spiegel.btw}); module {ons_incl} (btw {ons_btw})"
            )
    grootste = max(abs(b.incl - ons_incl) for _, b in kanten)
    if grootste == 0:
        return None, "gelijk aan RLZ"
    delen = ", ".join(f"{k} {b.incl} (btw {b.btw})" for k, b in kanten)
    if grootste > tolerantie:
        return "afwijking", f"module {ons_incl} (btw {ons_btw}) ≠ RLZ {delen} — verschil {grootste}"
    return "centverschil", f"module {ons_incl} (btw {ons_btw}) vs RLZ {delen} — cent-verschil {grootste} (data-stap)"


def reconcilieer_doorbelasting(administratie_id: uuid.UUID) -> list[DoorbelastingAfwijking]:
    afwijkingen, _cent = reconcilieer_doorbelasting_met_tellers(administratie_id)
    return afwijkingen


def reconcilieer_doorbelasting_met_tellers(administratie_id: uuid.UUID) -> tuple[list[DoorbelastingAfwijking], int]:
    """(afwijkingen, aantal cent-verschillen ≤ € 0,05) — de teller is informatief (CLI-regel), geen bevinding."""
    with scoped_session(administratie_id) as session:
        boekingen = session.scalars(
            select(DoorbelastingBoeking).where(
                DoorbelastingBoeking.administratie_id == administratie_id,
                DoorbelastingBoeking.status.in_(
                    (
                        DoorbelastingBoekingStatus.GEBOEKT.value,
                        DoorbelastingBoekingStatus.HALF_GEBOEKT.value,
                        DoorbelastingBoekingStatus.SPIEGEL_OPEN.value,
                    )
                ),
            )
        ).all()
    if not boekingen:
        return [], 0

    afwijkingen: list[DoorbelastingAfwijking] = []
    centverschillen = 0
    verkoop_bedragen: dict[uuid.UUID, RlzBedragen | None] = {}
    spiegel_bedragen: dict[uuid.UUID, RlzBedragen | None] = {}

    def meld(boeking: DoorbelastingBoeking, soort: str, detail: str, **extra: str) -> None:
        afwijkingen.append(
            DoorbelastingAfwijking(
                administratie_id=administratie_id,
                boeking_id=boeking.id,
                document_id=boeking.document_id,
                soort=soort,
                detail=detail,
                extra={k: v for k, v in extra.items() if v},
            )
        )

    nu = datetime.now(UTC)
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    with client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id) as bron_client:
        for boeking in boekingen:
            if boeking.status == DoorbelastingBoekingStatus.HALF_GEBOEKT.value:
                meld(
                    boeking,
                    "half_geboekt",
                    f"half geboekt sinds {boeking.aangemaakt_op:%Y-%m-%d}: {boeking.half_geboekt_detail}",
                )
                continue
            # bron-kant: de verkoopfactuur moet geboekt staan (geldt voor geboekt én spiegel_open)
            fout, bedragen = _controleer_met_bedragen(
                bron_client, "SalesInvoices", boeking.verkoop_rlz_id, "doorbelastings-verkoop"
            )
            verkoop_bedragen[boeking.id] = bedragen
            if fout is not None:
                meld(boeking, *fout)
            if boeking.status == DoorbelastingBoekingStatus.SPIEGEL_OPEN.value:
                leeftijd = nu - boeking.aangemaakt_op
                if leeftijd > _SPIEGEL_OPEN_SIGNALEER_NA:
                    meld(
                        boeking,
                        "spiegel_open_verouderd",
                        f"open spiegel-taak staat al {leeftijd.days} dagen open (doel niet onboarded?)",
                    )
            # 24-09 stap 4: geboekt zonder rechtsgeldige factuur-PDF, ouder dan een dag → bevinding mét handeling.
            if (
                boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value
                and boeking.factuur_pdf_status != FACTUUR_STATUS_AANWEZIG
                and (nu - boeking.aangemaakt_op) > FACTUUR_PDF_SIGNALEER_NA
            ):
                meld(
                    boeking,
                    SOORT_FACTUUR_PDF_ONTBREEKT,
                    f"geboekt op {boeking.aangemaakt_op:%Y-%m-%d} zonder factuur-PDF "
                    f"({boeking.factuur_pdf_status or 'nooit geprobeerd'}: {boeking.factuur_pdf_reden or '-'})",
                    factuur_pdf_reden=boeking.factuur_pdf_reden or "",
                )

    # doel-kant per doel-administratie (eigen client per administratie, alleen voor geboekte)
    per_doel: dict[uuid.UUID, list[DoorbelastingBoeking]] = {}
    for boeking in boekingen:
        if boeking.status == DoorbelastingBoekingStatus.GEBOEKT.value and boeking.doel_administratie_id:
            per_doel.setdefault(boeking.doel_administratie_id, []).append(boeking)
    for doel_administratie_id, doel_boekingen in per_doel.items():
        try:
            doel_rlz_admin_id = rlz_admin_id_voor(doel_administratie_id)
            with client_voor_rlz_admin_id(doel_rlz_admin_id).for_administration(doel_rlz_admin_id) as doel_client:
                for boeking in doel_boekingen:
                    fout, bedragen = _controleer_met_bedragen(
                        doel_client, "PurchaseInvoices", boeking.spiegel_rlz_id, "spiegel-inkoopfactuur"
                    )
                    spiegel_bedragen[boeking.id] = bedragen
                    if fout is not None:
                        meld(boeking, *fout)
        except GeenRlzCredentials:
            for boeking in doel_boekingen:
                meld(
                    boeking,
                    "controle_mislukt",
                    f"doel-administratie {doel_administratie_id} heeft geen credentials (meer) — "
                    "spiegel niet controleerbaar",
                )

    # 24-09: bedragtoets module ↔ RLZ (beide kanten), alleen op boekingen die aan beide kanten geboekt/leesbaar zijn.
    for boeking in boekingen:
        if boeking.status not in (DoorbelastingBoekingStatus.GEBOEKT.value, DoorbelastingBoekingStatus.SPIEGEL_OPEN.value):
            continue
        ons_incl = (boeking.netto_totaal + boeking.provisie_bedrag + boeking.btw_bedrag).quantize(Decimal("0.01"))
        uitkomst, detail = toets_bedragen(
            ons_incl=ons_incl,
            ons_btw=boeking.btw_bedrag,
            verkoop=verkoop_bedragen.get(boeking.id),
            spiegel=spiegel_bedragen.get(boeking.id),
        )
        if uitkomst == "afwijking":
            v, s = verkoop_bedragen.get(boeking.id), spiegel_bedragen.get(boeking.id)
            meld(
                boeking,
                SOORT_BEDRAG_AFWIJKING,
                detail,
                rlz_verkoop_incl=str(v.incl) if v and v.incl is not None else "",
                rlz_spiegel_incl=str(s.incl) if s and s.incl is not None else "",
            )
        elif uitkomst == "centverschil":
            centverschillen += 1
    return afwijkingen, centverschillen


# --- Opruimlijst achtergebleven RLZ-concepten (hygiëne-run 2026-08-16) ---------------------------
#
# RLZ-actie 19 (storno) verwijdert niet maar zet terug naar concept (Status 1); een gefaalde
# boekpoging kan bovendien een concept achterlaten zónder lokale boeking-rij (document-PUT
# geslaagd, actie 17 niet). Die concepten blijven in RLZ staan tot een mens ze opruimt —
# kernprincipe 3 (expliciet herbevestigd door Peter): DE APP VERWIJDERT NOOIT iets in RLZ.
# Deze lijst signaleert dus alleen ("handmatig opruimen indien gewenst") en telt nooit mee in
# de exit-code van de reconciliatie.


@dataclass(frozen=True)
class OpruimKandidaat:
    administratie_id: uuid.UUID  # bron-administratie (eigenaar van de doorbelasting)
    concept_administratie_id: uuid.UUID  # waar het concept staat (bron of doel)
    kant: str  # 'verkoop_bron' | 'spiegel_doel'
    rlz_id: uuid.UUID
    document_id: uuid.UUID
    referentie: str | None
    reden: str  # 'gestorneerd' | 'vervallen_run'
    detail: str


@dataclass(frozen=True)
class OpruimlijstResultaat:
    kandidaten: list[OpruimKandidaat]
    fouten: list[str]


def _rlz_status(client: RlzClient, pad: str, rlz_id: uuid.UUID) -> int | None:
    """RLZ-status van een document, of None bij 404 (al opgeruimd — geen bevinding)."""
    try:
        doc = client.get(f"{pad}/{rlz_id}")
    except RlzApiError as exc:
        if exc.status_code == 404:
            return None
        raise
    return doc.get("Status")


_TeControleren = tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID | None, str | None, str, str]


def _dedupliceer_te_controleren(items: list[_TeControleren]) -> list[_TeControleren]:
    """Eén regel per RLZ-concept (blok D, 06-09): sleutel = (verkoop_rlz_id, spiegel_rlz_id,
    doel_administratie_id). Referenties worden uniek samengevoegd ("24713188, 24713193"), redenen
    gesorteerd met '+' ("gestorneerd+vervallen_run"), details met '; '. Volgorde van eerste
    voorkomen blijft behouden zodat de CLI-uitvoer stabiel is."""
    samengevoegd: dict[tuple[uuid.UUID, uuid.UUID, uuid.UUID | None], dict] = {}
    for document_id, verkoop_id, spiegel_id, doel_id, referentie, reden, detail in items:
        sleutel = (verkoop_id, spiegel_id, doel_id)
        groep = samengevoegd.get(sleutel)
        if groep is None:
            groep = {"document_id": document_id, "referenties": [], "redenen": [], "details": []}
            samengevoegd[sleutel] = groep
        if referentie and referentie not in groep["referenties"]:
            groep["referenties"].append(referentie)
        if reden not in groep["redenen"]:
            groep["redenen"].append(reden)
        if detail not in groep["details"]:
            groep["details"].append(detail)
    uit: list[_TeControleren] = []
    for (verkoop_id, spiegel_id, doel_id), groep in samengevoegd.items():
        uit.append(
            (
                groep["document_id"],
                verkoop_id,
                spiegel_id,
                doel_id,
                ", ".join(groep["referenties"]) or None,
                "+".join(sorted(groep["redenen"])),
                "; ".join(groep["details"]),
            )
        )
    return uit


def verzamel_opruimlijst(administratie_id: uuid.UUID) -> OpruimlijstResultaat:
    """Achtergebleven RLZ-concepten (Status 1) van gestorneerde boekingen en vervallen
    (gefaalde) runs, beide kanten. Alleen rapporteren — verwijderen is mensenwerk in de
    RLZ-UI."""
    from app.documenten.rlz_ids import rlz_doorbelasting_spiegel_id, rlz_doorbelasting_verkoop_id
    from app.doorbelasting.models import (
        DoorbelastingMapping,
        DoorbelastingRegel,
        DoorbelastingRun,
        DoorbelastingRunStatus,
    )

    with scoped_session(administratie_id) as session:
        gestorneerd = session.scalars(
            select(DoorbelastingBoeking).where(
                DoorbelastingBoeking.administratie_id == administratie_id,
                DoorbelastingBoeking.status == DoorbelastingBoekingStatus.GESTORNEERD.value,
            )
        ).all()
        vervallen_runs = session.scalars(
            select(DoorbelastingRun).where(
                DoorbelastingRun.administratie_id == administratie_id,
                DoorbelastingRun.status == DoorbelastingRunStatus.CONCEPT.value,
                DoorbelastingRun.laatste_fout.is_not(None),
            )
        ).all()
        run_mappings: dict[uuid.UUID, set[uuid.UUID]] = {}
        for run in vervallen_runs:
            mapping_ids = set(
                session.scalars(
                    select(DoorbelastingRegel.mapping_id).where(DoorbelastingRegel.run_id == run.id)
                )
            )
            run_mappings[run.id] = mapping_ids
        mappings = {
            m.id: m
            for m in session.scalars(
                select(DoorbelastingMapping).where(DoorbelastingMapping.administratie_id == administratie_id)
            )
        }
        session.expunge_all()

    kandidaten: list[OpruimKandidaat] = []
    fouten: list[str] = []

    # Te controleren doelen: (document_id, verkoop_rlz_id, spiegel_rlz_id, doel_administratie_id,
    # referentie, reden, detail) — uit gestorneerde boekingen én afgeleide GUID's van
    # vervallen runs (deterministische UUIDv5, app/documenten/rlz_ids.py).
    te_controleren: list[tuple[uuid.UUID, uuid.UUID, uuid.UUID, uuid.UUID | None, str | None, str, str]] = []
    for boeking in gestorneerd:
        te_controleren.append(
            (
                boeking.document_id,
                boeking.verkoop_rlz_id,
                boeking.spiegel_rlz_id,
                boeking.doel_administratie_id,
                boeking.verkoop_referentie,
                "gestorneerd",
                f"gestorneerd ({boeking.storno_reden or 'zonder reden'})",
            )
        )
    for run in vervallen_runs:
        for mapping_id in run_mappings.get(run.id, set()):
            mapping = mappings.get(mapping_id)
            if mapping is None:
                continue
            te_controleren.append(
                (
                    run.document_id,
                    rlz_doorbelasting_verkoop_id(run.document_id, mapping.doel_customer_guid),
                    rlz_doorbelasting_spiegel_id(run.document_id, mapping.doel_customer_guid),
                    mapping.doel_administratie_id,
                    None,
                    "vervallen_run",
                    f"gefaalde boekpoging (run {run.id}, doel {mapping.doelentiteit_naam})",
                )
            )

    # Blok D (reconciliatie-melding 06-09): verkoop_rlz_id en spiegel_rlz_id zijn DETERMINISTISCH per
    # (document, doel-customer-GUID) — meerdere gestorneerde boekingen en/of vervallen runs op hetzelfde
    # document wijzen dus naar HETZELFDE RLZ-concept. Vóór de fix gaf dat één LET-OP-regel per boeking
    # (run 05-09: 11 regels voor ±6 concepten). Hier dedupliceren op (verkoop_rlz_id, spiegel_rlz_id,
    # doel) zodat elk concept één controle en één regel krijgt; referenties/redenen/details samengevoegd.
    te_controleren = _dedupliceer_te_controleren(te_controleren)

    if not te_controleren:
        return OpruimlijstResultaat(kandidaten=[], fouten=[])

    def voeg_toe(
        kant: str,
        concept_administratie_id: uuid.UUID,
        rlz_id: uuid.UUID,
        document_id: uuid.UUID,
        referentie: str | None,
        reden: str,
        detail: str,
    ) -> None:
        kandidaten.append(
            OpruimKandidaat(
                administratie_id=administratie_id,
                concept_administratie_id=concept_administratie_id,
                kant=kant,
                rlz_id=rlz_id,
                document_id=document_id,
                referentie=referentie,
                reden=reden,
                detail=detail,
            )
        )

    # Bron-kant: verkoop-concepten. Sweep bug 14-09: een bron zonder RLZ-credential (Odoo-administratie,
    # nog niet gekoppeld, credential ingetrokken) mét gestorneerde/vervallen runs gaf hier een onafgevangen
    # GeenRlzCredentials → 500 op de "Scan"-knop; nu dezelfde zichtbare fout-regel als de doel-kant.
    try:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        with client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id) as bron_client:
            for document_id, verkoop_rlz_id, _spiegel, _doel, referentie, reden, detail in te_controleren:
                try:
                    status = _rlz_status(bron_client, "SalesInvoices", verkoop_rlz_id)
                except RlzApiError as exc:
                    fouten.append(f"verkoop {verkoop_rlz_id} niet controleerbaar: {exc}")
                    continue
                if status == 1:
                    voeg_toe("verkoop_bron", administratie_id, verkoop_rlz_id, document_id, referentie, reden, detail)
    except GeenRlzCredentials:
        fouten.append(
            f"bron-administratie heeft geen RLZ-credentials (meer) — "
            f"{len(te_controleren)} verkoop-concept(en) niet controleerbaar"
        )

    # Doel-kant: spiegel-concepten, per doel-administratie één client.
    per_doel: dict[uuid.UUID, list[tuple[uuid.UUID, uuid.UUID, str | None, str, str]]] = {}
    for document_id, _verkoop, spiegel_rlz_id, doel_administratie_id, referentie, reden, detail in te_controleren:
        if doel_administratie_id is not None:
            per_doel.setdefault(doel_administratie_id, []).append(
                (document_id, spiegel_rlz_id, referentie, reden, detail)
            )
    for doel_administratie_id, items in per_doel.items():
        try:
            doel_rlz_admin_id = rlz_admin_id_voor(doel_administratie_id)
            with client_voor_rlz_admin_id(doel_rlz_admin_id).for_administration(doel_rlz_admin_id) as doel_client:
                for document_id, spiegel_rlz_id, referentie, reden, detail in items:
                    try:
                        status = _rlz_status(doel_client, "PurchaseInvoices", spiegel_rlz_id)
                    except RlzApiError as exc:
                        fouten.append(f"spiegel {spiegel_rlz_id} niet controleerbaar: {exc}")
                        continue
                    if status == 1:
                        voeg_toe(
                            "spiegel_doel", doel_administratie_id, spiegel_rlz_id, document_id,
                            referentie, reden, detail,
                        )
        except GeenRlzCredentials:
            fouten.append(
                f"doel-administratie {doel_administratie_id} heeft geen credentials (meer) — "
                f"{len(items)} spiegel-concept(en) niet controleerbaar"
            )
    return OpruimlijstResultaat(kandidaten=kandidaten, fouten=fouten)


def verzamel_alle_opruimlijsten() -> OpruimlijstResultaat:
    """Over alle administraties met doorbelasting aan — zelfde looppatroon als
    reconcilieer_alle_doorbelasting; puur informatief (nooit exit-code)."""
    with scoped_session(None) as session:
        administraties = session.scalars(
            select(Administratie).where(
                Administratie.actief.is_(True), Administratie.doorbelasting_ingeschakeld.is_(True)
            )
        ).all()
    from app.backends.port import Backend

    kandidaten: list[OpruimKandidaat] = []
    fouten: list[str] = []
    for administratie in administraties:
        if administratie.boekhoud_backend == Backend.ODOO.value:
            continue  # RLZ-only (A12, 07-09): de opruimlijst kijkt naar RLZ-concepten; Odoo kent die niet
        try:
            resultaat = verzamel_opruimlijst(administratie.id)
            kandidaten.extend(resultaat.kandidaten)
            fouten.extend(resultaat.fouten)
        except Exception as exc:  # noqa: BLE001 — rapportagerun: doorgaan, fout zichtbaar
            logger.exception("Opruimlijst faalde voor %s", administratie.naam)
            fouten.append(f"{administratie.naam}: {exc}")
    return OpruimlijstResultaat(kandidaten=kandidaten, fouten=fouten)


def reconcilieer_alle_doorbelasting() -> DoorbelastingReconciliatieResultaat:
    """Over alle actieve administraties mét doorbelasting aan (CLI-hook, zelfde vorm als
    reconcilieer_alle_omzet — een fout per administratie stopt de rest niet)."""
    with scoped_session(None) as session:
        administraties = session.scalars(
            select(Administratie).where(
                Administratie.actief.is_(True), Administratie.doorbelasting_ingeschakeld.is_(True)
            )
        ).all()
    from app.backends.port import Backend
    from app.backends.registry import RLZ_ONLY_OVERGESLAGEN

    afwijkingen: list[DoorbelastingAfwijking] = []
    fouten: dict[uuid.UUID, str] = {}
    overgeslagen: dict[uuid.UUID, str] = {}
    centverschillen: dict[uuid.UUID, int] = {}
    for administratie in administraties:
        if administratie.boekhoud_backend == Backend.ODOO.value:
            overgeslagen[administratie.id] = RLZ_ONLY_OVERGESLAGEN  # RLZ-only blok (A12, 07-09)
            continue
        try:
            eigen, cent = reconcilieer_doorbelasting_met_tellers(administratie.id)
            afwijkingen.extend(eigen)
            if cent:
                centverschillen[administratie.id] = cent
        except Exception as exc:  # noqa: BLE001 — rapportagerun: doorgaan, fout zichtbaar
            logger.exception("Doorbelasting-reconciliatie faalde voor %s", administratie.naam)
            fouten[administratie.id] = f"{administratie.naam}: {exc}"
    return DoorbelastingReconciliatieResultaat(
        afwijkingen=afwijkingen, fouten=fouten, overgeslagen=overgeslagen, centverschillen=centverschillen
    )
