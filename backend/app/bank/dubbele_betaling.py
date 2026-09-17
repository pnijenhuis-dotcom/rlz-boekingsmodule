"""Dubbele betaling signaleren — HERDEFINITIE 17-09 (SPOED, melding Peter: 1.214 valse bevindingen in één nacht).

Casus 16-09 (Kempen Facilities → Hello Kitchen Duiven): € 12.600,00 én € 16.250,00 elk tweemaal betaald omdat twee facturen
dubbel geboekt stonden (Zenvoices + module) — de tweede factuur was daarna in RLZ verwijderd. De regel van 16-09 ("twee gelijke
bedragen aan dezelfde IBAN ≤ 60 d") liep over 400 dagen historie van álle administraties en zag élke maandelijkse betaling
(Google Cloud, Insify, Greenchoice, Ziton, het eigen kantoor) als dubbel: de periodiek-uitsluiting steunde op
`classificeer_reeks`, die twee gelijke facturen ≤ 30 d per definitie BATCH noemt (Lusso-regel) en pas bij ≥ 3 facturen mét
maand-/kwartaalpatroon PERIODIEK zegt — de meeste periodieke reeksen kwamen daar nooit doorheen.

**Nieuwe definitie: dubbel betaald = méér betaald dan er aan facturen tegenover staat.** Pure, deterministische motor over de
eigen caches — géén RLZ-call, géén AI. Per crediteur-identiteit (tegenrekening-IBAN), venster `venster_dagen` (60):
  1. Kandidaat = ≥ 2 UITGAANDE mutaties, zelfde tegenrekening-IBAN, cent-exact gelijk, ≤ 60 d uit elkaar.
  2. Uitsluiting PERIODIEK: (a) de reeks van álle mutaties met die IBAN + bedrag heeft een week-/twee-weken-/maand-/kwartaal-/
     jaarpatroon (≥ 3 betalingen, élke tussenpoos ±35 % van het nominale interval — `is_periodieke_reeks`) óf
     `classificeer_reeks` zegt PERIODIEK; (b) de IBAN is een BEKENDE periodieke tegenpartij (`periodieke_ibans`: incasso-
     detectie op de facturen van de leverancier — `boekvoorstel.betaalstatus` "wordt automatisch geïncasseerd" — en het
     terugkerend-signaal `terugkerend_signaal`). Periodiek = nooit een bevinding.
  3. FACTUURTOETS (de kern): tel de facturen van die crediteur mét hetzelfde bedrag in het venster ± `FACTUUR_VENSTER_DAGEN`
     (30) rond de betalingen — module-documenten (boekvoorstel op álle crediteurrecords met die IBAN, niet-afgevoerd), RLZ-
     open-postencache (`payment_item_cache` op de entity's uit het IBAN-geheugen, óók al betaald/verdwenen) en de documenten
     waaraan de mutaties zelf in RLZ hangen (`rlz_koppelingen`, hulzen tellen niet) — gededupliceerd op RLZ-document-id /
     genormaliseerde referentie. Aantal betalingen > aantal facturen → bevinding; anders niets.
     Casus Hello Kitchen: 2 betalingen, 1 factuur (de tweede was verwijderd) → bevinding. Google Cloud: 2 betalingen,
     2 facturen → niets. Zonder factuurbron (`factuurtoets` = None) is er geen uitspraak → geen bevinding, wél geteld.
  4. Aflettering telt mee: elke betaling tegen een EIGEN document in RLZ = nooit dubbel; één betaling die niet aan een
     document hangt terwijl de andere wél (post al dicht) = STERK signaal (`sterk`).
  5. De bevinding draagt de handeling: "Factuur ontbreekt (verwijderd/nooit geboekt) — terugvorderen of factuur alsnog
     boeken" mét de bankregels én de gevonden facturen; acceptatie = "bewust (deelbetaling/creditnota)".
Signaleren, nooit handelen: een mens beoordeelt — de bevinding is oranje, nooit blokkerend. Bevindingssoort start in stand
`meten` (app/reconciliatie/soort_stand.py) tot de nameting 'm promoveert."""

from __future__ import annotations

import uuid
from collections import defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

VENSTER_DAGEN_DEFAULT = 60
#: Factuurtoets: facturen van de crediteur mét hetzelfde bedrag binnen ± zoveel dagen rond de betalingen tellen mee.
FACTUUR_VENSTER_DAGEN = 30
#: Leeshorizon van de per-administratie-variant (zelfde 400 dagen als de rlz_dubbel-toets).
LEESHORIZON_DAGEN = 400
#: Periodiek patroon: ≥ 3 betalingen, élke tussenpoos binnen ±35 % van één nominaal interval (dagen).
PERIODIEK_MIN_BETALINGEN = 3
PERIODIEK_TOLERANTIE = 0.35
PERIODIEKE_INTERVALLEN: tuple[tuple[str, float], ...] = (
    ("week", 7.0),
    ("twee weken", 14.0),
    ("maand", 30.44),
    ("kwartaal", 91.3),
    ("jaar", 365.25),
)
#: `boekvoorstel.betaalstatus`-waarde van RLZ's QuickPaymentSelection "Wordt automatisch geïncasseerd" (blok 3 bundel 08-09).
BETAALSTATUS_INCASSO = "Wordt automatisch geïncasseerd"  # app/documenten/betaalstatus.AUTOMATISCH_GEINCASSEERD
#: RLZ-systeemhulzen (bank-plumbing) — een koppeling dáárnaar zegt niets over "welke factuur".
_SYSTEEMHULS_DOCUMENT_TYPE = 19

_CENT = Decimal("0.01")
_TELWOORDEN = {2: "twee", 3: "drie", 4: "vier", 5: "vijf", 6: "zes", 7: "zeven", 8: "acht", 9: "negen", 10: "tien"}


@dataclass(frozen=True)
class Factuur:
    """Eén gevonden factuur van de crediteur mét het betaalde bedrag (voor de bevinding: wat er wél tegenover staat)."""

    bron: str  # module | rlz_open_post | rlz_koppeling
    referentie: str | None
    datum: date | None
    rlz_document_id: str | None = None
    document_id: str | None = None
    boekstuk: str | None = None


@dataclass(frozen=True)
class FactuurToets:
    """Uitkomst van de factuurtoets voor één cluster: welke facturen gevonden zijn (gededupliceerd) en uit welke bronnen."""

    facturen: tuple[Factuur, ...]
    bronnen: tuple[str, ...]  # geraadpleegde bronnen (ook als leeg): module, rlz_open_post, rlz_koppeling

    @property
    def aantal(self) -> int:
        return len(self.facturen)


@dataclass(frozen=True)
class DubbeleBetaling:
    """Eén vermoeden: dezelfde tegenrekening, hetzelfde bedrag, `datums` chronologisch (== volgorde `mutatie_ids`).
    Sinds 17-09 mét de factuurtoets erbij: `facturen` = wat er wél tegenover staat (minder dan `aantal` betalingen),
    `sterk` = één betaling hangt in RLZ aan geen enkel document terwijl een andere wél (post was al dicht)."""

    mutatie_ids: tuple[uuid.UUID, ...]
    tegenrekening_iban: str
    tegenpartij_naam: str | None
    bedrag: Decimal  # positief, cent-exact
    datums: tuple[date, ...]
    facturen: tuple[Factuur, ...] = ()
    factuur_bronnen: tuple[str, ...] = ()
    sterk: bool = False
    #: Bank-toets (regel Peter "bank is leidend", 17-09): de bevinding komt uit de bankregels zelf.
    bank_toets: str = "bevestigd"

    @property
    def jongste_mutatie_id(self) -> uuid.UUID:
        return self.mutatie_ids[-1]

    @property
    def aantal(self) -> int:
        return len(self.mutatie_ids)


@dataclass(frozen=True)
class DubbeleBetalingAnalyse:
    signalen: tuple[DubbeleBetaling, ...]
    #: Aantal sleutels (IBAN + bedrag) mét ≥ 2 uitgaande mutaties die getoetst zijn — de teller voor de reconciliatie.
    sleutels_getoetst: int
    #: Tellers van de uitsluitingen (rapport/systeemmail): waarom een kandidaat géén bevinding werd.
    periodiek_uitgesloten: int = 0
    facturen_dekken: int = 0
    afgeletterd_verschillend: int = 0
    zonder_factuurbron: int = 0


def euro_nl(bedrag: Decimal) -> str:
    """Decimal → '€ 12.600,00' (NL-notatie, altijd twee decimalen)."""
    q = abs(Decimal(bedrag)).quantize(_CENT)
    geheel, cent = f"{q:.2f}".split(".")
    groepen = []
    while len(geheel) > 3:
        groepen.insert(0, geheel[-3:])
        geheel = geheel[:-3]
    groepen.insert(0, geheel)
    return f"€ {'.'.join(groepen)},{cent}"


def _dd_mm(d: date) -> str:
    return d.strftime("%d-%m")


def _opsomming(delen: list[str]) -> str:
    if len(delen) <= 1:
        return "".join(delen)
    return ", ".join(delen[:-1]) + " en " + delen[-1]


def tekst_uit_delen(
    naam: str | None,
    bedrag: Decimal,
    datums: Iterable[date],
    *,
    iban: str | None = None,
    aantal_facturen: int | None = None,
    sterk: bool = False,
) -> str:
    """De ene zin voor bevinding, chip-tooltip en mail — mensentaal, geen id's.
    "Aan Hello Kitchen Duiven is € 12.600,00 twee keer betaald (18-08 en 03-09), terwijl er één factuur van dat bedrag
    tegenover staat — de tweede betaling hangt in Reeleezee aan geen factuur." Zonder factuurtelling (oude bevindingen)
    de zin van 16-09."""
    datums = sorted(datums)
    n = len(datums)
    keer = f"{_TELWOORDEN.get(n, str(n))} keer"
    wie = naam or (f"tegenrekening …{iban[-4:]}" if iban and len(iban) >= 4 else "dezelfde tegenrekening")
    wanneer = _opsomming([_dd_mm(d) for d in datums])
    if aantal_facturen is None:
        return (
            f"Aan {wie} is {euro_nl(bedrag)} {keer} betaald ({wanneer}) "
            "voor wat één factuur lijkt — controleer of terugvordering nodig is."
        )
    if aantal_facturen == 0:
        tegenover = "terwijl er geen factuur van dat bedrag tegenover staat"
    elif aantal_facturen == 1:
        tegenover = "terwijl er één factuur van dat bedrag tegenover staat"
    else:
        tegenover = f"terwijl er {_TELWOORDEN.get(aantal_facturen, str(aantal_facturen))} facturen van dat bedrag tegenover staan"
    slot = " — een van de betalingen hangt in Reeleezee aan geen factuur." if sterk else "."
    return f"Aan {wie} is {euro_nl(bedrag)} {keer} betaald ({wanneer}), {tegenover}{slot}"


def tekst(d: DubbeleBetaling) -> str:
    return tekst_uit_delen(
        d.tegenpartij_naam,
        d.bedrag,
        d.datums,
        iban=d.tegenrekening_iban,
        aantal_facturen=len(d.facturen) if d.factuur_bronnen else None,
        sterk=d.sterk,
    )


def is_periodieke_reeks(datums: Iterable[date]) -> tuple[bool, str | None]:
    """≥ PERIODIEK_MIN_BETALINGEN betalingen waarvan élke tussenpoos binnen ±PERIODIEK_TOLERANTIE van één nominaal interval
    (week … jaar) ligt → (True, "maand"). Dubbele datums (0 d) breken het patroon (dat is juist de dubbel-kandidaat)."""
    ds = sorted(datums)
    if len(ds) < PERIODIEK_MIN_BETALINGEN:
        return False, None
    gaten = [(b - a).days for a, b in zip(ds, ds[1:], strict=False)]
    if min(gaten) <= 0:
        return False, None
    for naam, nominaal in PERIODIEKE_INTERVALLEN:
        onder, boven = nominaal * (1 - PERIODIEK_TOLERANTIE), nominaal * (1 + PERIODIEK_TOLERANTIE)
        if all(onder <= g <= boven for g in gaten):
            return True, naam
    return False, None


# -- motor -------------------------------------------------------------------------------------------------------------


def _bedrag(m: Any) -> Decimal | None:
    b = getattr(m, "bedrag", None)
    if b is None:
        return None
    try:
        return Decimal(str(b)).quantize(_CENT)
    except Exception:  # noqa: BLE001 — een onleesbaar bedrag is geen kandidaat
        return None


def _referenties(m: Any) -> set[str]:
    """Genormaliseerde referenties van de ECHTE documenten waaraan de mutatie in RLZ hangt (hulzen tellen niet)."""
    from app.documenten.duplicaat_afvoer import normaliseer_referentie

    uit: set[str] = set()
    for k in getattr(m, "rlz_koppelingen", None) or []:
        if not isinstance(k, Mapping):
            continue
        if k.get("document_type") == _SYSTEEMHULS_DOCUMENT_TYPE:
            continue
        ref = normaliseer_referentie(k.get("referentie"))
        if ref:
            uit.add(ref)
    return uit


def _wijzen_naar_verschillende_facturen(cluster: list[Any]) -> bool:
    """Elke mutatie hangt aan minstens één echt document én geen referentie komt bij twee mutaties voor."""
    gezien: set[str] = set()
    for m in cluster:
        refs = _referenties(m)
        if not refs or refs & gezien:
            return False
        gezien |= refs
    return True


def _clusters_binnen_venster(gesorteerd: list[Any], venster_dagen: int) -> list[list[Any]]:
    """Ketens van opeenvolgende mutaties waarin élke volgende binnen `venster_dagen` van de vorige valt."""
    clusters: list[list[Any]] = []
    huidig: list[Any] = []
    for m in gesorteerd:
        if huidig and (m.boekdatum - huidig[-1].boekdatum).days > venster_dagen:
            clusters.append(huidig)
            huidig = []
        huidig.append(m)
    if huidig:
        clusters.append(huidig)
    return [c for c in clusters if len(c) >= 2]


def _koppeling_facturen(cluster: list[Any]) -> list[Factuur]:
    """Echte RLZ-documenten waaraan de mutaties hangen (hulzen tellen niet) — bron `rlz_koppeling`."""
    uit: list[Factuur] = []
    for m in cluster:
        for k in getattr(m, "rlz_koppelingen", None) or []:
            if not isinstance(k, Mapping) or k.get("document_type") == _SYSTEEMHULS_DOCUMENT_TYPE:
                continue
            uit.append(
                Factuur(
                    bron="rlz_koppeling",
                    referentie=str(k.get("referentie")) if k.get("referentie") else None,
                    datum=None,
                    rlz_document_id=str(k.get("document_id")) if k.get("document_id") else None,
                    boekstuk=str(k.get("boekstuk")) if k.get("boekstuk") else None,
                )
            )
    return uit


def dedupliceer_facturen(facturen: Iterable[Factuur]) -> tuple[Factuur, ...]:
    """Eén factuur kan uit drie bronnen komen: module-document, RLZ-open-post en RLZ-koppeling — sleutel = RLZ-document-id,
    anders genormaliseerde referentie, anders document-id. Zonder enige sleutel telt de factuur op zichzelf."""
    from app.documenten.duplicaat_afvoer import normaliseer_referentie

    gezien: set[str] = set()
    uit: list[Factuur] = []
    for f in facturen:
        sleutels = []
        if f.rlz_document_id:
            sleutels.append(f"rlz:{f.rlz_document_id}")
        ref = normaliseer_referentie(f.referentie)
        if ref:
            sleutels.append(f"ref:{ref}")
        if f.document_id:
            sleutels.append(f"doc:{f.document_id}")
        if sleutels and any(s in gezien for s in sleutels):
            gezien.update(sleutels)
            continue
        gezien.update(sleutels)
        uit.append(f)
    return tuple(uit)


def _onafgeletterd_naast_afgeletterd(cluster: list[Any]) -> bool:
    """Sterk signaal: minstens één mutatie hangt aan geen enkel echt document terwijl een andere wél (post al dicht)."""
    met = [bool(_referenties(m) or _koppeling_facturen([m])) for m in cluster]
    return any(met) and not all(met)


def analyseer_dubbele_betalingen(
    mutaties: Iterable[Any],
    *,
    venster_dagen: int = VENSTER_DAGEN_DEFAULT,
    facturen_per_sleutel: Mapping[tuple[str, Decimal], int] | None = None,
    periodieke_ibans: Iterable[str] = (),
    factuurtoets: Callable[[str, Decimal, tuple[date, ...]], FactuurToets | None] | None = None,
) -> DubbeleBetalingAnalyse:
    """Pure motor over `BankMutatie`-achtige records (duck-typed: id, boekdatum, bedrag, tegenrekening_iban,
    tegenpartij_naam, omschrijving, rlz_koppelingen). Zie de module-docstring voor de regel (herdefinitie 17-09).
    `factuurtoets(iban, bedrag, datums)` levert de facturen van de crediteur mét dat bedrag in het venster; None = geen
    bron beschikbaar → geen uitspraak. `facturen_per_sleutel` (16-09) blijft als eenvoudige teller-variant werken."""
    from app.bank.matchmotor import normaliseer_iban
    from app.terugkerend.service import ReeksClassificatie, classificeer_reeks

    periodiek_bekend = {x for x in (normaliseer_iban(i) for i in periodieke_ibans) if x}
    per_sleutel: dict[tuple[str, Decimal], list[Any]] = defaultdict(list)
    for m in mutaties:
        bedrag = _bedrag(m)
        if bedrag is None or bedrag >= 0 or getattr(m, "boekdatum", None) is None:
            continue
        iban = normaliseer_iban(getattr(m, "tegenrekening_iban", None))
        if not iban:
            continue
        per_sleutel[(iban, abs(bedrag))].append(m)

    signalen: list[DubbeleBetaling] = []
    sleutels_getoetst = 0
    periodiek_uitgesloten = facturen_dekken = afgeletterd_verschillend = zonder_factuurbron = 0
    for (iban, bedrag), groep in sorted(per_sleutel.items(), key=lambda kv: (kv[0][0], kv[0][1])):
        if len(groep) < 2:
            continue
        sleutels_getoetst += 1
        gesorteerd = sorted(groep, key=lambda m: (m.boekdatum, str(m.id)))
        clusters = _clusters_binnen_venster(gesorteerd, venster_dagen)
        if not clusters:
            continue
        # 2. periodiek: bekende periodieke tegenpartij, week-…-jaarpatroon over de reeks, of de Lusso-motor zegt PERIODIEK.
        datums_reeks = [m.boekdatum for m in gesorteerd]
        if (
            iban in periodiek_bekend
            or is_periodieke_reeks(datums_reeks)[0]
            or classificeer_reeks(datums_reeks).classificatie is ReeksClassificatie.PERIODIEK
        ):
            periodiek_uitgesloten += 1
            continue
        # (c, 16-09) de aanroeper kent evenveel (of meer) identieke facturen als betalingen.
        if facturen_per_sleutel is not None and facturen_per_sleutel.get((iban, bedrag), 0) >= len(gesorteerd):
            facturen_dekken += 1
            continue
        for cluster in clusters:
            # 4. aantoonbaar élke betaling aan een eigen factuur in RLZ = geen signaal.
            if _wijzen_naar_verschillende_facturen(cluster):
                afgeletterd_verschillend += 1
                continue
            # 3. factuurtoets: betalingen > facturen?
            datums = tuple(m.boekdatum for m in cluster)
            toets = factuurtoets(iban, bedrag, datums) if factuurtoets is not None else None
            if toets is None:
                if factuurtoets is not None:
                    # Een factuurbron is er wél, maar kent deze crediteur niet → geen uitspraak (geteld, geen bevinding).
                    zonder_factuurbron += 1
                    continue
                # Pure motor zonder factuurbron (16-09-gedrag, gouden set): alleen de RLZ-koppelingen tellen als facturen.
                toets = FactuurToets(facturen=(), bronnen=("rlz_koppeling",))
            alle = dedupliceer_facturen((*toets.facturen, *_koppeling_facturen(cluster)))
            if len(alle) >= len(cluster):
                facturen_dekken += 1
                continue
            naam = next((m.tegenpartij_naam for m in reversed(cluster) if getattr(m, "tegenpartij_naam", None)), None)
            signalen.append(
                DubbeleBetaling(
                    mutatie_ids=tuple(m.id for m in cluster),
                    tegenrekening_iban=iban,
                    tegenpartij_naam=naam,
                    bedrag=bedrag,
                    datums=datums,
                    facturen=alle,
                    factuur_bronnen=tuple(sorted(set(toets.bronnen) | {"rlz_koppeling"})),
                    sterk=_onafgeletterd_naast_afgeletterd(cluster),
                )
            )
    return DubbeleBetalingAnalyse(
        signalen=tuple(signalen),
        sleutels_getoetst=sleutels_getoetst,
        periodiek_uitgesloten=periodiek_uitgesloten,
        facturen_dekken=facturen_dekken,
        afgeletterd_verschillend=afgeletterd_verschillend,
        zonder_factuurbron=zonder_factuurbron,
    )


def vind_dubbele_betalingen(
    mutaties: Iterable[Any],
    *,
    venster_dagen: int = VENSTER_DAGEN_DEFAULT,
    facturen_per_sleutel: Mapping[tuple[str, Decimal], int] | None = None,
    periodieke_ibans: Iterable[str] = (),
    factuurtoets: Callable[[str, Decimal, tuple[date, ...]], FactuurToets | None] | None = None,
) -> list[DubbeleBetaling]:
    return list(
        analyseer_dubbele_betalingen(
            mutaties,
            venster_dagen=venster_dagen,
            facturen_per_sleutel=facturen_per_sleutel,
            periodieke_ibans=periodieke_ibans,
            factuurtoets=factuurtoets,
        ).signalen
    )


# -- per administratie (één query, eigen DB) ---------------------------------------------------------------------------


def _isodatum(x: Any) -> date | None:
    if x is None:
        return None
    if isinstance(x, date):
        return x
    try:
        return date.fromisoformat(str(x)[:10])
    except ValueError:
        return None


def factuurbronnen_voor_administratie(administratie_id: uuid.UUID, *, session: Any) -> tuple[set[str], Callable]:
    """Set-based lezen van de factuurbronnen van één administratie (eigen caches, geen RLZ-call):
    IBAN → crediteurrecords (`leverancier_iban`), IBAN → RLZ-entity's (`bank_relatie_iban`), module-documenten
    (`boekvoorstel` × `document`, niet-afgevoerd) en RLZ-open-posten (`payment_item_cache`, óók verdwenen = betaald).
    → (periodieke IBANs, factuurtoets-closure)."""
    from sqlalchemy import select

    from app.bank.matchmotor import normaliseer_iban
    from app.bank.models import BankRelatieIban, PaymentItemCache
    from app.documenten.models import Boekvoorstel, Document, DocumentStatus, LeverancierIban
    from app.terugkerend.models import TerugkerendSignaal
    from app.tijd import vandaag_nl

    vanaf = vandaag_nl() - timedelta(days=LEESHORIZON_DAGEN + FACTUUR_VENSTER_DAGEN)
    vendor_ibans: dict[uuid.UUID, set[str]] = defaultdict(set)
    iban_vendors: dict[str, set[uuid.UUID]] = defaultdict(set)
    for vendor_id, iban in session.execute(
        select(LeverancierIban.vendor_id, LeverancierIban.iban).where(LeverancierIban.administratie_id == administratie_id)
    ):
        n = normaliseer_iban(iban)
        if n:
            vendor_ibans[vendor_id].add(n)
            iban_vendors[n].add(vendor_id)
    iban_entities: dict[str, set[uuid.UUID]] = defaultdict(set)
    for iban, entity_guid in session.execute(
        select(BankRelatieIban.iban, BankRelatieIban.entity_guid).where(BankRelatieIban.administratie_id == administratie_id)
    ):
        n = normaliseer_iban(iban)
        if n and entity_guid is not None:
            iban_entities[n].add(entity_guid)

    # Bekende periodieke tegenpartijen: incasso-detectie op de facturen + het terugkerend-signaal (per crediteur → IBAN).
    periodieke_ibans: set[str] = set()
    incasso_vendors = set(
        session.scalars(
            select(Boekvoorstel.vendor_id)
            .join(Document, Document.id == Boekvoorstel.document_id)
            .where(
                Document.administratie_id == administratie_id,
                Boekvoorstel.vendor_id.is_not(None),
                Boekvoorstel.betaalstatus == BETAALSTATUS_INCASSO,
            )
        )
    )
    terugkerend_vendors = set(
        session.scalars(select(TerugkerendSignaal.vendor_id).where(TerugkerendSignaal.administratie_id == administratie_id))
    )
    for v in incasso_vendors | terugkerend_vendors:
        periodieke_ibans |= vendor_ibans.get(v, set())

    niet_factuur = {
        DocumentStatus.VERWIJDERD,
        DocumentStatus.AFGEWEZEN,
        DocumentStatus.SAMENGEVOEGD,
        DocumentStatus.AFGEVOERD_DUPLICAAT,
        DocumentStatus.GESPLITST,
    }
    module_per_sleutel: dict[tuple[uuid.UUID, Decimal], list[Factuur]] = defaultdict(list)
    for doc_id, vendor_id, totaal, factuurdatum, referentie, status in session.execute(
        select(
            Boekvoorstel.document_id,
            Boekvoorstel.vendor_id,
            Boekvoorstel.totaalbedrag,
            Boekvoorstel.factuurdatum,
            Boekvoorstel.referentie,
            Document.status,
        )
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(
            Document.administratie_id == administratie_id,
            Boekvoorstel.vendor_id.is_not(None),
            Boekvoorstel.totaalbedrag.is_not(None),
        )
    ):
        if status in niet_factuur or totaal is None:
            continue
        if factuurdatum is not None and factuurdatum < vanaf:
            continue
        module_per_sleutel[(vendor_id, abs(Decimal(str(totaal)).quantize(_CENT)))].append(
            Factuur(bron="module", referentie=referentie, datum=factuurdatum, document_id=str(doc_id))
        )
    post_per_sleutel: dict[tuple[uuid.UUID, Decimal], list[Factuur]] = defaultdict(list)
    for entity_guid, bedrag, boekdatum, referentie, referentie2, rlz_document_id, brondata in session.execute(
        select(
            PaymentItemCache.entity_guid,
            PaymentItemCache.bedrag,
            PaymentItemCache.boekdatum,
            PaymentItemCache.referentie,
            PaymentItemCache.referentie2,
            PaymentItemCache.rlz_document_id,
            PaymentItemCache.brondata,
        ).where(PaymentItemCache.administratie_id == administratie_id, PaymentItemCache.entity_guid.is_not(None))
    ):
        if bedrag is None:
            continue
        doc = (brondata or {}).get("Document") if isinstance(brondata, Mapping) else None
        # Alleen INKOOP-posten (DocumentType 1) of onbekend — een verkoopfactuur van dezelfde relatie telt niet.
        if isinstance(doc, Mapping) and doc.get("DocumentType") not in (None, 1):
            continue
        factuurdatum = _isodatum(doc.get("Date")) if isinstance(doc, Mapping) else None
        datum = factuurdatum or boekdatum
        if datum is not None and datum < vanaf:
            continue
        post_per_sleutel[(entity_guid, abs(Decimal(str(bedrag)).quantize(_CENT)))].append(
            Factuur(
                bron="rlz_open_post",
                referentie=(doc.get("Reference") if isinstance(doc, Mapping) else None) or referentie,
                datum=datum,
                rlz_document_id=str(rlz_document_id) if rlz_document_id else None,
                boekstuk=referentie2,
            )
        )

    def factuurtoets(iban: str, bedrag: Decimal, datums: tuple[date, ...]) -> FactuurToets | None:
        onder = min(datums) - timedelta(days=FACTUUR_VENSTER_DAGEN)
        boven = max(datums) + timedelta(days=FACTUUR_VENSTER_DAGEN)

        def in_venster(f: Factuur) -> bool:
            return f.datum is None or onder <= f.datum <= boven

        gevonden: list[Factuur] = []
        bronnen: list[str] = []
        vendors = iban_vendors.get(iban, set())
        if vendors:
            bronnen.append("module")
            for v in vendors:
                gevonden.extend(f for f in module_per_sleutel.get((v, bedrag), ()) if in_venster(f))
        entities = iban_entities.get(iban, set())
        if entities:
            bronnen.append("rlz_open_post")
            for e in entities:
                gevonden.extend(f for f in post_per_sleutel.get((e, bedrag), ()) if in_venster(f))
        if not bronnen:
            return None  # crediteur onbekend in beide caches → geen uitspraak (alleen de RLZ-koppelingen blijven)
        return FactuurToets(facturen=dedupliceer_facturen(gevonden), bronnen=tuple(bronnen))

    return periodieke_ibans, factuurtoets


def analyseer_voor_administratie(administratie_id: uuid.UUID, *, session: Any = None) -> DubbeleBetalingAnalyse:
    """Uitgaande, niet-verdwenen mutaties van de laatste `LEESHORIZON_DAGEN` in één set-based query, de factuurbronnen
    (17-09) in drie set-based queries, daarna de pure motor. Zonder `session` opent de functie zelf een
    `scoped_session(administratie_id)`."""
    from sqlalchemy import select

    from app.bank.models import BankMutatie
    from app.db.session import scoped_session
    from app.tijd import vandaag_nl

    vanaf = vandaag_nl() - timedelta(days=LEESHORIZON_DAGEN)
    stmt = select(
        BankMutatie.id,
        BankMutatie.boekdatum,
        BankMutatie.bedrag,
        BankMutatie.tegenrekening_iban,
        BankMutatie.tegenpartij_naam,
        BankMutatie.omschrijving,
        BankMutatie.rlz_koppelingen,
    ).where(
        BankMutatie.administratie_id == administratie_id,
        BankMutatie.bedrag < 0,
        BankMutatie.boekdatum >= vanaf,
        BankMutatie.verdwenen_uit_bron_op.is_(None),
    )

    def _run(s: Any) -> DubbeleBetalingAnalyse:
        rijen = list(s.execute(stmt))
        periodieke_ibans, toets = factuurbronnen_voor_administratie(administratie_id, session=s)
        return analyseer_dubbele_betalingen(rijen, periodieke_ibans=periodieke_ibans, factuurtoets=toets)

    if session is not None:
        return _run(session)
    with scoped_session(administratie_id) as s:
        return _run(s)


def vind_dubbele_betalingen_voor_administratie(
    administratie_id: uuid.UUID, *, session: Any = None
) -> list[DubbeleBetaling]:
    return list(analyseer_voor_administratie(administratie_id, session=session).signalen)
