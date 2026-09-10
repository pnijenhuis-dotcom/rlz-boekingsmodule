"""CLI-commando's van de bankmodule (blok B bundel 10-09) — geregistreerd vanuit app/cli.py met twee regels.

- `bank-voorstellen-lezen` (LEES-ONLY nameting-instrument, bundel 09-09 blok 0; verhuisd uit cli.py): per open
  mutatie het huidige matchmotor-voorstel + `regel` (soort + bron-label, bij historie "k van n op …") + `ai_toets`
  (opgeslagen uitkomst + reden). `--met-ai-toets` voert de AI-plausibiliteitstoets LIVE uit voor de kandidaten
  (vaste regel / groene historie-regel) ZONDER te boeken — audit én kostenmeter lopen wél ("kost AI-tegoed").
  `--json-uit <pad>` schrijft dezelfde tabel als JSON.
- `bank-historie-backfill --administratie` — eerste vulling van de historie-cache (≥ 6 maanden terug), zie
  app/bank/historie_bron.py. Schrijft alleen in de eigen cache, nooit in RLZ.

Productie-regel Peter 08-09: alleen via de gedeployde job-image (`gcloud run jobs execute … --args="-m,app.cli,…"`)."""

from __future__ import annotations

import argparse
import json
import sys
import uuid
from pathlib import Path

from sqlalchemy import select

from app.db.systeem_actor import SYSTEEM_ACTOR_ID

BANK_COMMANDOS = ("bank-voorstellen-lezen", "bank-historie-backfill")


def register_bank(subparsers) -> None:
    lezen = subparsers.add_parser(
        "bank-voorstellen-lezen",
        help="LEES-ONLY: print per onverwerkte bankmutatie van één administratie het huidige matchmotor-voorstel, "
        "de regel-uitkomst (vaste regel / historie k van n) en de opgeslagen AI-toets (nameting-instrument, "
        "bundel 09-09 blok 0 + blok B 10-09; geen schrijfacties, geen RLZ-calls — behalve met --met-ai-toets).",
    )
    lezen.add_argument("--administratie", required=True, help="UUID of (deel van de) naam.")
    lezen.add_argument("--rekening-iban", default=None, dest="rekening_iban", help="Alleen deze rekening.")
    lezen.add_argument(
        "--filter", default=None, help="Toon alleen rijen waarvan tegenpartij/omschrijving/bedrag dit bevat."
    )
    lezen.add_argument(
        "--met-ai-toets",
        action="store_true",
        dest="met_ai_toets",
        help="Voer de AI-plausibiliteitstoets LIVE uit voor de kandidaten (vaste regel / groene historie-regel) "
        "zonder te boeken. KOST AI-TEGOED (kostenmeter + audit lopen wél); uitkomst wordt op de mutatie opgeslagen.",
    )
    lezen.add_argument(
        "--json-uit", default=None, dest="json_uit", help="Schrijf dezelfde tabel als JSON naar dit pad."
    )

    backfill = subparsers.add_parser(
        "bank-historie-backfill",
        help="Eerste vulling van de historie-cache van de historie-regel (bank_historie_boeking) voor één "
        "administratie: eigen boekingen + RLZ-historie (BankMutationDirectBookings via afgeletterde mutaties, "
        "max --max RLZ-lezingen). Schrijft alleen in de eigen cache, nooit in Reeleezee.",
    )
    backfill.add_argument("--administratie", required=True, help="UUID of (deel van de) naam.")
    backfill.add_argument(
        "--max", type=int, default=2000, dest="max_lezingen", help="Maximaal aantal RLZ-lezingen (default 2000)."
    )
    backfill.add_argument(
        "--dry-run",
        action="store_true",
        dest="dry_run",
        help="LEES-ONLY (nameting, ochtendrun 11-09): tel wat de module-bron zou toevoegen en hoeveel afgeletterde "
        "mutaties nog nagelezen zouden worden — geen cache-rijen, geen RLZ-lezing, geen credential nodig.",
    )


def run_bank(args: argparse.Namespace) -> int:
    if args.commando == "bank-voorstellen-lezen":
        return _bank_voorstellen_lezen(args)
    if args.commando == "bank-historie-backfill":
        return _bank_historie_backfill(args)
    raise ValueError(f"onbekend bank-commando {args.commando!r}")


def _zoek_administratie(zoekterm: str) -> tuple[uuid.UUID, str] | None:
    from app.db.models import Administratie
    from app.db.session import scoped_session

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        try:
            administratie = session.get(Administratie, uuid.UUID(zoekterm))
        except ValueError:
            administratie = session.scalars(
                select(Administratie).where(Administratie.naam.ilike(f"%{zoekterm}%"))
            ).first()
        if administratie is None:
            return None
        return administratie.id, administratie.naam


def _ai_toets_label(uitkomst: str | None, reden: str | None) -> str:
    """Leesbare kolomtekst. Blok 4 (10-09 avond): 'overgeslagen' = de toets viel technisch uit en de boeking loopt
    (of liep) door zónder AI-toets — niet 'niet geboekt'."""
    if not uitkomst:
        return "—"
    if uitkomst == "overgeslagen":
        return f"zonder AI-toets (boekt door): {reden or ''}".strip()
    return f"{uitkomst}: {reden or ''}".strip()


def _ai_toets_tekst(stand) -> str:
    if stand is None or not stand.uitkomst:
        return "—"
    return _ai_toets_label(stand.uitkomst, stand.reden)


def _bank_voorstellen_lezen(args: argparse.Namespace) -> int:
    from app.bank import boeken
    from app.bank import voorstellen as bank_voorstellen
    from app.bank.matchmotor import VoorstelSoort
    from app.bank.models import PaymentAccountCache
    from app.db.session import scoped_session

    gevonden = _zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, administratie_naam = gevonden
    rekening_id: uuid.UUID | None = None
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rekeningen = list(
            session.scalars(select(PaymentAccountCache).where(PaymentAccountCache.administratie_id == administratie_id))
        )
        if args.rekening_iban:
            gezocht = args.rekening_iban.replace(" ", "").upper()
            treffers = [r for r in rekeningen if (r.iban or "").replace(" ", "").upper() == gezocht]
            if not treffers:
                print(f"FOUT  rekening {args.rekening_iban!r} niet bekend in {administratie_naam}", file=sys.stderr)
                return 2
            rekening_id = treffers[0].id

    rijen = bank_voorstellen.open_mutaties_met_voorstellen(
        administratie_id=administratie_id, payment_account_id=rekening_id
    )
    live_uitkomsten: dict[uuid.UUID, str] = {}
    if args.met_ai_toets:
        print("LET OP: --met-ai-toets toetst live met AI (kost AI-tegoed); er wordt NIET geboekt")
        context = bank_voorstellen.laad_matchcontext(administratie_id=administratie_id, payment_account_id=rekening_id)
        for rij in rijen:
            kandidaat = rij.voorstel.soort == VoorstelSoort.VASTE_REGEL or (
                rij.voorstel.soort == VoorstelSoort.HISTORIE_REGEL and rij.voorstel.kleur == "groen"
            )
            if not kandidaat or rij.mutatie.bedrag is None:
                continue
            uitkomst, hergebruikt = boeken.voer_ai_toets_uit(context, rij.mutatie, rij.voorstel, hergebruik=False)
            live_uitkomsten[rij.mutatie.id] = _ai_toets_label(uitkomst.uitkomst, uitkomst.reden)

    print(f"bank-voorstellen-lezen {administratie_naam} ({administratie_id}) — onverwerkte mutaties: {len(rijen)}")
    kop = (
        f"{'mutatie':8} {'datum':10} {'bedrag':>12} {'tegenpartij':28} | {'voorstel → referentie':44} | "
        f"{'regel / bron':40} | ai_toets"
    )
    print(kop)
    print("-" * len(kop))
    tel: dict[str, int] = {}
    json_rijen: list[dict] = []
    for rij in rijen:
        soort = rij.voorstel.soort.value
        tel[soort] = tel.get(soort, 0) + 1
        if args.filter and args.filter.lower() not in (
            f"{rij.mutatie.tegenpartij_naam or ''} {rij.mutatie.omschrijving or ''} {rij.mutatie.bedrag}".lower()
        ):
            continue
        referentie = (rij.open_post.referentie if rij.open_post else None) or "-"
        # `regel` = bron-label van de motor (bij vaste regel/historie de regel-uitkomst, bv. "historie: 3 van 3 op …").
        regel = str(rij.voorstel.bron)
        ai_toets = live_uitkomsten.get(rij.mutatie.id) or _ai_toets_tekst(getattr(rij, "ai_toets", None))
        print(
            f"{str(rij.mutatie.id)[:8]:8} {str(rij.boekdatum or ''):10} {str(rij.mutatie.bedrag):>12} "
            f"{(rij.mutatie.tegenpartij_naam or '')[:28]:28} | {(soort + ' → ' + referentie)[:44]:44} | "
            f"{regel[:40]:40} | {ai_toets}"
        )
        json_rijen.append(
            {
                "mutatie_id": str(rij.mutatie.id),
                "datum": str(rij.boekdatum or ""),
                "bedrag": str(rij.mutatie.bedrag),
                "tegenpartij": rij.mutatie.tegenpartij_naam,
                "omschrijving": rij.mutatie.omschrijving,
                "voorstel_soort": soort,
                "voorstel_kleur": getattr(rij.voorstel, "kleur", None),
                "voorstel_bron": rij.voorstel.bron,
                "referentie": referentie,
                "regel": regel,
                "historie_k": getattr(rij.voorstel, "historie_k", None),
                "historie_n": getattr(rij.voorstel, "historie_n", None),
                "ai_toets": ai_toets,
            }
        )
    print("-" * len(kop))
    print(f"Per soort: {dict(sorted(tel.items()))}")
    if args.json_uit:
        Path(args.json_uit).write_text(
            json.dumps(
                {"administratie": administratie_naam, "administratie_id": str(administratie_id), "rijen": json_rijen},
                ensure_ascii=False,
                indent=1,
            ),
            encoding="utf-8",
        )
        print(f"JSON geschreven naar {args.json_uit}")
    print("Geen boekingen uitgevoerd." if args.met_ai_toets else "Geen schrijfacties uitgevoerd.")
    return 0


def _bank_historie_backfill(args: argparse.Namespace) -> int:
    from app.bank import historie_bron
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

    gevonden = _zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, administratie_naam = gevonden
    if getattr(args, "dry_run", False):
        vulling = historie_bron.vul_historie_cache(administratie_id=administratie_id, client=None, dry_run=True)
        print(
            f"bank-historie-backfill DRY-RUN {administratie_naam} ({administratie_id}): module zou "
            f"+{vulling.module_toegevoegd} toevoegen, RLZ nog na te lezen (afgeletterd, ≤ "
            f"{historie_bron.HISTORIE_VENSTER_DAGEN} dagen, nog niet in de cache): {vulling.rlz_resterend} — niets "
            "geschreven, geen RLZ-lezing"
        )
        return 0
    client = None
    try:
        client = client_voor_rlz_admin_id(rlz_admin_id_voor(administratie_id))
    except GeenRlzCredentials as exc:
        print(f"OVERGESLAGEN RLZ-bron: {exc} — alleen de module-boekingen worden gevuld")
    try:
        vulling = historie_bron.vul_historie_cache(
            administratie_id=administratie_id, client=client, max_rlz_lezingen=args.max_lezingen
        )
    finally:
        if client is not None:
            client.close()
    print(
        f"bank-historie-backfill {administratie_naam} ({administratie_id}): module +{vulling.module_toegevoegd}, "
        f"rlz +{vulling.rlz_toegevoegd} (gemarkeerd zonder grootboek/gesplitst: {vulling.rlz_gemarkeerd}), "
        f"resterend: {vulling.rlz_resterend}"
    )
    for fout in vulling.fouten:
        print(f"FOUT  {fout}", file=sys.stderr)
    return 1 if vulling.fouten else 0
