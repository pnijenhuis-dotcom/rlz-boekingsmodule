"""Kliktest-voorbereiding accordeur-PWA (slot grote opdracht 2026-08-11).

Zet op de TEST-administratie klaar, via de BESTAANDE flows (geen sluiproutes):
1. een testaccordeur-account (uitnodiging, rol klant_accordeur, scope test-administratie) —
   print de activatielink;
2. de accorderingsinstellingen: toggle aan + één laag met de testaccordeur;
3. 2-3 documenten ter accordering (boekvoorstel invullen + `bied_ter_accordering_aan`, dus
   mét de echte harde-checks-poort incl. live RLZ-duplicaatquery). Vendor/grootboek/btw-code
   worden gekopieerd van een eerder GEBOEKT document op dezelfde administratie (bewezen
   geldige combinatie); referenties krijgen een uniek KLIKTEST-stempel (geen duplicaatblok).

Draaien: .venv/bin/python scripts/kliktest_accordeur_seed.py  (idempotent: bestaande
testaccordeur krijgt een nieuwe uitnodigingslink zolang die nog niet geactiveerd is; al
aangeboden documenten worden overgeslagen). NB het laatste akkoord van de accordeur BOEKT
ECHT naar de RLZ-test-administratie (bestaande boekmotor) — storneren kan met actie 19,
consistent met de testdata-afspraak (v1.3)."""

from __future__ import annotations

import hashlib
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select  # noqa: E402

from app.accordering import service as accordering_service  # noqa: E402
from app.auth import service as auth_service  # noqa: E402
from app.db.models import Gebruiker, GebruikerRol, GebruikerStatus, Uitnodiging  # noqa: E402
from app.db.session import scoped_session  # noqa: E402
from app.documenten import boekvoorstel as boekvoorstel_service  # noqa: E402
from app.documenten.models import Boekvoorstel, Document, DocumentSoort, DocumentStatus  # noqa: E402

TEST_ADMINISTRATIE_ID = uuid.UUID("faae29c5-d197-4c24-a704-be2eae91fe49")
PETER_ID = uuid.UUID("2f2262cd-0423-4910-b7b5-335ba37a6ef5")
ACCORDEUR_EMAIL = "accordeur-kliktest@nijenhuis.local"
ACCORDEUR_NAAM = "Test Accordeur (kliktest)"

# Bewezen geldige boekcombinatie: gekopieerd van het geboekte document 2600549.pdf op de
# test-administratie (vendor/ledger/taxrate bestaan gegarandeerd in RLZ).
VENDOR_ID = uuid.UUID("f7a74265-518a-4384-ad6e-214aeee28c27")
LEDGER_ID = uuid.UUID("c1c355aa-3618-4519-ad5e-e19712e13d72")
TAXRATE_ID = uuid.UUID("1e44993a-15f6-419f-87e5-3e31ac3d9383")

# Drie bedragen; nr. 2 en 3 exact gelijk → Peter ziet ná het 2e akkoord het
# staande-goedkeuring-voorstel (mockup-flow "2e identieke factuur").
DOCUMENT_PLAN = [
    ("KLIKTEST-ACC-1", Decimal("100.00"), Decimal("21.00")),
    ("KLIKTEST-ACC-2", Decimal("84.70"), Decimal("17.79")),
    ("KLIKTEST-ACC-3", Decimal("84.70"), Decimal("17.79")),
]


def _accordeur_met_uitnodiging() -> tuple[uuid.UUID, str | None]:
    """Bestaande accordeur hergebruiken; is die nog niet geactiveerd, geef dan een verse
    uitnodigingslink uit (zelfde hash-patroon als auth_service — het token verlaat dit script
    alleen via stdout, er wordt niets geprint dat als secret bewaard blijft)."""
    with scoped_session(None, actor_id=PETER_ID) as session:
        bestaand = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == ACCORDEUR_EMAIL)).one_or_none()
        if bestaand is None:
            pass
        elif bestaand.status == GebruikerStatus.ACTIEF:
            print(f"Testaccordeur bestaat al en is actief: {ACCORDEUR_EMAIL}")
            return bestaand.id, None
        else:
            token = secrets.token_urlsafe(32)
            session.add(
                Uitnodiging(
                    id=uuid.uuid4(),
                    gebruiker_id=bestaand.id,
                    token_hash=hashlib.sha256(token.encode()).hexdigest(),
                    aangemaakt_door=PETER_ID,
                    verloopt_op=datetime.now(UTC) + timedelta(hours=72),
                )
            )
            print(f"Nieuwe uitnodigingslink voor bestaande testaccordeur ({ACCORDEUR_EMAIL}).")
            return bestaand.id, token

    resultaat = auth_service.maak_uitnodiging(
        actor_id=PETER_ID,
        naam=ACCORDEUR_NAAM,
        e_mail=ACCORDEUR_EMAIL,
        rol=GebruikerRol.KLANT_ACCORDEUR,
        administratie_ids=[TEST_ADMINISTRATIE_ID],
    )
    print(f"Testaccordeur aangemaakt: {ACCORDEUR_EMAIL}")
    return resultaat.gebruiker_id, resultaat.token


def _zet_accorderingslaag(accordeur_id: uuid.UUID) -> None:
    ingeschakeld, lagen, _ = accordering_service.instellingen_ophalen(administratie_id=TEST_ADMINISTRATIE_ID)
    if ingeschakeld and any(laag.accordeur_gebruiker_id == accordeur_id for laag in lagen):
        print("Accordering staat al aan met de testaccordeur als laag.")
        return
    accordering_service.instellingen_opslaan(
        administratie_id=TEST_ADMINISTRATIE_ID,
        actor_id=PETER_ID,
        actor_rol=GebruikerRol.BEHEERDER.value,
        ingeschakeld=True,
        lagen=[
            accordering_service.LaagInput(volgnummer=1, accordeur_gebruiker_id=accordeur_id, bedrag_drempel=None)
        ],
    )
    print("Accordering aangezet: 1 laag (testaccordeur, geen drempel).")


def _kandidaat_documenten() -> list[uuid.UUID]:
    """Te controleren inkoop-PDF's zonder al-lopend/afgerond accorderingsspoor."""
    with scoped_session(TEST_ADMINISTRATIE_ID) as session:
        rijen = session.scalars(
            select(Document)
            .where(
                Document.administratie_id == TEST_ADMINISTRATIE_ID,
                Document.status == DocumentStatus.TE_CONTROLEREN,
                Document.soort == DocumentSoort.INKOOPFACTUUR,
                Document.bestandsnaam.like("%.pdf"),
            )
            .order_by(Document.aangemaakt_op)
        ).all()
        return [d.id for d in rijen]


def main() -> None:
    accordeur_id, token = _accordeur_met_uitnodiging()
    _zet_accorderingslaag(accordeur_id)

    kandidaten = _kandidaat_documenten()
    aangeboden = 0
    for referentie, netto, btw in DOCUMENT_PLAN:
        with scoped_session(TEST_ADMINISTRATIE_ID) as session:
            al_gebruikt = session.scalars(
                select(Boekvoorstel).where(Boekvoorstel.referentie == referentie)
            ).first()
        if al_gebruikt is not None:
            print(f"{referentie}: bestaat al — overgeslagen.")
            aangeboden += 1
            continue
        if not kandidaten:
            print(f"{referentie}: geen te_controleren-PDF meer beschikbaar — overgeslagen.")
            continue
        document_id = kandidaten.pop(0)
        boekvoorstel_service.sla_boekvoorstel_op(
            administratie_id=TEST_ADMINISTRATIE_ID,
            document_id=document_id,
            actor_id=PETER_ID,
            vendor_id=VENDOR_ID,
            referentie=referentie,
            factuurdatum=datetime.now(UTC).date(),
            totaalbedrag=netto + btw,
            regels=[
                boekvoorstel_service.BoekvoorstelRegelData(
                    ledger_id=LEDGER_ID,
                    taxrate_id=TAXRATE_ID,
                    project_id=None,
                    netto_bedrag=netto,
                    btw_bedrag=btw,
                    omschrijving=f"Kliktest accordeur-PWA {referentie}",
                )
            ],
        )
        resultaat = accordering_service.bied_ter_accordering_aan(
            administratie_id=TEST_ADMINISTRATIE_ID,
            document_id=document_id,
            actor_id=PETER_ID,
            actor_rol=GebruikerRol.BEHEERDER.value,
        )
        print(
            f"{referentie}: ter accordering aangeboden "
            f"(document {document_id}, status {resultaat.accordering.status})."
        )
        aangeboden += 1

    print()
    print(f"Klaar: {aangeboden}/{len(DOCUMENT_PLAN)} documenten ter accordering.")
    if token:
        print()
        print("ACTIVATIELINK testaccordeur (72 uur geldig, eenmalig):")
        print(f"  http://localhost:5173/activeren?token={token}")
        print("  (op de telefoon: vervang localhost door het LAN-IP van deze Mac)")


if __name__ == "__main__":
    main()
