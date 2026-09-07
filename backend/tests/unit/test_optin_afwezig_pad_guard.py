"""Guard "geen stille no-op" (herstelrun 07-09 blok 2; besluit Peter, kernprincipe 7): élke opt-in/automatiserings-
vlag heeft een afwezig-pad-test — een test die bewijst dat de automatisering doorloopt als een OPTIONELE voorwaarde
(eigenaar, toewijzing, ontvanger) ontbreekt — en géén module buiten de bewuste allowlist vertakt op de
administratie-eigenaar.

Mechanisme: (1) sweep over álle `*_ingeschakeld`-kolommen in Base.metadata (`platform.administratie`, de platformbrede
singleton-instellingen, de per-leverancier-/per-veldwerker-opt-ins) ↔ de marker `@pytest.mark.afwezig_pad("<tabel>.
<kolom>")` in tests/**; een nieuwe vlag zonder zo'n test = rood, een marker met een tikfout ook. (2) De marker staat
geregistreerd in pyproject (anders warnt pytest en kan de guard 'm niet vertrouwen). (3) Allowlist voor
`eigenaar_gebruiker_id`: alleen beheer (eigenaar-beheer), het model en de vier plekken die het leeg-pad expliciet
dragen (afwijzen, vragen, duplicaat_afvoer, verplaatsen) mogen de eigenaar lezen — een nieuwe lezer moet hier bewust
worden toegevoegd mét een leeg-pad."""

from __future__ import annotations

import importlib
import re
from pathlib import Path

_BACKEND_ROOT = Path(__file__).resolve().parents[2]
_MARKER = re.compile(r"""afwezig_pad\(\s*["']([^"']+)["']\s*\)""")

# Modules die `eigenaar_gebruiker_id` mogen lezen, mét reden. Alles wat hier niet staat en tóch de eigenaar leest,
# is een nieuwe eigenaar-afhankelijkheid — die krijgt eerst een leeg-pad (en een regel hier), nooit stil.
_EIGENAAR_ALLOWLIST: dict[str, str] = {
    "app/db/models.py": "kolomdefinitie",
    "app/documenten/models.py": "docstring-verwijzing (Vraag/Afwijzing: default toegewezene, nullable sinds 0121)",
    "app/beheer/service.py": "eigenaar-beheer (zetten/lezen, Beheerder-only) — geen automatisering",
    "app/beheer/router.py": "eigenaar-beheer-endpoints",
    "app/beheer/schemas.py": "eigenaar-DTO",
    "app/documenten/afwijzen.py": "default 'ter controle naar'; leeg = doorlopen (0121)",
    "app/documenten/vragen.py": "default toegewezene; leeg = doorlopen (0121)",
    "app/documenten/duplicaat_afvoer.py": "eigenaar → mens → niemand; leeg = doorlopen (0121)",
    "app/documenten/verplaatsen.py": "hertoewijzing naar doel-eigenaar; leeg = doorlopen (0121)",
}


def _alle_vlaggen() -> set[str]:
    for p in sorted((_BACKEND_ROOT / "app").rglob("models.py")):
        importlib.import_module(".".join(p.relative_to(_BACKEND_ROOT).with_suffix("").parts))
    from app.db.models import Base

    return {
        f"{tabel.name}.{kolom.name}"
        for tabel in Base.metadata.tables.values()
        for kolom in tabel.columns
        if kolom.name.endswith("_ingeschakeld")
    }


def _gemarkeerde_vlaggen() -> dict[str, list[str]]:
    gevonden: dict[str, list[str]] = {}
    for p in (_BACKEND_ROOT / "tests").rglob("test_*.py"):
        if p.name == Path(__file__).name:
            continue
        for vlag in _MARKER.findall(p.read_text(encoding="utf-8")):
            gevonden.setdefault(vlag, []).append(str(p.relative_to(_BACKEND_ROOT)))
    return gevonden


class TestElkeOptInHeeftEenAfwezigPadTest:
    def test_marker_is_geregistreerd_in_pyproject(self) -> None:
        pyproject = (_BACKEND_ROOT / "pyproject.toml").read_text(encoding="utf-8")
        assert '"afwezig_pad(vlag):' in pyproject, "marker `afwezig_pad` ontbreekt in [tool.pytest.ini_options].markers"

    def test_sweep_kolommen_dekt_de_bekende_vlaggen(self) -> None:
        vlaggen = _alle_vlaggen()
        # Zelfcontrole van de sweep: de kern-vlaggen uit CLAUDE.md moeten erin zitten (anders sweept de guard niets).
        for verwacht in (
            "administratie.boeken_ingeschakeld",
            "administratie.duplicaat_autoafvoer_ingeschakeld",
            "duplicaat_afvoer_instelling.platformbreed_ingeschakeld",
            "boeken_instelling.globaal_ingeschakeld",
            "leverancier_voorkeur.autoboeken_ingeschakeld",
        ):
            assert verwacht in vlaggen

    def test_elke_vlag_heeft_een_afwezig_pad_test(self) -> None:
        vlaggen = _alle_vlaggen()
        gemarkeerd = _gemarkeerde_vlaggen()
        ontbrekend = sorted(vlaggen - set(gemarkeerd))
        assert not ontbrekend, (
            f"opt-in-vlag(gen) zonder afwezig-pad-test: {ontbrekend} — schrijf een test die bewijst dat de "
            "automatisering doorloopt zonder eigenaar/toewijzing/ontvanger en markeer 'm met "
            '@pytest.mark.afwezig_pad("<tabel>.<kolom>") (herstelrun 07-09 blok 2, kernprincipe 7)'
        )

    def test_geen_marker_op_een_onbekende_vlag(self) -> None:
        vlaggen = _alle_vlaggen()
        gemarkeerd = _gemarkeerde_vlaggen()
        onbekend = {v: b for v, b in gemarkeerd.items() if v not in vlaggen}
        assert not onbekend, (
            f"afwezig_pad-marker(s) op een niet-bestaande vlag (tikfout of hernoemde kolom): {onbekend}"
        )


class TestEigenaarAfhankelijkheidBlijftBewust:
    def test_alleen_allowlist_modules_lezen_de_eigenaar(self) -> None:
        lezers = sorted(
            str(p.relative_to(_BACKEND_ROOT))
            for p in (_BACKEND_ROOT / "app").rglob("*.py")
            if "eigenaar_gebruiker_id" in p.read_text(encoding="utf-8")
        )
        onbekend = [m for m in lezers if m not in _EIGENAAR_ALLOWLIST]
        assert not onbekend, (
            f"nieuwe lezer(s) van `eigenaar_gebruiker_id`: {onbekend} — een ontbrekende eigenaar mag een "
            "automatisering nooit stil of zichtbaar tegenhouden (leeg = doorlopen); voeg een leeg-pad toe en "
            "registreer de module bewust in _EIGENAAR_ALLOWLIST"
        )
        verdwenen = [m for m in _EIGENAAR_ALLOWLIST if m not in lezers]
        assert not verdwenen, f"allowlist-regel(s) zonder lezer meer (opruimen): {verdwenen}"

    def test_geen_toewijzing_mogelijk_bestaat_niet_meer(self) -> None:
        """De weigering `GeenToewijzingMogelijk` is op 07-09 vervallen; een herintroductie (ook onder een andere naam
        die op 'geen eigenaar' weigert) hoort niet stil terug te komen."""
        treffers = [
            str(p.relative_to(_BACKEND_ROOT))
            for p in (_BACKEND_ROOT / "app").rglob("*.py")
            if re.search(r"^\s*(class|raise)\s+GeenToewijzingMogelijk", p.read_text(encoding="utf-8"), re.M)
        ]
        assert not treffers, f"`GeenToewijzingMogelijk` wordt weer gedefinieerd/geworpen in {treffers}"
