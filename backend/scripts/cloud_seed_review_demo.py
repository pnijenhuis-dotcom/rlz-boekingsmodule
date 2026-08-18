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

Idempotent per referentie; raakt de wachtrij leeg (reviewer heeft alles beoordeeld), draai
opnieuw met een nieuwe batch-letter: `... cloud_seed_review_demo.py b`.

Draaien (patroon cloud_seed_accordering.py):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
    cd backend
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
    DOCUMENT_GCS_BUCKET=rlz-boekhouding-documenten \
        .venv/bin/python scripts/cloud_seed_review_demo.py [batch]

Bestaat het review-account nog niet, dan print het script de activatielink — die doorloopt
PETER zelf (wachtwoord kiezen dat in de reviewnotities komt; passkey-stap mag hij op zijn
eigen toestel doen of overslaan door de flow op het reviewer-pad te laten — de reviewer
registreert sowieso een eigen passkey op het reviewtoestel, nieuw apparaat = volledige login)."""

from __future__ import annotations

import hashlib
import os
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


def main() -> int:
    batch = (sys.argv[1] if len(sys.argv) > 1 else "a").strip().lower()
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

    # 1. Review-account (normale uitnodigingsflow — Peter activeert de link zelf en kiest het
    #    wachtwoord dat in de App Review-notities komt).
    if review is None:
        resultaat = auth_service.maak_uitnodiging(
            actor_id=beheerder_id,
            naam=REVIEW_NAAM,
            e_mail=REVIEW_EMAIL,
            rol=GebruikerRol.KLANT_ACCORDEUR,
            administratie_ids=[administratie_id],
        )
        review_id = resultaat.gebruiker_id
        print(f"Review-account aangemaakt: {REVIEW_EMAIL}")
        print(f"ACTIVATIELINK (72 u geldig, Peter doorloopt 'm zelf): /activeren?token={resultaat.token}")
    else:
        review_id = review.id
        print(f"Review-account bestaat al: {REVIEW_EMAIL} (status {review.status.value})")

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

    # 3. Fictieve demo-facturen (patroon cloud_seed_accordering: direct klaar_om_te_boeken,
    #    synthetische GUID's — boeken kan hier toch nooit door laag 2).
    opslag = standaard_opslag()
    for i, (naam, adres, nrsuffix, datum, regels, sub, btw_s, tot, netto, btw) in enumerate(PLAN, start=1):
        nr = f"2026-{nrsuffix}{batch}" if batch != "a" else f"2026-{nrsuffix}"
        referentie = f"DEMO-REVIEW-{nrsuffix}{batch}"
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

    print()
    print("Klaar. Reviewnotities: e-mail + het door Peter gekozen wachtwoord; de reviewer")
    print("registreert bij eerste login een eigen passkey (Face ID) — normale flow, geen bypass.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
