"""Documenten-reconciliatie: elk lokaal GEBOEKT inkoopdocument naast de werkelijke stand in de
boekhoud-backend van de administratie (A11/A12, fixrun 07-09 — backend-agnostisch via de inkoop-port).

- RLZ (`RlzInkoopPort.toets_geboekt`): GET op het herboeking-GUID van de actieve `boek_cyclus`; 404 óf een hol
  antwoord = `ontbreekt_in_rlz` (zwaarste categorie — er is niets meer om tegen te boeken; herstel = de actie
  "Opnieuw boeken" in Inzicht › Reconciliatie, `app/documenten/herboeken.py`); Status ∉ {2,3} =
  `status_niet_definitief`; bedrag/boekstuknummer-verschillen zoals voorheen.
- Odoo (`OdooInkoopPort.toets_geboekt`): account.move via onze koppeling/marker; ontbreekt = `ontbreekt_in_odoo`,
  state ≠ posted = `niet_geboekt_in_odoo`, een ONBEKENDE reversal (niet onze eigen tegenboeking) =
  `teruggedraaid_in_odoo`, bedrag/boekstuk zoals bij RLZ. Een document dat vóór de overstap in Reeleezee is
  geboekt (boekstuk `RLZ-…`) is in Odoo niet van toepassing en telt als overgeslagen (zichtbaar in de CLI-regel).
- Elke API-fout die niets over het document zegt (500/401/rate-limit) = `controle_mislukt` (les 12-08).
- Bank/omzet/doorbelasting blijven RLZ-only (Steigerbouw gebruikt ze niet) — die blokken slaan een
  Odoo-administratie zichtbaar over (`app/backends/registry.py::RLZ_ONLY_OVERGESLAGEN`).

Elke afwijking draagt `context` (leverancier, factuurnummer, boekstuk, administratienaam, bedragen, backend,
extern id/state) zodat de kantoor-UI namen kan tonen zonder extra queries (contract A↔A8)."""

from __future__ import annotations

import uuid
from collections.abc import Callable
from dataclasses import dataclass, field
from decimal import Decimal

from sqlalchemy import select

from app.backends.port import Backend, InkoopPort, ToetsMislukt, ToetsUitkomst
from app.backends.registry import inkoop_port_voor
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.models import Boekvoorstel, Document, DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

# Kleine afrondingstolerantie, zelfde als de regeltelling-check (app/documenten/checks.py) —
# geen 0-tolerantie, wél klein genoeg om een echte afwijking te vangen.
_ROND_TOLERANTIE = Decimal("0.01")

#: Soorten die "het externe document is er niet meer" betekenen — de zwaarste categorie én de enige waarop de
#: actie "Opnieuw boeken (document verdwenen)" bestaat. Per backend een eigen naam (contract A↔A8 punt 2).
ONTBREEKT_SOORTEN = frozenset({"ontbreekt_in_rlz", "ontbreekt_in_odoo"})


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
    #: documenten die in déze backend niet te toetsen zijn (RLZ-verleden van een Odoo-administratie)
    aantal_overgeslagen: int = 0
    backend: str = Backend.RLZ.value


@dataclass(frozen=True)
class _Geboekt:
    document_id: uuid.UUID
    totaalbedrag: Decimal | None
    rlz_boekstuknummer: str | None
    boek_cyclus: int
    referentie: str | None
    leverancier_naam: str | None


def _geboekte_documenten(administratie_id: uuid.UUID) -> list[_Geboekt]:
    with scoped_session(administratie_id) as session:
        rows = session.execute(
            select(
                Document.id,
                Boekvoorstel.totaalbedrag,
                Boekvoorstel.rlz_boekstuknummer,
                Boekvoorstel.boek_cyclus,
                Boekvoorstel.referentie,
                VendorCache.naam,
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
    return {
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
        ctx = _context(doc, administratie_naam=administratie_naam, uitkomst=None, backend=port.backend)
        return (
            [
                ReconciliatieAfwijking(
                    doc.document_id,
                    rlz_herboeking_id(doc.document_id, doc.boek_cyclus),
                    "controle_mislukt",
                    str(exc),
                    ctx,
                )
            ],
            False,
        )
    if not uitkomst.van_toepassing:
        return [], True
    return beoordeel_uitkomst(doc, uitkomst, backend=port.backend, administratie_naam=administratie_naam), False


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def reconcilieer_administratie(
    *,
    administratie_id: uuid.UUID,
    client: RlzClient | None = None,
    port: InkoopPort | None = None,
    port_factory: Callable[[uuid.UUID], InkoopPort] | None = None,
) -> ReconciliatieRapport:
    """Failsafe (b) (CLAUDE.md-taak 2.4): vergelijkt elk lokaal GEBOEKT document met de werkelijke staat in de
    boekhoud-backend van de administratie (bestaat, geboekt, bedrag, boekstuknummer, niet teruggedraaid) — vangt
    gevallen waarin de boeking lokaal als geslaagd geregistreerd staat maar in het pakket zelf iets anders is
    (een latere handmatige correctie of verwijdering, een netwerkfout ná de schrijfactie maar vóór onze
    statusovergang). `client` = test-seam/compat (een RLZ-leesclient → RLZ-port); `port` = kant-en-klare adapter."""
    geboekte_documenten = _geboekte_documenten(administratie_id)
    if not geboekte_documenten:
        return ReconciliatieRapport(administratie_id=administratie_id, aantal_gecontroleerd=0, afwijkingen=())

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
    try:
        for doc in geboekte_documenten:
            uit, is_overgeslagen = _toets_document(port, doc, administratie_naam=administratie_naam)
            afwijkingen.extend(uit)
            overgeslagen += int(is_overgeslagen)
    finally:
        if eigen_port:
            port.__exit__(None, None, None)

    return ReconciliatieRapport(
        administratie_id=administratie_id,
        aantal_gecontroleerd=len(geboekte_documenten),
        afwijkingen=tuple(afwijkingen),
        aantal_overgeslagen=overgeslagen,
        backend=port.backend.value,
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
