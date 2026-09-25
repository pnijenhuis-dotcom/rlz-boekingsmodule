"""`crediteuren-naamclusters` — LEES-ONLY telling van crediteur-naamclusters kantoorbreed (blok 2 feedbackrun A 25-09,
FV-21 "crediteurnamen in meerdere schrijfwijzen"; nameting-allowlist, dispatch-onderdeel `crediteuren-naamclusters`).

Per administratie in haar EIGEN RLS-scope (patroon `app/beheer/bua_cli.py`): de dubbelen-motor
(`documenten/crediteur_kenmerk.dubbele_crediteuren` → `crediteuren/service._clusters_voor_administratie`) levert de
clusters; hier tellen we uitsluitend de clusters die UITSLUITEND op de genormaliseerde naam matchen
(`app/crediteuren/naam.py`): aantal clusters, aantal crediteuren erin, KvK-conflict (= géén dubbel, afmelden
primair), al afgemeld (`crediteur_dubbel_afmelding`) en al door een mens bevestigd (`crediteur_dubbel_afhandeling`
bron 'mens', alleen naam-sleutels, niet teruggedraaid). GEEN write, GEEN RLZ-call. Een kapotte administratie stopt de
rest niet: zichtbare FOUT-regel. De TOTAAL-regel is de oordeelregel van het nameting-onderdeel.

Vormen (élke vorm staat letterlijk in `tests/crediteuren/test_naamclusters.py`):
  crediteuren-naamclusters --alles [--detail] [--json-uit]
  crediteuren-naamclusters --administratie <uuid|naamdeel> [--detail] [--json-uit]
"""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from dataclasses import asdict, dataclass, field

COMMANDO = "crediteuren-naamclusters"


@dataclass(frozen=True)
class NaamclusterRij:
    administratie_id: str
    administratie_naam: str
    sleutel: str
    namen: list[str]
    aantal_crediteuren: int
    aantal_boekingen: int
    kvk_conflict: bool
    stand: str  # 'open' | 'afgemeld' | 'kvk_conflict'


@dataclass
class AdministratieTelling:
    administratie_id: str
    administratie_naam: str
    clusters: int = 0
    crediteuren: int = 0
    kvk_conflict: int = 0
    afgemeld: int = 0
    bevestigd: int = 0
    fout: str | None = None
    rijen: list[NaamclusterRij] = field(default_factory=list)


@dataclass
class Meting:
    administraties: list[AdministratieTelling]

    @property
    def fouten(self) -> list[str]:
        return [f"{a.administratie_naam}: {a.fout}" for a in self.administraties if a.fout]

    def som(self, veld: str) -> int:
        return sum(getattr(a, veld) for a in self.administraties if not a.fout)


def _administraties(term: str | None) -> list[tuple[uuid.UUID, str]] | None:
    from app.beheer.bua_cli import _administraties as _bua_administraties

    return _bua_administraties(term)


def telling_voor(administratie_id: uuid.UUID, administratie_naam: str) -> AdministratieTelling:
    """Eén administratie in haar eigen scope — naam-only clusters (open + afgemeld) en de mens-bevestigingen."""
    from sqlalchemy import select

    from app.crediteuren import afhandeling, service
    from app.crediteuren.models import CrediteurDubbelAfhandeling, CrediteurDubbelAfmelding, combinatie_sleutel
    from app.db.session import scoped_session
    from app.documenten.crediteur_kenmerk import dubbele_crediteuren

    uit = AdministratieTelling(administratie_id=str(administratie_id), administratie_naam=administratie_naam)
    actor = afhandeling._systeem_actor()
    # Open clusters (afgemelde zijn hier al weggefilterd) — alleen de clusters mét uitsluitend een naam-sleutel.
    clusters = service._clusters_voor_administratie(actor, administratie_id, administratie_naam)
    open_naam = [c for c in clusters if {s for s, _ in c.sleutels} == {"naam"}]
    # Afgemelde naam-only groepen: de motor-groepen opnieuw bundelen en tegen de afmeldingen leggen.
    groepen = dubbele_crediteuren(administratie_id=administratie_id)
    per_set: dict[frozenset[uuid.UUID], set[str]] = {}
    namen_per_set: dict[frozenset[uuid.UUID], list[str]] = {}
    for g in groepen:
        leden = frozenset(c.vendor_id for c in g.crediteuren)
        per_set.setdefault(leden, set()).add(g.soort)
        namen_per_set.setdefault(leden, [c.naam or str(c.vendor_id)[:8] for c in g.crediteuren])
    with scoped_session(administratie_id, actor_id=actor.id) as session:
        afgemeld = set(
            session.scalars(
                select(CrediteurDubbelAfmelding.combinatie).where(
                    CrediteurDubbelAfmelding.administratie_id == administratie_id
                )
            )
        )
        bevestigd = 0
        for log in session.scalars(
            select(CrediteurDubbelAfhandeling).where(
                CrediteurDubbelAfhandeling.administratie_id == administratie_id,
                CrediteurDubbelAfhandeling.bron == "mens",
                CrediteurDubbelAfhandeling.teruggedraaid_op.is_(None),
            )
        ):
            soorten = {s.get("soort") for s in (log.sleutels or [])}
            if soorten == {"naam"}:
                bevestigd += 1
    uit.bevestigd = bevestigd
    for c in open_naam:
        uit.clusters += 1
        uit.crediteuren += len(c.crediteuren)
        if c.kvk_verschilt:
            uit.kvk_conflict += 1
        uit.rijen.append(
            NaamclusterRij(
                administratie_id=str(administratie_id),
                administratie_naam=administratie_naam,
                sleutel=c.sleutel,
                namen=[k.naam or str(k.vendor_id)[:8] for k in c.crediteuren],
                aantal_crediteuren=len(c.crediteuren),
                aantal_boekingen=c.aantal_boekingen,
                kvk_conflict=c.kvk_verschilt,
                stand="kvk_conflict" if c.kvk_verschilt else "open",
            )
        )
    for leden, soorten in per_set.items():
        if soorten == {"naam"} and combinatie_sleutel(leden) in afgemeld:
            uit.afgemeld += 1
            uit.rijen.append(
                NaamclusterRij(
                    administratie_id=str(administratie_id),
                    administratie_naam=administratie_naam,
                    sleutel="",
                    namen=namen_per_set[leden],
                    aantal_crediteuren=len(leden),
                    aantal_boekingen=0,
                    kvk_conflict=False,
                    stand="afgemeld",
                )
            )
    return uit


def meet(*, administratie: str | None) -> Meting | None:
    scope = _administraties(administratie)
    if scope is None:
        return None
    uit: list[AdministratieTelling] = []
    for aid, naam in scope:
        try:
            uit.append(telling_voor(aid, naam))
        except Exception as exc:  # noqa: BLE001 — een kapotte administratie stopt de rest niet, zichtbaar
            uit.append(AdministratieTelling(administratie_id=str(aid), administratie_naam=naam, fout=str(exc)))
    return Meting(administraties=uit)


def totaalregel(meting: Meting) -> str:
    met = sum(1 for a in meting.administraties if not a.fout and a.clusters)
    n = sum(1 for a in meting.administraties if not a.fout)
    return (
        f"TOTAAL {meting.som('clusters')} naam-cluster(s) in {met} van {n} administratie(s) · "
        f"{meting.som('crediteuren')} crediteuren · KvK-conflict {meting.som('kvk_conflict')} · "
        f"afgemeld {meting.som('afgemeld')} · bevestigd (mens) {meting.som('bevestigd')} · "
        f"fouten {len(meting.fouten)} · automatisch samengevoegd op naam: 0 (nooit)"
    )


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    p = subparsers.add_parser(
        COMMANDO,
        help="LEES-ONLY (25-09, FV-21): crediteur-clusters die uitsluitend op de genormaliseerde naam matchen "
        "(casefold, rechtsvorm/leestekens/spaties weg) — per administratie in eigen RLS-scope; telling clusters/"
        "crediteuren/KvK-conflict/afgemeld/bevestigd. Geen write, geen RLZ-call; nooit automatisch samenvoegen.",
    )
    doel = p.add_mutually_exclusive_group(required=True)
    doel.add_argument("--administratie", default=None, help="Eén administratie (uuid of naamdeel).")
    doel.add_argument("--alles", action="store_true", help="Alle actieve administraties (kantoorbreed).")
    p.add_argument("--detail", action="store_true", help="Toon ook de clusters per administratie.")
    p.add_argument("--json-uit", action="store_true", dest="json_uit", help="Machineleesbare uitvoer (JSON).")


def dispatch(args: argparse.Namespace) -> int | None:
    if getattr(args, "commando", None) != COMMANDO:
        return None
    meting = meet(administratie=args.administratie)
    if meting is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    if args.json_uit:
        print(
            json.dumps(
                {
                    "administraties": [
                        {**{k: v for k, v in asdict(a).items() if k != "rijen"}, "rijen": [asdict(r) for r in a.rijen]}
                        if args.detail
                        else {k: v for k, v in asdict(a).items() if k != "rijen"}
                        for a in meting.administraties
                    ],
                    "totaal": {
                        "clusters": meting.som("clusters"),
                        "crediteuren": meting.som("crediteuren"),
                        "kvk_conflict": meting.som("kvk_conflict"),
                        "afgemeld": meting.som("afgemeld"),
                        "bevestigd": meting.som("bevestigd"),
                    },
                    "fouten": meting.fouten,
                },
                ensure_ascii=False,
                indent=1,
            )
        )
        return 0
    print(f"Crediteuren-naamclusters — {len(meting.administraties)} administratie(s) (lees-only, geen RLZ-call)")
    for a in meting.administraties:
        if a.fout:
            print(f"  FOUT  {a.administratie_naam}: {a.fout}")
            continue
        if a.clusters or a.afgemeld or a.bevestigd:
            print(
                f"  {a.administratie_naam}: {a.clusters} cluster(s), {a.crediteuren} crediteuren, "
                f"KvK-conflict {a.kvk_conflict}, afgemeld {a.afgemeld}, bevestigd {a.bevestigd}"
            )
            if args.detail:
                for r in a.rijen:
                    print(f"    - [{r.stand}] {' / '.join(r.namen)} ({r.aantal_boekingen} boekingen)")
    print(totaalregel(meting))
    return 0
