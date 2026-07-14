from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope
from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken, boekvoorstel, leverancier_iban, schemas, service, vragen
from app.documenten.checks import CheckRapport
from app.documenten.models import VraagStatus
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.rlz.credentials import GeenRlzCredentials

router = APIRouter(tags=["documenten"])


def _naar_check_rapport_response(rapport: CheckRapport) -> schemas.CheckRapportResponse:
    return schemas.CheckRapportResponse(
        geblokkeerd=rapport.geblokkeerd,
        resultaten=[schemas.CheckResultaatDto(naam=r.naam, ok=r.ok, melding=r.melding) for r in rapport.resultaten],
    )


def _naar_duplicaat_response(
    referentie: service.DuplicaatReferentie | None,
) -> schemas.DuplicaatReferentieResponse | None:
    if referentie is None:
        return None
    return schemas.DuplicaatReferentieResponse(
        document_id=referentie.document_id, bestandsnaam=referentie.bestandsnaam, aangemaakt_op=referentie.aangemaakt_op
    )


def _naar_regel_dto(r: boekvoorstel.BoekvoorstelRegelData) -> schemas.BoekvoorstelRegelDto:
    return schemas.BoekvoorstelRegelDto(
        ledger_id=r.ledger_id,
        taxrate_id=r.taxrate_id,
        project_id=r.project_id,
        netto_bedrag=r.netto_bedrag,
        btw_bedrag=r.btw_bedrag,
        omschrijving=r.omschrijving,
    )


def _naar_boekvoorstel_response(data: boekvoorstel.BoekvoorstelData) -> schemas.BoekvoorstelResponse:
    return schemas.BoekvoorstelResponse(
        document_id=data.document_id,
        vendor_id=data.vendor_id,
        referentie=data.referentie,
        factuurdatum=data.factuurdatum,
        totaalbedrag=data.totaalbedrag,
        rlz_boekstuknummer=data.rlz_boekstuknummer,
        opgeslagen=data.opgeslagen,
        regels=[_naar_regel_dto(r) for r in data.regels],
        regels_samenvoegen=data.regels_samenvoegen,
        samenvoegen_toegestaan=data.samenvoegen_toegestaan,
        samengevoegde_regel=_naar_regel_dto(data.samengevoegde_regel) if data.samengevoegde_regel else None,
    )


_TOEGESTANE_SUFFIXEN = {".pdf", ".xml"}


@router.post(
    "/administraties/{administratie_id}/documenten",
    response_model=schemas.DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def document_uploaden(
    administratie_id: uuid.UUID,
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentUploadResponse:
    if not bestand.filename or Path(bestand.filename).suffix.lower() not in _TOEGESTANE_SUFFIXEN:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Alleen PDF- of XML-bestanden")

    inhoud = await bestand.read()
    if not inhoud:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeg bestand")
    if len(inhoud) > settings.document_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Bestand te groot")

    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bestand.filename,
        inhoud=inhoud,
        actor_id=actor.id,
    )
    return schemas.DocumentUploadResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        mogelijk_duplicaat_van=_naar_duplicaat_response(resultaat.mogelijk_duplicaat_van),
    )


@router.get(
    "/administraties/{administratie_id}/documenten",
    response_model=schemas.DocumentListResponse,
)
def documenten_lijst(
    administratie_id: uuid.UUID,
    toon_verwijderd: bool = False,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentListResponse:
    items = service.lijst_documenten(administratie_id=administratie_id, toon_verwijderd=toon_verwijderd)
    return schemas.DocumentListResponse(
        documenten=[
            schemas.DocumentListItemResponse(
                id=item.document.id,
                bestandsnaam=item.document.bestandsnaam,
                status=item.document.status.value,
                bron=item.document.bron.value,
                mogelijk_duplicaat_van=_naar_duplicaat_response(item.duplicaat_referentie),
                toegewezen_aan=item.document.toegewezen_aan,
                aangemaakt_op=item.document.aangemaakt_op,
                laatst_gewijzigd_op=item.document.laatst_gewijzigd_op,
            )
            for item in items
        ]
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}",
    response_model=schemas.DocumentDetailResponse,
)
def document_detail(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentDetailResponse:
    try:
        detail = service.haal_document_op(administratie_id=administratie_id, document_id=document_id)
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    d = detail.document
    return schemas.DocumentDetailResponse(
        id=d.id,
        administratie_id=d.administratie_id,
        bestandsnaam=d.bestandsnaam,
        status=d.status.value,
        bron=d.bron.value,
        mogelijk_duplicaat_van=_naar_duplicaat_response(detail.duplicaat_referentie),
        toegewezen_aan=d.toegewezen_aan,
        aangemaakt_op=d.aangemaakt_op,
        laatst_gewijzigd_op=d.laatst_gewijzigd_op,
        veldvoorstel=detail.veldvoorstel,
        tijdlijn=[
            schemas.DocumentGebeurtenisResponse(
                van_status=g.van_status.value if g.van_status else None,
                naar_status=g.naar_status.value,
                actor_id=g.actor_id,
                actor_is_systeem=g.actor_id == SYSTEEM_ACTOR_ID,
                detail=g.detail,
                tijdstip=g.tijdstip,
            )
            for g in detail.gebeurtenissen
        ],
    )


@router.get("/administraties/{administratie_id}/documenten/{document_id}/bestand")
def document_bestand(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> Response:
    try:
        inhoud, bestandsnaam, content_type = service.haal_bijlage_op(
            administratie_id=administratie_id, document_id=document_id
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=inhoud,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{bestandsnaam}"'},
    )


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/verwijderen",
    response_model=schemas.DocumentActieResponse,
)
def document_verwijderen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.VerwijderenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentActieResponse:
    """Soft-delete (design-pass taak 4) — nooit een echte DELETE-route: het record en bestand
    blijven bestaan, alleen de status verandert (zie service.py::verwijder_document)."""
    try:
        nieuwe_status = service.verwijder_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id, reden=invoer.reden
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.VerwijderenNietToegestaan as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentActieResponse(document_id=document_id, status=nieuwe_status.value)


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/herstellen",
    response_model=schemas.DocumentActieResponse,
)
def document_herstellen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentActieResponse:
    """Zet een zachtgewist document terug op de status van vóór de verwijdering (design-pass
    taak 4, "toon verwijderde"-filter met herstelknop)."""
    try:
        nieuwe_status = service.herstel_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.DocumentNietVerwijderd as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentActieResponse(document_id=document_id, status=nieuwe_status.value)


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/extractie",
    response_model=schemas.DocumentActieResponse,
)
def document_opnieuw_extraheren(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentActieResponse:
    """"Opnieuw extraheren" na een transiënte AI-fout (timeout, 529) — draait de extractie
    opnieuw zonder her-upload; AVG-gate en key-check gelden onverkort (zie
    service.py::herextraheer_document). Klein-vs-groot-routing net als de upload: een groot
    document komt terug met status extractie_wachtrij en wordt door de worker afgemaakt."""
    try:
        nieuwe_status = service.herextraheer_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.HerextractieNietToegestaan as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentActieResponse(document_id=document_id, status=nieuwe_status.value)


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
    response_model=schemas.BoekvoorstelResponse,
)
def boekvoorstel_ophalen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BoekvoorstelResponse:
    try:
        data = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return _naar_boekvoorstel_response(data)


@router.put(
    "/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel",
    response_model=schemas.BoekvoorstelMetChecksResponse,
)
def boekvoorstel_opslaan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.BoekvoorstelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BoekvoorstelMetChecksResponse:
    try:
        data = boekvoorstel.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            vendor_id=invoer.vendor_id,
            referentie=invoer.referentie,
            factuurdatum=invoer.factuurdatum,
            totaalbedrag=invoer.totaalbedrag,
            regels=[
                boekvoorstel.BoekvoorstelRegelData(
                    ledger_id=r.ledger_id,
                    taxrate_id=r.taxrate_id,
                    project_id=r.project_id,
                    netto_bedrag=r.netto_bedrag,
                    btw_bedrag=r.btw_bedrag,
                    omschrijving=r.omschrijving,
                )
                for r in invoer.regels
            ],
            regels_samenvoegen=invoer.regels_samenvoegen,
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except boekvoorstel.BoekvoorstelFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # voer_checks_uit() vangt credential-/RLZ-fouten zelf af (app/documenten/boekvoorstel.py) —
    # het resultaat is altijd een CheckRapport, nooit een onafgevangen RlzApiError/GeenRlzCredentials.
    rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)

    return schemas.BoekvoorstelMetChecksResponse(
        boekvoorstel=_naar_boekvoorstel_response(data), checks=_naar_check_rapport_response(rapport)
    )


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/boekvoorstel/checks",
    response_model=schemas.CheckRapportResponse,
)
def boekvoorstel_checks_uitvoeren(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.CheckRapportResponse:
    """Herbereken de harde checks over het al opgeslagen voorstel, zonder het te wijzigen — bv.
    om na boeken_mislukt te zien of een duplicaatcheck of regeltelling inmiddels weer klopt.
    voer_checks_uit() vangt credential-/RLZ-fouten zelf af — altijd een CheckRapport terug."""
    try:
        rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except boekvoorstel.BoekvoorstelFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_check_rapport_response(rapport)


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/boeken",
    response_model=schemas.BoekenResponse,
)
def document_boeken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BoekenResponse:
    try:
        resultaat = boeken.boek_document(administratie_id=administratie_id, document_id=document_id, actor_id=actor.id)
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except boeken.OngeldigeBoekpoging as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except boeken.BoekenGeblokkeerdDoorChecks as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Boeken geblokkeerd door harde checks",
                "checks": _naar_check_rapport_response(exc.rapport).model_dump(),
            },
        ) from exc
    except boeken.BoekenUitgeschakeld as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except boeken.VolumeremBereikt as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except boeken.RlzBoekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc

    return schemas.BoekenResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        rlz_document_id=resultaat.rlz_document_id,
        rlz_boekstuknummer=resultaat.rlz_boekstuknummer,
    )


def _naar_vraag_response(data: vragen.VraagData) -> schemas.VraagResponse:
    return schemas.VraagResponse(
        id=data.id,
        document_id=data.document_id,
        document_bestandsnaam=data.document_bestandsnaam,
        document_status=data.document_status.value,
        totaalbedrag=data.totaalbedrag,
        vraag_tekst=data.vraag_tekst,
        status=data.status,
        status_voor_vraag=data.status_voor_vraag,
        gesteld_door=data.gesteld_door,
        gesteld_op=data.gesteld_op,
        toegewezen_aan=data.toegewezen_aan,
        antwoord_tekst=data.antwoord_tekst,
        beantwoord_door=data.beantwoord_door,
        beantwoord_op=data.beantwoord_op,
        ingetrokken_door=data.ingetrokken_door,
        ingetrokken_op=data.ingetrokken_op,
        ingetrokken_reden=data.ingetrokken_reden,
    )


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/vraag",
    response_model=schemas.VraagResponse,
    status_code=status.HTTP_201_CREATED,
)
def vraag_stellen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.VraagStellenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VraagResponse:
    """Vraag stellen (mockup #vraagmodal): document -> vraag_open (boeken geblokkeerd tot het
    antwoord er is), toewijzing default naar de administratie-eigenaar, overschrijfbaar binnen
    de scope van deze administratie."""
    try:
        data = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            vraag_tekst=invoer.vraag_tekst,
            toegewezen_aan=invoer.toegewezen_aan,
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except vragen.VraagTekstVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (vragen.GeenToewijzingMogelijk, vragen.ToegewezeneBuitenScope) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (vragen.ErIsAlEenOpenVraag, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_vraag_response(data)


@router.post(
    "/administraties/{administratie_id}/vragen/{vraag_id}/beantwoorden",
    response_model=schemas.VraagResponse,
)
def vraag_beantwoorden(
    administratie_id: uuid.UUID,
    vraag_id: uuid.UUID,
    invoer: schemas.VraagBeantwoordenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VraagResponse:
    """Antwoord vastleggen op de vraag-rij zelf (historie blijft) en het document terug naar de
    herkomst-status van vóór de vraag (status_voor_vraag) — boeken is daarna weer bereikbaar via
    de normale route."""
    try:
        data = vragen.beantwoord_vraag(
            administratie_id=administratie_id,
            vraag_id=vraag_id,
            actor_id=actor.id,
            antwoord_tekst=invoer.antwoord_tekst,
        )
    except (vragen.VraagNietGevonden, service.DocumentNietGevonden) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except vragen.AntwoordTekstVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (vragen.VraagNietOpen, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_vraag_response(data)


@router.post(
    "/administraties/{administratie_id}/vragen/{vraag_id}/intrekken",
    response_model=schemas.VraagResponse,
)
def vraag_intrekken(
    administratie_id: uuid.UUID,
    vraag_id: uuid.UUID,
    invoer: schemas.VraagIntrekkenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VraagResponse:
    """Open vraag intrekken (bewuste uitbreiding op de mockup, docs/BESLISSINGEN.md): de vraag
    blijft als 'ingetrokken' in de historie staan, het document gaat terug naar de herkomst-
    status en er kan daarna weer een nieuwe vraag gesteld worden. Reden optioneel."""
    try:
        data = vragen.trek_vraag_in(
            administratie_id=administratie_id, vraag_id=vraag_id, actor_id=actor.id, reden=invoer.reden
        )
    except (vragen.VraagNietGevonden, service.DocumentNietGevonden) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (vragen.VraagNietOpen, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_vraag_response(data)


@router.get(
    "/administraties/{administratie_id}/vragen",
    response_model=schemas.VraagLijstResponse,
)
def vragen_lijst(
    administratie_id: uuid.UUID,
    vraag_status: VraagStatus | None = None,
    document_id: uuid.UUID | None = None,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VraagLijstResponse:
    """Vragen van één administratie, nieuwste eerst (voedt de #vragen-view; optioneel gefilterd
    op status en/of document — het controlescherm haalt zo de open vraag van één document op)."""
    data = vragen.lijst_vragen(administratie_id=administratie_id, status=vraag_status, document_id=document_id)
    return schemas.VraagLijstResponse(vragen=[_naar_vraag_response(v) for v in data])


@router.post(
    "/administraties/{administratie_id}/crediteuren/{vendor_id}/ibans",
    response_model=schemas.IbanBevestigdResponse,
    status_code=status.HTTP_201_CREATED,
)
def leverancier_iban_bevestigen(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.IbanBevestigenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.IbanBevestigdResponse:
    """Menselijke bevestiging van een (afwijkend) factuur-IBAN — de enige route waarlangs een
    nieuw rekeningnummer na een IBAN-wissel-blokkade aan de vertrouwde set wordt toegevoegd
    (app/documenten/leverancier_iban.py). Het IBAN zit in de body, nooit in de URL."""
    try:
        genormaliseerd = leverancier_iban.bevestig_iban(
            administratie_id=administratie_id, vendor_id=vendor_id, iban=invoer.iban, actor_id=actor.id
        )
    except leverancier_iban.OngeldigIban as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return schemas.IbanBevestigdResponse(vendor_id=vendor_id, iban=genormaliseerd)
