"""Masterkey-herversleuteling (GCP-draaiboek F1.3-continuïteit): unwrap-met-oude-provider →
wrap-met-nieuwe, over álle envelope-versleutelde rijen. Dit is de vangrail tegen de
kluis-zonder-sleutel: bij de overstap lokale masterkey → Cloud KMS (of een key-rotatie)
zou een verse key zonder deze stap de credential-store en alle TOTP-secrets onbruikbaar
maken.

Wat er herversleuteld wordt (alleen de `wrapped_data_key`-kolom — de ciphertext van het
secret zelf blijft ongemoeid, dát is precies het voordeel van envelope encryption):
- `platform.rlz_credential` (RLZ-webservice-wachtwoorden)
- `platform.totp_secret`   (TOTP-secrets kantoorgebruikers)

Expliciet NIET van toepassing: `platform.webauthn_credential` draagt uitsluitend públieke
sleutels (passkeys — het private deel leeft op het apparaat van de gebruiker) en is dus
geen envelope-data. Komt er ooit een derde envelope-tabel bij, dan bewaakt
tests/security/test_herversleutel.py::test_geen_onbekende_envelope_tabellen dat die hier
niet stil buiten valt.

Classificatie per rij is bewijs-gedreven, niet aanname-gedreven: een kandidaat-data-key
telt alleen als juist wanneer hij de ciphertext van het secret daadwerkelijk ontsleutelt
(AES-GCM-tag klopt). Daardoor is de run idempotent/hervatbaar: rijen die al met de nieuwe
provider gewrapt zijn worden herkend en overgeslagen, en een provider die stil verkeerde
bytes teruggeeft kan nooit als "gelukt" tellen."""

from __future__ import annotations

from dataclasses import dataclass, field

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from sqlalchemy.orm import Session

from app.db.models import RlzCredential, TotpSecret
from app.odoo.models import OdooKoppeling
from app.security.envelope import MasterKeyProvider

# (label, modelklasse, ciphertext-attribuut, sleutel-attribuut-voor-rapportage)
ENVELOPE_TABELLEN: tuple[tuple[str, type, str, str], ...] = (
    ("rlz_credential", RlzCredential, "wachtwoord_ciphertext", "administratie_id"),
    ("totp_secret", TotpSecret, "secret_ciphertext", "gebruiker_id"),
    # Odoo-adapter (migratie 0101): de API-key per Odoo-koppeling, zelfde envelope — rotatie neemt 'm mee.
    ("odoo_koppeling", OdooKoppeling, "api_key_ciphertext", "administratie_id"),
)


@dataclass
class TabelTelling:
    totaal: int = 0
    herversleuteld: int = 0
    al_op_nieuw: int = 0
    mislukt: int = 0
    mislukte_rijen: list[str] = field(default_factory=list)


@dataclass
class HerversleutelResultaat:
    dry_run: bool
    per_tabel: dict[str, TabelTelling]

    @property
    def geslaagd(self) -> bool:
        return all(telling.mislukt == 0 for telling in self.per_tabel.values())


def _ontsleutelt(ciphertext: bytes, data_key: bytes) -> bool:
    """Bewijs dat deze data-key bij deze ciphertext hoort: de AES-GCM-tag klopt alleen met de
    juiste key. Nooit op 'unwrap gaf geen exception' vertrouwen — een verkeerde provider kan
    zonder fout verkeerde bytes teruggeven."""
    try:
        nonce, rest = ciphertext[:12], ciphertext[12:]
        AESGCM(data_key).decrypt(nonce, rest, None)
        return True
    except Exception:
        return False


def _probeer_unwrap(provider: MasterKeyProvider, wrapped: bytes, ciphertext: bytes) -> bytes | None:
    try:
        data_key = provider.unwrap(wrapped)
    except Exception:
        return None
    return data_key if _ontsleutelt(ciphertext, data_key) else None


def herversleutel_alles(
    session: Session,
    *,
    oud: MasterKeyProvider,
    nieuw: MasterKeyProvider,
    dry_run: bool = True,
) -> HerversleutelResultaat:
    """Herversleutelt alle envelope-rijen van `oud` naar `nieuw`. Bij dry_run wordt niets
    geschreven (alleen geteld en geclassificeerd); de aanroeper commit/rollbackt zelf.
    Een mislukte rij stopt de run niet (de rest wordt gewoon geteld/verwerkt) maar zet
    `geslaagd` op False — de aanroeper hoort dan NIET te committen."""
    resultaat = HerversleutelResultaat(dry_run=dry_run, per_tabel={})
    for label, model, ciphertext_attr, sleutel_attr in ENVELOPE_TABELLEN:
        telling = TabelTelling()
        resultaat.per_tabel[label] = telling
        for rij in session.query(model).order_by(getattr(model, sleutel_attr)):
            telling.totaal += 1
            ciphertext: bytes = getattr(rij, ciphertext_attr)
            rij_id = f"{label}:{getattr(rij, sleutel_attr)}"

            data_key = _probeer_unwrap(oud, rij.wrapped_data_key, ciphertext)
            if data_key is None:
                if _probeer_unwrap(nieuw, rij.wrapped_data_key, ciphertext) is not None:
                    telling.al_op_nieuw += 1  # eerdere (afgebroken) run — hervatbaar, geen fout
                    continue
                telling.mislukt += 1
                telling.mislukte_rijen.append(rij_id)
                continue

            nieuw_wrapped = nieuw.wrap(data_key)
            # Directe verificatie vóór het wegschrijven: de nieuwe wrap moet terug te draaien
            # zijn én dezelfde data-key opleveren — anders zou een kapotte nieuwe provider
            # precies de kluis-zonder-sleutel creëren die dit script moet voorkomen.
            if _probeer_unwrap(nieuw, nieuw_wrapped, ciphertext) != data_key:
                telling.mislukt += 1
                telling.mislukte_rijen.append(rij_id)
                continue
            if not dry_run:
                rij.wrapped_data_key = nieuw_wrapped
            telling.herversleuteld += 1
    if not dry_run:
        session.flush()
    return resultaat
