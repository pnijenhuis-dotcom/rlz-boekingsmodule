"""Documentsoort wijzigen ná toewijzing (bulk-acties documentenlijst, Peter 16-09 — casus ProfX Journaal-kassarapporten
die als inkoopfactuur in de werkvoorraad staan).

Zelfde regels als de bestaande soort-wissel bij het toewijzen vanuit de verzamelbak (`intake/verzamelbak.py::wijs_toe`,
offerte-matching 04-09): de soort wordt gezet, het document gaat terug naar ONTVANGEN (statusmachine: alleen vanuit de
kantoorbak-statussen — dezelfde set als verplaatsen, `VERPLAATSBARE_STATUSSEN`; geboekt/ter_accordering = geweigerd mét
uitleg) en de extractie draait opnieuw via het ene pad (`start_extractie_na_toewijzing`: klein-vs-groot, AVG-gate,
kassarapport-hook). Tijdlijnregel `documentsoort_gewijzigd` "a -> b" + audit `documentsoort_gewijzigd` oud→nieuw. Zelfde
soort = idempotent no-op mét melding (geen tijdlijnregel).
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang, start_extractie_na_toewijzing
from app.documenten.storage import DocumentOpslag
from app.documenten.verplaatsen import VERPLAATSBARE_STATUSSEN, reden_niet_verplaatsbaar

#: Alleen deze soorten kiest een mens (type wijzigen ↔): inkoopfactuur, kassarapport (omzet), verplichting (offerte).
WISSELBARE_SOORTEN = frozenset({DocumentSoort.INKOOPFACTUUR, DocumentSoort.KASSARAPPORT, DocumentSoort.VERPLICHTING})


class SoortWisselNietToegestaan(Exception):
    """Status laat het niet toe (geboekt, ter accordering, extractie loopt …) of de soort is niet kiesbaar → 409."""


@dataclass(frozen=True)
class SoortWisselResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    van_soort: str
    naar_soort: str
    ongewijzigd: bool = False


def wijzig_documentsoort(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    soort: DocumentSoort,
    actor_id: uuid.UUID,
    opslag: DocumentOpslag | None = None,
    reden: str | None = None,
    automatisch=None,  # noqa: ANN001 — app.omzet.autotype.Besluit (lokaal getypeerd: houdt de importgraaf klein)
    ingang: str = "werkvoorraad",
) -> SoortWisselResultaat:
    """`reden` = mens-tekst bij de wissel (tijdlijn; "Tóch inkoopfactuur" 19-09). `automatisch` = een
    `autotype.Besluit` (parser-treffer): dan heet de tijdlijnregel "type automatisch gewijzigd: … (ProfX-journaal
    herkend)", draagt de detail-sleutel `soort_automatisch_gewijzigd` (chip "automatisch getypeerd") en is de
    audit-actie `soort_automatisch_gewijzigd` i.p.v. `documentsoort_gewijzigd` (dagteller `kassarapport_autotype`)."""
    if soort not in WISSELBARE_SOORTEN:
        raise SoortWisselNietToegestaan(
            f"Documentsoort {soort.value} is niet kiesbaar — kies inkoopfactuur, kassarapport of verplichting."
        )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.soort == soort.value:
            return SoortWisselResultaat(document_id, document.status, document.soort, soort.value, ongewijzigd=True)
        if document.status not in VERPLAATSBARE_STATUSSEN:
            reden = reden_niet_verplaatsbaar(document.status) or f"status {document.status.value}"
            uitleg = reden.replace("verplaatst", "gewijzigd").replace("Verplaatsen", "Type wijzigen")
            raise SoortWisselNietToegestaan(f"Type wijzigen kan niet vanuit deze stand — {uitleg}")
        van = document.soort
        document.soort = soort.value
        if automatisch is not None and soort == DocumentSoort.KASSARAPPORT:
            from app.omzet import autotype

            detail = {
                **autotype.tijdlijn_detail(automatisch, van=van),
                "documentsoort_gewijzigd": f"{van} -> {soort.value}",
            }
        else:
            detail = {
                "reden": (
                    f"documentsoort gewijzigd: {van} -> {soort.value} — extractie opnieuw via het {soort.value}-pad"
                    + (f" — reden: {reden.strip()}" if reden and reden.strip() else "")
                ),
                "documentsoort_gewijzigd": f"{van} -> {soort.value}",
                **({"documentsoort_reden": reden.strip()} if reden and reden.strip() else {}),
            }
        _schrijf_overgang(session, document=document, naar=DocumentStatus.ONTVANGEN, actor_id=actor_id, detail=detail)
        if automatisch is not None and soort == DocumentSoort.KASSARAPPORT:
            autotype.audit_gewijzigd(
                session,
                administratie_id=administratie_id,
                document_id=document_id,
                actor_id=actor_id,
                besluit=automatisch,
                bestandsnaam=document.bestandsnaam,
                afzender=document.afzender_hint,
                ingang=ingang,
                van=van,
            )
        else:
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="document",
                record_id=document_id,
                actie="documentsoort_gewijzigd",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"soort": van},
                nieuwe_waarde={"soort": soort.value, **({"reden": reden.strip()} if reden and reden.strip() else {})},
                administratie_id=administratie_id,
            )
    eind = start_extractie_na_toewijzing(
        administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, opslag=opslag
    )
    return SoortWisselResultaat(document_id, eind, van, soort.value)
