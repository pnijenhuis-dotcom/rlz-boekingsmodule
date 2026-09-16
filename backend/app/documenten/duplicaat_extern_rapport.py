"""LEES-ONLY rapport "mogelijk eerder dubbel geboekt" (Peter 16-09, Zenvoices-casus Hello Kitchen / Kempen Facilities).

Vraag Peter: is dit vaker gebeurd? Per RLZ-administratie: alle door de MODULE geboekte inkoopfacturen van de laatste N
dagen (default 400) worden genormaliseerd vergeleken met álle RLZ-inkoopfacturen in datzelfde venster (één gepagineerde
leesroute per administratie — geen call per document, zodat de webfilter-grens van ~700 calls buiten bereik blijft):
zelfde crediteur-identiteit (KvK/btw/voorkeur-cluster) én zelfde genormaliseerde referentie (`app/documenten/
referentie.py`) → "mogelijk dubbel"; de eigen (her)boek-/tegenboek-GUID's van het document tellen nooit mee. Zelfde
bedrag én datum bij een ander nummer wordt apart geteld als 'verdacht' (niet als dubbel).

Geen enkele write (ook niet in de eigen DB); Odoo-administraties worden zichtbaar overgeslagen (rapport RLZ-only in
deze versie — de Odoo-leesfacade kent geen administratiebrede collectie-lezing). Nameting-allowlist: `scripts/gcp/
nameting.sh duplicaat-extern-rapport [--dagen 400] [--administratie <uuid|naamdeel>]`."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.backends.registry import Backend, backend_voor
from app.db.models import Administratie
from app.db.session import scoped_session
from app.documenten import duplicaat_module, extern_bestaan
from app.documenten.models import Boekvoorstel, Document, DocumentSoort, DocumentStatus
from app.documenten.referentie import normaliseer_referentie
from app.documenten.rlz_ids import rlz_herboeking_id, rlz_tegenboeking_id
from app.rlz.client import RlzClient, bedrag_cent_exact
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor
from app.tijd import vandaag_nl

STANDAARD_DAGEN = 400


@dataclass(frozen=True)
class Dubbel:
    document_id: uuid.UUID
    eigen_boekstuk: str | None
    eigen_referentie: str | None
    extern_boekstuk: str | None
    extern_referentie: str | None
    bedrag: Decimal | None
    extern_bedrag: Decimal | None
    extern_status: int | None
    basis: str


@dataclass
class AdministratieRapport:
    administratie_id: uuid.UUID
    naam: str
    overgeslagen: str | None = None
    fout: str | None = None
    geboekt_getoetst: int = 0
    rlz_facturen_gelezen: int = 0
    rlz_calls: int = 0
    dubbel: list[Dubbel] = field(default_factory=list)
    verdacht: list[Dubbel] = field(default_factory=list)


def _lees_rlz_facturen(
    client: RlzClient, *, van: date, per_pagina: int = 200, max_paginas: int = 60
) -> tuple[list[dict], int]:
    rijen: list[dict[str, Any]] = []
    calls = 0
    for pagina in range(max_paginas):
        params = {
            "$filter": f"Date ge {van.isoformat()}",
            "$expand": "Entity",
            "$orderby": "Date asc,id asc",
            "$top": str(per_pagina),
            "$skip": str(pagina * per_pagina),
        }
        deel = client.get("PurchaseInvoices", params=params).get("value", [])
        calls += 1
        rijen.extend(deel)
        if len(deel) < per_pagina:
            break
    return rijen, calls


def rapport_voor_administratie(
    administratie_id: uuid.UUID, *, dagen: int = STANDAARD_DAGEN, client: RlzClient | None = None
) -> AdministratieRapport:
    with scoped_session(None) as session:
        adm = session.get(Administratie, administratie_id)
        naam = adm.naam if adm is not None else str(administratie_id)
    r = AdministratieRapport(administratie_id=administratie_id, naam=naam)
    if backend_voor(administratie_id) == Backend.ODOO:
        r.overgeslagen = "Odoo-administratie — rapport is RLZ-only in deze versie"
        return r
    van = vandaag_nl() - timedelta(days=dagen)
    with scoped_session(administratie_id) as session:
        eigen = session.execute(
            select(Boekvoorstel, Document.id)
            .join(Document, Document.id == Boekvoorstel.document_id)
            .where(
                Document.administratie_id == administratie_id,
                Document.soort == DocumentSoort.INKOOPFACTUUR.value,
                Document.status == DocumentStatus.GEBOEKT,
                Boekvoorstel.factuurdatum.is_not(None),
                Boekvoorstel.factuurdatum >= van,
            )
        ).all()
        identiteiten = duplicaat_module._identiteiten(session, administratie_id=administratie_id)
        koppen = [
            (
                doc_id,
                bv.vendor_id,
                bv.referentie,
                bv.totaalbedrag,
                bv.factuurdatum,
                bv.rlz_boekstuknummer,
                bv.boek_cyclus,
            )
            for bv, doc_id in eigen
        ]
    r.geboekt_getoetst = len(koppen)
    if not koppen:
        return r
    eigen_client = client is None
    if client is None:
        rlz_admin_id = rlz_admin_id_voor(administratie_id)
        client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
    try:
        rijen, r.rlz_calls = _lees_rlz_facturen(client, van=van)
    except Exception as exc:  # noqa: BLE001 — lees-only rapport: fout is een uitkomst, geen crash
        r.fout = f"RLZ-lezing mislukt: {exc}"
        return r
    finally:
        if eigen_client:
            client.close()
    r.rlz_facturen_gelezen = len(rijen)
    # Index: (identiteitssleutel) → rijen; identiteit van een RLZ-rij via Entity/id → sleutelset.
    per_vendor: dict[str, list[dict]] = defaultdict(list)
    for rij in rijen:
        entity = str(((rij.get("Entity") or {}).get("id")) or "")
        per_vendor[entity].append(rij)

    def _identiteit(vendor_id: uuid.UUID | None) -> set[str]:
        if vendor_id is None:
            return set()
        return {str(vendor_id)} | {
            str(vid)
            for vid, sleutels in identiteiten.items()
            if sleutels & identiteiten.get(vendor_id, frozenset({f"vendor:{vendor_id}"}))
        }

    for doc_id, vendor_id, referentie, bedrag, factuurdatum, boekstuk, cyclus in koppen:
        keten = {str(rlz_herboeking_id(doc_id, c)) for c in range(cyclus + 1)} | {
            str(rlz_tegenboeking_id(doc_id, c)) for c in range(cyclus + 1)
        }
        norm = normaliseer_referentie(referentie)
        for entity in _identiteit(vendor_id):
            for rij in per_vendor.get(entity, []):
                if str(rij.get("id")) in keten:
                    continue
                basis = extern_bestaan.bepaal_basis(
                    rij, referentie_norm=norm, totaalbedrag=bedrag, factuurdatum=factuurdatum
                )
                if basis is None:
                    continue
                d = Dubbel(
                    document_id=doc_id,
                    eigen_boekstuk=boekstuk,
                    eigen_referentie=referentie,
                    extern_boekstuk=rij.get("ReceiptNumber"),
                    extern_referentie=rij.get("Reference"),
                    bedrag=bedrag,
                    extern_bedrag=bedrag_cent_exact(rij.get("BaseInvoiceAmount")),
                    extern_status=extern_bestaan.status_van(rij),
                    basis=basis,
                )
                (r.dubbel if basis in extern_bestaan.BLOKKERENDE_BASES else r.verdacht).append(d)
    return r


def rapport(
    *, dagen: int = STANDAARD_DAGEN, administratie_ids: list[uuid.UUID] | None = None
) -> list[AdministratieRapport]:
    with scoped_session(None) as session:
        q = select(Administratie.id).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
        if administratie_ids:
            q = q.where(Administratie.id.in_(administratie_ids))
        ids = list(session.scalars(q))
    uit: list[AdministratieRapport] = []
    for aid in ids:
        try:
            uit.append(rapport_voor_administratie(aid, dagen=dagen))
        except Exception as exc:  # noqa: BLE001 — één kapotte administratie stopt het rapport niet
            uit.append(AdministratieRapport(administratie_id=aid, naam=str(aid), fout=str(exc)))
    return uit


def print_rapport(rapporten: list[AdministratieRapport], *, dagen: int, stdout=print) -> None:
    tot_dubbel = sum(len(r.dubbel) for r in rapporten)
    tot_verdacht = sum(len(r.verdacht) for r in rapporten)
    tot_getoetst = sum(r.geboekt_getoetst for r in rapporten)
    stdout(
        f"duplicaat-extern-rapport (lees-only, laatste {dagen} dagen): {len(rapporten)} administratie(s), "
        f"{tot_getoetst} geboekte module-facturen getoetst, {tot_dubbel} mogelijk dubbel (zelfde crediteur + "
        f"genormaliseerde referentie), {tot_verdacht} verdacht (zelfde bedrag en datum, ander nummer)"
    )
    for r in rapporten:
        if r.overgeslagen:
            stdout(f"  OVERGESLAGEN {r.naam}: {r.overgeslagen}")
            continue
        if r.fout:
            stdout(f"  FOUT         {r.naam}: {r.fout}")
            continue
        kop = "DUBBEL     " if r.dubbel else ("VERDACHT   " if r.verdacht else "OK         ")
        stdout(
            f"  {kop} {r.naam}: {r.geboekt_getoetst} getoetst, {r.rlz_facturen_gelezen} RLZ-facturen gelezen "
            f"({r.rlz_calls} calls), {len(r.dubbel)} dubbel, {len(r.verdacht)} verdacht"
        )
        for d in r.dubbel + r.verdacht:
            status = {1: "concept", 2: "open", 3: "gesloten"}.get(d.extern_status or 0, "status onbekend")
            stdout(
                f"    - {d.basis}: module {d.eigen_boekstuk or '?'} ({d.eigen_referentie!r}, € {d.bedrag}) ↔ "
                f"RLZ {d.extern_boekstuk or '?'} ({d.extern_referentie!r}, € {d.extern_bedrag}, {status})"
            )
