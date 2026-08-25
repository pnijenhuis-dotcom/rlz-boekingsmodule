"""Harde checks doorbelasting (opdracht blok 1e) — pure functies op primitieven, zonder DB of
RLZ-sessie (zelfde ontwerp als app/documenten/checks.py en app/omzet/checks.py); de
orkestratie in service/boeken levert de invoer aan. Altijd blokkerend, nooit stil overslaan.

Vaste volgorde:
1. Verdeelsleutels sluiten op exact 100% per geselecteerde bron-regel (mockup #verdeelmodal:
   "Totaal moet exact 100% zijn, anders blokkeert boeken").
2. Bedragen sluiten: som(netto_delen per regel) == bron-regelnetto (grootste-rest-garantie
   hertoetst op de vastgelegde delen) én som(doorbelast + provisie per doelentiteit) ==
   verwacht totaal.
3. Doel-mapping bestaat, is actief en het bron-deel van de config is compleet (btw-tarief +
   omzet-GB — §2: config, nooit hardcoded).
4. Onboarded doelen boekbaar: doel-kosten-GB per verdeelregel gekozen én provisie-GB op de
   mapping gezet (mockup: verplicht) — alleen voor doelen mét doel_administratie_id; een
   niet-onboarded doel is geen fout maar wordt een open spiegel-taak.
De rechten-probe (beide administraties bereikbaar vóór de eerste write) is bewust géén pure
check maar een orkestratiestap in boeken.py — hij vergt live clients."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from decimal import Decimal

from app.documenten.checks import CheckRapport, CheckResultaat
from app.doorbelasting.geld import provisie_over

HONDERD = Decimal("100")


@dataclass(frozen=True)
class VerdeelRegelInvoer:
    """Eén verdeelregel zoals de checks 'm nodig hebben (los van het ORM-model)."""

    bron_regel_id: uuid.UUID
    bron_netto: Decimal
    mapping_id: uuid.UUID
    percentage: Decimal
    netto_deel: Decimal
    doel_kosten_ledger_id: uuid.UUID | None
    # Doorbelasting × projecten (25-08, deel 2 punt 2a): project in de doel-administratie; bij een
    # multi-project-verdeling staat per project één rij met hetzelfde `percentage`.
    project_id: uuid.UUID | None = None


@dataclass(frozen=True)
class MappingInvoer:
    mapping_id: uuid.UUID
    actief: bool
    doel_administratie_id: uuid.UUID | None
    provisie_kosten_ledger_id: uuid.UUID | None
    # Route-A-nazorg (besluit 2026-08-14): het RLZ-customer-GUID waarop de verkoopfactuur in
    # de bron geboekt wordt — nodig voor de anker-toets (check_geen_ankerdebiteur).
    doel_customer_guid: uuid.UUID | None = None
    # project_verplicht van de DOEL-administratie (25-08, deel 2 punt 2a): dan is een project per
    # verdeelregel verplicht — de spiegel ontsnapt niet meer aan de projectplicht van het doel.
    doel_project_verplicht: bool = False
    doelentiteit_naam: str | None = None


def check_verdeling_100(regels: list[VerdeelRegelInvoer]) -> CheckResultaat:
    naam = "Verdeling per regel = 100%"
    if not regels:
        return CheckResultaat(naam=naam, ok=False, melding="Geen verdeelregels — selecteer minimaal één regel")
    fouten: list[str] = []
    per_bron: dict[uuid.UUID, Decimal] = {}
    # Multi-project (25-08): de project-rijen van één doelentiteit delen hetzelfde percentage —
    # per (bron-regel, doelentiteit) één keer meetellen.
    gezien: set[tuple[uuid.UUID, uuid.UUID]] = set()
    for regel in regels:
        if (regel.bron_regel_id, regel.mapping_id) in gezien:
            continue
        gezien.add((regel.bron_regel_id, regel.mapping_id))
        per_bron[regel.bron_regel_id] = per_bron.get(regel.bron_regel_id, Decimal(0)) + regel.percentage
    for bron_id, som in per_bron.items():
        if som != HONDERD:
            fouten.append(f"regel {bron_id}: {som}%")
    if fouten:
        return CheckResultaat(
            naam=naam, ok=False, melding="Verdeling sluit niet op 100%: " + "; ".join(sorted(fouten))
        )
    return CheckResultaat(naam=naam, ok=True, melding="Elke geselecteerde regel is voor exact 100% verdeeld")


def check_bedragen_sluiten(
    regels: list[VerdeelRegelInvoer],
    *,
    provisie_percentage: Decimal,
    verwachte_totalen_per_mapping: dict[uuid.UUID, tuple[Decimal, Decimal]] | None = None,
) -> CheckResultaat:
    """Som van de vastgelegde netto-delen per bron-regel == het bron-regelnetto (er raakt nooit
    een cent kwijt), en — als de orkestratie verwachte totalen aanlevert — som doorbelast +
    provisie per doelentiteit == verwacht (opdracht blok 1e)."""
    naam = "Bedragen sluiten"
    fouten: list[str] = []
    per_bron_som: dict[uuid.UUID, Decimal] = {}
    per_bron_netto: dict[uuid.UUID, Decimal] = {}
    per_mapping_som: dict[uuid.UUID, Decimal] = {}
    for regel in regels:
        per_bron_som[regel.bron_regel_id] = per_bron_som.get(regel.bron_regel_id, Decimal(0)) + regel.netto_deel
        per_bron_netto[regel.bron_regel_id] = regel.bron_netto
        per_mapping_som[regel.mapping_id] = per_mapping_som.get(regel.mapping_id, Decimal(0)) + regel.netto_deel
    for bron_id, som in per_bron_som.items():
        if som != per_bron_netto[bron_id]:
            fouten.append(f"regel {bron_id}: delen sommen tot {som}, regelnetto is {per_bron_netto[bron_id]}")
    if verwachte_totalen_per_mapping is not None:
        for mapping_id, (verwacht_netto, verwachte_provisie) in verwachte_totalen_per_mapping.items():
            netto = per_mapping_som.get(mapping_id, Decimal(0))
            provisie = provisie_over(netto, provisie_percentage)
            if netto != verwacht_netto or provisie != verwachte_provisie:
                fouten.append(
                    f"doelentiteit {mapping_id}: doorbelast {netto} + provisie {provisie} "
                    f"≠ verwacht {verwacht_netto} + {verwachte_provisie}"
                )
    if fouten:
        return CheckResultaat(naam=naam, ok=False, melding="; ".join(sorted(fouten)))
    return CheckResultaat(naam=naam, ok=True, melding="Delen sluiten exact op de regelbedragen")


def check_mapping_en_config(
    regels: list[VerdeelRegelInvoer],
    mappings: dict[uuid.UUID, MappingInvoer],
    *,
    btw_taxrate_id: uuid.UUID | None,
    omzet_ledger_id: uuid.UUID | None,
) -> CheckResultaat:
    naam = "Doel-mapping en instellingen"
    fouten: list[str] = []
    if btw_taxrate_id is None:
        fouten.append("btw-tarief doorbelasting niet ingesteld (Instellingen)")
    if omzet_ledger_id is None:
        fouten.append("omzet-GB doorbelasting niet ingesteld (Instellingen)")
    for mapping_id in sorted({r.mapping_id for r in regels}, key=str):
        mapping = mappings.get(mapping_id)
        if mapping is None:
            fouten.append(f"doelentiteit {mapping_id}: geen mapping-rij (whitelist)")
        elif not mapping.actief:
            fouten.append(f"doelentiteit {mapping_id}: mapping is inactief")
    if fouten:
        return CheckResultaat(naam=naam, ok=False, melding="; ".join(fouten))
    return CheckResultaat(naam=naam, ok=True, melding="Alle doelentiteiten staan actief op de whitelist")


def check_onboarded_doelen_boekbaar(
    regels: list[VerdeelRegelInvoer],
    mappings: dict[uuid.UUID, MappingInvoer],
) -> CheckResultaat:
    """Voor doelen mét eigen administratie moet de spiegel direct boekbaar zijn: doel-kosten-GB
    per verdeelregel én provisie-GB op de mapping. Een niet-onboarded doel slaat deze eis
    bewust over — dat wordt een zichtbare open spiegel-taak, geen blokkade (opdracht 1c)."""
    naam = "Doel-GB's gekozen (onboarded doelen)"
    fouten: list[str] = []
    for regel in regels:
        mapping = mappings.get(regel.mapping_id)
        if mapping is None or mapping.doel_administratie_id is None:
            continue
        if regel.doel_kosten_ledger_id is None:
            fouten.append(f"verdeelregel {regel.bron_regel_id}→{regel.mapping_id}: geen doel-kosten-GB gekozen")
        if mapping.provisie_kosten_ledger_id is None:
            fouten.append(f"doelentiteit {regel.mapping_id}: geen provisie-GB ingesteld op de mapping")
    if fouten:
        return CheckResultaat(naam=naam, ok=False, melding="; ".join(sorted(set(fouten))))
    return CheckResultaat(naam=naam, ok=True, melding="Onboarded doelen zijn direct boekbaar")


def check_geen_ankerdebiteur(
    regels: list[VerdeelRegelInvoer],
    mappings: dict[uuid.UUID, MappingInvoer],
    *,
    anker_customer_guid: uuid.UUID | None,
) -> CheckResultaat:
    """Route-A-nazorg (besluit Peter 2026-08-14): het projectanker "Pandprojecten (systeem)"
    krijgt NOOIT een boeking — een whitelist-rij die (per vergissing) het anker-GUID draagt
    blokkeert dus onvoorwaardelijk. De orkestratie levert het deterministische anker-GUID van
    de bron-administratie aan (app/projecten/anker.py::anker_customer_id); None = geen toets
    mogelijk, dan telt de check als geslaagd-op-naamloze-basis — bewust niet fail-closed,
    want het GUID is puur lokaal berekenbaar en ontbreekt alleen in oude testinvoer."""
    naam = "Geen boeking op het projectanker"
    if anker_customer_guid is None:
        return CheckResultaat(naam=naam, ok=True, melding="Anker-toets zonder GUID overgeslagen")
    geraakt = [
        str(mapping_id)
        for mapping_id in sorted({r.mapping_id for r in regels}, key=str)
        if (m := mappings.get(mapping_id)) is not None and m.doel_customer_guid == anker_customer_guid
    ]
    if geraakt:
        return CheckResultaat(
            naam=naam,
            ok=False,
            melding="Doelentiteit verwijst naar het projectanker 'Pandprojecten (systeem)' "
            "(route A) — daar mag nooit op geboekt worden: " + "; ".join(geraakt),
        )
    return CheckResultaat(naam=naam, ok=True, melding="Geen doelentiteit verwijst naar het projectanker")


def check_project_verplicht_doel(
    regels: list[VerdeelRegelInvoer], mappings: dict[uuid.UUID, MappingInvoer]
) -> CheckResultaat:
    """Besluit Peter 25-08 "optie 2": heeft de DOEL-administratie project_verplicht aan, dan
    moet elke verdeelregel naar dat doel een project dragen — anders zou de spiegel-inkoopfactuur
    zonder project geboekt worden terwijl een gewone inkoopfactuur daar geblokkeerd zou zijn.
    Zonder projectplicht is het project optioneel (geen melding)."""
    naam = "Project verplicht in doel-administratie"
    fouten: list[str] = []
    for regel in regels:
        mapping = mappings.get(regel.mapping_id)
        if mapping is None or not mapping.doel_project_verplicht:
            continue
        if regel.project_id is None:
            fouten.append(f"{mapping.doelentiteit_naam or mapping.mapping_id}: regel {regel.bron_regel_id} zonder project")
    if fouten:
        return CheckResultaat(naam=naam, ok=False, melding="Project ontbreekt — " + "; ".join(sorted(fouten)))
    return CheckResultaat(naam=naam, ok=True, melding="Elke verdeelregel naar een doel met projectplicht draagt een project")


def voer_doorbelasting_checks_uit(
    *,
    regels: list[VerdeelRegelInvoer],
    mappings: dict[uuid.UUID, MappingInvoer],
    provisie_percentage: Decimal,
    btw_taxrate_id: uuid.UUID | None,
    omzet_ledger_id: uuid.UUID | None,
    verwachte_totalen_per_mapping: dict[uuid.UUID, tuple[Decimal, Decimal]] | None = None,
    anker_customer_guid: uuid.UUID | None = None,
) -> CheckRapport:
    return CheckRapport(
        resultaten=(
            check_verdeling_100(regels),
            check_bedragen_sluiten(
                regels,
                provisie_percentage=provisie_percentage,
                verwachte_totalen_per_mapping=verwachte_totalen_per_mapping,
            ),
            check_mapping_en_config(
                regels, mappings, btw_taxrate_id=btw_taxrate_id, omzet_ledger_id=omzet_ledger_id
            ),
            check_onboarded_doelen_boekbaar(regels, mappings),
            check_geen_ankerdebiteur(regels, mappings, anker_customer_guid=anker_customer_guid),
            check_project_verplicht_doel(regels, mappings),
        )
    )
