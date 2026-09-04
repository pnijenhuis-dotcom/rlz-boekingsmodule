from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from app.backends.registry import inkoop_port_voor, standaard_regels_samenvoegen
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import leverancier_iban
from app.documenten.checks import (
    CheckRapport,
    CheckRegel,
    CheckResultaat,
    check_afdeling,
    check_buitenland_tarief_crediteurkaart,
    check_iban_wissel,
    check_regeltelling,
    check_verplichte_velden,
    check_vervaldatum,
    vervaldatum_signaal,
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
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.documenten.service import DocumentNietGevonden
from app.projectverdeling.data import ProjectverdelingData
from app.rlz.client import RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)

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
            f"Document {document.id} kan niet meer gewijzigd of gecontroleerd worden (status: {document.status.value})"
        )


@dataclass(frozen=True)
class BoekvoorstelRegelData:
    ledger_id: uuid.UUID | None
    taxrate_id: uuid.UUID | None
    project_id: uuid.UUID | None
    netto_bedrag: Decimal | None
    btw_bedrag: Decimal | None
    omschrijving: str | None
    # DB-id van de opgeslagen regel (boekvoorstel_regel.id) — alleen gevuld voor persisted
    # regels; prefills (AI/UBL, nog niet opgeslagen) hebben er geen. De doorbelasting-verdeling
    # (blok 3) sleutelt hierop (bron_regel_id), en die bestaat alleen op GEBOEKTE documenten.
    id: uuid.UUID | None = None
    # Herkomst van de btw-code (feedbackronde 26-08 punt 3): "factuur" = deterministisch uit
    # netto/btw van de gelezen regel afgeleid (prefill, nog niet opgeslagen). None = leeg of van
    # de mens/het geheugen. Alleen gevuld op prefill-regels — ná opslaan is de keuze van de
    # controleur (zelfde regel als de AI-zekerheidschips). Sinds blok E 04-09 óók "standaard" = de
    # btw-default van de administratie (vult alleen wat factuur én leverancier-geheugen leeg lieten).
    btw_bron: str | None = None
    # Herkomst van het grootboek-voorstel per regel (blok D 04-09, app/geheugen/regel_gb.py):
    # "geheugen" (groen, app-bevestigd) | "geheugen_seed" / "geheugen_conflict" (oranje) | "ai"
    # (oranje, AI-classificatie tegen de historische grootboeken van deze leverancier). None = leeg of
    # van de mens. Alleen gevuld op prefill-regels; `gb_voorstel_detail` = tooltip-tekst.
    gb_bron: str | None = None
    gb_voorstel_detail: str | None = None


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
    # Tegenboek-pad (migratie 0061): bepaalt het RLZ-GUID van de (her)boeking — cyclus 0 is de
    # oorspronkelijke boeking, elke "tegenboeken én opnieuw boeken" verhoogt 'm.
    boek_cyclus: int = 0
    # "Btw verlegd"-vermelding uit de laatste extractie (punt 3, 26-08) — HINT voor de
    # controleur bij 0%-regels, nooit een invulling. None = niets gelezen of geen veldvoorstel.
    btw_verlegd_vermelding: str | None = None
    # Vervaldatum (C1 26-08): kopveld uit de scan; None = leeg (RLZ leidt DueDate dan zelf af).
    vervaldatum: date | None = None
    # Betalingskenmerk (Odoo-adapter fase 1, migratie 0101): kopveld uit de scan (sentinel-patroon) →
    # Odoo `payment_reference`; RLZ negeert het. None = niet gelezen.
    betalingskenmerk: str | None = None
    # Oranje signaal bij een implausibele betaaltermijn (> 90 dagen) — checks.vervaldatum_signaal.
    vervaldatum_signaal: str | None = None
    # Afdeling (blok A 28-08, migratie 0084): de handmatige keuze op dit document. `afdeling_prefill`
    # = vorige keuze voor deze leverancier (alleen zolang het document zelf nog geen afdeling heeft;
    # herkomst-chip "🧠 vorige keuze bij <leverancier>") — een voorstel, de mens beslist.
    afdeling_id: uuid.UUID | None = None
    afdeling_prefill_id: uuid.UUID | None = None
    afdeling_prefill_leverancier: str | None = None
    # Projectverdeling pro rato omzet (blok C 04-09, migratie 0107): vaste regels + restant pro rato over de
    # projecten mét omzet; None = niet van toepassing. Voorstel = live herrekend, geboekt = bevroren snapshot.
    # De adapters (RLZ: regels splitsen; Odoo: analytic_distribution) lezen hieruit — app/projectverdeling/.
    projectverdeling: ProjectverdelingData | None = None


def _met_projectverdeling(
    session: Session, administratie_id: uuid.UUID, project_verplicht: bool, data: BoekvoorstelData
) -> BoekvoorstelData:
    """Koppelpunt blok C: zet `projectverdeling` op het (frozen) voorstel — lazy import, geen kring."""
    from app.projectverdeling import service as projectverdeling_service

    return projectverdeling_service.verrijk_boekvoorstel(
        session, administratie_id=administratie_id, data=data, project_verplicht=project_verplicht
    )


def _project_verplicht_per_regel(project_verplicht: bool, voorstel: BoekvoorstelData) -> bool:
    """Draagt het document een ACTIEVE projectverdeling, dan toetst "Verplichte velden" het project niet meer per
    regel — de aanvullende check "Projectverdeling" (blokkeert tot de verdeling exact sluit) is dan de poort.
    Nooit een verzwakking: zonder verdeling geldt de projectplicht per regel onverkort."""
    if voorstel.projectverdeling is not None and voorstel.projectverdeling.actief:
        return False
    return project_verplicht


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
            btw_bron=_btw_bron(regel),
        )
        for regel in ai_regels
        if isinstance(regel, dict)
    ]


def _btw_bron(regel: dict) -> str | None:
    """Alleen "factuur" als de regel ook écht een afgeleide btw-code draagt."""
    return "factuur" if regel.get("btw_bron") == "factuur" and _als_uuid(regel.get("taxrate_id")) else None


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
    btw_bron = "factuur" if taxrate_id is not None and all(_btw_bron(r) == "factuur" for r in regels) else None

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
        btw_bron=btw_bron,
    )


def _verlegd_vermelding(veldvoorstel: dict | None) -> str | None:
    waarde = veldvoorstel.get("btw_verlegd_vermelding") if veldvoorstel else None
    return waarde if isinstance(waarde, str) and waarde else None


def _gelezen_totalen(veldvoorstel: dict | None) -> tuple[Decimal | None, Decimal | None]:
    """(totaal excl., factuur-btw-bedrag) zoals GELEZEN in het laatste veldvoorstel — voor de
    regeltelling-check (bugfix 04-09, Huvanco). Het boekvoorstel zelf draagt alleen het incl-totaal
    (mens-veld, blijft leidend voor de incl-kant); de excl-/btw-kant komt uit de extractie: AI-/
    template-voorstel `totaal_excl` + `btw_bedrag`, UBL `totaal_excl` + `totaal_btw`. Geen
    veldvoorstel = (None, None) → de check valt terug op de incl-vergelijking of meldt expliciet dat
    er niets te toetsen is (nooit stil excl-vs-incl)."""
    if not veldvoorstel:
        return None, None
    totaal_excl = _als_decimal(veldvoorstel.get("totaal_excl"))
    factuur_btw = _als_decimal(veldvoorstel.get("btw_bedrag")) or _als_decimal(veldvoorstel.get("totaal_btw"))
    return totaal_excl, factuur_btw


def _rlz_leesclient(administratie_id: uuid.UUID) -> RlzClient:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)


def _project_verplicht(administratie_id: uuid.UUID) -> bool:
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        return administratie.project_verplicht if administratie else False


def _voorkeur_samenvoegen(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None) -> bool | None:
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
    standaard_samenvoegen = standaard_regels_samenvoegen(administratie_id)

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
                # Default zonder leverancier-voorkeur = backend-capability (RLZ AAN; Odoo UIT — regelniveau-
                # data moet in Odoo landen, eis Peter 03-09); de leverancier-voorkeur wint altijd.
                "regels_samenvoegen": voorkeur if voorkeur is not None else standaard_samenvoegen,
                "samenvoegen_toegestaan": True,
                "samengevoegde_regel": _samengevoegde_regel(veldvoorstel) if veldvoorstel else None,
            }

        def afdeling_velden(vendor_id: uuid.UUID | None, huidige_afdeling_id: uuid.UUID | None) -> dict:
            """Blok A 28-08: prefill uit het leverancier-geheugen alleen als er nog geen keuze op het
            document staat; toggle uit = niets (het veld is dan onzichtbaar)."""
            from app.afdelingen.service import afdelingen_ingeschakeld_in_sessie, prefill_voor_vendor

            if not afdelingen_ingeschakeld_in_sessie(session, administratie_id):
                return {"afdeling_id": huidige_afdeling_id}
            prefill = (
                prefill_voor_vendor(session, administratie_id=administratie_id, vendor_id=vendor_id)
                if huidige_afdeling_id is None
                else None
            )
            return {
                "afdeling_id": huidige_afdeling_id,
                "afdeling_prefill_id": prefill.afdeling_id if prefill else None,
                "afdeling_prefill_leverancier": prefill.leverancier_naam if prefill else None,
            }

        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is not None:
            regels = session.scalars(
                select(BoekvoorstelRegel)
                .where(BoekvoorstelRegel.document_id == document_id)
                .order_by(BoekvoorstelRegel.volgnummer)
            ).all()
            return _met_projectverdeling(session, administratie_id, project_verplicht, BoekvoorstelData(
                document_id=document_id,
                vendor_id=bestaand.vendor_id,
                referentie=bestaand.referentie,
                factuurdatum=bestaand.factuurdatum,
                vervaldatum=bestaand.vervaldatum,
                vervaldatum_signaal=vervaldatum_signaal(
                    factuurdatum=bestaand.factuurdatum, vervaldatum=bestaand.vervaldatum
                ),
                betalingskenmerk=bestaand.betalingskenmerk,
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
                        id=r.id,
                    )
                    for r in regels
                ],
                boek_cyclus=bestaand.boek_cyclus,
                btw_verlegd_vermelding=_verlegd_vermelding(veldvoorstel),
                **samenvoeg_velden(bestaand.vendor_id),
                **afdeling_velden(bestaand.vendor_id, bestaand.afdeling_id),
            ))

        # Geen opgeslagen voorstel: prefill uit het veldvoorstel (UBL deterministisch geparst, of
        # het AI-voorstel uit app/extractie/ — zelfde tijdlijn-sleutel), indien aanwezig.
        if veldvoorstel is None:
            return _met_projectverdeling(session, administratie_id, project_verplicht, BoekvoorstelData(
                document_id=document_id,
                vendor_id=None,
                referentie=None,
                factuurdatum=None,
                totaalbedrag=None,
                rlz_boekstuknummer=None,
                opgeslagen=False,
                regels=[],
                **samenvoeg_velden(None),
                **afdeling_velden(None, None),
            ))

        # AI-voorstellen dragen een vendor-suggestie uit de controlelaag (exacte of fuzzy match
        # tegen de vendor-cache, alleen bij een uniek resultaat); anders de bestaande exacte
        # naammatch. In beide gevallen een voorstel dat de controleur kan overschrijven.
        suggestie = veldvoorstel.get("vendor_suggestie")
        vendor_id = _als_uuid(suggestie.get("vendor_id")) if isinstance(suggestie, dict) else None
        if vendor_id is None:
            vendor_id = _raad_vendor_id(
                session, administratie_id=administratie_id, leverancier_naam=veldvoorstel.get("leverancier_naam")
            )
        # Blok D + E (medewerker-wensen 04-09): regel-GB-voorstel (regel-geheugen → persistente
        # AI-classificatie → leeg) en btw-default van de administratie (factuur → leverancier-geheugen →
        # default → leeg) — uitsluitend op dit prefill-pad; een opgeslagen keuze van de mens wint altijd.
        from app.documenten import regel_prefill  # lokaal: regel_prefill leest de dataclass hierboven

        samenvoeg = samenvoeg_velden(vendor_id)
        prefill_regels, samenvoeg["samengevoegde_regel"] = regel_prefill.verrijk_prefill(
            session,
            administratie_id=administratie_id,
            document_id=document_id,
            vendor_id=vendor_id,
            regels=_regels_prefill(veldvoorstel),
            samengevoegde_regel=samenvoeg["samengevoegde_regel"],
        )
        return _met_projectverdeling(session, administratie_id, project_verplicht, BoekvoorstelData(
            document_id=document_id,
            vendor_id=vendor_id,
            referentie=veldvoorstel.get("factuurnummer"),
            factuurdatum=_als_datum(veldvoorstel.get("factuurdatum")),
            vervaldatum=_als_datum(veldvoorstel.get("vervaldatum")),
            vervaldatum_signaal=vervaldatum_signaal(
                factuurdatum=_als_datum(veldvoorstel.get("factuurdatum")),
                vervaldatum=_als_datum(veldvoorstel.get("vervaldatum")),
            ),
            betalingskenmerk=(veldvoorstel.get("betalingskenmerk") or None),
            totaalbedrag=_als_decimal(veldvoorstel.get("totaal_incl")),
            rlz_boekstuknummer=None,
            opgeslagen=False,
            regels=prefill_regels,
            btw_verlegd_vermelding=_verlegd_vermelding(veldvoorstel),
            **samenvoeg,
            **afdeling_velden(vendor_id, None),
        ))


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
    vervaldatum: date | None = None,
    afdeling_id: uuid.UUID | None = None,
    betalingskenmerk: str | None = None,
) -> BoekvoorstelData:
    """`regels_samenvoegen` (fix 3) is de weergavekeuze van de controleur op het moment van
    opslaan — die wordt als voorkeur per (administratie, crediteur) onthouden. None = niet
    meegegeven (bv. oude client of geen crediteur gekozen): voorkeur blijft ongemoeid. Bij
    projectplicht wordt de keuze genegeerd — daar is per-regel hard.

    `afdeling_id` (blok A 28-08): de handmatige afdelingskeuze; moet een afdeling van déze
    administratie zijn (gearchiveerd mag opgeslagen worden — de check blokkeert dan zichtbaar).
    Mét crediteur wordt de keuze als leverancier-geheugen onthouden (laatste wint). Verandert de
    afdeling terwijl een accorderingsronde open staat, dan vervalt die ronde zichtbaar mét reden
    (zelfde regel als een configuratiewijziging)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = _laad_document(session, document_id=document_id)
        _controleer_niet_bevroren(document)

        if afdeling_id is not None:
            from app.afdelingen.models import Afdeling

            afdeling = session.get(Afdeling, afdeling_id)
            if afdeling is None or afdeling.administratie_id != administratie_id:
                raise BoekvoorstelFout("Onbekende afdeling voor deze administratie")

        bestaand = session.get(Boekvoorstel, document_id)
        if bestaand is None:
            bestaand = Boekvoorstel(document_id=document_id)
            session.add(bestaand)
        oude_afdeling_id = bestaand.afdeling_id
        bestaand.vendor_id = vendor_id
        bestaand.referentie = referentie
        bestaand.factuurdatum = factuurdatum
        bestaand.vervaldatum = vervaldatum
        bestaand.betalingskenmerk = (" ".join(betalingskenmerk.split()) or None) if betalingskenmerk else None
        bestaand.afdeling_id = afdeling_id
        if afdeling_id is not None and vendor_id is not None:
            from app.afdelingen.service import onthoud_keuze

            onthoud_keuze(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                afdeling_id=afdeling_id,
                document_id=document_id,
                actor_id=actor_id,
            )
        if oude_afdeling_id != afdeling_id and document.status == DocumentStatus.TER_ACCORDERING:
            from app.accordering.service import laat_ronde_vervallen_bij_afdelingwijziging

            laat_ronde_vervallen_bij_afdelingwijziging(
                session, administratie_id=administratie_id, document_id=document_id, actor_id=actor_id
            )
        # Punt 14 (28-08): het btw-/KvK-nummer van de factuur per crediteur onthouden zodra de mens de
        # crediteur bevestigt (opslaan mét vendor) — voedt nummer-match, cross-crediteur-check en de
        # dubbel-signalering. Lazy import: crediteur_kenmerk gebruikt de extractie-controlelaag.
        if vendor_id is not None:
            from app.documenten.crediteur_kenmerk import neem_over_uit_veldvoorstel

            neem_over_uit_veldvoorstel(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                veldvoorstel=_laatste_veldvoorstel(session, document_id),
                document_id=document_id,
                actor_id=actor_id,
            )
        bestaand.totaalbedrag = totaalbedrag

        # Klaargezette doorbelasting (besluit 25-08) verwijst per regel-id — over de
        # delete+insert heen meenemen per volgnummer. Lazy import: doorbelasting.service
        # gebruikt deze module-familie (geen kringimport op moduleniveau).
        from app.doorbelasting import service as doorbelasting_service

        verdeling_snapshot = doorbelasting_service.neem_klaargezette_verdeling_los(session, document_id=document_id)
        session.execute(delete(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id == document_id))
        nieuwe_regels: list[BoekvoorstelRegel] = []
        for i, regel in enumerate(regels, start=1):
            nieuwe_regel = BoekvoorstelRegel(
                document_id=document_id,
                volgnummer=i,
                ledger_id=regel.ledger_id,
                taxrate_id=regel.taxrate_id,
                project_id=regel.project_id,
                netto_bedrag=regel.netto_bedrag,
                btw_bedrag=regel.btw_bedrag,
                omschrijving=regel.omschrijving,
            )
            session.add(nieuwe_regel)
            nieuwe_regels.append(nieuwe_regel)
        if verdeling_snapshot is not None:
            session.flush()
            doorbelasting_service.zet_klaargezette_verdeling_terug(
                session,
                snapshot=verdeling_snapshot,
                nieuwe_regels={r.volgnummer: r.id for r in nieuwe_regels},
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
            nieuwe_waarde={
                "referentie": referentie,
                "aantal_regels": len(regels),
                "afdeling_id": str(afdeling_id) if afdeling_id else None,
            },
            administratie_id=administratie_id,
        )

    # Factuurmatch (fase 2): ná élke voorstel-opslag herberekenen — crediteur, factuurdatum en
    # regelbedragen sturen alle drie de match. Post-commit en onder de systeem-actor (de
    # lees-policy op de bureau-tarieven is actor-gebonden, 0057); een fout is een gelogde
    # waarschuwing — de match is signalering, nooit een blokkade van de opslag.
    from app.uren import factuurmatch_pipeline  # lokaal: houdt de importgraaf klein

    try:
        factuurmatch_pipeline.draai_match_voor_document(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — de match is signalering, nooit een blokkade
        logger.exception("Factuurmatch-run na voorstel-opslag mislukt voor document %s", document_id)
    # Materiaalmatch (steigerbouw-run D6): crediteur, project en factuurdatum sturen de toets.
    from app.materiaal import match as materiaalmatch  # lokaal: houdt de importgraaf klein

    try:
        materiaalmatch.draai_materiaalmatch(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — signalering, nooit een blokkade
        logger.exception("Materiaalmatch-run na voorstel-opslag mislukt voor document %s", document_id)

    # Duplicaatsignaal (besluit Peter 25-08, deel 2 punt 6): herberekenen bij elke veldwijziging
    # — crediteur, referentie en totaal sturen de RLZ-duplicaatquery. Post-commit; signalering
    # (de live check op het boekmoment blijft bindend), fouten zichtbaar als 'onbekend'.
    from app.documenten import duplicaatsignaal  # lokaal: houdt de importgraaf klein

    duplicaatsignaal.bereken_duplicaatsignaal_stil(administratie_id=administratie_id, document_id=document_id)

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


def _naar_check_regels(
    voorstel: BoekvoorstelData, taxrate_percentages: dict[uuid.UUID, Decimal | None] | None = None
) -> list[CheckRegel]:
    """Boekvoorstelregels → CheckRegel. Een LEGE btw op een opgeslagen regel is in het boekvoorstel
    van oudsher "geen btw" (verlegd/vrijgesteld — de motoren boeken TaxAmount 0, zie
    tests/documenten/test_boeken.py::TestBoekDocumentRegelZonderBtw); pas sinds de regelsom-bugfix
    04-09 (Huvanco) telt een lege btw als ONBEKEND. Beide kloppen, afhankelijk van het tarief: bij een
    gesynct 0%-/verlegd-tarief (percentage 0 of zonder percentage in de cache) is leeg = 0 (bekend);
    bij een tarief mét percentage > 0, een niet-gesynct tarief óf géén tarief is leeg = niet gelezen —
    de regeltelling toetst dan netto-vs-netto (tak 2) of meldt expliciet wat ontbreekt (tak 4), nooit
    stil Σnetto tegen een incl-totaal. `taxrate_percentages` = de gesyncte cache (id → percentage)."""
    percentages = taxrate_percentages or {}

    def btw_van(r: BoekvoorstelRegelData) -> Decimal | None:
        if r.btw_bedrag is not None:
            return r.btw_bedrag
        if r.taxrate_id is None or r.taxrate_id not in percentages:
            return None
        pct = percentages[r.taxrate_id]
        return Decimal(0) if pct is None or pct == 0 else None

    return [
        CheckRegel(
            ledger_id=r.ledger_id,
            taxrate_id=r.taxrate_id,
            project_id=r.project_id,
            netto_bedrag=r.netto_bedrag,
            btw_bedrag=btw_van(r),
        )
        for r in voorstel.regels
    ]


def _taxrate_percentages(administratie_id: uuid.UUID) -> dict[uuid.UUID, Decimal | None]:
    """Tariefpercentages uit de gesyncte taxrate_cache (lokaal, geen RLZ-call) — voor de
    lege-btw-interpretatie in `_naar_check_regels`."""
    from app.sync.models import TaxRateCache

    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(TaxRateCache.id, TaxRateCache.percentage).where(TaxRateCache.administratie_id == administratie_id)
        ).all()
    return {r.id: r.percentage for r in rijen}


def _taxrate_namen(administratie_id: uuid.UUID) -> dict[uuid.UUID, str]:
    """Tariefnamen uit de gesyncte taxrate_cache voor de buitenland-tarief-check (blok A 31-08) —
    lokaal, geen RLZ-call: draait dus ook in de storings-tak mee."""
    from app.sync.models import TaxRateCache

    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(TaxRateCache.id, TaxRateCache.naam).where(TaxRateCache.administratie_id == administratie_id)
        ).all()
    return {r.id: r.naam for r in rijen if r.naam}


def _duplicaatcheck_niet_uitgevoerd_rapport(
    *,
    administratie_id: uuid.UUID,
    voorstel: BoekvoorstelData,
    project_verplicht: bool,
    factuur_iban: str | None,
    factuur_btw_nummer: str | None,
    reden: str,
    gelezen_totalen: tuple[Decimal | None, Decimal | None] = (None, None),
) -> CheckRapport:
    """Bouwt het rapport voor het geval de RLZ-verbinding zelf al niet tot stand komt (credential-
    fout, netwerkfout) — vóórdat check_duplicaat() de kans krijgt zijn eigen RlzApiError-vangnet te
    gebruiken (app/documenten/checks.py). De lokale checks (geen RLZ nodig) draaien gewoon door,
    inclusief de IBAN-wissel-check tegen de al opgeslagen vertrouwde set (zonder RLZ-seed of
    baseline — die vergen een werkende verbinding); alleen de duplicaatcheck wordt een blokkerend,
    herkenbaar checkresultaat — nooit een kale 500 bij de gebruiker."""
    regels = _naar_check_regels(voorstel, _taxrate_percentages(administratie_id))
    vertrouwd: set[str] = set()
    if voorstel.vendor_id is not None:
        vertrouwd = leverancier_iban.vertrouwde_ibans(administratie_id=administratie_id, vendor_id=voorstel.vendor_id)
    return CheckRapport(
        (
            check_verplichte_velden(
                vendor_id=voorstel.vendor_id,
                referentie=voorstel.referentie,
                factuurdatum=voorstel.factuurdatum,
                totaalbedrag=voorstel.totaalbedrag,
                regels=regels,
                project_verplicht=_project_verplicht_per_regel(project_verplicht, voorstel),
            ),
            _afdeling_check(administratie_id=administratie_id, voorstel=voorstel),
            _projectverdeling_check(voorstel),
            check_regeltelling(
                totaalbedrag=voorstel.totaalbedrag,
                regels=regels,
                totaal_excl=gelezen_totalen[0],
                factuur_btw=gelezen_totalen[1],
            ),
            check_vervaldatum(factuurdatum=voorstel.factuurdatum, vervaldatum=voorstel.vervaldatum),
            check_buitenland_tarief_crediteurkaart(
                regels=regels,
                taxrate_namen=_taxrate_namen(administratie_id),
                factuur_btw_nummer=factuur_btw_nummer,
            ),
            check_iban_wissel(factuur_iban=factuur_iban, vertrouwde_ibans=vertrouwd),
            CheckResultaat("Duplicaatcheck", False, f"Duplicaatcheck kon niet uitgevoerd worden: {reden}"),
        )
    )


def _projectverdeling_check(voorstel: BoekvoorstelData) -> CheckResultaat:
    """Blok C 04-09: lokale check op de projectverdeling (app/projectverdeling/service.py::check) — géén
    verdeling = niet van toepassing (ok); actieve verdeling die niet sluit = blokkerend mét de blokkade-zin."""
    from app.projectverdeling import service as projectverdeling_service

    return projectverdeling_service.check(voorstel.projectverdeling)


def _afdeling_check(*, administratie_id: uuid.UUID, voorstel: BoekvoorstelData) -> CheckResultaat:
    """Blok A 28-08: lokale check (geen RLZ nodig) — draait in beide rapport-takken, zodat hij ook
    bij een RLZ-storing niet stil wegvalt (valkuil _duplicaatcheck_niet_uitgevoerd_rapport)."""
    from app.afdelingen.models import Afdeling

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        ingeschakeld = administratie.afdelingen_ingeschakeld if administratie else False
        administratie_naam = administratie.naam if administratie else None
    afdeling_actief: bool | None = None
    afdeling_naam: str | None = None
    if ingeschakeld and voorstel.afdeling_id is not None:
        with scoped_session(administratie_id) as session:
            afdeling = session.get(Afdeling, voorstel.afdeling_id)
            if afdeling is not None:
                afdeling_actief, afdeling_naam = afdeling.actief, afdeling.naam
    return check_afdeling(
        afdelingen_ingeschakeld=ingeschakeld,
        afdeling_id=voorstel.afdeling_id,
        afdeling_actief=afdeling_actief,
        afdeling_naam=afdeling_naam,
        administratie_naam=administratie_naam,
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
        # Punt 14 (28-08): bekende btw-nummers per crediteur voor de check over crediteuren heen.
        from app.documenten.crediteur_kenmerk import btw_per_vendor as _btw_per_vendor

        btw_map = _btw_per_vendor(session, administratie_id=administratie_id)
    factuur_btw_nummer = veldvoorstel.get("btw_nummer") if veldvoorstel else None

    # Factuur-IBAN uit de extractie (gestructureerd kopveld sinds 2026-07-13); de controlelaag
    # heeft 'm al mod-97-gevalideerd (app/extractie/controle.py) — oudere veldvoorstellen zonder
    # iban-sleutel geven None: geen wisselcontrole mogelijk, nooit een blok op ontbrekende data.
    factuur_iban = veldvoorstel.get("iban") if veldvoorstel else None
    # Bugfix 04-09 (Huvanco): gelezen excl-totaal + factuur-btw voor een expliciete regeltelling-basis.
    gelezen_totalen = _gelezen_totalen(veldvoorstel)

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        project_verplicht = administratie.project_verplicht if administratie else False

    eigen_client = client is None
    eigen_port = None
    if client is None:
        try:
            # Via de boekhoud-backend-port (0016): RLZ opent de bestaande client (test-seam
            # `client_voor_rlz_admin_id` blijft de patch-plek), Odoo zijn eigen leesfacade.
            eigen_port = inkoop_port_voor(
                administratie_id, rlz_client_factory=lambda: _rlz_leesclient(administratie_id)
            )
            client = eigen_port.leesclient()
        except Exception as exc:  # noqa: BLE001 — bewust breed, zie de docstring hierboven
            return _duplicaatcheck_niet_uitgevoerd_rapport(
                administratie_id=administratie_id,
                voorstel=voorstel,
                project_verplicht=project_verplicht,
                factuur_iban=factuur_iban,
                factuur_btw_nummer=factuur_btw_nummer,
                reden=str(exc),
                gelezen_totalen=gelezen_totalen,
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
        # Tegenboek-pad: het eigen GUID volgt de boek_cyclus (herboeking = nieuw GUID); alle
        # eerdere (her)boekings- en tegenboekings-GUID's van dit document zijn de gekoppelde
        # correctieketen en tellen niet als duplicaat (mockup 22-08 — de herboeking heeft
        # bewust dezelfde Entity+Reference+bedrag als het origineel).
        keten = frozenset(
            {rlz_herboeking_id(document_id, c) for c in range(voorstel.boek_cyclus + 1)}
            | {rlz_tegenboeking_id(document_id, c) for c in range(voorstel.boek_cyclus + 1)}
        )
        rapport = voer_harde_checks_uit(
            client=client,
            vendor_id=voorstel.vendor_id,
            referentie=voorstel.referentie,
            factuurdatum=voorstel.factuurdatum,
            vervaldatum=voorstel.vervaldatum,
            totaalbedrag=voorstel.totaalbedrag,
            regels=_naar_check_regels(voorstel, _taxrate_percentages(administratie_id)),
            eigen_rlz_document_id=rlz_herboeking_id(document_id, voorstel.boek_cyclus),
            uitgezonderde_rlz_document_ids=keten,
            project_verplicht=_project_verplicht_per_regel(project_verplicht, voorstel),
            factuur_iban=factuur_iban,
            vertrouwde_ibans=vertrouwde_ibans,
            iban_baseline_vastgelegd=baseline_vastgelegd,
            iban_seed_mislukt=seed_mislukt,
            eigen_btw_nummer=factuur_btw_nummer,
            btw_per_vendor=btw_map,
            taxrate_namen=_taxrate_namen(administratie_id),
            totaal_excl=gelezen_totalen[0],
            factuur_btw=gelezen_totalen[1],
        )
        # Blok A 28-08: afdeling-check direct ná de verplichte velden (zelfde plek als in de
        # storings-tak), vóór de RLZ-afhankelijke checks.
        resultaten = list(rapport.resultaten)
        resultaten.insert(1, _afdeling_check(administratie_id=administratie_id, voorstel=voorstel))
        # Blok C 04-09: projectverdeling-check (lokaal, geen RLZ) direct ná de afdeling — zelfde plek als in
        # de storings-tak; blokkeert zolang een actieve verdeling niet exact op 100 % sluit.
        resultaten.insert(2, _projectverdeling_check(voorstel))
        return CheckRapport(tuple(resultaten))
    finally:
        if eigen_client and eigen_port is not None:
            eigen_port.__exit__(None, None, None)
