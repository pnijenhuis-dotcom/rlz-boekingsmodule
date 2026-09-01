from __future__ import annotations

import uuid

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.auth import service as auth_service
from app.auth.deps import CurrentGebruiker, get_current_gebruiker, vereis_administratie_scope, vereis_kantoorrol
from app.bank import afletteren, boeken, schemas, service, sync, voorstellen
from app.bank.models import BankMutatie
from app.db.session import scoped_session
from app.rlz.aangifte import StornoGeblokkeerdDoorAangifte
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.service import SyncFout

# Rolniveau-poort router-breed (rollen-gate-fix 2026-08-21): élk endpoint in deze router is
# kantoor-console — externe app-rollen (accordeur + veldrollen) krijgen 403, óók mét
# administratie-scope; nieuwe endpoints vallen automatisch onder dezelfde poort (fail-closed).
router = APIRouter(tags=["bank"], dependencies=[Depends(vereis_kantoorrol)])


def _rlz_client_voor(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _vertaal_rlz_fouten(exc: Exception) -> HTTPException:
    if isinstance(exc, GeenRlzCredentials):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    if isinstance(exc, RlzApiError):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    raise exc


def _afletter_opdracht_response(opdracht) -> schemas.AfletterOpdrachtResponse:
    """Volledige levenscyclus in het DTO (kliktest 2026-08-08): status + poging-stempel +
    verificatieresultaat uit verificatie_detail (koppelingen, voorstel_gevolgd)."""
    detail = opdracht.verificatie_detail or {}
    return schemas.AfletterOpdrachtResponse(
        id=opdracht.id,
        status=opdracht.status,
        payment_item_id=opdracht.payment_item_id,
        klaargezet_op=opdracht.klaargezet_op,
        laatste_verificatie_poging_op=opdracht.laatste_verificatie_poging_op,
        geverifieerd_op=opdracht.geverifieerd_op,
        voorstel_gevolgd=detail.get("voorstel_gevolgd"),
        uitvoering=detail.get("uitvoering"),
        koppelingen=[
            schemas.AfletterKoppelingResponse(
                rlz_document_id=k.get("rlz_document_id"),
                boekstuknummer=k.get("boekstuknummer"),
                bedrag=k.get("bedrag"),
            )
            for k in detail.get("koppelingen") or []
        ],
    )


@router.get("/bank/overzicht", response_model=schemas.BankOverzichtResponse)
def bank_overzicht(actor: CurrentGebruiker = Depends(get_current_gebruiker)) -> schemas.BankOverzichtResponse:
    """Bank-klantenlijst (mockup #bank) — uitsluitend administraties binnen de scope van de
    gebruiker (zelfde bron als GET /auth/administraties; Beheerder ziet alles). Alle
    administraties komen mee mét teller: de frontend toont klanten met open mutaties bovenaan
    en de rest compact eronder (nodig om een eerste sync te kunnen starten)."""
    administraties = auth_service.mijn_administraties(actor_id=actor.id, rol=actor.rol)
    klanten = service.bank_overzicht(
        administratie_ids_met_naam=[(a.id, a.naam) for a in administraties]
    )
    return schemas.BankOverzichtResponse(
        klanten=[
            schemas.BankKlantResponse(
                administratie_id=k.administratie_id,
                naam=k.naam,
                open_mutaties=k.open_mutaties,
                oudste_open_datum=k.oudste_open_datum,
                rekeningen=k.rekeningen,
                laatste_sync_op=k.laatste_sync_op,
                ooit_gesynchroniseerd=k.ooit_gesynchroniseerd,
            )
            for k in klanten
        ]
    )


@router.get("/administraties/{administratie_id}/bank/rekeningen", response_model=schemas.RekeningenResponse)
def rekeningen(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.RekeningenResponse:
    overzicht = service.rekeningen_overzicht(administratie_id=administratie_id)
    return schemas.RekeningenResponse(
        rekeningen=[
            schemas.RekeningResponse(
                id=r.id,
                naam=r.naam,
                iban=r.iban,
                rekening_type=r.rekening_type,
                is_kas=r.is_kas,
                saldo=r.saldo,
                saldo_datum=r.saldo_datum,
                open_mutaties=r.open_mutaties,
                heeft_aanlevering=r.heeft_aanlevering,
                laatste_import=_laatste_import_response(r.laatste_import),
                probe_fout=r.probe_fout,
            )
            for r in overzicht.rekeningen
        ],
        laatste_sync_op=overzicht.laatste_sync_op,
        ooit_gesynchroniseerd=overzicht.ooit_gesynchroniseerd,
        heeft_bankaanlevering=overzicht.heeft_bankaanlevering,
    )


def _laatste_import_response(laatste_import: dict | None) -> schemas.LaatsteImportResponse | None:
    if laatste_import is None:
        return None
    return schemas.LaatsteImportResponse(
        datum=str(laatste_import.get("Date")) if laatste_import.get("Date") else None,
        bron=(
            str(laatste_import.get("BankImportSource"))
            if laatste_import.get("BankImportSource") is not None
            else None
        ),
        type=str(laatste_import.get("BankImportType")) if laatste_import.get("BankImportType") is not None else None,
        bestandsnaam=laatste_import.get("FileName"),
    )


def _voorstel_response(item: voorstellen.MutatieMetVoorstel) -> schemas.VoorstelResponse:
    open_post = None
    if item.open_post is not None:
        open_post = schemas.OpenPostResponse(
            id=item.open_post.id,
            bedrag=item.open_post.bedrag,
            referentie=item.open_post.referentie,
            referentie2=item.open_post.referentie2,
            rlz_document_id=item.open_post.rlz_document_id,
            tegenpartij_naam=item.open_post.tegenpartij_naam,
            documentsoort=item.open_post.documentsoort,
            boekstuknummer=item.open_post.boekstuknummer,
            factuurdatum=item.open_post.factuurdatum,
        )
    return schemas.VoorstelResponse(
        soort=item.voorstel.soort.value,
        kleur=item.voorstel.kleur,
        bron=item.voorstel.bron,
        reden=item.voorstel.reden,
        payment_item_id=item.voorstel.payment_item_id,
        open_post=open_post,
        regel_id=item.voorstel.regel_id,
        regels=[
            schemas.BoekRegelResponse(
                ledger_id=regel.ledger_id,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                taxrate_id=regel.taxrate_id,
                project_id=regel.project_id,
                omschrijving=regel.omschrijving,
            )
            for regel in item.regel_boekregels
        ],
    )


@router.get(
    "/administraties/{administratie_id}/bank/rekeningen/{rekening_id}/mutaties",
    response_model=schemas.MutatiesResponse,
)
def mutaties(
    administratie_id: uuid.UUID,
    rekening_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.MutatiesResponse:
    """Open mutaties van één rekening, elk met hun voorstel (matchmotor, volgorde 1–5) +
    herkomst-chip, eventuele klaargezette afletter-opdracht en het 3×-regelvoorstel."""
    items = voorstellen.open_mutaties_met_voorstellen(
        administratie_id=administratie_id, payment_account_id=rekening_id
    )
    return schemas.MutatiesResponse(
        mutaties=[
            schemas.MutatieResponse(
                id=item.mutatie.id,
                boekdatum=item.boekdatum,
                bedrag=item.mutatie.bedrag,
                open_bedrag=item.mutatie.open_bedrag,
                tegenpartij_naam=item.mutatie.tegenpartij_naam,
                omschrijving=item.mutatie.omschrijving,
                tegenrekening_iban=item.mutatie.tegenrekening_iban,
                voorstel=_voorstel_response(item),
                afletter_opdracht=(
                    _afletter_opdracht_response(item.afletter_opdracht)
                    if item.afletter_opdracht is not None
                    else None
                ),
                regel_voorstel=(
                    schemas.RegelVoorstelResponse(
                        tegenpartij_sleutel=item.regel_voorstel.tegenpartij_sleutel,
                        ledger_id=item.regel_voorstel.ledger_id,
                        taxrate_id=item.regel_voorstel.taxrate_id,
                        aantal_boekingen=item.regel_voorstel.aantal_boekingen,
                    )
                    if item.regel_voorstel is not None
                    else None
                ),
            )
            for item in items
        ]
    )


@router.get(
    "/administraties/{administratie_id}/bank/rekeningen/{rekening_id}/afletter-opdrachten",
    response_model=schemas.AfletterHistorieResponse,
)
def afletter_opdrachten(
    administratie_id: uuid.UUID,
    rekening_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AfletterHistorieResponse:
    """Levenscyclus-lijst van afletter-opdrachten per rekening (kliktest 2026-08-08 "lijkt niets
    te doen"): ook geverifieerde/ingetrokken opdrachten blijven zichtbaar — een geverifieerde
    mutatie is niet meer open en verdween daardoor stil uit de mutatielijst."""
    overzichten = afletteren.afletter_opdrachten_voor_rekening(
        administratie_id=administratie_id, payment_account_id=rekening_id
    )
    return schemas.AfletterHistorieResponse(
        opdrachten=[
            schemas.AfletterHistorieRegelResponse(
                opdracht=_afletter_opdracht_response(o.opdracht),
                boekdatum=o.boekdatum,
                tegenpartij_naam=o.tegenpartij_naam,
                bedrag=o.bedrag,
            )
            for o in overzichten
        ]
    )


@router.post(
    "/administraties/{administratie_id}/bank/rekeningen/{rekening_id}/verifieer-afletteren",
    response_model=schemas.AfletterVerifieerResponse,
)
def verifieer_afletteren(
    administratie_id: uuid.UUID,
    rekening_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AfletterVerifieerResponse:
    """De "nu verifiëren"-knop: draait alléén de verificatieronde voor de klaargezette
    opdrachten van deze rekening (RLZ-GET's + lokale statusovergang — geen writes, geen
    volledige sync)."""
    try:
        geverifieerd = afletteren.verifieer_voor_rekening(
            administratie_id=administratie_id, payment_account_id=rekening_id
        )
    except (GeenRlzCredentials, RlzApiError) as exc:
        raise _vertaal_rlz_fouten(exc) from exc
    return schemas.AfletterVerifieerResponse(geverifieerd=geverifieerd)


@router.post("/administraties/{administratie_id}/bank/sync", response_model=schemas.BankSyncResponse)
def bank_sync_trigger(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.BankSyncResponse:
    """On-demand ververs-knop (zelfde patroon als de referentiedata-sync-triggers): leest RLZ,
    verifieert klaargezette afletter-opdrachten en draait — bij opt-in — de automatische
    vaste-regel-verwerking."""
    try:
        resultaat = sync.sync_bank_voor_administratie(administratie_id=administratie_id)
    except SyncFout as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except (GeenRlzCredentials, RlzApiError) as exc:
        raise _vertaal_rlz_fouten(exc) from exc
    return schemas.BankSyncResponse(
        rekeningen_bijgewerkt=resultaat.rekeningen.aangemaakt + resultaat.rekeningen.bijgewerkt,
        mutaties_nieuw=resultaat.mutaties.aangemaakt,
        mutaties_bijgewerkt=resultaat.mutaties.bijgewerkt,
        open_ververst=resultaat.mutaties.open_ververst,
        open_posten_bijgewerkt=resultaat.open_posten.aangemaakt + resultaat.open_posten.bijgewerkt,
        afletteren_geverifieerd=resultaat.afletteren_geverifieerd,
        afletteren_wachtend=resultaat.afletteren_wachtend,
        automatisch_afgeletterd=resultaat.automatisch_afgeletterd,
        afletter_fouten=resultaat.afletter_fouten,
        vastly_gemeld=resultaat.vastly_gemeld,
        automatisch_geboekt=resultaat.automatisch_geboekt,
        automatisch_fouten=resultaat.automatisch_fouten,
    )


@router.post(
    "/administraties/{administratie_id}/bank/mutaties/{mutatie_id}/afletteren-klaarzetten",
    response_model=schemas.AfletterKlaarzettenResponse,
    status_code=status.HTTP_201_CREATED,
)
def afletteren_klaarzetten(
    administratie_id: uuid.UUID,
    mutatie_id: uuid.UUID,
    invoer: schemas.AfletterKlaarzettenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AfletterKlaarzettenResponse:
    """Assist-model: markeer de mutatie "af te letteren in Reeleezee" met het gekozen doel-item.
    De koppeling zelf legt de mens in de RLZ-UI; de eerstvolgende sync verifieert op OpenAmount.
    Afletteren gaat bewust NIET door de klant-accorderingsflow (goedgekeurd ontwerp)."""
    try:
        uitvoering = afletteren.zet_klaar_voor_afletteren(
            administratie_id=administratie_id,
            payment_transaction_id=mutatie_id,
            payment_item_id=invoer.payment_item_id,
            actor_id=actor.id,
        )
    except (afletteren.MutatieNietGevonden, afletteren.OpenPostNietGevonden) as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except afletteren.OpdrachtBestaatAl as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except afletteren.AfletterFout as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.AfletterKlaarzettenResponse(
        opdracht_id=uitvoering.opdracht_id, uitkomst=uitvoering.uitkomst, fout=uitvoering.fout
    )


@router.post(
    "/administraties/{administratie_id}/bank/afletter-opdrachten/{opdracht_id}/voer-uit",
    response_model=schemas.AfletterKlaarzettenResponse,
)
def afletteren_voer_uit(
    administratie_id: uuid.UUID,
    opdracht_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AfletterKlaarzettenResponse:
    """'Nu afletteren' op een eerder klaargezette opdracht (assist-tijdperk of na een
    API-fout): legt de koppeling via de echte API (capture-replay 2026-08-09) mét directe
    verificatie — de RLZ-UI-instructie is daarmee vervallen."""
    try:
        uitvoering = afletteren.voer_bestaande_opdracht_uit(
            administratie_id=administratie_id, opdracht_id=opdracht_id, actor_id=actor.id
        )
    except afletteren.OpdrachtNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except GeenRlzCredentials as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except afletteren.AfletterFout as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    return schemas.AfletterKlaarzettenResponse(
        opdracht_id=uitvoering.opdracht_id, uitkomst=uitvoering.uitkomst, fout=uitvoering.fout
    )


@router.post(
    "/administraties/{administratie_id}/bank/afletter-opdrachten/{opdracht_id}/intrekken",
    status_code=status.HTTP_204_NO_CONTENT,
)
def afletteren_intrekken(
    administratie_id: uuid.UUID,
    opdracht_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        afletteren.trek_afletter_opdracht_in(
            administratie_id=administratie_id, opdracht_id=opdracht_id, actor_id=actor.id
        )
    except afletteren.OpdrachtNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except afletteren.AfletterFout as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@router.post(
    "/administraties/{administratie_id}/bank/mutaties/{mutatie_id}/direct-boeken",
    response_model=schemas.DirectBoekenResponse,
)
def direct_boeken(
    administratie_id: uuid.UUID,
    mutatie_id: uuid.UUID,
    invoer: schemas.DirectBoekenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DirectBoekenResponse:
    """Mutatie direct op grootboek boeken (bankkosten/rente/privé of vaste regel) — de knop op
    geld: alle failsafes en de bedrag-dekkingscheck draaien server-side."""
    if invoer.bron not in ("handmatig", "vaste_regel"):
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="bron moet 'handmatig' of 'vaste_regel' zijn ('automatisch' is voorbehouden aan het systeem)",
        )
    regels = [
        boeken.BankBoekRegelInput(
            ledger_id=regel.ledger_id,
            netto_bedrag=regel.netto_bedrag,
            btw_bedrag=regel.btw_bedrag,
            taxrate_id=regel.taxrate_id,
            project_id=regel.project_id,
            omschrijving=regel.omschrijving,
        )
        for regel in invoer.regels
    ]
    try:
        with _rlz_client_voor(administratie_id) as client:
            resultaat = boeken.boek_mutatie_direct(
                administratie_id=administratie_id,
                payment_transaction_id=mutatie_id,
                regels=regels,
                actor_id=actor.id,
                omschrijving=invoer.omschrijving,
                bron=boeken.BankBoekingBron(invoer.bron),
                client=client,
            )
    except boeken.BankMutatieNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except boeken.BankBoekingBestaatAl as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except boeken.BankBoekenUitgeschakeld as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except (boeken.RegelsDekkenMutatieNiet, boeken.MutatieAlAfgeletterd, boeken.BankVolumeremBereikt) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except boeken.RlzBankBoekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except (GeenRlzCredentials, RlzApiError) as exc:
        raise _vertaal_rlz_fouten(exc) from exc

    vaste_regel_aangemaakt = False
    if invoer.vaste_regel_opslaan:
        # Bevestiging van het 3×-voorstel (of het vinkje bij handmatig boeken): regel aanmaken
        # op basis van de eerste boekingsregel + de tegenpartij van de mutatie. Een al bestaande
        # regel of een onbruikbare naam is géén fout voor de boeking zelf — die is al gelukt;
        # het resultaat-veld maakt de uitkomst zichtbaar.
        with scoped_session(administratie_id) as sessie:
            mutatie = sessie.get(BankMutatie, (mutatie_id, administratie_id))
            tegenpartij_naam = mutatie.tegenpartij_naam if mutatie else None
        if tegenpartij_naam:
            try:
                service.maak_bank_regel(
                    administratie_id=administratie_id,
                    actor_id=actor.id,
                    tegenpartij_naam=tegenpartij_naam,
                    ledger_id=regels[0].ledger_id,
                    taxrate_id=regels[0].taxrate_id,
                    project_id=regels[0].project_id,
                    omschrijving=invoer.omschrijving,
                )
                vaste_regel_aangemaakt = True
            except (service.BankRegelBestaatAl, service.BankServiceFout):
                vaste_regel_aangemaakt = False

    return schemas.DirectBoekenResponse(
        boeking_id=resultaat.boeking_id,
        rlz_boekstuknummer=resultaat.rlz_boekstuknummer,
        al_eerder_geboekt=resultaat.al_eerder_geboekt,
        vaste_regel_aangemaakt=vaste_regel_aangemaakt,
    )


@router.post(
    "/administraties/{administratie_id}/bank/boekingen/{boeking_id}/storno",
    status_code=status.HTTP_204_NO_CONTENT,
)
def storno(
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    invoer: schemas.StornoInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    try:
        with _rlz_client_voor(administratie_id) as client:
            boeken.storno_bank_boeking(
                administratie_id=administratie_id,
                boeking_id=boeking_id,
                actor_id=actor.id,
                reden=invoer.reden,
                client=client,
            )
    except boeken.BankBoekingNietGevonden as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except StornoGeblokkeerdDoorAangifte as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail_tekst()) from exc
    except boeken.RlzBankBoekingMislukt as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc
    except boeken.BankBoekenFout as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except (GeenRlzCredentials, RlzApiError) as exc:
        raise _vertaal_rlz_fouten(exc) from exc


@router.get("/administraties/{administratie_id}/bank/regels", response_model=schemas.BankRegelLijstResponse)
def bank_regels(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.BankRegelLijstResponse:
    regels = service.lijst_bank_regels(administratie_id=administratie_id)
    return schemas.BankRegelLijstResponse(
        regels=[
            schemas.BankRegelResponse(
                id=regel.id,
                tegenpartij_sleutel=regel.tegenpartij_sleutel,
                tegenrekening_iban=regel.tegenrekening_iban,
                ledger_id=regel.ledger_id,
                taxrate_id=regel.taxrate_id,
                project_id=regel.project_id,
                omschrijving=regel.omschrijving,
                actief=regel.actief,
            )
            for regel in regels
        ]
    )


@router.post(
    "/administraties/{administratie_id}/bank/regels",
    response_model=schemas.BankRegelResponse,
    status_code=status.HTTP_201_CREATED,
)
def bank_regel_aanmaken(
    administratie_id: uuid.UUID,
    invoer: schemas.NieuweBankRegelInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BankRegelResponse:
    try:
        regel = service.maak_bank_regel(
            administratie_id=administratie_id,
            actor_id=actor.id,
            tegenpartij_naam=invoer.tegenpartij_naam,
            ledger_id=invoer.ledger_id,
            taxrate_id=invoer.taxrate_id,
            project_id=invoer.project_id,
            tegenrekening_iban=invoer.tegenrekening_iban,
            omschrijving=invoer.omschrijving,
        )
    except service.BankRegelBestaatAl as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except service.BankServiceFout as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return schemas.BankRegelResponse(
        id=regel.id,
        tegenpartij_sleutel=regel.tegenpartij_sleutel,
        tegenrekening_iban=regel.tegenrekening_iban,
        ledger_id=regel.ledger_id,
        taxrate_id=regel.taxrate_id,
        project_id=regel.project_id,
        omschrijving=regel.omschrijving,
        actief=regel.actief,
    )


# --- feedbackronde 25-08 deel 4: auto-verversing, relatie-koppeling, splitsen --------------------


def _sync_run_response(info) -> schemas.BankSyncRunResponse:
    return schemas.BankSyncRunResponse(
        run_id=info.run_id,
        status=info.status,
        overgeslagen=info.overgeslagen,
        laatste_sync_op=info.laatste_sync_op,
        aangevraagd_op=info.aangevraagd_op,
        beeindigd_op=info.beeindigd_op,
        resultaat=info.resultaat,
        fout_reden=info.fout_reden,
    )


@router.post(
    "/administraties/{administratie_id}/bank/sync-achtergrond",
    response_model=schemas.BankSyncRunResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def bank_sync_achtergrond(
    administratie_id: uuid.UUID,
    forceer: bool = Query(False),
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.BankSyncRunResponse:
    """Auto-verversing bij het openen van het bankscherm (besluit Peter 25-08, punt 2): cache blijft
    direct zichtbaar, de RLZ-ronde loopt op de achtergrond (202 + status-poll). Laatste sync jonger
    dan de drempel (`bank_auto_ververs_drempel_minuten`, default 5) → `overgeslagen`, geen ronde.
    `forceer=true` (blok E2, het ⟳-icoon als handmatige noodrem) slaat alleen die drempel over."""
    from app.bank import sync_run

    try:
        return _sync_run_response(
            sync_run.start_bij_openen(administratie_id=administratie_id, actor_id=actor.id, forceer=forceer)
        )
    except sync_run.BankSyncStartFout as exc:
        raise HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc)) from exc


@router.get("/administraties/{administratie_id}/bank/sync-achtergrond/status", response_model=schemas.BankSyncRunResponse)
def bank_sync_achtergrond_status(
    administratie_id: uuid.UUID, actor: CurrentGebruiker = Depends(vereis_administratie_scope)
) -> schemas.BankSyncRunResponse:
    from app.bank import sync_run

    return _sync_run_response(sync_run.laatste_run(administratie_id))


def _vertaal_relatie_fouten(exc: Exception) -> HTTPException:
    from app.bank import relatie

    if isinstance(exc, (boeken.BankMutatieNietGevonden, relatie.RelatieNietGevonden, relatie.RelatieBoekingNietGevonden)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, boeken.BankBoekenUitgeschakeld):
        return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc))
    if isinstance(exc, boeken.BankVolumeremBereikt):
        return HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))
    if isinstance(exc, (relatie.RlzRelatieBoekingMislukt,)):
        return HTTPException(status_code=status.HTTP_502_BAD_GATEWAY, detail=str(exc))
    if isinstance(exc, StornoGeblokkeerdDoorAangifte):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail_tekst())
    if isinstance(
        exc,
        (relatie.RelatieBoekingBestaatAl, relatie.BedragPastNiet, boeken.MutatieAlAfgeletterd,
         relatie.RelatieInstellingOntbreekt, relatie.RelatieBoekenFout),
    ):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (GeenRlzCredentials, RlzApiError)):
        return _vertaal_rlz_fouten(exc)
    raise exc


@router.post(
    "/administraties/{administratie_id}/bank/mutaties/{mutatie_id}/koppel-relatie",
    response_model=schemas.RelatieBoekingResponse,
    status_code=status.HTTP_201_CREATED,
)
def koppel_relatie(
    administratie_id: uuid.UUID,
    mutatie_id: uuid.UUID,
    invoer: schemas.KoppelRelatieInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.RelatieBoekingResponse:
    """Derde verwerkroute (besluit Peter 25-08, punt 3): mutatie op een crediteur/debiteur zónder
    factuur — aanbetalingsdocument + afletteren (bewezen vorm, api-verkenning 25-08)."""
    from app.bank import relatie

    try:
        with _rlz_client_voor(administratie_id) as client:
            r = relatie.boek_mutatie_op_relatie(
                administratie_id=administratie_id,
                payment_transaction_id=mutatie_id,
                relatie_soort=invoer.relatie_soort,
                entity_id=invoer.entity_id,
                actor_id=actor.id,
                client=client,
                omschrijving=invoer.omschrijving,
            )
    except Exception as exc:  # noqa: BLE001 — vertaald of opnieuw gegooid
        raise _vertaal_relatie_fouten(exc) from exc
    return schemas.RelatieBoekingResponse(
        boeking_id=r.boeking_id, rlz_document_id=r.rlz_document_id,
        rlz_boekstuknummer=r.rlz_boekstuknummer, open_restant=r.open_restant,
    )


@router.get("/administraties/{administratie_id}/bank/aanbetalingen", response_model=schemas.AanbetalingenResponse)
def aanbetalingen(
    administratie_id: uuid.UUID,
    alleen_open: bool = True,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.AanbetalingenResponse:
    """Open-posten-weergave van de relatie-koppelingen: RLZ kent de aanbetaling na het afletteren
    alleen als GB-saldo, de open post per relatie leeft hier (status geboekt = open)."""
    from app.bank import relatie

    rijen = relatie.open_aanbetalingen(administratie_id=administratie_id, alleen_open=alleen_open)
    return schemas.AanbetalingenResponse(
        aanbetalingen=[
            schemas.AanbetalingResponse(
                boeking_id=r.boeking_id, payment_transaction_id=r.payment_transaction_id,
                relatie_soort=r.relatie_soort, entity_id=r.entity_id, entity_naam=r.entity_naam,
                bedrag=r.bedrag, boekdatum=r.boekdatum, rlz_boekstuknummer=r.rlz_boekstuknummer,
                geboekt_op=r.geboekt_op, status=r.status,
            )
            for r in rijen
        ]
    )


@router.post(
    "/administraties/{administratie_id}/bank/aanbetalingen/{boeking_id}/storno",
    status_code=status.HTTP_204_NO_CONTENT,
)
def aanbetaling_storno(
    administratie_id: uuid.UUID,
    boeking_id: uuid.UUID,
    invoer: schemas.StornoInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> None:
    from app.bank import relatie

    try:
        with _rlz_client_voor(administratie_id) as client:
            relatie.storno_relatie_boeking(
                administratie_id=administratie_id, boeking_id=boeking_id, actor_id=actor.id,
                reden=invoer.reden, client=client,
            )
    except Exception as exc:  # noqa: BLE001
        raise _vertaal_relatie_fouten(exc) from exc


@router.get("/administraties/{administratie_id}/bank/debiteuren", response_model=schemas.DebiteurenZoekResponse)
def debiteuren_zoeken(
    administratie_id: uuid.UUID,
    zoek: str = "",
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.DebiteurenZoekResponse:
    """Debiteur-keuze voor de relatie-koppeling: debiteuren hebben geen lokale cache (verkoop maakt
    ze ad hoc aan), dus dit is een live RLZ-zoekactie (read-only) op naam — minimaal 2 tekens."""
    term = zoek.strip()
    if len(term) < 2:
        return schemas.DebiteurenZoekResponse(debiteuren=[])
    try:
        with _rlz_client_voor(administratie_id) as client:
            rijen = client.find_customers_by_name(name=term)
    except (GeenRlzCredentials, RlzApiError) as exc:
        raise _vertaal_rlz_fouten(exc) from exc
    uit = []
    for rij in rijen[:25]:
        try:
            uit.append(schemas.DebiteurOptieResponse(id=uuid.UUID(str(rij.get("id"))), naam=rij.get("Name") or rij.get("SearchName") or "?"))
        except ValueError:
            continue
    return schemas.DebiteurenZoekResponse(debiteuren=uit)


def _splitsing_response(r) -> schemas.SplitsingResponse:
    return schemas.SplitsingResponse(
        splitsing_id=r.splitsing_id, payment_transaction_id=r.payment_transaction_id, status=r.status,
        mutatie_bedrag=r.mutatie_bedrag, aangemaakt_op=r.aangemaakt_op,
        delen=[
            schemas.SplitsDeelResponse(
                deel_id=d.deel_id, volgnummer=d.volgnummer, soort=d.soort, bedrag=d.bedrag, status=d.status,
                fout=d.fout, bank_boeking_id=d.bank_boeking_id, afletter_opdracht_id=d.afletter_opdracht_id,
                relatie_boeking_id=d.relatie_boeking_id,
            )
            for d in r.delen
        ],
    )


def _vertaal_splits_fouten(exc: Exception) -> HTTPException:
    from app.bank import splitsen

    if isinstance(exc, (splitsen.SplitsingNietGevonden, boeken.BankMutatieNietGevonden)):
        return HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    if isinstance(exc, splitsen.SplitsingBestaatAl):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, splitsen.SplitsingOngeldig):
        return HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc))
    if isinstance(exc, StornoGeblokkeerdDoorAangifte):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=exc.detail_tekst())
    if isinstance(exc, splitsen.SplitsenFout):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, boeken.BankBoekenFout):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    if isinstance(exc, (GeenRlzCredentials, RlzApiError)):
        return _vertaal_rlz_fouten(exc)
    from app.bank import relatie

    if isinstance(exc, relatie.RelatieBoekenFout):
        return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))
    raise exc


@router.post(
    "/administraties/{administratie_id}/bank/mutaties/{mutatie_id}/splitsen",
    response_model=schemas.SplitsingResponse,
    status_code=status.HTTP_201_CREATED,
)
def splitsen_starten(
    administratie_id: uuid.UUID,
    mutatie_id: uuid.UUID,
    invoer: schemas.SplitsenInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SplitsingResponse:
    """Splitsen (besluit Peter 25-08, punt 4): delen moeten exact optellen tot het mutatiebedrag
    (server-side blokkerend, 422); uitvoering = geordende compositie van de bestaande motoren met
    het half-verwerkt-patroon (zie `app/bank/splitsen.py`)."""
    from app.bank import splitsen

    delen = [
        splitsen.DeelInvoer(
            soort=d.soort,
            bedrag=d.bedrag,
            omschrijving=d.omschrijving,
            spec={
                **({"regels": [r.model_dump(mode="json") for r in d.regels]} if d.regels is not None else {}),
                **({"payment_item_id": str(d.payment_item_id)} if d.payment_item_id else {}),
                **({"relatie_soort": d.relatie_soort} if d.relatie_soort else {}),
                **({"entity_id": str(d.entity_id)} if d.entity_id else {}),
            },
        )
        for d in invoer.delen
    ]
    try:
        with _rlz_client_voor(administratie_id) as client:
            r = splitsen.start_splitsing(
                administratie_id=administratie_id, payment_transaction_id=mutatie_id, delen=delen,
                actor_id=actor.id, client=client,
            )
    except Exception as exc:  # noqa: BLE001
        raise _vertaal_splits_fouten(exc) from exc
    return _splitsing_response(r)


@router.get(
    "/administraties/{administratie_id}/bank/rekeningen/{rekening_id}/splitsingen",
    response_model=schemas.SplitsingenResponse,
)
def splitsingen(
    administratie_id: uuid.UUID,
    rekening_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SplitsingenResponse:
    from app.bank import splitsen

    rijen = splitsen.splitsingen_voor_rekening(administratie_id=administratie_id, payment_account_id=rekening_id)
    return schemas.SplitsingenResponse(splitsingen=[_splitsing_response(r) for r in rijen])


@router.post(
    "/administraties/{administratie_id}/bank/splitsingen/{splitsing_id}/hervat",
    response_model=schemas.SplitsingResponse,
)
def splitsing_hervatten(
    administratie_id: uuid.UUID,
    splitsing_id: uuid.UUID,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SplitsingResponse:
    """Half-verwerkt herstel: de delen op wacht/fout alsnog, tegen de verse RLZ-staat."""
    from app.bank import splitsen

    try:
        with _rlz_client_voor(administratie_id) as client:
            r = splitsen.hervat_splitsing(
                administratie_id=administratie_id, splitsing_id=splitsing_id, actor_id=actor.id, client=client
            )
    except Exception as exc:  # noqa: BLE001
        raise _vertaal_splits_fouten(exc) from exc
    return _splitsing_response(r)


@router.post(
    "/administraties/{administratie_id}/bank/splitsingen/delen/{deel_id}/storno",
    response_model=schemas.SplitsingResponse,
)
def splitsing_deel_storno(
    administratie_id: uuid.UUID,
    deel_id: uuid.UUID,
    invoer: schemas.StornoInput,
    actor: CurrentGebruiker = Depends(vereis_administratie_scope),
) -> schemas.SplitsingResponse:
    from app.bank import splitsen

    try:
        with _rlz_client_voor(administratie_id) as client:
            r = splitsen.storno_deel(
                administratie_id=administratie_id, deel_id=deel_id, actor_id=actor.id, reden=invoer.reden, client=client
            )
    except Exception as exc:  # noqa: BLE001
        raise _vertaal_splits_fouten(exc) from exc
    return _splitsing_response(r)
