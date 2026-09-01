# ruff: noqa: F811 — pytest-fixtures als parameters
"""Maandagochtend-digest kantoor (D2, 01-09; migratie 0097): inhoud puur (alleen tellers > 0, klantleesbaar),
selectie per scope, alleen versturen bij iets te melden, idempotent per ISO-week (claim-vóór-verzenden),
opt-out per gebruiker (eigen endpoint, geaudit), mailfout zichtbaar (nooit stil)."""

from __future__ import annotations

import uuid
from datetime import date
from decimal import Decimal

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine, text

from app.berichten import digest, mail
from app.documenten import service as documenten_service
from app.documenten.models import Boekvoorstel
from app.documenten.service import WerkvoorraadKlant
from app.main import app
from app.security.tokens import create_access_token
from tests.auth.conftest import administratie_id, beheerder_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401

client = TestClient(app)


def _bearer(gebruiker_id: uuid.UUID, *, rol: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(gebruiker_id, rol=rol)}"}


def _klant(**over) -> WerkvoorraadKlant:
    basis = dict(
        administratie_id=uuid.uuid4(), naam="Testklant B.V.", te_controleren=0, klaar_om_te_boeken=0, vragen=0,
        afgewezen=0, bij_klant=0, iban_wachtend=0,
    )
    basis.update(over)
    return WerkvoorraadKlant(**basis)


class TestInhoudPuur:
    def test_alleen_administraties_met_tellers_klantleesbaar_gesorteerd(self) -> None:
        regels = digest.bouw_regels(
            [
                _klant(naam="Zebra B.V.", te_controleren=3, vragen=1, bij_klant=2, duplicaat_signalen=1),
                _klant(naam="Leeg B.V."),
                _klant(naam="Alfa B.V.", klaar_om_te_boeken=1, terugkerend_signalen=2, match_afwijkingen=1),
            ]
        )
        assert [r.naam for r in regels] == ["Alfa B.V.", "Zebra B.V."]
        assert regels[1].onderdelen == (
            "3 te controleren",
            "1 open vraag",
            "2 bij de klant (accordering)",
            "signalen: 1 duplicaatsignaal",
        )
        assert regels[0].onderdelen == (
            "1 klaar om te boeken",
            "signalen: 1 urenmatch-afwijking, 2 verwachte facturen ontbreken",
        )

    def test_mail_en_isoweek(self) -> None:
        onderwerp, tekst = digest.bouw_mail(
            naam="Demi", week="2026-W36", regels=[digest.AdministratieRegel("Alfa B.V.", ("2 te controleren",))]
        )
        assert onderwerp == "Weekstart: 1 administratie met openstaand werk (2026-W36)"
        assert "Beste Demi" in tekst and "• Alfa B.V.: 2 te controleren" in tekst
        assert "Instellingen › Beveiliging › Weekmail" in tekst
        assert digest.iso_week(date(2026, 8, 31)) == "2026-W36"  # maandag 31-08 = week 36
        assert digest.iso_week(date(2026, 1, 1)) == "2026-W01"


@pytest.fixture
def open_werk(administratie_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, opslag) -> uuid.UUID:
    """Eén te-controleren inkoopfactuur in de scope van de gescoopte medewerker én van de Beheerder."""
    from app.db.session import scoped_session

    document_id = documenten_service.upload_document(
        administratie_id=administratie_id,
        bestandsnaam="digest.pdf",
        inhoud=b"%PDF-1.4 digest",
        actor_id=gescoopte_gebruiker,
        opslag=opslag,
    ).document_id
    with scoped_session(administratie_id, actor_id=gescoopte_gebruiker) as session:
        session.add(Boekvoorstel(document_id=document_id, vendor_id=uuid.uuid4(), factuurdatum=date(2026, 8, 25), totaalbedrag=Decimal("10")))
    return document_id


def _verzonden(admin_engine: Engine) -> list[tuple]:
    with admin_engine.connect() as conn:
        return conn.execute(text("SELECT gebruiker_id, iso_week, status FROM platform.kantoor_digest ORDER BY aangemaakt_op")).all()


class TestVerzending:
    def test_niets_te_melden_geen_mail_geen_rij(self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine) -> None:
        mails: list[dict] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: mails.append(kw))
        rapport = digest.verstuur_weekdigest(vandaag=date(2026, 8, 31))
        assert rapport.verzonden == 0 and rapport.niets_te_melden >= 1 and not rapport.is_fout
        assert mails == [] and _verzonden(admin_engine) == []

    def test_open_werk_mailt_eenmaal_per_week_en_respecteert_opt_out(
        self, beheerder_id: uuid.UUID, gescoopte_gebruiker: uuid.UUID, open_werk: uuid.UUID, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine
    ) -> None:
        mails: list[dict] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: mails.append(kw))
        rapport = digest.verstuur_weekdigest(vandaag=date(2026, 8, 31))
        # Beheerder (alles) + gescoopte medewerker: beide zien de administratie mét 1 te controleren.
        assert rapport.verzonden == 2 and not rapport.is_fout
        assert all("1 te controleren" in m["tekst"] and "(2026-W36)" in m["onderwerp"] for m in mails)
        # Herhaalde run (zelfde week): idempotent — niets dubbel.
        opnieuw = digest.verstuur_weekdigest(vandaag=date(2026, 9, 2))
        assert opnieuw.verzonden == 0 and opnieuw.al_verzonden == 2 and len(mails) == 2
        assert {r.status for r in _verzonden(admin_engine)} == {"verzonden"}
        # Nieuwe week + opt-out van de medewerker: alleen de Beheerder krijgt 'm.
        digest.zet_opt_out(gebruiker_id=gescoopte_gebruiker, opt_out=True)
        volgende = digest.verstuur_weekdigest(vandaag=date(2026, 9, 7))
        assert volgende.verzonden == 1 and volgende.opt_out == 1 and len(mails) == 3
        with admin_engine.connect() as conn:
            n = conn.execute(text("SELECT count(*) FROM platform.audit_event WHERE actie = 'digest_opt_out_gewijzigd' AND record_id = :id"), {"id": gescoopte_gebruiker}).scalar()
        assert n == 1

    def test_mailfout_is_zichtbaar_en_herkansbaar(self, beheerder_id: uuid.UUID, open_werk: uuid.UUID, monkeypatch: pytest.MonkeyPatch, admin_engine: Engine) -> None:
        def kapot(**kw):
            raise mail.MailFout("SMTP weigert (simulatie)")

        monkeypatch.setattr(mail, "verzend_mail", kapot)
        rapport = digest.verstuur_weekdigest(vandaag=date(2026, 8, 31))
        assert rapport.is_fout and rapport.mislukt >= 1 and any("SMTP weigert" in f for f in rapport.fouten)
        assert {r.status for r in _verzonden(admin_engine)} == {"mislukt"}
        # Herkansing ná herstel: de mislukte rij wordt hergebruikt en alsnog verzonden.
        mails: list[dict] = []
        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: mails.append(kw))
        rapport2 = digest.verstuur_weekdigest(vandaag=date(2026, 8, 31))
        assert rapport2.verzonden >= 1 and not rapport2.is_fout
        assert {r.status for r in _verzonden(admin_engine)} == {"verzonden"}


class TestEndpoint:
    def test_eigen_voorkeur_lezen_en_zetten_kantoorrol(self, gescoopte_gebruiker: uuid.UUID) -> None:
        headers = _bearer(gescoopte_gebruiker, rol="boekhouding")
        assert client.get("/auth/mijn/digest", headers=headers).json() == {"opt_out": False}
        assert client.put("/auth/mijn/digest", headers=headers, json={"opt_out": True}).json() == {"opt_out": True}
        assert client.get("/auth/mijn/digest", headers=headers).json() == {"opt_out": True}
        assert digest.haal_opt_out_op(gebruiker_id=gescoopte_gebruiker) is True

    def test_cli(self, beheerder_id: uuid.UUID, monkeypatch: pytest.MonkeyPatch) -> None:
        import argparse

        from app.cli import main

        monkeypatch.setattr(mail, "verzend_mail", lambda **kw: None)
        monkeypatch.setattr("sys.argv", ["app.cli", "kantoor-digest"])
        try:
            code = main()
        except SystemExit as exc:  # main() kan sys.exit doen
            code = exc.code
        assert code in (0, None)
        del argparse
