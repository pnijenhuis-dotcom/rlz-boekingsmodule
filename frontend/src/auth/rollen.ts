// Rol-indeling kantoor vs externe app-rollen — spiegel van backend/app/auth/rollen.py
// (rollen-gate-fix 2026-08-21). Beide surfaces toetsen tegen ALLOWLISTS, nooit tegen een
// complement: een onbekende/nieuwe rol landt dan nergens stil in de verkeerde console.
// De backend blijft de waarheid (403 op rolniveau) — dit stuurt alleen de routing.

export const KANTOOR_ROLLEN = ['beheerder', 'boekhouding_projecten', 'boekhouding'] as const
export const VELD_ROLLEN = ['zzper', 'uitvoerder', 'detacheerder'] as const

export function isKantoorRol(rol: string | null): boolean {
  return rol !== null && (KANTOOR_ROLLEN as readonly string[]).includes(rol)
}

export function isVeldRol(rol: string | null): boolean {
  return rol !== null && (VELD_ROLLEN as readonly string[]).includes(rol)
}

/** Mag deze rol een nieuw project aanmaken? Sinds 04-09 (besluit Peter) álle drie de
 * kantoorrollen — óók Boekhouding: wie een inkoopfactuur op een nog niet bestaand project moet
 * boeken, moet dat project vanaf het controlescherm kunnen aanmaken zonder een collega te
 * moeten vragen. Spiegel van backend `app/projecten/kantoor.py::_AANMAAK_ROLLEN`; de overige
 * projectmutaties (specificatie, staffels, prijsafspraken, documenten) blijven Beheerder +
 * Boekhouding+Projecten (`_SCHRIJF_ROLLEN`). Allowlist, nooit een complement: een onbekende
 * of nieuwe rol krijgt de actie niet te zien. De backend blijft de waarheid (403). */
export const PROJECT_AANMAAK_ROLLEN = ['beheerder', 'boekhouding_projecten', 'boekhouding'] as const

export function magProjectAanmaken(rol: string | null): boolean {
  return rol !== null && (PROJECT_AANMAAK_ROLLEN as readonly string[]).includes(rol)
}

/** /veldwerkers (veldwerkers-run 14-09, besluiten Peter 14-09 punt 1+2): kantoorbrede pagina voor koppelingen,
 * tarieven en dossiers van veldwerkers. Routing-allowlist = de kantoorrollen (de backend blijft de waarheid:
 * `GET /uren/beheer/veldgebruikers` = Beheerder ÓF houder van het recht 'veldwerkerbeheer', anders 403 — het
 * scherm toont die 403 leesbaar). Het nav-item is strenger dan de route: alleen Beheerder óf een bewezen
 * recht-houder (`MijnToegangDto.heeft_veldwerkerbeheer_recht === true`); geen toegang-data = niet tonen. */
export const VELDWERKERS_ROUTE_ROLLEN = KANTOOR_ROLLEN

export function magVeldwerkersRoute(rol: string | null): boolean {
  return rol !== null && (VELDWERKERS_ROUTE_ROLLEN as readonly string[]).includes(rol)
}

export function toontVeldwerkersNav(
  rol: string | null,
  toegang: { heeft_veldwerkerbeheer_recht?: boolean } | null | undefined,
): boolean {
  if (rol === 'beheerder') return true
  if (!magVeldwerkersRoute(rol)) return false
  return toegang?.heeft_veldwerkerbeheer_recht === true
}

/** Planning-tab in de veld-app (feedback uitvoerder via Peter 18-09, blok D): de uitvoerder heeft geen planningstab
 * meer — hij schrijft uren op élk project (gepland bovenaan) en de meldingen "planning gewijzigd" blijven. ZZP'er en
 * detacheerder (namens) houden de alleen-lezen planningweergave (besluit B 22-08). Allowlist, nooit een complement:
 * een onbekende rol krijgt de tab niet. De backend-leesroute `/uren/zzp/planning` blijft voor iedere veldrol bestaan
 * (bron voor "gepland bovenaan"); dit stuurt alleen de UI. */
export const PLANNING_TAB_ROLLEN = ['zzper', 'detacheerder'] as const

export function toontPlanningTab(rol: string | null): boolean {
  return rol !== null && (PLANNING_TAB_ROLLEN as readonly string[]).includes(rol)
}
