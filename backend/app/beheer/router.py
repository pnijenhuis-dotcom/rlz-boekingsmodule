from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.aikosten import service as aikosten_service
from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_administratie_scope, vereis_kantoorrol
from app.beheer import schemas, service

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["beheer"], dependencies=[Depends(vereis_kantoorrol)])


@router.get(
    "/instellingen/administraties",
    response_model=schemas.AdministratieInstellingenLijstDto,
)
def administratie_instellingen_lijst(
    inclusief_gearchiveerd: bool = False,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AdministratieInstellingenLijstDto:
    """Instellingen-scherm (design-pass taak 3): alle administraties met beide schakelaars in
    één response — Beheerder-only, net als de losse per-administratie/globale endpoints.
    Gearchiveerde administraties (v2 30-08) alleen met `?inclusief_gearchiveerd=true`."""
    overzicht = service.overzicht_administratie_instellingen(inclusief_gearchiveerd=inclusief_gearchiveerd)
    return schemas.AdministratieInstellingenLijstDto(
        administraties=[
            schemas.AdministratieInstellingenDto(
                id=r.administratie_id,
                naam=r.naam,
                boeken_ingeschakeld=r.boeken_ingeschakeld,
                project_verplicht=r.project_verplicht,
                ai_extractie_ingeschakeld=r.ai_extractie_ingeschakeld,
                eigenaar_gebruiker_id=r.eigenaar_gebruiker_id,
                is_vastgoed=r.is_vastgoed,
                verkoop_autoboeken_ingeschakeld=r.verkoop_autoboeken_ingeschakeld,
                uren_meerwerk_ingeschakeld=r.uren_meerwerk_ingeschakeld,
                uren_dagmax_uren=r.uren_dagmax_uren,
                afdelingen_ingeschakeld=r.afdelingen_ingeschakeld,
                voorraad_ingeschakeld=r.voorraad_ingeschakeld,
                rlz_admin_id=r.rlz_admin_id,
                webservice_username=r.webservice_username,
                probe_groen=r.probe_groen,
                verkoopmodule_afwezig=r.verkoopmodule_afwezig,
                eerste_sync=None if r.eerste_sync is None else _eerste_sync_dto(r.eerste_sync),
                eigenaar_naam=r.eigenaar_naam,
                iban_accordeurs_aantal=r.iban_accordeurs_aantal,
                afgeletterd_event_ingeschakeld=r.afgeletterd_event_ingeschakeld,
                doorbelasting_ingeschakeld=r.doorbelasting_ingeschakeld,
                doorbelasting_doel=r.doorbelasting_doel,
                bank_autoboeken_ingeschakeld=r.bank_autoboeken_ingeschakeld,
                accordering_ingeschakeld=r.accordering_ingeschakeld,
                laatste_sync_op=r.laatste_sync_op,
                gearchiveerd_op=r.gearchiveerd_op,
                gearchiveerd_door_naam=r.gearchiveerd_door_naam,
            )
            for r in overzicht
        ]
    )


@router.post(
    "/instellingen/administraties/{administratie_id}/archiveren",
    response_model=schemas.ArchiveringResultaatDto,
)
def administratie_archiveren(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.ArchiveringResultaatDto:
    """Archiveren (🗑, v2 30-08 — nooit verwijderen): actief → false, webservice-login uit de store,
    syncs/jobs stoppen, documenten/historie blijven, registersync levert de rij niet meer. Al
    gearchiveerd = 409; onbekend = 404."""
    try:
        r = service.archiveer_administratie(actor_id=actor.id, administratie_id=administratie_id)
    except service.AdministratieGearchiveerd as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.ArchiveringResultaatDto(
        gearchiveerd_op=r.gearchiveerd_op,
        credential_ingetrokken=r.credential_ingetrokken,
        open_documenten=r.open_documenten,
    )


@router.post(
    "/instellingen/administraties/{administratie_id}/dearchiveren",
    response_model=schemas.ProbeRapportDto,
)
def administratie_dearchiveren(
    administratie_id: uuid.UUID,
    invoer: schemas.WebserviceGegevensDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.ProbeRapportDto:
    """Dearchiveren vereist een nieuwe webservice-login: admin-pin + rechten-probe groen (422 mét
    rapport, niets gewijzigd), dan credential opgeslagen en actief terug. Het wachtwoord reist
    alleen inkomend."""
    try:
        rapport = service.dearchiveer_administratie(
            actor_id=actor.id,
            administratie_id=administratie_id,
            webservice_username=invoer.webservice_username,
            wachtwoord=invoer.wachtwoord,
        )
    except service.BeheerFout as exc:
        code = status.HTTP_409_CONFLICT if "niet gearchiveerd" in str(exc) else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 — OnboardingFout (422 mét rapport) / verbindingsfout (502)
        raise _onboarding_fout(exc) from exc
    return schemas.ProbeRapportDto(rapport=rapport)


# --- Administratie toevoegen via de UI (feedbackronde 26-08 punt 5) ------------------------------
# Alle stappen Beheerder-only; het wachtwoord reist alleen inkomend en komt in geen enkele
# response, log of audit-payload terug (besluit 0012 — zie app/beheer/onboarding.py).


def _onboarding_fout(exc: Exception) -> HTTPException:
    from app.beheer.onboarding import OnboardingFout

    if isinstance(exc, OnboardingFout):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"bericht": str(exc), "rapporten": exc.rapporten},
        )
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/instellingen/administraties/verbinding-testen", response_model=schemas.VerbindingTestDto)
def administratie_verbinding_testen(
    invoer: schemas.WebserviceGegevensDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.VerbindingTestDto:
    """Stap a+c van de wizard: login proberen → gevonden administraties (naam + RLZ-id) mét
    'al aangesloten'. Niets wordt opgeslagen."""
    from app.beheer import onboarding

    try:
        gevonden = onboarding.test_verbinding(
            webservice_username=invoer.webservice_username, wachtwoord=invoer.wachtwoord
        )
    except onboarding.OnboardingFout as exc:
        raise _onboarding_fout(exc) from exc
    return schemas.VerbindingTestDto(
        administraties=[
            schemas.GevondenAdministratieDto(rlz_admin_id=g.rlz_admin_id, naam=g.naam, al_aangesloten=g.al_aangesloten)
            for g in gevonden
        ]
    )


@router.post(
    "/instellingen/administraties/aanmaken",
    response_model=schemas.AdministratiesAangemaaktDto,
    status_code=status.HTTP_201_CREATED,
)
def administraties_aanmaken(
    invoer: schemas.AdministratiesAanmakenDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.AdministratiesAangemaaktDto:
    """Stap b+d: rechten-probe verplicht groen per gekozen administratie (anders 422 mét rapport,
    niets opgeslagen) → administratie(s) + credential (envelope) + probe + audit in één
    transactie → eerste sync als achtergrondrun (status via …/eerste-sync/status)."""
    from app.beheer import onboarding

    try:
        resultaten = onboarding.maak_administraties_aan(
            actor_id=actor.id,
            webservice_username=invoer.webservice_username,
            wachtwoord=invoer.wachtwoord,
            rlz_admin_ids=invoer.rlz_admin_ids,
        )
    except onboarding.OnboardingFout as exc:
        raise _onboarding_fout(exc) from exc
    return schemas.AdministratiesAangemaaktDto(
        administraties=[
            schemas.AangemaakteAdministratieDto(
                id=r.id, naam=r.naam, rlz_admin_id=r.rlz_admin_id, probe=r.probe, sync_run_id=r.sync_run_id
            )
            for r in resultaten
        ]
    )


def _eerste_sync_dto(info) -> schemas.EersteSyncRunDto:
    return schemas.EersteSyncRunDto(
        run_id=info.run_id,
        status=info.status,
        onderdelen=info.onderdelen,
        aangevraagd_op=info.aangevraagd_op,
        beeindigd_op=info.beeindigd_op,
        fout_reden=info.fout_reden,
    )


@router.post(
    "/instellingen/administraties/{administratie_id}/eerste-sync",
    response_model=schemas.EersteSyncRunDto,
    status_code=status.HTTP_202_ACCEPTED,
)
def administratie_eerste_sync_starten(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.EersteSyncRunDto:
    """(Her)start de eerste sync als achtergrondrun — 202 + poll op …/eerste-sync/status."""
    from app.beheer import eerste_sync

    if not service.administratie_bestaat(administratie_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onbekende administratie")
    try:
        return _eerste_sync_dto(eerste_sync.start_run(administratie_id=administratie_id, actor_id=actor.id))
    except eerste_sync.EersteSyncStartFout as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get(
    "/instellingen/administraties/{administratie_id}/eerste-sync/status", response_model=schemas.EersteSyncRunDto
)
def administratie_eerste_sync_status(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.EersteSyncRunDto:
    from app.beheer import eerste_sync

    if not service.administratie_bestaat(administratie_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Onbekende administratie")
    return _eerste_sync_dto(eerste_sync.laatste_run(administratie_id))


@router.put(
    "/instellingen/administraties/{administratie_id}/webservice-gegevens", response_model=schemas.ProbeRapportDto
)
def administratie_webservice_gegevens_wijzigen(
    administratie_id: uuid.UUID,
    invoer: schemas.WebserviceGegevensDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.ProbeRapportDto:
    """Webservice-gegevens wijzigen (credential-herstel-scenario 15-08): admin-pin + probe groen
    met de nieuwe login, dan pas de upsert in de credential-store."""
    from app.beheer import onboarding

    try:
        rapport = onboarding.wijzig_webservice_gegevens(
            actor_id=actor.id,
            administratie_id=administratie_id,
            webservice_username=invoer.webservice_username,
            wachtwoord=invoer.wachtwoord,
        )
    except onboarding.OnboardingFout as exc:
        raise _onboarding_fout(exc) from exc
    return schemas.ProbeRapportDto(rapport=rapport)


@router.post(
    "/instellingen/administraties/{administratie_id}/schrijftest", response_model=schemas.SchrijftestResultaatDto
)
def administratie_schrijftest(
    administratie_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.SchrijftestResultaatDto:
    """Stap e: expliciete TEST-boeking + storno (actie 19) — nooit automatisch bij opslaan.
    Elke stap zichtbaar; geauditeerd; geweigerd als 'Boeken platformbreed' uit staat."""
    from app.beheer import onboarding
    from app.rlz.credentials import GeenRlzCredentials

    try:
        r = onboarding.voer_schrijftest_uit(actor_id=actor.id, administratie_id=administratie_id)
    except onboarding.OnboardingFout as exc:
        raise _onboarding_fout(exc) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return schemas.SchrijftestResultaatDto(
        uitkomst=r.uitkomst,
        referentie=r.referentie,
        document_id=r.document_id,
        stappen=[schemas.SchrijftestStapDto(stap=s.stap, status=s.status, detail=s.detail) for s in r.stappen],
    )


@router.get(
    "/administraties/{administratie_id}/uren-meerwerk-instelling",
    response_model=schemas.UrenMeerwerkDto,
)
def uren_meerwerk_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.UrenMeerwerkDto:
    try:
        ingeschakeld = service.haal_uren_meerwerk_ingeschakeld_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.UrenMeerwerkDto(ingeschakeld=ingeschakeld)


@router.put(
    "/administraties/{administratie_id}/uren-meerwerk-instelling",
    response_model=schemas.UrenMeerwerkDto,
)
def uren_meerwerk_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.UrenMeerwerkDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.UrenMeerwerkDto:
    """Opt-in uren & meerwerk (migratie 0056, steigerbouw-tak) — Beheerder-only, default UIT;
    alleen Universal initieel (besluit Peter 2026-08-21)."""
    try:
        ingeschakeld = service.zet_uren_meerwerk_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.UrenMeerwerkDto(ingeschakeld=ingeschakeld)


@router.get(
    "/administraties/{administratie_id}/uren-dagmax-instelling",
    response_model=schemas.UrenDagmaxDto,
)
def uren_dagmax_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.UrenDagmaxDto:
    try:
        waarde = service.haal_uren_dagmax_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.UrenDagmaxDto(dagmax_uren=waarde)


@router.put(
    "/administraties/{administratie_id}/uren-dagmax-instelling",
    response_model=schemas.UrenDagmaxDto,
)
def uren_dagmax_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.UrenDagmaxDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.UrenDagmaxDto:
    """Signaal >N uur per dag (steigerbouw-run A6): drempel per administratie, default 12."""
    try:
        waarde = service.zet_uren_dagmax(
            actor_id=actor.id, administratie_id=administratie_id, dagmax_uren=invoer.dagmax_uren
        )
    except service.BeheerFout as exc:
        code = status.HTTP_404_NOT_FOUND if "Onbekende" in str(exc) else status.HTTP_422_UNPROCESSABLE_ENTITY
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return schemas.UrenDagmaxDto(dagmax_uren=waarde)


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
    return schemas.MedewerkersLijstDto(
        medewerkers=[
            schemas.MedewerkerDto(id=m.id, naam=m.naam, is_klant_accordeur=m.is_klant_accordeur) for m in medewerkers
        ]
    )


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


@router.put(
    "/administraties/{administratie_id}/voorraad-instelling",
    response_model=schemas.VoorraadInstellingDto,
)
def voorraad_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.VoorraadInstellingDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.VoorraadInstellingDto:
    """Opt-in "Voorraad bijhouden" (blok D 28-08) — Beheerder-only, default UIT."""
    try:
        ingeschakeld = service.zet_voorraad_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.VoorraadInstellingDto(ingeschakeld=ingeschakeld)


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
    "/administraties/{administratie_id}/verkoop-autoboeken-instelling",
    response_model=schemas.VerkoopAutoboekenDto,
)
def verkoop_autoboeken_instelling_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.VerkoopAutoboekenDto:
    try:
        ingeschakeld = service.haal_verkoop_autoboeken_ingeschakeld_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.VerkoopAutoboekenDto(ingeschakeld=ingeschakeld)


@router.put(
    "/administraties/{administratie_id}/verkoop-autoboeken-instelling",
    response_model=schemas.VerkoopAutoboekenDto,
)
def verkoop_autoboeken_instelling_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.VerkoopAutoboekenDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.VerkoopAutoboekenDto:
    """Autoboek-opt-in VASTLY-VERKOOP (migratie 0051) — Beheerder-only, default UIT; aanzetten
    kan alleen voor is_vastgoed-administraties (service dwingt af → 409, geen stille no-op)."""
    try:
        ingeschakeld = service.zet_verkoop_autoboeken_ingeschakeld(
            actor_id=actor.id, administratie_id=administratie_id, ingeschakeld=invoer.ingeschakeld
        )
    except service.BeheerFout as exc:
        code = status.HTTP_409_CONFLICT if "is_vastgoed" in str(exc) else status.HTTP_404_NOT_FOUND
        raise HTTPException(status_code=code, detail=str(exc)) from exc
    return schemas.VerkoopAutoboekenDto(ingeschakeld=ingeschakeld)


@router.get(
    "/administraties/{administratie_id}/is-vastgoed",
    response_model=schemas.IsVastgoedResultaatDto,
)
def is_vastgoed_ophalen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.IsVastgoedResultaatDto:
    try:
        rij = service.haal_is_vastgoed_op(administratie_id=administratie_id)
        verkoop = service.haal_verkoop_autoboeken_ingeschakeld_op(administratie_id=administratie_id)
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.IsVastgoedResultaatDto(
        is_vastgoed=rij, verkoop_autoboeken_ingeschakeld=verkoop, verkoop_autoboeken_uitgezet=False
    )


@router.patch(
    "/administraties/{administratie_id}/is-vastgoed",
    response_model=schemas.IsVastgoedResultaatDto,
)
def is_vastgoed_zetten(
    administratie_id: uuid.UUID,
    invoer: schemas.IsVastgoedDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.IsVastgoedResultaatDto:
    """Vastgoed-koppeling per administratie (avondrun 26-08, S2-draaiboek R1) — Beheerder-only,
    audit oud→nieuw; UIT neemt verkoop-autoboeken zichtbaar mee uit (service)."""
    try:
        r = service.zet_is_vastgoed(
            actor_id=actor.id, administratie_id=administratie_id, is_vastgoed=invoer.is_vastgoed
        )
    except service.BeheerFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    return schemas.IsVastgoedResultaatDto(
        is_vastgoed=r.is_vastgoed,
        verkoop_autoboeken_ingeschakeld=r.verkoop_autoboeken_ingeschakeld,
        verkoop_autoboeken_uitgezet=r.verkoop_autoboeken_uitgezet,
    )


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
    from app.extractie import template_service  # lokaal: houdt de importgraaf van de router klein

    status_ = aikosten_service.haal_status_op()
    templates = template_service.maand_statistiek()
    return schemas.AiKostenStatusDto(
        extracties_template_maand=templates.via_template,
        extracties_ai_maand=templates.via_ai,
        templates_actief=templates.templates_actief,
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
