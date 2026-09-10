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
from datetime import UTC, datetime

from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from app.autoboek_kandidaten.models import DREMPEL_DEFAULT, AutoboekInstelling, AutoboekKandidaatStand
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import boeken as boeken_service
from app.documenten.boekvoorstel import (
    BoekvoorstelRegelData,
    _project_verplicht,
    haal_boekvoorstel_op,
    sla_boekvoorstel_op,
)
from app.documenten.models import (
    Boekvoorstel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    LeverancierVoorkeur,
)
from app.geheugen.engine import GeheugenVoorstel
from app.geheugen.service import voorstel_voor
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)


# ----------------------------------------------------------------------------- opt-in-beheer


class VeldwerkerKoppelingBlokkeertOptIn(Exception):
    """Factuurmatch fase 2 (Peter 2026-08-21): een crediteur die aan een veldwerker gekoppeld
    is (boekhouding.veldwerker_crediteur) krijgt de OUDE per-leverancier-autoboek-opt-in niet —
    die zou de urenmatch omzeilen. Autoboeken loopt daar via de opt-in per
    veldwerker-koppeling (besluit 4, activatie = fase 4, strikt groen incl. bedrag)."""


class RedenVerplicht(Exception):
    """Uitzonderen (blok A bundel 10-09) vraagt een reden — nooit stil (422 in de router)."""


@dataclass(frozen=True)
class LeverancierAutoboeken:
    """Eén rij in de UITZONDERINGENLIJST (blok A bundel 10-09): opt-in-stand + stand-chip (`leert` n/drempel |
    `boekt_automatisch` | `uitgezonderd` | `handmatig_aan`), herkomst (`bron` mens/systeem) en reset-moment."""

    vendor_id: uuid.UUID
    naam: str | None
    autoboeken_ingeschakeld: bool
    stand: str = "leert"
    reeks: int = 0
    drempel: int = DREMPEL_DEFAULT
    bron: str | None = None
    gereset_op: datetime | None = None
    uitgezonderd: bool = False
    uitzondering_reden: str | None = None


def _drempel(session: Session) -> int:
    rij = session.get(AutoboekInstelling, True)
    return int(rij.drempel_op_rij) if rij is not None else DREMPEL_DEFAULT


def lijst_leverancier_autoboeken(*, administratie_id: uuid.UUID) -> list[LeverancierAutoboeken]:
    """Alle actieve leveranciers van de administratie mét hun opt-in-stand (Instellingen-UI); verliezers van een
    afgehandeld dubbel-cluster staan er niet in (B13 07-09 — opt-in hoort op de voorkeur). Sinds blok A 10-09 mét
    stand-chip, reeks n/drempel (uit `autoboek_kandidaat_stand`, de laatst berekende stand), bron en reset-moment."""
    from app.autoboek_kandidaten.service import stand_label
    from app.crediteuren.voorkeur import BRUIKBAAR

    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        leren_aan = bool(
            administratie is not None
            and administratie.autoboeken_leren_ingeschakeld
            and not administratie.doorbelasting_ingeschakeld
        )
        drempel = _drempel(session)
        vendors = session.scalars(
            select(VendorCache)
            .where(
                VendorCache.administratie_id == administratie_id,
                VendorCache.verdwenen_uit_bron_op.is_(None),
                BRUIKBAAR,
            )
            .order_by(VendorCache.naam)
        ).all()
        voorkeuren = {
            v.vendor_id: v
            for v in session.scalars(
                select(LeverancierVoorkeur).where(LeverancierVoorkeur.administratie_id == administratie_id)
            )
        }
        reeksen = dict(
            session.execute(
                select(AutoboekKandidaatStand.vendor_id, AutoboekKandidaatStand.reeks_ongewijzigd).where(
                    AutoboekKandidaatStand.administratie_id == administratie_id
                )
            ).all()
        )
        uit: list[LeverancierAutoboeken] = []
        for vendor in vendors:
            voorkeur = voorkeuren.get(vendor.id)
            actief = bool(voorkeur and voorkeur.autoboeken_ingeschakeld)
            uitgezonderd = bool(voorkeur and voorkeur.autoboeken_uitgezonderd)
            bron = voorkeur.autoboeken_bron if voorkeur else None
            uit.append(
                LeverancierAutoboeken(
                    vendor_id=vendor.id,
                    naam=vendor.naam,
                    autoboeken_ingeschakeld=actief,
                    stand=stand_label(
                        actief=actief, bron=bron, uitgezonderd=uitgezonderd, administratie_leren_aan=leren_aan
                    ),
                    reeks=int(reeksen.get(vendor.id, 0) or 0),
                    drempel=drempel,
                    bron=bron,
                    gereset_op=voorkeur.autoboeken_gereset_op if voorkeur else None,
                    uitgezonderd=uitgezonderd,
                    uitzondering_reden=voorkeur.autoboeken_uitzondering_reden if voorkeur else None,
                )
            )
        return uit


def zet_leverancier_autoboeken(
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID,
    actor_id: uuid.UUID,
    ingeschakeld: bool,
    bron: str = "mens",
) -> bool:
    """Zet de opt-in per leverancier. Beheerder-only wordt in de router afgedwongen
    (require_beheerder); elke zetting — óók een herbevestiging — gaat het audit_event in
    (zelfde bewuste conventie als de beheer-toggles, app/beheer/service.py). AANzetten wordt
    geweigerd voor een crediteur mét veldwerker-koppeling (factuurmatch fase 2 — het
    veldwerker-autoboekpad, fase 4, is daar het enige kanaal); UITzetten mag altijd.
    `bron` (blok A 10-09): 'mens' (default — de Beheerder-switch/bulk) of 'systeem' (de leerregel via
    `autoboek_kandidaten.service.activeer_kwalificerend`); landt in `autoboeken_bron` en het audit-event. Een mens die
    AANzet heft daarmee een eerdere uitzondering op (mens wint, zichtbaar in het audit-event)."""
    from app.uren.factuurmatch import vind_veldwerker_koppeling

    with scoped_session(administratie_id, actor_id=actor_id) as session:
        if ingeschakeld and vind_veldwerker_koppeling(
            session, administratie_id=administratie_id, vendor_id=vendor_id
        ):
            raise VeldwerkerKoppelingBlokkeertOptIn(
                "Deze crediteur is gekoppeld aan een veldwerker — autoboeken loopt daar via de "
                "urenmatch-opt-in per veldwerker-koppeling, niet via de leverancier-opt-in"
            )
        voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
        oud = voorkeur.autoboeken_ingeschakeld if voorkeur else False
        oud_bron = voorkeur.autoboeken_bron if voorkeur else None
        oud_uitgezonderd = bool(voorkeur and voorkeur.autoboeken_uitgezonderd)
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
        voorkeur.autoboeken_bron = bron if ingeschakeld else None
        if ingeschakeld and bron == "mens" and oud_uitgezonderd:
            voorkeur.autoboeken_uitgezonderd = False
            voorkeur.autoboeken_uitzondering_reden = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_voorkeur",
            record_id=vendor_id,
            actie="leverancier_autoboeken_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"autoboeken_ingeschakeld": oud, "bron": oud_bron, "uitgezonderd": oud_uitgezonderd},
            nieuwe_waarde={
                "autoboeken_ingeschakeld": ingeschakeld,
                "bron": voorkeur.autoboeken_bron,
                "uitgezonderd": voorkeur.autoboeken_uitgezonderd,
            },
            administratie_id=administratie_id,
        )
    return ingeschakeld


def _leverancier_naam(session: Session, vendor_id: uuid.UUID) -> str | None:
    return session.scalar(select(VendorCache.naam).where(VendorCache.id == vendor_id))


def zonder_leverancier_uit(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID, reden: str
) -> None:
    """Uitzonderen (blok A bundel 10-09): de enige menselijke ingreep als de administratie-schakelaar aan staat —
    het systeem activeert deze leverancier nooit (meer). Zet óók de opt-in uit (via de bestaande schrijver, eigen
    audit) en legt de VERPLICHTE reden vast (audit `autoboek_leverancier_uitgezonderd`; `RedenVerplicht` → 422)."""
    reden = (reden or "").strip()
    if not reden:
        raise RedenVerplicht("Een reden is verplicht bij het uitzonderen van een leverancier")
    if _autoboeken_ingeschakeld(administratie_id=administratie_id, vendor_id=vendor_id):
        zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor_id, ingeschakeld=False
        )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
        if voorkeur is None:
            voorkeur = LeverancierVoorkeur(
                administratie_id=administratie_id,
                vendor_id=vendor_id,
                regels_samenvoegen=True,
                autoboeken_ingeschakeld=False,
            )
            session.add(voorkeur)
        oud = {"uitgezonderd": voorkeur.autoboeken_uitgezonderd, "reden": voorkeur.autoboeken_uitzondering_reden}
        voorkeur.autoboeken_uitgezonderd = True
        voorkeur.autoboeken_uitzondering_reden = reden
        stand = session.get(AutoboekKandidaatStand, (administratie_id, vendor_id))
        if stand is not None:
            stand.actief = False
            stand.actief_sinds = None
            stand.heroverweeg_signalen = []
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_voorkeur",
            record_id=vendor_id,
            actie="autoboek_leverancier_uitgezonderd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "uitgezonderd": True,
                "reden": reden,
                "leverancier_naam": _leverancier_naam(session, vendor_id),
            },
            administratie_id=administratie_id,
        )


def geef_leverancier_vrij(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Vrijgeven (blok A bundel 10-09): heft de uitzondering op (audit `autoboek_leverancier_vrijgegeven`) en laat
    het systeem direct toetsen — haalt de reeks de drempel al, dan is de leverancier meteen weer actief."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
        oud = {
            "uitgezonderd": bool(voorkeur and voorkeur.autoboeken_uitgezonderd),
            "reden": voorkeur.autoboeken_uitzondering_reden if voorkeur else None,
        }
        if voorkeur is not None:
            voorkeur.autoboeken_uitgezonderd = False
            voorkeur.autoboeken_uitzondering_reden = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_voorkeur",
            record_id=vendor_id,
            actie="autoboek_leverancier_vrijgegeven",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "uitgezonderd": False,
                "reden": None,
                "leverancier_naam": _leverancier_naam(session, vendor_id),
            },
            administratie_id=administratie_id,
        )
    from app.autoboek_kandidaten import service as kandidaten_service  # lokaal: geen kring

    kandidaten_service.activeer_kwalificerend_stil(administratie_id=administratie_id, vendor_id=vendor_id)


# ----------------------------------------------------------------------------- reset ná storno/correctie


def laatste_boeking_was_automatisch(session: Session, *, document_id: uuid.UUID) -> bool:
    """Draagt de jongste GEBOEKT-overgang van dit document `automatisch_geboekt`? (tegenboeken/herboeken/storno-detectie
    lezen dit ín hun transactie — de zojuist toegevoegde vervolg-overgang is geen GEBOEKT-overgang en stoort niet.)"""
    gebeurtenis = session.scalars(
        select(DocumentGebeurtenis)
        .where(
            DocumentGebeurtenis.document_id == document_id,
            DocumentGebeurtenis.naar_status == DocumentStatus.GEBOEKT,
            # Echte overgang, geen tijdlijn-notitie (van = naar, bv. de activatie-/reset-regel zelf).
            or_(
                DocumentGebeurtenis.van_status.is_(None),
                DocumentGebeurtenis.van_status != DocumentGebeurtenis.naar_status,
            ),
        )
        .order_by(DocumentGebeurtenis.tijdstip.desc())
        .limit(1)
    ).first()
    return bool(gebeurtenis is not None and (gebeurtenis.detail or {}).get("automatisch_geboekt"))


RESET_REDENEN = ("storno", "correctie")


def reset_na_correctie_in_sessie(
    session: Session, *, administratie_id: uuid.UUID, document_id: uuid.UUID, reden: str, actor_id: uuid.UUID
) -> bool:
    """Blok A bundel 10-09 (besluit Peter 10-09): een storno of correctie van een AUTOMATISCHE boeking zet de
    leverancier terug op "leert 0/N" — opt-in uit (via de bestaande schrijver, eigen sessie ná deze transactie is
    niet nodig: we schrijven hier ín de transactie van de tegenboeking/herboeking, samen of samen niet),
    `autoboeken_gereset_op = now()`, `autoboeken_bron = None`, audit `autoboek_leverancier_gereset` (reden +
    document) en een tijdlijnregel op het document. False = het document was niet automatisch geboekt (niets te
    resetten; een menselijke boeking corrigeren raakt de leerregel niet)."""
    if reden not in RESET_REDENEN:
        raise ValueError(f"Onbekende reset-reden: {reden}")
    if not laatste_boeking_was_automatisch(session, document_id=document_id):
        return False
    vendor_id = session.scalar(select(Boekvoorstel.vendor_id).where(Boekvoorstel.document_id == document_id))
    document = session.get(Document, document_id)
    if vendor_id is None or document is None:
        return False
    voorkeur = session.get(LeverancierVoorkeur, (administratie_id, vendor_id))
    if voorkeur is None:
        voorkeur = LeverancierVoorkeur(
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            regels_samenvoegen=True,
            autoboeken_ingeschakeld=False,
        )
        session.add(voorkeur)
    nu = datetime.now(UTC)
    oud = {
        "autoboeken_ingeschakeld": voorkeur.autoboeken_ingeschakeld,
        "bron": voorkeur.autoboeken_bron,
        "gereset_op": voorkeur.autoboeken_gereset_op.isoformat() if voorkeur.autoboeken_gereset_op else None,
    }
    voorkeur.autoboeken_ingeschakeld = False
    voorkeur.autoboeken_bron = None
    voorkeur.autoboeken_gereset_op = nu
    stand = session.get(AutoboekKandidaatStand, (administratie_id, vendor_id))
    if stand is not None:
        stand.actief = False
        stand.actief_sinds = None
        stand.reeks_ongewijzigd = 0
        stand.kwalificeert = False
        stand.heroverweeg_signalen = []
    drempel = _drempel(session)
    naam = _leverancier_naam(session, vendor_id)
    detail = {
        "reden": reden,
        "document_id": str(document_id),
        "vendor_id": str(vendor_id),
        "leverancier_naam": naam,
        "gereset_op": nu.isoformat(),
        "drempel": drempel,
    }
    if voorkeur.autoboeken_ingeschakeld != oud["autoboeken_ingeschakeld"]:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_voorkeur",
            record_id=vendor_id,
            actie="leverancier_autoboeken_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"autoboeken_ingeschakeld": True, "bron": oud["bron"]},
            nieuwe_waarde={"autoboeken_ingeschakeld": False, "bron": None, "aanleiding": f"reset ná {reden}"},
            administratie_id=administratie_id,
        )
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="leverancier_voorkeur",
        record_id=vendor_id,
        actie="autoboek_leverancier_gereset",
        correlatie_id=uuid.uuid4(),
        oude_waarde=oud,
        nieuwe_waarde={"autoboeken_ingeschakeld": False, "bron": None, **detail},
        administratie_id=administratie_id,
    )
    tekst = f"Autoboeken voor {naam or 'deze leverancier'} teruggezet naar leren (0/{drempel}) — {reden}"
    session.add(
        DocumentGebeurtenis(
            document_id=document_id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail={"autoboek_reset": detail, "reden": tekst},
        )
    )
    return True


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
    """Het autoboek-pad, aangeroepen ná de extractie (post-commit hook) én — voor
    veldwerker-crediteuren — ná een weekstaat-goedkeuring die de match groen maakt
    (factuurmatch fase 4, app/uren/factuurmatch_pipeline.py). Retourneert None wanneer
    autoboeken hier per definitie niet aan de orde is (geen inkoopfactuur, geen leverancier
    herkend, of opt-in uit — bewust géén audit-ruis), anders een AutoboekBesluit (geboekt of
    geweigerd-met-reden, altijd geauditeerd).

    Twee opt-in-kanalen, wederzijds exclusief per crediteur:
    - leverancier-opt-in (blok 2, 2026-08-09) voor gewone crediteuren;
    - veldwerker-opt-in (factuurmatch fase 4, besluit 4 Peter 2026-08-21): per
      veldwerker-koppeling (default UIT), mét de extra poort dat de urenmatch strikt GROEN is
      inclusief bedrag (uitkomst `match` — tarief dus ingevuld; alleen-uren/niet-toetsbaar/
      afwijking autoboekt nooit) én er getekende weekstaten in de match zitten. Alle overige
      poorten (harde checks, volledig app-bevestigd geheugen, duplicaat/vraag/afwijzing,
      volumerem, accorderingspoort, boeken-toggle) gelden onverkort — de staten worden ín de
      boek-transactie verrekend (fase 2)."""
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

    from app.uren.factuurmatch import vind_veldwerker_koppeling

    with scoped_session(administratie_id) as session:
        koppeling = vind_veldwerker_koppeling(
            session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id
        )
        veldwerker_gekoppeld = koppeling is not None
        veldwerker_opt_in = bool(koppeling and koppeling.autoboeken_ingeschakeld)
    legacy_opt_in = _autoboeken_ingeschakeld(administratie_id=administratie_id, vendor_id=voorstel.vendor_id)

    if veldwerker_gekoppeld and not veldwerker_opt_in:
        if not legacy_opt_in:
            return None  # geen enkel autoboek-kanaal aan — de default voor alles
        # Runtime-vangnet (factuurmatch fase 2): aanzetten wordt sinds die fase geweigerd voor
        # een gekoppelde crediteur, maar een opt-in van vóór de koppeling blijft anders stil
        # werken — en zou de urenmatch omzeilen. Autoboeken hier = alleen via fase 4.
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden=(
                "crediteur is gekoppeld aan een veldwerker — de leverancier-opt-in geldt daar "
                "niet (urenmatch; autoboeken alleen via de veldwerker-opt-in, fase 4)"
            ),
        )
    if not veldwerker_gekoppeld and not legacy_opt_in:
        return None

    # Vanaf hier is autoboeken expliciet aangezet — elke uitkomst wordt geauditeerd.
    bron = "veldwerker_opt_in" if veldwerker_gekoppeld else "leverancier_opt_in"

    if veldwerker_gekoppeld:
        # Fase-4-poort (besluit 2 + 4): het autoboek-slot is uitsluitend groen bij `match` —
        # bedrag getoetst en kloppend (tarief dus ingevuld). Alles anders blijft mensenwerk.
        from app.uren.factuurmatch_pipeline import lees_match

        match = lees_match(administratie_id=administratie_id, document_id=document_id)
        if match is None:
            return _weiger(
                administratie_id=administratie_id,
                document_id=document_id,
                reden="geen matchresultaat voor dit document — de urenmatch is de autoboek-poort",
            )
        if match.uitkomst != "match":
            cijfers = (
                f"staten {match.staten_som_uren} u / € {match.staten_som_bedrag}"
                f" vs factuur € {match.factuur_bedrag}"
            )
            return _weiger(
                administratie_id=administratie_id,
                document_id=document_id,
                reden=f"urenmatch niet groen (uitkomst: {match.uitkomst} — {cijfers}) — mens beoordeelt",
            )
        if not (match.details or {}).get("staten"):
            return _weiger(
                administratie_id=administratie_id,
                document_id=document_id,
                reden="urenmatch zonder getekende weekstaten — niets te verrekenen, mens beoordeelt",
            )

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
        vervaldatum=voorstel.vervaldatum,
        betalingskenmerk=voorstel.betalingskenmerk,
        totaalbedrag=voorstel.totaalbedrag,
        regels=gevulde_regels,
    )

    # B3-poort (blok B bundel 10-09, CONTRACT_A/CONTRACT_B §B3): AI-plausibiliteitstoets op het voorgestelde
    # GB/btw — de AI krijgt géén keuze, alleen ja/nee. 'plausibel' of 'uit' (platformbrede setting uit) → boeken;
    # 'twijfel' → NIET boeken, zichtbaar geweigerd (categorie twijfel in de reconciliatie-tellers).
    # Blok 4 (10-09 avond, besluit Peter): 'overgeslagen' (technische uitval — AVG-gate, API-key, kostengrens, AI-fout)
    # → WÉL boeken, mét `zonder_ai_toets` + oorzaak in het GEBOEKT-overgang-detail (tijdlijn + lijst-chip), audit
    # `automatisch_geboekt_zonder_ai_toets` en de teller/LET-OP in de reconciliatie. Lazy import: pakket van agent B.
    from app.aitoets.plausibiliteit import (
        SOORT_FACTUUR_AUTOBOEKING,
        registreer_geboekt_zonder_ai_toets,
        toets_factuur_autoboeking,
    )

    toets = toets_factuur_autoboeking(
        administratie_id=administratie_id,
        document_id=document_id,
        invoer_velden={
            "vendor_id": str(voorstel.vendor_id),
            "referentie": voorstel.referentie,
            "totaalbedrag": str(voorstel.totaalbedrag),
            "regels": [
                {
                    "omschrijving": r.omschrijving,
                    "ledger_id": str(r.ledger_id) if r.ledger_id else None,
                    "taxrate_id": str(r.taxrate_id) if r.taxrate_id else None,
                    "project_id": str(r.project_id) if r.project_id else None,
                    "netto_bedrag": str(r.netto_bedrag) if r.netto_bedrag is not None else None,
                }
                for r in gevulde_regels
            ],
        },
    )
    if not toets.boeken_toegestaan:
        return _weiger(
            administratie_id=administratie_id,
            document_id=document_id,
            reden=f"AI-plausibiliteitstoets: {toets.uitkomst} — {toets.reden}",
        )
    overgang_detail: dict = {"automatisch_geboekt": True, "bron": bron}
    if toets.zonder_ai_toets:
        overgang_detail.update(
            {"zonder_ai_toets": True, "ai_toets_oorzaak": toets.oorzaak, "ai_toets_reden": toets.reden}
        )

    try:
        boeken_service.boek_document(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=SYSTEEM_ACTOR_ID,
            extra_overgang_detail=overgang_detail,
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
            nieuwe_waarde={
                "vendor_id": str(voorstel.vendor_id),
                "referentie": voorstel.referentie,
                "bron": bron,
                "zonder_ai_toets": toets.zonder_ai_toets,
                "ai_toets_oorzaak": toets.oorzaak,
            },
            administratie_id=administratie_id,
        )
    registreer_geboekt_zonder_ai_toets(
        administratie_id=administratie_id,
        soort=SOORT_FACTUUR_AUTOBOEKING,
        referentie_id=document_id,
        uitkomst=toets,
        bron=bron,
    )
    if toets.zonder_ai_toets:
        return AutoboekBesluit(geboekt=True, reden=f"automatisch geboekt ({bron}) — zonder AI-toets ({toets.oorzaak})")
    return AutoboekBesluit(geboekt=True, reden=f"automatisch geboekt ({bron})")
