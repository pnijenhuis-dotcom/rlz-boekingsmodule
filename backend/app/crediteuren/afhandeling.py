"""Crediteuren-dubbelen schaalbaar — afhandeling (blok B13 fixrun 07-09; richting Peter 06-09).

Doel verlegd: RLZ-archivering is geen doel meer. Een afgehandeld cluster maakt de VERLIEZERS in de module
onbruikbaar (`vendor_cache.voorkeur_vendor_id`, één bron: `app/crediteuren/voorkeur.py`) en verhuist wat de
voorkeur nodig heeft: boekingsgeheugen (append-only kopieën), btw-/KvK-kenmerk (als de voorkeur dat mist),
vertrouwde IBAN's en de OPEN boekvoorstellen die nog een verliezer droegen (hervertaald naar de voorkeur, mét
spoor). Alles in één transactie per cluster, geauditeerd, en TERUGDRAAIBAAR via de log-tabel
`crediteur_dubbel_afhandeling` (migratie 0117) die de oude stand bewaart.

Classificatie (deterministisch, puur code):
  EENDUIDIG  = (genormaliseerde naam identiek óf IBAN identiek) én geen conflicterend KvK-/btw-nummer én élke
               niet-voorkeur-kaart draagt ≤ N boekingen/geheugenregels (N = settings, default 3) én op geen
               verliezer rust een menskeuze (autoboek-opt-in, veldwerker-koppeling).
  TWIJFEL    = alles anders — blijft voor de mens in de lijst, mét de reden op de rij.
Een cluster dat alléén op btw-/KvK-nummer dubbel is (namen én IBAN's verschillen) is bewust twijfel: een fiscale
eenheid deelt één btw-nummer over verschillende bedrijven.

Waarom géén RLZ-open-posten-toets (v2 03-09 had die): die toets bewaakte het ARCHIVEREN in RLZ (een gearchiveerde
crediteur mét open post is dáár een probleem). Een markering in de module raakt RLZ niet — open posten worden
in RLZ gewoon afgeletterd, ongeacht onze voorkeur. Dat bespaart bovendien N RLZ-calls per cluster (271 clusters =
honderden calls per run). Geen RLZ-write, nooit verwijderen."""

from __future__ import annotations

import csv
import io
import logging
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.crediteuren import service
from app.crediteuren.models import CrediteurArchiveerWerklijst, CrediteurDubbelAfhandeling
from app.db.audit import record_audit_event
from app.db.models import Administratie, GebruikerRol
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Boekvoorstel, CrediteurKenmerk, Document, DocumentStatus, LeverancierVoorkeur
from app.sync.models import VendorCache
from app.uren.models import VeldwerkerCrediteur

logger = logging.getLogger(__name__)

#: Statussen waarin een boekvoorstel historie is en NIET hervertaald wordt (zelfde set als
#: `odoo.mapping.TERMINALE_STATUSSEN` — hier los gedeclareerd om geen Odoo-import in de crediteurenlaag te trekken).
TERMINALE_STATUSSEN: tuple[DocumentStatus, ...] = (
    DocumentStatus.GEBOEKT,
    DocumentStatus.AFGEWEZEN,
    DocumentStatus.VERWIJDERD,
    DocumentStatus.GESPLITST,
    DocumentStatus.SAMENGEVOEGD,
    DocumentStatus.GEACCORDEERD,
)

MAX_VOORBEELDEN = 200


class AfhandelingFout(service.CrediteurenFout):
    pass


# ----------------------------------------------------------------------------- classificatie


@dataclass(frozen=True)
class Classificatie:
    eenduidig: bool
    reden: str
    voorkeur_vendor_id: uuid.UUID
    verliezer_vendor_ids: list[uuid.UUID]


def _btw_verschilt(kaarten: list[service.Kaart]) -> bool:
    return len({k.btw_nummer for k in kaarten if k.btw_nummer}) >= 2


def classificeer(
    cluster: service.Cluster, *, max_boekingen: int | None = None, menskeuze: frozenset[uuid.UUID] = frozenset()
) -> Classificatie:
    """Eenduidig vs twijfel — puur op de kaartgegevens van het cluster (geen RLZ-call). `menskeuze` = vendor-id's
    waarop een autoboek-opt-in of veldwerker-koppeling rust (die verhuizen bewust niet automatisch)."""
    grens = settings.crediteur_dubbel_auto_max_boekingen_verliezer if max_boekingen is None else max_boekingen
    kaarten = cluster.crediteuren
    voorkeur = cluster.voorkeur_suggestie
    verliezers = [k for k in kaarten if k.vendor_id != voorkeur]
    soorten = {s for s, _ in cluster.sleutels}
    twijfel: list[str] = []
    if not soorten & {"naam", "iban"}:
        twijfel.append("alleen zelfde btw-/KvK-nummer — naam en IBAN verschillen (fiscale eenheid mogelijk)")
    if service._kvk_verschilt(kaarten):
        twijfel.append("verschillend KvK-nummer")
    if _btw_verschilt(kaarten):
        twijfel.append("verschillend btw-nummer")
    for k in verliezers:
        if k.aantal_boekingen > grens:
            twijfel.append(f"{k.naam or str(k.vendor_id)[:8]} heeft {k.aantal_boekingen} boekingen (> {grens})")
        if k.vendor_id in menskeuze:
            twijfel.append(f"autoboek-opt-in of veldwerker-koppeling op {k.naam or str(k.vendor_id)[:8]}")
    if twijfel:
        return Classificatie(False, "twijfel: " + "; ".join(twijfel), voorkeur, [k.vendor_id for k in verliezers])
    basis = "identieke naam" if "naam" in soorten else "identiek IBAN"
    if "naam" in soorten and "iban" in soorten:
        basis = "identieke naam én IBAN"
    hoogste = max((k.aantal_boekingen for k in verliezers), default=0)
    reden = f"eenduidig: {basis}, geen conflicterend KvK/btw, verliezer(s) hooguit {hoogste} boeking(en) (≤ {grens})"
    return Classificatie(True, reden, voorkeur, [k.vendor_id for k in verliezers])


def menskeuze_vendors(session: Session, *, administratie_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """Crediteuren waarop een menskeuze rust: autoboek-opt-in (leverancier_voorkeur) of veldwerker-koppeling."""
    opt_in = set(
        session.scalars(
            select(LeverancierVoorkeur.vendor_id).where(
                LeverancierVoorkeur.administratie_id == administratie_id,
                LeverancierVoorkeur.autoboeken_ingeschakeld.is_(True),
            )
        )
    )
    veld = set(
        session.scalars(
            select(VeldwerkerCrediteur.vendor_id).where(VeldwerkerCrediteur.administratie_id == administratie_id)
        )
    )
    return frozenset(opt_in | veld)


# ----------------------------------------------------------------------------- kern: één cluster afhandelen


@dataclass(frozen=True)
class Afgehandeld:
    afhandeling_id: uuid.UUID
    voorkeur_vendor_id: uuid.UUID
    voorkeur_naam: str | None
    verliezer_namen: list[str]
    geheugen_verhuisd: int
    kenmerk_verhuisd: bool
    ibans_verhuisd: int
    boekvoorstellen_hervertaald: int


def _hervertaal_boekvoorstellen(
    session: Session, *, administratie_id: uuid.UUID, verliezers: list[uuid.UUID], voorkeur: uuid.UUID
) -> list[dict]:
    """Open boekvoorstellen (niet-terminale documentstatus) die nog een verliezer dragen → voorkeur. Geboekte en
    andere terminale documenten blijven onaangeroerd (historie). Spoor per document voor terugdraaien."""
    rijen = session.execute(
        select(Boekvoorstel, Document.id)
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(
            Document.administratie_id == administratie_id,
            Document.status.not_in(list(TERMINALE_STATUSSEN)),
            Boekvoorstel.vendor_id.in_(verliezers),
        )
    ).all()
    spoor: list[dict] = []
    for voorstel, document_id in rijen:
        spoor.append({"document_id": str(document_id), "van_vendor_id": str(voorstel.vendor_id)})
        voorstel.vendor_id = voorkeur
    return spoor


def handel_af(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    voorkeur: uuid.UUID,
    verliezers: list[uuid.UUID],
    sleutels: list[tuple[str, str]],
    reden: str,
    bron: str,
    actor_id: uuid.UUID,
    run_id: uuid.UUID,
) -> Afgehandeld:
    """De kern (mens én systeem): markeer verliezers, verhuis geheugen/kenmerk/IBAN's, hervertaal open
    boekvoorstellen, sla ketens plat, schrijf de log-rij + audit. Eén transactie = de sessie van de aanroeper.
    Weigert (fail-closed) als een lid al een verliezer is — de volgende run pakt het cluster opnieuw op."""
    if bron not in ("auto", "mens"):
        raise AfhandelingFout(f"Onbekende bron: {bron}")
    verliezers = [v for v in dict.fromkeys(verliezers) if v != voorkeur]
    if not verliezers:
        raise AfhandelingFout("Kies minstens één andere crediteur als verliezer")
    leden = [voorkeur, *verliezers]
    rijen = {
        r.id: r
        for r in session.scalars(
            select(VendorCache).where(VendorCache.administratie_id == administratie_id, VendorCache.id.in_(leden))
        )
    }
    ontbrekend = [v for v in leden if v not in rijen]
    if ontbrekend:
        raise AfhandelingFout(f"Onbekende crediteur in deze administratie: {ontbrekend[0]}")
    al_verliezer = [v for v in leden if rijen[v].voorkeur_vendor_id is not None]
    if al_verliezer:
        raise AfhandelingFout(
            f"Crediteur {rijen[al_verliezer[0]].naam or al_verliezer[0]} is al afgehandeld als verliezer — "
            "cluster wordt bij de volgende run opnieuw beoordeeld"
        )

    correlatie = uuid.uuid4()
    geheugen: list[list[str]] = []
    kenmerk_oud: dict | None = None
    ibans: list[str] = []
    for v in verliezers:
        geheugen.extend(
            [list(p) for p in service.verhuis_geheugen(
                session,
                administratie_id=administratie_id,
                bron_vendor_id=v,
                voorkeur=voorkeur,
                actor_id=actor_id,
                correlatie=correlatie,
            )]
        )
        oud = service.verhuis_kenmerk(
            session,
            administratie_id=administratie_id,
            bron_vendor_id=v,
            voorkeur=voorkeur,
            actor_id=actor_id,
            correlatie=correlatie,
        )
        if oud is not None and kenmerk_oud is None:
            kenmerk_oud = oud  # de eerste verhuizing bepaalt de oude stand van de voorkeur
        ibans.extend(
            service.verhuis_ibans(
                session,
                administratie_id=administratie_id,
                bron_vendor_id=v,
                voorkeur=voorkeur,
                actor_id=actor_id,
                correlatie=correlatie,
            )
        )
    boekvoorstellen = _hervertaal_boekvoorstellen(
        session, administratie_id=administratie_id, verliezers=verliezers, voorkeur=voorkeur
    )

    nu = datetime.now(UTC)
    for v in verliezers:
        rij = rijen[v]
        rij.voorkeur_vendor_id = voorkeur
        rij.dubbel_afgehandeld_op = nu
        rij.dubbel_afgehandeld_door = actor_id
        rij.dubbel_afgehandeld_bron = bron
    # Ketens platslaan: eerdere verliezers die naar een nieuwe verliezer wezen, wijzen nu naar de voorkeur.
    herwezen: list[dict] = []
    for rij in session.scalars(
        select(VendorCache).where(
            VendorCache.administratie_id == administratie_id, VendorCache.voorkeur_vendor_id.in_(verliezers)
        )
    ):
        if rij.id in rijen:
            continue
        herwezen.append({"vendor_id": str(rij.id), "van_voorkeur_id": str(rij.voorkeur_vendor_id)})
        rij.voorkeur_vendor_id = voorkeur

    log = CrediteurDubbelAfhandeling(
        id=uuid.uuid4(),
        administratie_id=administratie_id,
        run_id=run_id,
        bron=bron,
        voorkeur_vendor_id=voorkeur,
        voorkeur_naam=rijen[voorkeur].naam,
        verliezers=[{"vendor_id": str(v), "naam": rijen[v].naam} for v in verliezers],
        sleutels=[{"soort": s, "sleutel": w} for s, w in sleutels],
        classificatie_reden=reden,
        verhuisd={
            "geheugen": geheugen,
            "kenmerk_oud": kenmerk_oud,
            "ibans": ibans,
            "boekvoorstellen": boekvoorstellen,
            "herwezen": herwezen,
        },
        afgehandeld_door=actor_id,
    )
    session.add(log)
    session.flush()
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="crediteur_dubbel_afhandeling",
        record_id=log.id,
        actie="crediteur_dubbel_afgehandeld",
        correlatie_id=correlatie,
        oude_waarde={"verliezers": [{"vendor_id": str(v), "voorkeur_vendor_id": None} for v in verliezers]},
        nieuwe_waarde={
            "bron": bron,
            "run_id": str(run_id),
            "voorkeur_vendor_id": str(voorkeur),
            "voorkeur_naam": rijen[voorkeur].naam,
            "verliezers": log.verliezers,
            "sleutels": log.sleutels,
            "reden": reden,
            "geheugen_verhuisd": len(geheugen),
            "kenmerk_verhuisd": kenmerk_oud is not None,
            "ibans_verhuisd": len(ibans),
            "boekvoorstellen_hervertaald": len(boekvoorstellen),
            "herwezen": herwezen,
        },
        administratie_id=administratie_id,
    )
    return Afgehandeld(
        afhandeling_id=log.id,
        voorkeur_vendor_id=voorkeur,
        voorkeur_naam=rijen[voorkeur].naam,
        verliezer_namen=[str(rijen[v].naam or v) for v in verliezers],
        geheugen_verhuisd=len(geheugen),
        kenmerk_verhuisd=kenmerk_oud is not None,
        ibans_verhuisd=len(ibans),
        boekvoorstellen_hervertaald=len(boekvoorstellen),
    )


# ----------------------------------------------------------------------------- auto-run (één run, alle administraties)


@dataclass(frozen=True)
class Voorbeeld:
    cluster_id: str
    voorkeur_naam: str | None
    verliezer_namen: list[str]
    reden: str
    afgehandeld: bool
    fout: str | None = None


@dataclass
class AdministratieUitkomst:
    administratie_id: uuid.UUID
    administratie_naam: str
    eenduidig: int = 0
    twijfel: int = 0
    afgehandeld: int = 0
    fouten: int = 0
    voorbeelden: list[Voorbeeld] = field(default_factory=list)


@dataclass
class RunUitkomst:
    run_id: uuid.UUID
    dry_run: bool
    administraties: list[AdministratieUitkomst]

    @property
    def eenduidig(self) -> int:
        return sum(a.eenduidig for a in self.administraties)

    @property
    def twijfel(self) -> int:
        return sum(a.twijfel for a in self.administraties)

    @property
    def afgehandeld(self) -> int:
        return sum(a.afgehandeld for a in self.administraties)

    @property
    def fouten(self) -> int:
        return sum(a.fouten for a in self.administraties)


def _systeem_actor() -> service.Actor:
    return service.Actor(id=SYSTEEM_ACTOR_ID, rol=GebruikerRol.BEHEERDER)


def _alle_actieve_administraties() -> list[tuple[uuid.UUID, str]]:
    with scoped_session(None) as session:
        return [
            (aid, naam)
            for aid, naam in session.execute(
                select(Administratie.id, Administratie.naam)
                .where(Administratie.actief.is_(True))
                .order_by(Administratie.naam)
            ).all()
        ]


def auto_afhandelen(
    actor: service.Actor | None,
    *,
    dry_run: bool,
    administratie_id: uuid.UUID | None = None,
    max_boekingen: int | None = None,
) -> RunUitkomst:
    """Eén run over alle administraties in scope (actor None = CLI/systeem: álle actieve administraties). Per
    administratie: clusters → classificatie → eenduidige clusters afhandelen (één transactie per cluster; een fout
    in het ene cluster stopt de andere niet en is zichtbaar). `dry_run` = alleen classificeren en tellen.
    Server-side, geen RLZ-calls, N clusters per administratie in de log."""
    run_id = uuid.uuid4()
    uitvoerder = actor or _systeem_actor()
    scope = _alle_actieve_administraties() if actor is None else service.administraties_in_scope(actor)
    if administratie_id is not None:
        scope = [(aid, naam) for aid, naam in scope if aid == administratie_id]
        if not scope:
            raise service.OnbekendeAdministratie(f"Onbekende administratie of buiten je scope: {administratie_id}")
    uit = RunUitkomst(run_id=run_id, dry_run=dry_run, administraties=[])
    for aid, naam in scope:
        stand = AdministratieUitkomst(administratie_id=aid, administratie_naam=naam)
        clusters = service._clusters_voor_administratie(uitvoerder, aid, naam)
        if not clusters:
            continue
        with scoped_session(aid, actor_id=uitvoerder.id) as session:
            menskeuze = menskeuze_vendors(session, administratie_id=aid)
        for c in service._sorteer(clusters):
            cl = classificeer(c, max_boekingen=max_boekingen, menskeuze=menskeuze)
            if not cl.eenduidig:
                stand.twijfel += 1
                continue
            stand.eenduidig += 1
            namen = {k.vendor_id: k.naam for k in c.crediteuren}
            voorbeeld = Voorbeeld(
                cluster_id=c.cluster_id,
                voorkeur_naam=namen.get(cl.voorkeur_vendor_id),
                verliezer_namen=[str(namen.get(v) or v) for v in cl.verliezer_vendor_ids],
                reden=cl.reden,
                afgehandeld=False,
            )
            if not dry_run:
                try:
                    with scoped_session(aid, actor_id=uitvoerder.id) as session:
                        handel_af(
                            session,
                            administratie_id=aid,
                            voorkeur=cl.voorkeur_vendor_id,
                            verliezers=cl.verliezer_vendor_ids,
                            sleutels=c.sleutels,
                            reden=cl.reden,
                            bron="auto",
                            actor_id=uitvoerder.id,
                            run_id=run_id,
                        )
                    stand.afgehandeld += 1
                    voorbeeld = Voorbeeld(**{**voorbeeld.__dict__, "afgehandeld": True})
                except Exception as exc:  # noqa: BLE001 — één cluster stopt de rest niet, fout blijft zichtbaar
                    logger.exception("Auto-afhandeling cluster %s mislukt", c.cluster_id)
                    stand.fouten += 1
                    voorbeeld = Voorbeeld(**{**voorbeeld.__dict__, "fout": f"{type(exc).__name__}: {exc}"})
            if len(stand.voorbeelden) < MAX_VOORBEELDEN:
                stand.voorbeelden.append(voorbeeld)
        logger.info(
            "Crediteuren-dubbelen auto-run %s %s: %s eenduidig, %s twijfel, %s afgehandeld, %s fouten%s",
            run_id,
            naam,
            stand.eenduidig,
            stand.twijfel,
            stand.afgehandeld,
            stand.fouten,
            " [dry-run]" if dry_run else "",
        )
        uit.administraties.append(stand)
    return uit


# ----------------------------------------------------------------------------- terugdraaien + log


@dataclass(frozen=True)
class AfhandelingRegel:
    id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    bron: str
    voorkeur_vendor_id: uuid.UUID
    voorkeur_naam: str | None
    verliezers: list[dict]
    sleutels: list[dict]
    classificatie_reden: str
    geheugen_verhuisd: int
    kenmerk_verhuisd: bool
    ibans_verhuisd: int
    boekvoorstellen_hervertaald: int
    afgehandeld_op: datetime
    teruggedraaid_op: datetime | None
    teruggedraaid_reden: str | None


def _regel(rij: CrediteurDubbelAfhandeling, naam: str) -> AfhandelingRegel:
    v = rij.verhuisd or {}
    return AfhandelingRegel(
        id=rij.id,
        administratie_id=rij.administratie_id,
        administratie_naam=naam,
        bron=rij.bron,
        voorkeur_vendor_id=rij.voorkeur_vendor_id,
        voorkeur_naam=rij.voorkeur_naam,
        verliezers=list(rij.verliezers or []),
        sleutels=list(rij.sleutels or []),
        classificatie_reden=rij.classificatie_reden,
        geheugen_verhuisd=len(v.get("geheugen") or []),
        kenmerk_verhuisd=v.get("kenmerk_oud") is not None,
        ibans_verhuisd=len(v.get("ibans") or []),
        boekvoorstellen_hervertaald=len(v.get("boekvoorstellen") or []),
        afgehandeld_op=rij.afgehandeld_op,
        teruggedraaid_op=rij.teruggedraaid_op,
        teruggedraaid_reden=rij.teruggedraaid_reden,
    )


def lijst_afhandelingen(actor: service.Actor, *, administratie_id: uuid.UUID | None = None) -> list[AfhandelingRegel]:
    """Kantoorbreed binnen scope, nieuwste eerst; teruggedraaide regels blijven zichtbaar (niets verdwijnt stil)."""
    uit: list[AfhandelingRegel] = []
    for aid, naam in service.administraties_in_scope(actor):
        if administratie_id is not None and aid != administratie_id:
            continue
        with scoped_session(aid, actor_id=actor.id) as session:
            for rij in session.scalars(
                select(CrediteurDubbelAfhandeling).where(CrediteurDubbelAfhandeling.administratie_id == aid)
            ):
                uit.append(_regel(rij, naam))
    return sorted(uit, key=lambda r: r.afgehandeld_op, reverse=True)


def draai_terug(actor: service.Actor, *, afhandeling_id: uuid.UUID, reden: str) -> AfhandelingRegel:
    """Herstelt de markering (verliezers weer bruikbaar, ketens terug), het kenmerk van de voorkeur (oude stand) en
    de hervertaalde boekvoorstellen (alleen als de mens ze intussen niet zelf wijzigde). Geheugen-/IBAN-kopieën zijn
    append-only en blijven staan — zichtbaar in de log + audit. Reden verplicht; al teruggedraaid = 422."""
    reden = reden.strip()
    if not reden:
        raise service.OngeldigeInvoer("Een reden is verplicht bij het terugdraaien")
    for aid, naam in service.administraties_in_scope(actor):
        with scoped_session(aid, actor_id=actor.id) as session:
            rij = session.get(CrediteurDubbelAfhandeling, afhandeling_id)
            if rij is None:
                continue
            if rij.teruggedraaid_op is not None:
                raise service.OngeldigeInvoer("Deze afhandeling is al teruggedraaid")
            verhuisd = rij.verhuisd or {}
            verliezer_ids = [uuid.UUID(str(v["vendor_id"])) for v in rij.verliezers or []]
            hersteld: list[str] = []
            for v in verliezer_ids:
                vc = session.get(VendorCache, (v, aid))
                if vc is None or vc.voorkeur_vendor_id != rij.voorkeur_vendor_id:
                    continue  # intussen anders afgehandeld — niet blind overschrijven
                vc.voorkeur_vendor_id = None
                vc.dubbel_afgehandeld_op = None
                vc.dubbel_afgehandeld_door = None
                vc.dubbel_afgehandeld_bron = None
                hersteld.append(str(v))
            for h in verhuisd.get("herwezen") or []:
                vc = session.get(VendorCache, (uuid.UUID(str(h["vendor_id"])), aid))
                if vc is not None and vc.voorkeur_vendor_id == rij.voorkeur_vendor_id:
                    vc.voorkeur_vendor_id = uuid.UUID(str(h["van_voorkeur_id"]))
            kenmerk_oud = verhuisd.get("kenmerk_oud")
            kenmerk_hersteld = False
            if kenmerk_oud is not None:
                doel = session.get(CrediteurKenmerk, (aid, rij.voorkeur_vendor_id))
                if doel is not None:
                    doel.btw_nummer = kenmerk_oud.get("btw_nummer")
                    doel.btw_nummer_geverifieerd = kenmerk_oud.get("btw_nummer_geverifieerd")
                    doel.btw_nummer_bron = kenmerk_oud.get("btw_nummer_bron")
                    doel.kvk_nummer = kenmerk_oud.get("kvk_nummer")
                    doel.kvk_nummer_bron = kenmerk_oud.get("kvk_nummer_bron")
                    doel.bijgewerkt_door = actor.id
                    doel.bijgewerkt_op = datetime.now(UTC)
                    kenmerk_hersteld = True
            boekvoorstellen_hersteld = 0
            for b in verhuisd.get("boekvoorstellen") or []:
                voorstel = session.get(Boekvoorstel, uuid.UUID(str(b["document_id"])))
                if voorstel is not None and voorstel.vendor_id == rij.voorkeur_vendor_id:
                    voorstel.vendor_id = uuid.UUID(str(b["van_vendor_id"]))
                    boekvoorstellen_hersteld += 1
            rij.teruggedraaid_op = datetime.now(UTC)
            rij.teruggedraaid_door = actor.id
            rij.teruggedraaid_reden = reden
            record_audit_event(
                session,
                actor_id=actor.id,
                module="boekhouding",
                tabel="crediteur_dubbel_afhandeling",
                record_id=rij.id,
                actie="crediteur_dubbel_teruggedraaid",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"voorkeur_vendor_id": str(rij.voorkeur_vendor_id), "verliezers": rij.verliezers},
                nieuwe_waarde={
                    "reden": reden,
                    "verliezers_hersteld": hersteld,
                    "kenmerk_hersteld": kenmerk_hersteld,
                    "boekvoorstellen_hersteld": boekvoorstellen_hersteld,
                    "geheugen_kopieen_blijven": len(verhuisd.get("geheugen") or []),
                    "iban_kopieen_blijven": len(verhuisd.get("ibans") or []),
                },
                administratie_id=aid,
            )
            session.flush()
            return _regel(rij, naam)
    raise service.OnbekendeAdministratie("Onbekende afhandeling of buiten je scope")


# ----------------------------------------------------------------------------- export "wie wil opruimen in RLZ"


def export_opruimlijst(actor: service.Actor) -> str:
    """CSV (puntkomma, UTF-8 mét BOM voor Excel) van álle verliezers in scope + de legacy RLZ-werklijst-regels van
    vóór 0117 die nog open staan. Optioneel opruimwerk in RLZ — geen teller, geen chip. `in_rlz` komt uit de
    Vendors-sync (`is_gearchiveerd`), geen RLZ-call."""
    buf = io.StringIO()
    buf.write("﻿")
    w = csv.writer(buf, delimiter=";", lineterminator="\r\n")
    w.writerow(["administratie", "voorkeur", "verliezer", "verliezer_vendor_id", "bron", "afgehandeld_op", "in_rlz"])
    for aid, naam in service.administraties_in_scope(actor):
        with scoped_session(aid, actor_id=actor.id) as session:
            rijen = session.scalars(
                select(VendorCache)
                .where(VendorCache.administratie_id == aid, VendorCache.voorkeur_vendor_id.is_not(None))
                .order_by(VendorCache.naam)
            ).all()
            namen = dict(
                session.execute(
                    select(VendorCache.id, VendorCache.naam).where(
                        VendorCache.administratie_id == aid,
                        VendorCache.id.in_([r.voorkeur_vendor_id for r in rijen] or [uuid.UUID(int=0)]),
                    )
                ).all()
            )
            for r in rijen:
                w.writerow(
                    [
                        naam,
                        namen.get(r.voorkeur_vendor_id) or str(r.voorkeur_vendor_id),
                        r.naam or "",
                        str(r.id),
                        r.dubbel_afgehandeld_bron or "",
                        r.dubbel_afgehandeld_op.isoformat(timespec="seconds") if r.dubbel_afgehandeld_op else "",
                        "gearchiveerd" if r.is_gearchiveerd else "actief",
                    ]
                )
            for regel in session.scalars(
                select(CrediteurArchiveerWerklijst).where(
                    CrediteurArchiveerWerklijst.administratie_id == aid, CrediteurArchiveerWerklijst.status == "open"
                )
            ):
                for t in regel.te_archiveren or []:
                    w.writerow(
                        [
                            naam,
                            regel.voorkeur_naam or str(regel.voorkeur_vendor_id),
                            t.get("naam") or "",
                            str(t.get("vendor_id") or ""),
                            "werklijst (vóór 07-09)",
                            regel.aangemaakt_op.isoformat(timespec="seconds"),
                            (regel.hertoets_detail or {}).get(str(t.get("vendor_id")), "onbekend"),
                        ]
                    )
    return buf.getvalue()
