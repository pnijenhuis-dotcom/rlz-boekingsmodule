"""Crediteuren-dubbelen v2 → schaalbaar (design-ronde 03-09; blok B13 fixrun 07-09, richting Peter 06-09).

Kantoorbreed onder RLS: itereer over de administraties in scope van de actor (`mijn_administraties`) en lees per
administratie in `scoped_session(aid, actor_id=…)`; de BESTAANDE motor `dubbele_crediteuren` levert de groepen
(sinds 07-09 zónder verliezers — afgehandelde clusters verdwijnen vanzelf), hier worden ze gebundeld tot clusters
(zelfde ledenset over meerdere sleutels = één rij mét meerdere chips), verrijkt met kaartgegevens (aantal boekingen,
laatst geboekt), GECLASSIFICEERD (eenduidig → systeem, twijfel → mens; `afhandeling.classificeer`) en gesorteerd:
zwaarste sleutel eerst (btw > KvK > IBAN > naam), dan laatst geboekt, dan aantal boekingen.

Acties (allemaal zonder RLZ-call, nooit verwijderen):
- "Voorkeur kiezen…" (mens) en de auto-run (systeem) delen één kern: `afhandeling.handel_af` — verliezers worden in
  de module onbruikbaar, geheugen/kenmerk/IBAN's verhuizen, open boekvoorstellen worden hervertaald, log + audit,
  terugdraaibaar. RLZ-archivering is geen doel meer (07-09); de open-posten-toets van 03-09 is daarmee vervallen.
- "Geen dubbel — afmelden" → afmelding-rij per combinatie (reden verplicht) + audit; de lijst filtert 'm eruit.
- RLZ-opruimlijst = optionele CSV-export (`afhandeling.export_opruimlijst`), geen teller/chip.
"""

from __future__ import annotations

import logging
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.auth.service import mijn_administraties
from app.crediteuren.models import SLEUTEL_SOORTEN, CrediteurDubbelAfmelding, combinatie_sleutel
from app.db.audit import record_audit_event
from app.db.models import GebruikerRol
from app.db.session import scoped_session
from app.documenten.crediteur_kenmerk import DubbelGroep, dubbele_crediteuren
from app.documenten.models import Boekvoorstel, CrediteurKenmerk, Document, DocumentStatus, LeverancierIban
from app.extractie.btw_nummer import normaliseer_kvk_nummer
from app.geheugen.models import BoekingObservatie, ObservatieBron
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
    # Blok B13 07-09: deterministische classificatie — eenduidig = systeem handelt af, twijfel = mens.
    eenduidig: bool
    classificatie_reden: str

    @property
    def vendor_ids(self) -> frozenset[uuid.UUID]:
        return frozenset(k.vendor_id for k in self.crediteuren)


@dataclass(frozen=True)
class Tellers:
    clusters: int  # twijfel — mens nodig (de werkvoorraad-KPI)
    eenduidig: int  # automatisch afhandelbaar (knop "Eenduidige clusters automatisch afhandelen (N)")
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
class ClusterDetail:
    administratie_id: uuid.UUID
    administratie_naam: str
    crediteuren: list[Kaart]
    voorkeur_suggestie: uuid.UUID
    eenduidig: bool
    classificatie_reden: str


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
    """≥ 2 verschillende KvK-nummers op de kaarten — genormaliseerd (blok 5 07-09: "KvK 1234.5678" ≡ "12345678";
    een onnormaliseerbare waarde telt letterlijk mee, nooit stil weggefilterd)."""
    nummers = {normaliseer_kvk_nummer(k.kvk_nummer) or k.kvk_nummer for k in kaarten if k.kvk_nummer}
    return len(nummers) >= 2


# ----------------------------------------------------------------------------- clusters


def _clusters_voor_administratie(actor: Actor, administratie_id: uuid.UUID, administratie_naam: str) -> list[Cluster]:
    from app.crediteuren import afhandeling  # lokaal: afhandeling importeert deze module

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
        menskeuze = afhandeling.menskeuze_vendors(session, administratie_id=administratie_id)

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
        basis = Cluster(
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
            eenduidig=False,
            classificatie_reden="",
        )
        cl = afhandeling.classificeer(basis, menskeuze=menskeuze)
        clusters.append(
            Cluster(**{**basis.__dict__, "eenduidig": cl.eenduidig, "classificatie_reden": cl.reden})
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
        clusters=sum(1 for c in clusters if not c.eenduidig),
        eenduidig=sum(1 for c in clusters if c.eenduidig),
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
    classificatie: str | None = None,
) -> Lijst:
    if sleutel and sleutel not in SLEUTEL_SOORTEN:
        raise OngeldigeInvoer(f"Onbekende sleutel: {sleutel}")
    if classificatie and classificatie not in ("twijfel", "eenduidig"):
        raise OngeldigeInvoer(f"Onbekende classificatie: {classificatie}")
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
    if classificatie:
        selectie = [c for c in selectie if c.eenduidig == (classificatie == "eenduidig")]
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
    """Dialooggegevens "Voorkeur kiezen…": kaarten, vooringevulde voorkeur en de classificatie (eenduidig/twijfel
    mét reden). Geen RLZ-call meer (07-09): archiveren in RLZ is geen doel, dus geen open-posten-toets."""
    naam = _administratie_in_scope(actor, administratie_id)
    vendor_ids = list(dict.fromkeys(vendor_ids))
    if len(vendor_ids) < 2:
        raise OngeldigeInvoer("Een cluster bestaat uit minstens twee crediteuren")
    kaarten = _kaarten_voor(actor, administratie_id, vendor_ids)
    leden = frozenset(vendor_ids)
    passend = [c for c in _clusters_voor_administratie(actor, administratie_id, naam) if c.vendor_ids == leden]
    if passend:
        cl = passend[0]
        eenduidig, reden = cl.eenduidig, cl.classificatie_reden
    else:
        eenduidig, reden = False, "twijfel: geen bestaand dubbel-cluster voor deze combinatie"
    return ClusterDetail(
        administratie_id=administratie_id,
        administratie_naam=naam,
        crediteuren=kaarten,
        voorkeur_suggestie=_voorkeur_suggestie(kaarten),
        eenduidig=eenduidig,
        classificatie_reden=reden,
    )


# ----------------------------------------------------------------------------- verhuizen (geheugen, kenmerk, IBAN's)


def verhuis_geheugen(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    bron_vendor_id: uuid.UUID,
    voorkeur: uuid.UUID,
    actor_id: uuid.UUID,
    correlatie: uuid.UUID,
) -> list[tuple[str, str]]:
    """Boekingsgeheugen is append-only (grant zonder UPDATE): élke observatie van de verliezer krijgt een
    deterministische kopie op de voorkeur (uuid5 op de bron-id — een her-run legt niets dubbel vast); de bron-rijen
    blijven staan (inert: de verliezer is in de module onbruikbaar). Eén audit per bron-crediteur mét de volledige
    id-lijst oud→nieuw; retourneert die paren (voor de terugdraai-log)."""
    bron_rijen = list(
        session.scalars(
            select(BoekingObservatie).where(
                BoekingObservatie.administratie_id == administratie_id, BoekingObservatie.vendor_id == bron_vendor_id
            )
        )
    )
    if not bron_rijen:
        return []
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
    return verhuisd


def verhuis_kenmerk(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    bron_vendor_id: uuid.UUID,
    voorkeur: uuid.UUID,
    actor_id: uuid.UUID,
    correlatie: uuid.UUID,
) -> dict | None:
    """btw-/KvK-kenmerk op de voorkeur zetten als die leeg is; 'handmatig' op de voorkeur wint altijd, een handmatig
    kenmerk van de bron wint boven 'factuur'. Audit oud→nieuw. Retourneert de OUDE stand van de voorkeur (voor
    terugdraaien) of None als er niets gewijzigd is."""
    bron = session.get(CrediteurKenmerk, (administratie_id, bron_vendor_id))
    if bron is None or (not bron.btw_nummer and not bron.kvk_nummer):
        return None
    doel = session.get(CrediteurKenmerk, (administratie_id, voorkeur))
    oud = {
        "bestond": doel is not None,
        "btw_nummer": doel.btw_nummer if doel else None,
        "btw_nummer_geverifieerd": doel.btw_nummer_geverifieerd if doel else None,
        "btw_nummer_bron": doel.btw_nummer_bron if doel else None,
        "kvk_nummer": doel.kvk_nummer if doel else None,
        "kvk_nummer_bron": doel.kvk_nummer_bron if doel else None,
    }
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
        if not oud["bestond"]:
            session.expunge(doel)
        return None
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
        oude_waarde={
            "btw_nummer": oud["btw_nummer"],
            "kvk_nummer": oud["kvk_nummer"],
            "van_vendor_id": str(bron_vendor_id),
        },
        nieuwe_waarde={"btw_nummer": doel.btw_nummer, "kvk_nummer": doel.kvk_nummer},
        administratie_id=administratie_id,
    )
    return oud


def verhuis_ibans(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    bron_vendor_id: uuid.UUID,
    voorkeur: uuid.UUID,
    actor_id: uuid.UUID,
    correlatie: uuid.UUID,
) -> list[str]:
    """Vertrouwde IBAN's van de bron óók op de voorkeur (anders geeft de eerste factuur op de voorkeur een valse
    IBAN-wissel-blokkade). Kopie per record mét audit; bron blijft staan. Retourneert de gekopieerde IBAN's."""
    bron_rijen = list(
        session.scalars(
            select(LeverancierIban).where(
                LeverancierIban.administratie_id == administratie_id, LeverancierIban.vendor_id == bron_vendor_id
            )
        )
    )
    gekopieerd: list[str] = []
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
        gekopieerd.append(rij.iban)
    return gekopieerd


# ----------------------------------------------------------------------------- "Voorkeur kiezen…" (mens)


@dataclass(frozen=True)
class AfhandelUitkomst:
    afhandeling_id: uuid.UUID
    voorkeur_naam: str | None
    verliezer_namen: list[str]
    geheugen_verhuisd: int
    kenmerk_verhuisd: bool
    ibans_verhuisd: int
    boekvoorstellen_hervertaald: int


def afhandelen(
    actor: Actor, *, administratie_id: uuid.UUID, voorkeur_vendor_id: uuid.UUID, verliezer_vendor_ids: list[uuid.UUID]
) -> AfhandelUitkomst:
    """ "Voorkeur kiezen…" door de mens: zelfde kern als de auto-run (`afhandeling.handel_af`, bron 'mens') — de
    verliezers worden in de module onbruikbaar, geheugen/kenmerk/IBAN's en open boekvoorstellen gaan naar de voorkeur,
    alles in één transactie, geauditeerd en terugdraaibaar. Geen RLZ-call, geen RLZ-write."""
    from app.crediteuren import afhandeling

    naam = _administratie_in_scope(actor, administratie_id)
    verliezers = [v for v in dict.fromkeys(verliezer_vendor_ids) if v != voorkeur_vendor_id]
    if not verliezers:
        raise OngeldigeInvoer("Kies minstens één andere crediteur als verliezer")
    _kaarten_voor(actor, administratie_id, [voorkeur_vendor_id, *verliezers])  # bestaan in deze administratie
    leden = frozenset([voorkeur_vendor_id, *verliezers])
    passend = [c for c in _clusters_voor_administratie(actor, administratie_id, naam) if c.vendor_ids == leden]
    sleutels = passend[0].sleutels if passend else []
    reden = "mens: voorkeur gekozen" + (f" ({passend[0].classificatie_reden})" if passend else "")
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        try:
            u = afhandeling.handel_af(
                session,
                administratie_id=administratie_id,
                voorkeur=voorkeur_vendor_id,
                verliezers=verliezers,
                sleutels=sleutels,
                reden=reden,
                bron="mens",
                actor_id=actor.id,
                run_id=uuid.uuid4(),
            )
        except afhandeling.AfhandelingFout as exc:
            raise OngeldigeInvoer(str(exc)) from exc
    return AfhandelUitkomst(
        afhandeling_id=u.afhandeling_id,
        voorkeur_naam=u.voorkeur_naam,
        verliezer_namen=u.verliezer_namen,
        geheugen_verhuisd=u.geheugen_verhuisd,
        kenmerk_verhuisd=u.kenmerk_verhuisd,
        ibans_verhuisd=u.ibans_verhuisd,
        boekvoorstellen_hervertaald=u.boekvoorstellen_hervertaald,
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


