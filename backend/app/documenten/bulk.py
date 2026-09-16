"""Bulk-acties op de klant-documentenlijst (Peter 16-09: "nu moet dat 1 voor 1") — verwijderen, afwijzen, type
wijzigen, verplaatsen over N geselecteerde documenten.

Model = het bulk-afvoer-patroon (B2 07-09) en het verzamelbak-bulk (blok B 02-09): N × de BESTAANDE per-document-route,
één transactie per document (een fout op één rij stopt de rest niet), uitkomst per rij ('gelukt' / 'overgeslagen' mét
reden / 'geen_toegang') — nooit stil. Poorten blijven die van de enkelvoudige routes (geboekt/ter_accordering = het
409-pad → "overgeslagen — geboekt" enz.); scope per document server-side + RLS: een id buiten de scope of de
administratie is voor de actor onzichtbaar → 'geen_toegang'. Eén reden voor de hele selectie (verwijderen/afwijzen).
Er wordt niets in RLZ/Odoo geraakt (KP3): verwijderen = module-status `verwijderd` (herstelbaar), afwijzen = status
afgewezen mét reden, type wijzigen = extractie opnieuw via het juiste pad, verplaatsen = de bestaande verhuisroute
(extractie opnieuw in het doel).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Literal

from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten import afwijzen, service, verplaatsen, vragen
from app.documenten.models import Document, DocumentSoort
from app.documenten.soort import SoortWisselNietToegestaan, wijzig_documentsoort
from app.documenten.statusmachine import OngeldigeStatusovergang

BulkActie = Literal["verwijderen", "afwijzen", "soort_wijzigen", "verplaatsen"]
ACTIES: tuple[str, ...] = ("verwijderen", "afwijzen", "soort_wijzigen", "verplaatsen")
MAX_PER_AANROEP = 500


@dataclass(frozen=True)
class BulkRij:
    document_id: uuid.UUID
    bestandsnaam: str | None
    uitkomst: str  # gelukt | overgeslagen | geen_toegang
    reden: str | None = None
    status: str | None = None


@dataclass(frozen=True)
class BulkUitkomst:
    actie: str
    rijen: list[BulkRij] = field(default_factory=list)

    @property
    def gelukt(self) -> int:
        return sum(1 for r in self.rijen if r.uitkomst == "gelukt")

    @property
    def overgeslagen(self) -> int:
        return sum(1 for r in self.rijen if r.uitkomst == "overgeslagen")

    @property
    def geen_toegang(self) -> int:
        return sum(1 for r in self.rijen if r.uitkomst == "geen_toegang")


def _bestandsnaam(administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID) -> str | None | bool:
    """Naam voor de uitkomstrij; False = het document is voor deze actor onzichtbaar (RLS/scope/andere
    administratie)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.administratie_id != administratie_id:
            return False
        return document.bestandsnaam


def voer_bulk_uit(  # noqa: C901, PLR0912 — één orkestratiefunctie, vier acties, per rij vertaald
    *,
    administratie_id: uuid.UUID,
    document_ids: list[uuid.UUID],
    actie: BulkActie,
    actor_id: uuid.UUID,
    actor_rol: GebruikerRol,
    reden: str | None = None,
    soort: DocumentSoort | None = None,
    doel_administratie_id: uuid.UUID | None = None,
    onthoud_tenaamstelling: bool = False,
) -> BulkUitkomst:
    if actie not in ACTIES:
        raise ValueError(f"Onbekende bulk-actie: {actie}")
    uitkomst = BulkUitkomst(actie=actie)
    gezien: set[uuid.UUID] = set()
    for document_id in document_ids[:MAX_PER_AANROEP]:
        if document_id in gezien:
            continue
        gezien.add(document_id)
        naam = _bestandsnaam(administratie_id, document_id, actor_id)
        if naam is False:
            uitkomst.rijen.append(
                BulkRij(document_id, None, "geen_toegang", "overgeslagen — geen toegang (buiten je scope of onbekend)")
            )
            continue
        try:
            if actie == "verwijderen":
                status = service.verwijder_document(
                    administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=reden
                )
                uitkomst.rijen.append(BulkRij(document_id, naam, "gelukt", None, status.value))
            elif actie == "afwijzen":
                data = afwijzen.wijs_af(
                    administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=reden or ""
                )
                uitkomst.rijen.append(BulkRij(document_id, naam, "gelukt", None, data.document_status.value))
            elif actie == "soort_wijzigen":
                assert soort is not None
                r = wijzig_documentsoort(
                    administratie_id=administratie_id, document_id=document_id, soort=soort, actor_id=actor_id
                )
                if r.ongewijzigd:
                    uitkomst.rijen.append(
                        BulkRij(
                            document_id, naam, "overgeslagen", f"overgeslagen — is al een {soort.value}", r.status.value
                        )
                    )
                else:
                    uitkomst.rijen.append(BulkRij(document_id, naam, "gelukt", None, r.status.value))
            else:
                assert doel_administratie_id is not None
                v = verplaatsen.verplaats_document(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    doel_administratie_id=doel_administratie_id,
                    actor_id=actor_id,
                    actor_rol=actor_rol,
                    onthoud_tenaamstelling=onthoud_tenaamstelling,
                )
                uitkomst.rijen.append(BulkRij(document_id, naam, "gelukt", None, v.status.value))
        except service.DocumentNietGevonden:
            uitkomst.rijen.append(BulkRij(document_id, naam, "geen_toegang", "overgeslagen — geen toegang of onbekend"))
        except verplaatsen.GeenScopeOpDoel as exc:
            uitkomst.rijen.append(BulkRij(document_id, naam, "geen_toegang", f"overgeslagen — {exc}"))
        except service.VerwijderenNietToegestaan as exc:
            uitkomst.rijen.append(BulkRij(document_id, naam, "overgeslagen", _kort(exc, "geboekt")))
        except (
            OngeldigeStatusovergang,
            SoortWisselNietToegestaan,
            verplaatsen.VerplaatsenNietToegestaan,
            verplaatsen.OnbekendeDoelAdministratie,
            afwijzen.RedenVerplicht,
            vragen.ToegewezeneBuitenScope,
        ) as exc:
            uitkomst.rijen.append(BulkRij(document_id, naam, "overgeslagen", _kort(exc)))
    return uitkomst


def _kort(exc: Exception, hint: str | None = None) -> str:
    tekst = str(exc) or exc.__class__.__name__
    if hint and hint in tekst.lower():
        return f"overgeslagen — {hint}: {tekst}"
    return f"overgeslagen — {tekst}"
