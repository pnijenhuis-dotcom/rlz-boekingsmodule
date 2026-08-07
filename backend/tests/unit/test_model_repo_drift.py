"""Model↔repo-drift-guard (adoptie uit Platform/registers/verbeteringen.md, vastgoed 2026-07-11).

Twee verdedigingslinies, allebei pure introspectie — geen DB, geen HTTP:

1. **AST-sweep**: elke `functie(**x.model_dump())`-spread in `app/` moet in het contractregister
   hieronder staan. De spread is precies het patroon waar drift stil misgaat (een In-veld hernoemen
   zonder de repo-functie mee te nemen levert pas runtime een TypeError op); vandaag komt hij in
   deze codebase niet voor, en deze sweep houdt dat zo — een nieuwe spread zonder registratie
   faalt hier direct.
2. **Contractregister**: per (In/Patch-model, doelservicefunctie)-paar toetsen dat de
   modelveldnamen een subset zijn van de signatuurparameters. Dekt in elk geval de
   IBAN-bevestiging en crediteur-aanmaken (opdracht 2026-07-13), plus de overige router→service-
   paren met een pydantic-invoermodel op het geldpad.

Functies met `**kwargs` slikken élke veldnaam en maken de subsettoets betekenisloos — dat is een
blinde vlek die expliciet gemarkeerd moet worden in BLINDE_VLEKKEN, nooit stil overgeslagen.
"""

from __future__ import annotations

import ast
import inspect
from collections.abc import Callable
from pathlib import Path

from pydantic import BaseModel

from app.documenten import boekvoorstel as boekvoorstel_service
from app.documenten import iban_accordering
from app.documenten import schemas as documenten_schemas
from app.documenten import service as documenten_service
from app.sync import schemas as sync_schemas
from app.sync import service as sync_service

_APP_ROOT = Path(__file__).resolve().parents[2] / "app"

# Contractregister: In/Patch-model -> service-/repo-functie die zijn velden als kwargs ontvangt.
# Nieuw endpoint met pydantic-invoer dat naar een servicefunctie mapt? Hier registreren.
CONTRACTEN: list[tuple[type[BaseModel], Callable]] = [
    # Vier-ogen-accordering (2026-07-15) verving het directe bevestig-endpoint
    # (IbanBevestigenInput ↔ bevestig_iban) — aanbieden/afwijzen zijn nu de contracten.
    (documenten_schemas.IbanAanbiedenInput, iban_accordering.bied_aan),
    (documenten_schemas.IbanAfwijzenInput, iban_accordering.wijs_af),
    (sync_schemas.NieuweCrediteurInput, sync_service.maak_crediteur_aan),
    (documenten_schemas.BoekvoorstelInput, boekvoorstel_service.sla_boekvoorstel_op),
    (documenten_schemas.VerwijderenInput, documenten_service.verwijder_document),
]

# Doelfuncties met **kwargs: de subsettoets kan daar niets bewijzen. Bewust leeg — een functie
# hier toevoegen is een expliciete, review-bare beslissing (nooit stil overslaan); de test
# hieronder controleert bovendien dat elke vermelding hier écht **kwargs heeft (geen dode marker).
BLINDE_VLEKKEN: set[Callable] = set()

# Parameters die niet uit de request-body maar uit de route/auth komen (padparameter, ingelogde
# gebruiker, scope) — de omgekeerde drift-toets (verplichte parameter zonder modelveld) slaat
# die over. Nieuw route-geleverd argument? Hier toevoegen, met deze motivering als lat.
ROUTE_GELEVERD: set[str] = {"actor_id", "administratie_id", "document_id", "accordering_id"}


def _parameters_van(functie: Callable) -> tuple[set[str], bool]:
    """(parameternamen, heeft **kwargs) van de signatuur."""
    signatuur = inspect.signature(functie)
    heeft_kwargs = any(p.kind is inspect.Parameter.VAR_KEYWORD for p in signatuur.parameters.values())
    namen = {naam for naam, p in signatuur.parameters.items() if p.kind is not inspect.Parameter.VAR_KEYWORD}
    return namen, heeft_kwargs


class TestContractregister:
    def test_modelvelden_zijn_subset_van_de_signatuur(self) -> None:
        fouten: list[str] = []
        for model, functie in CONTRACTEN:
            parameters, heeft_kwargs = _parameters_van(functie)
            if heeft_kwargs and functie not in BLINDE_VLEKKEN:
                fouten.append(
                    f"{functie.__module__}.{functie.__qualname__} heeft **kwargs — de subsettoets "
                    "bewijst daar niets; markeer 'm expliciet in BLINDE_VLEKKEN of geef de functie "
                    "een expliciete signatuur"
                )
                continue
            ontbrekend = set(model.model_fields) - parameters
            if ontbrekend:
                fouten.append(
                    f"{model.__name__} -> {functie.__module__}.{functie.__qualname__}: veld(en) "
                    f"{sorted(ontbrekend)} bestaan niet in de signatuur — model en repo-functie "
                    "zijn uit de pas (drift)"
                )
        assert not fouten, "\n".join(fouten)

    def test_verplichte_parameters_hebben_een_modelveld(self) -> None:
        """De OMGEKEERDE richting (Vastly-port b, 2026-08-07): een verplichte functieparameter
        die niet route-geleverd is en géén modelveld heeft, betekent dat elke aanroep via dit
        model per definitie een TypeError wordt — dezelfde drift, andere kant op."""
        fouten: list[str] = []
        for model, functie in CONTRACTEN:
            signatuur = inspect.signature(functie)
            verplicht = {
                naam
                for naam, p in signatuur.parameters.items()
                if p.default is inspect.Parameter.empty
                and p.kind not in (inspect.Parameter.VAR_KEYWORD, inspect.Parameter.VAR_POSITIONAL)
            }
            ontbrekend = verplicht - ROUTE_GELEVERD - set(model.model_fields)
            if ontbrekend:
                fouten.append(
                    f"{model.__name__} -> {functie.__module__}.{functie.__qualname__}: verplichte "
                    f"parameter(s) {sorted(ontbrekend)} hebben geen modelveld en zijn niet "
                    "route-geleverd (ROUTE_GELEVERD) — drift in de omgekeerde richting"
                )
        assert not fouten, "\n".join(fouten)

    def test_iban_en_crediteur_contracten_zijn_geregistreerd(self) -> None:
        """De opdracht eist expliciete dekking van de nieuwe IBAN-endpoints + crediteur-aanmaken —
        deze toets voorkomt dat iemand die paren ooit uit het register 'opruimt'."""
        geregistreerd = {(model, functie) for model, functie in CONTRACTEN}
        assert (documenten_schemas.IbanAanbiedenInput, iban_accordering.bied_aan) in geregistreerd
        assert (sync_schemas.NieuweCrediteurInput, sync_service.maak_crediteur_aan) in geregistreerd

    def test_blinde_vlekken_zijn_geen_dode_markers(self) -> None:
        """Elke functie in BLINDE_VLEKKEN moet daadwerkelijk **kwargs hebben — anders is de
        markering verlopen (signatuur is expliciet geworden) en hoort hij weer onder de toets."""
        for functie in BLINDE_VLEKKEN:
            _, heeft_kwargs = _parameters_van(functie)
            assert heeft_kwargs, (
                f"{functie.__module__}.{functie.__qualname__} staat in BLINDE_VLEKKEN maar heeft "
                "geen **kwargs meer — verwijder de markering zodat de subsettoets weer geldt"
            )


def _model_dump_spreads(boom: ast.AST) -> list[ast.Call]:
    """Alle aanroepen `f(**x.model_dump())` in de module — het drift-gevoelige patroon."""
    treffers: list[ast.Call] = []
    for knoop in ast.walk(boom):
        if not isinstance(knoop, ast.Call):
            continue
        for keyword in knoop.keywords:
            if keyword.arg is not None:  # gewone kwarg, geen **spread
                continue
            waarde = keyword.value
            if (
                isinstance(waarde, ast.Call)
                and isinstance(waarde.func, ast.Attribute)
                and waarde.func.attr == "model_dump"
            ):
                treffers.append(knoop)
    return treffers


def _aanroep_naam(knoop: ast.Call) -> str:
    return ast.unparse(knoop.func)


class TestAstSweep:
    def test_elke_model_dump_spread_in_app_staat_in_het_contractregister(self) -> None:
        """Vandaag nul spreads (routers mappen expliciet per kwarg — dat blijft de voorkeur).
        Duikt er ooit één op, dan faalt deze test totdat het paar in CONTRACTEN staat, zodat de
        subsettoets 'm dekt. Vergelijking op functienaam (best-effort statisch): een naam die we
        niet kunnen herleiden is per definitie een blinde vlek en faalt ook."""
        geregistreerde_namen = {functie.__name__ for _, functie in CONTRACTEN}
        onbekend: list[str] = []
        for pad in sorted(_APP_ROOT.rglob("*.py")):
            boom = ast.parse(pad.read_text(), filename=str(pad))
            for aanroep in _model_dump_spreads(boom):
                naam = _aanroep_naam(aanroep)
                if naam.rsplit(".", maxsplit=1)[-1] not in geregistreerde_namen:
                    onbekend.append(f"{pad.relative_to(_APP_ROOT.parent)}:{aanroep.lineno} -> {naam}(**….model_dump())")
        assert not onbekend, (
            "**model_dump()-spread(s) gevonden buiten het contractregister — registreer het "
            "(model, functie)-paar in tests/unit/test_model_repo_drift.py::CONTRACTEN:\n" + "\n".join(onbekend)
        )


class TestStrikteInvoer:
    """`extra="forbid"` op elk request-body-model (Vastly-port b, 2026-08-07): een onbekend of
    verkeerd gespeld veld is een 422 mét veldnaam, nooit stil genegeerd. De sweep vindt modellen
    op naamconventie (In/Input/Patch/Request/Invoer + de beheer-Dto's die als PUT-body dienen);
    een nieuw request-model dat niet van app.schemas_basis.StrikteInvoer erft, faalt hier."""

    _NAAMPATROON = ("Input", "Request", "Patch", "Invoer", "InputDto")
    # Dto's die (ook) als request-body dienen maar de naamconventie niet volgen.
    _EXPLICIET = {
        "app.beheer.schemas": {
            "BoekenIngeschakeldDto",
            "WebhookAfleveringDto",
            "IntakeAiDto",
            "ProjectVerplichtDto",
            "AiExtractieIngeschakeldDto",
            "EigenaarDto",
        },
    }

    def _request_modellen(self) -> list[type[BaseModel]]:
        import importlib

        modellen: list[type[BaseModel]] = []
        for pad in sorted(_APP_ROOT.rglob("schemas*.py")):
            module_naam = ".".join(pad.relative_to(_APP_ROOT.parent).with_suffix("").parts)
            module = importlib.import_module(module_naam)
            expliciet = self._EXPLICIET.get(module_naam, set())
            for naam in dir(module):
                obj = getattr(module, naam)
                if not (isinstance(obj, type) and issubclass(obj, BaseModel) and obj is not BaseModel):
                    continue
                if obj.__module__ != module_naam:
                    continue  # re-export uit een andere module — daar getoetst
                if naam.endswith(self._NAAMPATROON) or naam in expliciet:
                    modellen.append(obj)
        return modellen

    def test_sweep_vindt_de_bekende_modellen(self) -> None:
        namen = {m.__name__ for m in self._request_modellen()}
        # Steekproef over de modules heen — beschermt tegen een sweep die stil niets vindt.
        assert {"BoekvoorstelInput", "LoginRequest", "DirectBoekenInput", "ToewijzenInput",
                "OmzetVoorstelInput", "IntakeAiDto", "NieuweCrediteurInput"} <= namen

    def test_elk_request_model_weigert_onbekende_velden(self) -> None:
        fouten = [
            f"{m.__module__}.{m.__name__}: model_config extra={m.model_config.get('extra')!r} — "
            "erf van app.schemas_basis.StrikteInvoer"
            for m in self._request_modellen()
            if m.model_config.get("extra") != "forbid"
        ]
        assert not fouten, "\n".join(fouten)
