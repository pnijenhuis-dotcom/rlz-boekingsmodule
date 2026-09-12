"""CLI `vgg-rekeningen` (run 2 VGG → Odoo, blok 4): RJ-220-rollen op de Odoo-doelcompany.

    python -m app.cli vgg-rekeningen --administratie "<naam of UUID>" [--company-id 6] [--json-uit pad]
    python -m app.cli vgg-rekeningen --administratie … --maak-aan        # WRITE — alleen ná akkoord Peter op de nummers

Default LEES-ONLY: leest de bestaande rekeningen van de company (read-only client) en print de voorstel-tabel
(rol | bestaand | voorstel code | naam | account_type | reden) + de huidige waarden in de koppeling-rij. `--maak-aan`
maakt de rekeningen + analytic "Overhead" aan en werkt de koppeling-rij bij — weigert zichtbaar als de kill-switch
`migratie_odoo_writes_ingeschakeld` UIT staat, als er geen koppeling-rij is of als die geen migratiedoel is.
`scripts/gcp/nameting.sh` laat alleen de lees-only vorm door (weigert `--maak-aan`)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from collections.abc import Callable
from pathlib import Path
from typing import Any

from app.odoo.rj220 import ROLLEN, RolFout, RolRekeningen, RolVoorstel

VGG_REKENINGEN_COMMANDO = "vgg-rekeningen"


def register_vgg_rekeningen(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        VGG_REKENINGEN_COMMANDO,
        help=(
            "RJ-220-rollen (voorraad panden, vooruitbetaald op voorraad, opbrengst verkoop panden, kostprijs verkochte "
            "panden + analytic Overhead) op de Odoo-doelcompany: default lees-only voorstel; --maak-aan maakt aan "
            "(kill-switch migratie_odoo_writes_ingeschakeld)."
        ),
    )
    p.add_argument("--administratie", required=True, help="UUID of (deel van de) naam van de administratie.")
    p.add_argument(
        "--company-id",
        dest="company_id",
        type=int,
        default=None,
        help="Odoo-company als er nog geen koppeling-rij is (alleen lees-only, dev met ODOO_URL/ODOO_API_KEY).",
    )
    p.add_argument("--maak-aan", dest="maak_aan", action="store_true", help="Rekeningen + Overhead aanmaken (WRITE).")
    p.add_argument("--json-uit", dest="json_uit", default=None, help="Pad voor het JSON-rapport.")


def _client_en_company(
    administratie_id: uuid.UUID, *, company_arg: int | None, schrijvend: bool
) -> tuple[Any, int, int | None, str | None]:
    """(client, company_id, analytic_plan_id, weigerreden). Store-first: koppeling-rij → URL + key; zonder rij alleen
    lees-only in dev via `lees_dev_env()` + --company-id. Schrijvend vereist een migratiedoel-rij (of backend odoo)."""
    from app.config import settings
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.odoo.client import OdooClient
    from app.odoo.credentials import lees_dev_env
    from app.odoo.models import OdooKoppeling
    from app.security.envelope import unwrap_secret

    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        rij = session.get(OdooKoppeling, administratie_id)
        backend = administratie.boekhoud_backend if administratie is not None else None
        if rij is not None:
            url, company, plan = rij.odoo_url, int(rij.company_id), rij.analytic_plan_id
            key = (
                unwrap_secret(rij.api_key_ciphertext, rij.wrapped_data_key).decode() if rij.api_key_ciphertext else None
            )
            migratie_doel = bool(rij.migratie_doel)
        else:
            url = key = None
            company = plan = None
            migratie_doel = False
    if rij is None:
        if schrijvend:
            return None, 0, None, "geen odoo_koppeling-rij — maak 'm eerst aan met odoo-koppeling-migratiedoel"
        if settings.environment != "dev":
            return None, 0, None, "geen odoo_koppeling-rij voor deze administratie (buiten dev geen terugval)"
        url, key = lees_dev_env()
        if not url or not key:
            return None, 0, None, "geen ODOO_URL/ODOO_API_KEY in de dev-omgeving"
        if company_arg is None:
            return None, 0, None, "geen koppeling-rij: geef --company-id mee (lees-only)"
        company = int(company_arg)
    elif company_arg is not None and int(company_arg) != company:
        return (
            None,
            0,
            None,
            f"--company-id {company_arg} ≠ company {company} uit de koppeling-rij — geweigerd (company-pin)",
        )
    if schrijvend and backend != "odoo" and not migratie_doel:
        return (
            None,
            0,
            None,
            "koppeling-rij is geen migratiedoel (migratie_doel=False) en de administratie draait op RLZ — geweigerd",
        )
    if not key or not url:
        return None, 0, None, "geen Odoo-API-key voor deze administratie"
    if settings.environment == "dev" and not key:
        _, key = lees_dev_env()
    assert company is not None
    client = OdooClient(url=url, api_key=key, company_id=company, read_only=not schrijvend)
    return client, company, plan, None


def tabel(voorstellen: list[RolVoorstel], huidig: RolRekeningen) -> str:
    regels = [
        "| rol | bestaand (id · code) | voorstel code | naam | account_type | reden |",
        "|---|---|---|---|---|---|",
    ]
    for v in voorstellen:
        bestaand = f"{v.bestaand_odoo_id} · {v.bestaand_code}" if v.bestaand_odoo_id is not None else "—"
        code = v.voorstel_code or "— (kies handmatig)"
        regels.append(f"| {v.rol} | {bestaand} | {code} | {v.voorstel_naam} | {v.account_type} | {v.reden} |")
    regels.append("")
    regels.append("Huidige koppeling-rij (0138):")
    for rol in ROLLEN:
        regels.append(
            f"  {rol}: {getattr(huidig, rol) if getattr(huidig, rol) is not None else '— (niet vastgesteld)'}"
        )
    overhead = huidig.analytic_overhead if huidig.analytic_overhead is not None else "— (niet vastgesteld)"
    regels.append(f"  analytic_overhead: {overhead}")
    return "\n".join(regels)


def run_vgg_rekeningen(
    args: argparse.Namespace,
    *,
    zoek: Callable[[str], tuple[uuid.UUID, str, str] | None] | None = None,
    client_factory: Callable[[uuid.UUID, int | None, bool], tuple[Any, int, int | None, str | None]] | None = None,
    uit: Any = None,
) -> int:
    from app.odoo import rj220

    uit = uit or sys.stdout
    zoek = zoek or _zoek_administratie
    gevonden = zoek(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam, _ = gevonden
    maak_aan = bool(getattr(args, "maak_aan", False))
    factory = client_factory or (
        lambda aid, comp, schrijvend: _client_en_company(aid, company_arg=comp, schrijvend=schrijvend)
    )
    client, company_id, plan_id, weigering = factory(administratie_id, getattr(args, "company_id", None), maak_aan)
    if weigering:
        print(f"FOUT  {weigering}", file=sys.stderr)
        return 2
    try:
        voorstellen = rj220.stel_rollen_voor(client, company_id=company_id)
        huidig = rj220.rollen_voor(administratie_id)
        modus = "AANMAKEN" if maak_aan else "lees-only voorstel"
        print(f"# RJ-220-rollen — {naam} → Odoo company {company_id} ({modus})", file=uit)
        print(tabel(voorstellen, huidig), file=uit)
        rapport: dict[str, Any] = {
            "administratie_id": str(administratie_id),
            "company_id": company_id,
            "voorstellen": [v.__dict__ for v in voorstellen],
            "huidig": huidig.als_dict(),
            "maak_aan": maak_aan,
        }
        if maak_aan:
            from app.db.systeem_actor import SYSTEEM_ACTOR_ID

            try:
                uitkomst = rj220.maak_rollen_aan(
                    client,
                    company_id=company_id,
                    voorstellen=voorstellen,
                    actor_id=SYSTEEM_ACTOR_ID,
                    administratie_id=administratie_id,
                    analytic_plan_id=plan_id,
                )
            except RolFout as exc:
                print(f"FOUT  {exc}", file=sys.stderr)
                return 1
            rapport["uitkomst"] = uitkomst.als_dict()
            print("", file=uit)
            print("Aangemaakt/vastgesteld (koppeling-rij bijgewerkt, audit odoo_rj220_rollen_vastgesteld):", file=uit)
            for rol, odoo_id in uitkomst.als_dict().items():
                print(f"  {rol}: {odoo_id}", file=uit)
        if args.json_uit:
            Path(args.json_uit).write_text(json.dumps(rapport, indent=1, default=str), encoding="utf-8")
            print(f"JSON geschreven: {args.json_uit}", file=uit)
        return 0
    finally:
        if hasattr(client, "close"):
            client.close()


def _zoek_administratie(tekst: str) -> tuple[uuid.UUID, str, str] | None:
    from app.migratie.cli_cmd import zoek_administratie

    return zoek_administratie(tekst)
