"""Resolutie van het secret van een INKOMEND machine-naar-machine-kanaal (koppelvlak vastgoed →
RLZ). Eén kanaal = één eigen secret (compartimentering: compromittering van het ene kanaal
raakt het andere niet — config.py), en buiten dev nooit een stil fallback: ontbreekt het secret
in productie, dan faalt de resolutie hard en antwoordt het endpoint zichtbaar 503
(`niet_geconfigureerd`). Gedeeld door het projectaanvraag- (§5) en het registersync-koppelvlak
(§8) zodat beide exact dezelfde bewaking hebben."""

from __future__ import annotations

from collections.abc import Mapping

DEV_ENVIRONMENTS = ("dev", "local")


def resolve_inkomend_kanaal_secret(env: Mapping[str, str], *, env_var: str, dev_fallback: str) -> str:
    """Zelfde bewaking als het webhook-/JWT-secret: geen stil fallback buiten dev."""
    secret = env.get(env_var)
    if secret:
        return secret
    environment = env.get("ENVIRONMENT", "dev")
    if environment not in DEV_ENVIRONMENTS:
        raise RuntimeError(
            f"{env_var} ontbreekt en ENVIRONMENT={environment!r} is geen dev-omgeving "
            f"({', '.join(DEV_ENVIRONMENTS)}). Zet het secret (Cloud Run: via Secret Manager) — "
            "zonder eigen kanaal-secret kan het koppelvlak niet verifiëren."
        )
    return dev_fallback
