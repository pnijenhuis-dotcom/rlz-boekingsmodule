"""Cloud-prep: herhaalbare verificatie van de nieuwe-facturen-bundelmelding (2026-08-17).

Aanleiding (diagnose 17-08): de eerste handmatige run van `rlz-nieuwe-facturen` verstuurde
niets — correct gedrag: de run viel om 06:54 NL-tijd in de stille uren (20:00–08:00) én het
geseede TEST-document was op 16-08 al goedgekeurd (accordering afgerond → 0 aan de beurt).
Dit script zet de uitgangssituatie klaar zodat één jobrun deterministisch precies één push
oplevert: "Er staat 1 factuur voor u klaar."

Wat het doet (idempotent, alleen op de vergankelijke SEED-PASSKEYTEST-administratie):
1. hergebruikt het bestaande TEST-ACC-NOTIF-01-document (cloud_seed_accordering.py) en biedt
   het opnieuw ter accordering aan als er geen open ronde loopt — het document blijft na een
   afgeronde ronde op klaar_om_te_boeken staan (boeken faalt zichtbaar: bewust geen credential);
2. reset de gemeld-claim (platform.accordeur_nieuw_gemeld) voor exact déze accordeur+document
   naar 'overgeslagen' zodat de job het document opnieuw als nieuw ziet.
   ⚠️ BEWUSTE AFWIJKING van de productieregel "nooit tweemaal melden" — uitsluitend hier,
   surgical op (passkeytest-accordeur, TEST-ACC-NOTIF-01), gemarkeerd in het detail-veld.
   De app-rol heeft bewust geen DELETE op die tabel; reset = UPDATE naar een her-claimbare
   status, precies het pad dat de job zelf ook opnieuw probeert.
3. bewaakt de randvoorwaarden voor het verwachte resultaat: geen staande goedkeuring (zou de
   verse ronde direct auto-afronden), exact 1 document aan de beurt voor de accordeur (anders
   zou de tekst "Er staan N facturen" luiden), en ≥1 actieve push-subscriptie (anders valt het
   bericht terug op e-mail — dat melden we, maar we stoppen er niet op).

Draaien: via scripts/gcp/nieuwe_facturen_verificatie.sh (dat regelt proxy, tijdvenster,
jobrun en logcontrole), of los met het recept uit cloud_seed_accordering.py:
    cloud-sql-proxy rlz-boekhouding:europe-west4:rlz-sql2 --port 5434 --gcloud-auth &
    cd backend
    APP_DATABASE_URL="postgresql+psycopg://boekhouding_app:\
$(gcloud secrets versions access latest --secret=APP_DB_PASSWORD)@127.0.0.1:5434/boekhouding" \
        .venv/bin/python scripts/cloud_verificatie_nieuwe_facturen.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

ACCORDEUR_EMAIL = "accordeur-passkeytest@ak-nijenhuis.nl"
TEST_ADMIN_RLZ_ID = "SEED-PASSKEYTEST"
REFERENTIE = "TEST-ACC-NOTIF-01"


def _controleer_database_doel() -> None:
    """Zelfde failsafe als de andere cloud-scripts: expliciet doel, nooit de lokale dev-DB."""
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


def main() -> int:
    _controleer_database_doel()

    # Imports pas ná de failsafe: het app-pakket bindt de database-engine bij import.
    from sqlalchemy import select

    from app.accordering import service as accordering_service
    from app.accordering.models import AccorderingStatus, DocumentAccordering, StaandeGoedkeuring
    from app.berichten import verzending
    from app.berichten.models import AccordeurNieuwGemeld, HerinneringStatus
    from app.berichten.nieuwe_facturen import _documenten_per_accordeur, in_stille_uren
    from app.db.models import Administratie, Gebruiker, GebruikerRol, GebruikerStatus
    from app.db.session import scoped_session
    from app.db.systeem_actor import SYSTEEM_ACTOR_ID
    from app.documenten.models import Boekvoorstel, Document, DocumentStatus

    # 0. Tijdvenster: buiten 08:00–20:00 NL verstuurt de job sowieso niets — dan is een
    #    verificatierun zinloos. Alleen melden; de wrapper stopt hier al eerder op.
    if in_stille_uren():
        print(
            "LET OP: het is nu stille uren (20:00–08:00 Europe/Amsterdam) — de job zal niets "
            "versturen. Draai de verificatie tussen 08:00 en 20:00."
        )

    # 1. Bestaande seed-objecten (dit script maakt niets nieuws aan — ontbreekt er iets,
    #    dan eerst cloud_seed_accordeur.py / cloud_seed_accordering.py draaien).
    with scoped_session(None) as session:
        beheerder = session.scalars(
            select(Gebruiker).where(Gebruiker.rol == GebruikerRol.BEHEERDER, Gebruiker.status == GebruikerStatus.ACTIEF)
        ).first()
        if beheerder is None:
            print("FOUT: geen actieve Beheerder in de doel-database.", file=sys.stderr)
            return 1
        beheerder_id = beheerder.id
        accordeur = session.scalars(select(Gebruiker).where(Gebruiker.e_mail == ACCORDEUR_EMAIL)).one_or_none()
        if accordeur is None or accordeur.status != GebruikerStatus.ACTIEF:
            print(f"FOUT: {ACCORDEUR_EMAIL} ontbreekt of is niet actief — draai cloud_seed_accordeur.py.", file=sys.stderr)
            return 1
        accordeur_id = accordeur.id
        administratie = session.scalars(
            select(Administratie).where(Administratie.rlz_admin_id == TEST_ADMIN_RLZ_ID)
        ).one_or_none()
        if administratie is None:
            print("FOUT: SEED-PASSKEYTEST-administratie ontbreekt — draai cloud_seed_accordeur.py.", file=sys.stderr)
            return 1
        administratie_id = administratie.id

    with scoped_session(administratie_id) as session:
        voorstel = session.scalars(select(Boekvoorstel).where(Boekvoorstel.referentie == REFERENTIE)).one_or_none()
        if voorstel is None:
            print(f"FOUT: {REFERENTIE} ontbreekt — draai eerst cloud_seed_accordering.py.", file=sys.stderr)
            return 1
        document_id = voorstel.document_id
        document = session.get(Document, document_id)
        assert document is not None
        document_status = document.status
        open_ronde = session.scalars(
            select(DocumentAccordering).where(
                DocumentAccordering.document_id == document_id,
                DocumentAccordering.status == AccorderingStatus.OPEN.value,
            )
        ).one_or_none()
        staande = session.scalars(
            select(StaandeGoedkeuring).where(
                StaandeGoedkeuring.accordeur_gebruiker_id == accordeur_id,
                StaandeGoedkeuring.actief.is_(True),
                StaandeGoedkeuring.ingetrokken_op.is_(None),
            )
        ).all()
    print(f"Accordeur {accordeur_id} · administratie {administratie_id} · document {document_id}")

    # 2. Guard: een actieve staande goedkeuring zou de verse ronde direct auto-afronden —
    #    dan komt er nooit een open ronde en dus geen melding. Intrekken is klikwerk (kantoor-UI).
    if staande:
        print(
            f"FOUT: er staan {len(staande)} actieve staande goedkeuring(en) voor dit account — "
            "die ronden een nieuwe aanbieding direct af. Eerst intrekken (Instellingen → "
            "accordering), dan dit script opnieuw draaien.",
            file=sys.stderr,
        )
        return 1

    # 3. Open ronde garanderen: her-aanbieden mag zodra er geen open ronde loopt (een eerdere
    #    afgeronde ronde blokkeert niet; het document blijft klaar_om_te_boeken).
    if open_ronde is not None:
        print("Open accorderingsronde bestaat al — hergebruikt.")
    else:
        if document_status != DocumentStatus.KLAAR_OM_TE_BOEKEN:
            print(
                f"FOUT: document staat op {document_status.value} (verwacht klaar_om_te_boeken) — "
                "handmatig beoordelen; niets aangeboden.",
                file=sys.stderr,
            )
            return 1
        resultaat = accordering_service.bied_ter_accordering_aan(
            administratie_id=administratie_id,
            document_id=document_id,
            actor_id=beheerder_id,
            actor_rol=GebruikerRol.BEHEERDER.value,
        )
        if resultaat.accordering.status != AccorderingStatus.OPEN.value:
            print(
                f"FOUT: nieuwe ronde kreeg status {resultaat.accordering.status} (verwacht open) — "
                "waarschijnlijk auto-afgerond; niets te melden.",
                file=sys.stderr,
            )
            return 1
        print(f"{REFERENTIE}: opnieuw ter accordering aangeboden (nieuwe open ronde).")

    # 4. Gemeld-claim resetten (surgical: alleen deze accordeur + dit document). 'verzonden'
    #    en 'bezig' worden her-claimbaar 'overgeslagen'; het detail-veld draagt de reden.
    with scoped_session(None, actor_id=SYSTEEM_ACTOR_ID) as session:
        rijen = session.scalars(
            select(AccordeurNieuwGemeld).where(
                AccordeurNieuwGemeld.gebruiker_id == accordeur_id,
                AccordeurNieuwGemeld.document_id == document_id,
            )
        ).all()
        gereset = 0
        for rij in rijen:
            if rij.status in (HerinneringStatus.VERZONDEN.value, HerinneringStatus.BEZIG.value):
                rij.detail = {"reset": "verificatie-herhaling nieuwe-facturen", "was": rij.status}
                rij.status = HerinneringStatus.OVERGESLAGEN.value
                rij.kanaal = None
                gereset += 1
    print(f"Gemeld-claim: {gereset} rij(en) gereset naar 'overgeslagen' (her-claimbaar).")

    # 5. Verwacht-resultaat-bewaking: exact 1 document aan de beurt voor deze accordeur,
    #    over álle administraties (dezelfde selectie als de job).
    aan_de_beurt = _documenten_per_accordeur().get(accordeur_id, set())
    if aan_de_beurt != {document_id}:
        print(
            f"FOUT: verwacht exact 1 document aan de beurt ({document_id}), "
            f"gevonden: {sorted(map(str, aan_de_beurt))} — de meldingstekst zou afwijken. "
            "Eerst opruimen/afronden, dan opnieuw.",
            file=sys.stderr,
        )
        return 1
    print("Aan de beurt voor deze accordeur: exact 1 document ✓")

    # 6. Kanaal-vooruitblik (informatief): zonder actieve subscriptie valt de job terug op mail.
    subscripties = verzending.actieve_subscripties(accordeur_id)
    if subscripties:
        print(f"Actieve push-subscriptie(s): {len(subscripties)} — verwacht kanaal: push.")
    else:
        print("LET OP: geen actieve push-subscriptie — de melding komt dan als e-mail, niet als push.")

    print()
    print("Klaar. Draai nu (tussen 08:00 en 20:00 NL):")
    print("  gcloud run jobs execute rlz-nieuwe-facturen --region europe-west4 --wait")
    print('Verwacht op de iPhone: push "Er staat 1 factuur voor u klaar."')
    print("Verwacht in de joblog: 'Nieuwe-facturen-meldingen: 1 push, 0 e-mail, 1 document(en) nieuw gemeld, …'")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
