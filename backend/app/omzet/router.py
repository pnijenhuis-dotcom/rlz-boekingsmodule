from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.documenten.boeken import (
    BoekenGeblokkeerdDoorChecks,
    BoekenUitgeschakeld,
    OngeldigeBoekpoging,
    RlzBoekingMislukt,
    VolumeremBereikt,
)
from app.documenten.checks import CheckRapport
from app.documenten.schemas import CheckRapportResponse, CheckResultaatDto
from app.documenten.service import DocumentNietGevonden
from app.omzet import boeken, mapping, schemas, voorstel
from app.omzet.boeken import HalfGeboekt
from app.rlz.credentials import GeenRlzCredentials

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["omzet"], dependencies=[Depends(vereis_kantoorrol)])


def _naar_check_rapport(rapport: CheckRapport) -> CheckRapportResponse:
    return CheckRapportResponse(
        geblokkeerd=rapport.geblokkeerd,
        resultaten=[CheckResultaatDto(naam=r.naam, ok=r.ok, melding=r.melding) for r in rapport.resultaten],
    )


def _naar_voorstel_response(data: voorstel.OmzetVoorstelData) -> schemas.OmzetVoorstelResponse:
    return schemas.OmzetVoorstelResponse(
        document_id=data.document_id,
        periode_start=data.periode_start,
        periode_eind=data.periode_eind,
        rapport_totaal_omzet=data.rapport_totaal_omzet,
        rapport_totaal_kostprijs=data.rapport_totaal_kostprijs,
        marge_pct=data.marge_pct,
        regels=[
            schemas.OmzetRegelDto(
                categorie=r.categorie,
                categorie_sleutel=r.categorie_sleutel,
                omzet_bedrag=r.omzet_bedrag,
                kostprijs_bedrag=r.kostprijs_bedrag,
                omzet_ledger_id=r.omzet_ledger_id,
                taxrate_id=r.taxrate_id,
                kostprijs_ledger_id=r.kostprijs_ledger_id,
                herkomst=r.herkomst,
            )
            for r in data.regels
        ],
        voorraad_ledger_id=data.voorraad_ledger_id,
        opgeslagen=data.opgeslagen,
        rapport_titel=data.rapport_titel,
        entiteit_naam=data.entiteit_naam,
    )


@router.get(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/voorstel",
    response_model=schemas.OmzetVoorstelResponse,
)
def omzet_voorstel_ophalen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetVoorstelResponse:
    try:
        data = voorstel.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except voorstel.GeenKassarapport as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_voorstel_response(data)


@router.put(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/voorstel",
    response_model=schemas.OmzetVoorstelResponse,
)
def omzet_voorstel_opslaan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.OmzetVoorstelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetVoorstelResponse:
    try:
        data = voorstel.sla_omzet_voorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            periode_start=invoer.periode_start,
            periode_eind=invoer.periode_eind,
            rapport_totaal_omzet=invoer.rapport_totaal_omzet,
            rapport_totaal_kostprijs=invoer.rapport_totaal_kostprijs,
            regels=[
                voorstel.OmzetRegelInput(
                    categorie=r.categorie,
                    omzet_bedrag=r.omzet_bedrag,
                    kostprijs_bedrag=r.kostprijs_bedrag,
                    omzet_ledger_id=r.omzet_ledger_id,
                    taxrate_id=r.taxrate_id,
                    kostprijs_ledger_id=r.kostprijs_ledger_id,
                )
                for r in invoer.regels
            ],
            voorraad_ledger_id=invoer.voorraad_ledger_id,
            mapping_onthouden=invoer.mapping_onthouden,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except voorstel.GeenKassarapport as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except voorstel.OmzetVoorstelFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_voorstel_response(data)


@router.post(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/checks",
    response_model=schemas.OmzetVoorstelMetChecksResponse,
)
def omzet_checks_uitvoeren(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetVoorstelMetChecksResponse:
    try:
        rapport = voorstel.voer_omzet_checks_uit(administratie_id=administratie_id, document_id=document_id)
        data = voorstel.haal_omzet_voorstel_op(administratie_id=administratie_id, document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (voorstel.GeenKassarapport, voorstel.OmzetVoorstelFout) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.OmzetVoorstelMetChecksResponse(
        voorstel=_naar_voorstel_response(data), checks=_naar_check_rapport(rapport)
    )


@router.post(
    "/administraties/{administratie_id}/omzet/documenten/{document_id}/boeken",
    response_model=schemas.OmzetBoekenResponse,
)
def omzet_boeken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetBoekenResponse:
    try:
        resultaat = boeken.boek_omzet_document(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except BoekenGeblokkeerdDoorChecks as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "melding": "Boeken geblokkeerd door harde checks",
                "checks": _naar_check_rapport(exc.rapport).model_dump(mode="json"),
            },
        ) from exc
    except (OngeldigeBoekpoging, BoekenUitgeschakeld, VolumeremBereikt) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except HalfGeboekt as exc:
        # 502: de fout ligt aan de RLZ-kant én er is een halve boeking die aandacht vraagt —
        # de melding zelf legt het herstelpad uit (omzet-reconciliatie).
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except RlzBoekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.OmzetBoekenResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        verkoop_rlz_id=resultaat.verkoop_rlz_id,
        verkoop_referentie=resultaat.verkoop_referentie,
        verkoop_boekstuknummer=resultaat.verkoop_boekstuknummer,
        memoriaal_rlz_id=resultaat.memoriaal_rlz_id,
        memoriaal_boekstuknummer=resultaat.memoriaal_boekstuknummer,
    )


@router.get(
    "/administraties/{administratie_id}/omzet/mappingen",
    response_model=schemas.OmzetMappingLijstResponse,
)
def omzet_mappingen_lijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.OmzetMappingLijstResponse:
    return schemas.OmzetMappingLijstResponse(
        mappingen=[
            schemas.OmzetMappingDto(
                categorie_sleutel=m.categorie_sleutel,
                weergave_naam=m.weergave_naam,
                omzet_ledger_id=m.omzet_ledger_id,
                taxrate_id=m.taxrate_id,
                kostprijs_ledger_id=m.kostprijs_ledger_id,
            )
            for m in mapping.lijst_mappings(administratie_id=administratie_id)
        ]
    )
