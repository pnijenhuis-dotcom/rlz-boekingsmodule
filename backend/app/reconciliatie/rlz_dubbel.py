"""Reconciliatie-blok `rlz_dubbel` — periodieke toets "mogelijk dubbel geboekt in RLZ" (blok 6, bundel 08-09;
aanleiding BESLISSINGEN "HERSTELRUN 07-09 — BLOK A" beslispunt 4: in Kempen Facilities stonden twee HANDMATIG
ingevoerde BOOT-facturen (RLZ-04-00004037/38, GUID-versie 4) die de module nooit kon zien — onze duplicaatchecks
kijken alleen naar wat de module zélf boekt).

Wat dit blok doet — en bewust níét:
- Per RLZ-administratie (Odoo-administraties zichtbaar OVERGESLAGEN, `RLZ_ONLY_OVERGESLAGEN`-patroon) worden de
  PurchaseInvoices van de laatste `VENSTER_DAGEN` dagen gelezen in ÉÉN gepagineerde lees-reeks ($top/$skip, zelfde
  vorm als `app/geheugen/seed.py::_facturen` — live bewezen op deze collectie; `$expand=Entity` omdat Entity op de
  collectie alleen mét expand zichtbaar is). Concepten (Status 1) komen mee (STAP-0 07-09) en worden gemarkeerd.
- Binnen dezelfde crediteur (Entity) worden REFERENTIEGROEPEN gevormd op UITSLUITEND gelijke GENORMALISEERDE
  referentie (`duplicaat_afvoer.normaliseer_referentie` — één normalisatie in de hele module). Placeholder-referenties
  ("Ingescand document", alleen nullen, "factuur"/"invoice", zie `PLACEHOLDER_REFERENTIES`) tellen als LEEG en
  matchen nooit. **Herstelrun "Basis eerst" 08-09 (blok 7, besluit Peter 08-09): de vroegere variant (B) "gelijk
  bedrag + gelijke factuurdatum" is VOLLEDIG vervallen** — de Kempen-live-check gaf 516 paren, waarvan 508 op
  bedrag+datum. **Aanvaarde grens:** BOOT 202632703/202632704 (RLZ-04-00004037/38, € 2.976,30 vs € 1.775,98, beide
  22-06-2026) heeft een ándere referentie én een ánder bedrag en wordt bewust NIET gevangen.
- **Blok 1 vervolgrun 10-09 avond (besluit Peter; productie 10-09 06:32 gaf 907 paren over 14 administraties, vrijwel
  allemaal op een referentie die géén factuurnummer is):**
  (1) REFERENTIE-CLASSIFICATIE (`referentie_classificatie.py`, puur): een groep wordt uitgesloten als de referentie
      (a) op een IBAN lijkt (Food service: NL86INGB0662462785 op 4 boekingen = 6 paren), (b) bij dezelfde crediteur
      ≥ 3× voorkomt met ≥ 2 verschillende bedragen (BP Express: klantnummer 0817725528 op 7 bank-directe boekingen =
      21 paren), (c) een placeholder is (blok 7). Tellers per reden per administratie staan in het rapport, de
      CLI-regel en de lees-only-uitvoer.
  (2) ÉÉN BEVINDING PER CLUSTER (crediteur + genormaliseerde referentie, álle exemplaren gesorteerd op datum), niet
      meer per paar. Acceptatie-sleutel = `cluster=<rlz_admin>|<entity>|<genormaliseerde ref>` → vingerafdruk stabiel
      per cluster (`service.vingerafdruk(documenten|dubbel_in_rlz|<sleutel>)`), record_id = UUIDv5 van die sleutel.
      Een cluster waarvan ÁLLE exemplaren van de module zijn telt niet (UUIDv5 uit de eigen DB); één module-exemplaar
      + één handmatig exemplaar IS een treffer; GUID-versie-4 is nooit van ons.
  (3) RANGORDE: minstens twee exemplaren die beide concept zijn + zelfde factuurdatum + zelfde bedrag =
      `waarschijnlijk_dubbel` (tekst "Waarschijnlijk dubbel", kantoorbreed urgenter), anders "Zelfde
      referentie, controleer". De 6-Steps-casus (RLZ-04-00000069/00000072, beide concept, zelfde dag, zelfde bedrag)
      is de testcasus voor "waarschijnlijk dubbel".
  (4) OVERGANG OUD → CLUSTER ZONDER MIGRATIE (bestaande tabellen/JSONB):
      - Open paar-bevindingen (`afwijking`, detail `rlz_id_a`/`rlz_id_b`) uit de VORIGE afgeronde run worden in de
        eerstvolgende cluster-run opnieuw geregistreerd onder hun EIGEN vingerafdruk als soort `uitgesloten` met
        uitsluiting "vervangen door cluster [vaf:…]" (beide id's in een cluster) of "referentie uitgesloten (<reden>)"
        — zo ziet de delta-motor ze niet als "verdwenen/hersteld" (huidig_vafs is soort-agnostisch), verschijnen ze
        niet als open afwijking, en verdwijnt de tussenstand vanzelf ná één run (de volgende run heeft geen open
        paar-bevindingen meer als 'vorige'). Paren waarvan een document uit het venster/RLZ verdween worden NIET
        opnieuw geregistreerd (dat is een echte "verdwenen"-melding).
      - Actieve PAAR-ACCEPTATIES (`reconciliatie_acceptatie`, detail `rlz_a=… rlz_b=…`) blijven staan en worden
        éénmalig op het cluster OVERGEDRAGEN als álle exemplaren van het cluster door geaccepteerde paren gedekt zijn
        (strenger dan "één paar valt erin": een cluster mét een nieuw, niet-beoordeeld exemplaar blijft open — niets
        verdwijnt stil). Overdracht = nieuwe acceptatie-rij op de cluster-sleutel (zelfde Beheerder als acceptant,
        reden mét verwijzing naar het paar) + audit `reconciliatie_acceptatie_overgedragen` (systeem-actor). Nooit
        opnieuw zodra er ooit een cluster-acceptatie bestond (ook een ingetrokken) — intrekken door een Beheerder
        wint. Deels gedekt = open mét `acceptatie_gedeeltelijk` in het detail (zichtbaar in de tekst).
- **Run 2 VGG 12-09 blok 2 (besluit Peter 12-09, CONTRACT_RUN2 besluit 4 + 6) — SNEDE 2, ALLEEN LEES-ONLY:**
  `reconciliatie-alles --alleen rlz_dubbel --lees-only` toetst óók paren binnen dezelfde crediteur met cent-exact
  gelijk bedrag en `BookDate` (terugval `Date`) binnen ±3 dagen, ONGEACHT referentie (Zenvoices × module: dezelfde
  factuur twee keer ingevoerd onder een andere referentie). Alleen paren die snede 1 niet al als cluster meldt; nooit
  als beide van de module. BANK IS LEIDEND: in lees-only-modus worden de PaymentTransactions van de administratie
  gelezen (zelfde venster; `$filter=BookDate ge …`, bij 400 zonder filter) en een paar wordt alleen gemeld als er
  minder dan twee bankmutaties (|bedrag|, teken −1 voor inkoop, ±3 dagen; `app/migratie/bankdekking.py`) tegenover
  staan; anders teller `bank_bevestigd`. Bank niet leesbaar → paren gemeld mét markering "bank niet gelezen". De
  DAGELIJKSE run leest GEEN PaymentTransactions en meldt niets van snede 2 — of snede 2 een bevinding-rij wordt is
  een beslispunt voor Peter (meetlat eerst).
- Uitkomst = bevinding `afwijking` soort `dubbel_in_rlz`; acceptatie mét reden via het bestaande pad (bron
  `documenten`: de DB-CHECK op `reconciliatie_acceptatie.bron` kent geen vijfde waarde en dit blok brengt bewust
  GEEN migratie). GEEN automatische actie: de RLZ-kant is mensenwerk, de app verwijdert nooit (kernprincipe 3). Er is
  geen bekende URL-vorm van de RLZ-web-UI per document → de handeling is "open álle boekstuknummers in Reeleezee".
- `vind_paren` (de OUDE paar-methode) blijft bestaan als MEETLAT voor de lees-only vergelijking "paren OUD → clusters
  NIEUW" (`reconciliatie-alles --alleen rlz_dubbel --lees-only`) en voor de overgang hierboven.

Geen AI, geen RLZ-writes. Alle geldvergelijking in Decimal."""

from __future__ import annotations

import logging
import re
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.session import scoped_session
from app.documenten.duplicaat_afvoer import normaliseer_referentie
from app.documenten.models import Boekvoorstel, Document, Tegenboeking
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.migratie import bankdekking
from app.reconciliatie import referentie_classificatie as classificatie
from app.rlz.client import RlzApiError, RlzClient, bedrag_cent_exact
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.rlz.lezen_cli import _initialen as initialen
from app.tijd import vandaag_nl

logger = logging.getLogger(__name__)

BLOK = "rlz_dubbel"
SOORT = "dubbel_in_rlz"
#: Acceptaties lopen via de bestaande `reconciliatie_acceptatie`-tabel; de DB-CHECK op `bron` kent alleen
#: documenten/bank/omzet/doorbelasting (migraties 0042/0044) — dit blok brengt geen migratie en meldt onder
#: `documenten`.
ACCEPTATIE_BRON = "documenten"
#: Leesvenster: factuurdatum (`Date`) niet ouder dan dit. 400 dagen dekt een boekjaar plús de nakomers van het vorige;
#: ouder handwerk is boekhoudkundig afgesloten (aangifte ingediend) en hoort niet elke nacht opnieuw gemeld te worden.
VENSTER_DAGEN = 400
PAGINA_GROOTTE = 200
REGEL_REFERENTIE = "referentie"
#: Snede 2 (run 2 VGG blok 2): zelfde crediteur + zelfde bedrag + boekdatum binnen dit venster, ongeacht referentie.
SNEDE2_VENSTER_DAGEN = 3
LABEL_MODULE_X_NIET = "module×niet-module"
LABEL_NIET_X_NIET = "niet-module×niet-module"
#: Uitsluitingsreden op een vervangen paar-bevinding (overgang 10-09) — letterlijke tekst in detail `uitsluiting`.
UITSLUITING_VERVANGEN = "vervangen door cluster"
UITSLUITING_REFERENTIE = "referentie uitgesloten"
#: Namespace voor het deterministische record_id van een cluster (UUIDv5 over de cluster-sleutel).
_CLUSTER_NAMESPACE = uuid.UUID("6d7f2a3e-1b4c-5d6e-8f90-0a1b2c3d4e5f")
_PAAR_DETAIL = re.compile(r"rlz_a=([0-9a-fA-F-]{36})\s+rlz_b=([0-9a-fA-F-]{36})")
#: Genormaliseerde referenties (`normaliseer_referentie`) die geen factuurnummer zijn maar een plaatsvervanger van de
#: RLZ-UI/scan-import — tellen als leeg, matchen nooit (blok 7 herstelrun 08-09). Alleen nullen (`0`, `000`, `00-00`)
#: vallen er via `_ALLEEN_NULLEN` ook onder; "factuur"/"invoice" zijn ná normalisatie al leeg (voorvoegsel-strip).
PLACEHOLDER_REFERENTIES: frozenset[str] = frozenset(
    {
        "ingescanddocument",
        "ingescand",
        "document",
        "scan",
        "factuur",
        "invoice",
        "nota",
        "bon",
        "onbekend",
        "nvt",
        "geen",
    }
)
_ALLEEN_NULLEN = re.compile(r"0+")


def is_placeholder_referentie(referentie_norm: str | None) -> bool:
    """Deterministisch: leeg, alleen nullen of een generieke plaatsvervanger = geen toetsbare referentie."""
    if not referentie_norm:
        return True
    return bool(_ALLEEN_NULLEN.fullmatch(referentie_norm)) or referentie_norm in PLACEHOLDER_REFERENTIES


def toetsbare_referentie(referentie: object) -> str | None:
    """Genormaliseerde referentie voor de match, of None als die leeg/placeholder is."""
    if referentie in (None, ""):
        return None
    norm = normaliseer_referentie(str(referentie))
    return None if is_placeholder_referentie(norm) else norm


# ---- data ----------------------------------------------------------------------------------------


@dataclass(frozen=True)
class RlzDocument:
    """Eén PurchaseInvoice zoals RLZ 'm teruggeeft, platgeslagen tot wat de toets nodig heeft."""

    rlz_id: uuid.UUID
    entity_id: uuid.UUID | None
    entity_naam: str | None
    referentie: str | None
    referentie_norm: str | None
    datum: date | None
    boekdatum: date | None
    bedrag: Decimal | None
    boekstuk: str | None
    status: int | None
    van_module: bool

    @property
    def concept(self) -> bool:
        return self.status == 1

    def als_dict(self) -> dict[str, Any]:
        """Eén exemplaar in het bevinding-detail (0114-JSONB): alleen JSON-veilige waarden."""
        return {
            "rlz_id": str(self.rlz_id),
            "boekstuk": self.boekstuk,
            "referentie": self.referentie,
            "datum": self.datum.isoformat() if self.datum else None,
            "boekdatum": self.boekdatum.isoformat() if self.boekdatum else None,
            "bedrag": str(self.bedrag) if self.bedrag is not None else None,
            "status": self.status,
            "concept": self.concept,
            "van_module": self.van_module,
        }


def _sorteer_op_datum(documenten: Iterable[RlzDocument]) -> tuple[RlzDocument, ...]:
    return tuple(sorted(documenten, key=lambda d: (d.datum or date.min, d.boekstuk or "", str(d.rlz_id))))


@dataclass(frozen=True)
class DubbelPaar:
    """OUDE paar-vorm (blok 6/7) — sinds 10-09 alleen nog meetlat (lees-only vergelijking) en overgangsbrug."""

    a: RlzDocument  # a.rlz_id < b.rlz_id (sortering op tekst) — stabiel over runs
    b: RlzDocument
    regels: tuple[str, ...]  # sinds 08-09 altijd (REGEL_REFERENTIE,); oude bevindingen kunnen nog 'bedrag_datum' dragen

    @property
    def detail(self) -> str:
        return f"rlz_a={self.a.rlz_id} rlz_b={self.b.rlz_id}"

    @property
    def record_id(self) -> uuid.UUID:
        return self.a.rlz_id

    @property
    def concept(self) -> bool:
        return self.a.concept or self.b.concept

    def context(self, *, administratie_naam: str | None = None, rlz_admin_id: str | None = None) -> dict[str, Any]:
        return {
            "leverancier_naam": self.a.entity_naam or self.b.entity_naam,
            "regel": "+".join(self.regels),
            "concept": self.concept,
            "referentie_a": self.a.referentie,
            "referentie_b": self.b.referentie,
            "boekstuk_a": self.a.boekstuk,
            "boekstuk_b": self.b.boekstuk,
            "bedrag_a": str(self.a.bedrag) if self.a.bedrag is not None else None,
            "bedrag_b": str(self.b.bedrag) if self.b.bedrag is not None else None,
            "datum_a": self.a.datum.isoformat() if self.a.datum else None,
            "datum_b": self.b.datum.isoformat() if self.b.datum else None,
            "boekdatum_a": self.a.boekdatum.isoformat() if self.a.boekdatum else None,
            "boekdatum_b": self.b.boekdatum.isoformat() if self.b.boekdatum else None,
            "status_a": self.a.status,
            "status_b": self.b.status,
            "van_module_a": self.a.van_module,
            "van_module_b": self.b.van_module,
            "rlz_id_a": str(self.a.rlz_id),
            "rlz_id_b": str(self.b.rlz_id),
            "administratie_naam": administratie_naam,
            "rlz_admin_id": rlz_admin_id,
        }


@dataclass(frozen=True)
class DubbelCluster:
    """Alle exemplaren van dezelfde crediteur met dezelfde genormaliseerde referentie (≥ 2, niet álle van de module),
    gesorteerd op factuurdatum. Sinds 10-09 DE bevinding-eenheid van dit blok."""

    entity_id: uuid.UUID
    entity_naam: str | None
    referentie_norm: str
    rlz_admin_id: str | None
    documenten: tuple[RlzDocument, ...]

    @property
    def sleutel(self) -> str:
        """De acceptatie-sleutel: stabiel zolang crediteur + referentie bestaan — een extra exemplaar verandert
        de vingerafdruk NIET (beslispunt 10-09: alternatief is de id's in de sleutel)."""
        return f"cluster={self.rlz_admin_id or ''}|{self.entity_id}|{self.referentie_norm}"

    @property
    def detail(self) -> str:
        return self.sleutel

    @property
    def record_id(self) -> uuid.UUID:
        return uuid.uuid5(_CLUSTER_NAMESPACE, self.sleutel)

    @property
    def rlz_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(d.rlz_id for d in self.documenten)

    @property
    def concept(self) -> bool:
        return any(d.concept for d in self.documenten)

    @property
    def aantal_module(self) -> int:
        return sum(1 for d in self.documenten if d.van_module)

    @property
    def waarschijnlijk_dubbel(self) -> bool:
        """Minstens twee exemplaren die beide concept zijn + zelfde factuurdatum + zelfde bedrag (6-Steps-casus)."""
        groepen: dict[tuple[date, Decimal], int] = {}
        for d in self.documenten:
            if d.concept and d.datum is not None and d.bedrag is not None:
                groepen[(d.datum, d.bedrag)] = groepen.get((d.datum, d.bedrag), 0) + 1
        return any(n >= 2 for n in groepen.values())

    @property
    def paren(self) -> frozenset[frozenset[uuid.UUID]]:
        ids = sorted(self.rlz_ids, key=str)
        return frozenset(frozenset((x, y)) for i, x in enumerate(ids) for y in ids[i + 1 :])

    def context(
        self,
        *,
        administratie_naam: str | None = None,
        acceptatie_gedeeltelijk: Sequence[str] | None = None,
    ) -> dict[str, Any]:
        """Naamvelden voor `teksten.py` + de UI-uitklap: exemplaren als lijst (N boekstukken), plus de A/B-velden van
        de eerste twee exemplaren zodat oude lezers (frontend-terugval, details-labels) blijven werken."""
        eerste, tweede = self.documenten[0], self.documenten[1]
        uit: dict[str, Any] = {
            "leverancier_naam": self.entity_naam,
            "referentie": eerste.referentie,
            "referentie_norm": self.referentie_norm,
            "regel": REGEL_REFERENTIE,
            "cluster": self.sleutel,
            "aantal_exemplaren": len(self.documenten),
            "aantal_module": self.aantal_module,
            "concept": self.concept,
            "waarschijnlijk_dubbel": self.waarschijnlijk_dubbel,
            "exemplaren": [d.als_dict() for d in self.documenten],
            "boekstukken": [d.boekstuk for d in self.documenten if d.boekstuk],
            "rlz_ids": [str(d.rlz_id) for d in self.documenten],
            "rlz_ids_tekst": ", ".join(str(d.rlz_id) for d in self.documenten),
            "administratie_naam": administratie_naam,
            "rlz_admin_id": self.rlz_admin_id,
            # Terugval-velden (paar-vorm) — eerste twee exemplaren.
            "referentie_a": eerste.referentie,
            "referentie_b": tweede.referentie,
            "boekstuk_a": eerste.boekstuk,
            "boekstuk_b": tweede.boekstuk,
            "bedrag_a": str(eerste.bedrag) if eerste.bedrag is not None else None,
            "bedrag_b": str(tweede.bedrag) if tweede.bedrag is not None else None,
            "datum_a": eerste.datum.isoformat() if eerste.datum else None,
            "datum_b": tweede.datum.isoformat() if tweede.datum else None,
            "status_a": eerste.status,
            "status_b": tweede.status,
            "van_module_a": eerste.van_module,
            "van_module_b": tweede.van_module,
            "rlz_id_a": str(eerste.rlz_id),
            "rlz_id_b": str(tweede.rlz_id),
        }
        if acceptatie_gedeeltelijk:
            uit["acceptatie_gedeeltelijk"] = list(acceptatie_gedeeltelijk)
        return uit


@dataclass(frozen=True)
class UitgeslotenGroep:
    """Eén referentiegroep die géén cluster werd, mét reden — voor tellers, CLI-regel en lees-only-uitvoer."""

    entity_id: uuid.UUID
    entity_naam: str | None
    referentie: str | None
    referentie_norm: str | None
    reden: str
    aantal_documenten: int
    aantal_bedragen: int
    rlz_ids: frozenset[uuid.UUID]


@dataclass(frozen=True)
class Snede2Paar:
    """Eén snede-2-paar (run 2 VGG blok 2, lees-only meetlat): zelfde crediteur, zelfde bedrag, boekdatum binnen
    ±`SNEDE2_VENSTER_DAGEN`, ongeacht referentie; niet al in een cluster; niet beide van de module."""

    a: RlzDocument  # a.rlz_id < b.rlz_id (tekstsortering) — stabiel over runs
    b: RlzDocument
    bank_mutaties: int  # k: gevonden bankmutaties (|bedrag|, teken, ±3 d), elke mutatie één keer
    bank_gelezen: bool

    @property
    def bedrag(self) -> Decimal | None:
        return self.a.bedrag

    @property
    def label(self) -> str:
        return LABEL_MODULE_X_NIET if (self.a.van_module or self.b.van_module) else LABEL_NIET_X_NIET

    @property
    def bank_bevestigd(self) -> bool:
        """Evenveel (of meer) bankmutaties als boekingen (2) → echt, niet melden; bank niet gelezen → nooit."""
        return self.bank_gelezen and self.bank_mutaties >= 2

    @property
    def dagen_verschil(self) -> int | None:
        da, db = _snede2_datum(self.a), _snede2_datum(self.b)
        return None if da is None or db is None else abs((da - db).days)

    def regel(self, aid: object) -> str:
        """`SNEDE2 <admin> <A> + <B> | <initialen> | € <bedrag> | <datum A>/<datum B> | <label> | bank k/2`."""
        naam = self.a.entity_naam or self.b.entity_naam or ""
        da, db = _snede2_datum(self.a), _snede2_datum(self.b)
        bank = f"bank {self.bank_mutaties}/2" if self.bank_gelezen else "bank niet gelezen"
        return (
            f"SNEDE2 {aid} {self.a.boekstuk or '?'} + {self.b.boekstuk or '?'} | {initialen(naam) or '?'} | "
            f"€ {self.bedrag} | {da.isoformat() if da else '?'}/{db.isoformat() if db else '?'} | {self.label} | {bank}"
        )


@dataclass(frozen=True)
class Snede2Uitkomst:
    paren: tuple[Snede2Paar, ...]  # gemeld (bank-tekort of bank niet gelezen)
    bank_bevestigd: int  # kandidaten die door de bank als echt zijn bevestigd (niet gemeld, wél geteld)
    bank_gelezen: bool
    gedraaid: bool = True

    def tellers(self) -> dict[str, int]:
        return {
            "paren": len(self.paren),
            LABEL_MODULE_X_NIET: sum(1 for p in self.paren if p.label == LABEL_MODULE_X_NIET),
            LABEL_NIET_X_NIET: sum(1 for p in self.paren if p.label == LABEL_NIET_X_NIET),
            "bank_bevestigd": self.bank_bevestigd,
        }


def _snede2_datum(d: RlzDocument) -> date | None:
    return d.boekdatum or d.datum


@dataclass(frozen=True)
class ClusterUitkomst:
    clusters: tuple[DubbelCluster, ...]
    uitgesloten: tuple[UitgeslotenGroep, ...]

    def tellers(self) -> dict[str, dict[str, int]]:
        """reden → {groepen, documenten}, in de vaste volgorde van `UITSLUITINGSREDENEN` (ook bij 0)."""
        uit = {r: {"groepen": 0, "documenten": 0} for r in classificatie.UITSLUITINGSREDENEN}
        for g in self.uitgesloten:
            uit.setdefault(g.reden, {"groepen": 0, "documenten": 0})
            uit[g.reden]["groepen"] += 1
            uit[g.reden]["documenten"] += g.aantal_documenten
        return uit


@dataclass(frozen=True)
class RlzDubbelRapport:
    administratie_id: uuid.UUID | None
    aantal_getoetst: int  # documenten in het venster
    aantal_module: int  # waarvan door de module aangemaakt
    aantal_zonder_crediteur: int  # zonder Entity — niet toetsbaar
    paren: tuple[DubbelPaar, ...]  # OUDE meetlat (paar-methode), alleen ter vergelijking
    venster_vanaf: date
    clusters: tuple[DubbelCluster, ...] = ()
    uitgesloten: tuple[UitgeslotenGroep, ...] = ()
    rlz_admin_id: str | None = None
    #: Snede 2 (run 2 VGG blok 2) — alleen gevuld in lees-only-modus (`toets_met_client(..., snede2=True)`).
    snede2: Snede2Uitkomst | None = None

    def uitsluiting_tellers(self) -> dict[str, dict[str, int]]:
        return ClusterUitkomst(clusters=self.clusters, uitgesloten=self.uitgesloten).tellers()


@dataclass(frozen=True)
class RlzDubbelResultaat:
    rapporten: dict[uuid.UUID, RlzDubbelRapport] = field(default_factory=dict)
    fouten: dict[uuid.UUID, str] = field(default_factory=dict)
    overgeslagen: dict[uuid.UUID, str] = field(default_factory=dict)


# ---- RLZ lezen -----------------------------------------------------------------------------------


def venster_vanaf(vandaag: date | None = None) -> date:
    return (vandaag or vandaag_nl()) - timedelta(days=VENSTER_DAGEN)


def lees_purchase_invoices(client: RlzClient, *, vanaf: date) -> list[dict[str, Any]]:
    """Alle inkoopfacturen met `Date ge <vanaf>` in één gepagineerde reeks — exact de literal- en pagineervorm van
    `app/geheugen/seed.py::_facturen` (draait dagelijks live op PurchaseInvoices). Throttling/retry zit in de
    client (`_request`). Bewust geen `$select` (niet STAP-0-geverifieerd op deze collectie) en geen `Status`-filter
    (`Status eq 1` = 400, enum-type; concepten moeten juist méé)."""
    uit: list[dict[str, Any]] = []
    skip = 0
    while True:
        batch = client.get(
            "PurchaseInvoices",
            params={
                "$filter": f"Date ge {vanaf.isoformat()}",
                "$expand": "Entity",
                "$top": str(PAGINA_GROOTTE),
                "$skip": str(skip),
            },
        ).get("value", [])
        uit.extend(batch)
        if len(batch) < PAGINA_GROOTTE:
            return uit
        skip += PAGINA_GROOTTE


def _als_uuid(waarde: object) -> uuid.UUID | None:
    try:
        return uuid.UUID(str(waarde)) if waarde else None
    except ValueError:
        return None


def _als_datum(waarde: object) -> date | None:
    if not isinstance(waarde, str) or len(waarde) < 10:
        return None
    try:
        return date.fromisoformat(waarde[:10])
    except ValueError:
        return None


def _als_int(waarde: object) -> int | None:
    try:
        return int(waarde) if waarde is not None else None  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def naar_rlz_document(rij: dict[str, Any], *, module_ids: set[uuid.UUID]) -> RlzDocument | None:
    """Eén RLZ-rij → `RlzDocument`; None als de rij geen leesbaar id draagt (dan is er niets te vergelijken)."""
    rlz_id = _als_uuid(rij.get("id"))
    if rlz_id is None:
        return None
    entity = rij.get("Entity") or {}
    referentie = rij.get("Reference")
    return RlzDocument(
        rlz_id=rlz_id,
        entity_id=_als_uuid(entity.get("id")) if isinstance(entity, dict) else None,
        entity_naam=(entity.get("Name") or entity.get("SearchName")) if isinstance(entity, dict) else None,
        referentie=str(referentie) if referentie not in (None, "") else None,
        referentie_norm=toetsbare_referentie(referentie),
        datum=_als_datum(rij.get("Date")),
        boekdatum=_als_datum(rij.get("BookDate")),
        bedrag=bedrag_cent_exact(rij.get("BaseInvoiceAmount")),
        boekstuk=str(rij["ReceiptNumber"]) if rij.get("ReceiptNumber") else None,
        status=_als_int(rij.get("Status")),
        van_module=is_van_module(rlz_id, module_ids),
    )


def is_van_module(rlz_id: uuid.UUID, module_ids: set[uuid.UUID]) -> bool:
    """Van de module = het GUID staat in de deterministische set uit onze eigen DB. Een GUID-versie-4 (RLZ-UI/
    import) is per definitie nooit van ons — die kortsluiting voorkomt dat een lege/verouderde set een handmatig
    exemplaar per ongeluk als 'module' laat doorgaan."""
    if rlz_id.version == 4:
        return False
    return rlz_id in module_ids


# ---- paren zoeken (puur; OUDE meetlat) -------------------------------------------------------------


def vind_paren(documenten: Iterable[RlzDocument]) -> list[DubbelPaar]:
    """OUDE paar-methode (blok 6/7): paren binnen dezelfde crediteur op UITSLUITEND gelijke genormaliseerde referentie
    (placeholder-referenties zijn al None). Sinds 10-09 alleen nog de meetlat "paren OUD" in de lees-only vergelijking
    en de overgangsbrug voor bestaande paar-bevindingen/-acceptaties — de bevinding-eenheid is `vind_clusters`."""
    per_crediteur: dict[uuid.UUID, list[RlzDocument]] = {}
    for d in documenten:
        if d.entity_id is None:
            continue
        per_crediteur.setdefault(d.entity_id, []).append(d)

    paren: dict[tuple[uuid.UUID, uuid.UUID], set[str]] = {}

    def _voeg_toe(x: RlzDocument, y: RlzDocument, regel: str) -> None:
        if x.rlz_id == y.rlz_id or (x.van_module and y.van_module):
            return
        sleutel = (x.rlz_id, y.rlz_id) if str(x.rlz_id) < str(y.rlz_id) else (y.rlz_id, x.rlz_id)
        paren.setdefault(sleutel, set()).add(regel)

    for docs in per_crediteur.values():
        op_referentie: dict[str, list[RlzDocument]] = {}
        for d in docs:
            if d.referentie_norm:
                op_referentie.setdefault(d.referentie_norm, []).append(d)
        for groep in op_referentie.values():
            for i, x in enumerate(groep):
                for y in groep[i + 1 :]:
                    _voeg_toe(x, y, REGEL_REFERENTIE)

    op_id = {d.rlz_id: d for d in documenten}
    uit = [
        DubbelPaar(a=op_id[a_id], b=op_id[b_id], regels=tuple(sorted(regels))) for (a_id, b_id), regels in paren.items()
    ]
    uit.sort(key=lambda p: (str(p.a.rlz_id), str(p.b.rlz_id)))
    return uit


# ---- clusters zoeken (puur) ----------------------------------------------------------------------


def vind_clusters(documenten: Iterable[RlzDocument], *, rlz_admin_id: str | None = None) -> ClusterUitkomst:
    """Referentiegroepen per crediteur → classificatie (`referentie_classificatie.classificeer_groep`) → cluster
    (toetsbaar, ≥ 2 exemplaren, niet álle van de module) of uitgesloten groep mét reden. Documenten zonder Entity zijn
    niet toetsbaar. Placeholder-groepen (referentie_norm None, ruwe referentie aanwezig) worden per crediteur op de
    ruwe genormaliseerde tekst gegroepeerd zodat de teller "hoeveel groepen om welke reden" ook voor (c) klopt.
    Clusters gesorteerd op crediteur-naam + referentie (stabiel), exemplaren op datum."""
    documenten = list(documenten)
    per_crediteur: dict[uuid.UUID, list[RlzDocument]] = {}
    for d in documenten:
        if d.entity_id is None:
            continue
        per_crediteur.setdefault(d.entity_id, []).append(d)

    clusters: list[DubbelCluster] = []
    uitgesloten: list[UitgeslotenGroep] = []
    for entity_id, docs in per_crediteur.items():
        groepen: dict[tuple[str, str], list[RlzDocument]] = {}
        for d in docs:
            if d.referentie_norm:
                groepen.setdefault(("ref", d.referentie_norm), []).append(d)
            elif d.referentie:
                ruw = normaliseer_referentie(d.referentie) or d.referentie.strip().lower()
                groepen.setdefault(("placeholder", ruw), []).append(d)
        for (soort, norm), groep in groepen.items():
            if len(groep) < 2:
                continue
            uitkomst = classificatie.classificeer_groep(groep)
            naam = next((d.entity_naam for d in groep if d.entity_naam), None)
            if not uitkomst.toetsbaar:
                uitgesloten.append(
                    UitgeslotenGroep(
                        entity_id=entity_id,
                        entity_naam=naam,
                        referentie=groep[0].referentie,
                        referentie_norm=norm if soort == "ref" else None,
                        reden=uitkomst.reden or classificatie.REDEN_PLACEHOLDER,
                        aantal_documenten=len(groep),
                        aantal_bedragen=uitkomst.aantal_bedragen,
                        rlz_ids=frozenset(d.rlz_id for d in groep),
                    )
                )
                continue
            if all(d.van_module for d in groep):
                continue  # domein van de module-duplicaatcheck en de RLZ-duplicaatcheck vóór de PUT
            clusters.append(
                DubbelCluster(
                    entity_id=entity_id,
                    entity_naam=naam,
                    referentie_norm=norm,
                    rlz_admin_id=rlz_admin_id,
                    documenten=_sorteer_op_datum(groep),
                )
            )
    clusters.sort(key=lambda c: (c.entity_naam or "", c.referentie_norm, str(c.entity_id)))
    uitgesloten.sort(key=lambda g: (g.reden, g.entity_naam or "", g.referentie or "", str(g.entity_id)))
    return ClusterUitkomst(clusters=tuple(clusters), uitgesloten=tuple(uitgesloten))


# ---- snede 2 (run 2 VGG blok 2; puur + één lezer) --------------------------------------------------


def lees_payment_transactions(client: RlzClient, *, vanaf: date) -> list[dict[str, Any]] | None:
    """Alle bankmutaties sinds `vanaf`, gepagineerd. Eerst `$filter=BookDate ge <vanaf>`; een 400 (filter op deze
    collectie niet ondersteund) → dezelfde reeks zónder filter en client-side gefilterd; elke andere fout (403
    rechten, 404, 5xx ná retries) → None = "bank niet gelezen" (de aanroeper markeert, filtert niets). Alleen GET's."""

    def _lees(filter_: str | None) -> list[dict[str, Any]]:
        uit: list[dict[str, Any]] = []
        skip = 0
        while True:
            params: dict[str, Any] = {"$top": str(PAGINA_GROOTTE), "$skip": str(skip)}
            if filter_:
                params["$filter"] = filter_
            batch = client.get("PaymentTransactions", params=params).get("value", [])
            uit.extend(r for r in batch if isinstance(r, dict))
            if len(batch) < PAGINA_GROOTTE:
                return uit
            skip += PAGINA_GROOTTE

    try:
        return _lees(f"BookDate ge {vanaf.isoformat()}")
    except RlzApiError as exc:
        if exc.status_code != 400:
            logger.warning("PaymentTransactions niet leesbaar voor snede 2: %s", exc)
            return None
    try:
        alles = _lees(None)
    except RlzApiError as exc:
        logger.warning("PaymentTransactions niet leesbaar voor snede 2 (zonder filter): %s", exc)
        return None
    return [r for r in alles if (_als_datum(r.get("BookDate")) or _als_datum(r.get("Date")) or date.min) >= vanaf]


def _snede2_kandidaten(
    documenten: Iterable[RlzDocument],
    *,
    clusters: Sequence[DubbelCluster],
    bank: Sequence[bankdekking.BankMutatie] | None,
    venster_dagen: int = SNEDE2_VENSTER_DAGEN,
) -> list[Snede2Paar]:
    """Alle snede-2-paren (ook de bank-bevestigde), gesorteerd op (rlz_id a, rlz_id b)."""
    al_gemeld: set[frozenset[uuid.UUID]] = set()
    for c in clusters:
        al_gemeld |= c.paren
    per_crediteur: dict[uuid.UUID, list[RlzDocument]] = {}
    for d in documenten:
        if d.entity_id is None or d.bedrag is None or _snede2_datum(d) is None:
            continue
        per_crediteur.setdefault(d.entity_id, []).append(d)
    uit: list[Snede2Paar] = []
    for docs in per_crediteur.values():
        docs = sorted(docs, key=lambda d: (_snede2_datum(d), str(d.rlz_id)))  # type: ignore[arg-type,return-value]
        for i, x in enumerate(docs):
            for y in docs[i + 1 :]:
                dx, dy = _snede2_datum(x), _snede2_datum(y)
                assert dx is not None and dy is not None
                if (dy - dx).days > venster_dagen:
                    break  # gesorteerd op datum: verder weg wordt het alleen groter
                if x.bedrag != y.bedrag or (x.van_module and y.van_module):
                    continue
                if frozenset((x.rlz_id, y.rlz_id)) in al_gemeld:
                    continue
                a, b = (x, y) if str(x.rlz_id) < str(y.rlz_id) else (y, x)
                teken = bankdekking.teken_van("PurchaseInvoices", x.bedrag)
                dekking = bankdekking.dekking_voor(
                    [(x.bedrag, dx, teken), (y.bedrag, dy, teken)],  # type: ignore[list-item]
                    bank,
                    venster_dagen=venster_dagen,
                )
                uit.append(Snede2Paar(a=a, b=b, bank_mutaties=dekking.bankmutaties, bank_gelezen=dekking.bank_gelezen))
    uit.sort(key=lambda p: (str(p.a.rlz_id), str(p.b.rlz_id)))
    return uit


def vind_snede2(
    documenten: Iterable[RlzDocument],
    *,
    clusters: Sequence[DubbelCluster],
    bank: Sequence[bankdekking.BankMutatie] | None,
    venster_dagen: int = SNEDE2_VENSTER_DAGEN,
) -> list[Snede2Paar]:
    """Puur: de te MELDEN snede-2-paren — zelfde crediteur, cent-exact gelijk bedrag, boekdatum (terugval datum)
    binnen ±`venster_dagen`, ongeacht referentie; niet al door snede 1 (cluster) gemeld; niet beide van de module;
    en bank-tekort (minder dan twee bankmutaties, of bank niet gelezen → gemeld mét markering). Bank-bevestigde
    paren (k ≥ 2) worden NIET teruggegeven — `snede2_uitkomst` telt ze."""
    kandidaten = _snede2_kandidaten(documenten, clusters=clusters, bank=bank, venster_dagen=venster_dagen)
    return [p for p in kandidaten if not p.bank_bevestigd]


def snede2_uitkomst(
    documenten: Iterable[RlzDocument],
    *,
    clusters: Sequence[DubbelCluster],
    bank: Sequence[bankdekking.BankMutatie] | None,
) -> Snede2Uitkomst:
    kandidaten = _snede2_kandidaten(documenten, clusters=clusters, bank=bank)
    return Snede2Uitkomst(
        paren=tuple(p for p in kandidaten if not p.bank_bevestigd),
        bank_bevestigd=sum(1 for p in kandidaten if p.bank_bevestigd),
        bank_gelezen=bank is not None,
    )


# ---- module-GUID's uit de eigen DB ----------------------------------------------------------------


def module_ids_voor(administratie_id: uuid.UUID) -> set[uuid.UUID]:
    """Alle RLZ-inkoopdocument-GUID's die de module voor deze administratie kan hebben aangemaakt — deterministisch
    afgeleid (rlz_ids.py bewaart ze bewust niet als kolom): élk inkoopdocument × élke boek_cyclus (herboekingen),
    tegenboekingen, doorbelasting-spiegels in deze (doel-)administratie en bank-relatieboekingen. Ruimer dan strikt
    nodig is onschadelijk: de set bepaalt alleen "álle van de module → geen treffer"."""
    uit: set[uuid.UUID] = set()
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Document.id, Boekvoorstel.boek_cyclus)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id, isouter=True)
            .where(Document.administratie_id == administratie_id)
        ).all()
        for document_id, boek_cyclus in rijen:
            for cyclus in range(int(boek_cyclus or 0) + 1):
                uit.add(rlz_herboeking_id(document_id, cyclus))
        for rij in session.execute(
            select(Tegenboeking.document_id, Tegenboeking.boek_cyclus, Tegenboeking.rlz_tegenboeking_id).where(
                Tegenboeking.administratie_id == administratie_id
            )
        ).all():
            uit.add(rij.rlz_tegenboeking_id)
            uit.add(rlz_tegenboeking_id(rij.document_id, rij.boek_cyclus))
        try:
            from app.doorbelasting.models import DoorbelastingBoeking

            for spiegel_id in session.scalars(
                select(DoorbelastingBoeking.spiegel_rlz_id).where(
                    DoorbelastingBoeking.doel_administratie_id == administratie_id
                )
            ):
                if spiegel_id is not None:
                    uit.add(spiegel_id)
        except Exception:  # noqa: BLE001 — een ontbrekende neventabel mag de toets nooit laten omvallen
            logger.exception("doorbelasting-spiegel-GUID's niet gelezen voor %s", administratie_id)
        try:
            from app.bank.models import BankRelatieBoeking

            for rlz_id in session.scalars(
                select(BankRelatieBoeking.rlz_document_id).where(
                    BankRelatieBoeking.administratie_id == administratie_id
                )
            ):
                if rlz_id is not None:
                    uit.add(rlz_id)
        except Exception:  # noqa: BLE001
            logger.exception("bank-relatieboeking-GUID's niet gelezen voor %s", administratie_id)
    return uit


# ---- toets per administratie ---------------------------------------------------------------------


def toets_met_client(
    client: RlzClient,
    *,
    module_ids: set[uuid.UUID],
    administratie_id: uuid.UUID | None = None,
    vandaag: date | None = None,
    rlz_admin_id: str | None = None,
    snede2: bool = False,
) -> RlzDubbelRapport:
    """De toets zelf, los van DB en credentials — ook het hart van het read-only live-script. `snede2=True` (alleen
    vanuit de lees-only CLI) leest óók de PaymentTransactions en voegt de snede-2-meetlat toe; de dagelijkse run
    laat dat op False."""
    vanaf = venster_vanaf(vandaag)
    rijen = lees_purchase_invoices(client, vanaf=vanaf)
    documenten = [d for d in (naar_rlz_document(r, module_ids=module_ids) for r in rijen) if d is not None]
    uitkomst = vind_clusters(documenten, rlz_admin_id=rlz_admin_id)
    snede2_resultaat: Snede2Uitkomst | None = None
    if snede2:
        bank_rijen = lees_payment_transactions(client, vanaf=vanaf)
        bank = bankdekking.bankmutaties_uit_rijen(bank_rijen) if bank_rijen is not None else None
        snede2_resultaat = snede2_uitkomst(documenten, clusters=uitkomst.clusters, bank=bank)
    return RlzDubbelRapport(
        administratie_id=administratie_id,
        aantal_getoetst=len(documenten),
        aantal_module=sum(1 for d in documenten if d.van_module),
        aantal_zonder_crediteur=sum(1 for d in documenten if d.entity_id is None),
        paren=tuple(vind_paren(documenten)),
        venster_vanaf=vanaf,
        clusters=uitkomst.clusters,
        uitgesloten=uitkomst.uitgesloten,
        rlz_admin_id=rlz_admin_id,
        snede2=snede2_resultaat,
    )


def toets_administratie(
    administratie_id: uuid.UUID,
    *,
    client_factory: Callable[[str], RlzClient] | None = None,
    vandaag: date | None = None,
    snede2: bool = False,
) -> RlzDubbelRapport:
    rlz_admin_id = rlz_admin_id_voor(administratie_id)
    module_ids = module_ids_voor(administratie_id)
    maak = client_factory or (lambda rid: client_voor_rlz_admin_id(rid).for_administration(rid))
    with maak(rlz_admin_id) as client:
        return toets_met_client(
            client,
            module_ids=module_ids,
            administratie_id=administratie_id,
            vandaag=vandaag,
            rlz_admin_id=rlz_admin_id,
            snede2=snede2,
        )


def toets_alle(
    *,
    client_factory: Callable[[str], RlzClient] | None = None,
    administratie_ids: Sequence[uuid.UUID] | None = None,
    snede2: bool = False,
) -> RlzDubbelResultaat:
    """Alle actieve RLZ-administraties (of alleen `administratie_ids`); één kapotte administratie stopt de rest niet
    (zichtbaar als fout); Odoo-administraties zichtbaar overgeslagen (A12-patroon)."""
    from app.backends.registry import RLZ_ONLY_OVERGESLAGEN, actieve_administraties_per_backend

    rlz_ids, odoo_ids = actieve_administraties_per_backend()
    if administratie_ids is not None:
        keuze = set(administratie_ids)
        rlz_ids = [aid for aid in rlz_ids if aid in keuze]
        odoo_ids = [aid for aid in odoo_ids if aid in keuze]
    rapporten: dict[uuid.UUID, RlzDubbelRapport] = {}
    fouten: dict[uuid.UUID, str] = {}
    for aid in rlz_ids:
        try:
            rapporten[aid] = toets_administratie(aid, client_factory=client_factory, snede2=snede2)
        except Exception as exc:  # noqa: BLE001 — rapporteren en door
            logger.exception("rlz_dubbel-toets mislukt voor administratie %s", aid)
            fouten[aid] = str(exc)
    return RlzDubbelResultaat(
        rapporten=rapporten, fouten=fouten, overgeslagen={aid: RLZ_ONLY_OVERGESLAGEN for aid in odoo_ids}
    )


# ---- overgang paar → cluster: acceptaties ---------------------------------------------------------


def paar_ids_uit_detail(detail: str | None) -> frozenset[uuid.UUID] | None:
    """`rlz_a=<id> rlz_b=<id>` (acceptatie-detail van de oude paar-vorm) → {id, id}; None als het geen paar is."""
    m = _PAAR_DETAIL.search(detail or "")
    if not m:
        return None
    try:
        return frozenset((uuid.UUID(m.group(1)), uuid.UUID(m.group(2))))
    except ValueError:
        return None


@dataclass(frozen=True)
class AcceptatieOverdracht:
    cluster_sleutel: str
    cluster_vingerafdruk: str
    status: str  # overgedragen | dry_run | gedeeltelijk
    paar_vingerafdrukken: tuple[str, ...]
    reden: str | None
    ongedekt: tuple[str, ...] = ()  # boekstuknummers/id's zonder geaccepteerd paar


def draag_paar_acceptaties_over(
    *, administratie_id: uuid.UUID, clusters: Sequence[DubbelCluster], dry_run: bool = False
) -> list[AcceptatieOverdracht]:
    """Bestaande PAAR-acceptaties (bron documenten, soort dubbel_in_rlz, detail `rlz_a=… rlz_b=…`) éénmalig op het
    cluster overdragen — uitsluitend als álle exemplaren van het cluster door geaccepteerde paren gedekt zijn. Nooit
    als er voor de cluster-sleutel ooit een acceptatie bestond (actief óf ingetrokken): een Beheerder die het cluster
    intrekt wint. `dry_run` = alleen rapporteren wat er zou gebeuren (lees-only CLI)."""
    from app.db.audit import record_audit_event
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.reconciliatie import service as acceptatie_service
    from app.reconciliatie.models import ReconciliatieAcceptatie

    if not clusters:
        return []
    uit: list[AcceptatieOverdracht] = []
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.scalars(
            select(ReconciliatieAcceptatie).where(
                ReconciliatieAcceptatie.administratie_id == administratie_id,
                ReconciliatieAcceptatie.bron == ACCEPTATIE_BRON,
                ReconciliatieAcceptatie.soort == SOORT,
            )
        ).all()
        cluster_vafs_bekend = {r.vingerafdruk for r in rijen if (r.detail or "").startswith("cluster=")}
        actieve_paren = [
            (r, ids) for r in rijen if r.ingetrokken_op is None and (ids := paar_ids_uit_detail(r.detail)) is not None
        ]
        if not actieve_paren:
            return []
        for cluster in clusters:
            vaf = acceptatie_service.vingerafdruk(bron=ACCEPTATIE_BRON, soort=SOORT, detail=cluster.detail)
            if vaf in cluster_vafs_bekend:
                continue
            ids = set(cluster.rlz_ids)
            dekkend = [(r, p) for r, p in actieve_paren if p <= ids]
            if not dekkend:
                continue
            gedekt: set[uuid.UUID] = set()
            for _, p in dekkend:
                gedekt |= p
            if gedekt != ids:
                ongedekt = tuple(d.boekstuk or str(d.rlz_id) for d in cluster.documenten if d.rlz_id not in gedekt)
                uit.append(
                    AcceptatieOverdracht(
                        cluster_sleutel=cluster.sleutel,
                        cluster_vingerafdruk=vaf,
                        status="gedeeltelijk",
                        paar_vingerafdrukken=tuple(r.vingerafdruk for r, _ in dekkend),
                        reden=None,
                        ongedekt=ongedekt,
                    )
                )
                continue
            eerste = dekkend[0][0]
            boekstukken = " + ".join(d.boekstuk or "?" for d in cluster.documenten)
            reden = (
                f"{eerste.reden} (overgenomen van paar-acceptatie {boekstukken}, "
                f"{eerste.geaccepteerd_op.date().isoformat()}; cluster-overgang 10-09)"
            )[:1000]
            if dry_run:
                uit.append(
                    AcceptatieOverdracht(
                        cluster_sleutel=cluster.sleutel,
                        cluster_vingerafdruk=vaf,
                        status="dry_run",
                        paar_vingerafdrukken=tuple(r.vingerafdruk for r, _ in dekkend),
                        reden=reden,
                    )
                )
                continue
            nieuw = ReconciliatieAcceptatie(
                id=uuid.uuid4(),
                administratie_id=administratie_id,
                bron=ACCEPTATIE_BRON,
                record_id=cluster.record_id,
                soort=SOORT,
                vingerafdruk=vaf,
                detail=cluster.detail,
                reden=reden,
                geaccepteerd_door=eerste.geaccepteerd_door,
            )
            session.add(nieuw)
            record_audit_event(
                session,
                actor_id=SYSTEEM_ACTOR_ID,
                module="boekhouding",
                tabel="reconciliatie_acceptatie",
                record_id=nieuw.id,
                actie="reconciliatie_acceptatie_overgedragen",
                correlatie_id=uuid.uuid4(),
                oude_waarde={
                    "paar_vingerafdrukken": [r.vingerafdruk for r, _ in dekkend],
                    "paar_details": [r.detail for r, _ in dekkend],
                },
                nieuwe_waarde={
                    "bron": ACCEPTATIE_BRON,
                    "soort": SOORT,
                    "vingerafdruk": vaf,
                    "detail": cluster.detail,
                    "reden": reden,
                    "geaccepteerd_door": str(eerste.geaccepteerd_door),
                },
                administratie_id=administratie_id,
            )
            cluster_vafs_bekend.add(vaf)
            uit.append(
                AcceptatieOverdracht(
                    cluster_sleutel=cluster.sleutel,
                    cluster_vingerafdruk=vaf,
                    status="overgedragen",
                    paar_vingerafdrukken=tuple(r.vingerafdruk for r, _ in dekkend),
                    reden=reden,
                )
            )
    return uit


# ---- overgang paar → cluster: open paar-bevindingen uit de vorige run ------------------------------


@dataclass(frozen=True)
class VervangenPaar:
    vingerafdruk: str  # de OUDE paar-vingerafdruk (blijft, zodat de delta-motor geen "verdwenen" ziet)
    rlz_ids: frozenset[uuid.UUID]
    boekstuk_a: str | None
    boekstuk_b: str | None
    uitsluiting: str  # "vervangen door cluster [vaf:…]" | "referentie uitgesloten (<reden>)"
    cluster_vingerafdruk: str | None
    detail_oud: dict[str, Any]


def vorige_paar_bevindingen(administratie_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, list[Any]]:
    """Open paar-bevindingen (`afwijking`, blok rlz_dubbel, detail rlz_id_a/rlz_id_b) uit de laatste afgeronde run,
    per administratie. Leeg als er nog geen run was."""
    from app.reconciliatie import run as run_service

    vorige = run_service.laatste_afgeronde_run()
    if vorige is None or not administratie_ids:
        return {}
    uit: dict[uuid.UUID, list[Any]] = {}
    for b in run_service.lees_bevindingen(vorige.run_id, administratie_ids=list(administratie_ids)):
        d = b.detail or {}
        if b.blok != BLOK or b.soort != "afwijking" or b.administratie_id is None:
            continue
        # Alleen de OUDE paar-vorm: acceptatie-detail `rlz_a=… rlz_b=…`. Een cluster-bevinding draagt de A/B-velden
        # óók (terugval voor oude lezers) maar heeft `cluster=…` als detail — die is nooit "vorig paar".
        if d.get("cluster") or not str(d.get("detail") or "").startswith("rlz_a="):
            continue
        if not (d.get("rlz_id_a") and d.get("rlz_id_b")):
            continue
        uit.setdefault(b.administratie_id, []).append(b)
    return uit


def vervang_paar_bevindingen(
    *, vorige: Sequence[Any], clusters: Sequence[DubbelCluster], uitgesloten: Sequence[UitgeslotenGroep]
) -> list[VervangenPaar]:
    """Puur: koppel elke oude open paar-bevinding aan een cluster (beide id's erin) of aan een uitgesloten groep
    (beide id's erin); paren waarvan een document niet meer in de toets zit worden NIET vervangen (echte
    "verdwenen"-melding)."""
    from app.reconciliatie import service as acceptatie_service

    uit: list[VervangenPaar] = []
    for b in vorige:
        d = b.detail or {}
        ids = {_als_uuid(d.get("rlz_id_a")), _als_uuid(d.get("rlz_id_b"))} - {None}
        if len(ids) != 2:
            continue
        ids_f = frozenset(ids)  # type: ignore[arg-type]
        cluster = next((c for c in clusters if ids_f <= c.rlz_ids), None)
        if cluster is not None:
            vaf = acceptatie_service.vingerafdruk(bron=ACCEPTATIE_BRON, soort=SOORT, detail=cluster.detail)
            uitsluiting = f"{UITSLUITING_VERVANGEN} [vaf:{vaf}]"
            cluster_vaf: str | None = vaf
        else:
            groep = next((g for g in uitgesloten if ids_f <= g.rlz_ids), None)
            if groep is None:
                continue
            uitsluiting = f"{UITSLUITING_REFERENTIE} ({classificatie.REDEN_LABEL.get(groep.reden, groep.reden)})"
            cluster_vaf = None
        uit.append(
            VervangenPaar(
                vingerafdruk=b.vingerafdruk,
                rlz_ids=ids_f,
                boekstuk_a=d.get("boekstuk_a"),
                boekstuk_b=d.get("boekstuk_b"),
                uitsluiting=uitsluiting,
                cluster_vingerafdruk=cluster_vaf,
                detail_oud=dict(d),
            )
        )
    return uit


# ---- CLI-blok (reconciliatie-alles) -------------------------------------------------------------


def _tellers_tekst(rapport: RlzDubbelRapport) -> str:
    delen = []
    for reden, t in rapport.uitsluiting_tellers().items():
        if t["groepen"]:
            delen.append(f"{reden} {t['groepen']} groep(en)/{t['documenten']} doc")
    return "uitgesloten: " + (", ".join(delen) if delen else "geen")


def _cluster_regel_tekst(administratie_id: uuid.UUID, cluster: DubbelCluster, beoordeeld) -> str:  # noqa: ANN001
    kenmerken = [REGEL_REFERENTIE, f"ref {cluster.referentie_norm}", f"{len(cluster.documenten)} exemplaren"]
    if cluster.waarschijnlijk_dubbel:
        kenmerken.append("waarschijnlijk dubbel")
    if cluster.concept:
        kenmerken.append("concept")
    if cluster.aantal_module:
        kenmerken.append(f"{cluster.aantal_module} via de module")
    kop = (
        f"{administratie_id} {cluster.sleutel} soort={SOORT} [vaf:{beoordeeld.vingerafdruk}]: "
        f"{' + '.join(d.boekstuk or '?' for d in cluster.documenten)} ({', '.join(kenmerken)})"
    )
    if beoordeeld.acceptatie is None:
        return kop
    return (
        f"GEACCEPTEERD {kop} — reden: {beoordeeld.acceptatie.reden} "
        f"(sinds {beoordeeld.acceptatie.geaccepteerd_op.date().isoformat()})"
    )


def _lees_only_administratie(
    aid: uuid.UUID, rapport: RlzDubbelRapport, *, naam: str | None, stdout: Callable[[str], None]
) -> None:
    """Lees-only vergelijking per administratie: paren OUD → clusters NIEUW + uitsluitingstellers + regels."""
    from app.reconciliatie import service as acceptatie_service

    beoordeeld = acceptatie_service.beoordeel(
        bron=ACCEPTATIE_BRON,
        administratie_id=aid,
        afwijkingen=[(c.record_id, SOORT, c.detail) for c in rapport.clusters],
    )
    overdrachten = draag_paar_acceptaties_over(administratie_id=aid, clusters=rapport.clusters, dry_run=True)
    zou_overdragen = {o.cluster_vingerafdruk for o in overdrachten if o.status == "dry_run"}
    open_hier = sum(1 for b in beoordeeld if b.telt_mee and b.vingerafdruk not in zou_overdragen)
    overdracht_tekst = f", waarvan {len(zou_overdragen)} via overdracht" if zou_overdragen else ""
    waarschijnlijk = sum(1 for c in rapport.clusters if c.waarschijnlijk_dubbel)
    stdout(
        f"LEES-ONLY  {aid}{f' ({naam})' if naam else ''}: {rapport.aantal_getoetst} inkoopfacturen sinds "
        f"{rapport.venster_vanaf.isoformat()} — paren OUD {len(rapport.paren)} → clusters NIEUW "
        f"{len(rapport.clusters)} ({waarschijnlijk} waarschijnlijk dubbel, {open_hier} open, "
        f"{len(beoordeeld) - open_hier} geaccepteerd{overdracht_tekst}); "
        f"{_tellers_tekst(rapport)}"
    )
    for cluster, b in zip(rapport.clusters, beoordeeld, strict=True):
        stdout(
            f"    - {'GEACCEPTEERD ' if b.vingerafdruk in zou_overdragen else ''}"
            f"{_cluster_regel_tekst(aid, cluster, b)}"
        )
    for g in rapport.uitgesloten:
        stdout(
            f"    · uitgesloten ({classificatie.REDEN_LABEL.get(g.reden, g.reden)}): {g.entity_naam or '?'} "
            f"ref {g.referentie!r} — {g.aantal_documenten} documenten, {g.aantal_bedragen} verschillende bedragen"
        )
    if rapport.snede2 is not None:
        _lees_only_snede2(aid, rapport.snede2, stdout=stdout)


def _snede2_tellers_tekst(t: dict[str, int]) -> str:
    return (
        f"paren {t['paren']}, {LABEL_MODULE_X_NIET} {t[LABEL_MODULE_X_NIET]}, "
        f"{LABEL_NIET_X_NIET} {t[LABEL_NIET_X_NIET]}, bank-bevestigd {t['bank_bevestigd']}"
    )


def _lees_only_snede2(aid: uuid.UUID, snede2: Snede2Uitkomst, *, stdout: Callable[[str], None]) -> None:
    """Snede 2 per administratie (run 2 VGG blok 2): regel per gemeld paar + tellers; bank niet gelezen zichtbaar."""
    for p in snede2.paren:
        stdout(f"    - {p.regel(aid)}")
    bank = "" if snede2.bank_gelezen else " — BANK NIET GELEZEN (PaymentTransactions weigerde; niets gefilterd)"
    stdout(f"    SNEDE2 tellers {aid}: {_snede2_tellers_tekst(snede2.tellers())}{bank}")


def _snede2_totaal(rapporten: dict[uuid.UUID, RlzDubbelRapport]) -> str | None:
    gedraaid = [r.snede2 for r in rapporten.values() if r.snede2 is not None]
    if not gedraaid:
        return None
    totaal = {"paren": 0, LABEL_MODULE_X_NIET: 0, LABEL_NIET_X_NIET: 0, "bank_bevestigd": 0}
    for u in gedraaid:
        for k, v in u.tellers().items():
            totaal[k] += v
    niet_gelezen = sum(1 for u in gedraaid if not u.bank_gelezen)
    return (
        f"SNEDE2 totaal over {len(gedraaid)} administratie(s): {_snede2_tellers_tekst(totaal)}"
        f"{f'; bank niet gelezen bij {niet_gelezen} administratie(s)' if niet_gelezen else ''}. "
        "Alleen meetlat — de dagelijkse run meldt snede 2 niet (beslispunt Peter)."
    )


def cli_blok(args, verzamelaar=None, *, stdout: Callable[[str], None] = print, stderr=None) -> int:  # noqa: ANN001
    """Blokfunctie voor `reconciliatie-alles` (zelfde contract als `_omzet_reconciliatie` in app/cli.py): print
    dezelfde soort regels, registreer élke regel als bevinding, exit 1 zodra er een open cluster of een fout is.
    Losse aanroep zonder verzamelaar blijft werken (alleen printen). `args.administratie_ids` beperkt de toets;
    `args.lees_only` = dry-run-vergelijking paren OUD → clusters NIEUW zonder bevindingen en zonder
    acceptatie-overdracht."""
    import sys

    from app.reconciliatie import service as acceptatie_service
    from app.reconciliatie import verrijking

    stderr = stderr or (lambda tekst: print(tekst, file=sys.stderr))
    administratie_ids = getattr(args, "administratie_ids", None)
    lees_only = bool(getattr(args, "lees_only", False))

    def meld(**kw) -> None:  # noqa: ANN003
        if verzamelaar is not None:
            verzamelaar.bevinding(**kw)

    def naam_van(aid: uuid.UUID) -> str | None:
        try:
            return verrijking.administratie_naam(aid)
        except Exception:  # noqa: BLE001
            return None

    # Snede 2 (run 2 VGG blok 2) leest PaymentTransactions en draait UITSLUITEND in lees-only-modus.
    resultaat = toets_alle(administratie_ids=administratie_ids, snede2=lees_only)
    for aid, reden in resultaat.overgeslagen.items():
        stdout(f"OVERGESLAGEN {aid}: {reden}")
    uitgesloten = acceptatie_service.uitgesloten_administraties()

    echte_fouten = 0
    for aid, fout in resultaat.fouten.items():
        uitsluiting = uitgesloten.get(aid)
        if uitsluiting:
            tekst = f"UITGESLOTEN {aid}: {fout} (uitgesloten: {uitsluiting})"
            stdout(tekst)
            meld(
                soort="uitgesloten",
                administratie_id=aid,
                tekst=tekst,
                detail=verrijking.administratie(aid, fout=fout, uitsluiting=uitsluiting) or None,
            )
            continue
        echte_fouten += 1
        tekst = f"FOUT       {aid}: {fout}"
        stderr(tekst)
        meld(soort="fout", administratie_id=aid, tekst=tekst, detail=verrijking.administratie(aid, fout=fout) or None)

    if lees_only:
        for aid, rapport in resultaat.rapporten.items():
            _lees_only_administratie(aid, rapport, naam=naam_van(aid), stdout=stdout)
        vorige = vorige_paar_bevindingen(list(resultaat.rapporten))
        te_vervangen = sum(
            len(vervang_paar_bevindingen(vorige=vorige.get(aid, []), clusters=r.clusters, uitgesloten=r.uitgesloten))
            for aid, r in resultaat.rapporten.items()
        )
        totaal_oud = sum(len(r.paren) for r in resultaat.rapporten.values())
        totaal_nieuw = sum(len(r.clusters) for r in resultaat.rapporten.values())
        stdout(
            f"\nLEES-ONLY: {len(resultaat.rapporten)} administratie(s) — paren OUD {totaal_oud} → clusters NIEUW "
            f"{totaal_nieuw}; {sum(len(v) for v in vorige.values())} open paar-bevinding(en) in de vorige run, waarvan "
            f"{te_vervangen} bij de eerstvolgende run vervangen worden. Niets geschreven, niets gemaild."
        )
        totaal_snede2 = _snede2_totaal(resultaat.rapporten)
        if totaal_snede2:
            stdout(totaal_snede2)
        return 1 if echte_fouten else 0

    # Overgang: open paar-bevindingen uit de vorige run → vervangen (eigen vingerafdruk, soort uitgesloten).
    try:
        vorige = vorige_paar_bevindingen(list(resultaat.rapporten))
    except Exception:  # noqa: BLE001 — de overgang mag de toets nooit laten omvallen
        logger.exception("vorige paar-bevindingen niet gelezen")
        vorige = {}

    open_totaal = 0
    geaccepteerd_totaal = 0
    getoetst_totaal = 0
    clusters_totaal = 0
    vervangen_totaal = 0
    for aid, rapport in resultaat.rapporten.items():
        getoetst_totaal += rapport.aantal_getoetst
        clusters_totaal += len(rapport.clusters)
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(rapport.aantal_getoetst)
        uitsluiting = uitgesloten.get(aid)
        administratie_naam = naam_van(aid)

        try:
            overdrachten = draag_paar_acceptaties_over(administratie_id=aid, clusters=rapport.clusters)
        except Exception as exc:  # noqa: BLE001 — zichtbaar, nooit stil; de toets zelf gaat door
            logger.exception("acceptatie-overdracht mislukt voor %s", aid)
            stderr(f"FOUT       {aid}: acceptatie-overdracht paar → cluster mislukt: {exc}")
            overdrachten = []
        gedeeltelijk = {o.cluster_vingerafdruk: o for o in overdrachten if o.status == "gedeeltelijk"}
        for o in overdrachten:
            if o.status == "overgedragen":
                stdout(
                    f"    · acceptatie overgedragen op cluster [vaf:{o.cluster_vingerafdruk}] ← paar "
                    f"{', '.join(o.paar_vingerafdrukken)}"
                )

        vervangen = vervang_paar_bevindingen(
            vorige=vorige.get(aid, []), clusters=rapport.clusters, uitgesloten=rapport.uitgesloten
        )
        for v in vervangen:
            vervangen_totaal += 1
            tekst = (
                f"UITGESLOTEN {aid}: paar {v.boekstuk_a or '?'} + {v.boekstuk_b or '?'} [vaf:{v.vingerafdruk}] "
                f"(uitgesloten: {v.uitsluiting})"
            )
            stdout(f"    - {tekst}")
            meld(
                soort="uitgesloten",
                administratie_id=aid,
                tekst=tekst,
                vingerafdruk=v.vingerafdruk,
                detail={
                    "afwijking_soort": SOORT,
                    "uitsluiting": v.uitsluiting,
                    "vervangen_door_vingerafdruk": v.cluster_vingerafdruk,
                    "boekstuk_a": v.boekstuk_a,
                    "boekstuk_b": v.boekstuk_b,
                    "rlz_id_a": v.detail_oud.get("rlz_id_a"),
                    "rlz_id_b": v.detail_oud.get("rlz_id_b"),
                    "leverancier_naam": v.detail_oud.get("leverancier_naam"),
                    "administratie_naam": administratie_naam,
                },
            )

        if not rapport.clusters:
            stdout(
                f"OK         {aid}: {rapport.aantal_getoetst} inkoopfacturen sinds {rapport.venster_vanaf.isoformat()} "
                f"({rapport.aantal_module} van de module, {rapport.aantal_zonder_crediteur} zonder crediteur), "
                f"geen clusters met dezelfde referentie; {_tellers_tekst(rapport)}"
            )
            continue
        beoordeeld = acceptatie_service.beoordeel(
            bron=ACCEPTATIE_BRON,
            administratie_id=aid,
            afwijkingen=[(c.record_id, SOORT, c.detail) for c in rapport.clusters],
        )
        open_hier = sum(1 for b in beoordeeld if b.telt_mee)
        waarschijnlijk = sum(1 for c in rapport.clusters if c.waarschijnlijk_dubbel)
        kop = "UITGESLOTEN" if uitsluiting else ("AFWIJKING " if open_hier else "OK        ")
        stdout(
            f"{kop} {aid}: {rapport.aantal_getoetst} inkoopfacturen sinds {rapport.venster_vanaf.isoformat()}, "
            f"{len(rapport.clusters)} cluster(s) met dezelfde referentie ({waarschijnlijk} waarschijnlijk dubbel; "
            f"{open_hier} open, {len(beoordeeld) - open_hier} geaccepteerd); {_tellers_tekst(rapport)}"
            f"{f' — telt niet mee ({uitsluiting})' if uitsluiting else ''}"
        )
        for cluster, b in zip(rapport.clusters, beoordeeld, strict=True):
            regel = _cluster_regel_tekst(aid, cluster, b)
            if uitsluiting:
                soort = "uitgesloten"
                tekst = f"    - UITGESLOTEN {regel}"
                stdout(tekst)
            elif b.telt_mee:
                soort = "afwijking"
                open_totaal += 1
                tekst = f"    - AFWIJKING  {regel}"
                stderr(tekst)
            else:
                soort = "geaccepteerd"
                geaccepteerd_totaal += 1
                tekst = f"    - {regel}"
                stdout(tekst)
            deels = gedeeltelijk.get(b.vingerafdruk)
            meld(
                soort=soort,
                administratie_id=aid,
                tekst=tekst.strip(),
                vingerafdruk=b.vingerafdruk,
                detail={
                    "bron": ACCEPTATIE_BRON,
                    "record_id": str(b.record_id),
                    "afwijking_soort": SOORT,
                    "detail": b.detail,
                    "geaccepteerd": not b.telt_mee,
                    "uitsluiting": uitsluiting,
                    **cluster.context(
                        administratie_naam=administratie_naam,
                        acceptatie_gedeeltelijk=deels.ongedekt if deels else None,
                    ),
                },
            )

    stdout(
        f"\n{len(resultaat.rapporten)}/{len(resultaat.rapporten) + len(resultaat.fouten)} administraties getoetst, "
        f"{getoetst_totaal} inkoopfacturen, {clusters_totaal} cluster(s) met dezelfde referentie "
        f"({open_totaal} open, {geaccepteerd_totaal} geaccepteerd)"
        f"{f'; {vervangen_totaal} paar-bevinding(en) uit de vorige run vervangen' if vervangen_totaal else ''}."
    )
    if echte_fouten or open_totaal:
        stderr(f"{open_totaal} open cluster(s) en {echte_fouten} mislukte administratie(s) in de RLZ-dubbel-toets")
        return 1
    return 0


def paren_als_tekst(rapport: RlzDubbelRapport) -> Sequence[str]:
    """Leesbare regels voor het live/dry-run-script (geen bevindingen, geen DB): clusters NIEUW + paren OUD."""
    uit = [
        f"{rapport.aantal_getoetst} inkoopfacturen sinds {rapport.venster_vanaf.isoformat()} "
        f"({rapport.aantal_module} van de module, {rapport.aantal_zonder_crediteur} zonder crediteur) — "
        f"{len(rapport.clusters)} cluster(s) (paren OUD: {len(rapport.paren)}); {_tellers_tekst(rapport)}"
    ]
    for c in rapport.clusters:
        exemplaren = "; ".join(
            f"{d.boekstuk or '?'} ({d.datum}, {d.bedrag}, status {d.status}{', module' if d.van_module else ''})"
            for d in c.documenten
        )
        uit.append(
            f"  - {c.entity_naam or '?'} ref {c.referentie_norm}"
            f"{' WAARSCHIJNLIJK DUBBEL' if c.waarschijnlijk_dubbel else ''}: "
            f"{exemplaren} [{c.sleutel}]"
        )
    for g in rapport.uitgesloten:
        uit.append(
            f"  · uitgesloten ({g.reden}): {g.entity_naam or '?'} ref {g.referentie!r} — {g.aantal_documenten} doc, "
            f"{g.aantal_bedragen} bedragen"
        )
    return uit
