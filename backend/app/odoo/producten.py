"""Materiaalcatalogus → Odoo `product.product` (blok B, eis Peter 03-09: boeken op PRODUCTEN waar mogelijk zodat
regelniveau-data — product, aantal, prijs — in Odoo landt voor Jarvis/MI).

Twee delen:
1. `leg_brug` — per (administratie, leverancier) élk actief catalogusproduct koppelen aan een product.product:
   LOOKUP EERST (op `default_code` = onze deterministische code, dan op exacte naam binnen de company-context),
   anders idempotente aanmaak (product.template mét `default_code`, `type consu`, `purchase_ok`, `uom`, categorie
   uit de catalogus-categorie — zie odoo-verkenning §6 voor de account-afleiding: de regel draagt ALTIJD een
   expliciete `account_id` uit het boekvoorstel; het product verandert de rekening niet). Koppeling in
   `odoo_product_koppeling` (bron gevonden/aangemaakt), audit per aanmaak.
2. `producten_voor_regels` — bij het boeken: per boekvoorstel-regel het product + aantal/stuksprijs bepalen uit
   het veldvoorstel (dezelfde regelvolgorde), UITSLUITEND als `aantal × stuksprijs = netto` cent-exact klopt
   (geld = code) én de omschrijving/artikelcode één catalogusproduct van déze leverancier aanwijst; anders
   quantity 1 × netto zonder product (nooit gokken). Samengevoegde voorstellen (één regel) krijgen geen product."""

from __future__ import annotations

import logging
import re
import uuid
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation

from sqlalchemy import select

from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.documenten.boekvoorstel import BoekvoorstelData
from app.documenten.models import DocumentGebeurtenis
from app.materiaal.models import MateriaalLeverancier, MateriaalProduct
from app.odoo.client import OdooClient, OdooFout
from app.odoo.credentials import koppeling_voor, odoo_client_voor
from app.odoo.models import OdooProductKoppeling

logger = logging.getLogger(__name__)

MODEL_PRODUCT = "product.product"
MODEL_TEMPLATE = "product.template"
MODEL_CATEGORIE = "product.category"

#: Eenheid catalogus → Odoo uom.uom-naam (STAP-0 §6: Units=1, m²=10, m=8 — id's per db, dus op naam zoeken).
UOM_NAAM_PER_EENHEID = {"stuks": "Units", "rol": "Units", "m1": "m", "m2": "m²"}


def product_code(materiaal_product_id: uuid.UUID) -> str:
    """Deterministische `default_code` — de idempotentie-sleutel van de brug."""
    return f"AKN-{str(materiaal_product_id)[:8].upper()}"


def _normaliseer(tekst: str | None) -> str:
    return re.sub(r"\s+", " ", (tekst or "")).strip().casefold()


@dataclass(frozen=True)
class ProductRegel:
    odoo_product_id: int
    naam: str
    quantity: Decimal | None
    price_unit: Decimal | None
    uom_id: int | None


@dataclass
class BrugUitkomst:
    gevonden: int = 0
    aangemaakt: int = 0
    overgeslagen: list[str] = field(default_factory=list)


def _uom_ids(client: OdooClient) -> dict[str, int]:
    rijen = client.search_read("uom.uom", [], ["id", "name"])
    return {str(r["name"]): int(r["id"]) for r in rijen}


def _categorie_id(client: OdooClient, naam: str | None, cache: dict[str, int | None]) -> int | None:
    """Bestaande Odoo-categorie op (complete_)naam; niets aanmaken — een categorie draagt de boekhoudkundige
    defaults (§6) en is daarmee een inrichtingskeuze in Odoo, geen adapter-beslissing."""
    if not naam:
        return None
    if naam in cache:
        return cache[naam]
    rijen = client.search_read(MODEL_CATEGORIE, [["name", "=ilike", naam]], ["id"])
    cache[naam] = int(rijen[0]["id"]) if len(rijen) == 1 else None
    return cache[naam]


def leg_brug(*, administratie_id: uuid.UUID, actor_id: uuid.UUID, client: OdooClient | None = None) -> BrugUitkomst:
    verbinding = koppeling_voor(administratie_id)
    eigen = client is None
    client = client or odoo_client_voor(administratie_id)
    uitkomst = BrugUitkomst()
    try:
        uoms = _uom_ids(client)
        categorie_cache: dict[str, int | None] = {}
        with scoped_session(administratie_id, actor_id=actor_id) as session:
            producten = session.scalars(
                select(MateriaalProduct)
                .join(MateriaalLeverancier, MateriaalLeverancier.id == MateriaalProduct.leverancier_id)
                .where(MateriaalLeverancier.administratie_id == administratie_id, MateriaalProduct.actief.is_(True))
                .order_by(MateriaalProduct.naam)
            ).all()
            leveranciers = {
                lev.id: lev
                for lev in session.scalars(
                    select(MateriaalLeverancier).where(MateriaalLeverancier.administratie_id == administratie_id)
                )
            }
            bestaande = {
                k.materiaal_product_id: k
                for k in session.scalars(
                    select(OdooProductKoppeling).where(OdooProductKoppeling.administratie_id == administratie_id)
                )
            }
            for product in producten:
                if product.id in bestaande:
                    uitkomst.gevonden += 1
                    continue
                code = product_code(product.id)
                treffer = client.search_read(
                    MODEL_PRODUCT,
                    [["default_code", "=", code], ["company_id", "in", [client.company_id, False]]],
                    ["id", "name", "product_tmpl_id"],
                )
                bron = "gevonden"
                if not treffer:
                    treffer = client.search_read(
                        MODEL_PRODUCT,
                        [["name", "=ilike", product.naam], ["company_id", "in", [client.company_id, False]]],
                        ["id", "name", "product_tmpl_id"],
                    )
                    if len(treffer) > 1:
                        uitkomst.overgeslagen.append(f"{product.naam}: {len(treffer)} Odoo-producten met deze naam")
                        continue
                if not treffer:
                    leverancier = leveranciers.get(product.leverancier_id)
                    categorie_naam = None
                    if product.categorie_id is not None:
                        from app.materiaal.models import MateriaalCategorie

                        cat = session.get(MateriaalCategorie, product.categorie_id)
                        categorie_naam = cat.naam if cat else None
                    vals = {
                        "name": product.naam,
                        "default_code": code,
                        "type": "consu",
                        "purchase_ok": True,
                        "sale_ok": False,
                        "company_id": client.company_id,
                        "description_purchase": (
                            f"Materiaalcatalogus {leverancier.naam if leverancier else ''} · {product.verpakking or ''}"
                        ).strip(" ·"),
                    }
                    uom_id = uoms.get(UOM_NAAM_PER_EENHEID.get(product.eenheid or "stuks", "Units"))
                    if uom_id:
                        vals["uom_id"] = uom_id
                    categ = _categorie_id(client, categorie_naam, categorie_cache)
                    if categ:
                        vals["categ_id"] = categ
                    try:
                        tmpl_id = client.create(MODEL_TEMPLATE, vals)
                    except OdooFout as exc:
                        uitkomst.overgeslagen.append(f"{product.naam}: Odoo weigert aanmaak ({exc.naam or exc.status})")
                        continue
                    treffer = client.search_read(
                        MODEL_PRODUCT, [["product_tmpl_id", "=", tmpl_id]], ["id", "name", "product_tmpl_id"]
                    )
                    bron = "aangemaakt"
                    uitkomst.aangemaakt += 1
                else:
                    uitkomst.gevonden += 1
                rij = treffer[0]
                tmpl = rij.get("product_tmpl_id")
                session.add(
                    OdooProductKoppeling(
                        administratie_id=administratie_id,
                        materiaal_product_id=product.id,
                        odoo_product_id=int(rij["id"]),
                        odoo_template_id=int(tmpl[0]) if isinstance(tmpl, list) else None,
                        default_code=code,
                        naam=str(rij.get("name") or product.naam),
                        bron=bron,
                    )
                )
                record_audit_event(
                    session,
                    actor_id=actor_id,
                    module="boekhouding",
                    tabel="odoo_product_koppeling",
                    record_id=product.id,
                    actie=f"odoo_product_{bron}",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "odoo_product_id": int(rij["id"]),
                        "default_code": code,
                        "company_id": verbinding.company_id,
                    },
                    administratie_id=administratie_id,
                )
    finally:
        if eigen:
            client.close()
    return uitkomst


# --- bij het boeken -------------------------------------------------------------------------------


def _laatste_veldvoorstel(session, document_id: uuid.UUID) -> dict | None:
    gebeurtenissen = session.scalars(
        select(DocumentGebeurtenis)
        .where(DocumentGebeurtenis.document_id == document_id)
        .order_by(DocumentGebeurtenis.tijdstip.desc())
    )
    for g in gebeurtenissen:
        if g.detail and "veldvoorstel" in g.detail:
            return g.detail["veldvoorstel"]
    return None


def _decimal(waarde: object) -> Decimal | None:
    if waarde is None or waarde == "":
        return None
    try:
        return Decimal(str(waarde).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None


def producten_voor_regels(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, voorstel: BoekvoorstelData
) -> dict[int, ProductRegel]:
    """{regel-index: ProductRegel} — alleen voor regels die eenduidig één gekoppeld catalogusproduct van de
    crediteur aanwijzen. Aantal/stuksprijs alleen als `aantal × stuksprijs = netto` cent-exact (anders None →
    quantity 1 × netto, wél mét product)."""
    if voorstel.vendor_id is None or not voorstel.regels or voorstel.regels_samenvoegen:
        return {}
    with scoped_session(administratie_id) as session:
        leverancier = session.scalars(
            select(MateriaalLeverancier).where(
                MateriaalLeverancier.administratie_id == administratie_id,
                MateriaalLeverancier.vendor_id == voorstel.vendor_id,
            )
        ).first()
        if leverancier is None:
            return {}
        koppelingen = {
            k.materiaal_product_id: k
            for k in session.scalars(
                select(OdooProductKoppeling).where(OdooProductKoppeling.administratie_id == administratie_id)
            )
        }
        producten = session.scalars(
            select(MateriaalProduct).where(
                MateriaalProduct.leverancier_id == leverancier.id, MateriaalProduct.id.in_(list(koppelingen))
            )
        ).all()
        if not producten:
            return {}
        op_naam: dict[str, list[MateriaalProduct]] = {}
        for p in producten:
            op_naam.setdefault(_normaliseer(p.naam), []).append(p)
        veldvoorstel = _laatste_veldvoorstel(session, document_id) or {}
    ai_regels = veldvoorstel.get("regels") if isinstance(veldvoorstel.get("regels"), list) else []
    uitkomst: dict[int, ProductRegel] = {}
    for i, regel in enumerate(voorstel.regels):
        kandidaten = op_naam.get(_normaliseer(regel.omschrijving), [])
        if len(kandidaten) != 1:
            # Terugval: omschrijving BEVAT exact één productnaam.
            omschrijving = _normaliseer(regel.omschrijving)
            kandidaten = [p for naam, ps in op_naam.items() if naam and naam in omschrijving for p in ps]
            if len(kandidaten) != 1:
                continue
        product = kandidaten[0]
        koppeling = koppelingen[product.id]
        quantity = price_unit = None
        ai = ai_regels[i] if i < len(ai_regels) and isinstance(ai_regels[i], dict) else {}
        aantal = _decimal(ai.get("hoeveelheid"))
        prijs = _decimal(ai.get("stuksprijs"))
        netto = Decimal(regel.netto_bedrag).quantize(Decimal("0.01")) if regel.netto_bedrag is not None else None
        if aantal and prijs and netto is not None and (aantal * prijs).quantize(Decimal("0.01")) == netto:
            quantity, price_unit = aantal, prijs
        uitkomst[i] = ProductRegel(
            odoo_product_id=koppeling.odoo_product_id,
            naam=koppeling.naam or product.naam,
            quantity=quantity,
            price_unit=price_unit,
            uom_id=None,
        )
    return uitkomst
