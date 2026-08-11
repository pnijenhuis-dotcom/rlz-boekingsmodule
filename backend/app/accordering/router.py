"""Klant-accorderingsflow — endpoints (migratie 0033, mockup #autorisatie).

Ontworpen voor twee afnemers: de kantoor-UI (instellingen, aanbieden/intrekken,
accorderingshistorie, staande regels) en de latere accordeur-PWA (wachtrij, akkoord,
afwijzen-met-reden, staande regel bij akkoord). Autorisatie: scope via de bestaande
dependencies + RLS; accordeur-besluiten worden in de service bovendien hard op de
stap-eigenaar getoetst, kantoor-acties weigeren de rol klant-accordeur."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.accordering import schemas, service
from app.auth import service as auth_service
from app.auth import voorwaarden
from app.auth.deps import CurrentGebruiker, get_current_gebruiker, require_beheerder, vereis_administratie_scope
from app.db.models import GebruikerRol
from app.documenten.service import DocumentNietGevonden

router = APIRouter(tags=["accordering"])

VOORWAARDEN_AKKOORD_VEREIST = "voorwaarden_akkoord_vereist"


def _vereis_voorwaarden_akkoord(actor: CurrentGebruiker) -> None:
    """Activeringsflow-poort (docs/avg/05 + blok 3 accordeur-PWA): een klant-accordeur zonder
    vastgelegd akkoord op de actuele voorwaarden-/privacytekst krijgt geen wachtrij en kan geen
    besluiten nemen — server-side afgedwongen, de PWA toont dan het akkoord-scherm. Kantoor-
    rollen hebben deze informatieplicht-laag niet (zij zien de wachtrij-endpoints toch al niet
    als accordeur)."""
    if actor.rol != GebruikerRol.KLANT_ACCORDEUR:
        return
    if not voorwaarden.heeft_akkoord(gebruiker_id=actor.id):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=VOORWAARDEN_AKKOORD_VEREIST)


def _vertaal(exc: service.AccorderingFout) -> HTTPException:
    if isinstance(exc, service.NietAanDeBeurt | service.KantoorActieVereist):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, service.GeenOpenAccordering):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _accordering_response(data: service.AccorderingData) -> schemas.AccorderingResponse:
    return schemas.AccorderingResponse(
        id=data.id,
        document_id=data.document_id,
        status=data.status,
        aangeboden_op=data.aangeboden_op,
        afgerond_op=data.afgerond_op,
        stappen=[
            schemas.StapResponse(
                volgnummer=s.volgnummer,
                accordeur_gebruiker_id=s.accordeur_gebruiker_id,
                accordeur_naam=s.accordeur_naam,
                bedrag_drempel=s.bedrag_drempel,
                vereist=s.vereist,
                besluit=s.besluit,
                besluit_bron=s.besluit_bron,
                reden=s.reden,
                besloten_op=s.besloten_op,
                aan_de_beurt=s.aan_de_beurt,
            )
            for s in data.stappen
        ],
    )


def _besluit_response(resultaat: service.AkkoordResultaat) -> schemas.BesluitResponse:
    return schemas.BesluitResponse(
        accordering=_accordering_response(resultaat.accordering),
        alles_akkoord=resultaat.alles_akkoord,
        geboekt=resultaat.geboekt,
        boek_fout=resultaat.boek_fout,
        staande_regel_id=resultaat.staande_regel_id,
    )


@router.get(
    "/administraties/{administratie_id}/accordering/instellingen",
    response_model=schemas.InstellingenResponse,
)
def instellingen_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.InstellingenResponse:
    """Scope-check, geen Beheerder-only: het controlescherm moet weten of de boekknop
    "Ter accordering" hoort te zijn."""
    ingeschakeld, lagen, namen = service.instellingen_ophalen(administratie_id=administratie_id)
    return schemas.InstellingenResponse(
        ingeschakeld=ingeschakeld,
        lagen=[
            schemas.LaagDto(
                volgnummer=laag.volgnummer,
                accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                accordeur_naam=namen.get(laag.accordeur_gebruiker_id),
                bedrag_drempel=laag.bedrag_drempel,
            )
            for laag in lagen
        ],
    )


@router.put(
    "/administraties/{administratie_id}/accordering/instellingen",
    response_model=schemas.InstellingenResponse,
)
def instellingen_opslaan(
    administratie_id: uuid.UUID,
    invoer: schemas.InstellingenInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.InstellingenResponse:
    """Beheerder-only, net als de andere administratie-toggles (rol- en schemabeheer =
    Beheerder, CLAUDE.md-autorisatie)."""
    try:
        service.instellingen_opslaan(
            administratie_id=administratie_id,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
            ingeschakeld=invoer.ingeschakeld,
            lagen=[
                service.LaagInput(
                    volgnummer=laag.volgnummer,
                    accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
                    bedrag_drempel=laag.bedrag_drempel,
                )
                for laag in invoer.lagen
            ],
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return instellingen_ophalen(administratie_id, actor)


@router.get(
    "/administraties/{administratie_id}/accordering/kandidaten",
    response_model=schemas.KandidatenResponse,
)
def kandidaten(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.KandidatenResponse:
    """Keuzelijst voor het lagen-beheer: actieve klant-accordeurs met scope op deze
    administratie. Beheerder-only, net als het schema-beheer zelf."""
    return schemas.KandidatenResponse(
        kandidaten=[
            schemas.KandidaatDto(id=k.id, naam=k.naam)
            for k in service.accordeur_kandidaten(administratie_id=administratie_id)
        ]
    )


@router.post(
    "/administraties/{administratie_id}/accordering/documenten/{document_id}/aanbieden",
    response_model=schemas.BesluitResponse,
)
def aanbieden(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BesluitResponse:
    """De "Ter accordering"-knop (kantoor). Staande goedkeuringen worden direct toegepast —
    zijn alle lagen daarmee akkoord, dan boekt de motor meteen (met alle harde checks)."""
    try:
        resultaat = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.ChecksNietGroen as exc:
        # Zelfde vorm als de boek-route (409 + CheckRapport in detail.checks) zodat het
        # controlescherm de check-rijen gewoon kan tonen.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Ter accordering geblokkeerd door harde checks",
                "checks": {
                    "geblokkeerd": exc.rapport.geblokkeerd,
                    "resultaten": [
                        {"naam": r.naam, "ok": r.ok, "melding": r.melding} for r in exc.rapport.resultaten
                    ],
                },
            },
        ) from exc
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return _besluit_response(resultaat)


@router.post(
    "/administraties/{administratie_id}/accordering/documenten/{document_id}/akkoord",
    response_model=schemas.BesluitResponse,
)
def akkoord(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.AkkoordInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BesluitResponse:
    """Akkoord van de accordeur die aan de beurt is (PWA-endpoint). Optioneel mét staande
    goedkeuring voor toekomstige facturen van deze leverancier bij exact dit bedrag."""
    _vereis_voorwaarden_akkoord(actor)
    try:
        resultaat = service.geef_akkoord(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            staande_regel_aanmaken=invoer.staande_regel_aanmaken,
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return _besluit_response(resultaat)


@router.post(
    "/administraties/{administratie_id}/accordering/documenten/{document_id}/afwijzen",
    response_model=schemas.AccorderingResponse,
)
def afwijzen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.AfwijsInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AccorderingResponse:
    """Afwijzen door de accordeur — verplichte reden (popup-principe); komt met reden terug in
    de werkvoorraad via het bestaande afwijzen-patroon."""
    _vereis_voorwaarden_akkoord(actor)
    try:
        data = service.wijs_af(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id, reden=invoer.reden
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return _accordering_response(data)


@router.post(
    "/administraties/{administratie_id}/accordering/documenten/{document_id}/intrekken",
    response_model=schemas.AccorderingResponse,
)
def intrekken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AccorderingResponse:
    try:
        data = service.trek_accordering_in(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return _accordering_response(data)


@router.get(
    "/administraties/{administratie_id}/accordering/documenten/{document_id}",
    response_model=schemas.AccorderingResponse | None,
)
def accordering_van_document(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AccorderingResponse | None:
    """Accorderingshistorie op het document (controlescherm-sectie)."""
    data = service.accordering_van_document(administratie_id=administratie_id, document_id=document_id)
    return _accordering_response(data) if data is not None else None


@router.get("/accordering/wachtrij", response_model=schemas.WachtrijResponse)
def wachtrij(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> schemas.WachtrijResponse:
    """De accordeer-wachtrij van de ingelogde gebruiker (PWA-endpoint, scope-aanscherping
    2026-08-08: uitsluitend de wachtrij). Administraties komen uit de eigen scope-bron —
    geen scope = geen data, RLS dwingt dat op DB-niveau nogmaals af."""
    _vereis_voorwaarden_akkoord(actor)
    administraties = auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    items = service.wachtrij_voor_accordeur(
        actor_id=actor.id, administratie_ids=[a.id for a in administraties]
    )
    return schemas.WachtrijResponse(
        items=[
            schemas.WachtrijItemResponse(
                document_id=item.document_id,
                administratie_id=item.administratie_id,
                administratie_naam=item.administratie_naam,
                leverancier_naam=item.leverancier_naam,
                referentie=item.referentie,
                factuurdatum=item.factuurdatum,
                totaalbedrag=item.totaalbedrag,
                aangeboden_op=item.aangeboden_op,
                laag_volgnummer=item.laag_volgnummer,
                boeking_omschrijving=item.boeking_omschrijving,
                staande_regel_kandidaat=item.staande_regel_kandidaat,
            )
            for item in items
        ]
    )


@router.get(
    "/administraties/{administratie_id}/accordering/staande-regels",
    response_model=schemas.StaandeRegelsResponse,
)
def staande_regels(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.StaandeRegelsResponse:
    regels, namen = service.staande_regels(administratie_id=administratie_id)
    return schemas.StaandeRegelsResponse(
        regels=[
            schemas.StaandeRegelResponse(
                id=r.id,
                accordeur_gebruiker_id=r.accordeur_gebruiker_id,
                accordeur_naam=namen.get(r.accordeur_gebruiker_id),
                vendor_id=r.vendor_id,
                leverancier_naam=r.leverancier_naam,
                bedrag=r.bedrag,
                actief=r.actief,
                aangemaakt_op=r.aangemaakt_op,
                ingetrokken_op=r.ingetrokken_op,
            )
            for r in regels
        ]
    )


@router.post(
    "/administraties/{administratie_id}/accordering/staande-regels/{regel_id}/intrekken",
    status_code=status.HTTP_204_NO_CONTENT,
)
def staande_regel_intrekken(
    administratie_id: uuid.UUID,
    regel_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    """Intrekbaar door kantoor én door de accordeur zelf (besluit 2026-08-08)."""
    try:
        service.trek_staande_regel_in(administratie_id=administratie_id, regel_id=regel_id, actor_id=actor.id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
