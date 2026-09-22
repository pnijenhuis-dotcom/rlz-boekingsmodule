"""Identiteit per administratie (blok A opdracht 16-09, fundament voor de IC-afleiding).

Bron per backend (STAP-0 16-09, lees-only):
- RLZ: `AdministrationSettings` (één rij per administratie) — `CompanyName`, `ChamberOfCommerceNumber`,
  `StandardBusinessIdentification` (SBI). RLZ kent GÉÉN btw-nummer van de administratie zelf; `Administrations`
  draagt alleen Name + DunsNumber, dus dáár staat niets bruikbaars.
- Odoo: `res.company` — `name`, `vat`, `company_registry` (KvK).

`naam_norm` is de ENE naam-normalisatie voor de hele intercompany-module (relaties én RC-koppelingen lezen 'm van hier):
lowercase, rechtsvorm weg (gepunte vorm b.v./n.v./c.v./v.o.f. overal als los woord; kale vorm bv/nv/cv/vof/gmbh/ltd
alleen als laatste woord — "Cv-ketel Service" blijft intact), alle leestekens naar spatie, witruimte samengevouwen.
"Holding", "Beheer", "Groep" e.d. worden BEWUST NIET gestript: dat zijn onderscheidende naamdelen ("Kempen Beheer" ≠
"Kempen Facilities"). "Kempen Facilities B.V." → "kempen facilities"; "Rekening-courant Kempen B.V." → "rekening courant
kempen".

`sync_identiteiten` leest per actieve administratie de bron en upsert `administratie_identiteit`; een rij met bron
'mens' (Beheerder heeft de identiteit zelf gezet) en de kolom `afkortingen` worden NOOIT overschreven. Eén kapotte
administratie (geen credential, RLZ-fout) stopt de rest niet — de uitkomst per administratie is zichtbaar (KP 4/7)."""

from __future__ import annotations

import re
import uuid
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select

from app.backends.registry import Backend, backend_voor
from app.db.models import Administratie
from app.db.session import scoped_session
from app.extractie.btw_nummer import normaliseer_btw_nummer, normaliseer_kvk_nummer
from app.intercompany.models import AdministratieIdentiteit
from app.rlz.credentials import GeenRlzCredentials, client_voor_rlz_admin_id, rlz_admin_id_voor

# Rechtsvormen: de GEPUNTE vorm (b.v., n.v., c.v., v.o.f., b.v.b.a.) is overal in de naam een rechtsvorm; de kale vorm
# (bv, nv, cv, vof, gmbh, ltd) alleen als LAATSTE woord — "Cv-ketel Service" en "NV Bouw" blijven zo intact.
_RECHTSVORMEN_GEPUNT = re.compile(
    r"(?<![a-z0-9])(b\.v\.|n\.v\.|v\.o\.f\.|c\.v\.|b\.v\.b\.a\.|s\.a\.)(?![a-z0-9])", re.IGNORECASE
)
_RECHTSVORMEN_EIND = re.compile(r"(?<![a-z0-9])(bv|nv|vof|cv|bvba|gmbh|ltd|inc|sa)\.?\s*$", re.IGNORECASE)
_LEESTEKENS = re.compile(r"[^a-z0-9]+")


def naam_norm(tekst: str | None) -> str:
    """Genormaliseerde naam (zie module-doc). Leeg/None → ''."""
    if not tekst:
        return ""
    laag = tekst.lower().strip()
    laag = _RECHTSVORMEN_GEPUNT.sub(" ", laag)
    laag = _RECHTSVORMEN_EIND.sub(" ", laag.strip())
    laag = _LEESTEKENS.sub(" ", laag)
    return " ".join(laag.split())


def btw_norm(ruw: str | None) -> str | None:
    """Btw-nummer in dezelfde vorm als `crediteur_kenmerk` (hoofdletters, zonder spaties/punten); leeg = None."""
    if not ruw:
        return None
    return normaliseer_btw_nummer(ruw) or None


@dataclass(frozen=True)
class Identiteit:
    kvk: str | None
    btw: str | None
    naam: str | None
    naam_norm: str
    sbi: str | None
    bron: str  # 'rlz' | 'odoo'
    # 22-09 (BUG Peter, casus VGG / Lacy Lion): RLZ `AdministrationSettings.EnableTaxReporting` (STAP-0 22-09: VGG
    # false, Kempen Facilities/Rubicon/Arvum true) — het btw-status-signaal voor `app/beheer/btw_plichtig.py`.
    # None = niet leesbaar / Odoo.
    enable_tax_reporting: bool | None = None


@dataclass(frozen=True)
class IdentiteitUitkomst:
    administratie_id: uuid.UUID
    administratie_naam: str
    stand: str  # 'gelezen' | 'overgeslagen' | 'fout' | 'mens'
    identiteit: Identiteit | None = None
    melding: str | None = None


def lees_identiteit_rlz(client: Any) -> Identiteit:
    """`AdministrationSettings?$top=1` — één rij; ontbrekende velden = None (nooit raden)."""
    antwoord = client.get("AdministrationSettings", params={"$top": "1"})
    rijen = antwoord.get("value", []) if isinstance(antwoord, dict) else []
    rij = rijen[0] if rijen else (antwoord if isinstance(antwoord, dict) and "CompanyName" in antwoord else {})
    naam = " ".join(str(rij.get("CompanyName") or "").split()) or None
    sbi = str(rij.get("StandardBusinessIdentification") or "").strip() or None
    etr = rij.get("EnableTaxReporting")
    return Identiteit(
        kvk=normaliseer_kvk_nummer(str(rij.get("ChamberOfCommerceNumber") or "")),
        btw=None,
        naam=naam,
        naam_norm=naam_norm(naam),
        sbi=sbi,
        bron="rlz",
        enable_tax_reporting=bool(etr) if isinstance(etr, bool) else None,
    )


def lees_identiteit_odoo(client: Any) -> Identiteit:
    """`res.company` van de gebonden company: name/vat/company_registry."""
    rij = client.read_een("res.company", client.company_id, ["name", "vat", "company_registry"]) or {}
    naam = " ".join(str(rij.get("name") or "").split()) or None
    return Identiteit(
        kvk=normaliseer_kvk_nummer(str(rij.get("company_registry") or "")),
        btw=btw_norm(str(rij.get("vat") or "") or None),
        naam=naam,
        naam_norm=naam_norm(naam),
        sbi=None,
        bron="odoo",
    )


def rlz_client_voor(administratie_id: uuid.UUID) -> Any:
    """RLZ-leesclient per administratie (credential-store/.env) — de ENE monkeypatch-plek voor tests
    (`app.intercompany.identiteit.client_voor_rlz_admin_id`). Aanroeper sluit 'm."""
    rid = rlz_admin_id_voor(administratie_id)
    return client_voor_rlz_admin_id(rid).for_administration(rid)


def odoo_client_voor_lezen(administratie_id: uuid.UUID) -> Any:
    from app.odoo.credentials import odoo_client_voor

    return odoo_client_voor(administratie_id, read_only=True)


def lees_identiteit(administratie_id: uuid.UUID) -> Identiteit:
    """Identiteit uit de bron van deze administratie (backend-agnostisch). Exceptions reizen door naar de aanroeper."""
    backend = backend_voor(administratie_id)
    if backend is Backend.ODOO:
        client = odoo_client_voor_lezen(administratie_id)
        try:
            return lees_identiteit_odoo(client)
        finally:
            client.close()
    client = rlz_client_voor(administratie_id)
    try:
        return lees_identiteit_rlz(client)
    finally:
        client.close()


def actieve_administraties(administratie_ids: Iterable[uuid.UUID] | None = None) -> list[tuple[uuid.UUID, str]]:
    with scoped_session(None) as session:
        q = select(Administratie.id, Administratie.naam).where(Administratie.actief.is_(True))
        if administratie_ids is not None:
            q = q.where(Administratie.id.in_(list(administratie_ids)))
        return [(r[0], r[1]) for r in session.execute(q.order_by(Administratie.naam)).all()]


def upsert_identiteit(administratie_id: uuid.UUID, identiteit: Identiteit) -> str:
    """Schrijft kvk/btw/naam/naam_norm/sbi/gelezen_op; `afkortingen` blijft staan; een 'mens'-rij wordt niet
    aangeraakt (stand 'mens'). Geeft de stand terug."""
    with scoped_session(None) as session:
        rij = session.get(AdministratieIdentiteit, administratie_id)
        if rij is None:
            rij = AdministratieIdentiteit(administratie_id=administratie_id, bron=identiteit.bron)
            session.add(rij)
        elif rij.bron == "mens":
            return "mens"
        rij.kvk = identiteit.kvk
        rij.btw = identiteit.btw
        rij.naam = identiteit.naam
        rij.naam_norm = identiteit.naam_norm or None
        rij.sbi = identiteit.sbi
        rij.bron = identiteit.bron
        rij.gelezen_op = datetime.now(UTC)
        return "gelezen"


def sync_identiteiten(
    administratie_ids: Iterable[uuid.UUID] | None = None,
    *,
    lezer: Callable[[uuid.UUID], Identiteit] | None = None,
) -> list[IdentiteitUitkomst]:
    """Per actieve administratie de identiteit lezen en opslaan. Geen credential = 'overgeslagen' (zichtbaar, geen
    fout); elke andere fout = 'fout' mét melding; nooit stop."""
    lees = lezer or lees_identiteit
    uitkomsten: list[IdentiteitUitkomst] = []
    for aid, naam in actieve_administraties(administratie_ids):
        try:
            identiteit = lees(aid)
        except GeenRlzCredentials as exc:
            uitkomsten.append(IdentiteitUitkomst(aid, naam, "overgeslagen", melding=f"geen credential: {exc}"))
            continue
        except Exception as exc:  # noqa: BLE001 — bewust breed: één kapotte administratie mag de rest niet raken
            uitkomsten.append(IdentiteitUitkomst(aid, naam, "fout", melding=f"{type(exc).__name__}: {exc}"))
            continue
        stand = upsert_identiteit(aid, identiteit)
        melding = None
        # 22-09: btw-status-signaal uit dezelfde AdministrationSettings-call — nooit een stop van de identiteit-sync.
        try:
            from app.beheer import btw_plichtig
            from app.db.systeem_actor import SYSTEEM_ACTOR_ID

            btw_stand = btw_plichtig.volg_rlz_signaal(
                administratie_id=aid, enable_tax_reporting=identiteit.enable_tax_reporting, actor_id=SYSTEEM_ACTOR_ID
            )
            if btw_stand == "bevestigd_rlz":
                melding = "btw-plichtig bevestigd uit RLZ (EnableTaxReporting)"
            elif btw_stand == "signaal_opgeslagen" and identiteit.enable_tax_reporting is False:
                melding = "RLZ EnableTaxReporting=false — kandidaat 'niet btw-plichtig', bevestig de btw-status"
        except Exception as exc:  # noqa: BLE001 — zichtbaar, nooit stop
            melding = f"btw-status-signaal niet verwerkt: {type(exc).__name__}: {exc}"
        uitkomsten.append(IdentiteitUitkomst(aid, naam, stand, identiteit=identiteit, melding=melding))
    return uitkomsten


def alle_identiteiten() -> dict[uuid.UUID, AdministratieIdentiteit]:
    """Alle opgeslagen identiteiten (gedetacheerd gebruik: alleen kolomwaarden lezen)."""
    with scoped_session(None) as session:
        rijen = list(session.scalars(select(AdministratieIdentiteit)))
        session.expunge_all()
        return {r.administratie_id: r for r in rijen}
