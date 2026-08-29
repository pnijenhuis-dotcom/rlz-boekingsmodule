#!/usr/bin/env python3
"""STAP 0 — Voorraad-uitstroom uit RLZ-verkoopfacturen (opdracht 29-08 blok A; voorraad fase 1
parkeerpost "RLZ-SalesInvoice-Lines, Quantity nog te verifiëren").

STRIKT READ-ONLY: uitsluitend GET's. Geen PUT/POST/Actions, geen DB-writes.

Vraag: dragen de regels van Universal Verkoop's EIGEN RLZ-verkoopfacturen (UI-/import-facturen,
géén API-documenten) een bruikbaar AANTAL-veld — veldnaam, vulling in de praktijk, eenheid,
gedrag bij creditfacturen/negatieve aantallen, nulregels?

Doel-administratie: de gekoppelde administratie "Universal Verkoop" mét voorraad-opt-in aan, via
de credential-store (cloud-DB — de voorraad-BV's zijn op 29-08 in de cloud gekoppeld, niet lokaal).

Draaien (Auth-Proxy-conventie poort 5434, patroon cloud_onboard_universal.py):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
    cd backend
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
    KMS_MASTERKEY_SLEUTEL="projects/rlz-boekhouding/locations/europe-west4/keyRings/rlz/cryptoKeys/masterkey" \
        .venv/bin/python ../verkenning/poc_voorraad_uitstroom.py [naam-fragment, default "Universal Verkoop"]

Uitvoer: verkenning/output/voorraad_uitstroom_stap0.json (gitignored) + samenvatting op stdout.
"""

from __future__ import annotations

import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

HIER = Path(__file__).resolve().parent
sys.path.insert(0, str(HIER.parent / "backend"))

from sqlalchemy import select, text  # noqa: E402

from app.db.models import Administratie  # noqa: E402
from app.db.session import scoped_session  # noqa: E402
from app.rlz.client import RlzApiError  # noqa: E402
from app.rlz.credentials import client_voor_rlz_admin_id, open_root_client  # noqa: E402
from app.security import envelope  # noqa: E402

OUTPUT = HIER / "output"
RESULTAAT = OUTPUT / "voorraad_uitstroom_stap0.json"
STEEKPROEF_KOPPEN = 80  # meest recente verkoopfacturen
STEEKPROEF_CREDIT = 15  # negatieve facturen (creditgedrag)

# Kandidaat-veldnamen voor aantal/eenheid/prijs/artikel op een regel — we tellen wat er écht staat.
AANTAL_KANDIDATEN = ("Quantity", "Amount", "Number", "Count", "Units")
EENHEID_KANDIDATEN = ("Unit", "UnitOfMeasure", "UnitName", "Measure", "UnitCode")
PRIJS_KANDIDATEN = ("UnitPrice", "Price", "PricePerUnit", "NetPrice")
ARTIKEL_KANDIDATEN = ("Article", "Product", "Item", "ArticleCode", "ProductCode", "ItemCode")


def _controleer_doel() -> None:
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        raise SystemExit("FAILSAFE: APP_DATABASE_URL niet gezet — zie docstring. Gestopt.")
    if ":5433/" in url:
        raise SystemExit("FAILSAFE: APP_DATABASE_URL wijst naar de lokale dev-DB (5433); de voorraad-BV's staan in de cloud (5434).")
    if not os.environ.get("KMS_MASTERKEY_SLEUTEL"):
        raise SystemExit("FAILSAFE: KMS_MASTERKEY_SLEUTEL niet gezet — de cloud-credential-store is alleen via KMS te ontsleutelen.")


def _kms_via_gcloud_gebruiker() -> None:
    """De credential-store-unwrap loopt via KMS met Application Default Credentials. Zijn die
    verlopen ("Reauthentication is needed"), dan gebruikt deze read-only PoC de actieve
    gcloud-GEBRUIKERStoken (zelfde identiteit als de ADC-login, `gcloud auth print-access-token`;
    de token wordt nooit geprint of opgeslagen). Alleen unwrap (decrypt) — er wordt niets gewrapt."""
    import subprocess

    from google.cloud import kms
    from google.oauth2.credentials import Credentials

    token = subprocess.run(
        ["gcloud", "auth", "print-access-token"], check=True, capture_output=True, text=True
    ).stdout.strip()
    client = kms.KeyManagementServiceClient(credentials=Credentials(token=token))
    provider = envelope.KmsMasterKeyProvider(os.environ["KMS_MASTERKEY_SLEUTEL"], client=client)
    envelope.standaard_masterkey_provider = lambda: provider  # type: ignore[assignment]


def _vind_administratie(fragment: str) -> Administratie:
    with scoped_session(None) as session:
        # Sanity: we zitten écht op de cloud-DB (er horen >15 administraties te zijn incl. de voorraad-BV's).
        aantal = session.execute(text("select count(*) from platform.administratie")).scalar_one()
        kandidaten = list(
            session.scalars(select(Administratie).where(Administratie.naam.ilike(f"%{fragment}%")))
        )
        session.expunge_all()
    if not kandidaten:
        raise SystemExit(f"Geen administratie met '{fragment}' in de naam (DB heeft {aantal} administraties).")
    if len(kandidaten) > 1:
        raise SystemExit("Meerdere treffers: " + ", ".join(f"{a.naam} ({a.id})" for a in kandidaten))
    a = kandidaten[0]
    print(f"Administratie: {a.naam} · id={a.id} · rlz_admin_id={a.rlz_admin_id} · voorraad_ingeschakeld={a.voorraad_ingeschakeld}")
    if not a.voorraad_ingeschakeld:
        print("⚠️  voorraad_ingeschakeld staat UIT op deze administratie — STAP-0 gaat door (read-only), maar noteer dit.")
    return a


def _velden(regel: dict[str, Any]) -> dict[str, Any]:
    """Gevonden kandidaat-velden mét waarde (alleen platte velden en expand-refs)."""
    uit: dict[str, Any] = {}
    for groep, kandidaten in (
        ("aantal", AANTAL_KANDIDATEN),
        ("eenheid", EENHEID_KANDIDATEN),
        ("prijs", PRIJS_KANDIDATEN),
        ("artikel", ARTIKEL_KANDIDATEN),
    ):
        for k in kandidaten:
            if k in regel:
                uit[f"{groep}:{k}"] = regel[k]
    return uit


def main() -> int:
    _controleer_doel()
    _kms_via_gcloud_gebruiker()
    fragment = sys.argv[1] if len(sys.argv) > 1 else "Universal Verkoop"
    administratie = _vind_administratie(fragment)
    rlz_admin_id = administratie.rlz_admin_id

    # Failsafe: de store-login moet deze administratie zien.
    root = open_root_client(rlz_admin_id)
    zichtbaar = [x["id"] for x in root.list_administrations()]
    if rlz_admin_id not in zichtbaar:
        raise SystemExit(f"FAILSAFE: de webservice-login ziet {zichtbaar}, niet {rlz_admin_id}. Gestopt.")
    print(f"Login ziet {len(zichtbaar)} administratie(s), incl. het doel ✓ — alles hierna is GET-only.")
    root.close()
    rlz = client_voor_rlz_admin_id(rlz_admin_id)

    rapport: dict[str, Any] = {
        "ts": datetime.now(UTC).isoformat(),
        "administratie": {"naam": administratie.naam, "rlz_admin_id": rlz_admin_id},
        "read_only": True,
    }

    # 1. Koppen: recentste facturen + negatieve (credit).
    koppen = rlz.get(
        "SalesInvoices", params={"$top": str(STEEKPROEF_KOPPEN), "$orderby": "Date desc"}
    ).get("value", [])
    credit: list[dict[str, Any]] = []
    try:
        credit = rlz.get(
            "SalesInvoices",
            params={"$top": str(STEEKPROEF_CREDIT), "$orderby": "Date desc", "$filter": "BaseInvoiceAmount lt 0"},
        ).get("value", [])
    except RlzApiError as exc:
        rapport["credit_filter_fout"] = f"{exc.status_code}: {exc.body[:200]}"
    print(f"Koppen: {len(koppen)} recentste · {len(credit)} negatieve (credit) via $filter")
    rapport["kop_velden"] = sorted(koppen[0].keys()) if koppen else []
    rapport["kop_voorbeeld"] = {
        k: koppen[0].get(k) for k in ("id", "Date", "Reference", "InvoiceNumber", "Status", "BaseInvoiceAmount", "Description")
    } if koppen else None
    statussen = Counter(k.get("Status") for k in koppen)
    rapport["kop_statussen"] = dict(statussen)

    # 2. Regels per factuur.
    regelveld_namen: Counter[str] = Counter()
    aantal_stats: dict[str, Counter[str]] = {k: Counter() for k in AANTAL_KANDIDATEN}
    eenheid_waarden: Counter[str] = Counter()
    prijs_aanwezig: Counter[str] = Counter()
    artikel_aanwezig: Counter[str] = Counter()
    voorbeelden: list[dict[str, Any]] = []
    credit_voorbeelden: list[dict[str, Any]] = []
    expand_fout: str | None = None
    totaal_regels = 0
    regels_zonder_quantity = 0
    quantity_null = 0
    quantity_nul = 0
    quantity_negatief = 0
    quantity_fractie = 0
    netto_negatief = 0
    consistentie_ok = 0
    consistentie_mis = 0
    consistentie_voorbeelden: list[dict[str, Any]] = []

    def _lees_regels(kop: dict[str, Any]) -> list[dict[str, Any]]:
        nonlocal expand_fout
        try:
            return rlz.get(f"SalesInvoices/{kop['id']}/Lines", params={"$expand": "Account,Project"}).get("value", [])
        except RlzApiError as exc:
            expand_fout = f"{exc.status_code}: {exc.body[:200]}"
            return rlz.get(f"SalesInvoices/{kop['id']}/Lines").get("value", [])

    def _verwerk(kop: dict[str, Any], regels: list[dict[str, Any]], *, is_credit: bool) -> None:
        nonlocal totaal_regels, regels_zonder_quantity, quantity_null, quantity_nul, quantity_negatief
        nonlocal quantity_fractie, netto_negatief, consistentie_ok, consistentie_mis
        for r in regels:
            totaal_regels += 1
            regelveld_namen.update(r.keys())
            if "Quantity" not in r:
                regels_zonder_quantity += 1
            q = r.get("Quantity")
            for k in AANTAL_KANDIDATEN:
                if k in r:
                    v = r[k]
                    aantal_stats[k]["null" if v is None else ("0" if v == 0 else ("neg" if isinstance(v, (int, float)) and v < 0 else "pos"))] += 1
            if q is None:
                quantity_null += 1
            elif q == 0:
                quantity_nul += 1
            elif q < 0:
                quantity_negatief += 1
            if isinstance(q, float) and q != int(q):
                quantity_fractie += 1
            for k in EENHEID_KANDIDATEN:
                if r.get(k) not in (None, ""):
                    eenheid_waarden[f"{k}={r[k]}"] += 1
            for k in PRIJS_KANDIDATEN:
                if r.get(k) is not None:
                    prijs_aanwezig[k] += 1
            for k in ARTIKEL_KANDIDATEN:
                if r.get(k) is not None:
                    artikel_aanwezig[k] += 1
            netto = r.get("NetAmount")
            if isinstance(netto, (int, float)) and netto < 0:
                netto_negatief += 1
            # Consistentie: Quantity × prijs ≈ NetAmount (welke prijsveldnaam ook)?
            prijs = next((r[k] for k in PRIJS_KANDIDATEN if isinstance(r.get(k), (int, float))), None)
            if isinstance(q, (int, float)) and prijs is not None and isinstance(netto, (int, float)) and q not in (0, None):
                if abs(q * prijs - netto) <= 0.011:
                    consistentie_ok += 1
                else:
                    consistentie_mis += 1
                    if len(consistentie_voorbeelden) < 8:
                        consistentie_voorbeelden.append(
                            {"factuur": kop.get("Reference"), "Quantity": q, "prijs": prijs, "NetAmount": netto, "Description": r.get("Description")}
                        )
            doel = credit_voorbeelden if is_credit else voorbeelden
            if len(doel) < 12:
                doel.append(
                    {
                        "factuur": kop.get("Reference"),
                        "datum": kop.get("Date"),
                        "BaseInvoiceAmount": kop.get("BaseInvoiceAmount"),
                        "Description": r.get("Description"),
                        "NetAmount": netto,
                        "TaxAmount": r.get("TaxAmount"),
                        "Account": (r.get("Account") or {}).get("Number") if isinstance(r.get("Account"), dict) else r.get("Account"),
                        **_velden(r),
                    }
                )

    gezien: set[str] = set()
    for kop in koppen:
        gezien.add(kop["id"])
        _verwerk(kop, _lees_regels(kop), is_credit=False)
    for kop in credit:
        if kop["id"] in gezien:
            continue
        _verwerk(kop, _lees_regels(kop), is_credit=True)

    # 3. Aanvullende expand-probe: bestaat een Article-/Product-referentie op de regel?
    artikel_expand: dict[str, str] = {}
    if koppen:
        for naam in ("Article", "Product", "Item"):
            try:
                rlz.get(f"SalesInvoices/{koppen[0]['id']}/Lines", params={"$expand": naam, "$top": "1"})
                artikel_expand[naam] = "expand geaccepteerd"
            except RlzApiError as exc:
                artikel_expand[naam] = f"{exc.status_code}"

    # 3b. Paging-/filter-/expand-probe voor de leesroute-motor (alle GET-only, $top klein).
    paging: dict[str, Any] = {}
    for naam, params in (
        ("count", {"$top": "1", "$count": "true"}),
        # DateTimeOffset-literal vereist een tijdzone-suffix ('Z'); Status is een enum-type
        # (Reeleezee.DTO.DocumentStatus) — een kale Int32 geeft 400 (eerste probe-ronde).
        ("filter_date_ge", {"$top": "1", "$count": "true", "$filter": "Date ge 2026-01-01T00:00:00Z"}),
        ("filter_date_ge_2026_08", {"$top": "1", "$count": "true", "$filter": "Date ge 2026-08-01T00:00:00Z"}),
        ("filter_status_enum", {"$top": "1", "$count": "true", "$filter": "Status ne Reeleezee.DTO.DocumentStatus'Tentative'"}),
        ("filter_status_enum_num", {"$top": "1", "$count": "true", "$filter": "Status ne Reeleezee.DTO.DocumentStatus'1'"}),
        ("filter_credit", {"$top": "1", "$count": "true", "$filter": "IsCreditInvoice eq true"}),
        ("filter_bookdate_ge", {"$top": "1", "$count": "true", "$filter": "BookDate ge 2026-08-01T00:00:00Z"}),
        ("date_asc_skip", {"$top": "200", "$skip": "200", "$orderby": "Date asc,id asc", "$filter": "Date ge 2026-01-01T00:00:00Z", "$select": "id,Date,Status"}),
        ("skip_top", {"$top": "5", "$skip": "50", "$orderby": "Date desc"}),
        ("expand_entity", {"$top": "2", "$expand": "Entity"}),
        ("select_kop", {"$top": "2", "$select": "id,Date,BookDate,Status,IsCreditInvoice,InvoiceNumber,Reference"}),
    ):
        try:
            antwoord = rlz.get("SalesInvoices", params=params)
            waarde = antwoord.get("value", [])
            paging[naam] = {
                "status": "ok",
                "odata_count": antwoord.get("@odata.count"),
                "n": len(waarde),
                "voorbeeld": (
                    {k: (waarde[0].get(k) if k != "Entity" else (waarde[0].get("Entity") or {}).get("Name") if isinstance(waarde[0].get("Entity"), dict) else waarde[0].get("Entity"))
                     for k in ("id", "Date", "BookDate", "Status", "IsCreditInvoice", "InvoiceNumber", "Reference", "Entity")}
                    if waarde else None
                ),
                "nextLink": antwoord.get("@odata.nextLink"),
            }
        except RlzApiError as exc:
            paging[naam] = {"status": f"{exc.status_code}", "body": exc.body[:160]}
    rapport["paging_probe"] = paging
    print("paging/filter/expand-probe:", json.dumps(paging, indent=1, default=str)[:3000])

    # 4. Metadata-probe (OData $metadata) — welke properties kent het regel-type?
    metadata_regeltype: list[str] | None = None
    try:
        xml = rlz.request_raw("GET", "$metadata", headers={"Accept": "application/xml"}).text
        import re

        m = re.search(r'<EntityType Name="(?:Sales)?(?:Invoice)?(?:Document)?Line"[^>]*>(.*?)</EntityType>', xml, re.S)
        if m:
            metadata_regeltype = re.findall(r'<Property Name="([^"]+)"', m.group(1))
        else:
            typen = re.findall(r'<EntityType Name="([^"]*Line[^"]*)"', xml)
            metadata_regeltype = [f"(geen exacte match; Line-typen: {', '.join(typen[:20])})"]
    except Exception as exc:  # noqa: BLE001 — probe, mag falen
        metadata_regeltype = [f"metadata niet leesbaar: {str(exc)[:120]}"]

    rapport.update(
        {
            "facturen_gelezen": len(gezien) + len([c for c in credit if c["id"] not in gezien]),
            "regels_totaal": totaal_regels,
            "regel_veldnamen": dict(regelveld_namen),
            "expand_Account_Project_fout": expand_fout,
            "aantal_veld_stats": {k: dict(v) for k, v in aantal_stats.items() if v},
            "quantity": {
                "regels_zonder_veld": regels_zonder_quantity,
                "null": quantity_null,
                "nul": quantity_nul,
                "negatief": quantity_negatief,
                "fractie": quantity_fractie,
            },
            "netto_negatief": netto_negatief,
            "eenheid_waarden": dict(eenheid_waarden.most_common(30)),
            "prijs_veld_aanwezig": dict(prijs_aanwezig),
            "artikel_veld_aanwezig": dict(artikel_aanwezig),
            "artikel_expand_probe": artikel_expand,
            "consistentie_quantity_x_prijs_vs_netto": {
                "ok": consistentie_ok,
                "mis": consistentie_mis,
                "voorbeelden_mis": consistentie_voorbeelden,
            },
            "metadata_regeltype_properties": metadata_regeltype,
            "voorbeelden": voorbeelden,
            "credit_voorbeelden": credit_voorbeelden,
        }
    )
    OUTPUT.mkdir(exist_ok=True)
    RESULTAAT.write_text(json.dumps(rapport, indent=2, default=str, ensure_ascii=False))
    rlz.close()

    print("\n=== SAMENVATTING ===")
    print(f"facturen gelezen: {rapport['facturen_gelezen']} · regels: {totaal_regels}")
    print(f"regel-veldnamen: {sorted(regelveld_namen)}")
    print(f"Quantity: {rapport['quantity']}")
    print(f"aantal-veld-stats: {rapport['aantal_veld_stats']}")
    print(f"eenheid-waarden: {rapport['eenheid_waarden']}")
    print(f"prijsveld aanwezig: {dict(prijs_aanwezig)} · artikelveld aanwezig: {dict(artikel_aanwezig)} · expand-probe: {artikel_expand}")
    print(f"consistentie Quantity×prijs≈NetAmount: ok={consistentie_ok} mis={consistentie_mis}")
    print(f"netto negatief: {netto_negatief} · credit-koppen: {len(credit)}")
    print(f"metadata regeltype: {metadata_regeltype}")
    print(f"\nVolledig rapport: {RESULTAAT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
