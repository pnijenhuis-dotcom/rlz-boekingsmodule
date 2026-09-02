"""Administratie-toewijzing op tenaamstelling (leidend) met afzender als hint (CLAUDE.md-
verzamelbakbesluit). Deterministisch — de AI leest hooguit de tenaamstelling vóór, de matching
zelf is code:

1. Tenaamstelling matcht exact (genormaliseerd) een administratienaam of een geleerde
   tenaamstelling-regel → automatische toewijzing.
2. Geen tenaamstelling-match, wél een geleerde afzender-regel → automatische toewijzing
   (mockup: "dezelfde afzender wordt de volgende keer automatisch gekoppeld"), MAAR alleen als
   er geen tegenstrijdig tenaamstelling-signaal is: is er wél een tenaamstelling gelezen die
   nergens op matcht, dan is dat twijfel → verzamelbak, met de afzender-administratie als
   suggestie ("nooit auto-toewijzen bij twijfel").
3. Anders → verzamelbak, met de beste hint als suggestie (nooit een stille keuze).
4. Mail-body als HINT (feedbackronde 25-08 deel 3, punt 1c — casus "dit is voor Oirschot"): komt
   er zonder tenaamstelling-/afzender-match nog géén suggestie uit, dan wordt de begeleidende
   mailtekst deterministisch afgezocht op administratienamen (onderscheidende naam-tokens als
   hele woorden; precies één administratie met de hoogste score) → uitsluitend een SUGGESTIE
   (`suggestie_bron="mail_body"`), nooit een automatische toewijzing — tenaamstelling blijft
   leidend, een collega-opmerking is een hint.

Leren: elke handmatige toewijzing in de verzamelbak wordt een regel (tenaamstelling én — als
bekend — afzender). Zelfde sleutel later anders toegewezen = oude regel deactiveren + nieuwe
rij (historie blijft)."""

from __future__ import annotations

import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.intake.models import ToewijzingRegel, ToewijzingRegelSoort

# Eigen normalisatie — bewust NIET de vendor-matchnormalisatie van app/extractie/controle.py:
# die strijkt ook "holding" weg, terwijl dat woord bij tenaamstelling-toewijzing juist het
# onderscheid maakt (mockup: tenaamstelling "BLOW Holding" matcht "BLOW B.V." níét exact — dat
# hoort verzamelbak te zijn, geen auto-match). Alleen rechtsvorm-afkortingen zijn opmaak.
_RECHTSVORM_SUFFIX = re.compile(r"\b(b\.?v\.?|n\.?v\.?|v\.?o\.?f\.?|c\.?v\.?)\b", re.IGNORECASE)
_GEEN_LETTER_OF_CIJFER = re.compile(r"[^0-9a-zà-ÿ]+")


def normaliseer_partijnaam(naam: str) -> str:
    zonder_rechtsvorm = _RECHTSVORM_SUFFIX.sub(" ", naam.lower())
    tokens = [t for t in _GEEN_LETTER_OF_CIJFER.split(zonder_rechtsvorm) if t]
    return " ".join(tokens)


@dataclass(frozen=True)
class ToewijzingBesluit:
    """None-administratie = verzamelbak. `suggestie_*` is de beste hint voor de mens."""

    administratie_id: uuid.UUID | None
    bron: str | None
    suggestie_administratie_id: uuid.UUID | None = None
    suggestie_bron: str | None = None


def normaliseer_afzender(afzender: str | None) -> str | None:
    if not afzender:
        return None
    schoon = afzender.strip().lower()
    return schoon or None


def afzender_uitgesloten(afzender_sleutel: str | None) -> bool:
    """Kantoor-/doorstuurdomein (config `intake_afzender_uitgesloten_domeinen`): géén afzender-regel
    leren en géén (auto-)toewijzing/suggestie op afzender — diagnose 02-09 punt 3 (peter@ak-nijenhuis.nl
    klapte in 9 dagen 4× om naar 4 administraties). Subdomeinen tellen mee."""
    if not afzender_sleutel or "@" not in afzender_sleutel:
        return False
    domein = afzender_sleutel.rsplit("@", 1)[1].strip().lower().rstrip(">")
    for uitgesloten in settings.intake_afzender_uitgesloten_domeinen:
        u = uitgesloten.strip().lower().lstrip("@")
        if u and (domein == u or domein.endswith("." + u)):
            return True
    return False


#: Flip-detectie afzender-regels: zodra een afzender-sleutel in zijn historie (actief + gedeactiveerd)
#: naar zoveel verschillende administraties heeft gewezen, is de afzender meerduidig — de regel wordt
#: gedeactiveerd en nooit meer geleerd of gesuggereerd (admin@kempenrecreatie.nl: 12 versies, 6 doelen).
AFZENDER_MEERDUIDIG_VANAF = 3


def _historische_doelen(session: Session, *, soort: ToewijzingRegelSoort, sleutel: str) -> set[uuid.UUID]:
    return set(
        session.scalars(
            select(ToewijzingRegel.administratie_id).where(
                ToewijzingRegel.soort == soort.value, ToewijzingRegel.sleutel == sleutel
            )
        ).all()
    )


def _actieve_regel(session: Session, *, soort: ToewijzingRegelSoort, sleutel: str) -> ToewijzingRegel | None:
    return session.scalars(
        select(ToewijzingRegel).where(
            ToewijzingRegel.soort == soort.value,
            ToewijzingRegel.sleutel == sleutel,
            ToewijzingRegel.actief.is_(True),
        )
    ).first()


def _administratie_op_naam(session: Session, genormaliseerde_naam: str) -> uuid.UUID | None:
    """Exacte (genormaliseerde) naammatch tegen het administratieregister — alleen bij precies
    één match, anders geen giswerk."""
    kandidaten = [
        rij.id
        for rij in session.scalars(select(Administratie).where(Administratie.actief.is_(True)))
        if normaliseer_partijnaam(rij.naam) == genormaliseerde_naam
    ]
    return kandidaten[0] if len(kandidaten) == 1 else None


# Naam-tokens die op zichzelf niets onderscheiden (komen in veel administratienamen voor).
_ALGEMENE_NAAM_TOKENS = {
    "beheer", "holding", "vastgoed", "groep", "group", "facilities", "recreatie", "exploitatie",
    "onroerend", "goed", "administratie", "kantoor", "bedrijf", "bedrijven", "van", "de", "het", "en",
}  # fmt: skip
_WOORD = re.compile(r"[0-9a-zà-ÿ]+")


def _naam_tokens(naam: str) -> set[str]:
    return {t for t in normaliseer_partijnaam(naam).split() if len(t) >= 3}


def vind_administratie_hint_in_tekst(session: Session, tekst: str | None) -> uuid.UUID | None:
    """Deterministische naamherkenning in vrije tekst (mail-body). Per actieve administratie:
    kandidaat zodra minstens één ONDERSCHEIDEND naam-token (niet uit _ALGEMENE_NAAM_TOKENS) als
    heel woord in de tekst staat; score = alle naam-tokens die voorkomen (ook de algemene, die
    maken het verschil tussen "Molenhof Beheer" en "Molenhof Vastgoed"). Precies één kandidaat
    met de hoogste score → de hint; gelijkspel ("voor Molenhof") = geen hint — nooit gokken."""
    if not tekst:
        return None
    woorden = set(_WOORD.findall(tekst.lower()))
    if not woorden:
        return None
    scores: list[tuple[int, uuid.UUID]] = []
    for rij in session.scalars(select(Administratie).where(Administratie.actief.is_(True))):
        tokens = _naam_tokens(rij.naam)
        if not (tokens - _ALGEMENE_NAAM_TOKENS) & woorden:
            continue
        scores.append((len(tokens & woorden), rij.id))
    if not scores:
        return None
    hoogste = max(score for score, _ in scores)
    winnaars = [adm_id for score, adm_id in scores if score == hoogste]
    return winnaars[0] if len(winnaars) == 1 else None


def bepaal_toewijzing(
    session: Session,
    *,
    tenaamstelling: str | None,
    afzender: str | None,
    body_hint: str | None = None,
) -> ToewijzingBesluit:
    tenaamstelling_sleutel = normaliseer_partijnaam(tenaamstelling) if tenaamstelling else ""
    afzender_sleutel = normaliseer_afzender(afzender)

    if tenaamstelling_sleutel:
        regel = _actieve_regel(session, soort=ToewijzingRegelSoort.TENAAMSTELLING, sleutel=tenaamstelling_sleutel)
        if regel is not None:
            return ToewijzingBesluit(administratie_id=regel.administratie_id, bron="tenaamstelling_regel")
        register_match = _administratie_op_naam(session, tenaamstelling_sleutel)
        if register_match is not None:
            return ToewijzingBesluit(administratie_id=register_match, bron="tenaamstelling_register")

    afzender_regel = (
        _actieve_regel(session, soort=ToewijzingRegelSoort.AFZENDER, sleutel=afzender_sleutel)
        if afzender_sleutel and not afzender_uitgesloten(afzender_sleutel)
        else None
    )
    if afzender_regel is not None:
        if tenaamstelling_sleutel:
            # Tegenstrijdig signaal: er ís een tenaamstelling maar die matcht niets — twijfel,
            # dus verzamelbak mét de afzender-administratie als suggestie.
            return ToewijzingBesluit(
                administratie_id=None,
                bron=None,
                suggestie_administratie_id=afzender_regel.administratie_id,
                suggestie_bron="afzender_regel_maar_onbekende_tenaamstelling",
            )
        return ToewijzingBesluit(administratie_id=afzender_regel.administratie_id, bron="afzender_regel")

    body_suggestie = vind_administratie_hint_in_tekst(session, body_hint)
    if body_suggestie is not None:
        return ToewijzingBesluit(
            administratie_id=None,
            bron=None,
            suggestie_administratie_id=body_suggestie,
            suggestie_bron="mail_body",
        )
    return ToewijzingBesluit(administratie_id=None, bron=None)


def leer_toewijzing(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    tenaamstelling: str | None,
    afzender: str | None,
) -> None:
    """Legt de handmatige toewijzing vast als regel(s) — tenaamstelling én afzender voor zover
    bekend. Ongewijzigd = no-op; ander doel voor dezelfde sleutel = oude regel deactiveren +
    nieuwe rij, mét audit_event."""
    paren: list[tuple[ToewijzingRegelSoort, str]] = []
    tenaamstelling_sleutel = normaliseer_partijnaam(tenaamstelling) if tenaamstelling else ""
    if tenaamstelling_sleutel:
        paren.append((ToewijzingRegelSoort.TENAAMSTELLING, tenaamstelling_sleutel))
    afzender_sleutel = normaliseer_afzender(afzender)
    if afzender_sleutel and not afzender_uitgesloten(afzender_sleutel):
        paren.append((ToewijzingRegelSoort.AFZENDER, afzender_sleutel))

    for soort, sleutel in paren:
        bestaand = _actieve_regel(session, soort=soort, sleutel=sleutel)
        if bestaand is not None and bestaand.administratie_id == administratie_id:
            continue
        oude_waarde = None
        if bestaand is not None:
            oude_waarde = {"administratie_id": str(bestaand.administratie_id)}
            bestaand.actief = False
            bestaand.gedeactiveerd_door = actor_id
            bestaand.gedeactiveerd_op = datetime.now(UTC)
        if soort == ToewijzingRegelSoort.AFZENDER:
            # Flip-detectie (02-09): een afzender die naar te veel verschillende administraties heeft
            # gewezen is meerduidig — géén nieuwe regel (en de oude is zojuist gedeactiveerd), wél audit.
            doelen = _historische_doelen(session, soort=soort, sleutel=sleutel) | {administratie_id}
            if len(doelen) >= AFZENDER_MEERDUIDIG_VANAF:
                # Het geweigerde doel wordt als INACTIEVE rij vastgelegd zodat de historie de
                # meerduidigheid blijft dragen (anders zou een latere toewijzing 'm weer leren).
                nu = datetime.now(UTC)
                spoor = ToewijzingRegel(
                    soort=soort.value,
                    sleutel=sleutel,
                    administratie_id=administratie_id,
                    aangemaakt_door=actor_id,
                    actief=False,
                    gedeactiveerd_door=actor_id,
                    gedeactiveerd_op=nu,
                )
                session.add(spoor)
                session.flush()
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="toewijzing_regel",
                    record_id=spoor.id,
                    actie="toewijzing_regel_meerduidig",
                    correlatie_id=uuid.uuid4(),
                    oude_waarde=oude_waarde,
                    nieuwe_waarde={
                        "soort": soort.value,
                        "sleutel": sleutel,
                        "geweigerd_doel": str(administratie_id),
                        "historische_doelen": sorted(str(d) for d in doelen),
                        "reden": "afzender is meerduidig — regel gedeactiveerd, wordt niet meer geleerd of gesuggereerd",
                    },
                    administratie_id=None,
                )
                continue
        regel = ToewijzingRegel(
            soort=soort.value,
            sleutel=sleutel,
            administratie_id=administratie_id,
            aangemaakt_door=actor_id,
        )
        session.add(regel)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="toewijzing_regel",
            record_id=regel.id,
            actie="toewijzing_regel_geleerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oude_waarde,
            nieuwe_waarde={"soort": soort.value, "sleutel": sleutel, "administratie_id": str(administratie_id)},
            # Platform-breed audit-feit (administratie_id=None): de regel zelf is intake-breed —
            # het doel staat in nieuwe_waarde. Zo werkt het leren ook vanuit een sessie zonder
            # (of met een andere) administratie-scope; audit_event-RLS eist anders scope=doel.
            administratie_id=None,
        )


def corrigeer_toewijzing_na_verplaatsing(
    session: Session,
    *,
    van_administratie_id: uuid.UUID,
    naar_administratie_id: uuid.UUID,
    actor_id: uuid.UUID,
    tenaamstelling: str | None,
    afzender: str | None,
) -> tuple[str, ...]:
    """Het toewijzings-geheugen leert mee terug bij "Verplaats naar andere administratie"
    (addendum kantoor-run 27-08 punt 5, besluit Peter): uitsluitend de actieve regel(s) op de
    sleutels van dít document die naar de OUDE administratie wijzen — de regel die de foute
    toewijzing veroorzaakte — worden gecorrigeerd naar de nieuwe (oude rij deactiveren + nieuwe rij,
    zelfde mechaniek als leer_toewijzing, mét audit). Wijst een sleutel al elders (of nergens)
    heen, dan blijft die met rust: een handmatige toewijzing zónder leer-regel = alleen verplaatsen.
    Geeft de gecorrigeerde soorten terug (voor tijdlijn + response)."""
    paren: list[tuple[ToewijzingRegelSoort, str]] = []
    tenaamstelling_sleutel = normaliseer_partijnaam(tenaamstelling) if tenaamstelling else ""
    if tenaamstelling_sleutel:
        paren.append((ToewijzingRegelSoort.TENAAMSTELLING, tenaamstelling_sleutel))
    afzender_sleutel = normaliseer_afzender(afzender)
    if afzender_sleutel:
        paren.append((ToewijzingRegelSoort.AFZENDER, afzender_sleutel))

    gecorrigeerd: list[str] = []
    for soort, sleutel in paren:
        bestaand = _actieve_regel(session, soort=soort, sleutel=sleutel)
        if bestaand is None or bestaand.administratie_id != van_administratie_id:
            continue
        bestaand.actief = False
        bestaand.gedeactiveerd_door = actor_id
        bestaand.gedeactiveerd_op = datetime.now(UTC)
        regel = ToewijzingRegel(
            soort=soort.value,
            sleutel=sleutel,
            administratie_id=naar_administratie_id,
            aangemaakt_door=actor_id,
        )
        session.add(regel)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="toewijzing_regel",
            record_id=regel.id,
            actie="toewijzing_regel_gecorrigeerd",
            correlatie_id=uuid.uuid4(),
            oude_waarde={"administratie_id": str(van_administratie_id), "regel_id": str(bestaand.id)},
            nieuwe_waarde={"soort": soort.value, "sleutel": sleutel, "administratie_id": str(naar_administratie_id)},
            administratie_id=None,  # platform-breed feit, zelfde reden als bij leer_toewijzing
        )
        gecorrigeerd.append(soort.value)
    return tuple(gecorrigeerd)


# ---- Data-nazorg afzender-geheugen (blok D 02-09) ------------------------------------------------------


@dataclass
class OpschoningTelling:
    """Uitkomst van `schoon_afzender_regels_op`: deterministisch, nooit verwijderen — regels worden
    gedeactiveerd mét audit. `details` = één regel per gedeactiveerde sleutel (voor de CLI-rapportage)."""

    sleutels_bekeken: int = 0
    gedeactiveerd: int = 0
    reden_uitgesloten_domein: int = 0
    reden_meerduidig: int = 0
    details: list[str] = field(default_factory=list)

    def als_dict(self) -> dict:
        return {
            "sleutels_bekeken": self.sleutels_bekeken,
            "gedeactiveerd": self.gedeactiveerd,
            "reden_uitgesloten_domein": self.reden_uitgesloten_domein,
            "reden_meerduidig": self.reden_meerduidig,
        }


def schoon_afzender_regels_op(session: Session, *, actor_id: uuid.UUID, dry_run: bool = False) -> OpschoningTelling:
    """Bestaande afzender-regels die de sinds 02-09 geldende begrenzingen al overschrijden alsnog
    deactiveren (mét audit `toewijzing_regel_opgeschoond`), zodat het geheugen niet blijft suggereren
    wat het nu niet meer zou leren: (a) sleutels op een config-uitgesloten kantoor-/doorstuurdomein
    (`intake_afzender_uitgesloten_domeinen`), (b) sleutels die in hun historie (actief + gedeactiveerd) al
    naar ≥ AFZENDER_MEERDUIDIG_VANAF verschillende administraties wezen (admin@kempenrecreatie.nl: 12
    versies, 6 doelen). Tenaamstelling-regels worden nooit geraakt. Idempotent: een tweede run vindt
    niets meer. `dry_run` telt en rapporteert alleen."""
    telling = OpschoningTelling()
    regels = session.scalars(
        select(ToewijzingRegel)
        .where(ToewijzingRegel.soort == ToewijzingRegelSoort.AFZENDER.value)
        .order_by(ToewijzingRegel.sleutel, ToewijzingRegel.aangemaakt_op)
    ).all()
    per_sleutel: dict[str, list[ToewijzingRegel]] = {}
    for regel in regels:
        per_sleutel.setdefault(regel.sleutel, []).append(regel)
    telling.sleutels_bekeken = len(per_sleutel)
    nu = datetime.now(UTC)
    for sleutel, rijen in sorted(per_sleutel.items()):
        actief = [r for r in rijen if r.actief]
        if not actief:
            continue
        doelen = {r.administratie_id for r in rijen}
        redenen: list[str] = []
        if afzender_uitgesloten(sleutel):
            redenen.append("uitgesloten_domein")
        if len(doelen) >= AFZENDER_MEERDUIDIG_VANAF:
            redenen.append("meerduidig")
        if not redenen:
            continue
        telling.gedeactiveerd += len(actief)
        if "uitgesloten_domein" in redenen:
            telling.reden_uitgesloten_domein += len(actief)
        if "meerduidig" in redenen:
            telling.reden_meerduidig += len(actief)
        telling.details.append(
            f"{sleutel}: {len(actief)} actieve regel(s) gedeactiveerd — {' + '.join(redenen)} "
            f"({len(rijen)} versies, {len(doelen)} doelen)"
        )
        if dry_run:
            continue
        for regel in actief:
            regel.actief = False
            regel.gedeactiveerd_door = actor_id
            regel.gedeactiveerd_op = nu
            session.flush()
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="toewijzing_regel",
                record_id=regel.id,
                actie="toewijzing_regel_opgeschoond",
                correlatie_id=uuid.uuid4(),
                oude_waarde={"actief": True, "administratie_id": str(regel.administratie_id)},
                nieuwe_waarde={
                    "actief": False,
                    "soort": regel.soort,
                    "sleutel": sleutel,
                    "redenen": redenen,
                    "historische_doelen": sorted(str(d) for d in doelen),
                    "versies": len(rijen),
                    "reden": (
                        "data-nazorg 02-09: afzender-regel op uitgesloten domein en/of meerduidig — "
                        "gedeactiveerd, niet verwijderd"
                    ),
                },
                administratie_id=None,
            )
    return telling
