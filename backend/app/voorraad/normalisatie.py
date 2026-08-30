"""Catalogus-normalisatie — VOLAUTOMATISCH (besluit Peter 28-08, mockup voorraad-aansluiting.html §2),
v2 30-08 (besluiten Peter 29-08 avond — BESLISSINGEN "OPDRACHT 30-08"):

Uitkomst per factuurregel = SOORT (artikel / dienst / transport) + bij een artikel de ARTIKELGROEP +
zekerheid. Dienst-/transportregels blijven in de MI-laag (omzet-/dienstinformatie: kilometers,
keuringen, werktijd) en tellen alleen niet in de voorraad-aansluiting — "uitgesloten" is sinds v2 een
soort-label, geen status meer.

Volgorde per regel (leverancier + artikeltekst + artikelcode):
 1. bestaande kennis, deterministisch — een HANDMATIGE correctie wint altijd (tekstregel óf
    code-koppeling), daarna de tekstregel, daarna de code-koppeling (artikelcode per RICHTING +
    leverancier: inkoopcodes en verkoopcodes zijn verschillende sleutelruimtes, nooit gelijkgesteld);
 2. dienst-/transportregex (geen AI) — uitgebreid op de bevindingen van 29-08 (kilometers, werk- en
    reistijd, inspectie/keuring/kalibratie, huurperiode), controleerbaar én corrigeerbaar in de
    dienst-inzage van het aansluitscherm (eis Peter: nooit blind vertrouwen);
 3. eerste match = AI-voorstel (achter de bestaande gates: per-administratie `ai_extractie_ingeschakeld`
    + API-key + kostengrens), in batches, DIRECT toegepast als tekstregel én — bij een code — als
    code-koppeling (bron 'ai', zekerheid zichtbaar); onzeker (< drempel) telt mee mét vlag;
 4. geen AI mogelijk = `niet_genormaliseerd` (prominent geteld).
Correctie is optioneel en herrekent historie; nooit een voorwaarde. Code voor cijfers: de AI kiest
alleen soort + groepsnaam, alle telling is deterministisch."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.extractie.client import AiExtractieFout, AiExtractieNietGeconfigureerd, ClaudeExtractieClient
from app.voorraad.models import (
    ONBEKENDE_LEVERANCIER,
    SOORTEN,
    ArtikelcodeKoppeling,
    Artikelgroep,
    NormalisatieRegel,
)

logger = logging.getLogger(__name__)

SOORT_ARTIKEL, SOORT_DIENST, SOORT_TRANSPORT = SOORTEN

# Onder deze zekerheid telt een AI-normalisatie mee mét de vlag "onzeker" (mockup: 61% → ⚑).
ONZEKER_DREMPEL = Decimal("0.75")
# Unieke onbekende teksten per AI-call (hernormalisatie van duizenden RLZ-regels = meerdere calls,
# nooit één reuzenprompt die afgekapt raakt).
AI_BATCH = 40
# Legacy-status vóór migratie 0088 ("uitgesloten" = dienst/transport); de hernormalisatie zet 'm om.
LEGACY_UITGESLOTEN = "uitgesloten"

# Transport = verplaatsing van goederen/mensen (vervoer, kilometers, bezorging). Dienst = arbeid, tijd,
# keuring, huur, toeslagen, kortingen. Beide zonder AI. Woordbegin (geen deel van een langer woord
# vóóraan: "Nalevering" ≠ levering) behalve de samenstellings-staarten (…huur, …korting, …toeslag,
# …kosten: "Kraanhuur", "Betalingskorting", "Milieutoeslag", "Verzendkosten").
_TRANSPORT_PATROON = re.compile(
    r"(?<![a-z])(transport|vracht|verzend|bezorg|levering|voorrij|brandstoftoeslag|kilometer|km|verreden|"
    r"vervoer|rittenkaart|rit(ten)?prijs)",
    re.IGNORECASE,
)
_DIENST_PATROON = re.compile(
    r"(?<![a-z])(toeslag|administratiekosten|orderkosten|montage|demontage|arbeid|uurloon|manuur|manuren|"
    r"uur|uren|huur|korting|statiegeld|emballage|pallet(kosten)?|verwerkingskosten|milieutoeslag|"
    r"reistijd|werktijd|werk- en reistijd|inspectie|keuring|gekeurd|kalibr|gekalibreerd|arbobesluit|"
    r"servicekosten|onderhoudsbeurt|reparatie|advies|begeleiding|opleiding|instructie|abonnement)"
    r"|[a-z]+(huur|korting|toeslag|kosten)(?![a-z])",
    re.IGNORECASE,
)

# Artikelcode in de regeltekst: "(560140.4)", "(Gebr. 550173.38)", "(Gebr.550100.6 )", "(580385024)",
# "(1002-3)". Alleen cijfers mét . - / als scheiding en minimaal vier cijfers ("(3m)", "(2x)", "(per 100)"
# zijn geen codes). Laatste haakjes-code telt ("... (st) (580385024)"). "Gebr." = gebruikt — dezelfde
# code, hetzelfde artikel.
_CODE_IN_TEKST = re.compile(r"\(\s*(?:gebr\.?\s*)?([0-9][0-9.\-/]*[0-9])\s*\)", re.IGNORECASE)


def normaliseer_tekst(tekst: str) -> str:
    """Sleutel voor de deterministische regel: kleine letters, komma → punt, interpunctie weg,
    één spatie (zelfde geest als materiaal/match.py::_normaliseer)."""
    t = tekst.lower().replace(",", ".")
    t = re.sub(r"[^a-z0-9.+/ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def classificeer_soort(tekst: str) -> str | None:
    """Deterministische dienst-/transportregex; None = geen evidente niet-artikelregel (kandidaat
    artikel → kennis/AI). Transport eerst (specifieker), daarna dienst."""
    if _TRANSPORT_PATROON.search(tekst):
        return SOORT_TRANSPORT
    if _DIENST_PATROON.search(tekst):
        return SOORT_DIENST
    return None


def is_dienst(tekst: str) -> bool:
    """Compat-helper: dienst óf transport."""
    return classificeer_soort(tekst) is not None


def artikelcode_uit_tekst(tekst: str) -> str | None:
    treffers = [t for t in _CODE_IN_TEKST.findall(tekst or "") if sum(ch.isdigit() for ch in t) >= 4]
    return normaliseer_code(treffers[-1]) if treffers else None


def normaliseer_code(code: object) -> str | None:
    """Codesleutel: hoofdletters, zonder spaties, ≤ 40 tekens, minimaal één cijfer (een kale
    omschrijving is geen code)."""
    if not isinstance(code, str):
        return None
    schoon = re.sub(r"\s+", "", code).upper().strip("()[]")
    if not (2 <= len(schoon) <= 40) or not re.search(r"[0-9]", schoon):
        return None
    return schoon


@dataclass(frozen=True)
class RegelInvoer:
    tekst: str
    vendor_id: uuid.UUID | None
    leverancier: str | None
    richting: str  # in | uit
    artikelcode: str | None = None  # expliciet (inkoop-veldvoorstel); None = uit de tekst halen


@dataclass(frozen=True)
class Normalisatie:
    status: str  # genormaliseerd | onzeker | niet_genormaliseerd
    artikelgroep_id: uuid.UUID | None
    zekerheid: Decimal | None
    soort: str = SOORT_ARTIKEL
    artikelcode: str | None = None

    @property
    def telt_in_voorraad(self) -> bool:
        return self.soort == SOORT_ARTIKEL and self.artikelgroep_id is not None


def bepaal_status(zekerheid: Decimal | None, *, soort: str = SOORT_ARTIKEL, artikelgroep_id: uuid.UUID | None) -> str:
    if soort != SOORT_ARTIKEL:
        return "genormaliseerd"
    if artikelgroep_id is None:
        return "niet_genormaliseerd"
    if zekerheid is not None and zekerheid < ONZEKER_DREMPEL:
        return "onzeker"
    return "genormaliseerd"


def _is_legacy(regel: NormalisatieRegel | ArtikelcodeKoppeling) -> bool:
    return isinstance(regel, NormalisatieRegel) and regel.uitgesloten and regel.soort == SOORT_ARTIKEL


def _soort_van(regel: NormalisatieRegel | ArtikelcodeKoppeling) -> str:
    # Legacy-rijen (pre-0088) dragen alleen `uitgesloten`: een regex-regel krijgt de (uitgebreide) regex
    # opnieuw (transport vs dienst), anders 'dienst'.
    if _is_legacy(regel):
        if regel.bron == "regel":
            return classificeer_soort(regel.artikeltekst_norm) or SOORT_DIENST
        return SOORT_DIENST
    return regel.soort


def pas_regel_toe(regel: NormalisatieRegel | ArtikelcodeKoppeling, *, artikelcode: str | None = None) -> Normalisatie:
    soort = _soort_van(regel)
    groep = regel.artikelgroep_id if soort == SOORT_ARTIKEL else None
    return Normalisatie(
        status=bepaal_status(regel.zekerheid, soort=soort, artikelgroep_id=groep),
        artikelgroep_id=groep,
        zekerheid=regel.zekerheid,
        soort=soort,
        artikelcode=artikelcode,
    )


def zoek_regel(
    session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID | None, tekst_norm: str
) -> NormalisatieRegel | None:
    return session.scalars(
        select(NormalisatieRegel).where(
            NormalisatieRegel.administratie_id == administratie_id,
            NormalisatieRegel.vendor_id == (vendor_id or ONBEKENDE_LEVERANCIER),
            NormalisatieRegel.artikeltekst_norm == tekst_norm,
        )
    ).first()


def zoek_koppeling(
    session: Session, *, administratie_id: uuid.UUID, richting: str, vendor_id: uuid.UUID | None, code: str
) -> ArtikelcodeKoppeling | None:
    return session.scalars(
        select(ArtikelcodeKoppeling).where(
            ArtikelcodeKoppeling.administratie_id == administratie_id,
            ArtikelcodeKoppeling.richting == richting,
            ArtikelcodeKoppeling.vendor_id == (vendor_id or ONBEKENDE_LEVERANCIER),
            ArtikelcodeKoppeling.code == code,
        )
    ).first()


def _vind_of_maak_groep(
    session: Session, *, administratie_id: uuid.UUID, naam: str, eenheid: str | None
) -> Artikelgroep:
    schoon = " ".join(naam.split())[:80]
    bestaande = session.scalars(
        select(Artikelgroep).where(Artikelgroep.administratie_id == administratie_id, Artikelgroep.actief.is_(True))
    ).all()
    for g in bestaande:
        if g.naam.lower() == schoon.lower():
            return g
    groep = Artikelgroep(
        administratie_id=administratie_id,
        naam=schoon,
        eenheid=(eenheid or "st")[:16],
        aangemaakt_door=SYSTEEM_ACTOR_ID,
    )
    session.add(groep)
    session.flush()
    record_audit_event(
        session,
        actor_id=SYSTEEM_ACTOR_ID,
        module="mi",
        tabel="artikelgroep",
        record_id=groep.id,
        actie="artikelgroep_automatisch_aangemaakt",
        correlatie_id=uuid.uuid4(),
        nieuwe_waarde={"naam": schoon, "eenheid": groep.eenheid},
        administratie_id=administratie_id,
    )
    return groep


def zet_tekstregel(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    tekst_norm: str,
    soort: str,
    artikelgroep_id: uuid.UUID | None,
    zekerheid: Decimal | None,
    bron: str,
    actor_id: uuid.UUID | None = None,
) -> tuple[NormalisatieRegel, dict[str, Any] | None]:
    """Upsert van de tekstregel; geeft (regel, oude waarde) terug. `uitgesloten` blijft in sync met
    soort ≠ artikel (legacy-kolom tot de opruim-migratie)."""
    regel = zoek_regel(session, administratie_id=administratie_id, vendor_id=vendor_id, tekst_norm=tekst_norm)
    oud = None
    if regel is None:
        regel = NormalisatieRegel(
            administratie_id=administratie_id,
            vendor_id=vendor_id or ONBEKENDE_LEVERANCIER,
            artikeltekst_norm=tekst_norm,
            bron=bron,
        )
        session.add(regel)
    else:
        oud = {
            "artikelgroep_id": str(regel.artikelgroep_id) if regel.artikelgroep_id else None,
            "soort": _soort_van(regel),
            "bron": regel.bron,
        }
    regel.soort = soort
    regel.uitgesloten = soort != SOORT_ARTIKEL
    regel.artikelgroep_id = artikelgroep_id if soort == SOORT_ARTIKEL else None
    regel.zekerheid = zekerheid
    regel.bron = bron
    regel.bijgewerkt_door = actor_id
    session.flush()
    return regel, oud


def zet_koppeling(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    richting: str,
    vendor_id: uuid.UUID | None,
    code: str,
    soort: str,
    artikelgroep_id: uuid.UUID | None,
    zekerheid: Decimal | None,
    bron: str,
    voorbeeld_tekst: str | None,
    actor_id: uuid.UUID | None = None,
) -> tuple[ArtikelcodeKoppeling, dict[str, Any] | None]:
    koppeling = zoek_koppeling(
        session, administratie_id=administratie_id, richting=richting, vendor_id=vendor_id, code=code
    )
    oud = None
    if koppeling is None:
        koppeling = ArtikelcodeKoppeling(
            administratie_id=administratie_id,
            richting=richting,
            vendor_id=vendor_id or ONBEKENDE_LEVERANCIER,
            code=code,
            bron=bron,
        )
        session.add(koppeling)
    else:
        oud = {
            "artikelgroep_id": str(koppeling.artikelgroep_id) if koppeling.artikelgroep_id else None,
            "soort": koppeling.soort,
            "bron": koppeling.bron,
        }
    koppeling.soort = soort
    koppeling.artikelgroep_id = artikelgroep_id if soort == SOORT_ARTIKEL else None
    koppeling.zekerheid = zekerheid
    koppeling.bron = bron
    koppeling.voorbeeld_tekst = (voorbeeld_tekst or None) and voorbeeld_tekst[:200]
    koppeling.bijgewerkt_door = actor_id
    session.flush()
    return koppeling, oud


# --- AI-voorstel -----------------------------------------------------------------------------------

_NORMALISATIE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "voorstellen": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "i": {"type": "integer"},
                    "s": {"type": "string", "enum": list(SOORTEN)},
                    "g": {"type": ["string", "null"]},
                    "e": {"type": ["string", "null"]},
                    "z": {"type": "number"},
                },
                "required": ["i", "s", "g", "e", "z"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["voorstellen"],
    "additionalProperties": False,
}

_SYSTEM = """\
Je normaliseert factuurregel-omschrijvingen van een handels-/verhuurbedrijf in steigermateriaal naar \
artikelgroepen voor een voorraadcontrole. Per regel geef je eerst de soort s: "artikel" (een fysiek \
product dat in voorraad kan liggen), "dienst" (arbeid, werk- of reistijd, keuring/inspectie/kalibratie, \
huur(periode), toeslag, korting, montage) of "transport" (vervoer, kilometers, bezorging). Bij een artikel \
geef je de artikelgroep g waarin dit artikel thuishoort: gebruik waar mogelijk een bestaande groep uit de \
meegegeven lijst (exact dezelfde naam), anders een korte nieuwe generieke groepsnaam (bijv. "Koppelingen \
48mm", "Steigerbuis 3m", "Vlonders alu 2,5m"). Afmetingen zijn onderscheidend: steigerdelen/-buizen/-planken \
van 3 m en 5 m zijn verschillende producten en krijgen verschillende groepen — nooit samenvoegen op lengte. \
"Gebr." betekent gebruikt en verandert de groep niet. Een artikelcode tussen haakjes hoort bij het artikel. \
Bij dienst of transport is g null. Geef per regel ook de eenheid e (bijv. "st", "m", "m2"; null bij dienst) \
en één zekerheidsscore z 0..1 — wees eerlijk over twijfel. Je rekent niets; je kiest uitsluitend soort en \
groepsnaam."""


def _client_voor(administratie_id: uuid.UUID, document_id: uuid.UUID | None) -> ClaudeExtractieClient | None:
    """AI alleen achter de bestaande gates (zelfde poorten als de extractie): per-administratie
    AVG-gate + API-key; de kostengrens zit in de client. None = geen AI → `niet_genormaliseerd`."""
    from app.aikosten.service import AiVerbruikReferentie
    from app.db.session import scoped_session

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.ai_extractie_ingeschakeld:
            return None
    if not settings.anthropic_api_key:
        return None
    try:
        return ClaudeExtractieClient(
            verbruik_referentie=AiVerbruikReferentie(bron="voorraad_normalisatie", document_id=document_id)
        )
    except AiExtractieNietGeconfigureerd:
        return None


@dataclass(frozen=True)
class AiVoorstel:
    soort: str
    groepsnaam: str | None
    eenheid: str | None
    zekerheid: Decimal


def stel_voor_met_ai(
    client: ClaudeExtractieClient,
    *,
    teksten: list[tuple[str, str | None]],
    bestaande_groepen: list[str],
) -> dict[int, AiVoorstel]:
    """Eén call per batch onbekende teksten. Uitkomst per index (1-gebaseerd). Faalt de call, dan
    lege dict — de regels blijven `niet_genormaliseerd` (zichtbaar, geen blokkade)."""
    if not teksten:
        return {}
    regels = "\n".join(
        f"{i}. {tekst}" + (f" (leverancier: {lev})" if lev else "") for i, (tekst, lev) in enumerate(teksten, start=1)
    )
    opdracht = (
        "Bestaande artikelgroepen:\n"
        + ("\n".join(f"- {g}" for g in bestaande_groepen) if bestaande_groepen else "- (nog geen)")
        + "\n\nFactuurregels:\n"
        + regels
        + "\n\nGeef per regel i (nummer) de soort s, de groep g (bestaande naam, nieuwe naam, of null), "
        "eenheid e en zekerheid z."
    )
    try:
        antwoord = client.vraag_json(system=_SYSTEM, opdracht=opdracht, json_schema=_NORMALISATIE_SCHEMA)
    except AiExtractieFout:
        logger.exception("Normalisatie-AI-call mislukt — regels blijven niet_genormaliseerd")
        return {}
    except Exception:  # noqa: BLE001 — kostengrens/model-onbekend: zichtbaar via niet_genormaliseerd
        logger.exception("Normalisatie-AI-call geweigerd/mislukt — regels blijven niet_genormaliseerd")
        return {}
    uit: dict[int, AiVoorstel] = {}
    for v in (antwoord.data or {}).get("voorstellen", []) or []:
        if not isinstance(v, dict) or not isinstance(v.get("i"), int):
            continue
        try:
            zekerheid = max(Decimal("0"), min(Decimal("1"), Decimal(str(v.get("z")))))
        except Exception:  # noqa: BLE001
            zekerheid = Decimal("0")
        groep = v.get("g")
        groepsnaam = str(groep).strip() if isinstance(groep, str) and groep.strip() else None
        soort = v.get("s") if v.get("s") in SOORTEN else None
        if soort is None:
            soort = SOORT_ARTIKEL if groepsnaam else SOORT_DIENST
        if soort == SOORT_ARTIKEL and groepsnaam is None:
            soort = SOORT_DIENST  # "artikel zonder groep" bestaat niet — dan is het geen artikel
        eenheid = v.get("e")
        uit[int(v["i"])] = AiVoorstel(
            soort=soort,
            groepsnaam=groepsnaam if soort == SOORT_ARTIKEL else None,
            eenheid=str(eenheid).strip() if isinstance(eenheid, str) and eenheid.strip() else None,
            zekerheid=zekerheid.quantize(Decimal("0.001")),
        )
    return uit


# --- de motor ------------------------------------------------------------------------------------------


def _bestaande_kennis(
    session: Session, *, administratie_id: uuid.UUID
) -> tuple[dict[tuple[uuid.UUID, str], NormalisatieRegel], dict[tuple[str, uuid.UUID, str], ArtikelcodeKoppeling]]:
    """Alle tekstregels + code-koppelingen van de administratie in één keer (hernormalisatie van
    duizenden regels = geen query per regel)."""
    regels = {
        (r.vendor_id, r.artikeltekst_norm): r
        for r in session.scalars(
            select(NormalisatieRegel).where(NormalisatieRegel.administratie_id == administratie_id)
        )
    }
    koppelingen = {
        (k.richting, k.vendor_id, k.code): k
        for k in session.scalars(
            select(ArtikelcodeKoppeling).where(ArtikelcodeKoppeling.administratie_id == administratie_id)
        )
    }
    return regels, koppelingen


def _uit_kennis(
    tekstregel: NormalisatieRegel | None, koppeling: ArtikelcodeKoppeling | None, *, code: str | None
) -> Normalisatie | None:
    """Prioriteit: handmatig (tekst óf code) > tekstregel > code-koppeling."""
    if tekstregel is not None and tekstregel.bron == "handmatig":
        return pas_regel_toe(tekstregel, artikelcode=code)
    if koppeling is not None and koppeling.bron == "handmatig":
        return pas_regel_toe(koppeling, artikelcode=code)
    if tekstregel is not None:
        return pas_regel_toe(tekstregel, artikelcode=code)
    if koppeling is not None:
        return pas_regel_toe(koppeling, artikelcode=code)
    return None


def normaliseer_regels(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID | None,
    regels: list[RegelInvoer],
    met_ai: bool = True,
) -> list[Normalisatie]:
    """Per regel de normalisatie — deterministisch waar kennis bestaat, regex zonder AI, anders AI in
    batches (`met_ai=False` = alleen het deterministische pad, voor herleiden ná een correctie). De
    uitkomst wordt als tekstregel (+ code-koppeling) vastgelegd zodat dezelfde tekst/code nooit
    opnieuw naar de AI gaat."""
    tekstregels, koppelingen = _bestaande_kennis(session, administratie_id=administratie_id)
    uitkomsten: list[Normalisatie | None] = [None] * len(regels)
    te_vragen: list[int] = []

    def _kennis_bij(i: int) -> tuple[uuid.UUID, str, str | None]:
        r = regels[i]
        vendor = r.vendor_id or ONBEKENDE_LEVERANCIER
        code = normaliseer_code(r.artikelcode) if r.artikelcode else artikelcode_uit_tekst(r.tekst)
        return vendor, normaliseer_tekst(r.tekst), code

    for i, r in enumerate(regels):
        vendor, norm, code = _kennis_bij(i)
        if not norm:
            uitkomsten[i] = Normalisatie("niet_genormaliseerd", None, None, artikelcode=code)
            continue
        if r.richting not in ("in", "uit"):
            raise ValueError(f"onbekende richting {r.richting!r}")
        tekstregel = tekstregels.get((vendor, norm))
        koppeling = koppelingen.get((r.richting, vendor, code)) if code else None
        bekend = _uit_kennis(tekstregel, koppeling, code=code)
        if bekend is not None:
            uitkomsten[i] = bekend
            if tekstregel is not None and _is_legacy(tekstregel):
                tekstregel.soort = bekend.soort  # pre-0088-regel naar de v2-representatie (in sync)
            # Kennis laten doorgroeien (deterministisch, geen AI): een tekstregel zonder koppeling
            # maakt de code-koppeling aan en vice versa — zo leren bestaande administraties hun codes.
            if tekstregel is not None and koppeling is None and code:
                nieuw_k, _ = zet_koppeling(
                    session,
                    administratie_id=administratie_id,
                    richting=r.richting,
                    vendor_id=vendor,
                    code=code,
                    soort=bekend.soort,
                    artikelgroep_id=bekend.artikelgroep_id,
                    zekerheid=bekend.zekerheid,
                    bron="handmatig" if tekstregel.bron == "handmatig" else "ai",
                    voorbeeld_tekst=r.tekst,
                )
                koppelingen[(r.richting, vendor, code)] = nieuw_k
            elif tekstregel is None and koppeling is not None:
                nieuw_r, _ = zet_tekstregel(
                    session,
                    administratie_id=administratie_id,
                    vendor_id=vendor,
                    tekst_norm=norm,
                    soort=bekend.soort,
                    artikelgroep_id=bekend.artikelgroep_id,
                    zekerheid=bekend.zekerheid,
                    bron="handmatig" if koppeling.bron == "handmatig" else "ai",
                )
                tekstregels[(vendor, norm)] = nieuw_r
            continue
        soort = classificeer_soort(r.tekst)
        if soort is not None:
            regel, _ = zet_tekstregel(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor,
                tekst_norm=norm,
                soort=soort,
                artikelgroep_id=None,
                zekerheid=Decimal("1.000"),
                bron="regel",
            )
            tekstregels[(vendor, norm)] = regel
            uitkomsten[i] = pas_regel_toe(regel, artikelcode=code)
            continue
        te_vragen.append(i)

    if not te_vragen:
        return [u if u is not None else Normalisatie("niet_genormaliseerd", None, None) for u in uitkomsten]

    # Dubbele teksten binnen de aanroep één keer vragen; batches van AI_BATCH unieke teksten.
    unieke: dict[tuple[uuid.UUID, str], int] = {}
    for i in te_vragen:
        vendor, norm, _ = _kennis_bij(i)
        unieke.setdefault((vendor, norm), i)
    client = _client_voor(administratie_id, document_id) if met_ai else None
    voorstellen: dict[int, AiVoorstel] = {}
    if client is not None:
        groepen = [
            g.naam
            for g in session.scalars(
                select(Artikelgroep).where(
                    Artikelgroep.administratie_id == administratie_id, Artikelgroep.actief.is_(True)
                )
            )
        ]
        volgorde = list(unieke.values())
        for start in range(0, len(volgorde), AI_BATCH):
            batch = volgorde[start : start + AI_BATCH]
            ai = stel_voor_met_ai(
                client,
                teksten=[(regels[i].tekst, regels[i].leverancier) for i in batch],
                bestaande_groepen=groepen,
            )
            for k, v in ai.items():
                if 1 <= k <= len(batch):
                    voorstellen[batch[k - 1]] = v
                    if v.groepsnaam and v.groepsnaam not in groepen:
                        groepen.append(v.groepsnaam)  # volgende batch kent de nieuwe groep
    for sleutel, eerste_i in unieke.items():
        vendor, norm = sleutel
        voorstel = voorstellen.get(eerste_i)
        _, _, code = _kennis_bij(eerste_i)
        if voorstel is None:
            nieuw = Normalisatie("niet_genormaliseerd", None, None, artikelcode=code)
        else:
            groep_id = None
            if voorstel.soort == SOORT_ARTIKEL and voorstel.groepsnaam:
                groep_id = _vind_of_maak_groep(
                    session, administratie_id=administratie_id, naam=voorstel.groepsnaam, eenheid=voorstel.eenheid
                ).id
            regel, _ = zet_tekstregel(
                session,
                administratie_id=administratie_id,
                vendor_id=vendor,
                tekst_norm=norm,
                soort=voorstel.soort,
                artikelgroep_id=groep_id,
                zekerheid=voorstel.zekerheid,
                bron="ai",
            )
            tekstregels[sleutel] = regel
            if code:
                richting = regels[eerste_i].richting
                if (richting, vendor, code) not in koppelingen:
                    k, _ = zet_koppeling(
                        session,
                        administratie_id=administratie_id,
                        richting=richting,
                        vendor_id=vendor,
                        code=code,
                        soort=voorstel.soort,
                        artikelgroep_id=groep_id,
                        zekerheid=voorstel.zekerheid,
                        bron="ai",
                        voorbeeld_tekst=regels[eerste_i].tekst,
                    )
                    koppelingen[(richting, vendor, code)] = k
            nieuw = pas_regel_toe(regel, artikelcode=code)
        for i in te_vragen:
            v_i, n_i, c_i = _kennis_bij(i)
            if (v_i, n_i) == sleutel:
                uitkomsten[i] = Normalisatie(nieuw.status, nieuw.artikelgroep_id, nieuw.zekerheid, nieuw.soort, c_i)
    return [u if u is not None else Normalisatie("niet_genormaliseerd", None, None) for u in uitkomsten]
