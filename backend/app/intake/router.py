from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, File, HTTPException, Response, UploadFile, status

from app.auth import service as auth_service
from app.auth.deps import CurrentGebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.documenten.models import DocumentSoort
from app.documenten.service import DocumentNietGevonden
from app.intake import nabundelen, schemas, splitsing, splitsing_uitsluiting, verwerking, verzamelbak

# De lokale vereis_kantoorrol is bij de rollen-gate-fix (2026-08-21) verhuisd naar
# app/auth/deps.py — één bron voor de kantoor-console-poort; de per-endpoint-Depends hieronder
# blijven ongewijzigd werken.
router = APIRouter(tags=["intake"])

# Documentsoort-keuze bij het toewijzen (offerte-matching 04-09): alleen deze twee soorten zijn
# vanuit de verzamelbak te kiezen — een kassarapport/verkoopfactuur/waarborg komt via een eigen
# kanaal, dus die zouden hier een stille misroutering zijn (fail-closed: onbekend = 422).
_TOEWIJSBARE_SOORTEN = {
    DocumentSoort.INKOOPFACTUUR.value: DocumentSoort.INKOOPFACTUUR,
    DocumentSoort.VERPLICHTING.value: DocumentSoort.VERPLICHTING,
}


def _documentsoort(ruw: str | None) -> DocumentSoort | None:
    if ruw is None:
        return None
    soort = _TOEWIJSBARE_SOORTEN.get(ruw)
    if soort is None:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=f"Onbekende of niet-toewijsbare documentsoort: {ruw}",
        )
    return soort


@router.post("/intake/eml", response_model=schemas.IntakeVerwerkResponse, status_code=status.HTTP_201_CREATED)
async def eml_verwerken(
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.IntakeVerwerkResponse:
    """Verwerkt een .eml-bestand (doorgestuurde/geëxporteerde mail) — hetzelfde codepad als de
    latere live postvak-fetch (app/intake/postvak.py, seam voor de GCP-uitrol)."""
    inhoud = await bestand.read()
    if not inhoud:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeg bestand")
    try:
        resultaat = verwerking.verwerk_eml(inhoud, actor_id=actor.id)
    except verwerking.GeenGeldigIntakeBericht as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    return schemas.IntakeVerwerkResponse(
        bericht_id=resultaat.bericht_id,
        al_eerder_verwerkt=resultaat.al_eerder_verwerkt,
        bijlagen=[
            schemas.IntakeBijlageResultaatDto(
                bestandsnaam=r.bestandsnaam, uitkomst=r.uitkomst, document_id=r.document_id, detail=r.detail
            )
            for r in resultaat.bijlagen
        ],
    )


@router.post("/intake/bestand", response_model=schemas.IntakeBijlageResultaatDto, status_code=status.HTTP_201_CREATED)
async def los_bestand_verwerken(
    bestand: UploadFile = File(...),
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.IntakeBijlageResultaatDto:
    """Los bestand op de werkvoorraad-sleepzone (feedbackronde 25-08 deel 3, punt 2): PDF, UBL of
    afbeelding (JPEG/PNG/HEIC) — zelfde tenaamstelling-routing als een mailbijlage; een .eml hoort
    op /intake/eml."""
    from app.config import settings

    inhoud = await bestand.read()
    if not inhoud:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeg bestand")
    if len(inhoud) > settings.document_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Bestand te groot")
    try:
        r = verwerking.verwerk_los_bestand(
            bestandsnaam=bestand.filename or "bestand",
            inhoud=inhoud,
            content_type=bestand.content_type,
            actor_id=actor.id,
        )
    except verwerking.BestandstypeNietOndersteund as exc:
        raise HTTPException(status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail=str(exc)) from exc
    return schemas.IntakeBijlageResultaatDto(
        bestandsnaam=r.bestandsnaam, uitkomst=r.uitkomst, document_id=r.document_id, detail=r.detail
    )


@router.get("/verzamelbak", response_model=schemas.VerzamelbakLijstResponse)
def verzamelbak_lijst(actor: CurrentGebruiker = Depends(vereis_kantoorrol)) -> schemas.VerzamelbakLijstResponse:
    items = verzamelbak.lijst_verzamelbak()
    return schemas.VerzamelbakLijstResponse(
        items=[
            schemas.VerzamelbakItemDto(
                document_id=item.document_id,
                bestandsnaam=item.bestandsnaam,
                soort=item.soort,
                bron=item.bron,
                afzender_hint=item.afzender_hint,
                tenaamstelling=item.tenaamstelling,
                suggestie_administratie_id=item.suggestie_administratie_id,
                suggestie_bron=item.suggestie_bron,
                reden=item.reden,
                reden_label=item.reden_label,
                aangemaakt_op=item.aangemaakt_op,
                splitsing_id=item.splitsing_id,
                beeld_bestandsnaam=item.beeld_bestandsnaam,
                samengevoegd_document_id=item.samengevoegd_document_id,
                samengevoegd_bestandsnaam=item.samengevoegd_bestandsnaam,
                intake_bericht_id=item.intake_bericht_id,
                zusje_document_id=item.zusje_document_id,
                zusje_bestandsnaam=item.zusje_bestandsnaam,
                zusje_administratie_id=item.zusje_administratie_id,
                splitsing_voorstel=[
                    schemas.SplitsSegmentDto(**segment)
                    for segment in (item.splitsing_voorstel or {}).get("facturen", [])
                ]
                if item.splitsing_voorstel
                else None,
            )
            for item in items
        ]
    )


@router.get("/verzamelbak/{document_id}/bestand")
def verzamelbak_bestand(
    document_id: uuid.UUID, vorm: str = "beeld", actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> Response:
    """Bestand van een verzamelbak-document (besluit Peter 25-08, punt D1: preview-popup per rij
    zodat je ziet voor wie het document is). Fail-closed: alleen documenten die nog écht in de
    verzamelbak staan (administratie NULL + niet_toegewezen), anders 404 — een toegewezen
    document loopt via zijn administratie-gescoopte bestand-route."""
    try:
        inhoud, bestandsnaam, content_type = verzamelbak.haal_bijlage_op(
            document_id=document_id, vorm="data" if vorm == "data" else "beeld"
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=inhoud,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{bestandsnaam}"'},
    )


@router.get("/verzamelbak/{document_id}/ubl-samenvatting", response_model=schemas.UblSamenvattingResponse)
def verzamelbak_ubl_samenvatting(
    document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.UblSamenvattingResponse:
    """Leesbare kaart voor een losse UBL zonder beeld (02-09): leverancier, afnemer, nummer, datum,
    totaal, regels — i.p.v. "geen paginabeeld"."""
    try:
        s = verzamelbak.ubl_samenvatting(document_id=document_id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.UblSamenvattingResponse(
        leverancier=s.leverancier,
        afnemer=s.afnemer,
        factuurnummer=s.factuurnummer,
        factuurdatum=s.factuurdatum,
        totaal_excl=s.totaal_excl,
        totaal_incl=s.totaal_incl,
        valuta=s.valuta,
        regelaantal=s.regelaantal,
        regels=[schemas.UblSamenvattingRegelDto(**r) for r in s.regels],
    )


@router.post("/verzamelbak/samenvoegen", response_model=schemas.SamenvoegenResponse)
def verzamelbak_samenvoegen(
    invoer: schemas.SamenvoegenInput, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.SamenvoegenResponse:
    """Handmatig samenvoegen van twee verzamelbak-rijen (toevoeging Peter 02-09): de mens kiest het
    leidende bestand, het andere wordt beeld/bron; tweede rij → status samengevoegd (nooit
    verwijderen). 409 mét code `zelfde_type` als twee UBL's/PDF's zonder bevestiging."""
    try:
        r = verzamelbak.voeg_samen(
            leidend_document_id=invoer.leidend_document_id,
            ander_document_id=invoer.ander_document_id,
            actor_id=actor.id,
            bevestig_zelfde_type=invoer.bevestig_zelfde_type,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except verzamelbak.ZelfdeTypeBevestigingNodig as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT, detail={"code": "zelfde_type", "message": str(exc)}
        ) from exc
    except (verzamelbak.DocumentNietInVerzamelbak, verzamelbak.SamenvoegenGeweigerd) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.SamenvoegenResponse(
        document_id=r.document_id,
        samengevoegd_document_id=r.samengevoegd_document_id,
        beeld_bestandsnaam=r.beeld_bestandsnaam,
        waarschuwingen=r.waarschuwingen,
    )


@router.post("/verzamelbak/{document_id}/samenvoegen-ongedaan", response_model=schemas.SamenvoegenOngedaanResponse)
def verzamelbak_samenvoegen_ongedaan(
    document_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.SamenvoegenOngedaanResponse:
    # Dubbelpaar-nabundeling (03-09): de UBL-rij kan een document in een administratie zijn — zoeken
    # uitsluitend binnen de administraties in de scope van de actor (Beheerder = alle actieve).
    administratie_kandidaten = [a.id for a in auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)]
    try:
        teruggezet = verzamelbak.maak_samenvoegen_ongedaan(
            document_id=document_id, actor_id=actor.id, administratie_kandidaten=administratie_kandidaten
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (
        verzamelbak.DocumentNietInVerzamelbak,
        verzamelbak.SamenvoegenGeweigerd,
        nabundelen.NabundelingOngedaanGeweigerd,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.SamenvoegenOngedaanResponse(document_id=document_id, teruggezet_document_id=teruggezet)


@router.post("/verzamelbak/{document_id}/toewijzen", response_model=schemas.DocumentStatusResponse)
def verzamelbak_toewijzen(
    document_id: uuid.UUID,
    invoer: schemas.ToewijzenInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.DocumentStatusResponse:
    """Idempotent (avondrun 26-08): een tweede klik op een al-toegewezen document geeft 200 mét
    `al_verwerkt=true` — geen rode fout (het paneel verwijdert de rij optimistisch en zou anders
    een geslaagde actie als fout terugmelden). Écht conflict (intussen afgehandeld als "hoort niet
    bij ons", andere administratie) blijft 409/404 mét leesbare melding."""
    try:
        r = verzamelbak.wijs_toe(
            document_id=document_id,
            administratie_id=invoer.administratie_id,
            actor_id=actor.id,
            soort=_documentsoort(invoer.soort),
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (verzamelbak.DocumentNietInVerzamelbak, verzamelbak.OnbekendeAdministratie) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentStatusResponse(
        document_id=document_id, status=r.status.value, al_verwerkt=r.al_verwerkt, melding=r.melding
    )


@router.post("/verzamelbak/{document_id}/hoort-niet-bij-ons", response_model=schemas.DocumentStatusResponse)
def verzamelbak_hoort_niet_bij_ons(
    document_id: uuid.UUID,
    invoer: schemas.HoortNietBijOnsInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.DocumentStatusResponse:
    try:
        r = verzamelbak.hoort_niet_bij_ons(document_id=document_id, actor_id=actor.id, reden=invoer.reden)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except verzamelbak.RedenVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except verzamelbak.DocumentNietInVerzamelbak as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentStatusResponse(
        document_id=document_id, status=r.status.value, al_verwerkt=r.al_verwerkt, melding=r.melding
    )


def _bulk_response(r: verzamelbak.BulkResultaat) -> schemas.BulkVerzamelbakResponse:
    return schemas.BulkVerzamelbakResponse(
        uitkomsten=[
            schemas.BulkRijUitkomstDto(
                document_id=u.document_id,
                bestandsnaam=u.bestandsnaam,
                uitkomst=u.uitkomst,
                status=u.status,
                reden=u.reden,
            )
            for u in r.uitkomsten
        ],
        verwerkt=r.verwerkt,
        al_verwerkt=r.al_verwerkt,
        fout=r.fout,
    )


@router.post("/verzamelbak/bulk-toewijzen", response_model=schemas.BulkVerzamelbakResponse)
def verzamelbak_bulk_toewijzen(
    invoer: schemas.BulkToewijzenInput, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.BulkVerzamelbakResponse:
    """Bulk-toewijzen (blok B 02-09, casus IC-stapel): orkestratie over de bestaande per-rij-route —
    uitkomst per rij (verwerkt / al_verwerkt / fout mét reden), altijd 200; een fout op één rij stopt
    de rest niet. Alleen een onbekende administratie is een 409 voor de hele aanroep."""
    try:
        r = verzamelbak.bulk_wijs_toe(
            document_ids=invoer.document_ids, administratie_id=invoer.administratie_id, actor_id=actor.id
        )
    except verzamelbak.OnbekendeAdministratie as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _bulk_response(r)


@router.post("/verzamelbak/bulk-hoort-niet-bij-ons", response_model=schemas.BulkVerzamelbakResponse)
def verzamelbak_bulk_hoort_niet_bij_ons(
    invoer: schemas.BulkHoortNietBijOnsInput, actor: CurrentGebruiker = Depends(vereis_kantoorrol)
) -> schemas.BulkVerzamelbakResponse:
    try:
        r = verzamelbak.bulk_hoort_niet_bij_ons(document_ids=invoer.document_ids, actor_id=actor.id, reden=invoer.reden)
    except verzamelbak.RedenVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return _bulk_response(r)


@router.post("/intake/splitsingen/{splitsing_id}/bevestigen", response_model=schemas.SplitsingBevestigenResponse)
def splitsing_bevestigen(
    splitsing_id: uuid.UUID,
    invoer: schemas.SplitsingBevestigenInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.SplitsingBevestigenResponse:
    try:
        resultaten = splitsing.bevestig_splitsing(
            splitsing_id=splitsing_id,
            actor_id=actor.id,
            delen=[
                splitsing.SplitsDeelInput(
                    start_pagina=d.start_pagina, eind_pagina=d.eind_pagina, tenaamstelling=d.tenaamstelling
                )
                for d in invoer.delen
            ],
        )
    except splitsing.SplitsingNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except splitsing.OngeldigeSplitsing as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except splitsing.SplitsingNietOpen as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.SplitsingBevestigenResponse(
        delen=[
            schemas.SplitsDeelResultaatDto(
                document_id=r.document_id,
                bestandsnaam=r.bestandsnaam,
                uitkomst=r.uitkomst,
                administratie_id=r.administratie_id,
            )
            for r in resultaten
        ]
    )


@router.post("/intake/splitsingen/{splitsing_id}/afwijzen", response_model=schemas.SplitsingAfwijzenResponse)
def splitsing_afwijzen(
    splitsing_id: uuid.UUID,
    invoer: schemas.SplitsingAfwijzenInput,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.SplitsingAfwijzenResponse:
    """"Is één factuur". Mét `onthoud_niet_splitsen` (blok B 04-09) legt de route óók de 'nooit
    splitsen'-regel vast voor de afzender × administratie — 422 mét leesbare reden als dat niet kan
    (geen afzender, uitgesloten kantoor-/doorstuurdomein, geen administratie gekozen); dan wordt er
    níéts afgewezen (alles-of-niets)."""
    if invoer.onthoud_niet_splitsen and invoer.administratie_id is not None:
        # Scope-toets op de gekozen administratie (Beheerder platform-breed, anderen alleen eigen scope).
        vereis_administratie_scope(invoer.administratie_id, actor)
    try:
        regel_id = splitsing.wijs_splitsing_af(
            splitsing_id=splitsing_id,
            actor_id=actor.id,
            reden=invoer.reden,
            onthoud_niet_splitsen=invoer.onthoud_niet_splitsen,
            administratie_id=invoer.administratie_id,
        )
    except splitsing.SplitsingNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except splitsing.SplitsingNietOpen as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (
        splitsing_uitsluiting.GeenAfzenderBekend,
        splitsing_uitsluiting.AfzenderDomeinUitgesloten,
        splitsing_uitsluiting.AdministratieVerplicht,
        splitsing_uitsluiting.OnbekendeAdministratie,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    return schemas.SplitsingAfwijzenResponse(splitsing_id=splitsing_id, nooit_splitsen_regel_id=regel_id)


def _uitsluiting_dto(r: splitsing_uitsluiting.RegelRij) -> schemas.SplitsingUitsluitingDto:
    return schemas.SplitsingUitsluitingDto(
        id=r.id,
        administratie_id=r.administratie_id,
        afzender_adres=r.afzender_adres,
        leverancier_naam=r.leverancier_naam,
        reden=r.reden,
        aangemaakt_op=r.aangemaakt_op,
        aangemaakt_door=r.aangemaakt_door,
        aangemaakt_door_naam=r.aangemaakt_door_naam,
    )


@router.get(
    "/administraties/{administratie_id}/intake/splitsing-uitsluitingen",
    response_model=schemas.SplitsingUitsluitingLijstResponse,
)
def splitsing_uitsluitingen_lijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SplitsingUitsluitingLijstResponse:
    """Beheer "Intake-regels" op de administratie-detailpagina (blok B 04-09): de actieve 'nooit
    splitsen'-regels van déze administratie. Aanmaken loopt uitsluitend via de afwijs-route."""
    rijen = splitsing_uitsluiting.lijst_regels(administratie_id=administratie_id, actor_id=actor.id)
    return schemas.SplitsingUitsluitingLijstResponse(regels=[_uitsluiting_dto(r) for r in rijen])


@router.delete(
    "/administraties/{administratie_id}/intake/splitsing-uitsluitingen/{regel_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def splitsing_uitsluiting_verwijderen(
    administratie_id: uuid.UUID,
    regel_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_kantoorrol),
    _scope: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    """"Verwijderen" = deactiveren mét audit — de rij blijft (nooit hard verwijderen)."""
    try:
        splitsing_uitsluiting.deactiveer_regel(administratie_id=administratie_id, regel_id=regel_id, actor_id=actor.id)
    except splitsing_uitsluiting.RegelNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
