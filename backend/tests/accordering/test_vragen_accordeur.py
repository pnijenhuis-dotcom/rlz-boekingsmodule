"""Vragen-dialoog naar de klant-accordeur (blok B5 gecombineerde run 26-08, migratie 0079):
- een vraag aan de accordeur op een document dat bij de klant ligt verandert de status NIET;
- de accordeur ziet UITSLUITEND vragen die aan hem gericht zijn (intern kantooroverleg nooit);
- antwoorden = append-only bericht, beurt wisselt naar de vraagsteller; afgehandeld = alleen de
  vraagsteller (bestaande 403-regel);
- het akkoord blijft mogelijk; ná het laatste akkoord wacht het BOEKEN zichtbaar op de vraag;
- de beurt-wissel naar de accordeur stuurt push-anders-mail, idempotent per beurt, stille uren.
"""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from sqlalchemy import Engine

from app.accordering import service
from app.berichten import vraag_meldingen
from app.berichten.models import HerinneringKanaal, HerinneringStatus
from app.berichten.verzending import VerzendUitkomst
from app.db.session import scoped_session
from app.documenten import vragen
from app.documenten.models import Vraag
from tests.accordering.conftest import document_status, zet_schema
from tests.accordering.test_service import _laag


def _stel_vraag_aan(administratie_id, document_id, vraagsteller, accordeur, tekst="Is dit meerwerk door u opgedragen?"):
    return vragen.stel_vraag(
        administratie_id=administratie_id,
        document_id=document_id,
        actor_id=vraagsteller,
        vraag_tekst=tekst,
        toegewezen_aan=accordeur,
    )


@pytest.fixture
def geen_meldingen(monkeypatch: pytest.MonkeyPatch) -> list[dict]:
    """Vangt de push-anders-mail-verzending op (geen echte kanalen in de suite)."""
    verzonden: list[dict] = []

    def nep(gebruiker, *, onderwerp, pushtekst, mailtekst, url, extra_payload=None):
        verzonden.append({"aan": gebruiker.id, "onderwerp": onderwerp, "url": url})
        return VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.PUSH, {"subscripties": 1}, 0)

    monkeypatch.setattr(vraag_meldingen.verzending, "verstuur_push_anders_mail", nep)
    # buiten de stille uren toetsen, onafhankelijk van het moment waarop de suite draait
    monkeypatch.setattr(vraag_meldingen, "in_stille_uren", lambda moment=None: False)
    return verzonden


class TestVraagAanAccordeur:
    def test_vraag_op_document_bij_klant_laat_status_staan_en_is_alleen_voor_die_accordeur(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        accordeur_2: uuid.UUID,
        admin_engine: Engine,
        geen_meldingen: list[dict],
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
        )
        vraag = _stel_vraag_aan(administratie_id, klaar_document, gescoopte_gebruiker, accordeur_1)
        assert vraag.status_voor_vraag == "ter_accordering"
        assert document_status(admin_engine, klaar_document) == "ter_accordering"  # géén overgang
        assert vraag.aan_de_beurt == accordeur_1

        # zichtbaarheid: alleen accordeur_1, nooit accordeur_2
        mijn = vragen.vragen_aan_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])
        assert [a.vraag.id for a in mijn] == [vraag.id] and mijn[0].ik_ben_aan_de_beurt
        assert mijn[0].leverancier_naam == "Energieleverancier B.V."
        assert vragen.vragen_aan_accordeur(actor_id=accordeur_2, administratie_ids=[administratie_id]) == []
        # wachtrij-kaart draagt de thread (alleen voor accordeur_1)
        item = service.wachtrij_voor_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])[0]
        assert item.vraag is not None and item.vraag.id == vraag.id
        # melding aan de accordeur direct verstuurd, deep-link naar de vraag
        assert geen_meldingen == [{"aan": accordeur_1, "onderwerp": "Vraag van het kantoor over een factuur", "url": f"/accordeur?vraag={vraag.id}"}]

        # antwoorden: alleen de geadresseerde; beurt wisselt terug naar de vraagsteller
        with pytest.raises(vragen.VraagNietAanDezeAccordeur):
            vragen.plaats_bericht_als_accordeur(
                administratie_id=administratie_id, vraag_id=vraag.id, actor_id=accordeur_2, tekst="Ik ben het niet"
            )
        na = vragen.plaats_bericht_als_accordeur(
            administratie_id=administratie_id, vraag_id=vraag.id, actor_id=accordeur_1, tekst="Ja, door mij opgedragen."
        )
        assert [b.auteur_id for b in na.berichten] == [accordeur_1] and na.aan_de_beurt == gescoopte_gebruiker
        assert not vragen.vragen_aan_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])[0].ik_ben_aan_de_beurt
        # afgehandeld: nooit door de accordeur
        with pytest.raises(vragen.AlleenVraagstellerMagAfhandelen):
            vragen.handel_vraag_af(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=accordeur_1)
        # kantoor reageert → beurt terug naar accordeur → tweede melding ("reactie")
        vragen.plaats_bericht(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=gescoopte_gebruiker, tekst="Dank!")
        assert len(geen_meldingen) == 2 and geen_meldingen[1]["onderwerp"] == "Reactie van het kantoor op uw vraag"
        # vraagsteller handelt af: document blijft gewoon bij de klant (er was nooit een overgang)
        vragen.handel_vraag_af(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=gescoopte_gebruiker)
        assert document_status(admin_engine, klaar_document) == "ter_accordering"
        assert vragen.vragen_aan_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id]) == []

    def test_intern_kantooroverleg_lekt_nooit_naar_de_accordeur(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        geen_meldingen: list[dict],
    ) -> None:
        # interne vraag (toegewezen aan de Beheerder) op een document in de kantoorbak
        vraag = vragen.stel_vraag(
            administratie_id=administratie_id,
            document_id=klaar_document,
            actor_id=gescoopte_gebruiker,
            vraag_tekst="Intern: klopt de GB?",
            toegewezen_aan=beheerder_id,
        )
        assert vragen.vragen_aan_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id]) == []
        with pytest.raises(vragen.VraagNietAanDezeAccordeur):
            vragen.plaats_bericht_als_accordeur(
                administratie_id=administratie_id, vraag_id=vraag.id, actor_id=accordeur_1, tekst="mag niet"
            )
        assert geen_meldingen == []  # geen accordeur-melding voor intern overleg

    def test_akkoord_blijft_mogelijk_boeken_wacht_op_de_open_vraag(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        boeken_aan: None,
        geen_meldingen: list[dict],
    ) -> None:
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
        )
        vraag = _stel_vraag_aan(administratie_id, klaar_document, gescoopte_gebruiker, accordeur_1)

        resultaat = service.geef_akkoord(administratie_id=administratie_id, document_id=klaar_document, actor_id=accordeur_1)
        assert resultaat.alles_akkoord is True and resultaat.geboekt is False
        assert resultaat.boek_fout is not None and "open vraag" in resultaat.boek_fout
        # document zichtbaar op vraag_open, herkomst omgezet naar klaar_om_te_boeken
        assert document_status(admin_engine, klaar_document) == "vraag_open"
        with scoped_session(administratie_id) as session:
            rij = session.get(Vraag, vraag.id)
            assert rij.status_voor_vraag == "klaar_om_te_boeken"
        # vraagsteller handelt af → terug naar klaar_om_te_boeken (kantoor boekt via de normale route)
        vragen.handel_vraag_af(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=gescoopte_gebruiker)
        assert document_status(admin_engine, klaar_document) == "klaar_om_te_boeken"

    def test_vraag_over_geboekt_document_zonder_overgang(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        admin_engine: Engine,
        boeken_aan: None,
        monkeypatch: pytest.MonkeyPatch,
        geen_meldingen: list[dict],
    ) -> None:
        from app.documenten import boeken
        from tests.documenten.fake_rlz_client import FakeBoekClient

        monkeypatch.setattr(boeken, "client_voor_rlz_admin_id", lambda rlz_admin_id: FakeBoekClient())
        boeken.boek_document(administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker)
        assert document_status(admin_engine, klaar_document) == "geboekt"
        vraag = _stel_vraag_aan(administratie_id, klaar_document, gescoopte_gebruiker, accordeur_1, "Klopt het werkadres?")
        assert document_status(admin_engine, klaar_document) == "geboekt"
        mijn = vragen.vragen_aan_accordeur(actor_id=accordeur_1, administratie_ids=[administratie_id])
        assert [a.vraag.id for a in mijn] == [vraag.id] and mijn[0].vraag.document_status.value == "geboekt"
        vragen.trek_vraag_in(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=gescoopte_gebruiker, reden="vergissing")
        assert document_status(admin_engine, klaar_document) == "geboekt"


class TestVraagMeldingen:
    def test_idempotent_per_beurt_en_stille_uren(
        self,
        klaar_document: uuid.UUID,
        administratie_id: uuid.UUID,
        beheerder_id: uuid.UUID,
        gescoopte_gebruiker: uuid.UUID,
        accordeur_1: uuid.UUID,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        verzonden: list[uuid.UUID] = []

        def nep(gebruiker, **_kw):
            verzonden.append(gebruiker.id)
            return VerzendUitkomst(HerinneringStatus.VERZONDEN, HerinneringKanaal.E_MAIL, None, 0)

        monkeypatch.setattr(vraag_meldingen.verzending, "verstuur_push_anders_mail", nep)
        # stille uren: de directe melding uit stel_vraag doet niets …
        monkeypatch.setattr(vraag_meldingen, "in_stille_uren", lambda moment=None: True)
        zet_schema(administratie_id=administratie_id, beheerder_id=beheerder_id, lagen=[_laag(1, accordeur_1)])
        service.bied_ter_accordering_aan(
            administratie_id=administratie_id, document_id=klaar_document, actor_id=gescoopte_gebruiker, actor_rol="boekhouding"
        )
        vraag = _stel_vraag_aan(administratie_id, klaar_document, gescoopte_gebruiker, accordeur_1)
        assert verzonden == []
        assert vraag_meldingen.verstuur_vraag_meldingen().stille_uren is True
        # … de job buiten de stille uren verstuurt precies één keer
        monkeypatch.setattr(vraag_meldingen, "in_stille_uren", lambda moment=None: False)
        rapport = vraag_meldingen.verstuur_vraag_meldingen()
        assert rapport.kandidaten == 1 and rapport.verzonden_mail == 1 and verzonden == [accordeur_1]
        rapport2 = vraag_meldingen.verstuur_vraag_meldingen()
        assert rapport2.kandidaten == 0 and verzonden == [accordeur_1]
        with scoped_session(administratie_id) as session:
            rij = session.get(Vraag, vraag.id)
            assert rij.accordeur_gemeld_op is not None and rij.accordeur_gemeld_op >= rij.aan_de_beurt_sinds
        # accordeur antwoordt → beurt bij kantoor: geen melding; kantoor reageert → nieuwe beurt → één melding
        vragen.plaats_bericht_als_accordeur(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=accordeur_1, tekst="ok")
        assert vraag_meldingen.verstuur_vraag_meldingen().kandidaten == 0
        vragen.plaats_bericht(administratie_id=administratie_id, vraag_id=vraag.id, actor_id=gescoopte_gebruiker, tekst="dank")
        assert verzonden == [accordeur_1, accordeur_1]
        assert datetime.now(UTC) is not None
