"""Boekhoud-backend-port (Platform-besluit 0016): het domein praat tegen de port, de registry kiest de
adapter op `administratie.boekhoud_backend`. Dit pakket is de ENIGE plek waar op de backend-sleutel
vertakt wordt (guardrail 0016 — `if backend == 'odoo'` elders is een ontbrekende port-operatie)."""

from app.backends.port import (  # noqa: F401
    Backend,
    BackendBoekFout,
    BoekUitkomst,
    NietOndersteund,
    OrigineelStand,
    TegenboekUitkomst,
)
from app.backends.registry import backend_voor, inkoop_port_voor, standaard_regels_samenvoegen  # noqa: F401
