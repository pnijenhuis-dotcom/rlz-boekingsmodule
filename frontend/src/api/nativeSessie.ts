// Native sessie-opslag (store-app fase 4, verkenning/17 (d) route 2): in de Capacitor-schil
// werkt de httpOnly-refresh-cookie niet (SameSite/third-party in de webview) — daar leeft het
// refresh-token in secure native storage (iOS Keychain / Android EncryptedSharedPreferences)
// via de eigen dunne VeiligeOpslag-plugin (zelfde geen-community-pakket-in-de-auth-kern-lijn
// als NatievePasskey). Zelfde toegangspatroon als nativePasskey.ts: bridge-globals, géén
// @capacitor-dependency in de webcode, fail-closed detectie.

// App-lock (31-08, mockup app-lock-pincode.html): mét ingesteld slot staat het refresh-token
// hier versleuteld op het lokale anker (prefix slot.v1.) — lezen kan alleen ná ontgrendelen
// (code of biometrie), schrijven alleen zolang het slot open is. Bewuste statische
// import-cyclus met appSlot (functie-gebruik in bodies, geen top-level uitvoering).
import { isSlotWaarde, ontsleutelSlotWaarde, versleutelAlsSlotActief } from './appSlot'

const REFRESH_SLEUTEL = 'refresh_token'

interface VeiligeOpslagPlugin {
  zet(opties: { sleutel: string; waarde: string }): Promise<void>
  haal(opties: { sleutel: string }): Promise<{ waarde: string | null }>
  verwijder(opties: { sleutel: string }): Promise<void>
}

interface CapacitorGlobal {
  isNativePlatform?: () => boolean
  Plugins?: Record<string, unknown>
}

export function veiligeOpslagPlugin(): VeiligeOpslagPlugin | null {
  if (typeof window === 'undefined') return null
  const capacitor = (window as { Capacitor?: CapacitorGlobal }).Capacitor
  if (!capacitor?.isNativePlatform?.()) return null
  const plugin = capacitor.Plugins?.VeiligeOpslag as VeiligeOpslagPlugin | undefined
  if (
    !plugin ||
    typeof plugin.zet !== 'function' ||
    typeof plugin.haal !== 'function' ||
    typeof plugin.verwijder !== 'function'
  ) {
    return null
  }
  return plugin
}

/** True in de native schil mét werkende opslag-plugin — de schakel voor het header-token-pad
 * in api/client.ts (zonder plugin valt de app terug op het cookie-pad, dat in de webview
 * niet werkt maar ook niets stuk maakt: gedrag = uitgelogd). */
export function natieveSessieBeschikbaar(): boolean {
  return veiligeOpslagPlugin() !== null
}

export async function haalNatiefRefreshToken(): Promise<string | null> {
  const plugin = veiligeOpslagPlugin()
  if (!plugin) return null
  try {
    const waarde = (await plugin.haal({ sleutel: REFRESH_SLEUTEL })).waarde
    // Slot-vorm: alleen leesbaar met het ontgrendelde anker; dicht slot = null, zodat de
    // stille refresh faalt en de app het slot-scherm toont i.p.v. stil een sessie te starten.
    if (waarde && isSlotWaarde(waarde)) return ontsleutelSlotWaarde(waarde)
    return waarde
  } catch {
    return null
  }
}

export async function bewaarNatiefRefreshToken(token: string): Promise<void> {
  const plugin = veiligeOpslagPlugin()
  if (!plugin) return
  try {
    // Mét ontgrendeld slot altijd de versleutelde vorm — het plain token raakt de opslag niet.
    const versleuteld = await versleutelAlsSlotActief(token)
    await plugin.zet({ sleutel: REFRESH_SLEUTEL, waarde: versleuteld ?? token })
  } catch {
    // Opslag mislukt: de sessie werkt deze app-run nog (access-token in geheugen), de
    // volgende opening vraagt gewoon een volledige login — nooit crashen op de opslag.
  }
}

export async function wisNatiefRefreshToken(): Promise<void> {
  const plugin = veiligeOpslagPlugin()
  if (!plugin) return
  try {
    await plugin.verwijder({ sleutel: REFRESH_SLEUTEL })
  } catch {
    // zie boven
  }
}
