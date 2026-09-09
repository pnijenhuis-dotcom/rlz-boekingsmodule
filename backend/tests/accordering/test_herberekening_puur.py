"""Pure regel voor het herberekenen van een lopende accorderingsronde (bundel 09-09 blok 2, besluit Peter 08-09 —
herziet "GECOMBINEERDE RUN 01-09" blok A beslispunt 2). Geen database: alle overgangen uit de opdracht (2c) als
tabel-tests op `herberekening.herbereken`."""

from __future__ import annotations

import uuid
from decimal import Decimal

from app.accordering.herberekening import LaagSpec, StapStand, herbereken

A = uuid.UUID("aaaaaaaa-0000-4000-8000-000000000001")
B = uuid.UUID("bbbbbbbb-0000-4000-8000-000000000002")
C = uuid.UUID("cccccccc-0000-4000-8000-000000000003")
BEDRAG = Decimal("121.00")


def _stap(volgnummer: int, accordeur: uuid.UUID, *, akkoord: bool = False, drempel: str | None = None, vereist=True):
    return StapStand(
        volgnummer=volgnummer,
        accordeur_gebruiker_id=accordeur,
        bedrag_drempel=Decimal(drempel) if drempel else None,
        vereist=vereist,
        besluit="akkoord" if akkoord else None,
    )


def _laag(volgnummer: int, accordeur: uuid.UUID, drempel: str | None = None) -> LaagSpec:
    return LaagSpec(
        volgnummer=volgnummer, accordeur_gebruiker_id=accordeur, bedrag_drempel=Decimal(drempel) if drempel else None
    )


class TestAkkoordBehouden:
    def test_zelfde_laag_behoudt_het_akkoord_en_vraagt_de_nieuwe_laag(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A), _laag(2, C)], BEDRAG)
        assert not h.ronde_vervalt
        assert h.akkoorden_gegeven == 1 and h.akkoorden_behouden == 1 and h.akkoorden_vervallen == 0
        assert [(s.volgnummer, s.accordeur_gebruiker_id, s.akkoord_behouden, s.bron_index) for s in h.stappen] == [
            (1, A, True, 0),
            (2, C, False, None),
        ]
        assert h.opnieuw_aangevraagd == (2,)
        assert h.vervallen_indices == (1,)  # de onbesliste stap van B past nergens meer
        assert h.alles_akkoord is False

    def test_eerdere_laag_behoudt_het_akkoord(self) -> None:
        # B gaf akkoord in laag 2 en komt nu in laag 1 (eerder) — blijft geldig; A verhuist van laag 1 naar laag 2
        # (LATER) — zijn akkoord vervalt en laag 2 wordt opnieuw aangevraagd.
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B, akkoord=True)], [_laag(1, B), _laag(2, A)], BEDRAG)
        assert h.akkoorden_behouden == 1
        assert [(s.accordeur_gebruiker_id, s.akkoord_behouden) for s in h.stappen] == [(B, True), (A, False)]
        assert h.opnieuw_aangevraagd == (2,)

    def test_positie_telt_niet_het_ruwe_volgnummer(self) -> None:
        # Zelfde positie (eerste laag) ondanks volgnummer 1 → 10.
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(10, A), _laag(20, B)], BEDRAG)
        assert h.akkoorden_behouden == 1 and h.stappen[0].volgnummer == 10 and h.stappen[0].akkoord_behouden

    def test_onbesliste_stap_wordt_hergebruikt(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A), _laag(2, B, "50")], BEDRAG)
        assert h.stappen[1].bron_index == 1 and h.stappen[1].akkoord_behouden is False
        assert h.vervallen_indices == ()


class TestLaagOpnieuwAangevraagd:
    def test_nieuwe_laag_tussenin_wordt_aangevraagd(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A), _laag(2, C), _laag(3, B)], BEDRAG)
        assert h.akkoorden_behouden == 1
        assert h.opnieuw_aangevraagd == (2, 3)
        assert h.stappen[2].bron_index == 1  # B's onbesliste stap volgt mee naar laag 3

    def test_accordeur_uit_laag_gehaald_akkoord_van_de_ander_blijft(self) -> None:
        h = herbereken(
            [_stap(1, A, akkoord=True), _stap(2, B, akkoord=True), _stap(3, C)], [_laag(1, A), _laag(2, C)], BEDRAG
        )
        assert h.akkoorden_behouden == 1 and h.akkoorden_vervallen == 1
        assert h.opnieuw_aangevraagd == (2,)
        assert h.stappen[1].bron_index == 2  # C's onbesliste stap hergebruikt
        assert h.vervallen_indices == (1,)  # B's akkoord vervalt (B staat niet meer in de lagen)


class TestDrempelwijziging:
    def test_strenger_maar_nog_van_toepassing_behoudt(self) -> None:
        # Drempel 0 → 100 op € 121: laag geldt nog → akkoord blijft.
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A, "100"), _laag(2, B)], BEDRAG)
        assert h.stappen[0].akkoord_behouden and h.stappen[0].vereist

    def test_strenger_en_niet_meer_van_toepassing_vraagt_niets_en_akkoord_vervalt(self) -> None:
        # Drempel → 1000 op € 121: laag 1 niet vereist; A's akkoord is nergens meer nodig → vervalt (telling),
        # de ronde loopt door op laag 2 (B) — niets verloren voor de klant, B was al aan de beurt.
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A, "1000"), _laag(2, B)], BEDRAG)
        assert h.stappen[0].vereist is False and h.stappen[0].akkoord_behouden is False
        assert h.akkoorden_behouden == 0 and h.akkoorden_gegeven == 1
        # Geen enkel gegeven akkoord past meer → de opdracht-regel: ronde vervalt.
        assert h.ronde_vervalt is True

    def test_akkoord_telt_mee_in_een_andere_passende_laag(self) -> None:
        # A's laag 1 valt weg door de drempel, maar A staat ook in laag 2 zonder drempel → akkoord blijft dáár
        # (laag 2 is nu de EERSTE vereiste laag: positie telt over vereiste lagen).
        h = herbereken(
            [_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A, "1000"), _laag(2, A), _laag(3, B)], BEDRAG
        )
        assert h.stappen[0].vereist is False
        assert h.stappen[1].akkoord_behouden is True and h.stappen[1].bron_index == 0
        assert h.ronde_vervalt is False and h.opnieuw_aangevraagd == (3,)

    def test_soepeler_drempel_maakt_een_laag_vereist_en_vraagt_die_aan(self) -> None:
        h = herbereken(
            [_stap(1, A, akkoord=True), _stap(2, B, drempel="1000", vereist=False)],
            [_laag(1, A), _laag(2, B, "100")],
            BEDRAG,
        )
        assert h.stappen[1].vereist is True and h.stappen[1].bron_index == 1
        assert h.opnieuw_aangevraagd == (2,) and h.alles_akkoord is False

    def test_onbekend_bedrag_is_vereist_fail_closed(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True)], [_laag(1, A), _laag(2, B, "1000000")], None)
        assert h.stappen[1].vereist is True and h.opnieuw_aangevraagd == (2,)


class TestAfrondingEnVervallen:
    def test_laatste_laag_verwijderd_alles_gedekt(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A)], BEDRAG)
        assert h.alles_akkoord is True and h.ronde_vervalt is False
        assert h.opnieuw_aangevraagd == () and h.vervallen_indices == (1,)

    def test_laatste_laag_door_drempel_leeg_alles_gedekt(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, A), _laag(2, B, "1000")], BEDRAG)
        assert h.alles_akkoord is True and h.stappen[1].vereist is False

    def test_accordeur_volledig_verwijderd_als_enige_akkoord_vervalt_de_ronde(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B)], [_laag(1, C), _laag(2, B)], BEDRAG)
        assert h.ronde_vervalt is True and h.akkoorden_behouden == 0

    def test_alle_akkoorden_ongeldig_vervalt(self) -> None:
        h = herbereken([_stap(1, A, akkoord=True), _stap(2, B, akkoord=True), _stap(3, C)], [_laag(1, C)], BEDRAG)
        assert h.ronde_vervalt is True

    def test_zonder_gegeven_akkoord_wordt_herberekend_nooit_vervallen(self) -> None:
        # Niets te verliezen: de ronde loopt door met de nieuwe accordeur (geen kantoor-actie nodig).
        h = herbereken([_stap(1, A)], [_laag(1, B)], BEDRAG)
        assert h.ronde_vervalt is False and h.opnieuw_aangevraagd == (1,) and h.vervallen_indices == (0,)

    def test_geen_lagen_meer_vervalt_altijd(self) -> None:
        assert herbereken([_stap(1, A, akkoord=True)], [], BEDRAG).ronde_vervalt is True
        assert herbereken([_stap(1, A)], [], BEDRAG).ronde_vervalt is True

    def test_deterministisch(self) -> None:
        oud = [_stap(1, A, akkoord=True), _stap(2, B)]
        nieuw = [_laag(2, C), _laag(1, A)]
        assert herbereken(oud, nieuw, BEDRAG) == herbereken(oud, nieuw, BEDRAG)
