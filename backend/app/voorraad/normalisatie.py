"""Catalogus-normalisatie — VOLAUTOMATISCH (besluit Peter 28-08, mockup voorraad-aansluiting.html §2).

Volgorde per factuurregel (leverancier + artikeltekst): (1) deterministische dienst-/transportregel
(automatisch uitgesloten, geen AI); (2) bestaande normalisatieregel (deterministisch — daarna nooit
meer een AI-call voor dezelfde tekst); (3) eerste match = AI-voorstel (achter de bestaande
AI-gates: per-administratie `ai_extractie_ingeschakeld` + API-key + kostengrens) dat DIRECT als regel
wordt toegepast — onzeker (< drempel) telt mee mét vlag; (4) geen AI mogelijk = `niet_genormaliseerd`
(prominent geteld in het aansluitscherm). Correctie is optioneel en herrekent historie; nooit een
voorwaarde. Code voor cijfers: de AI kiest alleen een groepsnaam, alle telling is deterministisch."""

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
from app.voorraad.models import ONBEKENDE_LEVERANCIER, Artikelgroep, NormalisatieRegel

logger = logging.getLogger(__name__)

# Onder deze zekerheid telt een AI-normalisatie mee mét de vlag "onzeker" (mockup: 61% → ⚑).
ONZEKER_DREMPEL = Decimal("0.75")

# Diensten/transport/toeslagen: automatisch uitgesloten zonder AI (mockup: "Transportkosten zone 2 —
# geen artikel — automatisch uitgesloten"). Bewust conservatief: alleen evidente niet-artikelen.
_DIENST_PATROON = re.compile(
    r"\b(transport|vracht|verzend|bezorg|levering|toeslag|administratiekosten|orderkosten|"
    r"montage|arbeid|uurloon|manuur|manuren|uren|huur|korting|statiegeld|emballage|pallet(kosten)?|"
    r"verwerkingskosten|milieutoeslag|brandstoftoeslag|voorrijkosten)",
    re.IGNORECASE,
)


def normaliseer_tekst(tekst: str) -> str:
    """Sleutel voor de deterministische regel: kleine letters, komma → punt, interpunctie weg,
    één spatie (zelfde geest als materiaal/match.py::_normaliseer)."""
    t = tekst.lower().replace(",", ".")
    t = re.sub(r"[^a-z0-9.+/ ]+", " ", t)
    return re.sub(r"\s+", " ", t).strip()


def is_dienst(tekst: str) -> bool:
    return bool(_DIENST_PATROON.search(tekst))


@dataclass(frozen=True)
class Normalisatie:
    status: str  # genormaliseerd | onzeker | uitgesloten | niet_genormaliseerd
    artikelgroep_id: uuid.UUID | None
    zekerheid: Decimal | None


def bepaal_status(zekerheid: Decimal | None, *, uitgesloten: bool, artikelgroep_id: uuid.UUID | None) -> str:
    if uitgesloten:
        return "uitgesloten"
    if artikelgroep_id is None:
        return "niet_genormaliseerd"
    if zekerheid is not None and zekerheid < ONZEKER_DREMPEL:
        return "onzeker"
    return "genormaliseerd"


def pas_regel_toe(regel: NormalisatieRegel) -> Normalisatie:
    return Normalisatie(
        status=bepaal_status(regel.zekerheid, uitgesloten=regel.uitgesloten, artikelgroep_id=regel.artikelgroep_id),
        artikelgroep_id=None if regel.uitgesloten else regel.artikelgroep_id,
        zekerheid=regel.zekerheid,
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
                    "g": {"type": ["string", "null"]},
                    "e": {"type": ["string", "null"]},
                    "z": {"type": "number"},
                },
                "required": ["i", "g", "e", "z"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["voorstellen"],
    "additionalProperties": False,
}

_SYSTEM = """\
Je normaliseert factuurregel-omschrijvingen van een handelsbedrijf in steigermateriaal naar \
artikelgroepen voor een voorraadcontrole. Per regel geef je de artikelgroep waarin dit artikel \
thuishoort: gebruik waar mogelijk een bestaande groep uit de meegegeven lijst (exact dezelfde naam), \
anders een korte nieuwe generieke groepsnaam (bijv. "Koppelingen 48mm", "Steigerbuis 3m", \
"Vlonders alu 2,5m"). Diensten, transport, toeslagen, huur en arbeid zijn géén artikel: geef dan \
null. Geef per regel ook de eenheid (bijv. "st", "m", "m2") en één zekerheidsscore 0..1 — wees \
eerlijk over twijfel. Je rekent niets; je kiest uitsluitend groepsnamen."""


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


def stel_voor_met_ai(
    client: ClaudeExtractieClient,
    *,
    teksten: list[tuple[str, str | None]],
    bestaande_groepen: list[str],
) -> dict[int, tuple[str | None, str | None, Decimal]]:
    """Eén call voor alle nog onbekende teksten van een document. Uitkomst per index:
    (groepsnaam | None=geen artikel, eenheid, zekerheid). Faalt de call, dan lege dict — de regels
    blijven `niet_genormaliseerd` (zichtbaar, geen blokkade)."""
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
        + "\n\nGeef per regel i (nummer) de groep g (bestaande naam, nieuwe naam, of null), eenheid e en zekerheid z."
    )
    try:
        antwoord = client.vraag_json(system=_SYSTEM, opdracht=opdracht, json_schema=_NORMALISATIE_SCHEMA)
    except AiExtractieFout:
        logger.exception("Normalisatie-AI-call mislukt — regels blijven niet_genormaliseerd")
        return {}
    except Exception:  # noqa: BLE001 — kostengrens/model-onbekend: zichtbaar via niet_genormaliseerd
        logger.exception("Normalisatie-AI-call geweigerd/mislukt — regels blijven niet_genormaliseerd")
        return {}
    uit: dict[int, tuple[str | None, str | None, Decimal]] = {}
    for v in (antwoord.data or {}).get("voorstellen", []) or []:
        if not isinstance(v, dict) or not isinstance(v.get("i"), int):
            continue
        z = v.get("z")
        try:
            zekerheid = max(Decimal("0"), min(Decimal("1"), Decimal(str(z))))
        except Exception:  # noqa: BLE001
            zekerheid = Decimal("0")
        groep = v.get("g")
        eenheid = v.get("e")
        uit[int(v["i"])] = (
            str(groep).strip() if isinstance(groep, str) and groep.strip() else None,
            str(eenheid).strip() if isinstance(eenheid, str) and eenheid.strip() else None,
            zekerheid.quantize(Decimal("0.001")),
        )
    return uit


def normaliseer_regels(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID | None,
    regels: list[tuple[str, uuid.UUID | None, str | None]],
) -> list[Normalisatie]:
    """Per (artikeltekst, vendor_id, leveranciersnaam) de normalisatie — deterministisch waar een
    regel bestaat, dienst-regel zonder AI, anders één AI-call voor de rest van het document. De
    uitkomst wordt als NormalisatieRegel vastgelegd zodat dezelfde tekst nooit opnieuw naar de AI gaat."""
    uitkomsten: list[Normalisatie | None] = [None] * len(regels)
    te_vragen: list[int] = []
    for i, (tekst, vendor_id, _lev) in enumerate(regels):
        norm = normaliseer_tekst(tekst)
        if not norm:
            uitkomsten[i] = Normalisatie("niet_genormaliseerd", None, None)
            continue
        bestaande = zoek_regel(session, administratie_id=administratie_id, vendor_id=vendor_id, tekst_norm=norm)
        if bestaande is not None:
            uitkomsten[i] = pas_regel_toe(bestaande)
            continue
        if is_dienst(tekst):
            regel = NormalisatieRegel(
                administratie_id=administratie_id,
                vendor_id=vendor_id or ONBEKENDE_LEVERANCIER,
                artikeltekst_norm=norm,
                uitgesloten=True,
                zekerheid=Decimal("1.000"),
                bron="regel",
            )
            session.add(regel)
            session.flush()
            uitkomsten[i] = pas_regel_toe(regel)
            continue
        te_vragen.append(i)

    # Dubbele teksten binnen één document één keer vragen.
    if te_vragen:
        client = _client_voor(administratie_id, document_id)
        unieke: dict[tuple[uuid.UUID, str], int] = {}
        for i in te_vragen:
            tekst, vendor_id, _ = regels[i]
            unieke.setdefault((vendor_id or ONBEKENDE_LEVERANCIER, normaliseer_tekst(tekst)), i)
        voorstellen: dict[int, tuple[str | None, str | None, Decimal]] = {}
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
            ai = stel_voor_met_ai(
                client,
                teksten=[(regels[i][0], regels[i][2]) for i in volgorde],
                bestaande_groepen=groepen,
            )
            voorstellen = {volgorde[k - 1]: v for k, v in ai.items() if 1 <= k <= len(volgorde)}
        for sleutel, eerste_i in unieke.items():
            vendor_id, norm = sleutel
            voorstel = voorstellen.get(eerste_i)
            if voorstel is None:
                nieuw: Normalisatie = Normalisatie("niet_genormaliseerd", None, None)
            else:
                groepsnaam, eenheid, zekerheid = voorstel
                if groepsnaam is None:
                    regel = NormalisatieRegel(
                        administratie_id=administratie_id,
                        vendor_id=vendor_id,
                        artikeltekst_norm=norm,
                        uitgesloten=True,
                        zekerheid=zekerheid,
                        bron="ai",
                    )
                else:
                    groep = _vind_of_maak_groep(
                        session, administratie_id=administratie_id, naam=groepsnaam, eenheid=eenheid
                    )
                    regel = NormalisatieRegel(
                        administratie_id=administratie_id,
                        vendor_id=vendor_id,
                        artikeltekst_norm=norm,
                        artikelgroep_id=groep.id,
                        zekerheid=zekerheid,
                        bron="ai",
                    )
                session.add(regel)
                session.flush()
                nieuw = pas_regel_toe(regel)
            for i in te_vragen:
                if (regels[i][1] or ONBEKENDE_LEVERANCIER, normaliseer_tekst(regels[i][0])) == sleutel:
                    uitkomsten[i] = nieuw
    return [u if u is not None else Normalisatie("niet_genormaliseerd", None, None) for u in uitkomsten]
