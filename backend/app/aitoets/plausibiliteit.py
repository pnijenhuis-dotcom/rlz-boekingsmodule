"""AI-plausibiliteitstoets als POORT vóór automatisch boeken (blok B bundel 10-09; besluit Peter 10-09).

Kernprincipe: code voor cijfers, AI voor taal. De rekening/btw is al deterministisch bepaald (historie-regel,
vaste regel of het factuur-autoboekpad); de AI mag alleen zeggen of dat voorstel plausibel is gezien
omschrijving/tegenpartij/bedrag/historie. Uitkomst uitsluitend 'plausibel' of 'twijfel' + reden (sentinel-schema,
0 unions) — de AI krijgt NOOIT de keuze uit rekeningen.

Poorten, in deze volgorde, elk `overgeslagen` mét oorzaak en NOOIT boeken:
(1) AVG-gate `intake_ai_ingeschakeld` (platform, dezelfde gate als de intake-AI),
(2) API-key geconfigureerd,
(3) AI-kostengrens (de client draait `controleer_poort` vóór en `registreer_verbruik` ná de call — zelfde meter),
(4) AI-fout/timeout/afkap/onbruikbaar antwoord.
Audit per toets: `ai_plausibiliteitstoets` mét soort/uitkomst/reden/model — nooit de prompt.

Testseam: `_client_factory` (module-niveau, monkeypatchbaar) — tests gebruiken `tests/aitoets/conftest.py::
StubPlausibiliteitClient`, nooit een echte call."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from app.config import settings
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID

logger = logging.getLogger(__name__)

SOORT_BANK_HISTORIE = "bank_historie"
SOORT_BANK_VASTE_REGEL = "bank_vaste_regel"
SOORT_FACTUUR_AUTOBOEKING = "factuur_autoboeking"

UITKOMST_PLAUSIBEL = "plausibel"
UITKOMST_TWIJFEL = "twijfel"
UITKOMST_OVERGESLAGEN = "overgeslagen"
UITKOMST_UIT = "uit"

OORZAAK_AVG_GATE = "avg_gate"
OORZAAK_API_KEY = "api_key"
OORZAAK_KOSTENGRENS = "kostengrens"
OORZAAK_AI_FOUT = "ai_fout"

AUDIT_ACTIE = "ai_plausibiliteitstoets"
_MAX_REDEN_TEKENS = 300

# Sentinel-schema: 0 union-parameters (bugfix 31-08, Anthropic-limiet 16). Alleen ja/nee op het voorgestelde.
# Geregistreerd in extractie/schema_poort.py::live_schemas zodat de union-poort-test 'm meetelt.
PLAUSIBILITEIT_SCHEMA: dict[str, Any] = {
    "type": "object",
    "required": ["uitkomst", "reden"],
    "properties": {
        "uitkomst": {"type": "string", "enum": [UITKOMST_PLAUSIBEL, UITKOMST_TWIJFEL]},
        "reden": {"type": "string"},
    },
    "additionalProperties": False,
}

SYSTEM_PROMPT = (
    "Je bent een controlerend boekhouder bij een Nederlands administratiekantoor. Je krijgt één voorgestelde "
    "boeking die door regels (code) is bepaald. Je kiest NIET zelf een rekening en je rekent niets na. Je zegt "
    "alleen of het voorstel plausibel is voor deze mutatie, gegeven omschrijving, tegenpartij, bedrag, de voorgestelde "
    "grootboekrekening met btw-behandeling en de samenvatting van eerdere boekingen. Bij gerede twijfel (rekening past "
    "duidelijk niet bij de omschrijving/tegenpartij, btw-behandeling botst met het soort kosten, bedrag of teken is "
    "ongewoon voor deze reeks) antwoord je 'twijfel' met een korte reden in het Nederlands. Anders 'plausibel' met een "
    "korte reden. Antwoord uitsluitend met de gevraagde JSON."
)


@dataclass(frozen=True)
class PlausibiliteitInvoer:
    administratie_id: uuid.UUID
    soort: str  # SOORT_BANK_HISTORIE | SOORT_BANK_VASTE_REGEL | SOORT_FACTUUR_AUTOBOEKING
    omschrijving: str | None
    tegenpartij: str | None
    bedrag: Decimal | None
    rekening_code: str | None  # GB-code
    rekening_naam: str | None
    btw_omschrijving: str | None
    historie_samenvatting: str  # deterministisch opgebouwd, bv. "12 eerdere mutaties, 12× 4400 Huur (100 %)"
    referentie_id: uuid.UUID  # payment_transaction_id (bank) of document_id (factuur) — audit-record


@dataclass(frozen=True)
class PlausibiliteitUitkomst:
    uitkomst: str  # UITKOMST_PLAUSIBEL | UITKOMST_TWIJFEL | UITKOMST_OVERGESLAGEN | UITKOMST_UIT
    reden: str  # leesbaar; bij overgeslagen begint de reden met de oorzaak (avg_gate, api_key, kostengrens, ai_fout)

    @property
    def boeken_toegestaan(self) -> bool:
        """Alleen 'plausibel' en 'uit' (toets niet van toepassing) laten het boekpad door."""
        return self.uitkomst in (UITKOMST_PLAUSIBEL, UITKOMST_UIT)


def _standaard_client_factory(referentie):
    from app.extractie.client import ClaudeExtractieClient

    return ClaudeExtractieClient(model=settings.ai_toets_model, verbruik_referentie=referentie)


#: Testseam: geeft een object met `vraag_json(system=, opdracht=, json_schema=) -> ClaudeAntwoord`-achtig resultaat.
_client_factory: Callable[[Any], Any] = _standaard_client_factory


def bouw_opdracht(invoer: PlausibiliteitInvoer) -> str:
    """Deterministische prompttekst — alleen de bankgegevens die de AVG-gate al dekt (tegenpartijnaam en
    omschrijving), het voorstel en een telling; geen historie-rijen, geen IBAN's."""
    bedrag = f"€ {invoer.bedrag:.2f}" if invoer.bedrag is not None else "onbekend"
    rekening = " ".join(deel for deel in (invoer.rekening_code, invoer.rekening_naam) if deel) or "onbekend"
    soort_tekst = {
        SOORT_BANK_HISTORIE: "bankmutatie — voorstel uit de historie-regel (zelfde tegenrekening + omschrijvingskern)",
        SOORT_BANK_VASTE_REGEL: "bankmutatie — voorstel uit een door een mens bevestigde vaste regel",
        SOORT_FACTUUR_AUTOBOEKING: "inkoopfactuur — automatisch boekvoorstel uit het boekingsgeheugen",
    }.get(invoer.soort, invoer.soort)
    return (
        f"Soort: {soort_tekst}\n"
        f"Omschrijving: {invoer.omschrijving or '(leeg)'}\n"
        f"Tegenpartij: {invoer.tegenpartij or '(onbekend)'}\n"
        f"Bedrag: {bedrag}\n"
        f"Voorgestelde grootboekrekening: {rekening}\n"
        f"Voorgestelde btw-behandeling: {invoer.btw_omschrijving or '(geen btw / onbekend)'}\n"
        f"Eerdere boekingen: {invoer.historie_samenvatting}\n"
        'Antwoord met {"uitkomst": "plausibel" | "twijfel", "reden": "<korte reden>"}.'
    )


def _audit(invoer: PlausibiliteitInvoer, uitkomst: PlausibiliteitUitkomst, *, model: str | None) -> None:
    tabel = "document" if invoer.soort == SOORT_FACTUUR_AUTOBOEKING else "bank_mutatie"
    with scoped_session(invoer.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel=tabel,
            record_id=invoer.referentie_id,
            actie=AUDIT_ACTIE,
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "soort": invoer.soort,
                "uitkomst": uitkomst.uitkomst,
                "reden": uitkomst.reden,
                "model": model,
            },
            administratie_id=invoer.administratie_id,
        )


def _overgeslagen(oorzaak: str, detail: str) -> PlausibiliteitUitkomst:
    return PlausibiliteitUitkomst(UITKOMST_OVERGESLAGEN, f"{oorzaak} — {detail}")


def toets_plausibiliteit(invoer: PlausibiliteitInvoer) -> PlausibiliteitUitkomst:
    """Voert de toets uit achter de vier poorten en legt de uitkomst vast in het audit_event. Elke niet-plausibele
    uitkomst betekent voor de aanroeper: NIET boeken, zichtbaar laten staan."""
    from app.aikosten.service import AiKostenFout, AiVerbruikReferentie
    from app.beheer.service import intake_ai_effectief_ingeschakeld
    from app.extractie.client import AiExtractieFout, AiExtractieNietGeconfigureerd

    model: str | None = None
    # (1) AVG-gate — zonder platformbrede opt-in gaat er geen byte naar de Claude API.
    if not intake_ai_effectief_ingeschakeld():
        uitkomst = _overgeslagen(OORZAAK_AVG_GATE, "AI staat platformbreed uit (Instellingen › Intake-AI)")
        _audit(invoer, uitkomst, model=model)
        return uitkomst
    # (2) API-key.
    referentie = AiVerbruikReferentie(
        bron=f"ai_toets_{invoer.soort}",
        document_id=invoer.referentie_id if invoer.soort == SOORT_FACTUUR_AUTOBOEKING else None,
    )
    try:
        client = _client_factory(referentie)
    except AiExtractieNietGeconfigureerd as exc:
        uitkomst = _overgeslagen(OORZAAK_API_KEY, f"geen API-key geconfigureerd ({exc})")
        _audit(invoer, uitkomst, model=model)
        return uitkomst
    model = getattr(client, "_model", None) or settings.ai_toets_model
    # (3) kostengrens + (4) AI-fout — de client draait de kostenpoort zelf vóór de call.
    try:
        antwoord = client.vraag_json(
            system=SYSTEM_PROMPT, opdracht=bouw_opdracht(invoer), json_schema=PLAUSIBILITEIT_SCHEMA
        )
    except AiKostenFout as exc:
        uitkomst = _overgeslagen(OORZAAK_KOSTENGRENS, str(exc))
        _audit(invoer, uitkomst, model=model)
        return uitkomst
    except AiExtractieFout as exc:
        uitkomst = _overgeslagen(OORZAAK_AI_FOUT, str(exc))
        _audit(invoer, uitkomst, model=model)
        return uitkomst
    except Exception as exc:  # noqa: BLE001 — een onverwachte fout in de AI-laag mag nooit een boeking doorlaten
        logger.exception("AI-plausibiliteitstoets onverwacht mislukt (%s)", invoer.referentie_id)
        uitkomst = _overgeslagen(OORZAAK_AI_FOUT, f"{type(exc).__name__}: {exc}")
        _audit(invoer, uitkomst, model=model)
        return uitkomst

    data = getattr(antwoord, "data", None)
    if getattr(antwoord, "afgekapt", False) or not isinstance(data, dict):
        uitkomst = _overgeslagen(OORZAAK_AI_FOUT, "antwoord afgekapt of geen JSON-object")
        _audit(invoer, uitkomst, model=model)
        return uitkomst
    oordeel = data.get("uitkomst")
    reden = " ".join(str(data.get("reden") or "").split())[:_MAX_REDEN_TEKENS] or "(geen reden gegeven)"
    if oordeel not in (UITKOMST_PLAUSIBEL, UITKOMST_TWIJFEL):
        uitkomst = _overgeslagen(OORZAAK_AI_FOUT, f"onbekende uitkomst {oordeel!r}")
        _audit(invoer, uitkomst, model=model)
        return uitkomst
    uitkomst = PlausibiliteitUitkomst(oordeel, reden)
    _audit(invoer, uitkomst, model=model)
    return uitkomst


# --- B3: facturen -------------------------------------------------------------------------------------------


def ai_toets_facturen_ingeschakeld() -> bool:
    """Platformbrede schakelaar (boeken_instelling.ai_toets_facturen_ingeschakeld, default AAN). Geen rij =
    AAN (de migratie-default) — een ontbrekende instelling zet nooit stil een poort open of dicht: AAN is de
    veilige kant (hooguit een extra toets)."""
    from app.db.models import BoekenInstelling

    with scoped_session(None) as session:
        instelling = session.get(BoekenInstelling, True)
        return instelling is None or bool(instelling.ai_toets_facturen_ingeschakeld)


def toets_factuur_autoboeking(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, invoer_velden: dict
) -> PlausibiliteitUitkomst:
    """Optionele extra poort op factuur-autoboekingen (B3). Leest eerst de platformbrede setting; uit → 'uit' (de
    aanroeper, documenten/autoboeken.py van blok A, boekt gewoon). Anders bouwt hij de invoer uit het boekvoorstel
    (regels → rekening/btw via de caches) en de door de aanroeper meegegeven velden en roept `toets_plausibiliteit`.

    `invoer_velden` (alle optioneel, de aanroeper geeft wat hij al heeft): `leverancier` (naam), `omschrijving`
    (kop-omschrijving/betreft), `bedrag` (Decimal totaal), `geheugen_samenvatting` (bv. "12 eerdere facturen, 12× 4400
    Huur (100 %)"), `ledger_id`, `taxrate_id` (winnen van de eerste regel van het boekvoorstel)."""
    if not ai_toets_facturen_ingeschakeld():
        return PlausibiliteitUitkomst(UITKOMST_UIT, "AI-toets facturen staat platformbreed uit")

    from app.db.models import Grootboekrekening
    from app.documenten.boekvoorstel import haal_boekvoorstel_op
    from app.sync.models import TaxRateCache, VendorCache

    ledger_id = invoer_velden.get("ledger_id")
    taxrate_id = invoer_velden.get("taxrate_id")
    bedrag = invoer_velden.get("bedrag")
    leverancier = invoer_velden.get("leverancier")
    omschrijving = invoer_velden.get("omschrijving")
    try:
        voorstel = haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    except Exception as exc:  # noqa: BLE001 — geen voorstel leesbaar = niet plausibel te maken; nooit doorlaten
        return _overgeslagen(OORZAAK_AI_FOUT, f"boekvoorstel niet leesbaar: {type(exc).__name__}: {exc}")
    regels = voorstel.regels or ([voorstel.samengevoegde_regel] if voorstel.samengevoegde_regel else [])
    if regels:
        ledger_id = ledger_id or regels[0].ledger_id
        taxrate_id = taxrate_id or regels[0].taxrate_id
        omschrijving = omschrijving or regels[0].omschrijving
    bedrag = bedrag if bedrag is not None else voorstel.totaalbedrag
    omschrijving = omschrijving or voorstel.referentie

    rekening_code = rekening_naam = btw = None
    with scoped_session(administratie_id) as session:
        if ledger_id is not None:
            gb = session.get(Grootboekrekening, (ledger_id, administratie_id))
            if gb is not None:
                rekening_code, rekening_naam = gb.code, gb.naam
        if taxrate_id is not None:
            tarief = session.get(TaxRateCache, (taxrate_id, administratie_id))
            btw = tarief.naam if tarief is not None else None
        if not leverancier and voorstel.vendor_id is not None:
            vendor = session.get(VendorCache, (voorstel.vendor_id, administratie_id))
            leverancier = vendor.naam if vendor is not None else None
    meerdere = len({(r.ledger_id, r.taxrate_id) for r in regels}) > 1
    samenvatting = str(invoer_velden.get("geheugen_samenvatting") or "geen samenvatting van eerdere boekingen")
    if meerdere:
        samenvatting += f" — voorstel heeft {len(regels)} regels; getoetst op de eerste"
    return toets_plausibiliteit(
        PlausibiliteitInvoer(
            administratie_id=administratie_id,
            soort=SOORT_FACTUUR_AUTOBOEKING,
            omschrijving=omschrijving,
            tegenpartij=leverancier,
            bedrag=Decimal(str(bedrag)) if bedrag is not None else None,
            rekening_code=rekening_code,
            rekening_naam=rekening_naam,
            btw_omschrijving=btw,
            historie_samenvatting=samenvatting,
            referentie_id=document_id,
        )
    )
