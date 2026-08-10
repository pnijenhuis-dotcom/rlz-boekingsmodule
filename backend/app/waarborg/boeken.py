"""Waarborg-boekmotor (§2d-waarborgroute DEFINITIEF v1.11, blok E 2026-08-10): boekt het
saldo-0-memoriaal (ManualJournal) voor een herkend VASTLY-WAARBORG-bericht — zelfde
poortvolgorde als inkoop/omzet/verkoop: statuspoort + soortpoort, harde checks server-side
(mét live RLZ-duplicaatquery, fail-closed), failsafes (boeken-toggle/kill switch + volumerem),
dan pas RLZ: dagboek borgen → PUT ManualJournal (deterministisch client-GUID, idempotente
retry) → bijlage → actie 17 → registratie + GEBOEKT in één transactie. Eén RLZ-document, dus
geen half-geboekt-pad nodig. Storno = actie 19 in RLZ zelf (geen user-facing storno — zelfde
lijn als omzet: GEBOEKT is terminaal, de reconciliatie signaleert RLZ-zijdige correcties)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.boeken import (
    _KAN_BOEKPOGING_STARTEN_VANUIT,
    BoekenGeblokkeerdDoorChecks,
    BoekenUitgeschakeld,
    OngeldigeBoekpoging,
    RlzBoekingMislukt,
    VolumeremBereikt,
    _boekingen_vandaag,
    _is_boeken_toegestaan,
    _rlz_client_voor,
    _zet_boeken_mislukt,
)
from app.documenten.models import Document, DocumentSoort, DocumentStatus
from app.documenten.rlz_ids import rlz_upload_id, rlz_waarborg_memoriaal_id
from app.documenten.service import DocumentNietGevonden, _schrijf_overgang, _standaard_opslag
from app.omzet.boeken import _boek_memoriaal, _zorg_voor_memoriaal_dagboek
from app.rlz.client import RlzApiError, RlzClient
from app.waarborg.models import WaarborgBericht, WaarborgStatus
from app.waarborg.service import (
    haal_waarborg_voorstel_op,
    memoriaal_lines,
    voer_waarborg_checks_uit,
    waarborg_referentie,
)


@dataclass(frozen=True)
class WaarborgBoekResultaat:
    document_id: uuid.UUID
    status: DocumentStatus
    memoriaal_rlz_id: uuid.UUID
    rlz_boekstuknummer: str | None


def _rlz_duplicaat_hits(client: RlzClient, *, referentie: str, eigen_rlz_id: uuid.UUID) -> int | None:
    """RLZ-side duplicaatsignaal op de deterministische memoriaal-Reference (zelfde patroon als
    de omzet-memoriaal-Reference-check); None = kon niet uitgevoerd worden → fail-closed."""
    try:
        gevonden = client.find_manual_journals_by_reference(reference=referentie)
    except RlzApiError:
        return None
    eigen = str(eigen_rlz_id)
    return len([j for j in gevonden if j.get("id") != eigen])


def boek_waarborg_document(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> WaarborgBoekResultaat:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None:
            raise DocumentNietGevonden(f"Onbekend document: {document_id}")
        if document.status not in _KAN_BOEKPOGING_STARTEN_VANUIT:
            raise OngeldigeBoekpoging(f"Document staat op status {document.status.value}, kan niet boeken")
        if document.soort != DocumentSoort.WAARBORG.value:
            raise OngeldigeBoekpoging(
                f"Document heeft soort {document.soort} — deze boekactie is alleen voor waarborg-berichten"
            )
        bestandsnaam = document.bestandsnaam
        opslag_pad = document.opslag_pad

    memoriaal_rlz_id = rlz_waarborg_memoriaal_id(document_id)
    with _rlz_client_voor(administratie_id) as client:
        voorstel = haal_waarborg_voorstel_op(administratie_id=administratie_id, document_id=document_id)
        referentie = waarborg_referentie(voorstel)
        rapport = voer_waarborg_checks_uit(
            administratie_id=administratie_id,
            document_id=document_id,
            rlz_memoriaal_hits=_rlz_duplicaat_hits(client, referentie=referentie, eigen_rlz_id=memoriaal_rlz_id),
        )
        if rapport.geblokkeerd:
            raise BoekenGeblokkeerdDoorChecks(rapport)

        with scoped_session(administratie_id, actor_id=actor_id) as session:
            document = session.get(Document, document_id)
            assert document is not None
            if document.status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
                _schrijf_overgang(
                    session,
                    document=document,
                    naar=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                    actor_id=actor_id,
                    detail={"harde_checks": "doorstaan"},
                )

        with scoped_session(administratie_id) as session:
            if not _is_boeken_toegestaan(session, administratie_id=administratie_id):
                raise BoekenUitgeschakeld("Boeken staat uit voor deze administratie of via de globale kill switch")
            limiet = settings.max_boekingen_per_dag_per_administratie
            if _boekingen_vandaag(session, administratie_id=administratie_id) >= limiet:
                raise VolumeremBereikt(f"Dagelijkse limiet van {limiet} boekingen bereikt voor deze administratie")

        try:
            diary_id = _zorg_voor_memoriaal_dagboek(client=client, administratie_id=administratie_id)
            bestand = _standaard_opslag().lezen(pad=opslag_pad)
            boekstuknummer = _boek_memoriaal(
                client=client,
                rlz_id=memoriaal_rlz_id,
                diary_id=diary_id,
                lines=memoriaal_lines(voorstel),
                referentie=referentie,
                datum_iso=f"{voorstel.datum.isoformat()}T00:00:00",
                upload_id=rlz_upload_id(document_id),
                bestandsnaam=bestandsnaam,
                bestand=bestand,
            )
        except RlzApiError as exc:
            _zet_boeken_mislukt(
                administratie_id=administratie_id, document_id=document_id, actor_id=actor_id, reden=str(exc)
            )
            raise RlzBoekingMislukt(str(exc)) from exc

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        bericht = session.get(WaarborgBericht, document_id)
        assert document is not None and bericht is not None
        bericht.status = WaarborgStatus.GEBOEKT.value
        bericht.rlz_boekstuknummer = boekstuknummer
        bericht.geboekt_door = actor_id
        bericht.geboekt_op = datetime.now(UTC)
        _schrijf_overgang(
            session,
            document=document,
            naar=DocumentStatus.GEBOEKT,
            actor_id=actor_id,
            detail={
                "rlz_document_id": str(memoriaal_rlz_id),
                "rlz_boekstuknummer": boekstuknummer,
                "waarborg_richting": voorstel.richting,
                "waarborg_referentie": referentie,
            },
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="waarborg_bericht",
            record_id=document_id,
            actie="waarborg_geboekt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "bericht_id": str(voorstel.bericht_id),
                "richting": voorstel.richting,
                "bedrag": str(voorstel.bedrag),
                "rlz_boekstuknummer": boekstuknummer,
            },
            administratie_id=administratie_id,
        )

    return WaarborgBoekResultaat(
        document_id=document_id,
        status=DocumentStatus.GEBOEKT,
        memoriaal_rlz_id=memoriaal_rlz_id,
        rlz_boekstuknummer=boekstuknummer,
    )
