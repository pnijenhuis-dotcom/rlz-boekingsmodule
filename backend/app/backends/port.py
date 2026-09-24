"""Port-interface van de boekhoud-backend voor het INKOOP-boekpad (fase 1; verkoop/omzet/bank volgen
per flow — besluit 0016 §5.1 van de Odoo-verkenning).

Twee kanten:
1. `leesclient()` — het duck-typed leesobject dat de bestaande harde checks al gebruiken
   (`find_purchase_invoices_by_reference`, `get("Vendors/{id}/BankRelations")`). De RLZ-adapter geeft
   hier gewoon de RlzClient; de Odoo-adapter een facade die dezelfde vorm (RLZ-veldnamen) teruggeeft.
   Zo blijven checks.py/leverancier_iban.py ongewijzigd — pakketkennis leeft in de adapter.
2. Schrijfoperaties mét één uitkomstvorm: `boek_inkoopfactuur` en `boek_tegenboeking`; fouten komen
   ALTIJD als `BackendBoekFout` mét een leesbare reden (de motor zet 'm als boeken_mislukt / 502).

Capability-contract: een operatie die een adapter niet kent raise-t `NietOndersteund` — zichtbaar, nooit
een stille no-op."""

from __future__ import annotations

import enum
import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any, Protocol

if TYPE_CHECKING:
    from datetime import date

    from app.documenten.boekvoorstel import BoekvoorstelData
    from app.rlz.aangifte import KantToets


class Backend(enum.StrEnum):
    RLZ = "rlz"
    ODOO = "odoo"


class NietOndersteund(Exception):
    """De adapter ondersteunt deze operatie niet (capability-contract 0016 §4)."""


class BackendBoekFout(Exception):
    """De backend weigerde/faalde tijdens een schrijfactie — `str(exc)` is de leesbare reden mét
    handelingsperspectief (vertaald in de adapter)."""


@dataclass(frozen=True)
class BoekUitkomst:
    #: lokale UUID van het externe document (RLZ: het client-GUID; Odoo: odoo_uuid van de account.move)
    extern_document_id: uuid.UUID
    boekstuknummer: str | None
    #: backend-specifiek detail voor tijdlijn/audit (bv. odoo_move_id, odoo_naam, btw_override)
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class TegenboekUitkomst:
    extern_document_id: uuid.UUID
    boekstuknummer: str | None
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StornoUitkomst:
    """Uitkomst van `InkoopPort.storneer` (Corrigeren vanuit de module, Peter 21-09): actie 19 op het externe
    document van de actieve boek_cyclus. `al_concept` = het stuk stond al op concept (in de RLZ-UI gestorneerd) —
    er is dan niets geschreven; `verdwenen` = het stuk bestaat niet meer (404) — óók niets geschreven, de
    aanroeper beslist (de herstelroute is dan "Opnieuw boeken" vanuit de reconciliatie)."""

    extern_document_id: uuid.UUID
    gestorneerd: bool
    al_concept: bool = False
    verdwenen: bool = False
    detail: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class OrigineelStand:
    """Stand van het origineel vóór een tegenboeking: de storno-toets (aangifte-/lock-poort), de
    betaalstatus en of het origineel nog geboekt staat."""

    kant: KantToets
    nog_geboekt: bool
    betaald_bedrag: Decimal | None
    open_bedrag: Decimal | None
    volledig_afgeletterd: bool


class CrediteurNietGekoppeld(Exception):
    """De crediteur van het voorstel heeft in deze backend nog geen tegenhanger (Odoo: geen `res.partner`-koppeling
    in `odoo_id_koppeling`) — de leesroutes van de harde checks (IBAN-seed, duplicaatquery) kunnen dan niet draaien.
    Blok D 07-09: nooit een kale 500 uit `…/boekvoorstel/checks`, maar een leesbare BLOKKERENDE checkuitkomst mét
    handelingsperspectief (`str(exc)`); fail-closed tot de koppeling er is."""

    def __init__(self, vendor_id: uuid.UUID | str, backend_label: str = "Odoo") -> None:
        self.vendor_id = vendor_id
        self.backend_label = backend_label
        super().__init__(
            f"Crediteur nog niet gekoppeld in {backend_label} — koppel de crediteur aan een {backend_label}-partner "
            f"(stamgegevens synchroniseren ná het aanmaken van de leverancier in {backend_label}, of kies een al "
            "gekoppelde crediteur in het voorstel) en voer de checks opnieuw uit"
        )


class ToetsMislukt(Exception):
    """De reconciliatie-toets zelf kon niet uitgevoerd worden (500, 401 ná een credential-rotatie, uitgeputte
    rate-limit-retry, meerdere kandidaten in Odoo) — zegt niets over het document, alleen over de verbinding.
    De documenten-reconciliatie meldt dit als `controle_mislukt`, nooit als 'verdwenen' (les 2026-08-12)."""


@dataclass(frozen=True)
class ToetsUitkomst:
    """Stand van één (her)boeking in de boekhoud-backend voor de documenten-reconciliatie (A11/A12, 07-09).

    Backend-agnostisch: RLZ = `GET PurchaseInvoices/{herboeking-GUID}` (Status 2/3 = geboekt); Odoo =
    `account.move` via onze koppeling/marker (state posted = geboekt; een ONBEKENDE reversal = teruggedraaid —
    een eigen tegenboeking uit `odoo_document_koppeling` telt niet, dat is net als in RLZ een bewuste correctie).
    `van_toepassing=False` = er is in déze backend niets te toetsen (bv. een document dat vóór de overstap in
    Reeleezee is geboekt — boekstuk `RLZ-…` — terwijl de administratie nu op Odoo draait)."""

    backend: Backend
    van_toepassing: bool = True
    bestaat: bool = False
    geboekt: bool = False
    teruggedraaid: bool = False
    bedrag: Decimal | None = None
    boekstuknummer: str | None = None
    #: RLZ-GUID resp. Odoo move-id (als string) — de sleutel waarmee een mens het stuk in het pakket vindt
    extern_id: str | None = None
    #: RLZ `Status` (als string) resp. Odoo `state`
    extern_state: str | None = None
    #: leesbare toelichting (hol object, niet van toepassing, verdwenen)
    reden: str | None = None
    ruw: dict[str, Any] = field(default_factory=dict, compare=False)


class InkoopPort(Protocol):
    backend: Backend

    def __enter__(self) -> InkoopPort: ...

    def __exit__(self, *exc_info: object) -> None: ...

    def leesclient(self) -> Any: ...

    def boek_inkoopfactuur(
        self, *, document_id: uuid.UUID, voorstel: BoekvoorstelData, bestand: bytes, bestandsnaam: str
    ) -> BoekUitkomst: ...

    def origineel_stand(self, *, document_id: uuid.UUID, boek_cyclus: int) -> OrigineelStand: ...

    def toets_geboekt(
        self, *, document_id: uuid.UUID, boek_cyclus: int, boekstuknummer: str | None = None
    ) -> ToetsUitkomst: ...

    def toets_btw_periode(self, *, boekdatum: date) -> KantToets:
        """Aangifte-poort op een BOEKDATUM zónder document (herboeken ná een verdwenen extern document, correctie
        Peter 07-09 op A11): valt de boekdatum in een periode waarvan de btw al is aangegeven, dan is de
        voorbelasting al geclaimd en zou een herboeking 'm opnieuw claimen. RLZ = TaxDeclarations Status 2/3;
        Odoo = lock dates (tax/fiscalyear/purchase/hard). Fail-closed: niet leesbaar = `toegestaan=False`."""
        ...

    def boek_tegenboeking(
        self,
        *,
        document_id: uuid.UUID,
        voorstel: BoekvoorstelData,
        referentie: str,
        omschrijving: str,
        reden: str,
        bestand: bytes,
        bestandsnaam: str,
    ) -> TegenboekUitkomst: ...

    def storneer(self, *, document_id: uuid.UUID, boek_cyclus: int) -> StornoUitkomst:
        """Corrigeren vanuit de module (Peter 21-09, `app/documenten/corrigeren.py`): zet het externe document van
        deze boek_cyclus terug naar concept — RLZ = actie 19 op het herboeking-GUID (hetzelfde document, geen
        creditstuk; api-verkenning "Actie 19 Correct"); Odoo kent geen storno op hetzelfde document
        (besluit Peter 02-09: corrigeren = reversal) en raise-t `NietOndersteund` — de aanroeper biedt dan het
        tegenboek-pad. Idempotent: al concept = niets schrijven, 404 = `verdwenen`, elke andere backend-fout =
        `BackendBoekFout` mét leesbare reden (er is dan niets lokaal gewijzigd)."""
        ...


# --- Heractiveren (dearchiveren) — blok 3 bundelrun 24-09 ------------------------------------------------------------


class HeractiverenGeweigerd(Exception):
    """Dearchiveren geweigerd door de backend-adapter (login ontbreekt/niet van toepassing, probe rood, company
    komt niet ongewijzigd terug) — `str(exc)` is de leesbare reden, `rapport` het probe-rapport (kan leeg zijn).
    Niets is gewijzigd. Router → 422 mét bericht + rapport (zelfde vorm als OnboardingFout)."""

    def __init__(self, bericht: str, *, rapport: dict[str, str] | None = None) -> None:
        super().__init__(bericht)
        self.rapport = rapport or {}


class HeractiveerPort(Protocol):
    """Backend-bewust dearchiveren (BUG Peter 24-09, Recreatief Vastgoed Nederland: de dialoog eiste een Reeleezee-
    webservice-login voor een Odoo-administratie — besluit 0016: alle pakketverschillen in de adapter, het domein
    vertakt nooit). `heractiveer_probe` doet uitsluitend de BACKEND-kant (probe + credential/koppeling bijwerken) en
    geeft het groene probe-rapport terug; de generieke administratie-stand (actief, archiefspoor, audit) zet
    `app/beheer/service.dearchiveer_administratie`. Rood = `HeractiverenGeweigerd`, niets gewijzigd.

    Reeleezee: nieuwe webservice-login verplicht (admin-pin + rechten-probe + herprobe in de opgeslagen vorm).
    Odoo: géén login — de bestaande `OdooKoppeling` + versleutelde API-sleutel worden hergebruikt en opnieuw geprobed;
    company_id moet ongewijzigd terugkomen."""

    backend: Backend

    def heractiveer_probe(
        self,
        *,
        administratie_id: uuid.UUID,
        actor_id: uuid.UUID,
        webservice_username: str | None,
        wachtwoord: str | None,
        client: Any = None,
    ) -> dict[str, str]: ...
