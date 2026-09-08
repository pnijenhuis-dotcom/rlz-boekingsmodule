#!/usr/bin/env python3
"""STAP 0 — Betaalstatus ("Betaling") op PurchaseInvoices (blok 3 bundel 08-09 avond; brief B3).

Feit uit de RLZ-UI (Peter 08-09): een inkoopfactuur heeft een veld "Betaling" met acht keuzes
(Nog te betalen · Wordt automatisch geïncasseerd · Betaald per bank · Betaald met PIN · Betaald met
Creditcard · Betaald – contant · Verrekend met privé · Verrekend met Rekening Courant). Effect: de post
blijft open tot de bankmutatie hem sluit, maar staat niet meer in de betaallijst.

Hypothese (api-verkenning "Verwachte-betaling-flow", 02-08): dat UI-veld = RLZ's `QuickPaymentSelection`
(keuze-id's per document via `GET PurchaseInvoices/{id}/QuickPaymentSelections`).

Vraag 1 (LEZEN, productie-administratie "Administratiekantoor Nijenhuis C.V.", alleen GET): welk veld
         verschilt tussen Kadaster (ref 9010961920, € 175,34, sinds 08-09 "Betaald per bank") en Exact
         Software (€ 45,92, "Nog te betalen")? Wat geeft `/QuickPaymentSelections` per document, en hoe heet
         de enum in `$metadata`?
Vraag 2 (SCHRIJVEN, TEST-administratie): is het veld te zetten via PUT op een GEBOEKT document (Status 2),
         zonder dat `BaseRemainingAmount`/`Status` veranderen? Kan het al bij de eerste PUT (vóór boeken) mee?
         Welke body-vorm is minimaal (kaal `{id, QuickPaymentSelection}` / mét PaymentAccount / volledige body)?

Stappen:
    lezen-cv  (cloud, alleen GET)  via <scratchpad>/cloud_env.sh — credential uit de cloud-store, Kadaster/Exact
                                    worden NIET aangeraakt. Output: <scratchpad>/stap0_cv_lezen.json (buiten de repo).
    keuzes    (test, GET)           QuickPaymentSelections op een bestaand TEST-document
    concept   (test, schrijf)       PUT TEST-BETAAL-01 (concept) + GET
    boek      (test, schrijf)       actie 17 op TEST-BETAAL-01 + GET
    zet       (test, schrijf)       her-PUT betaalstatus "Wordt automatisch geïncasseerd" → GET → "Betaald per bank" → GET
    voor-boeken (test, schrijf)     PUT TEST-BETAAL-02 mét betaalstatus in de eerste PUT, GET, boek, GET
    opruimen  (test, schrijf)       actie 19 op geboekte exemplaren (concept blijft staan; nooit verwijderen)
    alles     = keuzes → concept → boek → zet → voor-boeken → opruimen
Gebruik: backend/.venv/bin/python verkenning/poc_betaalstatus.py <stap>
"""

from __future__ import annotations

import json
import os
import re
import sys
import uuid
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent / "backend"))

from dotenv import load_dotenv  # noqa: E402

from app.rlz.client import RlzApiError, RlzClient  # noqa: E402
from app.rlz.credentials import resolve_credentials  # noqa: E402

TESTADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
TAXRATE_21_ID = "1e44993a-15f6-419f-87e5-3e31ac3d9383"
CREDITEUR_NAAM = "TEST-DOORB Kempen Facilities B.V."
_POC_NS = uuid.UUID("b1a6c9de-4f02-47d3-9b7a-2e8f0c5d1a44")
DOCS = {
    "TEST-BETAAL-01": (uuid.uuid5(_POC_NS, "betaalstatus:TEST-BETAAL-01"), 100.00, 21.00),
    "TEST-BETAAL-02": (uuid.uuid5(_POC_NS, "betaalstatus:TEST-BETAAL-02"), 10.00, 2.10),
}
KILL_SWITCH = HIER / "POC_STOP"
OUTPUT = HIER / "output"
AUDIT_LOG = OUTPUT / "betaalstatuspoc_audit.jsonl"
VANDAAG = datetime.now(UTC).date().isoformat()
SCRATCH = Path(os.environ.get("STAP0_SCRATCH", str(HIER.parent / "verkenning" / "output")))

CV_NAAM_FRAGMENT = "Nijenhuis C.V."
KADASTER_REF = "9010961920"
EXACT_BEDRAG = 45.92

KOPVELDEN_INTERESSANT = (
    "id", "Status", "ReceiptNumber", "Reference", "BaseInvoiceAmount", "BaseRemainingAmount", "BasePaidAmount",
    "PaymentStatus", "PaymentMethod", "QuickPaymentSelection", "PaymentAccount", "PaymentTermList", "IsPaid",
)


def _audit(entry: dict[str, Any], admin: str = TESTADMIN_ID) -> None:
    OUTPUT.mkdir(exist_ok=True)
    with AUDIT_LOG.open("a") as f:
        f.write(json.dumps({"ts": datetime.now(UTC).isoformat(), "admin": admin, **entry}, default=str) + "\n")


def _scalars(d: dict) -> dict:
    """Alle kopvelden plat: scalars zoals ze zijn, geneste dicts als {id, Name/Description}, lijsten als lengte."""
    uit: dict[str, Any] = {}
    for k, v in d.items():
        if isinstance(v, dict):
            uit[k] = {kk: v.get(kk) for kk in ("id", "Name", "Description", "Type", "Code") if kk in v}
        elif isinstance(v, list):
            uit[k] = f"<lijst {len(v)}>"
        else:
            uit[k] = v
    return uit


def _diff(a: dict, b: dict) -> dict[str, tuple[Any, Any]]:
    sa, sb = _scalars(a), _scalars(b)
    return {k: (sa.get(k), sb.get(k)) for k in sorted(set(sa) | set(sb)) if sa.get(k) != sb.get(k)}


def _quick(c: RlzClient, doc_id: str) -> Any:
    try:
        return c.get(f"PurchaseInvoices/{doc_id}/QuickPaymentSelections")
    except RlzApiError as e:
        return {"fout": f"{e.status_code} {e.body[:200]}"}


def _metadata_enums(c: RlzClient) -> dict[str, Any]:
    """`$metadata` (XML) — enum-types + property-namen rond 'Payment'. Root- én admin-scoped pad proberen."""
    uit: dict[str, Any] = {}
    for pad in ("$metadata", "/$metadata"):
        try:
            r = c.request_raw("GET", pad, headers={"Accept": "application/xml"})
        except RlzApiError as e:
            uit[pad] = f"{e.status_code} {e.body[:120]}"
            continue
        xml = r.text
        enums = {}
        for m in re.finditer(r'<EnumType Name="([^"]*Pay[^"]*)"[^>]*>(.*?)</EnumType>', xml, re.S):
            enums[m.group(1)] = re.findall(r'<Member Name="([^"]+)" Value="([^"]+)"', m.group(2))
        props = sorted(set(re.findall(r'<(?:Navigation)?Property Name="([^"]*(?:Payment|Quick)[^"]*)"[^>]*Type="([^"]+)"', xml)))
        entiteit = re.search(r'<EntityType Name="QuickPaymentSelection[^"]*"[^>]*>(.*?)</EntityType>', xml, re.S)
        uit[pad] = {
            "lengte": len(xml),
            "enums_met_Pay": enums,
            "properties_Payment_of_Quick": props[:60],
            "QuickPaymentSelection_entity": re.findall(r'<Property Name="([^"]+)"[^>]*Type="([^"]+)"', entiteit.group(1)) if entiteit else None,
        }
        break
    return uit


# ------------------------------------------------------------------ LEZEN (cloud, productie C.V.) --------------


def stap_lezen_cv() -> None:
    if not os.environ.get("APP_DATABASE_URL") or ":5433/" in os.environ.get("APP_DATABASE_URL", ""):
        raise SystemExit("lezen-cv vereist de CLOUD-omgeving (cloud_env.sh; APP_DATABASE_URL op de 5434-proxy).")
    from sqlalchemy import select

    from app.db.models import Administratie
    from app.db.session import scoped_session

    with scoped_session(None) as session:
        rijen = session.scalars(select(Administratie).where(Administratie.naam.ilike(f"%{CV_NAAM_FRAGMENT}%"))).all()
        kandidaten = [(str(a.id), a.naam, a.rlz_admin_id) for a in rijen]
    print("administraties met", CV_NAAM_FRAGMENT, "→", [(n, r) for _, n, r in kandidaten])
    if len(kandidaten) != 1:
        raise SystemExit(f"Verwacht precies één C.V.-administratie, gevonden {len(kandidaten)} — stop.")
    _, naam, rlz_admin_id = kandidaten[0]
    user, pw = resolve_credentials(rlz_admin_id)
    login = RlzClient(username=user, password=pw)
    ids = [a["id"] for a in login.list_administrations()]
    if rlz_admin_id not in ids:
        raise SystemExit(f"FAILSAFE: login ziet {ids}, niet {rlz_admin_id}")
    c = login.for_administration(rlz_admin_id)
    rapport: dict[str, Any] = {"administratie": naam, "rlz_admin_id": rlz_admin_id, "ts": datetime.now(UTC).isoformat()}

    kad = c.get("PurchaseInvoices", params={"$filter": f"Reference eq '{KADASTER_REF}'", "$expand": "Entity"}).get("value", [])
    print(f"Kadaster-treffers op Reference {KADASTER_REF}: {len(kad)} → "
          + json.dumps([{k: t.get(k) for k in ('id', 'Status', 'BaseInvoiceAmount', 'Date')} | {'Entity': (t.get('Entity') or {}).get('Name')} for t in kad], default=str))
    # Exact Software: geen referentie bekend → recente facturen ophalen en client-side op bedrag + naam kiezen.
    recent = c.get("PurchaseInvoices", params={"$expand": "Entity", "$orderby": "Date desc", "$top": "80"}).get("value", [])
    exact = [t for t in recent if abs(float(t.get("BaseInvoiceAmount") or 0) - EXACT_BEDRAG) < 0.005]
    print(f"Exact-kandidaten op bedrag {EXACT_BEDRAG}: "
          + json.dumps([{k: t.get(k) for k in ('id', 'Status', 'Reference', 'Date')} | {'Entity': (t.get('Entity') or {}).get('Name')} for t in exact], default=str))
    if not kad or not exact:
        rapport["fout"] = "Kadaster of Exact niet gevonden"
        _schrijf_rapport(rapport)
        return
    k_id, e_id = kad[0]["id"], exact[0]["id"]
    k_vol = c.get(f"PurchaseInvoices/{k_id}")
    e_vol = c.get(f"PurchaseInvoices/{e_id}")
    rapport["kadaster_kopvelden"] = _scalars(k_vol)
    rapport["exact_kopvelden"] = _scalars(e_vol)
    rapport["diff_kadaster_vs_exact"] = _diff(k_vol, e_vol)
    print("\n== DIFF Kadaster (Betaald per bank) vs Exact (Nog te betalen), kopvelden:")
    for k, (a, b) in rapport["diff_kadaster_vs_exact"].items():
        print(f"   {k}: Kadaster={a!r}  |  Exact={b!r}")
    # Expands die mogelijk het betaalveld dragen
    for exp in ("QuickPaymentSelection", "PaymentAccount", "PaymentTermList", "PaymentTermList($expand=PaymentAccount)"):
        try:
            k_e = c.get(f"PurchaseInvoices/{k_id}", params={"$expand": exp})
            e_e = c.get(f"PurchaseInvoices/{e_id}", params={"$expand": exp})
            sleutel = exp.split("(")[0]
            rapport[f"expand_{sleutel}"] = {"kadaster": k_e.get(sleutel), "exact": e_e.get(sleutel)}
            print(f"\n== $expand={exp}:\n   Kadaster: {json.dumps(k_e.get(sleutel), default=str)[:600]}\n   Exact:    {json.dumps(e_e.get(sleutel), default=str)[:600]}")
        except RlzApiError as e:
            rapport[f"expand_{exp}"] = f"{e.status_code} {e.body[:160]}"
            print(f"\n== $expand={exp}: {e.status_code} {e.body[:160]}")
    rapport["quick_kadaster"] = _quick(c, k_id)
    rapport["quick_exact"] = _quick(c, e_id)
    print("\n== QuickPaymentSelections Kadaster:", json.dumps(rapport["quick_kadaster"], default=str)[:1500])
    print("== QuickPaymentSelections Exact:", json.dumps(rapport["quick_exact"], default=str)[:1500])
    for naam_pi, d_id in (("kadaster", k_id), ("exact", e_id)):
        try:
            rapport[f"paymentitems_{naam_pi}"] = c.get(f"PurchaseInvoices/{d_id}/PaymentItems")
        except RlzApiError as e:
            rapport[f"paymentitems_{naam_pi}"] = f"{e.status_code} {e.body[:160]}"
        print(f"== PaymentItems {naam_pi}:", json.dumps(rapport[f"paymentitems_{naam_pi}"], default=str)[:800])
    rapport["metadata"] = _metadata_enums(login)
    print("\n== $metadata:", json.dumps(rapport["metadata"], default=str)[:3000])
    _schrijf_rapport(rapport)


def _schrijf_rapport(rapport: dict) -> None:
    SCRATCH.mkdir(parents=True, exist_ok=True)
    pad = SCRATCH / "stap0_cv_lezen.json"
    pad.write_text(json.dumps(rapport, indent=1, default=str))
    print("\nrapport →", pad)


# ------------------------------------------------------------------ SCHRIJVEN (test-administratie) -------------


class PocClient:
    def __init__(self) -> None:
        load_dotenv(HIER / ".env")
        user, pw = resolve_credentials(TESTADMIN_ID)
        login = RlzClient(username=user, password=pw)
        ids = [a["id"] for a in login.list_administrations()]
        if ids != [TESTADMIN_ID]:
            raise SystemExit(f"FAILSAFE: login ziet {ids}, verwacht alleen {TESTADMIN_ID}")
        self.root = login
        self.rlz = login.for_administration(TESTADMIN_ID)

    def get(self, path: str, **params: Any) -> Any:
        return self.rlz.get(path, params=params or None)

    def put(self, path: str, body: dict[str, Any]) -> int:
        if KILL_SWITCH.exists():
            raise SystemExit("KILL SWITCH actief")
        try:
            r = self.rlz.put(path, body)
            _audit({"actie": "PUT", "pad": path, "payload": body, "status": r.status_code})
            return r.status_code
        except RlzApiError as e:
            _audit({"actie": "PUT", "pad": path, "payload": body, "status": f"{e.status_code}: {e.body[:300]}"})
            raise

    def actie(self, pad: str, t: int) -> Any:
        if KILL_SWITCH.exists():
            raise SystemExit("KILL SWITCH actief")
        r = self.rlz.post_action(pad, t)
        nieuw = self.get(pad)
        _audit({"actie": f"POST Actions {t}", "pad": pad, "status": r.status_code, "nieuw": _scalars(nieuw)})
        return nieuw


def _vendor_id(c: PocClient) -> str:
    v = c.get("Vendors", **{"$filter": f"Name eq '{CREDITEUR_NAAM.replace(chr(39), chr(39) * 2)}'"}).get("value", [])
    if not v:
        raise SystemExit("TEST-crediteur ontbreekt")
    return v[0]["id"]


def _kosten(c: PocClient) -> str:
    k = next((x for x in c.get("Ledgers", search="4302").get("value", []) if x.get("AccountType") == 2), None)
    if k is None:
        raise SystemExit("Geen kostenrekening 4302")
    return k["id"]


def _doc(c: PocClient, doc_id: uuid.UUID, label: str) -> dict:
    d = c.get(f"PurchaseInvoices/{doc_id}")
    s = _scalars(d)
    print(f"   [{label}] " + "  ".join(f"{k}={s.get(k)!r}" for k in KOPVELDEN_INTERESSANT if k in s))
    return d


def _keuzes(c: PocClient, doc_id: uuid.UUID, label: str) -> list[dict]:
    q = _quick(c.rlz, str(doc_id))
    rijen = q.get("value", q) if isinstance(q, dict) else q
    print(f"   [{label}] QuickPaymentSelections:")
    if isinstance(rijen, list):
        for r in rijen:
            print("      " + json.dumps(r, default=str)[:300])
    else:
        print("      ", json.dumps(rijen, default=str)[:600])
    return rijen if isinstance(rijen, list) else []


def _keuze_id(keuzes: list[dict], naam_fragment: str) -> str | None:
    for r in keuzes:
        tekst = " ".join(str(v) for v in r.values() if isinstance(v, str))
        if naam_fragment.lower() in tekst.lower():
            return r.get("id")
    return None


def _body(c: PocClient, ref: str, **extra: Any) -> dict[str, Any]:
    doc_id, net, btw = DOCS[ref]
    return {
        "id": str(doc_id),
        "Entity": {"id": _vendor_id(c)},
        "DocumentLineList": [{"Account": {"id": _kosten(c)}, "TaxRate": {"id": TAXRATE_21_ID},
                              "NetAmount": net, "TaxAmount": btw, "Description": f"{ref} regel 1"}],
        "Reference": ref,
        "Date": f"{VANDAAG}T00:00:00",
        "BookDate": f"{VANDAAG}T00:00:00",
        **extra,
    }


def stap_keuzes(c: PocClient) -> None:
    doc_id = DOCS["TEST-BETAAL-01"][0]
    try:
        c.get(f"PurchaseInvoices/{doc_id}")
    except RlzApiError:
        print("== TEST-BETAAL-01 bestaat nog niet; keuzes worden bij 'concept' getoond")
        return
    _keuzes(c, doc_id, "TEST-BETAAL-01")
    print("== $metadata:", json.dumps(_metadata_enums(c.root), default=str)[:3000])


def stap_concept(c: PocClient) -> None:
    ref = "TEST-BETAAL-01"
    doc_id = DOCS[ref][0]
    print(f"== PUT {ref} (concept, zonder betaalstatus)")
    c.put(f"PurchaseInvoices/{doc_id}", _body(c, ref))
    _doc(c, doc_id, f"{ref} concept")
    _keuzes(c, doc_id, f"{ref} concept")


def stap_boek(c: PocClient) -> None:
    ref = "TEST-BETAAL-01"
    doc_id = DOCS[ref][0]
    print(f"== boek {ref} (actie 17)")
    c.actie(f"PurchaseInvoices/{doc_id}", 17)
    d = _doc(c, doc_id, f"{ref} geboekt")
    print("   alle kopvelden:", json.dumps(_scalars(d), default=str))
    _keuzes(c, doc_id, f"{ref} geboekt")


def _zet(c: PocClient, ref: str, keuze_naam: str) -> dict | None:
    """Probeer de betaalstatus te zetten op een bestaand document — minimale body eerst, dan varianten."""
    doc_id = DOCS[ref][0]
    keuzes = _keuzes(c, doc_id, f"{ref} vóór zetten")
    kid = _keuze_id(keuzes, keuze_naam)
    if kid is None:
        print(f"   !! geen keuze gevonden voor {keuze_naam!r}")
        return None
    voor = c.get(f"PurchaseInvoices/{doc_id}")
    varianten = [
        ("kaal {id, QuickPaymentSelection}", {"id": str(doc_id), "QuickPaymentSelection": {"id": kid}}),
        ("volledige body + QuickPaymentSelection", _body(c, ref, QuickPaymentSelection={"id": kid})),
    ]
    for label, body in varianten:
        print(f"== her-PUT {ref} → {keuze_naam!r} via {label}")
        try:
            status = c.put(f"PurchaseInvoices/{doc_id}", body)
        except RlzApiError as e:
            print(f"   {e.status_code} {e.body[:200]}")
            continue
        na = _doc(c, doc_id, f"{ref} ná {label} ({status})")
        d = _diff(voor, na)
        print("   diff vóór→ná:", json.dumps(d, default=str)[:800])
        for exp in ("QuickPaymentSelection", "PaymentTermList"):
            try:
                e = c.get(f"PurchaseInvoices/{doc_id}", **{"$expand": exp})
                print(f"   $expand={exp}: {json.dumps(e.get(exp), default=str)[:500]}")
            except RlzApiError as ex:
                print(f"   $expand={exp}: {ex.status_code}")
        _keuzes(c, doc_id, f"{ref} ná zetten")
        return na
    return None


def stap_zet(c: PocClient) -> None:
    _zet(c, "TEST-BETAAL-01", "automatisch")
    _zet(c, "TEST-BETAAL-01", "per bank")


def stap_voor_boeken(c: PocClient) -> None:
    ref = "TEST-BETAAL-02"
    doc_id = DOCS[ref][0]
    # Keuze-id's zijn per document; haal ze van TEST-BETAAL-01 (bestaat) — zijn ze document-onafhankelijk?
    keuzes = _keuzes(c, DOCS["TEST-BETAAL-01"][0], "TEST-BETAAL-01 (bron keuze-id)")
    kid = _keuze_id(keuzes, "automatisch")
    if kid is None:
        print("   !! geen incasso-keuze; stap overgeslagen")
        return
    print(f"== PUT {ref} mét QuickPaymentSelection in de EERSTE PUT (vóór boeken)")
    try:
        c.put(f"PurchaseInvoices/{doc_id}", _body(c, ref, QuickPaymentSelection={"id": kid}))
    except RlzApiError as e:
        print(f"   {e.status_code} {e.body[:200]} → terugval: PUT zonder, daarna her-PUT")
        c.put(f"PurchaseInvoices/{doc_id}", _body(c, ref))
        c.put(f"PurchaseInvoices/{doc_id}", {"id": str(doc_id), "QuickPaymentSelection": {"id": kid}})
    _doc(c, doc_id, f"{ref} concept")
    try:
        e = c.get(f"PurchaseInvoices/{doc_id}", **{"$expand": "QuickPaymentSelection"})
        print("   $expand=QuickPaymentSelection:", json.dumps(e.get("QuickPaymentSelection"), default=str)[:400])
    except RlzApiError as ex:
        print("   $expand:", ex.status_code)
    print(f"== boek {ref} (actie 17)")
    c.actie(f"PurchaseInvoices/{doc_id}", 17)
    _doc(c, doc_id, f"{ref} geboekt")
    try:
        e = c.get(f"PurchaseInvoices/{doc_id}", **{"$expand": "QuickPaymentSelection"})
        print("   $expand=QuickPaymentSelection ná boeken:", json.dumps(e.get("QuickPaymentSelection"), default=str)[:400])
    except RlzApiError as ex:
        print("   $expand:", ex.status_code)
    _keuzes(c, doc_id, f"{ref} geboekt")


def stap_opruimen(c: PocClient) -> None:
    for ref, (doc_id, *_) in DOCS.items():
        try:
            d = c.get(f"PurchaseInvoices/{doc_id}")
        except RlzApiError:
            print(f"   {ref}: bestaat niet")
            continue
        if d.get("Status") != 1:
            c.actie(f"PurchaseInvoices/{doc_id}", 19)
        _doc(c, doc_id, f"{ref} na opruimen")


STAPPEN = {"keuzes": stap_keuzes, "concept": stap_concept, "boek": stap_boek, "zet": stap_zet,
           "voor-boeken": stap_voor_boeken, "opruimen": stap_opruimen}

if __name__ == "__main__":
    stap = sys.argv[1] if len(sys.argv) > 1 else "help"
    if stap == "lezen-cv":
        stap_lezen_cv()
    elif stap == "alles":
        c = PocClient()
        for s in ("keuzes", "concept", "boek", "zet", "voor-boeken", "opruimen"):
            STAPPEN[s](c)
    elif stap in STAPPEN:
        STAPPEN[stap](PocClient())
    else:
        print(__doc__)
