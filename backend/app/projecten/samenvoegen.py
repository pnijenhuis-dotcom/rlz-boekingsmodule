"""Dubbel projectnummer samenvoegen — nazorg-CLI `project-dubbel-samenvoegen` (run A 02-10 punt 11, Peter 02-10: "per abuis
is 2x projectnummer 26149 gemaakt, moet gecheckt en voorkomen worden").

Diagnose 02-10 (leesreplica, Universal Steigerbouw 3ee6edf0): `0b394b0d…` "26149" (uuid4 — rechtstreeks in de RLZ-UI
gemaakt, Description "26149 Poeldijk, Anjerstraat 24 woningen (Weboma)", géén module-audit) náást `42b27746…` "26149
Poeldijk, Anjerstraat 245 (Weboma)" (uuid5 = projectenmodule, audit `project_aangemaakt_in_rlz` Haci 18-09 15:23 NL, 15 s
later de eerste planning-reservering). De 409-poort van 0160 zocht live in RLZ op `startswith(Name,'26149 ')` — mét spatie
— en zag een project dat alléén het nummer als naam draagt daardoor niet; de cache had het RLZ-UI-project nog niet
(dag-sync 07:00). Fix in `nummer.rlz_prefixen` (prefix zonder spatie; de exacte toets is al lokaal `cijfer_prefix`).

Samenvoegen (nooit automatisch — dry-run default, `--uitvoeren` ná Peters "ja" als job-executie op de gedeployde image):
1. Kandidaten = alle niet-verdwenen cache-projecten van de administratie mét exact dit nummer (`nummer.cijfer_prefix`).
2. BLIJVER = het OUDSTE project MÉT koppelingen (boekingen/weekstaten/planning/meerwerk/…); heeft geen enkel project
   koppelingen, dan het oudste; leeftijd = module-audit `project_aangemaakt_in_rlz`, anders RLZ `BeginDate`, anders
   onbekend (telt als jongst); gelijk → meeste koppelingen → via de module aangemaakt → langste naam → kleinste id.
3. Élke andere kandidaat is VERLIEZER: alle koppelingen gaan naar de blijver volgens `REGISTER` (één rij per tabel+kolom
   die naar een project wijst — guard `tests/projecten/test_samenvoegen.py` eist dat élke `project_id`/`project_ids`/
   `rlz_project_id`-kolom in `Base.metadata` hier staat), mét één audit-event per omgehangen rij
   (`project_dubbel_omgehangen`, oud→nieuw) en een tijdlijnregel op élk geraakt document. Een rij die bij de blijver al
   bestaat (zelfde unieke sleutel) BLIJFT STAAN en wordt gemeld — nooit verwijderd. Tabellen die een boeking in RLZ
   weerspiegelen (RLZ-factuurregel-cache, bankboekingen, doorbelasting) en append-only logs (mini-voorraad,
   projectaanvraag-register) worden alleen GERAPPORTEERD: herboeken in RLZ is mens-werk.
4. De verliezer gaat daarna op afgesloten via de BESTAANDE 0160-flow (`status.sluit_project_af`: RLZ `IsActive:false` /
   Odoo archived mét terugleesverificatie, bron wint) mét reden "dubbel projectnummer N — samengevoegd in ‹blijver›";
   `nummer.dubbele_nummers` telt zo'n verliezer niet meer, zodat de reconciliatie-soort `project_nummer_dubbel` sluit.
   Idempotent: een tweede run vindt niets om te hangen en een al-afgesloten verliezer ("al samengevoegd").
Geen migratie, geen DELETE, geen RLZ-write buiten `sluit_project_af`."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import Table, UniqueConstraint, func, select, update
from sqlalchemy.orm import Session
from sqlalchemy.orm.attributes import flag_modified

from app.db.audit import record_audit_event
from app.db.models import AuditEvent, Base
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.projecten import nummer as nummer_module
from app.sync.models import PROJECT_STATUS_AFGESLOTEN, ProjectCache

OMHANGEN = "omhangen"
RAPPORT = "rapport"
JSON_LIJST = "json_lijst"
EIGEN = "eigen"

AUDIT_OMGEHANGEN = "project_dubbel_omgehangen"
AUDIT_SAMENGEVOEGD = "project_dubbel_samengevoegd"
TIJDLIJN_SLEUTEL = "project_dubbel_samengevoegd"
SAMENVOEG_REDEN_PREFIX = nummer_module.SAMENVOEG_REDEN_PREFIX

#: Kolommen die naar een project wijzen — de guard loopt élke tabel in Base.metadata na op deze namen.
PROJECT_KOLOMMEN = ("project_id", "project_ids", "rlz_project_id")
_NS = uuid.UUID("5a1d6c2e-7b3f-4e0a-9c8d-2f1e0b4a6d7c")


@dataclass(frozen=True)
class Koppeling:
    tabel: str  # tabelnaam zonder schema (schema volgt uit Base.metadata)
    label: str
    wijze: str
    kolom: str = "project_id"
    reden: str = ""  # bij RAPPORT: waarom de rij blijft staan


REGISTER: tuple[Koppeling, ...] = (
    Koppeling("weekstaat", "weekstaten", OMHANGEN),
    Koppeling("meerwerk", "meerwerkmeldingen", OMHANGEN),
    Koppeling("planning_toewijzing", "planning (toewijzingen)", OMHANGEN),
    Koppeling("planning_reservering", "planning (reserveringen)", OMHANGEN),
    Koppeling("planning_signaal_afhandeling", "planning-signaalafhandelingen", OMHANGEN),
    Koppeling("planning_conflict_akkoord", "planning-conflictakkoorden", JSON_LIJST, kolom="project_ids"),
    Koppeling("werkopdracht", "werkopdrachten", OMHANGEN),
    Koppeling("uren_project_toewijzing", "uren-projecttoewijzingen", OMHANGEN),
    Koppeling("project_specificatie", "projectspecificatie", OMHANGEN),
    Koppeling("werkstempel", "werkstempels", OMHANGEN),
    Koppeling("project_document", "projectdocumenten", OMHANGEN),
    Koppeling("project_staffel", "verrekenstaffels", OMHANGEN),
    Koppeling("project_prijsafspraak", "prijsafspraken", OMHANGEN),
    Koppeling("project_ontleding_regel", "contract-ontledingsregels", OMHANGEN),
    Koppeling("leverancier_werknummer", "leverancier-werknummers", OMHANGEN),
    Koppeling("project_afsluit_uitstel", "niet-afsluiten-besluiten", OMHANGEN),
    Koppeling("verplichting", "verplichtingen/offertes", OMHANGEN),
    Koppeling("boeking_observatie", "boekingsgeheugen", OMHANGEN),
    Koppeling("bank_regel", "vaste bankregels", OMHANGEN),
    Koppeling("materiaal_bestelling", "materiaalbestellingen", OMHANGEN),
    Koppeling("materiaal_transport", "transporten", OMHANGEN),
    Koppeling("materiaalmatch", "materiaalmatches", OMHANGEN),
    Koppeling("pand", "panden", OMHANGEN, kolom="rlz_project_id"),
    Koppeling("boekvoorstel_regel", "boekingsregels (documenten)", EIGEN),
    Koppeling("projectverdeling", "projectverdelingen", EIGEN, kolom="verdeling"),
    Koppeling(
        "project_regel_cache",
        "RLZ-factuurregels (leescache)",
        RAPPORT,
        reden="de factuur staat in RLZ op het verliezende project — herboeken (storno 19 + opnieuw) is mens-werk",
    ),
    Koppeling(
        "bank_boeking_regel",
        "bankboekingen",
        RAPPORT,
        reden="geboekt in RLZ (BankMutationDirectBooking) op het verliezende project — storno 19 + opnieuw = mens-werk",
    ),
    Koppeling(
        "doorbelasting_regel",
        "doorbelastingsregels",
        RAPPORT,
        reden="onderdeel van een doorbelastingsrun (geboekt aan twee kanten) — herkoppelen is mens-werk",
    ),
    Koppeling(
        "mini_voorraad_mutatie",
        "mini-voorraadmutaties",
        RAPPORT,
        reden="append-only voorraadlog (kernbesluit Peter 05-09: mens-manipulatie onmogelijk) — nooit muteren",
    ),
    Koppeling(
        "projectaanvraag",
        "projectaanvragen route A",
        RAPPORT,
        kolom="rlz_project_id",
        reden="append-only register van vastgoed-aanvragen (idempotentiesleutel) — nooit muteren",
    ),
)


#: Dezelfde lijst als `migrations/env.py` — Base.metadata is pas compleet als élke model-module geladen is (de CLI
#: importeert anders alleen wat de aangeroepen code toevallig raakt).
_MODEL_MODULES = (
    "app.accordering.models", "app.activa.models", "app.afdelingen.models", "app.autoboek_kandidaten.models",
    "app.bank.models", "app.beheer.models", "app.berichten.models", "app.bewaking.models", "app.crediteuren.models",
    "app.documenten.models", "app.doorbelasting.models", "app.groepen.models", "app.intercompany.models",
    "app.extractie.models", "app.geheugen.models", "app.intake.models", "app.materiaal.models",
    "app.mini_voorraad.models", "app.odoo.models", "app.omzet.models", "app.panden.models", "app.projecten.models",
    "app.projectverdeling.models", "app.reconciliatie.models", "app.registersync.models", "app.sync.models",
    "app.terugkerend.models", "app.uren.models", "app.verkoop.models", "app.verplichting.models", "app.voorraad.models",
    "app.werkvoorraad.models", "app.waarborg.models",
)


def _laad_modellen() -> None:
    import importlib

    for module in _MODEL_MODULES:
        importlib.import_module(module)


def _tabel(naam: str) -> Table:
    _laad_modellen()
    for t in Base.metadata.tables.values():
        if t.name == naam:
            return t
    raise KeyError(naam)


def project_kolommen_in_metadata() -> set[tuple[str, str]]:
    """Alle (tabel, kolom)-paren in Base.metadata die naar een project wijzen — behalve `project_cache` zelf. Bron voor
    de FK-dekking-guard: élk paar hoort in `REGISTER`."""
    _laad_modellen()
    uit: set[tuple[str, str]] = set()
    for t in Base.metadata.tables.values():
        if t.name == "project_cache":
            continue
        for c in t.columns:
            if c.name in PROJECT_KOLOMMEN:
                uit.add((t.name, c.name))
    return uit


# --- kandidaten en blijver -------------------------------------------------------------------------------------------


@dataclass
class Kandidaat:
    project_id: uuid.UUID
    naam: str
    status: str
    is_actief: bool | None
    afsluit_reden: str | None
    aangemaakt_op: datetime | None  # module-audit, anders RLZ BeginDate, anders None
    module_aangemaakt: bool
    koppelingen: dict[str, int] = field(default_factory=dict)

    @property
    def koppelingen_totaal(self) -> int:
        return sum(self.koppelingen.values())

    @property
    def al_samengevoegd(self) -> bool:
        reden = self.afsluit_reden or ""
        return self.status == PROJECT_STATUS_AFGESLOTEN and reden.startswith(SAMENVOEG_REDEN_PREFIX)


def _begin_datum(brondata: dict | None) -> datetime | None:
    waarde = (brondata or {}).get("BeginDate")
    if not waarde:
        return None
    try:
        dt = datetime.fromisoformat(str(waarde))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def _tel_koppelingen(session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID) -> dict[str, int]:
    tellers: dict[str, int] = {}
    for k in REGISTER:
        if k.wijze == EIGEN and k.tabel == "projectverdeling":
            n = _projectverdeling_rijen(
                session, administratie_id=administratie_id, project_id=project_id, alleen_tellen=True
            )
        elif k.wijze == JSON_LIJST:
            n = len(
                _json_lijst_rijen(
                    session, _tabel(k.tabel), k.kolom, administratie_id=administratie_id, project_id=project_id
                )
            )
        else:
            t = _tabel(k.tabel)
            where = [t.c[k.kolom] == project_id]
            if "administratie_id" in t.c:
                where.append(t.c.administratie_id == administratie_id)
            n = int(session.scalar(select(func.count()).select_from(t).where(*where)) or 0)
        if n:
            tellers[k.label] = n
    return tellers


def kandidaten(session: Session, *, administratie_id: uuid.UUID, nummer: str) -> list[Kandidaat]:
    """Alle niet-verdwenen cache-projecten mét exact dit nummer, mét koppeling-tellers en leeftijd."""
    treffers = nummer_module.treffers_in_cache(session, administratie_id=administratie_id, nummer=nummer)
    uit: list[Kandidaat] = []
    for t in treffers:
        rij = session.get(ProjectCache, (t.project_id, administratie_id))
        if rij is None:
            continue
        audit = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.record_id == rij.id, AuditEvent.actie == "project_aangemaakt_in_rlz")
            .order_by(AuditEvent.tijdstip)
        ).first()
        uit.append(
            Kandidaat(
                project_id=rij.id,
                naam=rij.naam or "",
                status=rij.status,
                is_actief=rij.is_actief,
                afsluit_reden=rij.afsluit_reden,
                aangemaakt_op=audit.tijdstip if audit is not None else _begin_datum(rij.brondata),
                module_aangemaakt=audit is not None,
                koppelingen=_tel_koppelingen(session, administratie_id=administratie_id, project_id=rij.id),
            )
        )
    return sorted(uit, key=lambda k: (k.naam, str(k.project_id)))


def kies_blijver(kands: list[Kandidaat]) -> Kandidaat:
    """Het OUDSTE project MÉT koppelingen blijft; geen enkele koppeling → het oudste. Al-samengevoegde verliezers doen
    niet mee. Leeftijd onbekend = jongst. Gelijkspel: meeste koppelingen → module-aangemaakt → langste naam → kleinste
    id."""
    actief = [k for k in kands if not k.al_samengevoegd] or list(kands)
    ver = datetime.max.replace(tzinfo=UTC)

    def sleutel(k: Kandidaat):  # noqa: ANN202
        return (
            0 if k.koppelingen_totaal > 0 else 1,
            k.aangemaakt_op or ver,
            -k.koppelingen_totaal,
            0 if k.module_aangemaakt else 1,
            -len(k.naam),
            str(k.project_id),
        )

    return min(actief, key=sleutel)


# --- omhangen --------------------------------------------------------------------------------------------------------


@dataclass
class TabelUitkomst:
    label: str
    tabel: str
    wijze: str
    aantal: int = 0  # rijen die (zouden) omhangen
    blijft: int = 0  # rijen die blijven staan (conflict of RAPPORT)
    redenen: list[str] = field(default_factory=list)


def _unieke_sleutels(t: Table, kolom: str) -> list[list[str]]:
    sets: list[list[str]] = []
    pk = [c.name for c in t.primary_key.columns]
    if kolom in pk:
        sets.append(pk)
    for cons in t.constraints:
        if isinstance(cons, UniqueConstraint):
            namen = [c.name for c in cons.columns]
            if kolom in namen:
                sets.append(namen)
    for ix in t.indexes:
        if ix.unique:
            namen = [c.name for c in ix.columns]
            if kolom in namen:
                sets.append(namen)
    return sets


def _record_id(t: Table, rij: dict[str, Any]) -> uuid.UUID:
    pk = [c.name for c in t.primary_key.columns]
    if len(pk) == 1 and isinstance(rij.get(pk[0]), uuid.UUID):
        return rij[pk[0]]
    return uuid.uuid5(_NS, f"{t.name}:" + "|".join(f"{k}={rij.get(k)}" for k in pk))


def _audit_rij(
    session: Session,
    *,
    actor_id: uuid.UUID,
    administratie_id: uuid.UUID,
    tabel: str,
    record_id: uuid.UUID,
    correlatie_id: uuid.UUID,
    kolom: str,
    van: uuid.UUID,
    naar: uuid.UUID,
    nummer: str,
) -> None:
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel=tabel,
        record_id=record_id,
        actie=AUDIT_OMGEHANGEN,
        correlatie_id=correlatie_id,
        oude_waarde={kolom: str(van)},
        nieuwe_waarde={kolom: str(naar), "nummer": nummer, "reden": "dubbel projectnummer samengevoegd"},
        administratie_id=administratie_id,
    )


def _omhang_generiek(
    session: Session,
    k: Koppeling,
    *,
    administratie_id: uuid.UUID,
    van: uuid.UUID,
    naar: uuid.UUID,
    nummer: str,
    actor_id: uuid.UUID,
    correlatie_id: uuid.UUID,
    dry_run: bool,
) -> TabelUitkomst:
    t = _tabel(k.tabel)
    uit = TabelUitkomst(label=k.label, tabel=k.tabel, wijze=k.wijze)
    where = [t.c[k.kolom] == van]
    if "administratie_id" in t.c:
        where.append(t.c.administratie_id == administratie_id)
    rijen = [dict(r) for r in session.execute(select(t).where(*where)).mappings().all()]
    if not rijen:
        return uit
    if k.wijze == RAPPORT:
        uit.blijft = len(rijen)
        uit.redenen.append(f"{len(rijen)} rij(en) blijven staan — {k.reden}")
        return uit
    sleutels = _unieke_sleutels(t, k.kolom)
    pk = [c.name for c in t.primary_key.columns]
    for rij in rijen:
        conflict = False
        for namen in sleutels:
            cond = [t.c[n] == (naar if n == k.kolom else rij[n]) for n in namen]
            if session.scalar(select(func.count()).select_from(t).where(*cond)):
                conflict = True
                uit.blijft += 1
                uit.redenen.append(
                    f"rij {_record_id(t, rij)} blijft staan — bestaat al bij de blijver op sleutel ({', '.join(namen)})"
                )
                break
        if conflict:
            continue
        uit.aantal += 1
        if dry_run:
            continue
        session.execute(update(t).where(*[t.c[n] == rij[n] for n in pk]).values({k.kolom: naar}))
        _audit_rij(
            session,
            actor_id=actor_id,
            administratie_id=administratie_id,
            tabel=k.tabel,
            record_id=_record_id(t, rij),
            correlatie_id=correlatie_id,
            kolom=k.kolom,
            van=van,
            naar=naar,
            nummer=nummer,
        )
    return uit


def _json_lijst_rijen(
    session: Session, t: Table, kolom: str, *, administratie_id: uuid.UUID, project_id: uuid.UUID
) -> list[dict[str, Any]]:
    where = []
    if "administratie_id" in t.c:
        where.append(t.c.administratie_id == administratie_id)
    rijen = session.execute(select(t).where(*where)).mappings().all()
    return [dict(r) for r in rijen if str(project_id) in [str(x) for x in (r[kolom] or [])]]


def _omhang_json_lijst(
    session: Session,
    k: Koppeling,
    *,
    administratie_id: uuid.UUID,
    van: uuid.UUID,
    naar: uuid.UUID,
    nummer: str,
    actor_id: uuid.UUID,
    correlatie_id: uuid.UUID,
    dry_run: bool,
) -> TabelUitkomst:
    t = _tabel(k.tabel)
    uit = TabelUitkomst(label=k.label, tabel=k.tabel, wijze=k.wijze)
    pk = [c.name for c in t.primary_key.columns]
    for rij in _json_lijst_rijen(session, t, k.kolom, administratie_id=administratie_id, project_id=van):
        uit.aantal += 1
        if dry_run:
            continue
        nieuw = sorted({str(naar) if str(x) == str(van) else str(x) for x in (rij[k.kolom] or [])})
        session.execute(update(t).where(*[t.c[n] == rij[n] for n in pk]).values({k.kolom: nieuw}))
        _audit_rij(
            session,
            actor_id=actor_id,
            administratie_id=administratie_id,
            tabel=k.tabel,
            record_id=_record_id(t, rij),
            correlatie_id=correlatie_id,
            kolom=k.kolom,
            van=van,
            naar=naar,
            nummer=nummer,
        )
    return uit


def _omhang_boekvoorstel_regels(
    session: Session,
    k: Koppeling,
    *,
    administratie_id: uuid.UUID,
    van: uuid.UUID,
    naar: uuid.UUID,
    nummer: str,
    actor_id: uuid.UUID,
    correlatie_id: uuid.UUID,
    dry_run: bool,
) -> TabelUitkomst:
    """Boekingsregels van OPEN documenten hangen om (mét tijdlijnregel op het document); regels van geboekte/terminale
    documenten blijven staan — de boeking staat in RLZ/Odoo op het verliezende project."""
    from app.documenten.models import BoekvoorstelRegel, Document, DocumentGebeurtenis
    from app.verplichting.match_pipeline import ONDERWEG_UITGESLOTEN_STATUSSEN

    uit = TabelUitkomst(label=k.label, tabel=k.tabel, wijze=k.wijze)
    rijen = session.execute(
        select(BoekvoorstelRegel, Document)
        .join(Document, Document.id == BoekvoorstelRegel.document_id)
        .where(BoekvoorstelRegel.project_id == van, Document.administratie_id == administratie_id)
        .order_by(Document.id, BoekvoorstelRegel.volgnummer)
    ).all()
    per_document: dict[uuid.UUID, int] = {}
    for regel, document in rijen:
        if document.status in ONDERWEG_UITGESLOTEN_STATUSSEN:
            uit.blijft += 1
            uit.redenen.append(
                f"regel {regel.volgnummer} van document {document.id} ({document.status}) blijft staan — "
                "geboekt/afgehandeld op het verliezende project; corrigeren is mens-werk"
            )
            continue
        uit.aantal += 1
        if dry_run:
            continue
        regel.project_id = naar
        per_document[document.id] = per_document.get(document.id, 0) + 1
        _audit_rij(
            session,
            actor_id=actor_id,
            administratie_id=administratie_id,
            tabel=k.tabel,
            record_id=regel.id,
            correlatie_id=correlatie_id,
            kolom="project_id",
            van=van,
            naar=naar,
            nummer=nummer,
        )
    if not dry_run:
        for document_id, n in per_document.items():
            document = session.get(Document, document_id)
            session.add(
                DocumentGebeurtenis(
                    id=uuid.uuid4(),
                    document_id=document_id,
                    van_status=document.status,
                    naar_status=document.status,
                    actor_id=actor_id,
                    detail={
                        "sleutel": TIJDLIJN_SLEUTEL,
                        "reden": (
                            f"dubbel projectnummer {nummer} samengevoegd: {n} regel(s) van project {van} naar {naar}"
                        ),
                        "van_project_id": str(van),
                        "naar_project_id": str(naar),
                        "regels": n,
                    },
                )
            )
    return uit


def _projectverdeling_rijen(
    session: Session, *, administratie_id: uuid.UUID, project_id: uuid.UUID, alleen_tellen: bool = False
) -> Any:
    from app.projectverdeling.models import Projectverdeling

    rijen = session.scalars(select(Projectverdeling).where(Projectverdeling.administratie_id == administratie_id)).all()
    pid = str(project_id)

    def raakt(v: Projectverdeling) -> bool:
        lijsten = (v.vaste_regels, v.verdeling, v.omzetstanden)
        return any(str(d.get("project_id")) == pid for lijst in lijsten for d in (lijst or []))

    treffers = [v for v in rijen if raakt(v)]
    return len(treffers) if alleen_tellen else treffers


def _omhang_projectverdelingen(
    session: Session,
    k: Koppeling,
    *,
    administratie_id: uuid.UUID,
    van: uuid.UUID,
    naar: uuid.UUID,
    nummer: str,
    actor_id: uuid.UUID,
    correlatie_id: uuid.UUID,
    dry_run: bool,
) -> TabelUitkomst:
    """Verdelingen in stand `voorstel` krijgen het blijver-id in hun snapshot-JSON (de volgende lezing herrekent live);
    geboekte/vervallen verdelingen blijven staan (boekstand)."""
    uit = TabelUitkomst(label=k.label, tabel=k.tabel, wijze=k.wijze)
    for v in _projectverdeling_rijen(session, administratie_id=administratie_id, project_id=van):
        if v.status != "voorstel":
            uit.blijft += 1
            uit.redenen.append(f"verdeling van document {v.document_id} ({v.status}) blijft staan — bevroren boekstand")
            continue
        uit.aantal += 1
        if dry_run:
            continue
        for veld in ("vaste_regels", "verdeling", "omzetstanden"):
            lijst = getattr(v, veld) or []
            for d in lijst:
                if str(d.get("project_id")) == str(van):
                    d["project_id"] = str(naar)
            setattr(v, veld, lijst)
            flag_modified(v, veld)
        _audit_rij(
            session,
            actor_id=actor_id,
            administratie_id=administratie_id,
            tabel=k.tabel,
            record_id=v.id,
            correlatie_id=correlatie_id,
            kolom="verdeling.project_id",
            van=van,
            naar=naar,
            nummer=nummer,
        )
    return uit


_EIGEN = {"boekvoorstel_regel": _omhang_boekvoorstel_regels, "projectverdeling": _omhang_projectverdelingen}


# --- plan + uitvoering -----------------------------------------------------------------------------------------------


@dataclass
class VerliezerUitkomst:
    kandidaat: Kandidaat
    tabellen: list[TabelUitkomst] = field(default_factory=list)
    archief: str = ""  # "al samengevoegd" | "zou afsluiten" | "afgesloten (rlz/odoo)" | "bron weigert: …"

    @property
    def omgehangen(self) -> int:
        return sum(t.aantal for t in self.tabellen)

    @property
    def blijft(self) -> int:
        return sum(t.blijft for t in self.tabellen)


@dataclass
class Uitkomst:
    administratie_id: uuid.UUID
    administratie_naam: str
    nummer: str
    kandidaten: list[Kandidaat]
    blijver: Kandidaat | None
    verliezers: list[VerliezerUitkomst]
    dry_run: bool
    fout: str | None = None

    @property
    def omgehangen(self) -> int:
        return sum(v.omgehangen for v in self.verliezers)

    @property
    def blijft(self) -> int:
        return sum(v.blijft for v in self.verliezers)

    @property
    def tabellen_geraakt(self) -> int:
        return len({t.tabel for v in self.verliezers for t in v.tabellen if t.aantal})


def samenvoegen(
    *,
    administratie_id: uuid.UUID,
    administratie_naam: str,
    nummer: str,
    actor_id: uuid.UUID = SYSTEEM_ACTOR_ID,
    dry_run: bool = True,
    client: Any | None = None,
) -> Uitkomst:
    """Dry-run (default) toont exact wat zou gebeuren; `dry_run=False` hangt om (één transactie per verliezer) en
    sluit daarna de verliezer af via de 0160-flow. De systeem-actor (job-executie ná Peters "ja") passeert de rolpoort
    van `_vereis_schrijfrol` bewust: de job-executie zélf is de poort (regel 08-09)."""
    from app.db.session import scoped_session
    from app.projecten import status as status_module

    nummer = nummer.strip()
    with scoped_session(administratie_id) as session:
        kands = kandidaten(session, administratie_id=administratie_id, nummer=nummer)
    if len(kands) < 2:
        return Uitkomst(
            administratie_id, administratie_naam, nummer, kands, kands[0] if kands else None, [], dry_run,
            fout=f"nummer {nummer}: {len(kands)} project(en) in de cache — niets samen te voegen",
        )
    blijver = kies_blijver(kands)
    uit = Uitkomst(administratie_id, administratie_naam, nummer, kands, blijver, [], dry_run)
    for kand in kands:
        if kand.project_id == blijver.project_id:
            continue
        verliezer = VerliezerUitkomst(kandidaat=kand)
        correlatie_id = uuid.uuid4()
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            for k in REGISTER:
                if k.wijze == EIGEN:
                    fn = _EIGEN[k.tabel]
                elif k.wijze == JSON_LIJST:
                    fn = _omhang_json_lijst
                else:
                    fn = _omhang_generiek
                t_uit = fn(
                    session,
                    k,
                    administratie_id=administratie_id,
                    van=kand.project_id,
                    naar=blijver.project_id,
                    nummer=nummer,
                    actor_id=actor_id,
                    correlatie_id=correlatie_id,
                    dry_run=dry_run,
                )
                if t_uit.aantal or t_uit.blijft:
                    verliezer.tabellen.append(t_uit)
            if not dry_run:
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="project_cache",
                    record_id=kand.project_id,
                    actie=AUDIT_SAMENGEVOEGD,
                    correlatie_id=correlatie_id,
                    oude_waarde={"naam": kand.naam, "status": kand.status},
                    nieuwe_waarde={
                        "nummer": nummer,
                        "blijver_project_id": str(blijver.project_id),
                        "blijver_naam": blijver.naam,
                        "omgehangen": {t.label: t.aantal for t in verliezer.tabellen if t.aantal},
                        "blijft_staan": {t.label: t.blijft for t in verliezer.tabellen if t.blijft},
                    },
                    administratie_id=administratie_id,
                )
        # archiveren via de bestaande 0160-flow (bron eerst, terugleesverificatie)
        if kand.al_samengevoegd:
            verliezer.archief = "al samengevoegd (afgesloten mét samenvoeg-reden)"
        elif kand.status == PROJECT_STATUS_AFGESLOTEN:
            verliezer.archief = "al afgesloten (eigen reden blijft staan)"
        elif dry_run:
            verliezer.archief = "zou afsluiten via de 0160-flow (RLZ IsActive false / Odoo archived, teruglezen)"
        else:
            reden = (
                f"{SAMENVOEG_REDEN_PREFIX} {nummer} — samengevoegd in {blijver.project_id} ({blijver.naam}); "
                "project-dubbel-samenvoegen"
            )
            try:
                status_module.sluit_project_af(
                    administratie_id=administratie_id,
                    project_id=kand.project_id,
                    actor_id=actor_id,
                    reden=reden,
                    client=client,
                    rolpoort=actor_id != SYSTEEM_ACTOR_ID,
                )
                verliezer.archief = "afgesloten via de 0160-flow (bron inactief, teruggelezen)"
            except status_module.ProjectStatusFout as exc:
                verliezer.archief = (
                    f"NIET afgesloten — bron weigert: {exc} (koppelingen zijn wél omgehangen; run opnieuw)"
                )
                uit.fout = verliezer.archief
        uit.verliezers.append(verliezer)
    return uit


def rapportregels(uit: Uitkomst) -> list[str]:
    modus = "dry-run (niets geschreven)" if uit.dry_run else "UITGEVOERD"
    regels = [f"{uit.administratie_naam} ({uit.administratie_id}) — nummer {uit.nummer} — {modus}"]
    if uit.fout and not uit.verliezers:
        regels.append(f"  {uit.fout}")
        regels.append(f"TOTAAL: nummer {uit.nummer} — niets samen te voegen · modus {modus}")
        return regels
    for k in uit.kandidaten:
        rol = "BLIJFT" if uit.blijver and k.project_id == uit.blijver.project_id else "verliezer"
        leeftijd = k.aangemaakt_op.isoformat() if k.aangemaakt_op else "onbekend"
        bron = "module" if k.module_aangemaakt else "buiten de module (RLZ/Odoo/sync)"
        kop = ", ".join(f"{lbl} {n}" for lbl, n in sorted(k.koppelingen.items())) or "geen koppelingen"
        regels.append(
            f"  {rol:9} {k.project_id}  {k.naam!r}  status={k.status} actief={k.is_actief}  "
            f"aangemaakt={leeftijd} ({bron})  {kop}"
        )
    for v in uit.verliezers:
        blijver_id = uit.blijver.project_id if uit.blijver else "?"
        regels.append(f"  verliezer {v.kandidaat.project_id} → blijver {blijver_id}:")
        if not v.tabellen:
            regels.append("    geen koppelingen om te hangen")
        for t in v.tabellen:
            werkwoord = "omgehangen" if not uit.dry_run else "zou omhangen"
            regels.append(f"    {t.label} ({t.tabel}): {t.aantal} rij(en) {werkwoord}, {t.blijft} blijven staan")
            for r in t.redenen:
                regels.append(f"      · {r}")
        regels.append(f"    archief: {v.archief}")
    blijver_id = uit.blijver.project_id if uit.blijver else "?"
    blijver_naam = uit.blijver.naam if uit.blijver else ""
    regels.append(
        f"TOTAAL: nummer {uit.nummer} — blijft {blijver_id} {blijver_naam!r} · {len(uit.verliezers)} verliezer(s) · "
        f"{uit.omgehangen} rij(en) omgehangen in {uit.tabellen_geraakt} tabel(len) · {uit.blijft} rij(en) blijven staan "
        f"(mens) · modus {modus}"
    )
    return regels
