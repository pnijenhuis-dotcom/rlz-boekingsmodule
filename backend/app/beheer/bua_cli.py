"""BUA-kandidaten (lees-only) + bua-kenmerk-zetten (schrijvend, mét --dry-run) — opdracht Peter 21-09, vervolg op het
kenmerk `btw_aftrek_uitgesloten` (18-09, migratie 0163; `app/beheer/btw_aftrek.py`).

Aanleiding: het kenmerk staat in productie nergens aan (meting 21-09 op de leesreplica: 79 administraties, vier
RLZ-standaardrekeningen 4014/4503/4508/4510 in 74–75 administraties, 0 × kenmerk). De Beheerder-knop "Voorstel
overnemen" per administratie is bij 75 administraties invulwerk; dit bestand geeft (1) de kantoorbrede meting als
nameting-instrument en (2) de bulk-zetting als expliciete, idempotente data-stap ná Peters "ja".

- `bua-kandidaten [--administratie <uuid|naamdeel>] [--jaar 2026] [--detail] [--json-uit]` — LEES-ONLY (nameting-
  allowlist): per administratie de niet-verdwenen 4xxx-kostenrekeningen (AccountType 2) waarvan de naam een BUA-woord
  bevat (`BUA_NAAMDELEN`, breder dan `btw_aftrek.VOORSTEL_NAAMDELEN`), mét kenmerk-stand, RLZ-default, historie-default,
  module-geboekt in het jaar (boekvoorstel-regels van GEBOEKTE inkoopfacturen, factuurdatum in het jaar) en bank-direct-
  geboekt (bank_boeking_regel van GEBOEKTE bank_boekingen, geboekt_op in het jaar) — GEEN RLZ-call: de RLZ-kant is
  "niet gemeten". Advies per rekening = pure functie `advies_voor`.
- `bua-kenmerk-zetten (--administratie <uuid|naamdeel> | --alles) [--codes 4508,4510] [--dry-run]` — SCHRIJVEND, nooit
  via nameting.sh: per administratie de rekeningen met die codes (soort 2, niet verdwenen) aanzetten via
  `btw_aftrek.voeg_toe` (bestaande set ∪ nieuw; audit `btw_aftrek_uitgesloten_gewijzigd` oud→nieuw mét `bron`),
  systeem-actor; al aan = "ongewijzigd"; tweede run = 0 wijzigingen. Productie: `gcloud run jobs execute
  rlz-reconciliatie --args="^|^-m|app.cli|bua-kenmerk-zetten|--alles|--dry-run"` en pas ná Peters "ja" zonder
  `--dry-run`.

RLS: `grootboekrekening`, `document`, `boekvoorstel*` en `bank_boeking*` zijn per administratie — administraties worden
platformbreed gelezen (`scoped_session(None)`), daarna élke administratie in haar EIGEN `scoped_session(aid)` (patroon
`app/geheugen/grootboek_btw_historie.herbereken_alle`); één cross-administratie-query in `scoped_session(None)` geeft in
productie stil 0 rijen. Een kapotte administratie stopt de rest niet: de fout is een zichtbare regel in de uitvoer.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import uuid
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

COMMANDO_KANDIDATEN = "bua-kandidaten"
COMMANDO_ZETTEN = "bua-kenmerk-zetten"
COMMANDOS = (COMMANDO_KANDIDATEN, COMMANDO_ZETTEN)

#: Naamdelen die een 4xxx-kostenrekening tot BUA-kandidaat maken (meting 21-09; breder dan het scherm-voorstel).
BUA_NAAMDELEN = (
    "representatie",
    "relatiegeschenk",
    "geschenk",
    "kantine",
    "consumptie",
    "eten en drinken",
    "lunch",
    "diner",
    "horeca",
    "personeelsfeest",
    "personeelsuitje",
    "bedrijfsuitje",
    "giften",
    "sponsoring",
)
BUA_NAAM_RE = re.compile("|".join(re.escape(d) for d in BUA_NAAMDELEN), re.IGNORECASE)
#: Default-codes van het bulk-voorstel (rapport 21-09): relatiegeschenken + representatiekosten.
DEFAULT_CODES = ("4508", "4510")
BRON_ZETTEN = "cli bua-kenmerk-zetten (opdracht Peter 21-09)"
SOORT_KOSTEN = 2

ADVIES_ZETTEN = "zetten"
ADVIES_NIET_ZETTEN = "niet_zetten"
ADVIES_BEOORDELEN = "beoordelen"

# Volgorde is bindend (contract B 21-09): eerst de "zetten"-groepen, dan "beoordelen", dan "niet_zetten".
_ADVIES_REGELS: tuple[tuple[tuple[str, ...], str, str], ...] = (
    (
        ("representatie", "relatiegeschenk", "geschenk"),
        ADVIES_ZETTEN,
        "BUA: btw op representatie/relatiegeschenken is niet aftrekbaar boven € 227 per begunstigde per jaar; "
        "horeca-deel nooit aftrekbaar (art. 15 lid 5 Wet OB)",
    ),
    (
        ("horeca", "lunch", "diner", "eten en drinken", "consumptie"),
        ADVIES_ZETTEN,
        "art. 15 lid 5 Wet OB: btw op horeca (eten en drinken in een horecagelegenheid) is nooit aftrekbaar",
    ),
    (
        ("kantine",),
        ADVIES_BEOORDELEN,
        "BUA-kantineregeling: aftrek wél, correctie aan het jaareinde bij bevoordeling > € 227 — het kenmerk zet "
        "altijd álle btw in de kosten (te conservatief)",
    ),
    (
        ("personeelsfeest", "personeelsuitje", "bedrijfsuitje", "giften"),
        ADVIES_BEOORDELEN,
        "BUA: aftrekbaar tot € 227 per persoon per jaar — het kenmerk is conservatief",
    ),
    (
        ("sponsoring", "promotie"),
        ADVIES_NIET_ZETTEN,
        "zakelijke reclamekosten, btw aftrekbaar; alleen het geschenkdeel valt onder het BUA",
    ),
)


def advies_voor(code: str, naam: str) -> tuple[str, str]:
    """Pure regel: (advies, reden) uit code + naam. Deterministisch, geen DB, geen AI."""
    n = (naam or "").lower()
    for woorden, advies, reden in _ADVIES_REGELS:
        if any(w in n for w in woorden):
            return advies, reden
    return ADVIES_BEOORDELEN, "naam past bij geen BUA-categorie uit de regeltabel — mens beoordeelt"


def is_kandidaat(*, code: str, naam: str, soort: int) -> bool:
    """4xxx-kostenrekening (AccountType 2) waarvan de naam een BUA-woord bevat."""
    return bool(code) and code.startswith("4") and soort == SOORT_KOSTEN and BUA_NAAM_RE.search(naam or "") is not None


@dataclass
class KandidaatRij:
    administratie_id: str
    administratie: str
    ledger_id: str
    code: str
    naam: str
    kenmerk: bool
    rlz_default: str | None  # naam van het RLZ-default-tarief, None = geen
    rlz_default_pct: str | None  # percentage als tekst ("0", "0.21"), None = geen
    historie_default: str | None  # naam van het historie-default-tarief, None = geen
    mod_n: int = 0
    mod_netto: str = "0.00"
    mod_btw: str = "0.00"
    bank_n: int = 0
    bank_netto: str = "0.00"
    bank_btw: str = "0.00"
    advies: str = ADVIES_BEOORDELEN
    reden: str = ""


@dataclass
class Samenvatting:
    code: str
    naam: str
    administraties: int = 0
    kenmerk_aan: int = 0
    rlz_default_nul_of_geen: int = 0
    mod_n: int = 0
    mod_netto: Decimal = Decimal("0")
    mod_btw: Decimal = Decimal("0")
    bank_n: int = 0
    bank_netto: Decimal = Decimal("0")
    bank_btw: Decimal = Decimal("0")
    advies: str = ADVIES_BEOORDELEN
    reden: str = ""


@dataclass
class Meting:
    jaar: int
    administraties: int
    rijen: list[KandidaatRij] = field(default_factory=list)
    fouten: list[str] = field(default_factory=list)


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    k = subparsers.add_parser(
        COMMANDO_KANDIDATEN,
        help="LEES-ONLY (21-09): BUA-kandidaat-rekeningen (4xxx kosten, naam representatie/geschenk/kantine/horeca/…) "
        "per administratie mét kenmerk-stand, RLZ-/historie-default, module- en bank-geboekt in --jaar en advies. "
        "Geen RLZ-call.",
    )
    k.add_argument("--administratie", default=None, help="Beperk tot één administratie (uuid of naamdeel).")
    k.add_argument("--jaar", type=int, default=2026, help="Boekjaar voor de geboekte bedragen (default 2026).")
    k.add_argument("--detail", action="store_true", help="Toon ook de rijen per administratie.")
    k.add_argument("--json-uit", action="store_true", dest="json_uit", help="Machineleesbare uitvoer (JSON).")

    z = subparsers.add_parser(
        COMMANDO_ZETTEN,
        help="SCHRIJVEND (21-09, expliciete opdracht Peter): kenmerk 'btw niet aftrekbaar' aanzetten op de rekeningen "
        "met "
        "--codes (default 4508,4510) — bestaande set ∪ nieuw, audit oud→nieuw, idempotent. --dry-run telt alleen.",
    )
    doel = z.add_mutually_exclusive_group(required=True)
    doel.add_argument("--administratie", default=None, help="Eén administratie (uuid of naamdeel).")
    doel.add_argument("--alles", action="store_true", help="Alle actieve administraties.")
    z.add_argument(
        "--codes", default=",".join(DEFAULT_CODES), help="Grootboekcodes, kommagescheiden (default 4508,4510)."
    )
    z.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tellen en tonen, niets schrijven.")


def dispatch(args: argparse.Namespace) -> int | None:
    """None = niet ons commando (cli.py gaat verder); anders de exit-code."""
    commando = getattr(args, "commando", None)
    if commando == COMMANDO_KANDIDATEN:
        return kandidaten(args)
    if commando == COMMANDO_ZETTEN:
        return kenmerk_zetten(args)
    return None


# ---- administraties -------------------------------------------------------------------------------------------------


def _administraties(term: str | None) -> list[tuple[uuid.UUID, str]] | None:
    """Alle actieve administraties (platformbreed, `scoped_session(None)`), of de ene die `term` aanwijst.
    None = term onbekend/niet eenduidig (fout al op stderr)."""
    from sqlalchemy import select

    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.geheugen.btw_default_cli import _zoek_administratie

    if term:
        gevonden = _zoek_administratie(term)
        return [gevonden] if gevonden is not None else None
    with scoped_session(None) as session:
        rijen = session.execute(
            select(Administratie.id, Administratie.naam)
            .where(Administratie.actief.is_(True))
            .order_by(Administratie.naam)
        ).all()
    return [(r.id, r.naam) for r in rijen]


# ---- kandidaten (lees-only) ------------------------------------------------------------------------------------------


def _d(x) -> str:  # noqa: ANN001
    return f"{(Decimal(x) if x is not None else Decimal(0)):.2f}"


def kandidaten_voor(administratie_id: uuid.UUID, administratie_naam: str, *, jaar: int) -> list[KandidaatRij]:
    """Eén administratie in haar eigen scope: kandidaat-rekeningen + stand + geboekte bedragen (module én bank)."""
    from sqlalchemy import func, select

    from app.bank.models import BankBoeking, BankBoekingRegel, BankBoekingStatus
    from app.db.models import Grootboekrekening
    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel, BoekvoorstelRegel, Document, DocumentSoort, DocumentStatus
    from app.sync.models import TaxRateCache

    van, tot = date(jaar, 1, 1), date(jaar, 12, 31)
    van_dt = datetime.combine(van, datetime.min.time(), tzinfo=UTC)
    tot_dt = datetime.combine(date(jaar + 1, 1, 1), datetime.min.time(), tzinfo=UTC)
    uit: list[KandidaatRij] = []
    with scoped_session(administratie_id) as session:
        tarieven = {
            t.id: t
            for t in session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == administratie_id))
        }
        rekeningen = [
            r
            for r in session.scalars(
                select(Grootboekrekening)
                .where(
                    Grootboekrekening.administratie_id == administratie_id,
                    Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                    Grootboekrekening.is_totaalrekening.is_(False),
                    Grootboekrekening.soort == SOORT_KOSTEN,
                    Grootboekrekening.code.like("4%"),
                )
                .order_by(Grootboekrekening.code)
            )
            if is_kandidaat(code=r.code, naam=r.naam, soort=r.soort)
        ]
        if not rekeningen:
            return []
        ledger_ids = [r.ledger_id for r in rekeningen]
        module = {
            rij.ledger_id: rij
            for rij in session.execute(
                select(
                    BoekvoorstelRegel.ledger_id,
                    func.count().label("n"),
                    func.coalesce(func.sum(BoekvoorstelRegel.netto_bedrag), 0).label("netto"),
                    func.coalesce(func.sum(BoekvoorstelRegel.btw_bedrag), 0).label("btw"),
                )
                .join(Boekvoorstel, Boekvoorstel.document_id == BoekvoorstelRegel.document_id)
                .join(Document, Document.id == Boekvoorstel.document_id)
                .where(
                    Document.administratie_id == administratie_id,
                    Document.status == DocumentStatus.GEBOEKT,
                    Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                    Boekvoorstel.factuurdatum >= van,
                    Boekvoorstel.factuurdatum <= tot,
                    BoekvoorstelRegel.ledger_id.in_(ledger_ids),
                )
                .group_by(BoekvoorstelRegel.ledger_id)
            ).all()
        }
        bank = {
            rij.ledger_id: rij
            for rij in session.execute(
                select(
                    BankBoekingRegel.ledger_id,
                    func.count().label("n"),
                    func.coalesce(func.sum(BankBoekingRegel.netto_bedrag), 0).label("netto"),
                    func.coalesce(func.sum(BankBoekingRegel.btw_bedrag), 0).label("btw"),
                )
                .join(BankBoeking, BankBoeking.id == BankBoekingRegel.bank_boeking_id)
                .where(
                    BankBoeking.administratie_id == administratie_id,
                    BankBoeking.status == BankBoekingStatus.GEBOEKT.value,
                    BankBoeking.geboekt_op >= van_dt,
                    BankBoeking.geboekt_op < tot_dt,
                    BankBoekingRegel.ledger_id.in_(ledger_ids),
                )
                .group_by(BankBoekingRegel.ledger_id)
            ).all()
        }
        for r in rekeningen:
            rlz = tarieven.get(r.standaard_taxrate_id) if r.standaard_taxrate_id else None
            hist = tarieven.get(r.historie_taxrate_id) if r.historie_taxrate_id else None
            m = module.get(r.ledger_id)
            b = bank.get(r.ledger_id)
            advies, reden = advies_voor(r.code, r.naam)
            uit.append(
                KandidaatRij(
                    administratie_id=str(administratie_id),
                    administratie=administratie_naam,
                    ledger_id=str(r.ledger_id),
                    code=r.code,
                    naam=r.naam,
                    kenmerk=bool(r.btw_aftrek_uitgesloten),
                    rlz_default=rlz.naam if rlz is not None else None,
                    rlz_default_pct=(f"{rlz.percentage.normalize():f}" if rlz is not None else None),
                    historie_default=hist.naam if hist is not None else None,
                    mod_n=int(m.n) if m else 0,
                    mod_netto=_d(m.netto) if m else "0.00",
                    mod_btw=_d(m.btw) if m else "0.00",
                    bank_n=int(b.n) if b else 0,
                    bank_netto=_d(b.netto) if b else "0.00",
                    bank_btw=_d(b.btw) if b else "0.00",
                    advies=advies,
                    reden=reden,
                )
            )
    return uit


def meet(*, administratie: str | None, jaar: int) -> Meting | None:
    """Kantoorbreed (of één administratie): per administratie een eigen scope; een kapotte administratie wordt een
    fout-regel, de rest loopt door. None = administratie-term onbekend."""
    adms = _administraties(administratie)
    if adms is None:
        return None
    meting = Meting(jaar=jaar, administraties=len(adms))
    for aid, naam in adms:
        try:
            meting.rijen.extend(kandidaten_voor(aid, naam, jaar=jaar))
        except Exception as exc:  # noqa: BLE001 — per administratie zichtbaar, de rest gaat door
            meting.fouten.append(f"{naam} ({aid}): {type(exc).__name__}: {exc}")
    return meting


def samenvat(rijen: list[KandidaatRij]) -> list[Samenvatting]:
    """Per code × naam: administraties, kenmerk aan, RLZ-default 0 %/geen, sommen, advies."""
    per: dict[tuple[str, str], Samenvatting] = {}
    for r in rijen:
        s = per.setdefault((r.code, r.naam), Samenvatting(code=r.code, naam=r.naam, advies=r.advies, reden=r.reden))
        s.administraties += 1
        s.kenmerk_aan += 1 if r.kenmerk else 0
        if r.rlz_default is None or Decimal(r.rlz_default_pct or "0") == 0:
            s.rlz_default_nul_of_geen += 1
        s.mod_n += r.mod_n
        s.mod_netto += Decimal(r.mod_netto)
        s.mod_btw += Decimal(r.mod_btw)
        s.bank_n += r.bank_n
        s.bank_netto += Decimal(r.bank_netto)
        s.bank_btw += Decimal(r.bank_btw)
    return sorted(per.values(), key=lambda s: (s.code, s.naam))


VOETTEKST_RLZ = (
    "RLZ-kant niet gemeten (lees-only, geen RLZ-call) — een RLZ-kant-meting is een aparte `--rlz`-stap (niet gebouwd)."
)


def kandidaten(args: argparse.Namespace) -> int:
    meting = meet(administratie=args.administratie, jaar=args.jaar)
    if meting is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    samen = samenvat(meting.rijen)
    if args.json_uit:
        print(
            json.dumps(
                {
                    "jaar": meting.jaar,
                    "administraties": meting.administraties,
                    "samenvatting": [
                        {k: (str(v) if isinstance(v, Decimal) else v) for k, v in asdict(s).items()} for s in samen
                    ],
                    "rijen": [asdict(r) for r in meting.rijen] if args.detail else None,
                    "fouten": meting.fouten,
                    "rlz_kant": "niet gemeten",
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    print(
        f"BUA-kandidaten — {meting.administraties} administratie(s), boekjaar {meting.jaar} (lees-only; kenmerk = "
        f"`btw_aftrek_uitgesloten`; module = geboekte inkoopfacturen op factuurdatum, bank = geboekte bank-direct-"
        f"boekingen op boekmoment)"
    )
    print(
        f"{'code':<6}{'rekening':<42}{'adm':>4}{'kenm':>5}{'rlz0':>5}{'mod_n':>6}{'mod_netto':>11}{'mod_btw':>9}"
        f"{'bank_n':>7}{'bank_netto':>11}{'bank_btw':>9}  advies"
    )
    for s in samen:
        print(
            f"{s.code:<6}{s.naam[:40]:<42}{s.administraties:>4}{s.kenmerk_aan:>5}{s.rlz_default_nul_of_geen:>5}"
            f"{s.mod_n:>6}{s.mod_netto:>11.2f}{s.mod_btw:>9.2f}{s.bank_n:>7}{s.bank_netto:>11.2f}{s.bank_btw:>9.2f}"
            f"  {s.advies} — {s.reden}"
        )
    if args.detail:
        print("\nDETAIL per administratie")
        print(
            f"{'administratie':<34}{'code':<6}{'rekening':<42}{'kenm':<5}{'rlz-default':<22}{'historie':<22}{'mod_n':>6}{'mod_netto':>11}{'mod_btw':>9}{'bank_n':>7}{'bank_netto':>11}{'bank_btw':>9}"
        )
        for r in sorted(meting.rijen, key=lambda r: (r.administratie, r.code)):
            print(
                f"{r.administratie[:32]:<34}{r.code:<6}{r.naam[:40]:<42}{('aan' if r.kenmerk else 'uit'):<5}"
                f"{(r.rlz_default or 'geen')[:20]:<22}{(r.historie_default or 'geen')[:20]:<22}"
                f"{r.mod_n:>6}{Decimal(r.mod_netto):>11.2f}{Decimal(r.mod_btw):>9.2f}"
                f"{r.bank_n:>7}{Decimal(r.bank_netto):>11.2f}{Decimal(r.bank_btw):>9.2f}"
            )
    for fout in meting.fouten:
        print(f"FOUT  {fout}")
    kenmerk_aan = sum(1 for r in meting.rijen if r.kenmerk)
    zetten = sum(1 for r in meting.rijen if r.advies == ADVIES_ZETTEN)
    print(
        f"\nTOTAAL {len(meting.rijen)} kandidaat-rekening(en) in {len({r.administratie_id for r in meting.rijen})} van "
        f"{meting.administraties} administratie(s) · {kenmerk_aan} mét kenmerk aan · advies zetten: {zetten} · "
        f"module {sum(r.mod_n for r in meting.rijen)} regel(s) "
        f"netto {sum(Decimal(r.mod_netto) for r in meting.rijen):.2f} "
        f"btw {sum(Decimal(r.mod_btw) for r in meting.rijen):.2f} · "
        f"bank {sum(r.bank_n for r in meting.rijen)} regel(s) · "
        f"{len(meting.fouten)} fout(en)"
    )
    print(VOETTEKST_RLZ)
    return 0


# ---- kenmerk zetten (schrijvend) ------------------------------------------------------------------------------------


@dataclass
class ZetUitkomst:
    administratie: str
    administratie_id: str
    te_zetten: list[str] = field(default_factory=list)  # codes die (zouden) wijzigen
    al_aan: list[str] = field(default_factory=list)
    niet_gevonden: list[str] = field(default_factory=list)
    fout: str | None = None


def _parse_codes(tekst: str) -> list[str] | None:
    codes = [c.strip() for c in (tekst or "").split(",") if c.strip()]
    if not codes or any(not re.fullmatch(r"\d{3,6}", c) for c in codes):
        return None
    return sorted(set(codes))


def zet_voor(administratie_id: uuid.UUID, naam: str, *, codes: list[str], dry_run: bool) -> ZetUitkomst:
    """Eén administratie in haar eigen scope: rekeningen met `codes` (soort 2, niet verdwenen) → `btw_aftrek.voeg_toe`.
    Al aan = ongewijzigd; dry-run schrijft niets."""
    from sqlalchemy import select

    from app.beheer import btw_aftrek
    from app.db.models import Grootboekrekening
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    uit = ZetUitkomst(administratie=naam, administratie_id=str(administratie_id))
    with scoped_session(administratie_id) as session:
        rijen = session.scalars(
            select(Grootboekrekening).where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
                Grootboekrekening.soort == SOORT_KOSTEN,
                Grootboekrekening.code.in_(codes),
            )
        ).all()
        per_code = {r.code: r for r in rijen}
        uit.niet_gevonden = [c for c in codes if c not in per_code]
        uit.al_aan = sorted(c for c, r in per_code.items() if r.btw_aftrek_uitgesloten)
        te_zetten = {c: r.ledger_id for c, r in per_code.items() if not r.btw_aftrek_uitgesloten}
        uit.te_zetten = sorted(te_zetten)
    if te_zetten and not dry_run:
        btw_aftrek.voeg_toe(
            actor_id=SYSTEEM_ACTOR_ID,
            administratie_id=administratie_id,
            ledger_ids=list(te_zetten.values()),
            bron=BRON_ZETTEN,
        )
    return uit


def kenmerk_zetten(args: argparse.Namespace) -> int:
    codes = _parse_codes(args.codes)
    if codes is None:
        print(f"FOUT  --codes {args.codes!r}: verwacht kommagescheiden grootboekcodes (bv. 4508,4510)", file=sys.stderr)
        return 2
    adms = _administraties(None if args.alles else args.administratie)
    if adms is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    stand = (
        "DRY-RUN — niets geschreven"
        if args.dry_run
        else "GESCHREVEN (audit btw_aftrek_uitgesloten_gewijzigd, systeem-actor)"
    )
    print(f"bua-kenmerk-zetten — codes {','.join(codes)} · {len(adms)} administratie(s) · {stand}")
    uitkomsten: list[ZetUitkomst] = []
    for aid, naam in adms:
        try:
            uitkomsten.append(zet_voor(aid, naam, codes=codes, dry_run=args.dry_run))
        except Exception as exc:  # noqa: BLE001 — per administratie zichtbaar, de rest gaat door
            uitkomsten.append(
                ZetUitkomst(administratie=naam, administratie_id=str(aid), fout=f"{type(exc).__name__}: {exc}")
            )
    werkwoord = "zou zetten" if args.dry_run else "gezet"
    for u in uitkomsten:
        if u.fout:
            print(f"FOUT  {u.administratie[:40]:<42}{u.fout}")
            continue
        print(
            f"      {u.administratie[:40]:<42}{werkwoord}: {','.join(u.te_zetten) or '—'} · al aan: "
            f"{','.join(u.al_aan) or '—'} · niet gevonden: {','.join(u.niet_gevonden) or '—'}"
        )
    gewijzigd = sum(len(u.te_zetten) for u in uitkomsten if not u.fout)
    adm_gewijzigd = sum(1 for u in uitkomsten if u.te_zetten and not u.fout)
    fouten = sum(1 for u in uitkomsten if u.fout)
    print(
        f"TOTAAL {gewijzigd} rekening(en) in {adm_gewijzigd} administratie(s) {werkwoord} · "
        f"{sum(len(u.al_aan) for u in uitkomsten)} al aan (ongewijzigd) · "
        f"{sum(len(u.niet_gevonden) for u in uitkomsten)} code(s) niet gevonden · {fouten} fout(en)"
    )
    return 0
