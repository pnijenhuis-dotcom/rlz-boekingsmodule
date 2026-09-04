"""Odoo-koppeling-endpoints (Beheerder-only, kantoor-console — vereis_kantoorrol router-breed,
rollen-gate-fix 2026-08-21). Spiegel van de RLZ-wizard-endpoints onder /instellingen/administraties."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, status

from app.auth.deps import CurrentGebruiker, require_beheerder, vereis_kantoorrol
from app.odoo import mapping as odoo_mapping
from app.odoo import schemas, service
from app.odoo.credentials import GeenOdooKoppeling

router = APIRouter(tags=["odoo"], dependencies=[Depends(vereis_kantoorrol)])


def _koppel_fout(exc: Exception) -> HTTPException:
    if isinstance(exc, service.OdooKoppelFout):
        return HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"bericht": str(exc), "rapport": exc.rapport},
        )
    if isinstance(exc, GeenOdooKoppeling):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))


@router.post("/instellingen/odoo/verbinding-testen", response_model=schemas.OdooVerbindingTestDto)
def odoo_verbinding_testen(
    invoer: schemas.OdooGegevensDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooVerbindingTestDto:
    """Stap a: sleutel proberen → companies (mét 'al gekoppeld'). Niets opgeslagen."""
    try:
        gevonden = service.test_verbinding(odoo_url=invoer.odoo_url, api_key=invoer.api_key)
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooVerbindingTestDto(
        companies=[
            schemas.GevondenCompanyDto(company_id=g.company_id, naam=g.naam, al_gekoppeld=g.al_gekoppeld)
            for g in gevonden
        ]
    )


@router.post(
    "/instellingen/odoo/koppelen", response_model=schemas.OdooGekoppeldDto, status_code=status.HTTP_201_CREATED
)
def odoo_koppelen(
    invoer: schemas.OdooKoppelenDto, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooGekoppeldDto:
    """Stap b+c+d: probe verplicht groen per company (anders 422 mét rapport, niets opgeslagen) →
    administratie + koppeling + audit → eerste stamgegevens-sync mét zichtbare run."""
    try:
        resultaten = service.koppel_administraties(
            actor_id=actor.id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            api_gebruiker=invoer.api_gebruiker,
            company_ids=invoer.company_ids,
            namen={int(k): v for k, v in invoer.namen.items() if v.strip()},
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooGekoppeldDto(
        administraties=[
            schemas.GekoppeldeAdministratieDto(
                id=r.id, naam=r.naam, company_id=r.company_id, probe=r.probe, sync_run_id=r.sync_run_id, sync=r.sync
            )
            for r in resultaten
        ]
    )


@router.get("/administraties/{administratie_id}/odoo", response_model=schemas.OdooStandDto)
def odoo_stand(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooStandDto:
    stand = service.koppelstand([administratie_id]).get(administratie_id)
    if stand is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Geen Odoo-koppeling voor deze administratie")
    return schemas.OdooStandDto(**stand.__dict__)


@router.post(
    "/administraties/{administratie_id}/odoo/overstap",
    response_model=schemas.GekoppeldeAdministratieDto,
    status_code=status.HTTP_201_CREATED,
)
def odoo_overstap(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooOverstapDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.GekoppeldeAdministratieDto:
    """Blok E, ingang B (volledige backend): een bestaande RLZ-administratie stapt over op Odoo — probe verplicht
    groen (anders 422 mét rapport, niets opgeslagen) → backend 'odoo' + sentinel + koppeling mét kanteldatum +
    mapping (incl. optionele projectmapping, "aanmaken in Odoo" = de enige Odoo-write) + audit in één transactie →
    eerste stamgegevens-sync mét zichtbare run. Response: additief `projecten_aangemaakt`/`projecten_overgeslagen`."""
    try:
        r = service.koppel_overstap(
            actor_id=actor.id,
            administratie_id=administratie_id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            company_id=invoer.company_id,
            overgangsdatum=invoer.overgangsdatum,
            api_gebruiker=invoer.api_gebruiker,
            mapping=_mapping_invoer(invoer.mapping),
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.GekoppeldeAdministratieDto(
        id=r.id,
        naam=r.naam,
        company_id=r.company_id,
        probe=r.probe,
        sync_run_id=r.sync_run_id,
        sync=r.sync,
        projecten_aangemaakt=r.projecten_aangemaakt,
        projecten_overgeslagen=list(r.projecten_overgeslagen),
        hervertaling=r.hervertaling,
    )


# --- blok A Odoo-afrondingsrun 04-09: rekening-mapping RLZ → Odoo -----------------------------------------


def _mapping_invoer(dto: schemas.OdooMappingInvoerDto) -> odoo_mapping.MappingInvoer:
    return odoo_mapping.MappingInvoer(
        grootboek=[odoo_mapping.MappingRijInvoer(rlz_id=r.rlz_id, odoo_id=r.odoo_id) for r in dto.grootboek],
        btw=[odoo_mapping.MappingRijInvoer(rlz_id=r.rlz_id, odoo_id=r.odoo_id) for r in dto.btw],
        project=[
            odoo_mapping.ProjectMappingRijInvoer(rlz_id=r.rlz_id, odoo_id=r.odoo_id, aanmaken=r.aanmaken)
            for r in dto.project
        ],
    )


def _project_dto(o: odoo_mapping.OdooProject) -> schemas.OdooProjectDto:
    return schemas.OdooProjectDto(odoo_id=o.odoo_id, lokaal_id=o.lokaal_id, naam=o.naam, code=o.code)


def _rekening_dto(o: odoo_mapping.OdooRekening) -> schemas.OdooRekeningDto:
    return schemas.OdooRekeningDto(odoo_id=o.odoo_id, lokaal_id=o.lokaal_id, code=o.code, naam=o.naam)


def _tarief_dto(o: odoo_mapping.OdooTarief) -> schemas.OdooTariefDto:
    return schemas.OdooTariefDto(
        odoo_id=o.odoo_id,
        lokaal_id=o.lokaal_id,
        naam=o.naam,
        percentage=o.percentage,
        verlegd=o.verlegd,
        synthetisch=o.synthetisch,
    )


def _stand_dto(stand: odoo_mapping.MappingStand) -> schemas.OdooMappingStandDto:
    def rij(r: odoo_mapping.MappingRij) -> schemas.MappingRijDto:
        assert r.bevestigd_op is not None
        return schemas.MappingRijDto(
            soort=r.soort,
            rlz_id=r.rlz_id,
            rlz_code=r.rlz_code,
            rlz_naam=r.rlz_naam,
            odoo_id=r.odoo_id,
            odoo_code=r.odoo_code,
            odoo_naam=r.odoo_naam,
            bron=r.bron,
            versie=r.versie,
            bevestigd_op=r.bevestigd_op,
            bevestigd_door_naam=r.bevestigd_door_naam,
        )

    return schemas.OdooMappingStandDto(
        grootboek=[rij(r) for r in stand.grootboek],
        btw=[rij(r) for r in stand.btw],
        odoo_grootboek=[_rekening_dto(o) for o in stand.odoo_grootboek],
        odoo_btw=[_tarief_dto(o) for o in stand.odoo_btw],
        laatst_bevestigd_op=stand.laatst_bevestigd_op,
        laatst_bevestigd_door_naam=stand.laatst_bevestigd_door_naam,
        project=[rij(r) for r in stand.project],
        odoo_projecten=[_project_dto(o) for o in stand.odoo_projecten],
    )


@router.post(
    "/administraties/{administratie_id}/odoo/overstap/voorbereiden",
    response_model=schemas.OdooOverstapVoorbereidingDto,
)
def odoo_overstap_voorbereiden(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooOverstapVoorbereidenDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooOverstapVoorbereidingDto:
    """Blok A (04-09): de mapping-stap van de overstap-wizard — dezelfde voorvalidaties + probe als de overstap
    (rood/ongeldig → 422 mét rapport), dan live (read-only) het Odoo-grootboek + de inkooptarieven, de
    in-gebruik-RLZ-rijen (boekingsgeheugen ∪ open boekvoorstellen) en een deterministisch voorstel per rij.
    Niets persistent."""
    try:
        v = odoo_mapping.voorbereid_overstap(
            actor_id=actor.id,
            administratie_id=administratie_id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            company_id=invoer.company_id,
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooOverstapVoorbereidingDto(
        company_naam=v.company_naam,
        probe=v.probe,
        grootboek=[
            schemas.MappingVoorstelRijDto(
                rlz_id=r.rlz.rlz_id,
                rlz_code=r.rlz.code,
                rlz_naam=r.rlz.naam,
                in_gebruik_observaties=r.rlz.in_gebruik_observaties,
                in_gebruik_open_regels=r.rlz.in_gebruik_open_regels,
                voorstel_odoo_id=r.voorstel.odoo_id if r.voorstel else None,
                voorstel_odoo_code=r.voorstel.code if r.voorstel else None,
                voorstel_odoo_naam=r.voorstel.naam if r.voorstel else None,
                reden=r.reden,
            )
            for r in v.grootboek
        ],
        btw=[
            schemas.BtwMappingVoorstelRijDto(
                rlz_id=b.rlz.rlz_id,
                rlz_naam=b.rlz.naam,
                rlz_percentage=b.rlz.percentage,
                verlegd=b.rlz.verlegd,
                in_gebruik_observaties=b.rlz.in_gebruik_observaties,
                in_gebruik_open_regels=b.rlz.in_gebruik_open_regels,
                voorstel_odoo_id=b.voorstel.odoo_id if b.voorstel else None,
                voorstel_odoo_naam=b.voorstel.naam if b.voorstel else None,
                reden=b.reden,
            )
            for b in v.btw
        ],
        odoo_grootboek=[_rekening_dto(o) for o in v.odoo_grootboek],
        odoo_btw=[_tarief_dto(o) for o in v.odoo_btw],
        telling=schemas.OdooMappingTellingDto(
            grootboek_totaal=len(v.grootboek),
            grootboek_met_voorstel=sum(1 for r in v.grootboek if r.voorstel is not None),
            btw_totaal=len(v.btw),
            btw_met_voorstel=sum(1 for b in v.btw if b.voorstel is not None),
            project_totaal=len(v.project),
            project_met_voorstel=sum(1 for pr in v.project if pr.voorstel is not None),
        ),
        project=[
            schemas.ProjectMappingVoorstelRijDto(
                rlz_id=pr.rlz.rlz_id,
                rlz_naam=pr.rlz.naam,
                rlz_nummer=pr.rlz.nummer,
                actief=pr.rlz.actief,
                in_gebruik_observaties=pr.rlz.in_gebruik_observaties,
                in_gebruik_open_regels=pr.rlz.in_gebruik_open_regels,
                voorstel_odoo_id=pr.voorstel.odoo_id if pr.voorstel else None,
                voorstel_odoo_naam=pr.voorstel.naam if pr.voorstel else None,
                reden=pr.reden,
                kan_aanmaken=odoo_mapping.kan_project_aanmaken(pr.rlz, v.analytic_plan_id),
            )
            for pr in v.project
        ],
        odoo_projecten=[_project_dto(o) for o in v.odoo_projecten],
    )


@router.get("/administraties/{administratie_id}/odoo/mapping", response_model=schemas.OdooMappingStandDto)
def odoo_mapping_stand(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooMappingStandDto:
    """De geldende rekening-mapping (hoogste versie per rij) + de Odoo-keuzelijsten uit de gesyncte cache.
    404 zonder koppeling; een Odoo-administratie zonder RLZ-verleden = lege lijsten."""
    try:
        stand = odoo_mapping.mapping_stand(administratie_id)
    except GeenOdooKoppeling as exc:
        raise _koppel_fout(exc) from exc
    return _stand_dto(stand)


@router.put(
    "/administraties/{administratie_id}/odoo/mapping/{soort}/{rlz_id}", response_model=schemas.OdooMappingStandDto
)
def odoo_mapping_corrigeren(
    administratie_id: uuid.UUID,
    soort: str,
    rlz_id: uuid.UUID,
    invoer: schemas.OdooMappingCorrectieDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooMappingStandDto:
    """Correctie per rij ná de overstap (soort grootboek/btw/project): nieuwe versie (append-only, bron 'handmatig',
    audit oud→nieuw); 422 bij een onbekende soort, een odoo_id dat niet in de gesyncte stamgegevens staat of 0 op
    grootboek/project (0 = synthetisch geen-btw, alleen btw)."""
    try:
        stand = odoo_mapping.corrigeer_rij(
            actor_id=actor.id, administratie_id=administratie_id, soort=soort, rlz_id=rlz_id, odoo_id=invoer.odoo_id
        )
    except (service.OdooKoppelFout, GeenOdooKoppeling) as exc:
        raise _koppel_fout(exc) from exc
    return _stand_dto(stand)


@router.put("/administraties/{administratie_id}/odoo/overgangsdatum", response_model=schemas.OdooStandDto)
def odoo_overgangsdatum(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooOvergangsdatumDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooStandDto:
    """De KANTELDATUM van een schrijvende Odoo-koppeling zetten/verschuiven — altijd 200 mét audit oud→nieuw (de
    C1-409 is vervallen, slotstuk 04-09: géén poort op documenten meer); alleen-lezen/geen koppeling = 422."""
    try:
        stand = service.wijzig_overgangsdatum(
            actor_id=actor.id, administratie_id=administratie_id, overgangsdatum=invoer.overgangsdatum
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooStandDto(**stand.__dict__)


@router.put("/administraties/{administratie_id}/odoo", response_model=schemas.OdooProbeDto)
def odoo_wijzigen(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooWijzigDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooProbeDto:
    """Odoo-gegevens wijzigen / sleutel roteren / herprobe — probe-gated (groen vereist vóór opslaan)."""
    try:
        p = service.wijzig_koppeling(
            actor_id=actor.id,
            administratie_id=administratie_id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            api_gebruiker=invoer.api_gebruiker,
        )
    except (service.OdooKoppelFout, GeenOdooKoppeling) as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooProbeDto(
        groen=p.groen, rapport=p.rapport, company_naam=p.company_naam, versie=p.versie, lock_dates=p.lock_dates
    )


@router.post(
    "/administraties/{administratie_id}/odoo/leesbron",
    response_model=schemas.OdooProbeDto,
    status_code=status.HTTP_201_CREATED,
)
def odoo_leesbron_koppelen(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooLeesbronKoppelenDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooProbeDto:
    """Blok D: Odoo als LEESBRON voor een RLZ-administratie (voorraad-uitstroom vanaf de knip) — leesprobe
    verplicht groen, koppeling is hard alleen-lezen (nooit een write op die company)."""
    try:
        p = service.koppel_leesbron(
            actor_id=actor.id,
            administratie_id=administratie_id,
            odoo_url=invoer.odoo_url,
            api_key=invoer.api_key,
            company_id=invoer.company_id,
            voorraad_knip_datum=invoer.voorraad_knip_datum,
            api_gebruiker=invoer.api_gebruiker,
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooProbeDto(groen=p.groen, rapport=p.rapport, company_naam=p.company_naam, versie=p.versie)


@router.put("/administraties/{administratie_id}/odoo/leesbron", response_model=schemas.OdooStandDto)
def odoo_leesbron_knip(
    administratie_id: uuid.UUID,
    invoer: schemas.OdooLeesbronKnipDto,
    actor: CurrentGebruiker = Depends(require_beheerder),
) -> schemas.OdooStandDto:
    """De voorraad-knip zetten/verschuiven/wissen (audit oud→nieuw)."""
    try:
        stand = service.wijzig_leesbron(
            actor_id=actor.id, administratie_id=administratie_id, voorraad_knip_datum=invoer.voorraad_knip_datum
        )
    except service.OdooKoppelFout as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooStandDto(**stand.__dict__)


@router.post("/administraties/{administratie_id}/odoo/sync", response_model=schemas.OdooSyncResultaatDto)
def odoo_sync_nu(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooSyncResultaatDto:
    """Stamgegevens opnieuw syncen (zichtbaar als run, zelfde model als de eerste sync)."""
    try:
        run_id, onderdelen = service.eerste_sync(administratie_id=administratie_id, actor_id=actor.id)
    except GeenOdooKoppeling as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooSyncResultaatDto(run_id=run_id, onderdelen=onderdelen)


@router.post("/administraties/{administratie_id}/odoo/producten-brug", response_model=schemas.OdooProductBrugDto)
def odoo_producten_brug(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(require_beheerder)
) -> schemas.OdooProductBrugDto:
    """Materiaalcatalogus → product.product (blok B): lookup eerst, idempotente aanmaak, uitkomst per product."""
    from app.odoo import producten

    try:
        uitkomst = producten.leg_brug(administratie_id=administratie_id, actor_id=actor.id)
    except GeenOdooKoppeling as exc:
        raise _koppel_fout(exc) from exc
    return schemas.OdooProductBrugDto(
        gevonden=uitkomst.gevonden, aangemaakt=uitkomst.aangemaakt, overgeslagen=list(uitkomst.overgeslagen)
    )
