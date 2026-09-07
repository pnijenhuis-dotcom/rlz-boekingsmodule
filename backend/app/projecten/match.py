"""Deterministische project-matching op gelezen documenttekst — gedeelde motor (blok 10, 07-09).

Tot 07-09 leefde `match_project` in `app/extractie/verplichting.py` (offerte → project). De inkoopfactuur
krijgt sinds blok 10 hetzelfde nodig (casus Spot Services: óns projectnummer staat op de factuur), dus de
motor woont hier en beide importeren 'm. Nooit AI: de AI leest de tekst voor (`proj`), déze code matcht
tegen de eigen project-cache en het leverancier-werknummer-geheugen.

Twee ingangen:

- `match_project(tekst, kandidaten)` — de bestaande offerte-motor (gedrag ONGEWIJZIGD: nummer-prefix →
  naam-bevat → fuzzy ≥ 0,85; meerduidig = geen suggestie).
- `bepaal_project_uit_factuur(tekst, kandidaten, werknummers)` — de factuur-motor mét de match-VOLGORDE uit
  de opdracht 07-09:
    1. exacte projectcode (genormaliseerd: hoofdletters/spaties/leestekens weg) → GROEN;
    2. leverancier-werknummer-mapping (`leverancier_werknummer`) → groen als de mapping bevestigd is
       (`app_bevestigd`-patroon, CLAUDE.md "Boekingsgeheugen"), anders oranje;
    3. plaats-/opdrachtgever-fuzzy op de projectnaam → ALTIJD oranje; het OVH-project nooit via fuzzy
       (overhead wordt bewust gekozen, nooit geraden — CLAUDE.md "Projecten").
  Meerduidig op een niveau (meerdere kandidaten) = NIETS invullen; de kandidaten reizen mee in de
  uitkomst zodat het controlescherm ze kan tonen ("nooit auto-toewijzen bij twijfel").

Alleen ACTIEVE projecten van de administratie zijn kandidaat (de lader filtert `is_actief`/`verdwenen`).
"""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from datetime import UTC, datetime
from difflib import SequenceMatcher

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db.audit import record_audit_event
from app.projecten.models import LeverancierWerknummer
from app.projectverdeling.omzet import is_ovh_project
from app.sync.models import ProjectCache

logger = logging.getLogger(__name__)

#: Match-niveaus van de factuur-motor (ook de `project_bron`-detailtekst in de UI leest ze).
NIVEAU_CODE = "code"
NIVEAU_WERKNUMMER = "werknummer"
NIVEAU_FUZZY = "fuzzy"

#: Herkomst-waarden voor `BoekvoorstelRegelData.prefill_herkomst["project"]` / DTO `project_bron`.
HERKOMST_FACTUUR = "factuur"  # groen: exacte code of bevestigde werknummer-mapping
HERKOMST_FACTUUR_ONBEVESTIGD = "factuur_onbevestigd"  # oranje: onbevestigde mapping of fuzzy
HERKOMST_FACTUUR_MEERDUIDIG = "factuur_meerduidig"  # niets ingevuld: meerdere kandidaten

#: `leverancier_werknummer.bron` voor mappings die uit een geboekte factuur geleerd zijn.
WERKNUMMER_BRON_FACTUUR = "factuur"


@dataclass(frozen=True)
class ProjectKandidaat:
    """Actief project uit de project-cache — de deterministische match-basis (nooit AI)."""

    id: uuid.UUID
    naam: str


@dataclass(frozen=True)
class WerknummerKoppeling:
    """Eén rij uit `leverancier_werknummer` voor de leverancier van het document."""

    werknummer: str
    project_id: uuid.UUID
    bevestigd: bool


@dataclass(frozen=True)
class ProjectMatch:
    """Uitkomst van de factuur-motor. `project_id` None = niets invullen; `meerduidig` draagt dan de
    kandidaten van het niveau waarop het misging (leeg = simpelweg geen match)."""

    gelezen: str | None
    project_id: uuid.UUID | None = None
    project_naam: str | None = None
    niveau: str | None = None
    bevestigd: bool = False
    meerduidig: tuple[ProjectKandidaat, ...] = field(default_factory=tuple)

    @property
    def herkomst(self) -> str | None:
        if self.project_id is not None:
            return HERKOMST_FACTUUR if self.bevestigd else HERKOMST_FACTUUR_ONBEVESTIGD
        if self.meerduidig:
            return HERKOMST_FACTUUR_MEERDUIDIG
        return None

    @property
    def detail(self) -> str | None:
        """Tooltip-/checkdetail-tekst voor het controlescherm (leesbaar, geen id's)."""
        if self.gelezen is None:
            return None
        if self.project_id is not None:
            if self.niveau == NIVEAU_CODE:
                return f'Factuur vermeldt "{self.gelezen}" = projectcode van {self.project_naam}'
            if self.niveau == NIVEAU_WERKNUMMER:
                stand = "bevestigd" if self.bevestigd else "nog niet bevestigd — boeken bevestigt 'm"
                return f'Werknummer "{self.gelezen}" van deze leverancier hoort bij {self.project_naam} ({stand})'
            return f'Factuur vermeldt "{self.gelezen}" — lijkt op {self.project_naam}; controleer en bevestig'
        if self.meerduidig:
            namen = ", ".join(k.naam for k in self.meerduidig)
            return f'Factuur vermeldt "{self.gelezen}" — meerdere projecten passen: {namen}. Kies zelf.'
        return None


_NIET_ALFANUMERIEK = re.compile(r"[^0-9a-z]+")
# Projectcode = het eerste nummer-token van de projectnaam (naamconventie "26127 Tilburg (Heijmans)"; Odoo
# levert "[26127] Tilburg (Heijmans)" — haken tellen niet mee).
_NUMMER_PREFIX = re.compile(r"^\s*[\[\(]?\s*([0-9][0-9A-Za-z\-]*)")


def normaliseer_projectcode(tekst: str | None) -> str:
    """Case-, spatie- en leestekenongevoelig: "26-140 " == "26140" == "[26140]"."""
    return _NIET_ALFANUMERIEK.sub("", (tekst or "").lower())


def projectcode_van(naam: str | None) -> str | None:
    """Genormaliseerde projectcode uit een projectnaam, of None als de naam niet met een nummer begint."""
    m = _NUMMER_PREFIX.match(naam or "")
    return normaliseer_projectcode(m.group(1)) if m is not None else None


def _tokens(tekst: str) -> set[str]:
    """Genormaliseerde woord-tokens van de gelezen tekst ("Project 26140 / Koningstraat" → {"project",
    "26140", "koningstraat"}) — zodat "Werk 26140" de code 26140 draagt zonder dat "2614" of "261400" matcht."""
    return {t for t in (normaliseer_projectcode(deel) for deel in re.split(r"[\s/,;:|]+", tekst)) if t}


def _uniek_of_meerduidig(
    gelezen: str, treffers: list[ProjectKandidaat], *, niveau: str, bevestigd: bool
) -> ProjectMatch | None:
    """Precies één treffer = match; meerdere = meerduidig (nooit invullen); nul = None (volgende niveau)."""
    uniek = {k.id: k for k in treffers}
    if len(uniek) == 1:
        k = next(iter(uniek.values()))
        return ProjectMatch(gelezen=gelezen, project_id=k.id, project_naam=k.naam, niveau=niveau, bevestigd=bevestigd)
    if len(uniek) > 1:
        return ProjectMatch(gelezen=gelezen, meerduidig=tuple(sorted(uniek.values(), key=lambda k: k.naam)))
    return None


def bepaal_project_uit_factuur(
    project_tekst: str | None,
    kandidaten: list[ProjectKandidaat],
    werknummers: list[WerknummerKoppeling] | None = None,
) -> ProjectMatch:
    """Factuur-motor met de vaste volgorde code → werknummer → fuzzy (zie module-docstring)."""
    gelezen = " ".join((project_tekst or "").split()) or None
    if gelezen is None or not kandidaten:
        return ProjectMatch(gelezen=gelezen)
    actieve_ids = {k.id for k in kandidaten}
    doel = normaliseer_projectcode(gelezen)
    if not doel:
        return ProjectMatch(gelezen=gelezen)

    # 1. Exacte projectcode: de hele tekst is de code, óf de code staat als los token in de tekst
    #    ("Project 26140"), óf de tekst is exact de hele projectnaam.
    tokens = _tokens(gelezen)
    op_code = [
        k
        for k in kandidaten
        if (code := projectcode_van(k.naam))
        and (code == doel or code in tokens)
        or normaliseer_projectcode(k.naam) == doel
    ]
    uitkomst = _uniek_of_meerduidig(gelezen, op_code, niveau=NIVEAU_CODE, bevestigd=True)
    if uitkomst is not None:
        return uitkomst

    # 2. Leverancier-werknummer-mapping (alleen naar actieve projecten; genormaliseerde vergelijking).
    per_naam = {k.id: k for k in kandidaten}
    treffers = [
        w for w in (werknummers or []) if normaliseer_projectcode(w.werknummer) == doel and w.project_id in actieve_ids
    ]
    if treffers:
        uitkomst = _uniek_of_meerduidig(
            gelezen,
            [per_naam[w.project_id] for w in treffers],
            niveau=NIVEAU_WERKNUMMER,
            bevestigd=all(w.bevestigd for w in treffers),
        )
        if uitkomst is not None:
            return uitkomst

    # 3. Fuzzy op plaats/opdrachtgever in de projectnaam — altijd oranje, OVH nooit. Een puur NUMERIEKE tekst die
    #    op niveau 1 en 2 niets opleverde is een onbekend nummer, geen plaatsnaam: nooit fuzzy ("2614" ≠ 26140).
    if doel.isdigit():
        return ProjectMatch(gelezen=gelezen)
    fuzzy_kandidaten = [k for k in kandidaten if k.naam and not is_ovh_project(k.naam)]
    fuzzy_id, _match, fuzzy_naam = _match_op_naam(doel, fuzzy_kandidaten)
    if fuzzy_id is not None:
        return ProjectMatch(
            gelezen=gelezen, project_id=fuzzy_id, project_naam=fuzzy_naam, niveau=NIVEAU_FUZZY, bevestigd=False
        )
    op_naam = _naam_bevat(doel, fuzzy_kandidaten)
    if len({k.id for k in op_naam}) > 1:
        uniek = {k.id: k for k in op_naam}
        return ProjectMatch(gelezen=gelezen, meerduidig=tuple(sorted(uniek.values(), key=lambda k: k.naam)))
    return ProjectMatch(gelezen=gelezen)


def _naam_bevat(doel: str, kandidaten: list[ProjectKandidaat]) -> list[ProjectKandidaat]:
    if len(doel) < 4:
        return []
    return [k for k in kandidaten if (n := normaliseer_projectcode(k.naam)) and (doel in n or n in doel)]


def _match_op_naam(doel: str, kandidaten: list[ProjectKandidaat]) -> tuple[uuid.UUID | None, str | None, str | None]:
    """Naam-bevat (genormaliseerd, beide richtingen) → fuzzy ≥ 0,85 met één uniek beste resultaat —
    de bestaande offerte-logica, gedeeld door beide ingangen."""
    if len(doel) < 4:
        return None, None, None
    op_naam = _naam_bevat(doel, kandidaten)
    if len(op_naam) == 1:
        return op_naam[0].id, "naam", op_naam[0].naam
    if op_naam:
        return None, None, None
    scores = sorted(
        ((SequenceMatcher(None, doel, normaliseer_projectcode(k.naam)).ratio(), k) for k in kandidaten if k.naam),
        key=lambda item: item[0],
        reverse=True,
    )
    if not scores or scores[0][0] < 0.85:
        return None, None, None
    besten = [k for score, k in scores if scores[0][0] - score < 0.02]
    if len(besten) != 1:
        return None, None, None
    return besten[0].id, "naam", besten[0].naam


def match_project(
    project_tekst: str | None, kandidaten: list[ProjectKandidaat]
) -> tuple[uuid.UUID | None, str | None, str | None]:
    """Offerte-motor (verplichting, 04-09 — gedrag ongewijzigd): (project_id, match, naam) of (None, None, None).

    Volgorde: nummer-prefix exact (de naamconventie van de klant is "26127 Tilburg (Heijmans)" — het eerste
    token is het projectnummer) → naam-bevat (genormaliseerd, in één van beide richtingen) → fuzzy → geen
    suggestie. Bij méér dan één plausibele kandidaat géén suggestie ("nooit auto-toewijzen bij twijfel")."""
    if not project_tekst or not kandidaten:
        return None, None, None
    gelezen_nummer = _NUMMER_PREFIX.match(project_tekst)
    if gelezen_nummer is not None:
        doel = normaliseer_projectcode(gelezen_nummer.group(1))
        op_nummer = [k for k in kandidaten if projectcode_van(k.naam) == doel]
        if len(op_nummer) == 1:
            return op_nummer[0].id, "nummer", op_nummer[0].naam
        if len(op_nummer) > 1:
            return None, None, None
    return _match_op_naam(normaliseer_projectcode(project_tekst), kandidaten)


# --- laders + leerlus (DB) -------------------------------------------------------------------------------


def laad_projectkandidaten(session: Session, *, administratie_id: uuid.UUID) -> list[ProjectKandidaat]:
    """Alle ACTIEVE, niet-verdwenen projecten van de administratie (zelfde filter als de offerte-route)."""
    return [
        ProjectKandidaat(id=rij.id, naam=rij.naam or "")
        for rij in session.scalars(
            select(ProjectCache).where(
                ProjectCache.administratie_id == administratie_id,
                ProjectCache.verdwenen_uit_bron_op.is_(None),
                ProjectCache.is_actief.isnot(False),
            )
        )
        if rij.naam
    ]


def laad_werknummers(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID
) -> list[WerknummerKoppeling]:
    return [
        WerknummerKoppeling(werknummer=rij.werknummer, project_id=rij.project_id, bevestigd=rij.bevestigd)
        for rij in session.scalars(
            select(LeverancierWerknummer).where(
                LeverancierWerknummer.administratie_id == administratie_id,
                LeverancierWerknummer.vendor_id == vendor_id,
            )
        )
    ]


def leer_werknummers_uit_boeking(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vendor_id: uuid.UUID,
    actor_id: uuid.UUID,
    regel_projecten: list[tuple[uuid.UUID | None, str | None]],
    kandidaten: list[ProjectKandidaat] | None = None,
) -> int:
    """Leerlus (in de GEBOEKT-transactie, náást `leg_boeking_vast`): élke geboekte regel mét project én een op
    de factuur gelezen projecttekst legt de (leverancier, tekst) → project-mapping vast in
    `leverancier_werknummer` (bron 'factuur', bevestigd — boeken ís de menselijke bevestiging). Bestaat de
    mapping al met hetzelfde project: alleen bevestigen. Wijst ze naar een ánder project: de mens wint — de
    mapping wordt herschreven (audit oud→nieuw). Een tekst die exact de eigen projectcode van het gekozen
    project is, wordt niet als werknummer onthouden (die is al groen via niveau 1). Retourneert het aantal
    geschreven/gewijzigde rijen.

    `regel_projecten` = per geboekte regel (project_id, gelezen tekst) — de aanroeper bepaalt de tekst
    (regel-`proj`, anders kop-`proj`)."""
    if kandidaten is None:
        kandidaten = laad_projectkandidaten(session, administratie_id=administratie_id)
    code_per_project = {k.id: projectcode_van(k.naam) for k in kandidaten}
    bestaande = list(
        session.scalars(
            select(LeverancierWerknummer).where(
                LeverancierWerknummer.administratie_id == administratie_id,
                LeverancierWerknummer.vendor_id == vendor_id,
            )
        )
    )
    per_norm: dict[str, LeverancierWerknummer] = {normaliseer_projectcode(r.werknummer): r for r in bestaande}
    nu = datetime.now(UTC)
    geschreven = 0
    gezien: set[str] = set()
    for project_id, tekst in regel_projecten:
        schoon = " ".join((tekst or "").split())
        norm = normaliseer_projectcode(schoon)
        if project_id is None or not norm or norm in gezien or project_id not in code_per_project:
            continue
        gezien.add(norm)
        if (
            code_per_project.get(project_id) == norm
            or normaliseer_projectcode(next((k.naam for k in kandidaten if k.id == project_id), None)) == norm
        ):
            continue  # eigen projectcode/-naam: niveau 1 dekt dit al
        rij = per_norm.get(norm)
        if rij is None:
            rij = LeverancierWerknummer(
                administratie_id=administratie_id,
                project_id=project_id,
                vendor_id=vendor_id,
                werknummer=schoon,
                bron=WERKNUMMER_BRON_FACTUUR,
                bevestigd=True,
                aangemaakt_door=actor_id,
                bevestigd_door=actor_id,
                bevestigd_op=nu,
            )
            session.add(rij)
            session.flush()
            per_norm[norm] = rij
            record_audit_event(
                session,
                actor_id=actor_id,
                module="boekhouding",
                tabel="leverancier_werknummer",
                record_id=rij.id,
                actie="werknummer_geleerd_uit_factuur",
                correlatie_id=document_id,
                nieuwe_waarde={"vendor_id": str(vendor_id), "werknummer": schoon, "project_id": str(project_id)},
                administratie_id=administratie_id,
            )
            geschreven += 1
            continue
        if rij.project_id == project_id and rij.bevestigd:
            continue
        oud = {"project_id": str(rij.project_id), "bevestigd": rij.bevestigd}
        rij.project_id = project_id
        rij.bevestigd = True
        rij.bevestigd_door = actor_id
        rij.bevestigd_op = nu
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_werknummer",
            record_id=rij.id,
            actie="werknummer_bevestigd_uit_factuur",
            correlatie_id=document_id,
            oude_waarde=oud,
            nieuwe_waarde={"project_id": str(project_id), "bevestigd": True, "werknummer": rij.werknummer},
            administratie_id=administratie_id,
        )
        geschreven += 1
    return geschreven
