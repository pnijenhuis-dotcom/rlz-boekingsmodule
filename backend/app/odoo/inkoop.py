"""Odoo-adapter voor de inkoop-port (blok C, fase 1) — de Odoo-uitvoering van het bestaande inkoop-boekpad
(veldvoorstel → harde checks → boeken). Feiten: `verkenning/odoo-verkenning.md` §2.2, §3, §4 A, §6.

Boeken (`boek_inkoopfactuur`), in deze volgorde — élke stap fail-loud, nooit stil:
 1. vertaling UUID → Odoo-int via `odoo_id_koppeling` (partner, rekening, btw, project) — onbekend = fout;
 2. lock-date-poort: `date` (= factuurdatum, BookDate-lijn) op/vóór een Odoo-lock date = leesbare weigering
    vóór de create (STAP-0 §3.5; K3: lock dates staan op 31-12-2025);
 3. idempotentie (§3.1): (a) eigen `odoo_document_koppeling` voor (document, boek_cyclus) → move terug-lezen
    (posted = klaar, draft = doorgaan, cancel = opnieuw); (b) anders zoeken op onze marker in `invoice_origin`
    (company, in_invoice, state ≠ cancel) — een create waarvan het antwoord verloren ging; (c) anders create;
 4. create `account.move` in_invoice mét `company_id`, `journal_id` (uit de probe, nooit geraden), `partner_id`,
    `ref` = factuurnummer, `payment_reference` = betalingskenmerk, `invoice_date` + **`date` expliciet =
    factuurdatum** (Odoo-default = maandeinde), `invoice_date_due` + `invoice_payment_term_id False`,
    regels `quantity × price_unit = netto` (cent-exact), `tax_ids` (0 % = géén), `analytic_distribution`
    {project: 100}, `product_id` waar de materiaalbrug een product kent (regelniveau-data — eis Peter);
 5. btw-cent-override (besluit Peter 02-09): Odoo-berekende btw (round_globally) ≠ factuur-btw per tarief →
    tot ± € 0,02 `write balance` op de tax-regel mét zichtbare chip (detail `btw_override`), daarboven
    blokkerend (concept geannuleerd, nooit half);
 6. totaal-verificatie vóór het posten (amount_total = factuurtotaal cent-exact);
 7. `action_post` → POST-WRITE-VERIFICATIE (company-poort, heilig): terug-lezen state/name/company_id/
    amount_total — verkeerde company = kritieke fout mét audit;
 8. bijlage NÁ het posten (`ir.attachment` + `register_as_main_attachment(force)`), idempotent op checksum;
    een bijlage-fout ná een geslaagde post is een zichtbare waarschuwing op de boeking, geen boeken_mislukt
    (de boeking stáát in Odoo — inconsistentie zou erger zijn).
Tegenboeken (`boek_tegenboeking`) = Odoo's reversal (`account.move.reversal` → `in_refund`) mét
kruisverwijzing, de gespiegelde tax-override (de wizard neemt die niet mee, §3.3), posten, bijlage.
`button_draft` wordt bewust NOOIT gebruikt (governance-aanbeveling §3.3, besluit Peter 02-09)."""

from __future__ import annotations

import base64
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import date
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.backends.port import Backend, BackendBoekFout, BoekUitkomst, NietOndersteund, OrigineelStand, TegenboekUitkomst
from app.db.audit import record_audit_event
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.boekvoorstel import BoekvoorstelData
from app.odoo import sync as odoo_sync
from app.odoo.client import OdooClient, OdooFout
from app.odoo.credentials import OdooVerbinding, koppeling_voor, odoo_client_voor
from app.odoo.fouten import lock_date_melding, vertaal_odoo_fout
from app.odoo.ids import GEEN_BTW_ODOO_ID, odoo_uuid
from app.odoo.models import OdooDocumentKoppeling
from app.odoo.probe import lees_lock_dates
from app.rlz.aangifte import KantToets
from app.sync.models import TaxRateCache

logger = logging.getLogger(__name__)

MODEL_MOVE = "account.move"
MODEL_LINE = "account.move.line"
MODEL_ATTACHMENT = "ir.attachment"
MODEL_REVERSAL = "account.move.reversal"

#: Besluit Peter 02-09: cent-verschillen tussen factuur-btw en Odoo's berekening tot ± € 0,02 per tarief
#: worden overschreven (mét chip); daarboven blokkerend.
BTW_OVERRIDE_TOLERANTIE = Decimal("0.02")

_MOVE_VELDEN = [
    "name",
    "state",
    "payment_state",
    "company_id",
    "partner_id",
    "amount_untaxed",
    "amount_tax",
    "amount_total",
    "amount_residual",
    "date",
    "invoice_date",
    "ref",
    "invoice_origin",
    "reversed_entry_id",
    "reversal_move_ids",
    "move_type",
]


def marker(document_id: uuid.UUID, boek_cyclus: int, soort: str = "boeking") -> str:
    """Onze deterministische herkenning in `invoice_origin` (Odoo kent geen client-GUID) — zichtbaar in de
    Odoo-UI als 'Bron' en het zoek-anker bij een verloren create-antwoord."""
    return f"AKN:{document_id}:{boek_cyclus}:{soort}"


def _cent(waarde: Decimal | float | int | None) -> Decimal:
    return Decimal(str(waarde or 0)).quantize(Decimal("0.01"))


def _m2o_id(waarde: Any) -> int | None:
    if isinstance(waarde, list) and len(waarde) == 2:
        return int(waarde[0])
    if isinstance(waarde, int):
        return waarde
    return None


@dataclass(frozen=True)
class _Regel:
    naam: str
    account_id: int
    tax_id: int | None
    netto: Decimal
    btw: Decimal
    analytic_account_id: int | None
    product_id: int | None
    quantity: Decimal
    price_unit: Decimal
    product_uom_id: int | None


class OdooLeesFacade:
    """Het duck-typed leesobject voor de bestaande harde checks — geeft RLZ-veldnamen terug zodat
    checks.py/leverancier_iban.py ongewijzigd blijven (pakketkennis leeft hier)."""

    def __init__(self, port: OdooInkoopPort) -> None:
        self._port = port

    def find_purchase_invoices_by_reference(
        self,
        *,
        vendor_id: uuid.UUID | str | None,
        reference: str,
        total_amount: float | None = None,
        expand_entity: bool = False,
    ) -> list[dict[str, Any]]:
        client = self._port.client
        domain: list = [
            ["company_id", "=", client.company_id],
            ["move_type", "=", "in_invoice"],
            ["state", "!=", "cancel"],
            ["ref", "=", reference],
        ]
        if vendor_id is not None:
            domain.append(["partner_id", "=", self._port.partner_id_voor(uuid.UUID(str(vendor_id)))])
        rijen = client.search_read(MODEL_MOVE, domain, ["name", "partner_id", "amount_total", "state", "payment_state"])
        uit: list[dict[str, Any]] = []
        for rij in rijen:
            afwijking = abs(_cent(rij.get("amount_total")) - _cent(total_amount)) if total_amount is not None else 0
            if afwijking > Decimal("0.005"):
                continue
            partner = rij.get("partner_id")
            partner_id = _m2o_id(partner)
            uit.append(
                {
                    "id": str(odoo_uuid(client.company_id, MODEL_MOVE, int(rij["id"]))),
                    "ReceiptNumber": rij.get("name") or None,
                    "Status": (
                        1
                        if rij.get("state") == "draft"
                        else 3
                        if rij.get("payment_state") in ("paid", "reversed")
                        else 2
                    ),
                    "BaseInvoiceAmount": float(_cent(rij.get("amount_total"))),
                    "Entity": {
                        "id": str(odoo_uuid(client.company_id, "res.partner", partner_id)) if partner_id else None,
                        "Name": partner[1] if isinstance(partner, list) else None,
                    },
                }
            )
        return uit

    def get(self, path: str, *, params: dict[str, Any] | None = None) -> dict[str, Any]:
        """Alleen de leesroute die de IBAN-wissel-check gebruikt: `Vendors/{id}/BankRelations`."""
        delen = path.strip("/").split("/")
        if len(delen) == 3 and delen[0] == "Vendors" and delen[2] == "BankRelations":
            partner_id = self._port.partner_id_voor(uuid.UUID(delen[1]))
            rijen = self._port.client.search_read(
                "res.partner.bank",
                [["partner_id", "=", partner_id], ["active", "in", [True, False]]],
                ["acc_number", "active"],
            )
            return {"value": [{"IBAN": r.get("acc_number"), "IsArchived": not r.get("active", True)} for r in rijen]}
        raise NietOndersteund(f"Odoo-adapter: leesroute {path!r} bestaat niet (alleen Vendors/{{id}}/BankRelations)")

    def list_tax_declarations(self) -> list[dict[str, Any]]:
        raise NietOndersteund("Odoo-adapter: btw-aangiftestatus loopt via de lock dates, niet via TaxDeclarations")

    def close(self) -> None:  # de port sluit de verbinding
        return None


class OdooInkoopPort:
    backend = Backend.ODOO

    def __init__(self, administratie_id: uuid.UUID, verbinding: OdooVerbinding, client: OdooClient) -> None:
        self.administratie_id = administratie_id
        self.verbinding = verbinding
        self.client = client
        self._facade = OdooLeesFacade(self)

    @classmethod
    def voor(cls, administratie_id: uuid.UUID) -> OdooInkoopPort:
        verbinding = koppeling_voor(administratie_id)
        return cls(administratie_id, verbinding, odoo_client_voor(administratie_id))

    def __enter__(self) -> OdooInkoopPort:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.client.close()

    def leesclient(self) -> Any:
        return self._facade

    # --- id-vertaling ------------------------------------------------------------------------------
    def _odoo_id(self, model: str, lokaal_id: uuid.UUID) -> int:
        with scoped_session(self.administratie_id) as session:
            return odoo_sync.odoo_id_voor(
                session, administratie_id=self.administratie_id, model=model, lokaal_id=lokaal_id
            )

    def partner_id_voor(self, vendor_id: uuid.UUID) -> int:
        return self._odoo_id("res.partner", vendor_id)

    def _verlegde_taxrates(self) -> set[uuid.UUID]:
        with scoped_session(self.administratie_id) as session:
            rijen = session.scalars(select(TaxRateCache).where(TaxRateCache.administratie_id == self.administratie_id))
            return {r.id for r in rijen if (r.brondata or {}).get("IsRelayed")}

    def _vertaal_regels(self, document_id: uuid.UUID, voorstel: BoekvoorstelData) -> list[_Regel]:
        from app.odoo.producten import producten_voor_regels

        try:
            producten = producten_voor_regels(
                administratie_id=self.administratie_id, document_id=document_id, voorstel=voorstel
            )
        except Exception as exc:  # noqa: BLE001 — productverrijking is een verrijking, nooit een blokkade
            logger.warning("Productverrijking overgeslagen voor %s: %s", document_id, exc)
            producten = {}
        regels: list[_Regel] = []
        for i, regel in enumerate(voorstel.regels):
            if regel.ledger_id is None or regel.taxrate_id is None or regel.netto_bedrag is None:
                raise BackendBoekFout(f"Regel {i + 1} mist rekening, btw-code of bedrag — boeken geweigerd")
            tax_odoo = self._odoo_id("account.tax", regel.taxrate_id)
            product = producten.get(i)
            netto = _cent(regel.netto_bedrag)
            quantity, price_unit, product_id, uom = Decimal("1"), netto, None, None
            if product is not None:
                product_id, uom = product.odoo_product_id, product.uom_id
                if product.quantity is not None and product.price_unit is not None:
                    quantity, price_unit = product.quantity, product.price_unit
            regels.append(
                _Regel(
                    naam=regel.omschrijving or (product.naam if product else None) or "Inkoop",
                    account_id=self._odoo_id("account.account", regel.ledger_id),
                    tax_id=None if tax_odoo == GEEN_BTW_ODOO_ID else tax_odoo,
                    netto=netto,
                    btw=_cent(regel.btw_bedrag),
                    analytic_account_id=(
                        self._odoo_id("account.analytic.account", regel.project_id) if regel.project_id else None
                    ),
                    product_id=product_id,
                    quantity=quantity,
                    price_unit=price_unit,
                    product_uom_id=uom,
                )
            )
        return regels

    # --- koppeling-rijen ---------------------------------------------------------------------------
    def _koppeling(self, session, document_id: uuid.UUID, boek_cyclus: int, soort: str) -> OdooDocumentKoppeling | None:
        return session.scalars(
            select(OdooDocumentKoppeling).where(
                OdooDocumentKoppeling.administratie_id == self.administratie_id,
                OdooDocumentKoppeling.document_id == document_id,
                OdooDocumentKoppeling.boek_cyclus == boek_cyclus,
                OdooDocumentKoppeling.soort == soort,
            )
        ).one_or_none()

    def _leg_koppeling_vast(
        self,
        *,
        document_id: uuid.UUID,
        boek_cyclus: int,
        soort: str,
        move: dict[str, Any],
        reversal_van: int | None = None,
        detail: dict | None = None,
    ) -> None:
        with scoped_session(self.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
            rij = self._koppeling(session, document_id, boek_cyclus, soort)
            if rij is None:
                rij = OdooDocumentKoppeling(
                    administratie_id=self.administratie_id,
                    document_id=document_id,
                    boek_cyclus=boek_cyclus,
                    soort=soort,
                    odoo_move_id=int(move["id"]),
                    odoo_move_type=str(move.get("move_type") or "in_invoice"),
                    company_id=self.client.company_id,
                    state=str(move.get("state") or "draft"),
                )
                session.add(rij)
            rij.odoo_move_id = int(move["id"])
            rij.odoo_naam = move.get("name") or None
            rij.state = str(move.get("state") or "draft")
            rij.reversal_van_move_id = reversal_van
            if detail:
                rij.detail = {**(rij.detail or {}), **detail}

    def _lees_move(self, move_id: int) -> dict[str, Any] | None:
        return self.client.read_een(MODEL_MOVE, move_id, _MOVE_VELDEN)

    def _bestaande_move(self, document_id: uuid.UUID, boek_cyclus: int, soort: str) -> dict[str, Any] | None:
        """Idempotentie §3.1: eigen koppeling → anders onze marker in invoice_origin."""
        with scoped_session(self.administratie_id) as session:
            rij = self._koppeling(session, document_id, boek_cyclus, soort)
            move_id = rij.odoo_move_id if rij else None
        if move_id is not None:
            move = self._lees_move(move_id)
            if move is not None and move.get("state") != "cancel":
                return move
        move_type = "in_invoice" if soort == "boeking" else "in_refund"
        treffers = self.client.search_read(
            MODEL_MOVE,
            [
                ["company_id", "=", self.client.company_id],
                ["move_type", "=", move_type],
                ["state", "!=", "cancel"],
                ["invoice_origin", "=", marker(document_id, boek_cyclus, soort)],
            ],
            _MOVE_VELDEN,
        )
        if len(treffers) > 1:
            namen = ", ".join(str(t.get("name") or t["id"]) for t in treffers)
            raise BackendBoekFout(
                f"Meerdere Odoo-documenten dragen onze herkenning voor dit document ({namen}) — handmatig beoordelen "
                "in Odoo; niets geboekt"
            )
        return treffers[0] if treffers else None

    # --- poorten -----------------------------------------------------------------------------------
    def _toets_lock_dates(self, boekdatum: date) -> dict[str, date | None]:
        lock_dates = lees_lock_dates(self.client)
        melding = lock_date_melding(boekdatum=boekdatum, lock_dates=lock_dates)
        if melding:
            raise BackendBoekFout(melding)
        return lock_dates

    def _verifieer_company(self, move: dict[str, Any], *, document_id: uuid.UUID) -> None:
        """De heilige poort: staat het document op de company van de administratie? Anders kritiek."""
        company_id = _m2o_id(move.get("company_id"))
        if company_id != self.client.company_id:
            with scoped_session(self.administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
                record_audit_event(
                    session,
                    actor_id=SYSTEEM_ACTOR_ID,
                    module="boekhouding",
                    tabel="odoo_document_koppeling",
                    record_id=document_id,
                    actie="odoo_company_mismatch",
                    correlatie_id=uuid.uuid4(),
                    nieuwe_waarde={
                        "verwacht": self.client.company_id,
                        "gelezen": company_id,
                        "move_id": move.get("id"),
                    },
                    administratie_id=self.administratie_id,
                )
            raise BackendBoekFout(
                f"KRITIEK: Odoo-document {move.get('name') or move.get('id')} staat op company {company_id}, verwacht "
                f"company {self.client.company_id} ({self.verbinding.company_naam or ''}) — direct beoordelen in Odoo"
            )

    # --- bouwen ------------------------------------------------------------------------------------
    def _regel_vals(self, r: _Regel) -> dict[str, Any]:
        vals: dict[str, Any] = {
            "name": r.naam,
            "account_id": r.account_id,
            "quantity": float(r.quantity),
            "price_unit": float(r.price_unit),
            "tax_ids": [[6, 0, [r.tax_id]]] if r.tax_id else [],
        }
        if r.analytic_account_id is not None:
            vals["analytic_distribution"] = {str(r.analytic_account_id): 100}
        if r.product_id is not None:
            vals["product_id"] = r.product_id
            if r.product_uom_id is not None:
                vals["product_uom_id"] = r.product_uom_id
        return vals

    def _move_vals(
        self, *, document_id: uuid.UUID, voorstel: BoekvoorstelData, partner_id: int, regels: list[_Regel]
    ) -> dict:
        if self.verbinding.journal_purchase_id is None:
            raise BackendBoekFout("Odoo-koppeling zonder inkoopdagboek — voer de rechten-probe opnieuw uit")
        assert voorstel.factuurdatum is not None
        vals: dict[str, Any] = {
            "move_type": "in_invoice",
            "company_id": self.client.company_id,
            "journal_id": self.verbinding.journal_purchase_id,
            "partner_id": partner_id,
            "ref": voorstel.referentie,
            "invoice_origin": marker(document_id, voorstel.boek_cyclus),
            "invoice_date": voorstel.factuurdatum.isoformat(),
            # Boekdatum = factuurdatum, EXPLICIET (Odoo-default = maandeinde — STAP-0 §2.2 A3/A4).
            "date": voorstel.factuurdatum.isoformat(),
            "invoice_line_ids": [[0, 0, self._regel_vals(r)] for r in regels],
        }
        if voorstel.betalingskenmerk:
            vals["payment_reference"] = voorstel.betalingskenmerk
        if voorstel.vervaldatum:
            vals["invoice_date_due"] = voorstel.vervaldatum.isoformat()
            vals["invoice_payment_term_id"] = False
        return vals

    # --- btw-override ------------------------------------------------------------------------------
    def _btw_override(self, move_id: int, regels: list[_Regel], verlegd: set[int], *, teken: int = 1) -> list[dict]:
        """Vergelijk per tarief de factuur-btw (Σ regel.btw) met Odoo's tax-regel; ± tolerantie → write
        balance (bewezen A5), daarboven → BackendBoekFout. Verlegde tarieven (+/− regels, netto 0) doen niet
        mee. `teken` = +1 factuur (debet-voorbelasting), −1 creditnota."""
        verwacht: dict[int, Decimal] = {}
        for r in regels:
            if r.tax_id is None or r.tax_id in verlegd:
                continue
            verwacht[r.tax_id] = verwacht.get(r.tax_id, Decimal("0")) + r.btw
        tax_regels = self.client.search_read(
            MODEL_LINE, [["move_id", "=", move_id], ["display_type", "=", "tax"]], ["tax_line_id", "balance", "name"]
        )
        overrides: list[dict] = []
        for tl in tax_regels:
            tax_id = _m2o_id(tl.get("tax_line_id"))
            if tax_id is None or tax_id not in verwacht:
                continue
            odoo_btw = _cent(tl.get("balance")) * teken
            factuur_btw = verwacht[tax_id]
            verschil = factuur_btw - odoo_btw
            if verschil == 0:
                continue
            if abs(verschil) > BTW_OVERRIDE_TOLERANTIE:
                raise BackendBoekFout(
                    f"Btw-verschil € {abs(verschil)} op tarief {tl.get('name')}: factuur € {factuur_btw}, Odoo "
                    f"berekent "
                    f"€ {odoo_btw} — groter dan de toegestane € {BTW_OVERRIDE_TOLERANTIE}; controleer de regels"
                )
            self.client.write(MODEL_LINE, [int(tl["id"])], {"balance": float(factuur_btw * teken)})
            overrides.append(
                {
                    "tarief": tl.get("name"),
                    "odoo_btw": str(odoo_btw),
                    "factuur_btw": str(factuur_btw),
                    "verschil": str(verschil),
                }
            )
        return overrides

    def _annuleer_concept(self, move_id: int, reden: str) -> None:
        """Een concept dat wij niet kunnen posten blijft niet als ruis staan: `button_cancel` (state cancel —
        Odoo's eigen annulering, geen unlink). De volgende poging maakt een nieuw concept."""
        try:
            self.client.call(MODEL_MOVE, "button_cancel", ids=[move_id])
            logger.warning("Odoo-concept %s geannuleerd: %s", move_id, reden)
        except OdooFout as exc:  # noqa: BLE001 — het concept blijft dan zichtbaar staan; de fout is al leidend
            logger.warning("Odoo-concept %s kon niet geannuleerd worden: %s", move_id, exc)

    # --- bijlage -----------------------------------------------------------------------------------
    def _zorg_voor_bijlage(self, move_id: int, bestand: bytes, bestandsnaam: str) -> str:
        checksum = hashlib.sha1(bestand).hexdigest()  # noqa: S324 — Odoo's eigen ir.attachment.checksum
        bestaand = self.client.search_read(
            MODEL_ATTACHMENT,
            [["res_model", "=", MODEL_MOVE], ["res_id", "=", move_id], ["checksum", "=", checksum]],
            ["id"],
        )
        if bestaand:
            att_id = int(bestaand[0]["id"])
        else:
            att_id = self.client.create(
                MODEL_ATTACHMENT,
                {
                    "name": bestandsnaam,
                    "res_model": MODEL_MOVE,
                    "res_id": move_id,
                    "datas": base64.b64encode(bestand).decode(),
                    "mimetype": "application/pdf"
                    if bestandsnaam.lower().endswith(".pdf")
                    else "application/octet-stream",
                },
            )
        self.client.call(MODEL_ATTACHMENT, "register_as_main_attachment", ids=[att_id], force=True)
        return f"aanwezig ({att_id})"

    # --- de operaties ------------------------------------------------------------------------------
    def boek_inkoopfactuur(
        self, *, document_id: uuid.UUID, voorstel: BoekvoorstelData, bestand: bytes, bestandsnaam: str
    ) -> BoekUitkomst:
        assert voorstel.vendor_id is not None and voorstel.factuurdatum is not None  # harde checks
        try:
            partner_id = self.partner_id_voor(voorstel.vendor_id)
            regels = self._vertaal_regels(document_id, voorstel)
            verlegd_ids = {self._odoo_id("account.tax", t) for t in self._verlegde_taxrates()}
        except odoo_sync.OnbekendeOdooId as exc:
            raise BackendBoekFout(str(exc)) from exc

        detail: dict[str, Any] = {"backend": Backend.ODOO.value, "odoo_company_id": self.client.company_id}
        try:
            move = self._bestaande_move(document_id, voorstel.boek_cyclus, "boeking")
            if move is None:
                self._toets_lock_dates(voorstel.factuurdatum)
                vals = self._move_vals(document_id=document_id, voorstel=voorstel, partner_id=partner_id, regels=regels)
                move_id = self.client.create(MODEL_MOVE, vals)
                move = self._lees_move(move_id)
                if move is None:
                    raise BackendBoekFout(f"Odoo gaf id {move_id} terug maar het document is niet terug te lezen")
                self._leg_koppeling_vast(
                    document_id=document_id, boek_cyclus=voorstel.boek_cyclus, soort="boeking", move=move
                )
                detail["odoo_aangemaakt"] = True
            else:
                detail["odoo_hergebruikt"] = True
            move_id = int(move["id"])
            self._verifieer_company(move, document_id=document_id)

            if move.get("state") == "draft":
                overrides = self._btw_override(move_id, regels, verlegd_ids)
                if overrides:
                    detail["btw_override"] = overrides
                    move = self._lees_move(move_id) or move
                totaal = _cent(voorstel.totaalbedrag)
                if voorstel.totaalbedrag is not None and _cent(move.get("amount_total")) != totaal:
                    reden = (
                        f"Odoo-totaal € {_cent(move.get('amount_total'))} ≠ factuurtotaal € {totaal} — concept "
                        "geannuleerd, niets geboekt; controleer regels en btw"
                    )
                    self._annuleer_concept(move_id, reden)
                    self._leg_koppeling_vast(
                        document_id=document_id,
                        boek_cyclus=voorstel.boek_cyclus,
                        soort="boeking",
                        move={**move, "state": "cancel"},
                        detail={"geannuleerd_reden": reden},
                    )
                    raise BackendBoekFout(reden)
                self.client.call(MODEL_MOVE, "action_post", ids=[move_id])
                move = self._lees_move(move_id) or move

            # Post-write-verificatie (company-poort + stand).
            self._verifieer_company(move, document_id=document_id)
            if move.get("state") != "posted":
                raise BackendBoekFout(
                    f"Odoo-document {move_id} staat ná action_post op {move.get('state')!r}, niet posted"
                )
            if voorstel.totaalbedrag is not None and _cent(move.get("amount_total")) != _cent(voorstel.totaalbedrag):
                raise BackendBoekFout(
                    f"KRITIEK: geboekt Odoo-document {move.get('name')} heeft totaal "
                    f"€ {_cent(move.get('amount_total'))}, "
                    f"factuur € {_cent(voorstel.totaalbedrag)} — beoordeel in Odoo"
                )
            self._leg_koppeling_vast(
                document_id=document_id, boek_cyclus=voorstel.boek_cyclus, soort="boeking", move=move
            )
        except BackendBoekFout:
            raise
        except OdooFout as exc:
            raise BackendBoekFout(vertaal_odoo_fout(exc)) from exc

        try:
            detail["bijlage"] = self._zorg_voor_bijlage(move_id, bestand, bestandsnaam)
        except Exception as exc:  # noqa: BLE001 — de boeking stáát; de bijlage-fout is een zichtbare waarschuwing
            logger.exception("Bijlage op Odoo-document %s mislukt", move_id)
            detail["bijlage"] = f"MISLUKT: {vertaal_odoo_fout(exc)}"
            detail["waarschuwing"] = "bijlage niet gekoppeld in Odoo — later opnieuw koppelen"

        detail.update(
            {
                "odoo_move_id": move_id,
                "odoo_naam": move.get("name"),
                "odoo_boekdatum": move.get("date"),
                "regels_met_product": sum(1 for r in regels if r.product_id is not None),
                "regels": len(regels),
            }
        )
        return BoekUitkomst(
            extern_document_id=odoo_uuid(self.client.company_id, MODEL_MOVE, move_id),
            boekstuknummer=move.get("name") or None,
            detail=detail,
        )

    def origineel_stand(self, *, document_id: uuid.UUID, boek_cyclus: int) -> OrigineelStand:
        """Odoo-norm (besluit Peter 02-09): correctie = reversal — storno-op-hetzelfde-document bestaat niet
        in de capability-set, dus `kant.toegestaan` is altijd False mét de Odoo-reden (het tegenboek-pad ís de
        route). `nog_geboekt` = posted én niet al teruggedraaid."""
        with scoped_session(self.administratie_id) as session:
            rij = self._koppeling(session, document_id, boek_cyclus, "boeking")
            move_id = rij.odoo_move_id if rij else None
        kant = KantToets(
            kant="inkoopfactuur",
            toegestaan=False,
            reden="Odoo kent geen storno op hetzelfde document — corrigeren = creditnota (reversal) mét "
            "kruisverwijzing",
        )
        move = self._lees_move(move_id) if move_id is not None else None
        if move is None:
            return OrigineelStand(
                kant=kant, nog_geboekt=False, betaald_bedrag=None, open_bedrag=None, volledig_afgeletterd=False
            )
        totaal = _cent(move.get("amount_total"))
        residu = _cent(move.get("amount_residual"))
        return OrigineelStand(
            kant=kant,
            nog_geboekt=move.get("state") == "posted" and move.get("payment_state") != "reversed",
            betaald_bedrag=totaal - residu,
            open_bedrag=residu,
            volledig_afgeletterd=move.get("payment_state") in ("paid", "reversed", "in_payment"),
        )

    def boek_tegenboeking(
        self,
        *,
        document_id: uuid.UUID,
        voorstel: BoekvoorstelData,
        referentie: str,
        omschrijving: str,
        reden: str,
        bestand: bytes,
        bestandsnaam: str,
    ) -> TegenboekUitkomst:
        with scoped_session(self.administratie_id) as session:
            orig = self._koppeling(session, document_id, voorstel.boek_cyclus, "boeking")
            orig_move_id = orig.odoo_move_id if orig else None
        if orig_move_id is None:
            raise BackendBoekFout("Geen Odoo-boeking bekend voor dit document — tegenboeken kan niet")
        detail: dict[str, Any] = {"backend": Backend.ODOO.value, "odoo_company_id": self.client.company_id}
        try:
            regels = self._vertaal_regels(document_id, voorstel)
            verlegd_ids = {self._odoo_id("account.tax", t) for t in self._verlegde_taxrates()}
            refund = self._bestaande_move(document_id, voorstel.boek_cyclus, "tegenboeking")
            if refund is None:
                vandaag = date.today()
                self._toets_lock_dates(vandaag)
                wizard_id = self.client.create(
                    MODEL_REVERSAL,
                    {
                        "move_ids": [[6, 0, [orig_move_id]]],
                        "reason": reden,
                        "journal_id": self.verbinding.journal_purchase_id,
                        "date": vandaag.isoformat(),
                        "company_id": self.client.company_id,
                    },
                )
                actie = self.client.call(MODEL_REVERSAL, "reverse_moves", ids=[wizard_id]) or {}
                refund_id = actie.get("res_id") if isinstance(actie, dict) else None
                if not refund_id:
                    # Terugvallen op de kruisverwijzing van het origineel (reversal_move_ids).
                    orig_move = self._lees_move(orig_move_id) or {}
                    kandidaten = [int(i) for i in (orig_move.get("reversal_move_ids") or [])]
                    refund_id = kandidaten[-1] if kandidaten else None
                if not refund_id:
                    raise BackendBoekFout("Odoo's reversal gaf geen creditnota-id terug — beoordeel in Odoo")
                self.client.write(
                    MODEL_MOVE,
                    [int(refund_id)],
                    {"invoice_origin": marker(document_id, voorstel.boek_cyclus, "tegenboeking"), "ref": referentie},
                )
                refund = self._lees_move(int(refund_id))
                assert refund is not None
                self._leg_koppeling_vast(
                    document_id=document_id,
                    boek_cyclus=voorstel.boek_cyclus,
                    soort="tegenboeking",
                    move=refund,
                    reversal_van=orig_move_id,
                )
            refund_id = int(refund["id"])
            self._verifieer_company(refund, document_id=document_id)
            if refund.get("state") == "draft":
                # De wizard herberekent de btw uit de regels en neemt een cent-override NIET mee (§3.3) —
                # spiegel de factuur-btw (negatief) vóór het posten.
                overrides = self._btw_override(refund_id, regels, verlegd_ids, teken=-1)
                if overrides:
                    detail["btw_override"] = overrides
                self.client.call(MODEL_MOVE, "action_post", ids=[refund_id])
                refund = self._lees_move(refund_id) or refund
            self._verifieer_company(refund, document_id=document_id)
            if refund.get("state") != "posted":
                raise BackendBoekFout(f"Creditnota {refund_id} staat ná action_post op {refund.get('state')!r}")
            self._leg_koppeling_vast(
                document_id=document_id,
                boek_cyclus=voorstel.boek_cyclus,
                soort="tegenboeking",
                move=refund,
                reversal_van=orig_move_id,
            )
            orig_move = self._lees_move(orig_move_id) or {}
            detail["origineel_payment_state"] = orig_move.get("payment_state")
            detail["origineel_restant"] = str(_cent(orig_move.get("amount_residual")))
            if _cent(orig_move.get("amount_residual")) != 0:
                detail["waarschuwing"] = (
                    f"origineel {orig_move.get('name')} houdt € {_cent(orig_move.get('amount_residual'))} open ná de "
                    "creditnota — afletteren in Odoo controleren"
                )
        except BackendBoekFout:
            raise
        except OdooFout as exc:
            raise BackendBoekFout(vertaal_odoo_fout(exc)) from exc
        except odoo_sync.OnbekendeOdooId as exc:
            raise BackendBoekFout(str(exc)) from exc

        try:
            detail["bijlage"] = self._zorg_voor_bijlage(refund_id, bestand, bestandsnaam)
        except Exception as exc:  # noqa: BLE001
            detail["bijlage"] = f"MISLUKT: {vertaal_odoo_fout(exc)}"
        detail.update(
            {"odoo_move_id": refund_id, "odoo_naam": refund.get("name"), "odoo_origineel_move_id": orig_move_id}
        )
        return TegenboekUitkomst(
            extern_document_id=odoo_uuid(self.client.company_id, MODEL_MOVE, refund_id),
            boekstuknummer=refund.get("name") or None,
            detail=detail,
        )
