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
    3. plaats + opdrachtgever in de projectnaam — DETERMINISTISCH sinds run D 02-10 (blok B, casussen Huvanco/
       Hoogwerkservice 29-09; herziet de SequenceMatcher-fuzzy van 07-09): een plaats-token én een opdrachtgever-
       token van de projectnaam ("26127 Tilburg (Heijmans)": plaats = de woorden buiten de haken ná het nummer,
       opdrachtgever = de woorden tussen de haken) moeten BEIDE genormaliseerd in de gelezen factuurtekst staan;
       precies één kandidaat → ORANJE voorstel (`factuur_plaats_opdrachtgever`, chip "op plaats + opdrachtgever");
       meerdere → niets + de kandidaten in het scherm; alleen plaats óf alleen opdrachtgever → niets. Het OVH-project
       nooit via niveau 3 (overhead wordt bewust gekozen, nooit geraden — CLAUDE.md "Projecten"). Niveau 3 loopt
       uitsluitend op DOCUMENT-niveau (één project per document) — nooit per regel.
  Meerduidig op een niveau (meerdere kandidaten) = NIETS invullen; de kandidaten reizen mee in de
  uitkomst zodat het controlescherm ze kan tonen ("nooit auto-toewijzen bij twijfel").

Sinds run D 02-10 leest de factuur-motor de VOLLEDIGE tekst (kop-`proj`, `betreft`, UBL-`cbc:Note`,
regelomschrijvingen): `bepaal_werknummer_in_tekst` vindt een leverancier-werknummer als los token in élke gelezen
tekst (niveau 2 ongewijzigd in betekenis — bevestigd groen, onbevestigd oranje), `bepaal_project_uit_tekst` de
klant-loze code (25-09) en `bepaal_project_op_plaats_opdrachtgever` niveau 3 over kop + regels samen.

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
NIVEAU_FUZZY = "fuzzy"  # historisch (07-09 → 02-10); de factuur-motor levert dit niveau niet meer
NIVEAU_PLAATS_OPDRACHTGEVER = "plaats_opdrachtgever"  # run D 02-10 blok B: deterministisch niveau 3

#: Herkomst-waarden voor `BoekvoorstelRegelData.prefill_herkomst["project"]` / DTO `project_bron`.
HERKOMST_FACTUUR = "factuur"  # groen: exacte code of bevestigde werknummer-mapping
HERKOMST_FACTUUR_ONBEVESTIGD = "factuur_onbevestigd"  # oranje: onbevestigde mapping of fuzzy
HERKOMST_FACTUUR_MEERDUIDIG = "factuur_meerduidig"  # niets ingevuld: meerdere kandidaten
HERKOMST_FACTUUR_PLAATS_OPDRACHTGEVER = "factuur_plaats_opdrachtgever"  # oranje: niveau 3 (run D 02-10 blok B)
#: Oranje project-herkomsten — een mens bevestigt; het autoboek-pad boekt er NOOIT automatisch op (blok B 02-10).
ORANJE_PROJECT_HERKOMSTEN = frozenset({HERKOMST_FACTUUR_ONBEVESTIGD, HERKOMST_FACTUUR_PLAATS_OPDRACHTGEVER})

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
            if self.niveau == NIVEAU_PLAATS_OPDRACHTGEVER:
                return HERKOMST_FACTUUR_PLAATS_OPDRACHTGEVER
            return HERKOMST_FACTUUR if self.bevestigd else HERKOMST_FACTUUR_ONBEVESTIGD
        if self.meerduidig:
            return HERKOMST_FACTUUR_MEERDUIDIG
        return None

    @property
    def kandidaten(self) -> list[dict[str, str]] | None:
        """Meerduidig → de kandidaten als DTO-rijtjes ({id, naam}) voor het controlescherm ("kandidaten in het
        scherm", blok B 02-10); anders None."""
        if not self.meerduidig:
            return None
        return [{"id": str(k.id), "naam": k.naam} for k in self.meerduidig]

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
            if self.niveau == NIVEAU_PLAATS_OPDRACHTGEVER:
                return (
                    f"Factuur noemt plaats + opdrachtgever {self.gelezen} — past op {self.project_naam}; "
                    "controleer en bevestig (voorstel, geen projectnummer op de factuur)"
                )
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
    *,
    niveau3: bool = True,
) -> ProjectMatch:
    """Factuur-motor met de vaste volgorde code → werknummer → plaats + opdrachtgever (zie module-docstring).
    `niveau3=False` (prefill per REGEL, blok B 02-10): alleen niveau 1–2 — plaats/opdrachtgever loopt uitsluitend op
    document-niveau (`bepaal_project_op_plaats_opdrachtgever`), nooit per regel."""
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

    # 3. Plaats + opdrachtgever in de projectnaam — deterministisch (run D 02-10 blok B), altijd oranje, OVH nooit.
    #    Een puur NUMERIEKE tekst die op niveau 1 en 2 niets opleverde is een onbekend nummer, geen plaatsnaam
    #    ("2614" ≠ 26140). De SequenceMatcher-fuzzy van 07-09 is vervallen: "lijkt op" raadde (Hoogwerkservice 29-09
    #    kreeg per regel een ander project).
    if not niveau3 or doel.isdigit():
        return ProjectMatch(gelezen=gelezen)
    uitkomst = bepaal_project_op_plaats_opdrachtgever(kandidaten, gelezen)
    return uitkomst if uitkomst.herkomst is not None else ProjectMatch(gelezen=gelezen)


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


# --- blok 3 feedbackrun A 25-09 (FV-02): klant-loze projectcode-herkenning op het formaat van de administratie ----

#: `project_bron`-waarden van de bronvolgorde 25-09 (naast HERKOMST_FACTUUR/_ONBEVESTIGD/_MEERDUIDIG hierboven).
HERKOMST_GEHEUGEN = "geheugen"  # NIET gevuld (punt 4 02-10): de historie wijst naar een project — alleen herkomst-info
HERKOMST_FACTUUR_CONFLICT = "factuur_conflict"  # niets ingevuld: de factuur noemt een ánder nummer dan het geheugen
HERKOMST_GEHEUGEN_AFGESLOTEN = "geheugen_afgesloten"  # niets ingevuld: de historie wijst naar een afgesloten project

# Losse cijfer-tokens in factuurtekst ("Werk 26140", "proj. 105 / Koningstraat"); een token mét letters is geen code.
_CIJFER_TOKEN = re.compile(r"(?<![0-9A-Za-z])(?<![0-9][.,\-/])([0-9]{3,6})(?![.,\-/][0-9])(?![0-9A-Za-z])")


@dataclass(frozen=True)
class ProjectcodeFormaat:
    """Het projectnummer-formaat van één administratie, DETERMINISTISCH afgeleid uit de projectcache (nooit
    hardcoded per klant, nooit vrije tekst): per nummerlengte de set voorvoegsels van twee cijfers die voorkomen
    (jaargebonden "JJnnn": 25xxx/26xxx) — een 3-cijferig nummer (legacy 100–189) kent alleen zijn lengte. Een
    token past als de lengte voorkomt én (bij ≥ 5 cijfers) het voorvoegsel in de cache bestaat; zo is "2026" of
    een bedrag "1.150" nooit een projectnummer. `codes` = álle cijfer-prefixen (actief én afgesloten) → id."""

    lengtes: frozenset[int]
    jaar_prefixen: frozenset[str]
    codes: dict[str, tuple[uuid.UUID, ...]]

    @classmethod
    def uit_kandidaten(cls, kandidaten: list[ProjectKandidaat]) -> ProjectcodeFormaat:
        from app.projecten.nummer import cijfer_prefix

        lengtes: set[int] = set()
        prefixen: set[str] = set()
        codes: dict[str, list[uuid.UUID]] = {}
        for k in kandidaten:
            code = cijfer_prefix(k.naam)
            if not code or not code.isdigit():
                continue
            lengtes.add(len(code))
            if len(code) >= 5:
                prefixen.add(code[:2])
            codes.setdefault(code, []).append(k.id)
        return cls(
            lengtes=frozenset(lengtes),
            jaar_prefixen=frozenset(prefixen),
            codes={c: tuple(ids) for c, ids in codes.items()},
        )

    @property
    def leeg(self) -> bool:
        return not self.lengtes

    def past(self, token: str) -> bool:
        if not token.isdigit() or len(token) not in self.lengtes:
            return False
        return len(token) < 5 or token[:2] in self.jaar_prefixen

    def nummers_in(self, *teksten: str | None) -> tuple[str, ...]:
        """Alle cijfer-tokens in de teksten die het formaat van de administratie hebben — in leesvolgorde, uniek."""
        uit: list[str] = []
        for tekst in teksten:
            for m in _CIJFER_TOKEN.finditer(tekst or ""):
                token = m.group(1)
                if self.past(token) and token not in uit:
                    uit.append(token)
        return tuple(uit)


def bepaal_project_uit_tekst(
    formaat: ProjectcodeFormaat, kandidaten: list[ProjectKandidaat], *teksten: str | None
) -> ProjectMatch:
    """Bronvolgorde-stap (2) 25-09: een nummer in de gelezen factuurtekst (regeltekst, kop, cbc:Note) dat exact de
    cijfer-prefix van een project is. Alleen tokens in het administratie-formaat tellen; precies één project =
    groen niveau `code` (ook een AFGESLOTEN project — de factuur verwijst er dan expliciet naar, het oranje signaal
    `check_project_afgesloten` blijft); meerdere nummers/projecten = meerduidig (niets invullen, chip + keuze);
    niets = leeg voorstel (volgende stap: geheugen)."""
    nummers = formaat.nummers_in(*teksten)
    if not nummers:
        return ProjectMatch(gelezen=None)
    gelezen = ", ".join(nummers)
    per_id = {k.id: k for k in kandidaten}
    treffers: list[ProjectKandidaat] = []
    for nummer in nummers:
        for pid in formaat.codes.get(nummer, ()):
            if pid in per_id:
                treffers.append(per_id[pid])
    uitkomst = _uniek_of_meerduidig(gelezen, treffers, niveau=NIVEAU_CODE, bevestigd=True)
    return uitkomst if uitkomst is not None else ProjectMatch(gelezen=gelezen)


def factuur_noemt_ander_project(
    formaat: ProjectcodeFormaat, geheugen_project_id: uuid.UUID | None, *teksten: str | None
) -> str | None:
    """Conflict-toets (25-09): noemt de factuur een nummer in het administratie-formaat dat NIET de code van het
    geheugen-project is, dan mag het geheugen niet stil invullen. Geeft het/de genoemde nummer(s) terug, anders None."""
    if geheugen_project_id is None or formaat.leeg:
        return None
    nummers = formaat.nummers_in(*teksten)
    if not nummers:
        return None
    eigen = {code for code, ids in formaat.codes.items() if geheugen_project_id in ids}
    anders = [n for n in nummers if n not in eigen]
    return ", ".join(anders) if anders else None


# --- run D 02-10 blok B: werknummer in de volledige tekst + deterministisch niveau 3 (plaats + opdrachtgever) ----

_WOORD = re.compile(r"[^\W\d_]{3,}", re.UNICODE)
#: Woorden die in projectnamen staan maar niets over plaats of opdrachtgever zeggen (nooit een match-token).
_STOPWOORDEN = frozenset(
    {
        "afgesloten",
        "project",
        "werk",
        "fase",
        "bouw",
        "nieuwbouw",
        "renovatie",
        "woningen",
        "woning",
        "appartementen",
        "holding",
        "groep",
        "beheer",
        "vastgoed",
        "steigerbouw",
        "steiger",
        "steigers",
        "diensten",
        "service",
        "services",
        "overhead",
        "intern",
        "algemene",
        "kosten",
        # functiewoorden/afkortingen (≥ 3 letters) die nooit een plaats of opdrachtgever aanwijzen
        "van",
        "der",
        "den",
        "het",
        "een",
        "bij",
        "aan",
        "met",
        "voor",
        "per",
        "btw",
        "excl",
        "incl",
        "vof",
        "the",
        "and",
        "via",
        "uur",
        "stuk",
        "stuks",
        "prijs",
        "totaal",
        "week",
        "weken",
        "huur",
        "levering",
        "transport",
        "montage",
        "demontage",
        "factuur",
        "betreft",
        "referentie",
        "opdracht",
        "opdrachtgever",
        "plaats",
    }
)


def _woord_tokens(tekst: str | None) -> frozenset[str]:
    """Genormaliseerde woord-tokens (≥ 3 letters, accenten weg, kleine letters, functiewoorden eruit) —
    cijfers/bedragen/datums tellen nooit."""
    if not tekst:
        return frozenset()
    import unicodedata

    plat = unicodedata.normalize("NFKD", tekst)
    plat = "".join(ch for ch in plat if not unicodedata.combining(ch)).lower()
    return frozenset(t for t in _WOORD.findall(plat) if t not in _STOPWOORDEN)


_HAAKJES = re.compile(r"[\(\[]([^\)\]]*)[\)\]]")


def plaats_opdrachtgever_tokens(naam: str | None) -> tuple[frozenset[str], frozenset[str]]:
    """Projectnaam → (plaats-tokens, opdrachtgever-tokens) volgens de naamconventie "26127 Tilburg (Heijmans)" /
    "Afgesloten 25170 Hoogvliet, Troubadourlaan (Weboma)" / Odoo "[26133] Eindhoven (BAM)": opdrachtgever = de woorden
    tussen de laatste haken, plaats = de woorden daarbuiten (het nummer en "Afgesloten" tellen niet). Zonder haken is er
    geen opdrachtgever → zo'n project kan op niveau 3 nooit matchen (nooit raden)."""
    if not naam:
        return frozenset(), frozenset()
    from app.projecten.nummer import zonder_afgesloten_voorvoegsel

    kaal = zonder_afgesloten_voorvoegsel(naam) or naam
    kaal = _NUMMER_PREFIX.sub("", kaal, count=1)
    binnen = _HAAKJES.findall(kaal)
    # Een leidende "[26133]"-Odoo-haak is al door het nummer-prefix weggenomen; de láátste haak is de opdrachtgever.
    opdrachtgever = _woord_tokens(binnen[-1]) if binnen else frozenset()
    buiten = _HAAKJES.sub(" ", kaal)
    return _woord_tokens(buiten), opdrachtgever


def bepaal_project_op_plaats_opdrachtgever(kandidaten: list[ProjectKandidaat], *teksten: str | None) -> ProjectMatch:
    """Niveau 3 (run D 02-10 blok B), deterministisch: een plaats-token ÉN een opdrachtgever-token van de projectnaam
    staan BEIDE in de gelezen tekst (kop-`proj`, `betreft`, `cbc:Note`, regelomschrijvingen — samen, document-niveau).
    Precies één kandidaat → ORANJE voorstel; meerdere → meerduidig (niets invullen, kandidaten mee); alleen plaats óf
    alleen opdrachtgever → niets. OVH nooit. Casus Hoogwerkservice 29-09: "500zzp - walterpark - hoogvliet / Weboma /
    Troubadourlaan Hoogvliet" → "25170 Hoogvliet, Troubadourlaan (Weboma)" (plaats hoogvliet/troubadourlaan +
    opdrachtgever weboma); "25013 Deurne (…)" nooit."""
    tokens: set[str] = set()
    for tekst in teksten:
        tokens |= _woord_tokens(tekst)
    if not tokens or not kandidaten:
        return ProjectMatch(gelezen=None)
    treffers: list[tuple[ProjectKandidaat, str, str]] = []
    for k in kandidaten:
        if not k.naam or is_ovh_project(k.naam):
            continue
        plaats, opdrachtgever = plaats_opdrachtgever_tokens(k.naam)
        plaats_hit = sorted(plaats & tokens)
        opdr_hit = sorted(opdrachtgever & tokens)
        if plaats_hit and opdr_hit:
            treffers.append((k, plaats_hit[0], opdr_hit[0]))
    if not treffers:
        return ProjectMatch(gelezen=None)
    uniek = {k.id: (k, p, o) for k, p, o in treffers}
    if len(uniek) == 1:
        k, p, o = next(iter(uniek.values()))
        return ProjectMatch(
            gelezen=f'"{p}" + "{o}"',
            project_id=k.id,
            project_naam=k.naam,
            niveau=NIVEAU_PLAATS_OPDRACHTGEVER,
            bevestigd=False,
        )
    gelezen = ", ".join(sorted({f'"{p}" + "{o}"' for _k, p, o in uniek.values()}))
    return ProjectMatch(
        gelezen=gelezen, meerduidig=tuple(sorted((k for k, _p, _o in uniek.values()), key=lambda k: k.naam))
    )


def bepaal_werknummer_in_tekst(
    kandidaten: list[ProjectKandidaat], werknummers: list[WerknummerKoppeling] | None, *teksten: str | None
) -> ProjectMatch:
    """Niveau 2 over de volledige factuurtekst (run D 02-10 blok B — Huvanco: het werknummer stond niet in `proj`
    maar in de omschrijving/betreft-regel): een leverancier-werknummer dat als LOS TOKEN (genormaliseerd;
    "Werk 4711-B" = "werk4711b") in een van de teksten staat. Betekenis ongewijzigd: bevestigd = groen, onbevestigd =
    oranje, twee werknummers naar verschillende projecten = meerduidig. Alleen actieve projecten."""
    if not werknummers or not kandidaten:
        return ProjectMatch(gelezen=None)
    per_id = {k.id: k for k in kandidaten}
    tokens: set[str] = set()
    for tekst in teksten:
        if tekst:
            tokens |= _tokens(tekst)
    if not tokens:
        return ProjectMatch(gelezen=None)
    treffers: list[tuple[WerknummerKoppeling, str]] = []
    for w in werknummers:
        norm = normaliseer_projectcode(w.werknummer)
        if norm and norm in tokens and w.project_id in per_id:
            treffers.append((w, w.werknummer))
    if not treffers:
        return ProjectMatch(gelezen=None)
    gelezen = ", ".join(sorted({t for _w, t in treffers}))
    uitkomst = _uniek_of_meerduidig(
        gelezen,
        [per_id[w.project_id] for w, _t in treffers],
        niveau=NIVEAU_WERKNUMMER,
        bevestigd=all(w.bevestigd for w, _t in treffers),
    )
    return uitkomst if uitkomst is not None else ProjectMatch(gelezen=gelezen)


_DATUM_TOKEN = re.compile(r"^(\d{1,2}[-/.]\d{1,2}[-/.]\d{2,4}|\d{4}[-/.]\d{1,2}[-/.]\d{1,2})$")
_BEDRAG_TOKEN = re.compile(r"^[€$]?\d{1,3}([.,]\d{3})*([.,]\d{1,2})?$")


def werknummer_kandidaat_in_koptekst(*teksten: str | None) -> str | None:
    """Leerlus-hulp (run D 02-10 blok B, Huvanco): welk token in de koptekst (`betreft`, `cbc:Note`) is het werknummer
    van de leverancier als de factuur géén `proj` draagt? Deterministisch en smal: een token mét minstens één cijfer én
    minstens één letter of scheidingsteken ("2025-0117", "W03611", "PO-4711B"), ≥ 4 tekens, geen datum, geen bedrag;
    puur-numerieke tokens tellen NIET (jaartal, bedrag, projectcode — te ambigu om als werknummer te onthouden). Precies
    één kandidaat (genormaliseerd uniek) → die tekst; nul of meerdere → None (nooit raden)."""
    gevonden: dict[str, str] = {}
    for tekst in teksten:
        if not tekst:
            continue
        for ruw in re.split(r"[\s/,;:|]+", tekst):
            token = ruw.strip("()[]{}.,;:'\"")
            if len(token) < 4 or not any(ch.isdigit() for ch in token):
                continue
            if token.isdigit() or _DATUM_TOKEN.match(token) or _BEDRAG_TOKEN.match(token):
                continue
            norm = normaliseer_projectcode(token)
            if not norm:
                continue
            gevonden.setdefault(norm, token)
    return next(iter(gevonden.values())) if len(gevonden) == 1 else None


# --- laders + leerlus (DB) -------------------------------------------------------------------------------


def laad_projectkandidaten(
    session: Session, *, administratie_id: uuid.UUID, inclusief_inactief: bool = False
) -> list[ProjectKandidaat]:
    """Alle ACTIEVE, niet-verdwenen projecten van de administratie (zelfde filter als de offerte-route).
    `inclusief_inactief=True` (blok 3 25-09) geeft óók inactieve/afgesloten projecten — uitsluitend voor de exacte-code-
    stap ("afgesloten projecten nooit voorstellen tenzij de factuur ernaar verwijst") en het formaat van de cache."""
    voorwaarden = [ProjectCache.administratie_id == administratie_id, ProjectCache.verdwenen_uit_bron_op.is_(None)]
    if not inclusief_inactief:
        voorwaarden.append(ProjectCache.is_actief.isnot(False))
    return [
        ProjectKandidaat(id=rij.id, naam=rij.naam or "")
        for rij in session.scalars(select(ProjectCache).where(*voorwaarden))
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
