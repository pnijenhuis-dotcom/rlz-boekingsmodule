"""CLI's `odoo-koppeling-migratiedoel` en `vgg-odoo-stap0` (run 2 VGG blok 5) — SCHRIJVENDE commando's.

Productie-regel Peter 08-09: uitsluitend op de gedeployde job-image, op expliciete opdracht van Peter:
  gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait \
    --args="^|^-m|app.cli|odoo-koppeling-migratiedoel|--administratie|<VGG>|--bron-administratie|<Universal>|--company|6"
  gcloud run jobs execute rlz-reconciliatie --region europe-west4 --wait \
    --update-env-vars MIGRATIE_ODOO_WRITES_INGESCHAKELD=true \
    --args="^|^-m|app.cli|vgg-odoo-stap0|--administratie|<VGG>|--schrijf"
`scripts/gcp/nameting.sh` weigert beide hard (geen nameting). Default van beide = `--dry-run`: alles wordt geprint,
niets geschreven — geen DB-rij, geen Odoo-call met schrijfmethode. Odoo-LEZEN in de dry-run gebeurt wél (probe van de
dagboeken), altijd met een read-only client.
"""

from __future__ import annotations

import argparse
import sys
import uuid
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import UTC, date, datetime
from typing import Any

from sqlalchemy import text

from app.db.audit import record_audit_event
from app.db.models import Administratie
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.migratie.cli_cmd import zoek_administratie
from app.migratie.odoo_doel import (
    PROBE_SLEUTEL_BANKDAGBOEK,
    CompanyGepindeClient,
    CompanyPinGeschonden,
    GeenMigratieDoel,
)
from app.odoo.client import OdooClient, OdooFout
from app.odoo.models import OdooKoppeling
from app.security.envelope import unwrap_secret, wrap_secret

MIGRATIEDOEL_COMMANDO = "odoo-koppeling-migratiedoel"
STAP0_COMMANDO = "vgg-odoo-stap0"
ODOO_MIGRATIE_COMMANDOS = frozenset({MIGRATIEDOEL_COMMANDO, STAP0_COMMANDO})

#: Maand van de bewijscyclus op echte data (besluit Peter 12-09: de eerste `--max-per-type` vertaalbare documenten
#: van juli 2025).
STAP0_JAAR_MAAND = (2025, 7)


# =====================================================================================================================
# a. odoo-koppeling-migratiedoel
# =====================================================================================================================


class MigratiedoelFout(Exception):
    """Zichtbare weigering (verkeerde backend, bestaande koppeling zonder --bijwerken, bron zonder key, probe rood)."""


@dataclass(frozen=True)
class DagboekProbe:
    """Lees-only uitkomst van de dagboek-/plan-lezing op de doelcompany — nooit hardgecodeerd."""

    company_naam: str | None
    journal_sale_id: int | None
    journal_purchase_id: int | None
    journal_general_id: int | None
    journal_bank_id: int | None
    analytic_plan_id: int | None
    rapport: dict[str, str]

    @property
    def groen(self) -> bool:
        return all(
            v is not None
            for v in (
                self.journal_sale_id,
                self.journal_purchase_id,
                self.journal_general_id,
                self.journal_bank_id,
                self.analytic_plan_id,
            )
        )


def _een_dagboek(
    rijen: Iterable[dict[str, Any]], soort: str, rapport: dict[str, str], *, voorkeur_codes: Sequence[str] = ()
) -> int | None:
    kandidaten = [r for r in rijen if r.get("type") == soort]
    if len(kandidaten) == 1:
        rapport[f"dagboek:{soort}"] = f"ok ({kandidaten[0].get('code')} id {kandidaten[0]['id']})"
        return int(kandidaten[0]["id"])
    if not kandidaten:
        rapport[f"dagboek:{soort}"] = f"geen {soort}-dagboek in deze company"
        return None
    for code in voorkeur_codes:
        treffers = [r for r in kandidaten if str(r.get("code") or "").upper() == code]
        if len(treffers) == 1:
            rapport[f"dagboek:{soort}"] = (
                f"ok ({code} id {treffers[0]['id']}; {len(kandidaten)} {soort}-dagboeken, gekozen op code)"
            )
            return int(treffers[0]["id"])
    codes = ", ".join(str(r.get("code")) for r in kandidaten)
    rapport[f"dagboek:{soort}"] = f"{len(kandidaten)} {soort}-dagboeken ({codes}) — meerduidig, niet gekozen"
    return None


def lees_dagboeken(client: OdooClient) -> DagboekProbe:
    """Directe `account.journal`-/`account.analytic.plan`-/`res.company`-lezing op de company van de client (read-only).
    Company 6 heeft méér general-dagboeken (MEM, EXCH, CABA, TAX, STJ) → memoriaal op code MEM (company 1: MISC)."""
    rapport: dict[str, str] = {}
    rijen = client.search_read(
        "account.journal", [["company_id", "=", client.company_id]], ["id", "code", "name", "type"], order="id"
    )
    sale = _een_dagboek(rijen, "sale", rapport)
    purchase = _een_dagboek(rijen, "purchase", rapport)
    general = _een_dagboek(rijen, "general", rapport, voorkeur_codes=("MEM", "MISC"))
    bank = _een_dagboek(rijen, "bank", rapport)
    plannen = client.search_read("account.analytic.plan", [["name", "=", "Project"]], ["id", "name"])
    plan = int(plannen[0]["id"]) if len(plannen) == 1 else None
    rapport["analytic_plan"] = "ok" if plan is not None else f"{len(plannen)} plannen 'Project' — precies één verwacht"
    bedrijf = client.read_een("res.company", client.company_id, ["name"]) or {}
    naam = bedrijf.get("name") or None
    rapport["company"] = f"ok ({naam})" if naam else "company niet leesbaar"
    return DagboekProbe(
        company_naam=naam,
        journal_sale_id=sale,
        journal_purchase_id=purchase,
        journal_general_id=general,
        journal_bank_id=bank,
        analytic_plan_id=plan,
        rapport=rapport,
    )


@dataclass(frozen=True)
class MigratiedoelUitkomst:
    doel_id: uuid.UUID
    doel_naam: str
    bron_id: uuid.UUID
    bron_naam: str
    company_id: int
    odoo_url: str
    probe: DagboekProbe
    geschreven: bool
    bijgewerkt: bool

    def als_markdown(self) -> str:
        r = [
            f"# Migratiedoel Odoo company {self.company_id} voor {self.doel_naam}",
            "",
            f"- doel-administratie: `{self.doel_id}` ({self.doel_naam}, backend rlz)",
            f"- bron-koppeling: `{self.bron_id}` ({self.bron_naam}) — URL `{self.odoo_url}`, API-key gekopieerd "
            "(unwrap → wrap; nooit getoond)",
            f"- company: {self.company_id} ({self.probe.company_naam or '?'})",
            "",
            "| Onderdeel | Uitkomst |",
            "|---|---|",
        ]
        r.extend(f"| {k} | {v} |" for k, v in sorted(self.probe.rapport.items()))
        r.append("")
        stand = "GESCHREVEN" if self.geschreven else "DRY-RUN — niets geschreven"
        if self.geschreven and self.bijgewerkt:
            stand += " (bestaande koppeling bijgewerkt)"
        r.append(f"**{stand}** — probe {'groen' if self.probe.groen else 'ROOD (niet opgeslagen)'}")
        return "\n".join(r)


def _bron_key_en_url(bron_id: uuid.UUID, *, unwrap: Callable[[bytes, bytes], bytes]) -> tuple[str, str, str | None]:
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(OdooKoppeling, bron_id)
        if rij is None or not rij.api_key_ciphertext:
            raise MigratiedoelFout("bron-administratie heeft geen Odoo-koppeling mét API-key")
        return unwrap(rij.api_key_ciphertext, rij.wrapped_data_key).decode(), rij.odoo_url, rij.api_gebruiker


def maak_migratiedoel(
    *,
    doel_id: uuid.UUID,
    bron_id: uuid.UUID,
    company_id: int,
    dry_run: bool,
    bijwerken: bool = False,
    probe: Callable[[OdooClient], DagboekProbe] = lees_dagboeken,
    client_factory: Callable[..., OdooClient] = OdooClient,
    wrap: Callable[[bytes], tuple[bytes, bytes]] = wrap_secret,
    unwrap: Callable[[bytes, bytes], bytes] = unwrap_secret,
) -> MigratiedoelUitkomst:
    if int(company_id) <= 0:
        raise MigratiedoelFout("--company moet > 0 zijn")
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        doel = session.get(Administratie, doel_id)
        bron = session.get(Administratie, bron_id)
        if doel is None or bron is None:
            raise MigratiedoelFout("doel- of bron-administratie onbekend")
        if doel.boekhoud_backend == "odoo":
            raise MigratiedoelFout(
                f"{doel.naam} draait al op Odoo — een migratiedoel is alleen voor een RLZ-administratie vóór de "
                "kanteling"
            )
        bestaande = session.get(OdooKoppeling, doel_id)
        if bestaande is not None and not bijwerken:
            raise MigratiedoelFout(
                f"{doel.naam} heeft al een Odoo-koppeling (company {bestaande.company_id}) — gebruik --bijwerken om "
                "'m te vervangen"
            )
        doel_naam, bron_naam = doel.naam, bron.naam
        bestaat = bestaande is not None
    api_key, odoo_url, api_gebruiker = _bron_key_en_url(bron_id, unwrap=unwrap)
    with client_factory(url=odoo_url, api_key=api_key, company_id=int(company_id), read_only=True) as client:
        uitkomst_probe = probe(client)
    uitkomst = MigratiedoelUitkomst(
        doel_id=doel_id,
        doel_naam=doel_naam,
        bron_id=bron_id,
        bron_naam=bron_naam,
        company_id=int(company_id),
        odoo_url=odoo_url,
        probe=uitkomst_probe,
        geschreven=False,
        bijgewerkt=bestaat,
    )
    if dry_run:
        return uitkomst
    if not uitkomst_probe.groen:
        raise MigratiedoelFout(f"dagboek-probe niet groen — niets opgeslagen: {uitkomst_probe.rapport}")
    ciphertext, wrapped = wrap(api_key.encode())
    probe_rapport = {**uitkomst_probe.rapport, PROBE_SLEUTEL_BANKDAGBOEK: str(uitkomst_probe.journal_bank_id)}
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rij = session.get(OdooKoppeling, doel_id)
        oud: dict[str, Any] | None = None
        if rij is None:
            rij = OdooKoppeling(
                administratie_id=doel_id,
                odoo_url=odoo_url,
                company_id=int(company_id),
                api_key_ciphertext=ciphertext,
                wrapped_data_key=wrapped,
                aangemaakt_door=SYSTEEM_ACTOR_ID,
            )
            session.add(rij)
        else:
            oud = {"company_id": rij.company_id, "odoo_url": rij.odoo_url, "alleen_lezen": rij.alleen_lezen}
            rij.odoo_url = odoo_url
            rij.company_id = int(company_id)
            rij.api_key_ciphertext, rij.wrapped_data_key = ciphertext, wrapped
        rij.company_naam = uitkomst_probe.company_naam
        rij.api_gebruiker = api_gebruiker
        rij.journal_sale_id = uitkomst_probe.journal_sale_id
        rij.journal_purchase_id = uitkomst_probe.journal_purchase_id
        rij.journal_general_id = uitkomst_probe.journal_general_id
        rij.analytic_plan_id = uitkomst_probe.analytic_plan_id
        rij.probe_rapport = probe_rapport
        rij.probe_op = datetime.now(UTC)
        rij.alleen_lezen = False
        session.flush()
        if hasattr(rij, "migratie_doel"):
            rij.migratie_doel = True
        else:  # blok 4 (C) heeft het ORM-attribuut nog niet; de kolom (0138) is er wél
            session.execute(
                text("UPDATE platform.odoo_koppeling SET migratie_doel = true WHERE administratie_id = :id"),
                {"id": doel_id},
            )
        record_audit_event(
            session,
            actor_id=SYSTEEM_ACTOR_ID,
            module="platform",
            tabel="odoo_koppeling",
            record_id=doel_id,
            actie="odoo_koppeling_migratiedoel_aangemaakt",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde={
                "odoo_url": odoo_url,
                "company_id": int(company_id),
                "company_naam": uitkomst_probe.company_naam,
                "bron_administratie_id": str(bron_id),
                "migratie_doel": True,
                "journal_sale_id": uitkomst_probe.journal_sale_id,
                "journal_purchase_id": uitkomst_probe.journal_purchase_id,
                "journal_general_id": uitkomst_probe.journal_general_id,
                "journal_bank_id": uitkomst_probe.journal_bank_id,
                "analytic_plan_id": uitkomst_probe.analytic_plan_id,
            },
        )
    return replace(uitkomst, geschreven=True)


# =====================================================================================================================
# b. vgg-odoo-stap0
# =====================================================================================================================

STAP_NAMEN = {
    1: "in_invoice-concepten (notaris/verkoper, voorraad-/vooruitbetaald-regels + analytic)",
    2: "entry-concepten (memoriaal met analytic)",
    3: "out_invoice-concepten (notaris, tax-vrij)",
    4: "statement lines eerste bankdag (fase 1 bank — alleen ná groen 1–3)",
    5: "reconcile één echt paar factuur ↔ bankregel (eerste werkende route)",
    6: "terugweg: button_cancel op één concept + koppel_los op de reconcile",
}
_TYPE_PER_STAP = {1: "in_invoice", 2: "entry", 3: "out_invoice"}


@dataclass
class StapUitkomst:
    stap: int
    naam: str
    uitgevoerd: bool = False
    werkt: bool | None = None
    regels: list[str] = field(default_factory=list)
    odoo_ids: list[int] = field(default_factory=list)

    @property
    def oordeel(self) -> str:
        if not self.uitgevoerd:
            return "niet uitgevoerd"
        return "ja" if self.werkt else "nee"


@dataclass
class Stap0Rapport:
    administratie_naam: str
    company_id: int | None
    schrijf: bool
    stappen: dict[int, StapUitkomst]
    meldingen: list[str] = field(default_factory=list)
    replay_beschikbaar: bool = True

    def als_markdown(self) -> str:
        modus = f"SCHRIJF (concepten op company {self.company_id})" if self.schrijf else "DRY-RUN — geen Odoo-writes"
        r = [f"# vgg-odoo-stap0 — {self.administratie_naam} — {modus}", ""]
        r.extend(f"- {m}" for m in self.meldingen)
        if self.meldingen:
            r.append("")
        r.extend(["| # | Stap | Werkt op company %s | Detail |" % (self.company_id or "?"), "|---|---|---|---|"])
        for n in sorted(self.stappen):
            s = self.stappen[n]
            detail = "<br>".join(s.regels) if s.regels else "—"
            r.append(f"| {n} | {s.naam} | **{s.oordeel}** | {detail} |")
        return "\n".join(r)


def _in_maand(datum: Any, jaar_maand: tuple[int, int]) -> bool:
    if isinstance(datum, str):
        try:
            datum = date.fromisoformat(datum[:10])
        except ValueError:
            return False
    return isinstance(datum, date) and (datum.year, datum.month) == jaar_maand


def _laad_replay() -> Any | None:
    """Lazy import van agent E's motor; None = "E nog niet klaar" (ImportError/AttributeError, zichtbaar gemeld)."""
    import importlib

    try:
        # importlib i.p.v. `from app.migratie import replay`: die vorm leest een al geladen submodule als package-
        # attribuut en geeft dan geen ImportError meer (suite-volgorde), import_module wel.
        replay = importlib.import_module("app.migratie.replay")
    except ImportError:
        return None
    if not hasattr(replay, "dry_run"):
        return None
    return replay


def selecteer_moves(
    moves: Sequence[Any], *, max_per_type: int, jaar_maand: tuple[int, int] = STAP0_JAAR_MAAND
) -> dict[str, list[Any]]:
    """Eerste `max_per_type` VERTAALBARE documenten per type uit de opgegeven maand; bankregels apart onder 'bank'
    (alleen de EERSTE bankdag). Stabiele volgorde op datum, dan anker."""
    per_type: dict[str, list[Any]] = {"in_invoice": [], "entry": [], "out_invoice": [], "bank": []}
    kandidaten = [
        m
        for m in moves
        if getattr(m, "status", None) == "vertaalbaar" and _in_maand(getattr(m, "date", None), jaar_maand)
    ]
    kandidaten.sort(key=lambda m: str(getattr(m, "date", "")))  # stabiel: replay-volgorde binnen een dag blijft
    for m in kandidaten:
        if is_bankregel(m):
            per_type["bank"].append(m)
        else:
            soort = getattr(m, "move_type", None)
            if soort in per_type and len(per_type[soort]) < max_per_type:
                per_type[soort].append(m)
    if per_type["bank"]:
        eerste_dag = str(getattr(per_type["bank"][0], "date", ""))[:10]
        per_type["bank"] = [m for m in per_type["bank"] if str(getattr(m, "date", ""))[:10] == eerste_dag]
    return per_type


BANK_MOVE_TYPES = frozenset({"bank", "bank_direct"})


def is_bankregel(m: Any) -> bool:
    """E's vorm (vertaling.py): een bankregel is een `MoveVoorstel` met `move_type` 'bank'/'bank_direct'; `vals` = de
    statement-line-vals, `bank` = het extra blok (`tegenregel`, `reconcile` = lijst van {anker, boekstuk, move_type,
    bedrag})."""
    return getattr(m, "move_type", None) in BANK_MOVE_TYPES or bool(getattr(m, "bank", None))


def reconcile_ankers(m: Any) -> list[str]:
    """Document-ankers waartegen deze bankregel volgens de replay afgeletterd is (PaymentReferenceList)."""
    blok = getattr(m, "bank", None) or {}
    ankers: list[str] = []
    for item in blok.get("reconcile") or []:
        anker = item.get("anker") if isinstance(item, dict) else item
        if anker:
            ankers.append(str(anker))
    for sleutel in ("reconcile_paar", "reconcile_anker"):  # tolerant voor een lijst- of stringvorm
        waarde = blok.get(sleutel)
        if isinstance(waarde, (list, tuple)):
            ankers.extend(str(a) for a in waarde if a)
        elif waarde:
            ankers.append(str(waarde))
    return ankers


def voer_stap0_uit(
    administratie_id: uuid.UUID,
    *,
    administratie_naam: str,
    schrijf: bool,
    stappen: Iterable[int],
    max_per_type: int,
    client_factory: Callable[[uuid.UUID], CompanyGepindeClient],
    replay_module: Any | None,
    audit: Any,
    writes_aan: bool,
) -> Stap0Rapport:
    """De bewijscyclus. `schrijf=False` = print wat er zou gebeuren. Elke stap meldt 'werkt op company 6: ja/nee/niet
    uitgevoerd'. Stap 4 alleen ná groen 1–3; stap 5 alleen ná groen 4; stap 6 alleen als er iets is om terug te
    draaien."""
    from app.migratie import odoo_schrijf  # noqa: PLC0415

    gekozen = set(stappen)
    rapport = Stap0Rapport(
        administratie_naam=administratie_naam,
        company_id=None,
        schrijf=schrijf,
        stappen={n: StapUitkomst(stap=n, naam=STAP_NAMEN[n]) for n in sorted(gekozen)},
    )
    if replay_module is None:
        rapport.replay_beschikbaar = False
        rapport.meldingen.append(
            "agent E's motor `app.migratie.replay.dry_run` is nog niet beschikbaar — geen documenten; alle stappen "
            "niet uitgevoerd"
        )
        return rapport
    if schrijf and not writes_aan:
        rapport.meldingen.append(
            "--schrijf gevraagd maar de kill-switch staat UIT (MIGRATIE_ODOO_WRITES_INGESCHAKELD) — teruggevallen op "
            "dry-run"
        )
        schrijf = False
        rapport.schrijf = False

    try:
        client = client_factory(administratie_id)
    except GeenMigratieDoel as exc:
        rapport.meldingen.append(f"geen migratiedoel: {exc}")
        return rapport
    rapport.company_id = client.pin

    try:
        replay_rapport = replay_module.dry_run(administratie_id)
        moves = list(getattr(replay_rapport, "moves", []))
    except (AttributeError, TypeError) as exc:
        rapport.replay_beschikbaar = False
        rapport.meldingen.append(
            f"replay.dry_run past nog niet op het contract ({exc.__class__.__name__}: {exc}) — E nog niet klaar"
        )
        return rapport
    selectie = selecteer_moves(moves, max_per_type=max_per_type)
    rapport.meldingen.append(
        f"replay: {len(moves)} moves, selectie juli 2025: in_invoice {len(selectie['in_invoice'])} · "
        f"entry {len(selectie['entry'])} · out_invoice {len(selectie['out_invoice'])} · bank {len(selectie['bank'])} "
        "(eerste bankdag)"
    )

    with client:
        aangemaakt_moves: list[int] = []
        # --- stappen 1–3: concepten ---
        for n in (1, 2, 3):
            if n not in gekozen:
                continue
            s = rapport.stappen[n]
            kandidaten = selectie[_TYPE_PER_STAP[n]]
            if not kandidaten:
                s.regels.append("geen vertaalbaar document van dit type in juli 2025")
                continue
            if not schrijf:
                for m in kandidaten:
                    n_regels = len(m.vals.get("invoice_line_ids") or m.vals.get("line_ids") or [])
                    s.regels.append(f"ZOU aanmaken: {m.boekstuk} (rlz {m.rlz_id}) anker {m.anker} — {n_regels} regels")
                continue
            s.uitgevoerd = True
            s.werkt = True
            for m in kandidaten:
                vals = dict(m.vals)
                omschr = f"{m.boekstuk} (rlz {m.rlz_id}) anker {m.anker}"
                try:
                    move_id = odoo_schrijf.maak_concept_move(client, vals, anker=str(m.anker), audit=audit)
                    s.odoo_ids.append(move_id)
                    aangemaakt_moves.append(move_id)
                    s.regels.append(f"concept {move_id}: {omschr}")
                except (
                    OdooFout,
                    CompanyPinGeschonden,
                    odoo_schrijf.AnkerMeerduidig,
                    odoo_schrijf.ConceptNietDraft,
                ) as exc:
                    s.werkt = False
                    s.regels.append(f"FOUT {omschr}: {exc}")
        groen_1_3 = all(rapport.stappen[n].werkt for n in (1, 2, 3) if n in gekozen and rapport.stappen[n].uitgevoerd)

        # --- stap 4: statement lines ---
        stl_ids: list[int] = []
        paar: tuple[int, Any] | None = None  # (statement_line_id, MoveVoorstel bank)
        if 4 in gekozen:
            s = rapport.stappen[4]
            if not groen_1_3:
                s.regels.append("overgeslagen: stap 1–3 niet groen")
            elif not selectie["bank"]:
                s.regels.append("geen vertaalbare bankregel in juli 2025")
            else:
                if schrijf:
                    s.uitgevoerd = True
                    s.werkt = True
                for m in selectie["bank"]:
                    vals = dict(m.vals)
                    omschr = (
                        f"{m.date} {vals.get('amount')} {str(vals.get('payment_ref') or '')[:40]!r} anker {m.anker}"
                    )
                    if not schrijf:
                        s.regels.append(f"ZOU aanmaken: {omschr}")
                        if paar is None and reconcile_ankers(m):
                            paar = (0, m)
                        continue
                    try:
                        stl_id = odoo_schrijf.maak_statement_line(client, vals, anker=str(m.anker), audit=audit)
                        stl_ids.append(stl_id)
                        s.odoo_ids.append(stl_id)
                        s.regels.append(f"statement line {stl_id}: {omschr}")
                        if paar is None and reconcile_ankers(m):
                            paar = (stl_id, m)
                    except (OdooFout, CompanyPinGeschonden, odoo_schrijf.AnkerMeerduidig) as exc:
                        s.werkt = False
                        s.regels.append(f"FOUT {omschr}: {exc}")

        # --- stap 5: reconcile ---
        reconcile_regels: list[int] = []
        if 5 in gekozen:
            s = rapport.stappen[5]
            if schrijf and 4 in gekozen and not (rapport.stappen[4].uitgevoerd and rapport.stappen[4].werkt):
                s.regels.append("overgeslagen: stap 4 niet groen")
            elif paar is None:
                s.regels.append("geen bankregel met een reconcile-paar (PaymentReferenceList) op de eerste bankdag")
            else:
                stl_id, m = paar
                ankers = reconcile_ankers(m)
                doc_anker = ankers[0] if ankers else None
                if not schrijf:
                    s.regels.append(
                        f"ZOU reconcilen: statement line ↔ document-anker {doc_anker} via routes i → ii → iii"
                    )
                elif doc_anker is None:
                    s.regels.append("paar zonder document-anker — niet uitgevoerd")
                else:
                    s.uitgevoerd = True
                    try:
                        treffers = odoo_schrijf.zoek_move_op_anker(client, doc_anker)
                        if len(treffers) != 1:
                            s.werkt = False
                            s.regels.append(
                                f"document-anker {doc_anker}: {len(treffers)} moves gevonden — verwacht precies één"
                            )
                        else:
                            doc_move_id = int(treffers[0]["id"])
                            regels = client.search_read(
                                odoo_schrijf.MODEL_MOVE_LINE,
                                [
                                    ["move_id", "=", doc_move_id],
                                    ["company_id", "=", client.pin],
                                    ["account_id.account_type", "in", ["asset_receivable", "liability_payable"]],
                                ],
                                ["id", "account_id", "partner_id"],
                            )
                            if len(regels) != 1:
                                s.werkt = False
                                s.regels.append(
                                    f"move {doc_move_id}: {len(regels)} debiteuren-/crediteurenregels — verwacht "
                                    "precies één"
                                )
                            else:
                                uitkomst = odoo_schrijf.reconcile(
                                    client,
                                    move_line_ids=[int(regels[0]["id"])],
                                    statement_line_id=stl_id,
                                    tegenrekening_id=_m2o(regels[0].get("account_id")),
                                    partner_id=_m2o(regels[0].get("partner_id")),
                                    audit=audit,
                                )
                                s.werkt = bool(uitkomst.geslaagd and uitkomst.is_reconciled)
                                s.regels.append(
                                    f"route {uitkomst.route or 'geen'}; is_reconciled={uitkomst.is_reconciled}; "
                                    f"pogingen={uitkomst.pogingen}"
                                )
                                if uitkomst.geslaagd:
                                    reconcile_regels = [int(regels[0]["id"])]
                    except (OdooFout, CompanyPinGeschonden) as exc:
                        s.werkt = False
                        s.regels.append(f"FOUT: {exc}")

        # --- stap 6: terugweg ---
        if 6 in gekozen:
            s = rapport.stappen[6]
            if not schrijf:
                s.regels.append(
                    "ZOU: koppel_los op de reconcile-regels (regel blijft staan) + button_cancel op het eerste concept "
                    "van stap 1–3"
                )
            elif not aangemaakt_moves and not reconcile_regels:
                s.regels.append("niets om terug te draaien")
            else:
                s.uitgevoerd = True
                s.werkt = True
                try:
                    if reconcile_regels:
                        odoo_schrijf.koppel_los(client, move_line_ids=reconcile_regels, audit=audit)
                        s.regels.append(f"koppel_los op {reconcile_regels} — statement line blijft staan")
                    if aangemaakt_moves:
                        odoo_schrijf.annuleer_concept(
                            client, aangemaakt_moves[0], reden="STAP-0 terugweg (bewijscyclus)", audit=audit
                        )
                        s.regels.append(f"button_cancel op concept {aangemaakt_moves[0]} (state cancel terug-gelezen)")
                except (OdooFout, CompanyPinGeschonden, odoo_schrijf.NietEenConcept) as exc:
                    s.werkt = False
                    s.regels.append(f"FOUT: {exc}")
    return rapport


def _m2o(waarde: Any) -> int | None:
    if isinstance(waarde, (list, tuple)) and waarde:
        return int(waarde[0])
    if isinstance(waarde, int) and not isinstance(waarde, bool):
        return waarde
    return None


# =====================================================================================================================
# argparse-registratie + dispatch
# =====================================================================================================================


def register_odoo_migratie(subparsers: argparse._SubParsersAction) -> None:  # type: ignore[type-arg]
    a = subparsers.add_parser(
        MIGRATIEDOEL_COMMANDO,
        help=(
            "SCHRIJVEND (DB): maak de Odoo-MIGRATIEDOEL-koppeling voor een RLZ-administratie — kopieert URL + "
            "versleutelde API-key van een bestaande Odoo-koppeling, leest dagboeken/plan op de doelcompany "
            "(lees-only), zet migratie_doel=true. "
            "Default --dry-run."
        ),
    )
    a.add_argument("--administratie", required=True, help="UUID of naam(deel) van de DOEL-administratie (backend rlz).")
    a.add_argument(
        "--bron-administratie",
        dest="bron_administratie",
        required=True,
        help="UUID of naam(deel) van de administratie mét Odoo-koppeling (backend odoo).",
    )
    a.add_argument("--company", type=int, required=True, help="Odoo company-id van het doel (VGG = 6).")
    a.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Alleen tonen (default).")
    a.add_argument("--schrijf", dest="dry_run", action="store_false", help="Koppeling-rij écht schrijven.")
    a.add_argument("--bijwerken", action="store_true", help="Bestaande koppeling van de doel-administratie vervangen.")

    b = subparsers.add_parser(
        STAP0_COMMANDO,
        help=(
            "SCHRIJVEND (Odoo, alleen mét --schrijf én MIGRATIE_ODOO_WRITES_INGESCHAKELD=true): bewijscyclus stap 1–6 "
            "op de doelcompany met de eerste vertaalbare documenten van juli 2025 uit de replay (alles concept; "
            "terugweg = button_cancel/"
            "koppel_los, nooit unlink). Default --dry-run."
        ),
    )
    b.add_argument("--administratie", required=True, help="UUID of naam(deel) van de administratie (VGG).")
    b.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Alleen tonen (default).")
    b.add_argument("--schrijf", dest="dry_run", action="store_false", help="Echte writes (vereist de kill-switch AAN).")
    b.add_argument("--stap", default="1-6", help="Stappen, bv. '1-3' of '1,2,4' (default 1-6).")
    b.add_argument("--max-per-type", dest="max_per_type", type=int, default=3, help="Documenten per type (default 3).")


def parse_stappen(tekst: str) -> set[int]:
    gekozen: set[int] = set()
    for deel in str(tekst).split(","):
        deel = deel.strip()
        if not deel:
            continue
        if "-" in deel:
            a, b = deel.split("-", 1)
            gekozen.update(range(int(a), int(b) + 1))
        else:
            gekozen.add(int(deel))
    if not gekozen or not gekozen <= set(STAP_NAMEN):
        raise ValueError(f"--stap moet binnen 1-6 liggen, kreeg {tekst!r}")
    return gekozen


def run_odoo_migratie(args: argparse.Namespace) -> int:
    if args.commando == MIGRATIEDOEL_COMMANDO:
        return _run_migratiedoel(args)
    if args.commando == STAP0_COMMANDO:
        return _run_stap0(args)
    print(f"FOUT  onbekend commando {args.commando!r}", file=sys.stderr)
    return 2


def _run_migratiedoel(args: argparse.Namespace) -> int:
    doel = zoek_administratie(args.administratie)
    bron = zoek_administratie(args.bron_administratie)
    if doel is None or bron is None:
        print(f"FOUT  administratie onbekend: {args.administratie!r} / {args.bron_administratie!r}", file=sys.stderr)
        return 2
    try:
        uitkomst = maak_migratiedoel(
            doel_id=doel[0], bron_id=bron[0], company_id=args.company, dry_run=args.dry_run, bijwerken=args.bijwerken
        )
    except (MigratiedoelFout, OdooFout) as exc:
        print(f"FOUT  {exc}", file=sys.stderr)
        return 2
    print(uitkomst.als_markdown())
    return 0 if uitkomst.probe.groen else 1


def _run_stap0(args: argparse.Namespace) -> int:
    from app.config import settings  # noqa: PLC0415
    from app.migratie.odoo_doel import doelclient_voor  # noqa: PLC0415
    from app.migratie.odoo_schrijf import DbAudit, GeheugenAudit  # noqa: PLC0415

    gevonden = zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam, _ = gevonden
    try:
        stappen = parse_stappen(args.stap)
    except ValueError as exc:
        print(f"FOUT  {exc}", file=sys.stderr)
        return 2
    schrijf = not args.dry_run
    audit: Any = DbAudit(administratie_id) if schrijf else GeheugenAudit()
    rapport = voer_stap0_uit(
        administratie_id,
        administratie_naam=naam,
        schrijf=schrijf,
        stappen=stappen,
        max_per_type=args.max_per_type,
        client_factory=lambda aid: doelclient_voor(aid, read_only=not schrijf),
        replay_module=_laad_replay(),
        audit=audit,
        writes_aan=bool(settings.migratie_odoo_writes_ingeschakeld),
    )
    print(rapport.als_markdown())
    if not rapport.replay_beschikbaar or rapport.company_id is None:
        return 2
    return 0 if all(s.werkt is not False for s in rapport.stappen.values()) else 1
