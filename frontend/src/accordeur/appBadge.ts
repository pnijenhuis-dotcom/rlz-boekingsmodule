// App-icoon-badge (best-practice-punt D4, 01-09): het aantal openstaande accorderingen op het icoon.
// Native (Capacitor): via de eigen AppSlot-plugin (`zetBadge`); web/PWA: de Badging API. Fail-stil —
// een badge is gemak, nooit een blokkade. De server zet hetzelfde aantal in élke push-payload (APNs
// `badge`, FCM `notification_count`); dit is de reset/actualisatie bij app-opening en na een besluit.
interface BadgePlugin {
  zetBadge(opties: { aantal: number }): Promise<void>
}

function capacitorPlugin(): BadgePlugin | null {
  if (typeof window === 'undefined') return null
  const cap = (window as { Capacitor?: { isNativePlatform?: () => boolean; Plugins?: Record<string, unknown> } }).Capacitor
  if (!cap?.isNativePlatform?.()) return null
  const plugin = cap.Plugins?.AppSlot as Partial<BadgePlugin> | undefined
  return plugin && typeof plugin.zetBadge === 'function' ? (plugin as BadgePlugin) : null
}

export async function zetAppBadge(aantal: number): Promise<void> {
  const n = Math.max(0, Math.floor(aantal))
  try {
    const native = capacitorPlugin()
    if (native) {
      await native.zetBadge({ aantal: n })
      return
    }
    const nav = navigator as Navigator & { setAppBadge?: (n?: number) => Promise<void>; clearAppBadge?: () => Promise<void> }
    if (n === 0 && typeof nav.clearAppBadge === 'function') await nav.clearAppBadge()
    else if (typeof nav.setAppBadge === 'function') await nav.setAppBadge(n)
  } catch {
    // Geen badge-ondersteuning of geweigerd: stil — de wachtrij zelf is de waarheid.
  }
}
