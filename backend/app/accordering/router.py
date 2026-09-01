"""Klant-accorderingsflow — endpoints (migratie 0033, mockup #autorisatie).

Ontworpen voor twee afnemers: de kantoor-UI (instellingen, aanbieden/intrekken,
accorderingshistorie, staande regels) en de latere accordeur-PWA (wachtrij, akkoord,
afwijzen-met-reden, staande regel bij akkoord). Autorisatie: scope via de bestaande
dependencies + RLS; accordeur-besluiten worden in de service bovendien hard op de
stap-eigenaar getoetst, kantoor-acties weigeren de rol klant-accordeur."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.accordering import herinnering, schemas, service
from app.auth import service as auth_service
from app.auth import voorwaarden
from app.auth.deps import (
    CurrentGebruiker,
    get_current_gebruiker,
    require_beheerder,
    vereis_administratie_scope,
    vereis_kantoor_of_accordeur,
    vereis_kantoorrol,
)
from app.db.models import GebruikerRol
from app.documenten import vragen
from app.documenten.service import DocumentNietGevonden
from app.materiaal.match import MateriaalAfwijkingBevestigingVereist

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
    if isinstance(exc, service.KlantAkkoordAlCompleet):
        # Punt 24 (opruimrun 28-08): conflict met de actuele stand — boeken is de juiste actie.
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, herinnering.AlHerinnerdVandaag):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, herinnering.HerinneringVerzendingMislukt):
        # Bewust GEEN 502 (bewijs-push 2026-08-17): de gateway-statussen (502/503/504) worden
        # door de frontend én de loadbalancer als "backend niet bereikbaar" gelezen — een
        # mislukte bezorging is een nette applicatie-uitkomst mét reden. 424 Failed Dependency:
        # het verzoek zelf klopte, de afhankelijke bezorging (push/mail) faalde; opnieuw mag.
        return HTTPException(status_code=status.HTTP_424_FAILED_DEPENDENCY, detail=str(exc))
    return HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))


def _accordering_response(data: service.AccorderingData) -> schemas.AccorderingResponse:
    return schemas.AccorderingResponse(
        id=data.id,
        document_id=data.document_id,
        status=data.status,
        aangeboden_op=data.aangeboden_op,
        afgerond_op=data.afgerond_op,
        boek_fout=data.boek_fout,
        boek_fout_op=data.boek_fout_op,
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
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.InstellingenResponse:
    """Scope-check, geen Beheerder-only: het controlescherm moet weten of de boekknop
    "Ter accordering" hoort te zijn. Wél kantoor-only (rollen-gate-fix 2026-08-21): de
    accordeur-PWA heeft de lagen/drempels niet nodig."""
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
    Beheerder, CLAUDE.md-autorisatie). Wijzigt het effectieve schema, dan vervallen lopende
    rondes (punt 2a) — het aantal reist mee terug zodat de UI het direct kan melden."""
    try:
        vervallen = service.instellingen_opslaan(
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
    antwoord = instellingen_ophalen(administratie_id, actor)
    return antwoord.model_copy(update={"rondes_vervallen": vervallen})


@router.get(
    "/administraties/{administratie_id}/accordering/vervallen-meldingen",
    response_model=list[schemas.VervallenMeldingDto],
)
def vervallen_meldingen(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> list[schemas.VervallenMeldingDto]:
    """Eenmalige werkvoorraad-melding (punt 2a): configuratiewijzigingen van de afgelopen
    VERVALLEN_MELDING_DAGEN die lopende rondes lieten vervallen, nieuwste eerst — de UI toont een
    banner op de documentenlijst zolang er documenten uit de batch nog niet opnieuw zijn
    aangeboden (weggeklikt = per gebruiker onthouden, client-side)."""
    meldingen = service.vervallen_meldingen(administratie_id=administratie_id)
    namen = service._gebruikersnamen_publiek({m.door_gebruiker_id for m in meldingen})
    return [
        schemas.VervallenMeldingDto(
            batch_id=m.batch_id,
            tijdstip=m.tijdstip,
            door_gebruiker_id=m.door_gebruiker_id,
            door_naam=namen.get(m.door_gebruiker_id),
            aantal=m.aantal,
            nog_niet_opnieuw_aangeboden=m.nog_niet_opnieuw_aangeboden,
            reden=service.VERVALLEN_REDEN,
        )
        for m in meldingen
    ]


@router.post(
    "/administraties/{administratie_id}/accordering/documenten/bulk-aanbieden",
    response_model=schemas.BulkAanbiedenResponse,
)
def bulk_aanbieden(
    administratie_id: uuid.UUID,
    invoer: schemas.BulkAanbiedenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.BulkAanbiedenResponse:
    """Bulk "Ter accordering aanbieden" (punt 2b): zelfde poorten als de losse knop, per document;
    geweigerde documenten komen terug als `overgeslagen` mét reden — nooit stil."""
    try:
        resultaten = service.bulk_aanbieden(
            administratie_id=administratie_id,
            document_ids=list(invoer.document_ids),
            actor_id=actor.id,
            actor_rol=actor.rol.value,
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return schemas.BulkAanbiedenResponse(
        resultaten=[
            schemas.BulkAanbiedResultaatDto(
                document_id=r.document_id,
                bestandsnaam=r.bestandsnaam,
                uitkomst=r.uitkomst,
                reden=r.reden,
                boek_fout=r.boek_fout,
            )
            for r in resultaten
        ],
        aangeboden=sum(1 for r in resultaten if r.uitkomst == "aangeboden"),
        geboekt=sum(1 for r in resultaten if r.uitkomst == "geboekt"),
        overgeslagen=sum(1 for r in resultaten if r.uitkomst == "overgeslagen"),
    )


def _naar_bulk_uitkomsten(uitkomsten: list[service.BulkInstelUitkomst]) -> list[schemas.BulkInstelUitkomstDto]:
    return [
        schemas.BulkInstelUitkomstDto(
            administratie_id=u.administratie_id,
            administratie_naam=u.administratie_naam,
            uitkomst=u.uitkomst,
            rondes_vervallen=u.rondes_vervallen,
            toggle_aangezet=u.toggle_aangezet,
            scope_toegevoegd_voor=u.scope_toegevoegd_voor or [],
            reden=u.reden,
        )
        for u in uitkomsten
    ]


def _bulk_lagen(invoer: schemas.BulkInstellenInput) -> list[service.LaagInput]:
    return [
        service.LaagInput(
            volgnummer=laag.volgnummer,
            accordeur_gebruiker_id=laag.accordeur_gebruiker_id,
            bedrag_drempel=laag.bedrag_drempel,
        )
        for laag in invoer.lagen
    ]


@router.post("/accordering/bulk-instellen/preview", response_model=schemas.BulkInstellenPreviewResponse)
def bulk_instellen_preview(
    invoer: schemas.BulkInstellenInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.BulkInstellenPreviewResponse:
    """Preview van de bulk (mockup bulk-accordering.html): scope-meldingen per accordeur,
    overschrijf-waarschuwing mét telling vervallen rondes en de uitkomstenlijst — leest alleen.
    Beheerder-only: de bulk kan scope-rijen aanmaken en dat is Beheerder-exclusief."""
    try:
        uitkomsten, scope_ontbreekt = service.bulk_instellen_preview(
            administratie_ids=list(invoer.administratie_ids),
            lagen=_bulk_lagen(invoer),
            scope_toevoegen=invoer.scope_toevoegen,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return schemas.BulkInstellenPreviewResponse(
        uitkomsten=_naar_bulk_uitkomsten(uitkomsten),
        scope_ontbreekt=[
            schemas.BulkScopeOntbreektDto(
                accordeur_gebruiker_id=m.accordeur_gebruiker_id,
                accordeur_naam=m.accordeur_naam,
                administratie_ids=m.administratie_ids,
                administratie_namen=m.administratie_namen,
            )
            for m in scope_ontbreekt
        ],
    )


@router.post("/accordering/bulk-instellen", response_model=schemas.BulkInstellenResponse)
def bulk_instellen(
    invoer: schemas.BulkInstellenInput,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.BulkInstellenResponse:
    """Toepassen: orkestratie over de bestaande per-administratie-configuratieroute (zelfde
    validatie, vervallen-patroon en audits als een losse wijziging) — deelfout per BV zichtbaar
    in de uitkomst, nooit stil half. Beheerder-only (scope-aanmaak is Beheerder-exclusief)."""
    try:
        uitkomsten = service.bulk_instellen(
            administratie_ids=list(invoer.administratie_ids),
            lagen=_bulk_lagen(invoer),
            scope_toevoegen=invoer.scope_toevoegen,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return schemas.BulkInstellenResponse(uitkomsten=_naar_bulk_uitkomsten(uitkomsten))


@router.get("/accordering/accordeur-kandidaten", response_model=schemas.KandidatenResponse)
def alle_accordeur_kandidaten(
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.KandidatenResponse:
    """Keuzelijst voor de bulk-dialoog: álle actieve klant-accordeurs, platform-breed — de
    scope kan bij een geselecteerde BV immers nog ontbreken (dat lost de scope-vink op)."""
    return schemas.KandidatenResponse(
        kandidaten=[schemas.KandidaatDto(id=k.id, naam=k.naam) for k in service.alle_accordeur_kandidaten()]
    )


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
    invoer: schemas.AanbiedenInput | None = None,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.BesluitResponse:
    """De "Ter accordering"-knop (kantoor). Staande goedkeuringen worden direct toegepast —
    zijn alle lagen daarmee akkoord, dan boekt de motor meteen (met alle harde checks).
    Body optioneel (factuurmatch fase 2): bevestiging "aanbieden ondanks match-afwijking"."""
    from app.documenten import boeken as boeken_module

    try:
        resultaat = service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
            match_afwijking_bevestigd=invoer.match_afwijking_bevestigd if invoer else False,
            materiaal_afwijking_bevestigd=invoer.materiaal_afwijking_bevestigd if invoer else False,
        )
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except boeken_module.MatchAfwijkingBevestigingVereist as exc:
        # Zelfde 409-vorm als de boek-route: match-cijfers in detail.match, de client toont de
        # bevestigingspop-up en herhaalt de actie mét vlag.
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
    except boeken_module.OngeldigeBoekpoging as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.ChecksNietGroen as exc:
        # Zelfde vorm als de boek-route (409 + CheckRapport in detail.checks) zodat het
        # controlescherm de check-rijen gewoon kan tonen.
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={
                "message": "Ter accordering geblokkeerd door harde checks",
                "checks": {
                    "geblokkeerd": exc.rapport.geblokkeerd,
                    "resultaten": [{"naam": r.naam, "ok": r.ok, "melding": r.melding} for r in exc.rapport.resultaten],
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
    _rol: CurrentGebruiker = Depends(vereis_kantoor_of_accordeur),
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
    _rol: CurrentGebruiker = Depends(vereis_kantoor_of_accordeur),
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
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
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


@router.post(
    "/administraties/{administratie_id}/accordering/documenten/{document_id}/herinneren",
    response_model=schemas.HerinneringResponse,
)
def herinneren(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.HerinneringResponse:
    """Handmatige extra herinnering (push, anders mail) aan de accordeur die aan de beurt is —
    max één per document per dag, geauditeerd (beheer-mini 2026-08-16)."""
    try:
        resultaat = herinnering.stuur_handmatige_herinnering(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=actor.id,
            actor_rol=actor.rol.value,
        )
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
    return schemas.HerinneringResponse(
        document_id=resultaat.document_id,
        accordeur_naam=resultaat.accordeur_naam,
        verzonden_op=resultaat.verzonden_op,
        kanaal=resultaat.kanaal,
    )


@router.get(
    "/administraties/{administratie_id}/accordering/herinneringen",
    response_model=schemas.HerinneringenOverzichtResponse,
)
def herinneringen_overzicht(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.HerinneringenOverzichtResponse:
    """ "Laatst herinnerd" per document (klantpagina-paneel + accorderingssectie)."""
    return schemas.HerinneringenOverzichtResponse(
        laatst_herinnerd=herinnering.laatst_herinnerd_per_document(administratie_id=administratie_id)
    )


@router.get(
    "/administraties/{administratie_id}/accordering/documenten/{document_id}",
    response_model=schemas.AccorderingResponse | None,
)
def accordering_van_document(
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _kantoor: CurrentGebruiker = Depends(vereis_kantoorrol),
) -> schemas.AccorderingResponse | None:
    """Accorderingshistorie op het document (controlescherm-sectie)."""
    data = service.accordering_van_document(administratie_id=administratie_id, document_id=document_id)
    return _accordering_response(data) if data is not None else None


def _naar_accordeur_vraag(
    data: vragen.VraagData,
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    administratie_naam: str | None,
    leverancier_naam: str | None,
) -> schemas.AccordeurVraagResponse:
    return schemas.AccordeurVraagResponse(
        id=data.id,
        administratie_id=administratie_id,
        administratie_naam=administratie_naam,
        document_id=data.document_id,
        document_status=data.document_status.value,
        leverancier_naam=leverancier_naam,
        totaalbedrag=data.totaalbedrag,
        vraag_tekst=data.vraag_tekst,
        gesteld_op=data.gesteld_op,
        ik_ben_aan_de_beurt=data.aan_de_beurt == actor_id,
        berichten=[
            schemas.AccordeurVraagBerichtResponse(
                id=b.id,
                auteur_id=b.auteur_id,
                van_mij=b.auteur_id == actor_id,
                tekst=b.tekst,
                geplaatst_op=b.geplaatst_op,
            )
            for b in data.berichten
        ],
    )


@router.get("/accordering/vragen", response_model=schemas.VragenAanMijResponse)
def vragen_aan_mij(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> schemas.VragenAanMijResponse:
    """ "Vragen aan u" (blok B5 26-08, mockup accordeur-vragen.html): alle open vragen die expliciet
    aan de ingelogde accordeur gericht zijn — óók over al goedgekeurde/geboekte facturen. Vragen
    op een document dat nu in zijn wachtrij staat reizen mee op de wachtrij-kaart; de app toont
    ze op één plek. Zelfde poorten als de wachtrij (accordeur-rol + voorwaarden-akkoord)."""
    if actor.rol != GebruikerRol.KLANT_ACCORDEUR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alleen voor klant-accordeurs")
    _vereis_voorwaarden_akkoord(actor)
    administraties = auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    items = vragen.vragen_aan_accordeur(actor_id=actor.id, administratie_ids=[a.id for a in administraties])
    return schemas.VragenAanMijResponse(
        items=[
            _naar_accordeur_vraag(
                a.vraag,
                actor_id=actor.id,
                administratie_id=a.administratie_id,
                administratie_naam=a.administratie_naam,
                leverancier_naam=a.leverancier_naam,
            )
            for a in items
        ]
    )


@router.post(
    "/administraties/{administratie_id}/accordering/vragen/{vraag_id}/berichten",
    response_model=schemas.AccordeurVraagResponse,
    status_code=status.HTTP_201_CREATED,
)
def vraag_beantwoorden_als_accordeur(
    administratie_id: uuid.UUID,
    vraag_id: uuid.UUID,
    invoer: schemas.AccordeurVraagBerichtInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _rol: CurrentGebruiker = Depends(vereis_kantoor_of_accordeur),
) -> schemas.AccordeurVraagResponse:
    """Antwoord van de accordeur in de thread (append-only, zelfde vraag_bericht-model). Alleen op
    een vraag die aan hém gericht is (anders 404 — het bestaan van intern overleg lekt nooit);
    "aan de beurt" wisselt naar de vraagsteller (kantoor). Afgehandeld verklaren kan de
    accordeur niet (bestaande 403-regel: alleen de vraagsteller)."""
    if actor.rol != GebruikerRol.KLANT_ACCORDEUR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alleen voor klant-accordeurs")
    _vereis_voorwaarden_akkoord(actor)
    try:
        data = vragen.plaats_bericht_als_accordeur(
            administratie_id=administratie_id, vraag_id=vraag_id, actor_id=actor.id, tekst=invoer.tekst
        )
    except vragen.VraagNietAanDezeAccordeur as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except vragen.AntwoordTekstVerplicht as exc:
        raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
    except vragen.VraagNietOpen as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    administraties = {a.id: a.naam for a in auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)}
    return _naar_accordeur_vraag(
        data,
        actor_id=actor.id,
        administratie_id=administratie_id,
        administratie_naam=administraties.get(administratie_id),
        leverancier_naam=None,
    )


@router.get("/accordering/wachtrij", response_model=schemas.WachtrijResponse)
def wachtrij(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> schemas.WachtrijResponse:
    """De accordeer-wachtrij van de ingelogde gebruiker (PWA-endpoint, scope-aanscherping
    2026-08-08: uitsluitend de wachtrij). Administraties komen uit de eigen scope-bron —
    geen scope = geen data, RLS dwingt dat op DB-niveau nogmaals af. Rolniveau-poort
    (rollen-gate-fix 2026-08-21): uitsluitend de klant-accordeur — kantoor heeft eigen
    overzichten, veldrollen hebben hier niets (de voorwaarden-poort hieronder liet elke
    niet-accordeur-rol stil door)."""
    if actor.rol != GebruikerRol.KLANT_ACCORDEUR:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Alleen voor klant-accordeurs")
    _vereis_voorwaarden_akkoord(actor)
    administraties = auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    items = service.wachtrij_voor_accordeur(actor_id=actor.id, administratie_ids=[a.id for a in administraties])
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
                afdeling_id=item.afdeling_id,
                afdeling_naam=item.afdeling_naam,
                doorbelasting=(
                    None
                    if item.doorbelasting is None
                    else [
                        schemas.WachtrijDoorbelastingRegelResponse(
                            doelentiteit_naam=r.doelentiteit_naam,
                            percentage=r.percentage,
                            netto_totaal=r.netto_totaal,
                            provisie_bedrag=r.provisie_bedrag,
                        )
                        for r in item.doorbelasting
                    ]
                ),
                vraag=(
                    _naar_accordeur_vraag(
                        item.vraag,  # type: ignore[arg-type]
                        actor_id=actor.id,
                        administratie_id=item.administratie_id,
                        administratie_naam=item.administratie_naam,
                        leverancier_naam=item.leverancier_naam,
                    )
                    if item.vraag is not None
                    else None
                ),
            )
            for item in items
        ]
    )


@router.get(
    "/administraties/{administratie_id}/accordering/staande-regels",
    response_model=schemas.StaandeRegelsResponse,
)
def staande_regels(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
    _rol: CurrentGebruiker = Depends(vereis_kantoor_of_accordeur),
) -> schemas.StaandeRegelsResponse:
    """Zelfde voorwaarden-poort als wachtrij/akkoord/afwijzen (nazorg 2026-08-11): het
    ✓✓-beheer is onderdeel van de accordeur-flow en hoort niet open te staan vóór het
    akkoord. Kantoor-rollen raakt de poort niet."""
    _vereis_voorwaarden_akkoord(actor)
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
    _rol: CurrentGebruiker = Depends(vereis_kantoor_of_accordeur),
) -> None:
    """Intrekbaar door kantoor én door de accordeur zelf (besluit 2026-08-08)."""
    _vereis_voorwaarden_akkoord(actor)
    try:
        service.trek_staande_regel_in(administratie_id=administratie_id, regel_id=regel_id, actor_id=actor.id)
    except DocumentNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except service.AccorderingFout as exc:
        raise _vertaal(exc) from exc
