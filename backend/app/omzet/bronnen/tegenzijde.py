"""Tegenzijde per betaalwijze + btw-defaults van de omzetbronnen (besluiten Peter 16-09, opdracht 4 blok A/C/D).

Peter 16-09: "alleen de omzet boeken, dagstaten worden afgeboekt op bankontvangsten." De Receipt (entity-loze
SalesInvoice, bewezen write-vorm) blijft het énige omzetdocument; per betaalwijze registreert de module een
TEGENZIJDE-POST (bedrag, datum, tegenrekening + herkomst) waar de bank-matchmotor de echte ontvangst tegen legt:

- zonnestudio: PIN → tegenrekening "PIN/kruispost", Cash → kas, kasverschil (kascheck vs POS) → kasverschillen
  (oranje signaal blijft), storting automaat = kas → bank (matcht de sealbag-/stortingsontvangst op de bank);
- pilates: netto uitbetaling per batch → "Stripe/PSP onderweg", contant-batch → kas.

Tegenrekeningen komen uit de Beheerder-instelling `bron_instellingen.tegenrekeningen` en anders uit het RLZ-
rekeningschema OP NAAM (`platform.grootboekrekening`: kruispost / pin / onderweg / te ontvangen / kas / kasverschil /
stripe / psp) — nooit hardgecodeerde nummers; meerduidig = geen default (mens kiest). Geen tegenrekening bepaalbaar
voor een betaalwijze mét bedrag = BLOKKERENDE controle "Tegenrekening ‹betaalwijze›" mét handelingsperspectief.

Vorm van de RLZ-tegenzijde (beslispunt X4, default gekozen — zie beslissingen_X4.md): AFLETTERING. De PIN-/Stripe-
ontvangst op de bank wordt via het bewezen actie-15-pad (deel-)afgeletterd tegen de open post van de Receipt; de
storting kas → bank boekt direct-op-grootboek op de kas-tegenrekening (bewezen BankMutationDirectBookings-pad). Een
memoriaal-tegenzijde die de tussenrekening in RLZ zelf debiteert is NIET gebouwd: de credit-kant (de rekening waarop
RLZ een entity-loze Receipt laat landen) is niet geverifieerd — STAP-0 vóór die vorm.

Btw-defaults (blok C): laag voor lessen/sport/eten-drinken, hoog voor producten/punten — altijd het RLZ-TARIEF van de
administratie (`taxrate_cache`: fractie 0.09/0.21, niet verlegd, niet vrijgesteld, NL), nooit een hardgecodeerd
percentage; Punten (besluit Peter 16-09) = omzet zonnebank 21 % bij verkoop.

Alles puur (geen I/O): de servicelaag levert rekeningen/tarieven/instellingen aan."""

from __future__ import annotations

import re
import uuid
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal
from typing import Any

_TOL = Decimal("0.01")

# Betaalwijze-sleutels (contract CONTRACT_4 `tegenrekeningen`).
PIN = "pin"
CASH = "cash"
STRIPE = "stripe"
KASVERSCHIL = "kasverschil"
STORTING = "storting"
PSP_KOSTEN = "psp_kosten"
BETAALWIJZEN: tuple[str, ...] = (PIN, CASH, STRIPE, KASVERSCHIL, STORTING)

LABELS: dict[str, str] = {
    PIN: "PIN",
    CASH: "Contant (kas)",
    STRIPE: "Stripe/PSP-uitbetaling",
    KASVERSCHIL: "Kasverschil",
    STORTING: "Storting automaat (kas → bank)",
    PSP_KOSTEN: "Transactiekosten PSP",
}

HERKOMST_INSTELLING = "instelling"
HERKOMST_DEFAULT = "default"

#: Naam-patronen per sleutel, in volgorde van voorkeur; het EERSTE patroon met precies één niet-totaalrekening wint.
#: Woordgrenzen waar een substring te grof is ("kas" mag "kasverschillen" niet raken; "pin" niet "pinnen" o.i.d.).
_NAAM_PATRONEN: dict[str, tuple[str, ...]] = {
    PIN: (r"\bpin\b", r"kruispost", r"onderweg", r"te ontvangen"),
    CASH: (r"^kas$", r"\bkas\b(?!verschil)"),
    STORTING: (r"^kas$", r"\bkas\b(?!verschil)"),
    STRIPE: (r"stripe", r"\bpsp\b", r"onderweg", r"kruispost", r"te ontvangen"),
    KASVERSCHIL: (r"kasverschil",),
    PSP_KOSTEN: (r"transactiekosten", r"\bpsp\b", r"bankkosten"),
}

# Bank-matchvensters (dagen t.o.v. de post-datum, inclusief). Peter 16-09 (2): Stripe loopt altijd ACHTER op de
# omzet — bankdatum ≥ uitbetalings-/omzetdatum, +1 … +7 (weekend/feestdag), nooit ervoor. Storting kas → bank
# ± 3 dagen. PIN-ontvangsten (dagafrekening PSP) 0 … +5.
VENSTER_DAGEN: dict[str, tuple[int, int]] = {
    STRIPE: (1, 7),
    STORTING: (-3, 3),
    PIN: (0, 5),
    CASH: (0, 0),
    KASVERSCHIL: (0, 0),
}

#: Omschrijvingskernen waarop de bank-matchmotor de post herkent (lowercase, substring op de mutatietekst).
OMSCHRIJVINGSKERNEN: dict[str, tuple[str, ...]] = {
    STRIPE: ("stripe",),
    STORTING: ("storting", "sealbag", "afstorting", "sepa", "geldautomaat", "kasstorting"),
    PIN: ("pin", "ccv", "worldline", "adyen", "sepay", "payplaza", "buckaroo", "mollie", "sumup", "zettle", "izettle"),
}

# ---------------------------------------------------------------------------------------- btw-klassen

BTW_LAAG = "laag"
BTW_HOOG = "hoog"
BTW_VERLEGD = "verlegd"
#: ProfX/coffeeshop (Peter 16-09): cannabisomzet = "NL, Geen BTW (Vrijgesteld)" — bewust géén 0 %-tarief (BLOW-besluit,
#: aangifte-rubriek). Het default-tarief is het ENIGE vrijgestelde NL-tarief van de administratie (`IsExcempt`).
BTW_VRIJGESTELD = "vrijgesteld"
#: Canonieke fracties uit de taxrate-cache (app/sync/btw.py: fractie is de eenheid).
_FRACTIE_PER_KLASSE = {BTW_LAAG: Decimal("0.09"), BTW_HOOG: Decimal("0.21")}

#: Categorie-sleutel (lowercase, zoals `mapping.normaliseer_categorie_sleutel`) → btw-klasse-default.
BTW_KLASSE_PER_CATEGORIE: dict[str, str] = {
    # pilates (blok C): sport = laag, producten = hoog, eten/drinken = instelling (default laag)
    "pilateslessen": BTW_LAAG,
    "yoga": BTW_LAAG,
    "kleding producten": BTW_HOOG,
    # zonnestudio: zonnebank + producten + punten (besluit Peter 16-09: punten = omzet zonnebank 21 % bij verkoop)
    "points": BTW_HOOG,
    "products": BTW_HOOG,
    "tanning walk ins": BTW_HOOG,
    "tanning": BTW_HOOG,
    # ProfX Journaal (coffeeshop, Peter 16-09): Wiet/Hash/Joints vrijgesteld (BLOW-besluit), Edible = beslispunt →
    # default vrijgesteld mét oranje "bevestig"-controle (profx.BEVESTIG_GROEPEN), Dranken/Snacks laag, Headshop hoog.
    "wiet": BTW_VRIJGESTELD,
    "hash": BTW_VRIJGESTELD,
    "joints": BTW_VRIJGESTELD,
    "edible": BTW_VRIJGESTELD,
    "edibles": BTW_VRIJGESTELD,
    "dranken": BTW_LAAG,
    "snacks": BTW_LAAG,
    "headshop": BTW_HOOG,
}
CATEGORIE_ETEN_SLEUTEL = "eten drinken"
CATEGORIE_PSP_KOSTEN_SLEUTEL = "transactiekosten psp"

PSP_STRIPE = "stripe"
PSP_MOLLIE = "mollie"
PSP_ANDERS = "anders"
PSP_KEUZES: tuple[str, ...] = (PSP_STRIPE, PSP_MOLLIE, PSP_ANDERS)


@dataclass(frozen=True)
class Rekening:
    ledger_id: uuid.UUID
    code: str
    naam: str
    is_totaalrekening: bool = False


@dataclass(frozen=True)
class Tarief:
    taxrate_id: uuid.UUID
    naam: str | None
    percentage: Decimal | None
    is_verlegd: bool = False
    is_vrijgesteld: bool = False


@dataclass(frozen=True)
class Controle:
    naam: str
    ok: bool
    detail: str
    blokkerend: bool = True


@dataclass(frozen=True)
class TegenzijdeRegel:
    """Eén tegenzijde-post: betaalwijze, bedrag (positief = ontvangst die de bank nog moet tonen), datum-anker,
    tegenrekening + herkomst. `richting`: 'ontvangst' (bank moet 'm nog laten zien: PIN, Stripe, storting),
    'kas' (blijft in de kas; geen bankmatch), 'signaal' (kasverschil — nooit automatisch geboekt)."""

    betaalwijze: str
    bedrag: Decimal
    datum: date | None
    ledger_id: uuid.UUID | None
    herkomst: str | None
    richting: str
    label: str

    def als_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["bedrag"] = str(self.bedrag)
        d["datum"] = self.datum.isoformat() if self.datum else None
        d["ledger_id"] = str(self.ledger_id) if self.ledger_id else None
        d["venster_dagen"] = list(VENSTER_DAGEN.get(self.betaalwijze, (0, 0)))
        return d


@dataclass
class Tegenzijde:
    vorm: str
    regels: list[TegenzijdeRegel]
    controles: list[Controle] = field(default_factory=list)

    def als_dict(self) -> dict[str, Any]:
        return {
            "vorm": self.vorm,
            "regels": [r.als_dict() for r in self.regels],
            "controles": [asdict(c) for c in self.controles],
        }


VORM_AFLETTERING = "aflettering"

# ---------------------------------------------------------------------------------------- defaults op naam


def _kandidaten(rekeningen: list[Rekening], patroon: str) -> list[Rekening]:
    rx = re.compile(patroon, re.IGNORECASE)
    return [r for r in rekeningen if not r.is_totaalrekening and rx.search(r.naam or "")]


def default_rekening(sleutel: str, rekeningen: list[Rekening]) -> Rekening | None:
    """Het eerste naam-patroon van de sleutel met PRECIES één treffer wint; meerduidig of niets = None (mens kiest)."""
    for patroon in _NAAM_PATRONEN.get(sleutel, ()):
        treffers = _kandidaten(rekeningen, patroon)
        if len(treffers) == 1:
            return treffers[0]
    return None


def default_tegenrekeningen(rekeningen: list[Rekening]) -> dict[str, uuid.UUID | None]:
    """Code-default per betaalwijze uit het rekeningschema op naam (`defaults.tegenrekeningen` in de DTO)."""
    return {
        sleutel: (r.ledger_id if (r := default_rekening(sleutel, rekeningen)) else None) for sleutel in BETAALWIJZEN
    }


def default_psp_kosten_rekening(rekeningen: list[Rekening]) -> uuid.UUID | None:
    r = default_rekening(PSP_KOSTEN, rekeningen)
    return r.ledger_id if r else None


def default_tarief(klasse: str, tarieven: list[Tarief]) -> Tarief | None:
    """Het RLZ-tarief van de administratie voor de klasse laag/hoog: fractie exact 0.09/0.21, niet verlegd, niet
    vrijgesteld, NL (geen EU/buitenland-naam). Precies één = default; anders None. Klasse `vrijgesteld` (ProfX 16-09):
    het enige vrijgestelde NL-tarief (`IsExcempt`, niet verlegd)."""
    if klasse == BTW_VRIJGESTELD:
        vrij = [t for t in tarieven if t.is_vrijgesteld and not t.is_verlegd and not _is_buitenland(t.naam)]
        if len(vrij) == 1:
            return vrij[0]
        nl = [t for t in vrij if (t.naam or "").strip().upper().startswith("NL")]
        return nl[0] if len(nl) == 1 else None
    fractie = _FRACTIE_PER_KLASSE.get(klasse)
    if fractie is None:
        return None
    treffers = [
        t
        for t in tarieven
        if t.percentage is not None
        and t.percentage == fractie
        and not t.is_verlegd
        and not t.is_vrijgesteld
        and not _is_buitenland(t.naam)
    ]
    if len(treffers) == 1:
        return treffers[0]
    # Meerdere NL-tarieven met dezelfde fractie: de kortste naam die met "NL" begint (RLZ: "NL, Hoog") wint als hij
    # de enige NL-variant is.
    nl = [t for t in treffers if (t.naam or "").strip().upper().startswith("NL")]
    return nl[0] if len(nl) == 1 else None


def _is_buitenland(naam: str | None) -> bool:
    n = (naam or "").lower()
    return any(w in n for w in ("eu", "buiten", "export", "import", "intracommun", "ex-eu", "wereld"))


def btw_klasse_voor(categorie_sleutel: str | None, instellingen: dict[str, Any]) -> str | None:
    """Default-klasse (laag/hoog/verlegd) voor een categorie: eten/drinken volgt `eten_drinken_tarief` (default
    laag; beslispunt alcohol/horeca 21 %), PSP-kosten volgen `psp` (stripe = EU-dienst verlegd, mollie = NL hoog,
    anders = mens), overige uit de vaste tabel; onbekend = None (mens kiest — de mapping-check blijft de poort)."""
    if not categorie_sleutel:
        return None
    if categorie_sleutel == CATEGORIE_ETEN_SLEUTEL:
        return BTW_HOOG if (instellingen.get("eten_drinken_tarief") or BTW_LAAG) == BTW_HOOG else BTW_LAAG
    if categorie_sleutel == CATEGORIE_PSP_KOSTEN_SLEUTEL:
        psp = psp_naam(instellingen)
        if psp == PSP_STRIPE:
            return BTW_VERLEGD
        if psp == PSP_MOLLIE:
            return BTW_HOOG
        return None
    return BTW_KLASSE_PER_CATEGORIE.get(categorie_sleutel)


def psp_naam(instellingen: dict[str, Any]) -> str | None:
    """`psp` is sinds 16-09 een string ('stripe'|'mollie'|'anders'); de 15-09-vorm {'naam': …} wordt gelezen."""
    waarde = instellingen.get("psp")
    if isinstance(waarde, dict):
        waarde = waarde.get("naam")
    if not waarde:
        return None
    w = str(waarde).strip().lower()
    return w if w in PSP_KEUZES else (PSP_ANDERS if w else None)


def psp_btw_herkomst(psp: str | None) -> str | None:
    if psp == PSP_STRIPE:
        return "Stripe · EU-dienst verlegd"
    if psp == PSP_MOLLIE:
        return "Mollie · NL 21 % voorbelasting"
    return None


# ---------------------------------------------------------------------------------------- tegenzijde per bron


def _d(w: Any) -> Decimal | None:
    if w in (None, "", "None"):
        return None
    try:
        return Decimal(str(w)).quantize(_TOL)
    except Exception:  # noqa: BLE001 — bron-detail is JSON uit de eigen parser; onleesbaar = geen bedrag
        return None


def _datum(w: Any) -> date | None:
    try:
        return date.fromisoformat(w) if w else None
    except (TypeError, ValueError):
        return None


def _ledger(sleutel: str, instellingen: dict[str, Any], defaults: dict[str, uuid.UUID | None]):
    ingesteld = (instellingen.get("tegenrekeningen") or {}).get(sleutel)
    if ingesteld:
        try:
            return uuid.UUID(str(ingesteld)), HERKOMST_INSTELLING
        except ValueError:
            pass
    d = defaults.get(sleutel)
    return (d, HERKOMST_DEFAULT) if d else (None, None)


def bepaal_tegenzijde(
    *,
    bron: str | None,
    bron_detail: dict[str, Any] | None,
    instellingen: dict[str, Any],
    rekeningen: list[Rekening],
) -> Tegenzijde | None:
    """De tegenzijde-posten van één omzetbron-document (zonnestudio-dag of pilates-batch) + controles. None voor een
    document zonder omzetbron (AI-rapport) of zonder bedragen."""
    from app.omzet.bronnen import pilates, profx, zonnestudio  # lokale import: geen kring op module-niveau

    detail = bron_detail or {}
    defaults = default_tegenrekeningen(rekeningen)
    regels: list[TegenzijdeRegel] = []
    if bron == zonnestudio.BRON_DAGSTAAT:
        datum = _datum(detail.get("datum"))
        betaalwijzen = detail.get("betaalwijzen") or {}
        pin = _d(betaalwijzen.get("PIN"))
        cash = _d(betaalwijzen.get("Cash"))
        if pin:
            regels.append(_regel(PIN, pin, datum, instellingen, defaults, "ontvangst"))
        if cash:
            regels.append(_regel(CASH, cash, datum, instellingen, defaults, "kas"))
        kas = detail.get("kas") or {}
        storting = _d(kas.get("storting_automaat"))
        if storting:
            regels.append(_regel(STORTING, storting, datum, instellingen, defaults, "ontvangst"))
        contant = _d(kas.get("contante_omzet"))
        if contant is not None and cash is not None and contant != cash:
            verschil = (contant - cash).quantize(_TOL)
            regels.append(_regel(KASVERSCHIL, verschil, datum, instellingen, defaults, "signaal"))
    elif bron == profx.BRON_JOURNAAL:
        # Blok D ProfX (16-09): kas/PIN uit blad 3 (betaalwijzen); ontbreekt dat blad → alles op kas mét signaal.
        datum = _datum(detail.get("datum"))
        betaalwijzen = detail.get("betaalwijzen") or {}
        pin = _d(betaalwijzen.get("PIN"))
        cash = _d(betaalwijzen.get("Cash"))
        if pin:
            regels.append(_regel(PIN, pin, datum, instellingen, defaults, "ontvangst"))
        if cash:
            regels.append(_regel(CASH, cash, datum, instellingen, defaults, "kas"))
        if not regels:
            bruto = _d(detail.get("bruto"))
            if bruto:
                regels.append(_regel(CASH, bruto, datum, instellingen, defaults, "kas"))
    elif bron == pilates.BRON:
        datum = _datum(detail.get("uitbetaaldatum")) or _datum(detail.get("periode_eind"))
        netto = _d(detail.get("netto"))
        if netto:
            if detail.get("contant"):
                regels.append(_regel(CASH, netto, datum, instellingen, defaults, "kas"))
            else:
                regels.append(_regel(STRIPE, netto, datum, instellingen, defaults, "ontvangst"))
    else:
        return None
    if not regels:
        return None
    controles = [
        Controle(
            f"Tegenrekening {LABELS[r.betaalwijze]}",
            r.ledger_id is not None,
            (
                f"{'ingesteld' if r.herkomst == HERKOMST_INSTELLING else 'default uit het rekeningschema'} — "
                f"{r.label} € {r.bedrag}"
                if r.ledger_id is not None
                else f"geen tegenrekening voor {r.label} (€ {r.bedrag}) — stel 'm in onder Instellingen › "
                "Administraties › ‹administratie› › Omzet › Omzetbronnen, of geef de rekening in het rekeningschema "
                "een herkenbare naam (kruispost/PIN/kas/kasverschillen/Stripe)"
            ),
            blokkerend=r.richting != "signaal",
        )
        for r in regels
    ]
    return Tegenzijde(vorm=VORM_AFLETTERING, regels=regels, controles=controles)


def _regel(
    sleutel: str,
    bedrag: Decimal,
    datum: date | None,
    instellingen: dict[str, Any],
    defaults: dict[str, uuid.UUID | None],
    richting: str,
) -> TegenzijdeRegel:
    ledger_id, herkomst = _ledger(sleutel, instellingen, defaults)
    return TegenzijdeRegel(
        betaalwijze=sleutel,
        bedrag=bedrag,
        datum=datum,
        ledger_id=ledger_id,
        herkomst=herkomst,
        richting=richting,
        label=LABELS[sleutel],
    )


# ---------------------------------------------------------------------------------------- pro-rato-verdeling


def verdeel_pro_rato(bedrag: Decimal, basis: dict[str, Decimal]) -> dict[str, Decimal]:
    """Cent-exact sluitende pro-rato-verdeling van `bedrag` over de sleutels naar `basis` (netto-omzet per
    categorie). Restcent(en) op de grootste basis (gelijkspel: alfabetisch eerste sleutel). Basis zonder positieve
    som = lege dict (de aanroeper valt terug)."""
    positief = {k: v for k, v in basis.items() if v is not None and v > 0}
    totaal = sum(positief.values(), Decimal(0))
    if not positief or totaal <= 0:
        return {}
    volgorde = sorted(positief, key=lambda k: (-positief[k], k))
    uit: dict[str, Decimal] = {}
    toegewezen = Decimal(0)
    for k in volgorde[1:]:
        deel = (bedrag * positief[k] / totaal).quantize(_TOL)
        uit[k] = deel
        toegewezen += deel
    uit[volgorde[0]] = (bedrag - toegewezen).quantize(_TOL)
    return uit
