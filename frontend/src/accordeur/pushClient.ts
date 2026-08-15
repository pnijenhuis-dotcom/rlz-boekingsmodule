// Web Push-client van de accordeur-PWA (berichten-bouwsteen 2026-08-15).
//
// Registreert public/accordeur-sw.js op scope /accordeur (bewust: alléén push, geen
// fetch-handler/caching — de SW-les blijft geldig, zie main.tsx) en beheert de
// PushSubscription bij de backend (/notificaties/push/*). De permissieprompt komt NOOIT rauw
// bij het laden: alleen vanuit een expliciete gebruikersactie (activeringsflow ná het
// voorwaarden-akkoord, of de meldingen-knop in de wachtrij).

import { apiJson, apiPostJson } from '../api/client'

const SW_PAD = '/accordeur-sw.js'
const SW_SCOPE = '/accordeur'

export type MeldingenStatus =
  | 'niet-ondersteund' // geen SW/Push API (of iOS zonder thuisscherm-installatie)
  | 'niet-geconfigureerd' // server heeft geen VAPID-sleutels (dev)
  | 'uit' // ondersteund, nog geen permissie/subscriptie
  | 'geweigerd' // gebruiker weigerde de browserpermissie
  | 'aan'

export function pushOndersteund(): boolean {
  return 'serviceWorker' in navigator && 'PushManager' in window && 'Notification' in window
}

function b64urlNaarBytes(b64url: string): Uint8Array {
  const padding = '='.repeat((4 - (b64url.length % 4)) % 4)
  const b64 = (b64url + padding).replace(/-/g, '+').replace(/_/g, '/')
  const raw = atob(b64)
  return Uint8Array.from(raw, (c) => c.charCodeAt(0))
}

async function registratie(): Promise<ServiceWorkerRegistration> {
  return navigator.serviceWorker.register(SW_PAD, { scope: SW_SCOPE })
}

async function huidigeSubscription(): Promise<PushSubscription | null> {
  const bestaande = await navigator.serviceWorker.getRegistration(SW_SCOPE)
  if (!bestaande) return null
  return bestaande.pushManager.getSubscription()
}

export async function haalMeldingenStatus(): Promise<MeldingenStatus> {
  if (!pushOndersteund()) return 'niet-ondersteund'
  if (Notification.permission === 'denied') return 'geweigerd'
  try {
    const { publieke_sleutel } = await apiJson<{ publieke_sleutel: string | null }>('/notificaties/push/config')
    if (!publieke_sleutel) return 'niet-geconfigureerd'
  } catch {
    return 'niet-geconfigureerd'
  }
  const subscription = await huidigeSubscription().catch(() => null)
  return subscription ? 'aan' : 'uit'
}

/** Meldingen aanzetten — alleen aanroepen vanuit een gebruikersklik (permissieprompt). */
export async function zetMeldingenAan(): Promise<MeldingenStatus> {
  if (!pushOndersteund()) return 'niet-ondersteund'
  const { publieke_sleutel } = await apiJson<{ publieke_sleutel: string | null }>('/notificaties/push/config')
  if (!publieke_sleutel) return 'niet-geconfigureerd'
  const permissie = await Notification.requestPermission()
  if (permissie !== 'granted') return permissie === 'denied' ? 'geweigerd' : 'uit'
  const reg = await registratie()
  const subscription =
    (await reg.pushManager.getSubscription()) ??
    (await reg.pushManager.subscribe({
      userVisibleOnly: true,
      applicationServerKey: b64urlNaarBytes(publieke_sleutel).buffer as ArrayBuffer,
    }))
  const json = subscription.toJSON()
  if (!json.endpoint || !json.keys?.p256dh || !json.keys?.auth) {
    throw new Error('Onvolledige push-subscription uit de browser')
  }
  await apiPostJson('/notificaties/push/subscripties', {
    endpoint: json.endpoint,
    p256dh: json.keys.p256dh,
    auth: json.keys.auth,
  })
  return 'aan'
}

export async function zetMeldingenUit(): Promise<void> {
  const subscription = await huidigeSubscription()
  if (!subscription) return
  const endpoint = subscription.endpoint
  // Browser-kant eerst (kan niet falen door de server), daarna server-side intrekken —
  // faalt die call, dan ruimt de eerstvolgende herinnering-run 'm op als 'vervallen' (410).
  await subscription.unsubscribe().catch(() => {})
  await apiPostJson('/notificaties/push/subscripties/intrekken', { endpoint }).catch(() => {})
}
