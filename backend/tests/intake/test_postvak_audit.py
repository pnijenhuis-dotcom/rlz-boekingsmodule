# ruff: noqa: F811, E501 — pytest-fixtures als parameters; lange assert-regels bewust
"""Lees-only dubbele mailbox-audit (Peter 22-09 avond, opdracht D): pure koppellogica (Message-ID → References →
bijlage-sha256 → bestandsnaam, gelabeld), de drie uitvalcategorieën, de omgekeerde controle, het module-spoor uit de DB
en de CLI-vorm `intake-postvak-audit --sinds` zoals het meetrecept 'm noemt."""

from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, date, datetime

from app import cli
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.intake import postvak_audit as pa
from app.intake import verwerking
from app.intake.postvak import INBOX, PostvakKop
from tests.auth.conftest import administratie_id  # noqa: F401
from tests.documenten.conftest import _opslag_naar_tmp, gescoopte_gebruiker, opslag  # noqa: F401
from tests.intake.conftest import administratie_heet_blow, bouw_eml, bouw_pdf, bouw_ubl  # noqa: F401

SPAM = "[Gmail]/Spam"
T = datetime(2026, 9, 10, 9, 0, tzinfo=UTC)


def _b(kanaal: str, mid: str | None, *bijlagen: tuple[str, str], map: str = INBOX, gelezen: bool = False, refs: tuple[str, ...] = (), afzender: str = "lev@x.example") -> pa.Bericht:
    return pa.Bericht(
        kanaal=kanaal, message_id=mid, uid=str(uuid.uuid4())[:6], map=map, datum=T, afzender=afzender, onderwerp="Factuur",
        gelezen=gelezen, bijlagen=tuple(pa.Bijlage(n, h) for n, h in bijlagen), references=refs,
    )


def _geen_spoor(bron, doorgifte) -> pa.ModuleSpoor:
    return pa.ModuleSpoor(None, None, (), "")


class TestKoppelPuur:
    def test_koppelvolgorde_message_id_references_sha_bestandsnaam(self) -> None:
        bron = [
            _b("kg", "<m1@l>", ("a.pdf", "h1")),
            _b("kg", "<m2@l>", ("b.pdf", "h2")),
            _b("kg", "<m3@l>", ("c.pdf", "h3")),
            _b("kg", "<m4@l>", ("d.pdf", "h4")),
        ]
        doel = [
            _b("ak", "<m1@l>", ("a.pdf", "h1")),
            _b("ak", "<fwd2@kg>", ("b.pdf", "h2"), refs=("<m2@l>",)),
            _b("ak", "<fwd3@kg>", ("c-hernoemd.pdf", "h3")),
            _b("ak", "<fwd4@kg>", ("d.pdf", "andere-bytes")),
        ]
        koppelingen, rechtstreeks = pa.koppel(bron, doel, lambda b, d: pa.ModuleSpoor(uuid.uuid4(), "facturen", (("geboekt", "BLOW", "RLZ-1", "a.pdf"),), "message_id"))
        assert [k.koppelvorm for k in koppelingen] == ["message_id", "references", "bijlage_sha256", "bestandsnaam"]
        assert all(k.uitval is None for k in koppelingen) and rechtstreeks == []

    def test_drie_uitvalcategorieen_en_oorzaak(self) -> None:
        bron = [_b("kg", "<a@l>", ("a.pdf", "ha")), _b("kg", "<b@l>", ("b.pdf", "hb")), _b("kg", "<c@l>", ("c.pdf", "hc")), _b("kg", "<d@l>", ("d.pdf", "hd"))]
        doel = [_b("ak", "<b@l>", ("b.pdf", "hb"), map=SPAM), _b("ak", "<c@l>", ("c.pdf", "hc"), gelezen=True), _b("ak", "<d@l>", ("d.pdf", "hd"))]
        koppelingen, _ = pa.koppel(bron, doel, _geen_spoor)
        assert [k.uitval for k in koppelingen] == [pa.UITVAL_NIET_DOORGESTUURD, pa.UITVAL_SPAM_OVERGESLAGEN, pa.UITVAL_INBOX_NIET_VERWERKT, pa.UITVAL_INBOX_NIET_VERWERKT]
        assert "nooit doorgestuurd" in koppelingen[0].oorzaak
        assert "Spam" in koppelingen[1].oorzaak
        assert "gelezen vóór de intake" in koppelingen[2].oorzaak
        assert "ongelezen" in koppelingen[3].oorzaak

    def test_module_spoor_wint_van_uitval(self) -> None:
        bron = [_b("kg", "<a@l>", ("a.pdf", "ha"))]
        k, _ = pa.koppel(bron, [], lambda b, d: pa.ModuleSpoor(uuid.uuid4(), "facturen_kempengroep", (("te_controleren", "BLOW", None, "a.pdf"),), "message_id"))
        assert k[0].uitval is None and k[0].doorgifte is None and "te_controleren · BLOW" in k[0].module.samenvatting

    def test_omgekeerde_controle_rechtstreekse_leverancier_zonder_spoor(self) -> None:
        bron = [_b("kg", "<a@l>", ("a.pdf", "ha"))]
        doel = [_b("ak", "<a@l>", ("a.pdf", "ha")), _b("ak", "<direct@lev>", ("z.pdf", "hz"), afzender="direct@lev.example")]
        _, rechtstreeks = pa.koppel(bron, doel, _geen_spoor)
        assert [d.message_id for d, _ in rechtstreeks] == ["<direct@lev>"]

    def test_ontdubbel_houdt_specifieke_map_en_gelezen(self) -> None:
        a = _b("kg", "<a@l>", ("a.pdf", "ha"), map=pa.ALLE_MAIL, gelezen=True)
        b = _b("kg", "<a@l>", ("a.pdf", "ha"), map=SPAM)
        [u] = pa.ontdubbel([a, b])
        assert (u.map, u.gelezen) == (SPAM, True)

    def test_rapport_regels_tellers_en_oordeel(self) -> None:
        rapport = pa.AuditRapport(sinds=date(2026, 7, 1), kanaal_bron="facturen_kempengroep", kanaal_doel="facturen")
        rapport.bron = [_b("kg", "<a@l>", ("a.pdf", "ha")), _b("kg", "<b@l>", ("b.pdf", "hb"))]
        rapport.doorgifte = [_b("ak", "<a@l>", ("a.pdf", "ha"))]
        rapport.koppelingen, rapport.rechtstreeks_zonder_spoor = pa.koppel(rapport.bron, rapport.doorgifte, _geen_spoor)
        regels = pa.rapport_regels(rapport)
        assert any("Bronberichten mét factuurbijlage: 2 · aangekomen in facturen: 1 · met module-spoor: 0" in r for r in regels)
        assert regels[-1].startswith("Oordeel: ROOD — 2 bronberichten, 2 zonder module-spoor (a 1 / b 0 / c 1)")
        leeg = pa.AuditRapport(sinds=date(2026, 7, 1), kanaal_bron="facturen_kempengroep", kanaal_doel="facturen")
        assert pa.rapport_regels(leeg)[-1].startswith("Oordeel: GROEN")

    def test_bericht_uit_eml_alleen_met_factuurbijlage(self) -> None:
        kop = PostvakKop(uid="1", map=INBOX, message_id="<k@x>", afzender=None, onderwerp=None, datum=None, gelezen=False)
        pdf = bouw_pdf()
        b = pa.bericht_uit_eml(kop, bouw_eml(message_id="<k@x>", bijlagen=[("f.pdf", pdf, "application", "pdf")]), kanaal="facturen")
        assert b is not None and b.bijlagen[0].sha256 == hashlib.sha256(pdf).hexdigest()
        assert pa.bericht_uit_eml(kop, bouw_eml(message_id="<k@x>", bijlagen=[]), kanaal="facturen") is None
        assert pa.bericht_uit_eml(kop, b"geen mail", kanaal="facturen") is None


class TestModuleSpoorUitDb:
    def test_vindt_op_message_id_en_op_bijlage_hash(self, administratie_heet_blow, opslag) -> None:
        pdf = bouw_ubl(klant="BLOW B.V.")  # UBL = deterministische toewijzing; de hash-logica is bestandsagnostisch
        mid = f"<db-{uuid.uuid4()}@lev>"
        r = verwerking.verwerk_eml(
            bouw_eml(onderwerp="Factuur BLOW B.V.", message_id=mid, bijlagen=[("f.xml", pdf, "application", "xml")]),
            actor_id=SYSTEEM_ACTOR_ID, bron="imap", kanaal="facturen_kempengroep",
        )
        toets = pa.module_spoor_uit_db()
        h = hashlib.sha256(pdf).hexdigest()
        via_mid = toets(_b("kg", mid, ("f.xml", h)), None)
        assert via_mid.intake_bericht_id == r.bericht_id and via_mid.via == "message_id"
        assert via_mid.documenten and via_mid.documenten[0][1] == "BLOW B.V."
        via_hash = toets(_b("kg", "<ander-id@lev>", ("f.xml", h)), None)
        assert via_hash.aanwezig and via_hash.via == "bijlage_sha256"
        assert not toets(_b("kg", "<nooit@lev>", ("q.pdf", "onbekend")), None).aanwezig


class TestCli:
    def test_cli_vorm_uit_het_meetrecept(self, monkeypatch, capsys) -> None:
        def nep_lees(kanaal: str, *, sinds: date, mappen):
            if kanaal == "facturen_kempengroep":
                return [_b("kg", "<a@l>", ("a.pdf", "ha")), _b("kg", "<b@l>", ("b.pdf", "hb"))], {m: 1 for m in mappen}
            return [_b("ak", "<a@l>", ("a.pdf", "ha"), map=SPAM)], {m: 1 for m in mappen}

        monkeypatch.setattr(pa, "lees_postvak", nep_lees)
        monkeypatch.setattr(pa, "module_spoor_uit_db", lambda: _geen_spoor)
        assert cli.main(["intake-postvak-audit", "--sinds", "2026-07-01", "--detail"]) == 0
        uit = capsys.readouterr().out
        assert "Uitval (a) nooit doorgestuurd: 1" in uit and "Uitval (b) aangekomen in Spam, overgeslagen: 1" in uit
        assert "ALLE bronberichten:" in uit and "Oordeel: ROOD" in uit

    def test_niet_geconfigureerd_is_exit_1(self, capsys) -> None:
        assert cli.main(["intake-postvak-audit", "--sinds", "2026-07-01"]) == 1
        assert "NIET-GECONFIGUREERD" in capsys.readouterr().err
