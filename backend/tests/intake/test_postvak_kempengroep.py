# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Derde intake-kanaal facturen@kempengroep.nl DIRECT gelezen (Peter 22-09; migratie 0171): eigen instellingen
(INTAKE_KEMPENGROEP_IMAP_*), eigen job-alias `intake-postvak-kempengroep-verwerken`, kanaal-markering op het
intake-bericht + verwerkt-rij, "via facturen@kempengroep.nl" in de herkomst van het document, en het dubbel-pad in de
overgangsperiode (forward nog aan): zelfde Message-ID = al bekend, handmatige Fwd met zelfde bijlage = duplicaat-vlag +
teller "dubbel via forward"."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import Engine, text

from app import cli
from app.config import settings
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten import service as documenten_service
from app.documenten.betaalstatus import KANAAL_FACTUREN_KEMPENGROEP, KANALEN, POSTVAK_ADRES_PER_KANAAL
from app.intake import verwerking, verwerkt
from app.intake.postvak import INBOX, KANALEN_MET_JOB, ImapInstellingen, ImapPostvakBron, PostvakNietGeconfigureerd
from tests.auth.conftest import administratie_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.intake.conftest import administratie_heet_blow, bouw_eml, bouw_ubl  # noqa: F401
from tests.intake.test_postvak_imap import SPAM, FakeImap, _koppel_fake


@pytest.fixture
def kempengroep_geconfigureerd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "intake_kempengroep_imap_host", "imap.gmail.com")
    monkeypatch.setattr(settings, "intake_kempengroep_imap_gebruiker", "facturen@kempengroep.nl")
    monkeypatch.setattr(settings, "intake_kempengroep_imap_wachtwoord", "app-wachtwoord")


@pytest.fixture
def facturen_geconfigureerd(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(settings, "intake_imap_host", "imap.gmail.com")
    monkeypatch.setattr(settings, "intake_imap_gebruiker", "facturen@ak-nijenhuis.nl")
    monkeypatch.setattr(settings, "intake_imap_wachtwoord", "x")


def _blow_eml(message_id: str, ubl: bytes | None = None, *, afzender: str = "leverancier@voorbeeld.example") -> bytes:
    """UBL mét tenaamstelling BLOW B.V. — deterministische toewijzing (geen intake-AI nodig in de test)."""
    return bouw_eml(
        afzender=afzender,
        onderwerp="Factuur BLOW B.V.",
        message_id=message_id,
        bijlagen=[("factuur.xml", ubl or bouw_ubl(klant="BLOW B.V.", factuurnummer=f"F-{message_id[1:9]}"), "application", "xml")],
    )


class TestKanaal:
    def test_kanaal_bestaat_met_postvakadres_en_job(self) -> None:
        assert KANAAL_FACTUREN_KEMPENGROEP in KANALEN
        assert POSTVAK_ADRES_PER_KANAAL[KANAAL_FACTUREN_KEMPENGROEP] == "facturen@kempengroep.nl"
        assert KANALEN_MET_JOB == ("facturen", "facturen_kempengroep")  # declaraties@ heeft geen job → geen FOUT

    def test_instellingen_eigen_prefix(self, kempengroep_geconfigureerd) -> None:
        i = ImapInstellingen.voor_kanaal("facturen_kempengroep")
        assert (i.gebruiker, i.env_prefix, i.ontbrekend(), i.geconfigureerd) == (
            "facturen@kempengroep.nl",
            "INTAKE_KEMPENGROEP_IMAP",
            [],
            True,
        )

    def test_niet_geconfigureerd_meldt_de_eigen_envs(self) -> None:
        with pytest.raises(PostvakNietGeconfigureerd) as exc:
            list(ImapPostvakBron("facturen_kempengroep").nieuwe_berichten())
        assert "INTAKE_KEMPENGROEP_IMAP_*" in str(exc.value)
        assert "INTAKE_KEMPENGROEP_IMAP_WACHTWOORD" in str(exc.value)

    def test_cli_alias_niet_geconfigureerd_is_exit_1(self, capsys) -> None:
        assert cli.main(["intake-postvak-kempengroep-verwerken"]) == 1
        assert "facturen_kempengroep" in capsys.readouterr().err


class TestCliAlias:
    def test_alias_markeert_kanaal_op_bericht_verwerkt_rij_en_herkomst(
        self, kempengroep_geconfigureerd, monkeypatch, admin_engine: Engine, administratie_heet_blow, opslag, capsys
    ) -> None:
        mid = f"<kg-{uuid.uuid4()}@kempengroep.nl>"
        fake = FakeImap({INBOX: {b"3": _blow_eml(mid)}})
        _koppel_fake(monkeypatch, fake)

        assert cli.main(["intake-postvak-kempengroep-verwerken"]) == 0, capsys.readouterr()
        assert fake.gelezen_gemarkeerd == [(INBOX, b"3")]
        with admin_engine.connect() as conn:
            rij = conn.execute(
                text("SELECT id, kanaal, bron FROM boekhouding.intake_bericht WHERE message_id = :m"), {"m": mid}
            ).one()
            verwerkt_rij = conn.execute(
                text("SELECT kanaal, uitkomst FROM boekhouding.intake_bericht_verwerkt WHERE message_id = :m"), {"m": mid}
            ).one()
            document_id = conn.execute(
                text("SELECT id FROM boekhouding.document WHERE intake_bericht_id = :b"), {"b": rij.id}
            ).scalar_one()
        assert (rij.kanaal, rij.bron) == ("facturen_kempengroep", "imap")
        assert tuple(verwerkt_rij) == ("facturen_kempengroep", "verwerkt")

        # "Uit de e-mail" op het controlescherm zegt via welk postvak het kwam (Peter: kanaal zichtbaar).
        detail = documenten_service.haal_document_op(administratie_id=administratie_heet_blow, document_id=document_id)
        assert detail.herkomst_mail is not None
        assert (detail.herkomst_mail.kanaal, detail.herkomst_mail.postvak_adres, detail.herkomst_mail.uit_spam) == (
            "facturen_kempengroep",
            "facturen@kempengroep.nl",
            False,
        )

    def test_spam_herkomst_zichtbaar_in_document_detail(
        self, kempengroep_geconfigureerd, monkeypatch, admin_engine: Engine, administratie_heet_blow, opslag
    ) -> None:
        mid = f"<kg-spam-{uuid.uuid4()}@kempengroep.nl>"
        _koppel_fake(monkeypatch, FakeImap({SPAM: {b"8": _blow_eml(mid)}}))
        assert cli.main(["intake-postvak-kempengroep-verwerken"]) == 0
        with admin_engine.connect() as conn:
            document_id = conn.execute(
                text(
                    "SELECT d.id FROM boekhouding.document d JOIN boekhouding.intake_bericht b ON b.id = d.intake_bericht_id "
                    "WHERE b.message_id = :m"
                ),
                {"m": mid},
            ).scalar_one()
        detail = documenten_service.haal_document_op(administratie_id=administratie_heet_blow, document_id=document_id)
        assert detail.herkomst_mail is not None and detail.herkomst_mail.uit_spam is True


class TestTweeKanalenZelfdeBijlage:
    """Overgangsperiode: de Gmail-forward staat nog aan, dus hetzelfde bericht komt op beide postvakken binnen."""

    def test_forward_met_behouden_message_id_is_al_bekend_geen_tweede_document(
        self, kempengroep_geconfigureerd, facturen_geconfigureerd, monkeypatch, admin_engine, administratie_heet_blow, opslag, capsys
    ) -> None:
        mid = f"<zelfde-{uuid.uuid4()}@leverancier.example>"
        eml = _blow_eml(mid)
        _koppel_fake(monkeypatch, FakeImap({INBOX: {b"1": eml}}))
        assert cli.main(["intake-postvak-kempengroep-verwerken"]) == 0
        # Zelfde bericht (forward behoudt Message-ID) in facturen@ak-nijenhuis.nl: op de kop al bekend → nooit opgehaald.
        fake2 = FakeImap({INBOX: {b"1": eml}})
        _koppel_fake(monkeypatch, fake2)
        assert cli.main(["intake-postvak-verwerken"]) == 0
        assert fake2.gefetcht_body == []
        assert "1 al bekend overgeslagen" in capsys.readouterr().out
        with admin_engine.connect() as conn:
            n_docs = conn.execute(text("SELECT count(*) FROM boekhouding.document WHERE administratie_id = :a"), {"a": administratie_heet_blow}).scalar_one()
        assert n_docs == 1

    def test_handmatige_fwd_zelfde_bijlage_is_duplicaat_vlag_en_dubbel_via_forward(
        self, kempengroep_geconfigureerd, facturen_geconfigureerd, monkeypatch, admin_engine, administratie_heet_blow, opslag, capsys
    ) -> None:
        ubl = bouw_ubl(klant="BLOW B.V.", factuurnummer="F-FWD-1")
        _koppel_fake(monkeypatch, FakeImap({INBOX: {b"1": _blow_eml(f"<orig-{uuid.uuid4()}@lev.example>", ubl)}}))
        assert cli.main(["intake-postvak-kempengroep-verwerken"]) == 0
        capsys.readouterr()
        # Handmatige "Fwd:" = nieuw Message-ID, zelfde bytes → tweede document mét mogelijk_duplicaat_van + teller.
        _koppel_fake(monkeypatch, FakeImap({INBOX: {b"2": _blow_eml(f"<fwd-{uuid.uuid4()}@kempengroep.nl>", ubl, afzender="facturen@kempengroep.nl")}}))
        assert cli.main(["intake-postvak-verwerken"]) == 0
        uit = capsys.readouterr().out
        assert "DUBBEL-VIA-FORWARD" in uit and "1 dubbel via forward" in uit
        with admin_engine.connect() as conn:
            rijen = conn.execute(
                text(
                    "SELECT mogelijk_duplicaat_van_id IS NOT NULL AS dubbel FROM boekhouding.document "
                    "WHERE administratie_id = :a ORDER BY aangemaakt_op"
                ),
                {"a": administratie_heet_blow},
            ).scalars().all()
            audit = conn.execute(
                text("SELECT nieuwe_waarde FROM platform.audit_event WHERE actie = 'intake_postvak_run' ORDER BY tijdstip DESC LIMIT 1")
            ).scalar_one()
        assert rijen == [False, True]
        assert audit["kanaal"] == "facturen" and audit["dubbel_via_forward"] == 1

    def test_dubbel_via_forward_is_false_zonder_ander_kanaal(self, administratie_heet_blow, opslag) -> None:
        r = verwerking.verwerk_eml(_blow_eml(f"<solo-{uuid.uuid4()}@x>"), actor_id=SYSTEEM_ACTOR_ID, bron="imap", kanaal="facturen")
        assert r.bericht_id is not None and verwerkt.dubbel_via_forward(r.bericht_id) is False


class TestVerwerktAdministratie:
    def test_bekende_sleutels_zijn_verwerkt_tabel_plus_elk_intake_bericht(self, administratie_heet_blow, opslag) -> None:
        mid_upload = f"<upload-{uuid.uuid4()}@x>"
        verwerking.verwerk_eml(_blow_eml(mid_upload), actor_id=SYSTEEM_ACTOR_ID, bron="eml_upload", kanaal="facturen")
        verwerkt.registreer(kanaal="facturen_kempengroep", sleutel="<alleen-tabel@x>", uid="1", postvak_map=INBOX, uitkomst="niet_verwerkbaar", intake_bericht_id=None)
        sleutels = verwerkt.bekende_sleutels("facturen_kempengroep")
        assert {mid_upload, "<alleen-tabel@x>"} <= sleutels
        # De tabel-rij van een ánder kanaal telt niet als bekend voor dit kanaal (elk postvak zijn eigen administratie) …
        assert "<alleen-tabel@x>" not in verwerkt.bekende_sleutels("facturen")
        # … maar een intake_bericht (welk kanaal ook) wél.
        assert mid_upload in verwerkt.bekende_sleutels("facturen")

    def test_registreer_is_idempotent_op_kanaal_en_sleutel(self, admin_engine: Engine) -> None:
        verwerkt.registreer(kanaal="facturen", sleutel="<idem@x>", uid="1", postvak_map=INBOX, uitkomst="niet_verwerkbaar", intake_bericht_id=None)
        verwerkt.registreer(kanaal="facturen", sleutel="<idem@x>", uid="1", postvak_map=INBOX, uitkomst="verwerkt", intake_bericht_id=None)
        with admin_engine.connect() as conn:
            rijen = conn.execute(text("SELECT uitkomst FROM boekhouding.intake_bericht_verwerkt WHERE message_id = '<idem@x>'")).scalars().all()
        assert rijen == ["verwerkt"]
