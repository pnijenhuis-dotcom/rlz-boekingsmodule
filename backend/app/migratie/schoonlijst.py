"""Schoonlijst vóór een RLZ → Odoo-overstap (bundel 10-09 blok D1; besluit Peter 10-09, eerste casus Vastgoedgroep
Nederland, RLZ-VGG, Odoo company 6 leeg; herzien run 2 VGG 12-09 blok 1 — nameting 11-09 gaf 62 concepten en 51
dubbelen-groepen waar Peter 17 en 3 verwachtte).

LEES-ONLY rapport per administratie — elk een tabel boekstuk | datum | bedrag | entity | omschrijving | bevinding:
(a) concepten — PurchaseInvoices, SalesInvoices, ManualJournals (+ Receipts als die collectie leesbaar is) met
    Status 1. Het filter is CLIENT-SIDE: `$filter=Status eq 1` geeft een 400 (enum-type, api-verkenning
    "Description op PurchaseInvoices — STAP 0 07-09"); de collecties zijn klein genoeg voor één gepagineerde reeks.
    Sinds 12-09 zonder (a1) en (a2):
(a1) systeemhulzen open bank — RLZ maakt voor élke open bankmutatie een concept-huls aan (de RLZ-09-reeks op VGG:
    44 stuks = exact de 44 open bankregels). Herkenning op GEDRAG, niet op dagboekcode: concept (Status 1) + geen
    Entity + cent-exact signed bedrag én datum gelijk aan een OPEN PaymentTransaction (OpenAmount ≠ 0) + omschrijving
    leeg óf (genormaliseerd) bevat in de ontknipte bank-Reference; elke bankmutatie levert hoogstens één huls.
    Eigen categorie `systeemhulzen_open_bank`, BUITEN de concepten-teller. Bank niet leesbaar → geen hulzen
    herkenbaar, alles blijft concept (zichtbaar in de kop).
(a2) concept = kopie van geboekt — een concept met cent-exact |bedrag| + datum + genormaliseerde omschrijving gelijk
    aan een GEBOEKT document (Status 2/3) in dezelfde óf een andere collectie (VGG: RLZ-04-00000062 concept
    € 65.000 ↔ RLZ-06-00000070 memoriaal € −65.000, zelfde tekst "Aanbetaling volgens afspraak: Oosterdiepswal 7 te
    Kollum", zelfde dag → daarom |bedrag|). Een concept ZONDER omschrijving met precies één geboekt document met
    hetzelfde |bedrag| op dezelfde dag in dezelfde collectie is ALLEEN kopie als de bank-leidend-regel het bevestigt
    (besluit Peter 12-09 blok 7 punt 4): precies ÉÉN bankmutatie voor dat bedrag/die datum (±BANK_VENSTER_DAGEN)
    tegenover de twee boekingen. Twee of meer mutaties = twee echte boekingen (blijft gewoon concept); nul mutaties,
    bank niet gelezen of teken onbekend = categorie `concept_kopie_onbeslist` — zichtbaar, geen stille keuze.
    Bevinding "niet migreren, kopie van <boekstuk>"; kopieën én onbesliste verdwijnen uit (a) én uit (b).
(b) vermoedelijke dubbelen — binnen dezelfde collectie gelijk cent-exact bedrag + gelijke datum + dezelfde Entity
    (of beide zonder Entity); groepen mét boekstuknummers. Bewust ruimer dan `rlz_dubbel` (referentie-only): dit is
    een opruimlijst voor een mens, geen dagelijkse bevinding. Sinds 12-09 twee poorten eróverheen:
(b1) verschillend kenmerk — omschrijvingen in de groep dragen VERSCHILLENDE adressen of VERSCHILLENDE nummers
    (factuur-/order-/kenmerknummers ≥ 4 cijfers, geen jaartal): drie panden à € 20.000 op één dag, Full House
    2522781 vs 2522771, Kadaster-ordernummers, Consten drie adressen → categorie `zelfde_bedrag_verschillend_kenmerk`
    (ingeklapt in de md). Documenten zonder kenmerk ("Rc" vs "Afbetaling RC", lege omschrijving) zijn compatibel met
    alles en blijven kandidaat. Een groep kan splitsen: de compatibele deelgroep blijft dubbel-kandidaat, de losse
    exemplaren gaan naar (b1).
(b2) BANK IS LEIDEND (aanvulling Peter 12-09, CONTRACT_RUN2 besluit 6; `app/migratie/bankdekking.py`): een groep is
    alleen dubbel als er MINDER bankmutaties (cent-exact |bedrag|, zelfde teken, BookDate ±3 dagen) tegenover staan
    dan boekingen; evenveel/meer = `bank_bevestigd` (ingeklapt, niet in de dubbelen-tabel). Bank-directe boekingen
    (Receipts; reeksen die uit de data als bankdagboek blijken — VGG: RLZ-09/25/28/46/60) zijn per definitie
    bank-bevestigd. PaymentTransactions niet leesbaar → niets gefilterd, markering "bank niet gelezen" in kop én
    bevinding.
(c) open bankregels — PaymentTransactions met `OpenAmount != 0` (nooit `IsComplete`: stale ná storno), per rekening.
(d) rekeningen met dubbele IBAN — PaymentAccounts op genormaliseerde IBAN (de spaarrekening-casus), beide genoemd.
(e) boekingen zonder Entity mét een bijlage — de collecties dragen geen `AttachmentCount`/`HasAttachments`-veld
    (veldset geverifieerd op de PoC-audits), dus per document `GET …/{id}/Uploads?$top=1`, begrensd door
    `max_bijlage_checks` (default 200); wat buiten de grens valt staat ZICHTBAAR als "niet gecontroleerd".

Omschrijvingen komen ÁLTIJD via `app.rlz.tekst.ontknip_velden` (documenten) / `ontknip` (bankregels): RLZ levert
bank-geïmporteerde tekst als `\\n`-regels van 32 tekens (blok 0 12-09) — nooit meer `" ".join(x.split())`.

Verwachtingen van Peter worden NIET hardgecodeerd: de CLI neemt ze als `--verwacht` en het rapport zet "verwacht
door Peter" náást "gevonden". Een route die weigert (403 rechten, 404 onbekend, 5xx) wordt één zichtbare regel onder
"Fouten" — nooit een crash, nooit een stil lege categorie. Geen writes, geen AI, geld in Decimal."""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Iterable, Sequence
from dataclasses import asdict, dataclass, field, replace
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Any

from app.migratie import bankdekking
from app.migratie.bankdekking import BankMutatie, Dekking
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
from app.rlz.tekst import ontknip, ontknip_velden

logger = logging.getLogger(__name__)

STATUS_CONCEPT = 1
GEBOEKT_STATUSSEN: frozenset[int] = frozenset({2, 3})
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
#: Bankvenster voor de dekking van een dubbelen-groep (CONTRACT_RUN2 besluit 6: BookDate ±3 dagen).
BANK_VENSTER_DAGEN = 3

CATEGORIEEN: tuple[tuple[str, str], ...] = (
    ("concepten", "Concepten in RLZ (Status 1)"),
    ("systeemhulzen_open_bank", "Systeemhulzen open bank (concept-huls per open bankmutatie)"),
    ("concept_kopie_van_geboekt", "Concept = kopie van geboekt"),
    ("concept_kopie_onbeslist", "Concept zonder omschrijving — kopie onbeslist (bank bevestigt niet)"),
    ("dubbelen", "Vermoedelijke dubbelen (zelfde collectie, bedrag, datum, relatie; bank-tekort)"),
    ("zelfde_bedrag_verschillend_kenmerk", "Zelfde bedrag, verschillend kenmerk"),
    ("bank_bevestigd", "Bank-bevestigd (evenveel of meer bankmutaties dan boekingen)"),
    ("open_bankregels", "Open bankregels (OpenAmount ≠ 0)"),
    ("dubbele_iban", "Bankrekeningen met dubbele IBAN"),
    ("zonder_relatie_met_bijlage", "Boekingen zonder relatie mét bijlage"),
)
#: Categorieën die in de markdown standaard INGEKLAPT staan (`<details>`): lees-hulp, geen handeling.
INGEKLAPT: frozenset[str] = frozenset(
    {"systeemhulzen_open_bank", "zelfde_bedrag_verschillend_kenmerk", "bank_bevestigd"}
)
#: Categorieën die per GROEP tellen (niet per document).
GROEP_CATEGORIEEN: frozenset[str] = frozenset({"dubbelen", "zelfde_bedrag_verschillend_kenmerk", "bank_bevestigd"})
VERWACHT_SLEUTELS: frozenset[str] = frozenset(k for k, _ in CATEGORIEEN)

_IBAN_SCHOON = re.compile(r"[^A-Z0-9]")
_NIET_ALNUM = re.compile(r"[^a-z0-9]")
#: Kenmerk-nummers: cijferreeksen van ≥ 4 (factuur-/order-/kenmerknummers); een los jaartal telt niet.
_NUMMER = re.compile(r"\d{4,}")
_JAARTAL = re.compile(r"^(?:19|20)\d{2}$")
#: Terugval-adresherkenning: straatnaam (eerste letter vrij, daarna kleine letters — "RLZ-04" valt af) + huisnummer
#: (≤ 4 cijfers, geen jaartal) + optionele toevoeging ("34b", "84D", "123B", "Kouvenderstraat34b").
_ADRES_TERUGVAL = re.compile(
    r"(?<![A-Za-z])([A-Z]?[a-z][a-z'\-]{3,})\s?(\d{1,4})(?!\d)(?:\s?([A-Za-z]{1,2}))?(?![A-Za-z])"
)


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

    @property
    def status(self) -> int | None:
        return als_int(self.extra.get("status"))

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
    #: Bank-leidend: PaymentTransactions gelezen? aantal mutaties; afgeleide bankdagboek-reeksen (reeks → (n, k)).
    bank_gelezen: bool = False
    bank_mutaties: int = 0
    bank_reeksen: dict[str, tuple[int, int]] = field(default_factory=dict)

    @property
    def tellers(self) -> dict[str, int]:
        """Per categorie het aantal gemelde EENHEDEN: documenten (a/a1/a2/c/e), groepen (b/b1/b2), IBAN's (d)."""
        uit: dict[str, int] = {}
        for k, _ in CATEGORIEEN:
            rijen = self.rijen[k]
            if k in GROEP_CATEGORIEEN:
                uit[k] = len({r.extra.get("groep") for r in rijen})
            elif k == "dubbele_iban":
                uit[k] = len({r.extra.get("iban") for r in rijen})
            elif k == "zonder_relatie_met_bijlage":
                uit[k] = sum(1 for r in rijen if r.extra.get("bijlage") is True)
            else:
                uit[k] = len(rijen)
        return uit

    def als_dict(self) -> dict[str, Any]:
        return {
            "administratie_id": self.administratie_id,
            "rlz_admin_id": self.rlz_admin_id,
            "gegenereerd_op": self.gegenereerd_op,
            "tellers": self.tellers,
            "verwacht": {k: self.verwacht.get(k) for k, _ in CATEGORIEEN},
            "gelezen": dict(sorted(self.gelezen.items())),
            "bank": {
                "gelezen": self.bank_gelezen,
                "mutaties": self.bank_mutaties,
                "reeksen": {k: list(v) for k, v in sorted(self.bank_reeksen.items())},
            },
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


def normaliseer_omschrijving(tekst: str | None) -> str | None:
    """Vergelijkingsvorm van een (al ontknipte) omschrijving: kleine letters, alleen letters/cijfers. None = leeg."""
    if not isinstance(tekst, str):
        return None
    schoon = _NIET_ALNUM.sub("", tekst.lower())
    return schoon or None


def parse_verwacht(tekst: str | None) -> dict[str, int]:
    """`--verwacht "concepten=17,dubbelen=3,open_bankregels=44,dubbele_iban=1"` → dict; onbekende sleutel = ValueError
    (fail-fast, geen stil genegeerde verwachting). Sinds 12-09 ook `systeemhulzen_open_bank`,
    `concept_kopie_van_geboekt`, `zelfde_bedrag_verschillend_kenmerk`, `bank_bevestigd`."""
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
    """DE omschrijvingsbron voor documenten: eerste gevulde veld, ontknipt (blok 0 12-09)."""
    return ontknip_velden(rij, "Description", "Header", "Reference")


def _doc_datum(rij: dict[str, Any]) -> date | None:
    return als_datum(rij.get("Date")) or als_datum(rij.get("BookDate"))


def _doc_id(rij: dict[str, Any]) -> str | None:
    return str(rij["id"]) if rij.get("id") else None


def _document_rij(categorie: str, collectie: str, rij: dict[str, Any], bevinding: str, **extra: Any) -> Rij:
    _, entity_naam = entity_van(rij)
    extra.setdefault("status", als_int(rij.get("Status")))
    return Rij(
        categorie=categorie,
        collectie=collectie,
        rlz_id=_doc_id(rij),
        boekstuk=str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") else None,
        datum=_doc_datum(rij),
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


# ---- kenmerken (adres / nummer) ------------------------------------------------------------------


@dataclass(frozen=True)
class Kenmerk:
    """Wat een omschrijving onderscheidend maakt: adres-codes en kenmerknummers. Leeg = onderscheidt niets."""

    adressen: frozenset[str]
    nummers: frozenset[str]

    @property
    def leeg(self) -> bool:
        return not self.adressen and not self.nummers

    def conflicteert_met(self, ander: Kenmerk) -> bool:
        """Beide omschrijvingen dragen een kenmerk (adres en/of nummer) en die kenmerken verschillen. Eén kant leeg
        = compatibel ("Rc", een lege omschrijving of "RC" kan overal bij horen)."""
        return not self.leeg and not ander.leeg and self != ander


def _adres_codes_terugval(tekst: str) -> set[str]:
    uit: set[str] = set()
    for m in _ADRES_TERUGVAL.finditer(tekst):
        straat, nummer, toevoeging = m.group(1), m.group(2), m.group(3)
        if _JAARTAL.match(nummer):
            continue
        code = f"{re.sub(r'[^a-z]', '', straat.lower())}-{nummer.lstrip('0') or '0'}"
        if toevoeging:
            code += f"-{toevoeging.lower()}"
        uit.add(code)
    return uit


def _adres_codes(tekst: str) -> set[str]:
    """Adres-codes uit de omschrijving: de pandenregister-herkenning (`app.panden.afleiding.adressen_uit_tekst`,
    alleen-lezen) verenigd met een eigen eenvoudige terugval — de afleiding eist een straat-suffix ("Koraalerf 45",
    "Heidebeemd 3" vallen daar buiten), de terugval vangt die. Een fout in de afleiding maakt de schoonlijst nooit
    kapot (terugval alleen)."""
    codes = _adres_codes_terugval(tekst)
    try:
        from app.panden.afleiding import adressen_uit_tekst

        codes |= {str(a.code).lower() for a in adressen_uit_tekst(tekst)}
    except Exception:  # noqa: BLE001 — B herbouwt die module; de schoonlijst blijft draaien op de terugval
        logger.debug("adressen_uit_tekst niet beschikbaar of gefaald — terugval-adresherkenning", exc_info=True)
    return codes


def kenmerk_van(omschrijving: str | None) -> Kenmerk:
    """Adres-codes + kenmerknummers (≥ 4 cijfers, geen los jaartal) uit een ontknipte omschrijving."""
    if not isinstance(omschrijving, str) or not omschrijving.strip():
        return Kenmerk(adressen=frozenset(), nummers=frozenset())
    nummers = {n for n in _NUMMER.findall(omschrijving) if not _JAARTAL.match(n)}
    return Kenmerk(adressen=frozenset(_adres_codes(omschrijving)), nummers=frozenset(nummers))


def _kenmerk_tekst(k: Kenmerk) -> str:
    delen = []
    if k.adressen:
        delen.append("adres " + "/".join(sorted(k.adressen)))
    if k.nummers:
        delen.append("nr " + "/".join(sorted(k.nummers)))
    return "; ".join(delen) or "geen kenmerk"


# ---- categorieën (puur op rijen) ------------------------------------------------------------------


def concepten(collectie: str, rijen: Iterable[dict[str, Any]], *, uitsluiten: Iterable[str] = ()) -> list[Rij]:
    """Status 1, behalve de id's in `uitsluiten` (systeemhulzen, kopieën — die hebben hun eigen tabel)."""
    weg = set(uitsluiten)
    return [
        _document_rij("concepten", collectie, r, "concept (Status 1) — boeken of laten vervallen vóór de overstap")
        for r in rijen
        if als_int(r.get("Status")) == STATUS_CONCEPT and _doc_id(r) not in weg
    ]


def systeemhulzen_open_bank(
    documenten: dict[str, list[dict[str, Any]]], open_bank: Iterable[dict[str, Any]]
) -> list[Rij]:
    """(a1) Concept-hulzen die RLZ per open bankmutatie aanmaakt — herkend op gedrag over ÁLLE collecties heen:
    Status 1 + geen Entity + |bedrag| én teken (`teken_van`) én datum gelijk aan een open PaymentTransaction +
    omschrijving leeg of (genormaliseerd) bevat in de ontknipte bank-Reference. Greedy: één huls per bankmutatie (VGG
    21-08-2026: twee keer € −2.500 → twee hulzen, twee mutaties)."""
    vrij: dict[tuple[str, int, str], list[dict[str, Any]]] = {}
    for tx in open_bank:
        bedrag = als_bedrag(tx.get("Amount"))
        datum = als_datum(tx.get("BookDate")) or als_datum(tx.get("Date"))
        if bedrag is None or bedrag == 0 or datum is None:
            continue
        vrij.setdefault((str(abs(bedrag)), 1 if bedrag > 0 else -1, datum.isoformat()), []).append(tx)
    uit: list[Rij] = []
    for collectie, rijen in documenten.items():
        for r in sorted(rijen, key=lambda r: (str(r.get("ReceiptNumber") or ""), _doc_id(r) or "")):
            if als_int(r.get("Status")) != STATUS_CONCEPT or entity_van(r)[0] is not None:
                continue
            bedrag, datum = als_bedrag(r.get("BaseInvoiceAmount")), _doc_datum(r)
            teken = bankdekking.teken_van(collectie, bedrag)
            if bedrag is None or datum is None or teken is None:
                continue
            kandidaten = vrij.get((str(abs(bedrag)), teken, datum.isoformat())) or []
            omschrijving = normaliseer_omschrijving(_omschrijving(r))
            treffer_index = next(
                (
                    i
                    for i, tx in enumerate(kandidaten)
                    if omschrijving is None
                    or omschrijving in (normaliseer_omschrijving(ontknip(tx.get("Reference"))) or "")
                ),
                None,
            )
            if treffer_index is None:
                continue
            tx = kandidaten.pop(treffer_index)
            uit.append(
                _document_rij(
                    "systeemhulzen_open_bank",
                    collectie,
                    r,
                    f"systeemhuls van open bankmutatie {tx.get('TransactionId') or tx.get('id') or '?'} "
                    f"({ontknip(tx.get('Reference')) or 'zonder omschrijving'}) — verdwijnt bij afletteren, "
                    "niet migreren",
                    bank_tx_id=str(tx.get("id")) if tx.get("id") else None,
                    bank_reference=ontknip(tx.get("Reference")),
                )
            )
    return uit


def concept_kopieen(
    documenten: dict[str, list[dict[str, Any]]],
    *,
    uitsluiten: Iterable[str] = (),
    bank: Sequence[BankMutatie] | None = None,
    venster_dagen: int = BANK_VENSTER_DAGEN,
) -> list[Rij]:
    """(a2) Concepten die een kopie zijn van een GEBOEKT document (Status 2/3): |bedrag| + datum + genormaliseerde
    omschrijving gelijk, over alle collecties heen. Lege omschrijving: alleen bij precies één geboekt exemplaar met
    hetzelfde |bedrag| op dezelfde dag in DEZELFDE collectie (meerduidig = geen kopie) ÉN bank-bevestigd (besluit
    Peter 12-09 blok 7 punt 4): precies één bankmutatie voor de twee boekingen → `concept_kopie_van_geboekt`;
    twee of meer → geen kopie (blijft concept); nul / bank niet gelezen / teken onbekend → `concept_kopie_onbeslist`.
    Geeft rijen van beide categorieën terug (`Rij.categorie` onderscheidt)."""
    weg = set(uitsluiten)
    op_tekst: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    op_bedrag: dict[tuple[str, str, str], list[tuple[str, str]]] = {}
    for collectie, rijen in documenten.items():
        for r in rijen:
            if als_int(r.get("Status")) not in GEBOEKT_STATUSSEN:
                continue
            bedrag, datum = als_bedrag(r.get("BaseInvoiceAmount")), _doc_datum(r)
            if bedrag is None or datum is None:
                continue
            verwijzing = (collectie, str(r.get("ReceiptNumber") or _doc_id(r) or "?"))
            op_bedrag.setdefault((collectie, str(abs(bedrag)), datum.isoformat()), []).append(verwijzing)
            tekst = normaliseer_omschrijving(_omschrijving(r))
            if tekst:
                op_tekst.setdefault((str(abs(bedrag)), datum.isoformat(), tekst), []).append(verwijzing)
    uit: list[Rij] = []
    for collectie, rijen in documenten.items():
        for r in rijen:
            if als_int(r.get("Status")) != STATUS_CONCEPT or _doc_id(r) in weg:
                continue
            bedrag, datum = als_bedrag(r.get("BaseInvoiceAmount")), _doc_datum(r)
            if bedrag is None or datum is None:
                continue
            tekst = normaliseer_omschrijving(_omschrijving(r))
            categorie = "concept_kopie_van_geboekt"
            if tekst:
                treffers = op_tekst.get((str(abs(bedrag)), datum.isoformat(), tekst)) or []
                zeker = "zelfde |bedrag|, datum en omschrijving"
                dekking: Dekking | None = None
            else:
                treffers = op_bedrag.get((collectie, str(abs(bedrag)), datum.isoformat())) or []
                if len(treffers) != 1:
                    continue
                # bank leidend (blok 7 punt 4): twee boekingen (concept + geboekt), hoeveel mutaties staan ertegenover?
                teken = bankdekking.teken_van(collectie, bedrag)
                dekking = bankdekking.dekking_voor(
                    [(bedrag, datum, teken), (bedrag, datum, teken)], bank, venster_dagen=venster_dagen
                )
                if not dekking.bank_gelezen or teken is None:
                    categorie = "concept_kopie_onbeslist"
                    zeker = f"omschrijving leeg, zelfde |bedrag| en datum — {dekking.detail}"
                elif dekking.bankmutaties >= 2:
                    continue  # twee echte betalingen → twee echte boekingen, geen kopie
                elif dekking.bankmutaties == 1:
                    zeker = (
                        "omschrijving leeg — zelfde |bedrag| en datum, enige geboekte exemplaar in deze collectie, "
                        f"bank bevestigt: 1 mutatie tegenover 2 boekingen (±{venster_dagen} d)"
                    )
                else:
                    categorie = "concept_kopie_onbeslist"
                    zeker = (
                        "omschrijving leeg, zelfde |bedrag| en datum, maar geen bankmutatie voor dit bedrag "
                        f"(±{venster_dagen} d) — bank bevestigt de kopie niet"
                    )
            if not treffers:
                continue
            namen = sorted({f"{b} ({c})" if c != collectie else b for c, b in treffers})
            bevinding = (
                f"niet migreren, kopie van {', '.join(namen)} — {zeker}"
                if categorie == "concept_kopie_van_geboekt"
                else f"onbeslist — mogelijk kopie van {', '.join(namen)}: {zeker}; mens beslist"
            )
            uit.append(
                _document_rij(
                    categorie,
                    collectie,
                    r,
                    bevinding,
                    kopie_van=[b for _, b in sorted(set(treffers))],
                    kopie_van_collecties=sorted({c for c, _ in treffers}),
                    **({"bank_mutaties": dekking.bankmutaties} if dekking is not None else {}),
                )
            )
    return uit


def dubbelen(collectie: str, rijen: Iterable[dict[str, Any]], *, uitsluiten: Iterable[str] = ()) -> list[Rij]:
    """(b) Groepen op (bedrag cent-exact, datum, entity-id of None) met ≥ 2 documenten. Concepten tellen mee
    (gemarkeerd): een concept náást een geboekt exemplaar is precies de opruimcasus — tenzij het al als huls of
    kopie is afgevangen (`uitsluiten`). Puur; de kenmerk- en bankpoorten zitten in `beoordeel_dubbelen`."""
    weg = set(uitsluiten)
    groepen: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for r in rijen:
        if _doc_id(r) in weg:
            continue
        bedrag, datum = als_bedrag(r.get("BaseInvoiceAmount")), _doc_datum(r)
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


def _componenten(rijen: Sequence[Rij]) -> list[list[Rij]]:
    """Verbind rijen waarvan de kenmerken NIET conflicteren (transitief); elke component is een deelgroep die
    dezelfde boeking kán zijn."""
    kenmerken = [kenmerk_van(r.omschrijving) for r in rijen]
    ouder = list(range(len(rijen)))

    def wortel(i: int) -> int:
        while ouder[i] != i:
            ouder[i] = ouder[ouder[i]]
            i = ouder[i]
        return i

    for i in range(len(rijen)):
        for j in range(i + 1, len(rijen)):
            if not kenmerken[i].conflicteert_met(kenmerken[j]):
                ouder[wortel(i)] = wortel(j)
    per_wortel: dict[int, list[Rij]] = {}
    for i, r in enumerate(rijen):
        per_wortel.setdefault(wortel(i), []).append(r)
    return [sorted(c, key=lambda r: r.sleutel) for c in sorted(per_wortel.values(), key=lambda c: c[0].sleutel)]


def beoordeel_dubbelen(
    rijen: Sequence[Rij], *, bank: Sequence[BankMutatie] | None, bank_reeksen: Iterable[str] = ()
) -> dict[str, list[Rij]]:
    """(b1)+(b2) over de ruwe dubbelen-rijen: per groep kenmerk-componenten → losse exemplaren = verschillend
    kenmerk; componenten ≥ 2 → bankdekking: bank-direct of evenveel/meer bankmutaties = `bank_bevestigd`, anders
    `dubbelen` mét "n boekingen, k bankmutaties"; bank niet gelezen (`bank=None`) = alles gemeld mét markering."""
    reeksen = set(bank_reeksen)
    uit: dict[str, list[Rij]] = {"dubbelen": [], "zelfde_bedrag_verschillend_kenmerk": [], "bank_bevestigd": []}
    per_groep: dict[str, list[Rij]] = {}
    for r in rijen:
        per_groep.setdefault(str(r.extra.get("groep")), []).append(r)
    for groep, leden in sorted(per_groep.items()):
        alle_boekstukken = sorted(r.boekstuk or r.rlz_id or "?" for r in leden)
        componenten = _componenten(leden)
        for volgnr, component in enumerate(componenten):
            if len(component) < 2:
                (r,) = component
                anderen = [b for b in alle_boekstukken if b != (r.boekstuk or r.rlz_id)]
                uit["zelfde_bedrag_verschillend_kenmerk"].append(
                    replace(
                        r,
                        categorie="zelfde_bedrag_verschillend_kenmerk",
                        bevinding=(
                            f"zelfde bedrag als {', '.join(anderen)} op {r.datum.isoformat() if r.datum else '?'}, "
                            "verschillend kenmerk "
                            f"({_kenmerk_tekst(kenmerk_van(r.omschrijving))}) — waarschijnlijk echt"
                        ),
                        extra={**r.extra, "kenmerk": _kenmerk_tekst(kenmerk_van(r.omschrijving))},
                    )
                )
                continue
            sub_groep = groep if len(componenten) == 1 else f"{groep}#{volgnr + 1}"
            boekstukken = sorted(r.boekstuk or r.rlz_id or "?" for r in component)
            bank_direct = all(
                bankdekking.is_bank_direct(r.collectie, r.boekstuk, None, bank_reeksen=reeksen) for r in component
            )
            if bank_direct:
                # Per definitie bank-bevestigd: het document IS een bankmutatie-boeking (ook zonder gelezen bank).
                reeks_tekst = "/".join(sorted({bankdekking.reeks_van(r.boekstuk) or r.collectie for r in component}))
                dekking = Dekking(
                    boekingen=len(component),
                    bankmutaties=len(component),
                    bank_bevestigd=True,
                    bank_gelezen=bank is not None,
                    detail=f"bank-directe boekingen (reeks {reeks_tekst})",
                )
            else:
                dekking = bankdekking.dekking_voor(
                    [(r.bedrag, r.datum, bankdekking.teken_van(r.collectie, r.bedrag)) for r in component],  # type: ignore[misc]
                    bank,
                    venster_dagen=BANK_VENSTER_DAGEN,
                )
            kop = f"{len(component)}× € {component[0].bedrag} op {component[0].datum}: {', '.join(boekstukken)}"
            for r in component:
                concept = " (concept)" if r.status == STATUS_CONCEPT else ""
                extra = {
                    **r.extra,
                    "groep": sub_groep,
                    "groep_grootte": len(component),
                    "bank_boekingen": dekking.boekingen,
                    "bank_mutaties": dekking.bankmutaties,
                    "bank_gelezen": dekking.bank_gelezen,
                    "bank_direct": bank_direct,
                }
                if dekking.bank_bevestigd:
                    uit["bank_bevestigd"].append(
                        replace(
                            r,
                            categorie="bank_bevestigd",
                            bevinding=f"{kop}{concept} — bank-bevestigd: {dekking.detail}",
                            extra=extra,
                        )
                    )
                else:
                    staart = "BANK NIET GELEZEN — niet gefilterd" if not dekking.bank_gelezen else dekking.detail
                    uit["dubbelen"].append(
                        replace(r, categorie="dubbelen", bevinding=f"{kop}{concept} — {staart}", extra=extra)
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
                omschrijving=ontknip(r.get("Reference")),
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
    """Alles lezen, niets schrijven. Eén weigerende route = één regel onder Fouten; de andere categorieën gaan door.
    Volgorde: documenten → bank (nodig voor hulzen, reeksafleiding en dekking) → hulzen → kopieën → concepten (rest)
    → dubbelen (kenmerk + bank) → rekeningen → bijlagen."""
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

    bank_rijen: list[dict[str, Any]] | None = None
    bank = lees_collectie(client, "PaymentTransactions", expand="PaymentAccount")
    if _registreer(lijst, bank):
        bank_rijen = bank.rijen
        lijst.rijen["open_bankregels"].extend(open_bankregels(bank_rijen))
    mutaties: list[BankMutatie] | None = (
        bankdekking.bankmutaties_uit_rijen(bank_rijen) if bank_rijen is not None else None
    )
    lijst.bank_gelezen = mutaties is not None
    lijst.bank_mutaties = len(mutaties or [])
    lijst.bank_reeksen = bankdekking.leid_bank_reeksen_af(documenten, mutaties)

    open_bank = [r for r in (bank_rijen or []) if (als_bedrag(r.get("OpenAmount")) or Decimal(0)) != 0]
    hulzen = systeemhulzen_open_bank(documenten, open_bank)
    lijst.rijen["systeemhulzen_open_bank"].extend(hulzen)
    afgevangen = {r.rlz_id for r in hulzen if r.rlz_id}
    kopieen = concept_kopieen(documenten, uitsluiten=afgevangen, bank=mutaties)
    for rij in kopieen:
        lijst.rijen[rij.categorie].append(rij)
    afgevangen |= {r.rlz_id for r in kopieen if r.rlz_id}

    ruwe_dubbelen: list[Rij] = []
    for pad, rijen in documenten.items():
        lijst.rijen["concepten"].extend(concepten(pad, rijen, uitsluiten=afgevangen))
        ruwe_dubbelen.extend(dubbelen(pad, rijen, uitsluiten=afgevangen))
    for categorie, rijen_uit in beoordeel_dubbelen(
        ruwe_dubbelen, bank=mutaties, bank_reeksen=lijst.bank_reeksen
    ).items():
        lijst.rijen[categorie].extend(rijen_uit)

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


def _tabel(rijen: Sequence[Rij]) -> list[str]:
    regels = ["| Boekstuk | Datum | Bedrag | Entity | Omschrijving | Bevinding |", "|---|---|---|---|---|---|"]
    for r in rijen:
        regels.append(
            f"| {_md(r.boekstuk)} | {_md(r.datum.isoformat() if r.datum else None)} | {_bedrag_md(r.bedrag)} | "
            f"{_md(r.entity)} | {_md(r.omschrijving)} | {_md(r.bevinding)} |"
        )
    return regels


def als_markdown(lijst: Schoonlijst, *, administratie_naam: str | None = None) -> str:
    """BESLISSINGEN-vorm: tellers bovenaan (gevonden náást verwacht door Peter), bank-kop, per categorie een kop +
    tabel; lees-hulp-categorieën (`INGEKLAPT`) als `<details>` met een lege regel om de markdown erin."""
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
    if lijst.bank_gelezen:
        reeksen = ", ".join(f"{r} ({k}/{n})" for r, (n, k) in sorted(lijst.bank_reeksen.items())) or "geen afgeleid"
        regels.append(
            f"Bank leidend: {lijst.bank_mutaties} bankmutaties gelezen; bank-directe reeksen (documenten zonder "
            f"relatie die 1-op-1 op bankmutaties vallen): {reeksen}. Dubbelen alleen gemeld bij minder bankmutaties "
            "dan boekingen."
        )
    else:
        regels.append(
            "**BANK NIET GELEZEN** — PaymentTransactions weigerde: systeemhulzen niet herkenbaar, dubbelen NIET "
            "gefilterd op bankdekking (alle groepen gemeld, gemarkeerd)."
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
        if sleutel in INGEKLAPT:
            regels.append(f"<details><summary>{titel} — {tellers[sleutel]}</summary>")
            regels.append("")
            regels.extend(_tabel(rijen) if rijen else ["_geen_"])
            regels.append("")
            regels.append("</details>")
            continue
        regels.append(f"#### {titel} — {tellers[sleutel]}")
        regels.append("")
        regels.extend(_tabel(rijen) if rijen else ["_geen_"])
    return "\n".join(regels) + "\n"
