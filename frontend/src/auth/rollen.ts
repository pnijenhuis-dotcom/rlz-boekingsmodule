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
