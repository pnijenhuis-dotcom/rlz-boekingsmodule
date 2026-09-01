"""Maandagochtend-digest kantoor (best-practice-punt D2, 01-09): één weekmail per kantoormedewerker mét
zijn eigen scope — werkvoorraad-standen per administratie (alleen tellers > 0), de bij-klant-stand en
de signalen (duplicaat, factuurmatch, terugkerend). Alleen versturen als er iets te melden is;
idempotent per ISO-week per medewerker (claim-vóór-verzenden, patroon accordeur_herinnering);
opt-out per gebruiker (`platform.gebruiker.digest_opt_out`). Bestaand SMTP-kanaal; job
`rlz-kantoor-digest` ma 07:30 Europe/Amsterdam (CLI `kantoor-digest`). Geen AI."""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from app.auth import service as auth_service
from app.berichten import mail
from app.berichten.models import HerinneringStatus, KantoorDigest
from app.config import settings
from app.db.models import Gebruiker, GebruikerRol, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service as documenten_service
from app.documenten.service import WerkvoorraadKlant

TIJDZONE = ZoneInfo("Europe/Amsterdam")
KANTOOR_ROLLEN = (GebruikerRol.BEHEERDER, GebruikerRol.BOEKHOUDING_PROJECTEN, GebruikerRol.BOEKHOUDING)


@dataclass
class DigestRapport:
    verzonden: int = 0
    al_verzonden: int = 0
    niets_te_melden: int = 0
    opt_out: int = 0
    mislukt: int = 0
    onafgemaakt: int = 0
    fouten: list[str] = field(default_factory=list)

    @property
    def is_fout(self) -> bool:
        return bool(self.mislukt or self.onafgemaakt)


def iso_week(dag: date) -> str:
    jaar, week, _ = dag.isocalendar()
    return f"{jaar}-W{week:02d}"


def _vandaag() -> date:
    return datetime.now(TIJDZONE).date()


# ----------------------------------------------------------------------------- inhoud (puur)


@dataclass(frozen=True)
class AdministratieRegel:
    naam: str
    onderdelen: tuple[str, ...]


def _onderdelen(k: WerkvoorraadKlant) -> tuple[str, ...]:
    def n(aantal: int, enk: str, mv: str) -> str:
        return f"{aantal} {enk if aantal == 1 else mv}"

    uit: list[str] = []
    if k.te_controleren:
        uit.append(n(k.te_controleren, "te controleren", "te controleren"))
    if k.klaar_om_te_boeken:
        uit.append(n(k.klaar_om_te_boeken, "klaar om te boeken", "klaar om te boeken"))
    if k.vragen:
        uit.append(n(k.vragen, "open vraag", "open vragen"))
    if k.afgewezen:
        uit.append(n(k.afgewezen, "afgewezen", "afgewezen"))
    if k.bij_klant:
        uit.append(n(k.bij_klant, "bij de klant (accordering)", "bij de klant (accordering)"))
    if k.iban_wachtend:
        uit.append(n(k.iban_wachtend, "IBAN-wissel wacht op akkoord", "IBAN-wissels wachten op akkoord"))
    signalen: list[str] = []
    if k.duplicaat_signalen:
        signalen.append(n(k.duplicaat_signalen, "duplicaatsignaal", "duplicaatsignalen"))
    if k.match_afwijkingen:
        signalen.append(n(k.match_afwijkingen, "urenmatch-afwijking", "urenmatch-afwijkingen"))
    if k.terugkerend_signalen:
        signalen.append(n(k.terugkerend_signalen, "verwachte factuur ontbreekt", "verwachte facturen ontbreken"))
    if signalen:
        uit.append("signalen: " + ", ".join(signalen))
    return tuple(uit)


def bouw_regels(klanten: list[WerkvoorraadKlant]) -> list[AdministratieRegel]:
    """Alleen administraties mét iets te melden (tellers > 0), op naam."""
    regels = [AdministratieRegel(k.naam, _onderdelen(k)) for k in klanten]
    return sorted((r for r in regels if r.onderdelen), key=lambda r: r.naam.lower())


def bouw_mail(*, naam: str, week: str, regels: list[AdministratieRegel]) -> tuple[str, str]:
    """(onderwerp, tekst) — klantleesbaar, één regel per administratie."""
    totaal_adm = len(regels)
    kop = f"Beste {naam},\n\nDe stand van vanochtend voor jouw administraties ({week}):\n\n"
    body = "\n".join(f"• {r.naam}: " + " · ".join(r.onderdelen) for r in regels)
    staart = (
        f"\n\nOpen de werkvoorraad: {settings.app_basis_url.rstrip('/')}/\n\n"
        "Deze weekmail komt elke maandag om 07:30 zolang er iets te melden is. Uitzetten kan onder "
        "Instellingen › Beveiliging › Weekmail.\n\nAdministratiekantoor Nijenhuis"
    )
    onderwerp = f"Weekstart: {totaal_adm} administratie{'' if totaal_adm == 1 else 's'} met openstaand werk ({week})"
    return onderwerp, kop + body + staart


# ----------------------------------------------------------------------------- selectie + verzending


def _kantoormedewerkers() -> list[Gebruiker]:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.scalars(
            select(Gebruiker)
            .where(
                Gebruiker.rol.in_(list(KANTOOR_ROLLEN)),
                Gebruiker.status == GebruikerStatus.ACTIEF,
                Gebruiker.gepseudonimiseerd_op.is_(None),
                Gebruiker.id != SYSTEEM_ACTOR_ID,
            )
            .order_by(Gebruiker.naam)
        ).all()
        session.expunge_all()
        return list(rijen)


@dataclass(frozen=True)
class _Claim:
    uitkomst: str  # 'nieuw' | 'al_verzonden' | 'onafgemaakt'
    digest_id: uuid.UUID | None


def _claim(gebruiker_id: uuid.UUID, week: str) -> _Claim:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        bestaand = session.scalars(
            select(KantoorDigest).where(KantoorDigest.gebruiker_id == gebruiker_id, KantoorDigest.iso_week == week)
        ).first()
        if bestaand is not None:
            if bestaand.status == HerinneringStatus.VERZONDEN.value:
                return _Claim("al_verzonden", bestaand.id)
            if bestaand.status == HerinneringStatus.BEZIG.value:
                return _Claim("onafgemaakt", bestaand.id)
            # mislukt/overgeslagen: opnieuw proberen op dezelfde rij
            bestaand.status = HerinneringStatus.BEZIG.value
            return _Claim("nieuw", bestaand.id)
        rij = KantoorDigest(gebruiker_id=gebruiker_id, iso_week=week, status=HerinneringStatus.BEZIG.value)
        session.add(rij)
        try:
            session.flush()
        except IntegrityError:
            return _Claim("al_verzonden", None)
        return _Claim("nieuw", rij.id)


def _rond_af(digest_id: uuid.UUID, *, status: HerinneringStatus, detail: dict | None) -> None:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(KantoorDigest, digest_id)
        if rij is None:
            return
        rij.status = status.value
        rij.detail = detail
        if status == HerinneringStatus.VERZONDEN:
            rij.verzonden_op = datetime.now(UTC)


def regels_voor(gebruiker: Gebruiker) -> list[AdministratieRegel]:
    administraties = auth_service.mijn_administraties(actor_id=gebruiker.id, rol=gebruiker.rol)
    klanten = documenten_service.werkvoorraad_overzicht(
        administratie_ids_met_naam=[(a.id, a.naam) for a in administraties]
    )
    return bouw_regels(klanten)


def verstuur_weekdigest(*, vandaag: date | None = None) -> DigestRapport:
    """Job-entrypoint (ma 07:30). Idempotent per (medewerker, ISO-week): een herhaalde run stuurt nooit
    dubbel; niets te melden = geen mail én geen rij; opt-out = overslaan; fouten zichtbaar (exit 1)."""
    rapport = DigestRapport()
    week = iso_week(vandaag or _vandaag())
    for gebruiker in _kantoormedewerkers():
        if gebruiker.digest_opt_out:
            rapport.opt_out += 1
            continue
        try:
            regels = regels_voor(gebruiker)
        except Exception as exc:  # noqa: BLE001 — één medewerker stopt de rest niet, wél zichtbaar
            rapport.mislukt += 1
            rapport.fouten.append(f"standen voor {gebruiker.id}: {type(exc).__name__}: {exc}")
            continue
        if not regels:
            rapport.niets_te_melden += 1
            continue
        claim = _claim(gebruiker.id, week)
        if claim.uitkomst == "al_verzonden":
            rapport.al_verzonden += 1
            continue
        if claim.uitkomst == "onafgemaakt":
            rapport.onafgemaakt += 1
            rapport.fouten.append(
                f"digest voor {gebruiker.id} ({week}) bleef op 'bezig' staan (gecrashte run?) — niet automatisch "
                "opnieuw verstuurd, handmatig beoordelen"
            )
            continue
        onderwerp, tekst = bouw_mail(naam=gebruiker.naam, week=week, regels=regels)
        assert claim.digest_id is not None
        try:
            mail.verzend_mail(naar=gebruiker.e_mail, onderwerp=onderwerp, tekst=tekst)
        except Exception as exc:  # noqa: BLE001 — MailFout én onverwacht: beide zichtbaar mislukt
            _rond_af(claim.digest_id, status=HerinneringStatus.MISLUKT, detail={"fout": str(exc)})
            rapport.mislukt += 1
            rapport.fouten.append(f"verzending mislukt voor {gebruiker.id}: {exc}")
            continue
        _rond_af(
            claim.digest_id,
            status=HerinneringStatus.VERZONDEN,
            detail={"administraties": len(regels), "onderwerp": onderwerp},
        )
        rapport.verzonden += 1
    return rapport


# ----------------------------------------------------------------------------- opt-out


def haal_opt_out_op(*, gebruiker_id: uuid.UUID) -> bool:
    with scoped_session(None, actor_id=gebruiker_id) as session:
        g = session.get(Gebruiker, gebruiker_id)
        return bool(g and g.digest_opt_out)


def zet_opt_out(*, gebruiker_id: uuid.UUID, opt_out: bool) -> bool:
    """Eigen voorkeur (élke kantoorrol) — audit oud→nieuw op de eigen gebruikersrij."""
    from app.db.audit import record_audit_event

    with scoped_session(None, actor_id=gebruiker_id) as session:
        g = session.get(Gebruiker, gebruiker_id)
        if g is None:
            raise ValueError("Onbekende gebruiker")
        oud = g.digest_opt_out
        g.digest_opt_out = opt_out
        record_audit_event(
            session,
            actor_id=gebruiker_id,
            module="platform",
            tabel="gebruiker",
            record_id=gebruiker_id,
            actie="digest_opt_out_gewijzigd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"digest_opt_out": oud},
            nieuwe_waarde={"digest_opt_out": opt_out},
        )
        return opt_out
