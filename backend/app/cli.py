from __future__ import annotations

import argparse
import logging
import sys
import uuid
from decimal import Decimal
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import select

from app.accordering.cli_cmd import ACCORDERING_COMMANDOS, register_accordering, run_accordering
from app.auth import service
from app.backends.registry import RLZ_ONLY_OVERGESLAGEN
from app.bank import reconciliatie as bank_reconciliatie
from app.bank import sync as bank_sync_service
from app.bank.cli_cmd import BANK_COMMANDOS, register_bank, run_bank
from app.beheer import service as beheer_service
from app.berichten import herinneringen, nieuwe_facturen
from app.credentialstore import service as credentialstore_service
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import reconciliatie, storno_detectie, webhook_afleveraar
from app.doorbelasting import factuur_herstel as doorbelasting_factuur_herstel
from app.doorbelasting import reconciliatie as doorbelasting_reconciliatie
from app.doorbelasting import service as doorbelasting_service
from app.geheugen import seed as geheugen_seed
from app.intake import verwerking as intake_verwerking
from app.intake.postvak import ImapPostvakBron, PostvakFout, PostvakNietGeconfigureerd
from app.lezen.cli_cmd import DB_LEZEN_COMMANDO, register_db_lezen, run_db_lezen
from app.migratie.cli_cmd import register_migratie, run_migratie
from app.migratie.cli_odoo import ODOO_MIGRATIE_COMMANDOS, register_odoo_migratie, run_odoo_migratie  # run 2 VGG blok 5
from app.migratie.cli_replay import VGG_REPLAY_COMMANDO, register_vgg_replay, run_vgg_replay  # run 2 VGG blok 6
from app.odoo.cli_rj220 import VGG_REKENINGEN_COMMANDO, register_vgg_rekeningen, run_vgg_rekeningen  # run 2 VGG blok 4
from app.omzet import reconciliatie as omzet_reconciliatie
from app.panden.cli_cmd import register_panden, run_panden
from app.panden.toewijzen_cli import PAND_TOEWIJZEN_COMMANDO, register_pand_toewijzen, run_pand_toewijzen  # 21-09 VGG bp 1
from app.projecten.cli_cmd import PROJECTEN_COMMANDOS, register_projecten, run_projecten  # blok 3 18-09
from app.projectverdeling.cli_cmd import (  # opdracht 19-09: projectverdeling-afgesloten-rapport (lees-only)
    PROJECTVERDELING_COMMANDOS,
    register_projectverdeling,
    run_projectverdeling,
)
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.models import ReconciliatieBron
from app.rlz.credentials import GeenRlzCredentials
from app.rlz.feiten_cli import RLZ_FEITEN_COMMANDO, register_rlz_feiten, run_rlz_feiten
from app.rlz.lezen_cli import RLZ_LEZEN_COMMANDO, register_rlz_lezen, run_rlz_lezen
from app.sync import service as sync_service
from app.verplichting.cli_cmd import VERPLICHTING_COMMANDOS, register_verplichting, run_verplichting  # 18-09

# Dev-gemak: de RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_-logins staan in verkenning/.env
# (nooit in backend/.env, zie CLAUDE.md), en niets anders laadt dat bestand als de CLI los
# gedraaid wordt (buiten pytest, waar tests/integration/conftest.py dit al voor zijn eigen tests
# doet). Alleen relevant voor import-env-credentials; in Cloud Run bestaat dit pad niet en is
# load_dotenv() dan een stille no-op — echte credentials komen daar via Secret Manager-env-vars.
load_dotenv(Path(__file__).resolve().parents[2] / "verkenning" / ".env")


def _bootstrap_beheerder(args: argparse.Namespace) -> int:
    try:
        resultaat = service.bootstrap_eerste_beheerder(naam=args.naam, e_mail=args.e_mail)
    except service.AuthError as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"Eerste Beheerder aangemaakt: {resultaat.gebruiker_id} ({args.e_mail})")
    print(f"Uitnodigingstoken (eenmalig, verloopt {resultaat.verloopt_op.isoformat()}):")
    print(resultaat.token)
    print(
        "Rond de activatie af via POST /auth/uitnodigingen/accepteren met dit token, "
        "gevolgd door de TOTP-enrollment (POST /auth/totp/bevestigen)."
    )
    return 0


def _rapporteer_cijfers_runs(resultaten: dict) -> int:
    """Gedeelde rapportage voor de projectcijfers-runcommando's: run-uitkomst per
    administratie, exit 1 bij élke fout-run of exception (zichtbaar in de job-alerting)."""
    from app.projecten.cijfers_run import RunInfo

    fouten = 0
    for administratie_id, resultaat in resultaten.items():
        if isinstance(resultaat, RunInfo):
            if resultaat.status == "klaar":
                extra = f", {resultaat.leesfouten} leesfout(en)" if resultaat.leesfouten else ""
                print(
                    f"{administratie_id}: klaar — {resultaat.documenten} documenten, "
                    f"{resultaat.regels} regels, {resultaat.verdwenen} verdwenen{extra}"
                )
            elif resultaat.status in ("wachtrij", "bezig"):
                # Informatief, geen fout: er loopt al een verse run (bv. de knop vlak vóór de
                # job) — die maakt zijn eigen status af, dubbel draaien is juist ongewenst.
                print(f"{administratie_id}: al {resultaat.status} (run {resultaat.run_id}) — niet dubbel gestart")
            else:
                fouten += 1
                print(f"{administratie_id}: {resultaat.status} — {resultaat.fout_reden}")
        elif resultaat is None:
            print(f"{administratie_id}: geen wachtrij")
        else:
            fouten += 1
            print(f"{administratie_id}: FOUT — {resultaat}")
    print(f"Klaar: {len(resultaten)} administratie(s), {fouten} fout(en)")
    return 1 if fouten else 0


def _projecten_cijfers_sync(args: argparse.Namespace) -> int:
    """Projectcijfers-sync (projectenmodule, mockup 22-08) — zelfde nooit-vroeg-stoppen-patroon
    als sync-alles; loopt sinds de achtergrondrun-fix (23-08) via de run-administratie zodat
    'laatst ververst' óók voor deze route zichtbaar is in de status-leesroute."""
    from app.projecten.cijfers_run import sync_alle_via_runs

    return _rapporteer_cijfers_runs(sync_alle_via_runs())


def _projecten_cijfers_wachtrij(args: argparse.Namespace) -> int:
    """Entrypoint van de on-demand Cloud Run-job rlz-projecten-cijfers (achtergrondrun-fix
    23-08): verwerk klaargezette wachtrij-runs; geen wachtrij = snelle no-op (exit 0)."""
    from app.projecten.cijfers_run import verwerk_wachtrij

    return _rapporteer_cijfers_runs(verwerk_wachtrij())


def _bank_sync_wachtrij(args: argparse.Namespace) -> int:
    """Entrypoint van de on-demand Cloud Run-job rlz-bank-sync (bank auto-verversing bij openen,
    feedbackronde 25-08 deel 4 punt 2): verwerk klaargezette bank_sync_run-rijen; geen wachtrij =
    snelle no-op (exit 0). Fouten landen zichtbaar op de run (status fout + reden), nooit exit 1."""
    from app.bank.sync_run import verwerk_wachtrij

    aantal = verwerk_wachtrij()
    print(f"bank-sync-wachtrij: {aantal} run(s) verwerkt")
    return 0


def _eerste_sync_wachtrij(args: argparse.Namespace) -> int:
    from app.beheer import eerste_sync

    aantal = eerste_sync.verwerk_wachtrij()
    print(f"eerste-sync-wachtrij: {aantal} run(s) verwerkt")
    return 0


def _terugkerend_herbereken_wachtrij(args: argparse.Namespace) -> int:
    """Entrypoint van de on-demand Cloud Run-job rlz-terugkerend-herbereken (design-ronde 03-09 blok B1,
    mockup inzicht-kantoorbreed ③): verwerk klaargezette terugkerend_herbereken_run-rijen — de bestaande
    motor herbereken_alle(), geen RLZ-calls. Geen wachtrij = snelle no-op; fouten landen zichtbaar op
    de run (status fout + reden), nooit exit 1."""
    from app.terugkerend import herbereken_run

    aantal = herbereken_run.verwerk_wachtrij()
    print(f"terugkerend-herbereken-wachtrij: {aantal} run(s) verwerkt")
    return 0


def _extractie_wachtrij_verwerken(args: argparse.Namespace) -> int:
    """Job-entrypoint extractie-wachtrij (punt 4, 26-08): synchroon, systeem-actor, idempotent."""
    from app.documenten import service as documenten_service

    aantal = documenten_service.verwerk_extractie_wachtrij()
    print(f"extractie-wachtrij-verwerken: {aantal} document(en) verwerkt")
    return 0


def _boek_wachtrij_verwerken(args: argparse.Namespace) -> int:
    """Job-entrypoint achtergrond-schrijver (boeken sneller 18-09): álle documenten op wordt_geboekt afronden — oudste
    eerst, claim per idempotency-key (overlap trigger/scheduler is veilig), gestrande claims (> herstelgrens) hervat."""
    from app.documenten import boek_wachtrij

    aantal = boek_wachtrij.verwerk_boek_wachtrij(verwerker="job")
    print(f"boek-wachtrij-verwerken: {aantal} boeking(en) afgerond (geboekt of zichtbaar mislukt)")
    return 0


def _extractie_heraanbieden(args: argparse.Namespace) -> int:
    """Bulk-nazorg union-limiet-bugfix (31-08): biedt documenten waarvan de laatste
    extractiepoging sinds --sinds faalde opnieuw aan via de bestaande opnieuw-route."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.documenten import service as documenten_service

    try:
        sinds = datetime.fromisoformat(args.sinds).replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
    except ValueError:
        print(f"Ongeldige --sinds-datum: {args.sinds!r} (verwacht YYYY-MM-DD)", file=sys.stderr)
        return 2
    telling = documenten_service.heraanbied_gefaalde_extracties(
        sinds=sinds, fout_filter=args.filter, dry_run=args.dry_run
    )
    print(
        f"extractie-heraanbieden{' [dry-run]' if args.dry_run else ''}: "
        f"{telling['kandidaten']} kandidaat/kandidaten, {telling['heraangeboden']} heraangeboden "
        f"(waarvan {telling['naar_wachtrij']} via de wachtrij), {telling['overgeslagen']} overgeslagen"
    )
    return 0


def _intake_herlezen(args: argparse.Namespace) -> int:
    """Nazorg intake-splitsingsbug (spoedopdracht 02-09, punt 5): verzamelbak-PDF's die sinds
    --sinds op een verworpen/mislukt intake-AI-voorstel strandden opnieuw door de gefixte keten
    (nieuwe tenaamstelling-bepaling); al toegewezen/verwerkte rijen worden nooit geraakt."""
    from datetime import datetime
    from zoneinfo import ZoneInfo

    from app.intake import herlezen

    try:
        sinds = datetime.fromisoformat(args.sinds).replace(tzinfo=ZoneInfo("Europe/Amsterdam"))
    except ValueError:
        print(f"Ongeldige --sinds-datum: {args.sinds!r} (verwacht YYYY-MM-DD)", file=sys.stderr)
        return 2
    try:
        telling = herlezen.herlees_verzamelbak(
            sinds=sinds,
            dry_run=args.dry_run,
            opnieuw=args.opnieuw,
            alle_redenen=args.alle_redenen,
            toewijzen=not args.zonder_toewijzen,
            alleen_ubl=args.alleen_ubl,
        )
    except herlezen.IntakeGateDicht as exc:
        print(f"intake-herlezen: {exc}", file=sys.stderr)
        return 1
    label = " [dry-run]" if args.dry_run else ""
    print(
        f"intake-herlezen{label}: {telling.kandidaten} kandidaat/kandidaten, "
        f"{telling.overgeslagen_al_herlezen} al eerder herlezen (overgeslagen), {telling.herlezen} herlezen — "
        f"{telling.toegewezen} toegewezen, {telling.tenaamstelling_gezet} tenaamstelling/suggestie gezet, "
        f"{telling.splitsingsvoorstel} splitsingsvoorstel, {telling.beeld_gezet} beeld (ingesloten PDF) gezet, "
        f"{telling.mislukt} mislukt"
    )
    for regel in telling.details:
        print(f"  - {regel}")
    if telling.gestopt_reden:
        print(f"  ! {telling.gestopt_reden}")
    return 0


def _verzamelbak_nabundelen(args: argparse.Namespace) -> int:
    """Nabundel-nazorg (akkoord Peter 02-09): verzamelbak-UBL's waarvan de PDF-tegenhanger uit dezelfde
    e-mail al vóór de bundeling is toegewezen alsnog aan dat PDF-document koppelen (UBL = data, PDF =
    beeld, deterministische her-extractie; UBL-rij → samengevoegd). Alleen te_controleren/
    handmatig_afmaken zonder opgeslagen voorstel wordt her-geëxtraheerd; alles anders overgeslagen mét
    reden. Geen AI, geen RLZ-calls. --dry-run toetst alle poorten en schrijft niets."""
    from sqlalchemy import select

    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.intake import nabundelen

    administratie_filter: uuid.UUID | None = None
    if args.administratie:
        try:
            administratie_filter = uuid.UUID(args.administratie)
        except ValueError:
            print(f"Ongeldig --administratie-id: {args.administratie!r}", file=sys.stderr)
            return 2
    telling = nabundelen.nabundel_verzamelbak(
        dry_run=args.dry_run, ook_toegewezen=args.ook_toegewezen, administratie_id=administratie_filter
    )
    with scoped_session(None) as session:
        namen = dict(session.execute(select(Administratie.id, Administratie.naam)).all())
    label = " [dry-run]" if args.dry_run else ""
    if args.ook_toegewezen:
        label += " [ook toegewezen UBL-documenten]"
    if administratie_filter is not None:
        label += f" [alleen {namen.get(administratie_filter, administratie_filter)}]"
    print(
        f"verzamelbak-nabundelen{label}: {telling.kandidaten} kandidaat/kandidaten — "
        f"{telling.samengevoegd} samengevoegd (+ her-extractie), "
        f"{telling.gekoppeld_voorstel_behouden} gekoppeld met behoud van het opgeslagen voorstel, "
        f"{telling.overgeslagen} overgeslagen, {telling.mislukt} mislukt"
        + (f", {telling.herkanst} ná herkansing geslaagd" if telling.herkanst else "")
        + (f", {telling.niet_geprobeerd} niet geprobeerd" if telling.niet_geprobeerd else "")
    )
    if telling.paren_met_samenvouw:
        # Dubbel-exemplaren (07-09): byte-identieke PDF's/UBL's uit dezelfde e-mail, weggevouwen in het gehouden exemplaar.
        print(
            f"  dubbel-exemplaren samengevouwen{' (plan)' if args.dry_run else ''}: {telling.samengevouwen_dubbelen} "
            f"exemplaar/exemplaren in {telling.paren_met_samenvouw} paar/paren"
        )
    per_reden = telling.overgeslagen_per_reden()
    if per_reden:
        print("  overgeslagen per reden:")
        for reden, aantal in sorted(per_reden.items(), key=lambda kv: -kv[1]):
            print(f"    {aantal}× {reden}")
    per_adm = telling.per_administratie()
    if per_adm:
        print("  per administratie:")
        for adm_id, per in sorted(per_adm.items(), key=lambda kv: str(namen.get(kv[0], kv[0]))):
            samenvatting = ", ".join(f"{n} {u}" for u, n in sorted(per.items()))
            print(f"    {namen.get(adm_id, adm_id or 'administratie onbekend')}: {samenvatting}")
    for uitkomst in telling.uitkomsten:
        naam = namen.get(uitkomst.administratie_id, "?") if uitkomst.administratie_id else "?"
        print(f"  - [{naam}] {uitkomst.als_regel()}")
    if telling.gestopt_reden:
        print(f"  ! {telling.gestopt_reden}")
    return 0 if not telling.gestopt_reden else 1


def _duplicaten_backfill(args: argparse.Namespace) -> int:
    """Blok 1 07-09 (besluit Peter "duplicaten eruit"): álle bestaande Mogelijk-duplicaat-rijen én open documenten
    door de module-motor (sha256 / genormaliseerde referentie + bedrag) — duplicaten afgevoerd mét kruisverwijzing,
    buiten de dagrem, noodrem gerespecteerd, UBL+PDF-bundelparen en mens-afmeldingen beschermd. Geen RLZ-/Odoo-calls.
    --dry-run toetst alles en schrijft niets; cijfers per administratie."""
    from app.documenten import duplicaat_afvoer

    administratie_filter: uuid.UUID | None = None
    if args.administratie:
        try:
            administratie_filter = uuid.UUID(args.administratie)
        except ValueError:
            print(f"Ongeldig --administratie-id: {args.administratie!r}", file=sys.stderr)
            return 2
    uitkomsten = duplicaat_afvoer.backfill(dry_run=args.dry_run, administratie_id=administratie_filter)
    label = " [dry-run]" if args.dry_run else ""
    tot_kand = sum(u.kandidaten for u in uitkomsten)
    tot_plan = sum(u.af_te_voeren for u in uitkomsten)
    tot_af = sum(u.afgevoerd for u in uitkomsten)
    print(
        f"duplicaten-backfill{label}: {len(uitkomsten)} administratie(s), {tot_kand} kandidaten, "
        f"{tot_plan} af te voeren, {tot_af} afgevoerd"
    )
    for u in uitkomsten:
        if not u.kandidaten and not u.gestopt_reden and not u.bundelparen_beschermd:
            continue
        print(
            f"  {u.naam}: {u.documenten} toetsbaar, {u.kandidaten} kandidaten, {u.af_te_voeren} af te voeren, "
            f"{u.afgevoerd} afgevoerd, {u.bundelparen_beschermd} bundelpaar-beschermd, {u.afgemeld} afgemeld"
        )
        for reden, n in sorted(u.overgeslagen.items(), key=lambda kv: -kv[1]):
            print(f"    overgeslagen {n}× {reden}")
        for regel in u.regels:
            print(f"    - {regel}")
        if u.gestopt_reden:
            print(f"    ! {u.gestopt_reden}")
    return 0


def _referentie_norm_backfill(args: argparse.Namespace) -> int:
    """16-09 (Zenvoices-casus, migratie 0147): vul `boekvoorstel.referentie_norm` voor bestaande rijen. Puur afgeleide
    kolom, idempotent, geen tijdlijn/audit; --dry-run telt alleen."""
    from app.documenten import referentie_backfill

    administratie_filter: uuid.UUID | None = None
    if args.administratie:
        try:
            administratie_filter = uuid.UUID(args.administratie)
        except ValueError:
            print(f"Ongeldig --administratie-id: {args.administratie!r}", file=sys.stderr)
            return 2
    uitkomsten = referentie_backfill.backfill(dry_run=args.dry_run, administratie_id=administratie_filter)
    label = " [dry-run]" if args.dry_run else ""
    print(
        f"referentie-norm-backfill{label}: {len(uitkomsten)} administratie(s), "
        f"{sum(u.met_referentie for u in uitkomsten)} boekvoorstellen mét referentie, "
        f"{sum(u.te_vullen for u in uitkomsten)} te vullen, {sum(u.gevuld for u in uitkomsten)} gevuld"
    )
    for u in uitkomsten:
        if not u.te_vullen:
            continue
        print(f"  {u.naam}: {u.met_referentie} mét referentie, {u.te_vullen} te vullen, {u.gevuld} gevuld")
        for v in u.voorbeelden:
            print(f"    - {v}")
    return 0


def _activa_nulmeting(args: argparse.Namespace) -> int:
    """16-09 (STAP-0 activa, blok C): LEES-ONLY nulmeting MVA-rekeningen ↔ FixedAssets-register ↔ module-regels."""
    from app.activa import nulmeting

    ids: list[uuid.UUID] | None = None
    if args.administratie:
        treffers = _zoek_administraties(args.administratie)
        if len(treffers) != 1:
            print(
                f"--administratie {args.administratie!r}: {len(treffers)} treffer(s) — precies één vereist: "
                + ", ".join(f"{n} ({i})" for i, n in treffers),
                file=sys.stderr,
            )
            return 2
        ids = [treffers[0][0]]
    nulmeting.print_rapport(nulmeting.meet(dagen=args.dagen, administratie_ids=ids), dagen=args.dagen)
    return 0


def _duplicaat_extern_rapport(args: argparse.Namespace) -> int:
    """16-09 (Zenvoices-casus): LEES-ONLY rapport "mogelijk eerder dubbel geboekt" — geboekte module-facturen ↔ alle
    RLZ-inkoopfacturen in het venster, genormaliseerd op crediteur-identiteit + referentie. Geen writes."""
    from app.documenten import duplicaat_extern_rapport

    ids: list[uuid.UUID] | None = None
    if args.administratie:
        treffers = _zoek_administraties(args.administratie)
        if len(treffers) != 1:
            print(
                f"--administratie {args.administratie!r}: {len(treffers)} treffer(s) — precies één vereist: "
                + ", ".join(f"{n} ({i})" for i, n in treffers),
                file=sys.stderr,
            )
            return 2
        ids = [treffers[0][0]]
    rapporten = duplicaat_extern_rapport.rapport(dagen=args.dagen, administratie_ids=ids)
    duplicaat_extern_rapport.print_rapport(rapporten, dagen=args.dagen)
    return 0


def _omzet_binder_rapport(args: argparse.Namespace) -> int:
    """Blok C (Peter 16-09, Van Boxtel): LEES-ONLY rapport — (a) door de module geboekte Receipts waarvan de
    RLZ-categorie niet onder binder Inkomsten staat, (b) geboekte inkoopfacturen die omzet zijn (alle regels op
    omzetrekeningen; mét --met-pdf óók herkende omzetbron-PDF's), beide mét factuurdatum en de stand van de
    btw-aangiftepoort. Geen writes."""
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.omzet import inkoopstroom
    from app.omzet.models import OmzetBoeking, OmzetBoekingStatus
    from app.rlz.aangifte import AangiftePoort
    from app.rlz.client import RlzApiError
    from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

    ids: list[uuid.UUID] | None = None
    if args.administratie:
        treffers = _zoek_administraties(args.administratie)
        if len(treffers) != 1:
            print(
                f"--administratie {args.administratie!r}: {len(treffers)} treffer(s) — precies één vereist",
                file=sys.stderr,
            )
            return 2
        ids = [treffers[0][0]]
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        q = select(Administratie).where(Administratie.actief.is_(True))
        if ids:
            q = q.where(Administratie.id.in_(ids))
        administraties = [(a.id, a.naam) for a in session.scalars(q.order_by(Administratie.naam))]
    totaal_a = totaal_b = 0
    print(f"Omzet-binder-rapport — {len(administraties)} administratie(s), venster {args.dagen} dagen. LEES-ONLY.")
    for aid, naam in administraties:
        with scoped_session(aid) as session:
            boekingen = session.scalars(
                select(OmzetBoeking).where(
                    OmzetBoeking.administratie_id == aid, OmzetBoeking.status == OmzetBoekingStatus.GEBOEKT.value
                )
            ).all()
            treffers_b = inkoopstroom.geboekte_kassarapporten_in_inkoopstroom(
                session, administratie_id=aid, dagen=args.dagen, met_pdf=args.met_pdf
            )
        if not boekingen and not treffers_b:
            continue
        print(f"\n{naam} ({aid})")
        try:
            rlz_admin_id = rlz_admin_id_voor(aid)
            client = client_voor_rlz_admin_id(rlz_admin_id).for_administration(rlz_admin_id)
        except (GeenRlzCredentials, Exception) as exc:  # noqa: BLE001
            print(f"  RLZ niet leesbaar ({exc}) — alleen lokale signalen")
            client = None
        poort = AangiftePoort(client) if client is not None else None
        try:
            for b in boekingen[: args.max_per_administratie]:
                if client is None:
                    break
                try:
                    doc = client.get(
                        f"SalesInvoices/{b.verkoop_rlz_id}",
                        params={"$expand": "DocumentCategory($expand=DocumentBinder)"},
                    )
                except RlzApiError as exc:
                    print(
                        f"  ? Receipt {b.verkoop_boekstuknummer or b.verkoop_rlz_id}: niet leesbaar ({exc.status_code})"
                    )
                    continue
                cat = doc.get("DocumentCategory") or {}
                binder = (cat.get("DocumentBinder") or {}).get("Description") if isinstance(cat, dict) else None
                if binder and binder.casefold() != "inkomsten":
                    totaal_a += 1
                    toets = poort.toets_boekdatum(b.periode_eind, kant="verkoop") if poort else None
                    stand = "open" if toets and toets.toegestaan else (toets.reden if toets else "onbekend")
                    print(
                        f"  A {b.verkoop_boekstuknummer or b.verkoop_rlz_id}  periode "
                        f"{b.periode_start}..{b.periode_eind}  binder={binder!r} categorie={cat.get('Name')!r}  "
                        f"aangifte={stand}"
                    )
            for t in treffers_b:
                totaal_b += 1
                toets = poort.toets_boekdatum(t.factuurdatum, kant="inkoop") if (poort and t.factuurdatum) else None
                stand = "open" if toets and toets.toegestaan else (toets.reden if toets else "onbekend")
                print(
                    f"  B {t.boekstuknummer or str(t.document_id)[:8]}  {t.factuurdatum or '?'}  {t.signaal:<16} "
                    f"regels {t.regels_op_omzet}/{t.regels_totaal}  aangifte={stand}  {t.document_id}  {t.bestandsnaam}"
                )
        finally:
            if client is not None:
                client.close()
    print(
        f"\nTotaal: A (Receipt niet onder Inkomsten) {totaal_a} · B (omzet als inkoopfactuur) {totaal_b}. "
        "Herstel B: Inzicht › Reconciliatie › 'Herboeken als omzet…' (storno + kassarapport, aangiftepoort)."
    )
    return 0


def _omzet_stores_migreren(args: argparse.Namespace) -> int:
    """Data-stap 0151 (Peter 16-09 avond): `bron_instellingen.stores` per administratie → platformbrede
    `omzet_store_routering`. Default dry-run (lijst), `--schrijf` maakt de rijen aan; idempotent (bestaat_al), een store
    die al aan een ÁNDERE administratie hangt = conflict (nooit overschrijven — Beheerder beslist in het Stores-blok)."""
    from app.omzet.bronnen import stores as stores_service

    regels = stores_service.migreer_uit_bron_instellingen(schrijf=bool(args.schrijf))
    stores_service.print_migratie(regels, schrijf=bool(args.schrijf))
    return 0


def _kassarapporten_in_inkoopstroom(args: argparse.Namespace) -> int:
    """Blok A2 ProfX (Peter 16-09): LEES-ONLY rapport van inkoopfactuur-documenten die op inhoud een ProfX
    Journaal/Margerapport zijn (verkeerd geclassificeerd vóór de herkenning-op-inhoud). Geen writes."""
    from app.omzet.bronnen import inkoopstroom_rapport

    ids: list[uuid.UUID] | None = None
    if args.administratie:
        treffers = _zoek_administraties(args.administratie)
        if len(treffers) != 1:
            print(
                f"--administratie {args.administratie!r}: {len(treffers)} treffer(s) — precies één vereist: "
                + ", ".join(f"{n} ({i})" for i, n in treffers),
                file=sys.stderr,
            )
            return 2
        ids = [treffers[0][0]]
    rapporten = inkoopstroom_rapport.rapport(dagen=args.dagen, administratie_ids=ids)
    inkoopstroom_rapport.print_rapport(rapporten, dagen=args.dagen)
    return 0


def _kassarapport_autotype_nazorg(args: argparse.Namespace) -> int:
    """Nazorg (Peter 19-09, eenmalig ná deploy via de job-image): álle werkvoorraad-documenten mét een eenduidige
    parser-treffer die nog als inkoopfactuur staan alsnog automatisch omzetten (tijdlijn + audit per document, één
    rapportregel per administratie). --dry-run = 0 writes; idempotent (een tweede echte run vindt niets meer)."""
    from app.db.models import Administratie
    from app.db.session import scoped_session  # nameting 19-09 poging 2: ontbrak → NameError op de kantoorbrede tak
    from app.omzet import autotype

    if args.administratie:
        treffers = _zoek_administraties(args.administratie)
        if len(treffers) != 1:
            print(
                f"--administratie {args.administratie!r}: {len(treffers)} treffer(s) — precies één vereist: "
                + ", ".join(f"{n} ({i})" for i, n in treffers),
                file=sys.stderr,
            )
            return 2
        administraties = treffers
    else:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            administraties = [
                (a.id, a.naam)
                for a in session.scalars(
                    select(Administratie).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
                ).all()
            ]
    label = " [dry-run — 0 writes]" if args.dry_run else ""
    tot_verwacht = tot_gedaan = 0
    tot_over: dict[str, int] = {}
    for aid, naam in administraties:
        uit = autotype.verwerk_werkvoorraad(aid, dry_run=bool(args.dry_run))
        if not uit.documenten:
            continue
        tot_verwacht += uit.verwacht
        tot_gedaan += uit.gedaan + uit.zou_doen
        for r, n in uit.overgeslagen.items():
            tot_over[r] = tot_over.get(r, 0) + n
        over = ", ".join(f"{r} {n}" for r, n in sorted(uit.overgeslagen.items())) or "—"
        print(
            f"{naam}: {uit.verwacht} kandidaat/kandidaten, "
            f"{'zou omzetten' if args.dry_run else 'omgezet'} {uit.gedaan + uit.zou_doen}, overgeslagen {over}"
        )
        for d in uit.documenten:
            extra = f" ({d.reden}{f' {d.correcties}×' if d.correcties else ''})" if d.uitkomst == "overgeslagen" else ""
            print(f"  {d.uitkomst:12} {d.bestandsnaam} · {autotype.bron_leesbaar(d.bron)} · {d.document_id}{extra}")
    over_tot = ", ".join(f"{r} {n}" for r, n in sorted(tot_over.items())) or "—"
    print(
        f"kassarapport-autotype-nazorg{label}: {len(administraties)} administratie(s), {tot_verwacht} kandidaat/"
        f"kandidaten, {'zou omzetten' if args.dry_run else 'omgezet'} {tot_gedaan}, overgeslagen {over_tot}"
    )
    return 0


def _checks_cache_legen(args: argparse.Namespace) -> int:
    """Nazorg (BUG Peter 21-09, checks-cache-invalidatie op de bron; eenmalig ná deploy via de job-image): álle nog
    geldige rijen in `boekhouding.check_extern_cache` ongeldig markeren (prefix op de vingerafdruk — de tabel heeft geen
    DELETE-grant), zodat rapporten van vóór de fix niet tot 15 min lang een verouderde vertrouwde IBAN-set dragen. De
    volgende checks-run per document draait dan gewoon vers en cachet opnieuw. --dry-run = 0 writes; idempotent."""
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.documenten import checks_extern

    if not args.administratie and not args.alles:
        print("checks-cache-legen: geef --administratie <UUID|NAAMDEEL> óf --alles", file=sys.stderr)
        return 2
    if args.administratie:
        treffers = _zoek_administraties(args.administratie)
        if len(treffers) != 1:
            print(
                f"--administratie {args.administratie!r}: {len(treffers)} treffer(s) — precies één vereist: "
                + ", ".join(f"{n} ({i})" for i, n in treffers),
                file=sys.stderr,
            )
            return 2
        administraties = treffers
    else:
        with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
            administraties = [
                (a.id, a.naam)
                for a in session.scalars(
                    select(Administratie).where(Administratie.actief.is_(True)).order_by(Administratie.naam)
                ).all()
            ]
    label = " [dry-run — 0 writes]" if args.dry_run else ""
    totaal_geldig = totaal_gedaan = 0
    for aid, naam in administraties:
        with scoped_session(aid, actor_id=SYSTEEM_ACTOR_ID) as session:
            geldig = checks_extern.tel_geldig(session, administratie_id=aid)
            gedaan = 0 if args.dry_run else checks_extern.maak_alles_ongeldig(session, administratie_id=aid)
        totaal_geldig += geldig
        totaal_gedaan += gedaan
        if geldig:
            print(f"{naam}: {geldig} geldig, {gedaan} ongeldig gemaakt")
    print(
        f"checks-cache-legen{label}: {len(administraties)} administratie(s), {totaal_geldig} geldig, "
        f"{totaal_gedaan} ongeldig gemaakt"
    )
    return 0


def _duplicaat_status_backfill(args: argparse.Namespace) -> int:
    """Blok 3 (fixrun 08-09, feedback Peter): eenmalige data-stap ná migratie 0122 — legacy-rijen die vóór deze
    deploy als duplicaat naar `afgewezen` zijn afgevoerd (open afwijzing mét kruisverwijzing, exact het
    archief-filter-criterium) krijgen de eigen terminale status `afgevoerd_duplicaat`, via de statusmachine mét
    tijdlijn + audit (systeem-actor). Geen RLZ/Odoo-calls. --dry-run schrijft niets; idempotent."""
    from app.documenten import duplicaat_afvoer

    administratie_filter: uuid.UUID | None = None
    if args.administratie:
        try:
            administratie_filter = uuid.UUID(args.administratie)
        except ValueError:
            print(f"Ongeldig --administratie-id: {args.administratie!r}", file=sys.stderr)
            return 2
    uitkomsten = duplicaat_afvoer.status_backfill(dry_run=args.dry_run, administratie_id=administratie_filter)
    label = " [dry-run]" if args.dry_run else ""
    tot_gevonden = sum(u.legacy_gevonden for u in uitkomsten)
    tot_omgezet = sum(u.omgezet for u in uitkomsten)
    tot_fouten = sum(sum(u.fouten.values()) for u in uitkomsten)
    print(
        f"duplicaat-status-backfill{label}: {len(uitkomsten)} administratie(s), {tot_gevonden} legacy-rij(en) "
        f"(afgewezen mét duplicaat-kruisverwijzing), {tot_omgezet} omgezet naar afgevoerd_duplicaat"
        + (f", {tot_fouten} fout(en)" if tot_fouten else "")
    )
    for u in uitkomsten:
        if not u.legacy_gevonden and not u.fouten:
            continue
        print(f"  {u.naam}: {u.legacy_gevonden} gevonden, {u.omgezet} omgezet")
        for reden, n in sorted(u.fouten.items(), key=lambda kv: -kv[1]):
            print(f"    fout {n}× {reden}")
    return 0 if not tot_fouten else 1


def _app_passkeys_markeren(args: argparse.Namespace) -> int:
    """App-auth zonder passkey (besluit Peter 08-09, blok 2): markeert alle passkey-rijen van gebruikers met een
    externe app-rol als 'niet meer gebruikt' (`niet_meer_gebruikt_op`), audit per rij (systeem-actor). NIETS wordt
    verwijderd en `ingetrokken_op` blijft ongemoeid — bestaande sessies op oude toestellen lopen door tot hun TTL.
    --dry-run telt alleen. Idempotent (al gemarkeerde rijen worden overgeslagen)."""
    from app.auth import app_activatie

    per_rol = app_activatie.markeer_app_passkeys(dry_run=args.dry_run)
    label = " [dry-run]" if args.dry_run else ""
    totaal = sum(per_rol.values())
    print(
        f"app-passkeys-markeren{label}: {totaal} passkey-rij(en) van app-gebruikers gemarkeerd als niet meer gebruikt"
    )
    for rol, n in sorted(per_rol.items()):
        print(f"  {rol}: {n}")
    if not totaal:
        print("  (niets te markeren)")
    return 0


def _periode_backfill(args: argparse.Namespace) -> int:
    """Blok 7 bundel 08-09 (BESLISSINGEN "FACTUURPERIODE WEEKNIVEAU" beslispunt 4): vult de factuurperiode-
    kolommen (migratie 0120) van GEBOEKTE documenten mét boekvoorstel maar zonder periode — AI-veld `periode` uit
    het opgeslagen veldvoorstel als het er is, anders de ISO-week van de factuurdatum (exact de datalaag-regel).
    Een gevulde stand (ook `mens`) wordt nooit overschreven; tijdlijn + audit per gewijzigd document (systeem-
    actor); geen RLZ/Odoo/AI. --dry-run toetst alles en schrijft niets; --alle-statussen neemt ook open documenten
    mee; cijfers per administratie."""
    from app.documenten import periode_backfill

    administratie_filter: uuid.UUID | None = None
    if args.administratie:
        try:
            administratie_filter = uuid.UUID(args.administratie)
        except ValueError:
            print(f"Ongeldig --administratie-id: {args.administratie!r}", file=sys.stderr)
            return 2
    uitkomsten = periode_backfill.backfill(
        dry_run=args.dry_run, administratie_id=administratie_filter, alle_statussen=args.alle_statussen
    )
    label = " [dry-run]" if args.dry_run else ""
    tot = {
        "toetsbaar": sum(u.toetsbaar for u in uitkomsten),
        "al_gevuld": sum(u.al_gevuld for u in uitkomsten),
        "te_vullen": sum(u.te_vullen for u in uitkomsten),
        "ai": sum(u.uit_ai_veld for u in uitkomsten),
        "terugval": sum(u.uit_terugval for u in uitkomsten),
        "overgeslagen": sum(sum(u.overgeslagen.values()) for u in uitkomsten),
        "gevuld": sum(u.gevuld for u in uitkomsten),
    }
    print(
        f"periode-backfill{label}: {len(uitkomsten)} administratie(s), {tot['toetsbaar']} toetsbaar, "
        f"{tot['al_gevuld']} al gevuld, {tot['te_vullen']} te vullen ({tot['ai']} uit AI-veld, "
        f"{tot['terugval']} uit terugval), {tot['overgeslagen']} overgeslagen, {tot['gevuld']} gevuld"
    )
    for u in uitkomsten:
        if not u.toetsbaar:
            continue
        print(
            f"  {u.naam}: {u.toetsbaar} toetsbaar, {u.al_gevuld} al gevuld (waarvan {u.mens} mens), "
            f"{u.uit_ai_veld} uit AI-veld, {u.uit_terugval} uit terugval, {u.gevuld} gevuld"
        )
        for reden, n in sorted(u.overgeslagen.items(), key=lambda kv: -kv[1]):
            print(f"    overgeslagen {n}× {reden}")
        for regel in u.regels[:25]:
            print(f"    - {regel}")
        if len(u.regels) > 25:
            print(f"    … en {len(u.regels) - 25} meer")
    return 0


def _toewijzing_regels_opschonen(args: argparse.Namespace) -> int:
    """Data-nazorg afzender-geheugen (blok D 02-09): actieve afzender-regels op een config-uitgesloten
    kantoor-/doorstuurdomein óf met een meerduidige historie (≥ 3 doelen) deactiveren mét audit —
    nooit verwijderen; tenaamstelling-regels blijven staan. --dry-run rapporteert alleen."""
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.intake.toewijzing import schoon_afzender_regels_op

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        telling = schoon_afzender_regels_op(session, actor_id=SYSTEEM_ACTOR_ID, dry_run=args.dry_run)
    label = " [dry-run]" if args.dry_run else ""
    print(
        f"toewijzing-regels-opschonen{label}: {telling.sleutels_bekeken} afzender-sleutels bekeken, "
        f"{telling.gedeactiveerd} regel(s) gedeactiveerd ({telling.reden_uitgesloten_domein} uitgesloten domein, "
        f"{telling.reden_meerduidig} meerduidig)"
    )
    for regel in telling.details:
        print(f"  - {regel}")
    return 0


def _bewaking_probe(args: argparse.Namespace) -> int:
    """Entrypoint van de kwartier-job rlz-bewaking (best-practice-besluit 1, 31-08): draai alle
    probes, leg de statusrij vast en verstuur/sluit alerts. Een falende PROBE is een uitkomst
    (vastgelegd + eigen SMTP-alert bij 2 op rij), géén job-failure — exit 1 alleen als de
    bewaking zélf niet kon draaien (dan bijt de F3.2-job-failure-alert als vangnet)."""
    from app.bewaking.service import voer_probes_uit

    statussen = voer_probes_uit()
    print("bewaking-probe: " + ", ".join(f"{soort}={status}" for soort, status in statussen.items()))
    return 0


def _deploy_smoketest(args: argparse.Namespace) -> int:
    """Post-deploy-smoketest (best-practice-besluit 1, 31-08 punt 4 — geen stille kapotte
    deploys meer): AI-schema-zelftest (union-limiet, de 30-08-klasse), DB + migratieversie en
    de mailkanaal-config. Draait als one-off Cloud Run-job ná de revisie-switch (deploy.yml);
    élke fout = exit 1 = de deploy-run is luid rood. De health-/route-checks doet de workflow
    zelf met curl (die toetsen de nieuwe revisie van buitenaf)."""
    from app.berichten import mail
    from app.db import session as db_session
    from app.db.migratie_guard import _huidige_migratie_in_database, _laatste_migratie_in_repo
    from app.extractie.schema_poort import controleer_live_schemas

    fouten: list[str] = []
    overtredingen = controleer_live_schemas()
    if overtredingen:
        fouten.append("AI-schema-zelftest: " + "; ".join(overtredingen))
    try:
        huidige = _huidige_migratie_in_database(db_session.engine)
        laatste = _laatste_migratie_in_repo()
        if huidige != laatste:
            fouten.append(f"migratieversie: DB={huidige} ≠ repo-head={laatste}")
    except Exception as exc:  # noqa: BLE001 — élke DB-fout hoort de deploy rood te maken
        fouten.append(f"database onbereikbaar: {exc}")
    if not mail.is_geconfigureerd():
        fouten.append("mailkanaal niet geconfigureerd (BERICHTEN_SMTP_*) — alerts en meldingen liggen plat")
    fouten.extend(_smoketest_deploy_drift())
    fouten.extend(_smoketest_leesreplica())
    if fouten:
        for fout in fouten:
            print(f"deploy-smoketest FOUT: {fout}", file=sys.stderr)
        return 1
    print(
        "deploy-smoketest: alles groen (schema-zelftest, DB/migratieversie, mailkanaal job + service, "
        "service ↔ jobs zelfde beeld, leesreplica)"
    )
    return 0


def _smoketest_leesreplica() -> list[str]:
    """Leesreplica afronden 17-09 (Feiten eerst): is LEES_CLOUD_SQL_VERBINDING/LEES_DATABASE_URL gezet, dan hoort `SELECT 1`
    op de replica te werken in een READ ONLY-transactie — anders geeft `POST /lezen/sql` 503 terwijl de deploy groen lijkt.
    Niet geconfigureerd = overgeslagen mét melding (lokaal/dev)."""
    from sqlalchemy import text

    from app.config import settings
    from app.lezen import service as lees_service

    if not (settings.lees_database_url or "").strip():
        print("deploy-smoketest: leesreplica-toets overgeslagen (LEES_DATABASE_URL/LEES_CLOUD_SQL_VERBINDING leeg)")
        return []
    try:
        with lees_service.lees_engine().connect() as conn:
            conn.execute(text("BEGIN READ ONLY"))
            een = conn.execute(text("SELECT 1")).scalar()
            conn.execute(text("ROLLBACK"))
        if een != 1:
            return [f"leesreplica: SELECT 1 gaf {een!r}"]
    except Exception as exc:  # noqa: BLE001 — elke replica-fout hoort de deploy rood te maken
        return [f"leesreplica onbereikbaar (socket/IAM/URL): {exc}"]
    print("deploy-smoketest: leesreplica antwoordt (SELECT 1, READ ONLY)")
    return []


def _smoketest_deploy_drift() -> list[str]:
    """Ochtendrun 11-09 blok 2.1: direct ná de deploy móeten service en álle jobs hetzelfde beeld dragen — zónder
    gratieperiode (de F3-lus is dan al gelopen; deze job is de laatste stap). Geen BEWAKING_SERVICE_RESOURCE = de
    toets kan niet en zegt dat (lokaal/dev); een leesfout (403 = roles/run.viewer ontbreekt op run-jobs@) is een
    FOUT — een ontbrekende harde voorwaarde maakt de deploy zichtbaar rood, nooit stil groen."""
    from datetime import UTC, datetime, timedelta

    from app.bewaking import deploy_drift
    from app.config import settings

    resource = settings.bewaking_service_resource
    if not resource:
        print("deploy-smoketest: deploy-drift-toets overgeslagen (geen BEWAKING_SERVICE_RESOURCE)")
        return []
    try:
        stand = deploy_drift.lees_stand(service_resource=resource, token=deploy_drift.metadata_token())
    except Exception as exc:  # noqa: BLE001 — élke leesfout hoort de deploy rood te maken
        return [f"deploy-drift-toets onmogelijk (leesrecht roles/run.viewer op run-jobs@?): {exc}"]
    oordeel = deploy_drift.beoordeel(stand, nu=datetime.now(UTC), gratie=timedelta(0))
    print(f"deploy-smoketest: {deploy_drift.samenvatting(stand, oordeel)}")
    fouten: list[str] = []
    if oordeel.achter:
        fouten.append(f"service en jobs niet op hetzelfde beeld: {deploy_drift.samenvatting(stand, oordeel)}")
    fouten.extend(_smoketest_service_mailkanaal(resource))
    return fouten


def _smoketest_service_mailkanaal(resource: str) -> list[str]:
    """Peter 16-09 (BESLISSINGEN "DEPLOY — VOLLEDIGE ENVSET IN ÉÉN STAP"): de SERVICE-template hoort ná de deploy de
    mailconfig te dragen (BERICHTEN_SMTP_HOST/-GEBRUIKER + secret BERICHTEN_SMTP_WACHTWOORD). Tot 16-09 zette een latere
    `services update`-stap die pas terug → een run die daarvóór strandde liet de service zonder mail achter ("Mailkanaal
    niet geconfigureerd" bij de herstel-link). Lees-only via de Cloud Run Admin API (zelfde token als de drift-toets);
    een leesfout is een FOUT (nooit stil groen)."""
    from app.bewaking import deploy_drift

    try:
        config = deploy_drift.lees_service_config(service_resource=resource, token=deploy_drift.metadata_token())
    except Exception as exc:  # noqa: BLE001 — élke leesfout hoort de deploy rood te maken
        return [f"mailkanaal-toets op de service onmogelijk: {exc}"]
    ontbrekend = deploy_drift.mailkanaal_ontbrekend(config)
    if ontbrekend:
        return [
            "service-revisie zonder mailkanaal-config (deploy.yml service-stap): ontbreekt " + ", ".join(ontbrekend)
        ]
    print(
        "deploy-smoketest: service-template draagt de mailkanaal-config "
        f"({len(config.envs)} envs, {len(config.secrets)} secrets)"
    )
    return []


def _deploy_mislukt(args: argparse.Namespace) -> int:
    """Ochtendrun 11-09 blok 2.2: de deploy-workflow roept dit bij `if: failure()` aan via de bestaande job
    rlz-bewaking (zelfde SMTP-config, geen secret in GitHub Actions) — één mail naar het beheer
    (`reconciliatie_beheer_ontvangers`) met commit, run-URL en wat er dan NIET staat (jobs mogelijk op oud beeld).
    Zeven rode deploys #173–#179 (09/10-09) zag niemand; dit is het vangnet vóór de deploy-drift-probe."""
    from app.berichten import mail
    from app.config import settings

    # Nazorg 15-09: de beheer-lijst is default leeg (systeemmail uit), maar een rode deploy is een ALERT, geen
    # dagrapport → terugval op het bewakingskanaal (`bewaking_alert_ontvanger`), zodat dit vangnet nooit stil wegvalt.
    ontvangers = [o.strip() for o in (settings.reconciliatie_beheer_ontvangers or "").split(",") if o.strip()]
    if not ontvangers:
        ontvangers = [o.strip() for o in (settings.bewaking_alert_ontvanger or "").split(",") if o.strip()]
    sha = (args.sha or "?")[:7]
    onderwerp = f"⛔ RLZ-deploy mislukt ({sha})"
    tekst = (
        f"De deploy-workflow voor commit {args.sha or '?'} is ROOD afgebroken.\n\n"
        f"Run: {args.run_url or '(geen URL meegegeven)'}\n"
        f"Stap/branch: {args.stap or 'onbekend'}\n\n"
        "Gevolg: de Cloud Run-service en/of de F3-jobs staan mogelijk niet op het nieuwe beeld (de jobs worden ná de "
        "service bijgewerkt). De bewakingsprobe 'deploy_drift' meldt het blijvend zolang service en jobs uiteenlopen; "
        "de eerstvolgende groene push herstelt alles via de pijplijn — jobs nooit handmatig bijwerken "
        "(regel 08-09).\n\n"
        "Administratiekantoor Nijenhuis — automatisch bericht (deploy.yml → rlz-bewaking deploy-mislukt)"
    )
    if not ontvangers:
        print(
            "deploy-mislukt FOUT: geen reconciliatie_beheer_ontvangers én geen bewaking_alert_ontvanger", file=sys.stderr
        )
        return 1
    if not mail.is_geconfigureerd():
        print("deploy-mislukt FOUT: mailkanaal niet geconfigureerd (BERICHTEN_SMTP_*)", file=sys.stderr)
        return 1
    fouten = 0
    for naar in ontvangers:
        try:
            mail.verzend_mail(naar=naar, onderwerp=onderwerp, tekst=tekst)
            print(f"deploy-mislukt: melding verstuurd naar {naar}")
        except mail.MailFout as exc:
            fouten += 1
            print(f"deploy-mislukt FOUT: mail naar {naar} mislukt: {exc}", file=sys.stderr)
    return 1 if fouten else 0


def _sync_alles(args: argparse.Namespace) -> int:
    """Nachtelijke sync-entrypoint (fase-vervolg: Cloud Scheduler -> Cloud Run job roept dit
    commando aan). Eén administratie zonder werkende .env-credentials laat de rest niet
    stoppen — zie sync_alle_administraties()."""
    resultaten = sync_service.sync_alle_administraties()
    fouten = 0
    overgeslagen = 0
    for administratie_id, resultaat in resultaten.items():
        if isinstance(resultaat, GeenRlzCredentials):
            # Niet-onboarded (geen credential in store noch .env, bv. de cloud-seed-
            # testadministratie) — zichtbaar overslaan, telt niet als fout (F3: de nachtelijke
            # cloud-job mag hier niet permanent rood op staan; échte fouten blijven exit 1).
            overgeslagen += 1
            print(f"OVERGESLAGEN {administratie_id}: {resultaat}")
            continue
        if isinstance(resultaat, str):
            fouten += 1
            print(f"FOUT  {administratie_id}: {resultaat}", file=sys.stderr)
            continue
        # Administratienaam volgt de bron (15-09, 0144): gevolgd | gelijk | afwijkend_mens | bezet | onbekend —
        # meetrecept Zilverduynen: grep "naam=gevolgd" in Cloud Logging (job rlz-sync).
        print(
            f"OK    {administratie_id}: ledgers={resultaat.ledgers}, taxrates={resultaat.taxrates}, "
            f"vendors={resultaat.vendors}, projects={resultaat.projects}, naam={resultaat.naam or 'niet gelezen'}"
        )
    kern = f"{len(resultaten) - fouten - overgeslagen}/{len(resultaten)} administraties gesynchroniseerd."
    if overgeslagen:
        kern += f" ({overgeslagen} overgeslagen: geen credential geregistreerd)"
    print(f"\n{kern}")

    # Intercompany (blok A 16-09): identiteit per administratie (één AdministrationSettings-/res.company-call) →
    # IC-relaties (crediteuren uit de cache, debiteuren één Customers-leesroute) → RC-koppelingen (puur code). Elke stap
    # apart gevangen: een fout is een zichtbare regel, nooit een stop van de nachtelijke sync.
    from app.intercompany import cli_stap as intercompany_cli_stap

    print("\nIntercompany — identiteiten, relaties en rekening-courant-koppelingen (alle actieve administraties):")
    intercompany_cli_stap.rapporteer_afleiding()

    # Blok 1 doorbelasting-herkoppeling (Peter 12-09/16-09): whitelist-rijen zonder doel-administratie dagelijks op
    # genormaliseerde naam koppelen (exact) of als LET-OP melden (bijna-match/meerdere) — nooit raden. Uitkomst =
    # regels + audit `doorbelasting_herkoppeling_run` (teller); een omgevallen administratie = exit 1 van de job.
    from app.doorbelasting.herkoppeling import rapporteer_herkoppeling

    print("\nDoorbelasting — herkoppeling doelentiteiten (whitelist zonder doel):")
    herkoppel_exit = rapporteer_herkoppeling()

    # Groepssaldi (Peter 16-09): nachtelijke stand debiteuren/crediteuren (bruto + intercompany) per administratie in
    # een actieve groep → cache `groep_saldo_stand` voor de kaart op de klantenlijst ("stand van vannacht"). Lees-only
    # richting RLZ/Odoo; per administratie zichtbaar ok/niet-ok, nooit een stop van de sync.
    from app.groepen import saldi as groep_saldi

    print("\nGroepssaldi debiteuren/crediteuren (administraties in een actieve groep):")
    try:
        _rapporteer_groep_saldi_nacht(groep_saldi.meet_en_schrijf_alle())
    except Exception as exc:  # noqa: BLE001 — zichtbare regel, de sync loopt door
        print(f"  FOUT groepssaldi-stap: {exc}", file=sys.stderr)

    # Vervolg 14-09 (migratie 0143): btw-default per grootboekrekening uit de eigen boekingshistorie — puur code, geen
    # RLZ-calls; direct ná de Ledgers-sync zodat een nieuwe/verdwenen rekening dezelfde nacht meegaat. Eigen telling.
    from app.geheugen import grootboek_btw_historie

    print("\nBtw-default uit historie per grootboekrekening (alle actieve administraties):")
    btw_historie_exit = _rapporteer_btw_historie(grootboek_btw_historie.herbereken_alle())

    # BLOK 1 (besluit Peter 08-09, "bank-sync automatisch, geen knoppen"): de dagelijkse sync ververst óók
    # de bankcache van ÁLLE actieve administraties (07:00, ná RLZ's eigen bankimport) — tot 08-09 kwamen
    # mutaties alleen bij het openen van het bankscherm (29 van 33 administraties "nog nooit gesynchroniseerd").
    # Zelfde motor als de on-demand run, mét bank_sync_run-spoor (bron sync_alles); geen RLZ-verbinding
    # (geen credential / Odoo) = zichtbaar OVERGESLAGEN, geen fout; eigen fouten-telling (exit 1).
    from app.bank import sync_run as bank_sync_run

    print("\nBank-sync (alle actieve administraties):")
    bank_exit = _rapporteer_bank_runs(bank_sync_run.sync_alle_via_runs())

    # Automatisering-first (opdracht 23-08 punt 3): de dagelijkse sync ververst óók de
    # projectcijfers voor de uren-&-meerwerk-administraties — de knop blijft de handmatige
    # verversing. Eigen fouten-telling: een kapotte cijfers-sync maakt de job zichtbaar rood.
    from app.projecten.cijfers_run import sync_alle_via_runs

    print("\nProjectcijfers-sync (uren-&-meerwerk-administraties):")
    cijfers_exit = _rapporteer_cijfers_runs(sync_alle_via_runs())

    # Voorraad-uitstroom uit RLZ-verkoopfacturen (blok A 29-08): dagelijkse leesroute voor de
    # administraties mét de voorraad-opt-in — read-only, eigen fouten-telling (zichtbaar rood).
    from app.voorraad import rlz_uitstroom

    print("\nVoorraad-uitstroom RLZ-/Odoo-verkoopfacturen (voorraad-administraties):")
    voorraad_exit = _rapporteer_voorraad_rlz(rlz_uitstroom.sync_alle_voorraad_administraties())
    # Terugkerende-facturen-signaal (blok B 30-08): dagelijks meeliftend, puur code, geen RLZ-calls.
    from app.terugkerend import service as terugkerend_service

    print("\nTerugkerende-facturen-signaal (alle actieve administraties):")
    terugkerend_exit = _rapporteer_terugkerend(terugkerend_service.herbereken_alle())
    # Autoboek-kandidaten-motor (blok B 01-09): dagelijks meeliftend, puur code, geen RLZ-calls;
    # nomineert per (administratie, leverancier) — aanzetten blijft een menselijk besluit.
    from app.autoboek_kandidaten import service as kandidaten_service

    print("\nAutoboek-kandidaten (alle actieve administraties):")
    kandidaten_exit = _rapporteer_autoboek_kandidaten(kandidaten_service.herbereken_alle())
    # Crediteuren-dubbelen auto-afhandeling (blok B13 07-09): eenduidige clusters (identieke naam/IBAN, geen
    # conflicterend KvK/btw, verliezers ≤ N boekingen) handelt het systeem dagelijks af — verliezers worden in de
    # module onbruikbaar, geheugen/kenmerk verhuizen, audit, terugdraaibaar. Puur code, geen RLZ-calls. De
    # RLZ-werklijst-hertoets van 03-09 (N RLZ-GETs per dag) is vervallen: RLZ-archivering is geen doel meer.
    from app.crediteuren import afhandeling as crediteuren_afhandeling

    print("\nCrediteuren-dubbelen auto-afhandeling (eenduidige clusters, alle actieve administraties):")
    werklijst_exit = _rapporteer_crediteuren_dubbelen_auto(
        crediteuren_afhandeling.auto_afhandelen(None, dry_run=False)
    )
    # Projectverdeling-hercontrole (blok C 04-09, ⑥): maandelijks meeliftend (1e–7e óf ná verse cijfers) — herrekent
    # geboekte pro-rato-verdelingen tegen de actuele omzetstand; puur code, geen RLZ-/Odoo-calls.
    from app.projectverdeling import hercontrole as projectverdeling_hercontrole

    print("\nProjectverdeling-hercontrole (geboekte pro-rato-verdelingen, alle actieve administraties):")
    projectverdeling_exit = _rapporteer_projectverdeling(projectverdeling_hercontrole.herbereken_alle())
    # Werkvoorraad-tellers-cache (blok 6 11-09): nachtelijke volledige herberekening NÁ de signaalmotoren hierboven
    # (terugkerend/voorraad/planning schrijven hun signalen eerst), zodat de klantenlijst 's ochtends exact klopt.
    from app.werkvoorraad.cli_cmd import rapporteer_herrekenen

    print("\nWerkvoorraad-tellers herrekenen (alle actieve administraties):")
    tellers_exit = rapporteer_herrekenen(dry_run=False)
    return (
        1
        if fouten
        or btw_historie_exit
        or bank_exit
        or cijfers_exit
        or voorraad_exit
        or terugkerend_exit
        or kandidaten_exit
        or werklijst_exit
        or projectverdeling_exit
        or herkoppel_exit
        or tellers_exit
        else 0
    )


def _groep_saldi(args: argparse.Namespace) -> int:
    """Lees-only CLI (nameting-allowlist): live meting van één groep, tabel + totalen; `--stand` = de nachtelijke
    cache-stand i.p.v. live (21-09). Onbekende groep = leesbare melding + exit 2 (nooit stil leeg); een rode
    administratie (webfilter/fout/geen rekening) staat in de statuskolom en de exit blijft 0 — het rapport ís de
    uitkomst."""
    from datetime import date as _date

    from app.groepen import saldi

    try:
        groep = saldi.zoek_groep(args.groep)
    except saldi.GroepOnbekend as exc:
        print(f"groep-saldi: {exc}", file=sys.stderr)
        return 2
    if getattr(args, "stand", False):
        uit = saldi.lees_stand_systeem(groep)
        print(saldi.rapport_tekst(uit))
        if uit.zonder_stand:
            print(f"LET OP: {uit.zonder_stand} administratie(s) zonder nachtelijke stand (nog geen sync-alles gelopen).")
        return 0
    datum = _date.fromisoformat(args.datum) if args.datum else None
    print(saldi.rapport_tekst(saldi.meet_groep_live(groep, datum=datum)))
    return 0


def _rapporteer_groep_saldi_nacht(rapport) -> None:  # noqa: ANN001 — saldi.NachtRapport
    print(
        f"groepssaldi: {rapport.groepen} groep(en), {rapport.administraties} administratie(s) gemeten, "
        f"{rapport.ok} ok, {len(rapport.niet_ok)} niet ok"
    )
    for regel in rapport.niet_ok:
        print(f"  LET OP {regel}")


def _rapporteer_btw_historie(resultaten: dict) -> int:
    """Vervolg 14-09 (0143): één regel per administratie — rekeningen mét historie-default / mét regels zonder default /
    gewijzigd / inkoopregels in het venster; FOUT = leesbare exception-tekst (exit 1). Meetrecept in Cloud Logging
    (job rlz-sync): grep op "btw-historie " per administratie."""
    from app.geheugen.grootboek_btw_historie import HistorieRapport

    fouten = 0
    if not resultaten:
        print("OK    geen actieve administraties")
    for administratie_id, r in resultaten.items():
        if isinstance(r, HistorieRapport):
            voorbeelden = f" — o.a. {'; '.join(r.voorbeelden)}" if r.voorbeelden else ""
            print(
                f"OK    btw-historie {administratie_id}: {r.met_default}/{r.rekeningen} rekeningen mét default, "
                f"{r.zonder_default_met_regels} mét regels zonder default, {r.gewijzigd} gewijzigd, "
                f"{r.observaties} inkoopregels in het venster{voorbeelden}"
            )
        else:
            fouten += 1
            print(f"FOUT  btw-historie {administratie_id}: {r}", file=sys.stderr)
    print(f"{len(resultaten) - fouten}/{len(resultaten)} administraties afgeleid.")
    return 1 if fouten else 0


def _rapporteer_bank_runs(resultaten: dict) -> int:
    """BLOK 1 (08-09): rapportage van de nachtelijke bank-sync per administratie — één regel per administratie
    (OK / OVERGESLAGEN / FOUT), de tellers uit `bank_sync_run.resultaat`, exit 1 bij élke fout-run of exception.
    Deze regels zijn het meetrecept in Cloud Logging (job rlz-sync): grep op "bank-sync " per administratie."""
    from app.bank.sync_run import BankSyncOvergeslagen, BankSyncRunInfo

    fouten = 0
    overgeslagen = 0
    if not resultaten:
        print("OK    geen actieve administraties")
    for administratie_id, r in resultaten.items():
        if isinstance(r, BankSyncOvergeslagen):
            overgeslagen += 1
            print(f"OVERGESLAGEN bank-sync {administratie_id}: {r.reden} — {r.detail}")
        elif isinstance(r, BankSyncRunInfo):
            if r.status == "klaar":
                res = r.resultaat or {}
                print(
                    f"OK    bank-sync {administratie_id}: mutaties_nieuw={res.get('mutaties_nieuw', 0)}, "
                    f"mutaties_bijgewerkt={res.get('mutaties_bijgewerkt', 0)}, open_ververst={res.get('open_ververst', 0)}, "
                    f"afletteren_geverifieerd={res.get('afletteren_geverifieerd', 0)}, "
                    f"automatisch_afgeletterd={res.get('automatisch_afgeletterd', 0)}, "
                    f"automatisch_geboekt={res.get('automatisch_geboekt', 0)}, fouten={len(res.get('fouten') or [])}"
                )
                for fout in res.get("fouten") or []:
                    print(f"      autoflow-fout: {fout}", file=sys.stderr)
            elif r.status in ("wachtrij", "bezig"):
                # Informatief, geen fout: er loopt al een on-demand run (bankscherm open vlak vóór de job) —
                # die maakt zijn eigen status af, dubbel draaien is juist ongewenst.
                print(f"OK    bank-sync {administratie_id}: al {r.status} (run {r.run_id}) — niet dubbel gestart")
            else:
                fouten += 1
                print(f"FOUT  bank-sync {administratie_id}: {r.status} — {r.fout_reden}", file=sys.stderr)
        else:
            fouten += 1
            print(f"FOUT  bank-sync {administratie_id}: {r}", file=sys.stderr)
    kern = f"{len(resultaten) - fouten - overgeslagen}/{len(resultaten)} administraties bank-gesynchroniseerd."
    if overgeslagen:
        kern += f" ({overgeslagen} overgeslagen: geen Reeleezee-verbinding)"
    print(kern)
    return 1 if fouten else 0


def _rapporteer_projectverdeling(resultaten: dict) -> int:
    fouten = 0
    if not resultaten:
        print("OK    geen actieve administraties")
    for administratie_id, r in resultaten.items():
        if isinstance(r, dict):
            print(
                f"OK    {administratie_id}: {r['beoordeeld']} verdelingen beoordeeld, {r['herrekend']} herrekend, "
                f"{r['signalen']} signalen, {r['overgeslagen']} overgeslagen"
            )
        else:
            fouten += 1
            print(f"FOUT  {administratie_id}: {r}", file=sys.stderr)
    return 1 if fouten else 0


def _rapporteer_crediteuren_dubbelen_auto(uitkomst) -> int:
    label = " [dry-run]" if uitkomst.dry_run else ""
    if not uitkomst.administraties:
        print(f"OK    geen dubbel-clusters in scope{label}")
    for a in uitkomst.administraties:
        regel = (
            f"{a.administratie_naam}: {a.eenduidig} eenduidig, {a.twijfel} twijfel (mens), "
            f"{a.afgehandeld} afgehandeld, {a.fouten} fouten{label}"
        )
        print(f"{'FOUT ' if a.fouten else 'OK   '} {regel}", file=sys.stderr if a.fouten else sys.stdout)
        for v in a.voorbeelden:
            status = "FOUT " if v.fout else ("gedaan" if v.afgehandeld else "zou  ")
            fout = f" — {v.fout}" if v.fout else ""
            print(f"        {status} voorkeur {v.voorkeur_naam!r} ← {', '.join(v.verliezer_namen)} — {v.reden}{fout}")
    print(
        f"Totaal{label}: {uitkomst.eenduidig} eenduidig, {uitkomst.twijfel} twijfel, "
        f"{uitkomst.afgehandeld} afgehandeld, {uitkomst.fouten} fouten (run {uitkomst.run_id})"
    )
    return 1 if uitkomst.fouten else 0


def _intercompany_leverancier_markeren(args) -> int:
    """Blok 2 nachtrun 08/09-09: één geauditeerde IC-rij via de servicelaag van de Beheerder-instelling. De actor
    moet een bestaande Beheerder zijn (zelfde poort als de route); administratie en crediteur op uuid óf unieke naam."""
    from app.db.models import Administratie, Gebruiker
    from app.db.session import scoped_session
    from app.doorbelasting import intercompany_beheer
    from app.sync.models import VendorCache

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        actor = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == args.actor_email.strip().lower())).first()
        if actor is None or actor.rol != "beheerder":
            print(f"FOUT  actor {args.actor_email!r} is geen bestaande Beheerder", file=sys.stderr)
            return 2
        try:
            administratie = session.get(Administratie, uuid.UUID(args.administratie))
        except ValueError:
            administratie = session.scalars(
                select(Administratie).where(Administratie.naam == args.administratie)
            ).first()
        if administratie is None:
            print(f"FOUT  administratie {args.administratie!r} onbekend", file=sys.stderr)
            return 2
        actor_id, administratie_id, administratie_naam = actor.id, administratie.id, administratie.naam
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        try:
            vendors = [session.get(VendorCache, (uuid.UUID(args.crediteur), administratie_id))]
            vendors = [v for v in vendors if v is not None]
        except ValueError:
            vendors = list(
                session.scalars(
                    select(VendorCache).where(
                        VendorCache.administratie_id == administratie_id, VendorCache.naam == args.crediteur
                    )
                )
            )
        if len(vendors) != 1:
            print(
                f"FOUT  crediteur {args.crediteur!r} in {administratie_naam}: {len(vendors)} treffers (verwacht 1)",
                file=sys.stderr,
            )
            return 2
        vendor_id, vendor_naam = vendors[0].id, vendors[0].naam
        huidige = intercompany_beheer.lijst_intercompany_leveranciers(session, administratie_id=administratie_id)
    al_actief = any(lv.vendor_id == vendor_id for lv in huidige)
    werkwoord = "verwijderen" if args.verwijderen else "markeren"
    print(
        f"{'DRY  ' if args.dry_run else 'PLAN '} {werkwoord}: {vendor_naam} ({vendor_id}) in {administratie_naam} "
        f"({administratie_id}); actor {args.actor_email}; nu {'al' if al_actief else 'niet'} intercompany; "
        f"reden: {args.reden}"
    )
    if args.dry_run:
        return 0
    try:
        if args.verwijderen:
            intercompany_beheer.verwijder_intercompany_leverancier(
                administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor_id, reden=args.reden
            )
        else:
            intercompany_beheer.markeer_intercompany_leverancier(
                administratie_id=administratie_id, vendor_id=vendor_id, actor_id=actor_id, reden=args.reden
            )
    except intercompany_beheer.IntercompanyBeheerFout as exc:
        print(f"FOUT  {exc}", file=sys.stderr)
        return 1
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        stand = intercompany_beheer.lijst_intercompany_leveranciers(session, administratie_id=administratie_id)
    namen = ", ".join(f"{lv.naam} [{lv.bron}]" for lv in stand) or "geen"
    print(f"OK    intercompany-leveranciers in {administratie_naam} nu: {namen}")
    return 0


def _rapporteer_crediteuren_werklijst_nazorg(uitkomst) -> int:
    label = " [dry-run]" if uitkomst.dry_run else ""
    if not uitkomst.administraties:
        print(f"OK    geen open legacy-werklijst-regels{label}")
    for a in uitkomst.administraties:
        regel = (
            f"{a.administratie_naam}: {a.regels} regels, {a.om_te_zetten} om te zetten, {a.omgezet} omgezet, "
            f"{a.al_gemarkeerd} al gemarkeerd, {a.niet_meer_bestaand} niet meer bestaand, {a.fouten} fouten"
            f"{f', {a.systeem_actor_fallback}× systeem-actor (aanmaker onbekend)' if a.systeem_actor_fallback else ''}"
            f"{label}"
        )
        print(f"{'FOUT ' if a.fouten else 'OK   '} {regel}", file=sys.stderr if a.fouten else sys.stdout)
        for d in a.details:
            status = "FOUT " if d.uitkomst == "fout" else ("gedaan" if d.uitkomst == "omgezet" else "zou  ")
            if d.uitkomst == "niets om te zetten":
                status = "leeg " if uitkomst.dry_run else "gedaan"
            fout = f" — {d.fout}" if d.fout else ""
            actor = "systeem-actor (aanmaker onbekend)" if d.actor_fallback else f"aanmaker {str(d.actor_id)[:8]}"
            print(
                f"        {status} regel {str(d.werklijst_id)[:8]} ({d.aangemaakt_op:%d-%m-%Y}, {actor}) voorkeur "
                f"{d.voorkeur_naam!r} ← om te zetten {d.om_te_zetten}, al gemarkeerd {d.al_gemarkeerd}, "
                f"niet meer bestaand {d.niet_meer_bestaand}{fout}"
            )
    print(
        f"Totaal{label}: {uitkomst.regels} regels, {uitkomst.om_te_zetten} om te zetten, {uitkomst.omgezet} omgezet, "
        f"{uitkomst.al_gemarkeerd} al gemarkeerd, {uitkomst.niet_meer_bestaand} niet meer bestaand, "
        f"{uitkomst.fouten} fouten (run {uitkomst.run_id})"
    )
    return 1 if uitkomst.fouten else 0


def _rapporteer_autoboek_kandidaten(resultaten: dict) -> int:
    fouten = 0
    for administratie_id, r in resultaten.items():
        if isinstance(r, dict):
            print(
                f"OK    {administratie_id}: {r['kandidaten']} kandidaten, {r['actief']} actief, "
                f"{r['heroverwegen']} heroverwegen, {r['verborgen']} verborgen ({r['rijen']} leveranciers beoordeeld)"
            )
        else:
            fouten += 1
            print(f"FOUT  {administratie_id}: {r}", file=sys.stderr)
    return 1 if fouten else 0


def _rapporteer_terugkerend(resultaten: dict) -> int:
    fouten = 0
    for administratie_id, r in resultaten.items():
        if isinstance(r, dict):
            print(
                f"OK    {administratie_id}: {r['terugkerend']} terugkerende leveranciers, "
                f"{r['ontbreekt']} verwachte factuur ontbreekt, {r['prijsstijging']} prijsstijging, "
                f"{r['vervallen']} vervallen"
            )
        else:
            fouten += 1
            print(f"FOUT  {administratie_id}: {r}", file=sys.stderr)
    return 1 if fouten else 0


def _rapporteer_voorraad_rlz(resultaten: dict) -> int:
    """Rapportage voor de RLZ-uitstroom-leesroute: telling per administratie, geen credential =
    zichtbaar overgeslagen (geen fout), elke andere fout = exit 1."""
    from app.voorraad.rlz_uitstroom import RlzUitstroomTelling

    if not resultaten:
        print("(geen administraties met de voorraad-opt-in)")
        return 0
    fouten = 0
    for administratie_id, resultaat in resultaten.items():
        if isinstance(resultaat, RlzUitstroomTelling):
            print(
                f"OK    {administratie_id}: vanaf {resultaat.vanaf} — {resultaat.facturen_gelezen} facturen gelezen, "
                f"{resultaat.facturen_verwerkt} verwerkt ({resultaat.regels} regels), "
                f"{resultaat.overgeslagen_concept} concept, {resultaat.overgeslagen_in_app} in de app geboekt, "
                f"{resultaat.verwijderd_na_storno} regels weg na storno"
                + (
                    f", {resultaat.overgeslagen_na_knip} ná de Odoo-knip {resultaat.knip_datum}"
                    if resultaat.knip_datum
                    else ""
                )
                + (f" — RLZ overgeslagen: {resultaat.overgeslagen_reden}" if resultaat.overgeslagen_reden else "")
            )
            odoo = resultaat.odoo
            if odoo is not None:
                # Blok D: de Odoo-leesroute van dezelfde administratie (alleen-lezen, vanaf de knip).
                if odoo.get("overgeslagen_reden"):
                    print(f"      Odoo: overgeslagen — {odoo['overgeslagen_reden']}")
                else:
                    print(
                        f"      Odoo (company {odoo.get('company_id')}): vanaf {odoo.get('vanaf')} — "
                        f"{odoo.get('facturen_gelezen', 0)} facturen gelezen, "
                        f"{odoo.get('facturen_verwerkt', 0)} verwerkt ({odoo.get('regels', 0)} regels), "
                        f"{odoo.get('overgeslagen_niet_geboekt', 0)} niet geboekt, "
                        f"{odoo.get('verwijderd_na_annulering', 0)} regels weg na annulering, "
                        f"{odoo.get('overgeslagen_dubbel', 0)} dubbel met RLZ"
                    )
        elif isinstance(resultaat, GeenRlzCredentials):
            print(f"OVERGESLAGEN {administratie_id}: {resultaat}")
        else:
            fouten += 1
            print(f"FOUT  {administratie_id}: {resultaat}", file=sys.stderr)
    return 1 if fouten else 0


def _rapporteer_voorraad_normalisatie(
    resultaten: dict, *, kosten_voor: Decimal | None = None, kosten_na: Decimal | None = None
) -> int:
    """Rapport hernormalisatie (v2 blok D — zelfde vorm als het 29-08-rapport): per administratie
    genormaliseerd / onzeker / dienst / transport / niet genormaliseerd (+ legacy 'uitgesloten' die nog
    niet is omgezet, codes) en de AI-maandmeter vóór/ná. Fout per administratie = exit 1, rest loopt door."""
    if not resultaten:
        print("(geen administraties met de voorraad-opt-in)")
        return 0
    fouten = 0
    for administratie_id, resultaat in resultaten.items():
        if isinstance(resultaat, dict):
            st = resultaat["stand"]
            print(
                f"OK    {resultaat.get('naam', administratie_id)}: {st['regels']} regels — "
                f"genormaliseerd {st['genormaliseerd']} / onzeker {st['onzeker']} / dienst {st['dienst']} / "
                f"transport {st['transport']} / NIET genormaliseerd {st['niet_genormaliseerd']}"
                + (f" / legacy-uitgesloten {st['legacy_uitgesloten']}" if st["legacy_uitgesloten"] else "")
                + f"; codes: {st['regels_met_code']} regels mét code, {st['codes_gekoppeld']} koppelingen"
                f" (herrekend: {resultaat['inkoop_regels']} inkoop, {resultaat['verkoop_regels']} verkoop-app, "
                f"{resultaat['rlz_regels']} RLZ)"
            )
        else:
            fouten += 1
            print(f"FOUT  {administratie_id}: {resultaat}", file=sys.stderr)
    if kosten_voor is not None and kosten_na is not None:
        print(f"AI-maandmeter: € {kosten_voor:.2f} → € {kosten_na:.2f} (Δ € {kosten_na - kosten_voor:.2f})")
    return 1 if fouten else 0


def _voorraad_hernormaliseer(args: argparse.Namespace) -> int:
    """Hernormalisatie zonder RLZ-calls (v2 blok D): alle feitenregels van elke voorraad-administratie
    opnieuw door de motor (bekende teksten/codes deterministisch, onbekende via de AI-gates; `--zonder-ai`
    = alleen deterministisch), legacy 'uitgesloten' → soort-label, rapport per administratie + AI-kosten."""
    from app.aikosten.service import haal_status_op
    from app.db.models import Administratie
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.voorraad import service as voorraad_service

    with scoped_session(None) as session:
        q = select(Administratie).where(Administratie.voorraad_ingeschakeld.is_(True), Administratie.actief.is_(True))
        if args.administratie_id:
            try:
                q = q.where(Administratie.id == uuid.UUID(args.administratie_id))
            except ValueError as exc:
                print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
                return 1
        administraties = [(a.id, a.naam) for a in session.scalars(q.order_by(Administratie.naam))]
    kosten_voor = haal_status_op().verbruik_eur
    resultaten: dict = {}
    for administratie_id, naam in administraties:
        try:
            telling = voorraad_service.herreken_administratie(
                administratie_id=administratie_id, actor_id=SYSTEEM_ACTOR_ID, met_ai=not args.zonder_ai
            )
            resultaten[administratie_id] = {
                **telling,
                "naam": naam,
                "stand": voorraad_service.normalisatie_stand(administratie_id=administratie_id),
            }
        except Exception as exc:  # noqa: BLE001 — één administratie mag de rest niet raken
            logging.getLogger(__name__).exception("Hernormalisatie mislukt voor %s", administratie_id)
            resultaten[administratie_id] = str(exc)
    return _rapporteer_voorraad_normalisatie(
        resultaten, kosten_voor=kosten_voor, kosten_na=haal_status_op().verbruik_eur
    )


def _voorraad_rlz_sync(args: argparse.Namespace) -> int:
    """Handmatige/eerste run van de RLZ-uitstroom-leesroute (`--volledig` = het lopende jaar
    opnieuw lezen; zonder `--administratie-id` = alle voorraad-administraties)."""
    from app.voorraad import rlz_uitstroom

    if args.administratie_id:
        try:
            administratie_id = uuid.UUID(args.administratie_id)
        except ValueError as exc:
            print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
            return 1
        try:
            telling = rlz_uitstroom.sync_voorraad_uitstroom(administratie_id=administratie_id, volledig=args.volledig)
        except GeenRlzCredentials as exc:
            print(f"OVERGESLAGEN {administratie_id}: {exc}")
            return 0
        return _rapporteer_voorraad_rlz({administratie_id: telling})
    return _rapporteer_voorraad_rlz(rlz_uitstroom.sync_alle_voorraad_administraties(volledig=args.volledig))


def _odoo_leesbron(args: argparse.Namespace) -> int:
    """Beheer-terugval voor de leesbron-koppeling (Beheerder-endpoints bestaan ook): koppelen mét leesprobe of
    alleen de knip zetten. Actor = systeem-actor (audit benoemt de CLI); de key komt uit $ODOO_API_KEY."""
    import os
    from datetime import date as _date

    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.odoo import service as odoo_service

    try:
        administratie_id = uuid.UUID(args.administratie_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    knip: _date | None = None
    if args.knip and args.knip != "geen":
        try:
            knip = _date.fromisoformat(args.knip)
        except ValueError:
            print("FOUT: --knip moet JJJJ-MM-DD zijn (of 'geen')", file=sys.stderr)
            return 1
    try:
        if args.odoo_url:
            if args.company_id is None:
                print("FOUT: --company-id is verplicht bij koppelen", file=sys.stderr)
                return 1
            api_key = os.environ.get("ODOO_API_KEY")
            if not api_key:
                print("FOUT: zet de API-key in $ODOO_API_KEY (nooit op de commandoregel)", file=sys.stderr)
                return 1
            p = odoo_service.koppel_leesbron(
                actor_id=SYSTEEM_ACTOR_ID,
                administratie_id=administratie_id,
                odoo_url=args.odoo_url,
                api_key=api_key,
                company_id=args.company_id,
                voorraad_knip_datum=knip,
                api_gebruiker=args.api_gebruiker,
            )
            print(f"OK    leesbron gekoppeld: company {args.company_id} ({p.company_naam}), knip {knip or 'geen'}")
            for k, v in p.rapport.items():
                print(f"      {k}: {v}")
            return 0
        if args.knip is None:
            print("FOUT: geef --odoo-url/--company-id (koppelen) of --knip (knip zetten)", file=sys.stderr)
            return 1
        stand = odoo_service.wijzig_leesbron(
            actor_id=SYSTEEM_ACTOR_ID, administratie_id=administratie_id, voorraad_knip_datum=knip
        )
        print(f"OK    voorraad-knip nu {stand.voorraad_knip_datum or 'geen'} (company {stand.company_id})")
        return 0
    except odoo_service.OdooKoppelFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        for k, v in exc.rapport.items():
            print(f"      {k}: {v}", file=sys.stderr)
        return 1


def _meld(
    verzamelaar,  # noqa: ANN001 — app.reconciliatie.run.Verzamelaar | None (alleen vanuit reconciliatie-alles)
    *,
    soort: str,
    administratie_id: uuid.UUID | None,
    tekst: str,
    vingerafdruk: str | None = None,
    detail: dict | None = None,
) -> None:
    """Registreer een rapportregel als bevinding van de lopende reconciliatie-alles-run (opdracht
    06-09). Zonder verzamelaar (losse CLI-commando's) een no-op — de printregels blijven de bron."""
    if verzamelaar is None:
        return
    verzamelaar.bevinding(
        soort=soort, administratie_id=administratie_id, tekst=tekst, vingerafdruk=vingerafdruk, detail=detail
    )


def _print_overgeslagen(administratie_id: uuid.UUID) -> None:
    """A12 (07-09): bank/omzet/doorbelasting toetsen alleen Reeleezee; een Odoo-administratie staat zichtbaar in
    de uitvoer als OVERGESLAGEN — geen fout, geen bevinding, geen exit-code-effect."""
    print(f"OVERGESLAGEN {administratie_id}: {RLZ_ONLY_OVERGESLAGEN}")


def _soort_van(beoordeeld: acceptatie_service.Beoordeeld, uitsluiting: str | None) -> str:
    if uitsluiting:
        return "uitgesloten"
    return "afwijking" if beoordeeld.telt_mee else "geaccepteerd"


def _afwijking_detail(bron: str, beoordeeld: acceptatie_service.Beoordeeld, uitsluiting: str | None, **extra) -> dict:
    return {
        "bron": bron,
        "record_id": str(beoordeeld.record_id),
        "afwijking_soort": beoordeeld.soort,
        "detail": beoordeeld.detail,
        "geaccepteerd": not beoordeeld.telt_mee,
        "uitsluiting": uitsluiting,
        **{k: (str(v) if isinstance(v, uuid.UUID) else v) for k, v in extra.items()},
    }


def _verrijk(verzamelaar, functie: str, **kw) -> dict:  # noqa: ANN001
    """Naamverrijking van een detail-dict (fixrun 07-09 blok A8, `app/reconciliatie/verrijking.py`) —
    alleen binnen een reconciliatie-alles-run (verzamelaar), losse CLI-commando's blijven identiek.
    Nooit een fout: de verrijking levert hooguit een leeg dict."""
    if verzamelaar is None:
        return {}
    from app.reconciliatie import verrijking

    try:
        return getattr(verrijking, functie)(**kw)
    except Exception:  # noqa: BLE001 — een naamlookup mag de run nooit laten omvallen
        return {}


def _bevindingssoort_stand(args: argparse.Namespace) -> int:
    """SPOED 17-09 blok C. Lees-only zonder --stand (in de nameting-allowlist); mét --stand + --reden = promotie/
    degradatie onder de systeem-actor mét audit — een expliciete stap ná een meting, nooit stil."""
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.reconciliatie import kantoorbreed

    if args.stand is not None:
        if not args.soort or not args.reden:
            print("FOUT: --stand vereist <soort> én --reden", file=sys.stderr)
            return 2
        try:
            standen = kantoorbreed.zet_soort_stand(
                soort=args.soort, stand=args.stand, actor_id=SYSTEEM_ACTOR_ID, reden=args.reden
            )
        except kantoorbreed.ReconciliatieFout as exc:
            print(f"FOUT: {exc}", file=sys.stderr)
            return 2
        print(f"bevindingssoort {args.soort} → {args.stand} (reden: {args.reden})")
    else:
        standen = kantoorbreed.soort_standen_overzicht()
    print(f"{'soort':<34} {'blok':<26} {'sinds':<10} {'default':<8} {'override':<9} stand")
    for s in standen:
        if args.soort and s["soort"] != args.soort:
            continue
        print(f"{s['soort']:<34} {s['blok']:<26} {s['sinds']:<10} {s['default']:<8} {str(s['override'] or '-'):<9} {s['stand']}")
    return 0


def _verrijk_bank(verzamelaar, administratie_id: uuid.UUID, a) -> dict:  # noqa: ANN001
    # Blok C 16-09: leesbare extra velden van de afwijking zelf (`BankAfwijking.extra`, bv. de datums van een vermoede
    # dubbele betaling) reizen altijd mee — ook zonder verzamelaar; een naamlookup gaat er nooit door overheen.
    extra = dict(getattr(a, "extra", None) or {})
    return {
        **extra,
        **_verrijk(
            verzamelaar, "bank", administratie_id=administratie_id, record_id=a.record_id,
            payment_transaction_id=a.payment_transaction_id,
        ),
    }


def _verrijk_administratie(
    verzamelaar, administratie_id: uuid.UUID, *, fout: str | None = None, uitsluiting: str | None = None  # noqa: ANN001
) -> dict | None:
    d = _verrijk(verzamelaar, "administratie", administratie_id=administratie_id, fout=fout, uitsluiting=uitsluiting)
    return d or None


def _regel(kern: str, beoordeeld: acceptatie_service.Beoordeeld) -> str:
    """Eén rapportregel, zónder eigen prefix (de aanroeper bepaalt inspringing/stream). De
    vingerafdruk staat er altijd bij: dat is de sleutel waarmee een beoordeelde afwijking
    geaccepteerd — of weer ingetrokken — wordt."""
    kop = f"{kern} soort={beoordeeld.soort} [vaf:{beoordeeld.vingerafdruk}]: {beoordeeld.detail}"
    if beoordeeld.acceptatie is None:
        return kop
    geaccepteerd_op = beoordeeld.acceptatie.geaccepteerd_op.date().isoformat()
    return f"GEACCEPTEERD {kop} — reden: {beoordeeld.acceptatie.reden} (sinds {geaccepteerd_op})"


def _auto_accepteer_afrondingen(
    verzamelaar,  # noqa: ANN001 — Verzamelaar | None
    *,
    administratie_id: uuid.UUID,
    afwijkingen,  # noqa: ANN001 — Sequence[ReconciliatieAfwijking]
    beoordeeld,  # noqa: ANN001 — Sequence[Beoordeeld]
) -> int:
    """Reconciliatie-nazorg 15-09 (besluit Peter 14-09): `bedrag_wijkt_af` ≤ € 0,05 = btw-cent-afronding → systeem-
    acceptatie mét audit `reconciliatie_auto_geaccepteerd` en dagteller `auto_geaccepteerd` op het blok. Alleen in
    een vastgelegde run; nooit voor een al (mens-)geaccepteerde of eerder ingetrokken vingerafdruk. → aantal nieuw."""
    if verzamelaar is None:
        return 0
    nieuw = 0
    for a, b in zip(afwijkingen, beoordeeld, strict=True):
        if not b.telt_mee:
            continue
        verschil = reconciliatie.afrondingsverschil(a)
        if verschil is None:
            continue
        try:
            _, is_nieuw = acceptatie_service.auto_accepteer(
                administratie_id=administratie_id,
                bron=ReconciliatieBron.DOCUMENTEN,
                record_id=b.record_id,
                soort=b.soort,
                detail=b.detail,
                reden=reconciliatie.AFRONDING_REDEN,
                extra={"verschil": str(verschil), "regel": "reconciliatie-nazorg 15-09"},
            )
        except Exception as exc:  # noqa: BLE001 — een mislukte auto-acceptatie laat de afwijking gewoon open staan
            print(f"    ! automatisch accepteren mislukt ({reconciliatie.AFRONDING_REDEN}): {exc}", file=sys.stderr)
            continue
        if is_nieuw:
            nieuw += 1
            print(
                f"    · automatisch geaccepteerd ({reconciliatie.AFRONDING_REDEN}, verschil € {verschil}) "
                f"[vaf:{b.vingerafdruk}]"
            )
    if nieuw:
        verzamelaar.auto_geaccepteerd(nieuw)
    return nieuw


def _reconciliatie(args: argparse.Namespace, verzamelaar=None) -> int:  # noqa: ANN001
    """Boeken-failsafe (b) (CLAUDE.md-taak 2.4): vergelijk elk lokaal GEBOEKT document met de
    werkelijke RLZ-staat en rapporteer afwijkingen. Eén administratie zonder werkende
    credentials laat de rest niet stoppen — zie reconcilieer_alle_administraties().

    Geaccepteerde afwijkingen (migratie 0042) blijven zichtbaar maar tellen niet mee in de
    exit-code: onderdrukken doen we nooit, alarmeren over een beoordeelde situatie ook niet."""
    resultaten = reconciliatie.reconcilieer_alle_administraties()
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    fouten = 0
    afwijkingen_totaal = 0
    geaccepteerd_totaal = 0
    geaccepteerd_uitgesloten = 0
    for administratie_id, resultaat in resultaten.items():
        uitsluiting = uitgesloten.get(administratie_id)
        if isinstance(resultaat, str):
            if uitsluiting:
                tekst = f"UITGESLOTEN {administratie_id}: {resultaat} (uitgesloten: {uitsluiting})"
                print(tekst)
                _meld(verzamelaar, soort="uitgesloten", administratie_id=administratie_id, tekst=tekst)
                continue
            fouten += 1
            tekst = f"FOUT       {administratie_id}: {resultaat}"
            print(tekst, file=sys.stderr)
            _meld(verzamelaar, soort="fout", administratie_id=administratie_id, tekst=tekst)
            continue
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(resultaat.aantal_gecontroleerd)
        # A12 (07-09) + besluit Peter 07-09 (beslispunt 1): een Odoo-administratie toont de verdeling van de toets
        # — N documenten in Odoo, M in het Reeleezee-verleden (vóór de kanteldatum geboekt, getoetst via de bewaarde
        # RLZ-credential). Échte niet-van-toepassing-gevallen (port: van_toepassing=False) blijven apart zichtbaar
        # — nooit stil weggelaten.
        overgeslagen = ""
        if getattr(resultaat, "backend", "rlz") == "odoo":
            overgeslagen += (
                f" ({getattr(resultaat, 'aantal_in_odoo', 0)} getoetst in Odoo, "
                f"{getattr(resultaat, 'aantal_in_rlz_verleden', 0)} in Reeleezee-verleden)"
            )
        if getattr(resultaat, "aantal_overgeslagen", 0):
            overgeslagen += f" ({resultaat.aantal_overgeslagen} niet van toepassing: niets te toetsen in deze backend)"
        if not resultaat.afwijkingen:
            print(
                f"OK         {administratie_id}: {resultaat.aantal_gecontroleerd} gecontroleerd, "
                f"geen afwijkingen{overgeslagen}"
            )
            continue
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.DOCUMENTEN,
            administratie_id=administratie_id,
            afwijkingen=[(a.document_id, a.soort, a.detail) for a in resultaat.afwijkingen],
        )
        # Reconciliatie-nazorg 15-09: een bedragverschil ≤ € 0,05 op een geboekt document (btw-cent-afronding) wordt
        # door het systeem geaccepteerd — alleen binnen een vastgelegde run (verzamelaar); lees-only/losse CLI schrijft
        # niets en markeert de regel. Daarna opnieuw beoordelen zodat de regel als GEACCEPTEERD landt.
        afrondingen = _auto_accepteer_afrondingen(
            verzamelaar, administratie_id=administratie_id, afwijkingen=resultaat.afwijkingen, beoordeeld=beoordeeld
        )
        if afrondingen:
            beoordeeld = acceptatie_service.beoordeel(
                bron=ReconciliatieBron.DOCUMENTEN,
                administratie_id=administratie_id,
                afwijkingen=[(a.document_id, a.soort, a.detail) for a in resultaat.afwijkingen],
            )
        open_afwijkingen = [b for b in beoordeeld if b.telt_mee]
        if uitsluiting:
            # Zichtbaar blijven, niet meetellen: de bevindingen worden gewoon getoond zodat een
            # échte fout hier niet onzichtbaar wordt (besluit 0043). De geaccepteerd-telling loopt
            # hier wél mee (aparte teller in de slotregel) — "telt niet mee in de exit-code" mag
            # niet verworden tot "telt nergens mee".
            geaccepteerd_uitgesloten += len(beoordeeld) - len(open_afwijkingen)
            print(
                f"UITGESLOTEN {administratie_id}: {resultaat.aantal_gecontroleerd} gecontroleerd, "
                f"{len(open_afwijkingen)} open, {len(beoordeeld) - len(open_afwijkingen)} geaccepteerd "
                f"— telt niet mee ({uitsluiting})"
            )
            for a, b in zip(resultaat.afwijkingen, beoordeeld, strict=True):
                regel = _regel(f"document={a.document_id} rlz_document={a.rlz_document_id}", b)
                print(f"    - {regel}")
                _meld(
                    verzamelaar, soort="uitgesloten", administratie_id=administratie_id, tekst=regel,
                    vingerafdruk=b.vingerafdruk,
                    detail=_afwijking_detail(
                        "documenten", b, uitsluiting, document_id=a.document_id, **getattr(a, "context", {})
                    ),
                )
            continue
        afwijkingen_totaal += len(open_afwijkingen)
        geaccepteerd_totaal += len(beoordeeld) - len(open_afwijkingen)
        kop = "AFWIJKING " if open_afwijkingen else "OK        "
        print(
            f"{kop} {administratie_id}: {resultaat.aantal_gecontroleerd} gecontroleerd, "
            f"{len(open_afwijkingen)} afwijking(en), {len(beoordeeld) - len(open_afwijkingen)} geaccepteerd"
            f"{overgeslagen}"
        )
        for a, b in zip(resultaat.afwijkingen, beoordeeld, strict=True):
            regel = _regel(f"document={a.document_id} rlz_document={a.rlz_document_id}", b)
            if verzamelaar is None and b.telt_mee and reconciliatie.is_afrondingsverschil(a):
                regel += f" — {reconciliatie.AFRONDING_REDEN}: wordt in de dagelijkse run automatisch geaccepteerd"
            print(f"    - {regel}")
            _meld(
                verzamelaar, soort=_soort_van(b, None), administratie_id=administratie_id, tekst=regel,
                vingerafdruk=b.vingerafdruk,
                detail=_afwijking_detail(
                    "documenten", b, None, document_id=a.document_id, **getattr(a, "context", {})
                ),
            )
    # Boeken sneller (18-09): een document dat langer dan de herstelgrens op wordt_geboekt staat = gestrande
    # achtergrond-schrijver → bevinding `wordt_geboekt_verouderd` (start in `meten`) mét actie "Opnieuw proberen" op de
    # rij (deeplink naar het document). Het herstel-vangnet plant 'm bovendien zelf opnieuw in.
    from app.documenten import boek_wachtrij

    for aid, doc_id, sinds in boek_wachtrij.verouderde_boekingen():
        regel = (
            f"document={doc_id}: staat sinds {sinds.isoformat(timespec='minutes')} op wordt_geboekt "
            f"(> {_settings().boek_wachtrij_herstel_minuten} min) — achtergrond-schrijver gestrand"
        )
        print(f"    - {regel}")
        afwijkingen_totaal += 1
        _meld(
            verzamelaar,
            soort="afwijking",
            administratie_id=aid,
            tekst=regel,
            detail={
                "bron": "documenten",
                "record_id": str(doc_id),
                "document_id": str(doc_id),
                "afwijking_soort": boek_wachtrij.BEVINDING_VEROUDERD,
                "detail": regel,
                "geaccepteerd": False,
                "sinds": sinds.isoformat(),
            },
        )
    uitgesloten_naschrift = (
        f"; daarnaast {geaccepteerd_uitgesloten} geaccepteerd op uitgesloten administraties — telt niet mee"
        if geaccepteerd_uitgesloten
        else ""
    )
    print(
        f"\n{len(resultaten) - fouten}/{len(resultaten)} administraties gecontroleerd, "
        f"{afwijkingen_totaal} afwijking(en) totaal ({geaccepteerd_totaal} geaccepteerd{uitgesloten_naschrift})."
    )

    # Storno-detectie (koppelcontract §3 v1.14, randvraag c): een RLZ-UI-storno op een geboekte
    # inkoopfactuur van een vastgoed-administratie → factuur_gestorneerd-outbox-event. Bewust in
    # dit commando: de reconciliatie-cadans ís de contract-latentie van de detectie-bron.
    for administratie_id, storno_resultaat in storno_detectie.detecteer_en_meld_gestorneerd_alle().items():
        if isinstance(storno_resultaat, str):
            fouten += 1
            tekst = f"FOUT       storno-detectie {administratie_id}: {storno_resultaat}"
            print(tekst, file=sys.stderr)
            _meld(verzamelaar, soort="fout", administratie_id=administratie_id, tekst=tekst)
        elif storno_resultaat:
            print(f"STORNO     {administratie_id}: {storno_resultaat} factuur_gestorneerd-event(s) aangemaakt")

    return 1 if (fouten or afwijkingen_totaal) else 0


def _bank_sync(args: argparse.Namespace) -> int:
    """Bank-sync (rekeningen/mutaties/open posten + afletter-verificatie + Vastly-detectie +
    opt-in autoboeken) — voor één administratie of alle (zelfde tolerantie-patroon als
    sync-alles: één kapotte administratie stopt de rest niet). Cloud Scheduler-entrypoint."""
    if args.administratie_id:
        try:
            administratie_id = uuid.UUID(args.administratie_id)
        except ValueError as exc:
            print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
            return 1
        resultaten = {administratie_id: None}
        try:
            resultaten[administratie_id] = bank_sync_service.sync_bank_voor_administratie(
                administratie_id=administratie_id
            )
        except Exception as exc:  # noqa: BLE001 — zelfde zichtbare foutafhandeling als de alle-variant
            resultaten[administratie_id] = str(exc)
    else:
        resultaten = bank_sync_service.sync_bank_alle_administraties()

    fouten = 0
    overgeslagen = 0
    for administratie_id, resultaat in resultaten.items():
        if isinstance(resultaat, GeenRlzCredentials):
            # BLOK 1 (08-09): geen RLZ-verbinding (geen credential / Odoo) = zichtbaar overgeslagen, geen fout.
            overgeslagen += 1
            print(f"OVERGESLAGEN {administratie_id}: {resultaat}")
            continue
        if isinstance(resultaat, str) or resultaat is None:
            fouten += 1
            print(f"FOUT  {administratie_id}: {resultaat}", file=sys.stderr)
            continue
        print(
            f"OK    {administratie_id}: rekeningen={resultaat.rekeningen}, mutaties={resultaat.mutaties}, "
            f"open_posten={resultaat.open_posten}, afletteren_geverifieerd={resultaat.afletteren_geverifieerd}, "
            f"vastly_gemeld={resultaat.vastly_gemeld}, automatisch_geboekt={resultaat.automatisch_geboekt}, "
            f"automatisch_afgeletterd={resultaat.automatisch_afgeletterd}"
        )
        for fout in resultaat.automatisch_fouten:
            print(f"      autoboek-fout: {fout}", file=sys.stderr)
    kern = f"{len(resultaten) - fouten - overgeslagen}/{len(resultaten)} administraties bank-gesynchroniseerd."
    if overgeslagen:
        kern += f" ({overgeslagen} overgeslagen: geen Reeleezee-verbinding)"
    print(f"\n{kern}")
    return 1 if fouten else 0


def _bank_reconciliatie(args: argparse.Namespace, verzamelaar=None) -> int:  # noqa: ANN001
    """Bank-failsafe: vergelijk directe boekingen en geverifieerde afletteringen met de
    werkelijke RLZ-staat (OpenAmount/documentstatus — nooit IsComplete) en rapporteer
    afwijkingen. Zelfde patroon als het documenten-reconciliatie-commando."""
    resultaten = bank_reconciliatie.reconcilieer_bank_alle_administraties()
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    fouten = 0
    afwijkingen_totaal = 0
    geaccepteerd_totaal = 0
    geaccepteerd_uitgesloten = 0
    for administratie_id, resultaat in resultaten.items():
        uitsluiting = uitgesloten.get(administratie_id)
        if resultaat == RLZ_ONLY_OVERGESLAGEN:
            _print_overgeslagen(administratie_id)  # Odoo-administratie: RLZ-only blok (A12, 07-09)
            continue
        if isinstance(resultaat, str):
            if uitsluiting:
                tekst = f"UITGESLOTEN {administratie_id}: {resultaat} (uitgesloten: {uitsluiting})"
                print(tekst)
                _meld(
                    verzamelaar, soort="uitgesloten", administratie_id=administratie_id, tekst=tekst,
                    detail=_verrijk_administratie(
                        verzamelaar, administratie_id, fout=resultaat, uitsluiting=uitsluiting
                    ),
                )
                continue
            fouten += 1
            tekst = f"FOUT       {administratie_id}: {resultaat}"
            print(tekst, file=sys.stderr)
            _meld(
                verzamelaar, soort="fout", administratie_id=administratie_id, tekst=tekst,
                detail=_verrijk_administratie(verzamelaar, administratie_id, fout=resultaat),
            )
            continue
        gecontroleerd = (
            resultaat.boekingen_gecontroleerd
            + resultaat.afletteringen_gecontroleerd
            # Blok C 16-09: getoetste sleutels (tegenrekening + bedrag) van de dubbele-betaling-controle tellen mee.
            + getattr(resultaat, "dubbele_betalingen_gecontroleerd", 0)
        )
        if verzamelaar is not None:
            verzamelaar.gecontroleerd(gecontroleerd)
        if not resultaat.afwijkingen:
            print(f"OK         {administratie_id}: {gecontroleerd} gecontroleerd, geen afwijkingen")
            continue
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.BANK,
            administratie_id=administratie_id,
            afwijkingen=[(a.record_id, a.soort, a.detail) for a in resultaat.afwijkingen],
        )
        open_afwijkingen = [b for b in beoordeeld if b.telt_mee]
        if uitsluiting:
            # Zelfde zichtbaarheids-fix als de documenten-variant: geaccepteerd-telling loopt mee
            # in een aparte teller, alleen de exit-code negeert de uitgesloten administratie.
            geaccepteerd_uitgesloten += len(beoordeeld) - len(open_afwijkingen)
            print(
                f"UITGESLOTEN {administratie_id}: {gecontroleerd} gecontroleerd, "
                f"{len(open_afwijkingen)} open, {len(beoordeeld) - len(open_afwijkingen)} geaccepteerd "
                f"— telt niet mee ({uitsluiting})"
            )
            for a, b in zip(resultaat.afwijkingen, beoordeeld, strict=True):
                regel = _regel(f"record={a.record_id} mutatie={a.payment_transaction_id}", b)
                print(f"    - {regel}")
                _meld(
                    verzamelaar, soort="uitgesloten", administratie_id=administratie_id, tekst=regel,
                    vingerafdruk=b.vingerafdruk,
                    detail=_afwijking_detail(
                        "bank", b, uitsluiting, payment_transaction_id=a.payment_transaction_id,
                        **_verrijk_bank(verzamelaar, administratie_id, a),
                    ),
                )
            continue
        afwijkingen_totaal += len(open_afwijkingen)
        geaccepteerd_totaal += len(beoordeeld) - len(open_afwijkingen)
        kop = "AFWIJKING " if open_afwijkingen else "OK        "
        print(
            f"{kop} {administratie_id}: {gecontroleerd} gecontroleerd, "
            f"{len(open_afwijkingen)} afwijking(en), {len(beoordeeld) - len(open_afwijkingen)} geaccepteerd"
        )
        for a, b in zip(resultaat.afwijkingen, beoordeeld, strict=True):
            regel = _regel(f"record={a.record_id} mutatie={a.payment_transaction_id}", b)
            print(f"    - {regel}")
            _meld(
                verzamelaar, soort=_soort_van(b, None), administratie_id=administratie_id, tekst=regel,
                vingerafdruk=b.vingerafdruk,
                detail=_afwijking_detail(
                    "bank", b, None, payment_transaction_id=a.payment_transaction_id,
                    **_verrijk_bank(verzamelaar, administratie_id, a),
                ),
            )
    uitgesloten_naschrift = (
        f"; daarnaast {geaccepteerd_uitgesloten} geaccepteerd op uitgesloten administraties — telt niet mee"
        if geaccepteerd_uitgesloten
        else ""
    )
    print(
        f"\n{len(resultaten) - fouten}/{len(resultaten)} administraties gecontroleerd, "
        f"{afwijkingen_totaal} afwijking(en) totaal ({geaccepteerd_totaal} geaccepteerd{uitgesloten_naschrift})."
    )
    return 1 if (fouten or afwijkingen_totaal) else 0


def _omzet_reconciliatie(args: argparse.Namespace, verzamelaar=None) -> int:  # noqa: ANN001
    """Omzet-failsafe: vergelijk elke omzet-boeking (verkoopfactuur + kostprijsmemoriaal) met de
    werkelijke RLZ-staat en rapporteer afwijkingen — incl. alle half_geboekt-rijen."""
    # registreer = alleen in de echte run (verzamelaar): één audit-rij `kassarapport_inkoopstroom_run` per administratie
    # mét tellers (blok C 16-09 avond); lees-only/losse CLI schrijft niets.
    resultaat = omzet_reconciliatie.reconcilieer_alle_omzet(registreer=verzamelaar is not None)
    for administratie_id in getattr(resultaat, "overgeslagen", {}):
        _print_overgeslagen(administratie_id)  # RLZ-only blok (A12, 07-09); de lokale kassarapport-toets liep wél
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    echte_fouten = {aid: fout for aid, fout in resultaat.fouten.items() if aid not in uitgesloten}
    for administratie_id, fout in resultaat.fouten.items():
        if administratie_id in uitgesloten:
            tekst = f"UITGESLOTEN {administratie_id}: {fout} (uitgesloten: {uitgesloten[administratie_id]})"
            print(tekst)
            _meld(
                verzamelaar, soort="uitgesloten", administratie_id=administratie_id, tekst=tekst,
                detail=_verrijk_administratie(
                    verzamelaar, administratie_id, fout=fout, uitsluiting=uitgesloten[administratie_id]
                ),
            )
            continue
        tekst = f"FOUT       {administratie_id}: {fout}"
        print(tekst, file=sys.stderr)
        _meld(
            verzamelaar, soort="fout", administratie_id=administratie_id, tekst=tekst,
            detail=_verrijk_administratie(verzamelaar, administratie_id, fout=fout),
        )
    if verzamelaar is not None:
        verzamelaar.gecontroleerd(getattr(resultaat, "gecontroleerd", 0))

    open_totaal = 0
    geaccepteerd_totaal = 0
    per_administratie: dict[uuid.UUID, list[omzet_reconciliatie.OmzetAfwijking]] = {}
    for afwijking in resultaat.afwijkingen:
        per_administratie.setdefault(afwijking.administratie_id, []).append(afwijking)

    for administratie_id, afwijkingen in per_administratie.items():
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.OMZET,
            administratie_id=administratie_id,
            afwijkingen=[(a.boeking_id, a.soort, a.detail) for a in afwijkingen],
        )
        for a, b in zip(afwijkingen, beoordeeld, strict=True):
            regel = _regel(f"{administratie_id} boeking={a.boeking_id}", b)
            uitsluiting = uitgesloten.get(administratie_id)
            if uitsluiting:
                tekst = f"UITGESLOTEN {regel} — telt niet mee ({uitsluiting})"
                print(tekst)
            elif b.telt_mee:
                open_totaal += 1
                tekst = f"AFWIJKING  {regel}"
                print(tekst, file=sys.stderr)
            else:
                geaccepteerd_totaal += 1
                tekst = f"OK         {regel}"
                print(tekst)
            _meld(
                verzamelaar, soort=_soort_van(b, uitsluiting), administratie_id=administratie_id, tekst=tekst,
                vingerafdruk=b.vingerafdruk,
                detail=_afwijking_detail(
                    "omzet", b, uitsluiting, document_id=a.document_id,
                    **_verrijk(verzamelaar, "omzet", administratie_id=administratie_id, boeking_id=a.boeking_id),
                ),
            )

    if not echte_fouten and not open_totaal:
        print(f"OK         geen afwijkingen in de omzet-boekingen ({geaccepteerd_totaal} geaccepteerd)")
        return 0
    print(
        f"{open_totaal} afwijking(en) en {len(echte_fouten)} mislukte administratie(s) gevonden "
        f"({geaccepteerd_totaal} geaccepteerd)",
        file=sys.stderr,
    )
    return 1


def _doorbelasting_reconciliatie(args: argparse.Namespace, verzamelaar=None) -> int:  # noqa: ANN001
    """Doorbelasting-failsafe: vergelijk elke doorbelastings-boeking (verkoopfactuur in de bron
    + spiegel-inkoopfactuur in het doel) met de werkelijke RLZ-staat — incl. alle
    half_geboekt-rijen en verouderde open spiegel-taken."""
    resultaat = doorbelasting_reconciliatie.reconcilieer_alle_doorbelasting()
    for administratie_id in getattr(resultaat, "overgeslagen", {}):
        _print_overgeslagen(administratie_id)  # RLZ-only blok (A12, 07-09)
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    echte_fouten = {aid: fout for aid, fout in resultaat.fouten.items() if aid not in uitgesloten}
    for administratie_id, fout in resultaat.fouten.items():
        if administratie_id in uitgesloten:
            tekst = f"UITGESLOTEN {administratie_id}: {fout} (uitgesloten: {uitgesloten[administratie_id]})"
            print(tekst)
            _meld(
                verzamelaar, soort="uitgesloten", administratie_id=administratie_id, tekst=tekst,
                detail=_verrijk_administratie(
                    verzamelaar, administratie_id, fout=fout, uitsluiting=uitgesloten[administratie_id]
                ),
            )
            continue
        tekst = f"FOUT       {administratie_id}: {fout}"
        print(tekst, file=sys.stderr)
        _meld(
            verzamelaar, soort="fout", administratie_id=administratie_id, tekst=tekst,
            detail=_verrijk_administratie(verzamelaar, administratie_id, fout=fout),
        )
    if verzamelaar is not None:
        verzamelaar.gecontroleerd(getattr(resultaat, "gecontroleerd", 0))

    open_totaal = 0
    geaccepteerd_totaal = 0
    per_administratie: dict[uuid.UUID, list[doorbelasting_reconciliatie.DoorbelastingAfwijking]] = {}
    for afwijking in resultaat.afwijkingen:
        per_administratie.setdefault(afwijking.administratie_id, []).append(afwijking)

    for administratie_id, afwijkingen in per_administratie.items():
        beoordeeld = acceptatie_service.beoordeel(
            bron=ReconciliatieBron.DOORBELASTING,
            administratie_id=administratie_id,
            afwijkingen=[(a.boeking_id, a.soort, a.detail) for a in afwijkingen],
        )
        for a, b in zip(afwijkingen, beoordeeld, strict=True):
            regel = _regel(f"{administratie_id} boeking={a.boeking_id}", b)
            uitsluiting = uitgesloten.get(administratie_id)
            if uitsluiting:
                tekst = f"UITGESLOTEN {regel} — telt niet mee ({uitsluiting})"
                print(tekst)
            elif b.telt_mee:
                open_totaal += 1
                tekst = f"AFWIJKING  {regel}"
                print(tekst, file=sys.stderr)
            else:
                geaccepteerd_totaal += 1
                tekst = f"OK         {regel}"
                print(tekst)
            _meld(
                verzamelaar, soort=_soort_van(b, uitsluiting), administratie_id=administratie_id, tekst=tekst,
                vingerafdruk=b.vingerafdruk,
                detail=_afwijking_detail(
                    "doorbelasting", b, uitsluiting, document_id=a.document_id,
                    **_verrijk(
                        verzamelaar, "doorbelasting", administratie_id=administratie_id, boeking_id=a.boeking_id
                    ),
                ),
            )

    # Opruimlijst (hygiëne-run 2026-08-16): achtergebleven RLZ-concepten van gestorneerde/
    # vervallen runs — puur informatief (LET-OP), telt NOOIT mee in de exit-code. De app
    # verwijdert nooit iets in RLZ (kernprincipe 3); opruimen is klikwerk van een mens in de
    # RLZ-UI, "indien gewenst". Ook zichtbaar op Instellingen → Doorbelasting.
    opruim = doorbelasting_reconciliatie.verzamel_alle_opruimlijsten()
    for kandidaat in opruim.kandidaten:
        tekst = (
            f"LET-OP     opruim-kandidaat [{kandidaat.reden}] {kandidaat.kant} {kandidaat.rlz_id} "
            f"in administratie {kandidaat.concept_administratie_id} "
            f"(document {kandidaat.document_id}{f', ref {kandidaat.referentie}' if kandidaat.referentie else ''}) "
            f"— {kandidaat.detail}; handmatig opruimen in de RLZ-UI indien gewenst"
        )
        print(tekst)
        if verzamelaar is not None:
            from app.reconciliatie.run import vingerafdruk_opruim

            _meld(
                verzamelaar, soort="let_op", administratie_id=kandidaat.administratie_id, tekst=tekst,
                vingerafdruk=vingerafdruk_opruim(
                    kant=kandidaat.kant, concept_administratie_id=kandidaat.concept_administratie_id,
                    rlz_id=kandidaat.rlz_id,
                ),
                detail={
                    "kant": kandidaat.kant,
                    "rlz_id": str(kandidaat.rlz_id),
                    "concept_administratie_id": str(kandidaat.concept_administratie_id),
                    "document_id": str(kandidaat.document_id),
                    "referentie": kandidaat.referentie,
                    "reden": kandidaat.reden,
                    "detail": kandidaat.detail,
                    **_verrijk(
                        verzamelaar, "opruim_kandidaat",
                        administratie_id=kandidaat.administratie_id,
                        concept_administratie_id=kandidaat.concept_administratie_id,
                        document_id=kandidaat.document_id,
                    ),
                },
            )
    for fout in opruim.fouten:
        tekst = f"LET-OP     opruimlijst: {fout}"
        print(tekst)
        _meld(verzamelaar, soort="let_op", administratie_id=None, tekst=tekst, detail={"reden": "opruimlijst_fout"})
    if opruim.kandidaten:
        print(f"LET-OP     {len(opruim.kandidaten)} achtergebleven RLZ-concept(en) — informatief, geen fout")

    if not echte_fouten and not open_totaal:
        print(f"OK         geen afwijkingen in de doorbelastingen ({geaccepteerd_totaal} geaccepteerd)")
        return 0
    print(
        f"{open_totaal} afwijking(en) en {len(echte_fouten)} mislukte administratie(s) gevonden "
        f"({geaccepteerd_totaal} geaccepteerd)",
        file=sys.stderr,
    )
    return 1


def _doorbelasting_facturen_herstel(args: argparse.Namespace) -> int:
    """Nazorg blok A (26-08): factuur-PDF alsnog op bestaande GEBOEKTE doorbelastingen zonder
    factuur — géén herboeking, dry-run eerst, per run geauditeerd. Rapporteert het aantal."""
    actor = uuid.UUID(args.beheerder_id) if args.beheerder_id else SYSTEEM_ACTOR_ID
    resultaat = doorbelasting_factuur_herstel.herstel_facturen(dry_run=args.dry_run, actor_id=actor)
    label = "DRY-RUN   " if args.dry_run else "KANDIDAAT "
    for k in resultaat.kandidaten:
        print(
            f"{label} {k.administratie_naam} boeking={k.boeking_id} doel={k.doelentiteit_naam} "
            f"ref={k.verkoop_referentie} status={k.status} factuur={k.huidige_factuur_status or 'nooit geprobeerd'}"
        )
    if args.dry_run:
        print(f"DRY-RUN    {len(resultaat.kandidaten)} boeking(en) zonder factuur-PDF — niets gewijzigd")
        return 0
    for boeking_id in resultaat.hersteld:
        print(f"HERSTELD   boeking={boeking_id}: factuur-PDF gerenderd, getoetst en op beide kanten gezet")
    for boeking_id, reden in resultaat.mislukt.items():
        print(f"MISLUKT    boeking={boeking_id}: {reden}", file=sys.stderr)
    print(
        f"{len(resultaat.hersteld)} hersteld, {len(resultaat.mislukt)} mislukt "
        f"van {len(resultaat.kandidaten)} kandidaat/kandidaten"
    )
    return 1 if resultaat.mislukt else 0


def _settings():
    from app.config import settings

    return settings


def _accordering_herstel_boeken(args: argparse.Namespace) -> int:
    """Bugfix-run 28-08: documenten mét afgeronde klant-accordering die niet geboekt staan alsnog
    door het gefixte na-laatste-akkoord-pad boeken. Dry-run = lijst + diagnose per document, niets
    geschreven. Uitvoeren is een expliciete actie van Peter (make-target zonder DRY_RUN)."""
    from app.accordering import herstel as accordering_herstel

    administratie_id = uuid.UUID(args.administratie_id) if args.administratie_id else None
    resultaat = accordering_herstel.herstel_boeken(
        dry_run=args.dry_run, administratie_id=administratie_id, max_aantal=args.max_aantal
    )
    label = "DRY-RUN   " if args.dry_run else "KANDIDAAT "
    for k in resultaat.kandidaten:
        bedrag = f"€ {k.totaalbedrag}" if k.totaalbedrag is not None else "bedrag onbekend"
        afgerond = k.afgerond_op.isoformat(timespec="minutes") if k.afgerond_op else "?"
        print(
            f"{label} {k.administratie_naam} | {k.bestandsnaam} | {k.leverancier or 'leverancier onbekend'} | "
            f"{bedrag} | status={k.documentstatus} | akkoord compleet {afgerond} | "
            f"doorbelasting={'klaargezet' if k.doorbelasting_klaargezet else 'geen'} | document={k.document_id}"
        )
        if k.laatste_boek_fout:
            print(f"           laatste boekfout: {k.laatste_boek_fout}")
        if args.dry_run:
            blokkades = resultaat.diagnose.get(k.document_id, [])
            if blokkades:
                for b in blokkades:
                    print(f"           BLOKKEERT  {b}")
            else:
                print("           GROEN      boekt bij uitvoering (alle poorten groen op dit moment)")
    if args.dry_run:
        groen = sum(1 for k in resultaat.kandidaten if not resultaat.diagnose.get(k.document_id))
        print(
            f"DRY-RUN    {len(resultaat.kandidaten)} document(en) met afgerond klant-akkoord maar niet geboekt — "
            f"{groen} groen, {len(resultaat.kandidaten) - groen} geblokkeerd; niets gewijzigd. "
            f"Noodrem ná klant-akkoord: max {_settings().max_handmatige_boekingen_per_dag_per_administratie} "
            "handmatige boekingen/dag/administratie (de 20/dag-rem geldt alleen automatisch — punt 23, 28-08 + SPOED 18-09)."
        )
        return 0
    for document_id in resultaat.geboekt:
        print(f"GEBOEKT    document={document_id}")
    for document_id, reden in resultaat.mislukt.items():
        print(f"MISLUKT    document={document_id}: {reden}", file=sys.stderr)
    for document_id, reden in resultaat.overgeslagen.items():
        print(f"OVERGESLAGEN document={document_id}: {reden}")
    print(
        f"{len(resultaat.geboekt)} geboekt, {len(resultaat.mislukt)} mislukt, "
        f"{len(resultaat.overgeslagen)} overgeslagen van {len(resultaat.kandidaten)} kandidaat/kandidaten"
    )
    return 1 if resultaat.mislukt else 0


def _doorbelasting_seed_kempen(args: argparse.Namespace) -> int:
    """Losse, expliciete seed-stap (migraties zijn schema-only): de whitelist doelentiteit ↔
    Customer-GUID uit verkenning/16 §1 voor de opgegeven BRON-administratie. Idempotent."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    toegevoegd = doorbelasting_service.seed_kempen_mappings(administratie_id=administratie_id, actor_id=beheerder_id)
    print(f"OK         {toegevoegd} mapping(s) toegevoegd ({len(doorbelasting_service.KEMPEN_SEED)} totaal in de seed)")
    return 0


def _materiaal_seed_universal(args: argparse.Namespace) -> int:
    """Materiaalcatalogus Universal Nederland B.V. laden uit de bestellijst (steigerbouw-run D2;
    idempotent, nooit verwijderen). Beheerder-id verplicht (audit-actor)."""
    from app.materiaal import service as materiaal_service

    r = materiaal_service.seed_universal(
        administratie_id=uuid.UUID(args.administratie_id), actor_id=uuid.UUID(args.beheerder_id)
    )
    print(
        f"Catalogus geseed voor leverancier {r.leverancier_id}: {r.categorieen_nieuw} categorieën nieuw, "
        f"{r.producten_nieuw} producten nieuw, {r.producten_bestaand} bestaand (ongemoeid)."
    )
    return 0


def _reconciliatie_alles(args: argparse.Namespace) -> int:
    """Alle reconciliatie-blokken in één run. Bestaat omdat de handmatige `&&`-keten precies
    het verkeerde deed: viel de eerste om, dan draaiden de andere twee niet — juist op een dag
    waarop er iets aan de hand is verloor je zo de omzet-controle (half_geboekt) helemaal.
    Hier stopt niets vroegtijdig; de exit-code is 1 zodra één blok afwijkingen of fouten meldt.

    Sinds 06-09 (BESLISSINGEN "RECONCILIATIE-MELDING + INZICHT") legt `app/reconciliatie/run.py`
    élke run vast (run-rij + bevindingen), bepaalt de delta t.o.v. de vorige run en mailt alleen
    als er iets te melden is; de CLI-regels zijn ongewijzigd, er komt één RUN-slotregel bij.
    Een mail- of vastlegfout verandert de exit-code nooit.

    Blok 1 vervolgrun 10-09 avond: `--alleen <blok>` (herhaalbaar), `--administratie <uuid|naamdeel>` (alleen
    rlz_dubbel) en `--lees-only`/`--dry-run` (geen run-rij, geen bevindingen, geen mail, geen acceptatie-
    overdracht). `--alleen` vereist `--lees-only`: een deel-run die als 'laatste afgeronde run' zou worden
    vastgelegd laat de kantoorbrede lijst de andere blokken verliezen en mailt hun afwijkingen als 'hersteld'."""
    from app.activa import reconciliatie as activa_reconciliatie
    from app.doorbelasting import aansluiting as doorbelasting_aansluiting
    from app.intercompany import factuurmatch, rekening_courant
    from app.projecten import nummer as projecten_nummer
    from app.reconciliatie import rlz_dubbel
    from app.reconciliatie import run as reconciliatie_run

    alle_blokken = (
        ("bank", _bank_reconciliatie),
        ("documenten", _reconciliatie),
        # Peter 16-09 (blok B): intercompany-factuurmatch — verkoop bij A ↔ inkoop bij B voor élk actief IC-paar.
        (factuurmatch.BLOK, factuurmatch.cli_blok),
        # Peter 16-09 (blok C): rekening-courant-aansluiting per actieve rc_koppeling — ná het intercompany-blok.
        (rekening_courant.BLOK, rekening_courant.cli_blok),
        ("omzet", _omzet_reconciliatie),
        ("doorbelasting", _doorbelasting_reconciliatie),
        # Peter 12-09/16-09 (blok 2): aansluiting bron-verkoop ↔ inkoop in álle doelentiteiten (whitelist-volledigheid,
        # "doel niet in module", ook Zenvoices/handmatig) — ná het doorbelasting-blok.
        (doorbelasting_aansluiting.BLOK, doorbelasting_aansluiting.cli_blok),
        # Blok 6 (08-09): periodieke toets "mogelijk dubbel geboekt in RLZ" (handmatig ingevoerde paren) —
        # eigen blok, schrappen = deze regel + run.BLOKKEN.
        (rlz_dubbel.BLOK, rlz_dubbel.cli_blok),
        # Blok 3 18-09: dubbele projectnummers (buiten de module om in RLZ ontstaan) — soort `project_nummer_dubbel`
        # start in `meten`; schrappen = deze regel + run.BLOKKEN.
        (projecten_nummer.BLOK, projecten_nummer.cli_blok),
        # Activa fase 1 (Peter 21-09): aansluiting module-boekingen ↔ RLZ-activaregister (vijf soorten, alle in `meten`);
        # schrappen = deze regel + run.BLOKKEN.
        (activa_reconciliatie.BLOK, activa_reconciliatie.cli_blok),
    )
    alleen = set(getattr(args, "alleen", None) or [])
    lees_only = bool(getattr(args, "lees_only", False))
    administratie = getattr(args, "administratie", None)
    blokken = tuple(b for b in alle_blokken if not alleen or b[0] in alleen)

    if alleen and not lees_only:
        print(
            "FOUT: --alleen werkt uitsluitend samen met --lees-only — een deel-run mag niet als laatste run worden "
            "vastgelegd (kantoorbrede lijst + delta-mail lezen die).",
            file=sys.stderr,
        )
        return 2
    if administratie:
        if not lees_only or any(naam != rlz_dubbel.BLOK for naam, _ in blokken):
            print(
                "FOUT: --administratie geldt alleen voor `--alleen rlz_dubbel --lees-only` (de andere blokken "
                "kennen geen administratie-filter).",
                file=sys.stderr,
            )
            return 2
        gevonden = _zoek_administraties(administratie)
        if len(gevonden) != 1:
            if not gevonden:
                print(f"FOUT: geen administratie gevonden voor {administratie!r}", file=sys.stderr)
            else:
                print(f"FOUT: {administratie!r} is niet eenduidig:", file=sys.stderr)
                for aid, naam in gevonden:
                    print(f"    {aid}  {naam}", file=sys.stderr)
            return 2
        args.administratie_ids = [gevonden[0][0]]
        print(f"Administratie: {gevonden[0][1]} ({gevonden[0][0]})")

    if lees_only:
        print("LEES-ONLY: geen run-rij, geen bevindingen, geen acceptatie-overdracht, geen mail.")
        exit_code = 0
        for naam, functie in blokken:
            print(f"\n=== {naam}-reconciliatie (lees-only) ===")
            try:
                code = functie(args, verzamelaar=None)
            except Exception as exc:  # noqa: BLE001 — zichtbaar, en door met het volgende blok
                print(f"FOUT       {naam}-reconciliatie viel om: {exc}", file=sys.stderr)
                code = 1
            exit_code = max(exit_code, 1 if code else 0)
        print("\nLEES-ONLY afgerond — niets vastgelegd.")
        return exit_code

    return reconciliatie_run.voer_uit(blokken=blokken, args=args)


def _zoek_administraties(tekst: str) -> list[tuple[uuid.UUID, str]]:
    """(id, naam) op exacte UUID óf naam-substring (hoofdletterongevoelig); meerdere treffers = niet eenduidig."""
    from app.db.models import Administratie
    from app.db.session import scoped_session

    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        try:
            rij = session.get(Administratie, uuid.UUID(tekst))
            return [(rij.id, rij.naam)] if rij is not None else []
        except ValueError:
            rijen = session.scalars(
                select(Administratie).where(Administratie.naam.ilike(f"%{tekst}%")).order_by(Administratie.naam)
            ).all()
            return [(r.id, r.naam) for r in rijen]


def _huidige_afwijkingen(*, bron: str, administratie_id: uuid.UUID) -> list[tuple[uuid.UUID, str, str]]:
    """De afwijkingen zoals ze op dit moment gelden, per bron genormaliseerd tot
    (record_id, soort, detail). Accepteren gaat bewust via een verse run: je kunt daardoor
    alleen iets accepteren dat er écht is, en record_id/soort/detail komen uit de bron zelf in
    plaats van uit een overgetypte terminalregel."""
    if bron == ReconciliatieBron.DOCUMENTEN:
        rapport = reconciliatie.reconcilieer_administratie(administratie_id=administratie_id)
        return [(a.document_id, a.soort, a.detail) for a in rapport.afwijkingen]
    if bron == ReconciliatieBron.BANK:
        bank_rapport = bank_reconciliatie.reconcilieer_bank(administratie_id=administratie_id)
        return [(a.record_id, a.soort, a.detail) for a in bank_rapport.afwijkingen]
    if bron == ReconciliatieBron.DOORBELASTING:
        return [
            (a.boeking_id, a.soort, a.detail)
            for a in doorbelasting_reconciliatie.reconcilieer_doorbelasting(administratie_id)
        ]
    return [(a.boeking_id, a.soort, a.detail) for a in omzet_reconciliatie.reconcilieer_omzet(administratie_id)]


def _reconciliatie_accepteer(args: argparse.Namespace) -> int:
    """Markeer één beoordeelde afwijking als bewust-blijvend (verplichte reden + audit).
    De afwijking blijft in elk rapport staan, alleen niet meer in de exit-code."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1

    items = _huidige_afwijkingen(bron=args.bron, administratie_id=administratie_id)
    gevonden = [
        (record_id, soort, detail)
        for record_id, soort, detail in items
        if acceptatie_service.vingerafdruk(bron=args.bron, soort=soort, detail=detail) == args.vingerafdruk
    ]
    if not gevonden:
        print(
            f"FOUT: geen actuele {args.bron}-afwijking met vingerafdruk {args.vingerafdruk} in deze "
            "administratie. Draai de reconciliatie opnieuw — een afwijking die verdwenen of "
            "veranderd is, hoort niet geaccepteerd te worden.",
            file=sys.stderr,
        )
        for record_id, soort, detail in items:
            vaf = acceptatie_service.vingerafdruk(bron=args.bron, soort=soort, detail=detail)
            print(f"    actueel: [vaf:{vaf}] record={record_id} soort={soort}", file=sys.stderr)
        return 1

    record_id, soort, detail = gevonden[0]
    try:
        acceptatie_id = acceptatie_service.accepteer(
            administratie_id=administratie_id,
            bron=args.bron,
            record_id=record_id,
            soort=soort,
            detail=detail,
            reden=args.reden,
            beheerder_id=beheerder_id,
        )
    except acceptatie_service.AcceptatieFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(
        f"Geaccepteerd: {args.bron}/{soort} [vaf:{args.vingerafdruk}] record={record_id} (acceptatie {acceptatie_id})"
    )
    print("De afwijking blijft zichtbaar in het rapport, maar zet de exit-code niet meer op 1.")
    return 0


def _reconciliatie_intrekken(args: argparse.Namespace) -> int:
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        acceptatie_id = acceptatie_service.trek_in(
            administratie_id=administratie_id,
            bron=args.bron,
            vingerafdruk_waarde=args.vingerafdruk,
            reden=args.reden,
            beheerder_id=beheerder_id,
        )
    except acceptatie_service.AcceptatieFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"Acceptatie {acceptatie_id} ingetrokken — de afwijking telt vanaf de volgende run weer mee.")
    return 0


def _zet_reconciliatie_uitsluiting(args: argparse.Namespace, *, uitgesloten: bool) -> int:
    """Administratie wel/niet meetellen in de exit-code van de dagelijkse reconciliaties
    (migratie 0043). Bevindingen blijven in beide gevallen zichtbaar in het rapport."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        beheer_service.zet_reconciliatie_uitgesloten(
            actor_id=beheerder_id,
            administratie_id=administratie_id,
            uitgesloten=uitgesloten,
            reden=getattr(args, "reden", None),
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    if uitgesloten:
        print(f"Administratie {administratie_id} telt niet meer mee in de reconciliatie-exit-code.")
        print("De bevindingen blijven zichtbaar in het rapport onder de markering UITGESLOTEN.")
    else:
        print(f"Administratie {administratie_id} telt weer volledig mee in de reconciliaties.")
    return 0


def _reconciliatie_acceptaties(args: argparse.Namespace) -> int:
    """Overzicht van de actieve acceptaties, zodat ze nooit uit beeld raken doordat de afwijking
    zelf even niet optreedt."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    rijen = acceptatie_service.actieve_acceptaties_overzicht(administratie_id=administratie_id)
    if not rijen:
        print("Geen actieve acceptaties voor deze administratie.")
        return 0
    for rij in rijen:
        print(
            f"[vaf:{rij.vingerafdruk}] bron={rij.bron} soort={rij.soort} record={rij.record_id} "
            f"sinds {rij.geaccepteerd_op.date().isoformat()} — {rij.reden}"
        )
    return 0


def _intake_postvak_verwerken(args: argparse.Namespace) -> int:
    """E-mail-intake (F3.4): leest het centrale IMAP-postvak leeg en verwerkt elk bericht via
    exact hetzelfde codepad als de .eml-upload (verwerk_eml, idempotent op Message-ID). Actor =
    de systeem-actor (achtergrondverwerking zonder mens). Een ongeldig bericht (geen parsebare
    .eml) wordt zichtbaar overgeslagen én in het postvak als gelezen gemarkeerd (geen eeuwige
    retry-lus) — de run eindigt dan wel op exit 1 zodat de job-failure-alert bijt; een
    verwerkingscrash laat het bericht ongelezen staan (volgende run = retry)."""
    verwerkt = al_eerder = fouten = 0
    # Blok 3 bundel 08-09 (B3): --kanaal declaraties leest het tweede postvak (declaraties@) en markeert het bericht.
    kanaal = getattr(args, "kanaal", None) or "facturen"
    try:
        for inhoud in ImapPostvakBron(kanaal).nieuwe_berichten():
            try:
                resultaat = intake_verwerking.verwerk_eml(
                    inhoud, actor_id=SYSTEEM_ACTOR_ID, bron="imap", kanaal=kanaal
                )
            except intake_verwerking.GeenGeldigIntakeBericht as exc:
                fouten += 1
                print(
                    f"FOUT  ongeldig bericht overgeslagen (blijft in het postvak, gemarkeerd als gelezen): {exc}",
                    file=sys.stderr,
                )
                continue
            if resultaat.al_eerder_verwerkt:
                al_eerder += 1
                print(f"AL-VERWERKT {resultaat.bericht_id}")
            else:
                verwerkt += 1
                bijlagen = ", ".join(f"{r.bestandsnaam}={r.uitkomst}" for r in resultaat.bijlagen)
                print(
                    f"VERWERKT {resultaat.bericht_id}: {len(resultaat.bijlagen)} bijlage(n)"
                    + (f" — {bijlagen}" if bijlagen else "")
                )
    except PostvakNietGeconfigureerd as exc:
        print(f"NIET-GECONFIGUREERD {exc}", file=sys.stderr)
        return 1
    except PostvakFout as exc:
        print(f"FOUT  {exc}", file=sys.stderr)
        return 1
    print(f"Postvak verwerkt: {verwerkt} nieuw, {al_eerder} al eerder verwerkt, {fouten} ongeldig.")
    return 1 if fouten else 0


def _accordeur_herinneringen(args: argparse.Namespace) -> int:
    """Dagelijkse 09:00-herinnering (Cloud Scheduler-job `rlz-accordeur-herinneringen`,
    mockup-besluit "dagelijkse push 09:00 alleen bij >0 open"). Idempotent per dag per
    accordeur; 0 open werk = exit 0 met zichtbare tellers (F3-les: een niets-te-doen-run is
    geen failure). Exit 1 alleen bij échte fouten (verzending mislukt, bezig-blijver,
    volumerem) — dan bijt de F3.2-job-failure-alert."""
    rapport = herinneringen.verstuur_dagelijkse_herinneringen()
    for fout in rapport.fouten:
        print(f"FOUT  {fout}" if rapport.is_fout else f"LET-OP {fout}", file=sys.stderr)
    print(
        "Herinneringen: "
        f"{rapport.verzonden_push} push, {rapport.verzonden_mail} e-mail, "
        f"{rapport.al_verzonden} al verzonden vandaag, "
        f"{rapport.overgeslagen_geen_kanaal} overgeslagen (geen kanaal), "
        f"{rapport.geen_open_werk} accordeur(s) zonder open werk, "
        f"{rapport.mislukt} mislukt, {rapport.onafgemaakt} onafgemaakt, "
        f"{rapport.subscripties_vervallen} subscriptie(s) vervallen gemarkeerd."
    )
    return 1 if rapport.is_fout else 0


def _uren_herinneringen(args: argparse.Namespace) -> int:
    """Dag-einde herinnering "Nog geen uren voor vandaag" (run B 18-09; Cloud Run-job `rlz-uren-herinneringen`, scheduler
    elk kwartier 15:00–18:45 ma–vr Europe/Amsterdam — de job toetst zelf de administratie-tijd, default 16:30). Idempotent
    per veldwerker per dag (claim-tabel); 0 kandidaten / tijd nog niet bereikt = exit 0 mét zichtbare tellers; exit 1 alleen
    bij een échte verzendfout (F3.2-job-failure-alert)."""
    from app.uren import herinnering

    rapport = herinnering.verstuur_dag_einde_herinneringen()
    for fout in rapport.fouten:
        print(f"FOUT  {fout}", file=sys.stderr)
    print(herinnering.rapport_regel(rapport))
    return 1 if rapport.is_fout else 0


def _nieuwe_facturen_melden(args: argparse.Namespace) -> int:
    """Nieuwe-facturen-bundelmelding (Cloud Scheduler-job `rlz-nieuwe-facturen`, ~elke 10 min;
    besluit Peter 2026-08-16: geen melding per factuur — bundelen per accordeur). Stille uren
    (20:00–08:00 Europe/Amsterdam) en 0-nieuw-runs zijn exit 0 met zichtbare tellers; exit 1
    alleen bij échte fouten (verzending mislukt, bezig-blijver, volumerem) — F3.2-alert."""
    rapport = nieuwe_facturen.verstuur_nieuwe_facturen_meldingen()
    # Blok B5 (26-08): dezelfde 10-min-cadans vangt de vraag-meldingen aan accordeurs op die in de
    # stille uren of door een verzendfout nog niet gemeld zijn (idempotent per beurt).
    from app.berichten import vraag_meldingen

    vraag_rapport = vraag_meldingen.verstuur_vraag_meldingen()
    print(
        f"vraag-meldingen: stille_uren={vraag_rapport.stille_uren} kandidaten={vraag_rapport.kandidaten} "
        f"push={vraag_rapport.verzonden_push} mail={vraag_rapport.verzonden_mail} "
        f"geen_kanaal={vraag_rapport.overgeslagen_geen_kanaal} mislukt={vraag_rapport.mislukt}"
    )
    for fout in vraag_rapport.fouten:
        print(f"FOUT       vraag-melding: {fout}", file=sys.stderr)
    # Planning met terugwerkende kracht (Peter/Haci 15-09): bundelmelding "planning week N aangepast" aan de
    # veldwerker, zelfde 10-min-cadans en stille uren; open rijen blijven zichtbaar herkansen.
    from app.uren import planning_meldingen

    planning_rapport = planning_meldingen.verstuur_planning_meldingen()
    print(
        f"planning-meldingen: stille_uren={planning_rapport.stille_uren} open={planning_rapport.kandidaten} "
        f"berichten={planning_rapport.berichten} push={planning_rapport.verzonden_push} "
        f"mail={planning_rapport.verzonden_mail} geen_kanaal={planning_rapport.overgeslagen_geen_kanaal} "
        f"mislukt={planning_rapport.mislukt}"
    )
    for fout in planning_rapport.fouten:
        print(f"FOUT       planning-melding: {fout}", file=sys.stderr)
    if rapport.stille_uren:
        print("Stille uren (20:00–08:00 Europe/Amsterdam) — geen meldingen verstuurd.")
        return 0
    for fout in rapport.fouten:
        print(f"FOUT  {fout}" if rapport.is_fout else f"LET-OP {fout}", file=sys.stderr)
    print(
        "Nieuwe-facturen-meldingen: "
        f"{rapport.verzonden_push} push, {rapport.verzonden_mail} e-mail, "
        f"{rapport.gemelde_documenten} document(en) nieuw gemeld, "
        f"{rapport.accordeurs_zonder_nieuw} accordeur(s) zonder nieuw werk, "
        f"{rapport.overgeslagen_geen_kanaal} overgeslagen (geen kanaal), "
        f"{rapport.mislukt} mislukt, {rapport.onafgemaakt} onafgemaakt, "
        f"{rapport.subscripties_vervallen} subscriptie(s) vervallen gemarkeerd."
    )
    return 1 if rapport.is_fout else 0


def _zet_afgeletterd_event(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Tier-vlag voor het factuur_afgeletterd-event (koppelcontract §3 v1.11 punt 5, besluit
    0018) — default UIT; activatie wacht op vastgoeds verwerker."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_afgeletterd_event_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"afgeletterd_event_ingeschakeld={resultaat} voor administratie {administratie_id}")
    return 0


def _zet_bank_autoboeken(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Opt-in-toggle voor de volautomatische bankstappen (vaste regels automatisch boeken) —
    zelfde patroon als boeken-aan/-uit: Beheerder als audit_event-actor, default UIT."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_bank_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"bank_autoboeken_ingeschakeld={resultaat} voor administratie {administratie_id}")
    if resultaat and not beheer_service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id):
        print(
            "WAARSCHUWING: de boeken-toggle van deze administratie staat uit — automatisch boeken "
            "blijft effectief uit tot die (en 'Boeken platformbreed') ook aan staat."
        )
    return 0


def _zet_duplicaat_autoafvoer(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Platformbrede noodrem duplicaat-auto-afvoer (besluit Peter 04-09 blok A1, migratie 0109) — standaard
    AAN voor de hele module; make-terugval voor de UI-switch op Instellingen › Boeken. Beheerder als
    audit_event-actor."""
    try:
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_duplicaat_autoafvoer_platform(actor_id=beheerder_id, ingeschakeld=ingeschakeld)
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    stand = "AAN — harde duplicaten worden automatisch afgevoerd" if resultaat else "UIT — noodrem actief, alleen nog de één-klik"
    print(f"duplicaat_autoafvoer_platformbreed={resultaat} ({stand})")
    return 0


def _zet_omzet_autoboeken(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Autoboek-opt-in voor OMZETRAPPORTEN (GO Peter 01-09, migratie 0096) — zelfde patroon als de
    andere opt-ins: Beheerder als audit_event-actor, default UIT; make-terugval voor de UI-toggle."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_omzet_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"omzet_autoboeken_ingeschakeld={resultaat} voor administratie {administratie_id}")
    if resultaat and not beheer_service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id):
        print(
            "WAARSCHUWING: de boeken-toggle van deze administratie staat uit — automatisch boeken "
            "blijft effectief uit tot die (en 'Boeken platformbreed') ook aan staat."
        )
    return 0


def _zet_verkoop_autoboeken(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Autoboek-opt-in voor VASTLY-VERKOOP-documenten (migratie 0051, automatisering-first) —
    zelfde patroon als bank-autoboeken: Beheerder als audit_event-actor, default UIT; aanzetten
    kan alleen voor is_vastgoed-administraties (beheer-service dwingt af)."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_verkoop_autoboeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"verkoop_autoboeken_ingeschakeld={resultaat} voor administratie {administratie_id}")
    if resultaat and not beheer_service.haal_boeken_ingeschakeld_op(administratie_id=administratie_id):
        print(
            "WAARSCHUWING: de boeken-toggle van deze administratie staat uit — automatisch boeken "
            "blijft effectief uit tot die (en 'Boeken platformbreed') ook aan staat."
        )
    return 0


def _zet_is_vastgoed(args: argparse.Namespace, *, is_vastgoed: bool) -> int:
    """Vastgoed-koppeling per administratie (avondrun 26-08, S2-draaiboek R1) — begeleide
    terugval naast de Beheerder-toggle in de UI; zelfde service, zelfde audit. UIT neemt
    verkoop-autoboeken zichtbaar mee uit."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        r = beheer_service.zet_is_vastgoed(
            actor_id=beheerder_id, administratie_id=administratie_id, is_vastgoed=is_vastgoed
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"is_vastgoed={r.is_vastgoed} voor administratie {administratie_id}")
    if r.verkoop_autoboeken_uitgezet:
        print("LET OP: verkoop_autoboeken_ingeschakeld is mee UIT gezet (kan alleen bij is_vastgoed) — geauditeerd.")
    if r.is_vastgoed:
        print(
            "factuur_geboekt-/factuur_gestorneerd-events naar Vastly lopen per direct voor deze administratie "
            "(webhook-aflevering-toggle + kanaal-config blijven de failsafes)."
        )
    return 0


def _zet_voorraad(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Opt-in "Voorraad bijhouden" (migratie 0086, blok D 28-08): zelfde patroon als de andere
    toggles; Beheerder als audit_event-actor, default UIT."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_voorraad_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"voorraad_ingeschakeld={resultaat} voor administratie {administratie_id}")
    return 0


def _zet_uren_meerwerk(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Opt-in uren & meerwerk (migratie 0056, steigerbouw-tak — BOUW GO 2026-08-21): zelfde
    patroon als de andere toggles; Beheerder als audit_event-actor, default UIT."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_uren_meerwerk_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"uren_meerwerk_ingeschakeld={resultaat} voor administratie {administratie_id}")
    return 0


def _zet_boeken(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Boeken-failsafe (a), per-administratie deel — hergebruikt app.beheer.service (zelfde
    servicefunctie als het instellingen-scherm straks aanroept), met de Beheerder als actor
    (zelfde patroon als bootstrap-beheerder/import-env-credentials: BEHEERDER_ID-parameter),
    dus met het gebruikelijke audit_event erbij."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_boeken_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"boeken_ingeschakeld={resultaat} voor administratie {administratie_id}")
    if resultaat and not beheer_service.haal_globale_kill_switch_op():
        print(
            "WAARSCHUWING: 'Boeken platformbreed' staat UIT (boeken staat plat voor alle administraties) — "
            "boeken blijft effectief uit tot die ook aan staat."
        )
    return 0


def _boeken_aan(args: argparse.Namespace) -> int:
    return _zet_boeken(args, ingeschakeld=True)


def _boeken_uit(args: argparse.Namespace) -> int:
    return _zet_boeken(args, ingeschakeld=False)


def _boeken_status(args: argparse.Namespace) -> int:
    kill_switch_aan = beheer_service.haal_globale_kill_switch_op()
    # Label eenduidig (kliktest-les Peter 25-08): "aan" = boeken kan, "uit" = boeken staat plat —
    # de oude term "kill switch: uit" werd gelezen als "noodstop niet actief".
    stand = "AAN — boeken kan" if kill_switch_aan else "UIT — boeken staat plat (noodstop)"
    print(f"Boeken platformbreed: {stand}")
    print()
    overzicht = beheer_service.overzicht_boeken_status()
    if not overzicht:
        print("(geen administraties geregistreerd)")
        return 0
    print(f"{'toggle':<6} {'effectief':<11} administratie")
    for item in overzicht:
        effectief_aan = kill_switch_aan and item.boeken_ingeschakeld
        print(
            f"{'AAN' if item.boeken_ingeschakeld else 'uit':<6} "
            f"{'AAN' if effectief_aan else 'uit':<11} {item.administratie_id}  {item.naam}"
        )
    return 0


def _zet_ai_extractie(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """AVG-gate voor AI-extractie (migratie 0014) — zelfde patroon als de boeken-toggle:
    hergebruikt app.beheer.service met de Beheerder als audit_event-actor. Default UIT; bedoeld
    om alleen de test-administratie/eigen facturen aan te zetten tot de AVG-volgorde rond is
    (docs/BOUWPLAN.md)."""
    try:
        administratie_id = uuid.UUID(args.administratie_id)
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_ai_extractie_ingeschakeld(
            actor_id=beheerder_id, administratie_id=administratie_id, ingeschakeld=ingeschakeld
        )
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"ai_extractie_ingeschakeld={resultaat} voor administratie {administratie_id}")
    return 0


def _ai_extractie_aan(args: argparse.Namespace) -> int:
    return _zet_ai_extractie(args, ingeschakeld=True)


def _ai_extractie_uit(args: argparse.Namespace) -> int:
    return _zet_ai_extractie(args, ingeschakeld=False)


def _webhook_afleveren(args: argparse.Namespace) -> int:
    """Eén verwerk-run van de webhook-afleveraar (fase-vervolg: Cloud Scheduler → Cloud Run job
    roept dit commando aan — zelfde patroon als sync-alles). Onvoldoende geconfigureerd of
    toggle uit = nette melding + exit 0, géén fout: rijen blijven openstaand (failsafe)."""
    rapport = webhook_afleveraar.verwerk_openstaande_webhooks()
    if rapport.overgeslagen_reden:
        print(f"OVERGESLAGEN: {rapport.overgeslagen_reden}")
        return 0
    print(
        f"Afgeleverd: {rapport.afgeleverd}, poging(en) mislukt: {rapport.poging_mislukt}, "
        f"dead-letter: {rapport.dead_letter}, geweigerd (geen vastgoed): {rapport.geweigerd_geen_vastgoed}"
    )
    for fout in rapport.fouten:
        print(f"FOUT  {fout}", file=sys.stderr)
    return 1 if (rapport.dead_letter or rapport.geweigerd_geen_vastgoed) else 0


def _webhook_redrive(args: argparse.Namespace) -> int:
    """Re-drive van dead-letter-rijen (expliciete admin-actie, audit_event per rij): mislukt →
    openstaand met vol retry-budget. Het normale herstel na langdurige downtime van de
    vastgoed-ontvanger — draai daarna (of wacht op) webhook-afleveren."""
    try:
        beheerder_id = uuid.UUID(args.beheerder_id)
        outbox_id = uuid.UUID(args.outbox_id) if args.outbox_id else None
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    hersteld = webhook_afleveraar.herstel_dead_letters(actor_id=beheerder_id, outbox_id=outbox_id)
    if hersteld == 0:
        doel = f"outbox-rij {outbox_id}" if outbox_id else "dead-letter-rijen"
        print(f"Niets teruggezet: geen {doel} met status 'mislukt' gevonden.")
        return 0
    print(f"{hersteld} rij(en) teruggezet naar openstaand — de afleveraar pakt ze bij de volgende run op.")
    return 0


def _zet_intake_ai(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Intake-AI-toggle (migratie 0029) — zelfde patroon als webhook-aflevering-aan/-uit.
    Default UIT (AVG-gate voor AI op nog-niet-toegewezen intake-documenten)."""
    try:
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_intake_ai_ingeschakeld(actor_id=beheerder_id, ingeschakeld=ingeschakeld)
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"intake_ai_ingeschakeld={resultaat}")
    return 0


def _zet_webhook_aflevering(args: argparse.Namespace, *, ingeschakeld: bool) -> int:
    """Webhook-aflevering-toggle — zelfde patroon als boeken-aan/-uit: hergebruikt
    app.beheer.service met de Beheerder als audit_event-actor. Default UIT (migratie 0025)."""
    try:
        beheerder_id = uuid.UUID(args.beheerder_id)
    except ValueError as exc:
        print(f"FOUT: ongeldige UUID ({exc})", file=sys.stderr)
        return 1
    try:
        resultaat = beheer_service.zet_webhook_aflevering_ingeschakeld(actor_id=beheerder_id, ingeschakeld=ingeschakeld)
    except beheer_service.BeheerFout as exc:
        print(f"FOUT: {exc}", file=sys.stderr)
        return 1
    print(f"webhook_aflevering_ingeschakeld={resultaat}")
    if resultaat and webhook_afleveraar.haal_aflever_config_op() is None:
        print(
            "WAARSCHUWING: webhook_doel_url en/of WEBHOOK_HMAC_SECRET is niet geconfigureerd — "
            "aflevering blijft effectief uit (rijen blijven openstaand)."
        )
    return 0


def _importeer_env_credentials(args: argparse.Namespace) -> int:
    """Eenmalige overzet-hulp: de bekende .env-logins de credential-store in (zie
    app/credentialstore/service.py::importeer_env_credentials voor welke prefixen en waarom
    sommige bewust overgeslagen worden)."""
    beheerder_id = uuid.UUID(args.beheerder_id)
    resultaten = credentialstore_service.importeer_env_credentials(actor_id=beheerder_id)
    for prefix, uitkomst in resultaten.items():
        print(f"{prefix}: {uitkomst}")
    return 0


def _seed_boekingsgeheugen(args: argparse.Namespace) -> int:
    """Achtergrond-batch (CLI/Cloud Run job, nooit synchroon in een request): RLZ-seed van het
    boekingsgeheugen uit PurchaseInvoices+Lines. Idempotent en hervatbaar — gewoon opnieuw
    draaien na een afgebroken run."""
    rapport = geheugen_seed.seed_boekingsgeheugen(
        administratie_id=uuid.UUID(args.administratie_id),
        maanden=args.maanden,
    )
    print(
        f"Seed {rapport.administratie_id}: {rapport.aantal_facturen_bekeken} facturen bekeken, "
        f"{rapport.aantal_facturen_geseed} geseed, {rapport.observaties_nieuw} nieuwe observaties, "
        f"{rapport.observaties_bestonden_al} bestonden al, "
        f"{rapport.overgeslagen_zonder_entity} overgeslagen zonder crediteur, "
        f"{rapport.overgeslagen_zonder_bruikbare_regels} zonder bruikbare regels."
    )
    return 0


def _reconciliatie_run_blokken() -> tuple[str, ...]:
    """`--alleen`-keuzelijst van `reconciliatie-alles` = `app.reconciliatie.run.BLOKKEN` (één bron; 19-09)."""
    from app.reconciliatie import run as reconciliatie_run

    return tuple(reconciliatie_run.BLOKKEN)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.cli", description="RLZ Boekingsmodule beheer-CLI")
    subparsers = parser.add_subparsers(dest="commando", required=True)

    bootstrap_parser = subparsers.add_parser(
        "bootstrap-beheerder",
        help="Maak de allereerste Beheerder aan — weigert als er al een Beheerder bestaat.",
    )
    bootstrap_parser.add_argument("--naam", required=True)
    bootstrap_parser.add_argument("--e-mail", required=True, dest="e_mail")

    subparsers.add_parser(
        "sync-alles",
        help="Sync Ledgers/TaxRates/Vendors/Projects voor alle administraties (nachtelijke sync).",
    )

    subparsers.add_parser(
        "kantoor-digest",
        help="Maandagochtend-digest kantoor (D2 01-09): één weekmail per kantoormedewerker mét scope — alleen bij "
        "iets te melden, idempotent per ISO-week, opt-out per gebruiker (job rlz-kantoor-digest, ma 07:30).",
    )

    from app.autoboek_kandidaten.cli_cmd import dispatch as dispatch_autoboek_leren  # blok A 10-09
    from app.autoboek_kandidaten.cli_cmd import register as register_autoboek_leren

    register_autoboek_leren(subparsers)  # autoboek-drempel-zetten, autoboek-leren-rapport
    from app.beheer.administratienaam_cli import (  # 15-09 (0144)
        dispatch as dispatch_administratienaam,
    )
    from app.beheer.administratienaam_cli import (
        register as register_administratienaam,
    )
    from app.geheugen.btw_default_cli import dispatch as dispatch_btw_default  # 14-09 (0143)
    from app.geheugen.btw_default_cli import register as register_btw_default

    register_btw_default(subparsers)  # btw-default-rapport (lees-only)
    from app.beheer.bua_cli import dispatch as dispatch_bua  # 21-09: bua-kandidaten (lees-only) + bua-kenmerk-zetten
    from app.beheer.bua_cli import register as register_bua

    register_bua(subparsers)
    from app.documenten.btw_tarief_cli import dispatch as dispatch_btw_tarief  # 18-09 (lees-only)
    from app.documenten.btw_tarief_cli import register as register_btw_tarief

    register_btw_tarief(subparsers)  # btw-tarief-afwijking-rapport (lees-only, nameting-allowlist)
    register_administratienaam(subparsers)  # administratie-naam-bron-backfill (data-stap 0144, dry-run default)
    from app.appupdate.cli_cmd import dispatch as dispatch_appupdate  # OTA 16-09 nacht
    from app.appupdate.cli_cmd import register as register_appupdate
    from app.doorbelasting.aansluiting import dispatch as dispatch_doorbelasting_aansluiting  # blok 2 16-09 nacht
    from app.doorbelasting.aansluiting import register as register_doorbelasting_aansluiting
    from app.werkvoorraad.cli_cmd import dispatch as dispatch_werkvoorraad_tellers  # blok 6 11-09
    from app.werkvoorraad.cli_cmd import register as register_werkvoorraad_tellers

    register_werkvoorraad_tellers(subparsers)  # werkvoorraad-tellers-herrekenen
    register_doorbelasting_aansluiting(subparsers)  # doorbelasting-aansluiting (lees-only)
    register_appupdate(subparsers)  # app-bundel-registreren / app-bundels
    subparsers.add_parser(
        "autoboek-kandidaten-herbereken",
        help="Autoboek-kandidaten-motor los draaien (loopt óók dagelijks mee in sync-alles; puur code, geen RLZ-calls).",
    )

    dubbelen_auto_parser = subparsers.add_parser(
        "crediteuren-dubbelen-auto",
        help="Crediteuren-dubbelen (blok B13 07-09): eenduidige clusters automatisch afhandelen — verliezers worden "
        "in de module onbruikbaar, geheugen/kenmerk/IBAN's en open boekvoorstellen gaan naar de voorkeur (audit, "
        "terugdraaibaar via de UI). Twijfel blijft mens. Puur code, geen RLZ-calls; loopt óók dagelijks mee in "
        "sync-alles.",
    )
    dubbelen_auto_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run", help="Alleen classificeren en tellen; niets gewijzigd."
    )
    dubbelen_auto_parser.add_argument(
        "--administratie", default=None, metavar="UUID", help="Beperk de run tot deze administratie."
    )

    ic_parser = subparsers.add_parser(
        "intercompany-leverancier-markeren",
        help="Markeer één crediteur als intercompany-leverancier in één administratie (dezelfde servicelaag als "
        "Instellingen › Administraties › ‹BV› › Klant-accordering; blok 2 nachtrun 08/09-09). Klant-accordering wordt "
        "voor diens facturen overgeslagen. Audit oud→nieuw op de opgegeven actor; idempotent; geen RLZ-calls.",
    )
    ic_parser.add_argument(
        "--administratie", required=True, metavar="UUID|NAAM", help="Administratie (uuid of exacte naam)."
    )
    ic_parser.add_argument(
        "--crediteur",
        required=True,
        metavar="GUID|NAAM",
        help="Crediteur (RLZ-vendor-GUID of unieke naam in de cache).",
    )
    ic_parser.add_argument("--actor-email", required=True, metavar="E-MAIL", help="Beheerder namens wie (audit-actor).")
    ic_parser.add_argument("--reden", required=True, help="Reden (komt in de audit).")
    ic_parser.add_argument("--dry-run", action="store_true", dest="dry_run", help="Alleen tonen wat gezet zou worden.")
    ic_parser.add_argument("--verwijderen", action="store_true", help="Vlag weer weg (actief=False), i.p.v. zetten.")

    werklijst_nazorg_parser = subparsers.add_parser(
        "crediteuren-werklijst-nazorg",
        help="Eenmalige nazorg (besluit Peter 07-09, beslispunt 7): open legacy-regels van de RLZ-werklijst "
        "(crediteur_archiveer_werklijst, vóór blok B13) omzetten in markeringen via het gewone afhandel-pad — bron "
        "'mens', actor = oorspronkelijke aanmaker; de regel wordt 'gedaan' (bron 'nazorg'), nooit verwijderd. "
        "Idempotent; geen RLZ-calls.",
    )
    werklijst_nazorg_parser.add_argument(
        "--dry-run", action="store_true", dest="dry_run", help="Alleen tellen per administratie; niets gewijzigd."
    )
    werklijst_nazorg_parser.add_argument(
        "--administratie", default=None, metavar="UUID", help="Beperk de run tot deze administratie."
    )

    projectverdeling_parser = subparsers.add_parser(
        "projectverdeling-hercontrole",
        help="Projectverdeling-hercontrole los draaien: geboekte pro-rato-verdelingen herrekenen tegen de actuele "
        "omzetstand van dezelfde maand (loopt maandelijks mee in sync-alles; puur code, geen RLZ-/Odoo-calls).",
    )
    projectverdeling_parser.add_argument(
        "--forceer", action="store_true", help="Alle verdelingen herrekenen, ook buiten de maandcadans."
    )

    voorraad_hernorm_parser = subparsers.add_parser(
        "voorraad-hernormaliseer",
        help="Voorraad: alle feitenregels hernormaliseren (soort-label + artikelcodes, geen RLZ-calls) + rapport",
    )
    voorraad_hernorm_parser.add_argument("--administratie-id", dest="administratie_id", default=None)
    voorraad_hernorm_parser.add_argument(
        "--zonder-ai", dest="zonder_ai", action="store_true", help="alleen het deterministische pad"
    )

    voorraad_rlz_parser = subparsers.add_parser(
        "voorraad-rlz-sync",
        help="Voorraad-uitstroom uit RLZ-verkoopfacturen (leesroute, blok A 29-08) én — sinds blok D 03-09 — uit "
        "Odoo-verkoopfacturen vanaf de voorraad-knip (alleen-lezen koppeling); loopt ook mee in sync-alles; hier "
        "voor een eerste/volledige run of één administratie.",
    )
    voorraad_rlz_parser.add_argument("--administratie-id", dest="administratie_id", default=None)
    voorraad_rlz_parser.add_argument(
        "--volledig",
        action="store_true",
        help="Lees het lopende jaar opnieuw i.p.v. incrementeel (max(datum) − 14 dagen).",
    )

    odoo_leesbron_parser = subparsers.add_parser(
        "odoo-leesbron",
        help="Odoo als LEESBRON voor een RLZ-administratie (blok D 03-09): alleen-lezen koppeling + voorraad-knip "
        "(Universal Verkoop, company 3). Koppelen: --odoo-url --company-id [--knip] met de API-key uit "
        "$ODOO_API_KEY (nooit op de commandoregel); alleen de knip zetten: --knip zonder --odoo-url.",
    )
    odoo_leesbron_parser.add_argument("--administratie-id", dest="administratie_id", required=True)
    odoo_leesbron_parser.add_argument("--odoo-url", dest="odoo_url", default=None)
    odoo_leesbron_parser.add_argument("--company-id", dest="company_id", type=int, default=None)
    odoo_leesbron_parser.add_argument("--api-gebruiker", dest="api_gebruiker", default=None)
    odoo_leesbron_parser.add_argument(
        "--knip", dest="knip", default=None, help="voorraad-knip JJJJ-MM-DD (leeg laten = geen knip; 'geen' = wissen)"
    )

    subparsers.add_parser(
        "projecten-cijfers-sync",
        help="Ververs de project_regel_cache (RLZ-documentregels mét projectreferentie — de "
        "rekenbron voor resultaat-per-project) voor alle administraties mét de "
        "uren-&-meerwerk-opt-in, via de run-administratie (status zichtbaar in de UI).",
    )

    subparsers.add_parser(
        "bank-sync-wachtrij",
        help="Verwerk de wachtrij van bank-verversingsruns (entrypoint van de on-demand Cloud "
        "Run-job rlz-bank-sync — het openen van het bankscherm zet de run klaar en triggert "
        "deze job; geen wachtrij = snelle no-op).",
    )

    subparsers.add_parser(
        "eerste-sync-wachtrij",
        help="Verwerk de wachtrij van eerste-sync-runs van nieuw aangesloten administraties "
        "(entrypoint van de on-demand Cloud Run-job rlz-eerste-sync, wizard 26-08 punt 5; lege "
        "wachtrij = snelle no-op).",
    )

    subparsers.add_parser(
        "terugkerend-herbereken-wachtrij",
        help="Verwerk de wachtrij van kantoorbrede terugkerend-herberekeningen (entrypoint van de "
        "on-demand Cloud Run-job rlz-terugkerend-herbereken — '⟳ Herbereken alles' op Inzicht › "
        "Terugkerende facturen zet de run klaar en triggert deze job; lege wachtrij = snelle no-op).",
    )

    subparsers.add_parser(
        "extractie-wachtrij-verwerken",
        help="Werk de AI-extractie-wachtrij af (entrypoint van de on-demand Cloud Run-job "
        "rlz-extractie-wachtrij, feedbackronde 26-08 punt 4 — een groot document triggert de job, "
        "het scheduler-vangnet draait 'm elke 10 min; lege wachtrij = snelle no-op).",
    )

    subparsers.add_parser(
        "boek-wachtrij-verwerken",
        help="Achtergrond-schrijver 'Boeken in RLZ' (boeken sneller 18-09): alle documenten op wordt_geboekt afronden — "
        "job rlz-boek-wachtrij (on-demand trigger + scheduler-vangnet 2 min); idempotent via een claim per boeking, "
        "gestrande claims (> 10 min) worden hervat; lege wachtrij = snelle no-op.",
    )

    heraanbied_parser = subparsers.add_parser(
        "extractie-heraanbieden",
        help="Bied documenten waarvan de laatste AI-extractie sinds --sinds faalde opnieuw aan "
        "via de bestaande opnieuw-route (nazorg union-limiet-bugfix 31-08); --filter beperkt op "
        "fouttekst-substring, --dry-run telt alleen.",
    )
    heraanbied_parser.add_argument("--sinds", required=True, help="Datum (YYYY-MM-DD, Europe/Amsterdam).")
    heraanbied_parser.add_argument(
        "--filter", default=None, help="Alleen fouten waarvan de tekst deze substring bevat (case-insensitief)."
    )
    heraanbied_parser.add_argument("--dry-run", action="store_true", help="Alleen tellen, niets heraanbieden.")

    herlees_parser = subparsers.add_parser(
        "intake-herlezen",
        help="Nazorg intake-splitsingsbug (02-09): verzamelbak-PDF's die sinds --sinds op een verworpen/"
        "mislukt intake-AI-voorstel strandden opnieuw lezen met de gefixte keten (tenaamstelling, "
        "toewijzing, splitsingsvoorstel). Idempotent (al herlezen = overgeslagen, --opnieuw heft op); "
        "--dry-run telt alleen; --alle-redenen neemt óók rijen zonder tenaamstelling mee.",
    )
    herlees_parser.add_argument("--sinds", required=True, help="Datum (YYYY-MM-DD, Europe/Amsterdam).")
    herlees_parser.add_argument("--dry-run", action="store_true", help="Alleen tellen, niets herlezen.")
    herlees_parser.add_argument("--opnieuw", action="store_true", help="Ook al eerder herlezen rijen opnieuw.")
    herlees_parser.add_argument(
        "--alle-redenen", action="store_true", help="Ook 'niet eenduidig'-rijen zonder gelezen tenaamstelling."
    )
    herlees_parser.add_argument(
        "--zonder-toewijzen",
        action="store_true",
        help="Een eenduidige match niet toewijzen maar als suggestie op de rij zetten (de mens wijst zelf "
        "in bulk toe — blok A3/B 02-09). UBL-rijen (RLZ-export) worden altijd meegenomen: deterministisch, geen AI.",
    )
    herlees_parser.add_argument(
        "--alleen-ubl",
        action="store_true",
        help="Alleen UBL-rijen herlezen (geen AI-call, geen AI-kosten, geen intake-AI-gate nodig) — de RLZ-export-nazorg.",
    )

    opschoon_parser = subparsers.add_parser(
        "toewijzing-regels-opschonen",
        help="Data-nazorg afzender-geheugen (02-09): actieve afzender-regels op kantoor-/doorstuurdomeinen of "
        "met een meerduidige historie (≥ 3 doelen) deactiveren mét audit — niets verwijderen. --dry-run telt alleen.",
    )
    opschoon_parser.add_argument("--dry-run", action="store_true", help="Alleen rapporteren, niets wijzigen.")

    nabundel_parser = subparsers.add_parser(
        "verzamelbak-nabundelen",
        help="Nabundel-nazorg (03-09): verzamelbak-UBL's waarvan de PDF-tegenhanger uit dezelfde e-mail al is "
        "toegewezen alsnog aan dat PDF-document koppelen (UBL = data, PDF = beeld, her-extractie uit de UBL; "
        "UBL-rij → samengevoegd). Alleen te_controleren/handmatig_afmaken; opgeslagen voorstel blijft staan; "
        "twijfel = overgeslagen mét reden. Geen AI. --dry-run toetst alles en schrijft niets.",
    )
    nabundel_parser.add_argument("--dry-run", action="store_true", help="Alleen rapporteren, niets wijzigen.")
    nabundel_parser.add_argument(
        "--ook-toegewezen",
        action="store_true",
        help="Dubbelparen (03-09): óók een al toegewezen UBL-DOCUMENT dat naast zijn PDF-tegenhanger in dezelfde "
        "administratie staat (zelfde e-mail + naamstam) in dat PDF-document nabundelen; het UBL-document gaat naar "
        "samengevoegd (nooit verwijderd). Zelfde poorten aan beide kanten. Byte-identieke PDF-dubbelen uit dezelfde "
        "e-mail (07-09) worden vóór de paarvorming samengevouwen in het gehouden exemplaar (geboekt > verder verwerkt "
        "> opgeslagen boekvoorstel > oudste); afgewezen exemplaren tellen niet meer mee.",
    )
    nabundel_parser.add_argument(
        "--administratie",
        default=None,
        metavar="UUID",
        help="Beperk de run tot paren waarvan het leidende document in deze administratie staat (bereik-begrenzing).",
    )

    backfill_parser = subparsers.add_parser(
        "duplicaten-backfill",
        help="Blok 1 07-09: bestaande duplicaten (zelfde bestand of zelfde genormaliseerde referentie + bedrag) over "
        "alle actieve administraties afvoeren mét kruisverwijzing — zelfde motor als de auto-afvoer, buiten de dagrem, "
        "noodrem gerespecteerd, UBL+PDF-bundelparen en 'geen duplicaat'-afmeldingen beschermd. --dry-run schrijft "
        "niets.",
    )
    backfill_parser.add_argument("--dry-run", action="store_true", help="Alleen rapporteren, niets wijzigen.")
    backfill_parser.add_argument("--administratie", default=None, metavar="UUID", help="Beperk tot één administratie.")

    refnorm_parser = subparsers.add_parser(
        "referentie-norm-backfill",
        help="16-09 (migratie 0147): vul boekvoorstel.referentie_norm (genormaliseerde factuurreferentie) voor "
        "bestaande rijen — afgeleide kolom, idempotent, geen tijdlijn/audit. --dry-run telt alleen.",
    )
    refnorm_parser.add_argument("--dry-run", action="store_true", help="Alleen rapporteren, niets wijzigen.")
    refnorm_parser.add_argument("--administratie", default=None, metavar="UUID", help="Beperk tot één administratie.")

    activa_parser = subparsers.add_parser(
        "activa-nulmeting",
        help="16-09 (STAP-0 activa): LEES-ONLY nulmeting per RLZ-administratie — MVA-rekeningen (vlag + AccountType 3 + "
        "0xxx), saldo, aantal FixedAssets in het register, module-regels op die rekeningen. Geen writes.",
    )
    activa_parser.add_argument("--dagen", type=int, default=400, help="Venster module-regels in dagen (default 400).")
    activa_parser.add_argument(
        "--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie."
    )

    extern_rapport_parser = subparsers.add_parser(
        "duplicaat-extern-rapport",
        help="16-09 (Zenvoices-casus): LEES-ONLY rapport 'mogelijk eerder dubbel geboekt' — geboekte module-facturen "
        "van de laatste N dagen genormaliseerd vergeleken met álle RLZ-inkoopfacturen in dat venster (één gepagineerde "
        "leesroute per administratie). Geen writes; Odoo-administraties zichtbaar overgeslagen.",
    )
    extern_rapport_parser.add_argument("--dagen", type=int, default=400, help="Venster in dagen (default 400).")
    extern_rapport_parser.add_argument(
        "--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie."
    )

    binder_parser = subparsers.add_parser(
        "omzet-binder-rapport",
        help="Blok C 16-09 (Van Boxtel): LEES-ONLY — (A) module-Receipts waarvan de RLZ-categorie niet onder binder "
        "Inkomsten staat, (B) geboekte inkoopfacturen die omzet zijn (alle regels op omzetrekeningen; --met-pdf óók "
        "herkende omzetbron-PDF's), mét factuurdatum en aangiftepoort-stand. Geen writes.",
    )
    binder_parser.add_argument("--dagen", type=int, default=400, help="Venster in dagen voor B (default 400).")
    binder_parser.add_argument(
        "--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie."
    )
    binder_parser.add_argument(
        "--met-pdf", action="store_true", help="Ook PDF-herkenning (ProfX) als signaal voor B (trager)."
    )
    binder_parser.add_argument(
        "--max-per-administratie", type=int, default=200, help="Max Receipts per administratie voor A."
    )

    stores_parser = subparsers.add_parser(
        "omzet-stores-migreren",
        help="Data-stap 0151 (16-09 avond): bron_instellingen.stores per administratie → platformbrede store-routering "
        "(omzet_store_routering). Default dry-run; --schrijf maakt de rijen aan (idempotent; conflict = nooit "
        "overschrijven).",
    )
    stores_parser.add_argument("--schrijf", action="store_true", help="Rijen aanmaken (zonder = dry-run).")

    inkoopstroom_parser = subparsers.add_parser(
        "kassarapporten-in-inkoopstroom",
        help="Blok A2 ProfX 16-09: LEES-ONLY rapport van PDF-documenten die als inkoopfactuur in de module staan maar "
        "op inhoud een ProfX Journaal/Margerapport zijn — per administratie + verzamelbak; geboekt = alleen melden, "
        "de rest via 'Type wijzigen → kassarapport'. Geen writes, geen AI.",
    )
    inkoopstroom_parser.add_argument("--dagen", type=int, default=90, help="Venster in dagen (default 90).")
    inkoopstroom_parser.add_argument(
        "--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie."
    )

    autotype_parser = subparsers.add_parser(
        "kassarapport-autotype-nazorg",
        help="Peter 19-09: werkvoorraad-inkoopfacturen mét een eenduidige parser-treffer (ProfX/dagstaat/kascheck/"
        "pilates) alsnog automatisch omzetten naar kassarapport — tijdlijn + audit per document, één regel per "
        "administratie. --dry-run = 0 writes; idempotent. Geen AI, geen RLZ-call.",
    )
    autotype_parser.add_argument("--dry-run", action="store_true", help="Alleen rapporteren, niets wijzigen.")
    autotype_parser.add_argument(
        "--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie."
    )

    cache_legen_parser = subparsers.add_parser(
        "checks-cache-legen",
        help="21-09 (BUG IBAN-wissel ná vier-ogen-akkoord): álle nog geldige externe-checks-cache-rijen "
        "(boekhouding.check_extern_cache) ongeldig markeren — rapporten van vóór de invalidatie-fix dragen anders "
        "tot 15 min een verouderde vertrouwde IBAN-set. Volgende checks-run draait vers. --dry-run telt alleen; "
        "idempotent.",
    )
    cache_legen_parser.add_argument("--dry-run", action="store_true", help="Alleen tellen, niets wijzigen.")
    cache_legen_parser.add_argument(
        "--administratie", default=None, metavar="UUID|NAAMDEEL", help="Beperk tot één administratie."
    )
    cache_legen_parser.add_argument("--alles", action="store_true", help="Alle actieve administraties.")

    status_backfill_parser = subparsers.add_parser(
        "duplicaat-status-backfill",
        help="Blok 3 08-09: legacy duplicaat-afvoer-rijen (status afgewezen mét een open afwijzing die een "
        "duplicaat-kruisverwijzing draagt) omzetten naar de eigen terminale status afgevoerd_duplicaat (migratie "
        "0122) — via de statusmachine, mét tijdlijn + audit. --dry-run schrijft niets; idempotent.",
    )
    status_backfill_parser.add_argument("--dry-run", action="store_true", help="Alleen rapporteren, niets wijzigen.")
    status_backfill_parser.add_argument(
        "--administratie", default=None, metavar="UUID", help="Beperk tot één administratie."
    )

    passkeys_markeren_parser = subparsers.add_parser(
        "app-passkeys-markeren",
        help="Markeer legacy app-passkeys als 'niet meer gebruikt' (08-09) — niets verwijderen, sessies blijven",
    )
    passkeys_markeren_parser.add_argument("--dry-run", action="store_true", help="alleen tellen, niets schrijven")

    periode_parser = subparsers.add_parser(
        "periode-backfill",
        help="Blok 7 08-09: factuurperiode-kolommen (migratie 0120) vullen voor GEBOEKTE documenten mét boekvoorstel "
        "maar zonder periode — AI-veld `periode` uit het opgeslagen veldvoorstel, anders de week van de factuurdatum; "
        "een gevulde stand (ook mens) wordt nooit overschreven; tijdlijn + audit per document. --dry-run schrijft "
        "niets.",
    )
    periode_parser.add_argument("--dry-run", action="store_true", help="Alleen rapporteren, niets wijzigen.")
    periode_parser.add_argument("--administratie", default=None, metavar="UUID", help="Beperk tot één administratie.")
    periode_parser.add_argument(
        "--alle-statussen",
        action="store_true",
        help="Ook niet-geboekte documenten (alles behalve verwijderd/niet_toegewezen) — standaard alleen geboekt.",
    )

    subparsers.add_parser(
        "bewaking-probe",
        help="Synthetische bewaking (kwartier-job rlz-bewaking, 31-08): health/DB/documentopslag/"
        "mailkanaal/RLZ-leesroute + 1×/uur AI-call en extractie-foutratio; alert per SMTP bij 2 "
        "opeenvolgende fouten, herstelmelding zodra weer groen.",
    )

    subparsers.add_parser(
        "deploy-smoketest",
        help="Post-deploy-smoketest (deploy.yml, 31-08): AI-schema-zelftest + DB/migratieversie "
        "+ mailkanaal-config + (11-09) service en jobs op hetzelfde beeld; exit 1 = deploy-run rood.",
    )
    mislukt = subparsers.add_parser(
        "deploy-mislukt",
        help="Ochtendrun 11-09: mail naar het beheer dat de deploy-workflow rood is afgebroken (aangeroepen door "
        "deploy.yml `if: failure()` via de job rlz-bewaking — bestaand SMTP-kanaal, geen secret in GitHub Actions).",
    )
    mislukt.add_argument("--sha", default=None, help="Commit-sha van de mislukte deploy.")
    mislukt.add_argument("--run-url", default=None, dest="run_url", help="URL van de GitHub Actions-run.")
    mislukt.add_argument("--stap", default=None, help="Optioneel: branch/stap-omschrijving.")

    subparsers.add_parser(
        "projecten-cijfers-wachtrij",
        help="Verwerk de wachtrij van projectcijfers-syncruns (entrypoint van de on-demand "
        "Cloud Run-job rlz-projecten-cijfers — de sync-knop zet de run klaar en triggert "
        "deze job; geen wachtrij = snelle no-op).",
    )

    seed_parser = subparsers.add_parser(
        "seed-boekingsgeheugen",
        help="RLZ-seed van het boekingsgeheugen (PurchaseInvoices+Lines) voor één administratie — "
        "idempotent, hervatbaar, achtergrond-batch.",
    )
    seed_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    seed_parser.add_argument(
        "--maanden",
        type=int,
        default=None,
        help="Recency-cap in maanden (default: settings.boekingsgeheugen_seed_maanden).",
    )

    subparsers.add_parser(
        "reconciliatie",
        help="Vergelijk geboekte documenten met de werkelijke RLZ-staat en rapporteer afwijkingen.",
    )

    bank_sync_parser = subparsers.add_parser(
        "bank-sync",
        help="Bank-sync (rekeningen/mutaties/open posten + afletter-verificatie + Vastly-detectie "
        "+ opt-in autoboeken) voor één of alle administraties.",
    )
    bank_sync_parser.add_argument(
        "--administratie-id",
        default=None,
        dest="administratie_id",
        help="Alleen deze administratie (default: alle).",
    )

    register_bank(subparsers)  # blok B 10-09: bank-voorstellen-lezen + bank-historie-backfill (app/bank/cli_cmd.py)
    register_projecten(subparsers)  # blok 3 18-09: projecten-afsluit-kandidaten + projecten-dubbele-nummers (lees-only)
    register_projectverdeling(subparsers)  # opdracht 19-09: projectverdeling-afgesloten-rapport (lees-only)
    register_verplichting(subparsers)  # 18-09: verplichting-match-herberekenen (SCHRIJVEND, nazorg onderweg-verbruik)
    register_accordering(subparsers)  # blok 7 11-09: staande-goedkeuring-voorstellen-lezen (app/accordering/cli_cmd.py)
    register_migratie(subparsers)  # blok D1 10-09: migratie-schoonlijst (app/migratie/cli_cmd.py)
    register_panden(subparsers)  # blok D2 10-09: pandenregister-afleiden (app/panden/cli_cmd.py)
    register_pand_toewijzen(subparsers)  # 21-09 VGG beslispunt 1: pand-toewijzen (SCHRIJVEND met --schrijf, RLZ lees-only)
    register_rlz_lezen(subparsers)  # blok 10 11-09: rlz-lezen, LEES-ONLY OData-GET (app/rlz/lezen_cli.py)
    register_rlz_feiten(subparsers)  # Feiten eerst 17-09: rlz-feiten rlz|bank, LEES-ONLY (app/rlz/feiten_cli.py)
    register_db_lezen(subparsers)  # Feiten eerst 17-09: db-lezen querybibliotheek + vrije SELECT op de replica (app/lezen/cli_cmd.py)
    register_vgg_replay(subparsers)  # run 2 VGG blok 6: vgg-replay, LEES-ONLY dry-run (app/migratie/cli_replay.py)
    # run 2 VGG blok 5: odoo-koppeling-migratiedoel + vgg-odoo-stap0 (SCHRIJVEND, app/migratie/cli_odoo.py)
    register_odoo_migratie(subparsers)
    register_vgg_rekeningen(subparsers)  # run 2 VGG blok 4: vgg-rekeningen, RJ-220-rollen (app/odoo/cli_rj220.py)

    intake_postvak_parser = subparsers.add_parser(
        "intake-postvak-verwerken",
        help="Haal ongelezen berichten uit het centrale IMAP-postvak (facturen@ak-nijenhuis.nl) "
        "en verwerk ze idempotent via het intake-codepad (F3.4; zonder INTAKE_IMAP_*-settings "
        "meldt het commando expliciet dat de bron niet geconfigureerd is).",
    )
    # Blok 3 bundel 08-09 (B3): tweede postvak declaraties@ak-nijenhuis.nl (INTAKE_DECLARATIES_IMAP_*-envs).
    intake_postvak_parser.add_argument(
        "--kanaal",
        choices=("facturen", "declaraties"),
        default="facturen",
        help="Welk postvak: facturen (default, facturen@) of declaraties (declaraties@ — documenten krijgen "
        "betaalstatus 'Betaald per bank').",
    )

    subparsers.add_parser(
        "accordeur-herinneringen",
        help="Dagelijkse accordeur-herinnering (09:00 Europe/Amsterdam): push of e-mail bij >0 "
        "openstaande accorderingen — idempotent per dag per accordeur, volumerem, fail-zichtbaar.",
    )

    subparsers.add_parser(
        "uren-herinneringen",
        help="Dag-einde herinnering veld-app 'Nog geen uren voor vandaag' (run B 18-09): push-anders-mail aan ZZP'ers/"
        "uitvoerders zonder uren vandaag, ná de administratie-tijd (default 16:30), één per dag, opt-out per gebruiker.",
    )

    subparsers.add_parser(
        "nieuwe-facturen-melden",
        help="Nieuwe-facturen-bundelmelding (~elke 10 min): één bericht per accordeur zodra er "
        "nieuw werk klaarstaat — idempotent per (accordeur, document), stille uren 20:00–08:00, "
        "volumerem, fail-zichtbaar.",
    )

    subparsers.add_parser(
        "omzet-reconciliatie",
        help="Vergelijk omzet-boekingen (verkoopfactuur + kostprijsmemoriaal) met de werkelijke "
        "RLZ-staat en rapporteer afwijkingen, incl. half-geboekte boekingen.",
    )

    subparsers.add_parser(
        "bank-reconciliatie",
        help="Vergelijk directe bankboekingen en geverifieerde afletteringen met de werkelijke "
        "RLZ-staat (OpenAmount/documentstatus) en rapporteer afwijkingen.",
    )

    subparsers.add_parser(
        "doorbelasting-reconciliatie",
        help="Vergelijk doorbelastings-boekingen (verkoopfactuur bron + spiegel-inkoopfactuur "
        "doel) met de werkelijke RLZ-staat — incl. half-geboekte rijen en verouderde open "
        "spiegel-taken.",
    )

    facturen_herstel_parser = subparsers.add_parser(
        "doorbelasting-facturen-herstel",
        help="Nazorg blok A 26-08: RLZ's factuur-PDF alsnog als bijlage op bestaande GEBOEKTE "
        "doorbelastingen zonder factuur (beide kanten) — géén herboeking; --dry-run telt alleen.",
    )
    facturen_herstel_parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    facturen_herstel_parser.add_argument(
        "--beheerder-id", default=None, dest="beheerder_id", help="Audit-actor; default de systeem-actor."
    )

    acc_herstel_parser = subparsers.add_parser(
        "accordering-herstel-boeken",
        help="Bugfix-run 28-08: documenten mét afgeronde klant-accordering die niet geboekt staan alsnog "
        "boeken via het gefixte na-laatste-akkoord-pad (alle poorten). --dry-run = lijst + diagnose, niets "
        "gewijzigd; --administratie-id beperkt; --max N begrenst het aantal boekpogingen.",
    )
    acc_herstel_parser.add_argument("--dry-run", action="store_true", dest="dry_run")
    acc_herstel_parser.add_argument("--administratie-id", default=None, dest="administratie_id")
    acc_herstel_parser.add_argument("--max", type=int, default=None, dest="max_aantal")

    seed_kempen_parser = subparsers.add_parser(
        "doorbelasting-seed-kempen",
        help="Seed de doorbelasting-whitelist (doelentiteit ↔ Customer-GUID, verkenning/16 §1) "
        "voor een BRON-administratie — idempotent, losse stap (migraties zijn schema-only).",
    )
    seed_kempen_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    seed_kempen_parser.add_argument("--beheerder-id", required=True, dest="beheerder_id")

    seed_mat_parser = subparsers.add_parser(
        "materiaal-seed-universal",
        help="Materiaalcatalogus Universal Nederland B.V. laden uit de bestellijst (steigerbouw-run D2) — idempotent.",
    )
    seed_mat_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    seed_mat_parser.add_argument("--beheerder-id", required=True, dest="beheerder_id")

    alles_parser = subparsers.add_parser(
        "reconciliatie-alles",
        help="Draai alle reconciliatie-blokken (bank, documenten, omzet, doorbelasting, rlz_dubbel) in één "
        "run — stopt nooit vroegtijdig, exit 1 zodra één blok afwijkingen of fouten meldt. Met --lees-only: "
        "dry-run zonder run-rij, bevindingen of mail (blok 1 vervolgrun 10-09: vergelijking paren OUD → clusters NIEUW "
        "voor rlz_dubbel).",
    )
    alles_parser.add_argument(
        "--alleen",
        action="append",
        default=None,
        # Nameting 19-09 (ic_spiegel_rood): de keuzelijst IS run.BLOKKEN — `doorbelasting_aansluiting` ontbrak, waardoor
        # de meetlat "--alleen doorbelasting_aansluiting --lees-only" uit de regels op de job-image argparse-exit 2 gaf.
        # Guard: tests/unit/test_reconciliatie_alleen_keuzelijst.py.
        choices=_reconciliatie_run_blokken(),
        help="Alleen dit blok (herhaalbaar; één van run.BLOKKEN). Vereist --lees-only: een deel-run mag nooit als "
        "'laatste run' worden vastgelegd (de kantoorbrede lijst en de delta-mail lezen die).",
    )
    alles_parser.add_argument(
        "--administratie",
        default=None,
        metavar="UUID|NAAMDEEL",
        help="Beperk tot één administratie (UUID of deel van de naam; eenduidig). Alleen voor --alleen rlz_dubbel.",
    )
    alles_parser.add_argument(
        "--lees-only",
        "--dry-run",
        action="store_true",
        dest="lees_only",
        help="Niets vastleggen: geen run-rij, geen bevindingen, geen acceptatie-overdracht, geen mail — alleen "
        "printen.",
    )

    accepteer_parser = subparsers.add_parser(
        "reconciliatie-accepteer",
        help="Markeer één beoordeelde afwijking als bewust-blijvend (verplichte reden + audit): "
        "blijft zichtbaar in het rapport, telt niet meer mee in de exit-code.",
    )
    accepteer_parser.add_argument("--bron", required=True, choices=[b.value for b in ReconciliatieBron])
    accepteer_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    accepteer_parser.add_argument("--vingerafdruk", required=True, help="De [vaf:...]-waarde uit de rapportregel.")
    accepteer_parser.add_argument("--reden", required=True, help="Waarom deze afwijking blijft staan.")
    accepteer_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    intrekken_parser = subparsers.add_parser(
        "reconciliatie-intrekken",
        help="Trek een acceptatie terug — de afwijking telt vanaf de volgende run weer mee "
        "(de rij blijft bestaan, niets wordt verwijderd).",
    )
    intrekken_parser.add_argument("--bron", required=True, choices=[b.value for b in ReconciliatieBron])
    intrekken_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    intrekken_parser.add_argument("--vingerafdruk", required=True)
    intrekken_parser.add_argument("--reden", required=True, help="Waarom de acceptatie vervalt.")
    intrekken_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    groep_saldi_parser = subparsers.add_parser(
        "groep-saldi",
        help="LEES-ONLY (Peter 16-09): saldo debiteuren/crediteuren per administratie in een groep — bruto, "
        "intercompany (open posten op groepsmaatschappijen) en zonder intercompany; rekeningen uit de bron (RGS/naam, "
        "Odoo account_type), nooit 1300/1600 hardgecodeerd. Leest LIVE; geen debiteur-/crediteurnamen (geen PII).",
    )
    groep_saldi_parser.add_argument(
        "--groep", required=True, help='Naam, code of id van de groep (bv. "Kempen groep").'
    )
    groep_saldi_parser.add_argument(
        "--datum", default=None, help="Peildatum JJJJ-MM-DD (NL-kalenderdag); leeg = per vandaag zonder datumfilter."
    )
    groep_saldi_parser.add_argument(
        "--stand",
        action="store_true",
        help="21-09: niet live meten maar de NACHTELIJKE stand (cache groep_saldo_stand, gevuld door sync-alles) tonen — "
        "dezelfde tabel, bron 'stand'; leden zonder stand worden geteld. Combineert niet met --datum.",
    )

    acceptaties_parser = subparsers.add_parser(
        "reconciliatie-acceptaties",
        help="Toon de actieve acceptaties van één administratie.",
    )
    acceptaties_parser.add_argument("--administratie-id", required=True, dest="administratie_id")

    # SPOED 17-09 blok C: stand per bevindingssoort (meten | actie). Zonder --stand = lees-only overzicht (nameting).
    soort_stand_parser = subparsers.add_parser(
        "bevindingssoort-stand",
        help="Toon of zet de stand van een reconciliatie-bevindingssoort: meten (telt, geen actiemail) | actie.",
    )
    soort_stand_parser.add_argument("soort", nargs="?", default=None)
    soort_stand_parser.add_argument("--stand", choices=("meten", "actie"), default=None)
    soort_stand_parser.add_argument("--reden", default=None, help="Verplicht bij --stand (bv. verwijzing naar de nameting).")

    uitsluiten_parser = subparsers.add_parser(
        "reconciliatie-uitsluiten",
        help="Laat een administratie niet meer meetellen in de exit-code van de reconciliaties "
        "(bevindingen blijven zichtbaar als UITGESLOTEN) — bedoeld voor de test-administratie.",
    )
    uitsluiten_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    uitsluiten_parser.add_argument("--reden", required=True, help="Waarom deze administratie niet meetelt.")
    uitsluiten_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    insluiten_parser = subparsers.add_parser(
        "reconciliatie-insluiten",
        help="Draai de uitsluiting terug: de administratie telt weer volledig mee.",
    )
    insluiten_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    insluiten_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    for naam, hulp in (
        ("bank-autoboeken-aan", "Zet de bank-autoboek-toggle (vaste regels automatisch boeken) AAN."),
        ("bank-autoboeken-uit", "Zet de bank-autoboek-toggle UIT."),
        ("verkoop-autoboeken-aan", "Zet de verkoop-autoboek-toggle (VASTLY-VERKOOP automatisch boeken) AAN."),
        ("verkoop-autoboeken-uit", "Zet de verkoop-autoboek-toggle UIT."),
        ("omzet-autoboeken-aan", "Zet de omzet-autoboek-opt-in (kassarapporten automatisch boeken, GO 01-09) AAN."),
        ("omzet-autoboeken-uit", "Zet de omzet-autoboek-opt-in UIT."),
        ("afgeletterd-event-aan", "Zet de tier-vlag voor het factuur_afgeletterd-event AAN (§3 v1.11)."),
        ("afgeletterd-event-uit", "Zet de tier-vlag voor het factuur_afgeletterd-event UIT."),
        ("uren-meerwerk-aan", "Zet de uren-&-meerwerk-opt-in (steigerbouw-tak, migratie 0056) AAN."),
        ("uren-meerwerk-uit", "Zet de uren-&-meerwerk-opt-in UIT."),
        ("voorraad-aan", "Zet de opt-in 'Voorraad bijhouden' (voorraad-aansluiting, migratie 0086) AAN."),
        ("voorraad-uit", "Zet de opt-in 'Voorraad bijhouden' UIT."),
        ("is-vastgoed-aan", "Zet de vastgoed-koppeling (is_vastgoed: Vastly-events + VASTLY-VERKOOP) AAN — S2 R1."),
        ("is-vastgoed-uit", "Zet de vastgoed-koppeling UIT (verkoop-autoboeken gaat zichtbaar mee uit)."),
    ):
        bank_auto_parser = subparsers.add_parser(naam, help=hulp)
        bank_auto_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
        bank_auto_parser.add_argument(
            "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
        )

    for naam, hulp in (
        (
            "duplicaat-autoafvoer-aan",
            "Zet de platformbrede duplicaat-auto-afvoer (standaard AAN, blok A1 04-09) weer AAN.",
        ),
        (
            "duplicaat-autoafvoer-uit",
            "NOODREM: zet de platformbrede duplicaat-auto-afvoer UIT (één-klik 'Afvoeren als duplicaat' blijft).",
        ),
    ):
        noodrem_parser = subparsers.add_parser(naam, help=hulp)
        noodrem_parser.add_argument(
            "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
        )

    boeken_aan_parser = subparsers.add_parser(
        "boeken-aan",
        help="Zet de boeken-toggle AAN voor één administratie (failsafe a, per-administratie deel).",
    )
    boeken_aan_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    boeken_aan_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    boeken_uit_parser = subparsers.add_parser(
        "boeken-uit",
        help="Zet de boeken-toggle UIT voor één administratie.",
    )
    boeken_uit_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
    boeken_uit_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )

    subparsers.add_parser(
        "boeken-status",
        help=(
            "Overzicht: 'Boeken platformbreed' (aan = boeken kan, uit = boeken staat plat) "
            "+ per-administratie boeken-toggle."
        ),
    )

    for naam, hulp in (
        ("ai-extractie-aan", "Zet de AI-extractie-gate (AVG) AAN voor één administratie."),
        ("ai-extractie-uit", "Zet de AI-extractie-gate (AVG) UIT voor één administratie."),
    ):
        ai_parser = subparsers.add_parser(naam, help=hulp)
        ai_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
        ai_parser.add_argument(
            "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
        )

    subparsers.add_parser(
        "webhook-afleveren",
        help="Lever openstaande webhook-outbox-rijen af aan de vastgoed-ontvanger (één run — "
        "Cloud Scheduler/Cloud Run job-entrypoint, zelfde patroon als sync-alles).",
    )

    for naam, hulp in (
        ("webhook-aflevering-aan", "Zet de webhook-aflevering-toggle AAN (default UIT)."),
        ("webhook-aflevering-uit", "Zet de webhook-aflevering-toggle UIT."),
        ("intake-ai-aan", "Zet de intake-AI-toggle AAN (AVG-gate, default UIT — migratie 0029)."),
        ("intake-ai-uit", "Zet de intake-AI-toggle UIT."),
    ):
        webhook_parser = subparsers.add_parser(naam, help=hulp)
        webhook_parser.add_argument(
            "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
        )

    redrive_parser = subparsers.add_parser(
        "webhook-redrive",
        help="Zet dead-letter-webhookrijen (status 'mislukt') terug naar openstaand (re-drive, "
        "audit per rij) — herstel na bv. langdurige downtime van de vastgoed-ontvanger.",
    )
    redrive_parser.add_argument(
        "--beheerder-id", required=True, dest="beheerder_id", help="UUID van de Beheerder (audit_event-actor)."
    )
    redrive_parser.add_argument(
        "--outbox-id",
        default=None,
        dest="outbox_id",
        help="Alleen deze ene outbox-rij terugzetten (default: alle dead-letters).",
    )

    import_parser = subparsers.add_parser(
        "import-env-credentials",
        help="Zet de bekende .env-logins (RLZ_/UNIVERSAL_/TESTADMIN_/KEMPEN_/RUBICON_) eenmalig "
        "in de credential-store.",
    )
    import_parser.add_argument(
        "--beheerder-id", required=True, help="UUID van de Beheerder die deze import uitvoert (audit_event-actor)."
    )

    args = parser.parse_args(argv)

    if (uitkomst_autoboek_leren := dispatch_autoboek_leren(args)) is not None:  # blok A 10-09
        return uitkomst_autoboek_leren
    if (uitkomst_administratienaam := dispatch_administratienaam(args)) is not None:  # 15-09 (0144)
        return uitkomst_administratienaam
    if (uitkomst_btw_default := dispatch_btw_default(args)) is not None:  # 14-09 (0143), lees-only
        return uitkomst_btw_default
    if (uitkomst_bua := dispatch_bua(args)) is not None:  # 21-09: bua-kandidaten (lees-only) / bua-kenmerk-zetten
        return uitkomst_bua
    if (uitkomst_btw_tarief := dispatch_btw_tarief(args)) is not None:  # 18-09, lees-only
        return uitkomst_btw_tarief
    if (uitkomst_appupdate := dispatch_appupdate(args)) is not None:  # OTA 16-09 nacht
        return uitkomst_appupdate
    if (uitkomst_doorbelasting_aansluiting := dispatch_doorbelasting_aansluiting(args)) is not None:  # 16-09 nacht
        return uitkomst_doorbelasting_aansluiting
    if (uitkomst_werkvoorraad_tellers := dispatch_werkvoorraad_tellers(args)) is not None:  # blok 6 11-09
        return uitkomst_werkvoorraad_tellers
    if args.commando == "bootstrap-beheerder":
        return _bootstrap_beheerder(args)
    if args.commando == "kantoor-digest":
        from app.berichten import digest

        rapport = digest.verstuur_weekdigest()
        print(
            f"kantoor-digest: {rapport.verzonden} verzonden, {rapport.al_verzonden} al verzonden, "
            f"{rapport.niets_te_melden} niets te melden, {rapport.opt_out} opt-out, {rapport.mislukt} mislukt, "
            f"{rapport.onafgemaakt} onafgemaakt"
        )
        for fout in rapport.fouten:
            print(f"FOUT  {fout}", file=sys.stderr)
        return 1 if rapport.is_fout else 0
    if args.commando == "autoboek-kandidaten-herbereken":
        from app.autoboek_kandidaten import service as kandidaten_service

        return _rapporteer_autoboek_kandidaten(kandidaten_service.herbereken_alle())
    if args.commando == "crediteuren-dubbelen-auto":
        from app.crediteuren import afhandeling as crediteuren_afhandeling

        administratie_filter = uuid.UUID(args.administratie) if args.administratie else None
        return _rapporteer_crediteuren_dubbelen_auto(
            crediteuren_afhandeling.auto_afhandelen(
                None, dry_run=args.dry_run, administratie_id=administratie_filter
            )
        )
    if args.commando == "intercompany-leverancier-markeren":
        return _intercompany_leverancier_markeren(args)
    if args.commando in BANK_COMMANDOS:
        return run_bank(args)
    if args.commando in PROJECTEN_COMMANDOS:
        return run_projecten(args)
    if args.commando in PROJECTVERDELING_COMMANDOS:
        return run_projectverdeling(args)
    if args.commando in VERPLICHTING_COMMANDOS:
        return run_verplichting(args)
    if args.commando in ACCORDERING_COMMANDOS:
        return run_accordering(args)  # blok 7 11-09, lees-only
    if args.commando == "migratie-schoonlijst":
        return run_migratie(args)  # blok D1 10-09
    if args.commando == "pandenregister-afleiden":
        return run_panden(args)  # blok D2 10-09
    if args.commando == PAND_TOEWIJZEN_COMMANDO:
        return run_pand_toewijzen(args)  # 21-09 VGG beslispunt 1: mens-toewijzing pand + soort (app/panden/toewijzen_cli.py)
    if args.commando == RLZ_LEZEN_COMMANDO:
        return run_rlz_lezen(args)  # blok 10 11-09, lees-only
    if args.commando == RLZ_FEITEN_COMMANDO:
        return run_rlz_feiten(args)
    if args.commando == DB_LEZEN_COMMANDO:
        return run_db_lezen(args)
    if args.commando == VGG_REPLAY_COMMANDO:
        return run_vgg_replay(args)  # run 2 VGG blok 6, lees-only dry-run
    if args.commando in ODOO_MIGRATIE_COMMANDOS:
        return run_odoo_migratie(args)  # run 2 VGG blok 5, schrijvend — nooit via nameting.sh
    if args.commando == VGG_REKENINGEN_COMMANDO:
        return run_vgg_rekeningen(args)  # run 2 VGG blok 4 (default lees-only; --maak-aan achter kill-switch)
    if args.commando == "crediteuren-werklijst-nazorg":
        from app.crediteuren import afhandeling as crediteuren_afhandeling

        administratie_filter = uuid.UUID(args.administratie) if args.administratie else None
        return _rapporteer_crediteuren_werklijst_nazorg(
            crediteuren_afhandeling.nazorg_werklijst(dry_run=args.dry_run, administratie_id=administratie_filter)
        )
    if args.commando == "projectverdeling-hercontrole":
        from app.projectverdeling import hercontrole as projectverdeling_hercontrole

        return _rapporteer_projectverdeling(projectverdeling_hercontrole.herbereken_alle(forceer=args.forceer))
    if args.commando == "sync-alles":
        return _sync_alles(args)
    if args.commando == "voorraad-rlz-sync":
        return _voorraad_rlz_sync(args)
    if args.commando == "odoo-leesbron":
        return _odoo_leesbron(args)
    if args.commando == "voorraad-hernormaliseer":
        return _voorraad_hernormaliseer(args)
    if args.commando == "projecten-cijfers-sync":
        return _projecten_cijfers_sync(args)
    if args.commando == "projecten-cijfers-wachtrij":
        return _projecten_cijfers_wachtrij(args)
    if args.commando == "bank-sync-wachtrij":
        return _bank_sync_wachtrij(args)
    if args.commando == "bewaking-probe":
        return _bewaking_probe(args)
    if args.commando == "deploy-smoketest":
        return _deploy_smoketest(args)
    if args.commando == "deploy-mislukt":
        return _deploy_mislukt(args)
    if args.commando == "extractie-wachtrij-verwerken":
        return _extractie_wachtrij_verwerken(args)
    if args.commando == "boek-wachtrij-verwerken":
        return _boek_wachtrij_verwerken(args)
    if args.commando == "extractie-heraanbieden":
        return _extractie_heraanbieden(args)
    if args.commando == "intake-herlezen":
        return _intake_herlezen(args)
    if args.commando == "toewijzing-regels-opschonen":
        return _toewijzing_regels_opschonen(args)
    if args.commando == "verzamelbak-nabundelen":
        return _verzamelbak_nabundelen(args)
    if args.commando == "eerste-sync-wachtrij":
        return _eerste_sync_wachtrij(args)
    if args.commando == "terugkerend-herbereken-wachtrij":
        return _terugkerend_herbereken_wachtrij(args)
    if args.commando == "reconciliatie":
        return _reconciliatie(args)
    if args.commando == "bank-sync":
        return _bank_sync(args)
    if args.commando == "bank-reconciliatie":
        return _bank_reconciliatie(args)
    if args.commando == "omzet-reconciliatie":
        return _omzet_reconciliatie(args)
    if args.commando == "doorbelasting-reconciliatie":
        return _doorbelasting_reconciliatie(args)
    if args.commando == "doorbelasting-facturen-herstel":
        return _doorbelasting_facturen_herstel(args)
    if args.commando == "accordering-herstel-boeken":
        return _accordering_herstel_boeken(args)
    if args.commando == "doorbelasting-seed-kempen":
        return _doorbelasting_seed_kempen(args)
    if args.commando == "materiaal-seed-universal":
        return _materiaal_seed_universal(args)
    if args.commando == "reconciliatie-alles":
        return _reconciliatie_alles(args)
    if args.commando == "reconciliatie-accepteer":
        return _reconciliatie_accepteer(args)
    if args.commando == "reconciliatie-intrekken":
        return _reconciliatie_intrekken(args)
    if args.commando == "groep-saldi":
        return _groep_saldi(args)
    if args.commando == "reconciliatie-acceptaties":
        return _reconciliatie_acceptaties(args)
    if args.commando == "bevindingssoort-stand":
        return _bevindingssoort_stand(args)
    if args.commando == "reconciliatie-uitsluiten":
        return _zet_reconciliatie_uitsluiting(args, uitgesloten=True)
    if args.commando == "reconciliatie-insluiten":
        return _zet_reconciliatie_uitsluiting(args, uitgesloten=False)
    if args.commando == "intake-postvak-verwerken":
        return _intake_postvak_verwerken(args)
    if args.commando == "accordeur-herinneringen":
        return _accordeur_herinneringen(args)
    if args.commando == "nieuwe-facturen-melden":
        return _nieuwe_facturen_melden(args)
    if args.commando == "uren-herinneringen":
        return _uren_herinneringen(args)
    if args.commando == "bank-autoboeken-aan":
        return _zet_bank_autoboeken(args, ingeschakeld=True)
    if args.commando == "bank-autoboeken-uit":
        return _zet_bank_autoboeken(args, ingeschakeld=False)
    if args.commando == "uren-meerwerk-aan":
        return _zet_uren_meerwerk(args, ingeschakeld=True)
    if args.commando == "uren-meerwerk-uit":
        return _zet_uren_meerwerk(args, ingeschakeld=False)
    if args.commando == "voorraad-aan":
        return _zet_voorraad(args, ingeschakeld=True)
    if args.commando == "voorraad-uit":
        return _zet_voorraad(args, ingeschakeld=False)
    if args.commando == "omzet-autoboeken-aan":
        return _zet_omzet_autoboeken(args, ingeschakeld=True)
    if args.commando == "omzet-autoboeken-uit":
        return _zet_omzet_autoboeken(args, ingeschakeld=False)
    if args.commando == "duplicaat-autoafvoer-aan":
        return _zet_duplicaat_autoafvoer(args, ingeschakeld=True)
    if args.commando == "duplicaat-autoafvoer-uit":
        return _zet_duplicaat_autoafvoer(args, ingeschakeld=False)
    if args.commando == "verkoop-autoboeken-aan":
        return _zet_verkoop_autoboeken(args, ingeschakeld=True)
    if args.commando == "verkoop-autoboeken-uit":
        return _zet_verkoop_autoboeken(args, ingeschakeld=False)
    if args.commando == "afgeletterd-event-aan":
        return _zet_afgeletterd_event(args, ingeschakeld=True)
    if args.commando == "afgeletterd-event-uit":
        return _zet_afgeletterd_event(args, ingeschakeld=False)
    if args.commando == "is-vastgoed-aan":
        return _zet_is_vastgoed(args, is_vastgoed=True)
    if args.commando == "is-vastgoed-uit":
        return _zet_is_vastgoed(args, is_vastgoed=False)
    if args.commando == "seed-boekingsgeheugen":
        return _seed_boekingsgeheugen(args)
    if args.commando == "boeken-aan":
        return _boeken_aan(args)
    if args.commando == "boeken-uit":
        return _boeken_uit(args)
    if args.commando == "boeken-status":
        return _boeken_status(args)
    if args.commando == "ai-extractie-aan":
        return _ai_extractie_aan(args)
    if args.commando == "ai-extractie-uit":
        return _ai_extractie_uit(args)
    if args.commando == "webhook-afleveren":
        return _webhook_afleveren(args)
    if args.commando == "webhook-aflevering-aan":
        return _zet_webhook_aflevering(args, ingeschakeld=True)
    if args.commando == "webhook-aflevering-uit":
        return _zet_webhook_aflevering(args, ingeschakeld=False)
    if args.commando == "intake-ai-aan":
        return _zet_intake_ai(args, ingeschakeld=True)
    if args.commando == "intake-ai-uit":
        return _zet_intake_ai(args, ingeschakeld=False)
    if args.commando == "webhook-redrive":
        return _webhook_redrive(args)
    if args.commando == "import-env-credentials":
        return _importeer_env_credentials(args)
    if args.commando == "duplicaten-backfill":
        return _duplicaten_backfill(args)
    if args.commando == "duplicaat-status-backfill":
        return _duplicaat_status_backfill(args)
    if args.commando == "checks-cache-legen":
        return _checks_cache_legen(args)
    if args.commando == "referentie-norm-backfill":
        return _referentie_norm_backfill(args)
    if args.commando == "duplicaat-extern-rapport":
        return _duplicaat_extern_rapport(args)
    if args.commando == "kassarapport-autotype-nazorg":
        return _kassarapport_autotype_nazorg(args)
    if args.commando == "kassarapporten-in-inkoopstroom":
        return _kassarapporten_in_inkoopstroom(args)
    if args.commando == "omzet-stores-migreren":
        return _omzet_stores_migreren(args)
    if args.commando == "omzet-binder-rapport":
        return _omzet_binder_rapport(args)
    if args.commando == "activa-nulmeting":
        return _activa_nulmeting(args)
    if args.commando == "periode-backfill":
        return _periode_backfill(args)
    if args.commando == "app-passkeys-markeren":
        return _app_passkeys_markeren(args)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
