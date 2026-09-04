"""Regel-niveau GB-voorstel uit de gelezen omschrijving — blok D medewerker-wensen 04-09 (Derks-casus;
mockup `projectverdeling-en-regelvoorstellen.html` blok 2, ontwerpnotitie ⑦; akkoord Peter 04-09).

Strikte volgorde per boekvoorstel-regel zonder grootboek (server-side in de prefill van
`app/documenten/boekvoorstel.py::haal_boekvoorstel_op`, via `app/documenten/regel_prefill.py`):

1. **Deterministisch regel-geheugen** (groen, chip "uit geheugen") — sleutel = (crediteur-kenmerk,
   genormaliseerde omschrijving). Het crediteur-kenmerk is het btw-nummer (anders het KvK-nummer) uit
   `crediteur_kenmerk`: álle vendor-ids in DEZE administratie met dat kenmerk vormen één groep
   (dedupe "Wola" / "Wola b.v."); zonder kenmerk telt alleen de vendor zelf. Bron = de BESTAANDE
   `boeking_observatie` met `regel_sleutel = normaliseer_regel_sleutel(omschrijving)`:
   - ≥ 1 app-observatie (door een mens bevestigde boeking) → groen; meerdere grootboeken in de
     app-observaties = conflict: de jongste wint, gemarkeerd oranje (`geheugen_conflict`);
   - uitsluitend rlz_seed-observaties → oranje "uit historie, nog niet bevestigd" (`geheugen_seed`) —
     TENZIJ hetzelfde grootboek bij deze leverancier(-groep) elders wél een app-observatie heeft: dan
     is die WAARDE app-bevestigd en geldt de geheugen-regel (CLAUDE.md "Seed-only = oranje … pas de
     eerste app-bevestiging van die waarde maakt 'm groen") → groen.
   GEEN nieuwe tabel: `BoekingObservatie` draagt regel_sleutel + bron + bron_datum al; de leerlus
   (`leerlus.leg_boeking_vast`, bij gesplitste boekingen) voedt 'm bij élke boeking — een bevestigd
   AI-voorstel én een correctie landen zo beide als app-observatie, zonder extra schrijver.
2. **AI-classificatie** (oranje, chip "AI-voorstel — bevestig") — alleen voor regels zónder
   geheugen-treffer, alleen achter de bestaande gates (`ai_extractie_ingeschakeld` + API-key; de
   kostenmeter zit in de client, bron `regel_gb_classificatie`), één call per document (batch van
   alle open regels), kandidaten = UITSLUITEND de grootboeken die deze leverancier(-groep) historisch
   gebruikte (distinct gb_id uit app- + seed-observaties, mét code + naam uit de grootboek-cache).
   Minder dan twee kandidaten = geen call: bij precies één kandidaat kiest het deterministische
   leverancier-geheugen (engine) die al — een AI-call kan daar niets aan toevoegen en zou een groen
   engine-voorstel alleen naar oranje verkleuren. Het model kiest per regel een kandidaat-index of 0
   ("geen") — schema zonder unions (sentinel-patroon). Uitkomst PERSISTENT per document in
   `regel_gb_classificatie` (migratie 0108), zodat herladen nooit een tweede call doet. Draait ná de
   extractie (post-commit-hook náást het duplicaatsignaal), systeem-actor, stil — fout = gelogd, nooit
   blokkerend. Nooit in de GET.
3. Leeg = mens kiest (de bestaande kop-niveau-engine-prefill in de UI blijft zoals nu).

Een regel-voorstel is een VOORSTEL: de opgeslagen keuze van de mens wint altijd (de prefill raakt alleen
regels zonder grootboek in een nog niet opgeslagen voorstel), en een AI-/seed-voorstel telt nooit als
app-bevestigd geheugen — de autoboek-poorten (`app/documenten/autoboeken.py`) lezen uitsluitend de
engine (`voorstel_voor`) en overschrijven de regelwaarden daarmee.
"""

from __future__ import annotations

import logging
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import date
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Administratie, Grootboekrekening
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.geheugen.models import BoekingObservatie, ObservatieBron, RegelGbClassificatie
from app.geheugen.normalisatie import normaliseer_regel_sleutel

logger = logging.getLogger(__name__)

# Herkomst-waarden van een regel-GB-voorstel (BoekvoorstelRegelData.gb_bron / DTO gb_bron).
BRON_GEHEUGEN = "geheugen"  # groen — app-bevestigd, eenduidig
BRON_GEHEUGEN_CONFLICT = "geheugen_conflict"  # oranje — app-observaties met wisselend grootboek, jongste wint
BRON_GEHEUGEN_SEED = "geheugen_seed"  # oranje — uitsluitend RLZ-historie, nog niet bevestigd
BRON_AI = "ai"  # oranje — AI-classificatie tegen de historische grootboeken van deze leverancier

# Onder dit aantal historische grootboeken geen AI-call (zie moduledocstring, punt 2).
MIN_KANDIDATEN_VOOR_AI = 2

# Bron-aanduiding in de AI-kostenmeter (platform.ai_gebruik) voor élke classificatie-call.
AI_VERBRUIK_BRON = "regel_gb_classificatie"


@dataclass(frozen=True)
class RegelObservatie:
    """Pure engine-invoer, los van het ORM-model (zelfde patroon als engine.Observatie)."""

    regel_sleutel: str | None
    gb_id: uuid.UUID
    bron: str
    bron_datum: date


@dataclass(frozen=True)
class RegelGbVoorstel:
    ledger_id: uuid.UUID
    bron: str
    # Korte, omschrijving-vrije tooltip-tekst ("3× bevestigd, laatst 12-08-2026").
    detail: str


@dataclass(frozen=True)
class Kandidaat:
    ledger_id: uuid.UUID
    code: str
    naam: str


# ----------------------------------------------------------------------------- pure logica


def _datum(d: date) -> str:
    return d.strftime("%d-%m-%Y")


def bepaal_regel_gb(observaties: list[RegelObservatie], *, regel_sleutel: str | None) -> RegelGbVoorstel | None:
    """Deterministisch regel-geheugen (stap 1). `observaties` = álle observaties van de
    leverancier-groep (kenmerk-dedupe gebeurt bij het laden); alleen die met exact dezelfde
    regel_sleutel tellen voor de treffer, de rest dient om app-bevestiging van de WAARDE te toetsen.
    Geen sleutel (lege omschrijving) of geen treffer = None — het geheugen raadt nooit."""
    if regel_sleutel is None:
        return None
    treffers = [o for o in observaties if o.regel_sleutel == regel_sleutel]
    if not treffers:
        return None

    app = [o for o in treffers if o.bron == ObservatieBron.APP.value]
    if app:
        per_gb = Counter(o.gb_id for o in app)
        jongste = max(app, key=lambda o: (o.bron_datum, str(o.gb_id)))  # deterministische tiebreak
        if len(per_gb) == 1:
            n = per_gb[jongste.gb_id]
            return RegelGbVoorstel(
                ledger_id=jongste.gb_id,
                bron=BRON_GEHEUGEN,
                detail=f"{n}× bevestigd, laatst {_datum(jongste.bron_datum)}",
            )
        return RegelGbVoorstel(
            ledger_id=jongste.gb_id,
            bron=BRON_GEHEUGEN_CONFLICT,
            detail=(
                f"wisselend geboekt ({len(per_gb)} grootboeken bij deze omschrijving) — "
                f"jongste keuze van {_datum(jongste.bron_datum)} vooringevuld, controleer"
            ),
        )

    # Uitsluitend RLZ-historie voor deze omschrijving.
    per_gb = Counter(o.gb_id for o in treffers)
    jongste = max(treffers, key=lambda o: (o.bron_datum, str(o.gb_id)))
    if len(per_gb) == 1:
        n = per_gb[jongste.gb_id]
        elders_bevestigd = sum(
            1 for o in observaties if o.bron == ObservatieBron.APP.value and o.gb_id == jongste.gb_id
        )
        if elders_bevestigd:
            # De waarde is app-bevestigd bij deze leverancier (andere regel of leverancier-niveau):
            # geheugen-regel → groen, met de herkomst zichtbaar in de tooltip.
            return RegelGbVoorstel(
                ledger_id=jongste.gb_id,
                bron=BRON_GEHEUGEN,
                detail=(
                    f"omschrijving {n}× in de RLZ-historie; "
                    f"grootboek {elders_bevestigd}× bevestigd bij deze leverancier"
                ),
            )
        return RegelGbVoorstel(
            ledger_id=jongste.gb_id,
            bron=BRON_GEHEUGEN_SEED,
            detail=f"uit historie ({n}×, laatst {_datum(jongste.bron_datum)}), nog niet bevestigd",
        )
    return RegelGbVoorstel(
        ledger_id=jongste.gb_id,
        bron=BRON_GEHEUGEN_SEED,
        detail=(
            f"wisselend in de RLZ-historie ({len(per_gb)} grootboeken) — jongste van {_datum(jongste.bron_datum)}, "
            "nog niet bevestigd"
        ),
    )


def kandidaat_ids(observaties: list[RegelObservatie]) -> list[uuid.UUID]:
    """Alle grootboeken die deze leverancier(-groep) historisch gebruikte (app + seed), deterministisch
    geordend — de enige toegestane AI-kandidaten."""
    return sorted({o.gb_id for o in observaties}, key=str)


def ai_detail(kandidaten_n: int) -> str:
    return f"AI koos uit {kandidaten_n} grootboeken van deze leverancier — bevestig of corrigeer"


# ----------------------------------------------------------------------------- DB-lezers


def vendor_groep(session: Session, *, administratie_id: uuid.UUID, vendor_id: uuid.UUID) -> frozenset[uuid.UUID]:
    """Alle vendor-ids in deze administratie met hetzelfde crediteur-kenmerk (btw-nummer, anders
    KvK-nummer) als `vendor_id` — de dedupe-groep voor het regel-geheugen. Zonder kenmerk: alleen de
    vendor zelf (nooit op naam groeperen — dat doet de crediteur-voorstel-match al, mét mens)."""
    from app.documenten.crediteur_kenmerk import kenmerken_per_vendor  # lokaal: extractie-controlelaag

    kenmerken = kenmerken_per_vendor(session, administratie_id=administratie_id)
    eigen = kenmerken.get(vendor_id)
    if eigen is None:
        return frozenset({vendor_id})
    if eigen.btw_nummer:
        return frozenset({vendor_id} | {k.vendor_id for k in kenmerken.values() if k.btw_nummer == eigen.btw_nummer})
    if eigen.kvk_nummer:
        return frozenset({vendor_id} | {k.vendor_id for k in kenmerken.values() if k.kvk_nummer == eigen.kvk_nummer})
    return frozenset({vendor_id})


def laad_observaties(
    session: Session, *, administratie_id: uuid.UUID, vendor_ids: frozenset[uuid.UUID]
) -> list[RegelObservatie]:
    rijen = session.scalars(
        select(BoekingObservatie).where(
            BoekingObservatie.administratie_id == administratie_id,
            BoekingObservatie.vendor_id.in_(list(vendor_ids)),
        )
    ).all()
    return [
        RegelObservatie(regel_sleutel=r.regel_sleutel, gb_id=r.gb_id, bron=r.bron, bron_datum=r.bron_datum)
        for r in rijen
    ]


def kandidaten_met_naam(
    session: Session, *, administratie_id: uuid.UUID, observaties: list[RegelObservatie]
) -> list[Kandidaat]:
    """Kandidaten mét code + naam uit de grootboek-cache van deze administratie; een grootboek dat
    niet (meer) in de cache staat kan het model niet beschrijven en valt weg als kandidaat."""
    ids = kandidaat_ids(observaties)
    if not ids:
        return []
    rijen = {
        r.ledger_id: r
        for r in session.scalars(
            select(Grootboekrekening).where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.ledger_id.in_(ids),
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            )
        )
    }
    return [Kandidaat(ledger_id=i, code=rijen[i].code, naam=rijen[i].naam) for i in ids if i in rijen]


def classificaties_voor(session: Session, *, document_id: uuid.UUID) -> dict[int, RegelGbClassificatie]:
    return {
        r.regel_volgnummer: r
        for r in session.scalars(select(RegelGbClassificatie).where(RegelGbClassificatie.document_id == document_id))
    }


def geldige_classificatie(
    classificaties: dict[int, RegelGbClassificatie], *, volgnummer: int, omschrijving: str | None
) -> RegelGbClassificatie | None:
    """Een opgeslagen uitkomst geldt alleen voor exact dezelfde (genormaliseerde) omschrijving —
    ná een her-extractie met andere regels is de rij ongeldig."""
    rij = classificaties.get(volgnummer)
    if rij is None or rij.regel_sleutel != normaliseer_regel_sleutel(omschrijving):
        return None
    return rij


# ----------------------------------------------------------------------------- AI-classificatie

# Sentinel-gebaseerd, nul unions (Anthropic-limiet 16, testpoort tests/extractie/test_schema_unionlimiet.py):
# per regel i (1-gebaseerd) de kandidaat-index k (1..n) of 0 = geen passende kandidaat.
CLASSIFICATIE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "keuzes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"i": {"type": "integer"}, "k": {"type": "integer"}},
                "required": ["i", "k"],
                "additionalProperties": False,
            },
        }
    },
    "required": ["keuzes"],
    "additionalProperties": False,
}

_SYSTEM = """\
Je koppelt factuurregel-omschrijvingen van één leverancier aan een grootboekrekening. Je krijgt een vaste, \
genummerde lijst grootboekrekeningen die deze leverancier eerder gebruikte — kies per regel UITSLUITEND uit \
die lijst (het nummer k), of 0 als geen enkele rekening duidelijk past. Je rekent niets en verzint geen \
rekeningen; bij twijfel kies je 0. Antwoord alleen met de keuzes."""


def _opdracht(regels: list[tuple[int, str]], kandidaten: list[Kandidaat]) -> str:
    lijst = "\n".join(f"{k}. {c.code} {c.naam}" for k, c in enumerate(kandidaten, start=1))
    tekst = "\n".join(f"{i}. {omschrijving}" for i, omschrijving in regels)
    return (
        "Grootboekrekeningen van deze leverancier:\n"
        + lijst
        + "\n\nFactuurregels:\n"
        + tekst
        + "\n\nGeef per regel i het nummer k van de best passende grootboekrekening, of 0 als er geen past."
    )


def _client_voor(administratie_id: uuid.UUID, document_id: uuid.UUID):
    """AI alleen achter de bestaande gates (zelfde poorten als de extractie en de voorraad-normalisatie):
    per-administratie AVG-gate + API-key; de kostengrens zit in de client. None = geen AI."""
    from app.aikosten.service import AiVerbruikReferentie
    from app.extractie.client import AiExtractieNietGeconfigureerd, ClaudeExtractieClient

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.ai_extractie_ingeschakeld:
            return None
    if not settings.anthropic_api_key:
        return None
    try:
        return ClaudeExtractieClient(
            verbruik_referentie=AiVerbruikReferentie(bron=AI_VERBRUIK_BRON, document_id=document_id)
        )
    except AiExtractieNietGeconfigureerd:
        return None


def _parse_keuzes(data: dict[str, Any] | None) -> dict[int, int]:
    keuzes: dict[int, int] = {}
    for item in (data or {}).get("keuzes", []) or []:
        if isinstance(item, dict) and isinstance(item.get("i"), int) and isinstance(item.get("k"), int):
            keuzes[item["i"]] = item["k"]
    return keuzes


def classificeer_document(*, administratie_id: uuid.UUID, document_id: uuid.UUID, client=None) -> int:
    """Stap 2: één AI-call voor álle open regels (geen geheugen-treffer, nog geen geldige uitkomst) van
    een NOG NIET opgeslagen boekvoorstel; uitkomst persistent per (document, regel). Retourneert het
    aantal geclassificeerde regels (0 = niets te doen, geen call gedaan). `client` is de test-seam."""
    from app.documenten import boekvoorstel  # lokaal: boekvoorstel importeert de prefill die hierop leest

    voorstel = boekvoorstel.haal_boekvoorstel_op(administratie_id=administratie_id, document_id=document_id)
    if voorstel.opgeslagen or voorstel.vendor_id is None:
        return 0
    open_regels = [
        (i, r)
        for i, r in enumerate(voorstel.regels, start=1)
        if r.ledger_id is None and r.gb_bron is None and (r.omschrijving or "").strip()
    ]
    if not open_regels:
        return 0

    with scoped_session(administratie_id) as session:
        groep = vendor_groep(session, administratie_id=administratie_id, vendor_id=voorstel.vendor_id)
        observaties = laad_observaties(session, administratie_id=administratie_id, vendor_ids=groep)
        kandidaten = kandidaten_met_naam(session, administratie_id=administratie_id, observaties=observaties)
        bestaand = classificaties_voor(session, document_id=document_id)
    if len(kandidaten) < MIN_KANDIDATEN_VOOR_AI:
        return 0
    te_doen = [
        (i, r)
        for i, r in open_regels
        if geldige_classificatie(bestaand, volgnummer=i, omschrijving=r.omschrijving) is None
    ]
    if not te_doen:
        return 0

    if client is None:
        client = _client_voor(administratie_id, document_id)
        if client is None:
            return 0
    antwoord = client.vraag_json(
        system=_SYSTEM,
        opdracht=_opdracht([(i, (r.omschrijving or "").strip()) for i, r in te_doen], kandidaten),
        json_schema=CLASSIFICATIE_SCHEMA,
    )
    keuzes = _parse_keuzes(antwoord.data)
    model = getattr(client, "_model", None) or settings.ai_extractie_model

    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        huidig = classificaties_voor(session, document_id=document_id)
        for i, r in te_doen:
            k = keuzes.get(i, 0)
            ledger_id = kandidaten[k - 1].ledger_id if 1 <= k <= len(kandidaten) else None
            rij = huidig.get(i)
            if rij is None:
                rij = RegelGbClassificatie(
                    administratie_id=administratie_id,
                    document_id=document_id,
                    regel_volgnummer=i,
                    kandidaten_n=len(kandidaten),
                    model=model,
                )
                session.add(rij)
            rij.regel_sleutel = normaliseer_regel_sleutel(r.omschrijving)
            rij.ledger_id = ledger_id
            rij.kandidaten_n = len(kandidaten)
            rij.model = model
    logger.info(
        "Regel-GB-classificatie document %s: %d regel(s) tegen %d kandidaten",
        document_id,
        len(te_doen),
        len(kandidaten),
    )
    return len(te_doen)


def classificeer_document_stil(*, administratie_id: uuid.UUID | None, document_id: uuid.UUID) -> None:
    """Hook-variant (post-commit ná de extractie): een fout is een gelogde waarschuwing — het voorstel
    is signalering, nooit een blokkade van de verwerking; het document blijft gewoon mensenwerk."""
    if administratie_id is None:
        return
    try:
        classificeer_document(administratie_id=administratie_id, document_id=document_id)
    except Exception:  # noqa: BLE001 — kostengrens/model-onbekend/API-fout: nooit een blokkade
        logger.exception("Regel-GB-classificatie mislukt voor document %s", document_id)
