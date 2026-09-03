"""Crediteuren-dubbelen v2 — servicelaag (design-ronde 03-09, mockup crediteuren-dubbelen-v2.html ①–⑧).

Kantoorbreed onder RLS: itereer over de administraties in scope van de actor (`mijn_administraties`) en lees per
administratie in `scoped_session(aid, actor_id=…)`; de BESTAANDE motor `dubbele_crediteuren` levert de groepen,
hier worden ze gebundeld tot clusters (zelfde ledenset over meerdere sleutels = één rij mét meerdere chips),
verrijkt met kaartgegevens (aantal boekingen, laatst geboekt) en gesorteerd: zwaarste sleutel eerst
(btw > KvK > IBAN > naam), dan laatst geboekt, dan aantal boekingen.

Acties (allemaal zonder RLZ-write, nooit verwijderen):
- "Voorkeur kiezen & rest archiveren…" → LIVE open-posten-toets tegen verse RLZ-staat (leesroute; onbereikbaar =
  fail-closed), daarna in één transactie: werklijst-regel (pad "API werkt niet", STAP-0 03-09), boekingsgeheugen
  + crediteur_kenmerk (+ vertrouwde IBAN's) naar de voorkeur, audit per verhuisd record.
- "Geen dubbel — afmelden" → afmelding-rij per combinatie (reden verplicht) + audit; de lijst filtert 'm eruit.
- Dagelijkse hertoets (sync-alles): leest `Vendors/{id}?fields=all` — `IsArchived: true` óf 404 = gearchiveerd →
  werklijst-regel gedaan mét audit. Handmatig afvinken kan óók.
"""

from __future__ import annotations

import contextlib
import logging
import uuid
from collections import defaultdict
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.service import mijn_administraties
from app.crediteuren.models import (
    SLEUTEL_SOORTEN,
    CrediteurArchiveerWerklijst,
    CrediteurDubbelAfmelding,
    combinatie_sleutel,
)
from app.db.audit import record_audit_event
from app.db.models import Administratie, GebruikerRol
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.crediteur_kenmerk import DubbelGroep, dubbele_crediteuren
from app.documenten.models import Boekvoorstel, CrediteurKenmerk, Document, DocumentStatus, LeverancierIban
from app.geheugen.models import BoekingObservatie, ObservatieBron
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.sync.models import VendorCache

logger = logging.getLogger(__name__)

PER_PAGINA = 25
SOORT_RANG = {soort: i for i, soort in enumerate(SLEUTEL_SOORTEN)}
SOORT_CHIP = {
    "btw_nummer": "zelfde btw-nummer",
    "kvk_nummer": "zelfde KvK-nummer",
    "iban": "zelfde IBAN",
    "naam": "naam ≈",
}
CHIP_KVK_VERSCHILT = "verschillend KvK — géén dubbel"

# Vast, NOOIT wijzigen: deterministische id's voor verhuisde geheugen-observaties (idempotente her-run).
_VERHUIS_NAMESPACE = uuid.UUID("3f0d6a52-8b1e-4c1c-9a6f-2d7e5b1c0a44")


class CrediteurenFout(Exception):
    pass


class OnbekendeAdministratie(CrediteurenFout):
    pass


class OngeldigeInvoer(CrediteurenFout):
    pass


class OpenPostenBlokkeren(CrediteurenFout):
    def __init__(self, posten: dict[uuid.UUID, list[OpenPost]]) -> None:
        self.posten = posten
        aantal = sum(len(p) for p in posten.values())
        super().__init__(
            f"{aantal} open post(en) op een te archiveren crediteur — eerst afletteren in Reeleezee, daarna archiveren"
        )


class OpenPostenToetsMislukt(CrediteurenFout):
    pass


# ----------------------------------------------------------------------------- datatypes


@dataclass(frozen=True)
class Kaart:
    vendor_id: uuid.UUID
    naam: str | None
    btw_nummer: str | None
    kvk_nummer: str | None
    ibans: list[str]
    aantal_boekingen: int
    laatst_geboekt: date | None

    @property
    def compleetheid(self) -> int:
        return int(bool(self.btw_nummer)) + int(bool(self.kvk_nummer)) + int(bool(self.ibans))


@dataclass(frozen=True)
class Klaargezet:
    werklijst_id: uuid.UUID
    voorkeur_vendor_id: uuid.UUID
    namen: list[str]
    aangemaakt_op: datetime


@dataclass(frozen=True)
class Cluster:
    cluster_id: str
    administratie_id: uuid.UUID
    administratie_naam: str
    soort: str
    sleutel: str
    sleutels: list[tuple[str, str]]
    chips: list[str]
    crediteuren: list[Kaart]
    aantal_boekingen: int
    laatst_geboekt: date | None
    kvk_verschilt: bool
    afmelden_primair: bool
    voorkeur_suggestie: uuid.UUID
    klaargezet: Klaargezet | None

    @property
    def vendor_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(k.vendor_id for k in self.crediteuren)


@dataclass(frozen=True)
class Tellers:
    clusters: int  # nog te behandelen (niet klaargezet)
    klaargezet: int
    administraties: int


@dataclass(frozen=True)
class FacetAdministratie:
    administratie_id: uuid.UUID
    naam: str
    aantal: int


@dataclass(frozen=True)
class Facetten:
    administraties: list[FacetAdministratie]
    sleutels: dict[str, int]


@dataclass(frozen=True)
class Lijst:
    rijen: list[Cluster]
    totaal: int
    pagina: int
    per_pagina: int
    tellers: Tellers
    facetten: Facetten


@dataclass(frozen=True)
class OpenPost:
    rlz_document_id: str
    referentie: str | None
    datum: str | None
    open_bedrag: Decimal


@dataclass(frozen=True)
class ClusterDetail:
    administratie_id: uuid.UUID
    administratie_naam: str
    crediteuren: list[Kaart]
    voorkeur_suggestie: uuid.UUID
    open_posten: dict[uuid.UUID, list[OpenPost]]
    toets_ok: bool
    toets_fout: str | None


@dataclass(frozen=True)
class WerklijstRegel:
    id: uuid.UUID
    administratie_id: uuid.UUID
    administratie_naam: str
    voorkeur_vendor_id: uuid.UUID
    voorkeur_naam: str | None
    te_archiveren: list[dict]
    status: str
    aangemaakt_op: datetime
    gedaan_op: datetime | None
    gedaan_bron: str | None
    laatste_hertoets_op: datetime | None
    hertoets_detail: dict | None


@dataclass
class Actor:
    """Minimale actor-representatie (id + rol) — de router geeft `CurrentGebruiker` door, tests een Actor."""

    id: uuid.UUID
    rol: GebruikerRol


# ----------------------------------------------------------------------------- scope


def administraties_in_scope(actor: Actor) -> list[tuple[uuid.UUID, str]]:
    return [(a.id, a.naam) for a in mijn_administraties(actor_id=actor.id, rol=GebruikerRol(actor.rol))]


def _administratie_in_scope(actor: Actor, administratie_id: uuid.UUID) -> str:
    for aid, naam in administraties_in_scope(actor):
        if aid == administratie_id:
            return naam
    raise OnbekendeAdministratie(f"Onbekende administratie of buiten je scope: {administratie_id}")


# ----------------------------------------------------------------------------- kaarten


def _kaarten(session: Session, administratie_id: uuid.UUID, groepen: list[DubbelGroep]) -> dict[uuid.UUID, Kaart]:
    """Kaartgegevens per crediteur uit de motor-groepen + boekingsstatistiek (app-geboekte documenten én
    RLZ-boekingsgeheugen per boekstuk) — één set queries per administratie."""
    basis: dict[uuid.UUID, tuple] = {}
    for g in groepen:
        for c in g.crediteuren:
            basis[c.vendor_id] = (c.naam, c.btw_nummer, c.kvk_nummer, list(c.ibans))
    if not basis:
        return {}
    ids = list(basis)
    app_stat = {
        vendor_id: (int(aantal), laatste)
        for vendor_id, aantal, laatste in session.execute(
            select(Boekvoorstel.vendor_id, func.count(Document.id), func.max(Boekvoorstel.factuurdatum))
            .join(Document, Document.id == Boekvoorstel.document_id)
            .where(
                Document.administratie_id == administratie_id,
                Document.status == DocumentStatus.GEBOEKT,
                Boekvoorstel.vendor_id.in_(ids),
            )
            .group_by(Boekvoorstel.vendor_id)
        ).all()
    }
    seed_stat = {
        vendor_id: (int(aantal), laatste)
        for vendor_id, aantal, laatste in session.execute(
            select(
                BoekingObservatie.vendor_id,
                func.count(func.distinct(BoekingObservatie.boekstuk_ref)),
                func.max(BoekingObservatie.bron_datum),
            )
            .where(
                BoekingObservatie.administratie_id == administratie_id,
                BoekingObservatie.bron == ObservatieBron.RLZ_SEED.value,
                BoekingObservatie.vendor_id.in_(ids),
            )
            .group_by(BoekingObservatie.vendor_id)
        ).all()
    }
    uit: dict[uuid.UUID, Kaart] = {}
    for vendor_id, (naam, btw, kvk, ibans) in basis.items():
        a_n, a_d = app_stat.get(vendor_id, (0, None))
        s_n, s_d = seed_stat.get(vendor_id, (0, None))
        data = [d for d in (a_d, s_d) if d is not None]
        uit[vendor_id] = Kaart(
            vendor_id=vendor_id,
            naam=naam,
            btw_nummer=btw,
            kvk_nummer=kvk,
            ibans=ibans,
            aantal_boekingen=a_n + s_n,
            laatst_geboekt=max(data) if data else None,
        )
    return uit


def _voorkeur_suggestie(kaarten: list[Kaart]) -> uuid.UUID:
    """Vooringevuld: meest gebruikt (aantal boekingen) + meest complete kaart (btw/KvK/IBAN aanwezig), dan
    laatst geboekt, dan naam — deterministisch (ontwerpnotitie ②)."""
    return max(
        kaarten,
        key=lambda k: (
            k.aantal_boekingen,
            k.compleetheid,
            k.laatst_geboekt or date.min,
            -len(k.naam or ""),
            str(k.vendor_id),
        ),
    ).vendor_id


def _kvk_verschilt(kaarten: list[Kaart]) -> bool:
    nummers = {k.kvk_nummer for k in kaarten if k.kvk_nummer}
    return len(nummers) >= 2


# ----------------------------------------------------------------------------- clusters


def _clusters_voor_administratie(actor: Actor, administratie_id: uuid.UUID, administratie_naam: str) -> list[Cluster]:
    groepen = dubbele_crediteuren(administratie_id=administratie_id)
    if not groepen:
        return []
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        kaarten = _kaarten(session, administratie_id, groepen)
        afgemeld = set(
            session.scalars(
                select(CrediteurDubbelAfmelding.combinatie).where(
                    CrediteurDubbelAfmelding.administratie_id == administratie_id
                )
            )
        )
        open_werklijst = list(
            session.scalars(
                select(CrediteurArchiveerWerklijst).where(
                    CrediteurArchiveerWerklijst.administratie_id == administratie_id,
                    CrediteurArchiveerWerklijst.status == "open",
                )
            )
        )
    klaargezet_per_vendor: dict[uuid.UUID, Klaargezet] = {}
    for rij in open_werklijst:
        info = Klaargezet(
            werklijst_id=rij.id,
            voorkeur_vendor_id=rij.voorkeur_vendor_id,
            namen=[str(t.get("naam") or t.get("vendor_id")) for t in (rij.te_archiveren or [])],
            aangemaakt_op=rij.aangemaakt_op,
        )
        for t in rij.te_archiveren or []:
            try:
                klaargezet_per_vendor[uuid.UUID(str(t.get("vendor_id")))] = info
            except ValueError:
                continue

    # Bundelen: zelfde ledenset over meerdere sleutels = één cluster mét meerdere chips.
    per_set: dict[frozenset[uuid.UUID], list[tuple[str, str]]] = defaultdict(list)
    for g in groepen:
        per_set[frozenset(c.vendor_id for c in g.crediteuren)].append((g.soort, g.sleutel))
    clusters: list[Cluster] = []
    for leden, sleutels in per_set.items():
        if combinatie_sleutel(leden) in afgemeld:
            continue
        sleutels = sorted(sleutels, key=lambda s: (SOORT_RANG[s[0]], s[1]))
        soort, sleutel = sleutels[0]
        kaartlijst = sorted((kaarten[v] for v in leden if v in kaarten), key=lambda k: (k.naam or "").lower())
        if len(kaartlijst) < 2:
            continue
        kvk_verschilt = soort == "naam" and _kvk_verschilt(kaartlijst)
        chips = [SOORT_CHIP[s] for s, _ in sleutels]
        if kvk_verschilt:
            chips.append(CHIP_KVK_VERSCHILT)
        data = [k.laatst_geboekt for k in kaartlijst if k.laatst_geboekt]
        klaargezet = next(
            (klaargezet_per_vendor[k.vendor_id] for k in kaartlijst if k.vendor_id in klaargezet_per_vendor), None
        )
        clusters.append(
            Cluster(
                cluster_id=f"{administratie_id}:{soort}:{sleutel}",
                administratie_id=administratie_id,
                administratie_naam=administratie_naam,
                soort=soort,
                sleutel=sleutel,
                sleutels=sleutels,
                chips=chips,
                crediteuren=kaartlijst,
                aantal_boekingen=sum(k.aantal_boekingen for k in kaartlijst),
                laatst_geboekt=max(data) if data else None,
                kvk_verschilt=kvk_verschilt,
                afmelden_primair=kvk_verschilt,
                voorkeur_suggestie=_voorkeur_suggestie(kaartlijst),
                klaargezet=klaargezet,
            )
        )
    return clusters


def _sorteer(clusters: list[Cluster]) -> list[Cluster]:
    return sorted(
        clusters,
        key=lambda c: (
            SOORT_RANG[c.soort],
            -(c.laatst_geboekt.toordinal() if c.laatst_geboekt else 0),
            -c.aantal_boekingen,
            c.administratie_naam.lower(),
            (c.crediteuren[0].naam or "").lower(),
        ),
    )


def alle_clusters(actor: Actor) -> list[Cluster]:
    uit: list[Cluster] = []
    for aid, naam in administraties_in_scope(actor):
        uit.extend(_clusters_voor_administratie(actor, aid, naam))
    return _sorteer(uit)


def _tellers(clusters: list[Cluster]) -> Tellers:
    return Tellers(
        clusters=sum(1 for c in clusters if c.klaargezet is None),
        klaargezet=sum(1 for c in clusters if c.klaargezet is not None),
        administraties=len({c.administratie_id for c in clusters}),
    )


def stand(actor: Actor) -> Tellers:
    """Werkvoorraad-teller "crediteur-dubbelen (N)" (ontwerpnotitie ⑧) — zelfde bron als de lijst."""
    return _tellers(alle_clusters(actor))


def _zoek_treffer(c: Cluster, zoek: str) -> bool:
    if zoek in c.administratie_naam.lower():
        return True
    for k in c.crediteuren:
        velden = [k.naam or "", k.btw_nummer or "", k.kvk_nummer or "", *k.ibans]
        if any(zoek in v.lower() for v in velden):
            return True
    return False


def lijst(
    actor: Actor,
    *,
    q: str = "",
    pagina: int = 1,
    per_pagina: int = PER_PAGINA,
    administratie_id: uuid.UUID | None = None,
    sleutel: str | None = None,
) -> Lijst:
    if sleutel and sleutel not in SLEUTEL_SOORTEN:
        raise OngeldigeInvoer(f"Onbekende sleutel: {sleutel}")
    clusters = alle_clusters(actor)
    per_admin: dict[uuid.UUID, FacetAdministratie] = {}
    per_sleutel: dict[str, int] = defaultdict(int)
    for c in clusters:
        f = per_admin.get(c.administratie_id)
        per_admin[c.administratie_id] = FacetAdministratie(
            c.administratie_id, c.administratie_naam, (f.aantal if f else 0) + 1
        )
        per_sleutel[c.soort] += 1
    facetten = Facetten(
        administraties=sorted(per_admin.values(), key=lambda f: f.naam.lower()),
        sleutels={s: per_sleutel[s] for s in SLEUTEL_SOORTEN if per_sleutel.get(s)},
    )
    selectie = clusters
    if administratie_id is not None:
        selectie = [c for c in selectie if c.administratie_id == administratie_id]
    if sleutel:
        selectie = [c for c in selectie if c.soort == sleutel]
    zoek = q.strip().lower()
    if zoek:
        selectie = [c for c in selectie if _zoek_treffer(c, zoek)]
    start = max(pagina - 1, 0) * per_pagina
    return Lijst(
        rijen=selectie[start : start + per_pagina],
        totaal=len(selectie),
        pagina=pagina,
        per_pagina=per_pagina,
        tellers=_tellers(clusters),
        facetten=facetten,
    )


# ----------------------------------------------------------------------------- RLZ-leesroutes


def _open_client(administratie_id: uuid.UUID) -> RlzClient:
    """Eigen seam (tests monkeypatchen dit): één RlzClient per administratie via de credential-store."""
    return client_voor_rlz_admin_id(rlz_admin_id_voor(administratie_id))


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except (InvalidOperation, ValueError):
        return None


def open_posten_van_crediteur(client: RlzClient, vendor_id: uuid.UUID) -> list[OpenPost]:
    """Verse RLZ-staat: PurchaseInvoices op deze Entity mét Status 2 (Open) en BaseRemainingAmount ≠ 0.
    `$filter=Status eq 2` geeft in RLZ een 400 (enum-typering, api-verkenning) — status dus lokaal; het
    BaseRemainingAmount-predicaat is een optimalisatie mét terugval op een Entity-only filter bij 400."""
    basis = f"Entity/id eq {vendor_id}"
    try:
        rijen = client.get("PurchaseInvoices", params={"$filter": f"{basis} and BaseRemainingAmount ne 0"}).get(
            "value", []
        )
    except RlzApiError as exc:
        if exc.status_code != 400:
            raise
        rijen = client.get("PurchaseInvoices", params={"$filter": basis}).get("value", [])
    posten: list[OpenPost] = []
    for f in rijen:
        if f.get("Status") not in (2, "2"):
            continue
        rest = _als_decimal(f.get("BaseRemainingAmount"))
        if rest is None or rest == 0:
            continue
        posten.append(
            OpenPost(
                rlz_document_id=str(f.get("id") or ""),
                referentie=(str(f.get("Reference")) if f.get("Reference") else None),
                datum=(str(f.get("Date"))[:10] if f.get("Date") else None),
                open_bedrag=rest,
            )
        )
    return posten


def _toets_open_posten(
    administratie_id: uuid.UUID, vendor_ids: list[uuid.UUID]
) -> tuple[dict[uuid.UUID, list[OpenPost]], str | None]:
    """Per crediteur de open posten; (resultaat, fout) — fout gevuld = toets mislukt (fail-closed)."""
    uit: dict[uuid.UUID, list[OpenPost]] = {}
    try:
        client = _open_client(administratie_id)
    except Exception as exc:  # noqa: BLE001 — credential-/configfout is óók "toets mislukt"
        return uit, f"Reeleezee-verbinding niet beschikbaar: {exc}"
    try:
        for vendor_id in vendor_ids:
            uit[vendor_id] = open_posten_van_crediteur(client, vendor_id)
    except Exception as exc:  # noqa: BLE001 — RLZ onbereikbaar = toets mislukt, nooit stil groen
        return uit, f"Open-posten-toets in Reeleezee mislukt: {exc}"
    finally:
        with contextlib.suppress(Exception):
            client.close()
    return uit, None


# ----------------------------------------------------------------------------- cluster-detail


def _kaarten_voor(actor: Actor, administratie_id: uuid.UUID, vendor_ids: list[uuid.UUID]) -> list[Kaart]:
    groepen = dubbele_crediteuren(administratie_id=administratie_id)
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        kaarten = _kaarten(session, administratie_id, groepen)
        namen = dict(
            session.execute(select(VendorCache.id, VendorCache.naam).where(VendorCache.id.in_(vendor_ids))).all()
        )
    uit: list[Kaart] = []
    for v in vendor_ids:
        if v in kaarten:
            uit.append(kaarten[v])
        elif v in namen:
            uit.append(Kaart(v, namen[v], None, None, [], 0, None))
        else:
            raise OngeldigeInvoer(f"Onbekende crediteur in deze administratie: {v}")
    return uit


def cluster_detail(actor: Actor, *, administratie_id: uuid.UUID, vendor_ids: list[uuid.UUID]) -> ClusterDetail:
    """Dialooggegevens (ontwerpnotitie ②/③): kaarten, vooringevulde voorkeur en de LIVE open-posten-toets per
    crediteur (blokkerend signaal "eerst afletteren"); toets mislukt = fail-closed in de UI én op de server."""
    naam = _administratie_in_scope(actor, administratie_id)
    vendor_ids = list(dict.fromkeys(vendor_ids))
    if len(vendor_ids) < 2:
        raise OngeldigeInvoer("Een cluster bestaat uit minstens twee crediteuren")
    kaarten = _kaarten_voor(actor, administratie_id, vendor_ids)
    posten, fout = _toets_open_posten(administratie_id, vendor_ids)
    return ClusterDetail(
        administratie_id=administratie_id,
        administratie_naam=naam,
        crediteuren=kaarten,
        voorkeur_suggestie=_voorkeur_suggestie(kaarten),
        open_posten=posten,
        toets_ok=fout is None,
        toets_fout=fout,
    )


# ----------------------------------------------------------------------------- archiveren (werklijst + verhuizen)


def _verhuis_geheugen(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    bron_vendor_id: uuid.UUID,
    voorkeur: uuid.UUID,
    actor_id: uuid.UUID,
    correlatie: uuid.UUID,
) -> int:
    """Boekingsgeheugen is append-only (grant zonder UPDATE): élke observatie van de te archiveren crediteur krijgt
    een deterministische kopie op de voorkeur (uuid5 op de bron-id — een her-run legt niets dubbel vast); de
    bron-rijen blijven staan (inert: de crediteur wordt gearchiveerd). Eén audit per bron-crediteur mét de
    volledige id-lijst oud→nieuw."""
    bron_rijen = list(
        session.scalars(
            select(BoekingObservatie).where(
                BoekingObservatie.administratie_id == administratie_id, BoekingObservatie.vendor_id == bron_vendor_id
            )
        )
    )
    if not bron_rijen:
        return 0
    nieuwe_ids = [uuid.uuid5(_VERHUIS_NAMESPACE, f"verhuisd:{r.id}:{voorkeur}") for r in bron_rijen]
    bestaand = set(session.scalars(select(BoekingObservatie.id).where(BoekingObservatie.id.in_(nieuwe_ids))))
    verhuisd: list[tuple[str, str]] = []
    for rij, nieuw_id in zip(bron_rijen, nieuwe_ids, strict=True):
        if nieuw_id in bestaand:
            continue
        session.add(
            BoekingObservatie(
                id=nieuw_id,
                administratie_id=administratie_id,
                vendor_id=voorkeur,
                regel_sleutel=rij.regel_sleutel,
                regel_omschrijving_raw=rij.regel_omschrijving_raw,
                gb_id=rij.gb_id,
                btw_id=rij.btw_id,
                project_id=rij.project_id,
                bron=rij.bron,
                bron_datum=rij.bron_datum,
                boekstuk_ref=rij.boekstuk_ref,
            )
        )
        verhuisd.append((str(rij.id), str(nieuw_id)))
    if verhuisd:
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="boeking_observatie",
            record_id=bron_vendor_id,
            actie="crediteur_geheugen_verhuisd",
            correlatie_id=correlatie,
            oude_waarde={"vendor_id": str(bron_vendor_id), "observatie_ids": [o for o, _ in verhuisd]},
            nieuwe_waarde={
                "vendor_id": str(voorkeur),
                "observatie_ids": [n for _, n in verhuisd],
                "aantal": len(verhuisd),
            },
            administratie_id=administratie_id,
        )
    return len(verhuisd)


def _verhuis_kenmerk(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    bron_vendor_id: uuid.UUID,
    voorkeur: uuid.UUID,
    actor_id: uuid.UUID,
    correlatie: uuid.UUID,
) -> bool:
    """btw-/KvK-kenmerk op de voorkeur zetten als die leeg is; 'handmatig' op de voorkeur wint altijd, een
    handmatig kenmerk van de bron wint boven 'factuur'. Audit oud→nieuw per verhuisd record."""
    bron = session.get(CrediteurKenmerk, (administratie_id, bron_vendor_id))
    if bron is None or (not bron.btw_nummer and not bron.kvk_nummer):
        return False
    doel = session.get(CrediteurKenmerk, (administratie_id, voorkeur))
    oud = {"btw_nummer": doel.btw_nummer if doel else None, "kvk_nummer": doel.kvk_nummer if doel else None}
    if doel is None:
        doel = CrediteurKenmerk(administratie_id=administratie_id, vendor_id=voorkeur)
        session.add(doel)
    gewijzigd = False
    if bron.btw_nummer and not doel.btw_nummer:
        doel.btw_nummer = bron.btw_nummer
        doel.btw_nummer_geverifieerd = bron.btw_nummer_geverifieerd
        doel.btw_nummer_bron = bron.btw_nummer_bron or "factuur"
        gewijzigd = True
    if bron.kvk_nummer and not doel.kvk_nummer:
        doel.kvk_nummer = bron.kvk_nummer
        doel.kvk_nummer_bron = bron.kvk_nummer_bron or "factuur"
        gewijzigd = True
    if not gewijzigd:
        return False
    doel.laatst_uit_document_id = bron.laatst_uit_document_id
    doel.bijgewerkt_door = actor_id
    doel.bijgewerkt_op = datetime.now(UTC)
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="crediteur_kenmerk",
        record_id=voorkeur,
        actie="crediteur_kenmerk_verhuisd",
        correlatie_id=correlatie,
        oude_waarde={**oud, "van_vendor_id": str(bron_vendor_id)},
        nieuwe_waarde={"btw_nummer": doel.btw_nummer, "kvk_nummer": doel.kvk_nummer},
        administratie_id=administratie_id,
    )
    return True


def _verhuis_ibans(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    bron_vendor_id: uuid.UUID,
    voorkeur: uuid.UUID,
    actor_id: uuid.UUID,
    correlatie: uuid.UUID,
) -> int:
    """Vertrouwde IBAN's van de bron óók op de voorkeur (anders geeft de eerste factuur op de voorkeur een valse
    IBAN-wissel-blokkade). Kopie per record mét audit; bron blijft staan."""
    bron_rijen = list(
        session.scalars(
            select(LeverancierIban).where(
                LeverancierIban.administratie_id == administratie_id, LeverancierIban.vendor_id == bron_vendor_id
            )
        )
    )
    n = 0
    for rij in bron_rijen:
        if session.get(LeverancierIban, (administratie_id, voorkeur, rij.iban)) is not None:
            continue
        session.add(
            LeverancierIban(
                administratie_id=administratie_id,
                vendor_id=voorkeur,
                iban=rij.iban,
                bron=rij.bron,
                bevestigd_door=rij.bevestigd_door,
            )
        )
        record_audit_event(
            session,
            actor_id=actor_id,
            module="boekhouding",
            tabel="leverancier_iban",
            record_id=voorkeur,
            actie="crediteur_iban_verhuisd",
            correlatie_id=correlatie,
            oude_waarde={"vendor_id": str(bron_vendor_id), "iban": rij.iban},
            nieuwe_waarde={"vendor_id": str(voorkeur), "iban": rij.iban, "bron": rij.bron},
            administratie_id=administratie_id,
        )
        n += 1
    return n


@dataclass(frozen=True)
class ArchiveerUitkomst:
    werklijst_id: uuid.UUID
    voorkeur_naam: str | None
    te_archiveren_namen: list[str]
    geheugen_verhuisd: int
    kenmerk_verhuisd: bool
    ibans_verhuisd: int
    al_klaargezet: bool


def archiveer(
    actor: Actor, *, administratie_id: uuid.UUID, voorkeur_vendor_id: uuid.UUID, overige_vendor_ids: list[uuid.UUID]
) -> ArchiveerUitkomst:
    """ "Voorkeur kiezen & rest archiveren…" (ontwerpnotities ②③④⑥, pad "API werkt niet"): server hertoetst de
    open posten tegen verse RLZ-staat (blokkerend / fail-closed), daarna in één transactie de werklijst-regel
    én het verhuizen van geheugen + kenmerk + IBAN's naar de voorkeur, alles geauditeerd. Geen RLZ-write."""
    _administratie_in_scope(actor, administratie_id)
    overige = [v for v in dict.fromkeys(overige_vendor_ids) if v != voorkeur_vendor_id]
    if not overige:
        raise OngeldigeInvoer("Kies minstens één andere crediteur om te archiveren")
    _kaarten_voor(actor, administratie_id, [voorkeur_vendor_id, *overige])  # bestaan in deze administratie
    posten, fout = _toets_open_posten(administratie_id, overige)
    if fout is not None:
        raise OpenPostenToetsMislukt(f"{fout} — eerst opnieuw proberen; er is niets gewijzigd")
    geblokkeerd = {v: p for v, p in posten.items() if p}
    if geblokkeerd:
        raise OpenPostenBlokkeren(geblokkeerd)

    correlatie = uuid.uuid4()
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        namen = dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(VendorCache.id.in_([voorkeur_vendor_id, *overige]))
            ).all()
        )
        te_archiveren = [{"vendor_id": str(v), "naam": namen.get(v)} for v in overige]
        doelset = set(overige)
        for bestaand in session.scalars(
            select(CrediteurArchiveerWerklijst).where(
                CrediteurArchiveerWerklijst.administratie_id == administratie_id,
                CrediteurArchiveerWerklijst.status == "open",
                CrediteurArchiveerWerklijst.voorkeur_vendor_id == voorkeur_vendor_id,
            )
        ):
            if {uuid.UUID(str(t["vendor_id"])) for t in bestaand.te_archiveren} == doelset:
                return ArchiveerUitkomst(
                    werklijst_id=bestaand.id,
                    voorkeur_naam=bestaand.voorkeur_naam,
                    te_archiveren_namen=[str(t.get("naam") or t["vendor_id"]) for t in bestaand.te_archiveren],
                    geheugen_verhuisd=0,
                    kenmerk_verhuisd=False,
                    ibans_verhuisd=0,
                    al_klaargezet=True,
                )
        rij = CrediteurArchiveerWerklijst(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            voorkeur_vendor_id=voorkeur_vendor_id,
            voorkeur_naam=namen.get(voorkeur_vendor_id),
            te_archiveren=te_archiveren,
            status="open",
            aangemaakt_door=actor.id,
        )
        session.add(rij)
        session.flush()
        geheugen = kenmerk = ibans = 0
        for bron_vendor_id in overige:
            geheugen += _verhuis_geheugen(
                session,
                administratie_id=administratie_id,
                bron_vendor_id=bron_vendor_id,
                voorkeur=voorkeur_vendor_id,
                actor_id=actor.id,
                correlatie=correlatie,
            )
            kenmerk += int(
                _verhuis_kenmerk(
                    session,
                    administratie_id=administratie_id,
                    bron_vendor_id=bron_vendor_id,
                    voorkeur=voorkeur_vendor_id,
                    actor_id=actor.id,
                    correlatie=correlatie,
                )
            )
            ibans += _verhuis_ibans(
                session,
                administratie_id=administratie_id,
                bron_vendor_id=bron_vendor_id,
                voorkeur=voorkeur_vendor_id,
                actor_id=actor.id,
                correlatie=correlatie,
            )
        record_audit_event(
            session,
            actor_id=actor.id,
            module="boekhouding",
            tabel="crediteur_archiveer_werklijst",
            record_id=rij.id,
            actie="crediteur_archiveer_klaargezet",
            correlatie_id=correlatie,
            nieuwe_waarde={
                "voorkeur_vendor_id": str(voorkeur_vendor_id),
                "voorkeur_naam": rij.voorkeur_naam,
                "te_archiveren": te_archiveren,
                "geheugen_verhuisd": geheugen,
                "kenmerk_verhuisd": bool(kenmerk),
                "ibans_verhuisd": ibans,
            },
            administratie_id=administratie_id,
        )
        return ArchiveerUitkomst(
            werklijst_id=rij.id,
            voorkeur_naam=rij.voorkeur_naam,
            te_archiveren_namen=[str(t.get("naam") or t["vendor_id"]) for t in te_archiveren],
            geheugen_verhuisd=geheugen,
            kenmerk_verhuisd=bool(kenmerk),
            ibans_verhuisd=ibans,
            al_klaargezet=False,
        )


# ----------------------------------------------------------------------------- afmelden


def afmelden(actor: Actor, *, administratie_id: uuid.UUID, vendor_ids: list[uuid.UUID], reden: str) -> uuid.UUID:
    """ "Geen dubbel — afmelden" (ontwerpnotitie ⑤): reden verplicht; de combinatie moet een bestaand cluster zijn
    (fail-closed); idempotent (tweede keer = dezelfde rij). Audit."""
    reden = reden.strip()
    if not reden:
        raise OngeldigeInvoer("Een reden is verplicht bij het afmelden van een dubbel-cluster")
    _administratie_in_scope(actor, administratie_id)
    leden = frozenset(vendor_ids)
    if len(leden) < 2:
        raise OngeldigeInvoer("Een cluster bestaat uit minstens twee crediteuren")
    passend = [
        g
        for g in dubbele_crediteuren(administratie_id=administratie_id)
        if frozenset(c.vendor_id for c in g.crediteuren) == leden
    ]
    if not passend:
        raise OngeldigeInvoer("Geen dubbel-cluster voor deze combinatie van crediteuren")
    groep = min(passend, key=lambda g: SOORT_RANG[g.soort])
    combinatie = combinatie_sleutel(leden)
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        bestaand = session.scalar(
            select(CrediteurDubbelAfmelding).where(
                CrediteurDubbelAfmelding.administratie_id == administratie_id,
                CrediteurDubbelAfmelding.combinatie == combinatie,
            )
        )
        if bestaand is not None:
            return bestaand.id
        rij = CrediteurDubbelAfmelding(
            id=uuid.uuid4(),
            administratie_id=administratie_id,
            sleutel_soort=groep.soort,
            sleutel=groep.sleutel,
            combinatie=combinatie,
            vendor_ids=[str(v) for v in sorted(leden, key=str)],
            reden=reden,
            afgemeld_door=actor.id,
        )
        session.add(rij)
        session.flush()
        record_audit_event(
            session,
            actor_id=actor.id,
            module="boekhouding",
            tabel="crediteur_dubbel_afmelding",
            record_id=rij.id,
            actie="crediteur_dubbel_afgemeld",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={
                "sleutel_soort": groep.soort,
                "sleutel": groep.sleutel,
                "vendor_ids": rij.vendor_ids,
                "namen": [c.naam for c in groep.crediteuren],
                "reden": reden,
            },
            administratie_id=administratie_id,
        )
        return rij.id


# ----------------------------------------------------------------------------- werklijst


def _werklijst_regel(rij: CrediteurArchiveerWerklijst, administratie_naam: str) -> WerklijstRegel:
    return WerklijstRegel(
        id=rij.id,
        administratie_id=rij.administratie_id,
        administratie_naam=administratie_naam,
        voorkeur_vendor_id=rij.voorkeur_vendor_id,
        voorkeur_naam=rij.voorkeur_naam,
        te_archiveren=list(rij.te_archiveren or []),
        status=rij.status,
        aangemaakt_op=rij.aangemaakt_op,
        gedaan_op=rij.gedaan_op,
        gedaan_bron=rij.gedaan_bron,
        laatste_hertoets_op=rij.laatste_hertoets_op,
        hertoets_detail=rij.hertoets_detail,
    )


def werklijst(actor: Actor) -> list[WerklijstRegel]:
    """Kantoorbreed: open regels eerst (oudste bovenaan), daarna gedaan (nieuwste bovenaan)."""
    uit: list[WerklijstRegel] = []
    for aid, naam in administraties_in_scope(actor):
        with scoped_session(aid, actor_id=actor.id) as session:
            for rij in session.scalars(
                select(CrediteurArchiveerWerklijst).where(CrediteurArchiveerWerklijst.administratie_id == aid)
            ):
                uit.append(_werklijst_regel(rij, naam))
    return sorted(
        uit,
        key=lambda r: (
            0 if r.status == "open" else 1,
            r.aangemaakt_op.timestamp() if r.status == "open" else -(r.gedaan_op or r.aangemaakt_op).timestamp(),
        ),
    )


def _zet_gedaan(
    session: Session, rij: CrediteurArchiveerWerklijst, *, actor_id: uuid.UUID, bron: str, detail: dict | None
) -> None:
    oud = rij.status
    rij.status = "gedaan"
    rij.gedaan_op = datetime.now(UTC)
    rij.gedaan_door = actor_id
    rij.gedaan_bron = bron
    record_audit_event(
        session,
        actor_id=actor_id,
        module="boekhouding",
        tabel="crediteur_archiveer_werklijst",
        record_id=rij.id,
        actie="crediteur_archiveer_gedaan",
        correlatie_id=uuid.uuid4(),
        oude_waarde={"status": oud},
        nieuwe_waarde={"status": "gedaan", "bron": bron, "hertoets_detail": detail},
        administratie_id=rij.administratie_id,
    )


def markeer_gedaan(actor: Actor, *, werklijst_id: uuid.UUID) -> WerklijstRegel:
    """Handmatige afvinkroute "Markeer als gedaan" (audit); al gedaan = idempotent."""
    for aid, naam in administraties_in_scope(actor):
        with scoped_session(aid, actor_id=actor.id) as session:
            rij = session.get(CrediteurArchiveerWerklijst, werklijst_id)
            if rij is None:
                continue
            if rij.status != "gedaan":
                _zet_gedaan(session, rij, actor_id=actor.id, bron="handmatig", detail=None)
            session.flush()
            return _werklijst_regel(rij, naam)
    raise OnbekendeAdministratie("Onbekende werklijst-regel of buiten je scope")


def _vendor_gearchiveerd(client: RlzClient, vendor_id: str) -> str:
    """'gearchiveerd' | 'actief' | 'fout: …' — `IsArchived: true` óf afwezig (404) = gearchiveerd (STAP-0 03-09:
    welke van de twee RLZ toepast is pas zichtbaar bij een échte gearchiveerde crediteur; beide gelden)."""
    try:
        vendor = client.get(f"Vendors/{vendor_id}", params={"fields": "all"})
    except RlzApiError as exc:
        if exc.status_code == 404:
            return "gearchiveerd"
        return f"fout: {exc.status_code}"
    if isinstance(vendor, dict) and vendor.get("IsArchived") is True:
        return "gearchiveerd"
    return "actief"


def hertoets_werklijst(
    *, client_factory: Callable[[uuid.UUID], RlzClient] | None = None
) -> dict[uuid.UUID, dict[str, int] | str]:
    """Dagelijks meeliftend in sync-alles (+ CLI `crediteur-werklijst-hertoets`): per administratie mét open
    regels de Vendors in RLZ lezen; álle te archiveren crediteuren gearchiveerd/afwezig → regel gedaan mét
    audit (systeem-actor). Eén kapotte administratie stopt de rest niet. Strikt GET-only."""
    factory = client_factory or _open_client
    with scoped_session(None) as session:
        administraties = list(
            session.execute(
                select(Administratie.id).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
            ).all()
        )
    uit: dict[uuid.UUID, dict[str, int] | str] = {}
    for (aid,) in administraties:
        try:
            with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
                open_rijen = list(
                    session.scalars(
                        select(CrediteurArchiveerWerklijst).where(
                            CrediteurArchiveerWerklijst.administratie_id == aid,
                            CrediteurArchiveerWerklijst.status == "open",
                        )
                    )
                )
                if not open_rijen:
                    continue
                client = factory(aid)
                try:
                    gedaan = 0
                    nu = datetime.now(UTC)
                    for rij in open_rijen:
                        detail = {
                            str(t["vendor_id"]): _vendor_gearchiveerd(client, str(t["vendor_id"]))
                            for t in rij.te_archiveren or []
                        }
                        rij.laatste_hertoets_op = nu
                        rij.hertoets_detail = detail
                        if detail and all(v == "gearchiveerd" for v in detail.values()):
                            _zet_gedaan(session, rij, actor_id=SYSTEEM_ACTOR_ID, bron="hertoets", detail=detail)
                            gedaan += 1
                    uit[aid] = {"open": len(open_rijen), "gedaan": gedaan, "nog_open": len(open_rijen) - gedaan}
                finally:
                    with contextlib.suppress(Exception):
                        client.close()
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt de rest niet
            logger.exception("Crediteur-werklijst-hertoets mislukt voor %s", aid)
            uit[aid] = f"{type(exc).__name__}: {exc}"
    return uit
