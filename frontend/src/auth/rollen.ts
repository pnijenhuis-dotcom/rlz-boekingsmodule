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
