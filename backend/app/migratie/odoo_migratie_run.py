"""`vgg-odoo-migratie` — de volledige replay in ÉÉN run: concepten → toets → posten (aanvulling Peter 17-09 op de
vijfde-meting-opdracht: "waarom alles in concept? Liever 1 boeking testen en als het goed gaat alles meteen definitief
boeken (anders alsnog handmatig werk)"). Herziet het besluit 12-09 "alles concept": de toets blijft VÓÓR het onomkeerbare
moment zitten, maar er is geen klikwerk meer — BESLISSINGEN "VGG — CONCEPT → AUTO-POSTEN NÁ GROENE TOETS (Peter 17-09)".

Fasen (elke fase meldt zichzelf; een rode fase stopt de volgende):
  A. concepten — partners (zoek-vóór-create, besluit 12-09 punt 3), élk VERTAALBAAR document als concept-move
     (`maak_concept_move`: idempotent op het anker, dus een herhaalde run maakt niets dubbel), élke vertaalbare bankregel
     als statement line (`maak_statement_line`, idempotent op `unique_import_id`). Documenten zonder partner-voorstel of
     mét blokkade worden overgeslagen en genoemd (besluit 14-09: geen dummy-partner).
  B. toets — per geschreven concept worden de regels UIT ODOO teruggelezen: Σ debet = Σ credit (cent-exact) én — voor
     facturen — de debiteuren-/crediteurenregel = Σ factuurregels uit de replay-vals (cent-exact); aantal geschreven
     concepten = aantal vertaalbare documenten; per pand "sluit" uit het replay-rapport (GO-eis SCHRIJF c, blok 7d
     punt 5). Eén afwijking = ROOD.
  C. posten — alleen bij GROEN: `action_post` in batches op álle concepten van deze run, daarna élke move terug-gelezen
     (`state == 'posted'`); één move die niet post = ROOD mét de rest ongemoeid (wat al gepost is blijft gepost — nooit
     terugdraaien zonder mens, besluit 0021-lijn).
  D. reconcile — ná het posten: elke statement line waarvan de replay (PaymentReferenceList) het document kent, via de
     route-registry (`reconcile`, routes i → ii → iii). Een mislukte reconcile is een RESTPUNT (open bankregel), geen
     ROOD: de boeking zelf is dan al juist.
ROOD in B = concepten blijven staan (zichtbaar in Odoo als draft), niets gepost, rapport zegt letterlijk welke toets faalde.
Kill-switch: `--schrijf` én MIGRATIE_ODOO_WRITES_INGESCHAKELD=true (`eis_writes_aan` in élke primitief); default dry-run
toont alleen de plan-tellers. Nooit via nameting.sh (schrijvend commando, geweigerd)."""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.migratie.odoo_doel import CompanyGepindeClient, CompanyPinGeschonden, GeenMigratieDoel
from app.odoo.client import OdooFout

MIGRATIE_COMMANDO = "vgg-odoo-migratie"
POST_BATCH = 50
CENT = Decimal("0.01")
DOCUMENT_TYPES = frozenset({"in_invoice", "in_refund", "out_invoice", "out_refund", "entry"})
FACTUUR_TYPES = frozenset({"in_invoice", "in_refund", "out_invoice", "out_refund"})


@dataclass
class Fase:
    naam: str
    uitgevoerd: bool = False
    groen: bool | None = None
    regels: list[str] = field(default_factory=list)
    tellers: dict[str, int] = field(default_factory=dict)

    @property
    def oordeel(self) -> str:
        if not self.uitgevoerd:
            return "niet uitgevoerd"
        return "GROEN" if self.groen else "ROOD"


@dataclass
class MigratieRapport:
    administratie_naam: str
    company_id: int | None
    schrijf: bool
    fasen: dict[str, Fase]
    meldingen: list[str] = field(default_factory=list)
    move_ids: dict[str, int] = field(default_factory=dict)  # anker → move-id
    statement_line_ids: dict[str, int] = field(default_factory=dict)  # anker → id
    gepost: list[int] = field(default_factory=list)
    stand: dict[str, Any] = field(default_factory=dict)

    @property
    def oordeel(self) -> str:
        if not self.schrijf:
            return "DRY-RUN"
        if any(f.uitgevoerd and f.groen is False for f in self.fasen.values() if f.naam != "D. reconcile"):
            return "ROOD"
        return "GROEN" if self.fasen["C. posten"].uitgevoerd else "GROEN — niet gepost"

    def als_markdown(self) -> str:
        modus = f"SCHRIJF (company {self.company_id})" if self.schrijf else "DRY-RUN — geen Odoo-writes"
        r = [f"# vgg-odoo-migratie — {self.administratie_naam} — {modus}", "", f"**Oordeel: {self.oordeel}**", ""]
        r.extend(f"- {m}" for m in self.meldingen)
        if self.meldingen:
            r.append("")
        r.extend(["| Fase | Oordeel | Tellers | Detail (eerste 40) |", "|---|---|---|---|"])
        for f in self.fasen.values():
            tellers = ", ".join(f"{k} {v}" for k, v in f.tellers.items()) or "—"
            detail = "<br>".join(f.regels[:40]) + (f"<br>… en {len(f.regels) - 40} meer" if len(f.regels) > 40 else "")
            r.append(f"| {f.naam} | **{f.oordeel}** | {tellers} | {detail or '—'} |")
        if self.stand:
            r.extend(["", "**Stand in de doelcompany ná deze run:**", ""])
            r.extend(f"- {k}: {v}" for k, v in self.stand.items())
        return "\n".join(r)


def _dec(waarde: Any) -> Decimal:
    try:
        return Decimal(str(waarde if waarde is not None else 0)).quantize(CENT)
    except Exception:  # noqa: BLE001 — een onleesbaar bedrag is 0,00 mét zichtbare regelsom-afwijking
        return Decimal("0.00")


def _m2o(waarde: Any) -> int | None:
    if isinstance(waarde, (list, tuple)) and waarde:
        return int(waarde[0])
    return int(waarde) if isinstance(waarde, int) else None


def verwachte_factuursom(vals: dict[str, Any]) -> Decimal:
    """Σ factuurregels uit de replay-vals (Odoo-commands `[0, 0, {...}]` óf kale dicts): quantity × price_unit, cent-exact —
    de debiteuren-/crediteurenregel die Odoo zelf aanmaakt moet hier tegenover staan (VGG is niet btw-plichtig, besluit
    13-09: geen tax_ids, dus geen btw-verschil)."""
    som = Decimal("0.00")
    for item in vals.get("invoice_line_ids") or []:
        regel = item[2] if isinstance(item, (list, tuple)) and len(item) == 3 and isinstance(item[2], dict) else item
        if not isinstance(regel, dict):
            continue
        aantal = _dec(regel.get("quantity", 1)) if regel.get("quantity") is not None else Decimal("1.00")
        som += (aantal * _dec(regel.get("price_unit"))).quantize(CENT)
    return som.quantize(CENT)


def toets_move(move_type: str, vals: dict[str, Any], odoo_regels: Sequence[dict[str, Any]]) -> list[str]:
    """Cent-exacte toets op de regels zoals ODOO ze heeft: Σ debet = Σ credit; bij een factuur de tegenzijde
    (receivable/payable) = Σ factuurregels uit de vals. Geeft de afwijkingen (leeg = groen)."""
    fouten: list[str] = []
    if not odoo_regels:
        return ["geen regels in Odoo terug te lezen"]
    debet = sum((_dec(r.get("debit")) for r in odoo_regels), Decimal("0.00"))
    credit = sum((_dec(r.get("credit")) for r in odoo_regels), Decimal("0.00"))
    if debet != credit:
        fouten.append(f"Σ debet {debet} ≠ Σ credit {credit}")
    if move_type in FACTUUR_TYPES:
        tegen = [
            r for r in odoo_regels if (r.get("account_type") or "") in ("asset_receivable", "liability_payable")
        ]
        if len(tegen) != 1:
            fouten.append(f"{len(tegen)} debiteuren-/crediteurenregels (verwacht 1)")
        else:
            bedrag = abs(_dec(tegen[0].get("debit")) - _dec(tegen[0].get("credit")))
            verwacht = abs(verwachte_factuursom(vals))
            if bedrag != verwacht:
                fouten.append(f"tegenzijde {bedrag} ≠ Σ factuurregels {verwacht}")
    return fouten


def per_pand_sluit(per_pand: Iterable[dict[str, Any]]) -> list[str]:
    """GO-eis SCHRIJF c (blok 7d punt 5): élk verkocht pand 'sluit' (of 'sluit ná aanbetalingen'); niet-verkocht = geen eis."""
    fouten: list[str] = []
    for rij in per_pand:
        controle = str(rij.get("controle") or "")
        if controle.startswith("sluit") or controle.startswith("— (niet verkocht)"):
            continue
        fouten.append(f"pand {rij.get('pand') or rij.get('adres') or rij.get('cluster') or '?'}: {controle or 'geen controle'}")
    return fouten


def _reconcile_ankers(m: Any) -> list[str]:
    from app.migratie.cli_odoo import reconcile_ankers  # noqa: PLC0415

    return reconcile_ankers(m)


def voer_migratie_uit(
    administratie_id: uuid.UUID,
    *,
    administratie_naam: str,
    schrijf: bool,
    client_factory: Callable[[uuid.UUID], CompanyGepindeClient],
    replay_module: Any | None,
    audit: Any,
    writes_aan: bool,
    posten: bool = True,
) -> MigratieRapport:
    from app.migratie import odoo_schrijf  # noqa: PLC0415

    fasen = {
        naam: Fase(naam) for naam in ("A. concepten", "B. toets", "C. posten", "D. reconcile")
    }
    rapport = MigratieRapport(administratie_naam=administratie_naam, company_id=None, schrijf=schrijf, fasen=fasen)
    if replay_module is None or not hasattr(replay_module, "dry_run"):
        rapport.meldingen.append("replay-motor niet beschikbaar — niets gedaan")
        return rapport
    if schrijf and not writes_aan:
        rapport.meldingen.append(
            "--schrijf gevraagd maar de kill-switch staat UIT (MIGRATIE_ODOO_WRITES_INGESCHAKELD) — teruggevallen op dry-run"
        )
        schrijf = False
        rapport.schrijf = False
    try:
        client = client_factory(administratie_id)
    except GeenMigratieDoel as exc:
        rapport.meldingen.append(f"geen migratiedoel: {exc}")
        return rapport
    rapport.company_id = client.pin
    replay_rapport = replay_module.dry_run(administratie_id)
    moves = list(getattr(replay_rapport, "moves", []))
    per_pand = list(getattr(replay_rapport, "per_pand", []) or [])
    blokkering = getattr(replay_rapport, "blokkering", None)
    if blokkering:
        rapport.meldingen.append(f"replay geblokkeerd ({blokkering}) — niets geschreven")
        return rapport
    documenten = [m for m in moves if m.move_type in DOCUMENT_TYPES and m.status == "vertaalbaar"]
    bankregels = [m for m in moves if m.move_type in ("bank",) and m.status == "vertaalbaar"]
    rapport.meldingen.append(
        f"replay: {len(moves)} moves — {len(documenten)} vertaalbare documenten, {len(bankregels)} bankregels, "
        f"{sum(1 for m in moves if m.status != 'vertaalbaar' and m.move_type in DOCUMENT_TYPES)} niet vertaalbaar (blijven buiten)"
    )
    schrijf_fouten: tuple[type[Exception], ...] = (
        OdooFout,
        CompanyPinGeschonden,
        odoo_schrijf.AnkerMeerduidig,
        odoo_schrijf.ConceptNietDraft,
        odoo_schrijf.NietEenConcept,
        odoo_schrijf.PartnerMeerduidig,
        odoo_schrijf.PartnerOnbekend,
    )
    # pand-eis vóór het schrijven: rood = geen concept-berg (Peter: geen handwerk achteraf)
    pand_fouten = per_pand_sluit(per_pand)
    if not schrijf:
        a = fasen["A. concepten"]
        a.tellers = {"documenten": len(documenten), "bankregels": len(bankregels), "zonder partner": sum(1 for m in documenten if m.move_type != "entry" and not m.partner)}
        a.regels.append("ZOU: partners zoek-vóór-create, concepten + statement lines (idempotent op anker)")
        b = fasen["B. toets"]
        b.tellers = {"pand-eis afwijkingen": len(pand_fouten)}
        b.regels.extend(pand_fouten[:20] or ["per pand: alle verkochte panden sluiten (replay)"])
        fasen["C. posten"].regels.append("ZOU: action_post op álle concepten van deze run als B GROEN is")
        fasen["D. reconcile"].regels.append("ZOU: statement lines ↔ documenten via PaymentReferenceList (routes i → ii → iii)")
        return rapport

    with client:
        # ---- A. concepten ----
        a = fasen["A. concepten"]
        a.uitgevoerd, a.groen = True, True
        partner_per_anker: dict[str, int] = {}
        overgeslagen = 0
        for m in documenten:
            if m.move_type == "entry":
                continue
            voorstel = dict(m.partner) if isinstance(m.partner, dict) else None
            if voorstel is None:
                overgeslagen += 1
                a.regels.append(f"{m.boekstuk}: geen partner-voorstel — overgeslagen (Toewijzing)")
                continue
            try:
                uit = odoo_schrijf.zoek_of_maak_partner(client, voorstel, audit=audit)
                partner_per_anker[str(m.anker)] = uit.partner_id
            except schrijf_fouten as exc:
                overgeslagen += 1
                a.regels.append(f"{m.boekstuk}: partner FOUT {exc} — overgeslagen")
        geschreven_moves: dict[str, Any] = {}
        for m in documenten:
            vals = dict(m.vals)
            if m.move_type != "entry":
                pid = partner_per_anker.get(str(m.anker))
                if not pid:
                    continue
                vals["partner_id"] = pid
            try:
                move_id = odoo_schrijf.maak_concept_move(client, vals, anker=str(m.anker), audit=audit)
                rapport.move_ids[str(m.anker)] = move_id
                geschreven_moves[str(m.anker)] = m
            except schrijf_fouten as exc:
                a.groen = False
                a.regels.append(f"{m.boekstuk}: concept FOUT {exc}")
        for m in bankregels:
            try:
                rapport.statement_line_ids[str(m.anker)] = odoo_schrijf.maak_statement_line(
                    client, dict(m.vals), anker=str(m.anker), audit=audit
                )
            except schrijf_fouten as exc:
                a.groen = False
                a.regels.append(f"bankregel {m.boekstuk}: statement line FOUT {exc}")
        a.tellers = {
            "concepten": len(rapport.move_ids),
            "statement lines": len(rapport.statement_line_ids),
            "overgeslagen (partner)": overgeslagen,
            "verwacht": len(documenten),
        }
        # ---- B. toets ----
        b = fasen["B. toets"]
        b.uitgevoerd, b.groen = True, a.groen
        afwijkingen = 0
        if len(rapport.move_ids) + overgeslagen != len(documenten):
            b.groen = False
            b.regels.append(f"aantal concepten {len(rapport.move_ids)} + overgeslagen {overgeslagen} ≠ documenten {len(documenten)}")
        for anker, move_id in rapport.move_ids.items():
            m = geschreven_moves[anker]
            try:
                regels = client.search_read(
                    odoo_schrijf.MODEL_MOVE_LINE,
                    [["move_id", "=", move_id], ["company_id", "=", client.pin]],
                    ["id", "debit", "credit", "account_id", "account_type"],
                )
            except OdooFout as exc:
                regels = []
                b.regels.append(f"{m.boekstuk} (move {move_id}): regels niet leesbaar — {exc}")
            fouten = toets_move(m.move_type, m.vals, regels)
            if fouten:
                afwijkingen += 1
                b.groen = False
                b.regels.append(f"{m.boekstuk} (move {move_id}): " + "; ".join(fouten))
        if pand_fouten:
            b.groen = False
            b.regels.extend(pand_fouten[:20])
        b.tellers = {"getoetst": len(rapport.move_ids), "afwijkingen": afwijkingen, "pand-eis afwijkingen": len(pand_fouten)}
        # ---- C. posten ----
        c = fasen["C. posten"]
        if not b.groen:
            c.regels.append("NIET gepost: toets ROOD — concepten blijven staan (draft) voor de mens; zie fase B")
        elif not posten:
            c.regels.append("NIET gepost: --geen-posten gevraagd — concepten blijven staan")
        else:
            c.uitgevoerd, c.groen = True, True
            ids = sorted(rapport.move_ids.values())
            for i in range(0, len(ids), POST_BATCH):
                batch = ids[i : i + POST_BATCH]
                try:
                    client.call(odoo_schrijf.MODEL_MOVE, "action_post", ids=batch)
                except OdooFout as exc:
                    c.groen = False
                    c.regels.append(f"action_post batch {batch[0]}–{batch[-1]} FOUT: {exc}")
                    continue
                na = client.read(odoo_schrijf.MODEL_MOVE, batch, ["id", "state", "name"])
                for rij in na:
                    if rij.get("state") == "posted":
                        rapport.gepost.append(int(rij["id"]))
                    else:
                        c.groen = False
                        c.regels.append(f"move {rij.get('id')} staat ná action_post op {rij.get('state')!r}")
            audit.leg_vast(
                "odoo_migratie_bulk_gepost",
                nieuwe_waarde={"company": client.pin, "gepost": len(rapport.gepost), "verwacht": len(ids)},
            )
            c.tellers = {"gepost": len(rapport.gepost), "verwacht": len(ids)}
        # ---- D. reconcile ----
        d = fasen["D. reconcile"]
        if c.uitgevoerd and c.groen:
            d.uitgevoerd, d.groen = True, True
            gelukt = mislukt = zonder = 0
            for m in bankregels:
                stl_id = rapport.statement_line_ids.get(str(m.anker))
                doelen = [rapport.move_ids[a_] for a_ in _reconcile_ankers(m) if a_ in rapport.move_ids]
                if stl_id is None or not doelen:
                    zonder += 1
                    continue
                for move_id in doelen:
                    try:
                        regels = client.search_read(
                            odoo_schrijf.MODEL_MOVE_LINE,
                            [["move_id", "=", move_id], ["company_id", "=", client.pin], ["account_id.account_type", "in", ["asset_receivable", "liability_payable"]]],
                            ["id", "account_id", "partner_id"],
                        )
                        if len(regels) != 1:
                            mislukt += 1
                            d.regels.append(f"bankregel {m.boekstuk} ↔ move {move_id}: {len(regels)} tegenzijde-regels — open gelaten")
                            continue
                        uit = odoo_schrijf.reconcile(
                            client,
                            statement_line_id=stl_id,
                            audit=audit,
                            move_line_ids=[int(regels[0]["id"])],
                            tegenrekening_id=_m2o(regels[0].get("account_id")),
                            partner_id=_m2o(regels[0].get("partner_id")),
                        )
                        if uit.geslaagd and uit.is_reconciled:
                            gelukt += 1
                        else:
                            mislukt += 1
                            d.regels.append(f"bankregel {m.boekstuk} ↔ move {move_id}: geen route werkte — open gelaten (restpunt)")
                    except schrijf_fouten as exc:
                        mislukt += 1
                        d.regels.append(f"bankregel {m.boekstuk} ↔ move {move_id}: FOUT {exc} — open gelaten")
            d.tellers = {"gereconcilieerd": gelukt, "open (restpunt)": mislukt, "zonder koppeling": zonder}
            d.groen = mislukt == 0
        else:
            d.regels.append("niet uitgevoerd: alleen ná groen posten")
        try:
            rapport.stand["account.move op de company (posted)"] = client.search_count(
                odoo_schrijf.MODEL_MOVE, [["company_id", "=", client.pin], ["state", "=", "posted"]]
            )
            rapport.stand["account.move op de company (draft)"] = client.search_count(
                odoo_schrijf.MODEL_MOVE, [["company_id", "=", client.pin], ["state", "=", "draft"]]
            )
        except OdooFout as exc:
            rapport.stand["nameting"] = f"niet leesbaar: {exc}"
    return rapport


def register_odoo_migratie_run(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    p = subparsers.add_parser(
        MIGRATIE_COMMANDO,
        help=(
            "SCHRIJVEND (Odoo, alleen mét --schrijf én MIGRATIE_ODOO_WRITES_INGESCHAKELD=true): volledige replay in één run — "
            "concepten → cent-exacte toets (Odoo-regels + per pand sluit) → automatisch posten (bulk action_post) → reconcile; "
            "rood = niets gepost, concepten blijven staan. Default --dry-run."
        ),
    )
    p.add_argument("--administratie", required=True, help="UUID of naam(deel) van de administratie (VGG).")
    p.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Alleen tonen (default).")
    p.add_argument("--schrijf", dest="dry_run", action="store_false", help="Echte writes (vereist de kill-switch AAN).")
    p.add_argument(
        "--geen-posten", dest="geen_posten", action="store_true", default=False, help="Alleen concepten + toets, niet posten."
    )


def run_odoo_migratie_run(args: argparse.Namespace) -> int:
    from app.config import settings  # noqa: PLC0415
    from app.migratie.cli_cmd import zoek_administratie  # noqa: PLC0415
    from app.migratie.cli_odoo import _laad_replay  # noqa: PLC0415
    from app.migratie.odoo_doel import doelclient_voor  # noqa: PLC0415
    from app.migratie.odoo_schrijf import DbAudit, GeheugenAudit  # noqa: PLC0415
    from app.migratie.uitvoer import print_gedoseerd  # noqa: PLC0415

    gevonden = zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam, _ = gevonden
    schrijf = not args.dry_run
    rapport = voer_migratie_uit(
        administratie_id,
        administratie_naam=naam,
        schrijf=schrijf,
        client_factory=lambda aid: doelclient_voor(aid, read_only=not schrijf),
        replay_module=_laad_replay(),
        audit=DbAudit(administratie_id) if schrijf else GeheugenAudit(),
        writes_aan=bool(settings.migratie_odoo_writes_ingeschakeld),
        posten=not args.geen_posten,
    )
    print_gedoseerd(rapport.als_markdown())
    if rapport.company_id is None:
        return 2
    return 0 if rapport.oordeel != "ROOD" else 1
