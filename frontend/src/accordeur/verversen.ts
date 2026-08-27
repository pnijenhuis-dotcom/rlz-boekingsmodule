// Automatisch verversen zodra de app naar de voorgrond komt (feedback Peter 27-08: nooit meer
// een app-herstart nodig voor nieuwe boekingen). Bronnen, alle fail-soft en ontdubbeld:
//   • `visibilitychange` → visible (PWA én Capacitor-webview: WKWebView/Chrome vuren dit bij
//     terugkeer uit de achtergrond);
//   • `pageshow` (bfcache) en `focus` (desktop/tab-wissel);
//   • Capacitor's App-plugin `appStateChange` wanneer die in de schil aanwezig is (bridge-global,
//     géén import — de webcode kent geen @capacitor/*-dependency, zelfde patroon als nativePush).
// Een terugkeer binnen VERVERS_DEMPING_MS na de vorige verversing wordt overgeslagen.

import { useEffect, useRef } from 'react'

export const VERVERS_DEMPING_MS = 2000

interface CapacitorAppPlugin {
  addListener?: (naam: string, cb: (state: { isActive?: boolean }) => void) => unknown
}

function capacitorApp(): CapacitorAppPlugin | null {
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; Plugins?: { App?: CapacitorAppPlugin } } })
    .Capacitor
  if (!cap?.isNativePlatform?.()) return null
  const plugin = cap.Plugins?.App
  return plugin && typeof plugin.addListener === 'function' ? plugin : null
}

/** Roept `ververs` aan bij elke terugkeer naar de voorgrond (gedempt). De callback mag van
 * render tot render wisselen — er wordt altijd de laatste gebruikt. */
export function useVerversBijVoorgrond(ververs: () => void, actief = true): void {
  const laatste = useRef(ververs)
  laatste.current = ververs
  const laatsteKeer = useRef(0)

  useEffect(() => {
    if (!actief) return
    const trigger = () => {
      const nu = Date.now()
      if (nu - laatsteKeer.current < VERVERS_DEMPING_MS) return
      laatsteKeer.current = nu
      laatste.current()
    }
    const opZichtbaar = () => {
      if (document.visibilityState === 'visible') trigger()
    }
    document.addEventListener('visibilitychange', opZichtbaar)
    window.addEventListener('pageshow', trigger)
    window.addEventListener('focus', trigger)
    // Native schil: appStateChange (isActive true) — handle kan Promise óf plain object zijn
    // (bridge-shim-les 26-08); we bewaren wat er komt en roepen remove() aan als dat bestaat.
    let nativeHandle: unknown = null
    const plugin = capacitorApp()
    if (plugin?.addListener) {
      try {
        nativeHandle = plugin.addListener('appStateChange', (state) => {
          if (state?.isActive) trigger()
        })
      } catch {
        nativeHandle = null
      }
    }
    return () => {
      document.removeEventListener('visibilitychange', opZichtbaar)
      window.removeEventListener('pageshow', trigger)
      window.removeEventListener('focus', trigger)
      const verwijder = (h: unknown) => {
        const r = (h as { remove?: () => unknown } | null)?.remove
        if (typeof r === 'function') void r.call(h)
      }
      if (nativeHandle && typeof (nativeHandle as Promise<unknown>).then === 'function') {
        void (nativeHandle as Promise<unknown>).then(verwijder).catch(() => {})
      } else {
        verwijder(nativeHandle)
      }
    }
  }, [actief])
}
