"""CLI-commando's van de accorderingsmodule (blok 7 run 11-09 middag) — geregistreerd vanuit app/cli.py met twee regels.

- `staande-goedkeuring-voorstellen-lezen --administratie <uuid|naam>` (LEES-ONLY nameting-instrument): per open
  accorderingsronde die op een accordeur wacht: leverancier, bedrag, de classificatie van de reeks gelijke facturen
  (periodiek/batch/onbepaald + reden, gedeelde motor app/terugkerend), of er al een staande regel is, of het voorstel
  zwijgt (stilte/uitzondering) en de uitkomst "voorstel: ja/nee". Onderaan de actieve uitzonderingen. Geen
  schrijfacties, geen RLZ-calls — meetrecept voor de Lusso-casus ná deploy (in `scripts/gcp/nameting.sh`).

Productie-regel Peter 08-09: alleen via de gedeployde job-image (`gcloud run jobs execute … --args="-m,app.cli,…"`)."""

from __future__ import annotations

import argparse
import sys
import uuid

from sqlalchemy import select

from app.db.systeem_actor import SYSTEEM_ACTOR_ID

ACCORDERING_COMMANDOS = ("staande-goedkeuring-voorstellen-lezen",)


def register_accordering(subparsers) -> None:
    lezen = subparsers.add_parser(
        "staande-goedkeuring-voorstellen-lezen",
        help="LEES-ONLY: print per open accorderingsronde van één administratie of de accordeur-app het staande-"
        "goedkeuring-voorstel zou tonen en waarom (periodiek/batch/onbepaald, staande regel, stilte/uitzondering) "
        "— nameting-instrument blok 7 11-09; geen schrijfacties, geen RLZ-calls.",
    )
    lezen.add_argument("--administratie", required=True, help="UUID of (deel van de) naam.")


def run_accordering(args: argparse.Namespace) -> int:
    if args.commando == "staande-goedkeuring-voorstellen-lezen":
        return _voorstellen_lezen(args)
    raise ValueError(f"onbekend accordering-commando {args.commando!r}")


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


def _voorstellen_lezen(args: argparse.Namespace) -> int:
    from app.accordering import service
    from app.accordering.models import StaandeGoedkeuring
    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel
    from app.sync.models import VendorCache
    from app.terugkerend.service import classificeer_reeks, gelijke_facturen_per_vendor_bedrag
    from app.tijd import vandaag_nl

    gevonden = _zoek_administratie(args.administratie)
    if gevonden is None:
        print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
        return 2
    administratie_id, naam = gevonden
    vandaag = vandaag_nl()
    print(f"# staande-goedkeuring-voorstellen — {naam} ({administratie_id}) — peildatum {vandaag.isoformat()}")
    print(
        f"# regels: periodiek = ≥ {service.PERIODIEK_MIN_FACTUREN_TEKST} gelijke facturen, tussenpozen ≥ "
        f"{service.PERIODIEK_MIN_TUSSENPOOS_TEKST} d, maand-/kwartaalpatroon; batch = twee gelijke facturen < "
        f"{service.PERIODIEK_MIN_TUSSENPOOS_TEKST} d óf binnen {service.BATCH_VENSTER_TEKST} d zonder patroon; "
        f"'niet nu' = {service.VOORSTEL_STIL_DAGEN} d stil"
    )
    with scoped_session(administratie_id, actor_id=SYSTEEM_ACTOR_ID) as session:
        rondes = service._open_rondes_met_volgende_stap(session, administratie_id=administratie_id)
        if not rondes:
            print("geen open accorderingsrondes")
        voorstellen = (
            {
                v.document_id: v
                for v in session.scalars(
                    select(Boekvoorstel).where(Boekvoorstel.document_id.in_([r.document_id for r, _ in rondes]))
                )
            }
            if rondes
            else {}
        )
        vendor_ids = {v.vendor_id for v in voorstellen.values() if v.vendor_id is not None}
        namen = (
            dict(
                session.execute(
                    select(VendorCache.id, VendorCache.naam).where(
                        VendorCache.administratie_id == administratie_id, VendorCache.id.in_(vendor_ids)
                    )
                ).all()
            )
            if vendor_ids
            else {}
        )
        reeksen = gelijke_facturen_per_vendor_bedrag(session, administratie_id=administratie_id, vendor_ids=vendor_ids)
        regels = {
            (r.accordeur_gebruiker_id, r.vendor_id, r.bedrag)
            for r in session.scalars(
                select(StaandeGoedkeuring).where(
                    StaandeGoedkeuring.administratie_id == administratie_id, StaandeGoedkeuring.actief.is_(True)
                )
            )
        }
        gebruikersnamen = service._gebruikersnamen(session, {stap.accordeur_gebruiker_id for _, stap in rondes})
        telling = {"voorstel": 0, "geen": 0}
        for ronde, stap in rondes:
            voorstel = voorstellen.get(ronde.document_id)
            vendor_id = voorstel.vendor_id if voorstel else None
            bedrag = voorstel.totaalbedrag if voorstel else None
            accordeur = stap.accordeur_gebruiker_id
            reeks = (
                classificeer_reeks(reeksen.get((vendor_id, bedrag), [])) if vendor_id and bedrag is not None else None
            )
            kandidaten = service._staande_regel_kandidaten(
                session,
                administratie_id=administratie_id,
                accordeur_id=accordeur,
                kandidaten=[(ronde.document_id, vendor_id, bedrag, service._ronde_afdeling_id(ronde))],
                vandaag=vandaag,
            )
            stil = (
                service._stille_vendors(
                    session,
                    administratie_id=administratie_id,
                    accordeur_id=accordeur,
                    vendor_ids={vendor_id},
                    vandaag=vandaag,
                )
                if vendor_id
                else set()
            )
            toont = ronde.document_id in kandidaten
            telling["voorstel" if toont else "geen"] += 1
            print(
                f"{ronde.document_id} | accordeur {gebruikersnamen.get(accordeur, accordeur)} | "
                f"{namen.get(vendor_id, vendor_id) if vendor_id else '—'} | "
                f"€ {bedrag if bedrag is not None else '—'} | "
                f"reeks {len(reeksen.get((vendor_id, bedrag), []))} gelijke facturen → "
                f"{reeks.classificatie.value if reeks else 'onbekend'}"
                f"{' (' + reeks.reden + ')' if reeks else ''} | "
                f"staande regel {'ja' if (accordeur, vendor_id, bedrag) in regels else 'nee'} | "
                f"stil {'ja' if vendor_id in stil else 'nee'} | "
                f"voorstel: {'JA (' + kandidaten[ronde.document_id] + ')' if toont else 'nee'}"
            )
        print(
            f"# totaal: {len(rondes)} rondes, voorstel bij {telling['voorstel']}, geen voorstel bij {telling['geen']}"
        )
    uitzonderingen = service.voorstel_uitzonderingen(administratie_id=administratie_id)
    print(f"# actieve stiltes/uitzonderingen: {len(uitzonderingen)}")
    for u in uitzonderingen:
        print(
            f"  {u.soort} | {u.leverancier_naam or u.vendor_id} | accordeur "
            f"{u.accordeur_naam or (u.accordeur_gebruiker_id or 'alle')} | tot {u.stil_tot or '—'} | {u.reden or ''}"
        )
    return 0
