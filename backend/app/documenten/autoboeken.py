"""Automatisch boeken van inkoopfacturen — opt-in per leverancier (CLAUDE.md-poort, blok 2
grote opdracht 2026-08-09).

Principe onveranderd: "code voor cijfers, AI voor taal, mens voor de knop op geld" — het enige
dat hier vervalt is de menselijke boek-klik, en alléén wanneer élk oordeel dat die klik zou
vellen al eerder door een mens is geveld:

1. De Beheerder heeft autoboeken voor deze leverancier expliciet aangezet (default UIT).
2. De HARDE CHECKS draaien onverkort in de bestaande boekmotor (duplicaat, regeltelling,
   verplichte velden, IBAN-wissel, projectplicht) — een blokkerende check wint altijd.
3. Het voorstel komt volledig uit BEVESTIGD boekingsgeheugen: elk geheugen-veld (GB, btw,
   project bij projectplicht) moet `app_bevestigd` zijn én niet oranje — een waarde die alleen
   op RLZ-historie steunt (seed-only) boekt nooit automatisch (aanscherping 2026-07-14).
4. Geen open vraag, geen afwijzing, geen mogelijk-duplicaat-signaal — bij twijfel nooit gokken.
5. Volumerem, boeken-toggle/kill switch en de accorderingspoort gelden onverkort (de bestaande
   boekmotor dwingt ze af); klant-accordering aan = nooit direct autoboeken.

Elke autoboek-poging bij een leverancier mét opt-in wordt geauditeerd (geboekt of geweigerd
mét reden); de GEBOEKT-overgang draagt `automatisch_geboekt` in het tijdlijn-detail (systeem-
actor), zodat werkvoorraad-historie en filter het onderscheid tonen. Een leverancier zónder
opt-in genereert bewust géén audit-ruis (dat is de default voor alles)."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, replace

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken as boeken_service
from app.documenten.boekvoorstel import (
    BoekvoorstelRegelData,
    _project_verplicht,
    haal_boekvoorstel_op,
    sla_boekvoorstel_op,
)
from app.documenten.models import Document, DocumentSoort, DocumentStatus, LeverancierVoorkeur
from app.geheugen.engine import GeheugenVoorstel
from app.geheugen.service import voorstel_voor
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- opt-in-beheer


@dataclass(frozen=True)
class LeverancierAutoboeken:
    vendor_id: uuid.UUID
    naam: str | None
    autoboeken_ingeschakeld: bool


def lijst_leverancier_autoboeken(*, administratie_id: uuid.UUID) -> list[LeverancierAutoboeken]:
    """Alle actieve leveranciers van de administratie mét hun opt-in-stand (Instellingen-UI)."""
    with scoped_session(administratie_id) as session:
        vendors = session.scalars(
            select(VendorCache)
            .where(
                VendorCache.administratie_id == administratie_id,
                VendorCache.verdwenen_uit_bron_op.is_(None),
            )
            .order_by(VendorCache.naam)
        ).all()
        voorkeuren = {
            v.vendor_id: v.autoboeken_ingeschakeld
            for v in session.scalars(
                select(LeverancierVoorkeur).where(LeverancierVoorkeur.administratie_id == administratie_id)
            )
        }
        return [
            LeverancierAutoboeken(
                vendor_id=vendor.id,
                naam=vendor.naam,
                autoboeken_ingeschakeld=voorkeuren.get(vendor.id, False),
            )
            for vendor in vendors
        ]


def zet_leverancier_autoboeken(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID, ingeschakeld: bool
) -> bool:
    """Zet de opt-in per leverancier. Beheerder-only wordt in de router afgedwongen
    (require_beheerder); elke zetting — óók een herbevestiging — gaat het audit_event in
    (zelfde bewuste conventie als de beheer-toggles, app/beheer/service.py)."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
        oud = voorkeur.autoboeken_ingeschakeld if voorkeur else False
        if voorkeur is None:
            # regels_samenvoegen default AAN — zelfde default als het boekvoorstel hanteert
            # zolang er geen voorkeur bestaat (app/documenten/boekvoorstel.py).
            voorkeur = LeverancierVoorkeur(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                regels_samenvoegen=True,
                autoboeken_ingeschakeld=ingeschakeld,
            )
            session.add(voorkeur)
        else:
            voorkeur.autoboeken_ingeschakeld = ingeschakeld
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_voorkeur",
            record_id=vendor_id,
            actie="leverancier_autoboeken_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"autoboeken_ingeschakeld": oud},
            nieuwe_waarde={"autoboeken_ingeschakeld": ingeschakeld},
            administratie_id=administratie_id,
        )
    return ingeschakeld


def _autoboeken_ingeschakeld(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> bool:
    with scoped_session(administratie_id) as session:
        voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
        return bool(voorkeur and voorkeur.autoboeken_ingeschakeld)


# ----------------------------------------------------------------------------- autoboek-pad


@dataclass(frozen=True)
class AutoboekBesluit:
    geboekt: bool
    reden: str


def _geheugen_veld_geblokkeerd(voorstel: GeheugenVoorstel, *, project_vereist: bool) -> str | None:
    """Weiger-reden wanneer het geheugen-voorstel niet volledig app-bevestigd en groen is.
    Seed-only (alleen RLZ-historie) blijft oranje en boekt dus nooit automatisch."""
    velden = [("grootboek", voorstel.gb), ("btw", voorstel.btw)]
    if project_vereist:
        velden.append(("project", voorstel.project))
    for naam, veld in velden:
        if veld.waarde is None:
            return f"geheugen heeft geen voorstel voor {naam}"
        if veld.oranje or not veld.app_bevestigd:
            return f"geheugen-voorstel voor {naam} is niet app-bevestigd/groen ({veld.reden or 'oranje'})"
    return None


def _vul_regel_uit_geheugen(
    regel: BoekvoorstelRegelData, voorstel: GeheugenVoorstel, *, project_vereist: bool
) -> BoekvoorstelRegelData:
    return replace(
        regel,
        ledger_id=voorstel.gb.waarde,
        taxrate_id=voorstel.btw.waarde,
        project_id=voorstel.project.waarde if project_vereist else regel.project_id,
    )


def _weiger(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, reden: str
) -> AutoboekBesluit:
    logger.info("Autoboeken geweigerd voor document %s: %s", document_id, reden)
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="autoboeken_geweigerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"reden": reden},
            administratie_id=administratie_id,
        )
    return AutoboekBesluit(geboekt=False, reden=reden)


def probeer_autoboeken_na_extractie(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID
) -> AutoboekBesluit | None:
    """Het autoboek-pad, aangeroepen ná de extractie (post-commit hook). Retourneert None
    wanneer autoboeken hier per definitie niet aan de orde is (geen inkoopfactuur, geen
    leverancier herkend, of opt-in uit — bewust géén audit-ruis), anders een AutoboekBesluit
    (geboekt of geweigerd-met-reden, altijd geauditeerd)."""
    with scoped_session(administratie_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return None
        if document.status != DocumentStatus.TE_CONTROLEREN:
            # Handmatig afmaken/wachtrij/vraag: per definitie geen kandidaat.
            return None
        mogelijk_duplicaat = document.mogelijk_duplicaat_van_id is not None

    voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    if voorstel.vendor_id is None:
        return None  # geen herkende leverancier → sowieso mensenwerk
    if not _autoboeken_ingeschakeld(administratie_id=administratie_id, vendor_id=voorstel.vendor_id):
        return None

    # Vanaf hier is autoboeken expliciet aangezet — elke uitkomst wordt geauditeerd.
    if mogelijk_duplicaat:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="mogelijk-duplicaat-signaal op het document (zelfde bestandsinhoud) — mens beoordeelt",
        )
    if voorstel.referentie is None or voorstel.factuurdatum is None or voorstel.totaalbedrag is None:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="extractie leverde geen volledige kopgegevens (referentie/datum/totaal)",
        )

    project_vereist = _project_verplicht(administratie_id)
    # Samengevoegd (de default zonder projectplicht) = één boeking op leverancier-niveau: het
    # geheugen wordt dan zónder regelomschrijving bevraagd (de synthetische samenvoeg-tekst is
    # geen echte regel-sleutel; de btw-stem telt dan op leverancier-niveau, zie geheugen/engine).
    samengevoegd = voorstel.regels_samenvoegen and voorstel.samengevoegde_regel is not None
    if samengevoegd:
        basis_regels = [voorstel.samengevoegde_regel]
    elif voorstel.regels:
        basis_regels = voorstel.regels
    else:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="extractie leverde geen boekbare regels",
        )
    if any(r.netto_bedrag is None for r in basis_regels):
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="niet elke regel heeft een geëxtraheerd nettobedrag",
        )

    # Boekingsgeheugen: per regel (regelomschrijving verfijnt) — élk veld app-bevestigd + groen.
    gevulde_regels: list[BoekvoorstelRegelData] = []
    for regel in basis_regels:
        geheugen = voorstel_voor(
            administratie_id=administratie_id,
            vendor_id=voorstel.vendor_id,
            regel_omschrijving=None if samengevoegd else regel.omschrijving,
        )
        blokkade = _geheugen_veld_geblokkeerd(geheugen, project_vereist=project_vereist)
        if blokkade is not None:
            return _weiger(administratie_id=administratie_id, document_id=document_id, reden=blokkade)
        gevulde_regels.append(_vul_regel_uit_geheugen(regel, geheugen, project_vereist=project_vereist))

    sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=SYSTEEM_ACTOR_ID,
        vendor_id=voorstel.vendor_id,
        referentie=voorstel.referentie,
        factuurdatum=voorstel.factuurdatum,
        totaalbedrag=voorstel.totaalbedrag,
        regels=gevulde_regels,
    )

    try:
        boeken_service.boek_document(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            extra_overgang_detail={"automatisch_geboekt": True, "bron": "leverancier_opt_in"},
        )
    except boeken_service.BoekenGeblokkeerdDoorChecks as exc:
        geblokkeerd = [f"{r.naam}: {r.melding}" for r in exc.rapport.resultaten if not r.ok]
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden="harde checks blokkeren — " + "; ".join(geblokkeerd),
        )
    except (
        boeken_service.AccorderingVereist,
        boeken_service.BoekenUitgeschakeld,
        boeken_service.VolumeremBereikt,
    ) as exc:
        return _weiger(administratie_id=administratie_id, document_id=document_id, reden=str(exc))
    except boeken_service.RlzBoekingMislukt as exc:
        # Het document staat nu zichtbaar op boeken_mislukt (de motor zette dat al) — de
        # weigering wordt daarnaast geauditeerd; een mens pakt de retry op.
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden=f"RLZ-boekfout tijdens autoboeken (document staat op boeken_mislukt): {exc}",
        )

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="document",
            record_id=document_id,
            actie="automatisch_geboekt",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"vendor_id": str(voorstel.vendor_id), "referentie": voorstel.referentie},
            administratie_id=administratie_id,
        )
    return AutoboekBesluit(geboekt=True, reden="automatisch geboekt (opt-in leverancier)")
