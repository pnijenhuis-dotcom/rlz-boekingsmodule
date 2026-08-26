from __future__ import annotations

import argparse
import sys
import uuid
from pathlib import Path

from dotenv import load_dotenv

from app.auth import service
from app.bank import reconciliatie as bank_reconciliatie
from app.bank import sync as bank_sync_service
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
from app.omzet import reconciliatie as omzet_reconciliatie
from app.reconciliatie import service as acceptatie_service
from app.reconciliatie.models import ReconciliatieBron
from app.rlz.credentials import GeenRlzCredentials
from app.sync import service as sync_service

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


def _extractie_wachtrij_verwerken(args: argparse.Namespace) -> int:
    """Job-entrypoint extractie-wachtrij (punt 4, 26-08): synchroon, systeem-actor, idempotent."""
    from app.documenten import service as documenten_service

    aantal = documenten_service.verwerk_extractie_wachtrij()
    print(f"extractie-wachtrij-verwerken: {aantal} document(en) verwerkt")
    return 0


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
        print(
            f"OK    {administratie_id}: ledgers={resultaat.ledgers}, taxrates={resultaat.taxrates}, "
            f"vendors={resultaat.vendors}, projects={resultaat.projects}"
        )
    kern = f"{len(resultaten) - fouten - overgeslagen}/{len(resultaten)} administraties gesynchroniseerd."
    if overgeslagen:
        kern += f" ({overgeslagen} overgeslagen: geen credential geregistreerd)"
    print(f"\n{kern}")

    # Automatisering-first (opdracht 23-08 punt 3): de dagelijkse sync ververst óók de
    # projectcijfers voor de uren-&-meerwerk-administraties — de knop blijft de handmatige
    # verversing. Eigen fouten-telling: een kapotte cijfers-sync maakt de job zichtbaar rood.
    from app.projecten.cijfers_run import sync_alle_via_runs

    print("\nProjectcijfers-sync (uren-&-meerwerk-administraties):")
    cijfers_exit = _rapporteer_cijfers_runs(sync_alle_via_runs())
    return 1 if fouten or cijfers_exit else 0


def _regel(kern: str, beoordeeld: acceptatie_service.Beoordeeld) -> str:
    """Eén rapportregel, zónder eigen prefix (de aanroeper bepaalt inspringing/stream). De
    vingerafdruk staat er altijd bij: dat is de sleutel waarmee een beoordeelde afwijking
    geaccepteerd — of weer ingetrokken — wordt."""
    kop = f"{kern} soort={beoordeeld.soort} [vaf:{beoordeeld.vingerafdruk}]: {beoordeeld.detail}"
    if beoordeeld.acceptatie is None:
        return kop
    geaccepteerd_op = beoordeeld.acceptatie.geaccepteerd_op.date().isoformat()
    return f"GEACCEPTEERD {kop} — reden: {beoordeeld.acceptatie.reden} (sinds {geaccepteerd_op})"


def _reconciliatie(args: argparse.Namespace) -> int:
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
                print(f"UITGESLOTEN {administratie_id}: {resultaat} (uitgesloten: {uitsluiting})")
                continue
            fouten += 1
            print(f"FOUT       {administratie_id}: {resultaat}", file=sys.stderr)
            continue
        if not resultaat.afwijkingen:
            print(f"OK         {administratie_id}: {resultaat.aantal_gecontroleerd} gecontroleerd, geen afwijkingen")
            continue
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
                print(f"    - {_regel(f'document={a.document_id} rlz_document={a.rlz_document_id}', b)}")
            continue
        afwijkingen_totaal += len(open_afwijkingen)
        geaccepteerd_totaal += len(beoordeeld) - len(open_afwijkingen)
        kop = "AFWIJKING " if open_afwijkingen else "OK        "
        print(
            f"{kop} {administratie_id}: {resultaat.aantal_gecontroleerd} gecontroleerd, "
            f"{len(open_afwijkingen)} afwijking(en), {len(beoordeeld) - len(open_afwijkingen)} geaccepteerd"
        )
        for a, b in zip(resultaat.afwijkingen, beoordeeld, strict=True):
            print(f"    - {_regel(f'document={a.document_id} rlz_document={a.rlz_document_id}', b)}")
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
            print(f"FOUT       storno-detectie {administratie_id}: {storno_resultaat}", file=sys.stderr)
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
    for administratie_id, resultaat in resultaten.items():
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
    print(f"\n{len(resultaten) - fouten}/{len(resultaten)} administraties bank-gesynchroniseerd.")
    return 1 if fouten else 0


def _bank_reconciliatie(args: argparse.Namespace) -> int:
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
        if isinstance(resultaat, str):
            if uitsluiting:
                print(f"UITGESLOTEN {administratie_id}: {resultaat} (uitgesloten: {uitsluiting})")
                continue
            fouten += 1
            print(f"FOUT       {administratie_id}: {resultaat}", file=sys.stderr)
            continue
        gecontroleerd = resultaat.boekingen_gecontroleerd + resultaat.afletteringen_gecontroleerd
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
                print(f"    - {_regel(f'record={a.record_id} mutatie={a.payment_transaction_id}', b)}")
            continue
        afwijkingen_totaal += len(open_afwijkingen)
        geaccepteerd_totaal += len(beoordeeld) - len(open_afwijkingen)
        kop = "AFWIJKING " if open_afwijkingen else "OK        "
        print(
            f"{kop} {administratie_id}: {gecontroleerd} gecontroleerd, "
            f"{len(open_afwijkingen)} afwijking(en), {len(beoordeeld) - len(open_afwijkingen)} geaccepteerd"
        )
        for a, b in zip(resultaat.afwijkingen, beoordeeld, strict=True):
            print(f"    - {_regel(f'record={a.record_id} mutatie={a.payment_transaction_id}', b)}")
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


def _omzet_reconciliatie(args: argparse.Namespace) -> int:
    """Omzet-failsafe: vergelijk elke omzet-boeking (verkoopfactuur + kostprijsmemoriaal) met de
    werkelijke RLZ-staat en rapporteer afwijkingen — incl. alle half_geboekt-rijen."""
    resultaat = omzet_reconciliatie.reconcilieer_alle_omzet()
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    echte_fouten = {aid: fout for aid, fout in resultaat.fouten.items() if aid not in uitgesloten}
    for administratie_id, fout in resultaat.fouten.items():
        if administratie_id in uitgesloten:
            print(f"UITGESLOTEN {administratie_id}: {fout} (uitgesloten: {uitgesloten[administratie_id]})")
            continue
        print(f"FOUT       {administratie_id}: {fout}", file=sys.stderr)

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
            if administratie_id in uitgesloten:
                print(f"UITGESLOTEN {regel} — telt niet mee ({uitgesloten[administratie_id]})")
            elif b.telt_mee:
                open_totaal += 1
                print(f"AFWIJKING  {regel}", file=sys.stderr)
            else:
                geaccepteerd_totaal += 1
                print(f"OK         {regel}")

    if not echte_fouten and not open_totaal:
        print(f"OK         geen afwijkingen in de omzet-boekingen ({geaccepteerd_totaal} geaccepteerd)")
        return 0
    print(
        f"{open_totaal} afwijking(en) en {len(echte_fouten)} mislukte administratie(s) gevonden "
        f"({geaccepteerd_totaal} geaccepteerd)",
        file=sys.stderr,
    )
    return 1


def _doorbelasting_reconciliatie(args: argparse.Namespace) -> int:
    """Doorbelasting-failsafe: vergelijk elke doorbelastings-boeking (verkoopfactuur in de bron
    + spiegel-inkoopfactuur in het doel) met de werkelijke RLZ-staat — incl. alle
    half_geboekt-rijen en verouderde open spiegel-taken."""
    resultaat = doorbelasting_reconciliatie.reconcilieer_alle_doorbelasting()
    uitgesloten = acceptatie_service.uitgesloten_administraties()
    echte_fouten = {aid: fout for aid, fout in resultaat.fouten.items() if aid not in uitgesloten}
    for administratie_id, fout in resultaat.fouten.items():
        if administratie_id in uitgesloten:
            print(f"UITGESLOTEN {administratie_id}: {fout} (uitgesloten: {uitgesloten[administratie_id]})")
            continue
        print(f"FOUT       {administratie_id}: {fout}", file=sys.stderr)

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
            if administratie_id in uitgesloten:
                print(f"UITGESLOTEN {regel} — telt niet mee ({uitgesloten[administratie_id]})")
            elif b.telt_mee:
                open_totaal += 1
                print(f"AFWIJKING  {regel}", file=sys.stderr)
            else:
                geaccepteerd_totaal += 1
                print(f"OK         {regel}")

    # Opruimlijst (hygiëne-run 2026-08-16): achtergebleven RLZ-concepten van gestorneerde/
    # vervallen runs — puur informatief (LET-OP), telt NOOIT mee in de exit-code. De app
    # verwijdert nooit iets in RLZ (kernprincipe 3); opruimen is klikwerk van een mens in de
    # RLZ-UI, "indien gewenst". Ook zichtbaar op Instellingen → Doorbelasting.
    opruim = doorbelasting_reconciliatie.verzamel_alle_opruimlijsten()
    for kandidaat in opruim.kandidaten:
        print(
            f"LET-OP     opruim-kandidaat [{kandidaat.reden}] {kandidaat.kant} {kandidaat.rlz_id} "
            f"in administratie {kandidaat.concept_administratie_id} "
            f"(document {kandidaat.document_id}{f', ref {kandidaat.referentie}' if kandidaat.referentie else ''}) "
            f"— {kandidaat.detail}; handmatig opruimen in de RLZ-UI indien gewenst"
        )
    for fout in opruim.fouten:
        print(f"LET-OP     opruimlijst: {fout}")
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
    """Alle drie de reconciliaties in één run. Bestaat omdat de handmatige `&&`-keten precies
    het verkeerde deed: viel de eerste om, dan draaiden de andere twee niet — juist op een dag
    waarop er iets aan de hand is verloor je zo de omzet-controle (half_geboekt) helemaal.
    Hier stopt niets vroegtijdig; de exit-code is 1 zodra één blok afwijkingen of fouten meldt."""
    blokken = (
        ("bank", _bank_reconciliatie),
        ("documenten", _reconciliatie),
        ("omzet", _omzet_reconciliatie),
        ("doorbelasting", _doorbelasting_reconciliatie),
    )
    exitcodes: dict[str, int] = {}
    for naam, functie in blokken:
        print(f"\n=== {naam}-reconciliatie ===")
        try:
            exitcodes[naam] = functie(args)
        except Exception as exc:  # noqa: BLE001 — een omgevallen blok mag de rest nooit stoppen
            print(f"FOUT       {naam}-reconciliatie viel om: {exc}", file=sys.stderr)
            exitcodes[naam] = 1

    print("\n=== samenvatting ===")
    for naam, code in exitcodes.items():
        print(f"{'OK       ' if code == 0 else 'ACTIE    '} {naam}-reconciliatie (exit {code})")
    return 1 if any(exitcodes.values()) else 0


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
    try:
        for inhoud in ImapPostvakBron().nieuwe_berichten():
            try:
                resultaat = intake_verwerking.verwerk_eml(inhoud, actor_id=SYSTEEM_ACTOR_ID, bron="imap")
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
        "extractie-wachtrij-verwerken",
        help="Werk de AI-extractie-wachtrij af (entrypoint van de on-demand Cloud Run-job "
        "rlz-extractie-wachtrij, feedbackronde 26-08 punt 4 — een groot document triggert de job, "
        "het scheduler-vangnet draait 'm elke 10 min; lege wachtrij = snelle no-op).",
    )

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

    subparsers.add_parser(
        "intake-postvak-verwerken",
        help="Haal ongelezen berichten uit het centrale IMAP-postvak (facturen@ak-nijenhuis.nl) "
        "en verwerk ze idempotent via het intake-codepad (F3.4; zonder INTAKE_IMAP_*-settings "
        "meldt het commando expliciet dat de bron niet geconfigureerd is).",
    )

    subparsers.add_parser(
        "accordeur-herinneringen",
        help="Dagelijkse accordeur-herinnering (09:00 Europe/Amsterdam): push of e-mail bij >0 "
        "openstaande accorderingen — idempotent per dag per accordeur, volumerem, fail-zichtbaar.",
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

    subparsers.add_parser(
        "reconciliatie-alles",
        help="Draai alle vier de reconciliaties (bank, documenten, omzet, doorbelasting) in één "
        "run — stopt nooit vroegtijdig, exit 1 zodra één blok afwijkingen of fouten meldt.",
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

    acceptaties_parser = subparsers.add_parser(
        "reconciliatie-acceptaties",
        help="Toon de actieve acceptaties van één administratie.",
    )
    acceptaties_parser.add_argument("--administratie-id", required=True, dest="administratie_id")

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
        ("afgeletterd-event-aan", "Zet de tier-vlag voor het factuur_afgeletterd-event AAN (§3 v1.11)."),
        ("afgeletterd-event-uit", "Zet de tier-vlag voor het factuur_afgeletterd-event UIT."),
        ("uren-meerwerk-aan", "Zet de uren-&-meerwerk-opt-in (steigerbouw-tak, migratie 0056) AAN."),
        ("uren-meerwerk-uit", "Zet de uren-&-meerwerk-opt-in UIT."),
        ("is-vastgoed-aan", "Zet de vastgoed-koppeling (is_vastgoed: Vastly-events + VASTLY-VERKOOP) AAN — S2 R1."),
        ("is-vastgoed-uit", "Zet de vastgoed-koppeling UIT (verkoop-autoboeken gaat zichtbaar mee uit)."),
    ):
        bank_auto_parser = subparsers.add_parser(naam, help=hulp)
        bank_auto_parser.add_argument("--administratie-id", required=True, dest="administratie_id")
        bank_auto_parser.add_argument(
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

    if args.commando == "bootstrap-beheerder":
        return _bootstrap_beheerder(args)
    if args.commando == "sync-alles":
        return _sync_alles(args)
    if args.commando == "projecten-cijfers-sync":
        return _projecten_cijfers_sync(args)
    if args.commando == "projecten-cijfers-wachtrij":
        return _projecten_cijfers_wachtrij(args)
    if args.commando == "bank-sync-wachtrij":
        return _bank_sync_wachtrij(args)
    if args.commando == "extractie-wachtrij-verwerken":
        return _extractie_wachtrij_verwerken(args)
    if args.commando == "eerste-sync-wachtrij":
        return _eerste_sync_wachtrij(args)
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
    if args.commando == "reconciliatie-acceptaties":
        return _reconciliatie_acceptaties(args)
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
    if args.commando == "bank-autoboeken-aan":
        return _zet_bank_autoboeken(args, ingeschakeld=True)
    if args.commando == "bank-autoboeken-uit":
        return _zet_bank_autoboeken(args, ingeschakeld=False)
    if args.commando == "uren-meerwerk-aan":
        return _zet_uren_meerwerk(args, ingeschakeld=True)
    if args.commando == "uren-meerwerk-uit":
        return _zet_uren_meerwerk(args, ingeschakeld=False)
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
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
