from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.aikosten import service as aikosten_service
from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope
from app.beheer import schemas, service

router = APIRouter(tags=["beheer"])


@router.get(
    "/instellingen/administraties",
    response_model=schemas.AdministratieInstellingenLijstDto,
)
def administratie_instellingen_lijst(
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AdministratieInstellingenLijstDto:
    """Instellingen-scherm (design-pass taak 3): alle administraties met beide schakelaars in
    één response — Beheerder-only, net als de losse per-administratie/globale endpoints."""
    overzicht = service.overzicht_administratie_instellingen()
    return schemas.AdministratieInstellingenLijstDto(
        administraties=[
            schemas.AdministratieInstellingenDto(
                id=r.administratie_id,
                naam=r.naam,
                boeken_ingeschakeld=r.boeken_ingeschakeld,
                project_verplicht=r.project_verplicht,
                ai_extractie_ingeschakeld=r.ai_extractie_ingeschakeld,
                eigenaar_gebruiker_id=r.eigenaar_gebruiker_id,
            )
            for r in overzicht
        ]
    )


@router.get(
    "/administraties/{administratie_id}/medewerkers",
    response_model=schemas.MedewerkersLijstDto,
)
def medewerkers_lijst(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.MedewerkersLijstDto:
    """Toewijsbare medewerkers voor de vraagmodal (PART B): scope-gebruikers + actieve
    Beheerders — server-side scope-gecontroleerd (dependency) en op DB-niveau (RLS op de
    koppeltabel)."""
    medewerkers = service.lijst_medewerkers(administratie_id=administratie_id)
    return schemas.MedewerkersLijstDto(medewerkers=[schemas.MedewerkerDto(id=m.id, naam=m.naam) for m in medewerkers])


@router.get(
    "/administraties/{administratie_id}/eigenaar",
    response_model=schemas.EigenaarDto,
)
def eigenaar_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.EigenaarDto:
    """Scope-check, geen Beheerder-only: wie een vraag stelt moet kunnen zien wie de default-
    toegewezene is (vraagmodal: "— eigenaar ... (standaard)")."""
    try:
        eigenaar = service.haal_eigenaar_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.EigenaarDto(eigenaar_gebruiker_id=eigenaar)


@router.put(
    "/administraties/{administratie_id}/eigenaar",
    response_model=schemas.EigenaarDto,
)
def eigenaar_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.EigenaarDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.EigenaarDto:
    """Wijzigen is Beheerder-only, net als de andere administratie-instellingen (mockup
    Instellingen "Eigenaar (krijgt vragen)")."""
    try:
        eigenaar = service.zet_eigenaar(
            actor_id=actor.id, administratie_id=administratie_id, eigenaar_gebruiker_id=invoer.eigenaar_gebruiker_id
        )
    except service.OngeldigeEigenaar as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.EigenaarDto(eigenaar_gebruiker_id=eigenaar)


@router.get(
    "/administraties/{administratie_id}/project-instelling",
    response_model=schemas.ProjectVerplichtDto,
)
def project_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.ProjectVerplichtDto:
    """Scope-check, geen Beheerder-only: elke gebruiker die het controlescherm van deze
    administratie mag openen, moet kunnen weten of de Project-kolom verplicht is (design-pass
    taak 4) — dit is geen gevoelige beheerinstelling zoals de boeken-toggle."""
    try:
        verplicht = service.haal_project_verplicht_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.ProjectVerplichtDto(verplicht=verplicht)


@router.put(
    "/administraties/{administratie_id}/project-instelling",
    response_model=schemas.ProjectVerplichtDto,
)
def project_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.ProjectVerplichtDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.ProjectVerplichtDto:
    """Wijzigen blijft wél Beheerder-only, net als de boeken-toggle."""
    try:
        verplicht = service.zet_project_verplicht(
            actor_id=actor.id, administratie_id=administratie_id, verplicht=invoer.verplicht
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.ProjectVerplichtDto(verplicht=verplicht)


@router.get(
    "/administraties/{administratie_id}/boeken-instelling",
    response_model=schemas.BoekenIngeschakeldDto,
)
def boeken_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.BoekenIngeschakeldDto:
    try:
        ingeschakeld = service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.BoekenIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.put(
    "/administraties/{administratie_id}/boeken-instelling",
    response_model=schemas.BoekenIngeschakeldDto,
)
def boeken_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.BoekenIngeschakeldDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.BoekenIngeschakeldDto:
    """Boeken-failsafe (a), per-administratie toggle — Beheerder-only (CLAUDE.md-taak 2.4)."""
    try:
        ingeschakeld = service.zet_boeken_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.BoekenIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.get(
    "/administraties/{administratie_id}/ai-extractie-instelling",
    response_model=schemas.AiExtractieIngeschakeldDto,
)
def ai_extractie_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.AiExtractieIngeschakeldDto:
    try:
        ingeschakeld = service.haal_ai_extractie_ingeschakeld_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.AiExtractieIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.put(
    "/administraties/{administratie_id}/ai-extractie-instelling",
    response_model=schemas.AiExtractieIngeschakeldDto,
)
def ai_extractie_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.AiExtractieIngeschakeldDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AiExtractieIngeschakeldDto:
    """AVG-gate voor AI-extractie (migratie 0014) — Beheerder-only; default UIT, echte
    klantfacturen pas ná de AVG-volgorde uit docs/BOUWPLAN.md."""
    try:
        ingeschakeld = service.zet_ai_extractie_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.AiExtractieIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.get(
    "/administraties/{administratie_id}/doorbelasting-instelling",
    response_model=schemas.DoorbelastingIngeschakeldDto,
)
def doorbelasting_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.DoorbelastingIngeschakeldDto:
    """Scope-check, geen Beheerder-only: de UI moet per administratie weten of de actie
    "Doorbelasten…" bestaat (zelfde overweging als de project-instelling)."""
    try:
        ingeschakeld = service.haal_doorbelasting_ingeschakeld_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.DoorbelastingIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.put(
    "/administraties/{administratie_id}/doorbelasting-instelling",
    response_model=schemas.DoorbelastingIngeschakeldDto,
)
def doorbelasting_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.DoorbelastingIngeschakeldDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.DoorbelastingIngeschakeldDto:
    """Doorbelasting-toggle (migratie 0044) — Beheerder-only, default UIT."""
    try:
        ingeschakeld = service.zet_doorbelasting_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.DoorbelastingIngeschakeldDto(ingeschakeld=ingeschakeld)


@router.get(
    "/instellingen/webhook-aflevering",
    response_model=schemas.WebhookAfleveringDto,
)
def webhook_aflevering_ophalen(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.WebhookAfleveringDto:
    return schemas.WebhookAfleveringDto(ingeschakeld=service.haal_webhook_aflevering_ingeschakeld_op())


@router.put(
    "/instellingen/webhook-aflevering",
    response_model=schemas.WebhookAfleveringDto,
)
def webhook_aflevering_zetten(
    invoer: schemas.WebhookAfleveringDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.WebhookAfleveringDto:
    """Webhook-aflevering-toggle (migratie 0025) — Beheerder-only, default UIT; naast deze
    toggle geldt ook de config-failsafe (doel-URL + HMAC-secret, zie webhook_afleveraar.py)."""
    try:
        ingeschakeld = service.zet_webhook_aflevering_ingeschakeld(actor_id=actor.id, ingeschakeld=invoer.ingeschakeld)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return schemas.WebhookAfleveringDto(ingeschakeld=ingeschakeld)


@router.get(
    "/instellingen/intake-ai",
    response_model=schemas.IntakeAiDto,
)
def intake_ai_ophalen(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.IntakeAiDto:
    try:
        return schemas.IntakeAiDto(ingeschakeld=service.haal_intake_ai_ingeschakeld_op())
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc


@router.put(
    "/instellingen/intake-ai",
    response_model=schemas.IntakeAiDto,
)
def intake_ai_zetten(
    invoer: schemas.IntakeAiDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.IntakeAiDto:
    """Intake-AI-toggle (migratie 0029) — Beheerder-only, default UIT: de platform-brede
    AVG-gate voor AI op nog-niet-toegewezen intake-documenten. Env-setting is alleen fallback
    zolang de migratie ontbreekt."""
    try:
        ingeschakeld = service.zet_intake_ai_ingeschakeld(actor_id=actor.id, ingeschakeld=invoer.ingeschakeld)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return schemas.IntakeAiDto(ingeschakeld=ingeschakeld)


def _ai_kosten_status_dto() -> schemas.AiKostenStatusDto:
    status_ = aikosten_service.haal_status_op()
    return schemas.AiKostenStatusDto(
        maand=status_.maand.strftime("%Y-%m"),
        verbruik_eur=f"{status_.verbruik_eur:.2f}",
        limiet_eur=f"{status_.limiet_eur:.2f}",
        percentage=status_.percentage,
        waarschuwing_80=status_.waarschuwing_80_op is not None,
        limiet_bereikt=status_.limiet_bereikt_op is not None,
        geblokkeerd=status_.geblokkeerd,
    )


@router.get(
    "/instellingen/ai-kosten",
    response_model=schemas.AiKostenStatusDto,
)
def ai_kosten_status(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.AiKostenStatusDto:
    """AI-kostenmeter (besluit 2026-08-14): verbruik van de lopende kalendermaand
    (Europe/Amsterdam), limiet, percentage en de eenmalige meldingen — het verbruiksblok op
    Instellingen naast de AI-gate-knop, en de bron voor de werkvoorraad-banner."""
    return _ai_kosten_status_dto()


@router.put(
    "/instellingen/ai-kosten-limiet",
    response_model=schemas.AiKostenStatusDto,
)
def ai_kosten_limiet_zetten(
    invoer: schemas.AiKostenLimietInput, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.AiKostenStatusDto:
    """Maandlimiet aanpassen — Beheerder-only, wijziging in het audit_event (migratie 0047)."""
    try:
        service.zet_ai_kosten_maandlimiet(actor_id=actor.id, maandlimiet_eur=invoer.maandlimiet_eur)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return _ai_kosten_status_dto()


@router.get(
    "/instellingen/boeken-kill-switch",
    response_model=schemas.BoekenIngeschakeldDto,
)
def kill_switch_ophalen(actor: CurrentGebruiker = Depends(require_beheerder)) -> schemas.BoekenIngeschakeldDto:
    return schemas.BoekenIngeschakeldDto(ingeschakeld=service.haal_globale_kill_switch_op())


@router.put(
    "/instellingen/boeken-kill-switch",
    response_model=schemas.BoekenIngeschakeldDto,
)
def kill_switch_zetten(
    invoer: schemas.BoekenIngeschakeldDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.BoekenIngeschakeldDto:
    """Boeken-failsafe (a), globale kill switch — Beheerder-only (CLAUDE.md-taak 2.4)."""
    try:
        ingeschakeld = service.zet_globale_kill_switch(actor_id=actor.id, ingeschakeld=invoer.ingeschakeld)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    return schemas.BoekenIngeschakeldDto(ingeschakeld=ingeschakeld)
