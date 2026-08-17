// Push-client van de accordeur-app (berichten-bouwsteen 2026-08-15; native seam fase 3).
//
// Web (PWA): registreert public/accordeur-sw.js op scope /accordeur (bewust: alléén push,
// geen fetch-handler/caching — de SW-les blijft geldig, zie main.tsx) en beheert de
// PushSubscription bij de backend (/notificaties/push/*).
// Native (Capacitor-schil, fase 3): geen service worker/Web Push in de webview — het
// APNs-/FCM-device-token gaat via nativePush.ts naar /notificaties/push/subscripties/native;
// de aan-status leeft lokaal (marker met het token, zelfde kennisniveau als de
// browser-subscription op het webpad).
// Beide paden: de permissieprompt komt NOOIT rauw bij het laden — alleen vanuit een
// expliciete gebruikersactie (activeringsflow ná het voorwaarden-akkoord, of de
// meldingen-knop in de wachtrij).

import { apiJson, apiPostJson, ApiError } from '../api/client'
import { haalDeviceToken, nativePushPlugin, nativePushSoort } from './nativePush'

const SW_PAD = '/accordeur-sw.js'
const SW_SCOPE = '/accordeur'
const NATIVE_TOKEN_SLEUTEL = 'accordeur_native_push_token'

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

// ---- native pad (Capacitor-schil) ----------------------------------------------------------------

function bewaardNativeToken(): string | null {
  try {
    return localStorage.getItem(NATIVE_TOKEN_SLEUTEL)
  } catch {
    return null
  }
}

async function nativeMeldingenStatus(plugin: NonNullable<ReturnType<typeof nativePushPlugin>>): Promise<MeldingenStatus> {
  const permissie = await plugin.checkPermissions().catch(() => null)
  if (!permissie) return 'niet-ondersteund'
  if (permissie.receive === 'denied') return 'geweigerd'
  return permissie.receive === 'granted' && bewaardNativeToken() ? 'aan' : 'uit'
}

async function nativeMeldingenAan(plugin: NonNullable<ReturnType<typeof nativePushPlugin>>): Promise<MeldingenStatus> {
  const permissie = await plugin.requestPermissions()
  if (permissie.receive !== 'granted') return permissie.receive === 'denied' ? 'geweigerd' : 'uit'
  const token = await haalDeviceToken(plugin)
  try {
    await apiPostJson('/notificaties/push/subscripties/native', { soort: nativePushSoort(), token })
  } catch (fout) {
    // 409 = deze soort is (nog) niet geconfigureerd op de server — zelfde nette status als
    // het webpad zonder VAPID-sleutels.
    if (fout instanceof ApiError && fout.status === 409) return 'niet-geconfigureerd'
    throw fout
  }
  try {
    localStorage.setItem(NATIVE_TOKEN_SLEUTEL, token)
  } catch {
    // Geen localStorage (privéstand): de subscriptie werkt, alleen de lokale aan-status niet.
  }
  return 'aan'
}

async function nativeMeldingenUit(): Promise<void> {
  const token = bewaardNativeToken()
  if (!token) return
  await apiPostJson('/notificaties/push/subscripties/intrekken', { endpoint: token }).catch(() => {})
  try {
    localStorage.removeItem(NATIVE_TOKEN_SLEUTEL)
  } catch {
    // zie boven
  }
}

// ---- publieke API (kiest web- of native pad) -----------------------------------------------------

export async function haalMeldingenStatus(): Promise<MeldingenStatus> {
  const plugin = nativePushPlugin()
  if (plugin) return nativeMeldingenStatus(plugin)
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
  const plugin = nativePushPlugin()
  if (plugin) return nativeMeldingenAan(plugin)
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
  if (nativePushPlugin()) return nativeMeldingenUit()
  const subscription = await huidigeSubscription()
  if (!subscription) return
  const endpoint = subscription.endpoint
  // Browser-kant eerst (kan niet falen door de server), daarna server-side intrekken —
  // faalt die call, dan ruimt de eerstvolgende herinnering-run 'm op als 'vervallen' (410).
  await subscription.unsubscribe().catch(() => {})
  await apiPostJson('/notificaties/push/subscripties/intrekken', { endpoint }).catch(() => {})
}
