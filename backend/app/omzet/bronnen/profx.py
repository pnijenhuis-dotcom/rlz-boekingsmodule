"""ProfX Journaal + ProfX Margerapport (coffeeshop-kassa; casus De Bazar Apeldoorn, Peter 16-09) — DETERMINISTISCHE
tekstparser op de PDF-tekstlaag (pypdf, zelfde helper als de template-terugval), géén AI, géén AVG-gate.

Journaal (blad 1): kop (kassa's, rapportperiode van→tot, aantal klanten), tabel "Artikelgroepen" (omschrijving · aantal
· bedrag · retour-aantal · retour-bedrag · korting), totaalregels "Bruto omzet", "Kortingen", "Vouchers", "Netto omzet".
Bedragen zijn INCLUSIEF btw (kassa); netto per groep leidt de omzetmotor af uit het tarief van de categorie. Retouren
en kortingen zijn een negatieve component van dezelfde groepsregel. Blad 2 (artikellijst) wordt NIET geboekt (Peter:
groepen, niet artikelen); blad 3 (betaalwijzen kas/PIN) voedt alleen de tegenzijde. Een periode 05:00 → 05:00 = één
kassadag; boekdatum = de startdag.

Margerapport: per artikelgroep de inkoopwaarde (fiscaal aanvaarde bron voor de kostprijs van contant ingekochte
softdrugs) → `kostprijs_bedrag` per regel; periode-dekking bepaalt de bundeling (blok F: journaal per dag, margerapport
per dag óf per week — `dekt(...)`).

Sluitcontroles als check-rijen (`Controle`, blokkerend rood): Σ groepen (bedrag − retour − korting) = Bruto omzet;
Bruto − Kortingen − Vouchers = Netto omzet; margerapport: Σ groepen = totaal. Nooit raden: een ontbrekend blok = rood.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation

from app.omzet.bronnen.zonnestudio import Controle

BRON_JOURNAAL = "profx_journaal"
BRON_MARGE = "profx_margerapport"

_TOL = Decimal("0.01")
_DATUM_TIJD_RE = re.compile(r"(\d{1,2})-(\d{1,2})-(\d{4})(?:\s+(\d{1,2}):(\d{2}))?")
_BEDRAG_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*,\d{2}|-?\d+,\d{2}|-?\d+\.\d{2}")
_GETAL_RE = re.compile(r"-?\d{1,3}(?:\.\d{3})*(?:,\d+)?|-?\d+(?:[.,]\d+)?")
#: Sleutelwoorden van de herkenning (blok A1: inhoud vóór de AI, afzender/onderwerp zijn alleen hint).
_JOURNAAL_MARKERS = ("profx journaal", "rapportperiode", "artikelgroepen")
_MARGE_MARKERS = ("profx margerapport", "rapportperiode")
_TOTAAL_LABELS = ("bruto omzet", "kortingen", "vouchers", "netto omzet")
_BETAALWIJZE_LABELS = {"kas": "Cash", "contant": "Cash", "cash": "Cash", "pin": "PIN", "pinnen": "PIN"}


def _d2(w: Decimal) -> Decimal:
    return w.quantize(_TOL)


def _bedrag(tekst: str) -> Decimal | None:
    """ "1.669,64" / "1669,64" / "1669.64" → Decimal; None = geen bedrag."""
    s = tekst.strip().replace("€", "").replace(" ", "")
    if not s:
        return None
    if "," in s and "." in s:
        s = s.replace(".", "").replace(",", ".")
    elif "," in s:
        s = s.replace(",", ".")
    try:
        return Decimal(s)
    except InvalidOperation:
        return None


def _getallen(regel: str) -> list[Decimal]:
    """Alle getallen in de regel (achter de omschrijving), in leesvolgorde."""
    uit: list[Decimal] = []
    for m in _GETAL_RE.finditer(regel):
        w = _bedrag(m.group(0))
        if w is not None:
            uit.append(w)
    return uit


def _omschrijving(regel: str) -> str:
    """Tekst vóór het eerste getal (getrimd)."""
    m = _GETAL_RE.search(regel)
    return (regel[: m.start()] if m else regel).strip(" :·-\t")


def _laag(regels: list[str]) -> list[str]:
    return [r.lower() for r in regels]


def is_journaal(regels: list[str]) -> bool:
    tekst = "\n".join(_laag(regels))
    return all(m in tekst for m in _JOURNAAL_MARKERS)


def is_margerapport(regels: list[str]) -> bool:
    tekst = "\n".join(_laag(regels))
    return all(m in tekst for m in _MARGE_MARKERS) and "artikelgroepen" not in tekst.split("margerapport", 1)[0]


@dataclass(frozen=True)
class Groep:
    naam: str
    aantal: Decimal | None
    bedrag: Decimal
    retour_aantal: Decimal | None
    retour_bedrag: Decimal
    korting: Decimal

    @property
    def omzet(self) -> Decimal:
        """Kassabedrag INCLUSIEF btw dat geboekt wordt: bedrag − retouren − kortingen."""
        return _d2(self.bedrag - self.retour_bedrag - self.korting)


@dataclass
class Journaal:
    kassas: list[str]
    periode_van: datetime | None
    periode_tot: datetime | None
    klanten: int | None
    uitdraai: date | None
    groepen: list[Groep]
    bruto: Decimal | None
    kortingen: Decimal | None
    vouchers: Decimal | None
    netto: Decimal | None
    betaalwijzen: dict[str, Decimal] = field(default_factory=dict)
    bedrijf: str | None = None
    controles: list[Controle] = field(default_factory=list)

    @property
    def kassadag(self) -> date | None:
        """Startdag van de periode (05:00 → 05:00 = één kassadag; boekdatum = startdag)."""
        return self.periode_van.date() if self.periode_van else None

    @property
    def eind_dag(self) -> date | None:
        """Laatste kalenderdag die het journaal dekt: tot-moment om of vóór 06:00 = de dag ervoor."""
        if self.periode_tot is None:
            return self.kassadag
        t = self.periode_tot
        if t.hour <= 6:
            return (t.date() - _EEN_DAG) if t.date() > (self.kassadag or t.date()) else t.date()
        return t.date()


@dataclass
class Margerapport:
    periode_van: date | None
    periode_tot: date | None
    groepen: dict[str, Decimal]
    totaal: Decimal | None
    controles: list[Controle] = field(default_factory=list)


_EEN_DAG = timedelta(days=1)


def _datums(regel: str) -> list[datetime]:
    uit: list[datetime] = []
    for m in _DATUM_TIJD_RE.finditer(regel):
        d, mo, j, uu, mi = m.groups()
        try:
            uit.append(datetime(int(j), int(mo), int(d), int(uu or 0), int(mi or 0)))
        except ValueError:
            continue
    return uit


def parse_journaal(regels: list[str]) -> Journaal:
    """Puur: tekstregels → Journaal mét controles. Nooit raden: een ontbrekend blok = controle rood."""
    kassas: list[str] = []
    van = tot = None
    klanten: int | None = None
    uitdraai: date | None = None
    bedrijf: str | None = None
    for r in regels:
        laag = r.lower()
        if "rapportperiode" in laag:
            ds = _datums(r)
            if len(ds) >= 2:
                van, tot = ds[0], ds[1]
            elif len(ds) == 1:
                van = ds[0]
        elif laag.startswith("kassa") or " kassa " in f" {laag} ":
            for m in re.finditer(r"kassa\s*\d+", laag):
                naam = m.group(0).replace("kassa", "Kassa").replace("Kassa ", "Kassa ").strip()
                naam = re.sub(r"\s+", " ", naam)
                if naam not in kassas:
                    kassas.append(naam)
        elif "klanten" in laag and klanten is None:
            g = _getallen(r)
            if g:
                klanten = int(g[0])
        elif ("uitdraai" in laag or "afgedrukt" in laag) and uitdraai is None:
            ds = _datums(r)
            if ds:
                uitdraai = ds[0].date()
        elif laag.startswith("bedrijf") or laag.startswith("winkel"):
            bedrijf = r.split(":", 1)[1].strip() if ":" in r else None

    groepen: list[Groep] = []
    totalen: dict[str, Decimal] = {}
    in_tabel = False
    for r in regels:
        laag = r.strip().lower()
        if not laag:
            continue
        if laag.startswith("artikelgroepen"):
            in_tabel = True
            continue
        if in_tabel:
            label = laag.split(":")[0].strip()
            for tl in _TOTAAL_LABELS:
                if label.startswith(tl):
                    g = _getallen(r[len(tl) :])
                    if g:
                        totalen[tl] = _d2(g[-1])
                    label = ""
                    break
            if label == "":
                if len(totalen) == len(_TOTAAL_LABELS):
                    in_tabel = False
                continue
            if laag.startswith(("omschrijving", "artikelgroep", "totaal")) and not _getallen(r):
                continue
            g = _getallen(r)
            naam = _omschrijving(r)
            if not naam or len(g) < 2:
                continue
            aantal, bedrag = g[0], _d2(g[1])
            retour_aantal = g[2] if len(g) > 2 else None
            retour_bedrag = _d2(g[3]) if len(g) > 3 else Decimal("0.00")
            korting = _d2(g[4]) if len(g) > 4 else Decimal("0.00")
            groepen.append(Groep(naam, aantal, bedrag, retour_aantal, retour_bedrag, korting))

    betaalwijzen: dict[str, Decimal] = {}
    in_betaal = False
    for r in regels:
        laag = r.strip().lower()
        if not laag:
            continue
        eerste = laag.split()[0].rstrip(":")
        if laag.startswith(("betaalwijze", "betaalwijzen", "betalingen", "betaalmiddel")):
            in_betaal = True
            continue
        if in_betaal:
            # Einde van blad 3: een volgend blad/blok (kassa-afsluiting, artikellijst, blad-voetregel).
            if eerste.startswith(("kassa", "kasafsluiting", "artikel", "blad", "totaal", "profx")):
                if betaalwijzen:
                    in_betaal = False
                continue
            doel = _BETAALWIJZE_LABELS.get(eerste)
            if doel is not None:
                g = _getallen(r)
                if g:
                    betaalwijzen[doel] = _d2(betaalwijzen.get(doel, Decimal(0)) + g[-1])

    j = Journaal(
        kassas=kassas,
        periode_van=van,
        periode_tot=tot,
        klanten=klanten,
        uitdraai=uitdraai,
        groepen=groepen,
        bruto=totalen.get("bruto omzet"),
        kortingen=totalen.get("kortingen"),
        vouchers=totalen.get("vouchers"),
        netto=totalen.get("netto omzet"),
        betaalwijzen=betaalwijzen,
        bedrijf=bedrijf,
    )
    j.controles = _controles_journaal(j)
    return j


def _controles_journaal(j: Journaal) -> list[Controle]:
    c: list[Controle] = []
    c.append(Controle("Rapportperiode gelezen", j.periode_van is not None, f"{j.periode_van} → {j.periode_tot}"))
    c.append(Controle("Artikelgroepen gelezen", len(j.groepen) > 0, f"{len(j.groepen)} groepen"))
    som = _d2(sum((g.omzet for g in j.groepen), Decimal(0)))
    if j.bruto is None:
        c.append(Controle("Bruto omzet in rapport", False, "regel 'Bruto omzet' niet gevonden"))
    else:
        verschil = _d2(som - j.bruto)
        c.append(
            Controle(
                "Σ artikelgroepen (bedrag − retour − korting) = Bruto omzet",
                abs(verschil) <= _TOL,
                f"{som} vs {j.bruto} (verschil {verschil})",
            )
        )
    if j.bruto is not None and j.netto is not None:
        afgeleid = _d2(j.bruto - (j.kortingen or Decimal(0)) - (j.vouchers or Decimal(0)))
        c.append(
            Controle(
                "Bruto − Kortingen − Vouchers = Netto omzet",
                abs(afgeleid - j.netto) <= _TOL,
                f"{j.bruto} − {j.kortingen or 0} − {j.vouchers or 0} = {afgeleid} vs {j.netto}",
            )
        )
    else:
        c.append(Controle("Netto omzet in rapport", j.netto is not None, "regel 'Netto omzet' niet gevonden"))
    if j.betaalwijzen and j.bruto is not None:
        b = _d2(sum(j.betaalwijzen.values(), Decimal(0)))
        c.append(
            Controle(
                "Betaalwijzen (kas + PIN) = Bruto omzet",
                abs(b - j.bruto) <= _TOL,
                f"{b} vs {j.bruto}",
                blokkerend=False,
            )
        )
    else:
        c.append(
            Controle(
                "Betaalwijzen gelezen",
                False,
                "blad 3 (betaalwijzen) niet gevonden — tegenzijde volledig op kas (controleer)",
                blokkerend=False,
            )
        )
    return c


def parse_margerapport(regels: list[str]) -> Margerapport:
    """Per artikelgroep de inkoopwaarde. Kolomvolgorde per groepsregel: [verkoop, inkoopwaarde, …] of alleen
    [inkoopwaarde] — de kop bepaalt welke kolom 'Inkoopwaarde' is (nooit raden bij ontbreken → controle rood)."""
    van = tot = None
    for r in regels:
        if "rapportperiode" in r.lower():
            ds = _datums(r)
            if len(ds) >= 2:
                van, tot = ds[0].date(), ds[1].date()
            elif ds:
                van = tot = ds[0].date()
            break
    groepen: dict[str, Decimal] = {}
    totaal: Decimal | None = None
    kolom: int | None = None
    in_tabel = False
    for r in regels:
        laag = r.strip().lower()
        if not laag:
            continue
        if "inkoopwaarde" in laag and not _getallen(r):
            koppen = [k.strip().lower() for k in re.split(r"\s{2,}|\t|\|", r.strip()) if k.strip()]
            for i, k in enumerate(koppen):
                if "inkoop" in k:
                    kolom = i - 1 if koppen and not _getallen(koppen[0]) else i
                    break
            in_tabel = True
            continue
        if laag.startswith("artikelgroepen"):
            in_tabel = True
            continue
        if in_tabel:
            if laag.startswith("totaal"):
                g = _getallen(r)
                if g:
                    totaal = _d2(g[kolom] if kolom is not None and kolom < len(g) else g[-1] if len(g) == 1 else g[1])
                in_tabel = False
                continue
            g = _getallen(r)
            naam = _omschrijving(r)
            if not naam or not g:
                continue
            if kolom is not None and kolom < len(g):
                groepen[naam] = _d2(g[kolom])
            elif len(g) >= 2:
                groepen[naam] = _d2(g[1])
            else:
                groepen[naam] = _d2(g[0])
    m = Margerapport(periode_van=van, periode_tot=tot, groepen=groepen, totaal=totaal)
    som = _d2(sum(groepen.values(), Decimal(0)))
    m.controles = [
        Controle("Margerapport-periode gelezen", van is not None, f"{van} → {tot}"),
        Controle("Inkoopwaarde per artikelgroep gelezen", len(groepen) > 0, f"{len(groepen)} groepen"),
        Controle(
            "Σ inkoopwaarde artikelgroepen = totaal margerapport",
            totaal is not None and abs(som - totaal) <= _TOL,
            f"{som} vs {totaal}" if totaal is not None else "totaalregel niet gevonden",
        ),
    ]
    return m


def dekt(marge_van: date | None, marge_tot: date | None, dag: date | None) -> bool:
    """Blok F (Peter 16-09 12:05): een margerapport-periode dekt een kassadag als de dag erbinnen valt (dag = dag,
    week = 7 dagjournalen)."""
    if marge_van is None or dag is None:
        return False
    return marge_van <= dag <= (marge_tot or marge_van)


#: Categorie-namen zoals ProfX ze schrijft → de omzetmotor-categorie (mapping-sleutel is de groepsnaam zelf).
BTW_KLASSE_PER_GROEP: dict[str, str] = {
    "wiet": "vrijgesteld",
    "hash": "vrijgesteld",
    "joints": "vrijgesteld",
    "edible": "vrijgesteld",  # beslispunt Peter: cannabis-edibles vrijgesteld; controle-rij "bevestig"
    "edibles": "vrijgesteld",
    "dranken": "laag",
    "snacks": "laag",
    "headshop": "hoog",
}
BEVESTIG_GROEPEN = frozenset({"edible", "edibles"})


def bouw_veldvoorstel(
    journaal: Journaal | None,
    marge: Margerapport | None,
    *,
    marge_document_id: str | None = None,
    bestandsnaam: str | None = None,
) -> dict:
    """Het kassarapport-veldvoorstel (zelfde sleutels als de andere omzetbronnen) + `bron`/`bron_detail`. Zonder
    journaal (los margerapport) = alleen kostprijsregels, `wacht_op = 'journaal'`; zonder margerapport = alleen omzet,
    kostprijs oranje "margerapport ontbreekt" (geen blokkade — Peter: boeken alleen omzet, kostprijs volgt)."""
    controles: list[dict] = []
    regels: list[dict] = []
    if journaal is not None:
        controles += [asdict(c) for c in journaal.controles]
        for g in journaal.groepen:
            sleutel = g.naam.strip().lower()
            klasse = BTW_KLASSE_PER_GROEP.get(sleutel)
            kostprijs = marge.groepen.get(g.naam) if marge else None
            if kostprijs is None and marge:
                # Groepsnaam kan in het margerapport anders gespeld zijn (hoofdletters/spaties).
                for naam, w in marge.groepen.items():
                    if naam.strip().lower() == sleutel:
                        kostprijs = w
                        break
            regels.append(
                {
                    "categorie": g.naam,
                    "omzet_bedrag": str(g.omzet),  # INCLUSIEF btw — de motor splitst per taxrate
                    "kostprijs_bedrag": str(kostprijs) if kostprijs is not None else None,
                    "zekerheid": 1.0,
                    "onzeker": False,
                    "aantal": str(g.aantal) if g.aantal is not None else None,
                    "retour_bedrag": str(g.retour_bedrag),
                    "korting": str(g.korting),
                    "btw_klasse_default": klasse,
                    "bevestig_categorie": sleutel in BEVESTIG_GROEPEN,
                }
            )
            if sleutel in BEVESTIG_GROEPEN:
                controles.append(
                    asdict(
                        Controle(
                            f"{g.naam}: categorie uit default (vrijgesteld) — eerste keer bevestigen",
                            False,
                            "cannabis-edibles zijn vrijgesteld, gewone edibles 9 % — kies de categorie bewust",
                            blokkerend=False,
                        )
                    )
                )
    if marge is not None:
        controles += [asdict(c) for c in marge.controles]
        if journaal is None:
            for naam, w in marge.groepen.items():
                regels.append(
                    {
                        "categorie": naam,
                        "omzet_bedrag": None,
                        "kostprijs_bedrag": str(w),
                        "zekerheid": 1.0,
                        "onzeker": False,
                        "btw_klasse_default": BTW_KLASSE_PER_GROEP.get(naam.strip().lower()),
                    }
                )
        elif journaal.groepen:
            ontbrekend = [
                g.naam
                for g in journaal.groepen
                if marge.groepen.get(g.naam) is None
                and not any(n.strip().lower() == g.naam.strip().lower() for n in marge.groepen)
            ]
            if ontbrekend:
                controles.append(
                    asdict(
                        Controle(
                            "Inkoopwaarde per artikelgroep uit het margerapport",
                            False,
                            f"geen inkoopwaarde voor: {', '.join(ontbrekend)}",
                            blokkerend=False,
                        )
                    )
                )
    if journaal is not None and marge is None:
        controles.append(
            asdict(
                Controle(
                    "Margerapport (kostprijs)",
                    False,
                    "margerapport ontbreekt — alleen omzet boeken; de kostprijs volgt zodra het margerapport van deze "
                    "periode binnenkomt (bundeling op periode-dekking)",
                    blokkerend=False,
                )
            )
        )
    wacht_op = None if journaal is not None else "journaal"
    if wacht_op:
        controles.append(
            asdict(Controle("Journaal ontvangen", False, "dit is een los margerapport — het dagjournaal ontbreekt nog"))
        )
    dag = journaal.kassadag if journaal else (marge.periode_van if marge else None)
    eind = journaal.eind_dag if journaal else (marge.periode_tot if marge else None)
    totaal = journaal.bruto if journaal else None
    som = _d2(sum((Decimal(r["omzet_bedrag"]) for r in regels if r.get("omzet_bedrag")), Decimal(0)))
    kostprijs_totaal = (
        _d2(sum((Decimal(r["kostprijs_bedrag"]) for r in regels if r.get("kostprijs_bedrag")), Decimal(0)))
        if any(r.get("kostprijs_bedrag") for r in regels)
        else None
    )
    titel = (
        f"ProfX Journaal {dag.isoformat() if dag else ''} ({', '.join(journaal.kassas) or 'kassa'})".strip()
        if journaal
        else f"ProfX Margerapport {dag.isoformat() if dag else ''} → {eind.isoformat() if eind else ''}".strip()
    )
    return {
        "soort": "kassarapport",
        "bron": BRON_JOURNAAL if journaal is not None else BRON_MARGE,
        "rapport_titel": titel,
        "entiteit_naam": journaal.bedrijf if journaal else None,
        "periode_start": dag.isoformat() if dag else None,
        "periode_eind": (eind or dag).isoformat() if (eind or dag) else None,
        "totaal_omzet": str(totaal) if totaal is not None else None,
        "totaal_kostprijs": str(kostprijs_totaal) if kostprijs_totaal is not None else None,
        "marge_pct": None,
        "zekerheden": {
            "periode_start": 1.0 if dag else 0.0,
            "periode_eind": 1.0 if dag else 0.0,
            "totaal_omzet": 1.0 if totaal is not None else 0.0,
            "totaal_kostprijs": 1.0 if kostprijs_totaal is not None else 0.0,
        },
        "regels": regels,
        "regelsom_omzet": (
            {
                "vergelijkbaar": True,
                "som": str(som),
                "totaal": str(totaal),
                "verschil": str(_d2(som - totaal)),
                "sluit": abs(som - totaal) <= _TOL,
            }
            if journaal is not None and totaal is not None
            else {"vergelijkbaar": False, "reden": "geen journaal" if journaal is None else "geen bruto omzet"}
        ),
        "regelsom_kostprijs": (
            {
                "vergelijkbaar": True,
                "som": str(kostprijs_totaal),
                "totaal": str(marge.totaal),
                "verschil": str(_d2(kostprijs_totaal - marge.totaal)),
                "sluit": abs(kostprijs_totaal - marge.totaal) <= _TOL,
            }
            if marge is not None and marge.totaal is not None and kostprijs_totaal is not None
            else {"vergelijkbaar": False, "reden": "geen margerapport" if marge is None else "geen totaal"}
        ),
        "onparseerbaar": [],
        "bsn_verwijderd": 0,
        "bron_detail": {
            "kassas": journaal.kassas if journaal else [],
            "periode_van": journaal.periode_van.isoformat() if journaal and journaal.periode_van else None,
            "periode_tot": journaal.periode_tot.isoformat() if journaal and journaal.periode_tot else None,
            "datum": dag.isoformat() if dag else None,
            "klanten": journaal.klanten if journaal else None,
            "uitdraai": journaal.uitdraai.isoformat() if journaal and journaal.uitdraai else None,
            "betaalwijzen": {k: str(v) for k, v in (journaal.betaalwijzen if journaal else {}).items()},
            "bruto": str(journaal.bruto) if journaal and journaal.bruto is not None else None,
            "kortingen": str(journaal.kortingen) if journaal and journaal.kortingen is not None else None,
            "vouchers": str(journaal.vouchers) if journaal and journaal.vouchers is not None else None,
            "netto": str(journaal.netto) if journaal and journaal.netto is not None else None,
            "marge": (
                {
                    "periode_van": marge.periode_van.isoformat() if marge.periode_van else None,
                    "periode_tot": marge.periode_tot.isoformat() if marge.periode_tot else None,
                    "totaal": str(marge.totaal) if marge.totaal is not None else None,
                    "document_id": marge_document_id,
                    "stand": "gekoppeld",
                }
                if marge is not None
                else {"stand": "verwacht"}
            ),
            "controles": controles,
            "wacht_op": wacht_op,
            "sluit": all(c["ok"] for c in controles if c["blokkerend"]),
            "bestandsnaam": bestandsnaam,
        },
    }
