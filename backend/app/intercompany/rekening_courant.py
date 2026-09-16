"""Reconciliatie-blok `rekening_courant` — dagelijkse rekening-courant-aansluiting tussen gelieerde administraties
(opdracht Peter 16-09, blok C: "wij hebben op de balans verschillende RC's tussen gelieerde bedrijven. Dagelijks wil
ik een controle van die GB's of het eindsaldo aansluit en indien het niet aansluit wil ik weten welke mutatie mist").

Wat dit blok doet — en bewust níét:
- Per actieve `rc_koppeling` (status afgeleid|bevestigd, tabel van agent A — de afleiding zelf staat in
  `rc_koppelingen.py`) leest het beide kanten LEES-ONLY: het eindsaldo van rekening_a in administratie A en van
  rekening_b in administratie B, plus de mutaties van beide rekeningen. RLZ via `JournalEntryLines` (saldo = Σ
  DebitAmount − Σ CreditAmount — nooit `CreditOrDebit`, STAP-0 14-09/16-09), Odoo via `account.move.line` (posted,
  `balance`). Eén gepagineerde leesreeks per rekening: saldo én mutatievenster komen uit dezelfde set, dus het aantal
  calls hangt af van het aantal regels op de rekening (≤ `MAX_PAGINAS` pagina's van `PAGINA_GROOTTE`), niet van de
  omvang van de administratie.
- De TOETS is puur (`toets_paar`): de RC in A is een vordering (debet, positief), in B een schuld (credit, negatief)
  → sluit als saldo_a + saldo_b == 0 (cent-exact). Sluit het niet, dan is Δ = saldo_a + saldo_b en volgt de
  VERKLARING: mutaties van beide kanten paarsgewijs matchen op tegengesteld bedrag + datum ± `TOLERANTIE_DAGEN` +
  omschrijving-kern (`geheugen/normalisatie.normaliseer_regel_sleutel`; zelfde kern wint, anders de eerste op datum),
  greedy, elke mutatie hoogstens één keer. De restlijsten zijn "ontbreekt bij B" (rest van A) en "ontbreekt bij A"
  (rest van B). Verklaart Σ(rest) de Δ niet → `niet_herleidbaar` ("vermoedelijk afronding/koers; controleer
  handmatig"). Meerdere kandidaten met hetzelfde bedrag waarvan de kern niet beslist → ALLEMAAL noemen, nooit raden.
- Het VENSTER voor de verklaring begint de dag ná de laatste groene stand (`rc_stand.sluit = true`), anders
  `VENSTER_DAGEN` terug; élke run schrijft één `rc_stand`-rij per koppeling per dag (upsert op PK), ook bij rood.
- Bevindingen: `rc_sluit_niet` (afwijking, acceptatie-met-reden via `ReconciliatieBron.REKENING_COURANT`; detail
  stabiel per paar = rekeningen + Δ, geen datum van vandaag) en `rc_zonder_tegenrekening` (let_op — een koppeling
  waarvan rekening_b NULL is). Webfilter-blokkering (`RlzWebfilterError`) = FOUT "meting ongeldig", nooit een
  valse bevinding; geen credential = zichtbare FOUT (KP 6: nooit stil).
- Geen writes naar RLZ/Odoo, geen AI; alle geldvergelijking in Decimal. Het systeem herstelt niets zelf — het gaat
  om andermans boekhouding.

Zie docs/BESLISSINGEN.md "INTERCOMPANY-FACTUURMATCH + RC-AANSLUITING (Peter 16-09)"."""

from __future__ import annotations

import logging
import sys
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.backends.port import Backend
from app.db.models import Administratie
from app.db.session import scoped_session
from app.geheugen.normalisatie import normaliseer_regel_sleutel
from app.intercompany.models import RcKoppeling, RcStand
from app.reconciliatie.models import ReconciliatieBron
from app.rlz.client import RlzApiError, RlzWebfilterError
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)

BLOK = "rekening_courant"
SOORT_SLUIT_NIET = "rc_sluit_niet"
SOORT_ZONDER_TEGENREKENING = "rc_zonder_tegenrekening"
ACTIEVE_STATUSSEN = ("afgeleid", "bevestigd")
#: Verklaringsvenster als er nog geen groene stand is: een boekjaar plús nakomers (default beslispunt 1, Peter 16-09).
VENSTER_DAGEN = 400
#: Bank-overboekingen tussen groepsmaatschappijen duren dagen; ± 5 d (default beslispunt 2, 10 d als alternatief).
TOLERANTIE_DAGEN = 5
PAGINA_GROOTTE = 200
#: Harde bovengrens per rekening: nooit een runaway-lus richting de webfilter (~700 calls).
MAX_PAGINAS = 50
MELDING_METING_ONGELDIG = "RLZ-blokkering (webfilter) — meting ongeldig, geen bevinding"
NUL = Decimal("0.00")
_CENT = Decimal("0.01")


# ---- data ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RcMutatie:
    """Eén journaalregel op een RC-rekening. `bedrag` = Debit − Credit (debet positief, credit negatief)."""

    id: str
    datum: date
    bedrag: Decimal
    omschrijving: str | None
    kern: str | None
    boekstuk: str | None

    @classmethod
    def maak(
        cls, *, id: str, datum: date, bedrag: Decimal, omschrijving: str | None, boekstuk: str | None = None
    ) -> RcMutatie:
        return cls(
            id=str(id),
            datum=datum,
            bedrag=bedrag.quantize(_CENT),
            omschrijving=omschrijving,
            kern=normaliseer_regel_sleutel(omschrijving),
            boekstuk=boekstuk,
        )

    def regel(self) -> str:
        """`12-09 € 1.250,00 'huur september' (RLZ-05-00000412)` — DD-MM, NL-euro, omschrijving, boekstuk."""
        delen = [self.datum.strftime("%d-%m"), euro_nl(self.bedrag)]
        if self.omschrijving:
            delen.append(f"'{self.omschrijving.strip()}'")
        tekst = " ".join(delen)
        return f"{tekst} ({self.boekstuk})" if self.boekstuk else tekst


@dataclass(frozen=True)
class RcUitkomst:
    """Uitkomst van `toets_paar`. `ontbreekt_bij_b` = mutaties van A zonder tegenhanger in B (en omgekeerd);
    `kandidaten_bij_b`/`kandidaten_bij_a` = per restmutatie álle mutaties met hetzelfde bedrag waarvan de kern niet
    beslist (eerste element = de restmutatie zelf) — meerdere kandidaten worden allemaal genoemd."""

    saldo_a: Decimal
    saldo_b: Decimal
    delta: Decimal
    sluit: bool
    ontbreekt_bij_b: tuple[RcMutatie, ...] = ()
    ontbreekt_bij_a: tuple[RcMutatie, ...] = ()
    kandidaten_bij_b: tuple[tuple[RcMutatie, ...], ...] = ()
    kandidaten_bij_a: tuple[tuple[RcMutatie, ...], ...] = ()
    niet_herleidbaar: bool = False
    gematcht: int = 0

    @property
    def verklaard(self) -> bool:
        return not self.sluit and not self.niet_herleidbaar

    def regels_bij_b(self) -> list[str]:
        return [_kandidaten_regel(groep) for groep in self.kandidaten_bij_b]

    def regels_bij_a(self) -> list[str]:
        return [_kandidaten_regel(groep) for groep in self.kandidaten_bij_a]

    def tekst_niet_herleidbaar(self) -> str:
        return (
            f"Δ {euro_nl(self.delta)} niet herleidbaar tot losse mutaties — vermoedelijk afronding/koers; "
            "controleer handmatig"
        )


def _kandidaten_regel(groep: Sequence[RcMutatie]) -> str:
    if len(groep) == 1:
        return groep[0].regel()
    return f"één van {len(groep)} met hetzelfde bedrag: " + " of ".join(m.regel() for m in groep)


def euro_nl(waarde: Decimal) -> str:
    """Decimal → '€ 1.234,56' / '€ -1.234,56' (zelfde vorm als `reconciliatie/teksten.py::euro`, maar altijd str)."""
    q = Decimal(waarde).quantize(_CENT)
    teken = "-" if q < 0 else ""
    hele, _, cent = f"{abs(q):.2f}".partition(".")
    groepen: list[str] = []
    while len(hele) > 3:
        groepen.insert(0, hele[-3:])
        hele = hele[:-3]
    groepen.insert(0, hele)
    return f"€ {teken}{'.'.join(groepen)},{cent}"


# ---- de pure toets --------------------------------------------------------------------------------


@dataclass
class _Match:
    a: RcMutatie
    b: RcMutatie
    op_kern: bool


def _binnen(a: RcMutatie, b: RcMutatie, tolerantie_dagen: int) -> bool:
    return abs((a.datum - b.datum).days) <= tolerantie_dagen


def _match_paarsgewijs(
    mutaties_a: Sequence[RcMutatie], mutaties_b: Sequence[RcMutatie], tolerantie_dagen: int
) -> tuple[list[_Match], list[RcMutatie], list[RcMutatie]]:
    """Greedy op datumvolgorde van A: tegengesteld bedrag + datum ± tolerantie; zelfde kern wint, anders de eerste
    (vroegste) kandidaat op datum. Elke mutatie hoogstens één keer."""
    a_sorteer = sorted(mutaties_a, key=lambda m: (m.datum, m.id))
    b_open = sorted(mutaties_b, key=lambda m: (m.datum, m.id))
    matches: list[_Match] = []
    rest_a: list[RcMutatie] = []
    for a in a_sorteer:
        kandidaten = [b for b in b_open if b.bedrag == -a.bedrag and _binnen(a, b, tolerantie_dagen)]
        if not kandidaten:
            rest_a.append(a)
            continue
        op_kern = [b for b in kandidaten if a.kern is not None and b.kern == a.kern]
        if op_kern:
            gekozen, was_kern = op_kern[0], True
        else:
            gekozen, was_kern = kandidaten[0], False
        b_open.remove(gekozen)
        matches.append(_Match(a=a, b=gekozen, op_kern=was_kern))
    return matches, rest_a, b_open


def _kandidaten(
    rest: Sequence[RcMutatie], matches: Sequence[_Match], *, kant: str, tolerantie_dagen: int
) -> tuple[tuple[RcMutatie, ...], ...]:
    """Per restmutatie: zijzelf plus de al gematchte mutaties aan dezelfde kant met hetzelfde bedrag waarvan de match
    NIET op kern besliste en waarvan de tegenhanger óók binnen de tolerantie van de restmutatie ligt — dan had de
    tegenhanger even goed bij de restmutatie kunnen horen en is raden verboden."""
    uit: list[tuple[RcMutatie, ...]] = []
    for r in rest:
        extra = []
        for m in matches:
            eigen = m.a if kant == "a" else m.b
            tegen = m.b if kant == "a" else m.a
            if m.op_kern or eigen.bedrag != r.bedrag:
                continue
            if r.kern is not None and tegen.kern == r.kern:
                continue  # de tegenhanger hoort op kern juist níét bij de restmutatie
            if _binnen(r, tegen, tolerantie_dagen):
                extra.append(eigen)
        uit.append((r, *sorted(extra, key=lambda m: (m.datum, m.id))))
    return tuple(uit)


def toets_paar(
    *,
    saldo_a: Decimal,
    saldo_b: Decimal,
    mutaties_a: Sequence[RcMutatie],
    mutaties_b: Sequence[RcMutatie],
    tolerantie_dagen: int = TOLERANTIE_DAGEN,
) -> RcUitkomst:
    """PUUR. Sluit als saldo_a + saldo_b == 0 (cent-exact). Anders Δ + verklaring uit de restlijsten; Σ(rest_a) +
    Σ(rest_b) ≠ Δ → `niet_herleidbaar`. Mutaties in de aanroep zijn het VENSTER (sinds de laatste groene stand)."""
    sa, sb = Decimal(saldo_a).quantize(_CENT), Decimal(saldo_b).quantize(_CENT)
    delta = (sa + sb).quantize(_CENT)
    if delta == 0:
        return RcUitkomst(saldo_a=sa, saldo_b=sb, delta=NUL, sluit=True)
    matches, rest_a, rest_b = _match_paarsgewijs(mutaties_a, mutaties_b, tolerantie_dagen)
    som_rest = sum((m.bedrag for m in rest_a), NUL) + sum((m.bedrag for m in rest_b), NUL)
    niet_herleidbaar = som_rest.quantize(_CENT) != delta
    return RcUitkomst(
        saldo_a=sa,
        saldo_b=sb,
        delta=delta,
        sluit=False,
        ontbreekt_bij_b=tuple(rest_a),
        ontbreekt_bij_a=tuple(rest_b),
        kandidaten_bij_b=_kandidaten(rest_a, matches, kant="a", tolerantie_dagen=tolerantie_dagen),
        kandidaten_bij_a=_kandidaten(rest_b, matches, kant="b", tolerantie_dagen=tolerantie_dagen),
        niet_herleidbaar=niet_herleidbaar,
        gematcht=len(matches),
    )


# ---- lezers ---------------------------------------------------------------------------------------


def _decimal(waarde: Any) -> Decimal:
    if waarde in (None, ""):
        return NUL
    try:
        return Decimal(str(waarde)).quantize(_CENT)
    except (InvalidOperation, ValueError, TypeError):
        return NUL


def _datum(waarde: Any) -> date | None:
    if not waarde:
        return None
    if isinstance(waarde, datetime):
        return waarde.date()
    if isinstance(waarde, date):
        return waarde
    try:
        return date.fromisoformat(str(waarde)[:10])
    except ValueError:
        return None


def _rlz_boekstuk(entry: dict[str, Any]) -> str | None:
    """JournalEntry draagt in de STAP-0-vorm geen boekstuknummer (id, BookDate, DocumentType, EventID); defensief
    lezen we een eventueel `Reference`/`Number`/`EntryNumber` mee, anders None — nooit een GUID als 'boekstuk'."""
    for sleutel in ("Reference", "Number", "EntryNumber", "DocumentNumber"):
        v = entry.get(sleutel)
        if v not in (None, ""):
            return str(v)
    return None


def _rlz_regel(rij: dict[str, Any]) -> RcMutatie | None:
    entry = rij.get("JournalEntry") or {}
    datum = _datum(entry.get("BookDate"))
    if datum is None:
        return None
    bedrag = _decimal(rij.get("DebitAmount")) - _decimal(rij.get("CreditAmount"))
    return RcMutatie.maak(
        id=str(rij.get("id") or ""),
        datum=datum,
        bedrag=bedrag,
        omschrijving=rij.get("Description"),
        boekstuk=_rlz_boekstuk(entry),
    )


def _rlz_paginas(client: Any, *, ledger_id: uuid.UUID | str) -> tuple[list[dict[str, Any]], int]:
    """Alle JournalEntryLines van één rekening, gepagineerd. Eerst mét `$count=true`: staat `@odata.count` in het
    antwoord, dan stopt de lus zodra alles binnen is (200 regels = 1 call); weigert RLZ `$count` (400), dan zonder en
    op de pagina-lengte (200 regels = 2 calls — de tweede is leeg). → (rijen, aantal calls)."""
    basis = {
        "$filter": f"Account/id eq {ledger_id}",
        "$expand": "JournalEntry",
        "$orderby": "JournalEntry/BookDate asc,id asc",
    }
    rijen: list[dict[str, Any]] = []
    met_count = True
    calls = 0
    verwacht: int | None = None
    for pagina in range(MAX_PAGINAS):
        params = {**basis, "$top": str(PAGINA_GROOTTE), "$skip": str(pagina * PAGINA_GROOTTE)}
        if met_count:
            params["$count"] = "true"
        try:
            antwoord = client.get("JournalEntryLines", params=params)
            calls += 1
        except RlzWebfilterError:
            raise
        except RlzApiError as exc:
            if met_count and exc.status_code == 400:
                met_count = False
                calls += 1
                antwoord = client.get("JournalEntryLines", params={k: v for k, v in params.items() if k != "$count"})
                calls += 1
            else:
                raise
        deel = antwoord.get("value", []) if isinstance(antwoord, dict) else []
        rijen.extend(deel)
        if verwacht is None and isinstance(antwoord, dict) and antwoord.get("@odata.count") is not None:
            try:
                verwacht = int(antwoord["@odata.count"])
            except (TypeError, ValueError):
                verwacht = None
        if verwacht is not None:
            if len(rijen) >= verwacht or not deel:
                break
        elif len(deel) < PAGINA_GROOTTE:
            break
    return rijen, calls


def saldo_en_mutaties_rlz(
    client: Any, *, ledger_id: uuid.UUID | str, vanaf: date | None
) -> tuple[Decimal, list[RcMutatie]]:
    """Saldo per vandaag (Σ Debit − Credit over ÁLLE regels van de rekening) + de mutaties vanaf `vanaf`
    (client-side venster; None = alles), uit één leesreeks. Een `RlzWebfilterError` gaat ongewijzigd door."""
    rijen, _ = _rlz_paginas(client, ledger_id=ledger_id)
    saldo = NUL
    mutaties: list[RcMutatie] = []
    for rij in rijen:
        m = _rlz_regel(rij)
        if m is None:
            saldo += _decimal(rij.get("DebitAmount")) - _decimal(rij.get("CreditAmount"))
            continue
        saldo += m.bedrag
        if vanaf is None or m.datum >= vanaf:
            mutaties.append(m)
    return saldo.quantize(_CENT), mutaties


_ODOO_VELDEN = ["date", "debit", "credit", "balance", "name", "ref", "move_name"]


def saldo_en_mutaties_odoo(
    odoo_client: Any, *, account_id: int, vanaf: date | None, pagina: int = 500
) -> tuple[Decimal, list[RcMutatie]]:
    """Odoo-tegenhanger: `account.move.line` van de company van de client, alleen `parent_state = posted`;
    `balance` = debit − credit. Gepagineerd via `search_read(limit/offset)`; venster client-side."""
    domain = [
        ["company_id", "=", int(odoo_client.company_id)],
        ["account_id", "=", int(account_id)],
        ["parent_state", "=", "posted"],
    ]
    rijen: list[dict[str, Any]] = []
    offset = 0
    for _ in range(MAX_PAGINAS):
        deel = odoo_client.search_read(
            "account.move.line", domain, _ODOO_VELDEN, limit=pagina, offset=offset, order="date asc, id asc"
        )
        rijen.extend(deel)
        if len(deel) < pagina:
            break
        offset += pagina
    saldo = NUL
    mutaties: list[RcMutatie] = []
    for rij in rijen:
        if rij.get("balance") is not None:
            bedrag = _decimal(rij.get("balance"))
        else:
            bedrag = _decimal(rij.get("debit")) - _decimal(rij.get("credit"))
        saldo += bedrag
        datum = _datum(rij.get("date"))
        if datum is None:
            continue
        if vanaf is None or datum >= vanaf:
            omschrijving = rij.get("name") or rij.get("ref") or None
            mutaties.append(
                RcMutatie.maak(
                    id=str(rij.get("id") or ""),
                    datum=datum,
                    bedrag=bedrag,
                    omschrijving=omschrijving if isinstance(omschrijving, str) else None,
                    boekstuk=rij.get("move_name") if isinstance(rij.get("move_name"), str) else None,
                )
            )
    return saldo.quantize(_CENT), mutaties


# ---- per administratie: de juiste lezer -----------------------------------------------------------


class KantNietLeesbaar(Exception):
    """Eén kant van een RC-paar kon niet gelezen worden (geen credential, onbekende Odoo-rekening, API-fout) — de
    aanroeper maakt er een ZICHTBARE FOUT-regel van, nooit een bevinding en nooit een stille overslag."""


def _lees_kant(
    administratie_id: uuid.UUID, ledger_id: uuid.UUID, *, vanaf: date | None
) -> tuple[Decimal, list[RcMutatie]]:
    from app.backends.registry import backend_voor

    backend = backend_voor(administratie_id)
    if backend == Backend.ODOO:
        from app.odoo import sync as odoo_sync
        from app.odoo.inkoop import OdooInkoopPort

        with OdooInkoopPort.voor(administratie_id) as port:
            with scoped_session(administratie_id) as session:
                account_id = odoo_sync.odoo_id_voor(
                    session, administratie_id=administratie_id, model=odoo_sync.MODEL_ACCOUNT, lokaal_id=ledger_id
                )
            return saldo_en_mutaties_odoo(port.client, account_id=account_id, vanaf=vanaf)
    from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    return saldo_en_mutaties_rlz(client, ledger_id=ledger_id, vanaf=vanaf)


def lees_kant(
    administratie_id: uuid.UUID, ledger_id: uuid.UUID, *, vanaf: date | None
) -> tuple[Decimal, list[RcMutatie]]:
    """Test-seam (monkeypatch) + foutvertaling: webfilter gaat door (meting ongeldig), al het andere →
    `KantNietLeesbaar`."""
    try:
        return _lees_kant(administratie_id, ledger_id, vanaf=vanaf)
    except RlzWebfilterError:
        raise
    except Exception as exc:  # noqa: BLE001 — zichtbaar als FOUT-regel, de andere koppelingen lopen door
        raise KantNietLeesbaar(str(exc) or exc.__class__.__name__) from exc


# ---- rc_stand: venster + cache --------------------------------------------------------------------


def actieve_koppelingen(administratie_ids: Iterable[uuid.UUID] | None = None) -> list[RcKoppeling]:
    """Alle `rc_koppeling`-rijen met status afgeleid|bevestigd (rekening_b NULL inbegrepen — die worden een let_op).
    Optioneel beperkt tot koppelingen waarvan A óf B in `administratie_ids` zit."""
    ids = set(administratie_ids or [])
    with scoped_session(None) as session:
        q = (
            select(RcKoppeling)
            .where(RcKoppeling.status.in_(ACTIEVE_STATUSSEN))
            .order_by(RcKoppeling.administratie_a_id, RcKoppeling.rekening_a_code, RcKoppeling.id)
        )
        rijen = list(session.scalars(q).all())
        for r in rijen:
            session.expunge(r)
    if ids:
        rijen = [r for r in rijen if r.administratie_a_id in ids or r.administratie_b_id in ids]
    return rijen


def venster_vanaf(koppeling_id: uuid.UUID, *, vandaag: date | None = None) -> date:
    """Dag ná de laatste groene stand, anders `VENSTER_DAGEN` terug."""
    vandaag = vandaag or vandaag_nl()
    with scoped_session(None) as session:
        laatste = session.scalar(
            select(RcStand.datum)
            .where(RcStand.koppeling_id == koppeling_id, RcStand.sluit.is_(True), RcStand.datum < vandaag)
            .order_by(RcStand.datum.desc())
            .limit(1)
        )
    if laatste is not None:
        return laatste + timedelta(days=1)
    return vandaag - timedelta(days=VENSTER_DAGEN)


def schrijf_stand(
    *, koppeling_id: uuid.UUID, saldo_a: Decimal, saldo_b: Decimal, sluit: bool, datum: date | None = None
) -> None:
    """Eén `rc_stand`-rij per koppeling per dag (upsert op PK) — ook bij rood, zodat de historie compleet is."""
    datum = datum or vandaag_nl()
    with scoped_session(None) as session:
        stmt = pg_insert(RcStand).values(
            koppeling_id=koppeling_id, datum=datum, saldo_a=saldo_a, saldo_b=saldo_b, sluit=sluit
        )
        stmt = stmt.on_conflict_do_update(
            index_elements=[RcStand.koppeling_id, RcStand.datum],
            set_={"saldo_a": saldo_a, "saldo_b": saldo_b, "sluit": sluit, "gemeten_op": datetime.now().astimezone()},
        )
        session.execute(stmt)
        session.commit()


def _namen(ids: Iterable[uuid.UUID]) -> dict[uuid.UUID, str]:
    ids = set(ids)
    if not ids:
        return {}
    with scoped_session(None) as session:
        rijen = session.execute(select(Administratie.id, Administratie.naam).where(Administratie.id.in_(ids))).all()
        return dict(rijen)


# ---- detail + blokfunctie -------------------------------------------------------------------------


def acceptatie_detail(k: RcKoppeling, uitkomst: RcUitkomst) -> str:
    """De acceptatie-sleutel: stabiel per paar zolang de Δ gelijk blijft — geen datum van vandaag, geen saldo's
    (die verschuiven dagelijks mee terwijl de afwijking dezelfde blijft)."""
    return (
        f"rekening_a={k.rekening_a_code or k.rekening_a} rekening_b={k.rekening_b_code or k.rekening_b} "
        f"delta={uitkomst.delta}"
    )


def bevinding_detail(
    k: RcKoppeling, uitkomst: RcUitkomst, *, namen: dict[uuid.UUID, str], venster: date
) -> dict[str, Any]:
    """Naamvelden voor `teksten.py::_rekening_courant` en de UI-uitklap (0114-JSONB: alleen JSON-veilige waarden)."""
    return {
        "koppeling_id": str(k.id),
        "administratie_a_naam": namen.get(k.administratie_a_id),
        "administratie_b_naam": namen.get(k.administratie_b_id),
        "administratie_b_id": str(k.administratie_b_id),
        "rekening_a_code": k.rekening_a_code,
        "rekening_a_naam": k.rekening_a_naam,
        "rekening_b_code": k.rekening_b_code,
        "rekening_b_naam": k.rekening_b_naam,
        "saldo_a": str(uitkomst.saldo_a),
        "saldo_b": str(uitkomst.saldo_b),
        "delta": str(uitkomst.delta),
        "ontbreekt_bij_a": uitkomst.regels_bij_a(),
        "ontbreekt_bij_b": uitkomst.regels_bij_b(),
        "niet_herleidbaar": uitkomst.niet_herleidbaar,
        "gematcht": uitkomst.gematcht,
        "venster_vanaf": venster.isoformat(),
        "administratie_naam": namen.get(k.administratie_a_id),
    }


def _let_op_detail(k: RcKoppeling, *, namen: dict[uuid.UUID, str]) -> dict[str, Any]:
    return {
        "afwijking_soort": SOORT_ZONDER_TEGENREKENING,
        "rc_zonder_tegenrekening": True,
        "koppeling_id": str(k.id),
        "administratie_a_naam": namen.get(k.administratie_a_id),
        "administratie_b_naam": namen.get(k.administratie_b_id),
        "administratie_b_id": str(k.administratie_b_id),
        "rekening_a_code": k.rekening_a_code,
        "rekening_a_naam": k.rekening_a_naam,
        "administratie_naam": namen.get(k.administratie_a_id),
        "doel_pad": "/instellingen/boeken",
    }


def _paar_label(k: RcKoppeling, namen: dict[uuid.UUID, str]) -> str:
    a = namen.get(k.administratie_a_id) or str(k.administratie_a_id)
    b = namen.get(k.administratie_b_id) or str(k.administratie_b_id)
    return f"{a} {k.rekening_a_code or ''} ↔ {b} {k.rekening_b_code or '(geen tegenrekening)'}".replace("  ", " ")


def cli_blok(args, verzamelaar=None, *, stdout: Callable[[str], None] = print, stderr=None) -> int:  # noqa: ANN001
    """Blokfunctie voor `reconciliatie-alles` (contract `def _x(args, verzamelaar=None) -> int`): per actieve
    koppeling beide kanten lezen, toetsen, `rc_stand` schrijven (alleen in een vastgelegde run — lees-only print
    alleen), bevindingen melden; exit 1 zodra er een open afwijking of een fout is. `args.administratie_ids`
    beperkt tot koppelingen waarvan A of B erin zit."""
    from app.reconciliatie import service as acceptatie_service

    stderr = stderr or (lambda tekst: print(tekst, file=sys.stderr))
    lees_only = verzamelaar is None
    administratie_ids = getattr(args, "administratie_ids", None)

    def meld(**kw) -> None:  # noqa: ANN003
        if verzamelaar is not None:
            verzamelaar.bevinding(**kw)

    koppelingen = actieve_koppelingen(administratie_ids)
    namen = _namen([k.administratie_a_id for k in koppelingen] + [k.administratie_b_id for k in koppelingen])
    try:
        uitgesloten = acceptatie_service.uitgesloten_administraties()
    except Exception:  # noqa: BLE001 — een uitsluitingslookup mag het blok nooit laten omvallen
        uitgesloten = {}
    if verzamelaar is not None:
        verzamelaar.gecontroleerd(len(koppelingen))
    if not koppelingen:
        stdout("OK         geen actieve rekening-courant-koppelingen (afleiding: sync-alles / Instellingen › Boeken)")
        return 0

    vandaag = vandaag_nl()
    open_totaal = geaccepteerd_totaal = fouten = sluit_totaal = zonder_tegen = 0
    for k in koppelingen:
        label = _paar_label(k, namen)
        aid = k.administratie_a_id
        if k.rekening_b is None:
            zonder_tegen += 1
            tekst = f"LET-OP     {label}: RC zonder tegenrekening (koppeling {k.id})"
            stdout(tekst)
            meld(
                soort="let_op",
                administratie_id=aid,
                tekst=tekst,
                vingerafdruk=acceptatie_service.vingerafdruk(
                    bron=ReconciliatieBron.REKENING_COURANT.value, soort=SOORT_ZONDER_TEGENREKENING, detail=str(k.id)
                ),
                detail=_let_op_detail(k, namen=namen),
            )
            continue

        try:
            venster = venster_vanaf(k.id, vandaag=vandaag)
        except Exception:  # noqa: BLE001 — geen stand leesbaar = volledig venster
            logger.exception("rc_stand niet gelezen voor %s", k.id)
            venster = vandaag - timedelta(days=VENSTER_DAGEN)
        try:
            saldo_a, mutaties_a = lees_kant(aid, k.rekening_a, vanaf=venster)
            saldo_b, mutaties_b = lees_kant(k.administratie_b_id, k.rekening_b, vanaf=venster)
        except RlzWebfilterError as exc:
            fouten += 1
            tekst = f"FOUT       {label}: {MELDING_METING_ONGELDIG} ({exc})"
            stderr(tekst)
            meld(
                soort="fout",
                administratie_id=aid,
                tekst=tekst,
                detail={"fout": MELDING_METING_ONGELDIG, "administratie_naam": namen.get(aid)},
            )
            continue
        except KantNietLeesbaar as exc:
            fouten += 1
            tekst = f"FOUT       {label}: kant niet leesbaar — {exc}"
            stderr(tekst)
            meld(
                soort="fout",
                administratie_id=aid,
                tekst=tekst,
                detail={"fout": str(exc), "administratie_naam": namen.get(aid)},
            )
            continue

        uitkomst = toets_paar(saldo_a=saldo_a, saldo_b=saldo_b, mutaties_a=mutaties_a, mutaties_b=mutaties_b)
        if not lees_only:
            try:
                schrijf_stand(
                    koppeling_id=k.id,
                    saldo_a=uitkomst.saldo_a,
                    saldo_b=uitkomst.saldo_b,
                    sluit=uitkomst.sluit,
                    datum=vandaag,
                )
            except Exception:  # noqa: BLE001 — de cache is een cache; de toets telt
                logger.exception("rc_stand niet geschreven voor %s", k.id)

        if uitkomst.sluit:
            sluit_totaal += 1
            stdout(f"OK         {label}: sluit ({euro_nl(uitkomst.saldo_a)} / {euro_nl(uitkomst.saldo_b)})")
            continue

        detail_str = acceptatie_detail(k, uitkomst)
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.REKENING_COURANT,
            administratie_id=aid,
            afwijkingen=[(k.id, SOORT_SLUIT_NIET, detail_str)],
        )[0]
        uitsluiting = uitgesloten.get(aid)
        naam_a, naam_b = namen.get(aid) or "A", namen.get(k.administratie_b_id) or "B"
        verklaring = "; ".join(
            [
                *(f"ontbreekt bij {naam_b}: {r}" for r in uitkomst.regels_bij_b()),
                *(f"ontbreekt bij {naam_a}: {r}" for r in uitkomst.regels_bij_a()),
            ]
        )
        if uitkomst.niet_herleidbaar:
            verklaring = uitkomst.tekst_niet_herleidbaar() + (f" (rest: {verklaring})" if verklaring else "")
        kern = (
            f"{label} soort={SOORT_SLUIT_NIET} [vaf:{beoordeeld.vingerafdruk}]: Δ {euro_nl(uitkomst.delta)} "
            f"(saldo A {euro_nl(uitkomst.saldo_a)}, saldo B {euro_nl(uitkomst.saldo_b)}, "
            f"venster sinds {venster.isoformat()}) — {verklaring}"
        )
        if uitsluiting:
            soort, tekst = "uitgesloten", f"UITGESLOTEN {kern} (uitgesloten: {uitsluiting})"
            stdout(tekst)
        elif beoordeeld.telt_mee:
            open_totaal += 1
            soort, tekst = "afwijking", f"AFWIJKING  {kern}"
            stderr(tekst)
        else:
            geaccepteerd_totaal += 1
            soort = "geaccepteerd"
            tekst = f"GEACCEPTEERD {kern} — reden: {beoordeeld.acceptatie.reden}"
            stdout(tekst)
        meld(
            soort=soort,
            administratie_id=aid,
            tekst=tekst,
            vingerafdruk=beoordeeld.vingerafdruk,
            detail={
                "bron": ReconciliatieBron.REKENING_COURANT.value,
                "record_id": str(k.id),
                "afwijking_soort": SOORT_SLUIT_NIET,
                "detail": detail_str,
                "geaccepteerd": not beoordeeld.telt_mee,
                "uitsluiting": uitsluiting,
                **bevinding_detail(k, uitkomst, namen=namen, venster=venster),
            },
        )

    stdout(
        f"\n{len(koppelingen)} rekening-courant-koppeling(en) getoetst: {sluit_totaal} sluiten, {open_totaal} open, "
        f"{geaccepteerd_totaal} geaccepteerd, {zonder_tegen} zonder tegenrekening, {fouten} niet leesbaar."
    )
    if open_totaal or fouten:
        stderr(f"{open_totaal} open RC-afwijking(en) en {fouten} niet-leesbare koppeling(en)")
        return 1
    return 0
