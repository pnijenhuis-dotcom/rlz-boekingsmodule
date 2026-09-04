"""Duplicaat over de backend-grens (Odoo-slotstuk 04-09, blok A1-dedup; besluit Peter 04-09 "de overgangsdatum is
een kanteldatum, geen poort").

Ná een overstap RLZ → Odoo (ingang B) boekt een nakomer mét een factuurdatum vóór de kanteldatum óók in Odoo. Wat
al in Reeleezee geboekt was, mag dan níét nog eens in Odoo landen — maar de live duplicaatquery van de Odoo-adapter
(`odoo/inkoop.py::OdooLeesFacade`) ziet alleen Odoo, en de RLZ-webservice is voor die administratie bewust dood
(sentinel in `rlz_admin_id`). De enige bron die de RLZ-era kent is onze eigen historie: élk in de app GEBOEKT
document draagt zijn boekvoorstel (crediteur, referentie, totaalbedrag, boekstuknummer). Deze module levert die
treffers in exact de vorm van de facade/`_treffer_kort`, zodat de bestaande harde check, het duplicaatsignaal en de
auto-afvoer ze zonder eigen logica meenemen. Geen RLZ-/Odoo-calls, alleen DB.

Crediteur-sleutel = btw-nummer (`crediteur_kenmerk`) als beide kanten dat hebben, anders de vendor-UUID —
hergebruik van `duplicaat_afvoer._vendor_sleutel`: ná de overstap draagt de nakomer een Odoo-partner-UUID die nooit
gelijk is aan de RLZ-vendor-UUID van het origineel, dus matchen op vendor_id alleen zou de hele dedup blind maken.

Alleen actief voor een OVERGESTAPTE administratie (`boekhoud_backend == 'odoo'` én `odoo_koppeling.
rlz_admin_id_voor_overstap IS NOT NULL`). RLZ-administraties (live RLZ-query dekt alles) en nieuwe Odoo-
administraties zonder RLZ-verleden (niets te vinden) gedragen zich ongewijzigd."""

from __future__ import annotations

import uuid
from decimal import Decimal

from sqlalchemy import exists, select
from sqlalchemy.orm import Session

from app.db.models import Administratie
from app.documenten.models import Boekvoorstel, Document, DocumentSoort, DocumentStatus
from app.documenten.rlz_ids import rlz_herboeking_id
from app.sync.models import VendorCache

BRON_APP_HISTORIE = "app_historie"


def is_overgestapt(session: Session, administratie_id: uuid.UUID) -> bool:
    """True voor een administratie die van RLZ op Odoo is overgestapt (ingang B): backend 'odoo' mét bewaard oud
    RLZ-id op de koppeling. Platform-tabellen — leesbaar in élke sessie."""
    from app.odoo.models import OdooKoppeling  # lazy: geen kring documenten ↔ odoo op moduleniveau

    administratie = session.get(Administratie, administratie_id)
    if administratie is None or administratie.boekhoud_backend != "odoo":
        return False
    koppeling = session.get(OdooKoppeling, administratie_id)
    return koppeling is not None and bool(koppeling.rlz_admin_id_voor_overstap)


def _cent(waarde: Decimal | float | int | None) -> Decimal | None:
    if waarde is None:
        return None
    return Decimal(str(waarde)).quantize(Decimal("0.01"))


def geboekte_treffers_uit_historie(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    vendor_id: uuid.UUID | None,
    referentie: str | None,
    totaalbedrag: Decimal | None,
    eigen_document_id: uuid.UUID,
) -> list[dict]:
    """Alle in de app GEBOEKTE inkoopfacturen van de administratie met dezelfde kop (crediteur op vendor-sleutel,
    referentie genormaliseerd gelijk, totaalbedrag cent-gelijk), exclusief het eigen document en exclusief
    documenten die al in Odoo geboekt zijn (die vindt de live Odoo-query zelf). Lege lijst als de administratie niet
    overgestapt is of de kop incompleet is. Treffer-vorm = facade/`_treffer_kort` + `bron`/`document_id`/`backend`."""
    from app.documenten.crediteur_kenmerk import btw_per_vendor
    from app.documenten.duplicaat_afvoer import _vendor_sleutel, normaliseer_referentie

    ref = normaliseer_referentie(referentie)
    bedrag = _cent(totaalbedrag)
    if vendor_id is None or ref is None or bedrag is None:
        return []
    if not is_overgestapt(session, administratie_id):
        return []
    from app.odoo.models import OdooDocumentKoppeling

    in_odoo = exists().where(
        OdooDocumentKoppeling.document_id == Document.id,
        OdooDocumentKoppeling.soort == "boeking",
        OdooDocumentKoppeling.state != "cancel",
    )
    rijen = session.execute(
        select(Document, Boekvoorstel)
        .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
        .where(
            Document.administratie_id == administratie_id,
            Document.id != eigen_document_id,
            Document.soort == DocumentSoort.INKOOPFACTUUR.value,
            Document.status == DocumentStatus.GEBOEKT,
            Boekvoorstel.vendor_id.is_not(None),
            Boekvoorstel.totaalbedrag == bedrag,
            ~in_odoo,
        )
        .order_by(Document.aangemaakt_op, Document.id)
    ).all()
    if not rijen:
        return []

    btw = btw_per_vendor(session, administratie_id=administratie_id)
    eigen_sleutel = _vendor_sleutel(vendor_id, btw)
    kandidaten = [
        (document, voorstel)
        for document, voorstel in rijen
        if normaliseer_referentie(voorstel.referentie) == ref
        and _vendor_sleutel(voorstel.vendor_id, btw) == eigen_sleutel
    ]
    if not kandidaten:
        return []
    namen = {
        rij.id: rij.naam
        for rij in session.scalars(
            select(VendorCache).where(
                VendorCache.administratie_id == administratie_id,
                VendorCache.id.in_({v.vendor_id for _, v in kandidaten}),
            )
        )
    }
    treffers: list[dict] = []
    for document, voorstel in kandidaten:
        rlz_id = str(rlz_herboeking_id(document.id, voorstel.boek_cyclus))
        treffers.append(
            {
                "id": rlz_id,
                "Reference": voorstel.referentie,
                "reference": voorstel.referentie,
                "ReceiptNumber": voorstel.rlz_boekstuknummer,
                "InvoiceNumber": voorstel.rlz_boekstuknummer,
                "invoice_number": voorstel.rlz_boekstuknummer,
                # RLZ-vorm (dict mét id): `_treffer_kort` leest 'm als status 2 = geboekt/open.
                "Status": {"id": 2},
                "BaseInvoiceAmount": float(bedrag),
                "Entity": {"id": str(voorstel.vendor_id), "Name": namen.get(voorstel.vendor_id)},
                "bron": BRON_APP_HISTORIE,
                "document_id": str(document.id),
                "backend": "rlz",
            }
        )
    return treffers


def voeg_historie_toe(gevonden: list[dict], historie: list[dict]) -> list[dict]:
    """Merge live treffers + historie, dedup op `id` (een Odoo-era document dat de facade al onder zijn eigen
    deterministische id meldt, komt niet dubbel)."""
    if not historie:
        return list(gevonden)
    gezien = {str(f.get("id")) for f in gevonden}
    uit = list(gevonden)
    for t in historie:
        if str(t.get("id")) in gezien:
            continue
        gezien.add(str(t.get("id")))
        uit.append(t)
    return uit


def boekstukken(historie: list[dict]) -> str:
    """Leesbare opsomming van boekstuknummers (of 'boekstuk onbekend') voor check-/signaalmeldingen."""
    delen = [str(t.get("invoice_number") or t.get("ReceiptNumber") or "boekstuk onbekend") for t in historie]
    return ", ".join(delen)
