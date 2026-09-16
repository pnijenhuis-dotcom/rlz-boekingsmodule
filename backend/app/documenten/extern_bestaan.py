"""RLZ-/Odoo-bestaanscheck — "staat deze factuur al in de boekhouding?" — genormaliseerd (Peter 16-09, Zenvoices-casus
Hello Kitchen / Kempen Facilities).

Wortel van de casus: `RlzClient.find_purchase_invoices_by_reference` filtert server-side `Reference eq '<letterlijk>'`;
Zenvoices boekte `24594001722`, de module `2 4594 001722` → geen treffer → dubbel geboekt én dubbel betaald. OData kan
niet normaliseren, dus deze module haalt KANDIDATEN op (alle inkoopfacturen van de crediteur-IDENTITEIT — alle
crediteurrecords met dezelfde KvK/btw/voorkeur — in een datumvenster rond de factuurdatum, incl. concepten) en
vergelijkt client-side met `app/documenten/referentie.py::normaliseer_referentie` (één bron).

Match-basis per treffer (`match_basis`):
- `referentie`               — zelfde genormaliseerde referentie én cent-exact hetzelfde totaal → HARD (duplicaat-
                               signaal, auto-afvoer bij een extern GEBOEKT origineel, blokkerende check);
- `referentie_ander_bedrag`  — zelfde genormaliseerde referentie, ander totaal → BLOKKEREND in de check (mens beslist:
                               creditnota/correctie of écht dubbel), nooit auto-afvoer;
- `bedrag_datum`             — ander/onbekend nummer, cent-exact hetzelfde totaal binnen ± 30 dagen → ORANJE signaal
                               in de check (twee gelijke facturen van dezelfde leverancier komen legitiem voor; een
                               blokkade zonder mens-override zou werk bevriezen — beslispunt Peter 16-09), nooit
                               auto-afvoer.

De letterlijke `Reference eq`-route blijft de snelle eerste stap (werkt ook zonder factuurdatum en op clients die
`find_purchase_invoices_kandidaten` niet kennen); de kandidaten-stap vult aan. Fail-open richting de aanroeper: een
exception uit de client komt gewoon door (de harde check maakt daar al een blokkerende "kon niet controleren" van, het
signaal een zichtbare 'onbekend'-stand)."""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from app.documenten.referentie import normaliseer_referentie
from app.rlz.client import bedrag_cent_exact

BASIS_REFERENTIE = "referentie"
BASIS_REFERENTIE_ANDER_BEDRAG = "referentie_ander_bedrag"
BASIS_BEDRAG_DATUM = "bedrag_datum"
#: Alleen deze basis is hard genoeg voor het duplicaatsignaal + de automatische afvoer.
HARDE_BASES = frozenset({BASIS_REFERENTIE})
#: Deze bases blokkeren de boeking (mens beslist); `bedrag_datum` is een signaal.
BLOKKERENDE_BASES = frozenset({BASIS_REFERENTIE, BASIS_REFERENTIE_ANDER_BEDRAG})

VENSTER_DAGEN = 60
BEDRAG_VENSTER_DAGEN = 30


def _datum(waarde: object) -> date | None:
    if waarde is None:
        return None
    if isinstance(waarde, datetime):
        return waarde.date()
    if isinstance(waarde, date):
        return waarde
    tekst = str(waarde)[:10]
    try:
        return date.fromisoformat(tekst)
    except ValueError:
        return None


def status_van(rij: dict[str, Any]) -> int | None:
    """RLZ levert `Status` soms als `{id: n}` (expand), soms als kale int; de Odoo-facade als int."""
    status = rij.get("Status")
    if isinstance(status, dict):
        status = status.get("id")
    return int(status) if isinstance(status, int | str) and str(status).isdigit() else None


def bepaal_basis(
    rij: dict[str, Any],
    *,
    referentie_norm: str | None,
    totaalbedrag: Decimal | None,
    factuurdatum: date | None,
    bedrag_venster_dagen: int = BEDRAG_VENSTER_DAGEN,
) -> str | None:
    """Pure kern: welke match-basis heeft deze externe rij t.o.v. onze kop (None = geen match)."""
    rij_norm = normaliseer_referentie(rij.get("Reference") if rij.get("Reference") is not None else None)
    doel = bedrag_cent_exact(totaalbedrag) if totaalbedrag is not None else None
    rij_bedrag = bedrag_cent_exact(rij.get("BaseInvoiceAmount"))
    zelfde_bedrag = doel is not None and rij_bedrag is not None and doel == rij_bedrag
    # Bedrag aan één kant onbekend (kop nog leeg, of een leesroute zonder BaseInvoiceAmount): de referentie beslist.
    bedrag_onbekend = doel is None or rij_bedrag is None
    if referentie_norm is not None and rij_norm == referentie_norm:
        return BASIS_REFERENTIE if zelfde_bedrag or bedrag_onbekend else BASIS_REFERENTIE_ANDER_BEDRAG
    if zelfde_bedrag and factuurdatum is not None:
        rij_datum = _datum(rij.get("Date") or rij.get("BookDate"))
        if rij_datum is not None and abs((rij_datum - factuurdatum).days) <= bedrag_venster_dagen:
            return BASIS_BEDRAG_DATUM
    return None


def zoek_extern_bestaand(
    client: Any,
    *,
    vendor_ids: Iterable[uuid.UUID | str],
    referentie: str | None,
    totaalbedrag: Decimal | float | None,
    factuurdatum: date | None,
    uitgezonderd_ids: Iterable[uuid.UUID | str] = (),
    venster_dagen: int = VENSTER_DAGEN,
    bedrag_venster_dagen: int = BEDRAG_VENSTER_DAGEN,
) -> list[dict[str, Any]]:
    """Alle externe inkoopfacturen (RLZ of Odoo via de leesfacade) die met onze kop matchen, elk verrijkt met
    `match_basis`. Volgorde: letterlijke `Reference eq` per crediteurrecord (bestaande route), daarna de kandidaten in
    het datumvenster (als de client die route kent én er een factuurdatum is). Dedup op `id`; de eigen (her)boek-/
    tegenboek-keten (`uitgezonderd_ids`) telt nooit mee. Geen bedrag = alleen op referentie toetsen."""
    ids = [str(v) for v in vendor_ids if v]
    uitgezonderd = {str(i) for i in uitgezonderd_ids}
    bedrag = Decimal(str(totaalbedrag)) if totaalbedrag is not None else None
    norm = normaliseer_referentie(referentie)
    gevonden: dict[str, dict[str, Any]] = {}

    def _neem(rij: dict[str, Any], *, exact: bool = False) -> None:
        rij_id = str(rij.get("id") or "")
        if not rij_id or rij_id in uitgezonderd or rij_id in gevonden:
            return
        if exact:
            # De server filterde al op `Reference eq` (afgekapt op 30 tekens): die gelijkheid is gezaghebbend — een
            # ontbrekend of afgekapt Reference-veld in de rij mag de treffer niet wegnormaliseren.
            rij = {**rij, "Reference": referentie}
        basis = bepaal_basis(
            rij,
            referentie_norm=norm,
            totaalbedrag=bedrag,
            factuurdatum=factuurdatum,
            bedrag_venster_dagen=bedrag_venster_dagen,
        )
        if basis is None:
            return
        gevonden[rij_id] = {**rij, "match_basis": basis}

    if referentie:
        for vendor_id in ids:
            for rij in client.find_purchase_invoices_by_reference(
                vendor_id=vendor_id, reference=referentie, total_amount=None
            ):
                _neem(rij, exact=True)
    kandidaten = getattr(client, "find_purchase_invoices_kandidaten", None)
    if kandidaten is not None and factuurdatum is not None and ids:
        van = date.fromordinal(factuurdatum.toordinal() - venster_dagen)
        tot = date.fromordinal(factuurdatum.toordinal() + venster_dagen)
        for rij in kandidaten(vendor_ids=ids, van=van, tot=tot):
            _neem(rij)
    # Hard eerst, dan blokkerend, dan signaal; binnen een basis geboekt (2/3) vóór concept (1).
    rang = {BASIS_REFERENTIE: 0, BASIS_REFERENTIE_ANDER_BEDRAG: 1, BASIS_BEDRAG_DATUM: 2}
    return sorted(
        gevonden.values(),
        key=lambda r: (rang[r["match_basis"]], 0 if status_van(r) in (2, 3) else 1, str(r.get("id"))),
    )


def omschrijf_treffer(rij: dict[str, Any], *, systeem: str = "Reeleezee") -> str:
    """Mensentaal voor een treffer in een checkmelding: "al geboekt in Reeleezee: RLZ-04-00004314 (referentie
    24594001722, buiten de module)". `bron` = 'module' als de rij een eigen app-document is (aanroeper weet dat)."""
    boekstuk = rij.get("ReceiptNumber") or rij.get("InvoiceNumber") or "boekstuk onbekend"
    status = status_van(rij)
    stand = "als concept aanwezig" if status == 1 else "al geboekt"
    ref = rij.get("Reference")
    bron = "module" if rij.get("bron") in ("module", "app_historie") else "buiten de module"
    delen = [f"referentie {ref}" if ref else "zonder referentie", bron]
    if rij.get("match_basis") == BASIS_BEDRAG_DATUM:
        delen.append("zelfde bedrag en datum, ander nummer")
    elif rij.get("match_basis") == BASIS_REFERENTIE_ANDER_BEDRAG:
        delen.append("ander totaalbedrag")
    return f"{stand} in {systeem}: {boekstuk} ({', '.join(delen)})"
