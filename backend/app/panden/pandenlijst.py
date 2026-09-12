"""Pandenlijst-seam + adres-clustering (run 2 VGG 12-09, blok 3; besluit Peter 12-09 punt 3).

Salesforce levert later de canonieke pandenlijst — een LEES-lijst om afgeleide adressen tegen te matchen, nooit bron van
boeking of pand-aanmaak. Hier de seam `PandenlijstBron` (Protocol) met `CsvPandenlijst` als eerste implementatie; de
Salesforce-adapter is run 3+.

Matchdrempel (gedocumenteerd, één plek: `straat_gelijk`): huisnummer exact + toevoeging verenigbaar (gelijk ná
normalisatie — "70-02" = "70-2" = "2", "34b" = "34B" — óf één van beide leeg) + straatnaam-gelijkenis op de
genormaliseerde naam (diacritics, spaties en leestekens weg, kleine letters): `difflib.SequenceMatcher(...).ratio()
>= 0.85` ("Koekoekstraat"/"Koekoestraat", "Dwarsweg"/"Dwartsweg"), óf de ene naam is een prefix/suffix van de andere met
ten minste 6 tekens ("Kleiweg" ⊂ "Overschiese Kleiweg", "Hanssenlaan" ⊂ "Mgr. Hanssenlaan"). Het contract noemt prefix;
suffix is nodig voor de casus "Overschiese Kleiweg 667" = "Kleiweg 667" (weggevallen voorvoegsel) en staat als afwijking
in het rapport. Meerduidig (twee lijst-panden scoren even goed) = NOOIT binden, apart gemeld.

Zonder lijst: clusteren van de afgeleide adressen op dezelfde drempel (union-find binnen hetzelfde huisnummer); één
cluster = één pand-voorstel, representant = meest voorkomende straatvariant (tie: langste naam), varianten in de reden.
Geen I/O buiten `CsvPandenlijst.panden()`; geen AI."""

from __future__ import annotations

import csv
import re
import unicodedata
from collections import Counter
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from difflib import SequenceMatcher
from pathlib import Path
from typing import Protocol

from app.panden.afleiding import AdresVoorstel

RATIO_DREMPEL = 0.85
PREFIX_MIN_TEKENS = 6


# ---- normalisatie + drempel -------------------------------------------------------------------------


def normaliseer_straat(straat: str) -> str:
    plat = unicodedata.normalize("NFKD", straat).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "", plat)


def normaliseer_toevoeging(toevoeging: str | None) -> str:
    if not toevoeging:
        return ""
    t = re.sub(r"[^a-z0-9]+", "", toevoeging.lower())
    return t.lstrip("0") if t.isdigit() else t


def straat_gelijk(a: str, b: str) -> bool:
    """Dé drempel (zie moduledocstring): ratio ≥ 0,85 óf prefix/suffix met ≥ 6 tekens."""
    na, nb = normaliseer_straat(a), normaliseer_straat(b)
    if not na or not nb:
        return False
    if na == nb:
        return True
    kort, lang = sorted((na, nb), key=len)
    if len(kort) >= PREFIX_MIN_TEKENS and (lang.startswith(kort) or lang.endswith(kort)):
        return True
    return SequenceMatcher(None, na, nb).ratio() >= RATIO_DREMPEL


def straat_score(a: str, b: str) -> float:
    na, nb = normaliseer_straat(a), normaliseer_straat(b)
    if na == nb:
        return 1.0
    return SequenceMatcher(None, na, nb).ratio()


def toevoeging_verenigbaar(a: str | None, b: str | None) -> bool:
    ta, tb = normaliseer_toevoeging(a), normaliseer_toevoeging(b)
    return ta == tb or not ta or not tb


def zelfde_pand(a: AdresVoorstel, b: AdresVoorstel) -> bool:
    return (
        a.huisnummer == b.huisnummer
        and toevoeging_verenigbaar(a.toevoeging, b.toevoeging)
        and straat_gelijk(a.straat, b.straat)
    )


# ---- pandenlijst-seam -------------------------------------------------------------------------------


@dataclass(frozen=True)
class PandenlijstPand:
    straat: str
    huisnummer: str
    toevoeging: str | None = None
    postcode: str | None = None
    plaats: str | None = None
    salesforce_id: str | None = None

    @property
    def code(self) -> str:
        """Lijst-code = pand-sleutel in de DB: het Salesforce-id als dat er is (`sf-<id>`), anders de genormaliseerde
        adres-sleutel (zelfde vorm als `AdresVoorstel.code`)."""
        if self.salesforce_id:
            return f"sf-{re.sub(r'[^a-z0-9]+', '-', self.salesforce_id.lower()).strip('-')}"
        return self.als_adres.code

    @property
    def als_adres(self) -> AdresVoorstel:
        return AdresVoorstel(
            straat=self.straat,
            huisnummer=self.huisnummer,
            toevoeging=self.toevoeging or None,
            postcode=self.postcode or None,
            plaats=self.plaats or None,
        )


class PandenlijstBron(Protocol):
    def panden(self) -> list[PandenlijstPand]: ...


class PandenlijstFout(ValueError):
    """Onleesbare lijst: ontbrekende verplichte kolommen of geen enkele rij."""


_KOLOM_ALIASSEN: dict[str, tuple[str, ...]] = {
    "straat": ("adres", "straat", "straatnaam", "street"),
    "huisnummer": ("huisnummer", "nummer", "huisnr", "number"),
    "toevoeging": ("toevoeging", "huisnummertoevoeging", "toev", "addition"),
    "postcode": ("postcode", "zip", "postal_code"),
    "plaats": ("plaats", "woonplaats", "stad", "city"),
    "salesforce_id": ("salesforce_id", "salesforceid", "sf_id", "sfid", "id"),
}


class CsvPandenlijst:
    """CSV (UTF-8, `;` of `,`) met kolommen adres|straat, huisnummer, [toevoeging], [postcode], [plaats],
    [salesforce_id]; kolomkoppen hoofdletter-ongevoelig. Een rij zonder straat of huisnummer wordt geteld als
    overgeslagen (zichtbaar via `overgeslagen`), nooit stil weggelaten."""

    def __init__(self, pad: str | Path) -> None:
        self.pad = Path(pad)
        self.overgeslagen: list[str] = []

    def panden(self) -> list[PandenlijstPand]:
        tekst = self.pad.read_text(encoding="utf-8-sig")
        eerste = tekst.splitlines()[0] if tekst.strip() else ""
        scheiding = ";" if eerste.count(";") >= eerste.count(",") else ","
        lezer = csv.DictReader(tekst.splitlines(), delimiter=scheiding)
        koppen = [k.strip().lower() for k in (lezer.fieldnames or [])]
        mapping: dict[str, str] = {}
        for veld, aliassen in _KOLOM_ALIASSEN.items():
            for alias in aliassen:
                if alias in koppen:
                    mapping[veld] = (lezer.fieldnames or [])[koppen.index(alias)]
                    break
        if "straat" not in mapping or "huisnummer" not in mapping:
            raise PandenlijstFout(
                f"pandenlijst {self.pad}: kolommen adres/straat en huisnummer verplicht, gevonden: {koppen or 'geen'}"
            )
        uit: list[PandenlijstPand] = []
        for nr, rij in enumerate(lezer, start=2):

            def _v(veld: str, _rij: dict[str, str] = rij) -> str | None:
                kolom = mapping.get(veld)
                w = (_rij.get(kolom) or "").strip() if kolom else ""
                return w or None

            straat, huisnummer = _v("straat"), _v("huisnummer")
            if not straat or not huisnummer:
                self.overgeslagen.append(f"regel {nr}: straat/huisnummer ontbreekt")
                continue
            # "Kerkstraat 44a" in één adres-kolom mét apart huisnummer-veld leeg komt niet voor; toevoeging in het
            # huisnummer-veld ("44a", "70-2") wél → splitsen.
            m = re.match(r"^(\d{1,5})\s*(.*)$", huisnummer)
            if m is None:
                self.overgeslagen.append(f"regel {nr}: huisnummer {huisnummer!r} onleesbaar")
                continue
            toevoeging = _v("toevoeging") or (m.group(2).strip() or None)
            uit.append(
                PandenlijstPand(
                    straat=straat,
                    huisnummer=m.group(1),
                    toevoeging=toevoeging,
                    postcode=(_v("postcode") or "").replace(" ", "").upper() or None,
                    plaats=_v("plaats"),
                    salesforce_id=_v("salesforce_id"),
                )
            )
        if not uit and not self.overgeslagen:
            raise PandenlijstFout(f"pandenlijst {self.pad}: geen rijen")
        return uit


@dataclass(frozen=True)
class LijstMatch:
    pand: PandenlijstPand | None
    kandidaten: tuple[PandenlijstPand, ...]
    meerduidig: bool

    @property
    def gebonden(self) -> bool:
        return self.pand is not None


def zoek_in_lijst(adres: AdresVoorstel, lijst: Sequence[PandenlijstPand]) -> LijstMatch:
    """Bind een afgeleid adres aan precies één lijst-pand. Kandidaten = zelfde huisnummer + verenigbare toevoeging +
    `straat_gelijk`; bij meer kandidaten beslist eerst de plaats (als beide 'm kennen), dan de hoogste straat-score;
    twee kandidaten met dezelfde beste score = meerduidig → niet gebonden."""
    kandidaten = [p for p in lijst if zelfde_pand(adres, p.als_adres)]
    if not kandidaten:
        return LijstMatch(None, (), False)
    if len(kandidaten) > 1 and adres.plaats:
        met_plaats = [
            p for p in kandidaten if p.plaats and normaliseer_straat(p.plaats) == normaliseer_straat(adres.plaats)
        ]
        if met_plaats:
            kandidaten = met_plaats
    if len(kandidaten) > 1:
        exact = [
            p for p in kandidaten if normaliseer_toevoeging(p.toevoeging) == normaliseer_toevoeging(adres.toevoeging)
        ]
        if exact:
            kandidaten = exact
    if len(kandidaten) == 1:
        return LijstMatch(kandidaten[0], tuple(kandidaten), False)
    scores = sorted(((straat_score(adres.straat, p.straat), p) for p in kandidaten), key=lambda x: -x[0])
    if scores[0][0] > scores[1][0]:
        return LijstMatch(scores[0][1], tuple(kandidaten), False)
    return LijstMatch(None, tuple(kandidaten), True)


# ---- clusteren zonder lijst -------------------------------------------------------------------------


@dataclass
class AdresCluster:
    representant: AdresVoorstel
    leden: list[AdresVoorstel]

    @property
    def varianten(self) -> list[str]:
        """Unieke straatvarianten, representant eerst, daarna op voorkomen."""
        uit: list[str] = [self.representant.straat]
        for a in self.leden:
            if a.straat not in uit:
                uit.append(a.straat)
        return uit

    @property
    def codes(self) -> list[str]:
        uit: list[str] = [self.representant.code]
        for a in self.leden:
            if a.code not in uit:
                uit.append(a.code)
        return uit


def cluster_adressen(adressen: Iterable[AdresVoorstel]) -> list[AdresCluster]:
    """Union-find binnen hetzelfde huisnummer op `zelfde_pand`. Representant = meest voorkomende straatvariant
    (tie → langste genormaliseerde naam, dan minste woorden, dan alfabetisch), mét de meest voorkomende toevoeging;
    plaats/postcode = eerste gevulde."""
    lijst = list(adressen)
    ouder = list(range(len(lijst)))

    def vind(i: int) -> int:
        while ouder[i] != i:
            ouder[i] = ouder[ouder[i]]
            i = ouder[i]
        return i

    per_nummer: dict[str, list[int]] = {}
    for i, a in enumerate(lijst):
        per_nummer.setdefault(a.huisnummer, []).append(i)
    for indices in per_nummer.values():
        for x in range(len(indices)):
            for y in range(x + 1, len(indices)):
                i, j = indices[x], indices[y]
                if zelfde_pand(lijst[i], lijst[j]):
                    ri, rj = vind(i), vind(j)
                    if ri != rj:
                        ouder[max(ri, rj)] = min(ri, rj)
    groepen: dict[int, list[AdresVoorstel]] = {}
    for i, a in enumerate(lijst):
        groepen.setdefault(vind(i), []).append(a)
    uit: list[AdresCluster] = []
    for leden in groepen.values():
        straten = Counter(a.straat for a in leden)
        # meest voorkomend → langste genormaliseerde naam (specifiekst: "Overschiese Kleiweg" > "Kleiweg") → minste
        # woorden ("Chevremontstraat" > "C hevremontstraat") → alfabetisch
        straat = sorted(straten, key=lambda s: (-straten[s], -len(normaliseer_straat(s)), len(s.split()), s))[0]
        toevoegingen = Counter(normaliseer_toevoeging(a.toevoeging) for a in leden if a.toevoeging)
        toevoeging = None
        if toevoegingen:
            genorm = sorted(toevoegingen, key=lambda t: (-toevoegingen[t], t))[0]
            toevoeging = next(a.toevoeging for a in leden if normaliseer_toevoeging(a.toevoeging) == genorm)
        plaats = next((a.plaats for a in leden if a.plaats), None)
        postcode = next((a.postcode for a in leden if a.postcode), None)
        representant = AdresVoorstel(
            straat=straat, huisnummer=leden[0].huisnummer, toevoeging=toevoeging, postcode=postcode, plaats=plaats
        )
        uit.append(AdresCluster(representant=representant, leden=leden))
    return sorted(uit, key=lambda c: c.representant.code)
