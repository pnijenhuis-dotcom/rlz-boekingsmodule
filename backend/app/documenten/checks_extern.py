"""Externe harde checks: vingerafdruk, cache en parallelle uitvoering (opdracht Peter 18-09 "Boeken sneller").

Peter (18-09): "als ik nu een factuur boek duurt het lang voordat alle controles groen worden (4 à 5 seconden)". Die
seconden zaten in drie tot zes RLZ-roundtrips IN SERIE bij élke checks-run: `Vendors/{id}/BankRelations` (IBAN-seed),
`find_purchase_invoices_by_reference` per crediteurrecord van het identiteitscluster + de kandidatenquery ± 60 dagen
(`extern_bestaan.zoek_extern_bestaand`) en de query over crediteuren heen. En dat herhaalde zich bij élke wijziging —
ook een omschrijving, die geen enkele externe check raakt.

Regel (`docs/regels/autoboeken-ai.md` + `duplicaten-crediteuren.md`, BESLISSINGEN "BOEKEN SNELLER"):
- De harde checks blijven server-side en blokkerend; ze worden alleen niet twee keer met DEZELFDE externe invoer
  gedraaid. De externe invoer = de VINGERAFDRUK: crediteur (+ identiteitscluster), referentie genormaliseerd,
  factuurdatum, totaalbedrag, factuur-IBAN, boek_cyclus, backend. Omschrijving/grootboek/project/btw-code zitten er
  bewust NIET in — die veranderen niets aan wat RLZ over deze factuur weet.
- Het externe rapport is persistent (`boekhouding.check_extern_cache`, één rij per document) en geldig zolang de
  vingerafdruk gelijk is én de run ≤ `settings.checks_extern_cache_minuten` oud is. Bij boeken hergebruikt de motor
  hetzelfde rapport onder dezelfde voorwaarden; een boeken_mislukt-retry en het autoboek-pad draaien ALTIJD vers.
- Een storing (client niet te openen, RLZ-fout in de duplicaatquery) wordt nooit gecachet: de volgende run probeert
  opnieuw. Een crediteur zonder Odoo-partner-koppeling is wél een stabiele toestand (blokkerend, leesbaar) en wordt
  gecachet zoals elke uitkomst.
- De drie externe calls lopen PARALLEL (ThreadPool, max 3 — één RlzClient, httpx.Client is thread-safe; de
  client-throttling blijft gerespecteerd).

Puur waar het kan: `ExternRapport` is JSON-rond (cache), `vingerafdruk` is een pure hash; alleen `lees_cache`/
`schrijf_cache` raken de database.
"""

from __future__ import annotations

import hashlib
import logging
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.config import settings
from app.db.session import scoped_session
from app.documenten.checks import CheckResultaat
from app.documenten.models import CheckExternCache
from app.documenten.referentie import normaliseer_referentie

logger = logging.getLogger(__name__)

#: Modus van de externe checks in `boekvoorstel.voer_checks_uit`:
#: - AUTO: geldige cache hergebruiken, anders vers draaien en cachen (controlescherm, handmatig boeken);
#: - VERS: altijd draaien en cachen (boeken_mislukt-retry, autoboek-pad, herstel-CLI);
#: - CACHE: nooit RLZ raken — geldige cache of "nog niet gecontroleerd" (blokkerend), voor het snelle lokale pad
#:   van het controlescherm (de externe run volgt als aparte aanroep).
AUTO = "auto"
VERS = "vers"
CACHE = "cache"
MODI = (AUTO, VERS, CACHE)

#: Prefix van de melding die check_duplicaat bij een RLZ-/verbindingsfout teruggeeft — die uitkomst is een STORING
#: (blokkerend, maar nooit cachen: de volgende run probeert opnieuw).
STORING_PREFIX = "Duplicaatcheck kon niet uitgevoerd worden"
NOG_NIET_MELDING = "Externe controle loopt nog — Reeleezee/Odoo wordt geraadpleegd"


class StapTiming:
    """Server-Timing per stap (stap 0 van de opdracht): `met("checks.lokaal")` als contextmanager; `header()` = de
    `Server-Timing`-headerwaarde, `als_dict()` = de gestructureerde logregel. Dun en zonder afhankelijkheden zodat de
    routes én de worker 'm kunnen dragen."""

    def __init__(self) -> None:
        self.duur_ms: dict[str, float] = {}

    class _Meting:
        def __init__(self, timing: StapTiming, naam: str) -> None:
            self._timing, self._naam, self._t0 = timing, naam, 0.0

        def __enter__(self) -> None:
            self._t0 = time.perf_counter()

        def __exit__(self, *exc: object) -> None:
            self._timing.tel(self._naam, (time.perf_counter() - self._t0) * 1000)

    def met(self, naam: str) -> StapTiming._Meting:
        return StapTiming._Meting(self, naam)

    def tel(self, naam: str, ms: float) -> None:
        self.duur_ms[naam] = round(self.duur_ms.get(naam, 0.0) + ms, 1)

    def header(self) -> str:
        return ", ".join(f"{naam};dur={ms:.1f}" for naam, ms in self.duur_ms.items())

    def als_dict(self) -> dict[str, float]:
        return dict(self.duur_ms)


def vingerafdruk(
    *,
    vendor_id: uuid.UUID | None,
    identiteit_vendor_ids: list[uuid.UUID] | tuple[uuid.UUID, ...] = (),
    referentie: str | None,
    factuurdatum: date | None,
    totaalbedrag: Decimal | None,
    factuur_iban: str | None,
    boek_cyclus: int = 0,
    backend: str = "",
) -> str:
    """sha256 over de externe invoer. Referentie genormaliseerd (spaties tussen cijfergroepen = groepering, zelfde
    normalisatie als de duplicaatpoort), bedrag cent-exact, identiteitscluster gesorteerd."""
    delen = [
        str(vendor_id or ""),
        ",".join(sorted(str(v) for v in identiteit_vendor_ids if v is not None and v != vendor_id)),
        normaliseer_referentie(referentie) or "",
        factuurdatum.isoformat() if factuurdatum else "",
        f"{totaalbedrag:.2f}" if totaalbedrag is not None else "",
        (factuur_iban or "").replace(" ", "").upper(),
        str(boek_cyclus),
        backend,
    ]
    return hashlib.sha256("|".join(delen).encode()).hexdigest()


def _resultaat_json(r: CheckResultaat | None) -> dict | None:
    if r is None:
        return None
    return {"naam": r.naam, "ok": r.ok, "melding": r.melding, "signaal": r.signaal}


def _resultaat_uit(d: dict | None) -> CheckResultaat | None:
    if not d:
        return None
    return CheckResultaat(d["naam"], bool(d["ok"]), d["melding"], signaal=bool(d.get("signaal", False)))


@dataclass(frozen=True)
class ExternRapport:
    """Uitkomst van het externe deel — precies wat `voer_harde_checks_uit` nodig heeft náást de lokale checks."""

    gecontroleerd_op: datetime
    vertrouwde_ibans: tuple[str, ...] = ()
    baseline_vastgelegd: bool = False
    seed_mislukt: bool = False
    duplicaat: CheckResultaat | None = None
    duplicaat_over_crediteuren: CheckResultaat | None = None
    #: verbinding kon niet geopend worden / onverwachte fout — storings-tak, nooit cachen
    storing: str | None = None
    #: Odoo-crediteur zonder partner-koppeling (blok D 07-09) — stabiele, blokkerende toestand
    crediteur_niet_gekoppeld: str | None = None
    #: CACHE-modus zonder geldige cache: externe rijen "loopt nog" (blokkerend), nooit cachen
    nog_niet: bool = False
    uit_cache: bool = False
    duur_ms: dict[str, float] = field(default_factory=dict)

    @property
    def cachebaar(self) -> bool:
        if self.storing or self.nog_niet:
            return False
        if self.duplicaat is not None and self.duplicaat.melding.startswith(STORING_PREFIX):
            return False
        return True

    @property
    def is_storings_tak(self) -> bool:
        return bool(self.storing or self.crediteur_niet_gekoppeld or self.nog_niet)

    def naar_json(self) -> dict[str, Any]:
        return {
            "gecontroleerd_op": self.gecontroleerd_op.isoformat(),
            "vertrouwde_ibans": list(self.vertrouwde_ibans),
            "baseline_vastgelegd": self.baseline_vastgelegd,
            "seed_mislukt": self.seed_mislukt,
            "duplicaat": _resultaat_json(self.duplicaat),
            "duplicaat_over_crediteuren": _resultaat_json(self.duplicaat_over_crediteuren),
            "crediteur_niet_gekoppeld": self.crediteur_niet_gekoppeld,
            "duur_ms": dict(self.duur_ms),
        }

    @classmethod
    def uit_json(cls, d: dict[str, Any]) -> ExternRapport:
        return cls(
            gecontroleerd_op=datetime.fromisoformat(d["gecontroleerd_op"]),
            vertrouwde_ibans=tuple(d.get("vertrouwde_ibans") or ()),
            baseline_vastgelegd=bool(d.get("baseline_vastgelegd", False)),
            seed_mislukt=bool(d.get("seed_mislukt", False)),
            duplicaat=_resultaat_uit(d.get("duplicaat")),
            duplicaat_over_crediteuren=_resultaat_uit(d.get("duplicaat_over_crediteuren")),
            crediteur_niet_gekoppeld=d.get("crediteur_niet_gekoppeld"),
            uit_cache=True,
            duur_ms=dict(d.get("duur_ms") or {}),
        )

    @classmethod
    def nog_niet_gecontroleerd(cls, nu: datetime) -> ExternRapport:
        return cls(
            gecontroleerd_op=nu,
            duplicaat=CheckResultaat("Duplicaatcheck", False, NOG_NIET_MELDING),
            duplicaat_over_crediteuren=CheckResultaat("Duplicaat bij andere crediteur", True, NOG_NIET_MELDING),
            nog_niet=True,
        )


def lees_cache(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> CheckExternCache | None:
    with scoped_session(administratie_id) as session:
        rij = session.scalar(select(CheckExternCache).where(CheckExternCache.document_id == document_id))
        if rij is None:
            return None
        session.expunge(rij)
        return rij


def is_geldig(rij: CheckExternCache | None, *, vingerafdruk: str, nu: datetime | None = None) -> bool:
    """Geldig = zelfde vingerafdruk én niet ouder dan `settings.checks_extern_cache_minuten`."""
    if rij is None or rij.vingerafdruk != vingerafdruk:
        return False
    nu = nu or datetime.now(UTC)
    g = rij.gecontroleerd_op
    gecontroleerd = g.astimezone(UTC) if g.tzinfo else g.replace(tzinfo=UTC)
    return nu - gecontroleerd <= timedelta(minutes=settings.checks_extern_cache_minuten)


def schrijf_cache(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    vingerafdruk: str,
    rapport: ExternRapport,
    backend: str,
) -> None:
    """Eén rij per document (UPDATE bij bestaan). Nooit raise-n richting de checks: een niet-geschreven cache kost
    alleen de volgende run wat seconden."""
    try:
        with scoped_session(administratie_id) as session:
            rij = session.scalar(select(CheckExternCache).where(CheckExternCache.document_id == document_id))
            if rij is None:
                session.add(
                    CheckExternCache(
                        document_id=document_id,
                        administratie_id=administratie_id,
                        vingerafdruk=vingerafdruk,
                        rapport=rapport.naar_json(),
                        gecontroleerd_op=rapport.gecontroleerd_op,
                        backend=backend,
                    )
                )
            else:
                rij.vingerafdruk = vingerafdruk
                rij.rapport = rapport.naar_json()
                rij.gecontroleerd_op = rapport.gecontroleerd_op
                rij.backend = backend
    except Exception:  # noqa: BLE001 — cache is een versneller, nooit een poort
        logger.exception("check_extern_cache niet geschreven voor document %s", document_id)


def voer_parallel_uit(*, taken: dict[str, Any], max_workers: int = 3) -> tuple[dict[str, Any], dict[str, float]]:
    """Voert de (naam → callable)-taken parallel uit en geeft (uitkomsten, duur per taak in ms) terug. Een exception
    in één taak wordt als uitkomst doorgegeven (de aanroeper beslist — de seed-taak kan `CrediteurNietGekoppeld`
    geven, dat is een leesbare toestand, geen crash)."""
    uitkomsten: dict[str, Any] = {}
    duur: dict[str, float] = {}

    def _run(naam: str, fn: Any) -> tuple[str, Any, float]:
        t0 = time.perf_counter()
        try:
            return naam, fn(), (time.perf_counter() - t0) * 1000
        except Exception as exc:  # noqa: BLE001 — de aanroeper classificeert
            return naam, exc, (time.perf_counter() - t0) * 1000

    workers = max(1, min(max_workers, len(taken) or 1))
    with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="checks-extern") as pool:
        for naam, uitkomst, ms in pool.map(lambda kv: _run(*kv), taken.items()):
            uitkomsten[naam] = uitkomst
            duur[naam] = round(ms, 1)
    return uitkomsten, duur
