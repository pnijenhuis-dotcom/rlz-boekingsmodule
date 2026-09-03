"""Voorraad-uitstroom uit ODOO-verkoopfacturen — dagelijkse LEESROUTE (Odoo-adapter blok D 03-09, migratie
0102; casus Universal Verkoop, company 3: factureert sinds de knip in Odoo, boekt verder in RLZ).

Zusje van `app/voorraad/rlz_uitstroom.py`: dezelfde feitenlaag (`mi.voorraad_regel`, richting 'uit'), dezelfde
gedeelde schrijver (`registreer_externe_factuur`, vervangen per factuur = idempotent), dezelfde normalisatie —
alleen de bron verschilt (`odoo_verkoop`). STRIKT READ-ONLY tegen Odoo: de client is altijd `read_only=True`
(een alleen-lezen-koppeling dwingt dat in `odoo_client_voor` af; hier nog eens getoetst — nooit een write op
company 3).

Odoo-feiten waarop dit bouwt (odoo-verkenning §2.4 + §6):
- `account.move` met `move_type` out_invoice/out_refund; `state` posted = geboekt (draft/cancel = niet tellen, en
  eerder geregistreerde regels van een intussen geannuleerde factuur verdwijnen — zoals een RLZ-storno);
- `invoice_date` = factuurdatum (bron voor `datum` én voor de knip), `name` = het factuurnummer (F/2026/00027),
  `partner_id` = debiteur;
- regels `account.move.line` met `display_type = 'product'`: `quantity`, `price_unit`, `price_subtotal` (netto,
  cent-exact = quantity × price_unit), `name`, optioneel `product_id` → `default_code` = de artikelcode
  (expliciet, richting 'uit' — een andere sleutelruimte dan de inkoopcodes); `product_uom_id` = eenheid;
- een creditnota (`out_refund`) draagt POSITIEVE aantallen/bedragen — het teken zit in het documenttype, dus de
  route maakt aantal én netto negatief (bij RLZ zit het teken al in Quantity; nooit dubbel flippen).

Knip (migratie 0102): `voorraad_knip_datum` op de alleen-lezen-koppeling = vanaf deze factuurdatum is Odoo de
bron; de RLZ-route registreert facturen ≥ knip niet meer (en ruimt ze op), deze route leest nooit vóór de knip.
Tweede vangnet: een Odoo-factuurnummer dat al als RLZ-referentie in de feitenlaag staat wordt overgeslagen mét
teller (nooit dubbel tellen). Een échte Odoo-administratie (backend 'odoo') heeft geen knip: alles vanaf 1 januari.

Cadans: meelopend in `sync-alles`/`voorraad-rlz-sync` via `rlz_uitstroom.sync_voorraad_uitstroom` — incrementeel
vanaf max(datum) − 14 dagen (nooit vóór de knip), `--volledig` leest vanaf de knip/jaarstart opnieuw."""

from __future__ import annotations

import logging
import uuid
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from sqlalchemy import delete, func, select

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.odoo.credentials import GeenOdooKoppeling, OdooVerbinding, koppeling_voor, odoo_client_voor
from app.odoo.ids import odoo_uuid
from app.voorraad.models import VoorraadRegel

logger = logging.getLogger(__name__)

BRON = "odoo_verkoop"
MODEL_MOVE = "account.move"
MODEL_LINE = "account.move.line"
MODEL_PRODUCT = "product.product"
VERKOOP_TYPES = ("out_invoice", "out_refund")
HERLEES_VENSTER = timedelta(days=14)
PAGINA = 200

_MOVE_VELDEN = ["name", "state", "move_type", "invoice_date", "date", "partner_id", "invoice_line_ids", "company_id"]
_LINE_VELDEN = [
    "name",
    "quantity",
    "price_unit",
    "price_subtotal",
    "product_id",
    "product_uom_id",
    "display_type",
    "sequence",
]


class OdooLeesbronOngeldig(Exception):
    """De Odoo-verbinding voor de leesroute is niet read-only — fail-loud, nooit lezen met een schrijvende client."""


@dataclass(frozen=True)
class OdooUitstroomTelling:
    vanaf: date | None
    knip_datum: date | None = None
    company_id: int | None = None
    facturen_gelezen: int = 0
    facturen_verwerkt: int = 0
    regels: int = 0
    #: draft/cancel — niet geteld (+ eerder geregistreerde regels opgeruimd)
    overgeslagen_niet_geboekt: int = 0
    verwijderd_na_annulering: int = 0
    #: tweede vangnet: factuurnummer staat al als RLZ-referentie in de feitenlaag
    overgeslagen_dubbel: int = 0
    #: zichtbare skip-reden (geen Odoo-leesbron, opt-in uit, …) — nooit stil
    overgeslagen_reden: str | None = None

    def als_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["vanaf"] = self.vanaf.isoformat() if self.vanaf else None
        d["knip_datum"] = self.knip_datum.isoformat() if self.knip_datum else None
        return d


def _dec(waarde: object) -> Decimal | None:
    if waarde is None or isinstance(waarde, bool):
        return None
    try:
        return Decimal(str(waarde))
    except InvalidOperation:
        return None


def _m2o(waarde: Any) -> tuple[int | None, str | None]:
    if isinstance(waarde, list) and len(waarde) == 2:
        return int(waarde[0]), (str(waarde[1]) if waarde[1] else None)
    if isinstance(waarde, int):
        return waarde, None
    return None, None


def _datum(waarde: Any) -> date | None:
    if isinstance(waarde, str) and len(waarde) >= 10:
        try:
            return date.fromisoformat(waarde[:10])
        except ValueError:
            return None
    return None


def teken_voor(move_type: str | None) -> int:
    """Creditnota = retour = negatieve uitstroom; Odoo's out_refund draagt positieve regelbedragen."""
    return -1 if move_type == "out_refund" else 1


def externe_regels(move: dict[str, Any], lines: list[dict[str, Any]], product_codes: dict[int, str | None]) -> list:
    """Odoo-regels → `ExterneRegel`s voor de gedeelde schrijver (teken bepaald door het documenttype)."""
    from app.voorraad.rlz_uitstroom import ExterneRegel

    teken = teken_voor(move.get("move_type"))
    uit = []
    for line in sorted(lines, key=lambda r: (r.get("sequence") is None, r.get("sequence") or 0, int(r.get("id") or 0))):
        if line.get("display_type") not in (None, False, "product"):
            continue  # secties/notities/btw-/debiteurenregels tellen niet
        tekst = str(line.get("name") or "").strip()
        if not tekst:
            continue
        product_id, _ = _m2o(line.get("product_id"))
        _, eenheid = _m2o(line.get("product_uom_id"))
        aantal = _dec(line.get("quantity"))
        netto = _dec(line.get("price_subtotal"))
        uit.append(
            ExterneRegel(
                tekst=tekst,
                aantal=aantal * teken if aantal is not None else None,
                prijs=_dec(line.get("price_unit")),
                netto_bedrag=netto * teken if netto is not None else None,
                artikelcode=(product_codes.get(product_id) or None) if product_id is not None else None,
                eenheid=eenheid,
            )
        )
    return uit


def _leesbron_voor(administratie_id: uuid.UUID) -> tuple[OdooVerbinding | None, str | None]:
    """(verbinding, skip-reden): een alleen-lezen-koppeling MÉT knip, of een échte Odoo-administratie
    (geen knip: alles). Alleen-lezen zonder knip = geen voorraadrol → zichtbaar overgeslagen."""
    try:
        verbinding = koppeling_voor(administratie_id)
    except GeenOdooKoppeling:
        return None, "geen Odoo-koppeling"
    if verbinding.alleen_lezen and verbinding.voorraad_knip_datum is None:
        return None, "alleen-lezen Odoo-koppeling zonder voorraad-knip (Odoo heeft hier geen voorraadrol)"
    return verbinding, None


def _vanaf_datum(administratie_id: uuid.UUID, *, knip: date | None, volledig: bool) -> date:
    """Ondergrens = knip (of 1 januari van het lopende jaar). Incrementeel: jongste geregistreerde Odoo-datum −
    venster, maar nooit vóór de ondergrens."""
    ondergrens = knip or date(date.today().year, 1, 1)
    if volledig:
        return ondergrens
    with scoped_session(administratie_id) as session:
        laatste = session.scalar(
            select(func.max(VoorraadRegel.datum)).where(
                VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.bron == BRON
            )
        )
    if laatste is None:
        return ondergrens
    return max(ondergrens, min(laatste - HERLEES_VENSTER, date.today()))


def _rlz_referenties(administratie_id: uuid.UUID) -> set[str]:
    with scoped_session(administratie_id) as session:
        return {
            r
            for r in session.scalars(
                select(VoorraadRegel.rlz_referentie).where(
                    VoorraadRegel.administratie_id == administratie_id,
                    VoorraadRegel.bron == "rlz_verkoop",
                    VoorraadRegel.rlz_referentie.is_not(None),
                )
            )
            if r
        }


def lees_facturen(client: Any, *, company_id: int, vanaf: date) -> list[dict[str, Any]]:
    """Alle verkoopfacturen/-creditnota's van de company vanaf `vanaf` (álle states — annuleringen ruimen op),
    gepagineerd via de client (nooit de volledige collectie in één request)."""
    return client.search_read_alles(
        MODEL_MOVE,
        [
            ["company_id", "=", company_id],
            ["move_type", "in", list(VERKOOP_TYPES)],
            ["invoice_date", ">=", vanaf.isoformat()],
        ],
        _MOVE_VELDEN,
        pagina=PAGINA,
        order="invoice_date, id",
    )


def lees_regels(client: Any, line_ids: list[int]) -> list[dict[str, Any]]:
    if not line_ids:
        return []
    return client.read(MODEL_LINE, [int(i) for i in line_ids], _LINE_VELDEN)


def lees_product_codes(client: Any, product_ids: set[int]) -> dict[int, str | None]:
    if not product_ids:
        return {}
    rijen = client.read(MODEL_PRODUCT, sorted(product_ids), ["default_code"])
    return {int(r["id"]): (str(r["default_code"]).strip() or None) if r.get("default_code") else None for r in rijen}


def _verwijder_factuur(administratie_id: uuid.UUID, extern_id: uuid.UUID) -> int:
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        resultaat = session.execute(
            delete(VoorraadRegel).where(
                VoorraadRegel.administratie_id == administratie_id, VoorraadRegel.rlz_document_id == extern_id
            )
        )
        return int(resultaat.rowcount or 0)


def registreer_odoo_factuur(
    *,
    administratie_id: uuid.UUID,
    company_id: int,
    move: dict[str, Any],
    lines: list[dict[str, Any]],
    product_codes: dict,
) -> int:
    """Eén geposte Odoo-verkoopfactuur → haar regels als 'uit'-feiten (bron odoo_verkoop) via de gedeelde
    schrijver; het externe id is de deterministische odoo_uuid van de account.move."""
    from app.voorraad.rlz_uitstroom import registreer_externe_factuur

    datum = _datum(move.get("invoice_date")) or _datum(move.get("date"))
    if datum is None:
        raise ValueError(f"Odoo-factuur {move.get('name') or move.get('id')} zonder invoice_date/date")
    _, partner_naam = _m2o(move.get("partner_id"))
    return registreer_externe_factuur(
        administratie_id=administratie_id,
        bron=BRON,
        extern_document_id=odoo_uuid(company_id, MODEL_MOVE, int(move["id"])),
        referentie=str(move.get("name")) if move.get("name") else None,
        datum=datum,
        relatie_naam=partner_naam,
        regels=externe_regels(move, lines, product_codes),
    )


def sync_odoo_verkoopregels(
    *, administratie_id: uuid.UUID, client: Any | None = None, volledig: bool = False
) -> OdooUitstroomTelling:
    """De Odoo-leesroute voor één administratie. Opt-in uit / geen Odoo-leesbron = telling mét reden (nooit
    stil). Per factuur één transactie; audit per run (systeem-actor)."""
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None or not administratie.voorraad_ingeschakeld:
            return OdooUitstroomTelling(vanaf=None, overgeslagen_reden="voorraad-opt-in uit")
    verbinding, reden = _leesbron_voor(administratie_id)
    if verbinding is None:
        return OdooUitstroomTelling(vanaf=None, overgeslagen_reden=reden)
    knip = verbinding.voorraad_knip_datum
    vanaf = _vanaf_datum(administratie_id, knip=knip, volledig=volledig)
    eigen_client = client is None
    odoo = client or odoo_client_voor(administratie_id, read_only=True)
    if not getattr(odoo, "read_only", True):
        raise OdooLeesbronOngeldig("De voorraad-leesroute vereist een read-only Odoo-client (company-poort)")
    rlz_referenties = _rlz_referenties(administratie_id)
    gelezen = verwerkt = regels = niet_geboekt = verwijderd = dubbel = 0
    try:
        for move in lees_facturen(odoo, company_id=verbinding.company_id, vanaf=vanaf):
            gelezen += 1
            extern_id = odoo_uuid(verbinding.company_id, MODEL_MOVE, int(move["id"]))
            factuurdatum = _datum(move.get("invoice_date"))
            if knip is not None and factuurdatum is not None and factuurdatum < knip:
                continue  # vóór de knip is RLZ de bron (kan alleen bij een handmatig verschoven knip)
            if move.get("state") != "posted":
                niet_geboekt += 1
                verwijderd += _verwijder_factuur(administratie_id, extern_id)
                continue
            naam = str(move.get("name") or "")
            if naam and naam in rlz_referenties:
                dubbel += 1
                logger.warning(
                    "Odoo-factuur %s staat al als RLZ-referentie in de voorraad-feitenlaag van %s — overgeslagen",
                    naam,
                    administratie_id,
                )
                continue
            lines = lees_regels(odoo, list(move.get("invoice_line_ids") or []))
            product_ids = {pid for pid, _ in (_m2o(line.get("product_id")) for line in lines) if pid is not None}
            regels += registreer_odoo_factuur(
                administratie_id=administratie_id,
                company_id=verbinding.company_id,
                move=move,
                lines=lines,
                product_codes=lees_product_codes(odoo, product_ids),
            )
            verwerkt += 1
    finally:
        if eigen_client:
            odoo.close()
    telling = OdooUitstroomTelling(
        vanaf=vanaf,
        knip_datum=knip,
        company_id=verbinding.company_id,
        facturen_gelezen=gelezen,
        facturen_verwerkt=verwerkt,
        regels=regels,
        overgeslagen_niet_geboekt=niet_geboekt,
        verwijderd_na_annulering=verwijderd,
        overgeslagen_dubbel=dubbel,
    )
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="mi",
            tabel="voorraad_regel",
            record_id=administratie_id,
            actie="voorraad_odoo_uitstroom_gesynct",
            correlatie_id=uuid.uuid4(),
            nieuwe_waarde={**telling.als_dict(), "volledig": volledig},
            administratie_id=administratie_id,
        )
    return telling
