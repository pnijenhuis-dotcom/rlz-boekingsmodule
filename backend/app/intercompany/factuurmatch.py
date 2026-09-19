"""Intercompany-factuurmatch — dagelijks reconciliatieblok `intercompany` (opdracht Peter 16-09, blok B).

Peter: "Als Universal Verkoop een verkoopfactuur heeft staan aan Universal Nederland maar Universal Nederland heeft
die factuur niet bij inkopen staan dan wil ik het weten (en dat voor al onze boekhoudingen)."

Wat dit blok doet — en bewust níét:
- Voor élk actief IC-paar (`app/intercompany/relaties.py::actieve_paren`, blok A) worden de paren tot HANDELSRELATIES
  (verkoper-administratie → ontvanger-administratie) samengevouwen: de verkoopfacturen van A aan de entity die B in A
  voorstelt ↔ de inkoopfacturen van B van de entity die A in B voorstelt. Beide richtingen van hetzelfde paar (A ziet
  B als debiteur, B ziet A als crediteur) zijn ÉÉN handelsrelatie; meerdere entity-records voor dezelfde tegenpartij
  (crediteur-dubbelen) reizen als set mee in het server-side `$filter`.
- Lezen is LEES-ONLY en server-side gefilterd op Entity-id's + datumvenster (default `VENSTER_DAGEN`), gepagineerd
  met een harde bovengrens — het aantal calls per administratie hangt af van het aantal handelsrelaties en pagina's,
  nooit van het aantal facturen. Backend-agnostisch: RLZ (verkoop = `SalesInvoices` ∪ `Receipts` — de
  SalesInvoices-collectie ziet API-aangemaakte facturen niet, zie `VERKOOP_COLLECTIES`; inkoop = `PurchaseInvoices`)
  én Odoo
  (`account.move` out_/in_invoice + refunds) via de bestaande clients/ports; een RLZ↔Odoo-paar werkt gewoon.
- De match zelf is PUUR (`match_paar`): verrekenparen (factuur + creditnota, zelfde nummer-stam of som 0 binnen 7 d)
  eerst samenvouwen; daarna verkoop ↔ inkoop op (1) factuurnummer als heel token / gelijk (zelfde normalisatie als
  `rlz_dubbel`: `app/documenten/referentie.py`), (2) bedrag cent-exact + datum ± 7 d, (3) bedrag cent-exact zonder
  datum (`zeker=False`, nooit een bevinding). Soorten: `ic_ontbreekt_bij_ontvanger` (tenzij het nummer in de module
  van B nog onderweg is — dat is GEEN bevinding), `ic_ontbreekt_bij_verkoper`, `ic_bedrag_verschilt`,
  `ic_status_verschilt` (alleen ouder dan 7 dagen).
- Doorbelasting-spiegelparen uit onze eigen motor (`doorbelasting_boeking` verkoop_rlz_id ↔ spiegel_rlz_id) MOETEN
  100 % groen zijn: een rood paar is een systeemfout (bevinding `fout` zonder administratie → systeemmail; audit
  `automatisering_regressie` waarop de bewaking alarmeert), geen kantoor-bevinding.
- `RlzWebfilterError` = "RLZ-blokkering — meting ongeldig" voor die administratie: geen bevindingen, geen halve data.
  Geen credential / geen Odoo-koppeling = zichtbaar OVERGESLAGEN (KP 6: nooit een stille no-op).
- Acceptatie-met-reden loopt over `app/reconciliatie/service.py::beoordeel` (bron `intercompany`); de vingerafdruk is
  stabiel per paar (administraties + nummer + bedragen), nooit een datum van vandaag.

Geen AI, geen enkele write naar RLZ of Odoo."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select

from app.bank.matchmotor import referentie_als_token
from app.documenten.referentie import normaliseer_referentie
from app.rlz.client import RlzClient, RlzWebfilterError

logger = logging.getLogger(__name__)

BLOK = "intercompany"
ACCEPTATIE_BRON = "intercompany"  # == ReconciliatieBron.INTERCOMPANY.value
#: Default-venster (beslispunt 1, default gekozen): 400 dagen terug vanaf vandaag (NL-kalenderdag).
VENSTER_DAGEN = 400
#: Datumtolerantie bij de bedrag+datum-match én bij verrekenparen op som 0.
DATUM_TOLERANTIE_DAGEN = 7
#: Beslispunt 4 (default): een status-verschil (concept ↔ geboekt) telt pas als de factuur ouder is dan 7 dagen.
STATUS_VERSCHIL_NA_DAGEN = 7
#: Paginering van de leesroutes — begrensd zodat een webfilter-blokkering nooit uit een runaway-lus komt.
PER_PAGINA = 200
MAX_PAGINAS = 10
_MIN_STAM_LENGTE = 4

SOORT_ONTBREEKT_BIJ_ONTVANGER = "ic_ontbreekt_bij_ontvanger"
SOORT_ONTBREEKT_BIJ_VERKOPER = "ic_ontbreekt_bij_verkoper"
SOORT_BEDRAG_VERSCHILT = "ic_bedrag_verschilt"
SOORT_STATUS_VERSCHILT = "ic_status_verschilt"
SOORT_SPIEGEL_ROOD = "ic_spiegel_rood"
SOORTEN = (
    SOORT_ONTBREEKT_BIJ_ONTVANGER,
    SOORT_ONTBREEKT_BIJ_VERKOPER,
    SOORT_BEDRAG_VERSCHILT,
    SOORT_STATUS_VERSCHILT,
)

REGEL_NUMMER = "nummer"
REGEL_BEDRAG_DATUM = "bedrag_datum"
REGEL_BEDRAG = "bedrag"

WEBFILTER_ONGELDIG = "RLZ-blokkering — meting ongeldig"
GEEN_CREDENTIAL = "overgeslagen — geen RLZ-credential (webservice-login) voor deze administratie"
GEEN_ODOO_KOPPELING = "overgeslagen — geen Odoo-koppeling voor deze administratie"
TEGENRELATIE_ONBEKEND = "IC-tegenrelatie in de ontvangende administratie onbekend — inkoopkant niet gelezen"
ODOO_PARTNER_ONBEKEND = "IC-entity niet vertaalbaar naar een Odoo-partner — kant niet gelezen"
SPIEGEL_SYSTEEMFOUT = "Systeemfout — doorbelastingspaar niet sluitend"

_NAMESPACE = uuid.UUID("7c1d9f2e-16c9-5a4e-9b3d-1c0f0e0a0b0c")


# ---- genormaliseerde factuurvorm ---------------------------------------------------------------------


@dataclass(frozen=True)
class IcFactuur:
    """Eén factuur in één genormaliseerde vorm, onafhankelijk van RLZ/Odoo. `bedrag` is GETEKEND: een creditnota
    is negatief (RLZ `IsCreditInvoice`/negatief `BaseInvoiceAmount`, Odoo out_refund/in_refund). `nummer` is voor de
    verkoopkant het eigen factuurnummer (RLZ `InvoiceNumber`, Odoo `name`), voor de inkoopkant de referentie van de
    leverancier (RLZ `Reference`, Odoo `ref`); `nummer_norm` is de ene vergelijkingsvorm."""

    id: str
    administratie_id: uuid.UUID
    kant: str  # 'verkoop' | 'inkoop'
    nummer: str | None
    nummer_norm: str | None
    bedrag: Decimal
    datum: date
    status: int  # 1 concept / 2 open / 3 gesloten
    boekstuk: str | None = None

    @property
    def is_credit(self) -> bool:
        return self.bedrag < 0


def maak_factuur(
    *,
    id: str,  # noqa: A002 — spiegelt de RLZ-/Odoo-veldnaam
    administratie_id: uuid.UUID,
    kant: str,
    nummer: str | None,
    bedrag: Decimal,
    datum: date,
    status: int,
    boekstuk: str | None = None,
) -> IcFactuur:
    return IcFactuur(
        id=str(id),
        administratie_id=administratie_id,
        kant=kant,
        nummer=nummer,
        nummer_norm=normaliseer_referentie(nummer),
        bedrag=bedrag.quantize(Decimal("0.01")),
        datum=datum,
        status=int(status),
        boekstuk=boekstuk,
    )


@dataclass(frozen=True)
class Groep:
    """Een factuur óf een verrekenpaar (factuur + creditnota) als één te matchen eenheid."""

    facturen: tuple[IcFactuur, ...]

    @property
    def leidend(self) -> IcFactuur:
        return self.facturen[0]

    @property
    def bedrag(self) -> Decimal:
        return sum((f.bedrag for f in self.facturen), Decimal("0.00"))

    @property
    def nummer(self) -> str | None:
        return self.leidend.nummer

    @property
    def nummer_norm(self) -> str | None:
        return self.leidend.nummer_norm

    @property
    def datum(self) -> date:
        return self.leidend.datum

    @property
    def status(self) -> int:
        return max(f.status for f in self.facturen)

    @property
    def boekstuk(self) -> str | None:
        return self.leidend.boekstuk or self.leidend.nummer

    @property
    def ids(self) -> frozenset[str]:
        return frozenset(f.id for f in self.facturen)

    @property
    def is_verrekend(self) -> bool:
        return len(self.facturen) > 1


@dataclass(frozen=True)
class Match:
    verkoop: Groep
    inkoop: Groep
    regel: str  # REGEL_NUMMER | REGEL_BEDRAG_DATUM | REGEL_BEDRAG

    @property
    def zeker(self) -> bool:
        return self.regel != REGEL_BEDRAG

    @property
    def delta(self) -> Decimal:
        return self.verkoop.bedrag - self.inkoop.bedrag


@dataclass(frozen=True)
class IcBevinding:
    """Eén afwijking. `administratie_id` = waar de handeling ligt (ontbreekt_bij_ontvanger/bedrag/status → B, de
    ontvanger; ontbreekt_bij_verkoper → A, de verkoper). `detail` is stabiel per paar (administraties + nummer +
    bedragen — geen datum van vandaag): dat is de acceptatie-sleutel. `extra` = leesbare velden voor teksten/UI."""

    soort: str
    administratie_id: uuid.UUID
    record_id: uuid.UUID
    detail: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def vingerafdruk(self) -> str:
        from app.reconciliatie.service import vingerafdruk

        return vingerafdruk(bron=ACCEPTATIE_BRON, soort=self.soort, detail=self.detail)


@dataclass(frozen=True)
class MatchUitkomst:
    matches: tuple[Match, ...]
    bevindingen: tuple[IcBevinding, ...]
    onderweg: tuple[Groep, ...]  # verkoop zonder inkoop, maar het nummer staat in de module van B nog open
    verrekend_zonder_tegenkant: tuple[Groep, ...]  # netto-0-paren zonder tegenkant: geen bevinding, wél teller
    aantal_verkoop: int
    aantal_inkoop: int


# ---- puur: verrekenparen ------------------------------------------------------------------------------


def _zelfde_stam(a: str | None, b: str | None) -> bool:
    if not a or not b or len(min(a, b, key=len)) < _MIN_STAM_LENGTE:
        return False
    return a == b or a.startswith(b) or b.startswith(a)


def vouw_verrekenparen(facturen: Sequence[IcFactuur]) -> list[Groep]:
    """Factuur + creditnota van dezelfde kant als één groep: creditnota's zoeken een nog vrije positieve factuur met
    dezelfde nummer-stam ("2026-0123" ↔ "2026-0123-C"), anders één waarvan het bedrag exact tegengesteld is binnen
    `DATUM_TOLERANTIE_DAGEN`. Deterministisch: gesorteerd op datum, id."""
    positief = sorted((f for f in facturen if f.bedrag >= 0), key=lambda f: (f.datum, f.id))
    credits = sorted((f for f in facturen if f.bedrag < 0), key=lambda f: (f.datum, f.id))
    gebruikt: set[str] = set()
    groepen: list[Groep] = []
    los_credit: list[IcFactuur] = []
    for c in credits:
        partner: IcFactuur | None = None
        for p in positief:
            if p.id in gebruikt:
                continue
            if _zelfde_stam(c.nummer_norm, p.nummer_norm):
                partner = p
                break
        if partner is None:
            for p in positief:
                if p.id in gebruikt:
                    continue
                if p.bedrag == -c.bedrag and abs((p.datum - c.datum).days) <= DATUM_TOLERANTIE_DAGEN:
                    partner = p
                    break
        if partner is None:
            los_credit.append(c)
            continue
        gebruikt.add(partner.id)
        groepen.append(Groep(facturen=(partner, c)))
    for p in positief:
        if p.id not in gebruikt:
            groepen.append(Groep(facturen=(p,)))
    groepen.extend(Groep(facturen=(c,)) for c in los_credit)
    return sorted(groepen, key=lambda g: (g.datum, g.leidend.id))


# ---- puur: match -----------------------------------------------------------------------------------


def _nummer_match(v: Groep, i: Groep) -> bool:
    if v.nummer_norm is None or i.nummer_norm is None:
        return False
    if v.nummer_norm == i.nummer_norm:
        return True
    return referentie_als_token(v.nummer, i.nummer)


def _kies(kandidaten: list[Groep], v: Groep) -> Groep:
    return min(kandidaten, key=lambda i: (abs((i.datum - v.datum).days), i.leidend.id))


def match_groepen(verkoop: Sequence[Groep], inkoop: Sequence[Groep]) -> tuple[list[Match], list[Groep], list[Groep]]:
    """Drie ronden in vaste volgorde; elke groep matcht hooguit één keer. → (matches, verkoop_rest, inkoop_rest)."""
    vrij_i = list(inkoop)
    rest_v: list[Groep] = []
    matches: list[Match] = []

    def ronde(regel: str, bron: list[Groep], toets: Callable[[Groep, Groep], bool]) -> list[Groep]:
        over: list[Groep] = []
        for v in bron:
            kandidaten = [i for i in vrij_i if toets(v, i)]
            if not kandidaten:
                over.append(v)
                continue
            i = _kies(kandidaten, v)
            vrij_i.remove(i)
            matches.append(Match(verkoop=v, inkoop=i, regel=regel))
        return over

    rest_v = ronde(REGEL_NUMMER, list(verkoop), _nummer_match)
    rest_v = ronde(
        REGEL_BEDRAG_DATUM,
        rest_v,
        lambda v, i: v.bedrag == i.bedrag and abs((v.datum - i.datum).days) <= DATUM_TOLERANTIE_DAGEN,
    )
    rest_v = ronde(REGEL_BEDRAG, rest_v, lambda v, i: v.bedrag == i.bedrag)
    return matches, rest_v, vrij_i


def _record_uuid(waarde: str | None, terugval: str) -> uuid.UUID:
    try:
        return uuid.UUID(str(waarde))
    except (ValueError, TypeError, AttributeError):
        return uuid.uuid5(_NAMESPACE, terugval)


def _euro(bedrag: Decimal | None) -> str | None:
    return None if bedrag is None else f"{bedrag:.2f}"


def _basis_extra(
    *,
    verkoper_id: uuid.UUID,
    ontvanger_id: uuid.UUID,
    verkoper_naam: str | None,
    ontvanger_naam: str | None,
    verkoop: Groep | None,
    inkoop: Groep | None,
    regel: str | None,
) -> dict[str, Any]:
    nummer = (verkoop.nummer if verkoop else None) or (inkoop.nummer if inkoop else None)
    bedrag_v = verkoop.bedrag if verkoop else None
    bedrag_i = inkoop.bedrag if inkoop else None
    leidend = verkoop or inkoop
    return {
        "nummer": nummer,
        "bedrag_verkoop": _euro(bedrag_v),
        "bedrag_inkoop": _euro(bedrag_i),
        "delta": _euro(bedrag_v - bedrag_i) if bedrag_v is not None and bedrag_i is not None else None,
        "datum": leidend.datum.isoformat() if leidend is not None else None,
        "verkoper_naam": verkoper_naam,
        "ontvanger_naam": ontvanger_naam,
        "verkoper_administratie_id": str(verkoper_id),
        "ontvanger_administratie_id": str(ontvanger_id),
        "boekstuk_a": verkoop.boekstuk if verkoop else None,
        "boekstuk_b": inkoop.boekstuk if inkoop else None,
        "status_a": str(verkoop.status) if verkoop else None,
        "status_b": str(inkoop.status) if inkoop else None,
        "verkoop_ids": sorted(verkoop.ids) if verkoop else [],
        "inkoop_ids": sorted(inkoop.ids) if inkoop else [],
        "regel": regel,
        "verrekend": bool((verkoop and verkoop.is_verrekend) or (inkoop and inkoop.is_verrekend)),
    }


def match_paar(
    paar: Any,
    *,
    verkoop: Sequence[IcFactuur],
    inkoop: Sequence[IcFactuur],
    module_onderweg: set[str],
    nu: date,
    verkoper_naam: str | None = None,
    ontvanger_naam: str | None = None,
) -> list[IcBevinding]:
    """Contractvorm (CONTRACT_2 § factuurmatch.py): bevindingen voor één IC-paar/handelsrelatie. `paar` levert de
    verkoper-/ontvanger-administratie (zie `handelsrelatie_van`); de volledige uitkomst incl. matches en tellers geeft
    `match_facturen`."""
    rel = handelsrelatie_van(paar)
    return list(
        match_facturen(
            verkoper_id=rel.verkoper_id,
            ontvanger_id=rel.ontvanger_id,
            verkoop=verkoop,
            inkoop=inkoop,
            module_onderweg=module_onderweg,
            nu=nu,
            verkoper_naam=verkoper_naam,
            ontvanger_naam=ontvanger_naam,
        ).bevindingen
    )


def match_facturen(
    *,
    verkoper_id: uuid.UUID,
    ontvanger_id: uuid.UUID,
    verkoop: Sequence[IcFactuur],
    inkoop: Sequence[IcFactuur],
    module_onderweg: set[str],
    nu: date,
    verkoper_naam: str | None = None,
    ontvanger_naam: str | None = None,
) -> MatchUitkomst:
    """De pure kern. Zie module-docstring voor de regels."""
    groepen_v = vouw_verrekenparen(verkoop)
    groepen_i = vouw_verrekenparen(inkoop)
    matches, rest_v, rest_i = match_groepen(groepen_v, groepen_i)
    paar_sleutel = f"paar={verkoper_id}>{ontvanger_id}"

    def extra(v: Groep | None, i: Groep | None, regel: str | None) -> dict[str, Any]:
        return _basis_extra(
            verkoper_id=verkoper_id,
            ontvanger_id=ontvanger_id,
            verkoper_naam=verkoper_naam,
            ontvanger_naam=ontvanger_naam,
            verkoop=v,
            inkoop=i,
            regel=regel,
        )

    bevindingen: list[IcBevinding] = []
    for m in matches:
        if not m.zeker:
            continue
        nummer = m.verkoop.nummer or m.inkoop.nummer or "?"
        if m.regel == REGEL_NUMMER and m.delta != 0:
            bevindingen.append(
                IcBevinding(
                    soort=SOORT_BEDRAG_VERSCHILT,
                    administratie_id=ontvanger_id,
                    record_id=_record_uuid(m.inkoop.leidend.id, f"{paar_sleutel}|{nummer}|bedrag"),
                    detail=(
                        f"{paar_sleutel} nummer={nummer} verkoop={_euro(m.verkoop.bedrag)} "
                        f"inkoop={_euro(m.inkoop.bedrag)} delta={_euro(m.delta)}"
                    ),
                    extra=extra(m.verkoop, m.inkoop, m.regel),
                )
            )
            continue  # bedrag-verschil dekt het paar; status-verschil daarbovenop is ruis
        concept_v, concept_i = m.verkoop.status == 1, m.inkoop.status == 1
        if concept_v != concept_i:
            concept = m.verkoop if concept_v else m.inkoop
            if (nu - concept.datum).days > STATUS_VERSCHIL_NA_DAGEN:
                bevindingen.append(
                    IcBevinding(
                        soort=SOORT_STATUS_VERSCHILT,
                        administratie_id=ontvanger_id,
                        record_id=_record_uuid(m.inkoop.leidend.id, f"{paar_sleutel}|{nummer}|status"),
                        detail=(
                            f"{paar_sleutel} nummer={nummer} status_verkoop={m.verkoop.status} "
                            f"status_inkoop={m.inkoop.status}"
                        ),
                        extra={
                            **extra(m.verkoop, m.inkoop, m.regel),
                            "concept_kant": "verkoop" if concept_v else "inkoop",
                        },
                    )
                )

    onderweg: list[Groep] = []
    verrekend_leeg: list[Groep] = []
    for v in rest_v:
        if v.is_verrekend and v.bedrag == 0:
            verrekend_leeg.append(v)
            continue
        if v.nummer_norm and v.nummer_norm in module_onderweg:
            onderweg.append(v)
            continue
        nummer = v.nummer or v.leidend.id
        bevindingen.append(
            IcBevinding(
                soort=SOORT_ONTBREEKT_BIJ_ONTVANGER,
                administratie_id=ontvanger_id,
                record_id=uuid.uuid5(_NAMESPACE, f"{paar_sleutel}|{v.nummer_norm or v.leidend.id}|ontvanger"),
                detail=f"{paar_sleutel} nummer={nummer} bedrag={_euro(v.bedrag)} datum={v.datum.isoformat()}",
                extra=extra(v, None, None),
            )
        )
    for i in rest_i:
        if i.is_verrekend and i.bedrag == 0:
            verrekend_leeg.append(i)
            continue
        nummer = i.nummer or i.leidend.id
        bevindingen.append(
            IcBevinding(
                soort=SOORT_ONTBREEKT_BIJ_VERKOPER,
                administratie_id=verkoper_id,
                record_id=uuid.uuid5(_NAMESPACE, f"{paar_sleutel}|{i.nummer_norm or i.leidend.id}|verkoper"),
                detail=f"{paar_sleutel} nummer={nummer} bedrag={_euro(i.bedrag)} datum={i.datum.isoformat()}",
                extra=extra(None, i, None),
            )
        )
    return MatchUitkomst(
        matches=tuple(matches),
        bevindingen=tuple(bevindingen),
        onderweg=tuple(onderweg),
        verrekend_zonder_tegenkant=tuple(verrekend_leeg),
        aantal_verkoop=len(verkoop),
        aantal_inkoop=len(inkoop),
    )


# ---- handelsrelaties uit IC-paren ------------------------------------------------------------------------


@dataclass(frozen=True)
class Handelsrelatie:
    """Verkoper → ontvanger mét de entity-id's aan beide kanten (sets: crediteur-dubbelen)."""

    verkoper_id: uuid.UUID
    ontvanger_id: uuid.UUID
    verkoop_entity_ids: frozenset[uuid.UUID]  # debiteur-records in de verkoper die de ontvanger voorstellen
    inkoop_entity_ids: frozenset[uuid.UUID]  # crediteur-records in de ontvanger die de verkoper voorstellen
    bases: frozenset[str] = frozenset()

    @property
    def sleutel(self) -> tuple[uuid.UUID, uuid.UUID]:
        return (self.verkoper_id, self.ontvanger_id)


def handelsrelatie_van(paar: Any) -> Handelsrelatie:
    """Eén `Paar` (blok A) → handelsrelatie. `richting` is vanuit A gezien: 'debiteur' = A verkoopt aan B
    (entity_in_a is een klant in A), 'crediteur' = B levert aan A (entity_in_a is een leverancier in A). `entity_in_b`
    is optioneel
    (tegenrelatie); ontbreekt hij, dan vult `bouw_handelsrelaties` 'm uit het spiegelbeeld-paar."""
    a = uuid.UUID(str(paar.administratie_a_id))
    b = uuid.UUID(str(paar.administratie_b_id))
    e_a = uuid.UUID(str(paar.entity_in_a))
    e_b_ruw = getattr(paar, "entity_in_b", None)
    e_b = uuid.UUID(str(e_b_ruw)) if e_b_ruw else None
    basis = frozenset({str(getattr(paar, "basis", "") or "")} - {""})
    if str(paar.richting) == "debiteur":
        return Handelsrelatie(
            verkoper_id=a,
            ontvanger_id=b,
            verkoop_entity_ids=frozenset({e_a}),
            inkoop_entity_ids=frozenset({e_b} if e_b else ()),
            bases=basis,
        )
    return Handelsrelatie(
        verkoper_id=b,
        ontvanger_id=a,
        verkoop_entity_ids=frozenset({e_b} if e_b else ()),
        inkoop_entity_ids=frozenset({e_a}),
        bases=basis,
    )


def bouw_handelsrelaties(paren: Iterable[Any]) -> list[Handelsrelatie]:
    """Alle paren samengevouwen per (verkoper, ontvanger): entity-sets verenigd, beide richtingen één relatie."""
    per_sleutel: dict[tuple[uuid.UUID, uuid.UUID], Handelsrelatie] = {}
    for paar in paren:
        rel = handelsrelatie_van(paar)
        bestaand = per_sleutel.get(rel.sleutel)
        if bestaand is None:
            per_sleutel[rel.sleutel] = rel
            continue
        per_sleutel[rel.sleutel] = Handelsrelatie(
            verkoper_id=rel.verkoper_id,
            ontvanger_id=rel.ontvanger_id,
            verkoop_entity_ids=bestaand.verkoop_entity_ids | rel.verkoop_entity_ids,
            inkoop_entity_ids=bestaand.inkoop_entity_ids | rel.inkoop_entity_ids,
            bases=bestaand.bases | rel.bases,
        )
    return sorted(per_sleutel.values(), key=lambda r: (str(r.verkoper_id), str(r.ontvanger_id)))


# ---- lezers: RLZ -----------------------------------------------------------------------------------------


def _als_datum(waarde: object) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(str(waarde)[:10])
    except ValueError:
        return None


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _rlz_naar_factuur(rij: dict[str, Any], *, administratie_id: uuid.UUID, kant: str) -> IcFactuur | None:
    bedrag = _als_decimal(rij.get("BaseInvoiceAmount"))
    datum = _als_datum(rij.get("Date") or rij.get("BookDate"))
    if bedrag is None or datum is None or not rij.get("id"):
        return None
    if rij.get("IsCreditInvoice") and bedrag > 0:
        bedrag = -bedrag
    if kant == "verkoop":
        nummer_ruw = rij.get("InvoiceNumber")
        nummer = str(nummer_ruw) if nummer_ruw not in (None, "") else (rij.get("Reference") or None)
        boekstuk = rij.get("ReceiptNumber") or (str(nummer_ruw) if nummer_ruw not in (None, "") else None)
    else:
        nummer = rij.get("Reference") or None
        boekstuk = rij.get("ReceiptNumber") or None
    try:
        status = int(rij.get("Status") or 0)
    except (TypeError, ValueError):
        status = 0
    return maak_factuur(
        id=str(rij["id"]),
        administratie_id=administratie_id,
        kant=kant,
        nummer=nummer,
        bedrag=bedrag,
        datum=datum,
        status=status,
        boekstuk=boekstuk,
    )


def _entity_filter(entity_ids: Iterable[uuid.UUID | str]) -> str:
    ids = sorted(str(e) for e in entity_ids if e)
    filter_ = " or ".join(f"Entity/id eq {e}" for e in ids)
    return f"({filter_})" if len(ids) > 1 else filter_


#: RLZ `DocumentType` van een verkoopfactuur (Receipts-verkenning 07-08: "een Receipt ís een SalesInvoice", type 10;
#: STAP-0 19-09 op Kempen Facilities: álle SalesInvoices-records — UI én API — dragen `DocumentType: 10`). De
#: Receipts-collectie is op sommige administraties een UNIE van álle documenten (VGG 12-09: ook PurchaseInvoices type 1
#: en bank-directe boekingen type 19), dus een Receipts-rij telt hier alleen als verkoop met dit type.
RECEIPTS_DOCUMENTTYPE_VERKOOP = 10
#: De twee collecties die samen de verkoopkant dekken (STAP-0 19-09, opdracht ic_spiegel_rood 174×): de
#: `SalesInvoices`-COLLECTIE ziet API-aangemaakte verkoopfacturen NIET (gedocumenteerd sinds Omzetmodule STAP 0 §2 en
#: de kliktest-nazorg 16-08 punt 5; live herbevestigd 19-09: `SalesInvoices?$filter=InvoiceNumber eq 24713275` →
#: count 0 terwijl `SalesInvoices/{id}` 200 geeft), de `Receipts`-collectie ziet ze WÉL mét dezelfde
#: `Entity/id`-/`Date`-filters, `$expand=Entity` en `$orderby` (count 8 op KF → Mantelzorgwoningen sinds 01-08).
#: Vóór 19-09 las dit blok alleen SalesInvoices: élke doorbelastings-, Vastly- of omzet-verkoop van de module was
#: onzichtbaar → 174 × `ic_spiegel_rood` "verkoopfactuur niet gevonden bij de bron-administratie" (systeemfout).
VERKOOP_COLLECTIES: tuple[str, ...] = ("SalesInvoices", "Receipts")


def _lees_verkoop_collectie(client: RlzClient, collectie: str, filter_: str) -> list[dict[str, Any]]:
    rijen: list[dict[str, Any]] = []
    for pagina in range(MAX_PAGINAS):
        params = {
            "$filter": filter_,
            "$expand": "Entity",
            "$orderby": "Date asc,id asc",
            "$top": str(PER_PAGINA),
            "$skip": str(pagina * PER_PAGINA),
        }
        deel = client.get(collectie, params=params).get("value", [])
        rijen.extend(deel)
        if len(deel) < PER_PAGINA:
            break
    return rijen


def _is_verkoop_rij(rij: dict[str, Any], *, collectie: str) -> bool:
    """SalesInvoices-rijen zijn per definitie verkoop; een Receipts-rij alleen mét `DocumentType` 10 (of zonder het
    veld — oudere responsvorm, dan beslist de Entity-filter)."""
    if collectie != "Receipts":
        return True
    soort = rij.get("DocumentType")
    if soort in (None, ""):
        return True
    try:
        return int(soort) == RECEIPTS_DOCUMENTTYPE_VERKOOP
    except (TypeError, ValueError):
        return False


def lees_verkoop_rlz(
    client: RlzClient, entity_ids: Iterable[uuid.UUID | str], van: date, tot: date, *, administratie_id: uuid.UUID
) -> list[IcFactuur]:
    """Verkoopfacturen van de verkoper aan de IC-entity's = de UNIE van de `SalesInvoices`- en de `Receipts`-collectie
    (zie `VERKOOP_COLLECTIES`), ontdubbeld op `id` (SalesInvoices-rij wint), Receipts alleen `DocumentType` 10. Zelfde
    server-side filter op beide (STAP-0 16-09 + 19-09: `InvoiceNumber` int, `Reference`, `Entity{id, Name}` alleen mét
    `$expand`, `BaseInvoiceAmount`, `Date`, `Status`, `IsCreditInvoice`; datumfilter `Date ge …T00:00:00Z`).
    Gepagineerd ≤ MAX_PAGINAS per collectie."""
    ids = [e for e in entity_ids if e]
    if not ids:
        return []
    filter_ = f"{_entity_filter(ids)} and Date ge {van.isoformat()}T00:00:00Z and Date le {tot.isoformat()}T23:59:59Z"
    per_id: dict[str, dict[str, Any]] = {}
    for collectie in VERKOOP_COLLECTIES:
        for rij in _lees_verkoop_collectie(client, collectie, filter_):
            rid = str(rij.get("id") or "").lower()
            if not rid or rid in per_id or not _is_verkoop_rij(rij, collectie=collectie):
                continue
            per_id[rid] = rij
    uit = [_rlz_naar_factuur(r, administratie_id=administratie_id, kant="verkoop") for r in per_id.values()]
    return [f for f in uit if f is not None]


def lees_inkoop_rlz(
    client: RlzClient, entity_ids: Iterable[uuid.UUID | str], van: date, tot: date, *, administratie_id: uuid.UUID
) -> list[IcFactuur]:
    """PurchaseInvoices van de ontvanger van de IC-entity's — de bestaande leesroute van de Zenvoices-fix (16-09)."""
    ids = [e for e in entity_ids if e]
    if not ids:
        return []
    rijen = client.find_purchase_invoices_kandidaten(
        vendor_ids=ids, van=van, tot=tot, per_pagina=PER_PAGINA, max_paginas=MAX_PAGINAS
    )
    uit = [_rlz_naar_factuur(r, administratie_id=administratie_id, kant="inkoop") for r in rijen]
    return [f for f in uit if f is not None]


# ---- lezers: Odoo ----------------------------------------------------------------------------------------

_ODOO_VELDEN = ["name", "ref", "invoice_date", "amount_total", "state", "payment_state", "move_type", "partner_id"]


def _odoo_status(rij: dict[str, Any]) -> int:
    """Zelfde afleiding als `OdooLeesFacade.find_purchase_invoices_kandidaten`."""
    if rij.get("state") == "draft":
        return 1
    return 3 if rij.get("payment_state") in ("paid", "reversed") else 2


def _lees_odoo(
    client: Any,
    partner_ids: Sequence[int],
    van: date,
    tot: date,
    *,
    administratie_id: uuid.UUID,
    kant: str,
    move_types: tuple[str, str],
) -> list[IcFactuur]:
    from app.odoo.ids import odoo_uuid

    if not partner_ids:
        return []
    domain = [
        ["company_id", "=", client.company_id],
        ["move_type", "in", list(move_types)],
        ["state", "!=", "cancel"],
        ["partner_id", "in", [int(p) for p in partner_ids]],
        ["invoice_date", ">=", van.isoformat()],
        ["invoice_date", "<=", tot.isoformat()],
    ]
    rijen: list[dict[str, Any]] = []
    for pagina in range(MAX_PAGINAS):
        deel = client.search_read(
            "account.move",
            domain,
            _ODOO_VELDEN,
            limit=PER_PAGINA,
            offset=pagina * PER_PAGINA,
            order="invoice_date asc, id asc",
        )
        rijen.extend(deel)
        if len(deel) < PER_PAGINA:
            break
    uit: list[IcFactuur] = []
    for rij in rijen:
        bedrag = _als_decimal(rij.get("amount_total"))
        datum = _als_datum(rij.get("invoice_date"))
        if bedrag is None or datum is None:
            continue
        if str(rij.get("move_type") or "").endswith("refund") and bedrag > 0:
            bedrag = -bedrag
        nummer = (rij.get("name") if kant == "verkoop" else rij.get("ref")) or None
        uit.append(
            maak_factuur(
                id=str(odoo_uuid(client.company_id, "account.move", int(rij["id"]))),
                administratie_id=administratie_id,
                kant=kant,
                nummer=str(nummer) if nummer else None,
                bedrag=bedrag,
                datum=datum,
                status=_odoo_status(rij),
                boekstuk=rij.get("name") or None,
            )
        )
    return uit


def lees_verkoop_odoo(
    client: Any, partner_ids: Sequence[int], van: date, tot: date, *, administratie_id: uuid.UUID
) -> list[IcFactuur]:
    return _lees_odoo(
        client,
        partner_ids,
        van,
        tot,
        administratie_id=administratie_id,
        kant="verkoop",
        move_types=("out_invoice", "out_refund"),
    )


def lees_inkoop_odoo(
    client: Any, partner_ids: Sequence[int], van: date, tot: date, *, administratie_id: uuid.UUID
) -> list[IcFactuur]:
    return _lees_odoo(
        client,
        partner_ids,
        van,
        tot,
        administratie_id=administratie_id,
        kant="inkoop",
        move_types=("in_invoice", "in_refund"),
    )


# ---- bron per administratie (RLZ of Odoo) -----------------------------------------------------------------


class BronOvergeslagen(Exception):
    """Geen credential / geen koppeling: zichtbaar OVERGESLAGEN, geen fout."""


class EntityNietVertaalbaar(Exception):
    """Odoo: een IC-entity-uuid heeft geen partner-koppeling — die kant kan niet gelezen worden (LET-OP)."""


class Bron:
    """Leesbron van één administratie. `verkoop`/`inkoop` geven IcFactuur-lijsten; `sluit()` sluit de verbinding."""

    backend = "rlz"

    def __init__(self, administratie_id: uuid.UUID) -> None:
        self.administratie_id = administratie_id

    def verkoop(self, entity_ids: Iterable[uuid.UUID], van: date, tot: date) -> list[IcFactuur]:  # pragma: no cover
        raise NotImplementedError

    def inkoop(self, entity_ids: Iterable[uuid.UUID], van: date, tot: date) -> list[IcFactuur]:  # pragma: no cover
        raise NotImplementedError

    def sluit(self) -> None:
        return None


class RlzBron(Bron):
    backend = "rlz"

    def __init__(self, administratie_id: uuid.UUID, client: RlzClient) -> None:
        super().__init__(administratie_id)
        self.client = client

    def verkoop(self, entity_ids: Iterable[uuid.UUID], van: date, tot: date) -> list[IcFactuur]:
        return lees_verkoop_rlz(self.client, entity_ids, van, tot, administratie_id=self.administratie_id)

    def inkoop(self, entity_ids: Iterable[uuid.UUID], van: date, tot: date) -> list[IcFactuur]:
        return lees_inkoop_rlz(self.client, entity_ids, van, tot, administratie_id=self.administratie_id)

    def sluit(self) -> None:
        try:
            self.client.close()
        except Exception:  # noqa: BLE001
            logger.debug("RLZ-client sluiten mislukt", exc_info=True)


class OdooBron(Bron):
    backend = "odoo"

    def __init__(self, administratie_id: uuid.UUID, port: Any) -> None:
        super().__init__(administratie_id)
        self.port = port
        self._partner_uuid_map: dict[uuid.UUID, int] | None = None

    def _partner_uuids(self) -> dict[uuid.UUID, int]:
        """Blok A slaat een Odoo-DEBITEUR op als `odoo_uuid(company, 'res.partner', id)` (uuid5, niet omkeerbaar):
        één keer per administratie álle partner-id's van de company lezen (één call, gecachet) en de uuid5 per id
        terugrekenen. Crediteuren lopen via de vendor_cache-id → `partner_id_voor` (eerste route)."""
        from app.odoo.ids import odoo_uuid

        if self._partner_uuid_map is None:
            client = self.port.client
            rijen = client.search_read(
                "res.partner", ["|", ["company_id", "=", client.company_id], ["company_id", "=", False]], ["id"]
            )
            self._partner_uuid_map = {
                odoo_uuid(client.company_id, "res.partner", int(r["id"])): int(r["id"]) for r in rijen
            }
        return self._partner_uuid_map

    def _partner_ids(self, entity_ids: Iterable[uuid.UUID]) -> list[int]:
        """IC-entity → Odoo-partner-int: (1) vendor_cache-id via de bestaande id-koppeling (`partner_id_voor`),
        (2) directe `res.partner`-koppeling, (3) partner-uuid5 terugrekenen (debiteuren, blok A). Niet vertaalbaar =
        `EntityNietVertaalbaar` (zichtbare LET-OP, nooit een filterloze read)."""
        from app.db.session import scoped_session
        from app.odoo import sync as odoo_sync

        uit: list[int] = []
        for e in entity_ids:
            e_uuid = uuid.UUID(str(e))
            try:
                uit.append(int(self.port.partner_id_voor(e_uuid)))
                continue
            except Exception:  # noqa: BLE001 — tweede route: directe res.partner-koppeling
                pass
            try:
                with scoped_session(self.administratie_id) as session:
                    uit.append(
                        int(
                            odoo_sync.odoo_id_voor(
                                session, administratie_id=self.administratie_id, model="res.partner", lokaal_id=e_uuid
                            )
                        )
                    )
                continue
            except Exception:  # noqa: BLE001 — derde route: uuid5 terugrekenen
                pass
            try:
                uit.append(self._partner_uuids()[e_uuid])
            except (KeyError, Exception) as exc:  # noqa: BLE001
                raise EntityNietVertaalbaar(f"{ODOO_PARTNER_ONBEKEND}: {e}") from exc
        return uit

    def verkoop(self, entity_ids: Iterable[uuid.UUID], van: date, tot: date) -> list[IcFactuur]:
        return lees_verkoop_odoo(
            self.port.client, self._partner_ids(entity_ids), van, tot, administratie_id=self.administratie_id
        )

    def inkoop(self, entity_ids: Iterable[uuid.UUID], van: date, tot: date) -> list[IcFactuur]:
        return lees_inkoop_odoo(
            self.port.client, self._partner_ids(entity_ids), van, tot, administratie_id=self.administratie_id
        )

    def sluit(self) -> None:
        try:
            self.port.client.close()
        except Exception:  # noqa: BLE001
            logger.debug("Odoo-client sluiten mislukt", exc_info=True)


def open_bron(administratie_id: uuid.UUID) -> Bron:
    """RLZ- of Odoo-bron voor één administratie (`Administratie.boekhoud_backend`). Geen credential/koppeling =
    `BronOvergeslagen`."""
    from app.backends.registry import Backend, backend_voor
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

    if backend_voor(administratie_id) == Backend.ODOO:
        from app.odoo.credentials import GeenOdooKoppeling
        from app.odoo.inkoop import OdooInkoopPort

        try:
            return OdooBron(administratie_id, OdooInkoopPort.voor(administratie_id))
        except GeenOdooKoppeling as exc:
            raise BronOvergeslagen(GEEN_ODOO_KOPPELING) from exc
    try:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    except GeenRlzCredentials as exc:
        raise BronOvergeslagen(GEEN_CREDENTIAL) from exc
    return RlzBron(administratie_id, client)


# ---- "onderweg in de module" -----------------------------------------------------------------------------


def module_onderweg(administratie_b: uuid.UUID) -> set[str]:
    """Genormaliseerde referenties van documenten in B die nog niet geboekt/afgehandeld zijn — één query in
    `scoped_session(B)`. Een verkoop zonder inkoop met zo'n nummer is "onderweg in de module": geen bevinding."""
    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel, Document, DocumentStatus
    from app.documenten.service import AFGEHANDELDE_STATUSSEN

    uitgesloten = {s.value for s in (*AFGEHANDELDE_STATUSSEN, DocumentStatus.GEBOEKT)}
    with scoped_session(administratie_b) as session:
        rijen = session.execute(
            select(Boekvoorstel.referentie_norm)
            .join(Document, Document.id == Boekvoorstel.document_id)
            .where(
                Document.administratie_id == administratie_b,
                Document.status.notin_(sorted(uitgesloten)),
                Boekvoorstel.referentie_norm.isnot(None),
            )
        ).all()
    return {str(r[0]) for r in rijen if r[0]}


# ---- doorbelasting-spiegelparen ----------------------------------------------------------------------------


@dataclass(frozen=True)
class Spiegelpaar:
    boeking_id: uuid.UUID
    bron_administratie_id: uuid.UUID
    doel_administratie_id: uuid.UUID
    verkoop_rlz_id: str
    spiegel_rlz_id: str
    verkoop_invoice_number: str | None


def lees_spiegelparen(bron_administratie_id: uuid.UUID, *, vanaf: date) -> list[Spiegelpaar]:
    """Geboekte doorbelastingen mét doel-administratie sinds `vanaf` (RLS: gelezen in de scope van de bron)."""
    from app.db.session import scoped_session
    from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus

    with scoped_session(bron_administratie_id) as session:
        rijen = session.scalars(
            select(DoorbelastingBoeking).where(
                DoorbelastingBoeking.administratie_id == bron_administratie_id,
                DoorbelastingBoeking.doel_administratie_id.isnot(None),
                DoorbelastingBoeking.status == DoorbelastingBoekingStatus.GEBOEKT.value,
                DoorbelastingBoeking.aangemaakt_op >= datetime(vanaf.year, vanaf.month, vanaf.day),
            )
        ).all()
        return [
            Spiegelpaar(
                boeking_id=r.id,
                bron_administratie_id=r.administratie_id,
                doel_administratie_id=r.doel_administratie_id,  # type: ignore[arg-type]
                verkoop_rlz_id=str(r.verkoop_rlz_id),
                spiegel_rlz_id=str(r.spiegel_rlz_id),
                verkoop_invoice_number=str(r.verkoop_invoice_number) if r.verkoop_invoice_number is not None else None,
            )
            for r in rijen
        ]


@dataclass(frozen=True)
class SpiegelUitkomst:
    paar: Spiegelpaar
    groen: bool
    reden: str | None  # None bij groen


def toets_spiegelparen(
    spiegelparen: Sequence[Spiegelpaar], *, verkoop: Sequence[IcFactuur], inkoop: Sequence[IcFactuur]
) -> list[SpiegelUitkomst]:
    """PUUR: verkoop én spiegel moeten in de gelezen sets zitten en cent-exact gelijk zijn."""
    v_per_id = {f.id.lower(): f for f in verkoop}
    i_per_id = {f.id.lower(): f for f in inkoop}
    uit: list[SpiegelUitkomst] = []
    for p in spiegelparen:
        v = v_per_id.get(p.verkoop_rlz_id.lower())
        i = i_per_id.get(p.spiegel_rlz_id.lower())
        if v is None and i is None:
            reden = "verkoop én spiegel niet gevonden in de gelezen sets"
        elif v is None:
            reden = "verkoopfactuur niet gevonden bij de bron-administratie"
        elif i is None:
            reden = "spiegel-inkoopfactuur niet gevonden bij de doel-administratie"
        elif v.bedrag != i.bedrag:
            reden = f"bedrag verkoop {_euro(v.bedrag)} ≠ spiegel {_euro(i.bedrag)}"
        else:
            reden = None
        uit.append(SpiegelUitkomst(paar=p, groen=reden is None, reden=reden))
    return uit


def _registreer_spiegel_regressie(uitkomst: SpiegelUitkomst, *, vingerafdruk: str) -> None:
    """Audit `automatisering_regressie` (administratie-loos in `scoped_session(None)` — les: audit mét
    administratie_id vereist scoped_session(<adm>)); de bewakingsprobe `automatisering_regressie` alarmeert erop."""
    from app.db.audit import record_audit_event
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    p = uitkomst.paar
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="boekhouding",
            tabel="doorbelasting_boeking",
            record_id=p.boeking_id,
            actie="automatisering_regressie",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "automatisering": "intercompany_spiegel",
                "categorie": SOORT_SPIEGEL_ROOD,
                "aantal": 1,
                "administratie_id": None,
                "bron_administratie_id": str(p.bron_administratie_id),
                "doel_administratie_id": str(p.doel_administratie_id),
                "verkoop_rlz_id": p.verkoop_rlz_id,
                "spiegel_rlz_id": p.spiegel_rlz_id,
                "verkoop_invoice_number": p.verkoop_invoice_number,
                "reden": uitkomst.reden,
                "vingerafdruk": vingerafdruk,
            },
        )


# ---- blokfunctie ------------------------------------------------------------------------------------------


@dataclass
class RelatieRapport:
    relatie: Handelsrelatie
    uitkomst: MatchUitkomst | None = None
    spiegels: list[SpiegelUitkomst] = field(default_factory=list)
    let_op: list[str] = field(default_factory=list)


def _venster(nu: date, dagen: int) -> tuple[date, date]:
    return (nu - timedelta(days=dagen), nu)


def cli_blok(  # noqa: C901, PLR0912, PLR0915 — één blokfunctie, zelfde contract als de andere reconciliatie-blokken
    args,  # noqa: ANN001
    verzamelaar=None,  # noqa: ANN001 — app.reconciliatie.run.Verzamelaar | None
    *,
    bron_factory: Callable[[uuid.UUID], Bron] | None = None,
    paren: Sequence[Any] | None = None,
    nu: date | None = None,
    stdout: Callable[[str], None] = print,
    stderr: Callable[[str], None] | None = None,
) -> int:
    """Blokfunctie voor `reconciliatie-alles` (contract van `_omzet_reconciliatie`/`rlz_dubbel.cli_blok`): print
    dezelfde soort regels, registreer élke regel als bevinding, exit 1 zodra er een open afwijking of fout is.
    Zonder verzamelaar (lees-only, losse CLI) alleen printen — niets vastgelegd. `bron_factory`/`paren`/`nu` zijn
    injectiepunten voor tests; productie leest `relaties.actieve_paren()` (blok A) en opent bronnen per backend."""
    import sys

    from app.reconciliatie import service as acceptatie_service
    from app.reconciliatie import verrijking
    from app.tijd import vandaag_nl

    stderr = stderr or (lambda tekst: print(tekst, file=sys.stderr))
    nu = nu or vandaag_nl()
    dagen = int(getattr(args, "ic_venster_dagen", None) or VENSTER_DAGEN)
    van, tot = _venster(nu, dagen)
    administratie_filter = getattr(args, "administratie_ids", None)

    def meld(**kw: Any) -> None:
        if verzamelaar is not None:
            verzamelaar.bevinding(**kw)

    def naam_van(aid: uuid.UUID) -> str | None:
        try:
            return verrijking.administratie_naam(aid)
        except Exception:  # noqa: BLE001
            return None

    if paren is None:
        try:
            from app.intercompany.relaties import actieve_paren

            paren = list(actieve_paren())
        except Exception as exc:  # noqa: BLE001 — zichtbaar als blok-fout, nooit stil
            logger.exception("intercompany: actieve IC-paren niet gelezen")
            tekst = f"FOUT       intercompany: actieve IC-relaties niet gelezen: {str(exc)[:200]}"
            stderr(tekst)
            meld(soort="fout", administratie_id=None, tekst=tekst)
            return 1
    relaties = bouw_handelsrelaties(paren)
    if administratie_filter is not None:
        keuze = {uuid.UUID(str(a)) for a in administratie_filter}
        relaties = [r for r in relaties if r.verkoper_id in keuze or r.ontvanger_id in keuze]
    stdout(
        f"Venster {van.isoformat()} t/m {tot.isoformat()} ({dagen} dagen); {len(paren)} actieve IC-paren → "
        f"{len(relaties)} handelsrelatie(s)."
    )
    if not relaties:
        stdout(
            "OK         geen actieve intercompany-relaties — niets te toetsen "
            "(afleiding: sync-alles / Instellingen › Boeken)"
        )
        return 0

    maak_bron = bron_factory or open_bron
    bronnen: dict[uuid.UUID, Bron] = {}
    overgeslagen: dict[uuid.UUID, str] = {}
    ongeldig: dict[uuid.UUID, str] = {}  # webfilter / leesfout per administratie
    fouten = 0

    def bron_voor(aid: uuid.UUID) -> Bron | None:
        if aid in bronnen:
            return bronnen[aid]
        if aid in overgeslagen or aid in ongeldig:
            return None
        try:
            bronnen[aid] = maak_bron(aid)
        except BronOvergeslagen as exc:
            overgeslagen[aid] = str(exc)
            stdout(f"OVERGESLAGEN {aid}: {exc}")
            return None
        except Exception as exc:  # noqa: BLE001 — zichtbaar, en door met de rest
            logger.exception("intercompany: bron openen mislukt voor %s", aid)
            ongeldig[aid] = str(exc)
            return None
        return bronnen[aid]

    # Cache per (administratie, kant, entity-set): beide richtingen van een relatie delen niets, maar twee relaties
    # met dezelfde verkoper lezen wél elk hun eigen entity-set — calls per administratie = #relaties × pagina's.
    gelezen: dict[tuple[uuid.UUID, str, frozenset[uuid.UUID]], list[IcFactuur]] = {}
    onderweg_cache: dict[uuid.UUID, set[str]] = {}

    def lees(aid: uuid.UUID, kant: str, entity_ids: frozenset[uuid.UUID]) -> list[IcFactuur] | None:
        sleutel = (aid, kant, entity_ids)
        if sleutel in gelezen:
            return gelezen[sleutel]
        bron = bron_voor(aid)
        if bron is None:
            return None
        try:
            rijen = bron.verkoop(entity_ids, van, tot) if kant == "verkoop" else bron.inkoop(entity_ids, van, tot)
        except RlzWebfilterError as exc:
            ongeldig[aid] = f"{WEBFILTER_ONGELDIG}: {str(exc)[:200]}"
            return None
        except EntityNietVertaalbaar as exc:
            ongeldig.setdefault(aid, "")  # markeer, maar de tekst gaat als LET-OP op de relatie
            raise exc
        except Exception as exc:  # noqa: BLE001
            logger.exception("intercompany: lezen mislukt (%s, %s)", aid, kant)
            ongeldig[aid] = f"lezen mislukt: {str(exc)[:200]}"
            return None
        gelezen[sleutel] = rijen
        return rijen

    rapporten: list[RelatieRapport] = []
    try:
        for rel in relaties:
            rapport = RelatieRapport(relatie=rel)
            rapporten.append(rapport)
            if not rel.inkoop_entity_ids or not rel.verkoop_entity_ids:
                kant = "ontvangende" if not rel.inkoop_entity_ids else "verkopende"
                rapport.let_op.append(f"IC-tegenrelatie in de {kant} administratie onbekend — paar niet getoetst")
                continue
            try:
                verkoop = lees(rel.verkoper_id, "verkoop", rel.verkoop_entity_ids)
                inkoop = lees(rel.ontvanger_id, "inkoop", rel.inkoop_entity_ids)
            except EntityNietVertaalbaar as exc:
                rapport.let_op.append(str(exc))
                continue
            if verkoop is None or inkoop is None:
                continue  # administratie overgeslagen/ongeldig — regel volgt per administratie
            if rel.ontvanger_id not in onderweg_cache:
                try:
                    onderweg_cache[rel.ontvanger_id] = module_onderweg(rel.ontvanger_id)
                except Exception:  # noqa: BLE001 — geen module-stand = niets onderweg (fail-loud richting bevinding)
                    logger.exception("intercompany: module-onderweg niet gelezen voor %s", rel.ontvanger_id)
                    onderweg_cache[rel.ontvanger_id] = set()
            rapport.uitkomst = match_facturen(
                verkoper_id=rel.verkoper_id,
                ontvanger_id=rel.ontvanger_id,
                verkoop=verkoop,
                inkoop=inkoop,
                module_onderweg=onderweg_cache[rel.ontvanger_id],
                nu=nu,
                verkoper_naam=naam_van(rel.verkoper_id),
                ontvanger_naam=naam_van(rel.ontvanger_id),
            )
            try:
                spiegelparen = [
                    p
                    for p in lees_spiegelparen(rel.verkoper_id, vanaf=van)
                    if p.doel_administratie_id == rel.ontvanger_id
                ]
            except Exception:  # noqa: BLE001
                logger.exception("intercompany: spiegelparen niet gelezen voor %s", rel.verkoper_id)
                spiegelparen = []
            rapport.spiegels = toets_spiegelparen(spiegelparen, verkoop=verkoop, inkoop=inkoop)
    finally:
        for bron in bronnen.values():
            bron.sluit()

    # --- administratie-regels: ongeldig (webfilter/leesfout) = FOUT ------------------------------------------------
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    for aid, reden in sorted(ongeldig.items(), key=lambda kv: str(kv[0])):
        if not reden:
            continue
        uitsluiting = uitgesloten.get(aid)
        if uitsluiting:
            tekst = f"UITGESLOTEN {aid}: {reden} (uitgesloten: {uitsluiting})"
            stdout(tekst)
            meld(
                soort="uitgesloten",
                administratie_id=aid,
                tekst=tekst,
                detail=verrijking.administratie(aid, fout=reden, uitsluiting=uitsluiting) or None,
            )
            continue
        fouten += 1
        tekst = f"FOUT       {aid}: {reden}"
        stderr(tekst)
        meld(soort="fout", administratie_id=aid, tekst=tekst, detail=verrijking.administratie(aid, fout=reden) or None)

    # --- per relatie -----------------------------------------------------------------------------------------------
    from app.cli import _afwijking_detail, _regel, _soort_van

    open_totaal = 0
    geaccepteerd_totaal = 0
    paren_getoetst = 0
    onderweg_totaal = 0
    spiegels_groen = 0
    spiegels_rood = 0
    for rapport in rapporten:
        rel = rapport.relatie
        naam_v = naam_van(rel.verkoper_id) or str(rel.verkoper_id)
        naam_o = naam_van(rel.ontvanger_id) or str(rel.ontvanger_id)
        kop_rel = f"{naam_v} → {naam_o}"
        for let_op in rapport.let_op:
            tekst = f"LET-OP     {kop_rel}: {let_op}"
            stdout(tekst)
            meld(
                soort="let_op",
                administratie_id=rel.ontvanger_id,
                tekst=tekst,
                detail={
                    "reden": "ic_tegenrelatie_onbekend",
                    "verkoper_naam": naam_v,
                    "ontvanger_naam": naam_o,
                    "administratie_naam": naam_van(rel.ontvanger_id),
                    "doel_pad": "/instellingen/boeken",
                },
            )
        if rapport.uitkomst is None:
            if not rapport.let_op and (rel.verkoper_id in overgeslagen or rel.ontvanger_id in overgeslagen):
                stdout(f"OVERGESLAGEN {kop_rel}: één kant overgeslagen (zie regel hierboven)")
            elif not rapport.let_op:
                stdout(f"FOUT       {kop_rel}: niet getoetst — één kant ongeldig (zie regel hierboven)")
            continue
        u = rapport.uitkomst
        paren_getoetst += 1
        onderweg_totaal += len(u.onderweg)
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(u.aantal_verkoop + u.aantal_inkoop)

        # Spiegelparen: rood = systeemfout (administratie-loos → systeemmail) + audit; de gewone bevindingen van
        # die facturen worden onderdrukt (geen kantoor-handeling op een motor-bug).
        rode_ids: set[str] = set()
        for s in rapport.spiegels:
            if s.groen:
                spiegels_groen += 1
                continue
            spiegels_rood += 1
            rode_ids |= {s.paar.verkoop_rlz_id.lower(), s.paar.spiegel_rlz_id.lower()}
            tekst = (
                f"FOUT       {SPIEGEL_SYSTEEMFOUT} {kop_rel} verkoop={s.paar.verkoop_rlz_id} "
                f"spiegel={s.paar.spiegel_rlz_id} nummer={s.paar.verkoop_invoice_number}: {s.reden}"
            )
            stderr(tekst)
            fouten += 1
            from app.reconciliatie.run import vingerafdruk_tekst

            vaf = vingerafdruk_tekst(blok=BLOK, soort="fout", administratie_id=None, tekst=tekst)
            meld(
                soort="fout",
                administratie_id=None,
                tekst=tekst,
                vingerafdruk=vaf,
                detail={
                    "afwijking_soort": SOORT_SPIEGEL_ROOD,
                    "fout": s.reden,
                    "verkoper_naam": naam_v,
                    "ontvanger_naam": naam_o,
                    "nummer": s.paar.verkoop_invoice_number,
                    "verkoop_rlz_id": s.paar.verkoop_rlz_id,
                    "spiegel_rlz_id": s.paar.spiegel_rlz_id,
                    "systeemfout": True,
                },
            )
            if verzamelaar is not None:
                try:
                    _registreer_spiegel_regressie(s, vingerafdruk=vaf)
                except Exception:  # noqa: BLE001 — audit mag de toets niet laten omvallen
                    logger.exception("intercompany: regressie-audit mislukt")

        bevindingen = [
            b
            for b in u.bevindingen
            if not (
                set(map(str.lower, b.extra.get("verkoop_ids", []))) & rode_ids
                or set(map(str.lower, b.extra.get("inkoop_ids", []))) & rode_ids
            )
        ]
        per_administratie: dict[uuid.UUID, list[IcBevinding]] = {}
        for b in bevindingen:
            per_administratie.setdefault(b.administratie_id, []).append(b)

        samenvatting = (
            f"{u.aantal_verkoop} verkoop / {u.aantal_inkoop} inkoop gelezen, {len(u.matches)} gematcht "
            f"({sum(1 for m in u.matches if m.regel == REGEL_NUMMER)} op nummer, "
            f"{sum(1 for m in u.matches if m.regel == REGEL_BEDRAG_DATUM)} op bedrag+datum, "
            f"{sum(1 for m in u.matches if m.regel == REGEL_BEDRAG)} alleen bedrag), {len(u.onderweg)} onderweg in de "
            f"module, {len(u.verrekend_zonder_tegenkant)} verrekend zonder tegenkant, "
            f"spiegelparen {sum(1 for s in rapport.spiegels if s.groen)}/{len(rapport.spiegels)} groen"
        )
        if not bevindingen:
            stdout(f"OK         {kop_rel}: {samenvatting}, geen afwijkingen")
            continue
        for aid, lijst in per_administratie.items():
            beoordeeld = acceptatie_service.beoordeel(
                bron=ACCEPTATIE_BRON,
                administratie_id=aid,
                afwijkingen=[(b.record_id, b.soort, b.detail) for b in lijst],
            )
            uitsluiting = uitgesloten.get(aid)
            open_hier = [b for b in beoordeeld if b.telt_mee]
            if uitsluiting:
                geaccepteerd_totaal += len(beoordeeld) - len(open_hier)
                stdout(
                    f"UITGESLOTEN {aid} ({kop_rel}): {len(open_hier)} open, {len(beoordeeld) - len(open_hier)} "
                    f"geaccepteerd — telt niet mee ({uitsluiting})"
                )
            else:
                open_totaal += len(open_hier)
                geaccepteerd_totaal += len(beoordeeld) - len(open_hier)
                kop = "AFWIJKING " if open_hier else "OK        "
                stdout(
                    f"{kop} {aid} ({kop_rel}): {samenvatting}; {len(open_hier)} afwijking(en), "
                    f"{len(beoordeeld) - len(open_hier)} geaccepteerd"
                )
            for b, oordeel in zip(lijst, beoordeeld, strict=True):
                regel = _regel(f"factuur={b.extra.get('nummer')} {kop_rel}", oordeel)
                stdout(f"    - {regel}")
                meld(
                    soort=_soort_van(oordeel, uitsluiting),
                    administratie_id=aid,
                    tekst=regel,
                    vingerafdruk=oordeel.vingerafdruk,
                    detail=_afwijking_detail(
                        ACCEPTATIE_BRON,
                        oordeel,
                        uitsluiting,
                        administratie_naam=naam_van(aid),
                        **{k: v for k, v in b.extra.items() if k not in ("verkoop_ids", "inkoop_ids")},
                    ),
                )

    stdout(
        f"\n{paren_getoetst}/{len(relaties)} handelsrelatie(s) getoetst, {open_totaal} afwijking(en) totaal "
        f"({geaccepteerd_totaal} geaccepteerd), {onderweg_totaal} onderweg in de module, spiegelparen "
        f"{spiegels_groen} groen / {spiegels_rood} rood, {len(overgeslagen)} administratie(s) overgeslagen, "
        f"{fouten} fout(en)."
    )
    return 1 if (open_totaal or fouten) else 0
