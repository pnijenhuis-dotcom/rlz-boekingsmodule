"""Dag-einde herinnering "Nog geen uren voor vandaag" (veld-app UX run B, akkoord Peter 18-09 "alle punten";
migratie 0162).

Cloud Run-job `rlz-uren-herinneringen` (CLI `uren-herinneringen`, scheduler elk kwartier 15:00–18:45 ma–vr
Europe/Amsterdam) — de job toetst zélf de administratie-tijd: per administratie mét de uren-&-meerwerk-opt-in geldt
`uren_herinnering_tijd`
(NULL = 16:30, `STANDAARD_HERINNERING_TIJD`) en hooguit tot 19:00. Kandidaten = actieve gebruikers met een invullersrol
(ZZP'er / uitvoerder — de detacheerder vult namens anderen in en krijgt géén herinnering) mét scope op zo'n
administratie.
Overslaan (altijd geteld, nooit stil): geen werkdag (za/zo, NL-kalenderdag via `app/tijd.py`), tijd nog niet bereikt,
ná
19:00, vandaag al uren (som van `weekstaat_dag.uren` > 0 over ÁLLE weekstaten van de veldwerker, in élke
administratie),
opt-out (`gebruiker.uren_herinnering_uit`), al verzonden vandaag (claim `uren_herinnering`, UNIQUE gebruiker+datum),
stille uren (bestaand 20:00–08:00), geen kanaal (= claim `geen_kanaal`, zodat niet elk kwartier opnieuw geprobeerd
wordt). Verzending = push-anders-mail (`app/berichten/verzending.py`), deep-link `/accordeur?uren=vandaag`. Idempotent:
claim vóór
verzenden. Elke run schrijft één administratie-loos audit-event `uren_herinnering_run` mét de tellers — bron van de
reconciliatie-teller "Uren-herinnering einde werkdag" (verwacht / gedaan / overgeslagen mét reden).
Geen stille no-op (kernprincipe 7, WERKWIJZE v1.13): geen tijd ingesteld = default doorlopen; alleen de harde voorwaarde
"geen kanaal" blokkeert, zichtbaar."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime, time

from sqlalchemy import func, select

from app.berichten import verzending
from app.berichten.models import HerinneringKanaal, HerinneringStatus
from app.berichten.nieuwe_facturen import in_stille_uren
from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie, Gebruiker, GebruikerAdministratie, GebruikerStatus
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.tijd import TIJDZONE_NL
from app.uren.models import UrenHerinnering, Weekstaat, WeekstaatDag
from app.uren.service import INVULLER_ROLLEN

logger = logging.getLogger(__name__)

MODULE = "boekhouding"
#: Default herinneringstijd (Europe/Amsterdam) als de administratie niets instelt — beslispunt run B 18-09.
STANDAARD_HERINNERING_TIJD = time(16, 30)
#: Ná dit uur (NL) geen herinnering meer — de werkdag is voorbij, morgen is er een nieuwe dag.
EINDE_VENSTER = time(19, 0)
#: Kanaal-waarden in de claim-tabel (naast HerinneringKanaal.PUSH/E_MAIL).
KANAAL_GEEN = "geen_kanaal"
PAD = "/accordeur?uren=vandaag"
ONDERWERP = "Nog geen uren voor vandaag"


@dataclass
class HerinneringRapport:
    """Tellers van één run — verwacht = gedaan + alle overgeslagen-tellers (kernprincipe 7)."""

    datum: str = ""
    werkdag: bool = True
    stille_uren: bool = False
    administraties_met_opt_in: int = 0
    administraties_tijd_bereikt: int = 0
    kandidaten: int = 0
    verwacht: int = 0
    gedaan: int = 0
    verzonden_push: int = 0
    verzonden_mail: int = 0
    overgeslagen_al_uren: int = 0
    overgeslagen_opt_out: int = 0
    overgeslagen_al_verzonden: int = 0
    overgeslagen_stille_uren: int = 0
    overgeslagen_geen_kanaal: int = 0
    overgeslagen_niet_actief: int = 0
    geen_tijd_bereikt: int = 0
    mislukt: int = 0
    fouten: list[str] = field(default_factory=list)

    @property
    def is_fout(self) -> bool:
        return self.mislukt > 0

    def als_dict(self) -> dict:
        return asdict(self)


def bericht_teksten(*, vandaag: date) -> tuple[str, str, str]:
    link = f"{settings.app_basis_url.rstrip('/')}{PAD}"
    pushtekst = "Nog geen uren voor vandaag — vul ze even in voordat je stopt."
    mailtekst = (
        "Beste,\n\n"
        f"Voor vandaag ({vandaag.strftime('%d-%m-%Y')}) staan er nog geen uren in de app.\n\n"
        f"Open de app en vul je uren in:\n{link}\n\n"
        "Wil je deze herinnering niet meer? Zet 'm uit onder ⚙ Toegang in de app.\n\n"
        "Administratiekantoor Nijenhuis"
    )
    return ONDERWERP, pushtekst, mailtekst


def herinneringstijd(administratie: Administratie) -> time:
    return administratie.uren_herinnering_tijd or STANDAARD_HERINNERING_TIJD


def _administraties_met_opt_in(session) -> list[Administratie]:  # noqa: ANN001
    return list(
        session.scalars(
            select(Administratie).where(
                Administratie.actief.is_(True), Administratie.uren_meerwerk_ingeschakeld.is_(True)
            )
        ).all()
    )


def _kandidaten_in(session, administratie_id: uuid.UUID) -> list[Gebruiker]:  # noqa: ANN001
    """Invullers (ZZP'er/uitvoerder) mét scope op déze administratie — in de scope van die administratie (RLS op
    gebruiker_administratie), één statement."""
    return list(
        session.scalars(
            select(Gebruiker)
            .join(GebruikerAdministratie, GebruikerAdministratie.gebruiker_id == Gebruiker.id)
            .where(
                GebruikerAdministratie.administratie_id == administratie_id,
                Gebruiker.rol.in_(list(INVULLER_ROLLEN)),
            )
            .order_by(Gebruiker.id)
        ).all()
    )


def _met_uren_vandaag_in(session, administratie_id: uuid.UUID, vandaag: date) -> set[uuid.UUID]:  # noqa: ANN001
    """Wie heeft vandaag al uren (> 0) op een weekstaat in déze administratie — één statement per administratie; de som
    over alle opt-in-administraties geeft "op welke weekstaat dan ook"."""
    rijen = session.execute(
        select(Weekstaat.gebruiker_id)
        .join(WeekstaatDag, WeekstaatDag.weekstaat_id == Weekstaat.id)
        .where(Weekstaat.administratie_id == administratie_id, WeekstaatDag.datum == vandaag)
        .group_by(Weekstaat.gebruiker_id)
        .having(func.coalesce(func.sum(WeekstaatDag.uren), 0) > 0)
    ).all()
    return {r[0] for r in rijen}


def _al_verzonden(session, gebruiker_ids: list[uuid.UUID], vandaag: date) -> set[uuid.UUID]:  # noqa: ANN001
    if not gebruiker_ids:
        return set()
    rijen = session.execute(
        select(UrenHerinnering.gebruiker_id).where(
            UrenHerinnering.gebruiker_id.in_(gebruiker_ids), UrenHerinnering.datum == vandaag
        )
    ).all()
    return {r[0] for r in rijen}


def _claim(
    session, *, gebruiker_id: uuid.UUID, administratie_id: uuid.UUID, vandaag: date, kanaal: str, detail: str | None
) -> None:  # noqa: ANN001
    session.add(
        UrenHerinnering(
            gebruiker_id=gebruiker_id,
            administratie_id=administratie_id,
            datum=vandaag,
            verzonden_op=datetime.now(UTC),
            kanaal=kanaal,
            detail=detail,
        )
    )
    session.flush()


def verstuur_dag_einde_herinneringen(*, nu: datetime | None = None) -> HerinneringRapport:
    """Eén job-run. `nu` = UTC-moment (test-injectie); de NL-kalenderdag en -tijd worden eruit afgeleid."""
    moment = nu or datetime.now(UTC)
    lokaal = moment.astimezone(TIJDZONE_NL)
    vandaag = lokaal.date()
    rapport = HerinneringRapport(datum=vandaag.isoformat())
    if vandaag.weekday() >= 5:
        rapport.werkdag = False
        _schrijf_run_audit(rapport)
        return rapport
    if lokaal.time() >= EINDE_VENSTER:
        # Ná 19:00 geen herinnering meer (de scheduler stopt om 18:45; dit is het vangnet bij een late run).
        rapport.geen_tijd_bereikt = -1
        _schrijf_run_audit(rapport)
        return rapport
    stil = in_stille_uren(moment)
    rapport.stille_uren = stil

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        administraties = _administraties_met_opt_in(session)
        rapport.administraties_met_opt_in = len(administraties)
        bereikt: dict[uuid.UUID, time] = {}
        for a in administraties:
            t = herinneringstijd(a)
            if lokaal.time() >= t:
                bereikt[a.id] = t
            else:
                rapport.geen_tijd_bereikt += 1
        rapport.administraties_tijd_bereikt = len(bereikt)
        opt_in_ids = [a.id for a in administraties]
    if not bereikt:
        _schrijf_run_audit(rapport)
        return rapport

    # Per administratie in haar eigen scope (RLS op gebruiker_administratie en weekstaat): kandidaten waar de tijd
    # bereikt is, uren-van-vandaag over ÁLLE opt-in-administraties.
    kandidaten: dict[uuid.UUID, tuple[Gebruiker, uuid.UUID]] = {}
    met_uren: set[uuid.UUID] = set()
    for aid in opt_in_ids:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            met_uren |= _met_uren_vandaag_in(session, aid, vandaag)
            if aid in bereikt:
                for gebruiker in _kandidaten_in(session, aid):
                    session.expunge(gebruiker)
                    kandidaten.setdefault(gebruiker.id, (gebruiker, aid))
    rapport.kandidaten = len(kandidaten)
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        al_verzonden = _al_verzonden(session, list(kandidaten), vandaag)
    te_doen: list[tuple[Gebruiker, uuid.UUID]] = []
    for gid, (gebruiker, aid) in kandidaten.items():
        rapport.verwacht += 1
        if gid in al_verzonden:
            rapport.overgeslagen_al_verzonden += 1
        elif gebruiker.status != GebruikerStatus.ACTIEF:
            rapport.overgeslagen_niet_actief += 1
        elif gid in met_uren:
            rapport.overgeslagen_al_uren += 1
        elif gebruiker.uren_herinnering_uit:
            rapport.overgeslagen_opt_out += 1
        elif stil:
            rapport.overgeslagen_stille_uren += 1
        else:
            te_doen.append((gebruiker, aid))

    onderwerp, pushtekst, mailtekst = bericht_teksten(vandaag=vandaag)
    for gebruiker, aid in te_doen:
        try:
            uitkomst = verzending.verstuur_push_anders_mail(
                gebruiker, onderwerp=onderwerp, pushtekst=pushtekst, mailtekst=mailtekst, url=PAD
            )
        except Exception as exc:  # noqa: BLE001 — nooit stil; geen claim, de volgende run herkanst
            rapport.mislukt += 1
            rapport.fouten.append(f"uren-herinnering {gebruiker.id}: {exc}")
            continue
        if uitkomst.status == HerinneringStatus.VERZONDEN:
            kanaal = uitkomst.kanaal.value if uitkomst.kanaal else HerinneringKanaal.E_MAIL.value
            if uitkomst.kanaal == HerinneringKanaal.PUSH:
                rapport.verzonden_push += 1
            else:
                rapport.verzonden_mail += 1
            rapport.gedaan += 1
            _claim_veilig(gebruiker.id, aid, vandaag, kanaal, None)
        elif uitkomst.status == HerinneringStatus.OVERGESLAGEN:
            # Geen kanaal (geen toestel-subscriptie én geen mailadres): harde voorwaarde, zichtbaar — claim zodat de
            # volgende kwartier-run niet opnieuw probeert; morgen wél weer (nieuwe dag = nieuwe claim).
            rapport.overgeslagen_geen_kanaal += 1
            _claim_veilig(gebruiker.id, aid, vandaag, KANAAL_GEEN, str(uitkomst.detail) if uitkomst.detail else None)
        else:
            rapport.mislukt += 1
            rapport.fouten.append(f"uren-herinnering {gebruiker.id}: {uitkomst.detail}")
    _schrijf_run_audit(rapport)
    return rapport


def _claim_veilig(gebruiker_id: uuid.UUID, aid: uuid.UUID, vandaag: date, kanaal: str, detail: str | None) -> None:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        _claim(session, gebruiker_id=gebruiker_id, administratie_id=aid, vandaag=vandaag, kanaal=kanaal, detail=detail)
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module=MODULE,
            tabel="uren_herinnering",
            record_id=gebruiker_id,
            actie="uren_herinnering_verzonden",
            correlatie_id=gebruiker_id,
            nieuwe_waarde={"datum": vandaag.isoformat(), "kanaal": kanaal, **({"detail": detail} if detail else {})},
        )


def _schrijf_run_audit(rapport: HerinneringRapport) -> None:
    """Eén administratie-loos audit-event per run (systeem-actor) — de bron van de reconciliatie-teller."""
    try:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module=MODULE,
                tabel="uren_herinnering",
                record_id=SYSTEEM_ACTOR_ID,
                actie="uren_herinnering_run",
                correlatie_id=uuid.uuid4(),
                nieuwe_waarde=rapport.als_dict(),
            )
    except Exception:  # noqa: BLE001 — de teller mag de job nooit laten omvallen
        logger.exception("audit uren_herinnering_run mislukt")


def rapport_regel(rapport: HerinneringRapport) -> str:
    return (
        f"uren-herinneringen {rapport.datum}: werkdag={rapport.werkdag} stille_uren={rapport.stille_uren} "
        f"administraties_opt_in={rapport.administraties_met_opt_in} tijd_bereikt={rapport.administraties_tijd_bereikt} "
        f"kandidaten={rapport.kandidaten} verwacht={rapport.verwacht} gedaan={rapport.gedaan} "
        f"(push={rapport.verzonden_push} mail={rapport.verzonden_mail}) "
        f"overgeslagen: al_uren={rapport.overgeslagen_al_uren} opt_out={rapport.overgeslagen_opt_out} "
        f"al_verzonden={rapport.overgeslagen_al_verzonden} stille_uren={rapport.overgeslagen_stille_uren} "
        f"geen_kanaal={rapport.overgeslagen_geen_kanaal} niet_actief={rapport.overgeslagen_niet_actief} "
        f"mislukt={rapport.mislukt}"
    )
