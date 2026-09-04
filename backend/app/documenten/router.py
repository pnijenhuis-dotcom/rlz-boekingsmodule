from __future__ import annotations

import uuid
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Response, UploadFile, status

from app.auth import service as auth_service
from app.auth.deps import (
    CurrentGebruiker,
    get_current_gebruiker,
    require_beheerder,
    vereis_administratie_scope,
    vereis_kantoor_of_accordeur,
    vereis_kantoorrol,
)
from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import (
    afwijzen,
    boeken,
    boekvoorstel,
    duplicaat_afvoer,
    iban_accordering,
    leverancier_iban,
    schemas,
    service,
    tegenboeken,
    verplaatsen,
    vragen,
)
from app.documenten.afbeelding import AFBEELDING_SUFFIXEN, AfbeeldingOnbruikbaar, afbeelding_naar_pdf, is_afbeelding
from app.documenten.checks import CheckRapport
from app.documenten.mime import content_type_voor
from app.documenten.models import DocumentSoort, IbanAccorderingStatus, IbanSoort, VraagStatus
from app.documenten.statusmachine import OngeldigeStatusovergang
from app.materiaal.match import MateriaalAfwijkingBevestigingVereist, lees_materiaalmatch
from app.rlz.credentials import GeenRlzCredentials

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): de documenten-endpoints zijn
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope. Eén uitzondering leeft in `bestand_router` hieronder: het
# PDF-bestand-endpoint, dat de accordeur-PWA zelf nodig heeft (factuurbeeld centraal).
router = APIRouter(tags=["documenten"], dependencies=[Depends(vereis_kantoorrol)])

# Aparte router zonder de kantoor-poort: alleen /bestand, met de eigen kantoor-óf-accordeur-poort
# (veldrollen 403 — hun projectdocument-leesroute is /uren/projectdocumenten, vereis_veldrol).
bestand_router = APIRouter(tags=["documenten"])


def _naar_check_rapport_response(rapport: CheckRapport) -> schemas.CheckRapportResponse:
    return schemas.CheckRapportResponse(
        geblokkeerd=rapport.geblokkeerd,
        resultaten=[
            schemas.CheckResultaatDto(naam=r.naam, ok=r.ok, melding=r.melding, signaal=r.signaal)
            for r in rapport.resultaten
        ],
    )


def _naar_afwijzing_info(data: afwijzen.AfwijzingData | None) -> schemas.AfwijzingInfoDto | None:
    if data is None:
        return None
    return schemas.AfwijzingInfoDto(
        id=data.id,
        reden=data.reden,
        afgewezen_door=data.afgewezen_door,
        afgewezen_op=data.afgewezen_op,
        toegewezen_aan=data.toegewezen_aan,
        status_voor_afwijzing=data.status_voor_afwijzing,
        duplicaat_van_document_id=data.duplicaat_van_document_id,
        duplicaat_van_rlz_document_id=data.duplicaat_van_rlz_document_id,
        duplicaat_van_referentie=data.duplicaat_van_referentie,
        automatisch=data.automatisch,
    )


def _naar_origineel_dto(o: duplicaat_afvoer.Origineel | None) -> schemas.DuplicaatOrigineelDto | None:
    if o is None:
        return None
    return schemas.DuplicaatOrigineelDto(
        bron=o.bron,
        referentie=o.referentie,
        document_id=o.document_id,
        rlz_document_id=o.rlz_document_id,
        boekstuknummer=o.boekstuknummer,
        bestandsnaam=o.bestandsnaam,
        aangemaakt_op=o.aangemaakt_op,
        status=o.status,
    )


def _naar_duplicaat_afvoer_stand(
    administratie_id: uuid.UUID, document_id: uuid.UUID
) -> schemas.DuplicaatAfvoerStandDto:
    stand = duplicaat_afvoer.stand_voor_document(administratie_id=administratie_id, document_id=document_id)
    return schemas.DuplicaatAfvoerStandDto(
        kandidaat=_naar_origineel_dto(stand.kandidaat),
        afgevoerd_als_duplicaat_van=_naar_origineel_dto(stand.afgevoerd_als_duplicaat_van),
        afgevoerde_duplicaten=[
            schemas.AfgevoerdDuplicaatDto(
                afwijzing_id=d.afwijzing_id,
                document_id=d.document_id,
                bestandsnaam=d.bestandsnaam,
                aangemaakt_op=d.aangemaakt_op,
                referentie=d.referentie,
                automatisch=d.automatisch,
                afgewezen_op=d.afgewezen_op,
                afgewezen_door=d.afgewezen_door,
            )
            for d in stand.afgevoerde_duplicaten
        ],
    )


def _naar_match_kort(match: service.FactuurmatchKort | None) -> schemas.FactuurmatchKortDto | None:
    if match is None:
        return None
    return schemas.FactuurmatchKortDto(
        uitkomst=match.uitkomst,
        verschil_bedrag=match.verschil_bedrag,
        verschil_uren=match.verschil_uren,
        tarief_ontbreekt=match.tarief_ontbreekt,
    )


def _naar_match_dto(gegevens: object | None) -> schemas.FactuurmatchDto | None:
    """Mapper voor app.uren.factuurmatch_pipeline.FactuurmatchGegevens (lazy geïmporteerd in
    de endpoints — geen kringimport op moduleniveau)."""
    if gegevens is None:
        return None
    return schemas.FactuurmatchDto(
        document_id=gegevens.document_id,
        veldwerker_naam=gegevens.veldwerker_naam,
        uitkomst=gegevens.uitkomst,
        staten_som_uren=gegevens.staten_som_uren,
        staten_som_bedrag=gegevens.staten_som_bedrag,
        factuur_bedrag=gegevens.factuur_bedrag,
        factuur_uren=gegevens.factuur_uren,
        verschil_bedrag=gegevens.verschil_bedrag,
        verschil_uren=gegevens.verschil_uren,
        tarief_ontbreekt=gegevens.tarief_ontbreekt,
        details=gegevens.details,
        berekend_op=gegevens.berekend_op,
        afwijking_bevestigd=gegevens.afwijking_bevestigd_op is not None,
        afwijking_bevestigd_op=gegevens.afwijking_bevestigd_op,
    )


def _lees_match_dto(administratie_id: uuid.UUID, document_id: uuid.UUID) -> schemas.FactuurmatchDto | None:
    from app.uren import factuurmatch_pipeline

    return _naar_match_dto(factuurmatch_pipeline.lees_match(administratie_id=administratie_id, document_id=document_id))


def _naar_geboekt_in_rlz(stand) -> schemas.GeboektInRlzDto | None:
    if stand is None:
        return None
    return schemas.GeboektInRlzDto(
        regel=stand.als_regel(),
        boekstuknummer=stand.boekstuknummer,
        rlz_document_id=stand.rlz_document_id,
        tegenpartij=stand.tegenpartij,
        tegenpartij_rol=stand.tegenpartij_rol,
        geboekt_op=stand.geboekt_op,
        memoriaal_boekstuknummer=stand.memoriaal_boekstuknummer,
        vindplaats_hint=stand.vindplaats_hint,
        backend=stand.backend,
        company_naam=stand.company_naam,
        tegenboeking_boekstuknummer=stand.tegenboeking_boekstuknummer,
        kruisverwijzing=stand.kruisverwijzing,
        btw_override=stand.btw_override,
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
        id=r.id,
        ledger_id=r.ledger_id,
        taxrate_id=r.taxrate_id,
        project_id=r.project_id,
        netto_bedrag=r.netto_bedrag,
        btw_bedrag=r.btw_bedrag,
        omschrijving=r.omschrijving,
        btw_bron=r.btw_bron,
    )


def _naar_boekvoorstel_response(data: boekvoorstel.BoekvoorstelData) -> schemas.BoekvoorstelResponse:
    return schemas.BoekvoorstelResponse(
        document_id=data.document_id,
        vendor_id=data.vendor_id,
        referentie=data.referentie,
        factuurdatum=data.factuurdatum,
        vervaldatum=data.vervaldatum,
        vervaldatum_signaal=data.vervaldatum_signaal,
        betalingskenmerk=data.betalingskenmerk,
        totaalbedrag=data.totaalbedrag,
        rlz_boekstuknummer=data.rlz_boekstuknummer,
        opgeslagen=data.opgeslagen,
        regels=[_naar_regel_dto(r) for r in data.regels],
        regels_samenvoegen=data.regels_samenvoegen,
        samenvoegen_toegestaan=data.samenvoegen_toegestaan,
        samengevoegde_regel=_naar_regel_dto(data.samengevoegde_regel) if data.samengevoegde_regel else None,
        btw_verlegd_vermelding=data.btw_verlegd_vermelding,
        afdeling_id=data.afdeling_id,
        afdeling_prefill_id=data.afdeling_prefill_id,
        afdeling_prefill_leverancier=data.afdeling_prefill_leverancier,
    )


# Afbeeldingen (feedbackronde 25-08 deel 3 punt 2) worden bij binnenkomst naar PDF omgezet — de
# keten ziet uitsluitend PDF/UBL; het origineel blijft als brondocument bewaard.
_TOEGESTANE_SUFFIXEN = {".pdf", ".xml"} | set(AFBEELDING_SUFFIXEN)


@router.post(
    "/administraties/{administratie_id}/documenten",
    response_model=schemas.DocumentUploadResponse,
    status_code=status.HTTP_201_CREATED,
)
async def document_uploaden(
    administratie_id: uuid.UUID,
    bestand: UploadFile = File(...),
    soort: str = Form("inkoopfactuur"),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentUploadResponse:
    if not bestand.filename or Path(bestand.filename).suffix.lower() not in _TOEGESTANE_SUFFIXEN:
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE,
            detail="Alleen PDF-, XML- of afbeeldingsbestanden (JPEG/PNG/HEIC)",
        )
    try:
        document_soort = DocumentSoort(soort)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Onbekende documentsoort: {soort}"
        ) from None
    # Een kassarapport is altijd een PDF-scan/export — UBL is een factuurformaat, geen rapport.
    if document_soort == DocumentSoort.KASSARAPPORT and Path(bestand.filename).suffix.lower() == ".xml":
        raise HTTPException(
            status_code=status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, detail="Een kassarapport moet een PDF (of foto) zijn"
        )

    inhoud = await bestand.read()
    if not inhoud:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Leeg bestand")
    if len(inhoud) > settings.document_max_bytes:
        raise HTTPException(status_code=status.HTTP_413_CONTENT_TOO_LARGE, detail="Bestand te groot")

    bestandsnaam = bestand.filename
    bron_bestand: service.BronBestand | None = None
    if is_afbeelding(bestandsnaam, bestand.content_type):
        # Directe upload door een mens: een onbruikbare afbeelding meldt zich meteen terug (het
        # bestand staat nog op diens schijf) — via mail landt hetzelfde geval in de verzamelbak.
        try:
            omgezet = afbeelding_naar_pdf(inhoud, bestandsnaam=bestandsnaam)
        except AfbeeldingOnbruikbaar as exc:
            raise HTTPException(
                status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=f"Afbeelding onbruikbaar: {exc}"
            ) from exc
        bron_bestand = service.BronBestand(
            bestandsnaam=bestandsnaam,
            inhoud=inhoud,
            content_type=bestand.content_type or content_type_voor(bestandsnaam),
        )
        bestandsnaam, inhoud = omgezet.pdf_bestandsnaam, omgezet.pdf

    resultaat = service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam=bestandsnaam,
        inhoud=inhoud,
        actor_id=actor.id,
        soort=document_soort,
        bron_bestand=bron_bestand,
    )
    return schemas.DocumentUploadResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        mogelijk_duplicaat_van=_naar_duplicaat_response(resultaat.mogelijk_duplicaat_van),
    )


@router.get("/werkvoorraad/overzicht", response_model=schemas.WerkvoorraadOverzichtResponse)
def werkvoorraad_overzicht(
    actor: CurrentGebruiker = Depends(get_current_gebruiker),
) -> schemas.WerkvoorraadOverzichtResponse:
    """Werkvoorraad-klantenlijst met tellers (mockup #werkvoorraad "Overzicht per klant") —
    uitsluitend administraties binnen de scope van de gebruiker (zelfde bron als
    GET /auth/administraties; zelfde patroon als GET /bank/overzicht). Alle administraties komen
    mee; de frontend toont alleen klanten mét openstaand werk en vermeldt het aantal verborgen."""
    administraties = auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    klanten = service.werkvoorraad_overzicht(administratie_ids_met_naam=[(a.id, a.naam) for a in administraties])
    return schemas.WerkvoorraadOverzichtResponse(
        klanten=[
            schemas.WerkvoorraadKlantResponse(
                administratie_id=k.administratie_id,
                naam=k.naam,
                te_controleren=k.te_controleren,
                klaar_om_te_boeken=k.klaar_om_te_boeken,
                vragen=k.vragen,
                afgewezen=k.afgewezen,
                bij_klant=k.bij_klant,
                iban_wachtend=k.iban_wachtend,
                match_afwijkingen=k.match_afwijkingen,
                duplicaat_signalen=k.duplicaat_signalen,
                terugkerend_signalen=k.terugkerend_signalen,
                voorraad_verschillen=k.voorraad_verschillen,
            )
            for k in klanten
        ]
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
    # Werkvoorraad-chip "Afgewezen — ter controle" mét reden + wie afwees (mockup): één query
    # voor alle open afwijzingen, geen N+1.
    afwijzingen = afwijzen.open_afwijzingen(administratie_id=administratie_id)
    # Duplicaat-afvoer (04-09): werkvoorraad-matches in bulk (geen N+1, geen RLZ-calls) voor rijmenu + chip.
    werkvoorraad_duplicaten = duplicaat_afvoer.werkvoorraad_matches_bulk(
        administratie_id=administratie_id, document_ids=[item.document.id for item in items]
    )
    return schemas.DocumentListResponse(
        documenten=[
            schemas.DocumentListItemResponse(
                id=item.document.id,
                bestandsnaam=item.document.bestandsnaam,
                status=item.document.status.value,
                bron=item.document.bron.value,
                soort=item.document.soort,
                mogelijk_duplicaat_van=_naar_duplicaat_response(item.duplicaat_referentie),
                toegewezen_aan=item.document.toegewezen_aan,
                aangemaakt_op=item.document.aangemaakt_op,
                laatst_gewijzigd_op=item.document.laatst_gewijzigd_op,
                afwijzing=_naar_afwijzing_info(afwijzingen.get(item.document.id)),
                duplicaat_werkvoorraad_van=_naar_origineel_dto(werkvoorraad_duplicaten.get(item.document.id)),
                leverancier=item.leverancier,
                totaalbedrag=item.totaalbedrag,
                factuurdatum=item.factuurdatum,
                automatisch_geboekt=item.automatisch_geboekt,
                geboekt_in_rlz=_naar_geboekt_in_rlz(item.geboekt_in_rlz),
                factuurmatch=_naar_match_kort(item.factuurmatch),
                accordering_boek_fout=item.accordering_boek_fout,
                klant_akkoord_compleet=item.klant_akkoord_compleet,
                projectverdeling_afwijking_pct=item.projectverdeling_afwijking_pct,
                afdeling=(
                    schemas.AfdelingKortDto(id=item.afdeling[0], naam=item.afdeling[1]) if item.afdeling else None
                ),
                accordeur_aan_de_beurt=(
                    schemas.AccordeurAanDeBeurtDto(
                        gebruiker_id=item.accordeur_aan_de_beurt.gebruiker_id,
                        naam=item.accordeur_aan_de_beurt.naam,
                        laag=item.accordeur_aan_de_beurt.laag,
                    )
                    if item.accordeur_aan_de_beurt
                    else None
                ),
                duplicaatsignaal=(
                    schemas.DuplicaatSignaalKortDto(
                        uitkomst=item.duplicaatsignaal.uitkomst,
                        aantal_treffers=item.duplicaatsignaal.aantal_treffers,
                        berekend_op=item.duplicaatsignaal.berekend_op,
                    )
                    if item.duplicaatsignaal
                    else None
                ),
            )
            for item in items
        ]
    )


@router.get(
    "/administraties/{administratie_id}/leveranciers-autoboeken",
    response_model=schemas.LeverancierAutoboekenLijstResponse,
)
def leveranciers_autoboeken_lijst(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.LeverancierAutoboekenLijstResponse:
    from app.documenten import autoboeken

    return schemas.LeverancierAutoboekenLijstResponse(
        leveranciers=[
            schemas.LeverancierAutoboekenDto(
                vendor_id=rij.vendor_id,
                naam=rij.naam,
                autoboeken_ingeschakeld=rij.autoboeken_ingeschakeld,
            )
            for rij in autoboeken.lijst_leverancier_autoboeken(administratie_id=administratie_id)
        ]
    )


@router.put(
    "/administraties/{administratie_id}/leveranciers/{vendor_id}/autoboeken-instelling",
    response_model=schemas.LeverancierAutoboekenDto,
)
def leverancier_autoboeken_zetten(
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    invoer: schemas.LeverancierAutoboekenInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.LeverancierAutoboekenDto:
    """Beheerder-only (CLAUDE.md-poort): de opt-in vervangt alleen de menselijke boek-klik —
    de harde checks en failsafes blijven bij het automatisch boeken onverkort blokkerend."""
    from app.documenten import autoboeken

    ingeschakeld = autoboeken.zet_leverancier_autoboeken(
        administratie_id=administratie_id,
        vendor_id=vendor_id,
        actor_id=actor.id,
        ingeschakeld=invoer.ingeschakeld,
    )
    with_naam = next(
        (
            rij
            for rij in autoboeken.lijst_leverancier_autoboeken(administratie_id=administratie_id)
            if rij.vendor_id == vendor_id
        ),
        None,
    )
    return schemas.LeverancierAutoboekenDto(
        vendor_id=vendor_id,
        naam=with_naam.naam if with_naam else None,
        autoboeken_ingeschakeld=ingeschakeld,
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
        soort=d.soort,
        mogelijk_duplicaat_van=_naar_duplicaat_response(detail.duplicaat_referentie),
        toegewezen_aan=d.toegewezen_aan,
        aangemaakt_op=d.aangemaakt_op,
        laatst_gewijzigd_op=d.laatst_gewijzigd_op,
        veldvoorstel=detail.veldvoorstel,
        afwijzing=_naar_afwijzing_info(
            afwijzen.open_afwijzing_van(administratie_id=administratie_id, document_id=document_id)
            if d.status.value == "afgewezen"
            else None
        ),
        factuurmatch=_lees_match_dto(administratie_id, document_id),
        materiaalmatch=_lees_materiaalmatch_dto(administratie_id, document_id),
        bron_bestandsnaam=d.bron_bestandsnaam,
        tenaamstelling=d.tenaamstelling,
        geboekt_in_rlz=_naar_geboekt_in_rlz(detail.geboekt_in_rlz),
        duplicaat_afvoer=(
            _naar_duplicaat_afvoer_stand(administratie_id, document_id)
            if d.soort == DocumentSoort.INKOOPFACTUUR.value
            else None
        ),
        herkomst_mail=(
            schemas.HerkomstMailDto(
                afzender=detail.herkomst_mail.afzender,
                onderwerp=detail.herkomst_mail.onderwerp,
                ontvangen_op=detail.herkomst_mail.ontvangen_op,
                body_tekst=detail.herkomst_mail.body_tekst,
                bron=detail.herkomst_mail.bron,
            )
            if detail.herkomst_mail
            else None
        ),
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


@bestand_router.get("/administraties/{administratie_id}/documenten/{document_id}/bestand")
def document_bestand(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vorm: str = "beeld",
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _rol: CurrentGebruiker = Depends(vereis_kantoor_of_accordeur),
) -> Response:
    """`vorm=beeld` (default): wat de mens ziet — bij een gebundeld UBL+PDF-document de PDF;
    `vorm=data`: het opgeslagen hoofdbestand (de UBL)."""
    try:
        inhoud, bestandsnaam, content_type = service.haal_bijlage_op(
            administratie_id=administratie_id, document_id=document_id, vorm="data" if vorm == "data" else "beeld"
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return Response(
        content=inhoud,
        media_type=content_type,
        headers={"Content-Disposition": f'inline; filename="{bestandsnaam}"'},
    )


@bestand_router.get("/administraties/{administratie_id}/documenten/{document_id}/bronbestand")
def document_bronbestand(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _rol: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> Response:
    """Het aangeleverde origineel (bv. de foto) van een naar PDF omgezet document — punt 2; 404 als
    het document zelf het origineel is."""
    try:
        inhoud, bestandsnaam, content_type = service.haal_bronbestand_op(
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
    """ "Opnieuw extraheren" na een transiënte AI-fout (timeout, 529) — draait de extractie
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


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/verplaats",
    response_model=schemas.DocumentVerplaatsResponse,
)
def document_verplaatsen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.VerplaatsInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DocumentVerplaatsResponse:
    """Verplaats naar een andere administratie (addendum 27-08 punt 5, herstel foute toewijzing).
    Bron-scope via de dependency, doel-scope in de service (403 zonder toegang tot het doel); alleen
    te_controleren/handmatig_afmaken/klaar_om_te_boeken/vraag_open/afgewezen — geboekt en
    ter_accordering geven 409 mét uitleg (zie verplaatsen.reden_niet_verplaatsbaar). Ná de
    verhuizing draait de extractie opnieuw in het doel; de response draagt de eindstatus dáár."""
    try:
        resultaat = verplaatsen.verplaats_document(
            administratie_id=administratie_id,
            document_id=document_id,
            doel_administratie_id=invoer.doel_administratie_id,
            actor_id=actor.id,
            actor_rol=actor.rol,
            onthoud_tenaamstelling=invoer.onthoud_tenaamstelling,
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except verplaatsen.OnbekendeDoelAdministratie as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except verplaatsen.GeenScopeOpDoel as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except verplaatsen.VerplaatsenNietToegestaan as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.DocumentVerplaatsResponse(
        document_id=resultaat.document_id,
        status=resultaat.status.value,
        van_administratie_id=resultaat.van_administratie_id,
        van_administratie_naam=resultaat.van_administratie_naam,
        naar_administratie_id=resultaat.naar_administratie_id,
        naar_administratie_naam=resultaat.naar_administratie_naam,
        leerregels_gecorrigeerd=list(resultaat.leerregels_gecorrigeerd),
        vragen_verhuisd=resultaat.vragen_verhuisd,
        vragen_hertoegewezen=resultaat.vragen_hertoegewezen,
        tenaamstelling_geleerd=resultaat.tenaamstelling_geleerd,
    )


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
            vervaldatum=invoer.vervaldatum,
            betalingskenmerk=invoer.betalingskenmerk,
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
            afdeling_id=invoer.afdeling_id,
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except boekvoorstel.BoekvoorstelFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc

    # voer_checks_uit() vangt credential-/RLZ-fouten zelf af (app/documenten/boekvoorstel.py) —
    # het resultaat is altijd een CheckRapport, nooit een onafgevangen RlzApiError/GeenRlzCredentials.
    rapport = boekvoorstel.voer_checks_uit(administratie_id=administratie_id, document_id=document_id)

    return schemas.BoekvoorstelMetChecksResponse(
        boekvoorstel=_naar_boekvoorstel_response(data),
        checks=_naar_check_rapport_response(rapport),
        # sla_boekvoorstel_op herberekende de factuurmatch al (post-commit) — hier de verse stand.
        factuurmatch=_lees_match_dto(administratie_id, document_id),
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/aanbetaling-open",
    response_model=schemas.AanbetalingSignaalResponse,
)
def aanbetaling_open_signaal(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AanbetalingSignaalResponse:
    """Aanbetaling-open-signaal (besluit Peter 25-08, deel 4 punt 3): staat er voor de crediteur van
    dit document nog een vooruitbetaling/aanbetaling open (relatie-koppeling uit de bankmodule) —
    signaal op het controlescherm, alleen op het boekmoment, nooit blokkerend, puur lezen."""
    from app.bank import aanbetaling_signaal

    signaal = aanbetaling_signaal.signaal_voor_document(administratie_id=administratie_id, document_id=document_id)
    return schemas.AanbetalingSignaalResponse(
        toetsbaar=signaal.toetsbaar,
        treffers=[
            schemas.AanbetalingTrefferDto(
                boeking_id=t.boeking_id,
                payment_transaction_id=t.payment_transaction_id,
                bedrag=t.bedrag,
                boekdatum=t.boekdatum,
                geboekt_op=t.geboekt_op,
                rlz_boekstuknummer=t.rlz_boekstuknummer,
                entity_naam=t.entity_naam,
                vooruit_ledger_id=t.vooruit_ledger_id,
                herkenning=t.herkenning,
            )
            for t in signaal.treffers
        ],
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/al-betaald",
    response_model=schemas.AlBetaaldSignaalResponse,
)
def al_betaald_signaal(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AlBetaaldSignaalResponse:
    """Al-betaald-signaal (besluit Peter 25-08, deel 2 punt 1): toetst de ONafgeletterde
    bankmutaties uit de lokale cache tegen crediteur + totaalbedrag van dit document — een
    signaal op het controlescherm, nooit blokkerend, geen live RLZ-call, geen bijwerking."""
    from app.bank import betaald_signaal

    signaal = betaald_signaal.signaal_voor_document(administratie_id=administratie_id, document_id=document_id)
    return schemas.AlBetaaldSignaalResponse(
        toetsbaar=signaal.toetsbaar,
        treffers=[
            schemas.AlBetaaldTrefferDto(
                mutatie_id=t.mutatie_id,
                boekdatum=t.boekdatum,
                bedrag=t.bedrag,
                rekening_naam=t.rekening_naam,
                rekening_iban=t.rekening_iban,
                tegenpartij_naam=t.tegenpartij_naam,
                omschrijving=t.omschrijving,
                redenen=list(t.redenen),
            )
            for t in signaal.treffers
        ],
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
    invoer: schemas.BoekenInput | None = None,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BoekenResponse:
    """Body optioneel (factuurmatch fase 2): `match_afwijking_bevestigd` is de expliciete
    "boeken ondanks match-afwijking"-bevestiging; zonder die vlag antwoordt een afwijking
    met 409 + de match-cijfers in detail.match (client toont de bevestigingspop-up)."""
    # Orkestratie (besluit 25-08): mét klaargezette doorbelasting = "Boeken + doorbelasten" in
    # één gang, zonder = exact de bestaande boek_document-aanroep. Lazy import: geen kring.
    from app.doorbelasting import orkestratie

    try:
        gecombineerd = orkestratie.boek_document_met_doorbelasting(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            match_afwijking_bevestigd=invoer.match_afwijking_bevestigd if invoer else False,
            materiaal_afwijking_bevestigd=invoer.materiaal_afwijking_bevestigd if invoer else False,
        )
        resultaat = gecombineerd.boek
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except orkestratie.DoorbelastingChecksNietGroen as exc:
        # Zelfde 409-vorm als de inkoop-checks: het controlescherm toont de check-rijen.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Boeken geblokkeerd door doorbelasting-checks",
                "checks": _naar_check_rapport_response(exc.rapport).model_dump(),
            },
        ) from exc
    except boeken.MatchAfwijkingBevestigingVereist as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "match": exc.match_info},
        ) from exc
    except MateriaalAfwijkingBevestigingVereist as exc:
        # D6: zelfde 409-vorm, eigen sleutel — de client toont de materiaal-pop-up.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"message": str(exc), "materiaalmatch": exc.match_info},
        ) from exc
    except boeken.OngeldigeBoekpoging as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except boeken.AccorderingVereist as exc:
        # Bugfix-run 28-08: was onvertaald (500) — de accorderingspoort is een nette 409 mét reden
        # (ronde loopt / opnieuw aanbieden / bedrag gewijzigd ná akkoord).
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
        doorbelasting_run_id=gecombineerd.doorbelasting_run_id,
        doorbelasting=gecombineerd.doorbelasting,
        doorbelasting_fout=gecombineerd.doorbelasting_fout,
    )


def _naar_tegenboek_toets_response(data: tegenboeken.TegenboekToets) -> schemas.TegenboekToetsResponse:
    return schemas.TegenboekToetsResponse(
        document_id=data.document_id,
        storno_geblokkeerd=data.storno_geblokkeerd,
        blokkade_melding=data.blokkade_melding,
        tegenboeking=(
            schemas.TegenboekingInfoDto(
                soort=data.tegenboeking.soort,
                reden=data.tegenboeking.reden,
                boek_cyclus=data.tegenboeking.boek_cyclus,
                rlz_tegenboeking_id=data.tegenboeking.rlz_tegenboeking_id,
                rlz_boekstuknummer=data.tegenboeking.rlz_boekstuknummer,
                origineel_betaald_bedrag=data.tegenboeking.origineel_betaald_bedrag,
                aangemaakt_op=data.tegenboeking.aangemaakt_op,
            )
            if data.tegenboeking
            else None
        ),
        betaalstatus=(
            schemas.TegenboekBetaalstatusDto(
                betaald_bedrag=data.betaalstatus.betaald_bedrag,
                open_bedrag=data.betaalstatus.open_bedrag,
                volledig_afgeletterd=data.betaalstatus.volledig_afgeletterd,
            )
            if data.betaalstatus
            else None
        ),
        voorbeeld=[
            schemas.TegenboekVoorbeeldRegelDto(
                grootboek_code=r.grootboek_code,
                grootboek_naam=r.grootboek_naam,
                omschrijving=r.omschrijving,
                netto_bedrag=r.netto_bedrag,
                btw_bedrag=r.btw_bedrag,
            )
            for r in data.voorbeeld
        ],
        referentie=data.referentie,
        tegenboek_referentie=data.tegenboek_referentie,
        leverancier_naam=data.leverancier_naam,
        totaal_netto=data.totaal_netto,
        totaal_btw=data.totaal_btw,
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/tegenboek-toets",
    response_model=schemas.TegenboekToetsResponse,
)
def document_tegenboek_toets(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TegenboekToetsResponse:
    """Leesroute tegenboek-pad (mockup tegenboek-mockup.html): is storno door de aangifte-poort
    geblokkeerd (dan verschijnt "Tegenboeken…"), bestaat er al een tegenboeking (chip
    TEGENGEBOEKT + kruisverwijzing) en het voorbeeld + de betaalstatus-waarschuwing."""
    try:
        data = tegenboeken.toets(administratie_id=administratie_id, document_id=document_id)
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except tegenboeken.OngeldigeTegenboeking as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return _naar_tegenboek_toets_response(data)


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/tegenboeken",
    response_model=schemas.TegenboekenResponse,
)
def document_tegenboeken(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.TegenboekenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.TegenboekenResponse:
    """De tegenboek-actie (mockup: keuze volledig/vervang, verplichte reden). Zie
    app/documenten/tegenboeken.py voor de poorten en waarborgen."""
    try:
        resultaat = tegenboeken.voer_tegenboeking_uit(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            soort=invoer.soort,
            reden=invoer.reden,
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except tegenboeken.TegenboekenGeblokkeerdDoorChecks as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Tegenboeken geblokkeerd door harde checks",
                "checks": _naar_check_rapport_response(exc.rapport).model_dump(),
            },
        ) from exc
    except (
        tegenboeken.OngeldigeTegenboeking,
        tegenboeken.TegenboekenNietToegestaan,
        tegenboeken.TegenboekingBestaatAl,
    ) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except tegenboeken.RlzTegenboekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    return schemas.TegenboekenResponse(
        document_id=resultaat.document_id,
        soort=resultaat.soort,
        status=resultaat.status.value,
        rlz_tegenboeking_id=resultaat.rlz_tegenboeking_id,
        rlz_boekstuknummer=resultaat.rlz_boekstuknummer,
    )


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/factuurmatch/kandidaat-staten",
    response_model=schemas.KandidaatStatenResponse,
)
def factuurmatch_kandidaat_staten(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.KandidaatStatenResponse:
    """Selecteerbare weekstaten voor de periode-keuze in de match-sectie (fase 3): goedgekeurd
    én onverrekend (of met dít document verrekend), van de betrokken ZZP'er(s) — bewust zonder
    factuurdatum-grens (de motor valideert de uiteindelijke selectie hard bij herberekenen)."""
    from app.uren import factuurmatch_pipeline

    staten = factuurmatch_pipeline.kandidaat_staten_voor_document(
        administratie_id=administratie_id, document_id=document_id
    )
    return schemas.KandidaatStatenResponse(staten=[schemas.KandidaatStaatDto(**s.__dict__) for s in staten])


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/factuurmatch/herbereken",
    response_model=schemas.FactuurmatchResponse,
)
def factuurmatch_herberekenen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.FactuurmatchHerberekenInput | None = None,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.FactuurmatchResponse:
    """Expliciete herberekening van de urenmatch (fase 2; "periode-keuze"): optioneel mét een
    handmatige weekstaat-selectie en/of mens-opgegeven factuur-uren — de motor valideert de
    selectie hard (alleen goedgekeurde, onverrekende staten van de betrokken ZZP'ers). De
    berekening zelf draait onder de systeem-actor (lees-policy bureau-tarieven, 0057);
    NB een herberekening wist een eerdere "boeken ondanks afwijking"-bevestiging."""
    from app.uren import factuurmatch_pipeline
    from app.uren.service import NietGevonden as UrenNietGevonden
    from app.uren.service import OngeldigeInvoer as UrenOngeldigeInvoer

    try:
        data = factuurmatch_pipeline.draai_match_voor_document(
            administratie_id=administratie_id,
            document_id=document_id,
            weekstaat_ids=invoer.weekstaat_ids if invoer else None,
            factuur_uren=invoer.factuur_uren if invoer else None,
        )
    except UrenNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UrenOngeldigeInvoer as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    if data is None:
        return schemas.FactuurmatchResponse(factuurmatch=None)
    return schemas.FactuurmatchResponse(factuurmatch=_lees_match_dto(administratie_id, document_id))


@router.get(
    "/administraties/{administratie_id}/documenten/{document_id}/factuurmatch/concept-mail",
    response_model=schemas.MatchMailConceptResponse,
)
def factuurmatch_concept_mail(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MatchMailConceptResponse:
    """CONCEPT-mail aan de veldwerker over de matchstand (fase 2) — genereren is lezen, er
    wordt niets verzonden of vastgelegd; de mens bewerkt en verstuurt expliciet (POST)."""
    from app.uren import factuurmatch_mail
    from app.uren.service import NietGevonden as UrenNietGevonden

    try:
        concept = factuurmatch_mail.bouw_concept_mail(administratie_id=administratie_id, document_id=document_id)
    except UrenNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.MatchMailConceptResponse(
        ontvanger_naam=concept.ontvanger_naam,
        ontvanger_e_mail=concept.ontvanger_e_mail,
        onderwerp=concept.onderwerp,
        tekst=concept.tekst,
    )


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/factuurmatch/mail",
    response_model=schemas.MatchMailVerzondenResponse,
)
def factuurmatch_mail_verzenden(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.MatchMailVerzendenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MatchMailVerzondenResponse:
    """Verzend de (gereviewde) match-mail aan de veldwerker van de match — nooit automatisch.
    Fail-zichtbaar: mailkanaal niet geconfigureerd = 503, verzendfout = 424 (zelfde afweging
    als de accordeur-herinnering: een bezorgfout is een nette applicatie-uitkomst, geen
    gateway-status). Geslaagd = audit + tijdlijn-notitie."""
    from app.berichten.mail import MailNietGeconfigureerd, MailVerzendFout
    from app.uren import factuurmatch_mail
    from app.uren.service import NietGevonden as UrenNietGevonden
    from app.uren.service import OngeldigeInvoer as UrenOngeldigeInvoer

    try:
        verzonden_aan = factuurmatch_mail.verzend_match_mail(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            onderwerp=invoer.onderwerp,
            tekst=invoer.tekst,
        )
    except UrenNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except UrenOngeldigeInvoer as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except MailNietGeconfigureerd as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    except MailVerzendFout as exc:
        raise HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc)) from exc
    return schemas.MatchMailVerzondenResponse(verzonden_aan=verzonden_aan)


def _naar_vraag_response(data: vragen.VraagData, actor_id: uuid.UUID | None = None) -> schemas.VraagResponse:
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
        aan_de_beurt=data.aan_de_beurt,
        afgehandeld_door=data.afgehandeld_door,
        afgehandeld_op=data.afgehandeld_op,
        berichten=[
            schemas.VraagBerichtResponse(id=b.id, auteur_id=b.auteur_id, tekst=b.tekst, geplaatst_op=b.geplaatst_op)
            for b in data.berichten
        ],
        mag_afhandelen=(
            data.status == VraagStatus.OPEN.value
            and actor_id is not None
            and vragen.mag_afhandelen(data.gesteld_door, data.toegewezen_aan, actor_id)
        ),
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
    return _naar_vraag_response(data, actor.id)


@router.post(
    "/administraties/{administratie_id}/vragen/{vraag_id}/berichten",
    response_model=schemas.VraagResponse,
    status_code=status.HTTP_201_CREATED,
)
def vraag_bericht_plaatsen(
    administratie_id: uuid.UUID,
    vraag_id: uuid.UUID,
    invoer: schemas.VraagBerichtInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VraagResponse:
    """Bijdrage in de dialoog (besluit Peter 25-08): append-only bericht, de vraag blijft open en
    het document geblokkeerd; "aan de beurt" wisselt en Document.toegewezen_aan volgt (de
    bestaande melding). Alleen "Afgehandeld" door de vraagsteller sluit de thread."""
    try:
        data = vragen.plaats_bericht(
            administratie_id=administratie_id, vraag_id=vraag_id, actor_id=actor.id, tekst=invoer.tekst
        )
    except (vragen.VraagNietGevonden, service.DocumentNietGevonden) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except vragen.AntwoordTekstVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except vragen.VraagNietOpen as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_vraag_response(data, actor.id)


@router.post(
    "/administraties/{administratie_id}/vragen/{vraag_id}/afhandelen",
    response_model=schemas.VraagResponse,
)
def vraag_afhandelen(
    administratie_id: uuid.UUID,
    vraag_id: uuid.UUID,
    invoer: schemas.VraagAfhandelenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.VraagResponse:
    """ "Afgehandeld" (besluit Peter 25-08): uitsluitend de oorspronkelijke vraagsteller (403 voor
    ieder ander; systeem-vraag: de toegewezene). Sluit de thread en zet het document terug naar de
    herkomst-status van vóór de vraag — boeken is daarna weer bereikbaar via de normale route."""
    try:
        data = vragen.handel_vraag_af(
            administratie_id=administratie_id,
            vraag_id=vraag_id,
            actor_id=actor.id,
            slotbericht=invoer.slotbericht,
        )
    except (vragen.VraagNietGevonden, service.DocumentNietGevonden) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except vragen.AlleenVraagstellerMagAfhandelen as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (vragen.VraagNietOpen, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_vraag_response(data, actor.id)


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
    return _naar_vraag_response(data, actor.id)


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
    return schemas.VraagLijstResponse(vragen=[_naar_vraag_response(v, actor.id) for v in data])


def _naar_afwijzing_response(data: afwijzen.AfwijzingData) -> schemas.AfwijzingResponse:
    return schemas.AfwijzingResponse(
        id=data.id,
        document_id=data.document_id,
        document_status=data.document_status.value,
        reden=data.reden,
        status=data.status,
        status_voor_afwijzing=data.status_voor_afwijzing,
        afgewezen_door=data.afgewezen_door,
        afgewezen_op=data.afgewezen_op,
        toegewezen_aan=data.toegewezen_aan,
        heropend_door=data.heropend_door,
        heropend_op=data.heropend_op,
    )


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/afwijzen",
    response_model=schemas.AfwijzingResponse,
    status_code=status.HTTP_201_CREATED,
)
def document_afwijzen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.AfwijzenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AfwijzingResponse:
    """Afwijzen (mockup #afwijsmodal): reden verplicht, document -> afgewezen (blijft zichtbaar
    in de werkvoorraad als "Afgewezen — ter controle", boeken geblokkeerd), toewijzing default
    naar de administratie-eigenaar — zelfde patroon als vraag stellen."""
    try:
        data = afwijzen.wijs_af(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            reden=invoer.reden,
            toegewezen_aan=invoer.toegewezen_aan,
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except afwijzen.RedenVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (vragen.GeenToewijzingMogelijk, vragen.ToegewezeneBuitenScope) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except OngeldigeStatusovergang as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_afwijzing_response(data)


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/afvoeren-als-duplicaat",
    response_model=schemas.DuplicaatAfvoerResponse,
)
def document_afvoeren_als_duplicaat(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DuplicaatAfvoerResponse:
    """Één-klik "Afvoeren als duplicaat" (besluit Peter 04-09, migratie 0105) — altijd beschikbaar, ook
    zonder de opt-in. Zelfde motor als het automatische pad, actor = de mens, `automatisch=false`, reden
    deterministisch ("Duplicaat van ‹referentie› (…)"). Idempotent: al afgevoerd = 200 met dezelfde data;
    409 leesbaar zonder harde match (meer) of bij een status die het niet toelaat. Nooit verwijderen —
    terughalen via heropenen."""
    try:
        resultaat = duplicaat_afvoer.voer_af_als_duplicaat(
            administratie_id=administratie_id, document_id=document_id, actor_id=actor.id
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (duplicaat_afvoer.DuplicaatAfvoerFout, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except (vragen.GeenToewijzingMogelijk, vragen.ToegewezeneBuitenScope) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    a = resultaat.afwijzing
    return schemas.DuplicaatAfvoerResponse(
        afwijzing_id=a.id,
        document_id=a.document_id,
        document_status=a.document_status.value,
        reden=a.reden,
        automatisch=a.automatisch,
        al_afgevoerd=resultaat.al_afgevoerd,
        origineel=_naar_origineel_dto(resultaat.origineel),  # type: ignore[arg-type]
    )


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/heropenen",
    response_model=schemas.AfwijzingResponse,
)
def document_heropenen(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AfwijzingResponse:
    """Heropent een afgewezen document: de afwijzing blijft als 'heropend' in de historie
    staan, het document gaat terug naar exact de herkomst-status van vóór de afwijzing
    (status_voor_afwijzing) — zelfde herstel-patroon als beantwoorden/intrekken van een vraag."""
    try:
        data = afwijzen.heropen(administratie_id=administratie_id, document_id=document_id, actor_id=actor.id)
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (afwijzen.GeenOpenAfwijzing, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_afwijzing_response(data)


# Het vroegere directe bevestig-endpoint (POST .../crediteuren/{vendor_id}/ibans) is bewust
# verwijderd bij de vier-ogen-accordering (2026-07-15): élke gescoopte gebruiker kon er
# eigenhandig een IBAN vertrouwd mee maken, wat de vier-ogen-waarborg zou omzeilen. De enige
# menselijke route is nu aanbieden → accorderen door een tweede paar ogen (hieronder);
# docs/ontwerp/iban-wissel-accordering.md, bewuste keuze 1.


def _naar_iban_accordering_response(data: iban_accordering.AccorderingData) -> schemas.IbanAccorderingResponse:
    return schemas.IbanAccorderingResponse(
        id=data.id,
        document_id=data.document_id,
        document_status=data.document_status.value,
        vendor_id=data.vendor_id,
        nieuw_iban=data.nieuw_iban,
        soort=data.soort,
        status=data.status,
        status_voor_accordering=data.status_voor_accordering,
        aangevraagd_door=data.aangevraagd_door,
        aangevraagd_op=data.aangevraagd_op,
        besloten_door=data.besloten_door,
        besloten_op=data.besloten_op,
        afwijs_reden=data.afwijs_reden,
    )


@router.post(
    "/administraties/{administratie_id}/documenten/{document_id}/iban-accordering",
    response_model=schemas.IbanAccorderingResponse,
    status_code=status.HTTP_201_CREATED,
)
def iban_accordering_aanbieden(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    invoer: schemas.IbanAanbiedenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.IbanAccorderingResponse:
    """Afwijkend IBAN aanbieden ter vier-ogen-accordering: document → wacht_op_iban_accordering
    (boeken geblokkeerd tot een accordeur ≠ aanvrager besluit). Crediteur komt van het
    boekvoorstel; het IBAN zit in de body, nooit in de URL."""
    try:
        data = iban_accordering.bied_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            nieuw_iban=invoer.nieuw_iban,
            soort=IbanSoort(invoer.soort),
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except leverancier_iban.OngeldigIban as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (iban_accordering.GeenCrediteurOpVoorstel, iban_accordering.IbanAlVertrouwd) as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (iban_accordering.ErIsAlEenOpenAccordering, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_iban_accordering_response(data)


@router.post(
    "/administraties/{administratie_id}/iban-accorderingen/{accordering_id}/accorderen",
    response_model=schemas.IbanAccorderingResponse,
)
def iban_accordering_accorderen(
    administratie_id: uuid.UUID,
    accordering_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.IbanAccorderingResponse:
    """Vier-ogen-akkoord (accordeur ≠ aanvrager, server-side afgedwongen): IBAN wordt
    vertrouwd (bron=bevestigd), document terug naar de herkomst-status."""
    try:
        data = iban_accordering.accordeer(
            administratie_id=administratie_id, accordering_id=accordering_id, actor_id=actor.id
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (iban_accordering.VierOgenGeschonden, iban_accordering.GeenBevoegdeAccordeur) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (iban_accordering.GeenOpenAccordering, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_iban_accordering_response(data)


@router.post(
    "/administraties/{administratie_id}/iban-accorderingen/{accordering_id}/afwijzen",
    response_model=schemas.IbanAccorderingResponse,
)
def iban_accordering_afwijzen(
    administratie_id: uuid.UUID,
    accordering_id: uuid.UUID,
    invoer: schemas.IbanAfwijzenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.IbanAccorderingResponse:
    """Vier-ogen-afwijzing (zelfde accordeur-eisen): reden verplicht; het document blijft
    geblokkeerd op wacht_op_iban_accordering en is via de afgewezen aanvraag gemarkeerd als
    verdacht — geen automatische vervolgactie."""
    try:
        data = iban_accordering.wijs_af(
            administratie_id=administratie_id, accordering_id=accordering_id, actor_id=actor.id, reden=invoer.reden
        )
    except service.DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except iban_accordering.AfwijsRedenVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except (iban_accordering.VierOgenGeschonden, iban_accordering.GeenBevoegdeAccordeur) as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (iban_accordering.GeenOpenAccordering, OngeldigeStatusovergang) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return _naar_iban_accordering_response(data)


@router.get(
    "/administraties/{administratie_id}/iban-accorderingen",
    response_model=schemas.IbanAccorderingLijstResponse,
)
def iban_accorderingen_lijst(
    administratie_id: uuid.UUID,
    accordering_status: IbanAccorderingStatus | None = None,
    document_id: uuid.UUID | None = None,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.IbanAccorderingLijstResponse:
    """Accorderingen van één administratie, nieuwste eerst — optioneel gefilterd op status
    en/of document (PART B-UI haalt zo de open aanvraag van één document op)."""
    data = iban_accordering.lijst_accorderingen(
        administratie_id=administratie_id, status=accordering_status, document_id=document_id
    )
    return schemas.IbanAccorderingLijstResponse(accorderingen=[_naar_iban_accordering_response(a) for a in data])


@router.get(
    "/administraties/{administratie_id}/iban-accordeurs",
    response_model=schemas.IbanAccordeursResponse,
)
def iban_accordeurs_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.IbanAccordeursResponse:
    """Scope-check, geen Beheerder-only: wie een IBAN aanbiedt moet kunnen zien wie er kan
    accorderen (lege lijst = de actieve beheerders)."""
    return schemas.IbanAccordeursResponse(
        accordeurs=iban_accordering.haal_accordeurs_op(administratie_id=administratie_id)
    )


@router.put(
    "/administraties/{administratie_id}/iban-accordeurs",
    response_model=schemas.IbanAccordeursResponse,
)
def iban_accordeurs_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.IbanAccordeursInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.IbanAccordeursResponse:
    """Instelling "IBAN-wissel accorderen door" — Beheerder-only, net als de andere
    administratie-instellingen; elke wijziging in het audit_event."""
    try:
        accordeurs = iban_accordering.zet_accordeurs(
            administratie_id=administratie_id, actor_id=actor.id, accordeurs=invoer.accordeurs
        )
    except iban_accordering.AccordeurBuitenScope as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.IbanAccordeursResponse(accordeurs=accordeurs)


def _lees_materiaalmatch_dto(administratie_id: uuid.UUID, document_id: uuid.UUID):
    """Materiaalmatch (D6) op het controlescherm — None als er geen match-rij is (geen
    verhuur-crediteur). Lazy import: de materiaal-schemas kennen de document-schemas niet."""
    from app.materiaal import schemas as materiaal_schemas

    m = lees_materiaalmatch(administratie_id=administratie_id, document_id=document_id)
    return materiaal_schemas.MateriaalmatchDto(**m.__dict__) if m else None
