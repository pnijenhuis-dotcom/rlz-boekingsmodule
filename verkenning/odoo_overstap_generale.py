"""Overstap-generale ingang B (Odoo-afrondingsrun 04-09, blok C2) — via de eigen HTTP-API, geen losse Odoo-writes.

Draaiboek (elke stap gelogd naar verkenning/output/odoo_overstap_generale_<datum>.jsonl, API-key geredigeerd; een
mislukte stap STOPT het script — vastleggen + rapporteren, nooit doorstampen):

 0. Voorwaarden: dev-backend op :8011, company 1 (Universal Steigerbouw, TEST-company) VRIJ op de Odoo-host.
 1. Nulmeting op de RLZ-testadministratie (faae29c5, RLZ 8dbfb856): geheugen-voorstel van een leverancier mét
    app-bevestigde observaties (Action) — gb/btw-UUID's zijn RLZ-UUID's.
 2. RLZ-leg VÓÓR de overstap: TEST-PDF → boekvoorstel op het geheugen-gb → boeken in de RLZ-TESTadministratie
    (TEST-referentie) → storno actie 19 (opruiming; niets verwijderd).
 3. `POST …/odoo/overstap/voorbereiden` (company 1) → deterministisch mapping-voorstel; rijen zonder voorstel krijgen een
    expliciet gelogde generale-keuze (rol van "de mens").
 4. `POST …/odoo/overstap` mét mapping + overgangsdatum → backend odoo, sentinel, eerste sync.
 5. Geheugen-voorstel Action NÁ de overstap = de gemapte Odoo-rekening, `app_bevestigd` ongewijzigd.
 6. Odoo-leg: TEST-crediteur → TEST-PDF (factuurdatum ≥ overgangsdatum) → boekvoorstel op de gemapte rekening → boeken
    → BILL op company 1 → tegenboeken (reversal) → RBILL.
 7. Document mét factuurdatum VÓÓR de overgangsdatum → boeken = leesbare weigering (adapter-poort, beslispunt 3).
 8. C1: overgangsdatum ná de Odoo-boeking → 409; terug naar de oude datum → 200.
 9. Opruimen: TEST-crediteur in Odoo archiveren (nooit unlink); TEST-documenten afwijzen mét reden.

Aanroep (vanuit backend/, dev-DB): `.venv/bin/python ../verkenning/odoo_overstap_generale.py [--tot-stap N]`.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import uuid
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "backend" / "tests"))

BASE = "http://127.0.0.1:8011"
BEHEERDER = uuid.UUID("2f2262cd-0423-4910-b7b5-335ba37a6ef5")
TEST_ADMIN = uuid.UUID("faae29c5-d197-4c24-a704-be2eae91fe49")
RLZ_TEST_ADMIN_ID = "8dbfb856-d75b-4ec3-9124-c8b739fe3bc5"
VENDOR_ACTION = uuid.UUID("f7a74265-518a-4384-ad6e-214aeee28c27")
COMPANY = 1
OVERGANG = "2026-09-01"
STAMP = datetime.now(UTC).strftime("%Y%m%d-%H%M%S")
LOG = Path(__file__).resolve().parent / "output" / f"odoo_overstap_generale_{datetime.now(UTC).date().isoformat()}.jsonl"
LOG.parent.mkdir(exist_ok=True)


class Stop(Exception):
    pass


def log(stap: str, **data: object) -> None:
    rij = {"tijd": datetime.now(UTC).isoformat(), "stap": stap, **data}
    tekst = json.dumps(rij, default=str, ensure_ascii=False)
    for geheim in _GEHEIMEN:
        if geheim:
            tekst = tekst.replace(geheim, "<geredigeerd>")
    with LOG.open("a") as f:
        f.write(tekst + "\n")
    print(tekst[:400])


_GEHEIMEN: list[str] = []


def api(token: str) -> httpx.Client:
    return httpx.Client(base_url=BASE, headers={"Authorization": f"Bearer {token}"}, timeout=180)


def verwacht(resp: httpx.Response, *codes: int, stap: str) -> dict:
    body: object
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = resp.text[:500]
    log(stap, http=resp.status_code, url=str(resp.request.url), body=body if resp.status_code not in (200, 201) else "ok")
    if resp.status_code not in codes:
        raise Stop(f"{stap}: HTTP {resp.status_code} (verwacht {codes}) — {body}")
    return body if isinstance(body, dict) else {}


def pdf_bytes(regels: list[str]) -> bytes:
    from extractie.pdf_helper import maak_tekst_pdf

    return maak_tekst_pdf(regels)


def upload(c: httpx.Client, aid: uuid.UUID, naam: str, regels: list[str], stap: str) -> uuid.UUID:
    resp = c.post(f"/administraties/{aid}/documenten", files={"bestand": (naam, pdf_bytes(regels), "application/pdf")})
    body = verwacht(resp, 201, 200, stap=stap)
    did = uuid.UUID(body["document_id"])
    # wachten tot de extractie klaar is (kleine PDF = synchroon, maar zeker zijn)
    for _ in range(60):
        d = c.get(f"/administraties/{aid}/documenten/{did}").json()
        if d["status"] not in ("ontvangen", "extractie_bezig", "extractie_wachtrij"):
            log(stap, document_id=did, status=d["status"])
            return did
        time.sleep(2)
    raise Stop(f"{stap}: extractie blijft hangen op {did}")


def voorstel(c: httpx.Client, aid: uuid.UUID, did: uuid.UUID, *, vendor: uuid.UUID, ref: str, datum: str, gb: uuid.UUID, btw: uuid.UUID, pct: Decimal, stap: str) -> dict:
    netto = Decimal("10.00")
    btw_bedrag = (netto * pct).quantize(Decimal("0.01"))
    body = {
        "vendor_id": str(vendor),
        "referentie": ref,
        "factuurdatum": datum,
        "totaalbedrag": str(netto + btw_bedrag),
        "regels": [{"ledger_id": str(gb), "taxrate_id": str(btw), "netto_bedrag": str(netto), "btw_bedrag": str(btw_bedrag), "omschrijving": "TEST generale overstap"}],
        "regels_samenvoegen": False,
    }
    resp = c.put(f"/administraties/{aid}/documenten/{did}/boekvoorstel", json=body)
    out = verwacht(resp, 200, stap=stap)
    checks = out.get("checks", {})
    log(stap, checks_geblokkeerd=checks.get("geblokkeerd"), rood=[r["naam"] for r in checks.get("resultaten", []) if not r["ok"]])
    return out


def geheugen(c: httpx.Client, aid: uuid.UUID, vendor: uuid.UUID, stap: str) -> dict:
    out = verwacht(c.post(f"/administraties/{aid}/boekingsgeheugen/voorstel", json={"vendor_id": str(vendor)}), 200, stap=stap)
    log(stap, gb=out["gb"], btw=out["btw"])
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tot-stap", type=int, default=9)
    args = parser.parse_args()

    from app.odoo.credentials import lees_dev_env
    from app.security.tokens import create_access_token

    url, key = lees_dev_env()
    if not url or not key:
        raise Stop("ODOO_URL/ODOO_API_KEY ontbreken (verkenning/.env)")
    _GEHEIMEN.append(key)
    token = create_access_token(BEHEERDER, rol="beheerder")
    c = api(token)
    log("start", base=BASE, test_admin=TEST_ADMIN, company=COMPANY, overgang=OVERGANG, stamp=STAMP)

    # 0. voorwaarden
    verwacht(c.get("/health"), 200, stap="0.health")
    vt = verwacht(c.post("/instellingen/odoo/verbinding-testen", json={"odoo_url": url, "api_key": key}), 200, stap="0.verbinding")
    c1 = next((x for x in vt["companies"] if x["company_id"] == COMPANY), None)
    if c1 is None or c1["al_gekoppeld"]:
        raise Stop(
            "0: company 1 is niet vrij — draai eerst (dev-DB) scratchpad/dev_company1_vrijmaken.py "
            "(archiveert de dev-Odoo-administratie fa3f83ae en maakt haar sentinel/URL onherkenbaar; niets verwijderd)"
        )
    log("0.company_vrij", company=c1)

    # 1. nulmeting
    gb_lijst = {r["ledger_id"]: r for r in verwacht(c.get(f"/administraties/{TEST_ADMIN}/grootboek"), 200, stap="1.grootboek")["rekeningen"]}
    btw_lijst = {r["id"]: r for r in verwacht(c.get(f"/administraties/{TEST_ADMIN}/btw-codes"), 200, stap="1.btw")["btw_codes"]}
    voor = geheugen(c, TEST_ADMIN, VENDOR_ACTION, "1.geheugen_voor")
    gb_voor, btw_voor = voor["gb"]["waarde"], voor["btw"]["waarde"]
    if not gb_voor:
        raise Stop("1: geen geheugen-gb voor Action — kies een andere leverancier")
    pct_voor = Decimal(str(btw_lijst[btw_voor]["percentage"])) if btw_voor and btw_lijst.get(btw_voor, {}).get("percentage") is not None else Decimal("0.21")
    if not btw_voor:
        btw_voor = next(i for i, r in btw_lijst.items() if r["percentage"] and Decimal(str(r["percentage"])) == Decimal("0.21"))
        pct_voor = Decimal("0.21")
    log("1.nulmeting", gb_voor=gb_lijst.get(gb_voor), btw_voor=btw_lijst.get(btw_voor), app_bevestigd=voor["gb"]["app_bevestigd"])
    if args.tot_stap < 2:
        return 0

    # 2. RLZ-leg vóór de overstap
    ref_rlz = f"TEST-GENERALE-RLZ-{STAMP}"
    did_rlz = upload(c, TEST_ADMIN, "test-generale-rlz.pdf", ["TEST GENERALE OVERSTAP — RLZ-leg", f"Factuurnummer {ref_rlz}", "Factuurdatum 15-08-2026", "Netto 10,00  BTW 2,10  Totaal 12,10"], "2.upload")
    voorstel(c, TEST_ADMIN, did_rlz, vendor=VENDOR_ACTION, ref=ref_rlz, datum="2026-08-15", gb=uuid.UUID(gb_voor), btw=uuid.UUID(btw_voor), pct=pct_voor, stap="2.voorstel")
    geboekt = verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_rlz}/boeken", json={}), 200, stap="2.boeken")
    log("2.geboekt_rlz", status=geboekt["status"], boekstuk=geboekt.get("rlz_boekstuknummer"), rlz_document_id=geboekt["rlz_document_id"])
    # storno actie 19 op de TEST-administratie (opruiming, api-verkenning "Actie 19 Correct")
    from app.rlz.credentials import client_voor_rlz_admin_id

    rlz = client_voor_rlz_admin_id(RLZ_TEST_ADMIN_ID)
    try:
        r = rlz.post_action(f"PurchaseInvoices/{geboekt['rlz_document_id']}", 19)
        log("2.storno_19", http=r.status_code)
        doc = rlz.get(f"PurchaseInvoices/{geboekt['rlz_document_id']}")
        log("2.storno_verificatie", status=doc.get("Status") if isinstance(doc, dict) else doc)
    finally:
        rlz.close()
    if args.tot_stap < 3:
        return 0

    # 3. voorbereiden + mapping invullen
    vb = verwacht(c.post(f"/administraties/{TEST_ADMIN}/odoo/overstap/voorbereiden", json={"odoo_url": url, "api_key": key, "company_id": COMPANY}), 200, stap="3.voorbereiden")
    log("3.telling", telling=vb["telling"], odoo_grootboek=len(vb["odoo_grootboek"]), odoo_btw=len(vb["odoo_btw"]))
    odoo_gb = sorted(vb["odoo_grootboek"], key=lambda o: o["code"])
    mapping_gb, keuzes = [], []
    for rij in vb["grootboek"]:
        if rij["voorstel_odoo_id"] is not None:
            mapping_gb.append({"rlz_id": rij["rlz_id"], "odoo_id": rij["voorstel_odoo_id"]})
            continue
        # generale-keuze "de mens": dichtstbijzijnde Odoo-code bij RLZ-code × 100 (expliciet gelogd)
        doel = int(rij["rlz_code"]) * 100 if (rij["rlz_code"] or "").isdigit() else 400000
        kandidaat = min(odoo_gb, key=lambda o: abs(int(o["code"]) - doel) if o["code"].isdigit() else 10**9)
        mapping_gb.append({"rlz_id": rij["rlz_id"], "odoo_id": kandidaat["odoo_id"]})
        keuzes.append({"rlz": f"{rij['rlz_code']} {rij['rlz_naam']}", "odoo": f"{kandidaat['code']} {kandidaat['naam']}"})
    mapping_btw, btw_keuzes = [], []
    for rij in vb["btw"]:
        if rij["voorstel_odoo_id"] is not None:
            mapping_btw.append({"rlz_id": rij["rlz_id"], "odoo_id": rij["voorstel_odoo_id"]})
            continue
        pct = Decimal(str(rij["rlz_percentage"] or 0))
        kandidaten = [t for t in vb["odoo_btw"] if bool(t["verlegd"]) == bool(rij["verlegd"]) and not t["synthetisch"]] or vb["odoo_btw"]
        kandidaat = min(kandidaten, key=lambda t: abs(Decimal(str(t["percentage"])) - pct))
        mapping_btw.append({"rlz_id": rij["rlz_id"], "odoo_id": kandidaat["odoo_id"]})
        btw_keuzes.append({"rlz": rij["rlz_naam"], "odoo": kandidaat["naam"]})
    log("3.mapping_keuzes", grootboek_handmatig=keuzes, btw_handmatig=btw_keuzes, grootboek_voorstel=len(mapping_gb) - len(keuzes), btw_voorstel=len(mapping_btw) - len(btw_keuzes))
    if args.tot_stap < 4:
        return 0

    # 4. overstap
    ov = verwacht(
        c.post(f"/administraties/{TEST_ADMIN}/odoo/overstap", json={"odoo_url": url, "api_key": key, "api_gebruiker": "N-Module", "company_id": COMPANY, "overgangsdatum": OVERGANG, "mapping": {"grootboek": mapping_gb, "btw": mapping_btw}}),
        201,
        stap="4.overstap",
    )
    log("4.overgestapt", sync=ov.get("sync"), probe_rood=[k for k, v in ov.get("probe", {}).items() if v != "ok"])
    stand = verwacht(c.get(f"/administraties/{TEST_ADMIN}/odoo"), 200, stap="4.stand")
    log("4.stand", backend_stand={k: stand.get(k) for k in ("company_id", "overgangsdatum", "rlz_admin_id_voor_overstap", "stamgegevens")})

    # 5. geheugen ná de overstap
    mp = verwacht(c.get(f"/administraties/{TEST_ADMIN}/odoo/mapping"), 200, stap="5.mapping")
    gemapt = {r["rlz_id"]: r for r in mp["grootboek"]}
    na = geheugen(c, TEST_ADMIN, VENDOR_ACTION, "5.geheugen_na")
    doel_rij = gemapt.get(gb_voor)
    odoo_lokaal = next((o["lokaal_id"] for o in mp["odoo_grootboek"] if doel_rij and o["odoo_id"] == doel_rij["odoo_id"]), None)
    ok = na["gb"]["waarde"] == odoo_lokaal and na["gb"]["app_bevestigd"] == voor["gb"]["app_bevestigd"]
    log("5.vergelijking", gb_voor=gb_voor, gemapt_naar=doel_rij and f"{doel_rij['odoo_code']} {doel_rij['odoo_naam']}", gb_na=na["gb"]["waarde"], verwacht=odoo_lokaal, app_bevestigd_voor=voor["gb"]["app_bevestigd"], app_bevestigd_na=na["gb"]["app_bevestigd"], ok=ok)
    if not ok:
        raise Stop("5: geheugen-voorstel draagt níét de gemapte rekening")
    if args.tot_stap < 6:
        return 0

    # 6. Odoo-leg
    cred = verwacht(c.post(f"/administraties/{TEST_ADMIN}/crediteuren", json={"naam": f"TEST-GENERALE Leverancier {STAMP} (niet gebruiken)"}), 201, stap="6.crediteur")
    vendor_odoo = uuid.UUID(cred["id"])
    btw_map = {r["rlz_id"]: r for r in mp["btw"]}
    btw_rij = btw_map.get(btw_voor)
    btw_lokaal = next((t["lokaal_id"] for t in mp["odoo_btw"] if btw_rij and t["odoo_id"] == btw_rij["odoo_id"]), None)
    pct_odoo = next((Decimal(str(t["percentage"])) for t in mp["odoo_btw"] if btw_rij and t["odoo_id"] == btw_rij["odoo_id"]), pct_voor)
    if not (odoo_lokaal and btw_lokaal):
        raise Stop("6: geen gemapte rekening/btw voor de Odoo-leg")
    ref_odoo = f"TEST-GENERALE-ODOO-{STAMP}"
    did_odoo = upload(c, TEST_ADMIN, "test-generale-odoo.pdf", ["TEST GENERALE OVERSTAP — Odoo-leg", f"Factuurnummer {ref_odoo}", "Factuurdatum 03-09-2026", "Netto 10,00  BTW 2,10  Totaal 12,10"], "6.upload")
    voorstel(c, TEST_ADMIN, did_odoo, vendor=vendor_odoo, ref=ref_odoo, datum="2026-09-03", gb=uuid.UUID(odoo_lokaal), btw=uuid.UUID(btw_lokaal), pct=pct_odoo, stap="6.voorstel")
    geboekt_o = verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_odoo}/boeken", json={}), 200, stap="6.boeken")
    detail = c.get(f"/administraties/{TEST_ADMIN}/documenten/{did_odoo}").json()
    log("6.geboekt_odoo", status=geboekt_o["status"], boekstuk=geboekt_o.get("rlz_boekstuknummer"), geboekt_in=detail.get("geboekt_in_rlz"))
    tb = verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_odoo}/tegenboeken", json={"soort": "volledig", "reden": "TEST generale overstap — opruiming via reversal"}), 200, stap="6.tegenboeken")
    detail = c.get(f"/administraties/{TEST_ADMIN}/documenten/{did_odoo}").json()
    log("6.reversal", tegenboeking=tb, geboekt_in=detail.get("geboekt_in_rlz"))
    if args.tot_stap < 7:
        return 0

    # 7. pré-datum document → poort
    ref_pre = f"TEST-GENERALE-PRE-{STAMP}"
    did_pre = upload(c, TEST_ADMIN, "test-generale-pre.pdf", ["TEST GENERALE OVERSTAP — vóór de overgangsdatum", f"Factuurnummer {ref_pre}", "Factuurdatum 20-08-2026", "Netto 10,00  BTW 2,10  Totaal 12,10"], "7.upload")
    voorstel(c, TEST_ADMIN, did_pre, vendor=vendor_odoo, ref=ref_pre, datum="2026-08-20", gb=uuid.UUID(odoo_lokaal), btw=uuid.UUID(btw_lokaal), pct=pct_odoo, stap="7.voorstel")
    resp = c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_pre}/boeken", json={})
    detail = c.get(f"/administraties/{TEST_ADMIN}/documenten/{did_pre}").json()
    log("7.boeken_pre_datum", http=resp.status_code, body=resp.text[:400], status=detail["status"])
    if resp.status_code == 200:
        raise Stop("7: een document vóór de overgangsdatum is in Odoo geboekt — poort werkt niet")
    verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_pre}/afwijzen", json={"reden": "TEST generale — document vóór de overgangsdatum (poort bewezen), opgeruimd"}), 200, stap="7.afwijzen")

    # 8. C1
    r409 = c.put(f"/administraties/{TEST_ADMIN}/odoo/overgangsdatum", json={"overgangsdatum": "2026-10-01"})
    log("8.c1_409", http=r409.status_code, body=r409.text[:400])
    if r409.status_code != 409:
        raise Stop("8: overgangsdatum ná een Odoo-boeking werd niet geweigerd")
    verwacht(c.put(f"/administraties/{TEST_ADMIN}/odoo/overgangsdatum", json={"overgangsdatum": OVERGANG}), 200, stap="8.c1_terug")

    # 9. opruimen: TEST-crediteur archiveren in Odoo (nooit unlink)
    from app.db.session import scoped_session
    from app.odoo.credentials import odoo_client_voor
    from app.odoo.sync import odoo_id_voor

    with scoped_session(TEST_ADMIN) as s:
        partner_id = odoo_id_voor(s, administratie_id=TEST_ADMIN, model="res.partner", lokaal_id=vendor_odoo)
    odoo = odoo_client_voor(TEST_ADMIN)
    try:
        odoo.write("res.partner", [partner_id], {"active": False})
        log("9.partner_gearchiveerd", partner_id=partner_id)
    finally:
        odoo.close()
    log("klaar", log=str(LOG))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Stop as exc:
        log("STOP", reden=str(exc))
        print(f"STOP: {exc}", file=sys.stderr)
        raise SystemExit(2)
