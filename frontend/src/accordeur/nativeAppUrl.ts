// Universal links / App Links (pincode-activatie 31-08): een activatie- of accordeur-link uit
// een mail opent de geïnstalleerde app; Capacitor levert de URL via het App-plugin-event
// `appUrlOpen`. Zelfde toegangspatroon als nativePush: bridge-globals, geen @capacitor-import,
// fail-closed. Alleen /accordeur- en /activeren-paden worden geaccepteerd (zelfde hard principe
// als de melding-tap: de app-lock/auth-cadans blijft de poort); /activeren wordt hier naar de
// in-app-activatieroute vertaald (het kantoor-/activeren-scherm is een web-scherm).

// ⚠️ Deze listener bestaat alleen als de native schil `@capacitor/app` bundelt — Capacitor-core
// post op iOS enkel een NotificationCenter-notificatie (CAPApplicationDelegateProxy) en op Android
// gaat de intent alleen naar geregistreerde plugins; het JS-event `appUrlOpen` komt uitsluitend uit
// die plugin. Bevinding blok E1 (06-09): de plugin ontbrak in native/package.json → de link opende
// de app wél, maar niets navigeerde → login-scherm (casus detacheerder 04-09). Fix: dependency
// toegevoegd (`npx cap sync` = klikpunt bij de volgende store-build); hier daarnaast
// `getLaunchUrl()` als tweede vangnet voor de koude start en een zichtbare waarschuwing in de
// console als de plugin in een native build tóch ontbreekt (nooit meer stil).

interface AppUrlOpenPlugin {
  addListener?: (naam: string, cb: (data: { url?: string }) => void) => unknown
  getLaunchUrl?: () => Promise<{ url?: string } | null | undefined>
}

interface CapacitorGlobal {
  isNativePlatform?: () => boolean
  Plugins?: { App?: AppUrlOpenPlugin }
}

function capacitorGlobal(): CapacitorGlobal | null {
  if (typeof window === 'undefined') return null
  const cap = (window as { Capacitor?: CapacitorGlobal }).Capacitor
  return cap?.isNativePlatform?.() ? cap : null
}

function capacitorApp(): AppUrlOpenPlugin | null {
  const plugin = capacitorGlobal()?.Plugins?.App
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
  const cap = capacitorGlobal()
  if (!cap) return
  const plugin = capacitorApp()
  if (!plugin?.addListener) {
    // Native build zónder @capacitor/app: universal links bereiken de webcode nooit — luid in de
    // console (Safari Web Inspector / chrome://inspect), zodat dit nooit meer een stil gat is.
    console.warn('[accordeur] @capacitor/app ontbreekt in de native schil — universal links openen de app zonder te navigeren')
    return
  }
  // Dezelfde URL kan twee keer binnenkomen (retained appUrlOpen-event én getLaunchUrl op een koude
  // start) — één keer navigeren.
  const verwerkt = new Set<string>()
  const verwerk = (url: unknown) => {
    if (typeof url !== 'string' || verwerkt.has(url)) return
    const pad = inAppPadVoorUrl(url)
    if (!pad) return
    verwerkt.add(url)
    navigeer(pad)
  }
  try {
    plugin.addListener('appUrlOpen', (data) => verwerk(data?.url))
  } catch {
    // Geen listener = de link opent gewoon nog in de browser — nooit crashen.
  }
  if (typeof plugin.getLaunchUrl === 'function') {
    try {
      void Promise.resolve(plugin.getLaunchUrl())
        .then((r) => verwerk(r?.url))
        .catch(() => {})
    } catch {
      // idem
    }
  }
}
