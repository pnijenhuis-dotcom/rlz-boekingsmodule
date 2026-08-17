// Runtime-brug naar de NatievePasskey-Capacitor-plugin (native store-app fase 2, GO Peter
// 2026-08-16). BEWUST géén @capacitor/core-import: de webcode blijft dependency-vrij en de
// bridge-globals bestaan alleen ín de native webview (window.Capacitor). In de gewone
// browser/PWA geeft natievePasskeyPlugin() null en loopt alles via navigator.credentials.
//
// Contract met de native kant (Swift/Java in native/): beide methoden krijgen de
// py_webauthn-options als JSON-string (base64url, byte-exact zoals de backend ze maakt) en
// geven de WebAuthn-credential-JSON terug in exact de vorm die de backend verwacht — de
// vorm die webauthnClient.ts op het webpad zelf bouwt. Annuleren door de gebruiker = reject
// met melding 'geannuleerd' erin (zelfde toon als het webpad).

export interface NatievePasskeyPlugin {
  registreer(opties: { optiesJson: string }): Promise<{ credentialJson: string }>
  onderteken(opties: { optiesJson: string }): Promise<{ credentialJson: string }>
}

interface CapacitorGlobal {
  isNativePlatform?: () => boolean
  Plugins?: Record<string, unknown>
}

/** De plugin, of null buiten de native schil. Fail-closed: alleen een écht native platform
 * mét volledig plugin-oppervlak telt — anders valt de auth-flow terug op het webpad. */
export function natievePasskeyPlugin(): NatievePasskeyPlugin | null {
  if (typeof window === 'undefined') return null
  const capacitor = (window as { Capacitor?: CapacitorGlobal }).Capacitor
  if (!capacitor?.isNativePlatform?.()) return null
  const plugin = capacitor.Plugins?.NatievePasskey as NatievePasskeyPlugin | undefined
  if (!plugin || typeof plugin.registreer !== 'function' || typeof plugin.onderteken !== 'function') {
    return null
  }
  return plugin
}
