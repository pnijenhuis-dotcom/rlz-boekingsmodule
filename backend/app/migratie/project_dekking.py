"""Blok 11 (Peter 17-09: "in RLZ staat alles als project geboekt" — project = pand): STAP-0-instrument in de replay.

Puur over `RlzBron` (regels van álle geboekte documenten, `REGEL_EXPAND` = Account,TaxRate,Project): per DocumentType en
per grootboekgroep het aantal regels mét/zonder `Project`, de regels ZONDER project op pand-relevante rekeningen (boekstuk,
rekening, bedrag — klikwerk Peter in RLZ), of `Project` op bankmutaties bestaat (veld-aanwezigheid), en de kruistoets
RLZ-project ↔ adres-cluster (`PandToewijzing` per document): hoeveel clusters vallen samen met precies één project, hoeveel
projecten zijn over meerdere clusters versnipperd. Geen RLZ-calls, geen DB, geen AI — de replay leest, dit telt.
Meetlat (opdracht): dekking ≥ ~90 % op pand-relevante regels → pandenregister op projectsleutel (blok B)."""

from __future__ import annotations

import uuid
from collections import defaultdict
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from app.migratie import rlz_bron
from app.rlz.lezen import als_bedrag

#: Pand-relevante grootboekgroepen (RGS/VGG-rekeningschema, blok 7c): aankoop 7000, opbrengst 8xxx, aanbetalingen 1405,
#: vaste lasten/kosten 46xx/70xx (≠ 7000). Alles anders = "overig" (balans, btw, bank, resultaat).
DEKKINGSDREMPEL = Decimal("0.90")
DOCTYPE_NAAM = {1: "inkoop", 10: "verkoop", 11: "memoriaal", 19: "bank-direct", 0: "resultaat"}


def grootboekgroep(code: str | None) -> str:
    if not code:
        return "onbekend"
    if code == "7000":
        return "7000 aankoop"
    if code.startswith("8"):
        return "8xxx opbrengst"
    if code == "1405" or code.startswith("140"):
        return "1405 aanbetalingen"
    if code.startswith(("46", "70")):
        return "46xx/70xx vaste lasten & kosten"
    if code.startswith("10"):
        return "10xx bank/kas"
    return "overig"


PAND_RELEVANT = frozenset({"7000 aankoop", "8xxx opbrengst", "1405 aanbetalingen", "46xx/70xx vaste lasten & kosten"})


@dataclass
class Teller:
    totaal: int = 0
    met_project: int = 0

    @property
    def aandeel(self) -> Decimal | None:
        return (Decimal(self.met_project) / Decimal(self.totaal)).quantize(Decimal("0.001")) if self.totaal else None

    def als_dict(self) -> dict[str, Any]:
        return {"totaal": self.totaal, "met_project": self.met_project, "aandeel": str(self.aandeel) if self.aandeel is not None else None}


@dataclass
class ProjectDekking:
    documenten_met_regels: int = 0
    regels_totaal: int = 0
    regels_met_project: int = 0
    per_documenttype: dict[str, Teller] = field(default_factory=lambda: defaultdict(Teller))
    per_grootboekgroep: dict[str, Teller] = field(default_factory=lambda: defaultdict(Teller))
    #: Regels zonder project op pand-relevante rekeningen: boekstuk, rekening, bedrag (klikwerk Peter in RLZ/Toewijzing).
    zonder_project_pand_relevant: list[dict[str, Any]] = field(default_factory=list)
    projecten_in_regels: dict[str, str] = field(default_factory=dict)  # project-id → naam
    bank_project_veld_aanwezig: bool | None = None
    #: Kruistoets project ↔ adres-cluster (alleen documenten mét toewijzing én mét project).
    documenten_met_project_en_cluster: int = 0
    clusters_een_project: int = 0
    clusters_meer_projecten: int = 0
    projecten_een_cluster: int = 0
    projecten_versnipperd: int = 0
    cluster_naar_projecten: dict[str, list[str]] = field(default_factory=dict)
    project_naar_clusters: dict[str, list[str]] = field(default_factory=dict)

    @property
    def aandeel_pand_relevant(self) -> Decimal | None:
        tot = sum(t.totaal for g, t in self.per_grootboekgroep.items() if g in PAND_RELEVANT)
        met = sum(t.met_project for g, t in self.per_grootboekgroep.items() if g in PAND_RELEVANT)
        return (Decimal(met) / Decimal(tot)).quantize(Decimal("0.001")) if tot else None

    @property
    def dekking_voldoende(self) -> bool | None:
        a = self.aandeel_pand_relevant
        return None if a is None else a >= DEKKINGSDREMPEL

    @property
    def oordeel(self) -> str:
        a = self.aandeel_pand_relevant
        if a is None:
            return "geen pand-relevante regels gelezen — dekking niet meetbaar"
        pct = f"{(a * 100).quantize(Decimal('0.1'))} %"
        if a >= DEKKINGSDREMPEL:
            return f"dekking {pct} op pand-relevante regels ≥ 90 % — pandenregister op projectsleutel (blok B) verantwoord"
        return f"dekking {pct} op pand-relevante regels < 90 % — beslispunt Peter: regels zonder project in RLZ coderen vs adres-terugval"

    def als_dict(self) -> dict[str, Any]:
        return {
            "documenten_met_regels": self.documenten_met_regels,
            "regels_totaal": self.regels_totaal,
            "regels_met_project": self.regels_met_project,
            "aandeel_pand_relevant": str(self.aandeel_pand_relevant) if self.aandeel_pand_relevant is not None else None,
            "dekking_voldoende": self.dekking_voldoende,
            "oordeel": self.oordeel,
            "per_documenttype": {k: v.als_dict() for k, v in sorted(self.per_documenttype.items())},
            "per_grootboekgroep": {k: v.als_dict() for k, v in sorted(self.per_grootboekgroep.items())},
            "zonder_project_pand_relevant": self.zonder_project_pand_relevant,
            "projecten_in_regels": len(self.projecten_in_regels),
            "bank_project_veld_aanwezig": self.bank_project_veld_aanwezig,
            "kruistoets": {
                "documenten_met_project_en_cluster": self.documenten_met_project_en_cluster,
                "clusters_een_project": self.clusters_een_project,
                "clusters_meer_projecten": self.clusters_meer_projecten,
                "projecten_een_cluster": self.projecten_een_cluster,
                "projecten_versnipperd": self.projecten_versnipperd,
            },
        }


def _project_van(regel: dict[str, Any]) -> tuple[str | None, str | None]:
    p = regel.get("Project")
    if isinstance(p, dict) and p.get("id"):
        return str(p["id"]), str(p.get("Name") or "")
    return None, None


def _code_van(regel: dict[str, Any]) -> str | None:
    a = regel.get("Account")
    if isinstance(a, dict):
        c = a.get("Code") or a.get("Number") or a.get("AccountNumber")
        return str(c) if c else None
    return None


def _bedrag_van(regel: dict[str, Any]) -> Decimal | None:
    for veld in ("NetAmount", "DebitAmount", "CreditAmount", "Amount"):
        b = als_bedrag(regel.get(veld))
        if b is not None and b != 0:
            return b
    return als_bedrag(regel.get("NetAmount"))


def bereken(bron: rlz_bron.RlzBron, *, panden: dict[uuid.UUID, Any] | None = None) -> ProjectDekking:
    """`panden` = `PandToewijzing` per RLZ-document-id (attribuut `pand_code`) — de adres-clusters van blok B/3."""
    uit = ProjectDekking()
    cluster_projecten: dict[str, set[str]] = defaultdict(set)
    project_clusters: dict[str, set[str]] = defaultdict(set)
    for pad, rij in bron.alle_documenten():
        rid = rlz_bron.doc_id(rij)
        regels = bron.regels.get(rid or "")
        if not regels:
            continue
        uit.documenten_met_regels += 1
        dt = rlz_bron.documenttype_van(pad, rij)
        dt_naam = DOCTYPE_NAAM.get(dt if dt is not None else -1, f"type {dt}")
        boekstuk = rlz_bron.boekstuk_van(rij) or (rid or "?")[:8]
        projecten_doc: set[str] = set()
        for r in regels:
            pid, pnaam = _project_van(r)
            code = _code_van(r)
            groep = grootboekgroep(code)
            uit.regels_totaal += 1
            uit.per_documenttype[dt_naam].totaal += 1
            uit.per_grootboekgroep[groep].totaal += 1
            if pid:
                uit.regels_met_project += 1
                uit.per_documenttype[dt_naam].met_project += 1
                uit.per_grootboekgroep[groep].met_project += 1
                uit.projecten_in_regels.setdefault(pid, pnaam or "")
                projecten_doc.add(pid)
            elif groep in PAND_RELEVANT:
                b = _bedrag_van(r)
                uit.zonder_project_pand_relevant.append(
                    {"boekstuk": boekstuk, "documenttype": dt_naam, "rekening": code or "?", "groep": groep, "bedrag": str(b) if b is not None else None}
                )
        if panden and projecten_doc:
            try:
                toewijzing = panden.get(uuid.UUID(str(rid)))
            except (ValueError, TypeError):
                toewijzing = None
            pand_code = getattr(toewijzing, "pand_code", None) if toewijzing is not None else None
            if pand_code:
                uit.documenten_met_project_en_cluster += 1
                for pid in projecten_doc:
                    cluster_projecten[pand_code].add(pid)
                    project_clusters[pid].add(pand_code)
    uit.bank_project_veld_aanwezig = any("Project" in r for r in bron.bank) if bron.bank else None
    uit.clusters_een_project = sum(1 for s in cluster_projecten.values() if len(s) == 1)
    uit.clusters_meer_projecten = sum(1 for s in cluster_projecten.values() if len(s) > 1)
    uit.projecten_een_cluster = sum(1 for s in project_clusters.values() if len(s) == 1)
    uit.projecten_versnipperd = sum(1 for s in project_clusters.values() if len(s) > 1)
    uit.cluster_naar_projecten = {k: sorted(uit.projecten_in_regels.get(p, p)[:40] for p in v) for k, v in sorted(cluster_projecten.items())}
    uit.project_naar_clusters = {uit.projecten_in_regels.get(k, k)[:40]: sorted(v) for k, v in sorted(project_clusters.items())}
    uit.zonder_project_pand_relevant.sort(key=lambda r: (r["groep"], r["boekstuk"], r["rekening"]))
    return uit


def markdown(d: ProjectDekking) -> list[str]:
    L = [
        "#### Project-dekking (blok 11, Peter 17-09: pand = RLZ-project — STAP-0 op de regels van álle geboekte documenten)",
        "",
        f"- {d.oordeel}",
        f"- Documenten mét regels: {d.documenten_met_regels} · regels: {d.regels_totaal} · mét Project: {d.regels_met_project} · "
        f"projecten in regels: {len(d.projecten_in_regels)} · Project-veld op bankmutaties: "
        + ("aanwezig" if d.bank_project_veld_aanwezig else "afwezig" if d.bank_project_veld_aanwezig is False else "geen bank gelezen"),
        "",
        "| DocumentType | regels | mét project | aandeel |",
        "|---|---|---|---|",
    ]
    for k, t in sorted(d.per_documenttype.items()):
        L.append(f"| {k} | {t.totaal} | {t.met_project} | {t.aandeel if t.aandeel is not None else '—'} |")
    L += ["", "| Grootboekgroep | regels | mét project | aandeel |", "|---|---|---|---|"]
    for k, t in sorted(d.per_grootboekgroep.items()):
        L.append(f"| {k}{' *' if k in PAND_RELEVANT else ''} | {t.totaal} | {t.met_project} | {t.aandeel if t.aandeel is not None else '—'} |")
    L.append("(* = pand-relevant, telt in de meetlat)")
    L += ["", f"Kruistoets project ↔ adres-cluster: {d.documenten_met_project_en_cluster} documenten mét beide; clusters met precies één project "
          f"{d.clusters_een_project}, met meer projecten {d.clusters_meer_projecten}; projecten in één cluster {d.projecten_een_cluster}, "
          f"versnipperd over meer clusters {d.projecten_versnipperd}."]
    if d.zonder_project_pand_relevant:
        L += ["", f"Regels ZONDER project op pand-relevante rekeningen ({len(d.zonder_project_pand_relevant)}; eerste 60 — klikwerk Peter in RLZ of Toewijzing):", "",
              "| Boekstuk | Type | Rekening | Groep | Bedrag |", "|---|---|---|---|---|"]
        for r in d.zonder_project_pand_relevant[:60]:
            L.append(f"| {r['boekstuk']} | {r['documenttype']} | {r['rekening']} | {r['groep']} | {r['bedrag'] or '—'} |")
    return L
