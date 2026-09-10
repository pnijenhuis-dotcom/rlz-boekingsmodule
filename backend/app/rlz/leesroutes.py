"""Eén bron van waarheid voor de RLZ-LEESROUTES die de module bij het aansluiten van een administratie nodig heeft
(bundel 10-09 blok C — bevinding Baard beheer & management: wizard "10 leesroutes groen", eerste sync 403 op
Ledgers/Vendors/Projects/PaymentAccounts).

Vóór 10-09 stonden de probe-set (`credentialstore/service.py::_TE_PROBEREN_ENDPOINTS`) en de sync-paden
(`sync/service.py` `pad="Ledgers"` …, `RlzClient.list_payment_accounts`) los van elkaar als literals. Ze waren op 10-09
toevallig gelijk, maar niets bewaakte dat. Sinds 10-09:

  * de eerste sync leest zijn pad per onderdeel HIER (`pad_voor_sync_onderdeel`), de probe leest zijn set HIER
    (`PROBE_LEESROUTES`), en `tests/rlz/test_leesroutes.py` bewijst fail-closed dat élk sync-onderdeel een probe-route
    heeft én dat de paden die de sync-motoren daadwerkelijk opvragen ⊆ de paden die de probe opvraagt;
  * per route staat het RLZ-recht dat de Beheerder in Reeleezee moet zetten als de route 403 geeft
    (handelingsperspectief in `beschrijf_probe_fouten` en in de eerste-sync-stand).

Pure data — dit bestand importeert bewust niets uit `app.rlz.client` of de servicelagen (die importeren dít).
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Leesroute:
    """Eén RLZ-leesroute zoals de module 'm aanspreekt.

    `pad` is het exacte relatieve pad dat `RlzClient.get(pad)` krijgt (zonder adminId-prefix; die zet de gescoped client
    er zelf voor). `params` = de exacte query-parameters (leeg = kale collectie). `scope` = 'root' (zonder adminId,
    alleen `Administrations`) of 'administratie'. `sync_onderdeel` = de naam in `eerste_sync.ONDERDELEN` als deze
    route door de eerste sync gebruikt wordt. `rlz_recht` = wat in Reeleezee aan de webservice-gebruiker gegeven moet
    worden."""

    naam: str
    pad: str
    params: tuple[tuple[str, str], ...] = ()
    scope: str = "administratie"
    sync_onderdeel: str | None = None
    rlz_recht: str = ""
    afgeleide_paden: tuple[str, ...] = ()  #: sub-routes per record die de sync óók opvraagt (patroon met {id})


ADMINISTRATIONS = Leesroute(
    naam="Administrations",
    pad="Administrations",
    scope="root",
    rlz_recht="de webservice-gebruiker moet aan deze administratie gekoppeld zijn (RLZ › Instellingen › Gebruikers)",
)
LEDGERS = Leesroute(
    naam="Ledgers",
    pad="Ledgers",
    sync_onderdeel="ledgers",
    rlz_recht="leesrecht Grootboek/Financieel (rekeningschema) voor de webservice-gebruiker op deze administratie",
)
TAX_RATES = Leesroute(
    naam="TaxRates",
    pad="TaxRates",
    sync_onderdeel="taxrates",
    rlz_recht="leesrecht Btw-tarieven (Financieel) voor de webservice-gebruiker op deze administratie",
)
VENDORS = Leesroute(
    naam="Vendors",
    pad="Vendors",
    sync_onderdeel="vendors",
    rlz_recht="leesrecht Relaties › Crediteuren voor de webservice-gebruiker op deze administratie",
)
CUSTOMERS = Leesroute(
    naam="Customers",
    pad="Customers",
    rlz_recht="leesrecht Relaties › Debiteuren voor de webservice-gebruiker op deze administratie",
)
PROJECTS = Leesroute(
    naam="Projects",
    pad="Projects",
    sync_onderdeel="projects",
    rlz_recht="leesrecht Projecten voor de webservice-gebruiker op deze administratie",
)
SALES_INVOICES = Leesroute(
    naam="SalesInvoices",
    pad="SalesInvoices",
    rlz_recht="facturatiemodule afgenomen + leesrecht Verkoop (een 403 hier = module niet afgenomen, geen blokkade)",
)
PURCHASE_INVOICES = Leesroute(
    naam="PurchaseInvoices",
    pad="PurchaseInvoices",
    rlz_recht="leesrecht Inkoop (inkoopfacturen) voor de webservice-gebruiker op deze administratie",
)
JOURNAL_ENTRIES = Leesroute(
    naam="JournalEntries",
    pad="JournalEntries",
    rlz_recht=(
        "leesrecht Financieel › Journaalposten (boekingsgeheugen) voor de webservice-gebruiker op deze administratie"
    ),
)
PAYMENT_ACCOUNTS = Leesroute(
    naam="PaymentAccounts",
    pad="PaymentAccounts",
    sync_onderdeel="payment_accounts",
    rlz_recht="leesrecht Bank/Kas (betaalrekeningen) voor de webservice-gebruiker op deze administratie",
    afgeleide_paden=("PaymentAccounts/{id}/LastBankImport",),
)

#: De probe-set (koppel-flow): `Administrations` via de root-client, de rest via de administratie-gescoped client.
#: Volgorde = weergavevolgorde in het rapport (bestaande DTO-vorm `{naam: 'ok' | '<status>'}` blijft).
PROBE_LEESROUTES: tuple[Leesroute, ...] = (
    ADMINISTRATIONS,
    LEDGERS,
    TAX_RATES,
    VENDORS,
    CUSTOMERS,
    PROJECTS,
    SALES_INVOICES,
    PURCHASE_INVOICES,
    JOURNAL_ENTRIES,
    PAYMENT_ACCOUNTS,
)

#: De routes die de eerste sync gebruikt, op naam van het sync-onderdeel (`eerste_sync.ONDERDELEN`).
SYNC_LEESROUTES: dict[str, Leesroute] = {r.sync_onderdeel: r for r in PROBE_LEESROUTES if r.sync_onderdeel is not None}

_PER_NAAM: dict[str, Leesroute] = {r.naam: r for r in PROBE_LEESROUTES}


def pad_voor_sync_onderdeel(onderdeel: str) -> str:
    """Het exacte GET-pad van een eerste-sync-onderdeel — fail-loud op een onderdeel zonder route (dan ontbreekt de
    probe-dekking en móet hier een Leesroute bij; de test in tests/rlz/test_leesroutes.py vangt dat óók)."""
    try:
        return SYNC_LEESROUTES[onderdeel].pad
    except KeyError as exc:
        raise KeyError(f"Sync-onderdeel {onderdeel!r} heeft geen Leesroute in app/rlz/leesroutes.py") from exc


def route_voor(naam: str) -> Leesroute | None:
    return _PER_NAAM.get(naam)


def rlz_recht_voor(naam: str) -> str:
    """Handelingsperspectief bij een 403 op deze route (leeg als de route onbekend is)."""
    route = _PER_NAAM.get(naam)
    return route.rlz_recht if route is not None else ""


def route_voor_pad(pad: str) -> Leesroute | None:
    """Terugzoeken van een opgevraagd pad (zoals de sync 'm aan `client.get` geeft, evt. mét adminId-prefix of
    query-string) naar de Leesroute — voor de eerste-sync-stand ("welk recht ontbreekt") en de dekkingstest."""
    kaal = pad.split("?", 1)[0].strip("/")
    delen = kaal.split("/")
    for i in range(len(delen)):
        kandidaat = "/".join(delen[i:])
        for route in PROBE_LEESROUTES:
            if kandidaat == route.pad:
                return route
            for patroon in route.afgeleide_paden:
                prefix, _, suffix = patroon.partition("{id}")
                past = kandidaat.startswith(prefix) and kandidaat.endswith(suffix)
                if past and len(kandidaat) > len(prefix) + len(suffix):
                    return route
    return None
