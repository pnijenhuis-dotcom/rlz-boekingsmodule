"""Verbindings- en rechten-probe voor een Odoo-koppeling (besluit 0016 §5: zichtbaar vóór opslaan, nooit
pas bij de eerste boekactie). Zelfde rapportvorm als de RLZ-probe (`{onderdeel: "ok" | reden}`) zodat de
wizard-UI 'm 1-op-1 kan tonen. Uitsluitend leesacties.

Onderdelen:
- `verbinding`      versie bereikbaar (Odoo 19+e) — anders alles rood;
- `company`         het company-id bestaat én staat in `company_ids` van de API-gebruiker;
- `lezen:<model>`   has_access read op de modellen die de adapter leest;
- `schrijven:<model>` has_access create+write op de modellen die de adapter schrijft (account.move,
                    account.move.line, ir.attachment, res.partner, account.analytic.account, product.product);
- `dagboek:inkoop`/`dagboek:memoriaal`/`dagboek:verkoop`  precies één dagboek van dat type in de company
                    (anders benoemen — de motor raadt nooit);
- `btw:inkoop`      ≥ 1 actieve inkoop-btw-code (percent) in de company;
- `analytic_plan`   precies één analytic-plan "Project" (projecten per regel);
- `lock_dates`      informatief: de actuele lock dates (boekdatums daarvóór worden geweigerd);
- `digitalisering`  waarschuwing als `extract_in_invoice_digitalization_mode = auto_send` (OCR maakt dan
                    concepten naast de onze — klikpunt K2), ok bij `no_send`/`manual_send`;
- `api_key`         de sleutels van de API-gebruiker mét vervaldatum (Odoo: max 3 maanden — rotatie-klikpunt);
                    'ok' als er ≥ 1 sleutel is die nog ≥ 14 dagen geldig is of geen vervaldatum heeft.
Groen = alle harde onderdelen ok; `lock_dates`/`digitalisering`/`api_key` zijn informatief/waarschuwend."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from typing import Any

from app.odoo.client import OdooClient, OdooFout

LEES_MODELLEN = (
    "res.company",
    "account.account",
    "account.tax",
    "account.journal",
    "res.partner",
    "account.analytic.plan",
    "account.analytic.account",
    "account.move",
    "account.move.line",
    "ir.attachment",
    "product.product",
    "product.category",
)
SCHRIJF_MODELLEN = (
    "account.move",
    "account.move.line",
    "ir.attachment",
    "res.partner",
    "account.analytic.account",
    "product.product",
)
INFORMATIEF = frozenset({"lock_dates", "digitalisering", "api_key", "verkoopfacturen"})


@dataclass(frozen=True)
class ProbeUitkomst:
    rapport: dict[str, str]
    company_naam: str | None = None
    journal_purchase_id: int | None = None
    journal_general_id: int | None = None
    journal_sale_id: int | None = None
    analytic_plan_id: int | None = None
    lock_dates: dict[str, str | None] = field(default_factory=dict)
    api_key_verloopt_op: date | None = None
    versie: str | None = None

    @property
    def groen(self) -> bool:
        return bool(self.rapport) and all(v == "ok" for k, v in self.rapport.items() if k not in INFORMATIEF)

    def rode_regels(self) -> str:
        return ", ".join(f"{k}: {v}" for k, v in self.rapport.items() if v != "ok" and k not in INFORMATIEF)


def _datum(waarde: Any) -> date | None:
    if not waarde:
        return None
    try:
        return date.fromisoformat(str(waarde)[:10])
    except ValueError:
        return None


def _een_dagboek(client: OdooClient, soort: str, rapport: dict[str, str], sleutel: str) -> int | None:
    rijen = client.search_read(
        "account.journal", [["company_id", "=", client.company_id], ["type", "=", soort]], ["id", "code", "name"]
    )
    if len(rijen) == 1:
        rapport[sleutel] = "ok"
        return int(rijen[0]["id"])
    if not rijen:
        rapport[sleutel] = f"geen {soort}-dagboek in deze company — maak er één aan in Odoo"
        return None
    codes = ", ".join(str(r["code"]) for r in rijen)
    rapport[sleutel] = f"{len(rijen)} {soort}-dagboeken ({codes}) — de koppeling vereist er precies één"
    return None


def voer_probe_uit(client: OdooClient) -> ProbeUitkomst:
    rapport: dict[str, str] = {}
    try:
        versie = str(client.versie().get("server_version") or "")
        rapport["verbinding"] = "ok"
    except Exception as exc:  # noqa: BLE001 — zichtbaar in het rapport, nooit een crash
        return ProbeUitkomst(rapport={"verbinding": f"niet bereikbaar: {type(exc).__name__}"})

    company_naam: str | None = None
    lock_dates: dict[str, str | None] = {}
    try:
        company = client.read_een(
            "res.company",
            client.company_id,
            [
                "name",
                "fiscalyear_lock_date",
                "tax_lock_date",
                "purchase_lock_date",
                "hard_lock_date",
                "extract_in_invoice_digitalization_mode",
            ],
        )
    except OdooFout as exc:
        company = None
        rapport["company"] = f"company {client.company_id} niet leesbaar ({exc.status} {exc.naam or ''})".strip()
    if company is None:
        rapport.setdefault(
            "company", f"company {client.company_id} bestaat niet of is niet zichtbaar voor deze API-key"
        )
    else:
        company_naam = str(company.get("name") or "")
        # De read liep mét context allowed_company_ids=[company]: staat de company niet in de Allowed
        # Companies van de API-gebruiker, dan weigert Odoo de call (AccessError) — hierboven al rood.
        rapport["company"] = "ok"
        lock_dates = {
            k: (str(company.get(k)) if company.get(k) else None)
            for k in ("fiscalyear_lock_date", "tax_lock_date", "purchase_lock_date", "hard_lock_date")
        }
        gezet = ", ".join(f"{k}={v}" for k, v in lock_dates.items() if v)
        rapport["lock_dates"] = "ok (geen lock dates)" if not gezet else f"let op: {gezet}"
        modus = company.get("extract_in_invoice_digitalization_mode")
        rapport["digitalisering"] = (
            "ok"
            if modus in ("no_send", "manual_send", False, None)
            else f"waarschuwing: OCR staat op {modus} — Odoo maakt dan zelf concepten naast onze boekingen (K2)"
        )

    for model in LEES_MODELLEN:
        rapport[f"lezen:{model}"] = "ok" if client.has_access(model, "read") else "geen leesrecht"
    for model in SCHRIJF_MODELLEN:
        ok = client.has_access(model, "create") and client.has_access(model, "write")
        rapport[f"schrijven:{model}"] = "ok" if ok else "geen aanmaak-/schrijfrecht"

    journal_purchase_id = journal_general_id = journal_sale_id = None
    if rapport.get("lezen:account.journal") == "ok":
        journal_purchase_id = _een_dagboek(client, "purchase", rapport, "dagboek:inkoop")
        # Memoriaal: company 1 heeft méér general-dagboeken (MISC, STJ, EXCH, CABA, TAX) — kies op code MISC,
        # anders benoemen. Verkoop: precies één sale-dagboek verwacht.
        misc = client.search_read(
            "account.journal",
            [["company_id", "=", client.company_id], ["type", "=", "general"], ["code", "=", "MISC"]],
            ["id"],
        )
        if len(misc) == 1:
            journal_general_id = int(misc[0]["id"])
            rapport["dagboek:memoriaal"] = "ok"
        else:
            rapport["dagboek:memoriaal"] = "geen general-dagboek met code MISC — benoem het memoriaal-dagboek in Odoo"
        journal_sale_id = _een_dagboek(client, "sale", rapport, "dagboek:verkoop")

    if rapport.get("lezen:account.tax") == "ok":
        n = client.search_count(
            "account.tax",
            [
                ["company_id", "=", client.company_id],
                ["type_tax_use", "=", "purchase"],
                ["active", "=", True],
                ["amount_type", "=", "percent"],
            ],
        )
        rapport["btw:inkoop"] = "ok" if n else "geen actieve inkoop-btw-codes in deze company"

    analytic_plan_id = None
    if rapport.get("lezen:account.analytic.plan") == "ok":
        plannen = client.search_read("account.analytic.plan", [["name", "=", "Project"]], ["id", "name"])
        if len(plannen) == 1:
            analytic_plan_id = int(plannen[0]["id"])
            rapport["analytic_plan"] = "ok"
        else:
            rapport["analytic_plan"] = (
                f"{len(plannen)} analytic-plannen met naam 'Project' — precies één verwacht (projecten per regel)"
            )

    api_key_verloopt_op: date | None = None
    try:
        sleutels = client.search_read("res.users.apikeys", [], ["name", "expiration_date"])
        vervaldata = [_datum(s.get("expiration_date")) for s in sleutels]
        geldig = [d for d in vervaldata if d is None or (d - date.today()).days >= 14]
        if not sleutels:
            rapport["api_key"] = "geen API-keys zichtbaar voor deze gebruiker"
        elif geldig:
            rapport["api_key"] = "ok"
        else:
            rapport["api_key"] = "waarschuwing: alle API-keys verlopen binnen 14 dagen — roteer de sleutel (klikpunt)"
        gedateerd = sorted(d for d in vervaldata if d is not None)
        # De vroegst verlopende gedateerde sleutel is de conservatieve vervaldatum voor de bewaking.
        api_key_verloopt_op = gedateerd[0] if gedateerd and None not in vervaldata else None
    except OdooFout as exc:
        rapport["api_key"] = f"vervaldatum niet leesbaar ({exc.status})"

    return ProbeUitkomst(
        rapport=rapport,
        company_naam=company_naam,
        journal_purchase_id=journal_purchase_id,
        journal_general_id=journal_general_id,
        journal_sale_id=journal_sale_id,
        analytic_plan_id=analytic_plan_id,
        lock_dates=lock_dates,
        api_key_verloopt_op=api_key_verloopt_op,
        versie=versie,
    )


LEESBRON_MODELLEN = ("res.company", "account.move", "account.move.line", "product.product", "res.partner")


def voer_leesprobe_uit(client: OdooClient) -> ProbeUitkomst:
    """Probe voor een ALLEEN-LEZEN-koppeling (blok D: Odoo = leesbron voor de voorraad-uitstroom): verbinding,
    company en leesrecht op de modellen die de leesroute raakt — géén schrijfrechten, géén dagboeken (er wordt
    nooit geboekt). Informatief: het aantal geposte verkoopfacturen dat de company draagt."""
    rapport: dict[str, str] = {}
    try:
        versie = str(client.versie().get("server_version") or "")
        rapport["verbinding"] = "ok"
    except Exception as exc:  # noqa: BLE001
        return ProbeUitkomst(rapport={"verbinding": f"niet bereikbaar: {type(exc).__name__}"})
    company_naam: str | None = None
    try:
        company = client.read_een("res.company", client.company_id, ["name"])
    except OdooFout as exc:
        company = None
        rapport["company"] = f"company {client.company_id} niet leesbaar ({exc.status} {exc.naam or ''})".strip()
    if company is None:
        rapport.setdefault(
            "company", f"company {client.company_id} bestaat niet of is niet zichtbaar voor deze API-key"
        )
    else:
        company_naam = str(company.get("name") or "")
        rapport["company"] = "ok"
    for model in LEESBRON_MODELLEN:
        rapport[f"lezen:{model}"] = "ok" if client.has_access(model, "read") else "geen leesrecht"
    if rapport.get("lezen:account.move") == "ok":
        try:
            n = client.search_count(
                "account.move",
                [["company_id", "=", client.company_id], ["move_type", "=", "out_invoice"], ["state", "=", "posted"]],
            )
            rapport["verkoopfacturen"] = f"ok ({n} geposte verkoopfacturen)"
        except OdooFout as exc:
            rapport["verkoopfacturen"] = f"niet telbaar ({exc.status})"
    return ProbeUitkomst(rapport=rapport, company_naam=company_naam, versie=versie)


def lees_lock_dates(client: OdooClient) -> dict[str, date | None]:
    """Vóór élke boeking vers gelezen (STAP-0 §3.5): {veld: datum|None}."""
    rij = client.read_een(
        "res.company",
        client.company_id,
        ["fiscalyear_lock_date", "tax_lock_date", "purchase_lock_date", "hard_lock_date"],
    )
    if rij is None:
        raise OdooFout(
            404, "MissingCompany", f"company {client.company_id} niet leesbaar", model="res.company", methode="read"
        )
    velden = ("fiscalyear_lock_date", "tax_lock_date", "purchase_lock_date", "hard_lock_date")
    return {k: _datum(rij.get(k)) for k in velden}


def lees_companies(client: OdooClient) -> list[dict[str, Any]]:
    """Alle companies die de API-gebruiker ziet — voor de wizard-keuzelijst (nooit een id typen)."""
    rijen = client.search_read("res.company", [], ["id", "name"], order="id")
    return [{"id": int(r["id"]), "naam": str(r["name"])} for r in rijen]
