"""Overstap-generale ingang B (Odoo-afrondingsrun 04-09 blok C2, herzien in het Odoo-slotstuk 04-09 blok D) — via de eigen
HTTP-API, geen losse Odoo-writes buiten het opruimen (archiveren).

Draaiboek (elke stap gelogd naar verkenning/output/odoo_overstap_generale_<datum>.jsonl, API-key geredigeerd; een
mislukte stap STOPT het script — vastleggen + rapporteren, nooit doorstampen):

 0. Voorwaarden: dev-backend op :8011, company 1 (Universal Steigerbouw, TEST-company) VRIJ op de Odoo-host.
 1. Nulmeting op de RLZ-testadministratie (faae29c5, RLZ 8dbfb856): geheugen-voorstel van een leverancier mét
    app-bevestigde observaties (Action) — gb/btw-UUID's zijn RLZ-UUID's.
 2. RLZ-leg VÓÓR de overstap: TEST-PDF (mét btw-nummer van de leverancier) → boekvoorstel op het geheugen-gb + het
    RLZ-project → boeken in de RLZ-TESTadministratie (TEST-referentie) → storno actie 19 (opruiming; niets verwijderd).
    Het geheugen draagt daarna een observatie mét RLZ-project (blok B bewijst dat die de overstap overleeft).
 3. `POST …/odoo/overstap/voorbereiden` (company 1) → deterministisch mapping-voorstel grootboek/btw/PROJECT; rijen zonder
    voorstel krijgen een expliciet gelogde generale-keuze (rol van "de mens").
 4. `POST …/odoo/overstap` mét mapping (incl. project) + kanteldatum → backend odoo, sentinel, hervertaling van de open
    boekvoorstellen (blok C1), eerste sync.
 5. Geheugen-voorstel Action NÁ de overstap = de gemapte Odoo-rekening ÉN het gemapte Odoo-project, `app_bevestigd`
    ongewijzigd; 5b: open boekvoorstellen dragen `overstap_vertaling` per veld.
 6. Odoo-leg: TEST-crediteur → TEST-PDF (factuurdatum ≥ kanteldatum) → boekvoorstel op de gemapte rekening → boeken
    → BILL op company 1 → tegenboeken (reversal) → RBILL.
 7. Blok A (besluit Peter "geen blokkade"): (a) nakomer mét factuurdatum VÓÓR de kanteldatum boekt gewoon in Odoo (+ reversal);
    (b) nakomer die al in RLZ geboekt was (zelfde crediteur-btw-nummer/referentie/bedrag als de RLZ-leg) = duplicaatcheck rood
    mét het RLZ-boekstuk én automatisch afgevoerd als duplicaat; (c) nakomer mét factuurdatum in een in Odoo afgesloten periode
    (≤ tax_lock_date 31-12-2025) boekt mét zichtbaar verschoven boekdatum (lock + 1 dag, A2) → reversal.
 8. Kanteldatum wijzigen = altijd 200 (geen 409 meer) → terug naar de oude datum → 200.
 9. Opruimen: TEST-crediteur in Odoo archiveren (nooit unlink).

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
BTW_NUMMER = "NL812345678B01"  # geldig (elfproef) TEST-btw-nummer: crediteur-kenmerk voor de dedup over de backend-grens
RLZ_PROJECT = uuid.UUID("d050af7e-1d5b-50fc-abed-2b0ab6b50e77")  # "TEST-ROUTE-A Pand Dorpsstraat 1" (route A 14-08)
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


def voorstel(c: httpx.Client, aid: uuid.UUID, did: uuid.UUID, *, vendor: uuid.UUID, ref: str, datum: str, gb: uuid.UUID, btw: uuid.UUID, pct: Decimal, stap: str, project: uuid.UUID | None = None) -> dict:
    netto = Decimal("10.00")
    btw_bedrag = (netto * pct).quantize(Decimal("0.01"))
    body = {
        "vendor_id": str(vendor),
        "referentie": ref,
        "factuurdatum": datum,
        "totaalbedrag": str(netto + btw_bedrag),
        "regels": [{"ledger_id": str(gb), "taxrate_id": str(btw), "project_id": str(project) if project else None, "netto_bedrag": str(netto), "btw_bedrag": str(btw_bedrag), "omschrijving": "TEST generale overstap"}],
        "regels_samenvoegen": False,
    }
    resp = c.put(f"/administraties/{aid}/documenten/{did}/boekvoorstel", json=body)
    out = verwacht(resp, 200, stap=stap)
    checks = out.get("checks", {})
    log(stap, checks_geblokkeerd=checks.get("geblokkeerd"), rood=[f"{r['naam']}: {r['melding']}" for r in checks.get("resultaten", []) if not r["ok"]])
    return out


def geheugen(c: httpx.Client, aid: uuid.UUID, vendor: uuid.UUID, stap: str) -> dict:
    out = verwacht(c.post(f"/administraties/{aid}/boekingsgeheugen/voorstel", json={"vendor_id": str(vendor)}), 200, stap=stap)
    log(stap, gb=out["gb"], btw=out["btw"], project=out.get("project"))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tot-stap", type=int, default=9)
    parser.add_argument("--vanaf-stap", type=int, default=0, help="6 = stappen 1–5 overslaan op een al overgestapte administratie (ref van de RLZ-leg via --ref-rlz)")
    parser.add_argument("--ref-rlz", default=None)
    parser.add_argument("--vendor-odoo", default=None, help="vanaf stap 7: de al aangemaakte TEST-crediteur (Odoo) hergebruiken")
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
    if args.vanaf_stap >= 6:
        return vervolg(c, args)  # administratie is al overgestapt (company 1 dan terecht bezet)
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
    did_rlz = upload(c, TEST_ADMIN, "test-generale-rlz.pdf", ["TEST GENERALE OVERSTAP — RLZ-leg", "Leverancier: Action", f"BTW-nummer {BTW_NUMMER}", f"Factuurnummer {ref_rlz}", "Factuurdatum 15-08-2026", "Netto 10,00  BTW 2,10  Totaal 12,10"], "2.upload")
    voorstel(c, TEST_ADMIN, did_rlz, vendor=VENDOR_ACTION, ref=ref_rlz, datum="2026-08-15", gb=uuid.UUID(gb_voor), btw=uuid.UUID(btw_voor), pct=pct_voor, stap="2.voorstel", project=RLZ_PROJECT)
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
    # Blok B (slotstuk): projectmapping — voorstel volgen; zonder voorstel = generale-keuze "de mens": Odoo-project "Test Thomas"
    # (actief analytic account op company 1), expliciet gelogd. Een rij mag leeg blijven (project vervalt) — hier bewust niet.
    odoo_pr = vb.get("odoo_projecten", [])
    doel_pr = next((o for o in odoo_pr if "test thomas" in (o["naam"] or "").lower()), odoo_pr[0] if odoo_pr else None)
    mapping_pr, pr_keuzes = [], []
    for rij in vb.get("project", []):
        if rij["voorstel_odoo_id"] is not None:
            mapping_pr.append({"rlz_id": rij["rlz_id"], "odoo_id": rij["voorstel_odoo_id"]})
            continue
        if doel_pr is None:
            raise Stop("3: geen Odoo-projecten op company 1 om de generale-keuze op te maken")
        mapping_pr.append({"rlz_id": rij["rlz_id"], "odoo_id": doel_pr["odoo_id"]})
        pr_keuzes.append({"rlz": rij["rlz_naam"], "odoo": f"{doel_pr['code']} {doel_pr['naam']}", "kan_aanmaken": rij["kan_aanmaken"]})
    log("3.mapping_keuzes", grootboek_handmatig=keuzes, btw_handmatig=btw_keuzes, project_handmatig=pr_keuzes, grootboek_voorstel=len(mapping_gb) - len(keuzes), btw_voorstel=len(mapping_btw) - len(btw_keuzes), project_voorstel=len(mapping_pr) - len(pr_keuzes), project_in_gebruik=vb.get("project"))
    if args.tot_stap < 4:
        return 0

    # 4. overstap
    ov = verwacht(
        c.post(f"/administraties/{TEST_ADMIN}/odoo/overstap", json={"odoo_url": url, "api_key": key, "api_gebruiker": "N-Module", "company_id": COMPANY, "overgangsdatum": OVERGANG, "mapping": {"grootboek": mapping_gb, "btw": mapping_btw, "project": mapping_pr}}),
        201,
        stap="4.overstap",
    )
    log("4.overgestapt", sync=ov.get("sync"), probe_rood=[k for k, v in ov.get("probe", {}).items() if v != "ok"], projecten_aangemaakt=ov.get("projecten_aangemaakt"), projecten_overgeslagen=ov.get("projecten_overgeslagen"), hervertaling=ov.get("hervertaling"))
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
    # Blok B: het project uit de RLZ-leg (stap 2) is via de projectmapping vertaald naar het Odoo-analytic-account.
    pr_map = {r["rlz_id"]: r for r in mp.get("project", [])}
    pr_rij = pr_map.get(str(RLZ_PROJECT))
    pr_lokaal = next((o["lokaal_id"] for o in mp.get("odoo_projecten", []) if pr_rij and o["odoo_id"] == pr_rij["odoo_id"]), None)
    project_na = (na.get("project") or {}).get("waarde")
    ok_pr = pr_rij is not None and project_na == pr_lokaal
    log("5.project", rlz_project=str(RLZ_PROJECT), gemapt_naar=pr_rij and f"{pr_rij['odoo_code']} {pr_rij['odoo_naam']} (v{pr_rij['versie']}, {pr_rij['bron']})", project_na=project_na, verwacht=pr_lokaal, ok=ok_pr)
    if not ok_pr:
        raise Stop("5: geheugen-project draagt níét het gemapte Odoo-project")
    # 5b. Blok C1: open boekvoorstellen zijn hervertaald — `overstap_vertaling` per regelveld (DB-lezing, RLS-gescoopt).
    from app.db.session import scoped_session as _ss
    from app.documenten.models import BoekvoorstelRegel as _BR, Document as _Doc
    from sqlalchemy import select as _select
    with _ss(TEST_ADMIN) as _s:
        rijen = _s.execute(_select(_Doc.id, _Doc.status, _BR.overstap_vertaling).join(_BR, _BR.document_id == _Doc.id).where(_Doc.administratie_id == TEST_ADMIN, _BR.overstap_vertaling.isnot(None))).all()
    log("5b.hervertaling", regels_met_vertaling=len(rijen), voorbeeld=[{"document": str(d), "status": st.value if hasattr(st, "value") else str(st), "vertaling": v} for d, st, v in rijen[:3]])
    if ov.get("hervertaling") and ov["hervertaling"].get("regels", 0) != len(rijen):
        raise Stop(f"5b: hervertaling meldde {ov['hervertaling']['regels']} regels, DB toont {len(rijen)}")
    if args.tot_stap < 6:
        return 0

    return _stappen_6_9(c, args, mp=mp, gb_voor=gb_voor, btw_voor=btw_voor, pct_voor=pct_voor, ref_rlz=ref_rlz)


def vervolg(c: httpx.Client, args) -> int:
    """Stappen 6–9 op een administratie die stap 0–5 al doorliep (generale 04-09 18:52): mapping + RLZ-ids van de nulmeting."""
    mp = verwacht(c.get(f"/administraties/{TEST_ADMIN}/odoo/mapping"), 200, stap="6.mapping")
    gb_voor = "c1c355aa-3618-4519-ad5e-e19712e13d72"  # Action-geheugen vóór de overstap: 4104 Energiekosten (stap 1 van de run 18:52)
    btw_voor = "1e44993a-15f6-419f-87e5-3e31ac3d9383"  # NL, Hoog Tarief
    if not args.ref_rlz:
        raise Stop("vervolg: --ref-rlz (de TEST-referentie van de RLZ-leg uit stap 2) is verplicht")
    return _stappen_6_9(c, args, mp=mp, gb_voor=gb_voor, btw_voor=btw_voor, pct_voor=Decimal("0.21"), ref_rlz=args.ref_rlz)


def _stappen_6_9(c, args, *, mp, gb_voor, btw_voor, pct_voor, ref_rlz) -> int:
    odoo_lokaal = next((o["lokaal_id"] for o in mp["odoo_grootboek"] if o["odoo_id"] == {r["rlz_id"]: r for r in mp["grootboek"]}.get(gb_voor, {}).get("odoo_id")), None)
    # 6. Odoo-leg
    if getattr(args, "vanaf_stap", 0) >= 7 and args.vendor_odoo:
        vendor_odoo = uuid.UUID(args.vendor_odoo)  # stappen 6 + 7a al bewezen in een eerdere run (log 04-09 18:57)
    else:
        cred = verwacht(c.post(f"/administraties/{TEST_ADMIN}/crediteuren", json={"naam": f"TEST-GENERALE Leverancier {STAMP} (niet gebruiken)"}), 201, stap="6.crediteur")
        vendor_odoo = uuid.UUID(cred["id"])
    btw_map = {r["rlz_id"]: r for r in mp["btw"]}
    btw_rij = btw_map.get(btw_voor)
    btw_lokaal = next((t["lokaal_id"] for t in mp["odoo_btw"] if btw_rij and t["odoo_id"] == btw_rij["odoo_id"]), None)
    pct_odoo = next((Decimal(str(t["percentage"])) for t in mp["odoo_btw"] if btw_rij and t["odoo_id"] == btw_rij["odoo_id"]), pct_voor)
    if not (odoo_lokaal and btw_lokaal):
        raise Stop("6: geen gemapte rekening/btw voor de Odoo-leg")
    if getattr(args, "vanaf_stap", 0) >= 7:
        return _stappen_7_9(c, args, vendor_odoo=vendor_odoo, odoo_lokaal=odoo_lokaal, btw_lokaal=btw_lokaal, pct_odoo=pct_odoo, ref_rlz=ref_rlz)
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

    return _stappen_7_9(c, args, vendor_odoo=vendor_odoo, odoo_lokaal=odoo_lokaal, btw_lokaal=btw_lokaal, pct_odoo=pct_odoo, ref_rlz=ref_rlz)


def _stappen_7_9(c, args, *, vendor_odoo, odoo_lokaal, btw_lokaal, pct_odoo, ref_rlz) -> int:
    # 7a. Blok A: nakomer mét factuurdatum VÓÓR de kanteldatum boekt gewoon in Odoo (geen poort meer).
    if getattr(args, "vanaf_stap", 0) >= 7 and args.vendor_odoo:
        return _stappen_7b_9(c, args, vendor_odoo=vendor_odoo, odoo_lokaal=odoo_lokaal, btw_lokaal=btw_lokaal, pct_odoo=pct_odoo, ref_rlz=ref_rlz)
    ref_pre = f"TEST-GENERALE-PRE-{STAMP}"
    did_pre = upload(c, TEST_ADMIN, "test-generale-pre.pdf", ["TEST GENERALE OVERSTAP — nakomer vóór de kanteldatum", f"BTW-nummer {BTW_NUMMER}", f"Factuurnummer {ref_pre}", "Factuurdatum 20-08-2026", "Netto 10,00  BTW 2,10  Totaal 12,10"], "7a.upload")
    voorstel(c, TEST_ADMIN, did_pre, vendor=vendor_odoo, ref=ref_pre, datum="2026-08-20", gb=uuid.UUID(odoo_lokaal), btw=uuid.UUID(btw_lokaal), pct=pct_odoo, stap="7a.voorstel")
    geboekt_pre = verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_pre}/boeken", json={}), 200, stap="7a.boeken")
    detail = c.get(f"/administraties/{TEST_ADMIN}/documenten/{did_pre}").json()
    log("7a.geboekt_odoo_pre_datum", status=geboekt_pre["status"], boekstuk=geboekt_pre.get("rlz_boekstuknummer"), geboekt_in=detail.get("geboekt_in_rlz"))
    if geboekt_pre["status"] != "geboekt" or (detail.get("geboekt_in_rlz") or {}).get("backend") != "odoo":
        raise Stop("7a: nakomer vóór de kanteldatum is níét in Odoo geboekt")
    verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_pre}/tegenboeken", json={"soort": "volledig", "reden": "TEST generale — nakomer vóór de kanteldatum (blok A bewezen), opruiming via reversal"}), 200, stap="7a.tegenboeken")

    return _stappen_7b_9(c, args, vendor_odoo=vendor_odoo, odoo_lokaal=odoo_lokaal, btw_lokaal=btw_lokaal, pct_odoo=pct_odoo, ref_rlz=ref_rlz)


def _stappen_7b_9(c, args, *, vendor_odoo, odoo_lokaal, btw_lokaal, pct_odoo, ref_rlz) -> int:
    # 7b. Blok A dedup over de backend-grens: dezelfde factuur als de RLZ-leg (zelfde btw-nummer/referentie/bedrag) komt als
    # nakomer binnen op de Odoo-crediteur → duplicaatcheck rood mét het RLZ-boekstuk + automatisch afgevoerd.
    did_dup = upload(c, TEST_ADMIN, "test-generale-dup.pdf", ["TEST GENERALE OVERSTAP — nakomer die al in RLZ geboekt is", f"BTW-nummer {BTW_NUMMER}", f"Factuurnummer {ref_rlz}", "Factuurdatum 15-08-2026", "Netto 10,00  BTW 2,10  Totaal 12,10"], "7b.upload")
    out_dup = voorstel(c, TEST_ADMIN, did_dup, vendor=vendor_odoo, ref=ref_rlz, datum="2026-08-15", gb=uuid.UUID(odoo_lokaal), btw=uuid.UUID(btw_lokaal), pct=pct_odoo, stap="7b.voorstel")
    dup_check = next((r for r in out_dup.get("checks", {}).get("resultaten", []) if r["naam"] == "Duplicaatcheck"), None)
    log("7b.duplicaatcheck", check=dup_check)
    if dup_check is None or dup_check["ok"]:
        raise Stop("7b: duplicaatcheck ziet de in RLZ geboekte factuur níét (dedup over de backend-grens faalt)")
    status_dup = None
    for _ in range(15):
        d = c.get(f"/administraties/{TEST_ADMIN}/documenten/{did_dup}").json()
        status_dup = d["status"]
        if status_dup == "afgewezen":
            break
        time.sleep(1)
    log("7b.afvoer", status=status_dup, afwijzing=d.get("afwijzing"), duplicaat=d.get("duplicaat_afvoer") or d.get("duplicaatsignaal"))
    if status_dup != "afgewezen":
        raise Stop(f"7b: duplicaat is níét automatisch afgevoerd (status {status_dup})")

    # 7c. A2: nakomer mét factuurdatum in een in Odoo afgesloten periode (tax_lock_date 31-12-2025) → boekdatum lock + 1 dag.
    ref_lock = f"TEST-GENERALE-LOCK-{STAMP}"
    did_lock = upload(c, TEST_ADMIN, "test-generale-lock.pdf", ["TEST GENERALE OVERSTAP — factuurdatum in afgesloten btw-periode", f"BTW-nummer {BTW_NUMMER}", f"Factuurnummer {ref_lock}", "Factuurdatum 15-12-2025", "Netto 10,00  BTW 2,10  Totaal 12,10"], "7c.upload")
    voorstel(c, TEST_ADMIN, did_lock, vendor=vendor_odoo, ref=ref_lock, datum="2025-12-15", gb=uuid.UUID(odoo_lokaal), btw=uuid.UUID(btw_lokaal), pct=pct_odoo, stap="7c.voorstel")
    geboekt_lock = verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_lock}/boeken", json={}), 200, stap="7c.boeken")
    detail = c.get(f"/administraties/{TEST_ADMIN}/documenten/{did_lock}").json()
    gir = detail.get("geboekt_in_rlz") or {}
    log("7c.geboekt_verschoven", status=geboekt_lock["status"], boekstuk=geboekt_lock.get("rlz_boekstuknummer"), boekdatum_verschoven=gir.get("boekdatum_verschoven"), geboekt_in=gir)
    if geboekt_lock["status"] != "geboekt" or not gir.get("boekdatum_verschoven"):
        raise Stop("7c: boekdatum is níét zichtbaar verschoven")
    verwacht(c.post(f"/administraties/{TEST_ADMIN}/documenten/{did_lock}/tegenboeken", json={"soort": "volledig", "reden": "TEST generale — boekdatum-verschuiving (A2 bewezen), opruiming via reversal"}), 200, stap="7c.tegenboeken")

    # 8. Kanteldatum wijzigen = altijd 200 (A3: de 409 verviel met de poort), audit oud→nieuw; terug naar de oude datum.
    r8 = c.put(f"/administraties/{TEST_ADMIN}/odoo/overgangsdatum", json={"overgangsdatum": "2026-10-01"})
    log("8.kanteldatum_wijzigen", http=r8.status_code, body=r8.text[:300])
    if r8.status_code != 200:
        raise Stop(f"8: kanteldatum wijzigen gaf {r8.status_code} (verwacht 200 — geen poort meer)")
    verwacht(c.put(f"/administraties/{TEST_ADMIN}/odoo/overgangsdatum", json={"overgangsdatum": OVERGANG}), 200, stap="8.kanteldatum_terug")

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
