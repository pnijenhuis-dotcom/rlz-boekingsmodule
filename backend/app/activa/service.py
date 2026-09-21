"""Activa fase 1 — de handelingen op de kaart en het autoboek-pad ná boeken (akkoord Peter 21-09, ontwerp §2/§7 fase 1).

- `plan_of_maak_aan`: mens zegt "Activum aanmaken" → koppeling `gepland` (document nog niet geboekt) óf direct de
  RLZ-write
  (document geboekt). `sla_over`: "Niet activeren…" mét verplichte reden → `overgeslagen`.
- `maak_aan_in_rlz`: de ENIGE RLZ-schrijver — PUT `FixedAssets/{client-GUID}` (uuid5 op document/regel/cyclus,
  idempotent)
  + terug-lezen; élke fout = koppeling `mislukt` mét reden, tijdlijn + audit, nooit een exception naar de aanroeper
  (de boeking is al geslaagd, niets mag die verhullen). Loopt BUITEN de GEBOEKT-transactie.
- `verwerk_na_boeken`: (a) geplande koppelingen aanmaken; (b) opt-in `automatisch_aanmaken_ingeschakeld` → élke
  kandidaat
  zonder koppeling wordt herkomst `automatisch` (ontbrekende afschrijvingsrekening = `mislukt`, zichtbaar — géén stille
  no-op). Aangeroepen door `doorbelasting/orkestratie.boek_document_met_doorbelasting` ná een geslaagde boeking.
- `markeer_beoordelen_bij_storno`: storno/tegenboeken → `aangemaakt` wordt `beoordelen`; het activum wordt NOOIT
  verwijderd (kernprincipe 3) — de mens beoordeelt in RLZ.

Kernprincipe 2: geen geldberekening door AI — aanschafwaarde = regelnetto, restwaarde 0, RLZ rekent de afschrijving.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.activa import categorie as cat
from app.activa import instelling as instelling_service
from app.activa import register
from app.activa import voorstel as voorstel_service
from app.activa.models import ActivumKoppeling, KoppelingHerkomst, KoppelingStatus
from app.activa.voorstel import Kandidaat, VoorstelData
from app.db.audit import record_audit_event
from app.db.models import Grootboekrekening
from app.db.session import scoped_session
from app.db.systeem_actor import SYSTEEM_ACTOR_ID
from app.documenten.models import Boekvoorstel, Document, DocumentGebeurtenis, DocumentSoort, DocumentStatus
from app.rlz.credentials import client_voor_rlz_admin_id, rlz_admin_id_voor

logger = logging.getLogger(__name__)

TIJDLIJN_SLEUTEL = "activum"
MODULE = "boekhouding"
TABEL = "activum_koppeling"


class ActivaFout(Exception):
    """Basis (router: 409)."""


class GeenKandidaat(ActivaFout):
    """De regel is geen activum-kandidaat (422)."""


class AlAangemaakt(ActivaFout):
    """Het activum staat al in RLZ (409) — terugdraaien doet een mens in RLZ."""


class OngeldigeInvoer(ActivaFout):
    """Lege reden, ongeldige termijn of onbekende afschrijvingsrekening (422)."""


def client_guid(*, document_id: uuid.UUID, regel_volgnummer: int, boek_cyclus: int) -> uuid.UUID:
    """Deterministisch client-GUID (kernprincipe 5): dezelfde regel van dezelfde boekcyclus krijgt altijd hetzelfde id
    — een herhaalde PUT muteert in RLZ i.p.v. een tweede activum te maken."""
    return uuid.uuid5(uuid.NAMESPACE_URL, f"rlz-activum:{document_id}:{regel_volgnummer}:{boek_cyclus}")


@dataclass(frozen=True)
class NaBoekenResultaat:
    aangemaakt: int = 0
    mislukt: int = 0
    gepland_verwerkt: int = 0
    automatisch: int = 0

    def als_dict(self) -> dict[str, int]:
        return {
            "aangemaakt": self.aangemaakt,
            "mislukt": self.mislukt,
            "gepland_verwerkt": self.gepland_verwerkt,
            "automatisch": self.automatisch,
        }


def _euro(bedrag: Decimal) -> str:
    return f"€ {Decimal(bedrag).quantize(Decimal('0.01'))}"


def _tijdlijn(
    session: Session, *, document: Document, actor_id: uuid.UUID, koppeling: ActivumKoppeling, tekst: str
) -> None:
    """Tijdlijnregel zónder statusovergang (mini_voorraad/doorbelasting-patroon). `reden` reist mee zodat de generieke
    systeemovergang-weergave in de tijdlijn de tekst toont."""
    session.add(
        DocumentGebeurtenis(
            id=uuid.uuid4(),
            document_id=document.id,
            van_status=document.status,
            naar_status=document.status,
            actor_id=actor_id,
            detail={
                TIJDLIJN_SLEUTEL: {
                    "koppeling_id": str(koppeling.id),
                    "status": koppeling.status,
                    "herkomst": koppeling.herkomst,
                    "regel_volgnummer": koppeling.regel_volgnummer,
                    "boek_cyclus": koppeling.boek_cyclus,
                    "omschrijving": koppeling.omschrijving,
                    "aanschafwaarde": str(koppeling.aanschafwaarde),
                    "rlz_fixed_asset_id": str(koppeling.rlz_fixed_asset_id) if koppeling.rlz_fixed_asset_id else None,
                    "rlz_receipt_number": koppeling.rlz_receipt_number,
                    "tekst": tekst,
                },
                "reden": tekst,
            },
        )
    )


def _audit(
    session: Session,
    *,
    actor_id: uuid.UUID,
    koppeling: ActivumKoppeling,
    actie: str,
    oud: dict | None = None,
    nieuw: dict | None = None,
) -> None:
    record_audit_event(
        session,
        actor_id=actor_id,
        module=MODULE,
        tabel=TABEL,
        record_id=koppeling.id,
        actie=actie,
        correlatie_id=uuid.uuid4(),
        oude_waarde=oud,
        nieuwe_waarde={
            "document_id": str(koppeling.document_id),
            "regel_volgnummer": koppeling.regel_volgnummer,
            "boek_cyclus": koppeling.boek_cyclus,
            "status": koppeling.status,
            "herkomst": koppeling.herkomst,
            **(nieuw or {}),
        },
        administratie_id=koppeling.administratie_id,
    )


def _koppeling_snapshot(k: ActivumKoppeling) -> dict:
    return {
        "status": k.status,
        "reden": k.reden,
        "rlz_fixed_asset_id": str(k.rlz_fixed_asset_id) if k.rlz_fixed_asset_id else None,
    }


# --- kaart-handelingen ---------------------------------------------------------------------------------------------


def haal_voorstel_op(*, administratie_id: uuid.UUID, document_id: uuid.UUID) -> VoorstelData:
    with scoped_session(administratie_id) as session:
        data = voorstel_service.bepaal(session, administratie_id=administratie_id, document_id=document_id)
        for k in data.kandidaten:
            if k.koppeling is not None:
                session.expunge(k.koppeling)
        for r in data.afschrijving_ledger_opties:
            session.expunge(r)
        return data


def _vul_koppeling_uit_kandidaat(
    koppeling: ActivumKoppeling,
    kandidaat: Kandidaat,
    *,
    termijn_maanden: int | None,
    afschrijving_ledger_id: uuid.UUID | None,
) -> None:
    koppeling.categorie = kandidaat.categorie
    koppeling.termijn_maanden = termijn_maanden or kandidaat.termijn_maanden
    koppeling.methode_naam = cat.methode_naam(koppeling.termijn_maanden)
    koppeling.aanschafwaarde = kandidaat.aanschafwaarde
    koppeling.restwaarde = kandidaat.restwaarde
    koppeling.aanschafdatum = kandidaat.aanschafdatum
    koppeling.omschrijving = kandidaat.omschrijving
    koppeling.balans_ledger_id = kandidaat.ledger_id
    koppeling.afschrijving_ledger_id = afschrijving_ledger_id or kandidaat.afschrijving_ledger_id


def _nieuwe_koppeling(
    session: Session, *, data: VoorstelData, kandidaat: Kandidaat, herkomst: str, actor_id: uuid.UUID
) -> ActivumKoppeling:
    koppeling = ActivumKoppeling(
        id=uuid.uuid4(),
        administratie_id=data.administratie_id,
        document_id=data.document_id,
        regel_volgnummer=kandidaat.regel_volgnummer,
        boek_cyclus=data.boek_cyclus,
        status=KoppelingStatus.GEPLAND.value,
        herkomst=herkomst,
        door=actor_id,
    )
    _vul_koppeling_uit_kandidaat(koppeling, kandidaat, termijn_maanden=None, afschrijving_ledger_id=None)
    session.add(koppeling)
    return koppeling


def _valideer_invoer(
    session: Session,
    *,
    administratie_id: uuid.UUID,
    termijn_maanden: int | None,
    afschrijving_ledger_id: uuid.UUID | None,
) -> None:
    if termijn_maanden is not None and not cat.termijn_geldig(termijn_maanden):
        raise OngeldigeInvoer(f"termijn moet 12..600 maanden zijn, veelvoud van 12 (kreeg {termijn_maanden})")
    if afschrijving_ledger_id is not None:
        rek = session.get(Grootboekrekening, (afschrijving_ledger_id, administratie_id))
        if rek is None or rek.verdwenen_uit_bron_op is not None:
            raise OngeldigeInvoer(
                f"afschrijvingsrekening {afschrijving_ledger_id} is geen rekening van deze administratie"
            )


def plan_of_maak_aan(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    regel_volgnummer: int,
    actor_id: uuid.UUID,
    afschrijving_ledger_id: uuid.UUID | None = None,
    termijn_maanden: int | None = None,
    client=None,  # noqa: ANN001 — test-seam
) -> VoorstelData:
    """ "Activum aanmaken" op de kaart. Niet geboekt → `gepland` (velden vastgelegd, aanmaken ná boeken). Geboekt →
    direct `maak_aan_in_rlz`. `overgeslagen`/`mislukt` → opnieuw plannen mag (reden leeg); `aangemaakt` → 409."""
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        data = voorstel_service.bepaal(session, administratie_id=administratie_id, document_id=document_id)
        kandidaat = data.kandidaat(regel_volgnummer)
        if kandidaat is None:
            raise GeenKandidaat(
                f"regel {regel_volgnummer} is geen activum-kandidaat (geen activarekening of onder de grens)"
            )
        _valideer_invoer(
            session,
            administratie_id=administratie_id,
            termijn_maanden=termijn_maanden,
            afschrijving_ledger_id=afschrijving_ledger_id,
        )
        document = session.get(Document, document_id)
        assert document is not None
        koppeling = kandidaat.koppeling
        oud: dict | None = None
        if koppeling is not None:
            if koppeling.status == KoppelingStatus.AANGEMAAKT.value:
                raise AlAangemaakt(
                    f"activum al aangemaakt in RLZ (nr {koppeling.rlz_receipt_number or '?'}) — "
                    "wijzigen of verwijderen doet een mens in RLZ"
                )
            oud = _koppeling_snapshot(koppeling)
            koppeling.status = KoppelingStatus.GEPLAND.value
            koppeling.herkomst = KoppelingHerkomst.MENS.value
            koppeling.reden = None
            koppeling.door = actor_id
            koppeling.gewijzigd_op = datetime.now(UTC)
            _vul_koppeling_uit_kandidaat(
                koppeling, kandidaat, termijn_maanden=termijn_maanden, afschrijving_ledger_id=afschrijving_ledger_id
            )
        else:
            koppeling = _nieuwe_koppeling(
                session, data=data, kandidaat=kandidaat, herkomst=KoppelingHerkomst.MENS.value, actor_id=actor_id
            )
            _vul_koppeling_uit_kandidaat(
                koppeling, kandidaat, termijn_maanden=termijn_maanden, afschrijving_ledger_id=afschrijving_ledger_id
            )
        session.flush()
        tekst = (
            f"Activum gepland — wordt aangemaakt ná boeken: {koppeling.omschrijving} {_euro(koppeling.aanschafwaarde)}"
            if not data.document_geboekt
            else f"Activum aanmaken gestart: {koppeling.omschrijving} {_euro(koppeling.aanschafwaarde)}"
        )
        _tijdlijn(session, document=document, actor_id=actor_id, koppeling=koppeling, tekst=tekst)
        _audit(session, actor_id=actor_id, koppeling=koppeling, actie="activum_gepland", oud=oud)
        koppeling_id = koppeling.id
        geboekt = data.document_geboekt
    if geboekt:
        maak_aan_in_rlz(
            administratie_id=administratie_id,
            document_id=document_id,
            koppeling_id=koppeling_id,
            actor_id=actor_id,
            client=client,
        )
    return haal_voorstel_op(administratie_id=administratie_id, document_id=document_id)


def sla_over(
    *, administratie_id: uuid.UUID, document_id: uuid.UUID, regel_volgnummer: int, actor_id: uuid.UUID, reden: str
) -> VoorstelData:
    """ "Niet activeren…" — verplichte reden (niets verdwijnt stil); `aangemaakt` → 409."""
    reden = (reden or "").strip()
    if not reden:
        raise OngeldigeInvoer("reden is verplicht bij overslaan")
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        data = voorstel_service.bepaal(session, administratie_id=administratie_id, document_id=document_id)
        kandidaat = data.kandidaat(regel_volgnummer)
        if kandidaat is None:
            raise GeenKandidaat(f"regel {regel_volgnummer} is geen activum-kandidaat")
        document = session.get(Document, document_id)
        assert document is not None
        koppeling = kandidaat.koppeling
        oud: dict | None = None
        if koppeling is not None:
            if koppeling.status == KoppelingStatus.AANGEMAAKT.value:
                raise AlAangemaakt(
                    "activum al aangemaakt in RLZ — overslaan kan niet meer; beoordelen doet een mens in RLZ"
                )
            oud = _koppeling_snapshot(koppeling)
        else:
            koppeling = _nieuwe_koppeling(
                session, data=data, kandidaat=kandidaat, herkomst=KoppelingHerkomst.MENS.value, actor_id=actor_id
            )
        koppeling.status = KoppelingStatus.OVERGESLAGEN.value
        koppeling.herkomst = KoppelingHerkomst.MENS.value
        koppeling.reden = reden[:1000]
        koppeling.door = actor_id
        koppeling.gewijzigd_op = datetime.now(UTC)
        session.flush()
        _tijdlijn(
            session,
            document=document,
            actor_id=actor_id,
            koppeling=koppeling,
            tekst=(
                f"Activum niet aangemaakt: {koppeling.omschrijving} {_euro(koppeling.aanschafwaarde)} — reden: {reden}"
            ),
        )
        _audit(
            session,
            actor_id=actor_id,
            koppeling=koppeling,
            actie="activum_overgeslagen",
            oud=oud,
            nieuw={"reden": reden},
        )
    return haal_voorstel_op(administratie_id=administratie_id, document_id=document_id)


# --- de RLZ-write ----------------------------------------------------------------------------------------------------


def _open_client(administratie_id: uuid.UUID):  # noqa: ANN202
    rid = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rid).for_administration(rid)


def _is_odoo(administratie_id: uuid.UUID) -> bool:
    from app.backends.registry import Backend, OnbekendeBackend, backend_voor

    try:
        return backend_voor(administratie_id) is Backend.ODOO
    except OnbekendeBackend:
        return False


def _zet_uitkomst(
    *,
    administratie_id: uuid.UUID,
    koppeling_id: uuid.UUID,
    actor_id: uuid.UUID,
    status: str,
    reden: str | None,
    rlz_id: uuid.UUID | None = None,
    receipt_number: str | None = None,
    methode: register.Methode | None = None,
    body: dict | None = None,
) -> None:
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        koppeling = session.get(ActivumKoppeling, koppeling_id)
        if koppeling is None:
            return
        document = session.get(Document, koppeling.document_id)
        oud = _koppeling_snapshot(koppeling)
        koppeling.status = status
        koppeling.reden = reden
        koppeling.gewijzigd_op = datetime.now(UTC)
        if rlz_id is not None:
            koppeling.rlz_fixed_asset_id = rlz_id
            koppeling.rlz_receipt_number = receipt_number
        if methode is not None:
            koppeling.methode_id = methode.id
            koppeling.methode_naam = methode.naam
        session.flush()
        if status == KoppelingStatus.AANGEMAAKT.value:
            tekst = (
                f"Activum aangemaakt in RLZ: {koppeling.omschrijving} {_euro(koppeling.aanschafwaarde)} "
                f"({koppeling.methode_naam or cat.methode_naam(koppeling.termijn_maanden)})"
                + (f" · nr {receipt_number}" if receipt_number else "")
                + (" · automatisch" if koppeling.herkomst == KoppelingHerkomst.AUTOMATISCH.value else "")
            )
            actie = "activum_aangemaakt"
        else:
            tekst = (
                f"Activum aanmaken mislukt: {koppeling.omschrijving} {_euro(koppeling.aanschafwaarde)} — {reden} "
                "(opnieuw aanmaken op het controlescherm)"
            )
            actie = "activum_aanmaken_mislukt"
        if document is not None:
            _tijdlijn(session, document=document, actor_id=actor_id, koppeling=koppeling, tekst=tekst)
        _audit(
            session,
            actor_id=actor_id,
            koppeling=koppeling,
            actie=actie,
            oud=oud,
            nieuw={
                "reden": reden,
                "rlz_body": body,
                "rlz_fixed_asset_id": str(rlz_id) if rlz_id else None,
                "rlz_receipt_number": receipt_number,
            },
        )


def maak_aan_in_rlz(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    koppeling_id: uuid.UUID,
    actor_id: uuid.UUID,
    client=None,  # noqa: ANN001 — test-seam (FakeBoekClient)
) -> str:
    """PUT `FixedAssets/{client-GUID}` + terug-lezen → `aangemaakt`; élke fout → `mislukt` mét reden. Geeft de
    eindstatus terug en werpt NOOIT (de aanroeper heeft zojuist geboekt)."""
    try:
        with scoped_session(administratie_id) as session:
            koppeling = session.get(ActivumKoppeling, koppeling_id)
            if koppeling is None or koppeling.document_id != document_id:
                return KoppelingStatus.MISLUKT.value
            if koppeling.status == KoppelingStatus.AANGEMAAKT.value:
                return koppeling.status  # idempotent: al gedaan
            voorstel = session.get(Boekvoorstel, document_id)
            referentie = voorstel.referentie if voorstel is not None else None
            stand = instelling_service.lees_stand(session, administratie_id)
            afschrijving_id = koppeling.afschrijving_ledger_id or stand.afschrijving_ledger_voor(koppeling.categorie)
            termijn = koppeling.termijn_maanden
            regel = koppeling.regel_volgnummer
            cyclus = koppeling.boek_cyclus
            velden = {
                "Description": koppeling.omschrijving[:200],
                "PurchaseDate": koppeling.aanschafdatum.isoformat(),
                "TotalAmountPurchase": float(koppeling.aanschafwaarde),
                "LiquidationValue": float(koppeling.restwaarde),
                "BalanceAccount": {"id": str(koppeling.balans_ledger_id)},
                "NumberOfMonths": int(termijn),
                "FirstDepreciationMonth": koppeling.aanschafdatum.month,
                "FirstDepreciationYear": koppeling.aanschafdatum.year,
                "Type": register.TYPE_FIXED,
                "InvoiceReference": (referentie or "")[:30] or None,
            }
        if _is_odoo(administratie_id):
            _zet_uitkomst(
                administratie_id=administratie_id,
                koppeling_id=koppeling_id,
                actor_id=actor_id,
                status=KoppelingStatus.MISLUKT.value,
                reden="Odoo-activaregister wordt in fase 1 nog niet geschreven (RLZ vóór Odoo, ontwerp §8.6)",
            )
            return KoppelingStatus.MISLUKT.value
        if afschrijving_id is None:
            _zet_uitkomst(
                administratie_id=administratie_id,
                koppeling_id=koppeling_id,
                actor_id=actor_id,
                status=KoppelingStatus.MISLUKT.value,
                reden="geen afschrijvingsrekening — kies op de kaart of stel in onder Instellingen › Activa",
            )
            return KoppelingStatus.MISLUKT.value
        velden["DepreciationAccount"] = {"id": str(afschrijving_id)}
        eigen_client = client is None
        if client is None:
            client = _open_client(administratie_id)
        try:
            methode = register.methode_voor_termijn(register.lees_methoden(client), termijn)
            if methode is None:
                _zet_uitkomst(
                    administratie_id=administratie_id,
                    koppeling_id=koppeling_id,
                    actor_id=actor_id,
                    status=KoppelingStatus.MISLUKT.value,
                    reden=f"geen RLZ-afschrijvingsmethode voor {termijn} maanden ({cat.methode_naam(termijn)})",
                )
                return KoppelingStatus.MISLUKT.value
            velden["DepreciationMethod"] = {"id": str(methode.id)}
            guid = client_guid(document_id=document_id, regel_volgnummer=regel, boek_cyclus=cyclus)
            client.put_fixed_asset(guid, velden)
            terug = register.lees_activum(client, guid)
        finally:
            if eigen_client:
                client.close()
        if terug is None:
            _zet_uitkomst(
                administratie_id=administratie_id,
                koppeling_id=koppeling_id,
                actor_id=actor_id,
                status=KoppelingStatus.MISLUKT.value,
                reden="RLZ gaf ná de PUT geen activum terug (404) — niets aangemaakt",
                body={**velden, "id": str(guid)},
            )
            return KoppelingStatus.MISLUKT.value
        _zet_uitkomst(
            administratie_id=administratie_id,
            koppeling_id=koppeling_id,
            actor_id=actor_id,
            status=KoppelingStatus.AANGEMAAKT.value,
            reden=None,
            rlz_id=terug.id,
            receipt_number=terug.receipt_number,
            methode=methode,
            body={**velden, "id": str(guid)},
        )
        return KoppelingStatus.AANGEMAAKT.value
    except Exception as exc:  # noqa: BLE001 — zichtbaar mislukt, nooit een exception naar de boekflow
        logger.warning("activum aanmaken mislukt (document %s, koppeling %s): %s", document_id, koppeling_id, exc)
        try:
            _zet_uitkomst(
                administratie_id=administratie_id,
                koppeling_id=koppeling_id,
                actor_id=actor_id,
                status=KoppelingStatus.MISLUKT.value,
                reden=f"{type(exc).__name__}: {exc}"[:500],
            )
        except Exception:  # noqa: BLE001
            logger.exception("activum: uitkomst 'mislukt' niet weggeschreven (koppeling %s)", koppeling_id)
        return KoppelingStatus.MISLUKT.value


# --- ná boeken (orkestratie-hook) ------------------------------------------------------------------------------------


def verwerk_na_boeken(
    *,
    administratie_id: uuid.UUID,
    document_id: uuid.UUID,
    actor_id: uuid.UUID,
    boek_cyclus: int | None = None,
    client=None,  # noqa: ANN001 — test-seam
) -> NaBoekenResultaat:
    """(a) `gepland` → aanmaken; (b) opt-in AAN → élke kandidaat zonder koppeling → aanmaken, herkomst `automatisch`.
    Opt-in UIT = alleen (a). Alleen GEBOEKTE inkoopfacturen; anders een leeg resultaat."""
    te_maken: list[uuid.UUID] = []
    gepland = automatisch = 0
    with scoped_session(administratie_id, actor_id=actor_id) as session:
        document = session.get(Document, document_id)
        if document is None or document.soort != DocumentSoort.INKOOPFACTUUR.value:
            return NaBoekenResultaat()
        if document.status != DocumentStatus.GEBOEKT:
            return NaBoekenResultaat()
        voorstel = session.get(Boekvoorstel, document_id)
        if boek_cyclus is None:
            boek_cyclus = voorstel.boek_cyclus if voorstel is not None else 0
        for k in session.scalars(
            select(ActivumKoppeling).where(
                ActivumKoppeling.document_id == document_id,
                ActivumKoppeling.boek_cyclus == boek_cyclus,
                ActivumKoppeling.status == KoppelingStatus.GEPLAND.value,
            )
        ):
            te_maken.append(k.id)
            gepland += 1
        if instelling_service.is_automatisch_ingeschakeld(session, administratie_id):
            data = voorstel_service.bepaal(session, administratie_id=administratie_id, document_id=document_id)
            for kandidaat in data.kandidaten:
                if kandidaat.koppeling is not None:
                    continue
                koppeling = _nieuwe_koppeling(
                    session,
                    data=data,
                    kandidaat=kandidaat,
                    herkomst=KoppelingHerkomst.AUTOMATISCH.value,
                    actor_id=actor_id,
                )
                session.flush()
                _tijdlijn(
                    session,
                    document=document,
                    actor_id=actor_id,
                    koppeling=koppeling,
                    tekst=(
                        f"Activum automatisch gepland (opt-in aan): {koppeling.omschrijving} "
                        f"{_euro(koppeling.aanschafwaarde)}"
                    ),
                )
                _audit(session, actor_id=actor_id, koppeling=koppeling, actie="activum_automatisch_gepland")
                te_maken.append(koppeling.id)
                automatisch += 1
    aangemaakt = mislukt = 0
    for kid in te_maken:
        status = maak_aan_in_rlz(
            administratie_id=administratie_id,
            document_id=document_id,
            koppeling_id=kid,
            actor_id=actor_id,
            client=client,
        )
        if status == KoppelingStatus.AANGEMAAKT.value:
            aangemaakt += 1
        else:
            mislukt += 1
    return NaBoekenResultaat(aangemaakt=aangemaakt, mislukt=mislukt, gepland_verwerkt=gepland, automatisch=automatisch)


# --- storno ----------------------------------------------------------------------------------------------------------


def markeer_beoordelen_bij_storno(
    session: Session, *, document_id: uuid.UUID, actor_id: uuid.UUID = SYSTEEM_ACTOR_ID, reden: str | None = None
) -> int:
    """Factuur gestorneerd/tegengeboekt → élke `aangemaakt`-koppeling van het document wordt `beoordelen` (alle cycli);
    het activum blijft in RLZ staan (nooit verwijderen). Idempotent. Geeft het aantal gemarkeerde koppelingen terug."""
    koppelingen = session.scalars(
        select(ActivumKoppeling).where(
            ActivumKoppeling.document_id == document_id, ActivumKoppeling.status == KoppelingStatus.AANGEMAAKT.value
        )
    ).all()
    if not koppelingen:
        return 0
    document = session.get(Document, document_id)
    toelichting = (reden or "boeking teruggedraaid").strip()[:500]
    for k in koppelingen:
        oud = _koppeling_snapshot(k)
        k.status = KoppelingStatus.BEOORDELEN.value
        k.reden = f"factuur gestorneerd — activum beoordelen in RLZ (niet verwijderd): {toelichting}"[:1000]
        k.gewijzigd_op = datetime.now(UTC)
        session.flush()
        if document is not None:
            _tijdlijn(
                session,
                document=document,
                actor_id=actor_id,
                koppeling=k,
                tekst=(
                    f"Factuur gestorneerd — activum beoordelen in RLZ (niet verwijderd): {k.omschrijving} "
                    f"{_euro(k.aanschafwaarde)}" + (f" · nr {k.rlz_receipt_number}" if k.rlz_receipt_number else "")
                ),
            )
        _audit(session, actor_id=actor_id, koppeling=k, actie="activum_beoordelen", oud=oud, nieuw={"reden": k.reden})
    return len(koppelingen)


def tellers(session: Session, administratie_id: uuid.UUID) -> dict[str, int]:
    from sqlalchemy import func

    uit = {s.value: 0 for s in KoppelingStatus}
    for status, n in session.execute(
        select(ActivumKoppeling.status, func.count())
        .where(ActivumKoppeling.administratie_id == administratie_id)
        .group_by(ActivumKoppeling.status)
    ):
        uit[str(status)] = int(n)
    return uit
