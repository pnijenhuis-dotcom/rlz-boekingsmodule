"""Omzetbron ZONNESTUDIO DAGSTAAT (Peter 15-09; twee studio's, dagelijks per mail): POS-export "Daily Sales" (.xls,
vaste
lay-out, één blad) + "Kascheck" (.xlsx, blad Kascheck) van dezelfde dag en store. Deterministisch op
labels/celposities, harde controles (regelsom = Grand Total, deposit-som = gross, kas sluit) — klopt iets niet:
ONVOLLEDIG, zichtbaar, niet boeken.

Lezing van het voorbeeld 8-9-26.xls (Elderveld): "Sales Analysis Summary" per categorie QTY/Net/Service VAT/Product
VAT/Gross — Points Total 250,00 (verkochte punten = vooruitontvangen, mapping naar een BALANSrekening, 0 %), Products
288,45 + 60,58 = 349,03, Tanning (Walk-ins) 347,12 + 72,88 = 420,00, Grand Total 885,57 / 133,46 / 1.019,03; "Deposit
Analysis" Cash 86,81, PIN 932,22, Punten 0 → 1.019,03; "Points Redeemed" 921 (eenheid = STAP-0-vraag klant); "Store
Used: Elderveld". Kascheck: beginsaldo 198,20, telling 286,00, storting automaat 80,00, eindsaldo na storting 206,00,
contante omzet 87,80 (≠ Cash POS 86,81 → kasverschil 0,99 = oranje signaal).

Boekmodel: één Receipt per dag per studio via de bestaande omzetmotor (regels per categorie, kassabedragen inclusief
btw); de tegenzijde per betaalwijze is RLZ's eigen afletterpad — PIN-ontvangst en kasboeking letteren de open Receipt
af (deel- betalingen). `bron_detail.betaalwijzen` draagt de bedragen voor die aflettering; kasverschil boekt nooit
automatisch."""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date
from decimal import Decimal

from app.omzet.bronnen.grid import Grid

BRON_DAGSTAAT = "zonnestudio_dagstaat"
BRON_KASCHECK = "zonnestudio_kascheck"
CATEGORIE_PUNTEN = "Points"
REDEEMED_LABEL = "Points Redeemed"
_TOL = Decimal("0.01")
_DATUM_RE = re.compile(r"For\s+(\d{1,2})-(\d{1,2})-(\d{4})")
_BESTANDSNAAM_DATUM_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{2,4})")
_KASCHECK_NAAM_RE = re.compile(r"(\d{4})-(\d{2})-(\d{2})")


@dataclass(frozen=True)
class Categorie:
    naam: str
    aantal: Decimal | None
    netto: Decimal
    btw_service: Decimal
    btw_product: Decimal
    bruto: Decimal

    @property
    def btw(self) -> Decimal:
        return self.btw_service + self.btw_product


@dataclass(frozen=True)
class Controle:
    naam: str
    ok: bool
    detail: str
    blokkerend: bool = True


@dataclass
class Dagstaat:
    datum: date | None
    store: str | None
    categorieen: list[Categorie]
    grand_netto: Decimal | None
    grand_btw: Decimal | None
    grand_bruto: Decimal | None
    betaalwijzen: dict[str, Decimal]
    deposit_totaal: Decimal | None
    points_redeemed: Decimal | None
    controles: list[Controle] = field(default_factory=list)

    @property
    def sluit(self) -> bool:
        return all(c.ok for c in self.controles if c.blokkerend)


@dataclass
class Kascheck:
    datum: date | None
    beginsaldo: Decimal | None
    telling: Decimal | None
    eindsaldo: Decimal | None
    storting: Decimal | None
    eindsaldo_na_storting: Decimal | None
    contante_omzet: Decimal | None
    controles: list[Controle] = field(default_factory=list)


# ---------------------------------------------------------------------------------------- herkenning


def is_dagstaat(grid: Grid) -> bool:
    return grid.zoek("Daily Sales") is not None and grid.zoek("Sales Analysis Summary") is not None


def is_kascheck(grid: Grid) -> bool:
    blad = grid.bladen.get("Kascheck") or grid
    return blad.zoek("Beginsaldo kas") is not None and blad.zoek("Eindsaldo kas") is not None


# ---------------------------------------------------------------------------------------- dagstaat


def _d2(w: Decimal) -> Decimal:
    return w.quantize(_TOL)


def parse_dagstaat(grid: Grid) -> Dagstaat:
    """Puur: raster → Dagstaat mét controles. Nooit raden: een ontbrekend blok = controle rood."""
    datum: date | None = None
    for rij in grid.rijen:
        for w in rij.values():
            if isinstance(w, str) and (m := _DATUM_RE.search(w)):
                datum = date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
                break
        if datum:
            break

    store: str | None = None
    pos = grid.zoek("Store Used:")
    if pos is not None:
        for r in range(pos[0] + 1, min(pos[0] + 4, len(grid.rijen))):
            t = grid.tekst(r, pos[1])
            if t:
                store = t.strip()
                break

    # Sales Analysis Summary: van de kop 'Category' (kolom 1) tot 'Grand Total:' (kolom 1). Getallen alleen links van de
    # Deposit-kolommen (≥ 55). Per categorierij: [qty, net, total%, service_vat, product_vat, consumable_vat, gross].
    categorieen: list[Categorie] = []
    grand_netto = grand_btw = grand_bruto = None
    kop = grid.zoek("Sales Analysis Summary")
    if kop is not None:
        for r in range(kop[0] + 1, len(grid.rijen)):
            label = grid.tekst(r, 1)
            if not label:
                continue
            if label.strip().startswith("Grand Total"):
                g = grid.getallen_in_rij(r, kol_tot=55)
                if len(g) >= 6:
                    # qty, net, service_vat, product_vat, consumable_vat, gross
                    grand_netto, grand_btw, grand_bruto = _d2(g[1]), _d2(g[2] + g[3] + g[4]), _d2(g[5])
                elif len(g) == 5:
                    grand_netto, grand_btw, grand_bruto = _d2(g[0]), _d2(g[1] + g[2] + g[3]), _d2(g[4])
                break
            if label.strip().endswith("Total"):
                g = grid.getallen_in_rij(r, kol_tot=55)
                if len(g) >= 7:
                    categorieen.append(
                        Categorie(
                            naam=label.strip()[: -len("Total")].strip(),
                            aantal=g[0],
                            netto=_d2(g[1]),
                            btw_service=_d2(g[3]),
                            btw_product=_d2(g[4]),
                            bruto=_d2(g[6]),
                        )
                    )

    # Deposit Analysis: typelabel (kolom ≥ 55) → eerstvolgende rij mét getallen rechts (amount, refunds, net receipts).
    betaalwijzen: dict[str, Decimal] = {}
    deposit_totaal: Decimal | None = None
    dep = grid.zoek("Deposit Analysis")
    if dep is not None:
        for r in range(dep[0] + 1, len(grid.rijen)):
            rij = grid.rijen[r]
            for c in sorted(rij):
                if c < 55:
                    continue
                w = rij[c]
                if not isinstance(w, str):
                    continue
                label = w.strip().rstrip(":").strip()
                if label in ("Type", "Amount", "Refunds", "Net Receipts") or label.endswith("Total"):
                    if label.startswith("Grand Total"):
                        for rr in range(r, min(r + 3, len(grid.rijen))):
                            g = grid.getallen_in_rij(rr, kol_vanaf=55)
                            if g:
                                deposit_totaal = _d2(g[-1])
                                break
                    continue
                for rr in range(r + 1, min(r + 4, len(grid.rijen))):
                    g = grid.getallen_in_rij(rr, kol_vanaf=55)
                    if g:
                        betaalwijzen[label] = _d2(g[-1])  # Net Receipts (= amount − refunds)
                        break
            if grid.tekst(r, 1) and grid.tekst(r, 1).strip().startswith("Employee Sales"):
                break

    points_redeemed: Decimal | None = None
    pr = grid.zoek(REDEEMED_LABEL)
    if pr is not None:
        g = grid.getallen_in_rij(pr[0], kol_vanaf=pr[1] + 1)
        points_redeemed = g[0] if g else None

    staat = Dagstaat(
        datum=datum,
        store=store,
        categorieen=categorieen,
        grand_netto=grand_netto,
        grand_btw=grand_btw,
        grand_bruto=grand_bruto,
        betaalwijzen=betaalwijzen,
        deposit_totaal=deposit_totaal,
        points_redeemed=points_redeemed,
    )
    staat.controles = _controles_dagstaat(staat)
    return staat


def _controles_dagstaat(s: Dagstaat) -> list[Controle]:
    uit: list[Controle] = []
    uit.append(
        Controle(
            "Datum gelezen", s.datum is not None, s.datum.isoformat() if s.datum else "geen 'For d-m-jjjj' gevonden"
        )
    )
    uit.append(Controle("Store gelezen", bool(s.store), s.store or "geen 'Store Used' gevonden"))
    if not s.categorieen or s.grand_bruto is None:
        uit.append(Controle("Sales Analysis Summary", False, "categorieën of Grand Total ontbreken"))
        return uit
    som_n = _d2(sum((c.netto for c in s.categorieen), Decimal(0)))
    som_b = _d2(sum((c.btw for c in s.categorieen), Decimal(0)))
    som_g = _d2(sum((c.bruto for c in s.categorieen), Decimal(0)))
    uit.append(
        Controle(
            "Regelsom = Grand Total",
            abs(som_n - (s.grand_netto or 0)) <= _TOL
            and abs(som_b - (s.grand_btw or 0)) <= _TOL
            and abs(som_g - s.grand_bruto) <= _TOL,
            f"net {som_n} / btw {som_b} / gross {som_g} vs Grand Total {s.grand_netto} / {s.grand_btw} / {s.grand_bruto}",  # noqa: E501
        )
    )
    for c in s.categorieen:
        uit.append(
            Controle(
                f"Categorie {c.naam} sluit",
                abs(c.netto + c.btw - c.bruto) <= _TOL,
                f"{c.netto} + {c.btw} = {c.bruto}",
            )
        )
    dep_som = _d2(sum(s.betaalwijzen.values(), Decimal(0))) if s.betaalwijzen else None
    uit.append(
        Controle(
            "Deposit-som = Grand Total gross",
            dep_som is not None
            and abs(dep_som - s.grand_bruto) <= _TOL
            and (s.deposit_totaal is None or abs(s.deposit_totaal - s.grand_bruto) <= _TOL),
            f"betaalwijzen {dict((k, str(v)) for k, v in s.betaalwijzen.items())} som {dep_som} vs gross {s.grand_bruto}",  # noqa: E501
        )
    )
    uit.append(
        Controle(
            "Puntenwaarde bekend",
            not ((s.points_redeemed or 0) > 0),
            f"Points Redeemed {s.points_redeemed}: eenheid/waarde per punt is een STAP-0-vraag aan de klant — tot dan niet boeken"  # noqa: E501
            if (s.points_redeemed or 0) > 0
            else "geen punten verbruikt",
        )
    )
    return uit


# ---------------------------------------------------------------------------------------- kascheck


def parse_kascheck(grid: Grid) -> Kascheck:
    blad = grid.bladen.get("Kascheck") or grid

    def waarde_na(label: str) -> Decimal | None:
        pos = blad.zoek(label)
        if pos is None:
            return None
        g = blad.getallen_in_rij(pos[0], kol_vanaf=pos[1] + 1)
        return _d2(g[0]) if g else None

    datum: date | None = None
    pos = blad.zoek("Datum")
    if pos is not None:
        for c in sorted(blad.rijen[pos[0]]):
            w = blad.rijen[pos[0]][c]
            if isinstance(w, date):
                datum = w
    telling: Decimal | None = None
    start = blad.zoek("Telling eind van de dag")
    eind = blad.zoek("Eindsaldo kas")
    if start is not None and eind is not None and eind[0] > start[0]:
        som = Decimal(0)
        for r in range(start[0] + 1, eind[0]):
            g = blad.getallen_in_rij(r)
            if len(g) >= 3:
                som += g[2]  # kolom C: coupure × aantal
        telling = _d2(som)
    k = Kascheck(
        datum=datum,
        beginsaldo=waarde_na("Beginsaldo kas"),
        telling=telling,
        eindsaldo=waarde_na("Eindsaldo kas"),
        storting=waarde_na("Storting in automaat"),
        eindsaldo_na_storting=waarde_na("Eindsaldo na storting"),
        contante_omzet=waarde_na("Contante omzet"),
    )
    k.controles = _controles_kascheck(k)
    return k


def _controles_kascheck(k: Kascheck) -> list[Controle]:
    uit = [Controle("Kascheck-datum gelezen", k.datum is not None, k.datum.isoformat() if k.datum else "geen datum")]
    if k.telling is not None and k.eindsaldo is not None:
        uit.append(
            Controle("Telling = eindsaldo kas", abs(k.telling - k.eindsaldo) <= _TOL, f"{k.telling} vs {k.eindsaldo}")
        )
    if None not in (k.eindsaldo, k.storting, k.eindsaldo_na_storting):
        uit.append(
            Controle(
                "Eindsaldo − storting = eindsaldo na storting",
                abs((k.eindsaldo - k.storting) - k.eindsaldo_na_storting) <= _TOL,  # type: ignore[operator]
                f"{k.eindsaldo} − {k.storting} = {k.eindsaldo_na_storting}",
            )
        )
    if None not in (k.beginsaldo, k.contante_omzet, k.eindsaldo):
        uit.append(
            Controle(
                "Kas sluit (begin + contante omzet = eindsaldo)",
                abs((k.beginsaldo + k.contante_omzet) - k.eindsaldo) <= _TOL,  # type: ignore[operator]
                f"{k.beginsaldo} + {k.contante_omzet} = {k.eindsaldo}",
                blokkerend=False,
            )
        )
    return uit


# ---------------------------------------------------------------------------------------- veldvoorstel


def datum_uit_bestandsnaam(bestandsnaam: str) -> date | None:
    """'8-9-26.xls' / '09-09-2026.xls' → 2026-09-08 / -09; 'kascheck-2026-09-08.xlsx' → 2026-09-08."""
    if m := _KASCHECK_NAAM_RE.search(bestandsnaam):
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None
    if m := _BESTANDSNAAM_DATUM_RE.search(bestandsnaam):
        d, mo, j = int(m.group(1)), int(m.group(2)), int(m.group(3))
        j = j + 2000 if j < 100 else j
        try:
            return date(j, mo, d)
        except ValueError:
            return None
    return None


def bouw_veldvoorstel(dagstaat: Dagstaat | None, kascheck: Kascheck | None, *, bestandsnaam: str | None = None) -> dict:
    """Het kassarapport-veldvoorstel (zelfde sleutels als de AI-rapportextractie) + `bron`/`bron_detail`. Zonder
    dagstaat
    (alleen een kascheck) is het een wachtend voorstel: geen regels, `bron_detail.wacht_op = 'dagstaat'`; zonder
    kascheck
    `wacht_op = 'kascheck'` — beide zichtbaar in de werkvoorraad, nooit stil."""
    controles: list[dict] = []
    regels: list[dict] = []
    datum = dagstaat.datum if dagstaat else (kascheck.datum if kascheck else None)
    if dagstaat is not None:
        controles += [asdict(c) for c in dagstaat.controles]
        for c in dagstaat.categorieen:
            regels.append(
                {
                    "categorie": c.naam,
                    "omzet_bedrag": str(c.bruto),  # kassabedrag INCLUSIEF btw — de motor splitst per taxrate
                    "kostprijs_bedrag": None,
                    "zekerheid": 1.0,
                    "onzeker": False,
                    "aantal": str(c.aantal) if c.aantal is not None else None,
                    "netto_pos": str(c.netto),
                    "btw_pos": str(c.btw),
                    "balans": c.naam == CATEGORIE_PUNTEN,
                }
            )
        naamdatum = datum_uit_bestandsnaam(bestandsnaam) if bestandsnaam else None
        if naamdatum is not None and dagstaat.datum is not None:
            controles.append(
                asdict(
                    Controle(
                        "Datum in bestand = datum in bestandsnaam",
                        naamdatum == dagstaat.datum,
                        f"{dagstaat.datum} vs {naamdatum} ({bestandsnaam})",
                    )
                )
            )
    if kascheck is not None:
        controles += [asdict(c) for c in kascheck.controles]
    if dagstaat is not None and kascheck is not None:
        controles.append(
            asdict(
                Controle(
                    "Kascheck-datum = dagstaat-datum",
                    kascheck.datum is not None and kascheck.datum == dagstaat.datum,
                    f"{kascheck.datum} vs {dagstaat.datum}",
                )
            )
        )
        cash_pos = dagstaat.betaalwijzen.get("Cash")
        if cash_pos is not None and kascheck.contante_omzet is not None:
            verschil = _d2(kascheck.contante_omzet - cash_pos)
            controles.append(
                asdict(
                    Controle(
                        "Kasverschil (contante omzet kascheck vs Cash POS)",
                        verschil == 0,
                        f"{kascheck.contante_omzet} − {cash_pos} = {verschil} — boeken op de kasverschillenrekening alleen mét bevestiging"  # noqa: E501
                        if verschil != 0
                        else "geen kasverschil",
                        blokkerend=False,
                    )
                )
            )
    wacht_op = None if (dagstaat and kascheck) else ("dagstaat" if dagstaat is None else "kascheck")
    if wacht_op:
        controles.append(
            asdict(
                Controle(
                    f"Wederhelft ontvangen ({wacht_op})", False, f"{wacht_op} van dezelfde dag/store ontbreekt nog"
                )
            )
        )
    totaal = dagstaat.grand_bruto if dagstaat else None
    return {
        "soort": "kassarapport",
        "bron": BRON_DAGSTAAT,
        "rapport_titel": f"Daily Sales {dagstaat.store or ''} {datum.isoformat() if datum else ''}".strip()
        if dagstaat
        else f"Kascheck {datum.isoformat() if datum else ''}".strip(),
        "entiteit_naam": dagstaat.store if dagstaat else None,
        "periode_start": datum.isoformat() if datum else None,
        "periode_eind": datum.isoformat() if datum else None,
        "totaal_omzet": str(totaal) if totaal is not None else None,
        "totaal_kostprijs": None,
        "marge_pct": None,
        "zekerheden": {"periode_start": 1.0, "periode_eind": 1.0, "totaal_omzet": 1.0, "totaal_kostprijs": 0.0},
        "regels": regels,
        "regelsom_omzet": (
            {
                "vergelijkbaar": True,
                "som": str(sum((Decimal(r["omzet_bedrag"]) for r in regels), Decimal(0))),
                "totaal": str(totaal),
                "verschil": "0.00",
                "sluit": True,
            }
            if dagstaat
            and totaal is not None
            and abs(sum((Decimal(r["omzet_bedrag"]) for r in regels), Decimal(0)) - totaal) <= _TOL
            else {
                "vergelijkbaar": bool(dagstaat),
                "reden": "geen dagstaat" if not dagstaat else "regelsom ≠ Grand Total",
            }
        ),
        "regelsom_kostprijs": {"vergelijkbaar": False, "reden": "geen kostprijs in deze bron"},
        "onparseerbaar": [],
        "bsn_verwijderd": 0,
        "bron_detail": {
            "store": dagstaat.store if dagstaat else None,
            "datum": datum.isoformat() if datum else None,
            "betaalwijzen": {k: str(v) for k, v in (dagstaat.betaalwijzen if dagstaat else {}).items()},
            "grand_total": (
                {"netto": str(dagstaat.grand_netto), "btw": str(dagstaat.grand_btw), "bruto": str(dagstaat.grand_bruto)}
                if dagstaat
                else None
            ),
            "points_redeemed": str(dagstaat.points_redeemed)
            if dagstaat and dagstaat.points_redeemed is not None
            else None,
            "kas": (
                {
                    "beginsaldo": str(kascheck.beginsaldo),
                    "telling": str(kascheck.telling),
                    "eindsaldo": str(kascheck.eindsaldo),
                    "storting_automaat": str(kascheck.storting),
                    "eindsaldo_na_storting": str(kascheck.eindsaldo_na_storting),
                    "contante_omzet": str(kascheck.contante_omzet),
                }
                if kascheck
                else None
            ),
            "controles": controles,
            "wacht_op": wacht_op,
            "sluit": all(c["ok"] for c in controles if c["blokkerend"]),
        },
    }
