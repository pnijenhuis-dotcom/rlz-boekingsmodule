from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import leverancier_iban
from app.documenten.checks import (
    CheckRapport,
    CheckRegel,
    CheckResultaat,
    check_iban_wissel,
    check_regeltelling,
    check_verplichte_velden,
    voer_harde_checks_uit,
)
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentGebeurtenis,
    DocumentStatus,
    LeverancierVoorkeur,
)
from app.documenten.rlz_ids import rlz_purchase_invoice_id
from app.documenten.service import DocumentNietGevonden
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

# Zodra het document GEBOEKT is, is het RLZ-boekstuk de bron van waarheid (CLAUDE.md, kernprincipe
# 1) — het boekvoorstel wordt dan bevroren, geen bewerking (PUT) of herberekening (checks) meer via
# deze service. VERWIJDERD (soft-delete) is om een andere reden bevroren: een zachtgewist document
# hoort niet meer bewerkt te worden vóórdat het expliciet hersteld is (service.py::herstel_document)
# — anders zou een "verwijderd" document alsnog stiekem wijzigen terwijl het uit het zicht is.
_BEVROREN_STATUSSEN = frozenset({DocumentStatus.GEBOEKT, DocumentStatus.VERWIJDERD})


class BoekvoorstelFout(Exception):
    """Domeinfout in de boekvoorstel-servicelaag."""


def _controleer_niet_bevroren(document: Document) -> None:
    if document.status in _BEVROREN_STATUSSEN:
        raise BoekvoorstelFout(
            f"Document {document.id} kan niet meer gewijzigd of gecontroleerd worden "
            f"(status: {document.status.value})"
        )


@dataclass(frozen=True)
class BoekvoorstelRegelData:
    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    project_id: uuid.UUID | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    omschrijving: str | None


@dataclass(frozen=True)
class BoekvoorstelData:
    document_id: uuid.UUID
    vendor_id: uuid.UUID | None
    referentie: str | None
    factuurdatum: date | None
    totaalbedrag: Decimal | None
    rlz_boekstuknummer: str | None
    opgeslagen: bool
    regels: list[BoekvoorstelRegelData]
    # Fix 3 (2026-07-10): regels standaard samengevoegd tot één boekingsregel, keuze per
    # leverancier onthouden (LeverancierVoorkeur). `samenvoegen_toegestaan` is False bij
    # projectplicht (hard: project per regel, samenvoegen kan daar niet); `regels_samenvoegen`
    # is de effectieve stand voor dit document (voorkeur van deze crediteur, default AAN);
    # `samengevoegde_regel` is de deterministisch berekende één-regel-variant (None als er
    # geen veldvoorstel met bruikbare totalen is).
    regels_samenvoegen: bool = True
    samenvoegen_toegestaan: bool = True
    samengevoegde_regel: BoekvoorstelRegelData | None = None


def _als_decimal(waarde: str | None) -> Decimal | None:
    if not waarde:
        return None
    try:
        return Decimal(waarde)
    except InvalidOperation:
        return None


def _als_datum(waarde: str | None) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _raad_vendor_id(session: Session, *, administratie_id: uuid.UUID, leverancier_naam: str | None) -> uuid.UUID | None:
    """Best-effort suggestie op basis van een exacte (case-insensitive) naammatch tegen de
    vendor-cache — alleen bij precies één match, anders geen giswerk (consistent met CLAUDE.md's
    "nooit auto-toewijzen bij twijfel", hier toegepast op de crediteurkeuze i.p.v. de administratie-
    toewijzing)."""
    if not leverancier_naam:
        return None
    kandidaten = session.scalars(
        select(VendorCache).where(
            VendorCache.administratie_id == administratie_id,
            func.lower(VendorCache.naam) == leverancier_naam.strip().lower(),
        )
    ).all()
    if len(kandidaten) == 1:
        return kandidaten[0].id
    return None


def _regel_prefill_uit_ubl(veldvoorstel: dict) -> list[BoekvoorstelRegelData]:
    totaal_excl = _als_decimal(veldvoorstel.get("totaal_excl"))
    totaal_incl = _als_decimal(veldvoorstel.get("totaal_incl"))
    if totaal_excl is None or totaal_incl is None:
        return []
    return [
        BoekvoorstelRegelData(
            ledger_id=None,
            taxrate_id=None,
            project_id=None,
            netto_bedrag=totaal_excl,
            btw_bedrag=totaal_incl - totaal_excl,
            omschrijving=None,
        )
    ]


def _als_uuid(waarde: str | None) -> uuid.UUID | None:
    if not waarde:
        return None
    try:
        return uuid.UUID(waarde)
    except ValueError:
        return None


def _regels_prefill(veldvoorstel: dict) -> list[BoekvoorstelRegelData]:
    """AI-veldvoorstellen (bron "ai", app/extractie/controle.py) dragen echte factuurregels —
    die worden één-op-één regels in het boekvoorstel, incl. de eventuele btw-code-suggestie uit
    de sync-cache. GB (`ledger_id`) blijft bewust leeg: het boekingsgeheugen is een volgende
    sessie, en zonder geheugen is elke GB-keuze een gok. UBL-voorstellen houden hun bestaande
    één-regel-prefill uit de totalen."""
    ai_regels = veldvoorstel.get("regels")
    if not isinstance(ai_regels, list) or not ai_regels:
        return _regel_prefill_uit_ubl(veldvoorstel)
    return [
        BoekvoorstelRegelData(
            ledger_id=None,
            taxrate_id=_als_uuid(regel.get("taxrate_id")),
            project_id=None,
            netto_bedrag=_als_decimal(regel.get("netto_bedrag")),
            btw_bedrag=_als_decimal(regel.get("btw_bedrag")),
            omschrijving=regel.get("omschrijving"),
        )
        for regel in ai_regels
        if isinstance(regel, dict)
    ]


def _samengevoegde_regel(veldvoorstel: dict) -> BoekvoorstelRegelData | None:
    """Eén boekingsregel voor het hele factuurbedrag (fix 3, mockup: "één grootboek voor het
    hele factuurbedrag"): netto = gelezen totaal excl., btw = gelezen btw-bedrag (of incl −
    excl), met als vangnet de deterministische som van de geëxtraheerde regels — alleen als álle
    regelbedragen geparst zijn, nooit een gedeeltelijke som. Grootboek blijft leeg
    (boekingsgeheugen = sessie 2); btw-code alleen als alle regels dezelfde cache-suggestie
    dragen. De AI blijft altijd alle regels extraheren — dit is puur de weergave-/boekvorm."""
    regels = [r for r in veldvoorstel.get("regels") or [] if isinstance(r, dict)]

    netto = _als_decimal(veldvoorstel.get("totaal_excl"))
    if netto is None and regels:
        netto_bedragen = [_als_decimal(r.get("netto_bedrag")) for r in regels]
        if all(bedrag is not None for bedrag in netto_bedragen):
            netto = sum(netto_bedragen, Decimal(0))
    if netto is None:
        return None

    btw = _als_decimal(veldvoorstel.get("btw_bedrag"))
    if btw is None:
        totaal_incl = _als_decimal(veldvoorstel.get("totaal_incl"))
        if totaal_incl is not None:
            btw = totaal_incl - netto
    if btw is None and regels:
        btw_bedragen = [_als_decimal(r.get("btw_bedrag")) for r in regels]
        if all(bedrag is not None for bedrag in btw_bedragen):
            btw = sum(btw_bedragen, Decimal(0))

    taxrate_ids = {r.get("taxrate_id") for r in regels}
    taxrate_id = _als_uuid(next(iter(taxrate_ids))) if len(taxrate_ids) == 1 else None

    omschrijving = None
    if regels:
        factuurnummer = veldvoorstel.get("factuurnummer")
        omschrijving = (
            f"Factuur {factuurnummer} — samengevoegd ({len(regels)} regels)"
            if factuurnummer
            else f"Samengevoegd ({len(regels)} regels)"
        )

    return BoekvoorstelRegelData(
        ledger_id=None,
        taxrate_id=taxrate_id,
        project_id=None,
        netto_bedrag=netto,
        btw_bedrag=btw,
        omschrijving=omschrijving,
    )


def _project_verplicht(administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie.project_verplicht if administratie else False


def _voorkeur_samenvoegen(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None
) -> bool | None:
    if vendor_id is None:
        return None
    voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
    return voorkeur.regels_samenvoegen if voorkeur else None


def _laatste_veldvoorstel(session: Session, document_id: uuid.UUID) -> dict | None:
    """Nieuwste wint: na "opnieuw extraheren" is de laatste extractie de actuele."""
    return next(
        (
            g.detail["veldvoorstel"]
            for g in reversed(_gebeurtenissen_van(session, document_id))
            if g.detail and "veldvoorstel" in g.detail
        ),
        None,
    )


def _laad_document(session: Session, *, document_id: uuid.UUID) -> Document:
    document = session.get(Document, document_id)
    if document is None:
        raise DocumentNietGevonden(f"Onbekend document: {document_id}")
    return document


def haal_boekvoorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> BoekvoorstelData:
    """Het opgeslagen boekvoorstel, of — als er nog niets opgeslagen is — een niet-opgeslagen
    voorstel op basis van het UBL-veldvoorstel (CLAUDE.md-taak 2.1: "veldvoorstellen (UBL)
    vooringevuld waar aanwezig"). PDF-documenten hebben geen UBL-veldvoorstel en krijgen dus een
    volledig leeg voorstel — de controleur vult alles handmatig in."""
    project_verplicht = _project_verplicht(administratie_id)

    with scoped_session(administratie_id) as session:
        _laad_document(session, document_id=document_id)
        veldvoorstel = _laatste_veldvoorstel(session, document_id)

        def samenvoeg_velden(vendor_id: uuid.UUID | None) -> dict:
            """Fix 3: effectieve samenvoeg-stand (projectplicht = hard gesplitst; anders de
            onthouden leverancier-voorkeur, default AAN) + de berekende één-regel-variant."""
            if project_verplicht:
                return {"regels_samenvoegen": False, "samenvoegen_toegestaan": False, "samengevoegde_regel": None}
            voorkeur = _voorkeur_samenvoegen(session, administratie_id=administratie_id, vendor_id=vendor_id)
            return {
                "regels_samenvoegen": voorkeur if voorkeur is not None else True,
                "samenvoegen_toegestaan": True,
                "samengevoegde_regel": _samengevoegde_regel(veldvoorstel) if veldvoorstel else None,
            }

        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is not None:
            regels = session.scalars(
                select(BoekvoorstelRegel)
                .where(BoekvoorstelRegel.document_id == document_id)
                .order_by(BoekvoorstelRegel.volgnummer)
            ).all()
            return BoekvoorstelData(
                document_id=document_id,
                vendor_id=bestaand.vendor_id,
                referentie=bestaand.referentie,
                factuurdatum=bestaand.factuurdatum,
                totaalbedrag=bestaand.totaalbedrag,
                rlz_boekstuknummer=bestaand.rlz_boekstuknummer,
                opgeslagen=True,
                regels=[
                    BoekvoorstelRegelData(
                        ledger_id=r.ledger_id,
                        taxrate_id=r.taxrate_id,
                        project_id=r.project_id,
                        netto_bedrag=r.netto_bedrag,
                        btw_bedrag=r.btw_bedrag,
                        omschrijving=r.omschrijving,
                    )
                    for r in regels
                ],
                **samenvoeg_velden(bestaand.vendor_id),
            )

        # Geen opgeslagen voorstel: prefill uit het veldvoorstel (UBL deterministisch geparst, of
        # het AI-voorstel uit app/extractie/ — zelfde tijdlijn-sleutel), indien aanwezig.
        if veldvoorstel is None:
            return BoekvoorstelData(
                document_id=document_id,
                vendor_id=None,
                referentie=None,
                factuurdatum=None,
                totaalbedrag=None,
                rlz_boekstuknummer=None,
                opgeslagen=False,
                regels=[],
                **samenvoeg_velden(None),
            )

        # AI-voorstellen dragen een vendor-suggestie uit de controlelaag (exacte of fuzzy match
        # tegen de vendor-cache, alleen bij een uniek resultaat); anders de bestaande exacte
        # naammatch. In beide gevallen een voorstel dat de controleur kan overschrijven.
        suggestie = veldvoorstel.get("vendor_suggestie")
        vendor_id = _als_uuid(suggestie.get("vendor_id")) if isinstance(suggestie, dict) else None
        if vendor_id is None:
            vendor_id = _raad_vendor_id(
                session, administratie_id=administratie_id, leverancier_naam=veldvoorstel.get("leverancier_naam")
            )
        return BoekvoorstelData(
            document_id=document_id,
            vendor_id=vendor_id,
            referentie=veldvoorstel.get("factuurnummer"),
            factuurdatum=_als_datum(veldvoorstel.get("factuurdatum")),
            totaalbedrag=_als_decimal(veldvoorstel.get("totaal_incl")),
            rlz_boekstuknummer=None,
            opgeslagen=False,
            regels=_regels_prefill(veldvoorstel),
            **samenvoeg_velden(vendor_id),
        )


def _gebeurtenissen_van(session: Session, document_id: uuid.UUID) -> list[DocumentGebeurtenis]:
    return list(
        session.scalars(
            select(DocumentGebeurtenis)
            .where(DocumentGebeurtenis.document_id == document_id)
            .order_by(DocumentGebeurtenis.tijdstip)
        )
    )


def sla_boekvoorstel_op(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    factuurdatum: date | None,
    totaalbedrag: Decimal | None,
    regels: list[BoekvoorstelRegelData],
    regels_samenvoegen: bool | None = None,
) -> BoekvoorstelData:
    """`regels_samenvoegen` (fix 3) is de weergavekeuze van de controleur op het moment van
    opslaan — die wordt als voorkeur per (administratie, crediteur) onthouden. None = niet
    meegegeven (bv. oude client of geen crediteur gekozen): voorkeur blijft ongemoeid. Bij
    projectplicht wordt de keuze genegeerd — daar is per-regel hard."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_document(session, document_id=document_id)
        _controleer_niet_bevroren(document)

        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is None:
            bestaand = Boekvoorstel(document_id=document_id)
            session.add(bestaand)
        bestaand.vendor_id = vendor_id
        bestaand.referentie = referentie
        bestaand.factuurdatum = factuurdatum
        bestaand.totaalbedrag = totaalbedrag

        session.execute(delete(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
        for i, regel in enumerate(regels, start=1):
            session.add(
                BoekvoorstelRegel(
                    document_id=document_id,
                    volgnummer=i,
                    ledger_id=regel.ledger_id,
                    taxrate_id=regel.taxrate_id,
                    project_id=regel.project_id,
                    netto_bedrag=regel.netto_bedrag,
                    btw_bedrag=regel.btw_bedrag,
                    omschrijving=regel.omschrijving,
                )
            )

        if regels_samenvoegen is not None and vendor_id is not None and not _project_verplicht(administratie_id):
            _onthoud_voorkeur_samenvoegen(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                actor_id=actor_id,
                regels_samenvoegen=regels_samenvoegen,
            )

        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="boekvoorstel",
            record_id=document_id,
            actie="boekvoorstel_opgeslagen",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"referentie": referentie, "aantal_regels": len(regels)},
            administratie_id=administratie_id,
        )

    return haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)


def _onthoud_voorkeur_samenvoegen(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    actor_id: uuid.UUID,
    regels_samenvoegen: bool,
) -> None:
    """Upsert van de leverancier-voorkeur (fix 3). Alleen een échte wijziging krijgt een
    audit_event — elke opslaan-actie herhaalt de actuele stand, dat is geen handeling op de
    voorkeur zelf."""
    voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
    oud = voorkeur.regels_samenvoegen if voorkeur else None
    if oud == regels_samenvoegen:
        return
    if voorkeur is None:
        session.add(
            LeverancierVoorkeur(
                administratie_id=administratie_id, vendor_id=vendor_id, regels_samenvoegen=regels_samenvoegen
            )
        )
    else:
        voorkeur.regels_samenvoegen = regels_samenvoegen
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="leverancier_voorkeur",
        record_id=vendor_id,
        actie="leverancier_voorkeur_samenvoegen_gewijzigd",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"regels_samenvoegen": oud} if oud is not None else None,
        nieuwe_waarde={"regels_samenvoegen": regels_samenvoegen},
        administratie_id=administratie_id,
    )


def _naar_check_regels(voorstel: BoekvoorstelData) -> list[CheckRegel]:
    return [
        CheckRegel(
            ledger_id=r.ledger_id,
            taxrate_id=r.taxrate_id,
            project_id=r.project_id,
            netto_bedrag=r.netto_bedrag,
            btw_bedrag=r.btw_bedrag,
        )
        for r in voorstel.regels
    ]


def _duplicaatcheck_niet_uitgevoerd_rapport(
    *,
    administratie_id: uuid.UUID,
    voorstel: BoekvoorstelData,
    project_verplicht: bool,
    factuur_iban: str | None,
    reden: str,
) -> CheckRapport:
    """Bouwt het rapport voor het geval de RLZ-verbinding zelf al niet tot stand komt (credential-
    fout, netwerkfout) — vóórdat check_duplicaat() de kans krijgt zijn eigen RlzApiError-vangnet te
    gebruiken (app/documenten/checks.py). De lokale checks (geen RLZ nodig) draaien gewoon door,
    inclusief de IBAN-wissel-check tegen de al opgeslagen vertrouwde set (zonder RLZ-seed of
    baseline — die vergen een werkende verbinding); alleen de duplicaatcheck wordt een blokkerend,
    herkenbaar checkresultaat — nooit een kale 500 bij de gebruiker."""
    regels = _naar_check_regels(voorstel)
    vertrouwd: set[str] = set()
    if voorstel.vendor_id is not None:
        vertrouwd = leverancier_iban.vertrouwde_ibans(
            administratie_id=administratie_id, vendor_id=voorstel.vendor_id
        )
    return CheckRapport(
        (
            check_verplichte_velden(
                vendor_id=voorstel.vendor_id,
                referentie=voorstel.referentie,
                factuurdatum=voorstel.factuurdatum,
                totaalbedrag=voorstel.totaalbedrag,
                regels=regels,
                project_verplicht=project_verplicht,
            ),
            check_regeltelling(totaalbedrag=voorstel.totaalbedrag, regels=regels),
            check_iban_wissel(factuur_iban=factuur_iban, vertrouwde_ibans=vertrouwd),
            CheckResultaat("Duplicaatcheck", False, f"Duplicaatcheck kon niet uitgevoerd worden: {reden}"),
        )
    )


def voer_checks_uit(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, client: RlzClient | None = None
) -> CheckRapport:
    """Herleest het OPGESLAGEN boekvoorstel (nooit het niet-opgeslagen UBL-voorstel — de checks
    gelden over wat de controleur daadwerkelijk heeft bevestigd) en toetst de drie harde checks
    (app/documenten/checks.py). `client=None` opent een eigen RlzClient voor deze administratie
    (store/`.env`-credential-resolutie, zie app/rlz/credentials.py) — een aanroeper met een al
    open verbinding (bv. de boek-actie zelf) geeft 'm door om niet twee keer in te loggen.

    Lukt het openen van die eigen verbinding niet (credential-fout, RLZ onbereikbaar), dan wordt
    dat NOOIT een onafgevangen exception (dus geen kale 500) — zie _duplicaatcheck_niet_uitgevoerd_rapport."""
    with scoped_session(administratie_id) as session:
        document = _laad_document(session, document_id=document_id)
        _controleer_niet_bevroren(document)
        veldvoorstel = _laatste_veldvoorstel(session, document_id)

    # Factuur-IBAN uit de extractie (gestructureerd kopveld sinds 2026-07-13); de controlelaag
    # heeft 'm al mod-97-gevalideerd (app/extractie/controle.py) — oudere veldvoorstellen zonder
    # iban-sleutel geven None: geen wisselcontrole mogelijk, nooit een blok op ontbrekende data.
    factuur_iban = veldvoorstel.get("iban") if veldvoorstel else None

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        project_verplicht = administratie.project_verplicht if administratie else False

    eigen_client = client is None
    if client is None:
        try:
            rlz_admin_id = rlz_admin_id_voor(administratie_id)
            client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie de docstring hierboven
            return _duplicaatcheck_niet_uitgevoerd_rapport(
                administratie_id=administratie_id,
                voorstel=voorstel,
                project_verplicht=project_verplicht,
                factuur_iban=factuur_iban,
                reden=str(exc),
            )
    try:
        vertrouwde_ibans, baseline_vastgelegd, seed_mislukt = leverancier_iban.seed_en_baseline_voor_checks(
            administratie_id=administratie_id,
            vendor_id=voorstel.vendor_id,
            factuur_iban=factuur_iban,
            client=client,
            # Systeem-actor: seed/baseline gebeuren als bijeffect van de checks, niet als
            # bewuste gebruikershandeling — de menselijke bevestiging (bevestig_iban) draagt
            # wél de echte actor.
            actor_id=SYSTEEM_ACTOR_ID,
        )
        return voer_harde_checks_uit(
            client=client,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=_naar_check_regels(voorstel),
            eigen_rlz_document_id=rlz_purchase_invoice_id(document_id),
            project_verplicht=project_verplicht,
            factuur_iban=factuur_iban,
            vertrouwde_ibans=vertrouwde_ibans,
            iban_baseline_vastgelegd=baseline_vastgelegd,
            iban_seed_mislukt=seed_mislukt,
        )
    finally:
        if eigen_client:
            client.close()
