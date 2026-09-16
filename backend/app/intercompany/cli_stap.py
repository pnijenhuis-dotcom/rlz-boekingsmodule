"""Sync-alles-stap intercompany (blok A 16-09): drie deelstappen, elk apart gevangen, uitkomst als leesbare regels.
Los van cli.py gehouden zodat de hunk in `_sync_alles` één aanroep blijft (agenten B/C voegen elders in cli.py toe)."""

from __future__ import annotations

import sys
from collections import Counter

from app.intercompany import identiteit, rc_koppelingen, relaties


def rapporteer_afleiding() -> int:
    """0 = alle drie stappen liepen; 1 = minstens één stap viel om (zichtbaar op stderr). Fouten per administratie
    bínnen een stap zijn regels, geen exit-code (KP 6: geen stille no-op, maar ook geen rode job om één BV)."""
    fouten = 0
    try:
        uitkomsten = identiteit.sync_identiteiten()
        tellers = Counter(u.stand for u in uitkomsten)
        print(
            "  identiteiten: "
            + ", ".join(f"{k}={v}" for k, v in sorted(tellers.items()))
            + (f" ({len(uitkomsten)} administraties)" if uitkomsten else " (geen actieve administraties)")
        )
        for u in uitkomsten:
            if u.melding:
                print(f"    {u.stand.upper():12} {u.administratie_naam}: {u.melding}")
    except Exception as exc:  # noqa: BLE001 — zichtbaar, nooit stop
        fouten += 1
        print(f"  FOUT identiteiten-sync: {type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        rel = relaties.leid_relaties_af()
        print(
            f"  relaties: nieuw={rel.relaties_nieuw} bijgewerkt={rel.relaties_bijgewerkt} "
            f"ongewijzigd={rel.relaties_ongewijzigd} mens-rijen={rel.mens_rijen_overgeslagen} "
            f"doorbelasting={rel.doorbelasting_overgenomen} per_basis={dict(rel.per_basis)} "
            f"(crediteuren {rel.crediteuren_bekeken}, debiteuren {rel.debiteuren_bekeken})"
        )
        for aid, m in rel.overgeslagen:
            print(f"    OVERGESLAGEN {aid}: {m}")
        for aid, m in rel.fouten:
            print(f"    FOUT {aid}: {m}", file=sys.stderr)
    except Exception as exc:  # noqa: BLE001
        fouten += 1
        print(f"  FOUT relaties-afleiding: {type(exc).__name__}: {exc}", file=sys.stderr)
    try:
        rc = rc_koppelingen.leid_rc_koppelingen_af()
        print(
            f"  rc-koppelingen: nieuw={rc.koppelingen_nieuw} bijgewerkt={rc.koppelingen_bijgewerkt} "
            f"ongewijzigd={rc.koppelingen_ongewijzigd} zonder_tegenrekening={rc.zonder_tegenrekening} "
            f"meerduidig={rc.meerduidig} mens-rijen={rc.mens_rijen_overgeslagen} per_basis={dict(rc.per_basis)} "
            f"(rekeningen {rc.rekeningen_bekeken})"
        )
    except Exception as exc:  # noqa: BLE001
        fouten += 1
        print(f"  FOUT rc-afleiding: {type(exc).__name__}: {exc}", file=sys.stderr)
    return 1 if fouten else 0
