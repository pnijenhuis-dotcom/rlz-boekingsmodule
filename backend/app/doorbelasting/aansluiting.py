"""Doorbelasting-aansluiting bron-verkoop ↔ inkoop in álle doelentiteiten (Peter 12-09/16-09, blok 2).

Vraag Peter: zeker weten dat álle verkoopfacturen van Kempen Facilities 2026 als inkoopfactuur in álle doelentiteiten
staan — óók wat via Zenvoices of handmatig ging. De bestaande doorbelasting-reconciliatie toetst alleen module-
doorbelastingen (spiegelparen); het `intercompany`-blok toetst verkoop ↔ inkoop per IC-paar maar kent de whitelist
niet ("hoort er een inkoop te zijn?") en geen "doel niet in module".

Wat dit blok doet (lees-only, RLZ én Odoo via de IC-bronabstractie):
- per BRON-administratie mét actieve whitelist: per whitelist-rij de verkoopfacturen aan de doel-debiteur (RLZ
  `SalesInvoices` op `Entity/id`, geboekt ÉN concept) in het venster;
- doel = `doel_administratie_id` van de rij; ontbreekt die → "doel niet in module" (één regel per rij mét aantal + som);
- inkoop in het doel op álle crediteurrecords van de bron-identiteit: IC-relatie (`relaties.actieve_paren`), KvK-gelijk
  (`crediteur_kenmerk.kenmerken_per_vendor` ↔ `administratie_identiteit.kvk`), genormaliseerde naam (VendorCache);
- match = dezelfde pure motor als het IC-blok (`factuurmatch.match_facturen`: nummer > bedrag+datum ± 7 d > bedrag),
  "onderweg in de module" ≠ afwijking; soorten hier: sluit / ontbreekt in doel / bedrag afwijkt / status verschilt /
  doel niet in module / inkoop zonder verkoop;
- actie per rij: "Boek inkoop in doel" = het bestaande inhaalpad (alleen als er een open spiegel-taak voor die
  verkoop bestaat — een Zenvoices-/handmatige verkoop heeft die niet: dan zegt de doe-tekst wat te doen);
- webfilter = "RLZ-blokkering — meting ongeldig" (geen doorrekenen), geen credential = zichtbaar overgeslagen.

CLI (lees-only, nameting-allowlist): `doorbelasting-aansluiting --bron "Kempen Facilities" --jaar 2026`.
Reconciliatieblok `doorbelasting_aansluiting` (dagelijks, ná het intercompany-blok).
"""

from __future__ import annotations

import argparse
import logging
import sys
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingBoekingStatus, DoorbelastingMapping
from app.intercompany import factuurmatch as fm
from app.intercompany.factuurmatch import (
    Bron,
    BronOvergeslagen,
    EntityNietVertaalbaar,
    IcFactuur,
    MatchUitkomst,
    match_facturen,
    module_onderweg,
    open_bron,
)
from app.rlz.client import RlzWebfilterError

logger = logging.getLogger(__name__)

BLOK = "doorbelasting_aansluiting"
ACCEPTATIE_BRON = BLOK
COMMANDO = "doorbelasting-aansluiting"
VENSTER_DAGEN = 400

SOORT_ONTBREEKT_IN_DOEL = "da_ontbreekt_in_doel"
SOORT_BEDRAG_AFWIJKT = "da_bedrag_afwijkt"
SOORT_STATUS_VERSCHILT = "da_status_verschilt"
SOORT_DOEL_NIET_IN_MODULE = "da_doel_niet_in_module"
SOORT_INKOOP_ZONDER_VERKOOP = "da_inkoop_zonder_verkoop"
SOORTEN = (
    SOORT_ONTBREEKT_IN_DOEL,
    SOORT_BEDRAG_AFWIJKT,
    SOORT_STATUS_VERSCHILT,
    SOORT_DOEL_NIET_IN_MODULE,
    SOORT_INKOOP_ZONDER_VERKOOP,
)
_IC_NAAR_DA = {
    fm.SOORT_ONTBREEKT_BIJ_ONTVANGER: SOORT_ONTBREEKT_IN_DOEL,
    fm.SOORT_ONTBREEKT_BIJ_VERKOPER: SOORT_INKOOP_ZONDER_VERKOOP,
    fm.SOORT_BEDRAG_VERSCHILT: SOORT_BEDRAG_AFWIJKT,
    fm.SOORT_STATUS_VERSCHILT: SOORT_STATUS_VERSCHILT,
}
WEBFILTER_ONGELDIG = fm.WEBFILTER_ONGELDIG


# ---- datamodel ----------------------------------------------------------------------------------------------


@dataclass(frozen=True)
class WhitelistRij:
    mapping_id: uuid.UUID
    doelentiteit_naam: str
    doel_customer_guid: uuid.UUID
    doel_administratie_id: uuid.UUID | None


@dataclass
class DoelRapport:
    rij: WhitelistRij
    doel_naam: str | None = None
    verkoop: list[IcFactuur] = field(default_factory=list)
    inkoop: list[IcFactuur] = field(default_factory=list)
    inkoop_entity_ids: frozenset[uuid.UUID] = frozenset()
    inkoop_basis: str = ""  # "ic_relatie" | "kvk" | "naam" | ""
    uitkomst: MatchUitkomst | None = None
    open_spiegel: dict[str, uuid.UUID] = field(default_factory=dict)  # verkoop_rlz_id (lower) → boeking_id
    reden: str | None = None  # niet getoetst: waarom (overgeslagen/ongeldig/doel niet in module)

    @property
    def doel_in_module(self) -> bool:
        return self.rij.doel_administratie_id is not None

    @property
    def som_verkoop(self) -> Decimal:
        return sum((f.bedrag for f in self.verkoop), Decimal("0"))


@dataclass
class Aansluiting:
    bron_administratie_id: uuid.UUID
    bron_naam: str | None
    van: date
    tot: date
    doelen: list[DoelRapport] = field(default_factory=list)
    overgeslagen: dict[uuid.UUID, str] = field(default_factory=dict)
    ongeldig: dict[uuid.UUID, str] = field(default_factory=dict)

    @property
    def meting_ongeldig(self) -> bool:
        return any(WEBFILTER_ONGELDIG in r for r in self.ongeldig.values())


# ---- lezers ---------------------------------------------------------------------------------------------------


def whitelist_voor(bron_administratie_id: uuid.UUID) -> list[WhitelistRij]:
    with scoped_session(bron_administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.scalars(
            select(DoorbelastingMapping)
            .where(
                DoorbelastingMapping.administratie_id == bron_administratie_id,
                DoorbelastingMapping.actief.is_(True),
            )
            .order_by(DoorbelastingMapping.doelentiteit_naam)
        ).all()
        return [
            WhitelistRij(
                mapping_id=m.id,
                doelentiteit_naam=m.doelentiteit_naam,
                doel_customer_guid=m.doel_customer_guid,
                doel_administratie_id=m.doel_administratie_id,
            )
            for m in rijen
        ]


def bronnen_met_whitelist() -> list[uuid.UUID]:
    """Alle actieve administraties mét ≥ 1 actieve whitelist-rij (de bron-kant van de doorbelasting).

    Systeemfout 19-09 (opdracht ic_spiegel_rood): tot 19-09 las deze functie `doorbelasting_mapping` in
    `scoped_session(None)`. De tabel draagt ALLEEN een scope-policy (`administratie_id = current_administratie_id()`,
    FORCE RLS; geen Beheerder-/NULL-clausule) — lokaal maskeert de superuser-bypass dat, in productie (eigenaar zonder
    BYPASSRLS) gaf de query stil 0 rijen: het dagelijkse blok `doorbelasting_aansluiting` meldde sinds 16-09 elke run
    "0 bron-administratie(s) mét whitelist — niets te toetsen" terwijl Kempen Facilities 8 rijen heeft (stille no-op,
    KP 6). Nu: administraties platformbreed lezen (dat mag zonder scope) en de mapping per administratie in haar eigen
    scope — hetzelfde patroon als `app/intercompany/relaties.py::_doorbelasting_kandidaten`."""
    from app.db.models import Administratie

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        administratie_ids = list(session.scalars(select(Administratie.id).where(Administratie.actief.is_(True))).all())
    uit: set[uuid.UUID] = set()
    for aid in administratie_ids:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            heeft = session.scalar(
                select(DoorbelastingMapping.id)
                .where(DoorbelastingMapping.administratie_id == aid, DoorbelastingMapping.actief.is_(True))
                .limit(1)
            )
        if heeft is not None:
            uit.add(aid)
    return sorted(uit, key=str)


def crediteurrecords_van_bron_in_doel(
    *, bron_administratie_id: uuid.UUID, doel_administratie_id: uuid.UUID
) -> tuple[frozenset[uuid.UUID], str]:
    """Álle crediteurrecords in het DOEL die de bron-identiteit zijn: (1) actieve IC-relatie bron → doel
    (`entity_in_b`), (2) KvK van de bron-identiteit == KvK op het crediteurrecord (kenmerk-tabel of RLZ), (3) exact
    gelijke genormaliseerde naam. Bases worden gecombineerd; de genoemde basis is de sterkste die iets opleverde."""
    from app.documenten.crediteur_kenmerk import kenmerken_per_vendor
    from app.intercompany.identiteit import alle_identiteiten, naam_norm
    from app.intercompany.relaties import actieve_paren
    from app.sync.models import VendorCache

    ids: set[uuid.UUID] = set()
    basis = ""
    try:
        for p in actieve_paren():
            if p.administratie_a_id == bron_administratie_id and p.administratie_b_id == doel_administratie_id:
                if p.entity_in_b:
                    ids.add(p.entity_in_b)
                    basis = basis or "ic_relatie"
            if p.administratie_b_id == bron_administratie_id and p.administratie_a_id == doel_administratie_id:
                ids.add(p.entity_in_a)
                basis = basis or "ic_relatie"
    except Exception:  # noqa: BLE001 — relaties zijn een extra bron
        logger.exception("aansluiting: IC-paren niet gelezen")
    try:
        identiteiten = alle_identiteiten()
    except Exception:  # noqa: BLE001
        logger.exception("aansluiting: identiteiten niet gelezen")
        identiteiten = {}
    bron_ident = identiteiten.get(bron_administratie_id)
    bron_kvk = getattr(bron_ident, "kvk", None)
    bron_namen = {naam_norm(getattr(bron_ident, "naam", None))} - {""}
    from app.db.models import Administratie

    with scoped_session(doel_administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        bron_rij = session.get(Administratie, bron_administratie_id)
        if bron_rij is not None:
            bron_namen.add(naam_norm(bron_rij.naam))
        if bron_kvk:
            for vendor_id, k in kenmerken_per_vendor(session, administratie_id=doel_administratie_id).items():
                if k.kvk_nummer and k.kvk_nummer == bron_kvk:
                    ids.add(vendor_id)
                    basis = basis or "kvk"
        for rij in session.scalars(
            select(VendorCache).where(
                VendorCache.administratie_id == doel_administratie_id, VendorCache.verdwenen_uit_bron_op.is_(None)
            )
        ):
            if rij.naam and naam_norm(rij.naam) in bron_namen:
                ids.add(rij.id)
                basis = basis or "naam"
    return frozenset(ids), basis


def open_spiegel_taken_per_verkoop(bron_administratie_id: uuid.UUID) -> dict[str, uuid.UUID]:
    """verkoop_rlz_id (lower) → boeking_id van open spiegel-taken (SPIEGEL_OPEN) in de bron — de actie
    'Boek inkoop in doel' (inhaalpad `boek_spiegel_alsnog`) bestaat alleen voor die verkopen."""
    with scoped_session(bron_administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.execute(
            select(DoorbelastingBoeking.verkoop_rlz_id, DoorbelastingBoeking.id).where(
                DoorbelastingBoeking.administratie_id == bron_administratie_id,
                DoorbelastingBoeking.status == DoorbelastingBoekingStatus.SPIEGEL_OPEN.value,
            )
        ).all()
    return {str(v).lower(): b for v, b in rijen}


# ---- meting ---------------------------------------------------------------------------------------------------


def meet(
    *,
    bron_administratie_id: uuid.UUID,
    van: date,
    tot: date,
    nu: date,
    bron_factory: Callable[[uuid.UUID], Bron] | None = None,
    whitelist: Sequence[WhitelistRij] | None = None,
    crediteurrecords: Callable[[uuid.UUID, uuid.UUID], tuple[frozenset[uuid.UUID], str]] | None = None,
    onderweg: Callable[[uuid.UUID], set[str]] | None = None,
    spiegel_open: Callable[[uuid.UUID], dict[str, uuid.UUID]] | None = None,
    naam_van: Callable[[uuid.UUID], str | None] | None = None,
) -> Aansluiting:
    """Eén bron-administratie: per whitelist-rij lezen + matchen. Alle `*`-callables zijn test-seams."""
    maak_bron = bron_factory or open_bron
    whitelist = list(whitelist if whitelist is not None else whitelist_voor(bron_administratie_id))
    crediteurrecords = crediteurrecords or (
        lambda b, d: crediteurrecords_van_bron_in_doel(bron_administratie_id=b, doel_administratie_id=d)
    )
    onderweg = onderweg or module_onderweg
    spiegel_open = spiegel_open or open_spiegel_taken_per_verkoop
    naam_van = naam_van or _naam_van

    a = Aansluiting(bron_administratie_id=bron_administratie_id, bron_naam=naam_van(bron_administratie_id), van=van, tot=tot)
    bronnen: dict[uuid.UUID, Bron] = {}

    def bron_voor(aid: uuid.UUID) -> Bron | None:
        if aid in bronnen:
            return bronnen[aid]
        if aid in a.overgeslagen or aid in a.ongeldig:
            return None
        try:
            bronnen[aid] = maak_bron(aid)
        except BronOvergeslagen as exc:
            a.overgeslagen[aid] = str(exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("aansluiting: bron openen mislukt voor %s", aid)
            a.ongeldig[aid] = f"bron openen mislukt: {str(exc)[:200]}"
            return None
        return bronnen[aid]

    def lees(aid: uuid.UUID, kant: str, entity_ids: Iterable[uuid.UUID]) -> list[IcFactuur] | None:
        bron = bron_voor(aid)
        if bron is None:
            return None
        try:
            return bron.verkoop(entity_ids, van, tot) if kant == "verkoop" else bron.inkoop(entity_ids, van, tot)
        except RlzWebfilterError as exc:
            a.ongeldig[aid] = f"{WEBFILTER_ONGELDIG}: {str(exc)[:200]}"
            return None
        except EntityNietVertaalbaar as exc:
            a.ongeldig[aid] = str(exc)
            return None
        except Exception as exc:  # noqa: BLE001
            logger.exception("aansluiting: lezen mislukt (%s, %s)", aid, kant)
            a.ongeldig[aid] = f"lezen mislukt: {str(exc)[:200]}"
            return None

    try:
        try:
            spiegels = spiegel_open(bron_administratie_id)
        except Exception:  # noqa: BLE001
            logger.exception("aansluiting: open spiegel-taken niet gelezen")
            spiegels = {}
        onderweg_cache: dict[uuid.UUID, set[str]] = {}
        for rij in whitelist:
            d = DoelRapport(rij=rij, doel_naam=naam_van(rij.doel_administratie_id) if rij.doel_administratie_id else None)
            a.doelen.append(d)
            verkoop = lees(bron_administratie_id, "verkoop", [rij.doel_customer_guid])
            if verkoop is None:
                d.reden = a.ongeldig.get(bron_administratie_id) or a.overgeslagen.get(bron_administratie_id) or "bron niet gelezen"
                continue
            d.verkoop = verkoop
            d.open_spiegel = {k: v for k, v in spiegels.items()}
            if rij.doel_administratie_id is None:
                d.reden = "doel niet in module"
                continue
            doel = rij.doel_administratie_id
            try:
                d.inkoop_entity_ids, d.inkoop_basis = crediteurrecords(bron_administratie_id, doel)
            except Exception as exc:  # noqa: BLE001
                logger.exception("aansluiting: crediteurrecords niet bepaald voor %s", doel)
                d.reden = f"crediteurrecords in het doel niet bepaald: {str(exc)[:160]}"
                continue
            if not d.inkoop_entity_ids:
                d.inkoop = []
            else:
                inkoop = lees(doel, "inkoop", d.inkoop_entity_ids)
                if inkoop is None:
                    d.reden = a.ongeldig.get(doel) or a.overgeslagen.get(doel) or "doel niet gelezen"
                    continue
                d.inkoop = inkoop
            if doel not in onderweg_cache:
                try:
                    onderweg_cache[doel] = onderweg(doel)
                except Exception:  # noqa: BLE001
                    logger.exception("aansluiting: module-onderweg niet gelezen voor %s", doel)
                    onderweg_cache[doel] = set()
            d.uitkomst = match_facturen(
                verkoper_id=bron_administratie_id,
                ontvanger_id=doel,
                verkoop=d.verkoop,
                inkoop=d.inkoop,
                module_onderweg=onderweg_cache[doel],
                nu=nu,
                verkoper_naam=a.bron_naam,
                ontvanger_naam=d.doel_naam,
            )
    finally:
        for b in bronnen.values():
            b.sluit()
    return a


def _naam_van(aid: uuid.UUID | None) -> str | None:
    if aid is None:
        return None
    try:
        from app.reconciliatie import verrijking

        return verrijking.administratie_naam(aid)
    except Exception:  # noqa: BLE001
        return None


# ---- rapport (tabellen) ---------------------------------------------------------------------------------------


def _euro(b: Decimal | None) -> str:
    if b is None:
        return "—"
    s = f"{b:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")
    return f"€ {s}"


def _status(s: int) -> str:
    return {1: "concept", 2: "open", 3: "gesloten"}.get(s, str(s))


def rapport_regels(a: Aansluiting) -> list[str]:
    """Markdown-tabellen: sluit / ontbreekt in doel / bedrag afwijkt / status verschilt / doel niet in module /
    inkoop zonder verkoop — plus de kop mét meetstatus."""
    uit: list[str] = []
    uit.append(
        f"### Doorbelasting-aansluiting {a.bron_naam or a.bron_administratie_id} — verkoop {a.van.isoformat()} t/m "
        f"{a.tot.isoformat()} ↔ inkoop in de doelentiteiten (lees-only)"
    )
    if a.meting_ongeldig:
        uit.append(f"**{WEBFILTER_ONGELDIG}** — niet doorgerekend; regels hieronder alleen voor zover gelezen.")
    for aid, reden in sorted(a.overgeslagen.items(), key=lambda kv: str(kv[0])):
        uit.append(f"- OVERGESLAGEN {aid}: {reden}")
    for aid, reden in sorted(a.ongeldig.items(), key=lambda kv: str(kv[0])):
        uit.append(f"- FOUT {aid}: {reden}")
    tot_v = sum(len(d.verkoop) for d in a.doelen)
    uit.append(
        f"Whitelist-rijen: {len(a.doelen)} ({sum(1 for d in a.doelen if d.doel_in_module)} mét doel in de module); "
        f"verkoopfacturen gelezen: {tot_v}."
    )
    uit.append("")
    uit.append("| Doelentiteit | Doel in module | Basis crediteur | Verkoop | Inkoop | Sluit | Ontbreekt in doel | Bedrag afwijkt | Status verschilt | Inkoop zonder verkoop | Onderweg | Stand |")
    uit.append("|---|---|---|---|---|---|---|---|---|---|---|---|")
    secties: dict[str, list[str]] = {s: [] for s in ("sluit", *SOORTEN)}
    for d in a.doelen:
        u = d.uitkomst
        tel = {s: 0 for s in SOORTEN}
        if u is not None:
            for b in u.bevindingen:
                tel[_IC_NAAR_DA[b.soort]] += 1
        if not d.doel_in_module and d.verkoop:
            tel[SOORT_DOEL_NIET_IN_MODULE] = len(d.verkoop)
        sluit = sum(1 for m in (u.matches if u else []) if m.zeker and m.delta == 0)
        stand = d.reden or ("OK" if not any(tel.values()) else "AFWIJKING")
        uit.append(
            f"| {d.rij.doelentiteit_naam} | {'ja — ' + (d.doel_naam or str(d.rij.doel_administratie_id)) if d.doel_in_module else 'NEE'} | "
            f"{d.inkoop_basis or '—'} ({len(d.inkoop_entity_ids)}) | {len(d.verkoop)} ({_euro(d.som_verkoop)}) | {len(d.inkoop)} | {sluit} | "
            f"{tel[SOORT_ONTBREEKT_IN_DOEL]} | {tel[SOORT_BEDRAG_AFWIJKT]} | {tel[SOORT_STATUS_VERSCHILT]} | "
            f"{tel[SOORT_INKOOP_ZONDER_VERKOOP]} | {len(u.onderweg) if u else 0} | {stand} |"
        )
        if u is not None:
            for m in u.matches:
                if m.zeker and m.delta == 0:
                    secties["sluit"].append(
                        f"| {d.rij.doelentiteit_naam} | {m.verkoop.nummer or '?'} | {m.verkoop.datum.isoformat()} | "
                        f"{_euro(m.verkoop.bedrag)} | {m.verkoop.boekstuk or '—'} | {m.inkoop.boekstuk or '—'} | "
                        f"{_status(m.verkoop.status)} / {_status(m.inkoop.status)} | {m.regel} |"
                    )
            for b in u.bevindingen:
                x = b.extra
                secties[_IC_NAAR_DA[b.soort]].append(
                    f"| {d.rij.doelentiteit_naam} | {x.get('nummer') or '?'} | {x.get('datum') or '—'} | "
                    f"{x.get('bedrag_verkoop') or '—'} | {x.get('bedrag_inkoop') or '—'} | {x.get('boekstuk_a') or '—'} | "
                    f"{x.get('boekstuk_b') or '—'} | {b.detail} |"
                )
        if not d.doel_in_module:
            for f in d.verkoop:
                secties[SOORT_DOEL_NIET_IN_MODULE].append(
                    f"| {d.rij.doelentiteit_naam} | {f.nummer or '?'} | {f.datum.isoformat()} | {_euro(f.bedrag)} | "
                    f"{f.boekstuk or '—'} | {_status(f.status)} |"
                )
    koppen = {
        "sluit": ("Sluit", "| Doelentiteit | Nummer | Datum | Bedrag | Boekstuk verkoop | Boekstuk inkoop | Status v/i | Regel |", 8),
        SOORT_ONTBREEKT_IN_DOEL: ("Ontbreekt in doel (verkoop zónder inkoop)", None, 8),
        SOORT_BEDRAG_AFWIJKT: ("Bedrag afwijkt", None, 8),
        SOORT_STATUS_VERSCHILT: ("Status verschilt (> 7 d)", None, 8),
        SOORT_INKOOP_ZONDER_VERKOOP: ("Inkoop in doel zónder verkoop bij de bron", None, 8),
        SOORT_DOEL_NIET_IN_MODULE: ("Doel niet in module (verkoop aan een doelentiteit zonder administratie)", "| Doelentiteit | Nummer | Datum | Bedrag | Boekstuk | Status |", 6),
    }
    standaard_kop = "| Doelentiteit | Nummer | Datum | Bedrag verkoop | Bedrag inkoop | Boekstuk verkoop | Boekstuk inkoop | Detail |"
    for sleutel, (titel, kop, n) in koppen.items():
        rijen = secties[sleutel]
        uit.append("")
        uit.append(f"#### {titel} — {len(rijen)}")
        if rijen:
            uit.append(kop or standaard_kop)
            uit.append("|" + "---|" * n)
            uit.extend(rijen)
    return uit


# ---- reconciliatieblok ----------------------------------------------------------------------------------------


def cli_blok(  # noqa: C901, PLR0912, PLR0915 — één blokfunctie, contract van de andere blokken
    args,  # noqa: ANN001
    verzamelaar=None,  # noqa: ANN001
    *,
    bron_factory: Callable[[uuid.UUID], Bron] | None = None,
    bronnen: Sequence[uuid.UUID] | None = None,
    nu: date | None = None,
    meet_fn: Callable[..., Aansluiting] | None = None,
    stdout: Callable[[str], None] = print,
    stderr: Callable[[str], None] | None = None,
) -> int:
    """Blokfunctie voor `reconciliatie-alles`: per bron-administratie mét actieve whitelist één meting; élke
    afwijking als bevinding (acceptatie via `beoordeel`), exit 1 bij open afwijkingen of fouten."""
    from app.cli import _afwijking_detail, _regel, _soort_van
    from app.reconciliatie import service as acceptatie_service
    from app.tijd import vandaag_nl

    stderr = stderr or (lambda tekst: print(tekst, file=sys.stderr))
    nu = nu or vandaag_nl()
    dagen = int(getattr(args, "da_venster_dagen", None) or VENSTER_DAGEN)
    van, tot = nu - timedelta(days=dagen), nu
    meet_fn = meet_fn or meet

    def meld(**kw: Any) -> None:
        if verzamelaar is not None:
            verzamelaar.bevinding(**kw)

    if bronnen is None:
        try:
            bronnen = bronnen_met_whitelist()
        except Exception as exc:  # noqa: BLE001
            logger.exception("aansluiting: bron-administraties niet gelezen")
            tekst = f"FOUT       doorbelasting-aansluiting: whitelist niet gelezen: {str(exc)[:200]}"
            stderr(tekst)
            meld(soort="fout", administratie_id=None, tekst=tekst)
            return 1
    stdout(f"Venster {van.isoformat()} t/m {tot.isoformat()} ({dagen} dagen); {len(bronnen)} bron-administratie(s) mét whitelist.")
    if not bronnen:
        stdout("OK         geen administratie met een actieve doorbelasting-whitelist — niets te toetsen")
        return 0
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    open_totaal = 0
    geaccepteerd_totaal = 0
    fouten = 0
    for bron_id in bronnen:
        try:
            a = meet_fn(bron_administratie_id=bron_id, van=van, tot=tot, nu=nu, bron_factory=bron_factory)
        except Exception as exc:  # noqa: BLE001
            logger.exception("aansluiting: meting omgevallen voor %s", bron_id)
            fouten += 1
            tekst = f"FOUT       {bron_id}: meting omgevallen: {str(exc)[:200]}"
            stderr(tekst)
            meld(soort="fout", administratie_id=bron_id, tekst=tekst)
            continue
        kop = a.bron_naam or str(bron_id)
        for aid, reden in a.overgeslagen.items():
            stdout(f"OVERGESLAGEN {aid}: {reden}")
        for aid, reden in a.ongeldig.items():
            fouten += 1
            tekst = f"FOUT       {aid}: {reden}"
            stderr(tekst)
            meld(soort="fout", administratie_id=aid, tekst=tekst, detail={"fout": reden, "administratie_naam": _naam_van(aid)})
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(sum(len(d.verkoop) + len(d.inkoop) for d in a.doelen))
        afwijkingen: list[tuple[uuid.UUID, str, str, dict[str, Any]]] = []  # (record_id, soort, detail, extra)
        for d in a.doelen:
            if not d.doel_in_module:
                if d.verkoop:
                    afwijkingen.append(
                        (
                            d.rij.mapping_id,
                            SOORT_DOEL_NIET_IN_MODULE,
                            f"{len(d.verkoop)} verkoopfactu(u)r(en) ({_euro(d.som_verkoop)}) aan {d.rij.doelentiteit_naam} — "
                            "geen administratie in de module gekoppeld",
                            {
                                "doelentiteit_naam": d.rij.doelentiteit_naam,
                                "aantal": len(d.verkoop),
                                "som": _euro(d.som_verkoop),
                                "mapping_id": str(d.rij.mapping_id),
                                "doel_pad": f"/instellingen/administraties/{bron_id}/doorbelasting",
                            },
                        )
                    )
                continue
            if d.uitkomst is None:
                continue
            for b in d.uitkomst.bevindingen:
                extra = {k: v for k, v in b.extra.items() if k not in ("verkoop_ids", "inkoop_ids")}
                extra["doelentiteit_naam"] = d.rij.doelentiteit_naam
                extra["doel_administratie_id"] = str(d.rij.doel_administratie_id)
                boeking = next((d.open_spiegel.get(v.lower()) for v in b.extra.get("verkoop_ids", []) if d.open_spiegel.get(v.lower())), None)
                if boeking is not None:
                    extra["spiegel_boeking_id"] = str(boeking)
                    extra["doel_pad"] = f"/administraties/{bron_id}/doorbelasten"
                afwijkingen.append((b.record_id, _IC_NAAR_DA[b.soort], b.detail, extra))
        samenvatting = (
            f"{len(a.doelen)} doelentiteit(en), {sum(len(d.verkoop) for d in a.doelen)} verkoop / "
            f"{sum(len(d.inkoop) for d in a.doelen)} inkoop gelezen, "
            f"{sum(1 for d in a.doelen for m in (d.uitkomst.matches if d.uitkomst else []) if m.zeker and m.delta == 0)} sluiten"
        )
        if not afwijkingen:
            stdout(f"OK         {kop}: {samenvatting}, geen afwijkingen")
            continue
        beoordeeld = acceptatie_service.beoordeel(
            bron=ACCEPTATIE_BRON,
            administratie_id=bron_id,
            afwijkingen=[(rid, soort, detail) for rid, soort, detail, _ in afwijkingen],
        )
        uitsluiting = uitgesloten.get(bron_id)
        open_hier = [b for b in beoordeeld if b.telt_mee]
        if uitsluiting:
            geaccepteerd_totaal += len(beoordeeld) - len(open_hier)
            stdout(f"UITGESLOTEN {kop}: {len(open_hier)} open, {len(beoordeeld) - len(open_hier)} geaccepteerd — telt niet mee ({uitsluiting})")
        else:
            open_totaal += len(open_hier)
            geaccepteerd_totaal += len(beoordeeld) - len(open_hier)
            stdout(f"{'AFWIJKING ' if open_hier else 'OK        '} {kop}: {samenvatting}; {len(open_hier)} afwijking(en), {len(beoordeeld) - len(open_hier)} geaccepteerd")
        for (rid, soort, detail, extra), oordeel in zip(afwijkingen, beoordeeld, strict=True):
            regel = _regel(f"doelentiteit={extra.get('doelentiteit_naam')} nummer={extra.get('nummer')}", oordeel)
            stdout(f"    - {regel}")
            meld(
                soort=_soort_van(oordeel, uitsluiting),
                administratie_id=bron_id,
                tekst=regel,
                vingerafdruk=oordeel.vingerafdruk,
                detail=_afwijking_detail(ACCEPTATIE_BRON, oordeel, uitsluiting, administratie_naam=a.bron_naam, **extra),
            )
    stdout(f"\n{len(bronnen)} bron-administratie(s) getoetst, {open_totaal} afwijking(en) totaal ({geaccepteerd_totaal} geaccepteerd), {fouten} fout(en).")
    return 1 if (open_totaal or fouten) else 0


# ---- CLI `doorbelasting-aansluiting` (lees-only) ---------------------------------------------------------------


def register(subparsers) -> None:  # noqa: ANN001
    p = subparsers.add_parser(
        COMMANDO,
        help="Lees-only: verkoopfacturen van een bron-administratie ↔ inkoop in álle doelentiteiten (whitelist), "
        "incl. Zenvoices/handmatig; tabellen sluit / ontbreekt / bedrag / status / doel niet in module / inkoop zonder verkoop.",
    )
    p.add_argument("--bron", required=True, help="bron-administratie: uuid of naamdeel (bv. 'Kempen Facilities')")
    p.add_argument("--jaar", type=int, default=None, help="kalenderjaar van de verkoopfacturen (default: laatste 400 dagen)")
    p.add_argument("--van", default=None, help="begindatum JJJJ-MM-DD (overschrijft --jaar)")
    p.add_argument("--tot", default=None, help="einddatum JJJJ-MM-DD (default: vandaag)")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    return run_cli(args)


def run_cli(args: argparse.Namespace, *, zoek=None, meet_fn: Callable[..., Aansluiting] | None = None, stdout: Callable[[str], None] = print) -> int:  # noqa: ANN001
    from app.tijd import vandaag_nl

    if zoek is None:
        from app.cli import _zoek_administraties as zoek
    gevonden = zoek(args.bron)
    if len(gevonden) != 1:
        if not gevonden:
            print(f"FOUT: geen administratie gevonden voor {args.bron!r}", file=sys.stderr)
        else:
            print(f"FOUT: {args.bron!r} is niet eenduidig:", file=sys.stderr)
            for aid, naam in gevonden:
                print(f"    {aid}  {naam}", file=sys.stderr)
        return 2
    bron_id, naam = gevonden[0]
    nu = vandaag_nl()
    if args.van:
        van = date.fromisoformat(args.van)
    elif args.jaar:
        van = date(args.jaar, 1, 1)
    else:
        van = nu - timedelta(days=VENSTER_DAGEN)
    tot = date.fromisoformat(args.tot) if args.tot else (min(date(args.jaar, 12, 31), nu) if args.jaar and not args.van else nu)
    stdout(f"Bron: {naam} ({bron_id}); venster {van.isoformat()} t/m {tot.isoformat()} — LEES-ONLY, niets vastgelegd.")
    a = (meet_fn or meet)(bron_administratie_id=bron_id, van=van, tot=tot, nu=nu)
    for regel in rapport_regels(a):
        stdout(regel)
    if a.meting_ongeldig:
        return 3
    heeft_afwijking = any(
        (d.uitkomst is not None and d.uitkomst.bevindingen) or (not d.doel_in_module and d.verkoop) for d in a.doelen
    )
    return 1 if (heeft_afwijking or a.ongeldig) else 0
