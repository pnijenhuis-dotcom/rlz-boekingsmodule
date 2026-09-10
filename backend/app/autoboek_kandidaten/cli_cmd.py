"""CLI-commando's autoboeken per administratie (blok A bundel 10-09) — geregistreerd vanuit app/cli.py (2 regels).

- `autoboek-drempel-zetten --drempel N`        — platformbrede drempel "N op rij" via `service.zet_drempel` (audit
                                                 `autoboek_drempel_gewijzigd`, actor = systeem). Post-deploy-stap: de
                                                 productie-rij staat op 5, het besluit van 10-09 zegt 3.
- `autoboek-leren-rapport --administratie <uuid>` — LEES-ONLY nameting-instrument: per leverancier reeks
                                                 n/drempel, stand
                                                 (leert | boekt_automatisch | uitgezonderd | handmatig_aan), bron en de
                                                 kwalificatie-redenen uit de bestaande historie in de module.
                                                 Schrijft niets.

Productie-uitvoering (regel Peter 08-09): uitsluitend op de gedeployde job-image, bv.
`gcloud run jobs execute rlz-reconciliatie --region europe-west4 \
    --args="-m,app.cli,autoboek-leren-rapport,--administratie,<uuid>" --wait`."""

from __future__ import annotations

import argparse
import sys
import uuid

COMMANDO_DREMPEL = "autoboek-drempel-zetten"
COMMANDO_RAPPORT = "autoboek-leren-rapport"
COMMANDOS = (COMMANDO_DREMPEL, COMMANDO_RAPPORT)


def register(subparsers) -> None:  # noqa: ANN001 — argparse-subparsers-actie
    drempel = subparsers.add_parser(
        COMMANDO_DREMPEL,
        help="Autoboeken per administratie (blok A 10-09): platformbrede drempel 'N op rij ongewijzigd' zetten (1–50, "
        "audit oud→nieuw, actor = systeem). Post-deploy: productie van 5 naar 3.",
    )
    drempel.add_argument("--drempel", type=int, required=True, help="Nieuwe drempel (1–50); besluit Peter 10-09 = 3.")
    rapport = subparsers.add_parser(
        COMMANDO_RAPPORT,
        help="LEES-ONLY nameting autoboeken-leren: per leverancier n/drempel, stand en bron uit de historie in de "
        "module.",
    )
    rapport.add_argument("--administratie", required=True, help="UUID van de administratie.")
    rapport.add_argument(
        "--alleen-kwalificerend", action="store_true", help="Toon alleen leveranciers die de drempel al halen."
    )


def dispatch(args: argparse.Namespace) -> int | None:
    """None = niet ons commando (cli.py gaat verder); anders de exit-code."""
    if args.commando == COMMANDO_DREMPEL:
        return _drempel_zetten(args)
    if args.commando == COMMANDO_RAPPORT:
        return _leren_rapport(args)
    return None


def _drempel_zetten(args: argparse.Namespace) -> int:
    from app.autoboek_kandidaten import service
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID

    oud, _ = service.haal_instelling_op()
    try:
        nieuw = service.zet_drempel(actor_id=SYSTEEM_ACTOR_ID, drempel=int(args.drempel))
    except service.AutoboekKandidaatFout as exc:
        print(f"FOUT  {exc}", file=sys.stderr)
        return 1
    print(f"autoboek-drempel: {oud} -> {nieuw} (audit autoboek_drempel_gewijzigd, actor systeem)")
    return 0


def _leren_rapport(args: argparse.Namespace) -> int:
    from sqlalchemy import select

    from app.autoboek_kandidaten import service
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.sync.models import VendorCache

    try:
        administratie_id = uuid.UUID(args.administratie)
    except ValueError:
        print(f"FOUT  geen geldige UUID: {args.administratie}", file=sys.stderr)
        return 1
    with scoped_session(None) as session:
        administratie = session.get(Administratie, administratie_id)
        if administratie is None:
            print(f"FOUT  onbekende administratie: {administratie_id}", file=sys.stderr)
            return 1
        naam = administratie.naam
        schakelaar = bool(administratie.autoboeken_leren_ingeschakeld)
        toegestaan = not administratie.doorbelasting_ingeschakeld
    drempel, laatste_run = service.haal_instelling_op()
    standen = service.bereken_standen(administratie_id=administratie_id)
    with scoped_session(administratie_id) as session:
        namen = dict(
            session.execute(
                select(VendorCache.id, VendorCache.naam).where(VendorCache.id.in_([s.vendor_id for s in standen]))
            ).all()
        )
    print(f"=== autoboek-leren-rapport — {naam} ({administratie_id}) ===")
    print(
        f"schakelaar: {'AAN' if schakelaar else 'uit'}"
        + ("" if toegestaan else " — niet toegestaan (doorbelasting = mensenwerk)")
        + f" · drempel {drempel} · kandidaten-run {laatste_run.isoformat() if laatste_run else 'nog nooit'}"
    )
    leren_aan = schakelaar and toegestaan
    rijen = sorted(standen, key=lambda s: (-s.reeks_ongewijzigd, (namen.get(s.vendor_id) or "").lower()))
    if args.alleen_kwalificerend:
        rijen = [s for s in rijen if s.kwalificeert]
    tellers = {"leert": 0, "boekt_automatisch": 0, "uitgezonderd": 0, "handmatig_aan": 0, "kwalificeert": 0}
    print(f"{'leverancier':<48} {'reeks':>7} {'stand':<18} {'bron':<8} redenen")
    for s in rijen:
        stand = service.stand_label(
            actief=s.actief, bron=s.bron, uitgezonderd=s.uitgezonderd, administratie_leren_aan=leren_aan
        )
        tellers[stand] += 1
        if s.kwalificeert and not s.actief:
            tellers["kwalificeert"] += 1
        redenen = "; ".join(s.redenen) if s.redenen else ("—" if s.actief else "kwalificeert")
        if s.uitgezonderd and s.uitzondering_reden:
            redenen = f"uitgezonderd: {s.uitzondering_reden}"
        print(
            f"{(namen.get(s.vendor_id) or str(s.vendor_id))[:48]:<48} {s.reeks_ongewijzigd:>3}/{drempel:<3} "
            f"{stand:<18} {s.bron or '—':<8} {redenen}"
        )
    print(
        f"totaal {len(rijen)} leveranciers met historie: leert {tellers['leert']} (waarvan {tellers['kwalificeert']} "
        f"kwalificerend), boekt automatisch {tellers['boekt_automatisch']}, uitgezonderd {tellers['uitgezonderd']}, "
        f"handmatig aan {tellers['handmatig_aan']}"
    )
    if not leren_aan and tellers["kwalificeert"]:
        print(
            f"NB schakelaar uit: {tellers['kwalificeert']} leverancier(s) zou(den) bij aanzetten direct "
            "geactiveerd worden."
        )
    return 0
