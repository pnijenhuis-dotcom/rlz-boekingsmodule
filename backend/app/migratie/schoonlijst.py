"""Schoonlijst vóór een RLZ → Odoo-overstap (bundel 10-09 blok D1; besluit Peter 10-09, eerste casus Vastgoedgroep
Nederland, RLZ-VGG, Odoo company 6 leeg).

LEES-ONLY rapport per administratie, vijf categorieën — elk een tabel boekstuk | datum | bedrag | entity |
omschrijving | bevinding:
(a) concepten — PurchaseInvoices, SalesInvoices, ManualJournals (+ Receipts als die collectie leesbaar is) met
    Status 1. Het filter is CLIENT-SIDE: `$filter=Status eq 1` geeft een 400 (enum-type, api-verkenning
    "Description op PurchaseInvoices — STAP 0 07-09"); de collecties zijn klein genoeg voor één gepagineerde reeks.
(b) vermoedelijke dubbelen — binnen dezelfde collectie gelijk cent-exact bedrag + gelijke datum + dezelfde Entity
    (of beide zonder Entity); groepen mét boekstuknummers. Bewust ruimer dan `rlz_dubbel` (referentie-only): dit is
    een opruimlijst voor een mens, geen dagelijkse bevinding — ruis is hier goedkoper dan een gemist paar.
(c) open bankregels — PaymentTransactions met `OpenAmount != 0` (nooit `IsComplete`: stale ná storno), per rekening.
(d) rekeningen met dubbele IBAN — PaymentAccounts op genormaliseerde IBAN (de spaarrekening-casus), beide genoemd.
(e) boekingen zonder Entity mét een bijlage — de collecties dragen geen `AttachmentCount`/`HasAttachments`-veld
    (veldset geverifieerd op de PoC-audits), dus per document `GET …/{id}/Uploads?$top=1`, begrensd door
    `max_bijlage_checks` (default 200); wat buiten de grens valt staat ZICHTBAAR als "niet gecontroleerd".

Verwachtingen van Peter (17 concepten / 3 dubbelen / 44 bankregels / 1 dubbele IBAN) worden NIET hardgecodeerd:
de CLI neemt ze als `--verwacht` en het rapport zet "verwacht door Peter" náást "gevonden".

Een route die weigert (403 rechten, 404 onbekend, 5xx) wordt één zichtbare regel onder "Fouten" — nooit een crash,
nooit een stil lege categorie. Geen writes, geen AI, geld in Decimal."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from dataclasses import asdict, dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.rlz.lezen import (
    LeesClient,
    LeesUitkomst,
    als_bedrag,
    als_datum,
    als_int,
    entity_van,
    heeft_bijlage,
    lees_collectie,
)

STATUS_CONCEPT = 1
#: Collecties met documentstatus; Receipts is een collectie zónder eigen `{id}`-route (api-verkenning "Receipts-
#: verkenning") en bestaat mogelijk niet op elke login — daarom "optioneel": een fout dáár is een OVERGESLAGEN-regel.
DOCUMENT_COLLECTIES: tuple[tuple[str, str | None], ...] = (
    ("PurchaseInvoices", "Entity"),
    ("SalesInvoices", "Entity"),
    ("ManualJournals", None),
)
OPTIONELE_COLLECTIES: tuple[str, ...] = ("Receipts",)
#: Collecties waarop `GET …/{id}/Uploads` als aanwezigheidscheck is bewezen (16-08).
BIJLAGE_COLLECTIES: frozenset[str] = frozenset({"PurchaseInvoices", "SalesInvoices", "ManualJournals"})
MAX_BIJLAGE_CHECKS_DEFAULT = 200

CATEGORIEEN: tuple[tuple[str, str], ...] = (
    ("concepten", "Concepten in RLZ (Status 1)"),
    ("dubbelen", "Vermoedelijke dubbelen (zelfde collectie, bedrag, datum, relatie)"),
    ("open_bankregels", "Open bankregels (OpenAmount ≠ 0)"),
    ("dubbele_iban", "Bankrekeningen met dubbele IBAN"),
    ("zonder_relatie_met_bijlage", "Boekingen zonder relatie mét bijlage"),
)
VERWACHT_SLEUTELS: frozenset[str] = frozenset(k for k, _ in CATEGORIEEN)

_IBAN_SCHOON = re.compile(r"[^A-Z0-9]")


# ---- data ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class Rij:
    """Eén tabelrij; `sleutel` is de stabiele sorteersleutel (collectie, datum, boekstuk, id)."""

    categorie: str
    collectie: str
    rlz_id: str | None
    boekstuk: str | None
    datum: date | None
    bedrag: Decimal | None
    entity: str | None
    omschrijving: str | None
    bevinding: str
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def sleutel(self) -> tuple[str, str, str, str]:
        return (self.collectie, self.datum.isoformat() if self.datum else "", self.boekstuk or "", self.rlz_id or "")

    def als_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["datum"] = self.datum.isoformat() if self.datum else None
        d["bedrag"] = str(self.bedrag) if self.bedrag is not None else None
        return d


@dataclass(frozen=True)
class Fout:
    route: str
    status: int | None
    melding: str

    def als_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class Schoonlijst:
    administratie_id: str | None
    rlz_admin_id: str | None
    gegenereerd_op: str
    rijen: dict[str, list[Rij]] = field(default_factory=lambda: {k: [] for k, _ in CATEGORIEEN})
    fouten: list[Fout] = field(default_factory=list)
    overgeslagen: list[str] = field(default_factory=list)
    gelezen: dict[str, int] = field(default_factory=dict)
    bijlage_checks: int = 0
    bijlage_niet_gecontroleerd: int = 0
    verwacht: dict[str, int] = field(default_factory=dict)

    @property
    def tellers(self) -> dict[str, int]:
        """Per categorie het aantal gemelde EENHEDEN: documenten (a/c/e), groepen (b), IBAN's (d)."""
        return {
            "concepten": len(self.rijen["concepten"]),
            "dubbelen": len({r.extra.get("groep") for r in self.rijen["dubbelen"]}),
            "open_bankregels": len(self.rijen["open_bankregels"]),
            "dubbele_iban": len({r.extra.get("iban") for r in self.rijen["dubbele_iban"]}),
            "zonder_relatie_met_bijlage": sum(
                1 for r in self.rijen["zonder_relatie_met_bijlage"] if r.extra.get("bijlage") is True
            ),
        }

    def als_dict(self) -> dict[str, Any]:
        return {
            "administratie_id": self.administratie_id,
            "rlz_admin_id": self.rlz_admin_id,
            "gegenereerd_op": self.gegenereerd_op,
            "tellers": self.tellers,
            "verwacht": {k: self.verwacht.get(k) for k, _ in CATEGORIEEN},
            "gelezen": dict(sorted(self.gelezen.items())),
            "bijlage_checks": self.bijlage_checks,
            "bijlage_niet_gecontroleerd": self.bijlage_niet_gecontroleerd,
            "categorieen": {
                k: [r.als_dict() for r in sorted(v, key=lambda r: r.sleutel)] for k, v in self.rijen.items()
            },
            "fouten": [f.als_dict() for f in self.fouten],
            "overgeslagen": list(self.overgeslagen),
        }

    def als_json(self) -> str:
        return json.dumps(self.als_dict(), ensure_ascii=False, indent=2, sort_keys=False)


# ---- helpers -------------------------------------------------------------------------------------


def normaliseer_iban(iban: object) -> str | None:
    if not isinstance(iban, str):
        return None
    schoon = _IBAN_SCHOON.sub("", iban.upper())
    return schoon or None


def parse_verwacht(tekst: str | None) -> dict[str, int]:
    """`--verwacht "concepten=17,dubbelen=3,open_bankregels=44,dubbele_iban=1"` → dict; onbekende sleutel = ValueError
    (fail-fast, geen stil genegeerde verwachting)."""
    if not tekst:
        return {}
    uit: dict[str, int] = {}
    for deel in tekst.split(","):
        deel = deel.strip()
        if not deel:
            continue
        sleutel, _, waarde = deel.partition("=")
        sleutel = sleutel.strip()
        if sleutel not in VERWACHT_SLEUTELS:
            raise ValueError(f"onbekende verwachting {sleutel!r}; kies uit {sorted(VERWACHT_SLEUTELS)}")
        uit[sleutel] = int(waarde.strip())
    return uit


def _omschrijving(rij: dict[str, Any]) -> str | None:
    for veld in ("Description", "Header", "Reference"):
        w = rij.get(veld)
        if isinstance(w, str) and w.strip():
            return " ".join(w.split())
    return None


def _document_rij(categorie: str, collectie: str, rij: dict[str, Any], bevinding: str, **extra: Any) -> Rij:
    _, entity_naam = entity_van(rij)
    return Rij(
        categorie=categorie,
        collectie=collectie,
        rlz_id=str(rij["id"]) if rij.get("id") else None,
        boekstuk=str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") else None,
        datum=als_datum(rij.get("Date")) or als_datum(rij.get("BookDate")),
        bedrag=als_bedrag(rij.get("BaseInvoiceAmount")),
        entity=entity_naam,
        omschrijving=_omschrijving(rij),
        bevinding=bevinding,
        extra=extra,
    )


def _registreer(lijst: Schoonlijst, uitkomst: LeesUitkomst, *, optioneel: bool = False) -> bool:
    """Boek een leesuitkomst in (aantal gelezen, fout of overgeslagen). True = rijen bruikbaar."""
    if uitkomst.fout is not None:
        melding = f"{uitkomst.fout.status_code}: {uitkomst.fout.body[:160]}"
        if optioneel:
            lijst.overgeslagen.append(f"{uitkomst.pad}: collectie niet leesbaar ({melding}) — overgeslagen")
        else:
            lijst.fouten.append(Fout(route=uitkomst.pad, status=uitkomst.fout.status_code, melding=melding))
        return False
    lijst.gelezen[uitkomst.pad] = len(uitkomst.rijen)
    if not uitkomst.expand_gelukt:
        lijst.overgeslagen.append(f"{uitkomst.pad}: $expand geweigerd — relatie-naam ontbreekt in deze tabel")
    return True


# ---- categorieën (puur op rijen) ------------------------------------------------------------------


def concepten(collectie: str, rijen: Iterable[dict[str, Any]]) -> list[Rij]:
    return [
        _document_rij("concepten", collectie, r, "concept (Status 1) — boeken of laten vervallen vóór de overstap")
        for r in rijen
        if als_int(r.get("Status")) == STATUS_CONCEPT
    ]


def dubbelen(collectie: str, rijen: Iterable[dict[str, Any]]) -> list[Rij]:
    """Groepen op (bedrag cent-exact, datum, entity-id of None) met ≥ 2 documenten. Concepten tellen mee (gemarkeerd):
    een concept náást een geboekt exemplaar is precies de opruimcasus."""
    groepen: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rijen:
        bedrag = als_bedrag(r.get("BaseInvoiceAmount"))
        datum = als_datum(r.get("Date")) or als_datum(r.get("BookDate"))
        if bedrag is None or datum is None:
            continue
        entity_id, _ = entity_van(r)
        groepen.setdefault((str(bedrag), datum.isoformat(), entity_id or ""), []).append(r)
    uit: list[Rij] = []
    for (bedrag, datum, entity_id), docs in sorted(groepen.items()):
        if len(docs) < 2:
            continue
        groep = f"{collectie}|{datum}|{bedrag}|{entity_id or 'geen-relatie'}"
        boekstukken = sorted(str(d.get("ReceiptNumber") or d.get("id") or "?") for d in docs)
        for d in docs:
            concept = " (concept)" if als_int(d.get("Status")) == STATUS_CONCEPT else ""
            uit.append(
                _document_rij(
                    "dubbelen",
                    collectie,
                    d,
                    f"{len(docs)}× € {bedrag} op {datum}{' zonder relatie' if not entity_id else ''}: "
                    f"{', '.join(boekstukken)}{concept}",
                    groep=groep,
                    groep_grootte=len(docs),
                )
            )
    return uit


def open_bankregels(rijen: Iterable[dict[str, Any]]) -> list[Rij]:
    uit: list[Rij] = []
    for r in rijen:
        open_bedrag = als_bedrag(r.get("OpenAmount"))
        if open_bedrag is None or open_bedrag == 0:
            continue
        rekening = r.get("PaymentAccount") if isinstance(r.get("PaymentAccount"), dict) else {}
        rekening_naam = (
            rekening.get("Name") or rekening.get("Description") or rekening.get("IBAN") or "onbekende rekening"
        )
        uit.append(
            Rij(
                categorie="open_bankregels",
                collectie="PaymentTransactions",
                rlz_id=str(r["id"]) if r.get("id") else None,
                boekstuk=str(r.get("TransactionId") or ""),
                datum=als_datum(r.get("BookDate")) or als_datum(r.get("Date")),
                bedrag=als_bedrag(r.get("Amount")),
                entity=r.get("Name") if isinstance(r.get("Name"), str) else None,
                omschrijving=(" ".join(str(r.get("Reference")).split()) if r.get("Reference") else None),
                bevinding=f"open € {open_bedrag} op {rekening_naam}"
                + (f" ({r.get('CounterAccount')})" if r.get("CounterAccount") else ""),
                extra={
                    "rekening": str(rekening_naam),
                    "rekening_id": str(rekening.get("id")) if rekening.get("id") else None,
                    "open_bedrag": str(open_bedrag),
                    "tegenrekening": r.get("CounterAccount"),
                },
            )
        )
    return uit


def dubbele_iban(rijen: Iterable[dict[str, Any]]) -> list[Rij]:
    per_iban: dict[str, list[dict[str, Any]]] = {}
    for r in rijen:
        iban = normaliseer_iban(r.get("IBAN")) or normaliseer_iban(r.get("AccountNumber"))
        if iban:
            per_iban.setdefault(iban, []).append(r)
    uit: list[Rij] = []
    for iban, rekeningen in sorted(per_iban.items()):
        if len(rekeningen) < 2:
            continue
        namen = sorted(str(x.get("Name") or x.get("Description") or x.get("id") or "?") for x in rekeningen)
        for x in rekeningen:
            archief = " (gearchiveerd)" if x.get("IsArchived") else ""
            uit.append(
                Rij(
                    categorie="dubbele_iban",
                    collectie="PaymentAccounts",
                    rlz_id=str(x["id"]) if x.get("id") else None,
                    boekstuk=None,
                    datum=als_datum(x.get("LastBalanceDate")),
                    bedrag=als_bedrag(x.get("CurrentBalance")),
                    entity=str(x.get("Name") or x.get("Description") or "?") + archief,
                    omschrijving=f"type {x.get('Type')} · IBAN {iban}",
                    bevinding=f"IBAN {iban} op {len(rekeningen)} rekeningen: {' + '.join(namen)}",
                    extra={"iban": iban, "type": x.get("Type"), "is_archived": bool(x.get("IsArchived"))},
                )
            )
    return uit


def zonder_relatie_kandidaten(collectie: str, rijen: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    """Documenten zonder Entity — kandidaten voor de bijlagecheck; nieuwste eerst zodat de grens de oude historie
    treft, niet het recente werk."""
    kandidaten = [r for r in rijen if entity_van(r)[0] is None]
    kandidaten.sort(key=lambda r: (als_datum(r.get("Date")) or date.min, str(r.get("id") or "")), reverse=True)
    return kandidaten


# ---- de lijst ------------------------------------------------------------------------------------


def maak_schoonlijst(
    client: LeesClient,
    *,
    administratie_id: str | None = None,
    rlz_admin_id: str | None = None,
    max_bijlage_checks: int = MAX_BIJLAGE_CHECKS_DEFAULT,
    verwacht: dict[str, int] | None = None,
    nu: datetime | None = None,
) -> Schoonlijst:
    """Alles lezen, niets schrijven. Eén weigerende route = één regel onder Fouten; de andere categorieën gaan door."""
    lijst = Schoonlijst(
        administratie_id=administratie_id,
        rlz_admin_id=rlz_admin_id,
        gegenereerd_op=(nu or datetime.now(UTC)).isoformat(timespec="seconds"),
        verwacht=dict(verwacht or {}),
    )
    documenten: dict[str, list[dict[str, Any]]] = {}
    for pad, expand in DOCUMENT_COLLECTIES:
        uitkomst = lees_collectie(client, pad, expand=expand)
        if _registreer(lijst, uitkomst):
            documenten[pad] = uitkomst.rijen
    for pad in OPTIONELE_COLLECTIES:
        uitkomst = lees_collectie(client, pad)
        if _registreer(lijst, uitkomst, optioneel=True):
            # Een Receipt ís een SalesInvoice zonder Entity en staat in dezelfde RLZ-01-reeks: een rij die al
            # via SalesInvoices gelezen is telt niet dubbel.
            bekend = {str(r.get("id")) for rijen in documenten.values() for r in rijen}
            documenten[pad] = [r for r in uitkomst.rijen if str(r.get("id")) not in bekend]

    for pad, rijen in documenten.items():
        lijst.rijen["concepten"].extend(concepten(pad, rijen))
        lijst.rijen["dubbelen"].extend(dubbelen(pad, rijen))

    bank = lees_collectie(client, "PaymentTransactions", expand="PaymentAccount")
    if _registreer(lijst, bank):
        lijst.rijen["open_bankregels"].extend(open_bankregels(bank.rijen))

    rekeningen = lees_collectie(client, "PaymentAccounts")
    if _registreer(lijst, rekeningen):
        lijst.rijen["dubbele_iban"].extend(dubbele_iban(rekeningen.rijen))

    _bijlagen(client, lijst, documenten, max_bijlage_checks=max_bijlage_checks)

    for k in lijst.rijen:
        lijst.rijen[k].sort(key=lambda r: r.sleutel)
    return lijst


def _bijlagen(
    client: LeesClient, lijst: Schoonlijst, documenten: dict[str, list[dict[str, Any]]], *, max_bijlage_checks: int
) -> None:
    budget = max(0, int(max_bijlage_checks))
    for pad in [p for p, _ in DOCUMENT_COLLECTIES if p in BIJLAGE_COLLECTIES]:
        for r in zonder_relatie_kandidaten(pad, documenten.get(pad, [])):
            rlz_id = str(r.get("id") or "")
            if not rlz_id:
                continue
            if lijst.bijlage_checks >= budget:
                lijst.bijlage_niet_gecontroleerd += 1
                lijst.rijen["zonder_relatie_met_bijlage"].append(
                    _document_rij(
                        "zonder_relatie_met_bijlage",
                        pad,
                        r,
                        f"zonder relatie — bijlage NIET gecontroleerd (grens --max-bijlage-checks {budget})",
                        bijlage=None,
                    )
                )
                continue
            lijst.bijlage_checks += 1
            aanwezig = heeft_bijlage(client, pad, rlz_id)
            if aanwezig is True:
                lijst.rijen["zonder_relatie_met_bijlage"].append(
                    _document_rij(
                        "zonder_relatie_met_bijlage",
                        pad,
                        r,
                        "zonder relatie mét bijlage — bijlage suggereert een factuur: relatie toekennen of bevestigen "
                        "dat het een bank-directe/memoriaal-post is",
                        bijlage=True,
                    )
                )
            elif aanwezig is None:
                lijst.rijen["zonder_relatie_met_bijlage"].append(
                    _document_rij(
                        "zonder_relatie_met_bijlage", pad, r, "zonder relatie — Uploads-route weigerde", bijlage=None
                    )
                )


# ---- weergave -------------------------------------------------------------------------------------


def _md(waarde: object) -> str:
    if waarde is None or waarde == "":
        return "—"
    tekst = str(waarde).replace("|", "\\|").replace("\n", " ")
    return tekst if len(tekst) <= 120 else tekst[:117] + "…"


def _bedrag_md(bedrag: Decimal | None) -> str:
    return "—" if bedrag is None else f"€ {bedrag:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")


def als_markdown(lijst: Schoonlijst, *, administratie_naam: str | None = None) -> str:
    """BESLISSINGEN-vorm: tellers bovenaan (gevonden náást verwacht door Peter), per categorie een kop + tabel."""
    regels: list[str] = []
    kop = administratie_naam or lijst.administratie_id or "administratie"
    regels.append(f"### Schoonlijst {kop} (RLZ {lijst.rlz_admin_id or '?'}, gegenereerd {lijst.gegenereerd_op})")
    regels.append("")
    regels.append("| Categorie | Gevonden | Verwacht door Peter | Verschil |")
    regels.append("|---|---|---|---|")
    tellers = lijst.tellers
    for sleutel, titel in CATEGORIEEN:
        gevonden = tellers[sleutel]
        verwacht = lijst.verwacht.get(sleutel)
        verschil = "—" if verwacht is None else ("gelijk" if verwacht == gevonden else f"{gevonden - verwacht:+d}")
        regels.append(f"| {titel} | {gevonden} | {_md(verwacht)} | {verschil} |")
    regels.append("")
    gelezen = ", ".join(f"{k} {v}" for k, v in sorted(lijst.gelezen.items())) or "niets"
    regels.append(
        f"Gelezen: {gelezen}. Bijlagechecks: {lijst.bijlage_checks} gedaan, {lijst.bijlage_niet_gecontroleerd} "
        "niet gecontroleerd (grens)."
    )
    if lijst.fouten:
        regels.append("")
        regels.append("#### Fouten (route weigerde — categorie onvolledig)")
        regels.append("")
        regels.append("| Route | Status | Melding |")
        regels.append("|---|---|---|")
        for f in lijst.fouten:
            regels.append(f"| {_md(f.route)} | {_md(f.status)} | {_md(f.melding)} |")
    if lijst.overgeslagen:
        regels.append("")
        for o in lijst.overgeslagen:
            regels.append(f"- OVERGESLAGEN {o}")
    for sleutel, titel in CATEGORIEEN:
        rijen = sorted(lijst.rijen[sleutel], key=lambda r: r.sleutel)
        regels.append("")
        regels.append(f"#### {titel} — {tellers[sleutel]}")
        regels.append("")
        if not rijen:
            regels.append("_geen_")
            continue
        regels.append("| Boekstuk | Datum | Bedrag | Entity | Omschrijving | Bevinding |")
        regels.append("|---|---|---|---|---|---|")
        for r in rijen:
            regels.append(
                f"| {_md(r.boekstuk)} | {_md(r.datum.isoformat() if r.datum else None)} | {_bedrag_md(r.bedrag)} | "
                f"{_md(r.entity)} | {_md(r.omschrijving)} | {_md(r.bevinding)} |"
            )
    return "\n".join(regels) + "\n"
