"""Cloud-seed: één open TEST-accordering voor het accordeur-passkeytest-account (2026-08-15).

Doel: de live-verificatie van de dagelijkse 09:00-herinnering (job rlz-accordeur-herinneringen)
heeft ≥1 open accordering nodig voor de accordeur — anders valt er niets te sturen en bewijst
een groene run niets. Dit script zet op de bestaande SEED-PASSKEYTEST-administratie klaar:
1. accordering aan + één laag met het passkeytest-account (bestaande service, geauditeerd);
2. één document TEST-ACC-NOTIF-01 mét boekvoorstel, ter accordering aangeboden via de échte
   `bied_ter_accordering_aan`-flow (bevroren stappen, audit, status ter_accordering).

Bewuste seed-afwijkingen (gedocumenteerd, alleen op deze vergankelijke test-administratie):
- het document wordt direct in status klaar_om_te_boeken aangemaakt — de harde-checks-poort
  vergt een live RLZ-verbinding en SEED-PASSKEYTEST heeft bewust géén credential;
- vendor/ledger/taxrate zijn synthetische GUID's (geen FK's; boeken kán hier toch niet).
  Tikt Peter tóch alle akkoorden af, dan faalt de boekmotor ZICHTBAAR op de ontbrekende
  RLZ-credential — bedoeld gedrag (fail-zichtbaar), geen datacorruptie.
- de bijlage is een mini-PDF ("TEST notificatie-verificatie") die naar de documentenbucket
  gaat zodat het factuurbeeld in de PWA gewoon rendert; lukt de upload niet (geen ADC), dan
  meldt het script dat en gaat het dóór — de herinnering-verificatie heeft de PDF niet nodig.

⚠️ VERGANKELIJK: verdwijnt — net als de hele SEED-PASSKEYTEST-administratie — bij de
tranche-2-restore. Referentie TEST-ACC-NOTIF- ligt in het verlengde van de TEST-conventie.

Draaien (patroon + failsafes cloud_seed_accordeur.py):
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
    cd backend
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
    DOCUMENT_GCS_BUCKET=rlz-boekhouding-documenten \
        .venv/bin/python scripts/cloud_seed_accordering.py [--referentie TEST-ACC-NOTIF-02]

Herdraaibaar per referentie (--referentie, default TEST-ACC-NOTIF-01): bestaat de
referentie al, dan doet het script niets (behalve de laag-controle) — een nieuwe
referentie zet één nieuwe open accordering klaar. Actor is de actieve Beheerder in de
doel-database."""

from __future__ import annotations

import argparse
import hashlib
import os
import sys
import uuid
import zlib
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ACCORDEUR_EMAIL = "accordeur-passkeytest@ak-nijenhuis.nl"
TEST_ADMIN_RLZ_ID = "SEED-PASSKEYTEST"
STANDAARD_REFERENTIE = "TEST-ACC-NOTIF-01"
NETTO = Decimal("100.00")
BTW = Decimal("21.00")


def _controleer_database_doel() -> None:
    """Zelfde failsafe als cloud_seed_accordeur: expliciet doel, nooit de lokale dev-database."""
    url = os.environ.get("APP_DATABASE_URL", "")
    if not url:
        raise SystemExit(
            "FAILSAFE: APP_DATABASE_URL is niet gezet — zie de docstring voor het recept. "
            "Gestopt zonder database-verbinding."
        )
    if ":5433/" in url:
        raise SystemExit(
            "FAILSAFE: APP_DATABASE_URL wijst naar poort 5433 (lokale PG16). De Auth "
            "Proxy-conventie is poort 5434 — gestopt, niets gedaan."
        )
    print(f"Database-doel: {url.split('@')[-1]}")


def _mini_pdf(tekst: str) -> bytes:
    """Kleinste geldige één-pagina-PDF met de gegeven tekst (geen library nodig)."""
    stream = f"BT /F1 18 Tf 60 760 Td ({tekst}) Tj ET".encode()
    gecomprimeerd = zlib.compress(stream)
    objecten = [
        b"<< /Type /Catalog /Pages 2 0 R >>",
        b"<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        b"<< /Type /Page /Parent 2 0 R /MediaBox [0 0 595 842] /Contents 4 0 R "
        b"/Resources << /Font << /F1 5 0 R >> >> >>",
        b"<< /Length " + str(len(gecomprimeerd)).encode() + b" /Filter /FlateDecode >>\nstream\n"
        + gecomprimeerd
        + b"\nendstream",
        b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
    ]
    uit = bytearray(b"%PDF-1.4\n")
    offsets = []
    for i, obj in enumerate(objecten, start=1):
        offsets.append(len(uit))
        uit += f"{i} 0 obj\n".encode() + obj + b"\nendobj\n"
    xref_start = len(uit)
    uit += f"xref\n0 {len(objecten) + 1}\n0000000000 65535 f \n".encode()
    for offset in offsets:
        uit += f"{offset:010d} 00000 n \n".encode()
    uit += (
        f"trailer\n<< /Size {len(objecten) + 1} /Root 1 0 R >>\nstartxref\n{xref_start}\n%%EOF\n"
    ).encode()
    return bytes(uit)


def main() -> int:
    parser = argparse.ArgumentParser(description="Cloud-seed: één open TEST-accordering (herdraaibaar per referentie).")
    parser.add_argument(
        "--referentie",
        default=STANDAARD_REFERENTIE,
        help=f"TEST-referentie van de accordering (default {STANDAARD_REFERENTIE}); idempotent per referentie.",
    )
    argumenten = parser.parse_args()
    referentie: str = argumenten.referentie
    if not referentie.startswith("TEST-"):
        raise SystemExit(
            f"FAILSAFE: referentie {referentie!r} volgt de TEST-conventie niet (moet met 'TEST-' beginnen) — "
            "gestopt, niets gedaan."
        )
    bestandsnaam = f"{referentie}.pdf"

    _controleer_database_doel()

    # Imports pas ná de failsafe: het app-pakket bindt de database-engine bij import.
    from sqlalchemy import select

    from app.accordering import service as accordering_service
    from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus
    from app.db.session import scoped_session
    from app.documenten import boekvoorstel as boekvoorstel_service
    from app.documenten.models import Boekvoorstel, Document, DocumentBron, DocumentStatus
    from app.documenten.storage import standaard_opslag

    # 1. Actor + bestaande seed-objecten (dit script maakt géén accounts — dat is
    #    cloud_seed_accordeur.py; ontbreekt er iets, dan eerst dát draaien).
    with scoped_session(None) as session:
        beheerder = session.scalars(
            select(Gebruiker).where(Gebruiker.rol == GebruikerRol.BEHEERDER, Gebruiker.status == GebruikerStatus.ACTIEF)
        ).first()
        if beheerder is None:
            print("FOUT: geen actieve Beheerder — draai eerst cloud_bootstrap_beheerder.py.", file=sys.stderr)
            return 1
        beheerder_id = beheerder.id
        accordeur = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == ACCORDEUR_EMAIL)).one_or_none()
        if accordeur is None:
            print(f"FOUT: {ACCORDEUR_EMAIL} bestaat niet — draai eerst cloud_seed_accordeur.py.", file=sys.stderr)
            return 1
        accordeur_id = accordeur.id
        administratie = session.scalars(
            select(Administratie).where(Administratie.rlz_admin_id == TEST_ADMIN_RLZ_ID)
        ).one_or_none()
        if administratie is None:
            print(
                "FOUT: SEED-PASSKEYTEST-administratie ontbreekt — draai eerst cloud_seed_accordeur.py.",
                file=sys.stderr,
            )
            return 1
        administratie_id = administratie.id
    print(f"Actor: Beheerder {beheerder_id} · accordeur {accordeur_id} · administratie {administratie_id}")

    # 2. Accordering aan + één laag met het passkeytest-account (idempotent).
    ingeschakeld, lagen, _ = accordering_service.instellingen_ophalen(administratie_id=administratie_id)
    if ingeschakeld and any(laag.accordeur_gebruiker_id == accordeur_id for laag in lagen):
        print("Accordering staat al aan met het passkeytest-account als laag.")
    else:
        accordering_service.instellingen_opslaan(
            administratie_id=administratie_id,
            actor_id=beheerder_id,
            actor_rol=GebruikerRol.BEHEERDER.value,
            ingeschakeld=True,
            lagen=[
                accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur_id, bedrag_drempel=None)
            ],
        )
        print("Accordering aangezet: 1 laag (passkeytest-account, geen drempel).")

    # 3. Idempotentie: bestaat de TEST-referentie al, dan niets dubbel klaarzetten.
    with scoped_session(administratie_id) as session:
        bestaand = session.scalars(select(Boekvoorstel).where(Boekvoorstel.referentie == referentie)).first()
    if bestaand is not None:
        print(f"{referentie}: bestaat al — niets te doen.")
        return 0

    # 4. Document + mini-PDF. Status direct klaar_om_te_boeken (zie docstring: de checks-poort
    #    vergt RLZ en deze administratie heeft bewust geen credential).
    document_id = uuid.uuid4()
    pdf = _mini_pdf(f"TEST notificatie-verificatie {referentie}")
    opslag_pad = f"{administratie_id}/{document_id}.pdf"
    try:
        standaard_opslag().opslaan(pad=opslag_pad, inhoud=pdf)
        print(f"Mini-PDF opgeslagen: {opslag_pad}")
    except Exception as exc:  # noqa: BLE001 — bewust: PDF is nice-to-have voor deze verificatie
        print(f"LET OP: PDF-upload mislukt ({exc}) — factuurbeeld in de PWA zal een fout tonen; seed gaat door.")

    with scoped_session(administratie_id, actor_id=beheerder_id) as session:
        session.add(
            Document(
                id=document_id,
                administratie_id=administratie_id,
                bron=DocumentBron.UPLOAD,
                bestandsnaam=bestandsnaam,
                sha256_hash=hashlib.sha256(pdf).hexdigest(),
                status=DocumentStatus.KLAAR_OM_TE_BOEKEN,
                opslag_pad=opslag_pad,
            )
        )
    print(f"Document aangemaakt: {bestandsnaam} ({document_id})")

    boekvoorstel_service.sla_boekvoorstel_op(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=beheerder_id,
        vendor_id=uuid.uuid4(),  # synthetisch — zie docstring
        referentie=referentie,
        factuurdatum=datetime.now(UTC).date(),
        totaalbedrag=NETTO + BTW,
        regels=[
            boekvoorstel_service.BoekvoorstelRegelData(
                ledger_id=uuid.uuid4(),
                taxrate_id=uuid.uuid4(),
                project_id=None,
                netto_bedrag=NETTO,
                btw_bedrag=BTW,
                omschrijving=f"TEST notificatie-verificatie {referentie}",
            )
        ],
    )

    resultaat = accordering_service.bied_ter_accordering_aan(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=beheerder_id,
        actor_rol=GebruikerRol.BEHEERDER.value,
    )
    print(f"{referentie}: ter accordering aangeboden (status {resultaat.accordering.status}).")
    print()
    print("Klaar: 1 open accordering voor het passkeytest-account — de 09:00-job heeft nu iets te melden.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
