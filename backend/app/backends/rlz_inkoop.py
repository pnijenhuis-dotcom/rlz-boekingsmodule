"""RLZ-adapter voor de inkoop-port — de bestaande, live-bewezen schrijfvolgorde uit boeken.py /
tegenboeken.py, ongewijzigd verplaatst achter de port (PUT + /Uploads + actie 17; tegenboeking =
NIEUWE PurchaseInvoice met gespiegelde negatieve regels, boekdatum vandaag)."""

from __future__ import annotations

import base64
import uuid
from datetime import date
from decimal import Decimal
from typing import Any

from app.backends.port import (
    Backend,
    BackendBoekFout,
    BoekUitkomst,
    OrigineelStand,
    TegenboekUitkomst,
    ToetsMislukt,
    ToetsUitkomst,
)
from app.documenten.boekvoorstel import BoekvoorstelData
from app.documenten.rlz_ids import (
    rlz_herboeking_id,
    rlz_herboeking_upload_id,
    rlz_tegenboeking_id,
    rlz_tegenboeking_upload_id,
)
from app.projectverdeling.data import gewichten_per_project, splits_regel
from app.rlz.aangifte import AangiftePoort, KantToets
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


# RLZ kapt tekstvelden op PurchaseInvoices (document-Description, regel-Description én — aangenomen — Header) af
# op 200 tekens (STAP-0 07-09: een regel-Description van 250 tekens kwam als 200 terug). Zelf afkappen zodat de
# kop nooit stil halverwege een woord door RLZ wordt geknipt en `kop_omschrijving.MAX_LENGTE` (255) niet als
# schijnzekerheid dient.
RLZ_KOPTEKST_MAX = 200


def koptekst_velden(tekst: str | None) -> dict[str, str]:
    """`Header` + `Description` voor de PurchaseInvoice-PUT, of leeg als er geen kop-omschrijving is."""
    if not tekst:
        return {}
    kop = tekst if len(tekst) <= RLZ_KOPTEKST_MAX else tekst[: RLZ_KOPTEKST_MAX - 1].rstrip() + "…"
    return {"Header": kop, "Description": kop}


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


def is_bruikbaar_rlz_document(antwoord: object) -> bool:
    """Defensieve poort (A11, 07-09): een `GET PurchaseInvoices/{id}` die 200 geeft maar géén document draagt
    (geen dict, leeg object, geen `Status`-veld) telt als 'ontbreekt' — nooit stil als 'klopt' doorlaten. Een
    échte RLZ-PurchaseInvoice draagt altijd `Status` (live geverifieerd 07-09 op Kempen Facilities: 200 mét
    id/Status/Type/ReceiptNumber…; een onbekend GUID = 404 `NotFound_PurchaseInvoice`)."""
    return isinstance(antwoord, dict) and "Status" in antwoord


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
                # Kop-omschrijving (blok 9 vervolgrun 07-09, auto-first) → `Header` + `Description`. STAP-0 07-09
                # (api-verkenning "Description op PurchaseInvoices — STAP 0 07-09"): RLZ NEGEERT de document-
                # `Description` op PurchaseInvoices (net als op SalesInvoices) en leidt 'm af uit regel 1;
                # `Header` wordt WÉL bewaard en komt terug in de GET. Beide gaan mee (Description = harmloos,
                # Header = het veld dat blijft), afgekapt op RLZ's 200 tekens.
                **koptekst_velden(voorstel.omschrijving),
            )
            zorg_voor_bijlage(
                self.client,
                "PurchaseInvoices",
                rlz_document_id,
                upload_id=rlz_herboeking_upload_id(document_id, voorstel.boek_cyclus),
                filename=bestandsnaam,
                content_base64=base64.b64encode(bestand).decode(),
            )
            # Betaalstatus (blok 3 bundel 08-09; STAP-0 08-09 "Betaalstatus inkoopfactuur"): RLZ's "Betaling"-veld =
            # `QuickPaymentSelection`, kaal zetbaar vóór het boeken — de post blijft open maar staat niet in de
            # betaallijst (declaratie al betaald / incasso door de bank). Keuze op label uit de per-document-lijst.
            betaalstatus_detail = self._zet_betaalstatus(rlz_document_id, voorstel)
            self.client.book_purchase_invoice(rlz_document_id)
            geboekt = self.client.get(f"PurchaseInvoices/{rlz_document_id}")
        except RlzApiError as exc:
            raise BackendBoekFout(vertaal_rlz_boekfout(exc)) from exc
        return BoekUitkomst(
            extern_document_id=rlz_document_id,
            boekstuknummer=geboekt.get("ReceiptNumber"),
            detail={"backend": Backend.RLZ.value, **betaalstatus_detail},
        )

    def _zet_betaalstatus(self, rlz_document_id: uuid.UUID, voorstel: BoekvoorstelData) -> dict:
        """Zet `QuickPaymentSelection` als het voorstel een betaalstatus draagt (anders niets — RLZ-default "Nog te
        betalen" = geen PUT). Label niet in RLZ's lijst = BackendBoekFout (zichtbaar `boek_fout`, retry) — nooit stil
        boeken zonder status: op een declaratie zou dat een dubbele betaling uitlokken."""
        from app.documenten import betaalstatus as bs  # lokaal: houdt de importgraaf backends → documenten klein

        status = bs.canoniek(voorstel.betaalstatus)
        if status is None or status == bs.NOG_TE_BETALEN:
            return {}
        keuzes = self.client.list_quick_payment_selections(rlz_document_id)
        keuze_id = bs.kies_keuze_id(keuzes, status)
        if keuze_id is None:
            raise BackendBoekFout(
                f"Betaalstatus {status!r} staat niet in de keuzelijst van Reeleezee voor dit document "
                f"({', '.join(str(k.get('Description')) for k in keuzes) or 'lege lijst'}) — "
                "kies een andere betaalstatus of controleer de administratie in Reeleezee"
            )
        self.client.set_quick_payment_selection(rlz_document_id, keuze_id)
        return {"betaalstatus": status, "betaalstatus_herkomst": voorstel.betaalstatus_herkomst}

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

    def toets_geboekt(
        self, *, document_id: uuid.UUID, boek_cyclus: int, boekstuknummer: str | None = None
    ) -> ToetsUitkomst:
        """Documenten-reconciliatie (A11/A12): één GET op het herboeking-GUID van de actieve cyclus.
        404 óf een hol antwoord = het document bestaat niet (meer) in RLZ; elke andere API-fout = `ToetsMislukt`
        (verbinding, niet het document). Status 2/3 = geboekt (CLAUDE.md — nooit alleen op 2 toetsen)."""
        rlz_document_id = rlz_herboeking_id(document_id, boek_cyclus)
        try:
            invoice = self.client.get(f"PurchaseInvoices/{rlz_document_id}")
        except RlzApiError as exc:
            if exc.status_code == 404:
                return ToetsUitkomst(
                    backend=Backend.RLZ, bestaat=False, extern_id=str(rlz_document_id), reden=str(exc)
                )
            raise ToetsMislukt(str(exc)) from exc
        if not is_bruikbaar_rlz_document(invoice):
            return ToetsUitkomst(
                backend=Backend.RLZ,
                bestaat=False,
                extern_id=str(rlz_document_id),
                reden="RLZ gaf 200 zonder bruikbaar document (geen id/Status) — behandeld als verdwenen",
                ruw={"antwoord": invoice} if isinstance(invoice, dict) else {"antwoord": repr(invoice)[:200]},
            )
        status = invoice.get("Status")
        return ToetsUitkomst(
            backend=Backend.RLZ,
            bestaat=True,
            geboekt=status in _RLZ_GEBOEKT,
            teruggedraaid=False,
            bedrag=_als_decimal(invoice.get("BaseInvoiceAmount")),
            boekstuknummer=invoice.get("ReceiptNumber"),
            extern_id=str(rlz_document_id),
            extern_state=None if status is None else str(status),
            ruw=invoice,
        )

    def toets_btw_periode(self, *, boekdatum: date) -> KantToets:
        """Aangifte-poort op een boekdatum zónder document (herboeken ná verdwenen document, correctie Peter 07-09):
        dezelfde fail-closed `AangiftePoort` als het storno-/tegenboek-pad, maar op de bewaarde BookDate (= factuur-
        datum van de verdwenen boeking) — het RLZ-document zelf bestaat niet meer om op te toetsen."""
        return AangiftePoort(self.client).toets_boekdatum(boekdatum, kant="inkoopfactuur")

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
                    # Blok 9: de herkenbare tegenboek-omschrijving ("TEGENBOEKING ‹nr› · ‹leverancier›") die al op
                    # élke regel staat, óók als document-kop (`Header` + `Description`, STAP-0 07-09).
                    **koptekst_velden(omschrijving),
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
