// Universal links / App Links (pincode-activatie 31-08): een activatie- of accordeur-link uit
// een mail opent de geïnstalleerde app; Capacitor levert de URL via het App-plugin-event
// `appUrlOpen`. Zelfde toegangspatroon als nativePush: bridge-globals, geen @capacitor-import,
// fail-closed. Alleen /accordeur- en /activeren-paden worden geaccepteerd (zelfde hard principe
// als de melding-tap: de app-lock/auth-cadans blijft de poort); /activeren wordt hier naar de
// in-app-activatieroute vertaald (het kantoor-/activeren-scherm is een web-scherm).

interface AppUrlOpenPlugin {
  addListener?: (naam: string, cb: (data: { url?: string }) => void) => unknown
}

function capacitorApp(): AppUrlOpenPlugin | null {
  if (typeof window === 'undefined') return null
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; Plugins?: { App?: AppUrlOpenPlugin } } })
    .Capacitor
  if (!cap?.isNativePlatform?.()) return null
  const plugin = cap.Plugins?.App
  return plugin && typeof plugin.addListener === 'function' ? plugin : null
}

/** Pure vertaling van een binnengekomen universal link naar een in-app-pad; null = negeren.
 * Los getest — de listener-installatie hieronder is dunne glue. */
export function inAppPadVoorUrl(url: string): string | null {
  let pad: string
  let zoek: string
  try {
    const geparsed = new URL(url)
    pad = geparsed.pathname
    zoek = geparsed.search
  } catch {
    return null
  }
  if (pad === '/activeren') {
    // Zelfde vertaling als ActivateScreen (kantoor-web): token= → uitnodiging=, herstel reist mee.
    const params = new URLSearchParams(zoek)
    const token = params.get('token')
    if (!token) return '/accordeur/activeren'
    const herstel = params.get('herstel') === '1' ? '&herstel=1' : ''
    return `/accordeur/activeren?uitnodiging=${encodeURIComponent(token)}${herstel}`
  }
  if (pad === '/accordeur' || pad.startsWith('/accordeur/')) return `${pad}${zoek}`
  return null
}

export function installeerNativeUrlAfhandeling(
  navigeer: (url: string) => void = (url) => window.location.assign(url),
): void {
  const plugin = capacitorApp()
  if (!plugin?.addListener) return
  try {
    plugin.addListener('appUrlOpen', (data) => {
      const pad = typeof data?.url === 'string' ? inAppPadVoorUrl(data.url) : null
      if (pad) navigeer(pad)
    })
  } catch {
    // Geen listener = de link opent gewoon nog in de browser — nooit crashen.
  }
}
