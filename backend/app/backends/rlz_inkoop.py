"""RLZ-adapter voor de inkoop-port — de bestaande, live-bewezen schrijfvolgorde uit boeken.py /
tegenboeken.py, ongewijzigd verplaatst achter de port (PUT + /Uploads + actie 17; tegenboeking =
NIEUWE PurchaseInvoice met gespiegelde negatieve regels, boekdatum vandaag)."""

from __future__ import annotations

import base64
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.backends.port import Backend, BackendBoekFout, BoekUitkomst, OrigineelStand, TegenboekUitkomst
from app.documenten.boekvoorstel import BoekvoorstelData
from app.documenten.rlz_ids import (
    rlz_herboeking_id,
    rlz_herboeking_upload_id,
    rlz_tegenboeking_id,
    rlz_tegenboeking_upload_id,
)
from app.projectverdeling.data import gewichten_per_project, splits_regel
from app.rlz.aangifte import AangiftePoort
from app.rlz.bijlage import zorg_voor_bijlage
from app.rlz.client import RlzApiError, RlzClient
from app.rlz.fouten import vertaal_rlz_boekfout

# RLZ: geboekt = Status 2 óf 3 (CLAUDE.md — nooit alleen op 2 toetsen).
_RLZ_GEBOEKT = frozenset({2, 3})


def _projectgewichten(voorstel: BoekvoorstelData) -> list[tuple[uuid.UUID, Decimal]]:
    """Projectverdeling (blok C 04-09, ⑤): de totale verdeling per project (vast + pro rato) als gewichten voor de
    regelsplitsing — alleen bij een actieve, complete verdeling; anders leeg (= geen splitsing)."""
    verdeling = voorstel.projectverdeling
    if verdeling is None or not verdeling.dekt_regels_zonder_project:
        return []
    return gewichten_per_project(verdeling.delen)


def regels_naar_rlz_lines(voorstel: BoekvoorstelData) -> list[dict]:
    gewichten = _projectgewichten(voorstel)
    lines: list[dict] = []
    for regel in voorstel.regels:
        # btw_bedrag mag None zijn (verlegd/vrijgesteld); netto_bedrag is door de harde checks afgedwongen.
        basis: dict = {
            "Account": {"id": str(regel.ledger_id)},
            "TaxRate": {"id": str(regel.taxrate_id)},
        }
        if regel.omschrijving:
            basis["Description"] = regel.omschrijving
        if regel.project_id is None and gewichten:
            # Regel zonder eigen project → N regels mét Project, netto én btw per deel via grootste-rest (sluitend).
            for deel in splits_regel(regel.netto_bedrag, regel.btw_bedrag, gewichten):
                lines.append(
                    {**basis, "NetAmount": float(deel.netto), "TaxAmount": float(deel.btw), "Project": {"id": str(deel.project_id)}}
                )
            continue
        line: dict = {**basis, "NetAmount": float(regel.netto_bedrag), "TaxAmount": float(regel.btw_bedrag or 0)}
        if regel.project_id is not None:
            line["Project"] = {"id": str(regel.project_id)}
        lines.append(line)
    return lines


def tegenboek_lines(voorstel: BoekvoorstelData, omschrijving: str) -> list[dict]:
    """Gespiegelde regels (STAP-0-vorm): zelfde Account/TaxRate/Project, negatieve bedragen. Een bevroren
    projectverdeling wordt exact gespiegeld (dezelfde splitsing per project als de boeking)."""
    gewichten = _projectgewichten(voorstel)
    lines: list[dict] = []
    for regel in voorstel.regels:
        basis: dict = {
            "Account": {"id": str(regel.ledger_id)},
            "TaxRate": {"id": str(regel.taxrate_id)},
            "Description": omschrijving,
        }
        if regel.project_id is None and gewichten:
            for deel in splits_regel(regel.netto_bedrag or Decimal("0"), regel.btw_bedrag, gewichten):
                lines.append(
                    {**basis, "NetAmount": float(-deel.netto), "TaxAmount": float(-deel.btw), "Project": {"id": str(deel.project_id)}}
                )
            continue
        line: dict = {
            **basis,
            "NetAmount": float(-(regel.netto_bedrag or Decimal("0"))),
            "TaxAmount": float(-(regel.btw_bedrag or Decimal("0"))),
        }
        if regel.project_id is not None:
            line["Project"] = {"id": str(regel.project_id)}
        lines.append(line)
    return lines


def _als_decimal(waarde: object) -> Decimal | None:
    if waarde is None:
        return None
    try:
        return Decimal(str(waarde))
    except Exception:  # noqa: BLE001
        return None


class RlzInkoopPort:
    backend = Backend.RLZ

    def __init__(self, client: RlzClient) -> None:
        self.client = client

    def __enter__(self) -> RlzInkoopPort:
        return self

    def __exit__(self, *exc_info: object) -> None:
        self.client.close()

    def leesclient(self) -> Any:
        return self.client

    def boek_inkoopfactuur(
        self, *, document_id: uuid.UUID, voorstel: BoekvoorstelData, bestand: bytes, bestandsnaam: str
    ) -> BoekUitkomst:
        """PUT + /Uploads + actie 17, in die volgorde (RLZ berekent zelf totalen). Het GUID volgt de
        boek_cyclus (tegenboek-pad): een herboeking is een NIEUW RLZ-document."""
        rlz_document_id = rlz_herboeking_id(document_id, voorstel.boek_cyclus)
        assert voorstel.vendor_id is not None and voorstel.factuurdatum is not None  # harde checks
        try:
            self.client.put_purchase_invoice(
                rlz_document_id,
                vendor_id=voorstel.vendor_id,
                lines=regels_naar_rlz_lines(voorstel),
                reference=voorstel.referentie,
                # Volledige ISO-datetime (geverifieerde vorm, api-verkenning "Boekstuknummer, factuurdatum en
                # /Uploads").
                Date=f"{voorstel.factuurdatum.isoformat()}T00:00:00",
                # Boekingsdatum = factuurdatum (besluit Peter 27-08; STAP 0 28-08 "Boekingsdatum = BookDate").
                BookDate=f"{voorstel.factuurdatum.isoformat()}T00:00:00",
                # Vervaldatum (C1 26-08): live bewezen; zonder DueDate leidt RLZ 'm zelf af.
                **({"DueDate": f"{voorstel.vervaldatum.isoformat()}T00:00:00"} if voorstel.vervaldatum else {}),
            )
            zorg_voor_bijlage(
                self.client,
                "PurchaseInvoices",
                rlz_document_id,
                upload_id=rlz_herboeking_upload_id(document_id, voorstel.boek_cyclus),
                filename=bestandsnaam,
                content_base64=base64.b64encode(bestand).decode(),
            )
            self.client.book_purchase_invoice(rlz_document_id)
            geboekt = self.client.get(f"PurchaseInvoices/{rlz_document_id}")
        except RlzApiError as exc:
            raise BackendBoekFout(vertaal_rlz_boekfout(exc)) from exc
        return BoekUitkomst(
            extern_document_id=rlz_document_id,
            boekstuknummer=geboekt.get("ReceiptNumber"),
            detail={"backend": Backend.RLZ.value},
        )

    def origineel_stand(self, *, document_id: uuid.UUID, boek_cyclus: int) -> OrigineelStand:
        """Eén GET op het origineel: de aangifte-poort-toets én de betaalstatus uit dezelfde response."""
        rlz_document_id = rlz_herboeking_id(document_id, boek_cyclus)
        origineel: dict | None = None

        def ophalen() -> dict:
            nonlocal origineel
            origineel = self.client.get(f"PurchaseInvoices/{rlz_document_id}")
            return origineel

        kant = AangiftePoort(self.client).toets_document(ophalen, kant="inkoopfactuur")
        if origineel is None:
            return OrigineelStand(
                kant=kant, nog_geboekt=False, betaald_bedrag=None, open_bedrag=None, volledig_afgeletterd=False
            )
        return OrigineelStand(
            kant=kant,
            nog_geboekt=origineel.get("Status") in _RLZ_GEBOEKT,
            betaald_bedrag=_als_decimal(origineel.get("BasePaidAmount")),
            open_bedrag=_als_decimal(origineel.get("BaseRemainingAmount")),
            volledig_afgeletterd=origineel.get("Status") == 3,
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
        """Idempotent: bestaat de tegenboeking al geboekt (retry na een halve mislukking), geen tweede
        boekpoging — alleen het boekstuknummer teruggeven."""
        tegenboeking_id = rlz_tegenboeking_id(document_id, voorstel.boek_cyclus)
        assert voorstel.vendor_id is not None
        try:
            try:
                bestaand = self.client.get(f"PurchaseInvoices/{tegenboeking_id}")
            except RlzApiError as exc:
                if exc.status_code != 404:
                    raise
                bestaand = None
            if bestaand is not None and bestaand.get("Status") in _RLZ_GEBOEKT:
                boekstuknummer = bestaand.get("ReceiptNumber")
            else:
                self.client.put_purchase_invoice(
                    tegenboeking_id,
                    vendor_id=voorstel.vendor_id,
                    lines=tegenboek_lines(voorstel, omschrijving),
                    reference=referentie,
                    Date=f"{date.today().isoformat()}T00:00:00",
                )
                zorg_voor_bijlage(
                    self.client,
                    "PurchaseInvoices",
                    tegenboeking_id,
                    upload_id=rlz_tegenboeking_upload_id(document_id, voorstel.boek_cyclus),
                    filename=bestandsnaam,
                    content_base64=base64.b64encode(bestand).decode(),
                )
                self.client.book_purchase_invoice(tegenboeking_id)
                geboekt = self.client.get(f"PurchaseInvoices/{tegenboeking_id}")
                boekstuknummer = geboekt.get("ReceiptNumber")
        except RlzApiError as exc:
            raise BackendBoekFout(str(exc)) from exc
        return TegenboekUitkomst(
            extern_document_id=tegenboeking_id, boekstuknummer=boekstuknummer, detail={"backend": Backend.RLZ.value}
        )
