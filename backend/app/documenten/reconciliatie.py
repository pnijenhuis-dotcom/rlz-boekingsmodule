"""Documenten-reconciliatie: elk lokaal GEBOEKT inkoopdocument naast de werkelijke stand in de
boekhoud-backend van de administratie (A11/A12, fixrun 07-09 — backend-agnostisch via de inkoop-port).

- RLZ (`RlzInkoopPort.toets_geboekt`): GET op het herboeking-GUID van de actieve `boek_cyclus`; 404 óf een hol
  antwoord = `ontbreekt_in_rlz` (zwaarste categorie — er is niets meer om tegen te boeken; herstel = de actie
  "Opnieuw boeken" in Inzicht › Reconciliatie, `app/documenten/herboeken.py`); Status ∉ {2,3} =
  `status_niet_definitief`; bedrag/boekstuknummer-verschillen zoals voorheen.
- Odoo (`OdooInkoopPort.toets_geboekt`): account.move via onze koppeling/marker; ontbreekt = `ontbreekt_in_odoo`,
  state ≠ posted = `niet_geboekt_in_odoo`, een ONBEKENDE reversal (niet onze eigen tegenboeking) =
  `teruggedraaid_in_odoo`, bedrag/boekstuk zoals bij RLZ.
- RLZ-VERLEDEN van een overgestapte administratie (besluit Peter 07-09 op A12 beslispunt 1 — herziet "niet van
  toepassing/overgeslagen"): een document met een `RLZ-…`-boekstuk ZONDER Odoo-koppeling is vóór de kanteldatum in
  Reeleezee geboekt; Reeleezee blijft daar de bron van waarheid (bewaarplicht 7 jaar). Zo'n document wordt per
  document tegen RLZ getoetst met een `RlzInkoopPort` op de BEWAARDE credential (`odoo_koppeling.
  rlz_admin_id_voor_overstap` + de blijvende `rlz_credential`-rij — `app/rlz/credentials.py::
  client_voor_rlz_verleden`); documenten mét Odoo-spoor gaan naar de Odoo-port. Geen bewaarde credential
  (gearchiveerde webservice-login) = per document een ZICHTBARE `controle_mislukt`-bevinding
  "RLZ-verleden niet toetsbaar: geen bewaarde RLZ-credential" — nooit stil overslaan. `aantal_overgeslagen` blijft
  bestaan voor échte niet-van-toepassing-gevallen (een port die `van_toepassing=False` geeft) en is hier 0.
- Elke API-fout die niets over het document zegt (500/401/rate-limit) = `controle_mislukt` (les 12-08).
- Bank/omzet/doorbelasting blijven RLZ-only (Steigerbouw gebruikt ze niet) — die blokken slaan een
  Odoo-administratie zichtbaar over (`app/backends/registry.py::RLZ_ONLY_OVERGESLAGEN`).

Elke afwijking draagt `context` (leverancier, factuurnummer, boekstuk, administratienaam, bedragen, backend,
extern id/state) zodat de kantoor-UI namen kan tonen zonder extra queries (contract A↔A8)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import exists, func, select

from app.backends.port import Backend, InkoopPort, ToetsMislukt, ToetsUitkomst
from app.backends.registry import inkoop_port_voor
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document, DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.rlz.client import RlzClient
from app.rlz.credentials import (
    GeenRlzCredentials,
    client_voor_rlz_admin_id,
    client_voor_rlz_verleden,
    rlz_admin_id_voor,
)
from app.sync.models import VendorCache

# Kleine afrondingstolerantie, zelfde als de regeltelling-check (app/documenten/checks.py) —
# geen 0-tolerantie, wél klein genoeg om een echte afwijking te vangen.
_ROND_TOLERANTIE = Decimal("0.01")

#: Reconciliatie-nazorg 15-09 (besluit Peter 14-09 "systeem bepaalt of actie nodig is"): een bedragverschil tot en met
#: € 0,05 tussen de module en RLZ/Odoo op een GEBOEKT document is een btw-cent-afronding (RLZ rekent btw per regel, de
#: factuur per totaal; Kempen Facilities: Lusso/Booking Experts 2–3 ct) — geen bevinding voor het kantoor maar een
#: automatische acceptatie mét audit (`reconciliatie_auto_geaccepteerd`) en dagteller. Groter = echte afwijking (Booking
#: Experts 20260205347 Δ 0,97 = echte wijziging). De afwijking zélf wordt nog steeds aangemaakt (niets verdwijnt stil);
#: de acceptatie gebeurt in het reconciliatie-alles-blok (`app/cli.py::_reconciliatie`).
AFRONDING_TOLERANTIE = Decimal("0.05")
AFRONDING_REDEN = "afronding ≤ 0,05"

#: Soorten die "het externe document is er niet meer" betekenen — de zwaarste categorie én de enige waarop de
#: actie "Opnieuw boeken (document verdwenen)" bestaat. Per backend een eigen naam (contract A↔A8 punt 2).
ONTBREEKT_SOORTEN = frozenset({"ontbreekt_in_rlz", "ontbreekt_in_odoo"})

#: Hercontrole "intussen buiten de module geboekt" (Peter 22-09, casus Bouwadvies F/2026/01235): élk OPEN document dat
#: op de klant of het kantoor wacht wordt dagelijks VERS tegen RLZ/Odoo getoetst met dezelfde bestaanscheck als de harde
#: check Duplicaatcheck (`extern_bestaan.zoek_extern_bestaand`, over álle crediteurrecords van de identiteit, ± 60 d,
#: genormaliseerd) — bewust zonder de checks-cache (0165): dít is de vers-toets. Treffer buiten de module = bevinding
#: `intussen_extern_geboekt` mét boekstuk/bedrag/datum en twee handelingen op de rij (afwijzen als al geboekt / toch
#: verschillend).
SOORT_INTUSSEN_EXTERN_GEBOEKT = "intussen_extern_geboekt"
HERCONTROLE_STATUSSEN = frozenset(
    {DocumentStatus.TER_ACCORDERING, DocumentStatus.WACHT_OP_IBAN_ACCORDERING, DocumentStatus.KLAAR_OM_TE_BOEKEN}
)
#: `klaar_om_te_boeken` telt pas mee als het document langer dan dit stil ligt (een vers klaargezet document wordt zo
#: geboekt — de harde check op het boekmoment dekt dat al); ter_accordering/wacht_op_iban altijd.
HERCONTROLE_KLAAR_MINIMUM = timedelta(days=1)


@dataclass(frozen=True)
class ReconciliatieAfwijking:
    document_id: uuid.UUID
    rlz_document_id: uuid.UUID
    soort: str
    detail: str
    #: naamverrijking voor rapport/UI (leverancier_naam, factuurnummer, rlz_boekstuk, administratie_naam,
    #: bedrag_lokaal, bedrag_extern, backend, extern_id, extern_state) — bewust buiten eq/hash
    context: dict[str, str | None] = field(default_factory=dict, compare=False, hash=False)


@dataclass(frozen=True)
class ReconciliatieRapport:
    administratie_id: uuid.UUID
    aantal_gecontroleerd: int
    afwijkingen: tuple[ReconciliatieAfwijking, ...]
    #: documenten die in géén backend te toetsen zijn (een port gaf `van_toepassing=False`) — sinds 07-09 niet meer
    #: het RLZ-verleden (dat wordt getoetst), dus in de praktijk 0
    aantal_overgeslagen: int = 0
    backend: str = Backend.RLZ.value
    #: verdeling van de toets over de backends (Odoo-administratie: N in Odoo, M in het Reeleezee-verleden)
    aantal_in_odoo: int = 0
    aantal_in_rlz_verleden: int = 0
    #: Hercontrole open documenten (22-09): hoeveel getoetst; per overgeslagen document (id, reden) — zichtbaar, nooit
    #: stil (storing = géén bevinding, wél deze regel). De treffers zelf staan als `intussen_extern_geboekt` in
    #: `afwijkingen`.
    hercontrole_getoetst: int = 0
    hercontrole_overgeslagen: tuple[tuple[uuid.UUID, str], ...] = ()


@dataclass(frozen=True)
class _Open:
    """Eén open document voor de hercontrole (ter_accordering / wacht_op_iban / klaar_om_te_boeken > 1 dag)."""

    document_id: uuid.UUID
    status: DocumentStatus
    vendor_id: uuid.UUID | None
    referentie: str | None
    totaalbedrag: Decimal | None
    factuurdatum: Any
    boek_cyclus: int
    leverancier_naam: str | None
    #: sinds wanneer het document in deze stand staat (laatst_gewijzigd_op)
    sinds: datetime | None


@dataclass(frozen=True)
class HercontroleRapport:
    getoetst: int
    afwijkingen: tuple[ReconciliatieAfwijking, ...]
    overgeslagen: tuple[tuple[uuid.UUID, str], ...]


@dataclass(frozen=True)
class _Geboekt:
    document_id: uuid.UUID
    totaalbedrag: Decimal | None
    rlz_boekstuknummer: str | None
    boek_cyclus: int
    referentie: str | None
    leverancier_naam: str | None
    #: er bestaat een `odoo_document_koppeling` (soort boeking) voor déze boek_cyclus → het document is in Odoo geboekt
    heeft_odoo_koppeling: bool = False


def is_rlz_verleden(doc: _Geboekt) -> bool:
    """Geboekt in Reeleezee vóór de overstap: RLZ-boekstuk (`RLZ-…`) en geen Odoo-spoor voor deze cyclus. Puur op
    het lokale boekstuk/koppeling — geen API-call nodig om te routeren."""
    return not doc.heeft_odoo_koppeling and (doc.rlz_boekstuknummer or "").upper().startswith("RLZ-")


def _geboekte_documenten(administratie_id: uuid.UUID) -> list[_Geboekt]:
    from app.odoo.models import OdooDocumentKoppeling  # lazy: geen kring documenten ↔ odoo op moduleniveau

    in_odoo = (
        exists()
        .where(
            OdooDocumentKoppeling.document_id == Document.id,
            OdooDocumentKoppeling.boek_cyclus == func.coalesce(Boekvoorstel.boek_cyclus, 0),
            OdooDocumentKoppeling.soort == "boeking",
        )
        .label("heeft_odoo_koppeling")
    )
    with scoped_session(administratie_id) as session:
        rows = session.execute(
            select(
                Document.id,
                Boekvoorstel.totaalbedrag,
                Boekvoorstel.rlz_boekstuknummer,
                Boekvoorstel.boek_cyclus,
                Boekvoorstel.referentie,
                VendorCache.naam,
                in_odoo,
            )
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
            .join(
                VendorCache,
                (VendorCache.id == Boekvoorstel.vendor_id) & (VendorCache.administratie_id == administratie_id),
                isouter=True,
            )
            .where(Document.administratie_id == administratie_id, Document.status == DocumentStatus.GEBOEKT)
        ).all()
        return [
            _Geboekt(
                document_id=r[0],
                totaalbedrag=r[1],
                rlz_boekstuknummer=r[2],
                boek_cyclus=r[3] or 0,
                referentie=r[4],
                leverancier_naam=r[5],
                heeft_odoo_koppeling=bool(r[6]),
            )
            for r in rows
        ]


def _administratie_naam(administratie_id: uuid.UUID) -> str:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie.naam if administratie is not None else str(administratie_id)


def _str(waarde: object) -> str | None:
    return None if waarde is None else str(waarde)


def _context(doc: _Geboekt, *, administratie_naam: str, uitkomst: ToetsUitkomst | None, backend: Backend) -> dict:
    ctx = {
        "leverancier_naam": doc.leverancier_naam,
        "factuurnummer": doc.referentie,
        "rlz_boekstuk": doc.rlz_boekstuknummer,
        "administratie_naam": administratie_naam,
        "bedrag_lokaal": _str(doc.totaalbedrag),
        "bedrag_extern": _str(uitkomst.bedrag) if uitkomst is not None else None,
        "backend": backend.value,
        "extern_id": uitkomst.extern_id if uitkomst is not None else None,
        "extern_state": uitkomst.extern_state if uitkomst is not None else None,
        "boek_cyclus": str(doc.boek_cyclus),
    }
    if is_rlz_verleden(doc):
        # Alleen op verleden-documenten (andere detail-dicts blijven identiek): de leesbare laag zegt dan
        # "vóór de overstap in Reeleezee geboekt" en de UI kan het herkennen.
        ctx["rlz_verleden"] = "true"
    return ctx


def beoordeel_uitkomst(
    doc: _Geboekt, uitkomst: ToetsUitkomst, *, backend: Backend, administratie_naam: str
) -> list[ReconciliatieAfwijking]:
    """Pure vertaling van één port-uitkomst naar afwijkingen (testbaar zonder DB/HTTP). De soort-namen zijn
    stabiel: ze zitten in de acceptatie-vingerafdruk (bron|soort|detail)."""
    rlz_document_id = rlz_herboeking_id(doc.document_id, doc.boek_cyclus)
    ctx = _context(doc, administratie_naam=administratie_naam, uitkomst=uitkomst, backend=backend)
    pakket = "rlz" if backend is Backend.RLZ else "odoo"

    def afwijking(soort: str, detail: str) -> ReconciliatieAfwijking:
        return ReconciliatieAfwijking(doc.document_id, rlz_document_id, soort, detail, dict(ctx))

    if not uitkomst.bestaat:
        # Verdwenen: één afwijking, verder niets te vergelijken. Het detail draagt de RLZ-/Odoo-reden zodat de
        # vingerafdruk verandert als de werkelijkheid verandert (404 → hol object → …).
        return [afwijking(f"ontbreekt_in_{pakket}", uitkomst.reden or f"document niet gevonden in {pakket.upper()}")]

    uit: list[ReconciliatieAfwijking] = []
    if uitkomst.teruggedraaid:
        uit.append(
            afwijking(
                "teruggedraaid_in_odoo",
                uitkomst.reden or f"reversal aanwezig op {uitkomst.boekstuknummer or uitkomst.extern_id}",
            )
        )
    if not uitkomst.geboekt:
        if backend is Backend.RLZ:
            uit.append(afwijking("status_niet_definitief", f"RLZ-status={uitkomst.extern_state}"))
        else:
            uit.append(afwijking("niet_geboekt_in_odoo", f"Odoo-state={uitkomst.extern_state}"))
    if (
        doc.totaalbedrag is not None
        and uitkomst.bedrag is not None
        and abs(uitkomst.bedrag - doc.totaalbedrag) > _ROND_TOLERANTIE
    ):
        uit.append(afwijking("bedrag_wijkt_af", f"eigen=€{doc.totaalbedrag} {pakket}=€{uitkomst.bedrag}"))
    if uitkomst.boekstuknummer != doc.rlz_boekstuknummer:
        uit.append(
            afwijking(
                "boekstuknummer_wijkt_af",
                f"eigen={doc.rlz_boekstuknummer!r} {pakket}={uitkomst.boekstuknummer!r}",
            )
        )
    return uit


def afrondingsverschil(afwijking: ReconciliatieAfwijking) -> Decimal | None:
    """Puur: het absolute bedragverschil van een `bedrag_wijkt_af`-afwijking als het binnen `AFRONDING_TOLERANTIE`
    valt, anders None (ook None voor elke andere soort of als een bedrag ontbreekt/onleesbaar is — fail-closed: dan
    blijft het een gewone afwijking). Leest de context-bedragen (`bedrag_lokaal`/`bedrag_extern`), niet het detail."""
    if afwijking.soort != "bedrag_wijkt_af":
        return None
    try:
        lokaal = Decimal(str(afwijking.context.get("bedrag_lokaal")))
        extern = Decimal(str(afwijking.context.get("bedrag_extern")))
    except (InvalidOperation, TypeError, ValueError):
        return None
    if not lokaal.is_finite() or not extern.is_finite():
        return None
    verschil = abs(extern - lokaal)
    return verschil if verschil <= AFRONDING_TOLERANTIE else None


def is_afrondingsverschil(afwijking: ReconciliatieAfwijking) -> bool:
    return afrondingsverschil(afwijking) is not None


def _toets_document(
    port: InkoopPort, doc: _Geboekt, *, administratie_naam: str
) -> tuple[list[ReconciliatieAfwijking], bool]:
    """→ (afwijkingen, overgeslagen)."""
    try:
        uitkomst = port.toets_geboekt(
            document_id=doc.document_id, boek_cyclus=doc.boek_cyclus, boekstuknummer=doc.rlz_boekstuknummer
        )
    except ToetsMislukt as exc:
        # Alleen een échte "bestaat niet" is 'ontbreekt'; elke andere fout zegt niets over het document en werd
        # vóór 2026-08-12 tóch als verdwenen gerapporteerd — één kapotte verbinding zag er dan uit als een
        # administratie vol verdwenen boekingen. `controle_mislukt` is een andere vraag met een ander antwoord.
        return [_controle_mislukt(doc, str(exc), backend=port.backend, administratie_naam=administratie_naam)], False
    if not uitkomst.van_toepassing:
        return [], True
    return beoordeel_uitkomst(doc, uitkomst, backend=port.backend, administratie_naam=administratie_naam), False


def _controle_mislukt(
    doc: _Geboekt, detail: str, *, backend: Backend, administratie_naam: str
) -> ReconciliatieAfwijking:
    ctx = _context(doc, administratie_naam=administratie_naam, uitkomst=None, backend=backend)
    return ReconciliatieAfwijking(
        doc.document_id, rlz_herboeking_id(doc.document_id, doc.boek_cyclus), "controle_mislukt", detail, ctx
    )


def _rlz_verleden_port(administratie_id: uuid.UUID) -> InkoopPort:
    """Default-factory voor het RLZ-verleden: RLZ-port op de bewaarde credential (raise-t `GeenRlzCredentials`)."""
    from app.backends.rlz_inkoop import RlzInkoopPort

    return RlzInkoopPort(client_voor_rlz_verleden(administratie_id))


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _open_documenten(administratie_id: uuid.UUID, *, nu: datetime) -> list[_Open]:
    grens = nu - HERCONTROLE_KLAAR_MINIMUM
    with scoped_session(administratie_id) as session:
        rows = session.execute(
            select(
                Document.id,
                Document.status,
                Boekvoorstel.vendor_id,
                Boekvoorstel.referentie,
                Boekvoorstel.totaalbedrag,
                Boekvoorstel.factuurdatum,
                Boekvoorstel.boek_cyclus,
                VendorCache.naam,
                Document.laatst_gewijzigd_op,
            )
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
            .join(
                VendorCache,
                (VendorCache.id == Boekvoorstel.vendor_id) & (VendorCache.administratie_id == administratie_id),
                isouter=True,
            )
            .where(
                Document.administratie_id == administratie_id,
                Document.status.in_(tuple(HERCONTROLE_STATUSSEN)),
                Document.soort == "inkoopfactuur",
            )
            .order_by(Document.laatst_gewijzigd_op)
        ).all()
    uit: list[_Open] = []
    for r in rows:
        status = r[1]
        gewijzigd = r[8]
        if status == DocumentStatus.KLAAR_OM_TE_BOEKEN and gewijzigd is not None:
            g = gewijzigd if gewijzigd.tzinfo is not None else gewijzigd.replace(tzinfo=UTC)
            if g > grens:
                continue
        uit.append(
            _Open(
                document_id=r[0],
                status=status,
                vendor_id=r[2],
                referentie=r[3],
                totaalbedrag=r[4],
                factuurdatum=r[5],
                boek_cyclus=r[6] or 0,
                leverancier_naam=r[7],
                sinds=gewijzigd,
            )
        )
    return uit


def _hercontrole_context(
    doc: _Open, treffer: dict[str, Any], *, administratie_naam: str, backend: Backend
) -> dict[str, str | None]:
    from app.documenten import extern_bestaan

    status = extern_bestaan.status_van(treffer)
    datum = treffer.get("Date") or treffer.get("BookDate")
    return {
        "leverancier_naam": doc.leverancier_naam,
        "factuurnummer": doc.referentie,
        "administratie_naam": administratie_naam,
        "bedrag_lokaal": _str(doc.totaalbedrag),
        "bedrag_extern": _str(treffer.get("BaseInvoiceAmount")),
        "backend": backend.value,
        "extern_id": _str(treffer.get("id")),
        "extern_boekstuk": _str(treffer.get("ReceiptNumber") or treffer.get("InvoiceNumber")),
        "extern_referentie": _str(treffer.get("Reference")),
        "extern_status": _str(status),
        "extern_stand": "concept" if status == 1 else "geboekt",
        "extern_datum": str(datum)[:10] if datum else None,
        "match_basis": _str(treffer.get("match_basis")),
        "document_status": doc.status.value,
        "sinds": doc.sinds.isoformat() if doc.sinds is not None else None,
        "boek_cyclus": str(doc.boek_cyclus),
    }


def beoordeel_hercontrole(
    doc: _Open, treffers: list[dict[str, Any]], *, backend: Backend, administratie_naam: str, afgemeld: frozenset[str]
) -> ReconciliatieAfwijking | None:
    """Pure kern (testbaar zonder DB/HTTP): de eerste BLOKKERENDE treffer (zelfde genormaliseerde referentie, met of
    zonder gelijk bedrag — dezelfde bases die de boekstap blokkeren) die niet als "toch verschillend" is afgemeld → één
    afwijking `intussen_extern_geboekt`. Het detail = `omschrijf_treffer` (boekstuk, referentie, stand) —
    deterministisch, zit in de acceptatie-vingerafdruk. Een bedrag-datum-signaal (ander nummer) maakt hier bewust géén
    bevinding."""
    from app.documenten import extern_bestaan

    for treffer in treffers:
        if treffer.get("match_basis") not in extern_bestaan.BLOKKERENDE_BASES:
            continue
        if str(treffer.get("id") or "") in afgemeld:
            continue
        systeem = "Odoo" if backend is Backend.ODOO else "Reeleezee"
        return ReconciliatieAfwijking(
            doc.document_id,
            rlz_herboeking_id(doc.document_id, doc.boek_cyclus),
            SOORT_INTUSSEN_EXTERN_GEBOEKT,
            extern_bestaan.omschrijf_treffer(treffer, systeem=systeem),
            _hercontrole_context(doc, treffer, administratie_naam=administratie_naam, backend=backend),
        )
    return None


def hercontroleer_open_documenten(
    *,
    administratie_id: uuid.UUID,
    port: InkoopPort | None = None,
    client: Any | None = None,
    nu: datetime | None = None,
    administratie_naam: str | None = None,
) -> HercontroleRapport:
    """Dagelijkse vers-toets (Peter 22-09): voor élk open document (`HERCONTROLE_STATUSSEN`, klaar_om_te_boeken > 1 dag)
    de RLZ-/Odoo-bestaanscheck opnieuw — één `zoek_extern_bestaand` per document op één client per administratie (de
    throttling van de client bundelt), dagelijks dus hooguit één keer per document per dag. Storing (verbinding,
    RLZ-fout, geen credential) = géén bevinding, wél zichtbaar overgeslagen mét reden; de eigen (her)boek-/
    tegenboekketen en de door een mens afgemelde externe id's (`intussen_extern_geboekt.afgemelde_extern_ids`) tellen
    nooit als treffer."""
    from app.documenten import duplicaat_module, extern_bestaan, intussen_extern_geboekt

    nu = nu or datetime.now(UTC)
    open_docs = _open_documenten(administratie_id, nu=nu)
    if not open_docs:
        return HercontroleRapport(getoetst=0, afwijkingen=(), overgeslagen=())
    naam = administratie_naam or _administratie_naam(administratie_id)
    eigen_port = False
    if client is None:
        if port is None:
            try:
                port = inkoop_port_voor(administratie_id, rlz_client_factory=lambda: _rlz_client_voor(administratie_id))
                eigen_port = True
            except Exception as exc:  # noqa: BLE001 — geen credential/onbekende backend: alles zichtbaar overgeslagen
                reden = f"hercontrole niet mogelijk: {exc}"
                return HercontroleRapport(
                    getoetst=0, afwijkingen=(), overgeslagen=tuple((d.document_id, reden) for d in open_docs)
                )
        try:
            client = port.leesclient()
        except Exception as exc:  # noqa: BLE001 — leesclient openen mislukt = storing, zichtbaar
            if eigen_port:
                port.__exit__(None, None, None)
            reden = f"hercontrole niet mogelijk: {exc}"
            return HercontroleRapport(
                getoetst=0, afwijkingen=(), overgeslagen=tuple((d.document_id, reden) for d in open_docs)
            )
    backend = port.backend if port is not None else Backend.RLZ
    afwijkingen: list[ReconciliatieAfwijking] = []
    overgeslagen: list[tuple[uuid.UUID, str]] = []
    try:
        with scoped_session(administratie_id) as session:
            identiteiten = {
                d.document_id: duplicaat_module.identiteit_vendor_ids(
                    session, administratie_id=administratie_id, vendor_id=d.vendor_id
                )
                for d in open_docs
            }
            afgemeld = {
                d.document_id: intussen_extern_geboekt.afgemelde_extern_ids(session, d.document_id) for d in open_docs
            }
        for doc in open_docs:
            if doc.vendor_id is None or not doc.referentie:
                overgeslagen.append((doc.document_id, "geen crediteur of referentie — niets om op te toetsen"))
                continue
            keten = {str(rlz_herboeking_id(doc.document_id, c)) for c in range(doc.boek_cyclus + 1)} | {
                str(rlz_tegenboeking_id(doc.document_id, c)) for c in range(doc.boek_cyclus + 1)
            }
            try:
                treffers = extern_bestaan.zoek_extern_bestaand(
                    client,
                    vendor_ids=list(dict.fromkeys([doc.vendor_id, *identiteiten.get(doc.document_id, ())])),
                    referentie=doc.referentie,
                    totaalbedrag=doc.totaalbedrag,
                    factuurdatum=doc.factuurdatum,
                    uitgezonderd_ids=keten,
                )
            except Exception as exc:  # noqa: BLE001 — storing = geen bevinding, zichtbaar overgeslagen (opdracht 22-09)
                overgeslagen.append((doc.document_id, f"controle mislukt: {exc}"))
                continue
            afwijking = beoordeel_hercontrole(
                doc,
                treffers,
                backend=backend,
                administratie_naam=naam,
                afgemeld=afgemeld.get(doc.document_id, frozenset()),
            )
            if afwijking is not None:
                afwijkingen.append(afwijking)
    finally:
        if eigen_port and port is not None:
            port.__exit__(None, None, None)
    return HercontroleRapport(
        getoetst=len(open_docs) - len(overgeslagen), afwijkingen=tuple(afwijkingen), overgeslagen=tuple(overgeslagen)
    )


def _ongebundelde_tweelingen(
    administratie_id: uuid.UUID, administratie_naam: str | None = None
) -> list[ReconciliatieAfwijking]:
    """Blok 1 bundelrun 24-09 (Vastly-PDF-tweelingen 23-09): losse inkoopfactuur-PDF's in de werkvoorraad die de
    tweeling zijn van een UBL-verkoopfactuur uit dezelfde e-mail — soort `ubl_pdf_ongebundeld` (meten), actie
    "Bundelen" op de rij. Lees-only, lokaal (geen RLZ-call); één kandidaten-motor mét de nazorg-CLI
    (`app/intake/tweelingen_herstel`)."""
    from app.intake import tweelingen_herstel

    naam = administratie_naam or _administratie_naam(administratie_id)
    return list(tweelingen_herstel.afwijkingen_voor_reconciliatie(administratie_id, naam))


def reconcilieer_administratie(
    *,
    administratie_id: uuid.UUID,
    client: RlzClient | None = None,
    port: InkoopPort | None = None,
    port_factory: Callable[[uuid.UUID], InkoopPort] | None = None,
    rlz_verleden_port_factory: Callable[[uuid.UUID], InkoopPort] | None = None,
) -> ReconciliatieRapport:
    """Failsafe (b) (CLAUDE.md-taak 2.4): vergelijkt elk lokaal GEBOEKT document met de werkelijke staat in de
    boekhoud-backend van de administratie (bestaat, geboekt, bedrag, boekstuknummer, niet teruggedraaid) — vangt
    gevallen waarin de boeking lokaal als geslaagd geregistreerd staat maar in het pakket zelf iets anders is
    (een latere handmatige correctie of verwijdering, een netwerkfout ná de schrijfactie maar vóór onze
    statusovergang). `client` = test-seam/compat (een RLZ-leesclient → RLZ-port); `port` = kant-en-klare adapter.

    Odoo-administratie (besluit Peter 07-09): per document wordt de backend bepaald — `RLZ-…`-boekstuk zonder
    Odoo-koppeling = RLZ-verleden → RLZ-port op de bewaarde credential (`rlz_verleden_port_factory`, default
    `_rlz_verleden_port`; wordt pas geopend als er zo'n document is); alles anders → de Odoo-port. Lukt het openen
    van de RLZ-verleden-port niet (geen bewaarde credential), dan krijgt élk verleden-document een zichtbare
    `controle_mislukt`-bevinding."""
    geboekte_documenten = _geboekte_documenten(administratie_id)
    if not geboekte_documenten:
        # Hercontrole (22-09) loopt óók zonder geboekte documenten: een administratie met alleen open werk telt mee.
        herc = hercontroleer_open_documenten(administratie_id=administratie_id, port=port, client=client)
        return ReconciliatieRapport(
            administratie_id=administratie_id,
            aantal_gecontroleerd=0,
            afwijkingen=(*herc.afwijkingen, *_ongebundelde_tweelingen(administratie_id)),
            hercontrole_getoetst=herc.getoetst,
            hercontrole_overgeslagen=herc.overgeslagen,
        )

    eigen_port = port is None
    if port is None:
        if client is not None:
            from app.backends.rlz_inkoop import RlzInkoopPort

            port = RlzInkoopPort(client)
            eigen_port = False  # de aanroeper beheert de levensduur van zijn client
        elif port_factory is not None:
            port = port_factory(administratie_id)
        else:
            port = inkoop_port_voor(administratie_id, rlz_client_factory=lambda: _rlz_client_voor(administratie_id))
    administratie_naam = _administratie_naam(administratie_id)
    afwijkingen: list[ReconciliatieAfwijking] = []
    overgeslagen = 0
    in_odoo = 0
    in_rlz_verleden = 0
    verleden_port: InkoopPort | None = None
    verleden_fout: str | None = None
    try:
        for doc in geboekte_documenten:
            doc_port = port
            if port.backend is Backend.ODOO:
                if is_rlz_verleden(doc):
                    in_rlz_verleden += 1
                    if verleden_port is None and verleden_fout is None:
                        try:
                            verleden_port = (rlz_verleden_port_factory or _rlz_verleden_port)(administratie_id)
                        except GeenRlzCredentials as exc:
                            verleden_fout = str(exc)
                    if verleden_port is None:
                        # Zichtbaar per document, nooit stil: RLZ ís hier de bron van waarheid (bewaarplicht).
                        afwijkingen.append(
                            _controle_mislukt(
                                doc, verleden_fout or "", backend=Backend.RLZ, administratie_naam=administratie_naam
                            )
                        )
                        continue
                    doc_port = verleden_port
                else:
                    in_odoo += 1
            uit, is_overgeslagen = _toets_document(doc_port, doc, administratie_naam=administratie_naam)
            afwijkingen.extend(uit)
            overgeslagen += int(is_overgeslagen)
        # Hercontrole open documenten (22-09) op dezelfde port/client — één verbinding per administratie.
        herc = hercontroleer_open_documenten(
            administratie_id=administratie_id, port=port, administratie_naam=administratie_naam
        )
        afwijkingen.extend(herc.afwijkingen)
        afwijkingen.extend(_ongebundelde_tweelingen(administratie_id, administratie_naam))
    finally:
        if verleden_port is not None:
            verleden_port.__exit__(None, None, None)
        if eigen_port:
            port.__exit__(None, None, None)

    return ReconciliatieRapport(
        administratie_id=administratie_id,
        aantal_gecontroleerd=len(geboekte_documenten),
        afwijkingen=tuple(afwijkingen),
        aantal_overgeslagen=overgeslagen,
        backend=port.backend.value,
        aantal_in_odoo=in_odoo,
        aantal_in_rlz_verleden=in_rlz_verleden,
        hercontrole_getoetst=herc.getoetst,
        hercontrole_overgeslagen=herc.overgeslagen,
    )


def reconcilieer_alle_administraties() -> dict[uuid.UUID, ReconciliatieRapport | str]:
    """Eén administratie zonder werkende credentials laat de rest niet stoppen — zelfde patroon
    als app/sync/service.py::sync_alle_administraties."""
    with scoped_session(None) as session:
        administratie_ids = [
            row.id for row in session.scalars(select(Administratie).where(Administratie.actief.is_(True)))
        ]

    resultaten: dict[uuid.UUID, ReconciliatieRapport | str] = {}
    for administratie_id in administratie_ids:
        try:
            resultaten[administratie_id] = reconcilieer_administratie(administratie_id=administratie_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie sync_alle_administraties
            resultaten[administratie_id] = str(exc)
    return resultaten
