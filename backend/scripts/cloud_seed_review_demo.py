"""Cloud-seed: demo-account + fictieve demo-facturen voor de App Store-/Play-review (A2).

Strategie (native/TESTFLIGHT_DRAAIBOEK.md — de passkey-laag wordt NIET verzwakt):
- een gewoon accordeur-account "App-review" op de SEED-PASSKEYTEST-administratie; de reviewer
  doorloopt exact de normale flow: e-mail + wachtwoord → passkey-registratie op het eigen
  toestel (Face ID) → wachtrij. Geen bypass, geen reviewer-achterdeur, dev-stub blijft hard
  onwerkzaam buiten dev.
- de wachtrijdocumenten zijn FICTIEVE demonstratiefacturen (eigen gegenereerde PDF's,
  verzonnen leveranciers, voettekst "Fictieve demonstratiefactuur") — nooit echte
  klantfacturen voor reviewers/screenshots.
- TWEE accorderingslagen: laag 1 = het review-account, laag 2 = het passkeytest-account.
  Het akkoord van de reviewer is dus nooit het láátste akkoord → de boekmotor (die op deze
  credential-loze administratie zichtbaar zou falen) wordt nooit geraakt; de reviewer ziet
  gewoon "akkoord → volgende factuur".

HERZIEN 07-09 (Apple review 2.1, submission d46ad39e — reviewer kon niet inloggen): het script
levert nu een VOLLEDIG geactiveerd account op, zonder dat iemand een uitnodigingslink hoeft te
doorlopen. Rationale: de normale externe activatie parkeert de wachtwoord-hash op de link tot de
passkey-registratie (atomair, 28-08) en de native build activeert sinds 31-08 zelfs zonder
wachtwoord (pincode-flow) — een demo-account dat via zo'n flow ontstaat heeft dus niet
gegarandeerd een definitief wachtwoord. Voor de reviewer is het wachtwoord de ENIGE ingang, dus
dit script zet het zelf: status `actief`, definitieve hash, alle open links vervallen, audit.
De passkey-stap blijft onverkort: de wachtwoordlogin geeft alleen een passkey_setup-token en de
reviewer registreert een passkey op het reviewtoestel (`webauthn_service.start_accordeur_login`).
Daarom wist het script standaard de bestaande passkeys van het demo-account (kill-switch per
apparaat, dezelfde schrijver als de kantoor-UI): zonder actieve passkey slaat de app op een
nieuw toestel de assertion-poging over en gaat direct naar de registratie — één iOS-prompt
minder voor de reviewer. `--behoud-passkeys` laat ze staan. UITSLUITEND dit ene demo-account
wordt geraakt (e-mail hard gepind); voor echte accordeurs bestaat dit pad niet.

UITGEVOERD 07-09 tegen productie (wortel Apple-afwijzing: 21× `login_mislukt` op Apple-toestellen
04/05-09 = het wachtwoord in App Store Connect kwam niet overeen met de hash uit Peters activatie van
02-09; account, status en e-mail klopten). Tweede vondst bij de simulator-verificatie: drie
demo-documenten uit een eerdere seed-run hadden GEEN PDF-object in de bucket (500 op /bestand,
"factuurbeeld kon niet geladen worden"). Daarom sinds 07-09: (a) de seed weigert zonder
DOCUMENT_GCS_BUCKET (nooit stil naar lokale opslag), (b) élke upload wordt ná afloop geverifieerd
(`opslag.bestaat`), (c) zelfherstel: bestaande DEMO-REVIEW-documenten zonder object krijgen hun
deterministische PDF opnieuw geüpload (zelfde bytes, sha256 wordt getoetst — rijen blijven ongemoeid).

Opties:
    [batch]                  batch-letter voor de demo-facturen (default: 'a'; automatisch de
                             eerstvolgende letter als de reviewer-wachtrij leeg is)
    --wachtwoord WW          zet dít wachtwoord (≥ 12 tekens)
    --genereer-wachtwoord    genereert een vers wachtwoord en print het (voor App Store Connect)
    (geen van beide)         wachtwoord ongemoeid als er al een definitieve hash staat; anders
                             wordt er één gegenereerd + geprint (het account moet bruikbaar zijn)
    --behoud-passkeys        bestaande passkeys van het demo-account NIET intrekken

Draaien (patroon cloud_seed_accordering.py):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
    cd backend
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
    DOCUMENT_GCS_BUCKET=rlz-boekhouding-documenten \
        .venv/bin/python scripts/cloud_seed_review_demo.py --genereer-wachtwoord

Het geprinte wachtwoord gaat in App Store Connect › App Review Information (en in de
reviewnotities); het is een demo-credential, geen platform-secret."""

from __future__ import annotations

import argparse
import hashlib
import os
import secrets
import string
import sys
import uuid
import zlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

REVIEW_EMAIL = "p.nijenhuis+applereview@kempengroep.nl"
REVIEW_NAAM = "App-review (demo)"
TWEEDE_LAAG_EMAIL = "accordeur-passkeytest@ak-nijenhuis.nl"
TEST_ADMIN_RLZ_ID = "SEED-PASSKEYTEST"
BATCHLETTERS = string.ascii_lowercase

# Fictieve demonstratiefacturen — zelfde set als de store-screenshots (A3).
PLAN = [
    ("De Vries Bouwmaterialen B.V.", "Voorbeeldweg 12, 5504 XX Veldhoven", "0815", "05-08-2026",
     [("Steigerhuur week 31-32", "1.020,00"), ("Montage en demontage", "220,00")],
     "1.240,00", "260,40", "1.500,40", Decimal("1240.00"), Decimal("260.40")),
    ("Jansen Installatietechniek", "Voorbeeldkade 8, 5611 AB Eindhoven", "0821", "11-08-2026",
     [("Onderhoud klimaatinstallatie", "389,50")],
     "389,50", "81,80", "471,30", Decimal("389.50"), Decimal("81.80")),
    ("Van Dijk Transport & Logistiek", "Voorbeeldlaan 3, 5688 CD Oirschot", "0834", "14-08-2026",
     [("Transport bouwmaterialen, 3 ritten", "612,00"), ("Wachturen laadlocatie", "125,31")],
     "737,31", "154,83", "892,14", Decimal("737.31"), Decimal("154.83")),
]


def _controleer_database_doel() -> None:
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        raise SystemExit("FAILSAFE: APP_DATABASE_URL niet gezet — zie docstring. Gestopt.")
    if ":5433/" in url:
        raise SystemExit("FAILSAFE: APP_DATABASE_URL wijst naar 5433 (lokale PG16). Gestopt.")
    print(f"Database-doel: {url.split('@')[-1]}")
    if not os.environ.get("DOCUMENT_GCS_BUCKET"):
        raise SystemExit(
            "FAILSAFE: DOCUMENT_GCS_BUCKET niet gezet — de demo-PDF's zouden dan stil op lokale schijf "
            "belanden en het factuurbeeld in de app faalt (vondst 07-09). Gestopt."
        )


def genereer_wachtwoord() -> str:
    """Leesbaar én sterk: drie woordachtige blokken + cijfers, zonder verwarrende tekens
    (0/O, 1/l) — de reviewer tikt het over. Voldoet aan MIN_WACHTWOORD_LENGTE (12)."""
    alfabet = "abcdefghjkmnpqrstuvwxyzABCDEFGHJKMNPQRSTUVWXYZ"
    blok = lambda n: "".join(secrets.choice(alfabet) for _ in range(n))  # noqa: E731
    return f"{blok(5)}-{blok(5)}-{secrets.randbelow(9000) + 1000}"


def demo_pdf(nr: str, datum: str, leverancier: str, adres: str,
             regels: list[tuple[str, str]], subtotaal: str, btw: str, totaal: str) -> bytes:
    """Nette één-pagina-demofactuur (Helvetica, geen library) — expliciet als fictief gemarkeerd."""
    def esc(t: str) -> str:
        return t.replace("\\", r"\\").replace("(", r"\(").replace(")", r"\)")

    delen = [
        "BT /F2 20 Tf 60 770 Td (%s) Tj ET" % esc(leverancier),
        "BT /F1 10 Tf 60 752 Td (%s) Tj ET" % esc(adres),
        "BT /F2 14 Tf 420 770 Td (FACTUUR) Tj ET",
        "BT /F1 10 Tf 420 752 Td (Nr. %s) Tj ET" % esc(nr),
        "BT /F1 10 Tf 420 738 Td (Datum: %s) Tj ET" % esc(datum),
        "BT /F1 10 Tf 60 700 Td (Aan: Administratiekantoor Nijenhuis %s demo-administratie %s) Tj ET"
        % (r"\(", r"\)"),
        "0.6 w 60 676 m 535 676 l S",
        "BT /F2 10 Tf 60 660 Td (Omschrijving) Tj ET",
        "BT /F2 10 Tf 460 660 Td (Bedrag) Tj ET",
        "0.6 w 60 652 m 535 652 l S",
    ]
    y = 632
    for oms, bedrag in regels:
        delen.append("BT /F1 10 Tf 60 %d Td (%s) Tj ET" % (y, esc(oms)))
        delen.append("BT /F1 10 Tf 460 %d Td (%s) Tj ET" % (y, esc(bedrag)))
        y -= 18
    y -= 8
    delen.append("0.6 w 300 %d m 535 %d l S" % (y + 12, y + 12))
    for label, bedrag in (("Subtotaal", subtotaal), ("Btw 21%", btw)):
        delen.append("BT /F1 10 Tf 300 %d Td (%s) Tj ET" % (y - 4, esc(label)))
        delen.append("BT /F1 10 Tf 460 %d Td (%s) Tj ET" % (y - 4, esc(bedrag)))
        y -= 18
    delen.append("BT /F2 11 Tf 300 %d Td (Totaal) Tj ET" % (y - 4))
    delen.append("BT /F2 11 Tf 460 %d Td (%s) Tj ET" % (y - 4, esc(totaal)))
    delen.append("BT /F1 8 Tf 60 80 Td (Fictieve demonstratiefactuur - uitsluitend voor review en schermafbeeldingen.) Tj ET")
    stroom = zlib.compress("\n".join(delen).encode("latin-1"))
    objs = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Resources "
        b"<< /Font << /F1 4 0 R /F2 5 0 R >> >> /Contents 6 0 R >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold >>",
        b"<< /Length %d /Filter /FlateDecode >>\nstream\n" % len(stroom) + stroom + b"\nendstream",
    ]
    uit = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, inhoud in enumerate(objs, start=1):
        offsets.append(len(uit))
        uit += b"%d 0 obj\n" % i + inhoud + b"\nendobj\n"
    xref = len(uit)
    uit += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objs) + 1)
    for o in offsets:
        uit += b"%010d 00000 n \n" % o
    uit += b"trailer\n<< /Size %d /Root 1 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (len(objs) + 1, xref)
    return bytes(uit)


def zet_account_definitief(*, review_id: uuid.UUID, beheerder_id: uuid.UUID, wachtwoord: str | None) -> dict:
    """Maakt het demo-account volledig geactiveerd: status actief, (optioneel) definitieve
    wachtwoord-hash, álle nog-open uitnodigings-/herstel-links vervallen (incl. een eventueel
    geparkeerde hash — er is dan nog precies één waarheid: de hash op de gebruiker). Passkeys,
    akkoorden en scope blijven staan. Append-only audit oud→nieuw onder de Beheerder als actor.
    Hard gepind op REVIEW_EMAIL — geen generieke schrijver voor echte accounts."""
    from sqlalchemy import update

    from app.auth.service import MIN_WACHTWOORD_LENGTE
    from app.db.audit import record_audit_event
    from app.db.models import Gebruiker, GebruikerStatus, Uitnodiging
    from app.db.session import scoped_session
    from app.security.passwords import hash_password

    if wachtwoord is not None and len(wachtwoord) < MIN_WACHTWOORD_LENGTE:
        raise SystemExit(f"FOUT: wachtwoord moet minimaal {MIN_WACHTWOORD_LENGTE} tekens zijn.")
    nu = datetime.now(UTC)
    with scoped_session(None, actor_id=beheerder_id) as session:
        gebruiker = session.get(Gebruiker, review_id)
        assert gebruiker is not None
        if gebruiker.e_mail != REVIEW_EMAIL:
            raise SystemExit("FAILSAFE: dit is niet het demo-account — gestopt.")
        if gebruiker.status in (GebruikerStatus.GEBLOKKEERD, GebruikerStatus.GEARCHIVEERD):
            raise SystemExit(
                f"FOUT: demo-account is {gebruiker.status.value} — heractiveer/dearchiveer eerst via /gebruikers."
            )
        oud = {"status": gebruiker.status.value, "wachtwoord_hash_gezet": gebruiker.wachtwoord_hash is not None}
        if gebruiker.status != GebruikerStatus.ACTIEF:
            gebruiker.status = GebruikerStatus.ACTIEF
        if wachtwoord is not None:
            gebruiker.wachtwoord_hash = hash_password(wachtwoord)
        vervallen = session.execute(
            update(Uitnodiging)
            .where(
                Uitnodiging.gebruiker_id == review_id,
                Uitnodiging.gebruikt_op.is_(None),
                Uitnodiging.verloopt_op > nu,
            )
            .values(verloopt_op=nu, wachtwoord_hash_in_wacht=None)
        ).rowcount
        nieuw = {
            "status": gebruiker.status.value,
            "wachtwoord_hash_gezet": gebruiker.wachtwoord_hash is not None,
            "wachtwoord_gewijzigd": wachtwoord is not None,
            "open_links_vervallen": vervallen,
            "bron": "cloud_seed_review_demo",
        }
        record_audit_event(
            session,
            actor_id=beheerder_id,
            module="platform",
            tabel="gebruiker",
            record_id=review_id,
            actie="review_demo_account_definitief",
            correlatie_id=uuid.uuid4(),
            oude_waarde=oud,
            nieuwe_waarde=nieuw,
        )
    return {"oud": oud, "nieuw": nieuw}


def wis_passkeys(*, review_id: uuid.UUID, beheerder_id: uuid.UUID) -> int:
    """Trekt de actieve passkeys van het demo-account in via de bestaande kill-switch-schrijver
    (credential + gebonden refresh-tokens, audit). Eerste login op het reviewtoestel gaat dan
    rechtstreeks naar de passkey-registratie."""
    from app.auth import webauthn_service

    n = 0
    for apparaat in webauthn_service.apparaten_van(gebruiker_id=review_id):
        if apparaat.ingetrokken_op is None:
            webauthn_service.trek_apparaat_in(actor_id=beheerder_id, apparaat_id=apparaat.id)
            naam = apparaat.apparaat_naam or "?"
            print(f"  passkey ingetrokken: {naam} (aangemaakt {apparaat.aangemaakt_op:%d-%m %H:%M})")
            n += 1
    return n


def herstel_ontbrekende_pdfs(*, administratie_id: uuid.UUID, opslag) -> int:
    """Zelfherstel (vondst 07-09): een DEMO-REVIEW-document zonder object in de bucket krijgt zijn
    deterministische PDF opnieuw (zelfde invoer = zelfde bytes; de sha256 op de rij wordt getoetst
    en gemeld, nooit stil aangepast). Alleen documenten van dit seed-script (referentie-prefix),
    alleen de SEED-administratie, geen DB-mutaties."""
    from sqlalchemy import select

    from app.db.session import scoped_session
    from app.documenten.models import Boekvoorstel, Document

    per_suffix = {nrsuffix: rij for rij in PLAN for nrsuffix in (rij[2],)}
    with scoped_session(administratie_id) as session:
        rijen = session.execute(
            select(Document.opslag_pad, Document.bestandsnaam, Document.sha256_hash, Boekvoorstel.referentie)
            .join(Boekvoorstel, Boekvoorstel.document_id == Document.id)
            .where(Boekvoorstel.referentie.like("DEMO-REVIEW-%"))
        ).all()
    hersteld = 0
    for opslag_pad, bestandsnaam, sha, referentie in rijen:
        if not opslag_pad or opslag.bestaat(pad=opslag_pad):
            continue
        nrsuffix = referentie[len("DEMO-REVIEW-"):][:4]
        rij = per_suffix.get(nrsuffix)
        nr = bestandsnaam.removeprefix("factuur-").removesuffix(".pdf")
        if rij is None or not nr:
            print(f"LET OP: {referentie} mist zijn PDF en is niet herleidbaar tot het PLAN — handmatig nakijken.")
            continue
        naam, adres, _, datum, regels, sub, btw_s, tot, _, _ = rij
        pdf = demo_pdf(nr, datum, naam, adres, regels, sub, btw_s, tot)
        if hashlib.sha256(pdf).hexdigest() != sha:
            print(f"LET OP: {referentie}: geregenereerde PDF ≠ sha256 op de rij — toch geüpload (beeld > niets).")
        try:
            opslag.opslaan(pad=opslag_pad, inhoud=pdf)
            if not opslag.bestaat(pad=opslag_pad):
                raise RuntimeError("object ná upload niet aanwezig")
            print(f"  PDF hersteld: {referentie} → {opslag_pad}")
            hersteld += 1
        except Exception as exc:  # noqa: BLE001
            print(f"LET OP: PDF-herstel {referentie} mislukt ({exc}).")
    return hersteld


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("batch", nargs="?", default=None, help="batch-letter (default a / automatisch)")
    parser.add_argument("--wachtwoord", default=None)
    parser.add_argument("--genereer-wachtwoord", action="store_true")
    parser.add_argument("--behoud-passkeys", action="store_true")
    args = parser.parse_args()
    if args.wachtwoord and args.genereer_wachtwoord:
        raise SystemExit("Kies óf --wachtwoord óf --genereer-wachtwoord.")
    _controleer_database_doel()

    from sqlalchemy import select

    from app.accordering import service as accordering_service
    from app.auth import service as auth_service
    from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus
    from app.db.session import scoped_session
    from app.documenten import boekvoorstel as boekvoorstel_service
    from app.documenten.models import Boekvoorstel, Document, DocumentBron, DocumentStatus
    from app.documenten.storage import standaard_opslag
    from app.sync.models import VendorCache

    with scoped_session(None) as session:
        beheerder = session.scalars(
            select(Gebruiker).where(Gebruiker.rol == GebruikerRol.BEHEERDER, Gebruiker.status == GebruikerStatus.ACTIEF)
        ).first()
        if beheerder is None:
            print("FOUT: geen actieve Beheerder — draai eerst cloud_bootstrap_beheerder.py.", file=sys.stderr)
            return 1
        beheerder_id = beheerder.id
        administratie = session.scalars(
            select(Administratie).where(Administratie.rlz_admin_id == TEST_ADMIN_RLZ_ID)
        ).one_or_none()
        if administratie is None:
            print("FOUT: SEED-PASSKEYTEST ontbreekt — draai eerst cloud_seed_accordeur.py.", file=sys.stderr)
            return 1
        administratie_id = administratie.id
        tweede = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == TWEEDE_LAAG_EMAIL)).one_or_none()
        if tweede is None:
            print(f"FOUT: {TWEEDE_LAAG_EMAIL} ontbreekt — draai eerst cloud_seed_accordeur.py.", file=sys.stderr)
            return 1
        tweede_id = tweede.id
        review = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == REVIEW_EMAIL)).one_or_none()
        review_id = review.id if review else None
        heeft_hash = review is not None and review.wachtwoord_hash is not None
        review_status = review.status.value if review else None

    # 1. Review-account: aanmaken indien nodig (normale uitnodigingsroute, de link wordt hieronder
    #    direct vervallen — de reviewer krijgt alleen e-mail + wachtwoord), daarna definitief maken.
    if review_id is None:
        resultaat = auth_service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam=REVIEW_NAAM,
            e_mail=REVIEW_EMAIL,
            rol=GebruikerRol.KLANT_ACCORDEUR,
            administratie_ids=[administratie_id],
            uitnodiging_later=True,
        )
        review_id = resultaat.gebruiker_id
        print(f"Review-account aangemaakt: {REVIEW_EMAIL}")
    else:
        ww_stand = "gezet" if heeft_hash else "ONTBREEKT"
        print(f"Review-account bestaat al: {REVIEW_EMAIL} (status {review_status}, wachtwoord {ww_stand})")

    wachtwoord: str | None = args.wachtwoord
    if args.genereer_wachtwoord or (wachtwoord is None and not heeft_hash):
        wachtwoord = genereer_wachtwoord()
    uitkomst = zet_account_definitief(review_id=review_id, beheerder_id=beheerder_id, wachtwoord=wachtwoord)
    print(f"Account definitief: {uitkomst['oud']} → {uitkomst['nieuw']}")
    if not args.behoud_passkeys:
        n = wis_passkeys(review_id=review_id, beheerder_id=beheerder_id)
        print(f"Passkeys ingetrokken: {n} (eerste login op het reviewtoestel = directe registratie).")

    # 2. Twee lagen: reviewer éérst, passkeytest als tweede — het reviewer-akkoord is nooit
    #    het laatste akkoord, dus de boekmotor wordt nooit geraakt (credential-loze admin).
    ingeschakeld, lagen, _ = accordering_service.instellingen_ophalen(administratie_id=administratie_id)
    gewenst = [(1, review_id), (2, tweede_id)]
    huidig = [(laag.volgnummer, laag.accordeur_gebruiker_id) for laag in lagen]
    if ingeschakeld and huidig == gewenst:
        print("Accorderingslagen staan al goed (review → passkeytest).")
    else:
        accordering_service.instellingen_opslaan(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            actor_rol=GebruikerRol.BEHEERDER.value,
            ingeschakeld=True,
            lagen=[
                accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=review_id, bedrag_drempel=None),
                accordering_service.LaagInput(volgnummer=2, accordeur_gebruiker_id=tweede_id, bedrag_drempel=None),
            ],
        )
        print("Accorderingslagen gezet: laag 1 review-account, laag 2 passkeytest (vangnet).")

    # 3. Batch-letter: expliciet, anders 'a' — of de eerstvolgende vrije letter zodra de
    #    reviewer-wachtrij leeg is (alles beoordeeld), zodat er altijd werk klaarstaat.
    batch = (args.batch or "").strip().lower()
    if not batch:
        wachtrij = accordering_service.wachtrij_voor_accordeur(actor_id=review_id, administratie_ids=[administratie_id])
        if wachtrij:
            batch = "a"
            print(f"Wachtrij reviewer: {len(wachtrij)} open — batch 'a' wordt alleen aangevuld waar die ontbreekt.")
        else:
            with scoped_session(administratie_id) as session:
                refs = session.scalars(
                    select(Boekvoorstel.referentie).where(Boekvoorstel.referentie.like("DEMO-REVIEW-%"))
                ).all()
            gebruikt = {r[len("DEMO-REVIEW-") + 4:] or "a" for r in refs}
            batch = next(letter for letter in BATCHLETTERS if letter not in gebruikt)
            print(f"Wachtrij reviewer leeg — nieuwe batch '{batch}'.")

    # 4. Fictieve demo-facturen (patroon cloud_seed_accordering: direct klaar_om_te_boeken,
    #    synthetische GUID's — boeken kan hier toch nooit door laag 2).
    opslag = standaard_opslag()
    n_hersteld = herstel_ontbrekende_pdfs(administratie_id=administratie_id, opslag=opslag)
    print(f"Ontbrekende demo-PDF's hersteld: {n_hersteld}.")
    for naam, adres, nrsuffix, datum, regels, sub, btw_s, tot, netto, btw in PLAN:
        nr = f"2026-{nrsuffix}{batch}" if batch != "a" else f"2026-{nrsuffix}"
        referentie = f"DEMO-REVIEW-{nrsuffix}{batch}" if batch != "a" else f"DEMO-REVIEW-{nrsuffix}"
        with scoped_session(administratie_id) as session:
            if session.scalars(select(Boekvoorstel).where(Boekvoorstel.referentie == referentie)).first():
                print(f"{referentie}: bestaat al — overgeslagen.")
                continue
            vendor = session.scalars(select(VendorCache).where(
                VendorCache.administratie_id == administratie_id, VendorCache.naam == naam)).first()
            if vendor is None:
                vendor = VendorCache(id=uuid.uuid4(), administratie_id=administratie_id, naam=naam,
                                     brondata={"demo": True})
                session.add(vendor)
            vendor_id = vendor.id

        pdf = demo_pdf(nr, datum, naam, adres, regels, sub, btw_s, tot)
        document_id = uuid.uuid4()
        opslag_pad = f"{administratie_id}/{document_id}.pdf"
        try:
            opslag.opslaan(pad=opslag_pad, inhoud=pdf)
            if not opslag.bestaat(pad=opslag_pad):
                raise RuntimeError("object ná upload niet aanwezig")
        except Exception as exc:  # noqa: BLE001 — zichtbaar melden, seed gaat door
            print(f"LET OP: PDF-upload mislukt ({exc}) — factuurbeeld toont dan een fout.")
        with scoped_session(administratie_id, actor_id=beheerder_id) as session:
            session.add(Document(
                id=document_id,
                administratie_id=administratie_id,
                bron=DocumentBron.UPLOAD,
                bestandsnaam=f"factuur-{nr}.pdf",
                sha256_hash=hashlib.sha256(pdf).hexdigest(),
                status=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                opslag_pad=opslag_pad,
            ))
        boekvoorstel_service.sla_boekvoorstel_op(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            vendor_id=vendor_id,
            referentie=referentie,
            factuurdatum=datetime.now(UTC).date(),
            totaalbedrag=netto + btw,
            regels=[boekvoorstel_service.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(), taxrate_id=uuid.uuid4(), project_id=None,
                netto_bedrag=netto, btw_bedrag=btw, omschrijving=f"Demo-review {referentie}",
            )],
        )
        uit = accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            actor_rol=GebruikerRol.BEHEERDER.value,
        )
        print(f"{referentie}: ter accordering aangeboden (status {uit.accordering.status}).")

    wachtrij = accordering_service.wachtrij_voor_accordeur(actor_id=review_id, administratie_ids=[administratie_id])
    print()
    print(f"Klaar. Wachtrij reviewer: {len(wachtrij)} document(en).")
    print(f"Inloggen: e-mail {REVIEW_EMAIL}")
    if wachtwoord is not None:
        print(f"Wachtwoord (NIEUW — zet dit in App Store Connect › App Review Information): {wachtwoord}")
    else:
        print("Wachtwoord: ongewijzigd (bestaande hash).")
    print("De reviewer registreert bij de eerste login een eigen passkey (Face ID) — normale flow, geen bypass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
