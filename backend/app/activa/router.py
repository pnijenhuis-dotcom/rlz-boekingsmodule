"""API activa fase 1 (CONTRACT A): kaart "Activum aanmaken?" op het controlescherm + Instellingen › Activa.

Router-breed `vereis_kantoorrol` (rollen-gate-lijn 21-08; fail-closed sweep tests/security/test_rol_endpoint_gates.py);
per administratie-route `vereis_administratie_scope`; de instelling-PUT is Beheerder-only (`require_beheerder`).
"""

from __future__ import annotations

import uuid
from decimal import Decimal

from fastapi import APIRouter, Depends, HTTPException, status

from app.activa import categorie as cat
from app.activa import instelling as instelling_service
from app.activa import schemas, service
from app.activa.voorstel import VoorstelData
from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten.service import DocumentNietGevonden

router = APIRouter(tags=["activa"], dependencies=[Depends(vereis_kantoorrol)])


def _geld(bedrag: Decimal) -> str:
    return str(Decimal(bedrag).quantize(Decimal("0.01")))


def _voorstel_dto(data: VoorstelData) -> schemas.ActivaVoorstelDto:
    return schemas.ActivaVoorstelDto(
        administratie_id=data.administratie_id,
        document_id=data.document_id,
        document_geboekt=data.document_geboekt,
        grens=_geld(data.stand.effectieve_grens),
        grens_bron=data.stand.grens_bron,
        automatisch_ingeschakeld=data.stand.automatisch_aanmaken_ingeschakeld,
        register_leesbaar=data.stand.register_leesbaar,
        register_fout=data.stand.register_fout,
        kandidaten=[
            schemas.KandidaatDto(
                regel_volgnummer=k.regel_volgnummer,
                ledger_id=k.ledger_id,
                ledger_code=k.ledger_code,
                ledger_naam=k.ledger_naam,
                omschrijving=k.omschrijving,
                aanschafwaarde=_geld(k.aanschafwaarde),
                aanschafdatum=k.aanschafdatum,
                categorie=k.categorie,
                categorie_label=k.categorie_label,
                termijn_maanden=k.termijn_maanden,
                methode_naam=k.methode_naam,
                restwaarde=_geld(k.restwaarde),
                afschrijving_ledger_id=k.afschrijving_ledger_id,
                afschrijving_ledger_code=k.afschrijving_ledger_code,
                signalen=[schemas.SignaalDto(code=s.code, tekst=s.tekst) for s in k.signalen],
                koppeling=(
                    schemas.KoppelingDto(
                        id=k.koppeling.id,
                        status=k.koppeling.status,
                        herkomst=k.koppeling.herkomst,
                        rlz_fixed_asset_id=k.koppeling.rlz_fixed_asset_id,
                        rlz_receipt_number=k.koppeling.rlz_receipt_number,
                        reden=k.koppeling.reden,
                        door=k.koppeling.door,
                        gewijzigd_op=k.koppeling.gewijzigd_op,
                    )
                    if k.koppeling is not None
                    else None
                ),
            )
            for k in data.kandidaten
        ],
        onder_grens=[
            schemas.OnderGrensDto(
                regel_volgnummer=o.regel_volgnummer,
                ledger_code=o.ledger_code,
                ledger_naam=o.ledger_naam,
                netto=_geld(o.netto),
                tekst=o.tekst,
            )
            for o in data.onder_grens
        ],
        afschrijving_ledger_opties=[
            schemas.LedgerOptieDto(ledger_id=r.ledger_id, code=r.code, naam=r.naam)
            for r in data.afschrijving_ledger_opties
        ],
    )


def _vertaal(exc: service.ActivaFout) -> HTTPException:
    if isinstance(exc, (service.GeenKandidaat, service.OngeldigeInvoer)):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/activa-voorstel",
    response_model=schemas.ActivaVoorstelDto,
)
def activa_voorstel_ophalen(
    administratie_id: uuid.UUID, document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.ActivaVoorstelDto:
    """Kandidaten + onder-grens-signalen voor het controlescherm (geen RLZ-call). Leeg = kaart tonen we niet."""
    try:
        return _voorstel_dto(service.haal_voorstel_op(administratie_id=administratie_id, document_id=document_id))
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/activa-voorstel/{regel_volgnummer}/aanmaken",
    response_model=schemas.ActivaVoorstelDto,
)
def activum_aanmaken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    regel_volgnummer: int,
    invoer: schemas.AanmakenInput | None = None,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ActivaVoorstelDto:
    """Niet geboekt → `gepland` (aanmaken ná boeken); geboekt → direct in RLZ. Geen kandidaat 422, al aangemaakt 409."""
    invoer = invoer or schemas.AanmakenInput()
    try:
        data = service.plan_of_maak_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            regel_volgnummer=regel_volgnummer,
            actor_id=actor.id,
            afschrijving_ledger_id=invoer.afschrijving_ledger_id,
            termijn_maanden=invoer.termijn_maanden,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.ActivaFout as exc:
        raise _vertaal(exc) from exc
    return _voorstel_dto(data)


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/activa-voorstel/{regel_volgnummer}/overslaan",
    response_model=schemas.ActivaVoorstelDto,
)
def activum_overslaan(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    regel_volgnummer: int,
    invoer: schemas.OverslaanInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.ActivaVoorstelDto:
    """ "Niet activeren…" mét verplichte reden (leeg = 422); `aangemaakt` = 409."""
    try:
        data = service.sla_over(
            administratie_id=administratie_id,
            document_id=document_id,
            regel_volgnummer=regel_volgnummer,
            actor_id=actor.id,
            reden=invoer.reden,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.ActivaFout as exc:
        raise _vertaal(exc) from exc
    return _voorstel_dto(data)


# --- Instellingen › Activa -------------------------------------------------------------------------------------------


def _instelling_dto(session, administratie_id: uuid.UUID) -> schemas.ActivaInstellingDto:  # noqa: ANN001
    stand = instelling_service.lees_stand(session, administratie_id)
    tellers = service.tellers(session, administratie_id)
    return schemas.ActivaInstellingDto(
        automatisch_aanmaken_ingeschakeld=stand.automatisch_aanmaken_ingeschakeld,
        activeringsgrens=_geld(stand.activeringsgrens),
        grens_rlz=_geld(stand.grens_rlz) if stand.grens_rlz is not None else None,
        grens_rlz_gelezen_op=stand.grens_rlz_gelezen_op,
        effectieve_grens=_geld(stand.effectieve_grens),
        grens_bron=stand.grens_bron,
        termijnen=dict(stand.termijnen),
        afschrijving_ledgers=dict(stand.afschrijving_ledgers),
        register_leesbaar=stand.register_leesbaar,
        register_geprobeerd_op=stand.register_geprobeerd_op,
        register_fout=stand.register_fout,
        categorieen=[
            schemas.CategorieDto(code=c.code, label=c.label, default_maanden=c.default_maanden) for c in cat.CATEGORIEEN
        ],
        mva_rekeningen=[
            schemas.LedgerOptieDto(ledger_id=r.ledger_id, code=r.code, naam=r.naam)
            for r in instelling_service.mva_rekeningen(session, administratie_id)
        ],
        afschrijving_ledger_opties=[
            schemas.LedgerOptieDto(ledger_id=r.ledger_id, code=r.code, naam=r.naam)
            for r in instelling_service.afschrijving_ledger_opties(session, administratie_id)
        ],
        koppelingen_tellers=schemas.KoppelingTellersDto(**tellers),
    )


def _vereis_administratie(session, administratie_id: uuid.UUID) -> None:  # noqa: ANN001
    if session.get(Administratie, administratie_id) is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=f"Onbekende administratie {administratie_id}")


@router.get("/administraties/{administratie_id}/activa-instelling", response_model=schemas.ActivaInstellingDto)
def activa_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.ActivaInstellingDto:
    with scoped_session(administratie_id) as session:
        _vereis_administratie(session, administratie_id)
        return _instelling_dto(session, administratie_id)


@router.put("/administraties/{administratie_id}/activa-instelling", response_model=schemas.ActivaInstellingDto)
def activa_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.ActivaInstellingInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.ActivaInstellingDto:
    """Beheerder: opt-in, grens, termijnen en afschrijvingsrekeningen per categorie — upsert + audit oud→nieuw;
    validatie 422 (grens ≥ 0, maanden 12..600 veelvoud van 12, bekende categorie en rekening)."""
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        _vereis_administratie(session, administratie_id)
        try:
            instelling_service.zet(
                session,
                administratie_id=administratie_id,
                actor_id=actor.id,
                automatisch_aanmaken_ingeschakeld=invoer.automatisch_aanmaken_ingeschakeld,
                activeringsgrens=invoer.activeringsgrens,
                termijnen=invoer.termijnen,
                afschrijving_ledgers={
                    k: (str(v) if v is not None else None) for k, v in invoer.afschrijving_ledgers.items()
                },
            )
        except instelling_service.OngeldigeInstelling as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc
        return _instelling_dto(session, administratie_id)
