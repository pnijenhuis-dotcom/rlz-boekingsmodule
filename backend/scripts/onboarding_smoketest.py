"""Onboarding-smoketest (batch 15-08, opdracht Peter): per administratie één TEST-inkoopboeking
mét TEST-referentie → boeken (17) → verifiëren → storno (19) → verifiëren. Expliciet akkoord
Peter voor deze TEST-schrijfacties op echte administraties (opdracht 2026-08-15).

Waarborgen (PoC-protocol, verkenning/poc_doorbelasting_schrijf.py):
- ADMIN-PIN vóór élke write: list_administrations() moet exact de verwachte administratie tonen.
- KILL SWITCH: bestand verkenning/POC_STOP aanwezig = onmiddellijk stoppen.
- TEST-referentie `TEST-ONB-<CODE>-01` (≤ 30 tekens; prefix TEST-ONB- geclaimd in
  Platform/registers/reference-prefixen.md), regelomschrijving zegt dat het om een test gaat.
- Idempotent: deterministische client-GUID (eigen namespace) + duplicaatcheck-vóór-PUT
  (find_purchase_invoices_by_reference) — herdraaien maakt nooit een tweede document.
- NOOIT verwijderen: opruimen = actie 19 (document blijft als concept staan).
- Append-only audit-JSONL: verkenning/output/onboarding_smoketest_audit.jsonl.

Draaien: backend/.venv/bin/python scripts/onboarding_smoketest.py [CODE ...] (default: alle)."""

from __future__ import annotations

import json
import sys
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / "verkenning" / ".env")

from app.db.models import Administratie, Grootboekrekening  # noqa: E402
from app.db.session import scoped_session  # noqa: E402
from app.rlz.client import RlzApiError  # noqa: E402
from app.rlz.credentials import BEKENDE_ADMINISTRATIES, open_root_client  # noqa: E402
from app.sync.models import VendorCache  # noqa: E402

# Eigen namespace (los van de app- én PoC-namespace) — deterministische document-GUID per code.
NAMESPACE = uuid.uuid5(uuid.NAMESPACE_URL, "rlz-boekingsmodule/onboarding-smoketest")
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # 21% NL hoog (vaste systeem-GUID)
KILL_SWITCH = REPO / "verkenning" / "POC_STOP"
AUDIT_PAD = REPO / "verkenning" / "output" / "onboarding_smoketest_audit.jsonl"

BATCH_CODES = (
    "ARVUM", "MEYER", "ELISSEN", "FACILITIES", "MOLENHOFB",
    "MOLENHOFV", "OIRSCHOT", "OVB", "VELDHOVEN", "SHUTO",
    "NIJENHUIS",  # na-onboarding 15-08 (401 bij de batch, zelfde dag hersteld)
)


def audit(gebeurtenis: str, **detail: object) -> None:
    AUDIT_PAD.parent.mkdir(parents=True, exist_ok=True)
    with AUDIT_PAD.open("a") as f:
        f.write(json.dumps({"op": datetime.now(UTC).isoformat(), "gebeurtenis": gebeurtenis, **detail}) + "\n")


def controleer_kill_switch() -> None:
    if KILL_SWITCH.exists():
        raise SystemExit(f"KILL SWITCH actief ({KILL_SWITCH}) — gestopt vóór de volgende write.")


def smoketest(code: str) -> str:
    bekend = next((a for a in BEKENDE_ADMINISTRATIES if a.prefix == code), None)
    if bekend is None:
        return f"{code}: OVERGESLAGEN — niet in BEKENDE_ADMINISTRATIES (credentialprobleem?)"

    with scoped_session(None) as session:
        administratie = session.scalars(
            select(Administratie).where(Administratie.rlz_admin_id == bekend.rlz_admin_id)
        ).one_or_none()
        if administratie is None:
            return f"{code}: OVERGESLAGEN — administratie niet in platform.administratie (import eerst)"
        administratie_id = administratie.id

    # Kostenrekening (AccountType 2, geen totaalrekening) — laagste code eerst. NB binnen de
    # RLS-scope van de administratie (grootboekrekening is administratie-gebonden).
    with scoped_session(administratie_id) as session:
        kosten = session.scalars(
            select(Grootboekrekening)
            .where(
                Grootboekrekening.administratie_id == administratie_id,
                Grootboekrekening.soort == 2,
                Grootboekrekening.is_totaalrekening.is_(False),
                Grootboekrekening.verdwenen_uit_bron_op.is_(None),
            )
            .order_by(Grootboekrekening.code)
        ).first()
        kosten_ledger_id, kosten_code = (kosten.ledger_id, kosten.code) if kosten else (None, None)

    if kosten_ledger_id is None:
        return f"{code}: AFWIJKING — geen kostenrekening (AccountType 2) in de cache; TEST-boeking overgeslagen"

    # Vendor via RLS-gescoopte sessie (vendor_cache is administratie-gebonden).
    with scoped_session(administratie_id) as sessie:
        vendor = sessie.scalars(
            select(VendorCache)
            .where(VendorCache.administratie_id == administratie_id, VendorCache.verdwenen_uit_bron_op.is_(None))
            .order_by(VendorCache.naam)
        ).first()
        vendor_id, vendor_naam = (vendor.id, vendor.naam) if vendor else (None, None)
    if vendor_id is None:
        return f"{code}: AFWIJKING — geen crediteuren in RLZ; TEST-boeking overgeslagen"

    referentie = f"TEST-ONB-{code}-01"
    assert len(referentie) <= 30, referentie
    document_id = uuid.uuid5(NAMESPACE, f"{bekend.rlz_admin_id}/inkoop/01")

    controleer_kill_switch()
    root = open_root_client(bekend.rlz_admin_id)
    client = root.for_administration(bekend.rlz_admin_id)
    try:
        # ADMIN-PIN: deze login moet exact deze ene administratie zien.
        gezien = [a.get("id") for a in root.list_administrations()]
        if gezien != [bekend.rlz_admin_id]:
            return f"{code}: GESTOPT — admin-pin faalde (login ziet {gezien})"

        # Duplicaatcheck vóór PUT (idempotent herdraaien).
        bestaand = client.find_purchase_invoices_by_reference(vendor_id=vendor_id, reference=referentie)
        if bestaand:
            audit("al_aanwezig", code=code, document_id=str(document_id), referentie=referentie)
            print(f"   {code}: TEST-document bestond al (status {bestaand[0].get('Status')}) — geen nieuwe PUT")
        else:
            controleer_kill_switch()
            client.put_purchase_invoice(
                document_id,
                vendor_id=vendor_id,
                reference=referentie,
                lines=[
                    {
                        "Account": {"id": str(kosten_ledger_id)},
                        "TaxRate": {"id": TAXRATE_21_ID},
                        "NetAmount": 1.00,
                        "TaxAmount": 0.21,
                        "Description": "TEST onboarding-smoketest — wordt direct gestorneerd",
                    }
                ],
                Date=date.today().isoformat(),
            )
            audit("put", code=code, document_id=str(document_id), referentie=referentie,
                  vendor=vendor_naam, kosten_gb=kosten_code)

        # Verifieerbaar aanwezig?
        na_put = client.find_purchase_invoices_by_reference(vendor_id=vendor_id, reference=referentie)
        if not na_put:
            return f"{code}: FOUT — document na PUT niet terugvindbaar op referentie"

        # Boeken (17) — alleen als nog concept; daarna verifiëren (geboekt = Status 2 óf 3).
        doc = client.get(f"PurchaseInvoices/{document_id}")
        if doc.get("Status") == 1:
            controleer_kill_switch()
            client.book_purchase_invoice(document_id)
            audit("book", code=code, document_id=str(document_id))
        status_geboekt = client.get(f"PurchaseInvoices/{document_id}").get("Status")
        if status_geboekt not in (2, 3):
            return f"{code}: FOUT — status na boeken is {status_geboekt} (verwacht 2/3)"

        # Storno (19) + verificatie (terug naar concept, Status 1). Nooit verwijderen.
        controleer_kill_switch()
        client.correct_purchase_invoice(document_id)
        audit("storno", code=code, document_id=str(document_id))
        status_storno = client.get(f"PurchaseInvoices/{document_id}").get("Status")
        if status_storno != 1:
            return f"{code}: FOUT — status na storno is {status_storno} (verwacht 1/concept)"

        return (
            f"{code}: OK — PUT+book+storno geverifieerd (vendor '{vendor_naam}', "
            f"kosten-GB {kosten_code}, ref {referentie}, doc {document_id})"
        )
    except RlzApiError as exc:
        audit("api_fout", code=code, status=exc.status_code, detail=str(exc)[:300])
        return f"{code}: API-FOUT {exc.status_code} — zie audit-JSONL"
    finally:
        root.close()


def main() -> int:
    codes = sys.argv[1:] or list(BATCH_CODES)
    resultaten = [smoketest(code) for code in codes]
    print()
    for regel in resultaten:
        print(regel)
    return 0 if all(": OK" in r or "al aanwezig" in r for r in resultaten) else 1


if __name__ == "__main__":
    raise SystemExit(main())
