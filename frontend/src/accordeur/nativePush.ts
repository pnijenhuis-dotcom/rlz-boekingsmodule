// Native-push-brug (store-app fase 3): in de Capacitor-schil bestaat Web Push niet (geen
// service worker in de webview) — meldingen lopen daar via @capacitor/push-notifications
// (APNs op iOS, FCM op Android). Zelfde toegangspatroon als nativePasskey.ts: bridge-globals,
// géén @capacitor-dependency in de webcode, fail-closed detectie.
//
// De permissieprompt komt óók native alleen vanuit een expliciete klik (zelfde principe als
// de PWA); de melding-tap opent uitsluitend een /accordeur-deep-link — goedkeuren-vanuit-de-
// melding bestaat bewust niet.

interface PermissieStatus {
  receive: 'prompt' | 'prompt-with-rationale' | 'granted' | 'denied'
}

interface ListenerHandle {
  remove: () => Promise<void> | void
}

/** ⚠️ Capacitor's bridge-shim (`w.Capacitor.addListener` in JSExport/native-bridge.js) geeft een
 * PLAIN handle terug, geen Promise — de gepubliceerde plugin-typings beloven een Promise. Op het
 * toestel gaf `.then(...)` daardoor "`.then is not a function`" (bug 26-08, activeringsflow én het
 * oude 🔔-hoekje). Beide vormen worden hier geaccepteerd. */
interface PushNotificationsPlugin {
  checkPermissions(): Promise<PermissieStatus>
  requestPermissions(): Promise<PermissieStatus>
  register(): Promise<void>
  addListener(eventName: string, listener: (payload: never) => void): Promise<ListenerHandle> | ListenerHandle
}

/** Normaliseert de addListener-uitkomst (Promise óf plain handle) naar één belofte. */
export function alsHandle(uitkomst: Promise<ListenerHandle> | ListenerHandle): Promise<ListenerHandle> {
  return Promise.resolve(uitkomst)
}

interface CapacitorGlobal {
  isNativePlatform?: () => boolean
  getPlatform?: () => string
  Plugins?: Record<string, unknown>
}

function capacitor(): CapacitorGlobal | undefined {
  if (typeof window === 'undefined') return undefined
  return (window as { Capacitor?: CapacitorGlobal }).Capacitor
}

export function nativePushPlugin(): PushNotificationsPlugin | null {
  const cap = capacitor()
  if (!cap?.isNativePlatform?.()) return null
  const plugin = cap.Plugins?.PushNotifications as PushNotificationsPlugin | undefined
  if (
    !plugin ||
    typeof plugin.checkPermissions !== 'function' ||
    typeof plugin.requestPermissions !== 'function' ||
    typeof plugin.register !== 'function' ||
    typeof plugin.addListener !== 'function'
  ) {
    return null
  }
  return plugin
}

/** apns (iOS) | fcm (Android) — bepaalt welke server-adapter dit token gaat bedienen. */
export function nativePushSoort(): 'apns' | 'fcm' {
  return capacitor()?.getPlatform?.() === 'ios' ? 'apns' : 'fcm'
}

/** register() levert het token asynchroon via een event — hier één belofte van gemaakt,
 * mét timeout zodat "Bezig…" nooit eeuwig hangt (zelfde les als de request-timeout). */
export async function haalDeviceToken(plugin: PushNotificationsPlugin, timeoutMs = 15_000): Promise<string> {
  return new Promise<string>((resolve, reject) => {
    let klaar = false
    const listeners: ListenerHandle[] = []
    const rondAf = (fout: Error | null, token?: string) => {
      if (klaar) return
      klaar = true
      clearTimeout(timer)
      for (const l of listeners) void Promise.resolve(l.remove()).catch(() => {})
      if (fout) reject(fout)
      else resolve(token ?? '')
    }
    const timer = setTimeout(() => rondAf(new Error('Registratie bij de push-dienst duurde te lang')), timeoutMs)
    const registreer = (naam: string, listener: (payload: never) => void) => {
      let uitkomst: Promise<ListenerHandle> | ListenerHandle
      try {
        uitkomst = plugin.addListener(naam, listener)
      } catch (fout) {
        rondAf(fout instanceof Error ? fout : new Error(String(fout)))
        return
      }
      void alsHandle(uitkomst)
        .then((l) => listeners.push(l))
        .catch((fout: unknown) => rondAf(fout instanceof Error ? fout : new Error(String(fout))))
    }
    registreer('registration', ((t: { value: string }) => rondAf(null, t.value)) as never)
    registreer('registrationError', ((e: { error: string }) =>
      rondAf(new Error(`Registratie bij de push-dienst mislukte: ${e.error}`))) as never)
    void plugin.register().catch((fout: unknown) => rondAf(fout instanceof Error ? fout : new Error(String(fout))))
  })
}

/** Melding-tap → deep-link. Alleen /accordeur-URL's (hard principe: de auth-cadans blijft de
 * poort — de app opent op de ontgrendel-flow en navigeert daarna naar het document).
 * `navigeer` is injecteerbaar voor tests; default = volledige navigatie (de deep-link-
 * afhandeling in GoedkeurenFlow leest ?document bij het laden). */
export function installeerNativeTapAfhandeling(
  navigeer: (url: string) => void = (url) => window.location.assign(url),
): void {
  const plugin = nativePushPlugin()
  if (!plugin) return
  void plugin.addListener('pushNotificationActionPerformed', ((actie: {
    notification?: { data?: { url?: string } }
  }) => {
    const url = actie?.notification?.data?.url
    if (typeof url === 'string' && url.startsWith('/accordeur')) {
      navigeer(url)
    }
  }) as never)
}
