"""Naamverrijking van reconciliatie-details voor bank, omzet en doorbelasting (fixrun 07-09 blok A8).

De CLI-blokfuncties (`app/cli.py::_bank_reconciliatie` e.a.) leggen per afwijking een `detail`-dict vast
met technische sleutels (record_id, payment_transaction_id, document_id). Voor leesbare teksten
(`app/reconciliatie/teksten.py`) hebben we NAMEN nodig: tegenpartij, rekening, periode, doelentiteit,
leverancier, factuurnummer, bedragen. Die worden hier ADDITIEF uit onze eigen caches/tabellen gelezen
(geen RLZ-calls, geen AI) en aan het detail toegevoegd. Bedragen als string (JSONB-veilig), datums ISO.

Faalt nooit: elke lookup zit in een try/except en levert hooguit een leeg dict — een reconciliatie-run
mag niet omvallen op een naamlookup. De documenten-verrijking is van agent A (`app/documenten/
reconciliatie.py`) en staat bewust NIET hier."""

from __future__ import annotations

import logging
import uuid
from decimal import Decimal
from typing import Any

from sqlalchemy import select

from app.db.models import Administratie
from app.db.session import scoped_session

logger = logging.getLogger(__name__)


def _str(v: Any) -> str | None:
    if v is None or v == "":
        return None
    if isinstance(v, Decimal):
        return str(v.quantize(Decimal("0.01")))
    return str(v)


def _schoon(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in (None, "")}


def administratie_naam(administratie_id: uuid.UUID | None) -> str | None:
    if administratie_id is None:
        return None
    try:
        with scoped_session(None) as session:
            return session.scalar(select(Administratie.naam).where(Administratie.id == administratie_id))
    except Exception:  # noqa: BLE001
        logger.exception("administratienaam ophalen mislukt")
        return None


def _document_namen(session, document_id: uuid.UUID | None) -> dict[str, Any]:
    """leverancier_naam / factuurnummer / bedrag / factuurdatum van het bron-document (Boekvoorstel + VendorCache)."""
    if document_id is None:
        return {}
    from app.documenten.models import Boekvoorstel, Document
    from app.sync.models import VendorCache

    rij = session.execute(
        select(
            Boekvoorstel.referentie,
            Boekvoorstel.totaalbedrag,
            Boekvoorstel.factuurdatum,
            Boekvoorstel.rlz_boekstuknummer,
            Boekvoorstel.vendor_id,
            Document.administratie_id,
            Document.bestandsnaam,
        )
        .join(Document, Document.id == Boekvoorstel.document_id)
        .where(Boekvoorstel.document_id == document_id)
    ).first()
    if rij is None:
        return {}
    leverancier = None
    if rij.vendor_id is not None and rij.administratie_id is not None:
        leverancier = session.scalar(
            select(VendorCache.naam).where(
                VendorCache.id == rij.vendor_id, VendorCache.administratie_id == rij.administratie_id
            )
        )
    return _schoon(
        {
            "leverancier_naam": leverancier,
            "factuurnummer": rij.referentie,
            "document_bedrag": _str(rij.totaalbedrag),
            "factuurdatum": _str(rij.factuurdatum),
            "document_boekstuk": rij.rlz_boekstuknummer,
            "bestandsnaam": rij.bestandsnaam,
        }
    )


def bank(*, administratie_id: uuid.UUID, record_id: uuid.UUID, payment_transaction_id: uuid.UUID) -> dict[str, Any]:
    """Tegenpartij, IBAN, bedrag, datum en omschrijving van de mutatie; rekeningnaam/IBAN; bij een
    aflettering de referentie/relatie van de openstaande post; bij een boeking omschrijving + boekstuk."""
    try:
        from app.bank.models import (
            BankAfletterOpdracht,
            BankBoeking,
            BankMutatie,
            PaymentAccountCache,
            PaymentItemCache,
        )

        with scoped_session(administratie_id) as session:
            uit: dict[str, Any] = {"administratie_naam": administratie_naam(administratie_id)}
            mutatie = session.get(BankMutatie, payment_transaction_id)
            if mutatie is not None:
                uit.update(
                    {
                        "mutatie_datum": _str(mutatie.boekdatum),
                        "mutatie_bedrag": _str(mutatie.bedrag),
                        "tegenpartij_naam": mutatie.tegenpartij_naam,
                        "tegenrekening_iban": mutatie.tegenrekening_iban,
                        "omschrijving": mutatie.omschrijving,
                    }
                )
                if mutatie.payment_account_id is not None:
                    rekening = session.get(PaymentAccountCache, mutatie.payment_account_id)
                    if rekening is not None:
                        uit.update({"rekening_naam": rekening.naam, "rekening_iban": rekening.iban})
            boeking = session.get(BankBoeking, record_id)
            if boeking is not None:
                uit.update(
                    {
                        "controle": "boeking",
                        "omschrijving": boeking.omschrijving or uit.get("omschrijving"),
                        "rlz_boekstuk": boeking.rlz_boekstuknummer,
                        "rlz_document_id": _str(boeking.rlz_document_id),
                    }
                )
            else:
                opdracht = session.get(BankAfletterOpdracht, record_id)
                if opdracht is not None:
                    uit["controle"] = "aflettering"
                    if opdracht.payment_item_id is not None:
                        post = session.get(PaymentItemCache, opdracht.payment_item_id)
                        if post is not None:
                            uit.update(
                                {
                                    "referentie": post.referentie,
                                    "relatie_naam": post.entity_naam,
                                    "bedrag_lokaal": _str(post.bedrag),
                                    "payment_item_id": _str(post.id),
                                }
                            )
            return _schoon(uit)
    except Exception:  # noqa: BLE001 — verrijking mag de run nooit laten omvallen
        logger.exception("bank-verrijking mislukt voor record %s", record_id)
        return {}


def omzet(*, administratie_id: uuid.UUID, boeking_id: uuid.UUID) -> dict[str, Any]:
    """Periode, totalen en boekstuknummers van de omzetboeking."""
    try:
        from app.omzet.models import OmzetBoeking

        with scoped_session(administratie_id) as session:
            b = session.get(OmzetBoeking, boeking_id)
            uit: dict[str, Any] = {"administratie_naam": administratie_naam(administratie_id)}
            if b is not None:
                uit.update(
                    {
                        "periode_start": _str(b.periode_start),
                        "periode_eind": _str(b.periode_eind),
                        "totaal_omzet": _str(b.totaal_omzet),
                        "totaal_kostprijs": _str(b.totaal_kostprijs),
                        "rlz_boekstuk": b.verkoop_boekstuknummer,
                        "verkoop_referentie": b.verkoop_referentie,
                        "memoriaal_boekstuk": b.memoriaal_boekstuknummer,
                        "verkoop_rlz_id": _str(b.verkoop_rlz_id),
                        "memoriaal_rlz_id": _str(b.memoriaal_rlz_id),
                    }
                )
            return _schoon(uit)
    except Exception:  # noqa: BLE001
        logger.exception("omzet-verrijking mislukt voor boeking %s", boeking_id)
        return {}


def doorbelasting(*, administratie_id: uuid.UUID, boeking_id: uuid.UUID) -> dict[str, Any]:
    """Doelentiteit, doel-administratie, referentie, bedrag en het bron-document (leverancier/factuurnummer)."""
    try:
        from app.doorbelasting.models import DoorbelastingBoeking, DoorbelastingMapping

        with scoped_session(administratie_id) as session:
            b = session.get(DoorbelastingBoeking, boeking_id)
            uit: dict[str, Any] = {"administratie_naam": administratie_naam(administratie_id)}
            if b is None:
                return _schoon(uit)
            mapping = session.get(DoorbelastingMapping, b.mapping_id)
            uit.update(
                {
                    "doelentiteit_naam": mapping.doelentiteit_naam if mapping else None,
                    "doel_administratie_naam": administratie_naam(b.doel_administratie_id),
                    "verkoop_referentie": b.verkoop_referentie,
                    "bedrag_lokaal": _str(b.netto_totaal + b.provisie_bedrag + b.btw_bedrag),
                    "verkoop_rlz_id": _str(b.verkoop_rlz_id),
                    "spiegel_rlz_id": _str(b.spiegel_rlz_id),
                    "status_lokaal": b.status,
                }
            )
            uit.update(_document_namen(session, b.document_id))
            return _schoon(uit)
    except Exception:  # noqa: BLE001
        logger.exception("doorbelasting-verrijking mislukt voor boeking %s", boeking_id)
        return {}


def opruim_kandidaat(
    *, administratie_id: uuid.UUID, concept_administratie_id: uuid.UUID, document_id: uuid.UUID
) -> dict[str, Any]:
    """Naam van de administratie waar het concept staat + bron-document (leverancier/factuurnummer)."""
    try:
        uit: dict[str, Any] = {
            "administratie_naam": administratie_naam(administratie_id),
            "concept_administratie_naam": administratie_naam(concept_administratie_id),
        }
        with scoped_session(administratie_id) as session:
            uit.update(_document_namen(session, document_id))
        return _schoon(uit)
    except Exception:  # noqa: BLE001
        logger.exception("opruim-verrijking mislukt voor document %s", document_id)
        return {}


def administratie(administratie_id: uuid.UUID, *, fout: str | None = None, uitsluiting: str | None = None) -> dict:
    """Detail voor een fout-/uitgesloten-regel op administratieniveau (was tot 07-09 `None`)."""
    return _schoon(
        {"administratie_naam": administratie_naam(administratie_id), "fout": fout, "uitsluiting": uitsluiting}
    )
