"""Autoboek-kandidaten — DB-laag rond de pure motor (motor.py). Draait dagelijks meeliftend in
sync-alles (`herbereken_alle`) en LIVE per rij op het moment van aanzetten (`hertoets_vendor`,
ontwerpnotitie ②). Aanzetten/uitzetten lopen via de BESTAANDE opt-in-schrijver
`documenten.autoboeken.zet_leverancier_autoboeken` (geen tweede schrijver, zelfde audit);
"Kandidaat verbergen" = snooze mét verplichte reden, geaudit, terugvindbaar (filter). Heroverwegen
is advies-only: deze laag zet nooit zelf iets uit."""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from app.autoboek_kandidaten import motor
from app.autoboek_kandidaten.models import DREMPEL_DEFAULT, AutoboekInstelling, AutoboekKandidaatStand
from app.db.audit import record_audit_event
from app.db.models import Administratie, AuditEvent
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import (
    Boekvoorstel,
    BoekvoorstelRegel,
    Document,
    DocumentGebeurtenis,
    DocumentSoort,
    DocumentStatus,
    DuplicaatSignaal,
    LeverancierVoorkeur,
    Tegenboeking,
)
from app.geheugen.engine import Observatie, bepaal_voorstel
from app.geheugen.models import BoekingObservatie, ObservatieBron
from app.sync.models import TaxRateCache, VendorCache
from app.uren.models import VeldwerkerCrediteur

logger = logging.getLogger(__name__)

_OPEN_STATUSSEN = {
    DocumentStatus.TE_CONTROLEREN,
    DocumentStatus.KLAAR_OM_TE_BOEKEN,
    DocumentStatus.VRAAG_OPEN,
    DocumentStatus.AFGEWEZEN,
    DocumentStatus.BOEKEN_MISLUKT,
    DocumentStatus.HANDMATIG_AFMAKEN,
    DocumentStatus.WACHT_OP_IBAN_ACCORDERING,
    DocumentStatus.TER_ACCORDERING,
}


class AutoboekKandidaatFout(Exception):
    pass


# ----------------------------------------------------------------------------- instelling


def _instelling(session: Session) -> AutoboekInstelling:
    rij = session.get(AutoboekInstelling, True)
    if rij is None:
        rij = AutoboekInstelling(singleton=True, drempel_op_rij=DREMPEL_DEFAULT)
        session.add(rij)
        session.flush()
    return rij


def haal_instelling_op() -> tuple[int, datetime | None]:
    with scoped_session(None) as session:
        rij = _instelling(session)
        return rij.drempel_op_rij, rij.laatste_run_op


def zet_drempel(*, actor_id: uuid.UUID, drempel: int) -> int:
    """Beheerder-instelling "N identieke boekingen op rij" (platformbreed 3): 1–50, audit oud→nieuw. De stand wordt niet
    direct
    herberekend — de eerstvolgende run (of "Herbereken") past de nieuwe drempel toe; de bulk-aanzet
    hertoetst sowieso live."""
    if not 1 <= drempel <= 50:
        raise AutoboekKandidaatFout("De drempel moet tussen 1 en 50 identieke boekingen op rij liggen")
    with scoped_session(None, actor_id=actor_id) as session:
        rij = _instelling(session)
        oud = rij.drempel_op_rij
        rij.drempel_op_rij = drempel
        rij.gewijzigd_door = actor_id
        rij.gewijzigd_op = datetime.now(UTC)
        record_audit_event(
            session,
            actor_id=actor_id,
            module="platform",
            tabel="autoboek_instelling",
            record_id=uuid.UUID(int=0),
            actie="autoboek_drempel_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"drempel_op_rij": oud},
            nieuwe_waarde={"drempel_op_rij": drempel},
        )
        return drempel


# ----------------------------------------------------------------------------- verzamelen


@dataclass
class _VendorData:
    boekingen: list[motor.Boeking] = field(default_factory=list)
    gebeurtenissen: list[motor.Gebeurtenis] = field(default_factory=list)
    open_vragen: int = 0
    afgewezen: int = 0
    duplicaatsignalen: int = 0
    observaties: list[Observatie] = field(default_factory=list)
    seed: list[Observatie] = field(default_factory=list)
    actief: bool = False
    actief_sinds: datetime | None = None
    regels_samenvoegen: bool = True
    veldwerker: bool = False
    # Blok A bundel 10-09 (uitzonderingenlijst + reset-stand, migratie 0128).
    uitgezonderd: bool = False
    uitzondering_reden: str | None = None
    bron: str | None = None
    gereset_op: datetime | None = None


def _verzamel(
    session: Session, administratie_id: uuid.UUID, *, vendor_ids: set[uuid.UUID] | None = None
) -> dict[uuid.UUID, _VendorData]:
    """Alle invoer van de motor voor één administratie, in één RLS-gescoopte sessie. `vendor_ids` (blok A 10-09)
    beperkt de documentquery tot die leveranciers (incl. hun cluster-verliezers) — de live activatie ná élke
    mens-boeking leest zo niet de hele administratie."""
    from app.crediteuren.voorkeur import verliezers as verliezers_kaart  # B13 07-09

    data: dict[uuid.UUID, _VendorData] = {}
    # Verliezers van een afgehandeld dubbel-cluster nomineren we nooit: hun historie telt mee op de voorkeur.
    kaart = verliezers_kaart(session, administratie_id=administratie_id)

    def vd(vendor_id: uuid.UUID) -> _VendorData:
        return data.setdefault(kaart.get(vendor_id, vendor_id), _VendorData())

    doc_filter = []
    if vendor_ids is not None:
        bereik = set(vendor_ids) | {verliezer for verliezer, winnaar in kaart.items() if winnaar in vendor_ids}
        doc_filter.append(Boekvoorstel.vendor_id.in_(list(bereik)))

    taxrate_namen = dict(
        session.execute(
            select(TaxRateCache.id, TaxRateCache.naam).where(TaxRateCache.administratie_id == administratie_id)
        ).all()
    )
    docs = session.execute(
        select(Document, Boekvoorstel)
        .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
        .where(
            Document.administratie_id == administratie_id,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Document.status != DocumentStatus.VERWIJDERD,
            Boekvoorstel.vendor_id.is_not(None),
            *doc_filter,
        )
    ).all()
    doc_ids = [d.id for d, _ in docs]
    vendor_per_doc = {d.id: v.vendor_id for d, v in docs}
    voorstel_per_doc = {d.id: v for d, v in docs}
    regels_per_doc: dict[uuid.UUID, list[BoekvoorstelRegel]] = {}
    if doc_ids:
        for regel in session.scalars(
            select(BoekvoorstelRegel).where(BoekvoorstelRegel.document_id.in_(doc_ids)).order_by(BoekvoorstelRegel.volgnummer)
        ):
            regels_per_doc.setdefault(regel.document_id, []).append(regel)
    voorkeuren = {
        v.vendor_id: v
        for v in session.scalars(select(LeverancierVoorkeur).where(LeverancierVoorkeur.administratie_id == administratie_id))
    }
    for vendor_id, voorkeur in voorkeuren.items():
        vd(vendor_id).actief = bool(voorkeur.autoboeken_ingeschakeld)
        vd(vendor_id).regels_samenvoegen = bool(voorkeur.regels_samenvoegen)
        vd(vendor_id).uitgezonderd = bool(voorkeur.autoboeken_uitgezonderd)
        vd(vendor_id).uitzondering_reden = voorkeur.autoboeken_uitzondering_reden
        vd(vendor_id).bron = voorkeur.autoboeken_bron
        vd(vendor_id).gereset_op = voorkeur.autoboeken_gereset_op
        if voorkeur.autoboeken_ingeschakeld:
            vd(vendor_id).actief_sinds = voorkeur.gewijzigd_op
    # Activatiemoment uit het audit log (nauwkeuriger dan gewijzigd_op, dat óók op regels_samenvoegen reageert).
    for record_id, tijdstip, nieuwe in session.execute(
        select(AuditEvent.record_id, AuditEvent.tijdstip, AuditEvent.nieuwe_waarde)
        .where(
            AuditEvent.actie == "leverancier_autoboeken_gewijzigd",
            AuditEvent.administratie_id == administratie_id,
        )
        .order_by(AuditEvent.tijdstip)
    ).all():
        if record_id in data and data[record_id].actief and (nieuwe or {}).get("autoboeken_ingeschakeld") is True:
            data[record_id].actief_sinds = tijdstip
    for koppeling in session.scalars(
        select(VeldwerkerCrediteur).where(VeldwerkerCrediteur.administratie_id == administratie_id)
    ):
        vd(koppeling.vendor_id).veldwerker = True
    for obs in session.scalars(
        select(BoekingObservatie).where(BoekingObservatie.administratie_id == administratie_id)
    ):
        o = Observatie(
            regel_sleutel=obs.regel_sleutel,
            gb_id=obs.gb_id,
            btw_id=obs.btw_id,
            project_id=obs.project_id,
            bron=obs.bron,
            bron_datum=obs.bron_datum,
        )
        vd(obs.vendor_id).observaties.append(o)
        if obs.bron == ObservatieBron.RLZ_SEED.value:
            vd(obs.vendor_id).seed.append(o)
    duplicaat_ids: set[uuid.UUID] = set()
    if doc_ids:
        duplicaat_ids = set(
            session.scalars(
                select(DuplicaatSignaal.document_id).where(
                    DuplicaatSignaal.document_id.in_(doc_ids), DuplicaatSignaal.uitkomst == "mogelijk_duplicaat"
                )
            )
        )
    automatisch_docs: set[uuid.UUID] = set()
    if doc_ids:
        for gebeurtenis in session.scalars(
            select(DocumentGebeurtenis)
            .where(
                DocumentGebeurtenis.document_id.in_(doc_ids),
                DocumentGebeurtenis.naar_status.in_(
                    [DocumentStatus.GEBOEKT, DocumentStatus.VRAAG_OPEN, DocumentStatus.AFGEWEZEN]
                ),
                # Alleen échte overgangen: een tijdlijn-NOTITIE (van = naar, bv. "autoboeken geactiveerd/gereset",
                # blok A 10-09) is geen boeking en telt nooit als bevestiging.
                or_(
                    DocumentGebeurtenis.van_status.is_(None),
                    DocumentGebeurtenis.van_status != DocumentGebeurtenis.naar_status,
                ),
            )
            .order_by(DocumentGebeurtenis.tijdstip)
        ):
            vendor_id = vendor_per_doc[gebeurtenis.document_id]
            if gebeurtenis.naar_status == DocumentStatus.GEBOEKT:
                voorstel = voorstel_per_doc[gebeurtenis.document_id]
                automatisch = bool((gebeurtenis.detail or {}).get("automatisch_geboekt"))
                if automatisch:
                    automatisch_docs.add(gebeurtenis.document_id)
                elif gebeurtenis.document_id in automatisch_docs:
                    # Mens boekt opnieuw ná een automatische boeking (tegenboeken-én-herboeken).
                    vd(vendor_id).gebeurtenissen.append(
                        motor.Gebeurtenis("correctie_automatisch", gebeurtenis.tijdstip, gebeurtenis.document_id)
                    )
                vd(vendor_id).boekingen.append(
                    motor.Boeking(
                        document_id=gebeurtenis.document_id,
                        geboekt_op=gebeurtenis.tijdstip,
                        factuurdatum=voorstel.factuurdatum,
                        totaalbedrag=voorstel.totaalbedrag,
                        regels=tuple(
                            motor.GeboekteRegel(
                                gb_id=r.ledger_id,
                                btw_id=r.taxrate_id,
                                project_id=r.project_id,
                                omschrijving=r.omschrijving,
                                btw_naam=taxrate_namen.get(r.taxrate_id) if r.taxrate_id else None,
                            )
                            for r in regels_per_doc.get(gebeurtenis.document_id, [])
                        ),
                        automatisch=automatisch,
                        regels_samenvoegen=vd(vendor_id).regels_samenvoegen,
                    )
                )
            elif gebeurtenis.naar_status == DocumentStatus.VRAAG_OPEN:
                vd(vendor_id).gebeurtenissen.append(motor.Gebeurtenis("vraag", gebeurtenis.tijdstip, gebeurtenis.document_id))
            else:
                vd(vendor_id).gebeurtenissen.append(motor.Gebeurtenis("afwijzing", gebeurtenis.tijdstip, gebeurtenis.document_id))
        for tb in session.scalars(select(Tegenboeking).where(Tegenboeking.document_id.in_(doc_ids))):
            if tb.document_id in automatisch_docs:
                vd(vendor_per_doc[tb.document_id]).gebeurtenissen.append(
                    motor.Gebeurtenis("correctie_automatisch", tb.aangemaakt_op, tb.document_id)
                )
    for document, voorstel in docs:
        v = vd(voorstel.vendor_id)
        if document.status == DocumentStatus.VRAAG_OPEN:
            v.open_vragen += 1
        elif document.status == DocumentStatus.AFGEWEZEN:
            v.afgewezen += 1
        if document.status in _OPEN_STATUSSEN and (
            document.mogelijk_duplicaat_van_id is not None or document.id in duplicaat_ids
        ):
            v.duplicaatsignalen += 1
    return data


_VELD_NAAM = {1: "grootboek", 2: "btw", 3: "project"}


def _geheugen_bevestigd(
    observaties: list[Observatie],
    *,
    project_verplicht: bool,
    vandaag,
    reeks_waarden: motor.Handtekening = frozenset(),
) -> tuple[bool, str | None]:
    """Zelfde poort als het autoboek-pad (_geheugen_veld_geblokkeerd): élk veld app-bevestigd + groen,
    op leverancier-niveau. Sinds blok 3 10-09 (telling = identieke mens-boekingen, niet meer "ongewijzigd t.o.v.
    het voorstel") toetst deze poort óók dat het geheugen dezelfde waarden voorstelt als de reeks
    (`reeks_waarden`, per regel-sleutel): activeert het systeem, dan boekt het autoboek-pad het VOORSTEL — dat
    moet exact zijn wat de mens de laatste N keer boekte. Nooit gokken."""
    voorstel = bepaal_voorstel(observaties, regel_sleutel=None, vandaag=vandaag)
    velden = [("grootboek", voorstel.gb), ("btw", voorstel.btw)]
    if project_verplicht:
        velden.append(("project", voorstel.project))
    for naam, veld in velden:
        if veld.waarde is None:
            return False, f"geen voorstel voor {naam}"
        if veld.oranje or not veld.app_bevestigd:
            return False, f"{naam}: {veld.reden or 'oranje'}"
    for sleutel, gb_id, btw_id, project_id in sorted(reeks_waarden, key=lambda t: (t[0] or "", str(t[1]))):
        per_regel = (
            voorstel if sleutel is None else bepaal_voorstel(observaties, regel_sleutel=sleutel, vandaag=vandaag)
        )
        verwacht = [(1, gb_id, per_regel.gb.waarde), (2, btw_id, per_regel.btw.waarde)]
        if project_verplicht:
            verwacht.append((3, project_id, per_regel.project.waarde))
        afwijkend = [_VELD_NAAM[i] for i, geboekt, voorgesteld in verwacht if geboekt != voorgesteld]
        if afwijkend:
            return (
                False,
                f"geheugen stelt voor {'/'.join(afwijkend)} nog een andere waarde voor "
                "dan de laatste identieke boekingen",
            )
    return True, None


@dataclass(frozen=True)
class StandData:
    administratie_id: uuid.UUID
    vendor_id: uuid.UUID
    reeks_ongewijzigd: int
    correcties: int
    mens_boekingen: int
    open_vragen: int
    kwalificeert: bool
    actief: bool
    actief_sinds: datetime | None
    redenen: list[str]
    chips: list[str]
    heroverweeg_signalen: list[str]
    laatste_factuur_datum: object
    laatste_factuur_bedrag: Decimal | None
    laatste_document_id: uuid.UUID | None
    # Blok A bundel 10-09: uitzonderingenlijst + herkomst van de opt-in + reset-moment (voor DTO, rapport en activatie).
    uitgezonderd: bool = False
    uitzondering_reden: str | None = None
    bron: str | None = None
    gereset_op: datetime | None = None
    veldwerker: bool = False


def _bereken(vendor_id: uuid.UUID, d: _VendorData, *, administratie_id: uuid.UUID, drempel: int, project_verplicht: bool, nu: datetime) -> StandData:
    reeks = motor.analyseer_reeks(
        d.boekingen,
        seed_observaties=d.seed,
        project_verplicht=project_verplicht,
        vanaf=d.actief_sinds if d.actief else None,
        # Reset ná storno/correctie (blok A 10-09): zolang de opt-in uit staat telt de reeks alleen boekingen ná de
        # reset.
        reeks_vanaf=None if d.actief else d.gereset_op,
    )
    bevestigd, reden = _geheugen_bevestigd(
        d.observaties, project_verplicht=project_verplicht, vandaag=nu.date(), reeks_waarden=reeks.reeks_waarden
    )
    kwal = motor.kwalificeer(
        reeks,
        drempel=drempel,
        geheugen_bevestigd=bevestigd,
        geheugen_reden=reden,
        open_vragen=d.open_vragen,
        afgewezen=d.afgewezen,
        duplicaatsignalen=d.duplicaatsignalen,
        veldwerker_gekoppeld=d.veldwerker,
    )
    signalen = (
        motor.heroverweeg_signalen(reeks, gebeurtenissen=d.gebeurtenissen, actief_sinds=d.actief_sinds) if d.actief else ()
    )
    return StandData(
        administratie_id=administratie_id,
        vendor_id=vendor_id,
        reeks_ongewijzigd=reeks.reeks_ongewijzigd,
        correcties=reeks.correcties,
        mens_boekingen=reeks.mens_boekingen,
        open_vragen=d.open_vragen,
        kwalificeert=kwal.kwalificeert,
        actief=d.actief,
        actief_sinds=d.actief_sinds if d.actief else None,
        redenen=list(kwal.redenen),
        chips=list(kwal.chips),
        heroverweeg_signalen=list(signalen),
        laatste_factuur_datum=reeks.laatste_factuur_datum,
        laatste_factuur_bedrag=reeks.laatste_factuur_bedrag,
        laatste_document_id=reeks.laatste_document_id,
        uitgezonderd=d.uitgezonderd,
        uitzondering_reden=d.uitzondering_reden,
        bron=d.bron,
        gereset_op=d.gereset_op,
        veldwerker=d.veldwerker,
    )


def _upsert(session: Session, stand: StandData) -> AutoboekKandidaatStand:
    rij = session.get(AutoboekKandidaatStand, (stand.administratie_id, stand.vendor_id))
    if rij is None:
        rij = AutoboekKandidaatStand(administratie_id=stand.administratie_id, vendor_id=stand.vendor_id)
        session.add(rij)
    rij.reeks_ongewijzigd = stand.reeks_ongewijzigd
    rij.correcties = stand.correcties
    rij.mens_boekingen = stand.mens_boekingen
    rij.open_vragen = stand.open_vragen
    rij.kwalificeert = stand.kwalificeert
    rij.actief = stand.actief
    rij.actief_sinds = stand.actief_sinds
    rij.redenen = stand.redenen
    rij.chips = stand.chips
    rij.heroverweeg_signalen = stand.heroverweeg_signalen
    rij.laatste_factuur_datum = stand.laatste_factuur_datum
    rij.laatste_factuur_bedrag = stand.laatste_factuur_bedrag
    rij.laatste_document_id = stand.laatste_document_id
    rij.berekend_op = datetime.now(UTC)
    return rij


def herbereken_administratie(*, administratie_id: uuid.UUID, drempel: int | None = None, nu: datetime | None = None) -> dict[str, int]:
    """Herrekent álle vendor-standen van één administratie (UPSERT + opruimen van vervallen rijen —
    vendors zonder mens-boeking én zonder opt-in)."""
    nu = nu or datetime.now(UTC)
    if drempel is None:
        drempel, _ = haal_instelling_op()
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise AutoboekKandidaatFout(f"Onbekende administratie: {administratie_id}")
        project_verplicht = administratie.project_verplicht
        leren_aan = _leren_aan(administratie)
        data = _verzamel(session, administratie_id)
        relevant: set[uuid.UUID] = set()
        tellers = {"kandidaten": 0, "actief": 0, "heroverwegen": 0, "verborgen": 0, "rijen": 0, "geactiveerd": 0}
        te_activeren: list[StandData] = []
        for vendor_id, d in data.items():
            if not d.boekingen and not d.actief:
                continue
            relevant.add(vendor_id)
            stand = _bereken(vendor_id, d, administratie_id=administratie_id, drempel=drempel, project_verplicht=project_verplicht, nu=nu)
            rij = _upsert(session, stand)
            tellers["rijen"] += 1
            if leren_aan and _activatie_blokkade(stand) is None:
                te_activeren.append(stand)
            if rij.actief:
                tellers["actief"] += 1
                if rij.heroverweeg_signalen:
                    tellers["heroverwegen"] += 1
            elif rij.snooze_op is not None:
                tellers["verborgen"] += 1
            elif rij.kwalificeert:
                tellers["kandidaten"] += 1
        for rij in session.scalars(
            select(AutoboekKandidaatStand).where(AutoboekKandidaatStand.administratie_id == administratie_id)
        ).all():
            if rij.vendor_id not in relevant:
                session.delete(rij)
    # Blok A bundel 10-09: schakelaar aan → het systeem ACTIVEERT i.p.v. nomineert (ná de commit van de standen; elke
    # activatie zijn eigen transactie, één kapotte leverancier stopt de rest niet).
    for stand in te_activeren:
        if _activeer_vendor(stand, nu=nu, drempel=drempel) is not None:
            tellers["geactiveerd"] += 1
            tellers["kandidaten"] -= 1
            tellers["actief"] += 1
    return tellers


def herbereken_alle(*, nu: datetime | None = None) -> dict[uuid.UUID, dict[str, int] | str]:
    """Dagelijks meeliftend in sync-alles (ontwerpnotitie ⑦): alleen actieve administraties, één
    kapotte stopt de rest niet; het run-tijdstip landt in de instelling (tabs: "stand van HH:MM")."""
    nu = nu or datetime.now(UTC)
    drempel, _ = haal_instelling_op()
    with scoped_session(None) as session:
        ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True)).order_by(Administratie.naam)))
    resultaten: dict[uuid.UUID, dict[str, int] | str] = {}
    for aid in ids:
        try:
            resultaten[aid] = herbereken_administratie(administratie_id=aid, drempel=drempel, nu=nu)
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de rest niet
            logger.exception("Autoboek-kandidaten herberekenen mislukt voor %s", aid)
            resultaten[aid] = f"{type(exc).__name__}: {exc}"
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        _instelling(session).laatste_run_op = nu
    return resultaten


def hertoets_vendor(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, nu: datetime | None = None) -> StandData:
    """LIVE hertoets van één (administratie, leverancier) — de poort vóór het aanzetten (ontwerpnotitie ②)."""
    nu = nu or datetime.now(UTC)
    drempel, _ = haal_instelling_op()
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise AutoboekKandidaatFout(f"Onbekende administratie: {administratie_id}")
        data = _verzamel(session, administratie_id)
        d = data.get(vendor_id, _VendorData())
        stand = _bereken(vendor_id, d, administratie_id=administratie_id, drempel=drempel, project_verplicht=administratie.project_verplicht, nu=nu)
        if d.boekingen or d.actief:
            _upsert(session, stand)
        return stand


# ----------------------------------------------------------------------------- activeren (blok A bundel 10-09)

#: Stand-enum voor de uitzonderingenlijst en de kandidaten-rijen (CONTRACT_A): leert | boekt_automatisch |
#: uitgezonderd |
#: handmatig_aan (opt-in aan door een mens zonder administratie-schakelaar — de oude opt-in-flow van 01-09).
STAND_LEERT = "leert"
STAND_BOEKT_AUTOMATISCH = "boekt_automatisch"
STAND_UITGEZONDERD = "uitgezonderd"
STAND_HANDMATIG_AAN = "handmatig_aan"

BRON_MENS = "mens"
BRON_SYSTEEM = "systeem"


def stand_label(*, actief: bool, bron: str | None, uitgezonderd: bool, administratie_leren_aan: bool) -> str:
    """Eén bron voor de chip per leverancier (lijst, kandidaten-scherm, rapport-CLI)."""
    if uitgezonderd:
        return STAND_UITGEZONDERD
    if actief:
        return STAND_BOEKT_AUTOMATISCH if (bron == BRON_SYSTEEM or administratie_leren_aan) else STAND_HANDMATIG_AAN
    return STAND_LEERT


def _leren_aan(administratie: Administratie) -> bool:
    """Schakelaar aan én de Kempen-regel niet van toepassing (een doorbelastende administratie activeert nooit —
    ook niet als de kolom ooit tóch op true zou staan)."""
    return bool(administratie.autoboeken_leren_ingeschakeld) and not administratie.doorbelasting_ingeschakeld


def _activatie_blokkade(stand: StandData) -> str | None:
    """Leesbare reden waarom het systeem deze leverancier (nog) niet activeert; None = activeren."""
    if stand.actief:
        return "autoboeken staat al aan"
    if stand.uitgezonderd:
        return "door een mens uitgezonderd" + (f" ({stand.uitzondering_reden})" if stand.uitzondering_reden else "")
    if stand.veldwerker:
        return "crediteur gekoppeld aan een veldwerker — autoboeken loopt via de urenmatch-opt-in (fase 4)"
    if not stand.kwalificeert:
        return "kwalificeert niet: " + "; ".join(stand.redenen)
    return None


@dataclass(frozen=True)
class ActivatieUitkomst:
    administratie_id: uuid.UUID
    vendor_id: uuid.UUID
    status: str  # 'geactiveerd' | 'overgeslagen'
    reden: str | None
    reeks_ongewijzigd: int
    drempel: int


def _activeer_vendor(stand: StandData, *, nu: datetime, drempel: int) -> ActivatieUitkomst | None:
    """Zet de opt-in aan namens het systeem via de BESTAANDE schrijver (zelfde audit `leverancier_autoboeken_gewijzigd`,
    zelfde veldwerker-weigering) mét `autoboeken_bron='systeem'`, werkt de stand bij, schrijft het eigen audit-event
    `autoboek_leverancier_geactiveerd` (onderbouwing = chips + reeks + drempel) en een tijdlijnregel op het document dat
    de drempel haalde. None = niet geactiveerd (veldwerker-weigering — zichtbaar in de log, nooit stil)."""
    from app.documenten import autoboeken

    try:
        autoboeken.zet_leverancier_autoboeken(
            administratie_id=stand.administratie_id,
            vendor_id=stand.vendor_id,
            actor_id=SYSTEEM_ACTOR_ID,
            ingeschakeld=True,
            bron=BRON_SYSTEEM,
        )
    except autoboeken.VeldwerkerKoppelingBlokkeertOptIn as exc:
        logger.info("Autoboeken-activatie overgeslagen voor %s/%s: %s", stand.administratie_id, stand.vendor_id, exc)
        return None
    onderbouwing = {
        "onderbouwing": stand.chips,
        "reeks_ongewijzigd": stand.reeks_ongewijzigd,
        "drempel": drempel,
        "bron": BRON_SYSTEEM,
        "document_id": str(stand.laatste_document_id) if stand.laatste_document_id else None,
    }
    with scoped_session(stand.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(AutoboekKandidaatStand, (stand.administratie_id, stand.vendor_id))
        if rij is not None:
            rij.actief = True
            rij.actief_sinds = nu
            rij.kwalificeert = False
            rij.heroverweeg_signalen = []
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="leverancier_voorkeur",
            record_id=stand.vendor_id,
            actie="autoboek_leverancier_geactiveerd",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde=onderbouwing,
            administratie_id=stand.administratie_id,
        )
        if stand.laatste_document_id is not None:
            document = session.get(Document, stand.laatste_document_id)
            if document is not None:
                naam = session.scalar(select(VendorCache.naam).where(VendorCache.id == stand.vendor_id))
                session.add(
                    DocumentGebeurtenis(
                        document_id=document.id,
                        van_status=document.status,
                        naar_status=document.status,
                        actor_id=SYSTEEM_ACTOR_ID,
                        detail={
                            "autoboek_geactiveerd": {**onderbouwing, "leverancier_naam": naam},
                            "reden": (
                                f"Autoboeken voor {naam or 'deze leverancier'} geactiveerd — "
                                f"{motor.reeks_tekst(stand.reeks_ongewijzigd)} op rij door een mens (drempel {drempel})"
                            ),
                        },
                    )
                )
    return ActivatieUitkomst(
        administratie_id=stand.administratie_id,
        vendor_id=stand.vendor_id,
        status="geactiveerd",
        reden=None,
        reeks_ongewijzigd=stand.reeks_ongewijzigd,
        drempel=drempel,
    )


def activeer_kwalificerend(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None = None, nu: datetime | None = None
) -> list[ActivatieUitkomst]:
    """Blok A bundel 10-09 (besluit Peter 10-09): staat de administratie-schakelaar "Autoboeken (leren en boeken)" aan,
    dan ACTIVEERT het systeem élke leverancier die kwalificeert (bestaande poort `motor.kwalificeer` — ≥ drempel
    IDENTIEKE mens-boekingen op rij (telling herzien 10-09 avond, blok 3: de eerste boeking telt als 1), geheugen
    volledig app-bevestigd én gelijk aan de reeks, geen open vraag/afwijzing/duplicaatsignaal, geen
    veldwerker-koppeling) en niet door een mens is uitgezonderd. Zonder schakelaar (of bij doorbelasting): lege lijst —
    het gedrag van 01-09 (nomineren) blijft. Aangeroepen (1) post-commit ná élke GEBOEKT-overgang door een mens
    (documenten/boeken.py), (2) in `herbereken_administratie` (dagelijks), (3) bij aanzetten van de schakelaar en bij
    vrijgeven van een uitzondering. Lees-only voor niet-kwalificerende leveranciers (uitkomst 'overgeslagen' mét
    reden)."""
    nu = nu or datetime.now(UTC)
    drempel, _ = haal_instelling_op()
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise AutoboekKandidaatFout(f"Onbekende administratie: {administratie_id}")
        if not _leren_aan(administratie):
            return []
        data = _verzamel(session, administratie_id, vendor_ids={vendor_id} if vendor_id is not None else None)
        standen = [
            _bereken(
                v, d, administratie_id=administratie_id, drempel=drempel, project_verplicht=administratie.project_verplicht, nu=nu
            )
            for v, d in data.items()
            if d.boekingen or d.actief
        ]
        for stand in standen:
            _upsert(session, stand)
    uit: list[ActivatieUitkomst] = []
    for stand in standen:
        blokkade = _activatie_blokkade(stand)
        if blokkade is not None:
            uit.append(
                ActivatieUitkomst(
                    administratie_id, stand.vendor_id, "overgeslagen", blokkade, stand.reeks_ongewijzigd, drempel
                )
            )
            continue
        uitkomst = _activeer_vendor(stand, nu=nu, drempel=drempel)
        uit.append(
            uitkomst
            or ActivatieUitkomst(
                administratie_id, stand.vendor_id, "overgeslagen", "veldwerker-koppeling", stand.reeks_ongewijzigd, drempel
            )
        )
    return uit


def activeer_kwalificerend_stil(
    *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None = None
) -> list[ActivatieUitkomst]:
    """Post-commit-variant: een fout hier blokkeert nooit de boeking/instelling (gelogd, niet stil: de dagelijkse
    herberekening haalt het in)."""
    try:
        return activeer_kwalificerend(administratie_id=administratie_id, vendor_id=vendor_id)
    except Exception:  # noqa: BLE001 — optimalisatie, nooit een blokkade van de boeking
        logger.exception("Autoboeken-activatie mislukt voor administratie %s (vendor %s)", administratie_id, vendor_id)
        return []


def activeer_na_boeking_stil(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> list[ActivatieUitkomst]:
    """Hook ná een GEBOEKT-overgang door een MENS (documenten/boeken.py, post-commit): herleidt de leverancier van het
    document en toetst alleen díe. Goedkoop als de schakelaar uit staat (één administratie-read)."""
    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not _leren_aan(administratie):
            return []
        vendor_id = session.scalar(select(Boekvoorstel.vendor_id).where(Boekvoorstel.document_id == document_id))
    if vendor_id is None:
        return []
    return activeer_kwalificerend_stil(administratie_id=administratie_id, vendor_id=vendor_id)


def bereken_standen(*, administratie_id: uuid.UUID, nu: datetime | None = None) -> list[StandData]:
    """LEES-ONLY: de stand per leverancier uit de bestaande historie in de module, zonder iets te schrijven —
    het nameting-instrument (CLI `autoboek-leren-rapport`)."""
    nu = nu or datetime.now(UTC)
    drempel, _ = haal_instelling_op()
    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            raise AutoboekKandidaatFout(f"Onbekende administratie: {administratie_id}")
        data = _verzamel(session, administratie_id)
        return [
            _bereken(
                v, d, administratie_id=administratie_id, drempel=drempel, project_verplicht=administratie.project_verplicht, nu=nu
            )
            for v, d in data.items()
            if d.boekingen or d.actief
        ]


# ----------------------------------------------------------------------------- lezen


@dataclass(frozen=True)
class KandidaatRij:
    administratie_id: uuid.UUID
    administratie_naam: str
    vendor_id: uuid.UUID
    leverancier_naam: str | None
    reeks_ongewijzigd: int
    correcties: int
    open_vragen: int
    kwalificeert: bool
    actief: bool
    actief_sinds: datetime | None
    redenen: list[str]
    chips: list[str]
    heroverweeg_signalen: list[str]
    laatste_factuur_datum: object
    laatste_factuur_bedrag: Decimal | None
    laatste_document_id: uuid.UUID | None
    snooze_reden: str | None
    snooze_op: datetime | None
    berekend_op: datetime
    # Blok A bundel 10-09: staat de administratie-schakelaar aan (chip "administratie leert zelf") + de stand-enum.
    administratie_leren_aan: bool = False
    stand: str = STAND_LEERT


@dataclass(frozen=True)
class Tellers:
    kandidaten: int
    actief: int
    heroverwegen: int
    verborgen: int
    administraties_met_kandidaten: int
    drempel: int
    laatste_run_op: datetime | None


@dataclass(frozen=True)
class Lijst:
    rijen: list[KandidaatRij]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: Tellers


TABS = ("kandidaten", "actief", "heroverwegen")


def _alle_rijen() -> list[KandidaatRij]:
    with scoped_session(None) as session:
        administraties = list(
            session.execute(
                select(
                    Administratie.id,
                    Administratie.naam,
                    Administratie.autoboeken_leren_ingeschakeld,
                    Administratie.doorbelasting_ingeschakeld,
                )
                .where(Administratie.actief.is_(True))
                .order_by(Administratie.naam)
            ).all()
        )
    uit: list[KandidaatRij] = []
    for aid, naam, leren, doorbelasting in administraties:
        leren_aan = bool(leren) and not doorbelasting
        with scoped_session(aid) as session:
            rijen = session.scalars(select(AutoboekKandidaatStand).where(AutoboekKandidaatStand.administratie_id == aid)).all()
            if not rijen:
                continue
            namen = dict(
                session.execute(
                    select(VendorCache.id, VendorCache.naam).where(VendorCache.id.in_([r.vendor_id for r in rijen]))
                ).all()
            )
            voorkeuren = {
                v.vendor_id: v
                for v in session.scalars(select(LeverancierVoorkeur).where(LeverancierVoorkeur.administratie_id == aid))
            }
            for r in rijen:
                voorkeur = voorkeuren.get(r.vendor_id)
                uit.append(
                    KandidaatRij(
                        administratie_id=aid,
                        administratie_naam=naam,
                        vendor_id=r.vendor_id,
                        leverancier_naam=namen.get(r.vendor_id),
                        reeks_ongewijzigd=r.reeks_ongewijzigd,
                        correcties=r.correcties,
                        open_vragen=r.open_vragen,
                        kwalificeert=r.kwalificeert,
                        actief=r.actief,
                        actief_sinds=r.actief_sinds,
                        redenen=list(r.redenen or []),
                        chips=list(r.chips or []),
                        heroverweeg_signalen=list(r.heroverweeg_signalen or []),
                        laatste_factuur_datum=r.laatste_factuur_datum,
                        laatste_factuur_bedrag=r.laatste_factuur_bedrag,
                        laatste_document_id=r.laatste_document_id,
                        snooze_reden=r.snooze_reden,
                        snooze_op=r.snooze_op,
                        berekend_op=r.berekend_op,
                        administratie_leren_aan=leren_aan,
                        stand=stand_label(
                            actief=r.actief,
                            bron=voorkeur.autoboeken_bron if voorkeur else None,
                            uitgezonderd=bool(voorkeur and voorkeur.autoboeken_uitgezonderd),
                            administratie_leren_aan=leren_aan,
                        ),
                    )
                )
    return uit


def _tab_rij(r: KandidaatRij) -> str | None:
    if r.actief:
        return "actief"
    if r.snooze_op is not None:
        return "verborgen"
    if r.kwalificeert:
        return "kandidaten"
    return None


def tellers() -> Tellers:
    rijen = _alle_rijen()
    drempel, laatste_run = haal_instelling_op()
    kandidaten = [r for r in rijen if _tab_rij(r) == "kandidaten"]
    return Tellers(
        kandidaten=len(kandidaten),
        actief=sum(1 for r in rijen if r.actief),
        heroverwegen=sum(1 for r in rijen if r.actief and r.heroverweeg_signalen),
        verborgen=sum(1 for r in rijen if _tab_rij(r) == "verborgen"),
        administraties_met_kandidaten=len({r.administratie_id for r in kandidaten}),
        drempel=drempel,
        laatste_run_op=laatste_run,
    )


def _filter_selectie(rijen: list[KandidaatRij], *, tab: str, q: str, verborgen: bool) -> list[KandidaatRij]:
    """Dé filterbron van de lijst (tab + zoekterm + verborgen-filter, gesorteerd urgentste bovenaan) —
    gedeeld door `lijst` (mét paginering) en `rijen_binnen_filter` (zonder, voor "Selecteer alle N")."""
    if tab not in TABS:
        raise AutoboekKandidaatFout(f"Onbekende tab: {tab}")
    if tab == "kandidaten":
        doel = "verborgen" if verborgen else "kandidaten"
        selectie = [r for r in rijen if _tab_rij(r) == doel]
    elif tab == "actief":
        selectie = [r for r in rijen if r.actief]
    else:
        selectie = [r for r in rijen if r.actief and r.heroverweeg_signalen]
    zoek = q.strip().lower()
    if zoek:
        selectie = [
            r for r in selectie if zoek in (r.leverancier_naam or "").lower() or zoek in r.administratie_naam.lower()
        ]
    selectie.sort(
        key=lambda r: (-r.reeks_ongewijzigd, (r.leverancier_naam or "").lower(), r.administratie_naam.lower())
    )
    return selectie


def rijen_binnen_filter(*, tab: str, q: str = "", verborgen: bool = False) -> list[KandidaatRij]:
    """"Selecteer alle N resultaten" (B5.2, 03-09): exact de rijen die de lijst mét deze filters zou tonen,
    ZONDER paginering — de bulk-endpoints verwerken ze daarna met dezelfde per-rij-hertoets/uitkomst."""
    return _filter_selectie(_alle_rijen(), tab=tab, q=q, verborgen=verborgen)


def lijst(*, tab: str, q: str = "", pagina: int = 1, per_pagina: int = 25, verborgen: bool = False) -> Lijst:
    """Tab-inhoud (Kandidaten / Actief / Heroverwegen; Kandidaten mét `verborgen=True` = de gesnoozede
    rijen), zoekterm op leverancier óf administratie, paginering 25 (patroon /gebruikers)."""
    rijen = _alle_rijen()
    drempel, laatste_run = haal_instelling_op()
    selectie = _filter_selectie(rijen, tab=tab, q=q, verborgen=verborgen)
    totaal = len(selectie)
    start = max(pagina - 1, 0) * per_pagina
    kandidaten = [r for r in rijen if _tab_rij(r) == "kandidaten"]
    return Lijst(
        rijen=selectie[start : start + per_pagina],
        totaal=totaal,
        pagina=pagina,
        per_pagina=per_pagina,
        tellers=Tellers(
            kandidaten=len(kandidaten),
            actief=sum(1 for r in rijen if r.actief),
            heroverwegen=sum(1 for r in rijen if r.actief and r.heroverweeg_signalen),
            verborgen=sum(1 for r in rijen if _tab_rij(r) == "verborgen"),
            administraties_met_kandidaten=len({r.administratie_id for r in kandidaten}),
            drempel=drempel,
            laatste_run_op=laatste_run,
        ),
    )


# ----------------------------------------------------------------------------- acties


@dataclass(frozen=True)
class AanzetUitkomst:
    administratie_id: uuid.UUID
    vendor_id: uuid.UUID
    status: str  # aanzetten: 'aangezet' | 'overgeslagen' | 'fout' — verbergen: 'verborgen' | 'overgeslagen' | 'fout'
    reden: str | None
    leverancier_naam: str | None = None
    administratie_naam: str | None = None


_Sleutel = tuple[uuid.UUID, uuid.UUID]


def _naam_kaart() -> dict[_Sleutel, tuple[str | None, str]]:
    """(administratie, vendor) → (leverancier-naam, administratie-naam) voor leesbare bulk-uitkomsten —
    óók voor rijen buiten de huidige pagina ("Selecteer alle N")."""
    return {(r.administratie_id, r.vendor_id): (r.leverancier_naam, r.administratie_naam) for r in _alle_rijen()}


def _met_namen(uitkomsten: list[AanzetUitkomst], namen: dict[_Sleutel, tuple[str | None, str]]) -> list[AanzetUitkomst]:
    uit: list[AanzetUitkomst] = []
    for u in uitkomsten:
        lev, adm = namen.get((u.administratie_id, u.vendor_id), (None, None))
        uit.append(AanzetUitkomst(u.administratie_id, u.vendor_id, u.status, u.reden, lev, adm))
    return uit


def bulk_aanzetten(*, items: list[_Sleutel], actor_id: uuid.UUID) -> list[AanzetUitkomst]:
    """"Autoboeken aanzetten (n)": per rij LIVE hertoetsen; kwalificeert de rij niet (meer) → overgeslagen
    mét reden (uitkomst-patroon bulk-accordering); anders via de BESTAANDE opt-in-schrijver aanzetten
    (zelfde audit + poorten, incl. de veldwerker-weigering) + eigen audit met de onderbouwing."""
    return _met_namen(_bulk_aanzetten(items=items, actor_id=actor_id), _naam_kaart())


def _bulk_aanzetten(*, items: list[_Sleutel], actor_id: uuid.UUID) -> list[AanzetUitkomst]:
    from app.documenten import autoboeken

    uit: list[AanzetUitkomst] = []
    for administratie_id, vendor_id in items:
        try:
            stand = hertoets_vendor(administratie_id=administratie_id, vendor_id=vendor_id)
        except AutoboekKandidaatFout as exc:
            uit.append(AanzetUitkomst(administratie_id, vendor_id, "fout", str(exc)))
            continue
        if stand.actief:
            uit.append(AanzetUitkomst(administratie_id, vendor_id, "overgeslagen", "autoboeken staat al aan"))
            continue
        if not stand.kwalificeert:
            uit.append(
                AanzetUitkomst(
                    administratie_id, vendor_id, "overgeslagen", "kwalificeert niet meer: " + "; ".join(stand.redenen)
                )
            )
            continue
        try:
            autoboeken.zet_leverancier_autoboeken(
                administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor_id, ingeschakeld=True
            )
        except autoboeken.VeldwerkerKoppelingBlokkeertOptIn as exc:
            uit.append(AanzetUitkomst(administratie_id, vendor_id, "overgeslagen", str(exc)))
            continue
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            rij = session.get(AutoboekKandidaatStand, (administratie_id, vendor_id))
            if rij is not None:
                rij.actief = True
                rij.actief_sinds = datetime.now(UTC)
                rij.heroverweeg_signalen = []
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="autoboek_kandidaat_stand",
                record_id=vendor_id,
                actie="autoboek_kandidaat_aangezet",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde={"onderbouwing": stand.chips, "reeks_ongewijzigd": stand.reeks_ongewijzigd},
                administratie_id=administratie_id,
            )
        uit.append(AanzetUitkomst(administratie_id, vendor_id, "aangezet", None))
    return uit


def uitzetten(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Heroverwegen → "Uitzetten": één klik, via de bestaande opt-in-schrijver (audit); de leverancier
    verschijnt pas weer als kandidaat als de reeks opnieuw aan de drempel komt."""
    from app.documenten import autoboeken

    with scoped_session(administratie_id) as session:
        administratie = session.get(Administratie, administratie_id)
        leren_aan = administratie is not None and _leren_aan(administratie)
    if leren_aan:
        # Blok A bundel 10-09: met de administratie-schakelaar aan zou het systeem de leverancier bij de volgende run
        # meteen weer activeren — "uitzetten" ís dan uitzonderen (mét reden, zichtbaar in de uitzonderingenlijst).
        autoboeken.zonder_leverancier_uit(
            administratie_id=administratie_id,
            vendor_id=vendor_id,
            actor_id=actor_id,
            reden="uitgezet via Heroverwegen (Instellingen › Autoboeken)",
        )
    else:
        autoboeken.zet_leverancier_autoboeken(
            administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor_id, ingeschakeld=False
        )
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(AutoboekKandidaatStand, (administratie_id, vendor_id))
        if rij is not None:
            rij.actief = False
            rij.actief_sinds = None
            rij.heroverweeg_signalen = []
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="autoboek_kandidaat_stand",
            record_id=vendor_id,
            actie="autoboek_heroverwogen_uitgezet",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={"autoboeken_ingeschakeld": False},
            administratie_id=administratie_id,
        )
    # De reeks moet ná deze menskeuze opnieuw opbouwen: stand vers herrekenen.
    hertoets_vendor(administratie_id=administratie_id, vendor_id=vendor_id)


def verbergen(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID, reden: str) -> None:
    """"Kandidaat verbergen" = snooze per (administratie, leverancier) mét VERPLICHTE reden, geaudit,
    terugvindbaar onder het filter "verborgen" — nooit stil weg (ontwerpnotitie ④)."""
    reden = reden.strip()
    if not reden:
        raise AutoboekKandidaatFout("Een reden is verplicht bij het verbergen van een kandidaat")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(AutoboekKandidaatStand, (administratie_id, vendor_id))
        if rij is None:
            raise AutoboekKandidaatFout("Onbekende kandidaat")
        oud = rij.snooze_reden
        rij.snooze_reden = reden
        rij.snooze_op = datetime.now(UTC)
        rij.snooze_door = actor_id
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="autoboek_kandidaat_stand",
            record_id=vendor_id,
            actie="autoboek_kandidaat_verborgen",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"snooze_reden": oud},
            nieuwe_waarde={"snooze_reden": reden},
            administratie_id=administratie_id,
        )


def bulk_verbergen(*, items: list[_Sleutel], actor_id: uuid.UUID, reden: str) -> list[AanzetUitkomst]:
    """"Kandidaat verbergen" in bulk, server-side in één call (B5.1, design-ronde 03-09): per rij
    `verbergen` (zelfde audit `autoboek_kandidaat_verborgen`), élke rij zijn eigen transactie zodat één
    fout de rest niet stopt; uitkomst per rij verborgen | overgeslagen mét reden | fout (patroon
    `bulk_aanzetten`). Verbergen geldt voor kandidaten: een actieve opt-in of een al verborgen rij wordt
    overgeslagen mét reden — nooit stil."""
    reden = reden.strip()
    if not reden:
        raise AutoboekKandidaatFout("Een reden is verplicht bij het verbergen van een kandidaat")
    uit: list[AanzetUitkomst] = []
    for administratie_id, vendor_id in items:
        try:
            with scoped_session(administratie_id, actor_id=actor_id) as session:
                rij = session.get(AutoboekKandidaatStand, (administratie_id, vendor_id))
                if rij is None:
                    uit.append(AanzetUitkomst(administratie_id, vendor_id, "overgeslagen", "onbekende kandidaat"))
                    continue
                if rij.actief:
                    reden_actief = "autoboeken staat aan — uitzetten via Actief/Heroverwegen"
                    uit.append(AanzetUitkomst(administratie_id, vendor_id, "overgeslagen", reden_actief))
                    continue
                if rij.snooze_op is not None:
                    uit.append(AanzetUitkomst(administratie_id, vendor_id, "overgeslagen", "al verborgen"))
                    continue
            verbergen(administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor_id, reden=reden)
        except AutoboekKandidaatFout as exc:
            uit.append(AanzetUitkomst(administratie_id, vendor_id, "overgeslagen", str(exc)))
            continue
        except Exception as exc:  # noqa: BLE001 — één kapotte rij stopt de rest niet; zichtbaar als 'fout'
            logger.exception("bulk_verbergen: rij %s/%s mislukt", administratie_id, vendor_id)
            uit.append(AanzetUitkomst(administratie_id, vendor_id, "fout", f"{type(exc).__name__}: {exc}"))
            continue
        uit.append(AanzetUitkomst(administratie_id, vendor_id, "verborgen", None))
    return _met_namen(uit, _naam_kaart())


def toon_weer(*, administratie_id: uuid.UUID, vendor_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(AutoboekKandidaatStand, (administratie_id, vendor_id))
        if rij is None:
            raise AutoboekKandidaatFout("Onbekende kandidaat")
        oud = rij.snooze_reden
        rij.snooze_reden = None
        rij.snooze_op = None
        rij.snooze_door = None
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="autoboek_kandidaat_stand",
            record_id=vendor_id,
            actie="autoboek_kandidaat_weer_getoond",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"snooze_reden": oud},
            nieuwe_waarde={"snooze_reden": None},
            administratie_id=administratie_id,
        )


def tel_kandidaten_snel() -> int:
    """Nav-stand-chip (Instellingen v3): aantal kandidaten over alle administraties."""
    totaal = 0
    with scoped_session(None) as session:
        ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))))
    for aid in ids:
        with scoped_session(aid) as session:
            totaal += int(
                session.scalar(
                    select(func.count())
                    .select_from(AutoboekKandidaatStand)
                    .where(
                        AutoboekKandidaatStand.administratie_id == aid,
                        AutoboekKandidaatStand.kwalificeert.is_(True),
                        AutoboekKandidaatStand.actief.is_(False),
                        AutoboekKandidaatStand.snooze_op.is_(None),
                    )
                )
                or 0
            )
    return totaal
