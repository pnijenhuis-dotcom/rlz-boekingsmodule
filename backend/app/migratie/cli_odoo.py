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
    0: "partners: zoek-vóór-create (KvK → btw → IBAN → naam) voor de partijen van stap 1–3",
    1: "eerste echte inkoopfactuur juli 2025 mét bankregel(s): concept → GEPOST (de enige geposte boeking)",
    2: "memoriaal juli 2025 als concept (blijft concept)",
    3: "eerste echte verkoopfactuur juli 2025 als concept (blijft concept)",
    4: "statement line(s) voor de bankregel(s) die factuur (1) betalen — klikpunt IBAN op BNK1",
    5: "reconcile factuur (1) ↔ bankregel(s): routes i → ii → iii, de eerste werkende = DE route",
    6: "terugweg: button_cancel → button_draft op concept (2); koppel_los + opnieuw reconcile op (5)",
}
_TYPE_PER_STAP = {1: "in_invoice", 2: "entry", 3: "out_invoice"}
#: Blok 7 (besluit Peter 12-09 punt 2): het bewijspaar is de eerste échte inkoopfactuur van juli 2025 mét bankregel(s)
#: uit PaymentReferenceList; is er geen inkoopfactuur met betaling, dan de eerste verkoopfactuur mét ontvangst.
PAAR_TYPES: tuple[str, ...] = ("in_invoice", "out_invoice")


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
    #: Blok 7: wat er ná de run in de doelcompany staat (voor het rapport "wat staat er nu in company 6").
    stand: dict[str, Any] = field(default_factory=dict)

    def als_markdown(self) -> str:
        modus = f"SCHRIJF (company {self.company_id})" if self.schrijf else "DRY-RUN — geen Odoo-writes"
        r = [f"# vgg-odoo-stap0 — {self.administratie_naam} — {modus}", ""]
        r.extend(f"- {m}" for m in self.meldingen)
        if self.meldingen:
            r.append("")
        r.extend(["| # | Stap | Werkt op company %s | Detail |" % (self.company_id or "?"), "|---|---|---|---|"])
        for n in sorted(self.stappen):
            s = self.stappen[n]
            detail = "<br>".join(s.regels) if s.regels else "—"
            r.append(f"| {n} | {s.naam} | **{s.oordeel}** | {detail} |")
        if self.stand:
            r.extend(["", "**Stand in de doelcompany ná deze run:**", ""])
            r.extend(f"- {k}: {v}" for k, v in self.stand.items())
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


@dataclass
class Selectie:
    """Uitkomst van `selecteer_moves`: per type de concept-kandidaten (het paar-document vooraan in zijn type),
    `paar` = (factuur, bankregels die 'm betalen) of None."""

    per_type: dict[str, list[Any]]
    paar: tuple[Any, list[Any]] | None
    paar_reden: str

    def __getitem__(self, sleutel: str) -> list[Any]:  # bestaande aanroepen `selectie["in_invoice"]`
        return self.per_type[sleutel]


def bankregels_per_anker(moves: Sequence[Any]) -> dict[str, list[Any]]:
    """anker van een document → de vertaalbare bankregels (élke datum) die volgens PaymentReferenceList aan dat
    document gekoppeld zijn."""
    uit: dict[str, list[Any]] = {}
    for m in moves:
        if not is_bankregel(m) or getattr(m, "status", None) != "vertaalbaar":
            continue
        for anker in reconcile_ankers(m):
            uit.setdefault(anker, []).append(m)
    for lijst in uit.values():
        lijst.sort(key=lambda m: (str(getattr(m, "date", "")), str(getattr(m, "anker", ""))))
    return uit


def selecteer_moves(
    moves: Sequence[Any], *, max_per_type: int, jaar_maand: tuple[int, int] = STAP0_JAAR_MAAND
) -> Selectie:
    """Per type de eerste `max_per_type` VERTAALBARE documenten uit de opgegeven maand (datum, dan anker) — mét het
    bewijspaar vooraan (besluit Peter 12-09 punt 2): de eerste inkoopfactuur van die maand die volgens
    PaymentReferenceList door ≥ 1 bankregel betaald wordt; geen inkoopfactuur met betaling → de eerste verkoopfactuur
    met ontvangst; ook die niet → geen paar (zichtbaar). Bankregels komen uitsluitend via het paar mee — niet meer
    'de eerste bankdag'."""
    per_type: dict[str, list[Any]] = {"in_invoice": [], "entry": [], "out_invoice": []}
    kandidaten = [
        m
        for m in moves
        if getattr(m, "status", None) == "vertaalbaar"
        and _in_maand(getattr(m, "date", None), jaar_maand)
        and not is_bankregel(m)
    ]
    kandidaten.sort(key=lambda m: (str(getattr(m, "date", "")), str(getattr(m, "anker", ""))))
    per_anker = bankregels_per_anker(moves)
    paar: tuple[Any, list[Any]] | None = None
    for soort in PAAR_TYPES:
        for m in kandidaten:
            if getattr(m, "move_type", None) == soort and per_anker.get(str(getattr(m, "anker", ""))):
                paar = (m, per_anker[str(m.anker)])
                break
        if paar is not None:
            break
    if paar is not None:
        per_type[paar[0].move_type].append(paar[0])
        paar_reden = (
            f"paar: {paar[0].move_type} {paar[0].boekstuk} ↔ {len(paar[1])} bankregel(s) "
            f"({', '.join(str(getattr(b, 'date', '?')) for b in paar[1])})"
        )
    else:
        paar_reden = (
            f"geen factuur in {jaar_maand[0]}-{jaar_maand[1]:02d} met gekoppelde bankregel(s) in PaymentReferenceList "
            "— niets te posten, stap 4/5 niet uitvoerbaar"
        )
    for m in kandidaten:
        soort = getattr(m, "move_type", None)
        if soort in per_type and len(per_type[soort]) < max_per_type and m not in per_type[soort]:
            per_type[soort].append(m)
    return Selectie(per_type=per_type, paar=paar, paar_reden=paar_reden)


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


def lees_bank_iban(client: CompanyGepindeClient, journal_id: int | None) -> tuple[bool, str]:
    """Klikpunt Peter (blok 7): staat er een IBAN op het bankdagboek (BNK1)? (gevuld?, leesbare stand). Lees-only."""
    if journal_id is None:
        return False, "geen bankdagboek bekend (journal_id ontbreekt in de bankregel-vals)"
    journal = client.read_een("account.journal", int(journal_id), ["code", "bank_account_id", "bank_acc_number"]) or {}
    nummer = journal.get("bank_acc_number") if isinstance(journal.get("bank_acc_number"), str) else None
    rekening = _m2o(journal.get("bank_account_id"))
    if rekening is None and not nummer:
        return False, f"IBAN op dagboek {journal.get('code') or journal_id} is LEEG — klikpunt Peter"
    return True, f"IBAN op dagboek {journal.get('code') or journal_id}: {nummer or f'bank_account_id {rekening}'}"


def _partner_voorstel(m: Any) -> dict[str, Any] | None:
    voorstel = getattr(m, "partner", None)
    return dict(voorstel) if isinstance(voorstel, dict) else None


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
    """De bewijscyclus (blok 7 run 2, besluiten Peter 12-09 punt 2 + 3). `schrijf=False` = print wat er zou gebeuren.
    Elke stap meldt 'werkt op company 6: ja/nee/niet uitgevoerd'. Volgorde en poorten:
    0 partners → 1 inkoopfactuur (paar) concept → GEPOST → 2 memoriaal → 3 verkoopfactuur → 4 statement lines van de
    betalende bankregels (alleen mét IBAN op BNK1, anders overgeslagen + gemeld) → 5 reconcile (alleen ná groen 4) →
    6 terugweg (concept (2) cancel → draft; koppeling los en opnieuw gelegd)."""
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
    paar_factuur = selectie.paar[0] if selectie.paar else None
    bankregels = selectie.paar[1] if selectie.paar else []
    rapport.meldingen.append(
        f"replay: {len(moves)} moves, selectie juli 2025: in_invoice {len(selectie['in_invoice'])} · "
        f"entry {len(selectie['entry'])} · out_invoice {len(selectie['out_invoice'])} · {selectie.paar_reden}"
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

    with client:
        # --- stap 0: partners (besluit 3) — alleen de partijen die stap 1–3 nodig hebben ---
        partner_per_anker: dict[str, int] = {}
        zonder_partner: set[str] = set()
        if 0 in gekozen:
            s = rapport.stappen[0]
            nodig = [
                m
                for n in (1, 3)
                if n in gekozen
                for m in selectie[_TYPE_PER_STAP[n]]
                if getattr(m, "move_type", None) != "entry"
            ]
            if not nodig:
                s.regels.append("geen factuur-concepten gekozen — geen partners nodig")
            for m in nodig:
                voorstel = _partner_voorstel(m)
                if voorstel is None:
                    zonder_partner.add(str(m.anker))
                    s.regels.append(f"{m.boekstuk}: GEEN partner-voorstel in de replay — concept wordt overgeslagen")
                    if schrijf:
                        s.uitgevoerd, s.werkt = True, False
                    continue
                omschr = f"{m.boekstuk}: {voorstel.get('naam') or '?'} [{voorstel.get('sleutel')}]"
                if not schrijf:
                    s.regels.append(f"ZOU zoeken/aanmaken: {omschr}")
                    continue
                s.uitgevoerd = True
                if s.werkt is None:
                    s.werkt = True
                try:
                    uit = odoo_schrijf.zoek_of_maak_partner(client, voorstel, audit=audit)
                    partner_per_anker[str(m.anker)] = uit.partner_id
                    s.odoo_ids.append(uit.partner_id)
                    s.regels.append(
                        f"{uit.herkomst} partner {uit.partner_id} ({uit.naam}) — {uit.detail} voor {omschr}"
                    )
                except schrijf_fouten as exc:
                    s.werkt = False
                    zonder_partner.add(str(m.anker))
                    s.regels.append(f"FOUT {omschr}: {exc}")
            if schrijf and nodig:
                rapport.stand["partners aangemaakt"] = sum(1 for r in s.regels if r.startswith("aangemaakt partner"))
                rapport.stand["partners hergebruikt"] = sum(1 for r in s.regels if r.startswith("hergebruikt partner"))

        # --- stappen 1–3: concepten (+ posten van het paar in stap 1/3) ---
        aangemaakt_moves: dict[int, list[int]] = {1: [], 2: [], 3: []}
        gepost_move_id: int | None = None
        for n in (1, 2, 3):
            if n not in gekozen:
                continue
            s = rapport.stappen[n]
            kandidaten = selectie[_TYPE_PER_STAP[n]]
            if not kandidaten:
                s.regels.append("geen vertaalbaar document van dit type in juli 2025")
                continue
            for m in kandidaten:
                is_paar = paar_factuur is not None and m is paar_factuur
                n_regels = len(m.vals.get("invoice_line_ids") or m.vals.get("line_ids") or [])
                omschr = f"{m.boekstuk} (rlz {m.rlz_id}) anker {m.anker} — {n_regels} regels"
                if not schrijf:
                    s.regels.append(f"ZOU aanmaken: {omschr}" + (" → ZOU POSTEN (bewijspaar)" if is_paar else ""))
                    continue
                if n != 2 and str(m.anker) in zonder_partner:
                    s.uitgevoerd, s.werkt = True, False
                    s.regels.append(f"overgeslagen {omschr}: geen partner (concept draagt altijd een partner)")
                    continue
                s.uitgevoerd = True
                if s.werkt is None:
                    s.werkt = True
                vals = dict(m.vals)
                if n != 2:
                    if 0 in gekozen:
                        vals["partner_id"] = partner_per_anker.get(str(m.anker))
                    if not vals.get("partner_id"):
                        s.werkt = False
                        s.regels.append(f"overgeslagen {omschr}: partner_id leeg (stap 0 niet gedraaid of mislukt)")
                        continue
                try:
                    move_id = odoo_schrijf.maak_concept_move(client, vals, anker=str(m.anker), audit=audit)
                    s.odoo_ids.append(move_id)
                    aangemaakt_moves[n].append(move_id)
                    regel = f"concept {move_id}: {omschr}"
                    if is_paar:
                        na = odoo_schrijf.post_move(client, move_id, audit=audit)
                        gepost_move_id = move_id
                        regel += f" → GEPOST als {na.get('name')} (state {na.get('state')})"
                    s.regels.append(regel)
                except schrijf_fouten as exc:
                    s.werkt = False
                    s.regels.append(f"FOUT {omschr}: {exc}")
        groen_1_3 = all(rapport.stappen[n].werkt for n in (1, 2, 3) if n in gekozen and rapport.stappen[n].uitgevoerd)

        # --- stap 4: statement lines van de betalende bankregels (klikpunt IBAN) ---
        stl_ids: list[int] = []
        iban_ok = True
        if 4 in gekozen:
            s = rapport.stappen[4]
            if paar_factuur is None:
                s.regels.append("overgeslagen: geen bewijspaar (zie melding)")
            elif schrijf and not groen_1_3:
                s.regels.append("overgeslagen: stap 1–3 niet groen")
            elif schrijf and gepost_move_id is None:
                s.regels.append("overgeslagen: de paar-factuur is niet gepost")
            else:
                journal_id = bankregels[0].vals.get("journal_id") if bankregels else None
                try:
                    iban_ok, iban_stand = lees_bank_iban(client, journal_id)
                except OdooFout as exc:
                    iban_ok, iban_stand = False, f"IBAN-stand niet leesbaar: {exc}"
                s.regels.append(iban_stand)
                if not iban_ok:
                    rapport.meldingen.append(
                        "KLIKPUNT PETER: IBAN op BNK1 is leeg — stap 4 en 5 overgeslagen, rest doorgelopen"
                    )
                    s.regels.append("overgeslagen: IBAN op BNK1 leeg (klikpunt Peter) — stap 5 ook overgeslagen")
                else:
                    if schrijf:
                        s.uitgevoerd = True
                        s.werkt = True
                    for m in bankregels:
                        vals = dict(m.vals)
                        omschr = (
                            f"{m.date} {vals.get('amount')} {str(vals.get('payment_ref') or '')[:40]!r} anker {m.anker}"
                        )
                        if not schrijf:
                            s.regels.append(f"ZOU aanmaken: {omschr}")
                            continue
                        try:
                            stl_id = odoo_schrijf.maak_statement_line(client, vals, anker=str(m.anker), audit=audit)
                            stl_ids.append(stl_id)
                            s.odoo_ids.append(stl_id)
                            s.regels.append(f"statement line {stl_id}: {omschr}")
                        except schrijf_fouten as exc:
                            s.werkt = False
                            s.regels.append(f"FOUT {omschr}: {exc}")

        # --- stap 5: reconcile ---
        reconcile_regels: list[int] = []
        reconcile_params: dict[str, Any] | None = None
        if 5 in gekozen:
            s = rapport.stappen[5]
            if paar_factuur is None:
                s.regels.append("overgeslagen: geen bewijspaar")
            elif not iban_ok:
                s.regels.append("overgeslagen: IBAN op BNK1 leeg (klikpunt Peter)")
            elif not schrijf:
                s.regels.append(
                    f"ZOU reconcilen: {len(bankregels)} statement line(s) ↔ geposte factuur {paar_factuur.boekstuk} "
                    "via routes i → ii → iii"
                )
            elif 4 in gekozen and not (rapport.stappen[4].uitgevoerd and rapport.stappen[4].werkt):
                s.regels.append("overgeslagen: stap 4 niet groen")
            elif gepost_move_id is None or not stl_ids:
                s.regels.append("overgeslagen: geen geposte factuur of geen statement line")
            else:
                s.uitgevoerd = True
                try:
                    regels = client.search_read(
                        odoo_schrijf.MODEL_MOVE_LINE,
                        [
                            ["move_id", "=", gepost_move_id],
                            ["company_id", "=", client.pin],
                            ["account_id.account_type", "in", ["asset_receivable", "liability_payable"]],
                        ],
                        ["id", "account_id", "partner_id"],
                    )
                    if len(regels) != 1:
                        s.werkt = False
                        s.regels.append(
                            f"move {gepost_move_id}: {len(regels)} debiteuren-/crediteurenregels — verwacht precies één"
                        )
                    else:
                        s.werkt = True
                        reconcile_params = {
                            "move_line_ids": [int(regels[0]["id"])],
                            "tegenrekening_id": _m2o(regels[0].get("account_id")),
                            "partner_id": _m2o(regels[0].get("partner_id")),
                        }
                        for stl_id in stl_ids:
                            uitkomst = odoo_schrijf.reconcile(
                                client, statement_line_id=stl_id, audit=audit, **reconcile_params
                            )
                            s.regels.append(
                                f"statement line {stl_id}: route {uitkomst.route or 'geen'}; "
                                f"is_reconciled={uitkomst.is_reconciled}; pogingen={uitkomst.pogingen}"
                            )
                            if not (uitkomst.geslaagd and uitkomst.is_reconciled):
                                s.werkt = False
                        if s.werkt:
                            reconcile_regels = list(reconcile_params["move_line_ids"])
                except schrijf_fouten as exc:
                    s.werkt = False
                    s.regels.append(f"FOUT: {exc}")

        # --- stap 6: terugweg ---
        if 6 in gekozen:
            s = rapport.stappen[6]
            concept_2 = aangemaakt_moves[2][0] if aangemaakt_moves[2] else None
            if not schrijf:
                s.regels.append(
                    "ZOU: button_cancel → button_draft op concept (2) (memoriaal; nooit unlink) + koppel_los op de "
                    "reconcile-regels en de koppeling opnieuw leggen (bewijs remove_move_reconcile)"
                )
            elif concept_2 is None and not reconcile_regels:
                s.regels.append("niets om terug te draaien (geen concept (2), geen reconcile)")
            else:
                s.uitgevoerd = True
                s.werkt = True
                if concept_2 is not None:
                    try:
                        odoo_schrijf.annuleer_concept(
                            client, concept_2, reden="STAP-0 terugweg (bewijscyclus blok 7)", audit=audit
                        )
                        odoo_schrijf.zet_terug_naar_concept(client, concept_2, audit=audit)
                        s.regels.append(
                            f"concept {concept_2}: button_cancel → cancel → button_draft → draft (terug-gelezen)"
                        )
                    except schrijf_fouten as exc:
                        s.werkt = False
                        s.regels.append(f"FOUT terugweg concept {concept_2}: {exc}")
                if reconcile_regels and reconcile_params is not None:
                    try:
                        odoo_schrijf.koppel_los(client, move_line_ids=reconcile_regels, audit=audit)
                        s.regels.append(f"koppel_los op {reconcile_regels} — statement line(s) blijven staan")
                        opnieuw = [
                            odoo_schrijf.reconcile(client, statement_line_id=stl_id, audit=audit, **reconcile_params)
                            for stl_id in stl_ids
                        ]
                        s.regels.append(
                            "opnieuw gelegd: "
                            + ", ".join(f"route {u.route or 'geen'} is_reconciled={u.is_reconciled}" for u in opnieuw)
                        )
                        if not all(u.geslaagd and u.is_reconciled for u in opnieuw):
                            s.werkt = False
                    except schrijf_fouten as exc:
                        s.werkt = False
                        s.regels.append(f"FOUT terugweg reconcile: {exc}")

        if schrijf:
            rapport.stand["geposte boekingen (deze run)"] = 1 if gepost_move_id is not None else 0
            rapport.stand["concepten (deze run)"] = sum(len(v) for v in aangemaakt_moves.values()) - (
                1 if gepost_move_id is not None else 0
            )
            rapport.stand["statement lines (deze run)"] = len(stl_ids)
            try:
                rapport.stand["account.move op de company (totaal, niet cancel)"] = client.search_count(
                    odoo_schrijf.MODEL_MOVE, [["company_id", "=", client.pin], ["state", "!=", "cancel"]]
                )
                rapport.stand["account.bank.statement.line op de company (totaal)"] = client.search_count(
                    odoo_schrijf.MODEL_STATEMENT_LINE, [["company_id", "=", client.pin]]
                )
            except OdooFout as exc:
                rapport.stand["nameting"] = f"niet leesbaar: {exc}"
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
            "SCHRIJVEND (Odoo, alleen mét --schrijf én MIGRATIE_ODOO_WRITES_INGESCHAKELD=true): bewijscyclus stap 0–6 "
            "op de doelcompany (blok 7: partners → eerste inkoopfactuur juli 2025 mét bankregel(s) GEPOST → memoriaal/"
            "verkoopfactuur concept → statement lines → reconcile → terugweg; nooit unlink). Default --dry-run."
        ),
    )
    b.add_argument("--administratie", required=True, help="UUID of naam(deel) van de administratie (VGG).")
    b.add_argument("--dry-run", dest="dry_run", action="store_true", default=True, help="Alleen tonen (default).")
    b.add_argument("--schrijf", dest="dry_run", action="store_false", help="Echte writes (vereist de kill-switch AAN).")
    b.add_argument("--stap", default="0-6", help="Stappen, bv. '0-3' of '0,1,4' (default 0-6).")
    b.add_argument(
        "--max-per-type",
        dest="max_per_type",
        type=int,
        default=1,
        help="Documenten per type (default 1 — besluit Peter 12-09: één inkoop, één memoriaal, één verkoop).",
    )


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
        raise ValueError(f"--stap moet binnen 0-6 liggen, kreeg {tekst!r}")
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
