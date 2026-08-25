"""ZZP-dossier per veldwerker + handhaving + KvK (steigerbouw-run blok A1–A3, besluiten Peter
23/24-08 — mockup meerwerk-kantoor.html "Dossier" is de norm; migratie 0072).

Statusmodel per documenttype (afgeleid uit de jongste upload van dat type):
    ontbreekt ──(upload kantoor/app)──> ter_controle ──(kantoor)──> goedgekeurd
                                             │                          │ (geldig_tot < vandaag)
                                             └──(kantoor, reden)──> afgewezen        verlopen
`verloopt_binnenkort` = goedgekeurd met geldig_tot binnen VOORAANKONDIGING_DAGEN (30).

Handhaving (A2): kantoor herinnert per knop (push, anders mail — gedeeld kanaal
app/berichten/verzending.py; max 1/dag; teller "N van 3"); ná de 3e herinnering blokkeert het
INDIENEN van weekstaten voor die veldwerker — óók namens-invoer door de detacheerder. Deblokkade
zodra alle verplichte documenten geüpload zijn (ter controle telt); een afwijzing heractiveert
de blokkade (dossier is dan weer incompleet terwijl de teller ≥ 3 staat). De teller reset pas
als het dossier volledig GOEDGEKEURD én geldig is — dan is de episode dicht. Uren over een
geblokkeerde periode blijven bewaard (dagen zetten mag altijd) en kunnen ná deblokkade alsnog
ingediend worden — er raken nooit uren zoek.

Blokkade wordt HERLEID bij élke mutatie én op het indien-moment (`toets_indienen`), zodat een
intussen verlopen document zichtbaar bijt en de overgang geauditeerd is (actor + oud→nieuw).

BSN-regel (kopie ID, `bsn_gevoelig`): nooit extraheren/indexeren — dossierbestanden gaan nooit
door extractie of zoeken; inzage uitsluitend via de geauthenticeerde leesroute, élke inzage van
een bsn-gevoelig document geauditeerd, weergave in de UI standaard gemaskeerd.

Alle mutaties append-only geauditeerd (audit-eis 24-08): upload, beoordeling, herinnering,
blokkade-overgangen, teller-reset, documenttypen-instelling, KvK-bevestiging, inzage."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.berichten import verzending
from app.berichten.models import HerinneringStatus
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import (
    Administratie,
    DetacheerderKoppeling,
    Gebruiker,
    GebruikerAdministratie,
    GebruikerRol,
    GebruikerStatus,
)
from app.db.session import scoped_session
from app.uren.models import (
    DossierDocument,
    DossierDocumentStatus,
    DossierDocumenttype,
    DossierHerinnering,
    VeldwerkerDossier,
)
from app.uren.service import (
    MODULE,
    GeenToegang,
    NietGevonden,
    OngeldigeInvoer,
    RedenVerplicht,
    UrenFout,
    _administratie_met_opt_in,
    _gebruiker,
    heeft_meerwerk_urenstaten_recht,
)

TIJDZONE = ZoneInfo("Europe/Amsterdam")
VOORAANKONDIGING_DAGEN = 30
MAX_HERINNERINGEN = 3
DOSSIER_ROLLEN = frozenset({GebruikerRol.ZZPER, GebruikerRol.UITVOERDER})
TOEGESTANE_CONTENT_TYPES = frozenset({"application/pdf", "image/jpeg", "image/png"})
MAX_BESTAND_BYTES = 15 * 1024 * 1024


class DossierGeblokkeerd(UrenFout):
    """Weekstaat indienen geweigerd: dossier-handhaving actief (ná de 3e herinnering, dossier
    incompleet). Router → 423 Locked, de app toont melding + upload-ingang."""


class AlHerinnerdVandaag(UrenFout):
    """Dagrem: vandaag is er al een dossier-herinnering aan deze veldwerker verstuurd."""


class DossierCompleet(UrenFout):
    """Herinneren heeft geen zin: alle verplichte documenten zijn aanwezig."""


class HerinneringMislukt(UrenFout):
    """Verzenden aantoonbaar mislukt — zichtbaar, opnieuw proberen mag (vandaag nog)."""


# --- documenttypen (Beheerder-instelling, default-set virtueel) ----------------------------------


@dataclass(frozen=True)
class TypeDef:
    code: str
    naam: str
    verplicht: bool
    geldig_tot_vereist: bool
    bsn_gevoelig: bool
    volgorde: int
    actief: bool = True


STANDAARD_TYPEN: tuple[TypeDef, ...] = (
    TypeDef("kopie_id", "Kopie ID", True, True, True, 1),
    TypeDef("steigerpas", "Steigerpas", True, True, False, 2),
    TypeDef("vca_vol", "VCA (vol)", True, True, False, 3),
    TypeDef("avb", "Aansprakelijkheidsverzekering (AVB)", True, True, False, 4),
    TypeDef("kvk_uittreksel", "KvK-uittreksel", True, True, False, 5),
)


def _typen_in_sessie(session, administratie_id: uuid.UUID, *, alleen_actief: bool = True) -> list[TypeDef]:
    rijen = session.scalars(
        select(DossierDocumenttype)
        .where(DossierDocumenttype.administratie_id == administratie_id)
        .order_by(DossierDocumenttype.volgorde, DossierDocumenttype.code)
    ).all()
    if not rijen:
        return [t for t in STANDAARD_TYPEN if t.actief or not alleen_actief]
    typen = [
        TypeDef(r.code, r.naam, r.verplicht, r.geldig_tot_vereist, r.bsn_gevoelig, r.volgorde, r.actief) for r in rijen
    ]
    return [t for t in typen if t.actief or not alleen_actief]


def documenttypen(*, administratie_id: uuid.UUID, actor_id: uuid.UUID) -> tuple[list[TypeDef], bool]:
    """(typen incl. inactieve, is_standaard) — Beheerder-only via de router."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        bestaand = session.scalars(
            select(DossierDocumenttype.id).where(DossierDocumenttype.administratie_id == administratie_id)
        ).first()
        return _typen_in_sessie(session, administratie_id, alleen_actief=False), bestaand is None


def zet_documenttypen(*, administratie_id: uuid.UUID, typen: list[TypeDef], actor_id: uuid.UUID) -> list[TypeDef]:
    """Persisteert de VOLLEDIGE set (upsert op code; codes die ontbreken worden inactief — nooit
    verwijderd, bestaande uploads van dat type blijven zichtbaar). Elke wijziging geauditeerd."""
    codes = [t.code for t in typen]
    if len(set(codes)) != len(codes):
        raise OngeldigeInvoer("Dubbele documenttype-code")
    for t in typen:
        if not t.naam.strip():
            raise OngeldigeInvoer(f"Documenttype {t.code!r} heeft geen naam")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        bestaand = {
            r.code: r
            for r in session.scalars(
                select(DossierDocumenttype).where(DossierDocumenttype.administratie_id == administratie_id)
            )
        }
        wijzigingen: list[dict] = []
        if not bestaand:
            # Eerste PUT: de (tot nu virtuele) default-set eerst materialiseren, zodat een
            # weggelaten standaardtype als INACTIEVE rij achterblijft — nooit stil verdwenen.
            for t in STANDAARD_TYPEN:
                rij = DossierDocumenttype(
                    administratie_id=administratie_id,
                    code=t.code,
                    naam=t.naam,
                    verplicht=t.verplicht,
                    geldig_tot_vereist=t.geldig_tot_vereist,
                    bsn_gevoelig=t.bsn_gevoelig,
                    volgorde=t.volgorde,
                    actief=t.actief,
                    bijgewerkt_door=actor_id,
                )
                session.add(rij)
                bestaand[t.code] = rij
            session.flush()
            wijzigingen.append({"code": "*", "oud": None, "nieuw": "standaardset gematerialiseerd"})
        for t in typen:
            rij = bestaand.get(t.code)
            nieuw = {
                "naam": t.naam.strip(),
                "verplicht": t.verplicht,
                "geldig_tot_vereist": t.geldig_tot_vereist,
                "bsn_gevoelig": t.bsn_gevoelig,
                "volgorde": t.volgorde,
                "actief": t.actief,
            }
            if rij is None:
                session.add(
                    DossierDocumenttype(
                        administratie_id=administratie_id, code=t.code, bijgewerkt_door=actor_id, **nieuw
                    )
                )
                wijzigingen.append({"code": t.code, "oud": None, "nieuw": nieuw})
                continue
            oud = {k: getattr(rij, k) for k in nieuw}
            if oud != nieuw:
                for k, v in nieuw.items():
                    setattr(rij, k, v)
                rij.bijgewerkt_door = actor_id
                wijzigingen.append({"code": t.code, "oud": oud, "nieuw": nieuw})
        for code, rij in bestaand.items():
            if code not in codes and rij.actief:
                rij.actief = False
                rij.bijgewerkt_door = actor_id
                wijzigingen.append({"code": code, "oud": {"actief": True}, "nieuw": {"actief": False}})
        if wijzigingen:
            record_audit_event(
                session,
                actor_id=actor_id,
                module=MODULE,
                tabel="dossier_documenttype",
                record_id=administratie_id,
                actie="dossier_documenttypen_gewijzigd",
                correlatie_id=administratie_id,
                nieuwe_waarde={"wijzigingen": wijzigingen},
                administratie_id=administratie_id,
            )
        session.flush()
        return _typen_in_sessie(session, administratie_id, alleen_actief=False)


# --- stand -----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class DocumentStand:
    code: str
    naam: str
    verplicht: bool
    geldig_tot_vereist: bool
    bsn_gevoelig: bool
    status: str  # ontbreekt | ter_controle | afgewezen | goedgekeurd | verloopt_binnenkort | verlopen
    document_id: uuid.UUID | None
    geldig_tot: date | None
    verloopt_over_dagen: int | None
    bestandsnaam: str | None
    content_type: str | None
    geupload_op: datetime | None
    geupload_door_naam: str | None
    bron: str | None
    afwijs_reden: str | None
    beoordeeld_door_naam: str | None
    beoordeeld_op: datetime | None


@dataclass(frozen=True)
class DossierStand:
    administratie_id: uuid.UUID
    gebruiker_id: uuid.UUID
    gebruiker_naam: str
    documenten: list[DocumentStand]
    aantal_verplicht: int
    aantal_aanwezig: int  # verplicht én goedgekeurd/verloopt_binnenkort
    aantal_ontbrekend: int  # verplicht: ontbreekt of afgewezen
    aantal_verlopen: int
    aantal_verloopt_binnenkort: int
    aantal_ter_controle: int
    compleet: bool  # alle verplichte goedgekeurd en geldig → teller-reset
    compleet_incl_ter_controle: bool  # deblokkade-criterium
    herinneringen_teller: int
    laatste_herinnering_op: datetime | None
    geblokkeerd: bool
    geblokkeerd_op: datetime | None
    kan_herinneren_vandaag: bool
    kvk_nummer: str | None
    btw_nummer: str | None
    kvk_naam: str | None
    kvk_plaats: str | None
    kvk_rechtsvorm: str | None
    kvk_bevestigd_op: datetime | None
    kvk_bevestigd_door_naam: str | None
    signalen: list[str] = field(default_factory=list)


def _vandaag() -> date:
    return datetime.now(TIJDZONE).date()


def _dossier_rij(session, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID) -> VeldwerkerDossier:
    rij = session.get(VeldwerkerDossier, (administratie_id, gebruiker_id))
    if rij is None:
        rij = VeldwerkerDossier(administratie_id=administratie_id, gebruiker_id=gebruiker_id)
        session.add(rij)
        session.flush()
    return rij


def _status_van(doc: DossierDocument | None, vandaag: date) -> tuple[str, int | None]:
    if doc is None:
        return "ontbreekt", None
    if doc.status == DossierDocumentStatus.TER_CONTROLE.value:
        return "ter_controle", None
    if doc.status == DossierDocumentStatus.AFGEWEZEN.value:
        return "afgewezen", None
    if doc.geldig_tot is None:
        return "goedgekeurd", None
    dagen = (doc.geldig_tot - vandaag).days
    if dagen < 0:
        return "verlopen", dagen
    if dagen <= VOORAANKONDIGING_DAGEN:
        return "verloopt_binnenkort", dagen
    return "goedgekeurd", dagen


AANWEZIG = frozenset({"goedgekeurd", "verloopt_binnenkort"})
GEUPLOAD = AANWEZIG | {"ter_controle"}


def _stand_in_sessie(
    session, *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, vandaag: date | None = None
) -> DossierStand:
    vandaag = vandaag or _vandaag()
    gebruiker = _gebruiker(session, gebruiker_id)
    typen = _typen_in_sessie(session, administratie_id)
    # Lezen schrijft niets: zonder rij gelden de defaults (teller 0, niet geblokkeerd, geen KvK).
    rij = session.get(VeldwerkerDossier, (administratie_id, gebruiker_id)) or VeldwerkerDossier(
        administratie_id=administratie_id, gebruiker_id=gebruiker_id, herinneringen_teller=0, geblokkeerd=False
    )
    docs = session.scalars(
        select(DossierDocument)
        .where(DossierDocument.administratie_id == administratie_id, DossierDocument.gebruiker_id == gebruiker_id)
        .order_by(DossierDocument.geupload_op.desc(), DossierDocument.id.desc())
    ).all()
    jongste: dict[str, DossierDocument] = {}
    for d in docs:
        jongste.setdefault(d.type_code, d)
    naam_ids = {d.geupload_door for d in jongste.values()} | {d.beoordeeld_door for d in jongste.values()}
    naam_ids.add(rij.kvk_bevestigd_door)
    namen = (
        {
            g.id: g.naam
            for g in session.scalars(select(Gebruiker).where(Gebruiker.id.in_([i for i in naam_ids if i is not None])))
        }
        if any(naam_ids)
        else {}
    )

    documenten: list[DocumentStand] = []
    for t in typen:
        d = jongste.get(t.code)
        status, dagen = _status_van(d, vandaag)
        documenten.append(
            DocumentStand(
                code=t.code,
                naam=t.naam,
                verplicht=t.verplicht,
                geldig_tot_vereist=t.geldig_tot_vereist,
                bsn_gevoelig=t.bsn_gevoelig,
                status=status,
                document_id=d.id if d else None,
                geldig_tot=d.geldig_tot if d else None,
                verloopt_over_dagen=dagen,
                bestandsnaam=d.bestandsnaam if d else None,
                content_type=d.content_type if d else None,
                geupload_op=d.geupload_op if d else None,
                geupload_door_naam=namen.get(d.geupload_door) if d else None,
                bron=d.bron if d else None,
                afwijs_reden=d.afwijs_reden if d else None,
                beoordeeld_door_naam=namen.get(d.beoordeeld_door) if d and d.beoordeeld_door else None,
                beoordeeld_op=d.beoordeeld_op if d else None,
            )
        )
    verplicht = [x for x in documenten if x.verplicht]
    compleet = all(x.status in AANWEZIG for x in verplicht)
    compleet_incl = all(x.status in GEUPLOAD for x in verplicht)
    signalen: list[str] = []
    ontbrekend = [x for x in verplicht if x.status in ("ontbreekt", "afgewezen")]
    verlopen = [x for x in documenten if x.status == "verlopen"]
    binnenkort = [x for x in documenten if x.status == "verloopt_binnenkort"]
    if ontbrekend:
        signalen.append("ontbrekend: " + ", ".join(x.naam for x in ontbrekend))
    if verlopen:
        signalen.append("verlopen: " + ", ".join(x.naam for x in verlopen))
    if binnenkort:
        signalen.append(
            "verloopt binnenkort: " + ", ".join(f"{x.naam} ({x.verloopt_over_dagen} d)" for x in binnenkort)
        )
    al_vandaag = session.scalars(
        select(DossierHerinnering.status).where(
            DossierHerinnering.administratie_id == administratie_id,
            DossierHerinnering.gebruiker_id == gebruiker_id,
            DossierHerinnering.datum == vandaag,
        )
    ).first()
    return DossierStand(
        administratie_id=administratie_id,
        gebruiker_id=gebruiker_id,
        gebruiker_naam=gebruiker.naam,
        documenten=documenten,
        aantal_verplicht=len(verplicht),
        aantal_aanwezig=sum(1 for x in verplicht if x.status in AANWEZIG),
        aantal_ontbrekend=len(ontbrekend),
        aantal_verlopen=len(verlopen),
        aantal_verloopt_binnenkort=len(binnenkort),
        aantal_ter_controle=sum(1 for x in documenten if x.status == "ter_controle"),
        compleet=compleet,
        compleet_incl_ter_controle=compleet_incl,
        herinneringen_teller=rij.herinneringen_teller,
        laatste_herinnering_op=rij.laatste_herinnering_op,
        geblokkeerd=rij.geblokkeerd,
        geblokkeerd_op=rij.geblokkeerd_op,
        kan_herinneren_vandaag=(not compleet_incl) and al_vandaag not in ("verzonden", "bezig"),
        kvk_nummer=rij.kvk_nummer,
        btw_nummer=rij.btw_nummer,
        kvk_naam=rij.kvk_naam,
        kvk_plaats=rij.kvk_plaats,
        kvk_rechtsvorm=rij.kvk_rechtsvorm,
        kvk_bevestigd_op=rij.kvk_bevestigd_op,
        kvk_bevestigd_door_naam=namen.get(rij.kvk_bevestigd_door) if rij.kvk_bevestigd_door else None,
        signalen=signalen,
    )


def _herleid_blokkade(
    session, *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, actor_id: uuid.UUID
) -> DossierStand:
    """Herleid teller-reset + blokkade uit de actuele stand en auditeer élke overgang."""
    stand = _stand_in_sessie(session, administratie_id=administratie_id, gebruiker_id=gebruiker_id)
    rij = _dossier_rij(session, administratie_id, gebruiker_id)
    nu = datetime.now(UTC)
    if stand.compleet and rij.herinneringen_teller > 0:
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="veldwerker_dossier",
            record_id=gebruiker_id,
            actie="dossier_compleet_teller_reset",
            correlatie_id=gebruiker_id,
            oude_waarde={"herinneringen_teller": rij.herinneringen_teller},
            nieuwe_waarde={"herinneringen_teller": 0},
            administratie_id=administratie_id,
        )
        rij.herinneringen_teller = 0
    nieuw_geblokkeerd = rij.herinneringen_teller >= MAX_HERINNERINGEN and not stand.compleet_incl_ter_controle
    if nieuw_geblokkeerd != rij.geblokkeerd:
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="veldwerker_dossier",
            record_id=gebruiker_id,
            actie="dossier_geblokkeerd" if nieuw_geblokkeerd else "dossier_gedeblokkeerd",
            correlatie_id=gebruiker_id,
            oude_waarde={"geblokkeerd": rij.geblokkeerd},
            nieuwe_waarde={
                "geblokkeerd": nieuw_geblokkeerd,
                "herinneringen_teller": rij.herinneringen_teller,
                "signalen": stand.signalen,
            },
            administratie_id=administratie_id,
        )
        rij.geblokkeerd = nieuw_geblokkeerd
        if nieuw_geblokkeerd:
            rij.geblokkeerd_op = nu
        else:
            rij.gedeblokkeerd_op = nu
    session.flush()
    return _stand_in_sessie(session, administratie_id=administratie_id, gebruiker_id=gebruiker_id)


# --- toegang ------------------------------------------------------------------------------------------


def _vereis_dossier_rol(gebruiker: Gebruiker) -> None:
    if gebruiker.rol not in DOSSIER_ROLLEN:
        raise OngeldigeInvoer("Een dossier hoort bij een ZZP'er of uitvoerder")


def _vereis_toegang(session, *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, actor_id: uuid.UUID) -> Gebruiker:
    """De veldwerker zelf, een gekoppelde detacheerder (namens), of kantoor mét module-recht."""
    veldwerker = _gebruiker(session, gebruiker_id)
    _vereis_dossier_rol(veldwerker)
    if actor_id == gebruiker_id:
        return veldwerker
    actor = _gebruiker(session, actor_id)
    if actor.rol == GebruikerRol.DETACHEERDER:
        if session.get(DetacheerderKoppeling, (actor_id, gebruiker_id)) is None:
            raise GeenToegang("Deze detacheerder is niet aan deze veldwerker gekoppeld")
        return veldwerker
    if heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol):
        return veldwerker
    raise GeenToegang("Geen toegang tot dit dossier")


def _vereis_kantoor(session, actor_id: uuid.UUID) -> Gebruiker:
    actor = _gebruiker(session, actor_id)
    if not heeft_meerwerk_urenstaten_recht(gebruiker_id=actor_id, rol=actor.rol):
        raise GeenToegang("Vereist het module-recht 'Meerwerk & urenstaten'")
    return actor


def dossier_van(*, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, actor_id: uuid.UUID) -> DossierStand:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_toegang(session, administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=actor_id)
        return _stand_in_sessie(session, administratie_id=administratie_id, gebruiker_id=gebruiker_id)


# --- upload + beoordeling ---------------------------------------------------------------------------------


def upload_document(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    type_code: str,
    geldig_tot: date | None,
    bestand: tuple[str, str, bytes],
    actor_id: uuid.UUID,
) -> DossierStand:
    """Nieuwe upload → status ter_controle (ook bij een kantoor-upload: één uniforme keten, het
    kantoor keurt daarna expliciet goed). `bron` volgt uit de actor-rol."""
    bestandsnaam, content_type, inhoud = bestand
    if not inhoud:
        raise OngeldigeInvoer("Leeg bestand")
    if len(inhoud) > MAX_BESTAND_BYTES:
        raise OngeldigeInvoer("Bestand groter dan 15 MB")
    if content_type not in TOEGESTANE_CONTENT_TYPES:
        raise OngeldigeInvoer("Alleen PDF, JPEG of PNG")
    bestandsnaam = (bestandsnaam or "document").replace("/", "_")[:200]
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_toegang(session, administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=actor_id)
        actor = _gebruiker(session, actor_id)
        typen = {t.code: t for t in _typen_in_sessie(session, administratie_id)}
        t = typen.get(type_code)
        if t is None:
            raise NietGevonden(f"Onbekend documenttype {type_code!r} voor deze administratie")
        if t.geldig_tot_vereist and geldig_tot is None:
            raise OngeldigeInvoer(f"{t.naam}: geldig-tot-datum is verplicht")
        if geldig_tot is not None and geldig_tot < _vandaag():
            raise OngeldigeInvoer(f"{t.naam}: de geldig-tot-datum ligt in het verleden")
        from app.auth.rollen import is_kantoorrol
        from app.documenten.storage import standaard_opslag

        doc = DossierDocument(
            administratie_id=administratie_id,
            gebruiker_id=gebruiker_id,
            type_code=type_code,
            status=DossierDocumentStatus.TER_CONTROLE.value,
            geldig_tot=geldig_tot,
            opslag_pad="",
            bestandsnaam=bestandsnaam,
            content_type=content_type,
            bron="kantoor" if is_kantoorrol(actor.rol) else "app",
            geupload_door=actor_id,
        )
        session.add(doc)
        session.flush()
        pad = f"dossier/{administratie_id}/{gebruiker_id}/{doc.id}/{bestandsnaam}"
        standaard_opslag().opslaan(pad=pad, inhoud=inhoud)
        doc.opslag_pad = pad
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="dossier_document",
            record_id=doc.id,
            actie="dossier_document_geupload",
            correlatie_id=gebruiker_id,
            nieuwe_waarde={
                "gebruiker_id": str(gebruiker_id),
                "type_code": type_code,
                "status": doc.status,
                "geldig_tot": geldig_tot.isoformat() if geldig_tot else None,
                "bestandsnaam": bestandsnaam,
                "bron": doc.bron,
                "namens": actor_id != gebruiker_id,
            },
            administratie_id=administratie_id,
        )
        return _herleid_blokkade(
            session, administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=actor_id
        )


def beoordeel_document(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, goedgekeurd: bool, reden: str | None, actor_id: uuid.UUID
) -> DossierStand:
    """Kantoor (module-recht): ter_controle → goedgekeurd / afgewezen (reden verplicht)."""
    reden = (reden or "").strip()
    if not goedgekeurd and not reden:
        raise RedenVerplicht("Afwijzen vereist een reden — die ziet de veldwerker in de app")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_kantoor(session, actor_id)
        doc = session.get(DossierDocument, document_id)
        if doc is None or doc.administratie_id != administratie_id:
            raise NietGevonden("Onbekend dossierdocument")
        if doc.status != DossierDocumentStatus.TER_CONTROLE.value:
            raise OngeldigeInvoer("Alleen een document 'ter controle' kan beoordeeld worden")
        oud = doc.status
        doc.status = DossierDocumentStatus.GOEDGEKEURD.value if goedgekeurd else DossierDocumentStatus.AFGEWEZEN.value
        doc.beoordeeld_door = actor_id
        doc.beoordeeld_op = datetime.now(UTC)
        doc.afwijs_reden = None if goedgekeurd else reden
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="dossier_document",
            record_id=doc.id,
            actie="dossier_document_goedgekeurd" if goedgekeurd else "dossier_document_afgewezen",
            correlatie_id=doc.gebruiker_id,
            oude_waarde={"status": oud},
            nieuwe_waarde={"status": doc.status, "reden": doc.afwijs_reden, "type_code": doc.type_code},
            administratie_id=administratie_id,
        )
        return _herleid_blokkade(
            session, administratie_id=administratie_id, gebruiker_id=doc.gebruiker_id, actor_id=actor_id
        )


def document_inhoud(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, actor_id: uuid.UUID
) -> tuple[str, str, bytes, bool]:
    """(bestandsnaam, content_type, bytes, bsn_gevoelig). Inzage van een bsn-gevoelig document
    wordt geauditeerd (wie, wanneer) — de BSN-regel."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        doc = session.get(DossierDocument, document_id)
        if doc is None or doc.administratie_id != administratie_id:
            raise NietGevonden("Onbekend dossierdocument")
        _vereis_toegang(session, administratie_id=administratie_id, gebruiker_id=doc.gebruiker_id, actor_id=actor_id)
        typen = {t.code: t for t in _typen_in_sessie(session, administratie_id, alleen_actief=False)}
        gevoelig = typen[doc.type_code].bsn_gevoelig if doc.type_code in typen else True
        if gevoelig:
            record_audit_event(
                session,
                actor_id=actor_id,
                module=MODULE,
                tabel="dossier_document",
                record_id=doc.id,
                actie="dossier_document_ingezien",
                correlatie_id=doc.gebruiker_id,
                nieuwe_waarde={"type_code": doc.type_code, "bsn_gevoelig": True},
                administratie_id=administratie_id,
            )
        pad, naam, ctype = doc.opslag_pad, doc.bestandsnaam, doc.content_type
    from app.documenten.storage import standaard_opslag

    return naam, ctype, standaard_opslag().lezen(pad=pad), gevoelig


# --- handhaving --------------------------------------------------------------------------------------------


def toets_indienen(session, *, administratie_id: uuid.UUID, zzper_id: uuid.UUID, actor_id: uuid.UUID) -> None:
    """Aan te roepen ín de indien-transactie (service.dien_week_in): herleidt de blokkade tegen
    de actuele stand (verlopen documenten bijten zichtbaar) en weigert met DossierGeblokkeerd.
    Dagen zetten blijft altijd mogelijk — er raken nooit uren zoek."""
    if session.get(VeldwerkerDossier, (administratie_id, zzper_id)) is None:
        return  # nooit herinnerd/geüpload → geen handhaving actief
    stand = _herleid_blokkade(session, administratie_id=administratie_id, gebruiker_id=zzper_id, actor_id=actor_id)
    if stand.geblokkeerd:
        raise DossierGeblokkeerd(
            "Weekstaat indienen is geblokkeerd: het dossier is na drie herinneringen nog niet compleet ("
            + "; ".join(stand.signalen)
            + "). Upload de ontbrekende documenten in de app — daarna kan de week alsnog ingediend worden."
        )


def _bericht_teksten(stand: DossierStand) -> tuple[str, str, str, str]:
    pad = "/accordeur?dossier=1"
    link = f"{settings.app_basis_url.rstrip('/')}{pad}"
    ontbrekend = "; ".join(stand.signalen) or "documenten ontbreken of zijn verlopen"
    onderwerp = "Herinnering: je dossier is nog niet compleet"
    pushtekst = (
        f"Herinnering {stand.herinneringen_teller + 1} van {MAX_HERINNERINGEN}: je dossier is nog niet compleet."
    )
    mailtekst = (
        f"Beste {stand.gebruiker_naam},\n\n"
        f"Je dossier bij Administratiekantoor Nijenhuis is nog niet compleet ({ontbrekend}).\n\n"
        f"Dit is herinnering {stand.herinneringen_teller + 1} van {MAX_HERINNERINGEN}. Na de derde herinnering "
        f"kun je geen weekstaten meer indienen tot het dossier compleet is.\n\n"
        f"Upload de documenten in de app:\n{link}\n\n"
        "Administratiekantoor Nijenhuis"
    )
    return onderwerp, pushtekst, mailtekst, pad


@dataclass(frozen=True)
class HerinneringResultaat:
    gebruiker_id: uuid.UUID
    volgnummer: int
    kanaal: str
    verzonden_op: datetime
    geblokkeerd: bool


def stuur_herinnering(
    *, administratie_id: uuid.UUID, gebruiker_id: uuid.UUID, actor_id: uuid.UUID
) -> HerinneringResultaat:
    vandaag = _vandaag()
    # Stap 1 — valideren + dagrij claimen (eigen transactie).
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_kantoor(session, actor_id)
        veldwerker = _gebruiker(session, gebruiker_id)
        _vereis_dossier_rol(veldwerker)
        if veldwerker.status != GebruikerStatus.ACTIEF:
            raise OngeldigeInvoer("De veldwerker is niet actief — herinneren heeft geen zin")
        stand = _stand_in_sessie(session, administratie_id=administratie_id, gebruiker_id=gebruiker_id)
        if stand.compleet_incl_ter_controle:
            raise DossierCompleet("Alle verplichte documenten zijn aanwezig (of ter controle) — geen herinnering nodig")
        bestaande = session.scalars(
            select(DossierHerinnering).where(
                DossierHerinnering.administratie_id == administratie_id,
                DossierHerinnering.gebruiker_id == gebruiker_id,
                DossierHerinnering.datum == vandaag,
            )
        ).first()
        volgnummer = stand.herinneringen_teller + 1
        if bestaande is not None:
            if bestaande.status in (HerinneringStatus.VERZONDEN.value, HerinneringStatus.BEZIG.value):
                raise AlHerinnerdVandaag("Vandaag is er al een dossier-herinnering aan deze veldwerker verstuurd")
            bestaande.status = HerinneringStatus.BEZIG.value
            bestaande.volgnummer = volgnummer
            bestaande.verzonden_door = actor_id
            herinnering_id = bestaande.id
        else:
            rij = DossierHerinnering(
                administratie_id=administratie_id,
                gebruiker_id=gebruiker_id,
                datum=vandaag,
                volgnummer=volgnummer,
                status=HerinneringStatus.BEZIG.value,
                verzonden_door=actor_id,
            )
            session.add(rij)
            try:
                session.flush()
            except IntegrityError as exc:
                raise AlHerinnerdVandaag(
                    "Vandaag is er al een dossier-herinnering aan deze veldwerker verstuurd"
                ) from exc
            herinnering_id = rij.id
        session.expunge(veldwerker)

    # Stap 2 — verzenden (buiten de transactie).
    onderwerp, pushtekst, mailtekst, pad = _bericht_teksten(stand)
    uitkomst = verzending.verstuur_push_anders_mail(
        veldwerker, onderwerp=onderwerp, pushtekst=pushtekst, mailtekst=mailtekst, url=pad
    )

    # Stap 3 — uitkomst vastleggen (eigen transactie, óók bij mislukken: de dagrij mag niet op
    # 'bezig' blijven hangen — anders zou een mislukte poging de rest van de dag blokkeren).
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(DossierHerinnering, herinnering_id)
        assert rij is not None
        rij.status = uitkomst.status.value
        rij.kanaal = uitkomst.kanaal.value if uitkomst.kanaal else None
        rij.detail = uitkomst.detail
        mislukt = uitkomst.status != HerinneringStatus.VERZONDEN
        if mislukt:
            record_audit_event(
                session,
                actor_id=actor_id,
                module=MODULE,
                tabel="dossier_herinnering",
                record_id=rij.id,
                actie="dossier_herinnering_mislukt",
                correlatie_id=gebruiker_id,
                nieuwe_waarde={"status": rij.status, "detail": rij.detail},
                administratie_id=administratie_id,
            )
    if mislukt:
        raise HerinneringMislukt(
            "Herinnering niet bezorgd: "
            + str((uitkomst.detail or {}).get("fout") or (uitkomst.detail or {}).get("reden") or uitkomst.status.value)
        )

    # Stap 4 — afronden: teller + blokkade + audit.
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        rij = session.get(DossierHerinnering, herinnering_id)
        assert rij is not None
        rij.verzonden_op = datetime.now(UTC)
        dossier = _dossier_rij(session, administratie_id, gebruiker_id)
        oud_teller = dossier.herinneringen_teller
        dossier.herinneringen_teller = volgnummer
        dossier.laatste_herinnering_op = rij.verzonden_op
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="veldwerker_dossier",
            record_id=gebruiker_id,
            actie="dossier_herinnering_verstuurd",
            correlatie_id=gebruiker_id,
            oude_waarde={"herinneringen_teller": oud_teller},
            nieuwe_waarde={"herinneringen_teller": volgnummer, "kanaal": rij.kanaal, "signalen": stand.signalen},
            administratie_id=administratie_id,
        )
        nieuwe_stand = _herleid_blokkade(
            session, administratie_id=administratie_id, gebruiker_id=gebruiker_id, actor_id=actor_id
        )
        return HerinneringResultaat(
            gebruiker_id=gebruiker_id,
            volgnummer=volgnummer,
            kanaal=rij.kanaal or "",
            verzonden_op=rij.verzonden_op,
            geblokkeerd=nieuwe_stand.geblokkeerd,
        )


# --- KvK / btw (A3) ------------------------------------------------------------------------------------


def bevestig_bedrijfsgegevens(
    *,
    administratie_id: uuid.UUID,
    gebruiker_id: uuid.UUID,
    kvk_nummer: str | None,
    btw_nummer: str | None,
    naam: str | None,
    plaats: str | None,
    rechtsvorm: str | None,
    actor_id: uuid.UUID,
) -> DossierStand:
    """Kantoor bevestigt de (via de KvK-API opgehaalde of handmatig ingevulde) gegevens — de
    lookup zelf schrijft nooit; alleen deze bevestiging landt in het dossier (geaudit oud→nieuw)."""
    kvk_nummer = (kvk_nummer or "").strip() or None
    if kvk_nummer is not None and not (len(kvk_nummer) == 8 and kvk_nummer.isdigit()):
        raise OngeldigeInvoer("Een KvK-nummer bestaat uit precies 8 cijfers")
    btw_nummer = (btw_nummer or "").strip().upper().replace(" ", "").replace(".", "") or None
    if btw_nummer is not None and not (btw_nummer.startswith("NL") and len(btw_nummer) == 14 and btw_nummer[-3] == "B"):
        raise OngeldigeInvoer("Een Nederlands btw-nummer heeft de vorm NL123456789B01")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        _administratie_met_opt_in(session, administratie_id)
        _vereis_kantoor(session, actor_id)
        veldwerker = _gebruiker(session, gebruiker_id)
        _vereis_dossier_rol(veldwerker)
        rij = _dossier_rij(session, administratie_id, gebruiker_id)
        oud = {
            "kvk_nummer": rij.kvk_nummer,
            "btw_nummer": rij.btw_nummer,
            "kvk_naam": rij.kvk_naam,
            "kvk_plaats": rij.kvk_plaats,
            "kvk_rechtsvorm": rij.kvk_rechtsvorm,
        }
        rij.kvk_nummer = kvk_nummer
        rij.btw_nummer = btw_nummer
        rij.kvk_naam = (naam or "").strip() or None
        rij.kvk_plaats = (plaats or "").strip() or None
        rij.kvk_rechtsvorm = (rechtsvorm or "").strip() or None
        rij.kvk_bevestigd_door = actor_id
        rij.kvk_bevestigd_op = datetime.now(UTC)
        nieuw = {
            "kvk_nummer": rij.kvk_nummer,
            "btw_nummer": rij.btw_nummer,
            "kvk_naam": rij.kvk_naam,
            "kvk_plaats": rij.kvk_plaats,
            "kvk_rechtsvorm": rij.kvk_rechtsvorm,
        }
        record_audit_event(
            session,
            actor_id=actor_id,
            module=MODULE,
            tabel="veldwerker_dossier",
            record_id=gebruiker_id,
            actie="dossier_bedrijfsgegevens_bevestigd",
            correlatie_id=gebruiker_id,
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
            administratie_id=administratie_id,
        )
        return _stand_in_sessie(session, administratie_id=administratie_id, gebruiker_id=gebruiker_id)


# --- signalen (veldwerkers-paneel + klantpagina-stand) --------------------------------------------------


@dataclass(frozen=True)
class DossierSamenvatting:
    administratie_id: uuid.UUID
    administratie_naam: str | None
    aantal_verplicht: int
    aantal_aanwezig: int
    aantal_ontbrekend: int
    aantal_verlopen: int
    aantal_verloopt_binnenkort: int
    aantal_ter_controle: int
    herinneringen_teller: int
    geblokkeerd: bool
    compleet: bool


def veldwerkers_van(session, administratie_id: uuid.UUID) -> list[uuid.UUID]:
    """Veldwerkers (dossier-rollen) mét scope op deze administratie — de doelgroep van de
    dossier-signalen; de scope-tabel heeft zelf RLS, dus altijd binnen scoped_session(administratie)."""
    return list(
        session.scalars(
            select(Gebruiker.id)
            .join(GebruikerAdministratie, GebruikerAdministratie.gebruiker_id == Gebruiker.id)
            .where(
                GebruikerAdministratie.administratie_id == administratie_id,
                Gebruiker.rol.in_(list(DOSSIER_ROLLEN)),
                Gebruiker.status == GebruikerStatus.ACTIEF,
            )
        )
    )


def samenvatting_in_sessie(session, *, administratie: Administratie, gebruiker_id: uuid.UUID) -> DossierSamenvatting:
    s = _stand_in_sessie(session, administratie_id=administratie.id, gebruiker_id=gebruiker_id)
    return DossierSamenvatting(
        administratie_id=administratie.id,
        administratie_naam=administratie.naam,
        aantal_verplicht=s.aantal_verplicht,
        aantal_aanwezig=s.aantal_aanwezig,
        aantal_ontbrekend=s.aantal_ontbrekend,
        aantal_verlopen=s.aantal_verlopen,
        aantal_verloopt_binnenkort=s.aantal_verloopt_binnenkort,
        aantal_ter_controle=s.aantal_ter_controle,
        herinneringen_teller=s.herinneringen_teller,
        geblokkeerd=s.geblokkeerd,
        compleet=s.compleet,
    )


@dataclass(frozen=True)
class DossierSignalen:
    veldwerkers_met_signaal: int  # ontbrekend, verlopen of verloopt binnenkort
    ter_controle: int  # documenten die op kantoor-beoordeling wachten
    geblokkeerd: int


def signalen_in_sessie(session, *, administratie: Administratie) -> DossierSignalen:
    met_signaal = ter_controle = geblokkeerd = 0
    for gid in veldwerkers_van(session, administratie.id):
        s = _stand_in_sessie(session, administratie_id=administratie.id, gebruiker_id=gid)
        if s.aantal_ontbrekend or s.aantal_verlopen or s.aantal_verloopt_binnenkort:
            met_signaal += 1
        ter_controle += s.aantal_ter_controle
        if s.geblokkeerd:
            geblokkeerd += 1
    return DossierSignalen(met_signaal, ter_controle, geblokkeerd)
